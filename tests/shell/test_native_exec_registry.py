"""Portable native gate and Registry controls, no listener/API/model query."""
from pathlib import Path
import copy
import hashlib
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
import process_lifecycle as life
import native_exec_registry as native

SCRATCH=Path(os.environ.get('AIJADE_NATIVE_TEST_SCRATCH',str(REPO/'.runtime/native-exec-controls')))
SCRATCH.mkdir(parents=True,exist_ok=True)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NativeExecControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build=tempfile.TemporaryDirectory(dir=SCRATCH,prefix='build-')
        cls.source=REPO/'experiments/ch7/lifecycle_exec_native.c'
        cls.binary=Path(cls.build.name)/'native-ready'
        compiler=shutil.which('clang') or shutil.which('cc')
        if not compiler:raise unittest.SkipTest('existing C compiler unavailable')
        args=[compiler,'-std=c11','-D_POSIX_C_SOURCE=200809L','-Wall','-Wextra','-Werror','-O2',str(cls.source),'-o',str(cls.binary)]
        result=subprocess.run(args,capture_output=True,timeout=30)
        if result.returncode:raise AssertionError(result.stderr.decode())
        cls.binary.chmod(0o755)

    @classmethod
    def tearDownClass(cls):cls.build.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=SCRATCH);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.posix=self.root/'.runtime/posix';(self.posix/'locks').mkdir(parents=True)
        if sys.platform!='darwin':
            p=mock.patch.object(life,'BASE',REPO);p.start();self.addCleanup(p.stop)
        # Only a fixture lock-root is relocated, never original source bytes.
        p=mock.patch.object(life,'POSIX',self.posix);p.start();self.addCleanup(p.stop)
        self.shim=self.root/'native-ready';shutil.copyfile(self.binary,self.shim);self.shim.chmod(0o755)
        self.binding=dict(mode=native.MODE,adapterSourceSha256=sha(native.__file__),
            sourcePath=str(self.source),sourceSha256=sha(self.source),binaryPath=str(self.shim),binarySha256=sha(self.shim))
        self.policy=dict(lifecycleExecMode=native.MODE,nativeExec=self.binding,
            lifecycle=dict(execShimSha256=self.binding['binarySha256']))
        self.registries=[]
        self.addCleanup(self.cleanup_handles)

    def cleanup_handles(self):
        for registry in self.registries:
            for handle in registry.handles:
                if handle.process.poll() is None:handle.kill()
                handle.wait(timeout=3)

    def registry(self,policy=None):
        value=native.registry_for_policy(self.policy if policy is None else policy,self.posix/('journal-'+str(len(self.registries))+'.jsonl'),
            stage='native-control',source_commit='2'*40,policy_sha256='3'*64,
            capture_lock_path=self.posix/'locks/shared.lock')
        self.registries.append(value);return value

    def bare(self,target,*,ready_text=None,gate_text=None,separator='--'):
        ready_r,ready_w=os.pipe();gate_r,gate_w=os.pipe()
        process=subprocess.Popen([str(self.shim),str(ready_w) if ready_text is None else ready_text,
            str(gate_r) if gate_text is None else gate_text,separator,*target],pass_fds=(ready_w,gate_r),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        os.close(ready_w);os.close(gate_r)
        return process,ready_r,gate_w

    def ready(self,fd):
        selected=selectors.DefaultSelector();selected.register(fd,selectors.EVENT_READ)
        try:
            self.assertTrue(selected.select(2),'bounded READY timeout')
            raw=os.read(fd,4096)
            return json.loads(raw)
        finally:selected.close()

    def end_bare(self,process,ready,gate):
        for fd in (ready,gate):
            try:os.close(fd)
            except OSError:pass
        if process.poll() is None:process.kill()
        process.communicate(timeout=3)

    def test_gate_blocks_then_same_pid_exec_and_matching_monotonic(self):
        marker=self.root/'marker';begin=time.monotonic()
        p,r,g=self.bare(['/bin/sh','-c','printf "%s" "$$" > "$1"','fixture',str(marker)])
        try:
            ready=self.ready(r);end=time.monotonic()
            self.assertEqual(ready['pid'],p.pid);self.assertEqual(ready['parentPid'],os.getpid())
            self.assertLessEqual(begin,ready['readyMonotonic']);self.assertLessEqual(ready['readyMonotonic'],end+.002)
            self.assertFalse(marker.exists());self.assertIsNone(p.poll())
            os.write(g,b'1');stdout,stderr=p.communicate(timeout=3)
            self.assertEqual((p.returncode,stdout,stderr),(0,b'',b''))
            self.assertEqual(int(marker.read_text()),p.pid)
        finally:self.end_bare(p,r,g)

    def test_wrong_release_and_eof_never_exec(self):
        for value in (b'0',None):
            with self.subTest(gate=value):
                marker=self.root/('marker-'+str(value));p,r,g=self.bare(['/usr/bin/touch',str(marker)])
                try:
                    self.ready(r)
                    if value is None:os.close(g);g=-1
                    else:os.write(g,value)
                    _,stderr=p.communicate(timeout=3)
                    self.assertEqual(p.returncode,125);self.assertIn(b'RELEASE_REQUIRED',stderr)
                    self.assertFalse(marker.exists())
                finally:self.end_bare(p,r,g)

    def test_strict_fd_argv_and_absolute_target_refuse(self):
        for args in [dict(ready_text='-1'),dict(ready_text=' 9'),dict(ready_text='9999999999999999999999'),
                     dict(ready_text='1'),dict(gate_text='-1'),dict(separator='wrong')]:
            with self.subTest(args=args):
                p,r,g=self.bare(['/usr/bin/true'],**args)
                try:
                    _,stderr=p.communicate(timeout=3);self.assertEqual(p.returncode,125);self.assertIn(b'ARGUMENTS',stderr)
                finally:self.end_bare(p,r,g)
        p,r,g=self.bare(['relative-target'])
        try:self.assertEqual(p.communicate(timeout=3)[0],b'');self.assertEqual(p.returncode,125)
        finally:self.end_bare(p,r,g)

    def test_exec_failure_is_nonzero_after_real_gate(self):
        p,r,g=self.bare([str(self.root/'missing-target')])
        try:
            self.ready(r);os.write(g,b'1');_,stderr=p.communicate(timeout=3)
            self.assertEqual(p.returncode,126);self.assertIn(b'EXEC_FAILED',stderr)
        finally:self.end_bare(p,r,g)

    def test_actual_native_managed_wait_and_full_canonical_replay(self):
        registry=self.registry();handle=registry.launch(['/usr/bin/true'])
        self.assertIs(type(handle),life.ManagedProcess);self.assertEqual(handle.wait(timeout=3),0)
        evidence=native.evidence_for_handle(handle);state=life.replay_journal(registry.path.read_bytes())
        lease=state['leases'][handle.lease_id]
        self.assertEqual(lease['shimSha256'],self.binding['binarySha256'])
        self.assertEqual(evidence['identity'],lease['identity']);self.assertEqual(evidence['waitSequence'],lease['waitSeq'])
        self.assertEqual(evidence['actualReapedMonotonic'],lease['reapedMonotonic'])
        self.assertEqual(evidence['waitSource'],'Popen.wait');self.assertEqual(evidence['exitCode'],0)
        self.assertEqual(evidence['captureLock']['state'],'HELD_AND_RELEASED')
        evidence['identity']['pid']=999
        handle.native_launch_evidence['identity']['pid']=888
        self.assertNotEqual(native.evidence_for_handle(handle)['identity']['pid'],999)
        self.assertNotEqual(native.evidence_for_handle(handle)['identity']['pid'],888)

    def test_launch_phase_order_and_event_envelopes(self):
        registry=self.registry();handle=registry.launch(['/usr/bin/true']);handle.wait(timeout=3)
        e=native.evidence_for_handle(handle);clocks=e['phaseClocks'];state=registry._state();lease=state['leases'][handle.lease_id]
        names=['requestStartedMonotonic','captureRequestedMonotonic','captureAcquiredMonotonic','popenStartedMonotonic',
            'popenReturnedMonotonic','readyReadCompletedMonotonic','firstIdentityCompletedMonotonic','secondIdentityCompletedMonotonic',
            'registerStartedMonotonic','registerCompletedMonotonic','releaseStartedMonotonic','releaseCompletedMonotonic',
            'gateWrittenMonotonic','postProvenanceCompletedMonotonic','returnedMonotonic']
        self.assertEqual(sorted(clocks[name] for name in names),[clocks[name] for name in names])
        self.assertLessEqual(clocks['registerStartedMonotonic'],lease['registerMonotonic'])
        self.assertLessEqual(lease['registerMonotonic'],clocks['registerCompletedMonotonic'])
        self.assertLessEqual(clocks['releaseStartedMonotonic'],lease['releaseMonotonic'])
        self.assertLessEqual(lease['releaseMonotonic'],clocks['releaseCompletedMonotonic'])
        self.assertLessEqual(clocks['gateWrittenMonotonic'],e['actualReapedMonotonic'])

    def test_wrong_policy_mode_pin_or_legacy_field_substitution_refuse(self):
        for key,value in [('mode','unapproved'),('adapterSourceSha256','f'*64),('sourceSha256','f'*64),('binarySha256','f'*64)]:
            binding=dict(self.binding);binding[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                native.NativeExecRegistry(self.posix/'bad.jsonl',stage='x',source_commit='2'*40,policy_sha256='3'*64,native_exec=binding)
        with self.assertRaises(ValueError):native.registry_for_policy(dict(nativeExec=self.binding),self.posix/'bad2.jsonl')
        with self.assertRaises(ValueError):native.registry_for_policy(dict(lifecycleExecMode='unknown'),self.posix/'bad3.jsonl')

    def test_legacy_factory_keeps_original_class_and_shim(self):
        registry=self.registry(policy={})
        self.assertIs(type(registry),life.Registry)
        handle=registry.launch(['/usr/bin/true']);self.assertEqual(handle.wait(timeout=3),0)
        self.assertEqual(registry._lease(handle.lease_id)['shimSha256'],native.LEGACY_SHIM_SHA256)

    def test_binary_generation_change_after_binding_refuses_before_spawn(self):
        registry=self.registry();replacement=self.root/'replacement';shutil.copyfile(self.shim,replacement);replacement.chmod(0o755);replacement.replace(self.shim)
        with mock.patch.object(native.subprocess,'Popen') as popen:
            with self.assertRaisesRegex(ValueError,'generation changed'):registry.launch(['/usr/bin/true'])
            popen.assert_not_called()
        self.assertEqual(len(registry._state()['launchRefusals']),1)

    def test_binary_or_source_substitution_and_mode_change_refuse_constructor(self):
        self.shim.chmod(0o644)
        with self.assertRaisesRegex(ValueError,'mode'):self.registry()
        self.shim.chmod(0o755);link=self.root/'link';link.symlink_to(self.shim)
        bad=copy.deepcopy(self.policy);bad['nativeExec']['binaryPath']=str(link)
        with self.assertRaises(ValueError):self.registry(bad)
        bad=copy.deepcopy(self.policy);bad['nativeExec']['sourcePath']=str(self.shim)
        with self.assertRaisesRegex(ValueError,'colocated'):self.registry(bad)

    def test_changed_path_while_ready_gate_held_refuses_and_actual_child_is_reaped(self):
        registry=self.registry();original=native._executed_shim
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            replacement=self.root/'new-image';replacement.write_bytes(b'changed provenance');replacement.chmod(0o755);replacement.replace(self.shim)
            return result
        with mock.patch.object(native,'_executed_shim',side_effect=changed):
            with self.assertRaises(ValueError) as context:registry.launch(['/usr/bin/true'])
        refusal=context.exception.lifecycleRefusal
        self.assertTrue(refusal['cleanupKnown']);self.assertEqual(refusal['waitSource'],'Popen.wait')
        self.assertIsInstance(refusal['actualExitCode'],int)
        self.assertTrue(all(p.poll() is not None for p in registry.refused_processes))

    def test_wrong_actual_executable_witness_refuses_without_release(self):
        registry=self.registry()
        with mock.patch.object(native,'_executed_shim',side_effect=ValueError('wrong executable witness')):
            with self.assertRaisesRegex(ValueError,'wrong executable') as context:registry.launch(['/usr/bin/true'])
        self.assertIsNone(context.exception.lifecycleRefusal['registeredLeaseId'])
        self.assertTrue(context.exception.lifecycleRefusal['cleanupKnown'])

    def test_two_concurrent_actual_native_launches_have_independent_leases(self):
        registry=self.registry();results=[];errors=[]
        def run():
            try:
                handle=registry.launch(['/usr/bin/true']);handle.wait(timeout=3);results.append(native.evidence_for_handle(handle))
            except BaseException as error:errors.append(error)
        threads=[threading.Thread(target=run) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads));self.assertEqual(errors,[])
        self.assertEqual(len({row['leaseId'] for row in results}),2)
        self.assertTrue(all(row['exitCode']==0 for row in results))

    def test_actual_environment_activation_reuses_same_adapter(self):
        registry=self.registry()
        with mock.patch.dict(os.environ,registry.environment()),mock.patch.object(life,'_env_registry',None):
            # Root controller cannot attach itself as a nested finite child; use
            # the intended activation API and prove the original lazy API reuse.
            registry.activate()
            self.assertIs(native.activate_from_environment(self.policy),registry)
            self.assertIs(life.from_environment(),registry)
            self.assertEqual(life.run(['/usr/bin/true'],timeout=3).returncode,0)

    def test_signal_before_release_cannot_execute_target(self):
        marker=self.root/'signal-target';p,r,g=self.bare(['/usr/bin/touch',str(marker)])
        try:
            self.ready(r);p.terminate();p.communicate(timeout=3)
            self.assertEqual(p.returncode,-signal.SIGTERM);self.assertFalse(marker.exists())
        finally:self.end_bare(p,r,g)

    def test_wrong_ready_pid_and_future_clock_are_refused_before_register(self):
        for field in ('pid','readyMonotonic'):
            registry=self.registry();real_read=os.read
            def changed(fd,size):
                raw=real_read(fd,size)
                if raw.startswith(b'{"pid":'):
                    value=json.loads(raw);value[field]+=100
                    return json.dumps(value).encode()+b'\n'
                return raw
            with self.subTest(field=field),mock.patch.object(native.os,'read',side_effect=changed):
                with self.assertRaises(ValueError) as context:registry.launch(['/usr/bin/true'])
            self.assertIsNone(context.exception.lifecycleRefusal['registeredLeaseId'])
            self.assertTrue(context.exception.lifecycleRefusal['cleanupKnown'])

    def test_second_parent_birth_witness_cannot_differ(self):
        registry=self.registry();real_identity=native.identity;count=0
        def changed(pid=None):
            nonlocal count
            result=real_identity(pid);count+=1
            if count==2:result['createTimeMicros']+=1
            return result
        with mock.patch.object(native,'identity',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'kernel identity') as context:registry.launch(['/usr/bin/true'])
        self.assertTrue(context.exception.lifecycleRefusal['cleanupKnown'])
        self.assertIsNone(context.exception.lifecycleRefusal['registeredLeaseId'])

    def test_provenance_change_after_release_stays_refused_with_canonical_actual_wait(self):
        registry=self.registry();real_verify=registry._verify_native_binding;calls=0
        def changed():
            nonlocal calls
            calls+=1
            if calls==3:
                replacement=self.root/'post-release-image';replacement.write_bytes(b'changed after release');replacement.chmod(0o755);replacement.replace(self.shim)
            return real_verify()
        with mock.patch.object(registry,'_verify_native_binding',side_effect=changed):
            with self.assertRaises(ValueError) as context:registry.launch(['/usr/bin/true'])
        refusal=context.exception.lifecycleRefusal;self.assertTrue(refusal['cleanupKnown'])
        self.assertIsNotNone(refusal['registeredLeaseId'])
        state=registry._state();lease=state['leases'][refusal['registeredLeaseId']]
        self.assertIsNotNone(lease['waitSeq']);self.assertEqual(lease['exitCode'],refusal['actualExitCode'])
        self.assertEqual(len(state['launchRefusals']),1)

    def test_fd_direction_and_same_descriptor_are_refused(self):
        r,w=os.pipe()
        try:
            for first,second in ((r,r),(r,w),(w,w)):
                result=subprocess.run([str(self.shim),str(first),str(second),'--','/usr/bin/true'],
                    pass_fds=(r,w),capture_output=True,timeout=3)
                self.assertEqual(result.returncode,125)
        finally:os.close(r);os.close(w)

    def test_compiled_c_eintr_and_partial_write_loops(self):
        driver=self.root/'eintr.c';binary=self.root/'eintr-control'
        source=str(self.source).replace('\\','\\\\').replace('"','\\"')
        driver.write_text('''#include <errno.h>
#include <stddef.h>
#include <string.h>
#include <unistd.h>
static int writes=0,reads=0;
static char received[32]; static size_t used=0;
static ssize_t controlled_write(int fd,const void *data,size_t n) {
    (void)fd; ++writes;
    if (writes==1) {errno=EINTR; return -1;}
    size_t take=n>2?2:n; memcpy(received+used,data,take);used+=take;return (ssize_t)take;
}
static ssize_t controlled_read(int fd,void *data,size_t n) {
    (void)fd;(void)n;++reads;
    if (reads==1) {errno=EINTR;return -1;}
    *(char *)data='1';return 1;
}
#define write controlled_write
#define read controlled_read
#define main native_program_main
#include "'''+source+'''"
#undef main
int main(void) {
    if (write_all(8,"complete-bytes",14) || used!=14 || memcmp(received,"complete-bytes",14) || writes!=8) return 1;
    if (release_byte(9) || reads!=2) return 2;
    return 0;
}
''')
        compiler=shutil.which('clang') or shutil.which('cc')
        built=subprocess.run([compiler,'-std=c11','-D_POSIX_C_SOURCE=200809L','-Wall','-Wextra','-Werror',str(driver),'-o',str(binary)],capture_output=True,timeout=30)
        self.assertEqual(built.returncode,0,built.stderr.decode())
        result=subprocess.run([str(binary)],capture_output=True,timeout=3)
        self.assertEqual((result.returncode,result.stdout,result.stderr),(0,b'',b''))


if __name__=='__main__':unittest.main(verbosity=2)
