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

GIB=1024**3


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def utc():return dt.datetime.now(dt.timezone.utc).isoformat()


def execute(a):
    repo=a.repo.resolve();output=a.output.resolve();require=lambda c,m: None if c else (_ for _ in ()).throw(ValueError(m))
    require(not output.exists(),'never overwrite a window/attempt')
    require(psutil.__version__=='7.2.2' and os.environ.get('DOTNET_PROCESSOR_COUNT')=='2','runtime/processor identity')
    require(subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)=='','dirty execution checkout')
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    require(os.environ['AIJADE_GIT_COMMIT']==head,'current execution commit')
    qualification=(a.inputs/'runtime-manifest.json').exists()
    sources=[a.inputs] if qualification else [a.inputs/('block-'+str(i)) for i in range(1,5)]
    inputs=[json.loads((d/'runtime-manifest.json').read_text()) for d in sources]
    require(all(m['purpose']==('qualification_only' if qualification else 'confirmed_finite_heldout') for m in inputs),'mixed scope')
    require([m['blockIndex'] for m in inputs]==([0] if qualification else [0,1,2,3]),'block order')
    require(all(len(m['cases'])==10 for m in inputs),'planned block size')
    output.mkdir(parents=True);(output/'admission').mkdir()
    if a.settle_seconds:
        require(a.settle_seconds==600 and qualification,'only the prospectively bounded known-qualification settling phase is enabled')
        amendment=repo/'experiments/plans/2026-11-12-ch7-finite-qualification-settling.md'
        require(amendment.is_file(),'missing prospective settling protocol')
        (output/'settling').mkdir();settle_start=time.monotonic();settle_samples=[]
        write(output/'receipt.json',dict(status='FIXED_UNLOADED_SETTLING_RUNNING',codeCommit=head,requestedSeconds=600,
            prospectiveAmendmentSha256=hashlib.sha256(amendment.read_bytes()).hexdigest(),measurementStarted=False))
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
    sample_start=time.monotonic();samples=[]
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
    admitted=min(s['availableBytes'] for s in samples)>=4*GIB and max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples)<=64*1024**2 and not any(s['researchProcesses'] for s in samples)
    admission=dict(status='ADMITTED' if admitted else 'NOT_ADMITTED_NO_MEASUREMENT',codeCommit=head,
        elapsedSeconds=samples[-1]['elapsedSeconds'],samples=len(samples),minimumAvailableBytes=min(s['availableBytes'] for s in samples),
        swapRangeBytes=max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples),
        noResearchProcesses=not any(s['researchProcesses'] for s in samples),formalHardwareQualification=False,windowReset=False,
        precedingFixedSettlingSeconds=a.settle_seconds)
    write(output/'admission/receipt.json',admission)
    planned=[m['cases'][i]['input']['caseId']+'/'+arm for m in inputs for i in range(10) for arm in m['cases'][i]['input']['conditions']]
    sequence=dict(schema='aijade.ch7.finite-sequence-receipt.v1',status='ADMITTED_NOT_STARTED' if admitted else 'NOT_ADMITTED_NO_MEASUREMENT',
        codeCommit=head,purpose=inputs[0]['purpose'],plannedPairs=len(planned)//2,plannedConditionRows=len(planned),
        plannedBlocks=len(inputs),completedBlocks=0,completedConditionRows=0,inFlightCaseIds=[],unattemptedCaseIds=planned,
        blocks=[],modelRequests=0,formalHardwareQualification=False,independentHumanReview=False)
    write(output/'receipt.json',sequence)
    if not admitted:print(json.dumps(sequence));return 0
    epoch=time.monotonic();baseline=psutil.swap_memory().used;timers=output/'sustained-timers.json';write(timers,{})
    env=dict(os.environ,AIJADE_FINITE_EPOCH=str(epoch),AIJADE_FINITE_SWAP_BASELINE=str(baseline),AIJADE_FINITE_TIMERS_FILE=str(timers))
    sequence.update(status='RUNNING',startedAt=utc(),initialSystemSwapUsedBytes=baseline)
    write(output/'receipt.json',sequence);reason=None;active=None
    completed=[];inflight=[]
    try:
        for index,source in enumerate(sources):
            require(time.monotonic()-epoch<4800,'overall wall exhausted before next block')
            # Carry sustained global timers across the small between-block interval.
            now=time.monotonic();state=json.loads(timers.read_text());available=psutil.virtual_memory().available;swap=max(0,psutil.swap_memory().used-baseline)
            for name,crossed in [('available',available<3*GIB),('swap',swap>GIB)]:
                if not crossed:state.pop(name,None)
                else:
                    state.setdefault(name,now);require(now-state[name]<30,'between-block sustained '+name+' stop')
            write(timers,state)
            target=output/('block-'+str(index+1));command=[sys.executable,str(repo/'experiments/ch7/run_finite_block.py')]
            values=dict(repo=repo,client=a.client,model=a.model,selection=a.selection,manifest=source/'runtime-manifest.json',
                        scoring=source/'scoring-manifest.json',output=target,dotnet=a.dotnet)
            for key,value in values.items():command+=['--'+key,str(value)]
            with (output/('block-'+str(index+1)+'-controller.log')).open('x') as log:
                active=subprocess.Popen(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                while active.poll() is None:time.sleep(1)
            block=json.loads((target/'receipt.json').read_text());sequence['blocks'].append(block)
            completed.extend(r['caseId']+'/'+r['condition'] for r in (json.loads((target/'cases.json').read_text()) if (target/'cases.json').exists() else []))
            inflight=block['inFlightCaseIds'];sequence.update(completedConditionRows=len(completed),inFlightCaseIds=inflight,
                unattemptedCaseIds=[p for p in planned if p not in completed and p not in inflight])
            require(active.returncode==0 and block['status']=='COMPLETE_FINITE_BLOCK_OBSERVATIONS','block stopped; no subsequent block or retry')
            require(all(r['remaining']==0 for r in json.loads((target/'database-cleanup.json').read_text())),'owned lease remains')
            sequence['completedBlocks']+=1;write(output/'receipt.json',sequence)
        sequence['status']='COMPLETE_FINITE_SEQUENCE_OBSERVATIONS'
    except BaseException as error:
        reason=type(error).__name__+': '+str(error);sequence['status']='STOPPED'
        if active is not None and active.poll() is None:
            # The owned block catches this signal and runs its exact process/database cleanup.
            active.send_signal(signal.SIGTERM)
            try:active.wait(timeout=30)
            except subprocess.TimeoutExpired:
                sequence['ownedControllerCleanupTimedOut']=True
        if active is not None:sequence['lastControllerExitCode']=active.poll()
    finally:
        sequence.update(reason=reason,finishedAt=utc(),wallSeconds=time.monotonic()-epoch)
        write(output/'receipt.json',sequence)
    print(json.dumps(sequence));return 0 if sequence['status'].startswith('COMPLETE') else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['repo','client','model','selection','inputs','output','dotnet']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--settle-seconds',type=int,default=0)
    raise SystemExit(execute(p.parse_args()))
