"""Staged integration with fabricated process/raw/clock fixtures only.

No actual lsof, native helper, daemon, model or business child is queried.
File reads authenticate staged source; runtime factory effects are mocked.
"""
import ast
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
REPO=HERE/'fixture-repo'; P=REPO/'experiments/ch7'
sys.path[:0]=[str(P),str(REPO/'tests/shell')]
import process_lifecycle as life
import mac_process_guard_v3 as guard
import listener_evidence as listener
import native_exec_registry as native
import newowned_guard_cursor as owned
import finite_runtime as runtime
import pure_listener_fixtures as pure
from test_segmented_capture import segmented_fixture
from test_mac_lifecycle_guard import rehash,raw_events


def make_fixture():
    p,o,raw=segmented_fixture()
    p.update(onlineReplayMode=owned.MODE,onlineReplayInitializationMode=owned.INITIALIZATION_MODE,
        onlineReplaySourceSha256=guard._file_sha(P/'newowned_guard_cursor.py'),
        binaryAuthenticationMode='full-read-exact-bytes-v1',
        binaryAuthenticationSourceSha256=guard._file_sha(P/'binary_authentication.py'),
        lifecycleExecMode='native-ready-release-v1',nativeExec=dict(mode='native-ready-release-v1',
            adapterSourceSha256=guard._file_sha(P/'native_exec_registry.py'),
            sourcePath=str(P/'lifecycle_exec_native.c'),sourceSha256=guard._file_sha(P/'lifecycle_exec_native.c'),
            binaryPath=str(life.BASE/'.runtime/posix/tmp/FIXTURE_ONLY_NEVER_EXECUTED_NATIVE'),binarySha256='e'*64),
        listenerEvidence=dict(mode=listener.MODE,moduleSha256=guard._file_sha(P/'listener_evidence.py'),
            command=list(listener.ARGV),executableSha256='f'*64,maxSeconds=.5,maxBytes=65536))
    p['lifecycle']['execShimSha256']=p['nativeExec']['binarySha256']
    pins=dict(adapterSourceSha256=p['nativeExec']['adapterSourceSha256'],shimSourceSha256=p['nativeExec']['sourceSha256'],
        shimSha256=p['nativeExec']['binarySha256'],executableSha256=p['listenerEvidence']['executableSha256'],
        parserSourceSha256=p['listenerEvidence']['moduleSha256'],callerSourceSha256=guard._file_sha(P/'mac_process_guard_v3.py'))
    rows=[json.loads(line) for line in raw.splitlines()]
    parent=copy.deepcopy(rows[0]['writer'])
    for phase,base,pid,lid in [('before',100.14,601,'e'*32),('after',100.74,602,'f'*32)]:
        t,_,_,_=pure.fixture(b'p11\nf17\nPTCP\ntIPv4\nn127.0.0.1:11434\nTST=LISTEN\n')
        t['sourcePins']=copy.deepcopy(pins)
        t['startedMonotonic']=base
        t['runCompletedMonotonic']=base+.03
        t['parseCompletedMonotonic']=base+.04
        n=t['nativeLaunch'];n.update(leaseId=lid,stageId='observer-listener',
            identity=dict(pid=pid,createTimeMicros=pid*1000000,parentPid=20),
            commandSha256=listener.sha256(listener.canonical(listener.ARGV)),
            executableSha256=pins['executableSha256'],shimSha256=pins['shimSha256'],
            adapterSourceSha256=pins['adapterSourceSha256'],shimSourceSha256=pins['shimSourceSha256'],
            readyMonotonic=base+.0055,actualReapedMonotonic=base+.024,waitEventMonotonic=base+.025)
        n['phaseClocks']={k:base+v*.1 for k,v in n['phaseClocks'].items()}
        n['captureLock']['pathSha256']=listener.sha256(p['lifecycle']['coordinationLockPath'].encode())
        for proof in ('sourceProofBefore','sourceProofReady','sourceProofAfter'):
            for name,path,sha in [('adapter',str(P/'native_exec_registry.py'),pins['adapterSourceSha256']),
                ('source',p['nativeExec']['sourcePath'],pins['shimSourceSha256']),
                ('binary',p['nativeExec']['binaryPath'],pins['shimSha256'])]:
                n[proof][name].update(path=path,sha256=sha)
        n['executedShimIdentity']=dict(n['identity'],executable=p['nativeExec']['binaryPath'],argvSha256='3'*64)
        data=dict(leaseId=lid,role='finite',stageId=n['stageId'],identity=copy.deepcopy(n['identity']),
            parentIdentity=copy.deepcopy(parent),commandSha256=n['commandSha256'],executableSha256=n['executableSha256'],
            readyMonotonic=n['readyMonotonic'],shimSha256=n['shimSha256'])
        for name,event_data,mono in [('FINITE_REGISTER',data,base+.01),('RELEASE',dict(leaseId=lid),base+.013),
            ('WAIT',dict(leaseId=lid,identity=copy.deepcopy(n['identity']),exitCode=0,waitSource='Popen.wait',
                         reapedMonotonic=n['actualReapedMonotonic']),n['waitEventMonotonic'])]:
            rows.append(dict(rows[0],event=name,data=event_data,monotonicSeconds=mono))
        o['evidence'][phase]['listener']=dict(state='OBSERVED',records=listener.parse_global_stdout(
            base64.b64decode(t['stdout']['dataBase64'])),transcript=t)
    rows=rehash(sorted(rows,key=lambda e:e['monotonicSeconds']));raw=raw_events(rows);state=life.replay_journal(raw)
    for phase in ('before','after'):
        n=o['evidence'][phase]['listener']['transcript']['nativeLaunch']
        n['waitSequence']=state['leases'][n['leaseId']]['waitSeq']
    view=o['lifecycle'];refs={tuple(v) for v in view['referencedIdentities']}
    view.update(journalBytes=len(raw),journalSha256=life.digest(raw),lastSequence=len(rows),
        leases=[v for v in state['leases'].values() if v['absence'] is None or life.identity_key(v['identity']) in refs])
    a,b,record=owned.bootstrap_pair(view,raw)
    writer=dict(path=str(life.BASE/'.runtime/posix/tmp/FIXTURE_ONLY/initialization.json'),sha256='a'*64,
        startedMonotonic=1.,completedMonotonic=1.0001)
    a.bind_preparation(record,writer);b.bind_preparation(record,writer)
    o.update(onlineReplayMode=owned.MODE,onlineReplayInitializationMode=owned.INITIALIZATION_MODE,
        onlineReplaySourceSha256=p['onlineReplaySourceSha256'],onlineReplayPreparation=a.preparation_reference(),
        binaryAuthenticationMode=p['binaryAuthenticationMode'],binaryAuthenticationModuleSha256=p['binaryAuthenticationSourceSha256'],
        binaryAuthenticationWork={'fullReads':1},policyCanonicalSha256=guard.canonical_sha256(p))
    return p,o,raw,a,b


class FakeProcess:
    def __init__(self,out=b'',err=b'',error=None,poll_error=None,kill_error=None,wait_error=None):
        self.out,self.err,self.error=out,err,error
        self.poll_error,self.kill_error,self.wait_error=poll_error,kill_error,wait_error
        self.returncode=0;self.calls=[]
    def communicate(self,timeout):
        self.calls.append(('communicate',timeout))
        if self.error:raise self.error
        return self.out,self.err
    def poll(self):
        self.calls.append(('poll',))
        if self.poll_error:raise self.poll_error
        return None
    def kill(self):
        self.calls.append(('kill',))
        if self.kill_error:raise self.kill_error
    def wait(self,timeout):
        self.calls.append(('wait',timeout))
        if self.wait_error:raise self.wait_error
        self.returncode=-9;return -9


class FakeRegistry:
    def __init__(self,process):self.process=process;self.calls=[]
    def launch(self,argv,**kwargs):
        self.calls.append((list(argv),kwargs));return self.process


class NativeIntegrationTests(unittest.TestCase):
    def capture(self,process,*,evidence_error=None,clock=None):
        p,_,_,_,_=make_fixture();reg=FakeRegistry(process)
        n=SimpleNamespace(NativeExecRegistry=FakeRegistry,
            evidence_for_handle=lambda handle: (_ for _ in ()).throw(evidence_error) if evidence_error else {'fixtureOnly':True})
        patches=[patch.object(guard,'_native_exec_module',return_value=n),patch.object(guard,'_native_listener_module',return_value=listener)]
        if clock:patches.append(patch.object(guard.time,'monotonic',side_effect=clock))
        from contextlib import ExitStack
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            t=guard._read_native_listener(p,reg)
        return t,reg

    def decisions(self,values):
        p,o,raw,a,b=values
        cold=guard.validate_observation(p,o,raw)
        warm=guard.validate_observation(p,o,raw,lifecycle_cursor=a)
        second=guard.validate_observation(p,o,raw,lifecycle_cursor=b)
        return cold,warm,second

    def test_01_cold_and_both_private_owners_actually_invoke_native_witness(self):
        values=make_fixture()
        with patch.object(listener,'verify_transcript',wraps=listener.verify_transcript) as verify:
            decisions=self.decisions(values)
        self.assertEqual([x['status'] for x in decisions],['PASS']*3,decisions)
        self.assertEqual(verify.call_count,6)
        self.assertEqual(decisions[0],decisions[1]);self.assertEqual(decisions[1],decisions[2])

    def test_02_actual_full_core_and_current_predicate_AST(self):
        source=(P/'mac_process_guard_v3.py').read_bytes();node=next(n for n in ast.parse(source).body
            if isinstance(n,ast.FunctionDef) and n.name=='_guard_decision_from_validated_lifecycle')
        tr=next(n for n in node.body if isinstance(n,ast.Try))
        self.assertEqual(hashlib.sha256(ast.dump(ast.Module(body=tr.body[3:],type_ignores=[]),include_attributes=False).encode()).hexdigest(),
            'b6bc9b54ba40d04503cbee3ad71ddfe64acdd6724abf47f8f01c50693b49c30b')
        self.assertEqual(hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest(),owned.GUARD_PREDICATE_AST_SHA256)

    def test_03_deadline_epsilon_never_passes_cold_or_warm(self):
        values=make_fixture();frame=values[1]['evidence']['before'];frame['listenerReadClock']['finishedMonotonic']=100.64000000000001
        for d in self.decisions(values):self.assertNotEqual(d['status'],'PASS',d)

    def test_04_raw_hash_change_never_passes_cold_or_warm(self):
        values=make_fixture();values[1]['evidence']['before']['listener']['transcript']['stdout']['capturedSha256']='0'*64
        for d in self.decisions(values):self.assertNotEqual(d['status'],'PASS',d)

    def test_05_native_lease_change_never_passes_cold_or_warm(self):
        values=make_fixture();values[1]['evidence']['before']['listener']['transcript']['nativeLaunch']['leaseId']='0'*32
        for d in self.decisions(values):self.assertNotEqual(d['status'],'PASS',d)

    def test_06_native_source_change_never_passes_cold_or_warm(self):
        values=make_fixture();values[1]['evidence']['before']['listener']['transcript']['sourcePins']['callerSourceSha256']='0'*64
        for d in self.decisions(values):self.assertNotEqual(d['status'],'PASS',d)

    def test_07_coarse_legacy_listener_cannot_satisfy_native(self):
        values=make_fixture();values[1]['evidence']['before']['listener'].pop('transcript')
        for d in self.decisions(values):self.assertNotEqual(d['status'],'PASS',d)

    def test_08_derived_records_cannot_hide_other_visible_listener(self):
        values=make_fixture();values[1]['evidence']['before']['listener']['records'].append(dict(pid=99))
        for d in self.decisions(values):self.assertNotEqual(d['status'],'PASS',d)

    def test_09_wrong_native_flag_rejected(self):
        p,*_=make_fixture();p['lifecycleExecMode']='unknown'
        with self.assertRaises(ValueError):guard.validate_policy(p)

    def test_10_no_owned_mode_rejected(self):
        p,*_=make_fixture();p['onlineReplayMode']='incremental-exact-prefix-v1'
        with self.assertRaises(ValueError):guard.validate_policy(p)

    def test_11_native_fields_without_flag_rejected(self):
        p,*_=make_fixture();p.pop('lifecycleExecMode')
        with self.assertRaises(ValueError):guard.validate_policy(p)
        with self.assertRaises(ValueError):runtime.lifecycle_observer_sources(p)

    def test_12_native_sources_closed_deduplicated(self):
        p,*_=make_fixture();sources=runtime.lifecycle_observer_sources(p)
        self.assertEqual(len(sources),len(set(sources)))
        self.assertTrue({'experiments/ch7/native_exec_registry.py','experiments/ch7/lifecycle_exec_native.c',
                         'experiments/ch7/listener_evidence.py'}<=set(sources))

    def test_13_no_actual_binary_needed_for_cold_policy_check(self):
        p,*_=make_fixture()
        with patch.object(native,'_authenticated_file',side_effect=AssertionError('must not authenticate binary in pure cold policy')):
            guard.validate_policy(p)

    def test_14_wrapper_preserves_exact_full_global_command_and_handle(self):
        process=FakeProcess(b'p11\nf17\nPTCP\ntIPv4\nn127.0.0.1:11434\nTST=LISTEN\n')
        t,reg=self.capture(process)
        self.assertEqual(reg.calls[0][0],listener.ARGV)
        self.assertEqual(base64.b64decode(t['stdout']['dataBase64']),process.out)
        self.assertFalse(t['stdout']['truncated']);self.assertEqual(t['returnCode'],0)

    def test_15_timeout_retains_partial_and_unknown_total(self):
        error=subprocess.TimeoutExpired(listener.ARGV,.1,output=b'partial stdout',stderr=b'partial stderr')
        process=FakeProcess(error=error);t,_=self.capture(process)
        self.assertEqual(t['exception']['class'],'TimeoutExpired')
        self.assertEqual(base64.b64decode(t['stdout']['dataBase64']),b'partial stdout')
        for key in ('stdout','stderr'):
            self.assertTrue(t[key]['truncated']);self.assertIsNone(t[key]['totalBytes']);self.assertIsNone(t[key]['totalSha256'])

    def test_16_timeout_and_poll_cleanup_and_evidence_errors_all_retained(self):
        error=subprocess.TimeoutExpired(listener.ARGV,.1,output=b'partial',stderr=b'warning')
        process=FakeProcess(error=error,poll_error=PermissionError('fixture poll'),wait_error=RuntimeError('fixture wait'))
        t,_=self.capture(process,evidence_error=LookupError('fixture evidence'))
        self.assertEqual(t['exception']['class'],'TimeoutExpired')
        self.assertTrue(all(name in t['exception']['message'] for name in ('PermissionError','RuntimeError','LookupError')))
        self.assertEqual(base64.b64decode(t['stdout']['dataBase64']),b'partial')
        self.assertIsNone(t['returnCode'])

    def test_17_kill_failure_preserves_capture_exception(self):
        process=FakeProcess(error=ValueError('fixture read'),kill_error=PermissionError('fixture kill'))
        t,_=self.capture(process)
        self.assertEqual(t['exception']['class'],'ValueError');self.assertIn('PermissionError',t['exception']['message'])

    def test_18_forensic_large_complete_is_prefix_with_known_total_only(self):
        raw=b'x'*(listener.MAX_FORENSIC+1);t,_=self.capture(FakeProcess(out=raw))
        self.assertEqual(t['stdout']['capturedBytes'],listener.MAX_FORENSIC)
        self.assertEqual(t['stdout']['totalBytes'],len(raw));self.assertIsNone(t['stdout']['totalSha256'])
        self.assertTrue(t['stdout']['truncated'])

    def test_19_complete_stderr_retained_at_exit_zero(self):
        t,_=self.capture(FakeProcess(err=b'warning'))
        outer=dict(startedMonotonic=t['startedMonotonic'],finishedMonotonic=t['parseCompletedMonotonic'])
        self.assertIn('STDERR_NOT_EMPTY',listener.derive_outcome(t,outer)['reasons'])

    def test_20_expired_source_check_does_not_launch(self):
        process=FakeProcess();t,reg=self.capture(process,clock=[0.,.5000001,.5000002,.5000003])
        self.assertEqual(reg.calls,[]);self.assertEqual(t['exception']['class'],'TimeoutError')
        self.assertTrue(t['stdout']['truncated'])

    def test_21_prefix_or_and_cleanup_failure_still_unknown(self):
        error=subprocess.TimeoutExpired(listener.ARGV,.1,output=b'x'*65537,stderr=b'warning')
        t,_=self.capture(FakeProcess(error=error,wait_error=RuntimeError('no actual wait')))
        outer=dict(startedMonotonic=t['startedMonotonic'],finishedMonotonic=t['parseCompletedMonotonic'])
        outcome=listener.derive_outcome(t,outer)
        self.assertEqual(outcome['state'],'UNKNOWN')
        self.assertTrue({'RETURN_CODE_MISSING_OR_INVALID','STDOUT_TRUNCATED','STDOUT_ACCEPTANCE_CAP',
                         'STDERR_TRUNCATED','STDERR_NOT_EMPTY','CAPTURE_EXCEPTION_TimeoutExpired'}<=set(outcome['reasons']))

    def test_22_native_flags_on_unknown_replay_not_accepted_by_sourceclosure(self):
        p,*_=make_fixture();p['onlineReplayMode']='future'
        with self.assertRaises(ValueError):runtime.lifecycle_observer_sources(p)


if __name__=='__main__':unittest.main(verbosity=2)
