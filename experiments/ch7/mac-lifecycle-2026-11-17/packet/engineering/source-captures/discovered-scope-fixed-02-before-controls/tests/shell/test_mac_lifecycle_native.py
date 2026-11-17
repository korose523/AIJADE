"""Disposable fake helpers test native launch plumbing; never call real sysctl."""
import hashlib
import os
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

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
        compiler=shutil.which('cc') or shutil.which('clang')
        if compiler is None:self.skipTest('existing C compiler required for non-census dummy helper')
        source=self.root/'fake-native-helper.c'
        source.write_text('#define _POSIX_C_SOURCE 200809L\n#include <stdio.h>\n#include <time.h>\n'
                          'int main(int argc,char **argv){(void)argv;if(argc!=1)return 8;'+body+';return 0;}\n')
        result=subprocess.run([compiler,'-std=c11','-O1',str(source),'-o',str(p)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        return p
    def run_helper(self,path):
        with life.capture_lock(self.registry.lock_path):return guard._run_native(path,self.registry)
    def test_native_primitive_uses_identity_ready_register_release_actual_wait(self):
        helper=self.helper('fputs("synthetic-native-fixture\\n",stdout)')
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
        helper=self.helper('struct timespec t={3,0};nanosleep(&t,0)')
        r=self.run_helper(helper)
        self.assertTrue(r['timedOut'],r);self.assertTrue(r['cleanupKnown'],r)
        self.assertIsNotNone(r['managedLeaseId']);self.assertLess(r['exitCode'],0)
        lease=self.registry._state()['leases'][r['managedLeaseId']]
        self.assertEqual(lease['exitCode'],r['exitCode'])
    def test_native_ready_refusal_keeps_failure_identity_without_direct_fallback(self):
        helper=self.helper('fputs("must-not-execute",stdout)')
        with patch.object(life,'READY_SECONDS',0.):r=self.run_helper(helper)
        self.assertIsNone(r['managedLeaseId']);self.assertIn('launchRefusal',r)
        self.assertEqual(r['launchRefusal']['identityStatus'],'UNKNOWN')
        self.assertEqual(r['stdout'],b'')
        self.assertEqual(len(self.registry._state()['launchRefusals']),1)


class NativeWaitErrorFixture(unittest.TestCase):
    def test_native_output_cap_refuses_and_reaps_exact_pipe_fixture(self):
        # Isolate output accounting from executable startup. A cold ready-gate
        # delay is a timeout, never evidence that the output-cap path ran.
        # Real disposable C register/wait and deadline are separate above.
        out_r,out_w=os.pipe();err_r,err_w=os.pipe()
        os.write(out_w,b'x'*2048);os.close(out_w);os.close(err_w)
        class FakeManaged:
            pid=999998;lease_id='e'*32;exit_code=None;kills=0
            stdout=os.fdopen(out_r,'rb');stderr=os.fdopen(err_r,'rb')
            def __init__(self):self.process=self
            def poll(self):return self.exit_code
            def wait(self,timeout=None):return self.exit_code
            def kill(self):self.kills+=1;self.exit_code=-9
        process=FakeManaged();lifecycle=SimpleNamespace(launch=lambda *args,**kwargs:process)
        with patch.object(guard,'MAX_CENSUS_BYTES',1024):
            r=guard._run_native('/fixture-not-executed',lifecycle)
        self.assertTrue(r['oversized'],r);self.assertTrue(r['cleanupKnown'],r)
        self.assertFalse(r['timedOut'],r);self.assertEqual(len(r['stdout']),1025)
        self.assertEqual(process.kills,1);self.assertEqual(r['exitCode'],-9)
    def test_wait_error_keeps_already_received_raw_bytes_and_remains_adverse(self):
        # Deterministic transport fault: no executable, compiler, census or
        # process is started. Positive managed wait is covered by the real
        # disposable C actor above; this isolates the metadata-error branch.
        out_r,out_w=os.pipe();err_r,err_w=os.pipe()
        os.write(out_w,b'fixture-body');os.close(out_w);os.close(err_w)
        class FakeManaged:
            pid=999999;lease_id='f'*32
            stdout=os.fdopen(out_r,'rb');stderr=os.fdopen(err_r,'rb')
            process=SimpleNamespace(poll=lambda:0)
            def poll(self):return 0
            def wait(self,timeout=None):raise ValueError('controlled journal evidence fault')
            def kill(self):raise AssertionError('must not signal a kernel-terminal fixture')
        lifecycle=SimpleNamespace(launch=lambda *args,**kwargs:FakeManaged())
        r=guard._run_native('/fixture-not-executed',lifecycle)
        self.assertFalse(r['cleanupKnown']);self.assertEqual(r['cleanupErrorClass'],'ValueError')
        self.assertEqual(r['stdout'],b'fixture-body')


if __name__=='__main__':unittest.main()
