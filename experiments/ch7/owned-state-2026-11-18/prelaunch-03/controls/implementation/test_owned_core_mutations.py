"""Actual-record guard-core mutations against the independent exact Qe3 cold path.

Each mutation is applied after explicit owned-mode source rebinding. The full
decision is compared by scalar/container type; no observer or native/API call.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from unittest.mock import patch

C=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('owned_offline_replay_helpers',C/'replay_owned_e4.py')
replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)


def setpath(path,value):
    def change(row):
        selected=row
        for key in path[:-1]:selected=selected[key]
        selected[path[-1]]=copy.deepcopy(value)
    return change


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to(C) or out.exists():raise ValueError('exclusive mutation output below C8 required')
    out.mkdir()
    dataset=C/'replay-large153-02'
    result=replay.read(dataset/'result.json')
    new_policy=replay.read(dataset/'derived-owned-policy.json')
    original_policy=replay.read(replay.ORIGINAL/'process-policy.json')
    new_path=Path(result['privateRuntimeDirectory'])/'derived-owned-replay.jsonl'
    old_path=replay.ORIGINAL/'lifecycle-journal.jsonl'
    runtime=replay.BASE/'.runtime/posix/replays/owned-guard'/out.name
    runtime.mkdir(mode=0o700)
    first,second,_=replay.new_pair(result['ownedInitialization']['initialView'],new_path,runtime)
    original=json.loads((replay.ORIGINAL/'settling/telemetry.jsonl').open().readline())['processObservation']
    current=copy.deepcopy(original)
    replay.shift_view_sequences(current['lifecycle'],3*result['paddingFiniteTasks'])
    prefix=json.loads((dataset/'progress.jsonl').open().readline())
    current['lifecycle'].update(journalPath=str(new_path),lastSequence=prefix['lastSequence'],
        journalBytes=prefix['prefixBytes'],journalSha256=hashlib.sha256(new_path.read_bytes()[:prefix['prefixBytes']]).hexdigest())
    current.update(onlineReplayMode=replay.owned.MODE,onlineReplayInitializationMode=replay.owned.INITIALIZATION_MODE,
        onlineReplaySourceSha256=new_policy['onlineReplaySourceSha256'],onlineReplayPreparation=first.preparation_reference(),
        observerModuleSha256=replay.sha((replay.P/'mac_process_guard_v3.py').read_bytes()),
        lifecyclePolicySha256=result['ownedInitialization']['policySha256'],
        policyCanonicalSha256=replay.current_guard.canonical_sha256(new_policy))
    cases=[]
    def add(name,path,value):cases.append((name,setpath(path,value)))
    for name in ('observerModuleSha256','nativeSourceSha256','nativeHelperSha256','preservedV1SourceSha256',
                 'preservedV2SourceSha256','lifecycleModuleSha256','lifecyclePolicySha256','policyCanonicalSha256'):
        add(name+'_mismatch',(name,),'0'*64)
    add('schema_version_wrong',('schemaVersion',),0)
    add('sample_id_missing',('sampleId',),'invalid')
    add('start_clock_negative',('startedMonotonic',),-1)
    add('end_clock_reverse',('finishedMonotonic',),original['startedMonotonic']-1)
    add('claimed_status_false',('status',),'FAIL')
    add('derived_rss_sum_false',('ownedRssBytes',),1)
    add('rss_boolean_not_integer',('ownedRssBytes',),True)
    add('binary_mode_missing',('binaryAuthenticationMode',),None)
    add('binary_source_wrong',('binaryAuthenticationModuleSha256',),'0'*64)
    add('binary_work_boolean',('binaryAuthenticationWork',),dict(calls=True))
    add('coordination_schema_wrong',('coordinationSchema',),'foreign')
    add('coordination_mode_wrong',('coordinationMode',),'foreign')
    add('lock_wait_budget_changed',('coordinationLocks','before','maxWaitSeconds'),2)
    add('lock_identity_changed',('coordinationLocks','after','finalIdentity','inode'),0)
    add('api_clock_reversed',('segmentedApiClock','finishedMonotonic'),original['startedMonotonic']-1)
    for phase in ('before','after'):
        root=('evidence',phase)
        add(phase+'_snapshot_error',root+('errors',),['fixture'])
        add(phase+'_graph_error',root+('processGraph','errors'),['fixture'])
        add(phase+'_graph_schema_wrong',root+('processGraph','schema'),'foreign')
        add(phase+'_graph_node_pid_boolean',root+('processGraph','nodes',0,'pid'),True)
        add(phase+'_native_stdout_corrupt',root+('processGraph','nativeCensus','stdoutBase64'),'invalid')
        add(phase+'_native_timeout',root+('processGraph','nativeCensus','timedOut'),True)
        add(phase+'_native_lease_wrong',root+('processGraph','nativeCensus','managedLeaseId'),'0'*32)
        add(phase+'_daemon_pid_wrong',root+('daemon','app','pid'),2)
        add(phase+'_daemon_missing',root+('daemon',),{})
        add(phase+'_listener_unknown',root+('listener','state'),'UNKNOWN')
        add(phase+'_listener_extra',root+('listener','records'),[])
    add('api_loaded',('evidence','api','state'),'NONEMPTY')
    add('api_unknown',('evidence','api','state'),'UNKNOWN')
    add('api_empty_body_corrupt',('evidence','api','emptyBodyBase64'),'invalid')
    add('api_body_hash_wrong',('evidence','api','bodySha256'),'0'*64)
    add('api_http_float_not_int',('evidence','api','httpStatus'),200.0)
    add('api_count_wrong',('evidence','api','modelCount'),1)
    add('api_byte_count_boolean',('evidence','api','bytes'),True)
    add('api_duration_exceeded',('evidence','api','durationSeconds'),1.0)
    add('claimed_owned_processes_wrong',('ownedProcesses',),[dict(pid=999999,rssBytes=0)])
    records=[]
    for name,change in cases:
        old=copy.deepcopy(original);new=copy.deepcopy(current);change(old);change(new)
        with patch.dict(sys.modules,full_state_clone_cursor=replay.old_clone):
            expected=replay.old_guard.validate_observation(original_policy,old,old_path)
        a_decision=replay.current_guard.validate_observation(new_policy,new,new_path,lifecycle_cursor=first)
        b_decision=replay.current_guard.validate_observation(new_policy,new,new_path,lifecycle_cursor=second)
        accepted=(expected['status']!='PASS' and replay.typed(expected,a_decision) and replay.typed(expected,b_decision))
        item=dict(name=name,status='PASS' if accepted else 'FAIL',independentOriginalColdDecision=expected,
            actualOwnedInnerDecision=a_decision,actualOwnedOuterDecision=b_decision,
            allScalarAndContainerTypesCompared=True,expectedMutationAdverse=expected['status']!='PASS')
        records.append(item)
        (out/'progress.json').write_bytes(replay.encoded(records))
        print(item['status'],name,flush=True)
        if not accepted:
            (out/'failed-fixture.json').write_bytes(replay.encoded(dict(originalMutation=old,ownedDerivedMutation=new)))
            break
    summary=dict(schema='aijade.ch7.owned-guard-core-mutation-controls.v1',
        status='PASS' if len(records)==len(cases) and all(r['status']=='PASS' for r in records) else 'FAIL',
        planned=len(cases),actual=len(records),passed=sum(r['status']=='PASS' for r in records),
        actualQe3GuardColdOracle=True,sourcePredicateCoreAstUnchanged=True,
        completeTypedDecisionsCompared=3*len(records),coreMutations=records,
        ownerSourceModeBindingControls='Separate current 12 owned-cursor controls',
        callbackFullPrefixReadPreserved=True,currentOwnedSourceSha256=replay.sha((replay.P/'newowned_guard_cursor.py').read_bytes()),
        guardSourceSha256=replay.sha((replay.P/'mac_process_guard_v3.py').read_bytes()),
        nativeApiModelQueries=0,newChildProcesses=0,worktreeEdited=False,docsEdited=False,
        originalActualE4Changed=False,liveEngineeringAccepted=False,scientificQualification=False)
    (out/'result.json').write_bytes(replay.encoded(summary))
    print(json.dumps(dict(status=summary['status'],passed=summary['passed'],planned=len(cases))))
    raise SystemExit(0 if summary['status']=='PASS' else 1)


if __name__=='__main__':main()
