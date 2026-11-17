"""Offline audit of the single P4 terminal record; never collect observations.

Every one of the360 idle observations is cold-replayed once by frozen Q2 guard
and the independent lifecycle prefix parser. A process-local cache may serve
that exact already-proven predicate to the later whole-continuity call; keys
bind actual row/policy/journal/source bytes. Adverse runtime/lifecycle outcomes
are retained, not relabelled as successful scientific qualification.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib,json,math
from pathlib import Path
import socket,subprocess,sys,time,traceback
import urllib.request

BASE=Path('/Volumes/Untitled/AIJADE')
C=BASE/'.research/runs/ch7-prefix-qualification-20261117'
W=BASE/'.runtime/posix/research/ch7-prefix-20261117/worktree'
RUN=BASE/'.runtime/posix/runs/ch7-prefix-v4-20261117/qualification-01'
Q='147564c9db812c1a9e5ae07992d9aa282399a310'
B='8acfa99d061f1c41197fac2a1c243b3b347bcfef'
P='42fc728ade94c60b0d24575b9510b69dd2048676'
PLAN='experiments/plans/2026-11-17-ch7-mac-prefix-v4-qualification.md'
PLAN_SHA='7aa91508eee3e728cadd8d25f8cdd122deb9a35d06a09901e8143d1e028d9d36'
POLICY_SHA='caf8392394a09ec168df44347337ec0676f695f5d3cd9af576372678e03a925a'

def need(ok,message):
    if not ok:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def read(path):return json.loads(Path(path).read_bytes())
def rows(path):
    with Path(path).open('rb') as stream:return [json.loads(line) for line in stream if line.strip()]
def stamp(value):need(type(value) in (int,float) and math.isfinite(value),'clock invalid');return value
def file_proof(path):
    before=path.stat();digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    after=path.stat();need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'input changed while hashing')
    return {'path':str(path),'sha256':digest.hexdigest(),'sizeBytes':before.st_size}
def git(commit,path):return subprocess.check_output(['git','--no-replace-objects','-C',str(W),'show',commit+':'+path],stderr=subprocess.DEVNULL)

@contextmanager
def no_live_operations():
    old_popen,old_connect,old_open=subprocess.Popen,socket.create_connection,urllib.request.OpenerDirector.open
    def forbidden(*args,**kwargs):raise RuntimeError('live/process/network operation forbidden in offline audit')
    subprocess.Popen=forbidden;socket.create_connection=forbidden;urllib.request.OpenerDirector.open=forbidden
    try:yield
    finally:subprocess.Popen=old_popen;socket.create_connection=old_connect;urllib.request.OpenerDirector.open=old_open

def result_of(call):
    try:return {'status':'PASS','result':call()}
    except Exception as error:return {'status':'REFUSED','errorClass':type(error).__name__,'error':str(error),'traceback':traceback.format_exc()}

def main():
    output=C/'analysis/independent-p4-terminal-audit-01.json';need(not output.exists(),'never overwrite terminal audit')
    sources_before={};receipt=read(RUN/'receipt.json')
    for name,expected in receipt['observerSources'].items():
        raw=(W/name).read_bytes();need(sha(raw)==expected and raw==git(Q,name),'frozen Q2 source differs: '+name);sources_before[name]=sha(raw)
    need(len(sources_before)==15,'exact15 source closure')
    launcher='experiments/ch7/launch_frozen_sequence.py';need((W/launcher).read_bytes()==git(Q,launcher),'parent source differs from Q2')
    sources_before[launcher]=sha((W/launcher).read_bytes())
    need(sha((W/PLAN).read_bytes())==PLAN_SHA and (W/PLAN).read_bytes()==git(P,PLAN),'published P4 bytes differ')
    policy_raw=(RUN/'process-policy.json').read_bytes();need(sha(policy_raw)==POLICY_SHA,'actual policy differs');policy=json.loads(policy_raw)
    need(receipt['implementationCommit']==receipt['repositoryCommit']==Q and receipt['buildFreezeCommit']==B,'Q2/B4 binding')
    build_path='experiments/ch7/mac-prefix-v4-2026-11-17/frozen-build.json'
    build_raw=(C/'frozen-build.json').read_bytes();build=json.loads(build_raw)
    need(build_raw==git(B,build_path) and build['commit']==Q and build['observerSources']==receipt['observerSources']
         and build['assemblyInformationalVersion']=='0.1.0+'+Q,'actual public B4 metadata differs from Q2/source15')
    paths=sorted(path for path in RUN.rglob('*') if path.is_file())
    adjacent=RUN.with_name(RUN.name+'-lifecycle.jsonl')
    if adjacent.exists():paths.append(adjacent)
    parent_names=('qualification-single-launch.json','qualification-single-launch.terminal.json','qualification-single-launch.controller.log',
                  'qualification-fixed-launch.json','qualification-prelaunch.json','qualification-prelaunch-integrity.json')
    paths.extend(C/name for name in parent_names)
    paths.append(C/'frozen-build.json')
    inputs_before=[file_proof(path) for path in paths]
    journal=(RUN/'lifecycle-journal.jsonl').read_bytes()
    need(sha(journal)==receipt['lifecycleJournalSha256'],'final journal hash receipt differs')
    if adjacent.exists():need(adjacent.read_bytes()==journal,'archived and adjacent actual journal differ')
    streams={name:rows(RUN/name/'telemetry.jsonl') for name in ('settling','admission')}
    phases={name:read(RUN/name/'receipt.json') for name in streams};events=rows(RUN/'phase-events.jsonl')
    runtime=rows(RUN/'process-observations.jsonl');actual_runtime=[row for row in runtime if 'processObservation' in row]
    runtime_errors=[row for row in runtime if 'observationError' in row]
    registry=read(RUN/'owned-process-registry.json');preflight=read(RUN/'preflight-continuity.json')
    launch=read(C/'qualification-single-launch.json');terminal=read(C/'qualification-single-launch.terminal.json')
    config=read(C/'qualification-fixed-launch.json')
    need(terminal['configSha256']==sha((C/'qualification-fixed-launch.json').read_bytes()),'parent exact config binding')
    need(terminal['launchRecordSha256']==sha((C/'qualification-single-launch.json').read_bytes()),'parent launch binding')
    need(terminal['logSha256']==sha((C/'qualification-single-launch.controller.log').read_bytes()),'parent terminal log hash')
    need(terminal['implementationCommit']==terminal['repositoryCommit']==Q and terminal['buildFreezeCommit']==B,'parent source binding')
    need(terminal['controllerExitCode']==1 and terminal['intervention'] is False and terminal['watchdogSeconds']==5700
         and terminal['automaticRetries']==0 and terminal['unresolved'] is False,'actual parent adverse/no intervention contract')
    need(terminal['controllerProcess']['pid']==receipt['controllerProcess']['pid'] and terminal['controllerProcess']['createTime']==receipt['controllerProcess']['createTime'],'controller kernel identity binding')
    evidence=terminal['processEvidence'];polls=evidence['terminalPolls'];waits=evidence['waitCalls']
    need(len(polls)==len(waits)==1 and polls[0]['exitCode']==waits[0]['exitCode']==1
         and polls[0]['provenance']=='TERMINAL_STATUS_FIRST_OBTAINED_BY_POPEN_POLL'
         and waits[0]['provenance']=='CACHED_RETURN_AFTER_PRIOR_TERMINAL_STATUS'
         and polls[0]['independentKernelWaitClaimed'] is False and waits[0]['independentKernelWaitClaimed'] is False,'normal poll/cached-wait provenance')
    need(receipt['status']=='STOPPED' and receipt['completedBlocks']==receipt['completedConditionRows']==receipt['modelRequests']==0
         and len(receipt['unattemptedCaseIds'])==20 and receipt['unknownCaseIds']==receipt['inFlightCaseIds']==receipt['blocks']==receipt['blockControllers']==[], 'actual terminal disposition contract')
    need(not list(RUN.glob('block-*')) or {p.name for p in RUN.glob('block-*')}=={'block-1-controller.log'},'unexpected block artifact')
    need((RUN/'block-1-controller.log').stat().st_size==0 and not (RUN/'block-1').exists(),'block launch should have no directory/receipt/output')
    sys.path.insert(0,str(W/'experiments/ch7'))
    import mac_process_guard_v3 as guard
    import lifecycle_audit as independent
    source_context_sha=sha(encoded(sources_before));journal_sha=sha(journal)
    cached={};progress=[];native_leases=set();prefix_errors=[];cold_count=0
    original_validate=independent._validate_sample
    def key(row):return sha(encoded({'row':row,'policySha':sha(policy_raw),'journalSha':journal_sha,'sourcesSha':source_context_sha}))
    def cold_validate(row,current_policy,lifecycle_journal=None):
        nonlocal cold_count
        cache_key=key(row)
        if cache_key in cached:return cached[cache_key]
        need(current_policy==policy and lifecycle_journal==journal,'same exact audit policy/journal required')
        decision=original_validate(row,current_policy,lifecycle_journal)
        observation=row['processObservation'];view=observation['lifecycle'];size=view['journalBytes'];prefix=journal[:size]
        need(sha(prefix)==view['journalSha256'],'original prefix bytes differ')
        state=independent._replay(prefix,Q,POLICY_SHA)
        frames=independent._raw_frames(observation,policy)
        refs=sorted({independent.node_identity(node) for frame in frames for node in frame['nodes']})
        need(view['referencedIdentities']==[list(item) for item in refs],'independent native identity coverage')
        projected=[lease for lease in state['leases'].values() if lease['absence'] is None or independent.identity(lease['identity']) in refs]
        need(view['leases']==projected,'independent lifecycle view projection differs')
        need(view['lastSequence']==len(state['events']) and view['runId']==state['runId'],'independent prefix context differs')
        for frame in frames:
            lease=independent._native_lease(frame,state,view['controllerIdentity'],policy)
            need(lease is not None and lease not in native_leases,'original native lease duplicate/omitted');native_leases.add(lease)
        need(observation['ownedRoots']==[] and observation['ownedProcesses']==[] and row['rssBytes']==0,'idle workload-owned population must be empty')
        cached[cache_key]=decision;cold_count+=1
        if cold_count%15==0:
            item={'coldRawReplayed':cold_count,'expected':360,'nativeLeaseBindings':len(native_leases)};progress.append(item);print(json.dumps(item),flush=True)
        return decision
    independent._validate_sample=cold_validate
    with no_live_operations():
        # Do not let any one adverse predicate prevent other original records
        # from being independently replayed or the terminal state from reported.
        raw_decisions=[]
        for phase in ('settling','admission'):
            for row in streams[phase]:
                outcome=result_of(lambda row=row:cold_validate(row,policy,journal))
                raw_decisions.append({'phase':phase,'globalIndex':row.get('globalIndex'),'sampleId':row.get('sampleId'),
                    'status':outcome['status'],**({} if outcome['status']=='PASS' else {'error':outcome['error'],'traceback':outcome['traceback']})})
        checkpoint={'status':'ALL_IDLE_COLD_REPLAY_COMPLETED','samples':len(raw_decisions),'passed':sum(r['status']=='PASS' for r in raw_decisions),
                    'refused':sum(r['status']!='PASS' for r in raw_decisions),'nativeLeaseBindings':len(native_leases),'decisions':raw_decisions,
                    'inputHashes':inputs_before,'sourceHashes':sources_before}
        with (C/'analysis/independent-p4-cold-checkpoint-01.json').open('xb') as stream:stream.write(encoded(checkpoint))
        phase_continuity=result_of(lambda:independent.verify_continuity(phases,streams,events,policy=policy,lifecycle_journal=journal))
        runtime_replays=[guard.validate_observation(policy,row['processObservation'],lifecycle_journal=journal) for row in actual_runtime]
        runtime_whole_continuity=result_of(lambda:independent.verify_continuity(phases,streams,events,policy=policy,
            runtime_samples=actual_runtime,runtime_epoch=receipt['sequenceEpochMonotonic'],lifecycle_journal=journal))
        chain=result_of(lambda:independent._replay(journal,Q,POLICY_SHA))
        lifecycle_whole=result_of(lambda:independent.verify_lifecycle(journal,streams['settling']+streams['admission']+actual_runtime,
            source_commit=Q,policy_sha256=POLICY_SHA,policy=policy,controller=receipt['controllerProcess']))
    independent._validate_sample=original_validate
    need(chain['status']=='PASS','complete journal integrity did not replay')
    state=chain['result'];finite=[lease for lease in state['leases'].values() if lease['role']=='finite']
    finite_unresolved=[lease for lease in finite if lease['waitSeq'] is None or lease['exitCode'] is None or lease['absence'] is None]
    finite_nonzero=[lease for lease in finite if lease['exitCode']!=0]
    event_counts=Counter(event['event'] for event in state['events'])
    need(len(finite)==len(registry['knownFiniteLeases'])==1476 and not finite_unresolved and not finite_nonzero,'direct finite actual WAIT terminal population differs')
    producer={lease['leaseId']:lease for lease in registry['knownFiniteLeases']};independent_finite={lease['leaseId']:lease for lease in finite}
    need(producer==independent_finite,'independent full finite lease projection differs from final producer registry')
    refusals=state['launchRefusals'];need(len(refusals)==1,'actual single refusal population')
    refusal=refusals[0]
    data=refusal.get('data',refusal)
    need(data['spawnedPid'] is None and data['registeredLeaseId'] is None and data['readyBytes']==0 and data['identityReads']==[]
         and data['cleanupKnown'] is True and data['actualExitCode'] is None and data['stageId']=='block-1','actual refused-before-spawn evidence differs')
    need(registry['remainingIdentities']==registry['unresolvedFiniteLeases']==registry['unleasedDiscoveredIdentities']==[]
         and registry['scopeClosed'] is True and registry['status']=='UNKNOWN_OR_ADVERSE_OWNED_LIFECYCLE','final recorded cleanup scope differs')
    need(sha((RUN/'phase-events.jsonl').read_bytes())==receipt['phaseEventsSha256'] and sha((RUN/'owned-process-registry.json').read_bytes())==receipt['ownedProcessRegistrySha256']
         and sha((RUN/'preflight-continuity.json').read_bytes())==receipt['preflightContinuitySha256'],'terminal hash closures differ')
    need(all(file_proof(Path(proof['path']))==proof for proof in inputs_before),'original input bytes changed during offline audit')
    need(all(sha((W/name).read_bytes())==digest for name,digest in sources_before.items()),'frozen audit source changed')
    runtime_failure_only=len(runtime_replays)==1 and runtime_replays[0]['status']=='FAIL'
    numbers={'settlingRawSamples':len(streams['settling']),'settlingColdPassSamples':sum(row['status']=='PASS' and row['phase']=='settling' for row in raw_decisions),
        'admissionRawSamples':len(streams['admission']),'admissionColdPassSamples':sum(row['status']=='PASS' and row['phase']=='admission' for row in raw_decisions),
        'idleColdReplayed':len(raw_decisions),'idleColdPassSamples':sum(row['status']=='PASS' for row in raw_decisions),
        'phaseEvents':len(events),'runtimeRawObservationRecords':len(actual_runtime),'runtimeErrorSidecarRows':len(runtime_errors),
        'runtimeColdFailSamples':sum(row['status']=='FAIL' for row in runtime_replays),'nativeIdleBindings':len(native_leases),
        'journalEvents':len(state['events']),'finiteLeases':len(finite),'finiteActualParentWaitZero':sum(lease['exitCode']==0 for lease in finite),
        'unresolvedFiniteLeases':len(finite_unresolved),'launchRefusals':len(refusals),'spawnedRefusedPids':sum(row.get('spawnedPid') is not None for row in refusals),
        'recordedRemainingIdentities':len(registry['remainingIdentities']),'controllerExitCode':terminal['controllerExitCode'],
        'completedBlocks':receipt['completedBlocks'],'completedConditionRows':receipt['completedConditionRows'],'unattemptedConditionRows':len(receipt['unattemptedCaseIds']),
        'unknownConditionRows':len(receipt['unknownCaseIds']),'inFlightConditionRows':len(receipt['inFlightCaseIds']),'modelRequests':receipt['modelRequests'],
        'settlingRequestedSeconds':600,'admissionRequestedSeconds':120,
        'settlingAdmissionBoundaryGapSeconds':phases['admission']['phaseClock']['startMonotonic']-phases['settling']['phaseClock']['endMonotonic'],
        'admissionEndToRuntimeEpochSeconds':receipt['sequenceEpochMonotonic']-phases['admission']['phaseClock']['endMonotonic'],
        'parentElapsedSeconds':terminal['elapsedSeconds'],'runtimeWallSeconds':receipt['wallSeconds']}
    result={'schema':'aijade.ch7.p4-independent-terminal-refusal-audit.v1',
        'status':'INDEPENDENT_TERMINAL_REFUSAL_RECORD_AUDIT_COMPLETE','implementationCommit':Q,'buildFreezeCommit':B,'planCommit':P,
        'planSha256':PLAN_SHA,'policySha256':POLICY_SHA,'sourceHashes':sources_before,'inputFiles':inputs_before,
        'numbers':numbers,'phaseOnlyContinuity':phase_continuity,'wholeRuntimeContinuity':runtime_whole_continuity,
        'wholeLifecyclePredicate':lifecycle_whole,'completeJournalIntegrity':{'status':'PASS','events':len(state['events']),'eventCounts':dict(event_counts)},
        'runtimeIndependentGuardDecisions':runtime_replays,'runtimeOriginalErrorRows':runtime_errors,'recordedLaunchRefusal':data,
        'parentTerminal':terminal,'originalControllerReceiptReason':receipt['reason'],
        'cleanupInterpretation':{'recordedRemainingIdentityPopulation':0,'unresolvedFiniteIdentityPopulation':0,
            'registryAdverseBecauseLaunchRefusalRemains':True,'physicalLivingDescendantProvenByGenericReason':False,
            'beforeSpawnNoPidRecorded':True,'noCurrentPidQueriesPerformed':True,
            'noExitCodeInventedForUnspawnedAttempt':True,'parentPollFirstThenCachedWaitKeptDistinct':True},
        'scope':{'terminalRecordIntegrityAccepted':checkpoint['refused']==0 and phase_continuity['status']=='PASS' and runtime_failure_only,
            'settlingAndAdmissionRawPhaseAccepted':phase_continuity['status']=='PASS','fullFiniteDriverQualified':False,
            'scientificAcceptance':False,'formalHardwareQualification':False,'independentHumanReview':False,'authorApproval':False,
            'heldoutComparisonComplete':False,'currentProductInheritsResearchQualification':False,'freshHeldoutCases':0,'seedConstructed':False,'table7_3':'NOT_RUN'},
        'replayScope':'All360 idle original records cold guard+independent prefix/native replay; whole continuity reuses exact actual-byte cache. Runtime adverse evidence independently replayed; original adverse frozen predicates retained.',
        'livePhysicalSdkOrNativeRechecked':False,'observerOrModelOrRendererOrNetworkInvoked':False,'inputAndSourceBytesUnchanged':True,
        'checkedAt':datetime.now(timezone.utc).isoformat()}
    with output.open('xb') as stream:stream.write(encoded(result))
    print(json.dumps({'status':result['status'],'output':str(output),'sha256':sha(output.read_bytes()),'numbers':numbers,'scope':result['scope']},indent=2),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as error:
        failure={'status':'INDEPENDENT_AUDIT_TOOL_REFUSED_PRESERVE_ORIGINALS','errorClass':type(error).__name__,
                 'error':str(error),'traceback':traceback.format_exc(),'scientificQualificationAccepted':False,
                 'sourceOrRawDataModified':False,'at':datetime.now(timezone.utc).isoformat()}
        path=C/'analysis/independent-p4-terminal-audit-01.failure.json'
        if not path.exists():
            with path.open('xb') as stream:stream.write(encoded(failure))
        raise
