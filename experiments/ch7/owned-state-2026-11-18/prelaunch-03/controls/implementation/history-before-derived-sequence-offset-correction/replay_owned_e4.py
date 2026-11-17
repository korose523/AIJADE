"""Offline actual-E4 oracle comparison and bounded derived-prefix component timings.

No OS process/API/native/model query or live engineering window. Every callback
reads its actual complete file prefix. Timings cover replay/guard/detachment,
not native capture or complete services, and are not qualification acceptance.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import statistics
import sys
import time
from unittest.mock import patch

C=Path(__file__).resolve().parent
P=C/'candidate/experiments/ch7'
BASE=Path('/Volumes/Untitled/AIJADE')
ORIGINAL=BASE/'.runtime/posix/runs/ch7-nested-copy-20261118/engineering-02'
ORACLES=BASE/'.research/runs/ch7-nested-copy-20261118/audit/e4-full-cold-decisions-01.jsonl'
sys.path.insert(0,str(P))
import process_lifecycle as life
import full_state_clone_cursor as current_clone
import mac_process_guard_v3 as current_guard
import newowned_guard_cursor as owned


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


old_guard=load('exact_qe3_guard_reference',C/'baseline/experiments/ch7/mac_process_guard_v3.py')
old_clone=load('exact_qe3_clone_reference',C/'baseline/experiments/ch7/full_state_clone_cursor.py')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_bytes())
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


def typed(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return set(a)==set(b) and all(typed(a[k],b[k]) for k in a)
    if type(a) in (list,tuple):return len(a)==len(b) and all(typed(x,y) for x,y in zip(a,b))
    return a==b


def recontext(events,policy_sha,padding_count):
    """Synthetic completed prep tasks only; never borrow a future actual WAIT."""
    original=copy.deepcopy(events)
    if padding_count:
        template_index=next(i for i,e in enumerate(original) if e['event']=='FINITE_REGISTER')
        template=original[template_index]
        mono=(original[1]['monotonicSeconds']+template['monotonicSeconds'])/2
        parent=original[0]['data']['identity']
        root_writer=original[0]['writer']
        existing={e['data']['leaseId'] for e in original if e['event'] in ('CONTROLLER_REGISTER','FINITE_REGISTER')}
        addition=[]
        for i in range(padding_count):
            lease_id=format((1<<124)+i,'032x')
            if lease_id in existing:raise ValueError('derived lease collision')
            identity=dict(pid=800000+i,createTimeMicros=parent['createTimeMicros']+3000000+i,parentPid=parent['pid'])
            reg=copy.deepcopy(template)
            reg.update(writer=copy.deepcopy(root_writer),monotonicSeconds=mono)
            reg['data'].update(leaseId=lease_id,identity=identity,parentIdentity=copy.deepcopy(parent),
                readyMonotonic=mono,stageId='derived-padding')
            release=copy.deepcopy(reg);release.update(event='RELEASE',data=dict(leaseId=lease_id))
            wait=copy.deepcopy(reg);wait.update(event='WAIT',data=dict(leaseId=lease_id,identity=copy.deepcopy(identity),
                exitCode=0,waitSource='Popen.wait',reapedMonotonic=mono))
            addition.extend((reg,release,wait))
        original=original[:2]+addition+original[2:]
    raw=[];previous=life.ZERO
    for i,event in enumerate(original,1):
        event.update(seq=i,policySha256=policy_sha,previousSha256=previous)
        event['sha256']=life.digest(life.canonical({k:v for k,v in event.items() if k!='sha256'}))
        line=life.canonical(event)+b'\n';raw.append(line);previous=event['sha256']
    need_bytes=b''.join(raw)
    if len(need_bytes)>16*1024*1024 or len(original)>20000:raise ValueError('derived fixed journal/event envelope exceeded')
    return need_bytes,original,raw


def views_for(journal_lines,cutoffs):
    hasher=hashlib.sha256();size=0;result={}
    for index,line in enumerate(journal_lines,1):
        size+=len(line);hasher.update(line)
        if index in cutoffs:result[index]=(size,hasher.hexdigest())
    if set(result)!=set(cutoffs):raise ValueError('derived prefix cutoff missing')
    return result


def old_pair(view,path,original_record,original_writer):
    with patch.dict(sys.modules,full_state_clone_cursor=old_clone):
        first,second,_=old_clone.bootstrap_pair(view,path)
    first.bind_preparation(original_record,original_writer);second.bind_preparation(original_record,original_writer)
    return first,second


def new_pair(view,path,output):
    factory_started=time.monotonic()
    actual_view=copy.deepcopy(view)
    captured=time.monotonic()
    first,second,record=owned.bootstrap_pair(actual_view,path)
    record.update(factoryStartedMonotonic=factory_started,viewCapturedMonotonic=captured,
        inputViewKind='EXPLICIT_PRECOMPUTED_OFFLINE_VIEW_NO_PROCESS_SAMPLE',
        recordWriteStartedMonotonic=time.monotonic())
    raw=encoded(record);target=output/'initialization.json';target.write_bytes(raw);target.chmod(0o600)
    ended=time.monotonic()
    writer=dict(path=str(target),sha256=sha(raw),startedMonotonic=record['recordWriteStartedMonotonic'],completedMonotonic=ended)
    first.bind_preparation(record,writer);second.bind_preparation(record,writer)
    return first,second,record


def summary(values):
    return dict(calls=len(values),minimumSeconds=min(values),medianSeconds=statistics.median(values),
        maximumSeconds=max(values),totalSeconds=sum(values))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--large',action='store_true');a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to(C) or out.exists():raise ValueError('exclusive output below C8 implementation required')
    out.mkdir()
    runtime=BASE/'.runtime/posix/replays/owned-guard'/out.name
    if runtime.exists():raise ValueError('exclusive private APFS runtime replay directory required')
    runtime.mkdir(parents=True,mode=0o700)
    original_paths=('lifecycle-journal.jsonl','settling/telemetry.jsonl','process-policy.json','initialization.json','receipt.json')
    before={name:dict(sha256=sha((ORIGINAL/name).read_bytes()),sizeBytes=(ORIGINAL/name).stat().st_size) for name in original_paths}
    rows=[json.loads(line) for line in (ORIGINAL/'settling/telemetry.jsonl').read_bytes().splitlines()]
    oracle_raw=ORACLES.read_bytes()
    if sha(oracle_raw)!='c0d3248de674c0ff545e04fa26997349c9c38dcc2016fe50086aac05310dc42d':raise ValueError('fixed independent full cold decisions differ')
    oracle_rows=[json.loads(line) for line in oracle_raw.splitlines()]
    oracles={row['sampleId']:row['actualFullTypedDecision'] for row in oracle_rows}
    if len(rows)!=153 or len(oracles)!=153:raise ValueError('complete raw/oracle population required')
    old_policy=read(ORIGINAL/'process-policy.json');initial=read(ORIGINAL/'initialization.json');receipt=read(ORIGINAL/'receipt.json')
    original_journal=(ORIGINAL/'lifecycle-journal.jsonl').read_bytes()
    events=[json.loads(line) for line in original_journal.splitlines()]
    original_finite=sum(e['event']=='FINITE_REGISTER' for e in events)
    padding=6318-original_finite if a.large else 0
    if padding<0:raise ValueError('original finite population already exceeds frozen fixture bound')
    new_policy=copy.deepcopy(old_policy)
    new_policy.update(onlineReplayMode=owned.MODE,onlineReplayInitializationMode=owned.INITIALIZATION_MODE,
        onlineReplaySourceSha256=sha((P/'newowned_guard_cursor.py').read_bytes()))
    policy_raw=encoded(new_policy);policy_sha=sha(policy_raw);(out/'derived-owned-policy.json').write_bytes(policy_raw)
    old_policy_sha=events[0]['policySha256']
    old_body,old_events,old_lines=recontext(events,old_policy_sha,padding)
    new_body,new_events,new_lines=recontext(events,policy_sha,padding)
    if not a.large and old_body!=original_journal:raise ValueError('zero-padding old archive must be byte-identical')
    old_path=runtime/'source-bound-legacy-replay.jsonl';new_path=runtime/'derived-owned-replay.jsonl'
    old_path.write_bytes(old_body);old_path.chmod(0o600)
    new_path.write_bytes(new_body);new_path.chmod(0o600)
    added_events=3*padding
    cutoffs={initial['lastSequence']+added_events}|{r['processObservation']['lifecycle']['lastSequence']+added_events for r in rows}
    old_prefix=views_for(old_lines,cutoffs);new_prefix=views_for(new_lines,cutoffs)
    old_view=copy.deepcopy(initial['initialView']);new_view=copy.deepcopy(old_view)
    for view,prefix,path in ((old_view,old_prefix,old_path),(new_view,new_prefix,new_path)):
        view['lastSequence']+=added_events;view['journalBytes'],view['journalSha256']=prefix[view['lastSequence']]
        if a.large:view['journalPath']=str(path)
    new_view['journalPath']=str(new_path)
    old_record=copy.deepcopy(initial);old_record.update(prefixBytes=old_view['journalBytes'],prefixSha256=old_view['journalSha256'],
        lastSequence=old_view['lastSequence'],initialView=old_view,journalPath=old_view['journalPath'])
    # Legacy large-prefix metadata is explicitly a derived replay binding, not
    # an original E4 initialization or a claimed live source publication.
    if a.large:
        old_record['sourceOrigin']=['file',str(old_path),old_path.stat().st_dev,old_path.stat().st_ino]
    old_writer=copy.deepcopy(receipt['initializationWriteClock'])
    if a.large:
        legacy_dir=runtime/'legacy';legacy_dir.mkdir(mode=0o700)
        old_init=legacy_dir/'initialization.json';old_init.write_bytes(encoded(old_record));old_init.chmod(0o600)
        old_writer['path']=str(old_init)
        old_writer['sha256']=sha(old_init.read_bytes())
    baseline=old_pair(old_view,old_path,old_record,old_writer)
    owners=new_pair(new_view,new_path,runtime)
    new_source_sha=sha((P/'mac_process_guard_v3.py').read_bytes())
    timed={'legacyInner':[],'legacyOuter':[],'ownedInner':[],'ownedOuter':[]}
    records=[];large_records=[]
    for index,row in enumerate(rows):
        sample=row['processObservation'];key=sample['sampleId'];expected=oracles[key]
        legacy_obs=copy.deepcopy(sample);owned_obs=copy.deepcopy(sample)
        sequence=sample['lifecycle']['lastSequence']+added_events
        for obs,prefix,path in ((legacy_obs,old_prefix,old_path),(owned_obs,new_prefix,new_path)):
            obs['lifecycle'].update(lastSequence=sequence,journalBytes=prefix[sequence][0],journalSha256=prefix[sequence][1])
            if a.large:obs['lifecycle']['journalPath']=str(path)
        if a.large:
            legacy_obs['onlineReplayPreparation']=baseline[0].preparation_reference()
        owned_obs['lifecycle']['journalPath']=str(new_path)
        owned_obs.update(onlineReplayMode=owned.MODE,onlineReplayInitializationMode=owned.INITIALIZATION_MODE,
            onlineReplaySourceSha256=new_policy['onlineReplaySourceSha256'],onlineReplayPreparation=owners[0].preparation_reference(),
            observerModuleSha256=new_source_sha,lifecyclePolicySha256=policy_sha,
            policyCanonicalSha256=current_guard.canonical_sha256(new_policy))
        order=('legacy','owned') if index%2==0 else ('owned','legacy')
        outcomes={};durations={}
        for condition in order:
            for role,cursor in zip(('Inner','Outer'),baseline if condition=='legacy' else owners[:2]):
                start=time.perf_counter()
                if condition=='legacy':
                    with patch.dict(sys.modules,full_state_clone_cursor=old_clone):
                        decision=old_guard.validate_observation(old_policy,legacy_obs,old_path,lifecycle_cursor=cursor)
                else:
                    decision=current_guard.validate_observation(new_policy,owned_obs,new_path,lifecycle_cursor=cursor)
                elapsed=time.perf_counter()-start;label=condition+role
                timed[label].append(elapsed);durations[label]=elapsed;outcomes[label]=decision
                if not typed(decision,expected):
                    (out/('adverse-sample-'+str(index)+'.json')).write_bytes(encoded(dict(index=index,sampleId=key,condition=label,
                        actual=decision,expected=expected,derivedOwnedObservation=owned_obs)))
                    raise ValueError('full independent typed decision differs: '+str(index)+' '+label)
        item=dict(globalIndex=index,sampleId=key,fullTypedDecisionsEqual=True,prefixBytes=new_prefix[sequence][0],
            lastSequence=sequence,conditionOrder=list(order),componentSeconds=durations,
            actualFullTypedDecision=outcomes['ownedInner'])
        records.append(item)
        if item['prefixBytes']>=14*1024*1024:large_records.append(item)
        with (out/'progress.jsonl').open('ab') as stream:stream.write(encoded(item).replace(b'\n',b' ')+b'\n')
        if index%25==0:print('complete typed replay',index+1,'/',len(rows),flush=True)
    after={name:dict(sha256=sha((ORIGINAL/name).read_bytes()),sizeBytes=(ORIGINAL/name).stat().st_size) for name in original_paths}
    if before!=after:raise ValueError('actual original E4 changed during offline replay')
    stats={name:cursor.statistics() for name,cursor in zip(('legacyInner','legacyOuter','ownedInner','ownedOuter'),(*baseline,*owners[:2]))}
    for name in ('ownedInner','ownedOuter'):
        if stats[name]['guardEvaluations']!=153 or stats[name]['snapshotCopies']!=0 or stats[name]['detachedDecisionCopies']!=153:
            raise ValueError('actual owned callback/snapshot/detachment accounting differs')
        canonical_decision_bytes=sum(len(life.canonical(oracles[row['processObservation']['sampleId']])) for row in rows)
        if stats[name]['detachedDecisionCanonicalBytes']!=canonical_decision_bytes:
            raise ValueError('actual canonical decision byte counter differs from complete independent cold decisions')
    if original_finite+padding>6318 or len(new_events)>20000 or len(new_body)>16*1024*1024:
        raise ValueError('derived fixed context bounds exceeded')
    result=dict(schema='aijade.ch7.owned-guard-e4-offline-replay.v1',
        status='COMPLETE_153_TYPED_DECISIONS_MATCH_INDEPENDENT_QE3_COLD_ORACLE_NOT_LIVE_ACCEPTANCE',
        originalSourceCommit='8231d8b9d67e5188787b69225a72145f2d4c5a63',originalInputsBefore=before,originalInputsAfter=after,
        independentColdOracleSha256=sha(oracle_raw),rawRecords=153,conditionCallsEach=153,
        sourceFileIdentities={name:sha((P/name).read_bytes()) for name in ('newowned_guard_cursor.py','mac_process_guard_v3.py',
            'process_lifecycle.py','full_state_clone_cursor.py','finite_runtime.py','run_nested_load.py','binary_authentication.py')},
        replayScriptSha256=sha(Path(__file__).read_bytes()),
        privateRuntimeDirectory=str(runtime),legacyReplayJournalSha256=sha(old_body),ownedReplayJournalSha256=sha(new_body),
        completeDecisionsCompared=612,paddingFiniteTasks=padding,totalFiniteTasks=original_finite+padding,
        derivedJournalBytes=len(new_body),derivedJournalEvents=len(new_events),
        actualPrefixMinimumBytes=min(r['prefixBytes'] for r in records),actualPrefixMaximumBytes=max(r['prefixBytes'] for r in records),
        prefixAtLeast14MiBRecords=len(large_records),
        allRecordComponentTimings={k:summary(v) for k,v in timed.items()},
        atLeast14MiBComponentTimings=({k:summary([r['componentSeconds'][k] for r in large_records]) for k in timed} if large_records else None),
        finalCursorStatistics=stats,ownedInitialization=owners[2],
        originalDecisionCoreAstUnchanged=True,derivation='Explicit source/policy/ref/owner recontextualization; optional completed synthetic pre-observation finite chains. No future actual WAIT is moved earlier.',
        conditionOrder='per-record legacy/owned order alternates; both independent roles evaluated each time',
        completeServiceMeasured=False,nativeApiModelRequests=0,newRealChildProcesses=0,
        actualE4RecordModified=False,worktreeEdited=False,docsEdited=False,concurrentReviewExcluded=False,
        causalSpeedupClaim=False,fullEngineeringAccepted=False,backendQualified=False,
        seedConstructed=False,heldoutComparisonRun=False)
    (out/'result.json').write_bytes(encoded(result))
    print(json.dumps(dict(status=result['status'],prefixRange=[result['actualPrefixMinimumBytes'],result['actualPrefixMaximumBytes']],
        largeRecords=len(large_records),timings=result['allRecordComponentTimings']),indent=2))


if __name__=='__main__':main()
