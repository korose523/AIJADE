"""Re-derive retained E5 partial populations/clocks; never a cold kernel audit.

This result-specific transport verifier is separate from prior immutable
single-sample predicate. It verifies all retained records and initializer
references without claiming an unexecuted phase or complete nested acceptance.
"""
from packet_common import decode,need,sha,typed_equal,parent_wait_known
import json,math


def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def verify(body,summary,audit,root):
    base='run/engineering-03/'
    rec=decode(body(base+'receipt.json'));pre=decode(body(base+'preflight-continuity.json'))
    passport=decode(body('publication/engineering-03-passport.json'))
    terminal=decode(body('launch/engineering-03-launch.terminal.json'));parent_wait_known(terminal)
    rows=[decode(x) for x in body(base+'settling/telemetry.jsonl').splitlines()]
    admission=[decode(x) for x in body(base+'admission/telemetry.jsonl').splitlines()]
    phases=[decode(x) for x in body(base+'phase-events.jsonl').splitlines()]
    disks=[decode(x) for x in body(base+'preflight-service-events.jsonl').splitlines()]
    stages=[decode(x) for x in body(base+'stage-events.jsonl').splitlines()]
    journal=body(base+'lifecycle-journal.jsonl');events=[];previous='0'*64
    for seq,line in enumerate(journal.splitlines(),1):
        event=decode(line);payload={k:v for k,v in event.items() if k!='sha256'}
        need(type(event['seq']) is int and event['seq']==seq and event['previousSha256']==previous
             and sha(canonical(payload))==event['sha256'],'retained E5 journal canonical hash chain differs')
        need(event['sourceCommit']==summary['sourceCommit'] and event['policySha256']==passport['policySha256'],
             'retained E5 journal source/policy differs')
        events.append(event);previous=event['sha256']
    need(journal.endswith(b'\n') and sha(journal)==rec['lifecycleJournalSha256']
         and len(journal)==rec['lifecycleJournalBytes'],'retained E5 final journal identity differs')
    finite={v['data']['leaseId']:v for v in events if v['event']=='FINITE_REGISTER'}
    waits={v['data']['leaseId']:v for v in events if v['event']=='WAIT'}
    need(set(finite)==set(waits) and all(waits[k]['data']['waitSource']=='Popen.wait'
         and type(waits[k]['data']['exitCode']) is int and waits[k]['data']['exitCode']==0
         and waits[k]['data']['identity']==v['data']['identity'] and waits[k]['writer']==v['data']['parentIdentity']
         for k,v in finite.items()),'retained E5 finite actual owner wait population differs')
    services=rec['preflightServices'];n=len(rows)
    need(n==174 and admission==[] and len(services)==len(disks)==n and len(phases)==n+1,
         'actual E5 partial retained population differs')
    need(pre['status']=='PREFLIGHT_REFUSED' and pre['validatedSamples']==173
         and pre['phases']['settling']['validatedSamples']==173 and pre['runtimeHandoffAnchor'] is None
         and pre['phases']['settling']['elapsedSeconds'] is None
         and pre['phases']['settling']['phaseClock']['endMonotonic'] is None
         and rec['nestedEpochMonotonic'] is None and rec['nestedBlocks']==rec['blockWaits']==[]
         and terminal['controllerExitCode']==1,'retained E5 refusal/counts/nulls promoted')
    origin=pre['schedule']['originMonotonic'];details=[]
    init_raw=body(base+'initialization.json');init=decode(init_raw);writer=rec['initializationWriteClock']
    need(typed_equal(init,rec['initialization']) and writer['sha256']==sha(init_raw)
         and type(init['canonicalParserRuns']) is int and init['canonicalParserRuns']==1
         and type(init['detachedCacheCloneOperations']) is int and init['detachedCacheCloneOperations']==1
         and init['processObservationPerformed'] is False and init['nativeApiOrModelRequest'] is False
         and init['verdictGranted'] is False and init['independentMutableReplayStates'] is True,
         'retained E5 initializer bytes/typed clone/observation scope differs')
    initial_prefix=journal[:init['prefixBytes']]
    need(sha(initial_prefix)==init['prefixSha256'] and len(initial_prefix.splitlines())==init['lastSequence']
         and init['cursorSourceSha256']==passport['onlineReplaySourceSha256']
         ==passport['sourceFiles']['experiments/ch7/newowned_guard_cursor.py']
         and init['scopeId']==rec['registryFinal']['scopeId'],'retained E5 initializer prefix/source/scope differs')
    reference=dict(path=writer['path'],sha256=writer['sha256'],mode=init['mode'],prefixBytes=init['prefixBytes'],
        prefixSha256=init['prefixSha256'],lastSequence=init['lastSequence'],scopeId=init['scopeId'],
        sourceCommit=init['sourceCommit'],policySha256=init['policySha256'],cursorSourceSha256=init['cursorSourceSha256'],ownerId=init['innerOwner']['ownerId'],ownerRole='inner',
        pairedOwnerId=init['outerOwner']['ownerId'],guardPredicateAstSha256=init['guardPredicateAstSha256'])
    previous_count=init['prefixBytes'];previous_seq=init['lastSequence'];read_sum=compare_sum=tail_bytes=tail_events=0
    cold_raw=body('audit/retained/e5-full-cold-decisions-01.jsonl')
    need(sha(cold_raw)==audit['actualAll174FullColdDecisionsSha256'],'actual full cold decision export hash differs')
    cold_export=[decode(v) for v in cold_raw.splitlines()]
    need(len(cold_export)==174,'all174 complete cold decisions must remain')
    decisions={}
    for i,(row,service,disk,phase) in enumerate(zip(rows,services,disks,phases[1:])):
        obs=row['processObservation'];view=obs['lifecycle'];start=row['monotonicSeconds'];done=service['serviceCompletedMonotonic']
        if i<173:
            need(row['streamValidationStatus']==obs['status']=='PASS' and obs['blockers']==[] and row['rssBytes']==0,
                 'retained original first173 E5 raw/stream PASS was modified')
        else:
            need(row['streamValidationStatus']=='REFUSED' and obs['status']=='UNKNOWN' and row['rssBytes'] is None
                 and obs['ownedRssBytes'] is None and obs['blockers']==[dict(code='LISTENER_OBSERVATION_UNKNOWN',severity='UNKNOWN',phase='before')]
                 and obs['evidence']['before']['listener']==dict(state='UNKNOWN',code='LISTENER_ENUMERATION_UNKNOWN'),
                 'retained final E5 raw UNKNOWN/stream refusal/None RSS was modified')
        actual_decision=dict(status=obs['status'],blockers=obs['blockers'],ownedProcesses=obs['ownedProcesses'],ownedRssBytes=obs['ownedRssBytes'])
        exported=cold_export[i]
        need(exported['sourceCommit']==summary['sourceCommit'] and exported['globalIndex']==i
             and exported['sampleId']==row['sampleId'] and typed_equal(exported['actualFullTypedDecision'],actual_decision),
             'actual complete typed cold decision export differs from retained raw')
        decisions[row['sampleId']]=actual_decision
        need(type(row['globalIndex']) is int and row['globalIndex']==i==service['globalIndex']==phase['globalIndex']
             and row['sampleId']==obs['sampleId']==service['sampleId']==disk['sampleId']==phase['sampleId']
             and row['globalScheduledMonotonic']==service['scheduledMonotonic']==origin+2*i,
             'retained E5 complete original sample/phase/slot population differs')
        expected_disk={k:v for k,v in service.items() if k not in ('diagnosticWriteCompletedMonotonic','serviceCompletedMonotonic','fullServiceSeconds')}
        need(typed_equal(expected_disk,disk) and done-start==service['fullServiceSeconds']
             and 0<=start-(origin+2*i)<=.5 and row['observationCompletedMonotonic']-start<=2.5
             and service['fullServiceSeconds']<=2,'retained E5 actual full-service refusal distribution differs')
        prefix=journal[:view['journalBytes']]
        need(prefix.endswith(b'\n') and sha(prefix)==view['journalSha256']
             and len(prefix.splitlines())==view['lastSequence'] and view['scopeId']==init['scopeId']
             and typed_equal(obs['onlineReplayPreparation'],reference), 'retained E5 actual cutoff/init reference differs')
        need(view['journalBytes']>=previous_count and view['lastSequence']>=previous_seq,'retained E5 prefix regressed')
        read_sum+=view['journalBytes'];compare_sum+=previous_count
        tail_bytes+=view['journalBytes']-previous_count;tail_events+=view['lastSequence']-previous_seq
        previous_count,previous_seq=view['journalBytes'],view['lastSequence']
        details.append(dict(fullServiceSeconds=service['fullServiceSeconds'],startLatenessSeconds=start-(origin+2*i),
            rawCaptureSeconds=row['observationCompletedMonotonic']-start,
            outerValidatorSeconds=row['validatorCompletedMonotonic']-row['validatorStartedMonotonic'],
            rawWriteSeconds=phase['writerCompletedMonotonic']-row['writerStartedMonotonic'],
            beforeLockHeldSeconds=obs['coordinationLocks']['before']['releasedMonotonic']-obs['coordinationLocks']['before']['acquiredMonotonic'],
            afterLockHeldSeconds=obs['coordinationLocks']['after']['releasedMonotonic']-obs['coordinationLocks']['after']['acquiredMonotonic'],
            beforeLockRequestToAcquireSeconds=obs['coordinationLocks']['before']['acquiredMonotonic']-obs['coordinationLocks']['before']['requestStartedMonotonic'],
            afterLockRequestToAcquireSeconds=obs['coordinationLocks']['after']['acquiredMonotonic']-obs['coordinationLocks']['after']['requestStartedMonotonic']))
    for label,initial_calls,initial_events,initial_bytes,population,role in [
            ('innerCursor',1,init['lastSequence'],init['prefixBytes'],rows,'inner'),('outerCursor',0,0,0,rows[:-1],'outer')]:
        stats=rec[label];last_count=init['prefixBytes'];last_seq=init['lastSequence'];read_total=compare_total=0
        for row in population:
            view=row['processObservation']['lifecycle'];read_total+=view['journalBytes'];compare_total+=last_count
            last_count,last_seq=view['journalBytes'],view['lastSequence']
        calls=len(population);parsed_bytes=last_count-init['prefixBytes'];parsed_events=last_seq-init['lastSequence']
        logical=sum(len(canonical(decisions[row['sampleId']])) for row in population)
        retained_leases=sum(e['event'] in ('CONTROLLER_REGISTER','FINITE_REGISTER') for e in events[:last_seq])
        expected=dict(calls=calls+initial_calls,parsedEvents=parsed_events+initial_events,parsedBytes=parsed_bytes+initial_bytes,
            fullPrefixReadBytes=read_total+initial_bytes,fullPrefixComparedBytes=compare_total,
            hashUpdatedBytes=parsed_bytes+initial_bytes,snapshotCopies=0,initializationStateClones=0 if role=='inner' else 1,
            privateStateValidations=calls+initial_calls,guardEvaluations=calls,detachedDecisionCopies=calls,
            detachedDecisionCanonicalBytes=logical,bootstrapReceivedStates=1,latestPrefixBytes=last_count,frontierScopes=1,
            builtinTailEvents=parsed_events,builtinColdStates=1 if role=='inner' else 0,failures=0,coldOldPrefixReplays=0,
            poisoned=False,retainedEvents=last_seq,retainedLeases=retained_leases,
            ownerId=init[role+'Owner']['ownerId'],ownerRole=role)
        need(all(typed_equal(stats[k],v) for k,v in expected.items()),'retained E5 actual per-owner prefix/read/compare/tail/eval/canonical counter population differs')
        need(typed_equal(audit['initializationAudit']['results'][role]['finalStatistics'],stats),
             'retained independent per-owner initialization audit/final counters differ')
    last=details[-1];last_view=rows[-1]['processObservation']['lifecycle']
    original_files=decode(body('metadata/run-directory-state.json'))['files']
    child_leases=[v for v in finite.values() if v['data']['stageId'] in ['nested-block-'+str(i) for i in range(1,5)]]
    chain={};other=0
    for line,event in zip(journal.splitlines(keepends=True),events):
        if event['event'] in ('FINITE_REGISTER','RELEASE','WAIT'):chain.setdefault(event['data']['leaseId'],[]).append(len(line))
        else:other+=len(line)
    values=dict(originalRunFiles=len(original_files),settlingRawSamples=n,settlingRawGuardColdPass=sum(v['processObservation']['status']=='PASS' for v in rows),settlingRawGuardColdUnknown=sum(v['processObservation']['status']=='UNKNOWN' for v in rows),
        settlingOriginalStreamValidationPass=sum(v['streamValidationStatus']=='PASS' for v in rows),settlingOriginalStreamValidationRefused=sum(v['streamValidationStatus']=='REFUSED' for v in rows),
        settlingCompleteEngineeringServicePass=sum(v['streamValidationStatus']=='PASS' for v in rows),settlingCompleteServiceClockWithinTwoSeconds=sum(v['fullServiceSeconds']<=2 for v in details),
        settlingControllerValidatedSamples=pre['validatedSamples'],settlingPlannedSlots=300,settlingUnattemptedSlots=300-n,
        admissionPlannedSlots=60,admissionRawSamples=len(admission),originalPhaseEventRecords=len(phases),originalPreflightServiceRecords=len(disks),
        nestedRuntimeSamples=0,nestedBlocksStarted=len(child_leases),nestedBlocksCompleted=len(rec['nestedBlocks']),
        sourceProofGitTasks=len(rec['preflightCommands']),prefixPaddingGitTasks=len(rec['prefixPaddingCommands']),
        actualGitFiniteTasks=sum(v['data']['executableSha256']==passport['toolExecutableSha256']['git'] for v in finite.values()),
        nativeCaptures=sum(v['data']['stageId']=='observer-native-census' for v in finite.values()),
        listenerFiniteTasks=sum(v['data']['executableSha256']==passport['toolExecutableSha256']['lsof'] for v in finite.values()),
        finiteLeases=len(finite),finiteActualParentWaitZero=len(waits),journalEvents=len(events),finalJournalBytes=len(journal),
        originalSampleJournalCutoffBytes=last_view['journalBytes'],originalSampleJournalCutoffEvents=last_view['lastSequence'],
        **last,actualPreparationSeconds=stages[1]['monotonicSeconds']-rec['preparationEpochMonotonic'],
        initializationSeconds=init['elapsedSeconds'],initializationThroughWriteSeconds=writer['completedMonotonic']-init['factoryStartedMonotonic'],
        initializationPrefixBytes=init['prefixBytes'],initializationPrefixEvents=init['lastSequence'],actualLastElapsedSeconds=rows[-1]['elapsedSeconds'],
        actualControllerExitCode=terminal['controllerExitCode'],innerActualGuardEvaluations=rec['innerCursor']['guardEvaluations'],outerActualGuardEvaluations=rec['outerCursor']['guardEvaluations'],
        innerDetachedDecisionCanonicalBytes=rec['innerCursor']['detachedDecisionCanonicalBytes'],outerDetachedDecisionCanonicalBytes=rec['outerCursor']['detachedDecisionCanonicalBytes'],
        finalOuterValidatorCalledCursor=False,originalLastOwnedRssBytes=rows[-1]['rssBytes'],maximumFiniteChainBytes=max(map(sum,chain.values())),nonFiniteEventBytes=other,
        modelRequests=rec['modelRequests'],rendererRequests=rec['rendererRequests'])
    need(typed_equal(values,audit['numbers']),'coherently changed E5 negative numbers differ from all retained actual originals')
    return dict(status='ALL_E5_RETAINED_PARTIAL_POPULATIONS_CLOCKS_AND_COUNTERS_REDERIVED_NOT_QUALIFIED',
        numbers=len(values),actualRawRecords=n,actualKernelColdReplayRepeated=False,completeEngineeringAuditAccepted=False,
        scientificQualification=False,interpretation='Independent post-terminal cold audit remains separately hash bound; transport replay grants no full settling, nested-load or scientific acceptance.')
