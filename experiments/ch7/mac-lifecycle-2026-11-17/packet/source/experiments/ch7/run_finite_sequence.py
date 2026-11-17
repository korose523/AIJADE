#!/usr/bin/env python3
"""One fixed admission followed by one serial qualification block or all four confirmed blocks."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psutil
from finite_runtime import (validate_build, read_block_receipt, dispositions, BUILD_FREEZE_PATH,
    MAC_PLAN, MAC_PLANS, mac_observer, mac_plan, mac_build_path, validate_mac_build_policy, validate_repository_binding, load_mac_policy, validate_mac_observation,
    validate_coverage, fixed_phase, MacMonitor, validate_mac_sample, OwnedRegistry,
    MAC_LIFECYCLE_PLAN, setup_lifecycle, managed_check_output, finish_monitored_cleanup, seal_refused_cleanup)

GIB=1024**3


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def utc():return dt.datetime.now(dt.timezone.utc).isoformat()


def _execute(a):
    lifecycle=getattr(a,'_lifecycle_registry',None);v3=lifecycle is not None
    repo=a.repo.resolve();output=a.output.resolve();require=lambda c,m: None if c else (_ for _ in ()).throw(ValueError(m))
    require(not output.exists(),'never overwrite a window/attempt')
    require(psutil.__version__=='7.2.2' and os.environ.get('DOTNET_PROCESSOR_COUNT')=='2','runtime/processor identity')
    require(managed_check_output(['git','status','--porcelain'],cwd=repo,text=True)=='','dirty execution checkout')
    plan=a.execution_plan.resolve()
    require(plan.is_relative_to(repo) and plan.is_file(),'explicit tracked execution plan required')
    head=managed_check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    mac=plan.name in MAC_PLANS
    if mac:require(str(plan.relative_to(repo))=='experiments/plans/'+plan.name,'wrong canonical Mac execution plan')
    implementation=getattr(a,'implementation_commit',None) or head
    require(os.environ['AIJADE_GIT_COMMIT']==implementation,'actual implementation commit')
    require(mac or implementation==head,'legacy execution requires current source binaries')
    freeze_path=getattr(a,'build_freeze_path',BUILD_FREEZE_PATH)
    binding=validate_repository_binding(repo,implementation,head,getattr(a,'data_publication_manifest',None),require_head=True) if mac else {}
    build=validate_build(a.assembly,a.build_manifest,implementation,repo,a.build_freeze_commit,freeze_path,strict_publication=mac)
    original=managed_check_output(['git','show',head+':'+str(plan.relative_to(repo))],cwd=repo)
    require(original==plan.read_bytes(),'execution plan differs from committed bytes')
    qualification=(a.inputs/'runtime-manifest.json').exists()
    sources=[a.inputs] if qualification else [a.inputs/('block-'+str(i)) for i in range(1,5)]
    inputs=[json.loads((d/'runtime-manifest.json').read_text()) for d in sources]
    require(all(m['purpose']==('qualification_only' if qualification else 'confirmed_finite_heldout') for m in inputs),'mixed scope')
    require([m['blockIndex'] for m in inputs]==([0] if qualification else [0,1,2,3]),'block order')
    require(all(len(m['cases'])==10 for m in inputs),'planned block size')
    policy=None;process_identity={}
    if mac:
        require(all(m['constructionFreezeCommit']==implementation for m in inputs),'inputs are not constructed against Q')
        require((head==implementation) if qualification else (head!=implementation),'qualification must run Q; formal execution must run additive I')
        if not qualification:
            for original_path in [a.selection]+[directory/name for directory in sources for name in ['runtime-manifest.json','scoring-manifest.json']]:
                path=original_path.resolve()
                require(not original_path.is_symlink() and path.is_file() and path.is_relative_to(repo),'formal input must be a regular tracked repository file before admission')
                require(managed_check_output(['git','show',head+':'+str(path.relative_to(repo))],cwd=repo)==path.read_bytes(),'formal input differs from published I before admission')
        require(getattr(a,'process_policy',None) is not None,'new Mac process policy required')
        policy,process_identity=load_mac_policy(repo,a.process_policy,implementation)
        require(plan.name==mac_plan(policy) and freeze_path==mac_build_path(policy),'policy/plan/build decision mismatch')
        validate_mac_build_policy(policy,build)
        observe=mac_observer(policy).observe
    metadata=dict(binding,buildFreezeCommit=a.build_freeze_commit,buildFreezePath=freeze_path,
                  executionPlanSha256=hashlib.sha256(plan.read_bytes()).hexdigest(),**process_identity) if mac else {}
    if mac:metadata['controllerProcess']=dict(pid=os.getpid(),createTime=psutil.Process().create_time())
    if v3:metadata.update(lifecycleJournalPath=str(lifecycle.path),lifecycleScopeId=lifecycle.scope_id)
    if qualification:
        require(plan.name in ['2026-11-16-ch7-relocated-runtime-qualification.md',*MAC_PLANS] and a.settle_seconds==600,'new known qualification requires its one fixed settling phase')
    output.mkdir(parents=True);(output/'admission').mkdir()
    planned=[m['cases'][i]['input']['caseId']+'/'+arm for m in inputs for i in range(10) for arm in m['cases'][i]['input']['conditions']]
    prepared=dict(status='PREPARED_NO_MEASUREMENT',codeCommit=implementation,purpose=inputs[0]['purpose'],
        plannedPairs=len(planned)//2,plannedConditionRows=len(planned),plannedBlocks=len(inputs),completedBlocks=0,
        completedConditionRows=0,inFlightCaseIds=[],unknownCaseIds=[],unattemptedCaseIds=planned,blocks=[],modelRequests=0,
        formalHardwareQualification=False,independentHumanReview=False,**metadata)
    if mac:
        (output/'process-policy.json').write_bytes(a.process_policy.read_bytes())
        require(hashlib.sha256((output/'process-policy.json').read_bytes()).hexdigest()==process_identity['processPolicySha256'],'policy changed before phase')
        write(output/'receipt.json',prepared)
    def observed(owned_roots=None):
        process=observe(policy,owned_roots=owned_roots or [],lifecycle=lifecycle) if v3 else observe(policy,owned_roots=owned_roots or [])
        process.update(process_identity)
        return dict(utc=utc(),availableBytes=psutil.virtual_memory().available,
                    swapUsedBytes=psutil.swap_memory().used,processObservation=process,
                    rssBytes=process.get('ownedRssBytes'),**process_identity)
    def phase(duration,path):
        with path.open('x') as log:
            def save(item):log.write(json.dumps(item)+'\n');log.flush()
            return fixed_phase(duration,observed,save)
    preflight=None
    if v3:
        from phase_continuity import run_preflight, PreflightRefused
        from contextlib import ExitStack
        if a.settle_seconds:(output/'settling').mkdir()
        with ExitStack() as stack:
            streams={name:stack.enter_context((output/name/'telemetry.jsonl').open('x'))
                     for name in (['settling','admission'] if a.settle_seconds else ['admission'])}
            events=stack.enter_context((output/'phase-events.jsonl').open('x'))
            def event_save(item):events.write(json.dumps(item)+'\n');events.flush()
            def raw_save(name):
                def save(item):streams[name].write(json.dumps(item)+'\n');streams[name].flush()
                return save
            try:
                preflight=run_preflight(observed,
                    lambda item:validate_mac_sample(item,process_identity['processPolicySha256'],process_identity['observerModuleSha256'],policy),
                    {name:raw_save(name) for name in streams},event_writer=event_save,settling_seconds=a.settle_seconds)
            except PreflightRefused as error:
                write(output/'preflight-continuity.json',error.result)
                for name,partial in error.result['phases'].items():
                    write(output/name/'receipt.json',dict(partial,codeCommit=implementation,**metadata))
                raise
        write(output/'preflight-continuity.json',preflight)
        if 'settling' in preflight['phases']:
            phase=preflight['phases']['settling']
            settling=dict(phase,codeCommit=implementation,requestedSeconds=600,intervalReset=False,measurementStarted=False,
                prospectiveAmendmentSha256=hashlib.sha256(plan.read_bytes()).hexdigest(),**metadata)
            write(output/'settling/receipt.json',settling)
        phase=preflight['phases']['admission'];admitted=phase['status']=='ADMITTED'
        admission=dict(phase,codeCommit=implementation,noResearchProcesses=admitted,formalHardwareQualification=False,
            windowReset=False,precedingFixedSettlingSeconds=a.settle_seconds,
            observationError=None,**metadata)
        write(output/'admission/receipt.json',admission)
    else:
        if a.settle_seconds:
            require(a.settle_seconds==600 and qualification,'only the prospectively bounded known-qualification settling phase is enabled')
            amendment=plan
            require(amendment.is_file(),'missing prospective settling protocol')
            (output/'settling').mkdir();settle_start=time.monotonic();settle_samples=[]
            settling_progress=dict(prepared) if mac else dict(codeCommit=head)
            settling_progress.update(status='FIXED_UNLOADED_SETTLING_RUNNING',requestedSeconds=600,
                prospectiveAmendmentSha256=hashlib.sha256(amendment.read_bytes()).hexdigest(),measurementStarted=False)
            write(output/'receipt.json',settling_progress)
            if mac:
                settle_samples,settle_clock=phase(600,output/'settling/telemetry.jsonl')
                settling=dict(status='FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION',codeCommit=implementation,
                    requestedSeconds=600,elapsedSeconds=settle_clock['endMonotonic']-settle_clock['startMonotonic'],
                    samples=len(settle_samples),intervalReset=False,measurementStarted=False,
                    prospectiveAmendmentSha256=hashlib.sha256(amendment.read_bytes()).hexdigest(),phaseClock=settle_clock,**metadata)
                try:
                    settling['coverage']=validate_coverage(settle_samples,600,300)
                    for sample in settle_samples:
                        require(sample['processObservation'].get('ownedRoots')==[] and sample['processObservation'].get('ownedProcesses')==[],'idle phase cannot authorize owned runtime processes')
                        validate_mac_sample(sample,process_identity['processPolicySha256'],process_identity['observerModuleSha256'],policy)
                except ValueError as error:
                    settling.update(status='SETTLING_OBSERVATION_REFUSED',reason=str(error));write(output/'settling/receipt.json',settling);raise
                write(output/'settling/receipt.json',settling)
            else:
              with (output/'settling/telemetry.jsonl').open('x') as log:
                while True:
                    elapsed=time.monotonic()-settle_start
                    item=dict(utc=utc(),elapsedSeconds=elapsed,availableBytes=psutil.virtual_memory().available,
                        swapUsedBytes=psutil.swap_memory().used,researchProcesses=[p.info for p in psutil.process_iter(['pid','name'])
                        if (p.info['name'] or '').lower() in ['dotnet','ollama'] or 'godot' in (p.info['name'] or '').lower()])
                    settle_samples.append(item);log.write(json.dumps(item)+'\n');log.flush()
                    if elapsed>=600:break
                    time.sleep(min(2,600-elapsed))
              write(output/'settling/receipt.json',dict(status='FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION',codeCommit=head,
                requestedSeconds=600,elapsedSeconds=settle_samples[-1]['elapsedSeconds'],samples=len(settle_samples),
                intervalReset=False,measurementStarted=False,prospectiveAmendmentSha256=hashlib.sha256(amendment.read_bytes()).hexdigest()))
        sample_start=time.monotonic();samples=[];coverage=None;observation_error=None
        if mac:
            samples,admission_clock=phase(120,output/'admission/telemetry.jsonl')
            try:
                coverage=validate_coverage(samples,120,60)
                for sample in samples:
                    require(sample['processObservation'].get('ownedRoots')==[] and sample['processObservation'].get('ownedProcesses')==[],'idle phase cannot authorize owned runtime processes')
                    validate_mac_sample(sample,process_identity['processPolicySha256'],process_identity['observerModuleSha256'],policy)
            except ValueError as error:observation_error=str(error)
        else:
          with (output/'admission/telemetry.jsonl').open('x') as log:
            while True:
                elapsed=time.monotonic()-sample_start
                processes=[p.info for p in psutil.process_iter(['pid','name'])
                           if (p.info['name'] or '').lower() in ['dotnet','ollama'] or 'godot' in (p.info['name'] or '').lower()]
                item=dict(utc=utc(),elapsedSeconds=elapsed,availableBytes=psutil.virtual_memory().available,
                          swapUsedBytes=psutil.swap_memory().used,researchProcesses=processes)
                samples.append(item);log.write(json.dumps(item)+'\n');log.flush()
                if elapsed>=120:break
                time.sleep(min(2,120-elapsed))
        idle=(observation_error is None and coverage is not None) if mac else not any(s['researchProcesses'] for s in samples)
        admitted=bool(samples) and min(s['availableBytes'] for s in samples)>=4*GIB and max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples)<=64*1024**2 and idle
        admission=dict(status='ADMITTED' if admitted else 'NOT_ADMITTED_NO_MEASUREMENT',codeCommit=implementation,
            elapsedSeconds=(admission_clock['endMonotonic']-admission_clock['startMonotonic']) if mac else samples[-1]['elapsedSeconds'],samples=len(samples),minimumAvailableBytes=min(s['availableBytes'] for s in samples) if samples else None,
            swapRangeBytes=max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples) if samples else None,
            noResearchProcesses=idle,formalHardwareQualification=False,windowReset=False,
            precedingFixedSettlingSeconds=a.settle_seconds,executionPlanSha256=hashlib.sha256(plan.read_bytes()).hexdigest())
        if mac:admission.update(metadata,coverage=coverage,observationError=observation_error,phaseClock=admission_clock)
        write(output/'admission/receipt.json',admission)
    sequence=dict(schema='aijade.ch7.finite-sequence-receipt.v1',status='ADMITTED_NOT_STARTED' if admitted else 'NOT_ADMITTED_NO_MEASUREMENT',
        codeCommit=implementation,purpose=inputs[0]['purpose'],plannedPairs=len(planned)//2,plannedConditionRows=len(planned),
        plannedBlocks=len(inputs),completedBlocks=0,completedConditionRows=0,inFlightCaseIds=[],unattemptedCaseIds=planned,
        blocks=[],modelRequests=0,formalHardwareQualification=False,independentHumanReview=False,
        executionPlanSha256=hashlib.sha256(plan.read_bytes()).hexdigest(),unknownCaseIds=[])
    sequence.update(metadata)
    write(output/'receipt.json',sequence)
    if not admitted:print(json.dumps(sequence));return 0
    epoch=time.monotonic();baseline=psutil.swap_memory().used;timers=output/'sustained-timers.json';write(timers,{})
    env=dict(os.environ,AIJADE_FINITE_EPOCH=str(epoch),AIJADE_FINITE_SWAP_BASELINE=str(baseline),AIJADE_FINITE_TIMERS_FILE=str(timers))
    sequence.update(status='RUNNING',startedAt=utc(),initialSystemSwapUsedBytes=baseline,sequenceEpochMonotonic=epoch)
    if mac:sequence['blockControllers']=[]
    write(output/'receipt.json',sequence);reason=None;active=None
    completed=[];inflight=[];target=None;active_planned=[]
    monitor=None;owned_registry=None
    if mac:
        own=[(metadata['controllerProcess']['pid'],metadata['controllerProcess']['createTime'])]
        owned_registry=lifecycle if v3 else OwnedRegistry(own)
        def runtime_observed():
            item=observed(owned_registry.roots())
            if not v3:owned_registry.remember(item['processObservation'])
            return item
        monitor=MacMonitor(output/'process-observations.jsonl',runtime_observed,
            lambda item:validate_mac_sample(item,process_identity['processPolicySha256'],process_identity['observerModuleSha256'],policy),
            epoch,baseline,timers,previous_sample_monotonic=(preflight['runtimeHandoffAnchor']['lastSampleMonotonic'] if v3 else None)).start()
    try:
        for index,source in enumerate(sources):
            require(time.monotonic()-epoch<4800,'overall wall exhausted before next block')
            # Carry sustained global timers across the small between-block interval.
            now=time.monotonic();state={} if mac else json.loads(timers.read_text());available=psutil.virtual_memory().available;swap=max(0,psutil.swap_memory().used-baseline)
            if mac:monitor.check()
            for name,crossed in ([] if mac else [('available',available<3*GIB),('swap',swap>GIB)]):
                if not crossed:state.pop(name,None)
                else:
                    state.setdefault(name,now);require(now-state[name]<30,'between-block sustained '+name+' stop')
            if not mac:write(timers,state)
            target=output/('block-'+str(index+1));command=[sys.executable,str(repo/'experiments/ch7/run_finite_block.py')]
            active=None
            values=dict(repo=repo,client=a.client,model=a.model,selection=a.selection,manifest=source/'runtime-manifest.json',
                        scoring=source/'scoring-manifest.json',output=target,dotnet=a.dotnet,assembly=a.assembly,
                        build_manifest=a.build_manifest,godot=a.godot,docker=a.docker,execution_plan=plan,db_container=a.db_container,
                        build_freeze_commit=a.build_freeze_commit)
            if mac:
                values.update(implementation_commit=implementation,build_freeze_path=freeze_path,process_policy=a.process_policy)
                if getattr(a,'data_publication_manifest',None) is not None:values['data_publication_manifest']=a.data_publication_manifest
            values={key.replace('_','-'):value for key,value in values.items()}
            for key,value in values.items():command+=['--'+key,str(value)]
            active_planned=[p['input']['caseId']+'/'+arm for p in inputs[index]['cases'] for arm in p['input']['conditions']]
            with (output/('block-'+str(index+1)+'-controller.log')).open('x') as log:
                active=(lifecycle.launch(command,role='finite',stage='block-'+str(index+1),cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True) if v3 else
                        subprocess.Popen(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
                if mac:
                    if v3:
                        lease=owned_registry.register(active);created=lease['identity']['createTimeMicros']/1000000
                    else:
                        created=psutil.Process(active.pid).create_time();owned_registry.register(active.pid,created)
                    sequence['blockControllers'].append(dict(blockIndex=index,pid=active.pid,createTime=created))
                    write(output/'receipt.json',sequence)
                block_started=time.monotonic()
                while active.poll() is None:
                    if mac:monitor.check()
                    require(time.monotonic()-block_started<1245,'owned block/cleanup watchdog expired')
                    time.sleep(1)
                if v3:active.wait(timeout=1.25)
            block=read_block_receipt(target/'receipt.json');sequence['blocks'].append(block)
            state=dispositions(target,active_planned,flow_started=True)
            completed.extend(state['completedCaseIds']);inflight=state['inFlightCaseIds']
            sequence.update(completedConditionRows=len(completed),inFlightCaseIds=inflight,unknownCaseIds=state['unknownCaseIds'],
                unattemptedCaseIds=[p for p in planned if p not in completed and p not in inflight and p not in state['unknownCaseIds']])
            require(active.returncode==0 and block['status']=='COMPLETE_FINITE_BLOCK_OBSERVATIONS','block stopped; no subsequent block or retry')
            require(all(r['remaining']==0 and not r.get('error') for r in json.loads((target/'database-cleanup.json').read_text())),'owned lease remains/unknown')
            if mac:monitor.check()
            sequence['completedBlocks']+=1;write(output/'receipt.json',sequence)
        sequence['status']='COMPLETE_FINITE_SEQUENCE_OBSERVATIONS'
    except BaseException as error:
        reason=type(error).__name__+': '+str(error);sequence['status']='STOPPED'
        if active is not None and active.poll() is None:
            # The owned block catches this signal and runs its exact process/database cleanup.
            active.send_signal(signal.SIGTERM)
            try:active.wait(timeout=45)
            except subprocess.TimeoutExpired:
                sequence['ownedControllerCleanupTimedOut']=True
        if active is not None:sequence['lastControllerExitCode']=active.poll()
    finally:
        if v3:
            try:
                refused=seal_refused_cleanup(lifecycle,output)
                if refused is not None:
                    sequence['refusedProcessCleanupSha256']=hashlib.sha256((output/'launch-refused-process-cleanup.json').read_bytes()).hexdigest()
                    reason=(reason+'; ' if reason else '')+'finite launch refused; cleanup cannot confer acceptance';sequence['status']='STOPPED'
            except BaseException as error:
                reason=(reason+'; ' if reason else '')+'refused-process cleanup: '+type(error).__name__+': '+str(error);sequence['status']='STOPPED'
        if monitor is not None:
            try:finish_monitored_cleanup(monitor,require_terminal_sample=v3)
            except ValueError as error:
                reason=(reason+'; ' if reason else '')+str(error);sequence['status']='STOPPED'
            sequence['processObservationCount']=len(monitor.samples)
            sequence['processObservationErrors']=monitor.errors
            try:registry_final=owned_registry.final()
            except ValueError as error:registry_final=dict(status='UNKNOWN_OWNED_IDENTITY_ABSENCE',error=str(error))
            write(output/'owned-process-registry.json',registry_final)
            sequence['ownedProcessRegistrySha256']=hashlib.sha256((output/'owned-process-registry.json').read_bytes()).hexdigest()
            if v3:
                sequence['lifecycleJournalSha256']=hashlib.sha256(lifecycle.path.read_bytes()).hexdigest()
                sequence['phaseEventsSha256']=hashlib.sha256((output/'phase-events.jsonl').read_bytes()).hexdigest()
                sequence['preflightContinuitySha256']=hashlib.sha256((output/'preflight-continuity.json').read_bytes()).hexdigest()
            if registry_final['status']!='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT':
                reason=(reason+'; ' if reason else '')+'known owned descendant remains or identity unknown';sequence['status']='STOPPED'
        if reason is not None and target is not None:
            try:
                last=json.loads((target/'receipt.json').read_text())
                sequence['stoppedBlockReceipt']=last
                flow_started=bool(last.get('phases',{}).get('flow'))
            except (OSError,ValueError,AttributeError):flow_started=active is not None
            state=dispositions(target,active_planned,flow_started=flow_started)
            actual_completed=list(dict.fromkeys(completed+state['completedCaseIds']))
            sequence.update(completedConditionRows=len(actual_completed),inFlightCaseIds=state['inFlightCaseIds'],unknownCaseIds=state['unknownCaseIds'],
                unattemptedCaseIds=[p for p in planned if p not in actual_completed and p not in state['inFlightCaseIds'] and p not in state['unknownCaseIds']],
                dispositionErrors=state['dispositionErrors'])
        sequence.update(reason=reason,finishedAt=utc(),wallSeconds=time.monotonic()-epoch)
        write(output/'receipt.json',sequence)
    print(json.dumps(sequence));return 0 if sequence['status'].startswith('COMPLETE') else 1


def execute(a):
    existed=a.output.exists()
    previous=signal.getsignal(signal.SIGTERM)
    def interrupted(signum,frame):raise RuntimeError('sequence signal '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    lifecycle=None
    try:
        if not existed:lifecycle=setup_lifecycle(a,'sequence')
        a._lifecycle_registry=lifecycle
        return _execute(a)
    except BaseException as error:
        if not existed:
            a.output.mkdir(parents=True,exist_ok=True)
            path=a.output/'receipt.json'
            try:receipt=json.loads(path.read_text())
            except (OSError,ValueError):receipt={}
            started=bool(receipt.get('startedAt'))
            receipt.update(status='STOPPED_CONTROLLER_ERROR' if started else 'STOPPED_PRE_BLOCK',reason=type(error).__name__+': '+str(error),finishedAt=utc(),
                           measurementStarted=started,modelRequests=0)
            if not started:receipt['completedConditionRows']=0
            write(path,receipt)
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        return 1
    finally:
        try:
            if lifecycle is not None:
                refused=seal_refused_cleanup(lifecycle,a.output)
                if not lifecycle.closed:lifecycle.close()
                # The final immutable bytes include SCOPE_CLOSE. Blocks bind
                # earlier prefixes of this exact shared append-only journal.
                raw=lifecycle.path.read_bytes()
                archive=a.output/'lifecycle-journal.jsonl'
                with archive.open('xb') as stream:stream.write(raw)
                receipt=json.loads((a.output/'receipt.json').read_text())
                receipt.update(lifecycleJournalSha256=hashlib.sha256(raw).hexdigest(),
                               lifecycleJournalBytes=len(raw),lifecycleJournalArchive='lifecycle-journal.jsonl',
                               lifecycleScopeId=lifecycle.scope_id,lifecycleJournalPath=str(lifecycle.path))
                if refused is not None:
                    receipt['refusedProcessCleanupSha256']=hashlib.sha256((a.output/'launch-refused-process-cleanup.json').read_bytes()).hexdigest()
                    receipt['status']='STOPPED_REFUSED_LAUNCH'
                write(a.output/'receipt.json',receipt)
                if refused is not None:return 1
        except BaseException as error:
            if not existed:
                a.output.mkdir(parents=True,exist_ok=True);path=a.output/'receipt.json'
                try:receipt=json.loads(path.read_text())
                except (OSError,ValueError):receipt={}
                detail='lifecycle finalization: '+type(error).__name__+': '+str(error)
                receipt.update(status='STOPPED_LIFECYCLE_FINALIZATION_ERROR',
                               reason=(receipt.get('reason')+'; ' if receipt.get('reason') else '')+detail,
                               finishedAt=utc(),modelRequests=0,lifecycleJournalPath=str(lifecycle.path),
                               lifecycleScopeId=lifecycle.scope_id)
                write(path,receipt)
            print(type(error).__name__+': '+str(error),file=sys.stderr)
            return 1
        finally:signal.signal(signal.SIGTERM,previous)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['repo','client','model','selection','inputs','output','dotnet','assembly','build-manifest','godot','docker','execution-plan']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--db-container',required=True)
    p.add_argument('--build-freeze-commit',required=True)
    p.add_argument('--settle-seconds',type=int,default=0)
    p.add_argument('--implementation-commit')
    p.add_argument('--build-freeze-path',default=BUILD_FREEZE_PATH)
    p.add_argument('--data-publication-manifest')
    p.add_argument('--process-policy',type=Path)
    raise SystemExit(execute(p.parse_args()))
