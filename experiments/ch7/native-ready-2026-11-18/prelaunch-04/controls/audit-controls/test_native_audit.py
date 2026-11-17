"""Portable native-audit fixtures; no live capture, executable or Git command."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import integration_fixtures as f
sys.path.insert(0,str(f.P))
import audit_nested_load as audit
import lifecycle_audit as oracle


def contract_fixture():
    policy=f.make_fixture()[0]
    source={str(p.relative_to(f.REPO)):audit.file_sha(p) for p in (f.REPO/'experiments/ch7').iterdir()
            if p.is_file() and p.suffix in ('.py','.c')}
    observer={name:source[name] for name in f.runtime.lifecycle_observer_sources(policy)}
    passport=dict(lifecycleExecMode=f.native.MODE,nativeExec=copy.deepcopy(policy['nativeExec']),
        listenerEvidence=copy.deepcopy(policy['listenerEvidence']),sourceFiles=source,observerSources=observer,
        toolExecutableSha256=dict(lsof=policy['listenerEvidence']['executableSha256'],git='7'*64))
    return policy,passport


def context(policy,passport):
    return audit.verify_native_contract(passport,policy,f.REPO,guard=f.guard,runtime=f.runtime,
                                        native=f.native,listener=f.listener)


def proof_fixture(count=1):
    p,passport=contract_fixture();ctx=context(p,passport)
    _,observation,raw,_,_=f.make_fixture()
    original=[json.loads(line) for line in raw.splitlines()]
    rows=copy.deepcopy(original[:2]);owner=copy.deepcopy(rows[0]['writer']);records=[]
    command=['git','show','2'*40+':README.md']
    expected=[dict(arguments=['show','{SOURCE}:README.md'],stdoutSha256='0'*64)]*30
    for i in range(count):
        base=3.+i
        n=copy.deepcopy(observation['evidence']['before']['listener']['transcript']['nativeLaunch'])
        prior=observation['evidence']['before']['listener']['transcript']['startedMonotonic']
        n.update(leaseId=('%032x'%(0x700+i)),stageId='nested-load-sequence',
            identity=dict(pid=700+i,createTimeMicros=(700+i)*1000000,parentPid=20),
            commandSha256=audit.sha(audit.canonical(command)),executableSha256=passport['toolExecutableSha256']['git'],
            readyMonotonic=base+.0055,actualReapedMonotonic=base+.024,waitEventMonotonic=base+.025)
        n['phaseClocks']={k:base+(v-prior) for k,v in n['phaseClocks'].items()}
        n['executedShimIdentity']=dict(n['identity'],executable=p['nativeExec']['binaryPath'],argvSha256='3'*64)
        lockid=dict(device=1,inode=77,regular=True,singleLink=True,ownedByCurrentUser=True)
        n['captureLock']=dict(schema='aijade.lifecycle.capture-lock.v1',pathSha256=audit.sha(
            p['lifecycle']['coordinationLockPath'].encode()),maxWaitSeconds=1.25,state='HELD_AND_RELEASED',
            waitSeconds=.001,acquiredMonotonic=base+.0025,releasedMonotonic=base+.0165,nested=False,
            initialIdentity=lockid,finalIdentity=copy.deepcopy(lockid))
        data={k:copy.deepcopy(n[k]) for k in ('leaseId','stageId','role','identity','commandSha256','executableSha256','shimSha256','readyMonotonic')}
        data.update(parentIdentity=copy.deepcopy(owner),identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD')
        for name,body,mono in [('FINITE_REGISTER',data,base+.01),('RELEASE',dict(leaseId=n['leaseId']),base+.013),
            ('WAIT',dict(leaseId=n['leaseId'],identity=copy.deepcopy(n['identity']),exitCode=0,
                waitSource='Popen.wait',reapedMonotonic=n['actualReapedMonotonic']),n['waitEventMonotonic'])]:
            rows.append(dict(rows[0],event=name,data=body,monotonicSeconds=mono))
        record=dict(index=i,padding=False,command=list(command),startedMonotonic=base,completedMonotonic=base+.03,
            status='COMPLETE',stdoutSha256='0'*64,exitCode=0)
        if i==0:
            record.update(firstNativeProofLaunchEvidence=n,firstNativeProofEvidenceCompletedMonotonic=base+.04)
        records.append(record)
    rows=f.rehash(rows);raw=f.raw_events(rows)
    state=oracle._replay(raw,'2'*40,'3'*64)
    first=records[0]['firstNativeProofLaunchEvidence'];lease=state['leases'][first['leaseId']]
    first['waitSequence']=lease['waitSeq']
    return dict(policy=p,passport=passport,context=ctx,records=records,state=state,raw=raw,owner=owner,
        lease=lease,expected=expected,boundary=10.)


class NativeAuditControls(unittest.TestCase):
    def proof(self,b):
        return audit.verify_first_native_proof(b['records'][0],b['lease'],b['state'],b['owner'],b['context'],b['boundary'])

    def test_01_actual_source_policy_passport_and21closure(self):
        p,passport=contract_fixture();self.assertEqual(context(p,passport)['observerSourceCount'],21)

    def test_02_passport_native_mode_mismatch(self):
        p,passport=contract_fixture();passport['lifecycleExecMode']='old'
        with self.assertRaises(ValueError):context(p,passport)

    def test_03_listener_passport_command_mismatch(self):
        p,passport=contract_fixture();passport['listenerEvidence']['command'].append('-p11')
        with self.assertRaises(ValueError):context(p,passport)

    def test_04_native_passport_source_mismatch(self):
        p,passport=contract_fixture();passport['nativeExec']['sourceSha256']='0'*64
        with self.assertRaises(ValueError):context(p,passport)

    def test_05_current_source_map_cannot_be_forged(self):
        p,passport=contract_fixture();passport['sourceFiles']['experiments/ch7/native_exec_registry.py']='0'*64
        with self.assertRaises(ValueError):context(p,passport)

    def test_06_missing_observer_dependency(self):
        p,passport=contract_fixture();passport['observerSources'].pop('experiments/ch7/listener_evidence.py')
        with self.assertRaises(ValueError):context(p,passport)

    def test_07_extra_observer_dependency(self):
        p,passport=contract_fixture();passport['observerSources']['extra.py']='0'*64
        with self.assertRaises(ValueError):context(p,passport)

    def test_08_lsof_executable_passport_mismatch(self):
        p,passport=contract_fixture();passport['toolExecutableSha256']['lsof']='0'*64
        with self.assertRaises(ValueError):context(p,passport)

    def test_09_contract_does_not_construct_or_authenticate_native_binary(self):
        p,passport=contract_fixture()
        with patch.object(f.native.NativeExecRegistry,'__init__',side_effect=AssertionError('no actual Registry')), \
             patch.object(f.native,'_authenticated_file',side_effect=AssertionError('no actual binary')):
            context(p,passport)

    def test_10_first_git_proof_independent_original_ffbf_state(self):
        b=proof_fixture();result=self.proof(b)
        self.assertEqual(result['leaseId'],b['lease']['leaseId'])
        self.assertEqual(audit.verify_native_final_leases(b['state'],b['context']),1)

    def test_11_bool_wait_cannot_mean_zero(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['exitCode']=False
        with self.assertRaises(ValueError):self.proof(b)

    def test_12_wrong_original_lease(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['leaseId']='0'*32
        with self.assertRaises(ValueError):self.proof(b)

    def test_13_another_parent_controller(self):
        b=proof_fixture();b['owner']=dict(pid=999,createTimeMicros=999000000,parentPid=1)
        with self.assertRaises(ValueError):self.proof(b)

    def test_14_future_wait_after_command_completion(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['waitEventMonotonic']=3.031
        with self.assertRaises(ValueError):self.proof(b)

    def test_15_stable_source_generation_replaced(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['sourceProofAfter']['binary']['inode']+=1
        with self.assertRaises(ValueError):self.proof(b)

    def test_16_actual_gated_birth_mismatch(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['executedShimIdentity']['createTimeMicros']+=1
        with self.assertRaises(ValueError):self.proof(b)

    def test_17_first_git_capture_path_mismatch(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['captureLock']['pathSha256']='0'*64
        with self.assertRaises(ValueError):self.proof(b)

    def test_18_first_git_capture_nested_substitution(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['captureLock']['nested']=True
        with self.assertRaises(ValueError):self.proof(b)

    def test_19_bool_phase_clock(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['phaseClocks']['requestStartedMonotonic']=True
        with self.assertRaises(ValueError):self.proof(b)

    def test_20_missing_actual_wait_sequence(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['waitSequence']=None
        with self.assertRaises(ValueError):self.proof(b)

    def test_21_first_proof_missing_diagnostic(self):
        b=proof_fixture();b['records'][0].pop('firstNativeProofLaunchEvidence')
        with self.assertRaises((ValueError,KeyError)):
            audit.verify_command_records(b['records'],b['expected'],'2'*40,1,False,b['owner'],b['state'],10.,native_context=b['context'])

    def test_22_second_command_may_not_borrow_diagnostic(self):
        b=proof_fixture(2);b['records'][1]['firstNativeProofLaunchEvidence']=copy.deepcopy(b['records'][0]['firstNativeProofLaunchEvidence'])
        with self.assertRaisesRegex(ValueError,'extra native diagnostic'):
            audit.verify_command_records(b['records'],b['expected'],'2'*40,2,False,b['owner'],b['state'],10.,native_context=b['context'])

    def test_23_first_proof_diagnostic_inside_original_deadline(self):
        b=proof_fixture();b['records'][0]['firstNativeProofEvidenceCompletedMonotonic']=10.0001
        with self.assertRaises(ValueError):self.proof(b)

    def test_24_all_finite_shims_match_frozen_native_binary(self):
        b=proof_fixture();rows=[json.loads(x) for x in b['raw'].splitlines()]
        rows[2]['data']['shimSha256']='0'*64
        coherent=f.raw_events(f.rehash(rows));state=oracle._replay(coherent,'2'*40,'3'*64)
        with self.assertRaisesRegex(ValueError,'frozen native shim'):audit.verify_native_final_leases(state,b['context'])

    def test_25_first_proof_bad_source_kind(self):
        b=proof_fixture();b['records'][0]['firstNativeProofLaunchEvidence']['sourceProofBefore']['source']['mode']=600.0
        with self.assertRaises(ValueError):self.proof(b)

    def test_26_actual_native_predicate_and_original_core(self):
        result=audit.verify_guard_predicate_source(f.guard.__file__)
        self.assertEqual(result['predicateAstSha256'],'abc29b40650ffecaacfb3d601c2736504a06c491a1494329d494d9cdb50bb6bb')
        self.assertEqual(result['originalCoreAstSha256'],'b6bc9b54ba40d04503cbee3ad71ddfe64acdd6724abf47f8f01c50693b49c30b')

    def test_27_native_command_source_records_have_one_exact_diagnostic(self):
        b=proof_fixture(2)
        result=audit.verify_command_records(b['records'],b['expected'],'2'*40,2,False,b['owner'],b['state'],10.,native_context=b['context'])
        self.assertEqual(len(result),1)

    def test_28_legacy_command_control_still_requires_no_new_fields(self):
        b=proof_fixture();b['records'][0].pop('firstNativeProofLaunchEvidence');b['records'][0].pop('firstNativeProofEvidenceCompletedMonotonic')
        self.assertIsNone(audit.verify_command_records(b['records'],b['expected'],'2'*40,1,False,b['owner'],b['state'],10.))

    def test_29_init_counts_remain_one_parse_one_clone(self):
        inner,outer=audit.expected_initial_statistics(100,2,5,1,dict(ownerId='1'*32),dict(ownerId='2'*32))
        self.assertEqual(inner['initializationStateClones'],0);self.assertEqual(outer['initializationStateClones'],1)
        self.assertEqual(inner['calls'],1);self.assertEqual(outer['calls'],0)
        self.assertEqual(inner['privateStateValidations'],1);self.assertEqual(outer['privateStateValidations'],0)

    def test_30_immutable_original_oracle_and_parser(self):
        self.assertEqual(audit.file_sha(oracle.__file__),audit.ORACLE_SHA)
        self.assertEqual(audit.file_sha(f.life.__file__),audit.PARSER_SHA)


if __name__=='__main__':unittest.main(verbosity=2)
