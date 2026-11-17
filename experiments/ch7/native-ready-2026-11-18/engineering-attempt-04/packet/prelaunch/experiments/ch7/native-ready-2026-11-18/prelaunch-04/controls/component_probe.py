"""One fixed 10+10 development comparison; no engineering/qualification entry."""
from pathlib import Path
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import math
import os
import selectors
import signal
import statistics
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
BASE=Path('/Volumes/Untitled/AIJADE')
sys.path.insert(0,str(HERE/'candidate/experiments/ch7'))
import process_lifecycle as life
import native_exec_registry as native

PARSER=HERE/'listener-evidence/listener_evidence.py'
PARSER_SHA='45617a0a4ee8cec0c10f76151adfe4bd82f9fab4ca67dcd5b78b0f3a444ac2f2'
spec=importlib.util.spec_from_file_location('fixed_listener_component_parser',PARSER)
parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
ARGV=['/usr/sbin/lsof','-nP','-iTCP:11434','-sTCP:LISTEN','-FpfPtTn']
PRIOR_CHAINS=6308
ACTUAL_PER_HALF=10
CAP=65536
WHOLE_SECONDS=.5
SOURCE_ID='0'*40  # Explicit synthetic component context, never a Git commit claim.


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):return life.canonical(value)
def write_new(path,value):
    with path.open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())


def source_paths():
    return {'caller':Path(__file__),'parser':PARSER,'adapter':Path(native.__file__),
        'CSource':HERE/'candidate/experiments/ch7/lifecycle_exec_native.c',
        'lifecycle':Path(life.__file__),'legacyShim':Path(life.__file__).with_name('lifecycle_exec.py'),
        'coldOracle':Path(life.__file__).with_name('lifecycle_audit.py')}


def check_sources(plan):
    for key,path in source_paths().items():
        if sha(path)!=plan['sourcePins'][key]:raise ValueError('component source drift: '+key)
    if sha(plan['nativeBinding']['binaryPath'])!=plan['nativeBinding']['binarySha256']:
        raise ValueError('component native binary drift')
    if sha(ARGV[0])!=plan['lsofExecutableSha256']:raise ValueError('component lsof executable drift')


def prepare(plan,root):
    policies={};registries={};initials={}
    for method in ('legacy','native'):
        directory=root/method;directory.mkdir()
        shim=plan['nativeBinding']['binarySha256'] if method=='native' else native.LEGACY_SHIM_SHA256
        policy=dict(lifecycle=dict(execShimSha256=shim,coordinationLockPath=str(directory/'capture.lock')),
            listenerEvidence=dict(mode=parser.MODE,moduleSha256=PARSER_SHA,command=ARGV,
                executableSha256=plan['lsofExecutableSha256'],maxSeconds=.5,maxBytes=CAP))
        if method=='native':policy.update(lifecycleExecMode=native.MODE,nativeExec=plan['nativeBinding'])
        policy_sha=life.digest(canonical(policy));policies[method]=policy
        registry=native.registry_for_policy(policy,directory/'lifecycle-journal.jsonl',stage='native-ready-component',
            source_commit=SOURCE_ID,policy_sha256=policy_sha,capture_lock_path=Path(policy['lifecycle']['coordinationLockPath']))
        registries[method]=registry;initials[method]=registry.path.read_bytes()
        write_new(directory/'process-policy.json',policy)
    clock_base=math.ceil(time.monotonic())
    summaries={}
    for method,registry in registries.items():
        original=initials[method];state=life.replay_journal(original);previous=state['events'][-1]['sha256']
        seq=state['lastSequence'];parts=[original];maximum_chain=0
        owner=registry.writer;shim=policies[method]['lifecycle']['execShimSha256']
        for index in range(PRIOR_CHAINS):
            lease='f'+format(index+1,'031x')
            ident=dict(pid=300000+index,createTimeMicros=owner['createTimeMicros']+10000+index,parentPid=owner['pid'])
            mono=clock_base+(index+1)*.000001
            data=dict(leaseId=lease,role='finite',stageId='native-component-prior',identity=ident,parentIdentity=owner,
                commandSha256='a'*64,executableSha256='b'*64,readyMonotonic=mono-.0000001,
                shimSha256=shim,identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD')
            chain=[]
            for event_name,event_data,event_clock in (
                    ('FINITE_REGISTER',data,mono),('RELEASE',dict(leaseId=lease),mono+.0000001),
                    ('WAIT',dict(leaseId=lease,identity=ident,exitCode=0,waitSource='Popen.wait',reapedMonotonic=mono+.0000002),mono+.0000003)):
                seq+=1
                event=dict(schema=life.EVENT_SCHEMA,seq=seq,event=event_name,monotonicSeconds=event_clock,
                    runId=registry.run_id,writer=owner,sourceCommit=SOURCE_ID,policySha256=registry.policy_sha256,
                    data=event_data,previousSha256=previous)
                event['sha256']=life.digest(canonical(event));previous=event['sha256']
                chain.append(canonical(event)+b'\n')
            maximum_chain=max(maximum_chain,sum(map(len,chain)));parts.extend(chain)
        body=b''.join(parts)
        if maximum_chain>2560 or len(body)>=16*1024**2 or seq>20000:raise ValueError('synthetic component population exceeds declared bounds')
        # All original producer bytes survive unchanged. Added history is an
        # explicitly synthetic canonical fixture, never actual Popen evidence.
        with registry.path.open('ab') as stream:stream.write(body[len(original):]);stream.flush();os.fsync(stream.fileno())
        if registry.path.read_bytes()!=body:raise ValueError('synthetic journal body differs')
        started=time.monotonic();loaded=registry._state();completed=time.monotonic()
        if loaded['lastSequence']!=seq or len(loaded['leases'])!=PRIOR_CHAINS+1:raise ValueError('synthetic canonical population differs')
        if loaded['events'][-1]['monotonicSeconds']>completed:raise ValueError('synthetic prior timestamps have not passed; refuse without waiting/retrying')
        summaries[method]=dict(initialActualProducerBytes=len(original),initialActualProducerSha256=life.digest(original),
            syntheticPriorChains=PRIOR_CHAINS,syntheticPriorEventSequences=[3,seq],
            actualPriorPopenRuns=0,syntheticWaitSourceIsFixtureEncodingNotObservedWait=True,
            prefixBytes=len(body),prefixSha256=life.digest(body),lastSequence=seq,maximumSyntheticChainBytes=maximum_chain,
            canonicalPreparationStartedMonotonic=started,canonicalPreparationCompletedMonotonic=completed,
            generationManifestScope='Original first two producer events plus explicitly synthetic prior finite events; no padding fields.')
    return policies,registries,summaries


def capture(registry,method,policy,plan):
    started=time.monotonic();deadline=started+WHOLE_SECONDS
    handle=None;error=None;out=bytearray();err=bytearray();eof={'stdout':False,'stderr':False};native_evidence=None
    source_before_ok=False;source_after_ok=False
    selector=selectors.DefaultSelector()
    try:
        check_sources(plan);source_before_ok=True
        left=deadline-time.monotonic()
        if left<=0:raise TimeoutError('whole listener deadline exhausted before launch')
        handle=registry.launch(ARGV,stage='listener-component',ready_timeout=min(life.READY_SECONDS,left),
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False)
        for stream,name in [(handle.stdout,'stdout'),(handle.stderr,'stderr')]:
            os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ,name)
        while selector.get_map():
            left=deadline-time.monotonic()
            if left<=0:raise TimeoutError('whole listener deadline during stream read')
            events=selector.select(left)
            if not events:raise TimeoutError('whole listener deadline waiting for stream EOF')
            for key,_ in events:
                target=out if key.data=='stdout' else err
                block=os.read(key.fileobj.fileno(),min(16384,CAP+1-len(target)))
                if not block:eof[key.data]=True;selector.unregister(key.fileobj);continue
                target.extend(block)
                if len(target)>CAP:raise ValueError(key.data+' acceptance cap exceeded')
        left=deadline-time.monotonic()
        if left<=0:raise TimeoutError('whole listener deadline before actual wait')
        handle.wait(timeout=left)
    except BaseException as caught:
        error={'class':type(caught).__name__,'message':str(caught)}
    finally:
        selector.close()
        if handle is not None:
            if handle.process.poll() is None:handle.kill()
            try:handle.wait(timeout=1)
            except BaseException as caught:
                error=error or {'class':type(caught).__name__,'message':str(caught)}
            for stream in (handle.stdout,handle.stderr):
                if stream is not None:stream.close()
    state=registry._state()
    if handle is not None and method=='native':native_evidence=native.evidence_for_handle(handle)
    # Canonical state and detached source/phase evidence retrieval are included
    # in the observed whole-call clock, not deferred to a favorable timing pass.
    try:check_sources(plan);source_after_ok=True
    except BaseException as caught:error=error or {'class':type(caught).__name__,'message':str(caught)}
    run_completed=time.monotonic()
    pins=dict(adapterSourceSha256=plan['sourcePins']['adapter'] if method=='native' else plan['sourcePins']['lifecycle'],
        shimSourceSha256=plan['sourcePins']['CSource'] if method=='native' else plan['sourcePins']['legacyShim'],
        shimSha256=policy['lifecycle']['execShimSha256'],executableSha256=plan['lsofExecutableSha256'],
        parserSourceSha256=PARSER_SHA,callerSourceSha256=plan['sourcePins']['caller'])
    transcript=dict(schema=parser.SCHEMA,mode=parser.MODE,argv=ARGV,
        stdout=parser.encode_capture(bytes(out),truncated=not eof['stdout']),
        stderr=parser.encode_capture(bytes(err),truncated=not eof['stderr']),
        returnCode=handle.returncode if handle is not None else None,exception=error,
        startedMonotonic=started,runCompletedMonotonic=run_completed,
        parseCompletedMonotonic=run_completed,sourcePins=pins,nativeLaunch=native_evidence)
    # Actual parsing happens before its completion clock. Native semantic
    # binding also executes once inside the measured operation.
    try:parser.parse_global_stdout(bytes(out))
    except ValueError:pass  # derive_outcome retains the exact parser reason.
    transcript['parseCompletedMonotonic']=time.monotonic()
    preliminary_outer=dict(startedMonotonic=started,finishedMonotonic=time.monotonic())
    if method=='native':
        preliminary=parser.verify_transcript(transcript,state,policy,parser_source_sha256=PARSER_SHA,
            caller_source_sha256=plan['sourcePins']['caller'],outer_clock=preliminary_outer)
    else:preliminary=parser.derive_outcome(transcript,preliminary_outer)
    outer=dict(startedMonotonic=started,finishedMonotonic=time.monotonic())
    outcome=parser.derive_outcome(transcript,outer)
    lease=state['leases'].get(handle.lease_id) if handle is not None else None
    return dict(method=method,transcript=transcript,outerClock=outer,outcome=outcome,
        preliminaryMeasuredSemanticResult=preliminary,sourceBeforeVerified=source_before_ok,sourceAfterVerified=source_after_ok,
        actualManagedLeaseId=handle.lease_id if handle is not None else None,actualLease=copy.deepcopy(lease),
        observedJournalBytes=state['bytes'],observedJournalSha256=state['sha256'],
        observedLastSequence=state['lastSequence'],wholeSeconds=outer['finishedMonotonic']-started,
        oldBaselineNativeProvenanceNotClaimed=method=='legacy')


def run(plan_path,expected):
    if sha(plan_path)!=expected:raise ValueError('component plan external SHA differs')
    plan=json.loads(plan_path.read_bytes());check_sources(plan)
    if plan['priorChainsPerHalf']!=6308 or plan['actualCallsPerHalf']!=10 or plan['automaticRetries']!=0:raise ValueError('fixed component population differs')
    if plan.get('fixedOrder')!=['legacy','native']*10:raise ValueError('fixed alternating order differs')
    root=Path(plan['output'])
    if root!=BASE/'.runtime/posix/runs/ch7-native-ready-20261118/component-01':raise ValueError('fixed component output differs')
    root.mkdir()
    write_new(root/'plan-copy.json',plan)
    preparation_started=time.monotonic();policies,registries,preparation=prepare(plan,root)
    if time.monotonic()-preparation_started>plan['preparationMaximumSeconds']:raise TimeoutError('declared component preparation exceeded60s')
    write_new(root/'preparation.json',dict(startedMonotonic=preparation_started,completedMonotonic=time.monotonic(),halves=preparation))
    write_new(root/'queries-started.json',dict(planSha256=expected,sourcePins=plan['sourcePins'],automaticRetries=0))
    results=[];component_started=time.monotonic()
    try:
        for repeat in range(10):
            for method in ('legacy','native'):
                if time.monotonic()-component_started>plan['componentRunMaximumSeconds']:raise TimeoutError('declared fixed component runtime exceeded120s')
                row=capture(registries[method],method,policies[method],plan);row['repeat']=repeat
                write_new(root/(f'{repeat:02d}-{method}.json'),row);results.append(row)
    finally:
        for registry in registries.values():
            for handle in registry.handles:
                if handle.process.poll() is None:handle.kill()
                handle.wait(timeout=2)
            for process in registry.refused_processes:
                if process.poll() is None:process.kill()
                process.wait(timeout=2)
    # Cold canonical replay is independent, outside timing. No new OS capture.
    audits={}
    for method,registry in registries.items():
        raw=registry.path.read_bytes();state=life.replay_journal(raw)
        actual=[r for r in results if r['method']==method]
        if len(actual)!=10 or len(registry.handles)!=10:raise ValueError('component actual population incomplete')
        if len(state['leases'])!=6319 or state['lastSequence']!=18956:raise ValueError('component final canonical population differs')
        audits[method]=dict(finalBytes=len(raw),finalSha256=life.digest(raw),finalEvents=state['lastSequence'],
            syntheticPriorChains=6308,actualFiniteChains=10,totalFiniteChains=6318,
            allActualPopenHandlesTerminated=all(h.process.poll() is not None for h in registry.handles))
        for row in actual:
            cutoff=row['observedJournalBytes'];cold=life.replay_journal(raw[:cutoff])
            if method=='native':
                row['independentColdTranscriptResult']=parser.verify_transcript(row['transcript'],cold,policies[method],
                    parser_source_sha256=PARSER_SHA,caller_source_sha256=plan['sourcePins']['caller'],outer_clock=row['outerClock'])
            else:row['independentColdTranscriptResult']=dict(scope='Legacy canonical actual lease and whole-call outcome; native proof deliberately not claimed')
    summary={}
    for method in ('legacy','native'):
        rows=[r for r in results if r['method']==method]
        summary[method]=dict(attempts=len(rows),actualGlobalLsofProcesses=len(registries[method].handles),
            observedCompleteWithinWholeDeadline=sum(r['outcome']['state']=='OBSERVED' for r in rows),
            unknown=sum(r['outcome']['state']=='UNKNOWN' for r in rows),
            medianWholeSeconds=statistics.median(r['wholeSeconds'] for r in rows),
            maximumWholeSeconds=max(r['wholeSeconds'] for r in rows),
            nativeIndependentTranscriptObserved=sum(r.get('independentColdTranscriptResult',{}).get('state')=='OBSERVED' for r in rows) if method=='native' else None,
            allMeasurementsSeconds=[r['wholeSeconds'] for r in rows])
    check_sources(plan)
    if sha(plan_path)!=expected:raise ValueError('component plan changed during fixed run')
    report=dict(schema='aijade.native-ready.fixed-component-development.v1',
        status='FIXED_10_PLUS_10_COMPONENT_MEASURED_NOT_ENGINEERING_ACCEPTANCE',planSha256=expected,
        preparation=preparation,summary=summary,finalCanonical=audits,results=results,
        scope=dict(syntheticPriorJournal=True,syntheticSourceIdentityNotGitCommit=SOURCE_ID,
            naturalUnpaddedPrefix=True,requested15_4MiBNotCovered=True,full15_5MiBUpperEnvelopeNotCovered=True,
            newEngineeringWindows=0,qualificationStarted=False,backendQualified=False,scientificAcceptance=False,
            modelRequests=0,rendererRequests=0,apiRequests=0,automaticRetries=0,allActualHandlesTerminated=True))
    write_new(root/'result.json',report);print(json.dumps(dict(summary=summary,finalCanonical=audits,path=str(root/'result.json')),indent=2))


if __name__=='__main__':
    args=argparse.ArgumentParser();args.add_argument('--plan',type=Path,required=True);args.add_argument('--plan-sha256',required=True)
    parsed=args.parse_args();run(parsed.plan,parsed.plan_sha256)
