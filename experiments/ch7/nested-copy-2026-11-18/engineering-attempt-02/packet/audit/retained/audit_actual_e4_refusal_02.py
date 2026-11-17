"""Independent full-population cold audit of actual E4 settling refusal.

Post-terminal only. Never invokes the complete PASS auditor or a live observer.
Every retained raw record, full prefix, initialization, counter and direct-parent
wait is checked; a finite partial window never becomes nested-load acceptance.
"""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import hashlib,json,math,subprocess,sys,time
import psutil

B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-nested-copy-20261118'
R=B/'.runtime/posix/nested-20261117/worktree'
RUN=B/'.runtime/posix/runs/ch7-nested-copy-20261118/engineering-02'
Q='8231d8b9d67e5188787b69225a72145f2d4c5a63'
sys.path.insert(0,str(C/'archive-tools'))
from packet_common import read,decode,sha,file_sha,encoded,new,inventory,need,typed_equal,parent_wait_known


def jsonl(p):
    raw=p.read_bytes();need(not raw or raw.endswith(b'\n'),'original JSONL truncated')
    return [decode(x) for x in raw.splitlines()]


def probe_original(ident):
    """Corroborate exact original birth, never infer waits from disappearance."""
    try:
        node=psutil.Process(ident['pid']);first=node.create_time();parent=node.ppid();last=node.create_time()
        need(first==last,'current PID birth changed during corroboration')
        micros=round(first*1000000)
        need(micros!=ident['createTimeMicros'],'an original managed identity remains live')
        return dict(state='PID_REUSED_DIFFERENT_BIRTH_NOT_ORIGINAL',pid=ident['pid'],
            originalCreateTimeMicros=ident['createTimeMicros'],currentCreateTimeMicros=micros,currentParentPid=parent)
    except psutil.NoSuchProcess:
        return dict(state='ORIGINAL_PID_CURRENTLY_ABSENT',pid=ident['pid'],originalCreateTimeMicros=ident['createTimeMicros'])


def distribution(values):
    ordered=sorted(values);need(ordered,'empty descriptive distribution')
    def percentile(p):
        at=(len(ordered)-1)*p;i=math.floor(at);j=math.ceil(at)
        return ordered[i]+(ordered[j]-ordered[i])*(at-i)
    return dict(n=len(ordered),minimum=ordered[0],median=percentile(.5),p95=percentile(.95),
        p99=percentile(.99),maximum=ordered[-1],quantileMethod='linear interpolation at (n-1)*p; descriptive original records')


def main():
    before=inventory(RUN);passport_path=C/'engineering-02-passport.json'
    p=read(passport_path);receipt=read(RUN/'receipt.json')
    launch_path=C/'engineering-02-launch.json';terminal_path=C/'engineering-02-launch.terminal.json'
    launch=read(launch_path);terminal=read(terminal_path);wait=parent_wait_known(terminal)
    need(p['sourceCommit']==receipt['sourceCommit']==launch['sourceCommit']==terminal['sourceCommit']==Q,'original Qe3 source identity')
    need(wait['exitCode']==terminal['controllerExitCode']==1 and terminal['watchdogTimedOut'] is False
         and terminal['watchdogActions']==[] and terminal['automaticRetries']==0
         and terminal['engineeringReportDelivered'] is False,'actual adverse outer parent wait/intervention binding')
    need(file_sha(launch_path)==terminal['launchRecordSha256']
         and file_sha(C/'engineering-02-launch.log')==terminal['logSha256']
         and file_sha(passport_path)==launch['passportSha256']==terminal['passportSha256']==receipt['passportSha256'],
         'original actual launch/log/passport byte binding')
    need(file_sha(C/'launch_nested_load.py')==p['launcherSha256']==launch['launcherSha256']==terminal['launcherSha256'],
         'actual executed launcher source binding')
    need((RUN/'engineering-passport.json').read_bytes()==passport_path.read_bytes(),'internal passport body differs')
    source=[]
    for name,expected in p['sourceFiles'].items():
        raw=(R/name).read_bytes();original=subprocess.check_output(['git','--no-replace-objects','-C',str(R),'show',Q+':'+name])
        need(raw==original and sha(raw)==expected,'frozen Git/source work bytes differ: '+name)
        source.append(dict(path=name,sha256=expected,bytes=len(raw)))
    need(len(source)==47 and len(p['observerSources'])==17,'actual complete Qe3 source closure population')
    sys.path.insert(0,str(R/'experiments/ch7'))
    import lifecycle_audit as oracle
    import process_lifecycle as parser
    import mac_process_guard_v3 as guard
    import audit_nested_load as helpers
    import nested_event_index as index_module
    import full_state_clone_cursor as clone
    for module in (oracle,parser,guard,helpers,index_module,clone):helpers.verify_loaded_module(module,R,p['sourceFiles'])
    need(file_sha(oracle.__file__)==helpers.ORACLE_SHA and file_sha(parser.__file__)==helpers.PARSER_SHA,
         'unchanged independent oracle/canonical parser source identity')
    policy=read(RUN/'process-policy.json')
    need(file_sha(RUN/'process-policy.json')==p['policySha256']
         and (RUN/'process-policy.json').read_bytes()==subprocess.check_output(['git','--no-replace-objects','-C',str(R),'show',Q+':'+p['policyPath']]),
         'original source-bound policy bytes')
    helpers.verify_runtime_contract(p['runtime']);helpers.no_science(receipt)
    journal=(RUN/'lifecycle-journal.jsonl').read_bytes()
    need(len(journal)==receipt['lifecycleJournalBytes']==7795321 and sha(journal)==receipt['lifecycleJournalSha256'],
         'stable original complete journal bytes/hash')
    index=index_module.EventIndex(journal,oracle._replay,Q,p['policySha256']);state=index.state(len(index.events))
    helpers.verify_numeric_context(state['events'])
    finite=[v for v in state['leases'].values() if v['role']=='finite']
    need(len(finite)==3142 and len(state['events'])==9429 and not state['launchRefusals'] and not state['discovered'],
         'actual original finite/journal/refusal population')
    need(len(state['scopes'])==1 and all(s['closeSeq'] is not None for s in state['scopes'].values()),'actual writer scope not closed')
    for lease in finite:
        need(lease['releaseSeq'] is not None and lease['waitSeq'] is not None and type(lease['exitCode']) is int
             and lease['exitCode']==0 and lease['absence'] is not None,'actual finite wait/zero/absence missing')
        event=state['events'][lease['waitSeq']-1]
        need(event['event']=='WAIT' and event['data']['waitSource']=='Popen.wait'
             and event['writer']==lease['parentIdentity'] and event['data']['identity']==lease['identity'],
             'actual direct-parent finite Popen.wait witness differs')
    final=receipt['registryFinal'];view=final['lifecycleView'];scope=final['scopeId']
    need(final['status']=='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' and final['scopeClosed'] is True
         and all(final[k]==[] for k in ('unresolvedFiniteLeases','launchRefusals','launchRefusalArtifacts',
            'localDiscoveredIdentities','unleasedDiscoveredIdentities','remainingIdentities'))
         and typed_equal(final['knownFiniteLeases'],finite),'original terminal registry differs from independent cold state')
    need(view['journalBytes']==len(journal) and view['journalSha256']==sha(journal)
         and view['lastSequence']==len(state['events']),'terminal journal prefix consistency')
    writer=state['events'][0]['writer'];bound=terminal['controllerProcess']
    need(writer==dict(pid=bound['pid'],createTimeMicros=bound['createTimeMicros'],parentPid=bound['parentPid'])
         and writer['pid']==launch['controllerPidFromPopen']==terminal['controllerPidFromPopen']
         and writer['parentPid']==launch['parentProcess']['pid']==terminal['parentProcess']['pid']
         and state['events'][0]['data']['executableSha256']==p['pythonSha256'],'actual original birth/parent/interpreter binding')
    helpers.verify_scope_owner(view,scope,writer)
    writer_probes=dict(controller=probe_original(writer),enclosingLauncher=probe_original(terminal['parentProcess']))
    finite_probes=[dict(leaseId=v['leaseId'],**probe_original(v['identity'])) for v in finite]
    settling=jsonl(RUN/'settling/telemetry.jsonl');admission=jsonl(RUN/'admission/telemetry.jsonl')
    phases=jsonl(RUN/'phase-events.jsonl');services=jsonl(RUN/'preflight-service-events.jsonl');stages=jsonl(RUN/'stage-events.jsonl')
    preflight=read(RUN/'preflight-continuity.json');origin=preflight['schedule']['originMonotonic']
    need(len(settling)==len(services)==len(receipt['preflightServices'])==153 and admission==[]
         and len(phases)==154 and len(stages)==2,'actual retained E4 partial population')
    need(phases[0]['event']=='phase-enter' and phases[0]['phase']=='settling'
         and phases[0]['monotonicSeconds']==origin,'actual settling origin/phase entry')
    helpers.verify_command_records(receipt['preflightCommands']+receipt['prefixPaddingCommands'],p['preflightCommands'],
        Q,2530,'combined-parent',writer,state,origin)
    initial=helpers.verify_initialization(RUN,receipt,RUN/'lifecycle-journal.jsonl',index,oracle,parser,p,
        owner=writer,scope=scope,earliest=receipt['prefixPaddingCommands'][-1]['completedMonotonic'],
        latest=origin,anchor=receipt['preparationEpochMonotonic'],budget=900)
    usage=helpers.verify_initialization_usage(initial,settling,receipt,index,p)
    need(stages[0]['externalPreparationEpochMonotonic']==launch['preparationEpochMonotonic']==receipt['preparationEpochMonotonic']
         <=stages[0]['monotonicSeconds']<=receipt['preflightCommands'][0]['startedMonotonic']
         and receipt['prefixPaddingCommands'][-1]['completedMonotonic']<=initial['core']['factoryStartedMonotonic']
         <=initial['writeClock']['completedMonotonic']<=stages[1]['monotonicSeconds']<=origin
         and stages[1]['monotonicSeconds']-launch['preparationEpochMonotonic']<=900,
         'external complete preparation/bootstrap/write clock boundary')
    seen=set();native=set();details=[];key_crosschecks=[];started=time.monotonic();previous_start=previous_done=None
    for n,(row,disk,service,phase) in enumerate(zip(settling,services,receipt['preflightServices'],phases[1:])):
        obs=row['processObservation'];actual=row['monotonicSeconds'];done=service['serviceCompletedMonotonic']
        helpers.verify_scope_owner(obs['lifecycle'],scope,writer)
        need(row['sampleId']==obs['sampleId']==service['sampleId']==disk['sampleId']==phase['sampleId']
             and row['sampleId'] not in seen,'original sample identity/order differs')
        seen.add(row['sampleId'])
        need(type(row['globalIndex']) is int and row['globalIndex']==service['globalIndex']==phase['globalIndex']==n
             and row['globalScheduledMonotonic']==service['scheduledMonotonic']==origin+2*n
             and row['elapsedSeconds']==actual-origin and row['phase']==service['phase']==phase['phase']=='settling',
             'actual original global slot/phase/clock reset')
        need(previous_start is None or 0<actual-previous_start<=3,'original partial global sample coverage gap')
        need(previous_done is None or previous_done<=actual,'same-stream full services overlap')
        previous_start,previous_done=actual,done
        decision=oracle._validate_sample(row,policy,journal)
        need(decision['status']==obs['status']==row['streamValidationStatus']=='PASS'
             and decision['blockers']==obs['blockers']==[] and obs['ownedRoots']==obs['ownedProcesses']==[]
             and row['rssBytes']==0,'actual original raw guard/stream/RSS adverse or changed')
        need(row['observerModuleSha256']==p['sourceFiles']['experiments/ch7/mac_process_guard_v3.py']
             and row['processPolicySha256']==p['policySha256'] and typed_equal(row['observerSources'],p['observerSources']),
             'actual original observer closure differs')
        prefix,cutoff=index.prefix(obs['lifecycle']['journalBytes'],obs['lifecycle']['journalSha256'],obs['lifecycle']['lastSequence'])
        if n in (0,152):
            need(typed_equal(cutoff,oracle._replay(prefix,Q,p['policySha256'])),'key original cutoff disagrees with independent full cold oracle')
            key_crosschecks.append(dict(globalIndex=n,bytes=len(prefix),events=obs['lifecycle']['lastSequence'],sha256=sha(prefix),exactTypedStateMatch=True))
        need(cutoff['scopes'][scope]['closeSeq'] is None and cutoff['scopes'][scope]['controllerIdentity']==writer,
             'future terminal scope close cannot repair original sample')
        frames=oracle._raw_frames(obs,policy);refs=sorted({oracle.node_identity(node) for frame in frames for node in frame['nodes']})
        projected=[v for v in cutoff['leases'].values() if v['absence'] is None or oracle.identity(v['identity']) in refs]
        need(typed_equal(obs['lifecycle']['leases'],projected)
             and typed_equal(obs['lifecycle']['referencedIdentities'],[list(v) for v in refs])
             and typed_equal(obs['lifecycle']['controllers'],[v['leaseId'] for v in projected if v['identity']==writer]),
             'exact independent original prefix view projection differs')
        for frame in frames:
            lease=oracle._native_lease(frame,cutoff,writer,policy);need(lease not in native,'original native lease reused');native.add(lease)
        provisional={k:v for k,v in service.items() if k not in ('diagnosticWriteCompletedMonotonic','serviceCompletedMonotonic','fullServiceSeconds')}
        need(typed_equal(provisional,disk) and phase['event']=='sample-written'
             and actual==service['actualStartMonotonic']
             and actual<=obs['startedMonotonic']<=obs['finishedMonotonic']<=row['observationCompletedMonotonic']
             <=row['validatorStartedMonotonic']<=row['validatorCompletedMonotonic']<=row['writerStartedMonotonic']
             <=phase['writerCompletedMonotonic']<=service['phaseEventWriteCompletedMonotonic']
             <=service['diagnosticWriteCompletedMonotonic']<=done
             and service['fullServiceSeconds']==done-actual and 0<=actual-(origin+2*n)<=.5
             and row['observationCompletedMonotonic']-actual<=2.5 and done<origin+600,
             'complete original raw/validator/writer/diagnostic/full-service chronology')
        need((service['fullServiceSeconds']<=2) is (n<152),'actual152 service passes then single final refusal differs')
        details.append(dict(globalIndex=n,sampleId=row['sampleId'],prefixBytes=len(prefix),prefixEvents=obs['lifecycle']['lastSequence'],
            prefixSha256=sha(prefix),rawGuardColdStatus=decision['status'],originalStreamStatus=row['streamValidationStatus'],
            fullServiceSeconds=service['fullServiceSeconds'],fullServiceWithinTwoSeconds=service['fullServiceSeconds']<=2,
            startLatenessSeconds=actual-(origin+2*n),rawCaptureSeconds=row['observationCompletedMonotonic']-actual,
            outerValidatorSeconds=row['validatorCompletedMonotonic']-row['validatorStartedMonotonic'],
            rawWriteSeconds=phase['writerCompletedMonotonic']-row['writerStartedMonotonic'],
            beforeLockHeldSeconds=obs['coordinationLocks']['before']['releasedMonotonic']-obs['coordinationLocks']['before']['acquiredMonotonic'],
            afterLockHeldSeconds=obs['coordinationLocks']['after']['releasedMonotonic']-obs['coordinationLocks']['after']['acquiredMonotonic'],
            beforeLockRequestToAcquireSeconds=obs['coordinationLocks']['before']['acquiredMonotonic']-obs['coordinationLocks']['before']['requestStartedMonotonic'],
            afterLockRequestToAcquireSeconds=obs['coordinationLocks']['after']['acquiredMonotonic']-obs['coordinationLocks']['after']['requestStartedMonotonic']))
        if (n+1)%10==0 or n==152:print(json.dumps(dict(stage='ALL_ORIGINAL_E4_NEGATIVE_RAW_GUARD_AND_FULL_PREFIX_COLD_REPLAY',samples=n+1,total=153,seconds=time.monotonic()-started)),flush=True)
    counts=Counter(v['stageId'] for v in finite)
    git_count=sum(v['executableSha256']==p['toolExecutableSha256']['git'] for v in finite)
    listener_count=sum(v['executableSha256']==p['toolExecutableSha256']['lsof'] for v in finite)
    child_leases=[v for v in finite if v['stageId'] in ['nested-block-'+str(n) for n in range(1,5)]]
    need(git_count==2530 and counts['observer-native-census']==listener_count==len(native)==306
         and len(child_leases)==0 and len(finite)==2530+4*len(settling),'complete actual Git/native/listener/child population')
    chain_bytes={};nonfinite_bytes=0
    for line,event in zip(journal.splitlines(keepends=True),state['events']):
        if event['event'] in ('FINITE_REGISTER','RELEASE','WAIT'):chain_bytes.setdefault(event['data']['leaseId'],[]).append(len(line))
        else:nonfinite_bytes+=len(line)
    need(len(chain_bytes)==3142 and all(len(v)==3 and sum(v)<=2560 for v in chain_bytes.values()) and nonfinite_bytes<=65536,
         'actual frozen numeric/finite-chain serialization envelope')
    need(preflight['status']=='PREFLIGHT_REFUSED' and preflight['reasonCode']=='PREFLIGHT_CALLBACK_FAILED'
         and preflight['samples']==153 and preflight['validatedSamples']==preflight['phases']['settling']['validatedSamples']==152
         and preflight['runtimeHandoffAnchor'] is None and preflight['windowReset'] is False
         and preflight['phases']['settling']['elapsedSeconds'] is None
         and preflight['phases']['settling']['phaseClock']['endMonotonic'] is None
         and preflight['phases']['settling']['coverage']['coverageComplete'] is False
         and receipt['nestedEpochMonotonic'] is None and receipt['nestedBlocks']==receipt['blockWaits']==[],
         'recorded adverse phase counts/nulls/window boundary differ')
    need(not list(RUN.glob('block-*')) and not (RUN/'process-observations.jsonl').exists(),'unexpected actual nested runtime artifacts')
    need(details[-1]['prefixBytes']==7794731 and details[-1]['prefixEvents']==9428
         and details[-1]['fullServiceSeconds']==2.0032313160190824,'actual adverse service/cutoff differs')
    need(receipt['lifecycleJournalStable'] is True and before==inventory(RUN),'original file population/hash changed during cold audit')
    need(all(file_sha(R/v['path'])==v['sha256'] for v in source),'frozen source changed during cold audit')
    last=details[-1]
    numbers=dict(originalRunFiles=len(before['files']),settlingRawSamples=153,settlingRawGuardColdPass=153,
        settlingOriginalStreamValidationPass=153,settlingCompleteEngineeringServicePass=152,settlingControllerValidatedSamples=152,
        settlingPlannedSlots=300,settlingUnattemptedSlots=147,admissionPlannedSlots=60,admissionRawSamples=0,
        originalPhaseEventRecords=len(phases),originalPreflightServiceRecords=len(services),nestedRuntimeSamples=0,
        nestedBlocksStarted=len(child_leases),nestedBlocksCompleted=0,sourceProofGitTasks=len(receipt['preflightCommands']),
        prefixPaddingGitTasks=len(receipt['prefixPaddingCommands']),actualGitFiniteTasks=git_count,nativeCaptures=len(native),
        listenerFiniteTasks=listener_count,finiteLeases=len(finite),finiteActualParentWaitZero=len(finite),journalEvents=len(state['events']),
        finalJournalBytes=len(journal),originalSampleJournalCutoffBytes=last['prefixBytes'],originalSampleJournalCutoffEvents=last['prefixEvents'],
        fullServiceSeconds=last['fullServiceSeconds'],startLatenessSeconds=last['startLatenessSeconds'],
        rawCaptureSeconds=last['rawCaptureSeconds'],outerValidatorSeconds=last['outerValidatorSeconds'],rawWriteSeconds=last['rawWriteSeconds'],
        beforeLockHeldSeconds=last['beforeLockHeldSeconds'],afterLockHeldSeconds=last['afterLockHeldSeconds'],
        beforeLockRequestToAcquireSeconds=last['beforeLockRequestToAcquireSeconds'],afterLockRequestToAcquireSeconds=last['afterLockRequestToAcquireSeconds'],
        actualPreparationSeconds=stages[1]['monotonicSeconds']-receipt['preparationEpochMonotonic'],
        initializationSeconds=initial['core']['elapsedSeconds'],initializationThroughWriteSeconds=initial['writeClock']['completedMonotonic']-initial['core']['factoryStartedMonotonic'],
        initializationPrefixBytes=initial['core']['prefixBytes'],initializationPrefixEvents=initial['core']['lastSequence'],
        actualLastElapsedSeconds=settling[-1]['elapsedSeconds'],actualControllerExitCode=terminal['controllerExitCode'],
        maximumFiniteChainBytes=max(map(sum,chain_bytes.values())),nonFiniteEventBytes=nonfinite_bytes,
        modelRequests=receipt['modelRequests'],rendererRequests=receipt['rendererRequests'])
    stability=dict(schema='aijade.ch7.nested-writer-stability.v1',sourceCommit=Q,runRoot=str(RUN),parentTerminalSha256=file_sha(terminal_path),
        writerStabilityAccepted=True,allOriginalWritersTerminatedOrClosed=True,unresolvedWriters=[],
        writerProofKind='SOURCE_BOUND_SCOPE_CLOSE_AND_ACTUAL_PARENT_WAITS',journalSha256=sha(journal),
        closedSourceBoundScopes=1,finiteActualParentWaitZero=len(finite),originalEnclosingParentActualWait=wait,
        currentBirthCorroboration=writer_probes,exactFiniteBirthCorroborations=finite_probes,
        wholeProcessGroupCleanupClaimed=False,wholeMachineCleanupClaimed=False,
        source='Actual source-bound WAIT/closed scope plus exact original PID/birth corroboration; current disappearance never repairs old unknowns or refusal.')
    stability_path=C/'audit/e4-writer-stability-01.json';new(stability_path,encoded(stability))
    details_path=C/'audit/e4-all-raw-cold-details-01.json';new(details_path,encoded(dict(schema='aijade.ch7.e4-partial-all-raw-cold-details.v1',sourceCommit=Q,samples=details)))
    report=dict(schema='aijade.ch7.e4-partial-cold-negative-audit.v1',
        status='REFUSED_NESTED_PARTIAL_RECORDS_INVENTORIED_NOT_ENGINEERING_ACCEPTED',sourceCommit=Q,checkedAt=datetime.now(timezone.utc).isoformat(),
        writerStabilityAccepted=True,writerStabilityProofSha256=file_sha(stability_path),parentTerminalSha256=file_sha(terminal_path),
        inputFiles=before['files'],originalDirectoryState=before,sourceFiles=source,numbers=numbers,
        allRawColdDetailsSha256=file_sha(details_path),initializationAudit=usage,
        keyIndependentOldOraclePrefixCrosschecks=key_crosschecks,
        auditMethod='FrozenE4 method: independent original full oracle final once via EventIndex plus initialization/first/last key-prefix exact typed crosschecks; every153 raw guard original full cold replay and every actual prefix hash/view/index. No production PASS cache.',
        extraPosthocOracleAuditStopped='posthoc-extra-oracle-stop-01.json; preserved01 source/log; no engineering measurement or refusal changed',
        actualAdversePredicate='COMPLETE_ENGINEERING_SERVICE_SECONDS_GREATER_THAN_2',
        originalProducerErrors=receipt['errors'],originalParentErrors=terminal['errors'],
        descriptiveDistributions={k:distribution([v[k] for v in details]) for k in ('fullServiceSeconds','rawCaptureSeconds','outerValidatorSeconds',
            'rawWriteSeconds','startLatenessSeconds','beforeLockHeldSeconds','afterLockHeldSeconds','beforeLockRequestToAcquireSeconds','afterLockRequestToAcquireSeconds')},
        retainedNulls=dict(settlingElapsedSeconds=preflight['phases']['settling']['elapsedSeconds'],
            settlingEndMonotonic=preflight['phases']['settling']['phaseClock']['endMonotonic'],nestedEpochMonotonic=receipt['nestedEpochMonotonic'],
            runtimeHandoffAnchor=preflight['runtimeHandoffAnchor']),completeEngineeringAuditAccepted=False,
        scope=dict(terminalRecordIntegrityAccepted=True,fullEngineeringEnvelopeAccepted=False,all153OriginalRawGuardsColdAccepted=True,
            actualCompleteServicesAccepted=152,completeSettlingAccepted=False,dualNestedLoadExecuted=False,
            backendQualified=False,formalHardwareQualification=False,independentHumanReview=False,authorApproval=False,
            scientificAcceptance=False,seedConstructed=False,heldoutComparisonComplete=False,table7_3='NOT_RUN'),
        interpretation='153 original raw guards and stream validations passed; 152 full engineering services were within two seconds and final index152 exceeded by0.003231316s. Settling stopped, leaving147 unattempted slots and60 admission slots; no nested controllers were registered. This is a retained partial refusal, not full nested validation, a startup improvement, or causal speedup evidence.',
        originalProducerFieldsModified=False,fullPassAuditorInvoked=False,currentSdkBytesRechecked=False,
        noNewObserverOrModelOrRenderer=True,noWholeMachineOrProcessGroupCleanupClaim=True)
    output=C/'audit/e4-independent-negative-audit-01.json';new(output,encoded(report))
    print(json.dumps(dict(status=report['status'],path=str(output),sha256=file_sha(output),writerStabilitySha256=file_sha(stability_path),numbers=numbers),indent=2),flush=True)


if __name__=='__main__':main()
