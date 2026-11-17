"""Bounded disposable-process controls, no actual research observation."""
import copy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
import process_lifecycle as life


@unittest.skipUnless(sys.platform=='darwin','project APFS disposable-process engineering controls')
class ManagedProcessControls(unittest.TestCase):
    def setUp(self):
        self.scratch=tempfile.TemporaryDirectory(prefix='lifecycle-process-controls-',dir=life.POSIX/'tmp')
        self.root=Path(self.scratch.name);self.env=dict(os.environ)
        own=life.identity();self.registry=life.Registry(self.root/'journal.jsonl',[(own['pid'],own['createTimeMicros']/1000000)],
            source_commit='1'*40,policy_sha256='2'*64,capture_lock_path=self.root/'capture.lock')
    def tearDown(self):
        for p in self.registry.handles:
            if p.poll() is None:p.kill()
            p.wait(timeout=2)
        self.registry.close();os.environ.clear();os.environ.update(self.env)
        life._env_registry=None;self.scratch.cleanup()
    def test_fast_true_has_real_identity_release_and_parent_wait(self):
        result=self.registry.run(['/usr/bin/true'],capture_output=True,timeout=2)
        self.assertEqual(result.returncode,0)
        lease=[v for v in life.validate_view(self.registry.sample())['leases'].values() if v['role']=='finite'][0]
        self.assertLess(lease['registerSeq'],lease['releaseSeq']);self.assertLess(lease['releaseSeq'],lease['waitSeq'])
        self.assertEqual(lease['absence']['witnessKind'],'PARENT_WAIT_REAPED')
        self.assertEqual(self.registry.final()['status'],'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT')
    def test_activate_returns_same_local_scope(self):
        self.registry.activate();self.assertIs(life.from_environment(),self.registry)
    def test_nested_child_opens_distinct_scope_bound_to_its_parent_lease(self):
        command=[sys.executable,'-B','-c',
            "import sys;sys.path.insert(0,"+repr(str(REPO/'experiments/ch7'))+
            ");import process_lifecycle as p;r=p.from_environment();print(r.stage,flush=True);r.close()"]
        result=self.registry.run(command,stage='nested-block',capture_output=True,text=True,timeout=3)
        self.assertEqual(result.stdout.strip(),'nested-block')
        state=self.registry._state();self.assertEqual(len(state['scopes']),2)
    def test_nonzero_is_reaped_but_not_successful_workload(self):
        p=self.registry.launch([sys.executable,'-c','raise SystemExit(7)'])
        self.assertEqual(p.wait(timeout=3),7)
        self.assertEqual(self.registry.final()['status'],'UNKNOWN_OR_ADVERSE_OWNED_LIFECYCLE')
    def test_identity_ready_failure_never_falls_back_to_pid_only(self):
        with patch.object(life,'READY_SECONDS',0.):
            with self.assertRaisesRegex(ValueError,'identity-ready'):self.registry.launch(['/usr/bin/true'])
        self.assertFalse(any(v['role']=='finite' for v in self.registry._state()['leases'].values()))
    def test_wait_timeout_has_owned_cleanup_and_recorded_signal(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.registry.run([sys.executable,'-c','import time;time.sleep(3)'],timeout=.01)
        lease=next(v for v in self.registry._state()['leases'].values() if v['role']=='finite')
        self.assertLess(lease['exitCode'],0)
    def test_manual_pid_registration_is_forbidden(self):
        with self.assertRaises(ValueError):self.registry.register(os.getpid())
    def test_reentrant_current_thread_capture_has_no_second_flock(self):
        with life.capture_lock(self.registry.lock_path):
            result=self.registry.run(['/usr/bin/true'],timeout=2)
            self.assertEqual(result.returncode,0)
    def test_peer_lock_deadline_is_adverse(self):
        ready=threading.Event();release=threading.Event()
        def hold():
            with life.capture_lock(self.registry.lock_path):ready.set();release.wait(2)
        thread=threading.Thread(target=hold);thread.start();self.assertTrue(ready.wait(1))
        try:
            with self.assertRaisesRegex(ValueError,'timeout'):
                with life.capture_lock(self.registry.lock_path,timeout=.03):pass
        finally:release.set();thread.join()
    def test_prefix_mutation_truncation_and_replacement_refuse_cache(self):
        self.registry.sample();raw=self.registry.path.read_bytes();self.registry.path.write_bytes(raw[:-1])
        with self.assertRaises(ValueError):self.registry.sample()
        changed=bytearray(raw);changed[0]=ord(' ')
        self.registry.path.write_bytes(changed)
        with self.assertRaises(ValueError):self.registry.sample()
        self.registry.path.write_bytes(raw);other=self.registry.path.with_suffix('.new');other.write_bytes(raw);other.chmod(0o600);os.replace(other,self.registry.path)
        with self.assertRaises(ValueError):self.registry.sample()
        # Reset only this deliberately corrupted fixture for ordinary teardown.
        self.registry._cached_inode=None;self.registry._cached_raw=b'';self.registry._cached_state=None
    def test_concurrent_launches_have_distinct_identity_bound_waits(self):
        errors=[]
        def launch():
            try:self.assertEqual(self.registry.run(['/usr/bin/true'],timeout=2).returncode,0)
            except BaseException as error:errors.append(error)
        threads=[threading.Thread(target=launch) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join(4)
        self.assertFalse(any(t.is_alive() for t in threads));self.assertEqual(errors,[])
        finite=[v for v in self.registry._state()['leases'].values() if v['role']=='finite']
        self.assertEqual(len(finite),4);self.assertTrue(all(v['exitCode']==0 and v['waitSeq'] for v in finite))
    def test_kernel_reaped_poll_is_not_reported_alive_while_metadata_waits(self):
        p=self.registry.launch([sys.executable,'-c','import time;time.sleep(.05)'])
        with self.registry._mutex:
            self.assertEqual(p.process.wait(timeout=2),0)
            self.assertEqual(p.poll(),0)
            self.assertFalse(p._done.is_set())
        self.assertEqual(p.wait(timeout=2),0)
    def test_local_scope_does_not_adopt_parent_only_discovered_sibling(self):
        # Virtual identities exercise scoping only; no process with these PIDs
        # is created, adopted, probed or signalled.
        parent=self.registry.writer
        child=dict(pid=parent['pid']+1000000,createTimeMicros=parent['createTimeMicros']+100,parentPid=parent['pid'])
        lid='c'*32
        self.registry._append('FINITE_REGISTER',dict(leaseId=lid,role='finite',stageId='virtual-child',identity=child,
            parentIdentity=parent,commandSha256='d'*64,executableSha256='e'*64,readyMonotonic=time.monotonic()))
        self.registry._append('RELEASE',dict(leaseId=lid))
        with patch.object(life,'identity',return_value=child):
            local=life.Registry(self.registry.path,[(child['pid'],child['createTimeMicros']/1000000)],stage='virtual-child',
                source_commit=self.registry.source_commit,policy_sha256=self.registry.policy_sha256,
                run_id=self.registry.run_id,capture_lock_path=self.registry.lock_path,parent_lease_id=lid)
        sibling=dict(pid=parent['pid']+1000001,createTimeMicros=parent['createTimeMicros']+200,parentPid=parent['pid'])
        now=time.monotonic()
        self.registry._append('DISCOVER',dict(identity=sibling,scopeId=self.registry.scope_id,ancestry=[sibling,parent],
            sampleId='f'*32,phase='before',nativeStdoutSha256='a'*64,graphStartedMonotonic=now-.02,
            graphCompletedMonotonic=now-.01))
        self.assertEqual(local.final()['status'],'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT')
        self.assertEqual(self.registry.final()['status'],'UNKNOWN_OR_ADVERSE_OWNED_LIFECYCLE')


if __name__=='__main__':unittest.main()
