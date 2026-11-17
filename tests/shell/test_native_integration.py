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
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
REPO=Path(os.environ.get('AIJADE_NATIVE_INTEGRATION_REPO',str(Path(__file__).resolve().parents[2]))).resolve()
P=REPO/'experiments/ch7'
SCRATCH=Path(os.environ.get('AIJADE_NATIVE_INTEGRATION_SCRATCH',str(REPO/'.runtime/native-integration-controls')))
SCRATCH.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(P),str(REPO/'tests/shell')]
import process_lifecycle as life
import mac_process_guard_v3 as guard
import listener_evidence as listener
import native_exec_registry as native
import newowned_guard_cursor as owned
import finite_runtime as runtime
import run_nested_load as runner
import pure_listener_fixtures as pure
from verify_frozen_listener_oracle import verify_frozen_oracle
verify_frozen_oracle(REPO)
from test_segmented_capture import segmented_fixture
from test_mac_lifecycle_guard import rehash,raw_events


def make_fixture(*,logical_repo=None,sibling_phase=None):
    logical_p=life.BASE/'.runtime/posix/NATIVE_TEST_ORIGIN/experiments/ch7' if logical_repo is None else Path(logical_repo)
    p,o,raw=segmented_fixture()
    p.update(onlineReplayMode=owned.MODE,onlineReplayInitializationMode=owned.INITIALIZATION_MODE,
        onlineReplaySourceSha256=guard._file_sha(P/'newowned_guard_cursor.py'),
        binaryAuthenticationMode='full-read-exact-bytes-v1',
        binaryAuthenticationSourceSha256=guard._file_sha(P/'binary_authentication.py'),
        lifecycleExecMode='native-ready-release-v1',nativeExec=dict(mode='native-ready-release-v1',
            adapterSourceSha256=guard._file_sha(P/'native_exec_registry.py'),
            sourcePath=str(logical_p/'lifecycle_exec_native.c'),sourceSha256=guard._file_sha(P/'lifecycle_exec_native.c'),
            binaryPath=str(life.BASE/'.runtime/posix/tmp/FIXTURE_ONLY_NEVER_EXECUTED_NATIVE'),binarySha256='e'*64),
        listenerEvidence=dict(mode=listener.MODE,moduleSha256=guard._file_sha(P/'listener_evidence.py'),
            command=list(listener.ARGV),executableSha256='f'*64,maxSeconds=.5,maxBytes=65536))
    p['lifecycle']['execShimSha256']=p['nativeExec']['binarySha256']
    pins=dict(adapterSourceSha256=p['nativeExec']['adapterSourceSha256'],shimSourceSha256=p['nativeExec']['sourceSha256'],
        shimSha256=p['nativeExec']['binarySha256'],executableSha256=p['listenerEvidence']['executableSha256'],
        parserSourceSha256=p['listenerEvidence']['moduleSha256'],callerSourceSha256=guard._file_sha(P/'mac_process_guard_v3.py'))
    rows=[json.loads(line) for line in raw.splitlines()]
    parent=copy.deepcopy(rows[0]['writer'])
    sibling=dict(pid=40,createTimeMicros=40000000,parentPid=1)
    if sibling_phase is not None:
        rows.append(dict(rows[0],event='CONTROLLER_REGISTER',monotonicSeconds=1.5,writer=copy.deepcopy(sibling),
            data=dict(leaseId='9'*32,role='controller',stageId='legitimate-sibling-controller-fixture',
                identity=copy.deepcopy(sibling),parentIdentity=None,commandSha256='9'*64,executableSha256='8'*64,readyMonotonic=1.4)))
    for phase,base,pid,lid in [('before',100.14,601,'e'*32),('after',100.74,602,'f'*32)]:
        actual_parent=sibling if sibling_phase==phase else parent
        t,_,_,_=pure.fixture(b'p11\nf17\nPTCP\ntIPv4\nn127.0.0.1:11434\nTST=LISTEN\n')
        t['sourcePins']=copy.deepcopy(pins)
        t['startedMonotonic']=base
        t['runCompletedMonotonic']=base+.03
        t['parseCompletedMonotonic']=base+.04
        n=t['nativeLaunch'];n.update(leaseId=lid,stageId='observer-listener',
            identity=dict(pid=pid,createTimeMicros=pid*1000000,parentPid=actual_parent['pid']),
            commandSha256=listener.sha256(listener.canonical(listener.ARGV)),
            executableSha256=pins['executableSha256'],shimSha256=pins['shimSha256'],
            adapterSourceSha256=pins['adapterSourceSha256'],shimSourceSha256=pins['shimSourceSha256'],
            readyMonotonic=base+.0055,actualReapedMonotonic=base+.024,waitEventMonotonic=base+.025)
        n['phaseClocks']={k:base+v*.1 for k,v in n['phaseClocks'].items()}
        n['captureLock']['pathSha256']=listener.sha256(p['lifecycle']['coordinationLockPath'].encode())
        for proof in ('sourceProofBefore','sourceProofReady','sourceProofAfter'):
            for name,path,sha in [('adapter',str(logical_p/'native_exec_registry.py'),pins['adapterSourceSha256']),
                ('source',p['nativeExec']['sourcePath'],pins['shimSourceSha256']),
                ('binary',p['nativeExec']['binaryPath'],pins['shimSha256'])]:
                n[proof][name].update(path=path,sha256=sha)
        n['executedShimIdentity']=dict(n['identity'],executable=p['nativeExec']['binaryPath'],argvSha256='3'*64)
        data=dict(leaseId=lid,role='finite',stageId=n['stageId'],identity=copy.deepcopy(n['identity']),
            parentIdentity=copy.deepcopy(actual_parent),commandSha256=n['commandSha256'],executableSha256=n['executableSha256'],
            readyMonotonic=n['readyMonotonic'],shimSha256=n['shimSha256'])
        for name,event_data,mono in [('FINITE_REGISTER',data,base+.01),('RELEASE',dict(leaseId=lid),base+.013),
            ('WAIT',dict(leaseId=lid,identity=copy.deepcopy(n['identity']),exitCode=0,waitSource='Popen.wait',
                         reapedMonotonic=n['actualReapedMonotonic']),n['waitEventMonotonic'])]:
            rows.append(dict(rows[0],event=name,data=event_data,monotonicSeconds=mono,writer=copy.deepcopy(actual_parent)))
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
    now=time.monotonic()
    writer=dict(path=str(life.BASE/'.runtime/posix/tmp/FIXTURE_ONLY/initialization.json'),sha256='a'*64,
        startedMonotonic=now,completedMonotonic=now+.0001)
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

    def factory_case(self,native_mode,inherited):
        import psutil
        p=make_fixture()[0] if native_mode else segmented_fixture()[0]
        label=('native' if native_mode else 'legacy')+('-env' if inherited else '-fresh')
        folder=SCRATCH/('factory-fixture-'+label);folder.mkdir(exist_ok=True)
        path=folder/'policy.json';raw=(json.dumps(p,sort_keys=True)+'\n').encode();path.write_bytes(raw)
        class Registry:
            source_commit='2'*40
            policy_sha256=hashlib.sha256(raw).hexdigest()
            activated=0
            def activate(self):self.activated+=1;return self
        registry=Registry()
        args=SimpleNamespace(execution_plan=SimpleNamespace(name=runtime.MAC_LIFECYCLE_PLAN),
            process_policy=path,output=folder/'output.json')
        env=dict(AIJADE_GIT_COMMIT='2'*40)
        if inherited:env['AIJADE_LIFECYCLE_JOURNAL']=str(folder/'inherited.jsonl')
        with patch.dict(os.environ,env,clear=True),patch.object(runtime.os,'getpid',return_value=20),patch.object(psutil,'Process',return_value=SimpleNamespace(create_time=lambda:20.)), \
             patch.object(life,'Registry',return_value=registry) as old_fresh, \
             patch.object(life,'from_environment',return_value=registry) as old_env, \
             patch.object(native,'registry_for_policy',return_value=registry) as new_fresh, \
             patch.object(native,'activate_from_environment',return_value=registry) as new_env:
            result=runtime.setup_lifecycle(args,'fixture-stage')
        self.assertIs(result,registry);self.assertEqual(registry.activated,1)
        counts=[old_fresh.call_count,old_env.call_count,new_fresh.call_count,new_env.call_count]
        expected=[0,0,0,0];expected[(2 if native_mode else 0)+(1 if inherited else 0)]=1
        self.assertEqual(counts,expected)

    def test_23_legacy_fresh_factory_preserved(self):self.factory_case(False,False)
    def test_24_legacy_inherited_factory_preserved(self):self.factory_case(False,True)
    def test_25_native_fresh_factory_selected(self):self.factory_case(True,False)
    def test_26_native_inherited_factory_selected(self):self.factory_case(True,True)

    def snapshot_case(self,finished):
        t,_,_,_=pure.fixture();t['startedMonotonic']=0.;t['runCompletedMonotonic']=.3;t['parseCompletedMonotonic']=.4
        graph=dict(nodes=[],errors=[{'code':'MOCK_GRAPH_NO_OS_QUERY'}])
        daemon=dict(daemon={},errors=[],daemonIdentityReadClock=dict(startedMonotonic=0.,finishedMonotonic=0.))
        ticks=[0.,0.,0.,0.,0.,.49,finished]
        with patch.object(guard,'_read_processes',return_value=graph),patch.object(guard,'_read_native_listener',return_value=t), \
             patch.object(guard,'_native_listener_module',return_value=listener),patch.object(guard.time,'monotonic',side_effect=ticks):
            return guard._snapshot({'lifecycleExecMode':native.MODE},[],object(),daemon_sample=daemon)

    def test_27_snapshot_final_whole_clock_exact_half_second(self):
        frame=self.snapshot_case(.5)
        self.assertEqual(frame['listener']['state'],'OBSERVED',frame['listener'])
        self.assertEqual(frame['listenerReadClock']['finishedMonotonic'],.5)

    def test_28_snapshot_final_whole_clock_includes_parse_cost(self):
        frame=self.snapshot_case(.5000000000000001)
        self.assertEqual(frame['listener']['state'],'UNKNOWN')
        self.assertIn('WHOLE_CALL_DEADLINE_EXCEEDED',frame['listener']['reasons'])

    def test_29_scientific_loader_still_refuses_owned_native_on_legacy_plan(self):
        p,*_=make_fixture();path=SCRATCH/'mock-native-policy.json';raw=json.dumps(p,sort_keys=True).encode();path.write_bytes(raw)
        with patch.object(runtime,'git_bytes',return_value=raw):
            with self.assertRaisesRegex(ValueError,'separately frozen new scientific execution decision'):
                runtime.load_mac_policy(REPO,path,'2'*40)

    def test_30_native_sourceclosure_unknown_flag_refused(self):
        p,*_=make_fixture();p['lifecycleExecMode']='native-future'
        with self.assertRaises(ValueError):runtime.lifecycle_observer_sources(p)

    def proof_fixture(self,*,native_mode=True,wrong_handle=False):
        output=b'FAKE_GIT_SOURCE_BYTES\n';source='2'*40
        passport=dict(sourceCommit=source,preflightCommands=[dict(arguments=['show','{SOURCE}:README.md'],
            stdoutSha256=runner.sha(output))]*30)
        command=['git','show',source+':README.md']
        class Registry:
            stage='fixture-parent-proof'
            def __init__(self):
                self._mutex=threading.RLock();self.calls=[]
                if native_mode:self._native_binding={'mode':native.MODE}
                self.handles=[SimpleNamespace(registry=self,native_launch_evidence=dict(
                    commandSha256=runner.sha(life.canonical(command if not wrong_handle else ['git','OTHER'])),stageId=self.stage))]
            def run(self,actual,**options):
                self.calls.append((actual,options))
                return SimpleNamespace(stdout=output,returncode=0)
        return Registry(),passport,command

    def test_31_first_native_proof_attaches_only_after_complete(self):
        reg,p,command=self.proof_fixture();records=[]
        def evidence(handle):
            self.assertIs(handle,reg.handles[-1]);self.assertEqual(records[0]['status'],'COMPLETE')
            return {'fixtureOnly':True}
        with patch.object(native,'NativeExecRegistry',type(reg)),patch.object(native,'evidence_for_handle',side_effect=evidence) as capture:
            result=runner.commands(reg,p,REPO,2,records=records)
        self.assertEqual(capture.call_count,1);self.assertEqual(len(reg.calls),2)
        self.assertEqual(reg.calls[0][0],command)
        self.assertEqual(result[0]['firstNativeProofLaunchEvidence'],{'fixtureOnly':True})
        self.assertNotIn('firstNativeProofLaunchEvidence',result[1])

    def test_32_padding_has_no_new_native_diagnostic(self):
        reg,p,_=self.proof_fixture()
        with patch.object(native,'NativeExecRegistry',type(reg)),patch.object(native,'evidence_for_handle') as capture:
            result=runner.commands(reg,p,REPO,2,padding=True)
        self.assertEqual(capture.call_count,0)
        self.assertTrue(all('firstNativeProofLaunchEvidence' not in row for row in result))

    def test_33_legacy_proof_has_no_new_native_diagnostic(self):
        reg,p,_=self.proof_fixture(native_mode=False)
        with patch.object(native,'evidence_for_handle') as capture:
            result=runner.commands(reg,p,REPO,1)
        self.assertEqual(capture.call_count,0);self.assertEqual(result[0]['status'],'COMPLETE')

    def test_34_wrong_last_handle_is_refused_never_borrowed(self):
        reg,p,_=self.proof_fixture(wrong_handle=True);records=[]
        with patch.object(native,'NativeExecRegistry',type(reg)),patch.object(native,'evidence_for_handle') as capture:
            with self.assertRaisesRegex(ValueError,'last managed handle does not bind'):
                runner.commands(reg,p,REPO,1,records=records)
        self.assertEqual(capture.call_count,0);self.assertEqual(records[0]['status'],'REFUSED')

    def test_35_diagnostic_cost_stays_inside_original_preparation_deadline(self):
        reg,p,_=self.proof_fixture();records=[]
        with patch.object(native,'NativeExecRegistry',type(reg)),patch.object(native,'evidence_for_handle',return_value={'fixtureOnly':True}), \
             patch.object(runner,'clock',side_effect=[0.,.001,.01,.02,.03,.06,.07]):
            with self.assertRaisesRegex(ValueError,'first native proof evidence exceeded'):
                runner.commands(reg,p,REPO,1,records=records,deadline=.05)
        self.assertEqual(records[0]['status'],'REFUSED')
        self.assertIn('firstNativeProofLaunchEvidence',records[0])

    def test_36_diagnostic_is_per_actual_parent_child_proof_scope(self):
        parent,p,_=self.proof_fixture();child,_,_=self.proof_fixture()
        with patch.object(native,'NativeExecRegistry',type(parent)),patch.object(native,'evidence_for_handle',return_value={'fixtureOnly':True}) as capture:
            runner.commands(parent,p,REPO,1)
        with patch.object(native,'NativeExecRegistry',type(child)),patch.object(native,'evidence_for_handle',return_value={'fixtureOnly':True}) as child_capture:
            runner.commands(child,p,REPO,1)
        self.assertEqual(capture.call_count,1);self.assertEqual(child_capture.call_count,1)

    def test_37_cold_policy_requires_native_C_source_basename(self):
        p,*_=make_fixture();p['nativeExec']['sourcePath']=str(life.BASE/'OTHER/foreign.c')
        with self.assertRaisesRegex(ValueError,'native C source basename differs'):
            guard.validate_policy(p)

    def test_38_exact_historical_runtime_population_and_separate_setup_dispatch(self):
        path=REPO/'tests/shell/test_mac_prefix_decision.py'
        tree=ast.parse(path.read_bytes());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='EngineeringSourceByteControls')
        assignment=next(n for n in cls.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ORIGINAL_RUNTIME_FUNCTIONS' for t in n.targets))
        expected=ast.literal_eval(assignment.value);body=(P/'finite_runtime.py').read_bytes();lines=body.splitlines(keepends=True);actual={}
        def collect(nodes,prefix=''):
            for node in nodes:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    start=min([node.lineno]+[d.lineno for d in node.decorator_list])-1
                    actual[prefix+node.name]=hashlib.sha256(b''.join(lines[start:node.end_lineno])).hexdigest()
                elif isinstance(node,ast.ClassDef):collect(node.body,prefix+node.name+'.')
        collect(ast.parse(body).body)
        self.assertEqual(len(expected),34);self.assertNotIn('setup_lifecycle',expected)
        self.assertEqual([name for name,sha in expected.items() if actual.get(name)!=sha],['online_lifecycle_cursors'])

    def test_39_relocated_cold_and_warm_read_original_logical_paths_without_rewrite(self):
        logical=life.BASE/'.runtime/posix/ARCHIVED_ORIGIN_ONLY/experiments/ch7'
        values=make_fixture(logical_repo=logical)
        original_policy=life.canonical(values[0]);original_observation=life.canonical(values[1]);raw=values[2]
        self.assertNotEqual(values[0]['nativeExec']['sourcePath'],str(P/'lifecycle_exec_native.c'))
        for result in self.decisions(values):self.assertEqual(result['status'],'PASS',result)
        self.assertEqual(life.canonical(values[0]),original_policy)
        self.assertEqual(life.canonical(values[1]),original_observation);self.assertEqual(values[2],raw)

    def assert_formal_refusal(self,values,code):
        for decision in self.decisions(values):
            self.assertNotEqual(decision['status'],'PASS',decision)
            self.assertIn(code,[row['code'] for row in decision['blockers']],decision)

    def test_40_formal_native_shared_path_must_match_current_outer_lock(self):
        for phase in ('before','after'):
            with self.subTest(phase=phase):
                values=make_fixture();values[1]['evidence'][phase]['listener']['transcript']['nativeLaunch']['captureLock']['pathSha256']='0'*64
                self.assert_formal_refusal(values,'NATIVE_LISTENER_SHARED_LOCK_BINDING_MISMATCH')

    def test_41_valid_standalone_nonnested_proof_cannot_replace_formal_nested_lock(self):
        values=make_fixture();frame=values[1]['evidence']['before'];t=frame['listener']['transcript'];n=t['nativeLaunch'];base=t['startedMonotonic']
        ident=dict(device=1,inode=77,regular=True,singleLink=True,ownedByCurrentUser=True)
        n['captureLock']=dict(schema='aijade.lifecycle.capture-lock.v1',pathSha256=listener.sha256(
            values[0]['lifecycle']['coordinationLockPath'].encode()),maxWaitSeconds=1.25,state='HELD_AND_RELEASED',
            waitSeconds=.001,acquiredMonotonic=base+.0025,releasedMonotonic=base+.0165,nested=False,
            initialIdentity=ident,finalIdentity=copy.deepcopy(ident))
        raw_result=listener.verify_transcript(t,life.replay_journal(values[2]),values[0],
            parser_source_sha256=values[0]['listenerEvidence']['moduleSha256'],caller_source_sha256=guard._file_sha(P/'mac_process_guard_v3.py'),outer_clock=frame['listenerReadClock'])
        self.assertEqual(raw_result['state'],'OBSERVED',raw_result)
        self.assert_formal_refusal(values,'NATIVE_LISTENER_SHARED_LOCK_BINDING_MISMATCH')

    def test_42_native_request_must_be_within_current_outer_hold(self):
        values=make_fixture();values[1]['coordinationLocks']['before']['acquiredMonotonic']=100.145
        self.assert_formal_refusal(values,'NATIVE_LISTENER_SHARED_LOCK_BINDING_MISMATCH')

    def test_43_malformed_bool_phase_clock_remains_unknown(self):
        values=make_fixture();values[1]['evidence']['before']['listener']['transcript']['nativeLaunch']['phaseClocks']['requestStartedMonotonic']=True
        for decision in self.decisions(values):
            self.assertEqual(decision['status'],'UNKNOWN',decision)
            self.assertIn('NATIVE_LISTENER_SHARED_LOCK_EVIDENCE_UNKNOWN',[row['code'] for row in decision['blockers']])

    def test_44_coherent_sibling_controller_listener_lease_cannot_be_borrowed(self):
        for phase in ('before','after'):
            with self.subTest(phase=phase):
                values=make_fixture(sibling_phase=phase);frame=values[1]['evidence'][phase];t=frame['listener']['transcript']
                independent=listener.verify_transcript(t,life.replay_journal(values[2]),values[0],
                    parser_source_sha256=values[0]['listenerEvidence']['moduleSha256'],caller_source_sha256=guard._file_sha(P/'mac_process_guard_v3.py'),outer_clock=frame['listenerReadClock'])
                self.assertEqual(independent['state'],'OBSERVED',independent)
                self.assert_formal_refusal(values,'NATIVE_LISTENER_CONTROLLER_OWNER_MISMATCH')

    def test_45_native_return_must_precede_outer_unlock(self):
        values=make_fixture();values[1]['coordinationLocks']['after']['releasedMonotonic']=100.755
        self.assert_formal_refusal(values,'NATIVE_LISTENER_SHARED_LOCK_BINDING_MISMATCH')


if __name__=='__main__':unittest.main(verbosity=2)
