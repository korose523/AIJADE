"""Coherent source-level audit controls, explicitly no live observation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'experiments/ch7'))
import audit_nested_load as a
from test_nested_event_index import fixture, ROOT

REPO=Path(__file__).resolve().parents[2]
SCRATCH=(Path('/Volumes/Untitled/AIJADE/.runtime/posix/tmp') if sys.platform=='darwin' else REPO/'.runtime/nested-audit-controls')
SCRATCH.mkdir(parents=True,exist_ok=True)


class NestedAuditControls(unittest.TestCase):
    def test_01_conditional_numeric_context_accepts_valid_baseline(self):
        events=fixture()
        for i,e in enumerate(events,1):e['seq']=i
        self.assertEqual(a.verify_numeric_context(events)['maximumManagedPid'],999999)

    def test_02_boolean_sequence_cannot_be_integer_one(self):
        events=fixture()
        for i,e in enumerate(events,1):e['seq']=i
        a.verify_numeric_context(events)
        changed=copy.deepcopy(events);changed[0]['seq']=True
        self.assertNotEqual(a.canonical(changed),a.canonical(events))
        with self.assertRaisesRegex(ValueError,'sequence'):
            a.verify_numeric_context(changed)

    def test_03_pid_or_stage_expansion_cannot_keep_serialization_claim(self):
        events=fixture()
        for i,e in enumerate(events,1):e['seq']=i
        a.verify_numeric_context(events)
        changed=copy.deepcopy(events);changed[0]['writer']['pid']=1000000
        with self.assertRaisesRegex(ValueError,'identity'):
            a.verify_numeric_context(changed)
        changed=copy.deepcopy(events);changed[2]['data']['stageId']='x'*23
        with self.assertRaisesRegex(ValueError,'stage'):
            a.verify_numeric_context(changed)

    def test_04_unknown_clock_or_context_expansion_refuses(self):
        events=fixture()
        for i,e in enumerate(events,1):e['seq']=i
        a.verify_numeric_context(events)
        changed=copy.deepcopy(events);changed[3]['monotonicSeconds']=1e9+1
        with self.assertRaisesRegex(ValueError,'clock'):
            a.verify_numeric_context(changed)
        changed=copy.deepcopy(events);changed[3]['monotonicSeconds']=float('nan')
        with self.assertRaisesRegex(ValueError,'clock'):
            a.verify_numeric_context(changed)

    def test_05_scientific_or_boolean_zero_scope_promotion_refuses(self):
        value={k:False for k in ('qualificationStarted','backendQualified','scientificAdmission',
            'formalHardwareQualification','independentHumanReview','seedConstructed')}
        value.update({k:0 for k in ('flowBlocks','modelRequests','rendererRequests','freshHeldoutCases','automaticRetries')})
        a.no_science(value)
        changed=copy.deepcopy(value);changed['backendQualified']=True
        with self.assertRaises(ValueError):a.no_science(changed)
        changed=copy.deepcopy(value);changed['modelRequests']=False
        with self.assertRaises(ValueError):a.no_science(changed)

    def make_stream(self, root, rows_count=2, *, rss=100):
        rows=[];services=[];lines=[]
        origin=100.0
        for n in range(rows_count):
            start=origin+2*n;sid=('%032x'%n)
            rows.append(dict(monitorSlotIndex=n,monotonicSeconds=start,sequenceElapsedSeconds=start-90,
                elapsedSeconds=start-90,swapUsedBytes=500,swapIncreaseBytes=0,rssBytes=rss,availableBytes=4*1024**3,
                processObservation=dict(sampleId=sid,lifecycle=dict(scopeId='2'*32,controllerIdentity=copy.deepcopy(ROOT)))))
            provisional=dict(slotIndex=n,observationSampleId=sid,scheduledMonotonic=start)
            line=a.canonical(provisional)+b'\n';lines.append(line)
            services.append(dict(provisional,sampleStartedMonotonic=start,
                serviceCompletedMonotonic=start+.5,diagnosticWriterCompletedMonotonic=start+.5,startLatenessSeconds=0))
        (root/'process-observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (root/'service-events.jsonl').write_bytes(b''.join(lines))
        terminal=dict(scheduleOriginMonotonic=origin,stopRequestedMonotonic=origin+2*rows_count-.5,
            expectedSlotCount=rows_count,epochMonotonic=90,localEpochMonotonic=90,services=services,
            status='COMPLETE_MEASURED_MONITOR_SERVICES',errors=[],threadAlive=False)
        (root/'service-events.terminal.json').write_text(json.dumps(terminal))
        (root/'resource-timers.json').write_text('{}')
        return rows,terminal

    def stream_receipt(self):
        return dict(controllerProcess=dict(pid=ROOT['pid'],createTime=ROOT['createTimeMicros']/1000000,
            parentPid=ROOT['parentPid']),registryFinal=dict(scopeId='2'*32))

    def run_stream(self, root, prefix='', receipt=None):
        # Deliberately bypass the other module's validator so these tests prove
        # the independent checks below, rather than merely echo its verdict.
        measured=types.SimpleNamespace(validate_terminal=lambda *args,**kwargs:dict(status='SYNTHETIC_VALIDATOR_CANARY'))
        return a.verify_stream(prefix,root,self.stream_receipt() if receipt is None else receipt,
            measured,maximum_seconds=600,slots_maximum=300,epoch=90,baseline=500)

    def test_06_independent_stream_checks_accept_valid_synthetic_baseline(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            root=Path(d);self.make_stream(root)
            self.assertEqual(self.run_stream(root)[2]['status'],'SYNTHETIC_VALIDATOR_CANARY')

    def test_07_lateness_summary_cannot_override_original_clock(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            root=Path(d);self.make_stream(root);self.run_stream(root)
            p=root/'service-events.terminal.json';value=json.loads(p.read_text())
            value['services'][0]['startLatenessSeconds']=.4;p.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'lateness'):
                self.run_stream(root)

    def test_08_independent_resources_reject_sustained_crossing_despite_pass_claim(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            root=Path(d);self.make_stream(root,rows_count=17);self.run_stream(root)
            self.make_stream(root,rows_count=17,rss=3*1024**3)
            with self.assertRaisesRegex(ValueError,'sustained resource'):
                self.run_stream(root)

    def test_09_global_swap_baseline_is_not_restarted_for_child(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            root=Path(d);self.make_stream(root);self.run_stream(root)
            p=root/'process-observations.jsonl';rows=[json.loads(v) for v in p.read_text().splitlines()]
            rows[1]['swapUsedBytes']=600;p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.assertRaisesRegex(ValueError,'swap baseline'):
                self.run_stream(root)

    def test_10_coherent_parent_local_epoch_reset_refuses_file_context(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            root=Path(d);self.make_stream(root);self.run_stream(root)
            p=root/'service-events.terminal.json';terminal=json.loads(p.read_text())
            original=a.canonical(terminal);terminal['localEpochMonotonic']=95
            self.assertNotEqual(a.canonical(terminal),original);p.write_text(json.dumps(terminal))
            raw=root/'process-observations.jsonl';rows=[json.loads(v) for v in raw.read_text().splitlines()]
            for row in rows:row['elapsedSeconds']=row['monotonicSeconds']-95
            raw.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.assertRaisesRegex(ValueError,'parent local epoch'):
                self.run_stream(root)

    def test_11_coherent_child_epoch_and_startup_reset_cannot_rewrite_parent_release(self):
        terminal=dict(localEpochMonotonic=95.0);child=dict(startedMonotonic=95.0)
        lease=dict(releaseMonotonic=95.0)
        a.verify_child_epoch_anchor(terminal,child,lease)
        original=a.canonical(dict(terminal=terminal,child=child))
        terminal['localEpochMonotonic']=96.0;child['startedMonotonic']=96.0
        self.assertNotEqual(a.canonical(dict(terminal=terminal,child=child)),original)
        with self.assertRaisesRegex(ValueError,'actual parent release'):
            a.verify_child_epoch_anchor(terminal,child,lease)

    def test_12_legal_other_scope_controller_cannot_replace_this_stream_or_idle_owner(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            root=Path(d);self.make_stream(root);self.run_stream(root)
            p=root/'process-observations.jsonl';rows=[json.loads(v) for v in p.read_text().splitlines()]
            original=a.canonical(rows)
            replacement=dict(scopeId='3'*32,controllerIdentity=dict(pid=201,createTimeMicros=201000000,parentPid=100))
            for row in rows:row['processObservation']['lifecycle']=copy.deepcopy(replacement)
            self.assertNotEqual(a.canonical(rows),original)
            p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.assertRaisesRegex(ValueError,'file owner'):
                self.run_stream(root)
            # The exact same predicate binds all 360 idle rows to parent_scope.
            with self.assertRaisesRegex(ValueError,'file owner'):
                a.verify_scope_owner(replacement,'2'*32,ROOT)

    def test_13_wrong_loaded_module_cannot_borrow_same_content_hash(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            repo=Path(d);valid=repo/'fixed.py';wrong=repo/'other.py'
            valid.write_bytes(b'# fixed synthetic dependency\n');wrong.write_bytes(valid.read_bytes())
            sources={'fixed.py':a.file_sha(valid)}
            self.assertEqual(a.verify_loaded_module(types.SimpleNamespace(__file__=str(valid)),repo,sources),'fixed.py')
            self.assertNotEqual(str(wrong),str(valid))
            with self.assertRaisesRegex(ValueError,'source identity mismatch'):
                a.verify_loaded_module(types.SimpleNamespace(__file__=str(wrong)),repo,sources)


if __name__=='__main__':unittest.main()
