"""Pure fake-clock controls. No observer, process, API, flock or native helper."""
import ast
from contextlib import contextmanager
import hashlib
import math
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest

import locked_schedule_candidate as c

HERE=Path(__file__).resolve().parent
BASE=Path('/Volumes/Untitled/AIJADE')
SOURCE_RELATIVE='experiments/ch7/process_lifecycle.py'
SOURCE_SHA='93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65'
OBSERVED_CRITICAL=1.4372957790037617
OBSERVED_POST=1.6352402319898829-OBSERVED_CRITICAL
UNSET=object()
PORTABLE_LAYOUT_PROOF={}


def select_lifecycle_source(test_file=None,source_env=UNSET):
    """Use an explicit project checkout or exact packaged/ancestor Q source.

    An explicit override is authoritative: invalid/missing/newer bytes refuse
    without fallback. All modes authenticate the complete frozen file before
    extracting the one function. No source module or OS observer is imported.
    """
    anchor=Path(__file__ if test_file is None else test_file).resolve()
    value=os.environ.get('AIJADE_RESEARCH_SOURCE') if source_env is UNSET else source_env
    def verified(path):
        if path.is_symlink() or not path.is_file():
            raise ValueError('frozen Q lifecycle source missing or linked')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=SOURCE_SHA:
            raise ValueError('frozen Q lifecycle complete-file SHA differs; newer source is not accepted')
        return path
    if value is not None:
        if type(value) is not str or not value:
            raise ValueError('explicit AIJADE_RESEARCH_SOURCE must name a BASE-local checkout')
        root=Path(value)
        if not root.is_absolute() or root.resolve()!=root or not root.is_relative_to(BASE.resolve()) \
                or any(p.is_symlink() for p in (root,*root.parents)):
            raise ValueError('explicit AIJADE_RESEARCH_SOURCE must name a BASE-local canonical checkout')
        return verified(root/SOURCE_RELATIVE)
    packaged=anchor.parent/'fixtures/process_lifecycle.py'
    if packaged.exists() or packaged.is_symlink():return verified(packaged)
    for root in anchor.parents:
        candidate=root/SOURCE_RELATIVE
        if candidate.exists() or candidate.is_symlink():return verified(candidate)
    raise ValueError('frozen Q lifecycle source unavailable; supply its exact fixture or AIJADE_RESEARCH_SOURCE')


class FakeClock:
    def __init__(self,now=0.0):self.now=now;self.sleeps=[]
    def monotonic(self):return self.now
    def sleep(self,value):
        if value<0:raise AssertionError('negative fake sleep')
        self.sleeps.append(value)
        self.now=max(self.now+value,math.nextafter(self.now,math.inf))


def original_lock_fixture(release,*,started=0.0):
    """Execute the frozen original function with every OS/clock operation fake."""
    source=select_lifecycle_source().read_bytes()
    if hashlib.sha256(source).hexdigest()!=SOURCE_SHA:raise AssertionError('frozen P4 lifecycle source changed')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='capture_lock')
    clock=FakeClock(started);closed=[];calls=[]
    item=SimpleNamespace(st_dev=1,st_ino=2,st_mode=stat.S_IFREG|0o600,st_nlink=1,st_uid=1234)
    def flock(fd,flags):
        calls.append((clock.now,flags))
        if flags!=8 and clock.now<release:raise BlockingIOError('synthetic other-thread holder')
    fake_os=SimpleNamespace(O_RDWR=2,O_CREAT=64,fstat=lambda fd:item,
        stat=lambda path,follow_symlinks=False:item,getuid=lambda:1234,close=closed.append)
    namespace=dict(contextmanager=contextmanager,MAX_LOCK_WAIT=c.MAX_LOCK_WAIT,
        POSIX=Path('/Volumes/Untitled/AIJADE/.runtime/posix'),project_path=Path,
        need=c.need,_number=c.finite,_locks=SimpleNamespace(active={}),
        time=clock,os=fake_os,stat=stat,digest=lambda raw:hashlib.sha256(raw).hexdigest(),
        _open_owned=lambda path,flags:77,
        fcntl=SimpleNamespace(flock=flock,LOCK_EX=2,LOCK_NB=4,LOCK_UN=8))
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<frozen-source-fake-OS>','exec'),namespace)
    return namespace['capture_lock'],clock,closed,calls


class OriginalContentionControls(unittest.TestCase):
    def test_original_code_refuses_measured_holder_without_any_process_spawn(self):
        # Model the final public archive layout using a tiny BASE-local tree.
        # This validates source selection only; no source module is executed.
        source=select_lifecycle_source(source_env=None).read_bytes()
        scratch=BASE/'.runtime/posix/tmp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='public-scheduler-layout-',dir=scratch) as temporary:
            root=Path(temporary)/'repo';path=root/SOURCE_RELATIVE;path.parent.mkdir(parents=True);path.write_bytes(source)
            public=root/'experiments/ch7/mac-prefix-v4-2026-11-17/qualification-attempt-01/followup-proposal/test_locked_schedule_candidate.py'
            public.parent.mkdir(parents=True);public.write_text('# public-layout placeholder; never imported\n')
            chosen=select_lifecycle_source(public,source_env=None)
            self.assertEqual(chosen,path)
            self.assertEqual(select_lifecycle_source(public,source_env=str(root)),path)
            PORTABLE_LAYOUT_PROOF.update(publicRelativeTestPath=str(public.relative_to(root)),
                sourceRelativePath=SOURCE_RELATIVE,sourceSha256=hashlib.sha256(chosen.read_bytes()).hexdigest(),
                ancestorResolution=True,explicitBaseCheckoutResolution=True,actualPlatform=os.sys.platform)
            path.write_bytes(source+b'\nnewer source must refuse\n')
            with self.assertRaisesRegex(ValueError,'complete-file SHA differs'):
                select_lifecycle_source(public,source_env=None)
            with self.assertRaisesRegex(ValueError,'complete-file SHA differs'):
                select_lifecycle_source(source_env=str(root))
            path.unlink()
            with self.assertRaisesRegex(ValueError,'unavailable'):select_lifecycle_source(public,source_env=None)
            with self.assertRaisesRegex(ValueError,'missing'):select_lifecycle_source(source_env=str(root))
            with self.assertRaisesRegex(ValueError,'BASE-local'):
                select_lifecycle_source(source_env='/outside-authorized-fixture')
        lock,clock,closed,calls=original_lock_fixture(OBSERVED_CRITICAL,started=.06)
        entered=False
        with self.assertRaisesRegex(ValueError,'capture lock timeout'):
            with lock(Path('/Volumes/Untitled/AIJADE/.runtime/posix/locks/fake.lock')):entered=True
        self.assertFalse(entered)
        self.assertAlmostEqual(clock.now,.06+1.25,places=9)
        self.assertEqual(closed,[77]);self.assertGreater(len(calls),1)

    def test_original_code_can_acquire_only_when_holder_releases_within_unchanged_bound(self):
        lock,clock,closed,calls=original_lock_fixture(.9)
        with lock(Path('/Volumes/Untitled/AIJADE/.runtime/posix/locks/fake.lock')) as evidence:
            self.assertLessEqual(evidence['waitSeconds'],1.25)
            self.assertGreaterEqual(clock.now,.9)
        self.assertEqual(evidence['state'],'HELD_AND_RELEASED')
        self.assertEqual(closed,[77])

    def test_same_thread_reentrance_does_not_prove_peer_thread_reentrance(self):
        lock,clock,closed,calls=original_lock_fixture(0)
        path=Path('/Volumes/Untitled/AIJADE/.runtime/posix/locks/fake.lock')
        with lock(path):
            count=len(calls)
            with lock(path) as evidence:self.assertTrue(evidence['nested'])
            self.assertEqual(len(calls),count)
        self.assertEqual(closed,[77])


class SchedulingControls(unittest.TestCase):
    def test_declared_real_two_monitor_profile_refuses_before_dummy_stage(self):
        streams=[c.CaptureStream(name,OBSERVED_CRITICAL,OBSERVED_POST) for name in ('sequence','block')]
        capacity=c.capture_capacity(streams)
        self.assertGreater(capacity['utilization'],1)
        result=c.simulate_guarded_stage(streams,[],ticks=360)
        self.assertEqual(result['status'],'REFUSED_BEFORE_STAGE_UNSCHEDULABLE_PROFILE')
        self.assertEqual(result['observations'],[])
        self.assertFalse(result['scientificQualification'])

    def test_simultaneous_dual_observers_fail_original_capture_wait(self):
        streams=[c.CaptureStream(name,OBSERVED_CRITICAL,OBSERVED_POST) for name in ('a','b')]
        rows=c.original_fixed_grid_trace(streams,4)['records']
        self.assertEqual(rows[-1]['status'],'CAPTURE_LOCK_TIMEOUT')
        self.assertFalse(rows[-1]['granted'])

    def test_offsets_do_not_solve_repeated_nominal_capacity_overload(self):
        for offset in [i/10 for i in range(20)]:
            streams=[c.CaptureStream('sequence',OBSERVED_CRITICAL,OBSERVED_POST),
                     c.CaptureStream('block',OBSERVED_CRITICAL,OBSERVED_POST,offset)]
            rows=c.original_fixed_grid_trace(streams,15)['records']
            with self.subTest(offset=offset):
                self.assertIn(rows[-1]['status'],('CAPTURE_LOCK_TIMEOUT','WHOLE_OBSERVATION_BUDGET_EXCEEDED'))

    def test_individual_valid_service_can_still_exceed_whole_budget_after_queueing(self):
        streams=[c.CaptureStream('a',OBSERVED_CRITICAL,OBSERVED_POST),
                 c.CaptureStream('b',OBSERVED_CRITICAL,OBSERVED_POST,.75)]
        rows=c.original_fixed_grid_trace(streams,4)['records']
        self.assertEqual(rows[-1]['status'],'WHOLE_OBSERVATION_BUDGET_EXCEEDED')
        self.assertGreater(rows[-1]['wholeObservationSeconds'],2.5)
        self.assertEqual(rows[-1]['actualStartedSeconds'],rows[-1]['scheduledSeconds'])

    def test_single_scope_sufficient_slack_keeps_absolute_grid_and_finite_work_visible(self):
        jobs=[c.FiniteWork('gate',.1,.2,.15),c.FiniteWork('source-proof',1.1,.2,.15)]
        result=c.simulate_guarded_stage([c.CaptureStream('one',.5,.1)],jobs,ticks=4)
        self.assertEqual(result['status'],'DUMMY_DECLARED_TRACE_WITHIN_BOUNDS_NOT_BACKEND_QUALIFICATION')
        self.assertEqual([r['scheduledSeconds'] for r in result['observations']],[0,2,4,6])
        self.assertEqual([r['actualStartedSeconds'] for r in result['observations']],[0,2,4,6])
        self.assertEqual(len(result['work']),2)
        self.assertGreater(result['work'][0]['queueSeconds'],0)
        self.assertFalse(result['actualReadsPerformed'])

    def test_unresolved_multi_scope_coordination_does_not_gain_an_adapter(self):
        streams=[c.CaptureStream('a',.2,.1),c.CaptureStream('b',.2,.1,1)]
        with self.assertRaisesRegex(ValueError,'not implemented'):c.simulate_guarded_stage(streams,[],ticks=2)

    def test_finite_reservation_overrun_is_refused_without_extending_slots(self):
        with self.assertRaisesRegex(ValueError,'reservation'):
            c.simulate_guarded_stage([c.CaptureStream('one',.5,.1)],
                [c.FiniteWork('slow-ready',.1,.2,.3)],ticks=4)

    def test_pending_work_after_fixed_end_is_not_a_success(self):
        result=c.simulate_guarded_stage([c.CaptureStream('one',.5,.1)],
            [c.FiniteWork('later',8,.2,.1)],ticks=2)
        self.assertEqual(result['status'],'REFUSED_PENDING_FINITE_WORK_AT_FIXED_END')
        self.assertEqual(result['pending'],['later'])

    def test_delayed_intent_cannot_hide_outside_capture_budget(self):
        with self.assertRaisesRegex(ValueError,'conservative original wait'):
            c.simulate_guarded_stage([c.CaptureStream('one',1.4,.2)],
                [c.FiniteWork('queued',0,.2,.1)],ticks=2)

    def test_actual_clock_reversal_and_late_writer_remain_adverse(self):
        row=dict(scheduledSeconds=10,actualStartedSeconds=10,acquiredSeconds=10.1,
            releasedSeconds=11,actualCompletedSeconds=11.2,writerCompletedSeconds=11.3)
        self.assertTrue(c.validate_observation(row,8))
        for key,value in [('acquiredSeconds',9.9),('writerCompletedSeconds',12.5001)]:
            with self.subTest(field=key),self.assertRaises(ValueError):
                c.validate_observation(dict(row,**{key:value}),8)

    def test_handoff_actual_start_gap_cannot_be_reset(self):
        row=dict(scheduledSeconds=10,actualStartedSeconds=10,acquiredSeconds=10,
            releasedSeconds=11,actualCompletedSeconds=11.2,writerCompletedSeconds=11.3)
        self.assertTrue(c.validate_observation(row,7))
        with self.assertRaisesRegex(ValueError,'continuity'):c.validate_observation(row,6.999)

    def test_invalid_profile_identity_boolean_and_nonfinite_are_refused(self):
        for value in (True,float('inf'),-1):
            with self.subTest(value=value),self.assertRaises(ValueError):
                c.capture_capacity([c.CaptureStream('scope',value,.1)])
        with self.assertRaisesRegex(ValueError,'duplicate'):
            c.capture_capacity([c.CaptureStream('same',.1,.1),c.CaptureStream('same',.1,.1)])


if __name__=='__main__':unittest.main(verbosity=2)
