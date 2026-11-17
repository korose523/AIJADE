"""Measured callbacks and coherent cold-evidence controls; no native/model run."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'experiments/ch7'))
from measured_mac_monitor import MeasuredMacMonitor, canonical, validate_terminal

BASE=Path('/Volumes/Untitled/AIJADE')


class MeasuredMonitorControls(unittest.TestCase):
    def setUp(self):
        scratch_root=(BASE/'.runtime/posix/tmp' if sys.platform=='darwin' else
                      Path(__file__).resolve().parents[2]/'.runtime/measured-monitor-controls')
        scratch_root.mkdir(parents=True,exist_ok=True)
        self.scratch=tempfile.TemporaryDirectory(dir=scratch_root,prefix='measured-monitor-')
        self.root=Path(self.scratch.name)
        self.path_patch=None
        if sys.platform!='darwin':
            # Portable fake-callback evidence control only. The production Mac
            # namespace validator remains unchanged and is used on this Mac.
            def fixture_path(value):
                p=Path(value)
                if not p.is_absolute() or not p.is_relative_to(scratch_root) or p.resolve()!=p:
                    raise ValueError('portable test fixture boundary')
                return p
            self.path_patch=patch('measured_mac_monitor.project_path',side_effect=fixture_path)
            self.path_patch.start()
    def tearDown(self):
        if self.path_patch:self.path_patch.stop()
        self.scratch.cleanup()

    def baseline(self):
        def sample():return dict(utc=None,availableBytes=5*1024**3,swapUsedBytes=0,rssBytes=0,
                                processObservation={'sampleId':'a'*32})
        monitor=MeasuredMacMonitor(self.root/'raw.jsonl',sample,lambda item:None,
            time.monotonic(),0,timers_path=self.root/'timers.json',diagnostic_path=self.root/'services.jsonl').start()
        deadline=time.monotonic()+2
        while not monitor.services:
            if time.monotonic()>deadline:
                monitor.stop()
                self.fail('one actual callback not completed')
            time.sleep(.001)
        monitor.stop()
        terminal=json.loads((self.root/'services.terminal.json').read_bytes())
        raw=[json.loads(line) for line in (self.root/'raw.jsonl').read_bytes().splitlines()]
        diagnostic=(self.root/'services.jsonl').read_bytes()
        self.assertEqual(validate_terminal(terminal,raw,diagnostic)['samples'],1)
        return monitor,terminal,raw,diagnostic

    def test_01_actual_callback_full_writer_and_terminal_population(self):
        monitor,terminal,raw,diagnostic=self.baseline()
        row=terminal['services'][0]
        self.assertLessEqual(row['resourcesCompletedMonotonic'],row['diagnosticWriterStartedMonotonic'])
        self.assertEqual(row['fullServiceSeconds'],row['diagnosticWriterCompletedMonotonic']-raw[0]['monotonicSeconds'])
        before=(self.root/'services.terminal.json').read_bytes()
        monitor.stop()
        self.assertEqual((self.root/'services.terminal.json').read_bytes(),before)

    def test_02_raw_and_terminal_semantics_reject_coherent_mutations(self):
        _,base,raw,diagnostic=self.baseline()
        def rebind(terminal,records):
            rows=[]
            for row in terminal['services']:
                p={k:v for k,v in row.items() if k not in {'diagnosticRecordSha256',
                    'diagnosticWriterCompletedMonotonic','serviceCompletedMonotonic','fullServiceSeconds'}}
                line=canonical(p)+b'\n';rows.append(line);row['diagnosticRecordSha256']=hashlib.sha256(line).hexdigest()
            return b''.join(rows)
        def wrong_slot(t,r):t['services'][0]['slotIndex']=r[0]['monitorSlotIndex']=2
        def wrong_target(t,r):t['services'][0]['scheduledMonotonic']=r[0]['monitorScheduledMonotonic']=t['scheduleOriginMonotonic']+.01
        def wrong_sample(t,r):t['services'][0]['observationSampleId']='b'*32
        def gap(t,r):t['stopRequestedMonotonic']=t['scheduleOriginMonotonic']+2.1;t['joinedMonotonic']=t['stopRequestedMonotonic']+.1
        def reordered(t,r):t['services'][0]['resourcesCompletedMonotonic']=t['services'][0]['diagnosticWriterCompletedMonotonic']+.1
        def service(t,r):
            row=t['services'][0];row['diagnosticWriterCompletedMonotonic']=row['serviceCompletedMonotonic']=row['sampleStartedMonotonic']+2.01
            row['fullServiceSeconds']=2.01;t['joinedMonotonic']=row['serviceCompletedMonotonic']+.1
        def false_status(t,r):t['status']='COMPLETE_OTHER'
        def callback_error(t,r):t['services'][0]['error']='injected actual callback failure'
        def outer_clock(t,r):r[0]['observationCompletedMonotonic']+=.001
        def negative_clock(t,r):t['services'][0]['rawWriterStartedMonotonic']=float('nan')
        def false_alive(t,r):t['threadAlive']=True
        def missing_raw(t,r):r.clear()
        def false_lateness(t,r):t['services'][0]['startLatenessSeconds']+=.01
        def false_endpoint(t,r):
            row=t['services'][0];row['serviceCompletedMonotonic']+=.001
            row['fullServiceSeconds']=row['serviceCompletedMonotonic']-row['sampleStartedMonotonic']
            t['joinedMonotonic']=max(t['joinedMonotonic'],row['serviceCompletedMonotonic'])
        def false_elapsed(t,r):r[0]['sequenceElapsedSeconds']+=.01
        def false_local_elapsed(t,r):r[0]['elapsedSeconds']+=.01
        def bool_slot(t,r):t['services'][0]['slotIndex']=r[0]['monitorSlotIndex']=False
        def bool_count(t,r):t['expectedSlotCount']=True
        def bool_epoch(t,r):
            t['epochMonotonic']=False
            r[0]['sequenceElapsedSeconds']=r[0]['monotonicSeconds']
        def negative_epoch(t,r):
            t['localEpochMonotonic']=-1
            r[0]['elapsedSeconds']=r[0]['monotonicSeconds']+1
        controls=[wrong_slot,wrong_target,wrong_sample,gap,reordered,service,false_status,
                  callback_error,outer_clock,negative_clock,false_alive,missing_raw,
                  false_lateness,false_endpoint,false_elapsed,false_local_elapsed,bool_slot,bool_count,
                  bool_epoch,negative_epoch]
        accepted=0
        for mutate in controls:
            with self.subTest(control=mutate.__name__):
                self.assertEqual(validate_terminal(copy.deepcopy(base),copy.deepcopy(raw),diagnostic)['samples'],1)
                t,r=copy.deepcopy(base),copy.deepcopy(raw)
                mutate(t,r)
                # Coherently rehash finite JSON modifications, then test semantics.
                if mutate is negative_clock:
                    d=diagnostic
                else:d=rebind(t,r)
                self.assertNotEqual(json.dumps([t,r,d.hex()],sort_keys=True,allow_nan=True),
                                    json.dumps([base,raw,diagnostic.hex()],sort_keys=True,allow_nan=True))
                with self.assertRaises((ValueError,KeyError,TypeError)):
                    validate_terminal(t,r,d)
                accepted+=1
        self.assertEqual(accepted,20)
        for malformed in (diagnostic.replace(b'"slotIndex":0',b'"slotIndex":0,"slotIndex":0'),
                          b' '+diagnostic):
            t=copy.deepcopy(base);t['services'][0]['diagnosticRecordSha256']=hashlib.sha256(malformed).hexdigest()
            with self.assertRaises(ValueError):validate_terminal(t,copy.deepcopy(raw),malformed)

    def test_03_outside_project_and_changed_service_budget_refused(self):
        with self.assertRaises(ValueError):
            MeasuredMacMonitor(self.root/'r',lambda:None,lambda _:None,time.monotonic(),0,
                               diagnostic_path='/outside-project/services.jsonl')
        with self.assertRaises(ValueError):
            MeasuredMacMonitor(self.root/'r',lambda:None,lambda _:None,time.monotonic(),0,
                               diagnostic_path=self.root/'d',maximum_service_seconds=2.5)


if __name__=='__main__':unittest.main(verbosity=2)
