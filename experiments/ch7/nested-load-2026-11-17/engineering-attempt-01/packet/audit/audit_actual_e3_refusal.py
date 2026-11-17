"""Independent audit of the immutable E3 first-slot refusal; never a PASS run."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import ast
import hashlib
import json
import math
import subprocess
import sys
import time
import psutil

B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-nested-20261117'
R=B/'.runtime/posix/nested-20261117/worktree'
RUN=B/'.runtime/posix/runs/ch7-nested-20261117/engineering-01'
Q='1ab9056dfee6cc804f84677830989b1d2f8153a4'
sys.path.insert(0,str(C/'archive-tools'))
from packet_common import read,sha,file_sha,encoded,new,inventory,need,typed_equal,parent_wait_known


def jsonl(p):
    raw=p.read_bytes();need(not raw or raw.endswith(b'\n'),'original JSONL truncated')
    return [json.loads(x) for x in raw.splitlines()]


def original_identity_probe(ident):
    """Corroboration only; original actual waits remain the terminal evidence."""
    try:
        p=psutil.Process(ident['pid']);first=p.create_time();parent=p.ppid();second=p.create_time()
        need(first==second,'current PID birth changed during corroboration')
        micros=round(first*1000000)
        need(micros!=ident['createTimeMicros'],'original writer identity remains live despite recorded terminal wait')
        return dict(state='PID_REUSED_BY_DIFFERENT_BIRTH_NOT_ORIGINAL_WRITER',pid=ident['pid'],
            originalCreateTimeMicros=ident['createTimeMicros'],currentCreateTimeMicros=micros,currentParentPid=parent,
            changesOriginalResearchOutcome=False)
    except psutil.NoSuchProcess:
        return dict(state='ORIGINAL_PID_CURRENTLY_ABSENT',pid=ident['pid'],
            originalCreateTimeMicros=ident['createTimeMicros'],changesOriginalResearchOutcome=False)


def main():
    before=inventory(RUN);p=read(C/'engineering-01-passport.json');receipt=read(RUN/'receipt.json')
    launch=read(C/'engineering-01-launch.json');terminal=read(C/'engineering-01-launch.terminal.json')
    need(p['sourceCommit']==receipt['sourceCommit']==launch['sourceCommit']==terminal['sourceCommit']==Q,'original Qe2 identity')
    wait=parent_wait_known(terminal)
    need(wait['exitCode']==terminal['controllerExitCode']==1 and terminal['watchdogTimedOut'] is False
         and terminal['watchdogActions']==[] and terminal['automaticRetries']==0,'actual adverse parent wait/intervention binding')
    need(file_sha(C/'engineering-01-launch.json')==terminal['launchRecordSha256']
         and file_sha(C/'engineering-01-launch.log')==terminal['logSha256']
         and file_sha(C/'engineering-01-passport.json')==launch['passportSha256']==terminal['passportSha256']==receipt['passportSha256'],
         'original external parent/passport bytes changed')
    source=[]
    for name,expected in p['sourceFiles'].items():
        raw=(R/name).read_bytes()
        original=subprocess.check_output(['git','--no-replace-objects','-C',str(R),'show',Q+':'+name])
        need(raw==original and sha(raw)==expected,'exact frozen source/work bytes changed: '+name)
        source.append(dict(path=name,sha256=expected,bytes=len(raw)))
    sys.path.insert(0,str(R/'experiments/ch7'))
    import lifecycle_audit as oracle
    import mac_process_guard_v3 as guard
    import audit_nested_load as cold_helpers
    from nested_event_index import EventIndex
    need(file_sha(Path(oracle.__file__))=='ffbf69965dd68bcdbf1f7b67ab6e2bda31839ee80ca176a8bc3f9ba2fd77bfef','preserved original cold oracle changed')
    need(file_sha(Path(guard.__file__))==p['sourceFiles']['experiments/ch7/mac_process_guard_v3.py'],'loaded original guard changed')
    journal=(RUN/'lifecycle-journal.jsonl').read_bytes()
    need(len(journal)==receipt['lifecycleJournalBytes']==6286696 and sha(journal)==receipt['lifecycleJournalSha256'], 'stable original complete journal bytes')
    began=time.monotonic();index=EventIndex(journal,oracle._replay,Q,p['policySha256']);state=index.state(len(index.events))
    print(json.dumps(dict(stage='COMPLETE_ORIGINAL_NEGATIVE_JOURNAL_COLD_REPLAY',events=len(state['events']),seconds=time.monotonic()-began)),flush=True)
    cold_helpers.verify_numeric_context(state['events'])
    finite=[v for v in state['leases'].values() if v['role']=='finite']
    need(len(finite)==2534 and len(state['events'])==7605 and not state['launchRefusals'] and not state['discovered'],'actual finite/journal/refusal population')
    need(len(state['scopes'])==1 and all(s['closeSeq'] is not None for s in state['scopes'].values()),'actual original writer scope not closed')
    need(all(v['releaseSeq'] is not None and v['waitSeq'] is not None and type(v['exitCode']) is int and v['exitCode']==0
        and v['absence'] is not None for v in finite),'finite outcome missing/nonzero/unreaped')
    for v in finite:
        e=state['events'][v['waitSeq']-1]
        need(e['event']=='WAIT' and e['data']['waitSource']=='Popen.wait' and e['writer']==v['parentIdentity']
             and e['data']['identity']==v['identity'],'original actual direct-parent finite wait witness')
    final=receipt['registryFinal'];view=final['lifecycleView']
    need(final['status']=='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' and final['scopeClosed'] is True
         and all(final[k]==[] for k in ('unresolvedFiniteLeases','launchRefusals','launchRefusalArtifacts',
             'localDiscoveredIdentities','unleasedDiscoveredIdentities','remainingIdentities'))
         and typed_equal(final['knownFiniteLeases'],finite),'complete original terminal registry differs from cold replay')
    need(view['journalBytes']==len(journal) and view['journalSha256']==sha(journal)
         and view['lastSequence']==len(state['events']),'original terminal journal prefix inconsistent')
    writer=state['events'][0]['writer'];bound=terminal['controllerProcess']
    need(writer==dict(pid=bound['pid'],createTimeMicros=bound['createTimeMicros'],parentPid=bound['parentPid'])
         and writer['pid']==launch['controllerPidFromPopen']==terminal['controllerPidFromPopen']
         and writer['parentPid']==launch['parentProcess']['pid']==terminal['parentProcess']['pid']
         and state['events'][0]['data']['executableSha256']==p['pythonSha256'],'actual original controller birth/parent/interpreter binding')
    probes=dict(controller=original_identity_probe(writer),enclosingLauncher=original_identity_probe(terminal['parentProcess']))
    settling=jsonl(RUN/'settling/telemetry.jsonl');admission=jsonl(RUN/'admission/telemetry.jsonl')
    phases=jsonl(RUN/'phase-events.jsonl');services=jsonl(RUN/'preflight-service-events.jsonl');stages=jsonl(RUN/'stage-events.jsonl')
    preflight=read(RUN/'preflight-continuity.json');policy=read(RUN/'process-policy.json')
    need(len(settling)==1 and admission==[] and len(services)==1 and len(phases)==2 and len(stages)==2,'actual retained negative population')
    row=settling[0];obs=row['processObservation'];sv=receipt['preflightServices'][0]
    decision=oracle._validate_sample(row,policy,journal)
    need(decision['status']==obs['status']==row['streamValidationStatus']=='PASS'
         and obs['blockers']==decision['blockers']==[] and obs['ownedRoots']==obs['ownedProcesses']==[],'retained first raw process guard changed/adverse')
    prefix,cutoff=index.prefix(obs['lifecycle']['journalBytes'],obs['lifecycle']['journalSha256'],obs['lifecycle']['lastSequence'])
    need(len(prefix)==6286107 and obs['lifecycle']['lastSequence']==7604
         and typed_equal(cutoff,oracle._replay(prefix,Q,p['policySha256'])),'exact original sample cutoff/independent cold index disagreement')
    scope=cutoff['scopes'][obs['lifecycle']['scopeId']]
    need(scope['closeSeq'] is None and scope['controllerIdentity']==writer and obs['lifecycle']['controllerIdentity']==writer,
         'future scope closure cannot repair original sample scope')
    frames=oracle._raw_frames(obs,policy);refs=sorted({oracle.node_identity(n) for f in frames for n in f['nodes']})
    projected=[v for v in cutoff['leases'].values() if v['absence'] is None or oracle.identity(v['identity']) in refs]
    need(typed_equal(obs['lifecycle']['leases'],projected) and obs['lifecycle']['referencedIdentities']==[list(x) for x in refs],
         'complete original raw sample lifecycle projection differs')
    need(len({oracle._native_lease(f,cutoff,writer,policy) for f in frames})==2,'actual two distinct native capture leases')
    cold_helpers.verify_command_records(receipt['preflightCommands']+receipt['prefixPaddingCommands'],p['preflightCommands'],
        Q,2530,'combined-parent',writer,state,preflight['schedule']['originMonotonic'])
    counts=Counter(v['stageId'] for v in finite)
    need(counts['observer-native-census']==2,'native actual task count')
    git_count=sum(v['executableSha256']==p['toolExecutableSha256']['git'] for v in finite)
    listener_count=sum(v['executableSha256']==p['toolExecutableSha256']['lsof'] for v in finite)
    need(git_count==2530 and listener_count==2,'actual source-proof/listener task population')
    raw_write=phases[1];need(raw_write['sampleId']==row['sampleId']==sv['sampleId']==services[0]['sampleId'],'original sample/writer/service identity')
    disk={k:v for k,v in sv.items() if k not in ('diagnosticWriteCompletedMonotonic','serviceCompletedMonotonic','fullServiceSeconds')}
    need(typed_equal(disk,services[0]),'original provisional/final service binding')
    start=row['monotonicSeconds'];origin=preflight['schedule']['originMonotonic'];done=sv['serviceCompletedMonotonic']
    need(start<=obs['startedMonotonic']<=obs['finishedMonotonic']<=row['observationCompletedMonotonic']
         <=row['validatorStartedMonotonic']<=row['validatorCompletedMonotonic']<=row['writerStartedMonotonic']
         <=raw_write['writerCompletedMonotonic']<=sv['phaseEventWriteCompletedMonotonic']
         <=sv['diagnosticWriteCompletedMonotonic']<=done,'complete actual adverse service chronology')
    need(sv['fullServiceSeconds']==done-start>2 and 0<=start-origin<=.5
         and row['observationCompletedMonotonic']-start<=2.5 and done<origin+600,
         'exact adverse predicate is complete-service >2, not lateness/2.5capture/600sdeadline')
    need(preflight['status']=='PREFLIGHT_REFUSED' and preflight['reasonCode']=='PREFLIGHT_CALLBACK_FAILED'
         and preflight['validatedSamples']==0 and preflight['phases']['settling']['validatedSamples']==0
         and preflight['runtimeHandoffAnchor'] is None and receipt['nestedEpochMonotonic'] is None
         and receipt['nestedBlocks']==receipt['blockWaits']==[],'recorded phase refusal/counts/runtime cutoff')
    need(not list(RUN.glob('block-*')) and not (RUN/'process-observations.jsonl').exists(), 'unexpected actual nested runtime artifacts')
    need(stages[0]['externalPreparationEpochMonotonic']==launch['preparationEpochMonotonic']==receipt['preparationEpochMonotonic']
         and stages[1]['monotonicSeconds']-launch['preparationEpochMonotonic']<=900,'external full preparation clock bound')
    for key in ('qualificationStarted','backendQualified','scientificAdmission','formalHardwareQualification','independentHumanReview','seedConstructed'):
        need(receipt[key] is False,'scientific gate promoted')
    for key in ('flowBlocks','modelRequests','rendererRequests','freshHeldoutCases','automaticRetries'):
        need(type(receipt[key]) is int and receipt[key]==0,'forbidden operation/typed zero changed')
    need(receipt['lifecycleJournalStable'] is True and before==inventory(RUN),'original writer/hash closure changed')
    numbers=dict(originalRunFiles=len(before['files']),settlingRawSamples=1,settlingRawGuardColdPass=1,
        settlingOriginalStreamValidationPass=1,settlingCompleteEngineeringServicePass=0,settlingControllerValidatedSamples=0,
        settlingPlannedSlots=300,settlingUnattemptedSlots=299,admissionPlannedSlots=60,admissionRawSamples=0,
        originalPhaseEventRecords=2,originalPreflightServiceRecords=1,nestedRuntimeSamples=0,nestedBlocksStarted=0,
        nestedBlocksCompleted=0,sourceProofGitTasks=30,prefixPaddingGitTasks=2500,actualGitFiniteTasks=2530,
        nativeCaptures=2,listenerFiniteTasks=2,finiteLeases=2534,finiteActualParentWaitZero=2534,journalEvents=7605,
        finalJournalBytes=len(journal),originalSampleJournalCutoffBytes=len(prefix),originalSampleJournalCutoffEvents=7604,
        fullServiceSeconds=sv['fullServiceSeconds'],startLatenessSeconds=start-origin,
        rawCaptureSeconds=row['observationCompletedMonotonic']-start,
        outerValidatorSeconds=row['validatorCompletedMonotonic']-row['validatorStartedMonotonic'],
        rawWriteSeconds=raw_write['writerCompletedMonotonic']-row['writerStartedMonotonic'],
        beforeLockHeldSeconds=obs['coordinationLocks']['before']['releasedMonotonic']-obs['coordinationLocks']['before']['acquiredMonotonic'],
        afterLockHeldSeconds=obs['coordinationLocks']['after']['releasedMonotonic']-obs['coordinationLocks']['after']['acquiredMonotonic'],
        beforeLockRequestToAcquireSeconds=obs['coordinationLocks']['before']['acquiredMonotonic']-obs['coordinationLocks']['before']['requestStartedMonotonic'],
        afterLockRequestToAcquireSeconds=obs['coordinationLocks']['after']['acquiredMonotonic']-obs['coordinationLocks']['after']['requestStartedMonotonic'],
        actualPreparationSeconds=stages[1]['monotonicSeconds']-launch['preparationEpochMonotonic'],
        actualControllerExitCode=terminal['controllerExitCode'],modelRequests=receipt['modelRequests'],rendererRequests=receipt['rendererRequests'])
    stability=dict(schema='aijade.ch7.nested-writer-stability.v1',sourceCommit=Q,runRoot=str(RUN),
        parentTerminalSha256=file_sha(C/'engineering-01-launch.terminal.json'),writerStabilityAccepted=True,
        allOriginalWritersTerminatedOrClosed=True,unresolvedWriters=[],
        writerProofKind='SOURCE_BOUND_SCOPE_CLOSE_AND_ACTUAL_PARENT_WAITS',
        journalSha256=sha(journal),closedSourceBoundScopes=1,finiteActualParentWaitZero=len(finite),
        originalEnclosingParentActualWait=wait,currentBirthCorroboration=probes,
        wholeProcessGroupCleanupClaimed=False,wholeMachineCleanupClaimed=False,
        source='Original source-bound actual WAIT/closed scopes plus current exact birth corroboration; no current-PID disappearance repairs an old unknown or refusal.')
    stability_path=C/'audit/e3-writer-stability-01.json';new(stability_path,encoded(stability))
    report=dict(schema='aijade.ch7.nested-partial-cold-negative-audit.v1',
        status='REFUSED_NESTED_PARTIAL_RECORDS_INVENTORIED_NOT_ENGINEERING_ACCEPTED',sourceCommit=Q,
        checkedAt=datetime.now(timezone.utc).isoformat(),writerStabilityAccepted=True,
        writerStabilityProofSha256=file_sha(stability_path),parentTerminalSha256=file_sha(C/'engineering-01-launch.terminal.json'),
        inputFiles=before['files'],originalDirectoryState=before,sourceFiles=source,numbers=numbers,
        actualFirstRawGuardColdDecision=decision,actualAdversePredicate='COMPLETE_ENGINEERING_SERVICE_SECONDS_GREATER_THAN_2',
        originalProducerErrors=receipt['errors'],originalParentErrors=terminal['errors'],
        retainedNulls=dict(settlingElapsedSeconds=preflight['phases']['settling']['elapsedSeconds'],
            settlingEndMonotonic=preflight['phases']['settling']['phaseClock']['endMonotonic'],
            nestedEpochMonotonic=receipt['nestedEpochMonotonic'],runtimeHandoffAnchor=preflight['runtimeHandoffAnchor']),
        scope=dict(terminalRecordIntegrityAccepted=True,fullEngineeringEnvelopeAccepted=False,
            actualRawSampleColdAccepted=True,completeServiceAccepted=False,dualNestedLoadExecuted=False,
            backendQualified=False,formalHardwareQualification=False,independentHumanReview=False,authorApproval=False,
            scientificAcceptance=False,seedConstructed=False,heldoutComparisonComplete=False,table7_3='NOT_RUN'),
        interpretation='One process observation/stream validator passed, but its complete engineering callback exceeded the prospectively frozen two-second service bound. No admission or nested block ran; lock observations are single-stream measurements and do not demonstrate dual-stream repair or causal speedup. All original phase service refusals/nulls remain.',
        originalProducerFieldsModified=False,fullPassAuditorInvoked=False,currentSdkBytesRechecked=False,
        noNewObserverOrModelOrRenderer=True,noWholeMachineOrProcessGroupCleanupClaim=True)
    output=C/'audit/e3-independent-negative-audit-01.json';new(output,encoded(report))
    print(json.dumps(dict(status=report['status'],path=str(output),sha256=file_sha(output),writerStabilitySha256=file_sha(stability_path),numbers=numbers),indent=2),flush=True)


if __name__=='__main__':main()
