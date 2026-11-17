"""Disposable fake helpers test native launch plumbing; never call real sysctl."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
import process_lifecycle as life
import mac_process_guard_v3 as guard


@unittest.skipUnless(sys.platform=='darwin','project APFS fake-helper controls; no real native census')
class NativeManagedLaunchControls(unittest.TestCase):
    def setUp(self):
        self.scratch=tempfile.TemporaryDirectory(prefix='lifecycle-fake-native-',dir=life.POSIX/'tmp')
        self.root=Path(self.scratch.name);own=life.identity()
        self.registry=life.Registry(self.root/'journal.jsonl',[(own['pid'],own['createTimeMicros']/1000000)],
            source_commit='1'*40,policy_sha256='2'*64,capture_lock_path=self.root/'capture.lock')
    def tearDown(self):
        for p in self.registry.handles:
            if p.poll() is None:p.kill()
            p.wait(timeout=2)
        self.registry.close();self.scratch.cleanup()
    def helper(self,body):
        p=self.root/'fake-native-helper'
        p.write_text('#!'+sys.executable+'\n'+body+'\n');p.chmod(0o700)
        return p
    def run_helper(self,path):
        with life.capture_lock(self.registry.lock_path):return guard._run_native(path,self.registry)
    def test_native_primitive_uses_identity_ready_register_release_actual_wait(self):
        helper=self.helper("import sys;assert len(sys.argv)==1;sys.stdout.write('synthetic-native-fixture\\n')")
        r=self.run_helper(helper)
        self.assertEqual(r['exitCode'],0,r);self.assertTrue(r['cleanupKnown'],r)
        self.assertFalse(r['timedOut'],r);self.assertEqual(r['stdout'],b'synthetic-native-fixture\n')
        self.assertLessEqual(r['durationSeconds'],guard.NATIVE_TIMEOUT,r)
        lease=self.registry._state()['leases'][r['managedLeaseId']]
        self.assertEqual(lease['identity']['pid'],r['spawnedHelperPid'])
        self.assertEqual(lease['parentIdentity'],self.registry.writer)
        self.assertEqual(lease['stageId'],'observer-native-census')
        self.assertEqual(lease['commandSha256'],guard.canonical_sha256([str(helper)]))
        self.assertEqual(lease['executableSha256'],hashlib.sha256(helper.read_bytes()).hexdigest())
        self.assertLess(lease['registerSeq'],lease['releaseSeq']);self.assertLess(lease['releaseSeq'],lease['waitSeq'])
        self.assertEqual(lease['absenceWitnessKind'],'PARENT_WAIT_REAPED')
    def test_native_timeout_kills_only_owned_fake_and_keeps_wait_status(self):
        helper=self.helper('import time;time.sleep(3)')
        r=self.run_helper(helper)
        self.assertTrue(r['timedOut'],r);self.assertTrue(r['cleanupKnown'],r)
        self.assertIsNotNone(r['managedLeaseId']);self.assertLess(r['exitCode'],0)
        lease=self.registry._state()['leases'][r['managedLeaseId']]
        self.assertEqual(lease['exitCode'],r['exitCode'])
    def test_native_output_cap_still_refuses_and_reaps_fake(self):
        helper=self.helper("import sys;sys.stdout.write('x'*100000);sys.stdout.flush()")
        with patch.object(guard,'MAX_CENSUS_BYTES',1024):r=self.run_helper(helper)
        self.assertTrue(r['oversized'],r);self.assertTrue(r['cleanupKnown'],r)
        self.assertLessEqual(len(r['stdout']),1025)
    def test_journal_wait_error_preserves_native_stdout_as_adverse(self):
        helper=self.helper("import sys;sys.stdout.write('fixture-body');sys.stdout.flush()")
        with patch.object(life.ManagedProcess,'wait',side_effect=ValueError('controlled wait evidence fault')):
            r=self.run_helper(helper)
        self.assertFalse(r['cleanupKnown']);self.assertEqual(r['cleanupErrorClass'],'ValueError')
        self.assertEqual(r['stdout'],b'fixture-body')


if __name__=='__main__':unittest.main()
