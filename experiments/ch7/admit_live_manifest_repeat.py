#!/usr/bin/env python3
"""One fixed idle admission window, then at most one unchanged known-case repeat."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

GIB=1024**3


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path,value): path.write_text(json.dumps(value,indent=2)+'\n')


def main(args):
    repo=args.repo.resolve(); first=args.first.resolve(); directory=args.admission.resolve()
    assert not directory.exists() and not args.output.exists(), 'Preserve previous windows/attempts'
    assert subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)==''
    assert os.environ.get('DOTNET_PROCESSOR_COUNT')=='2' and psutil.__version__=='7.2.2'
    initial=json.loads((first/'receipt.json').read_text())
    assert initial['status']=='STOPPED' and initial['reason']=='RuntimeError: swap_sustained_resource_stop'
    assert initial['completedCases']==0 and initial['plannedCases']==20
    assert all(not psutil.pid_exists(p['pid']) for p in initial['phases'].values()), 'Earlier owned root still present'
    assert all(r['remaining']==0 for r in json.loads((first/'database-cleanup.json').read_text()))
    frozen=json.loads(args.frozen_build.read_text()); identities=json.loads((first/'input-identities.json').read_text())
    hashes={p.name:sha(p) for p in (repo/'tests/Aijade.Tests/bin/Release/net10.0').glob('*.dll')}
    assert hashes==frozen['binaries']==identities['binaries'], 'No rebuild/changed binary is allowed'
    for rel,expected in identities['liveSources'].items(): assert sha(repo/rel)==expected, rel
    assert sha(args.manifest)==identities['runtimeManifestSha256'] and sha(args.scoring)==identities['windowTemplateSha256']
    original={str(p.relative_to(first)):sha(p) for p in first.rglob('*') if p.is_file()}
    directory.mkdir(parents=True)
    write(directory/'first-attempt-preservation.json',original)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    started=time.monotonic(); samples=[]
    with (directory/'telemetry.jsonl').open('x') as log:
        while True:
            now=time.monotonic()
            names=[]
            for process in psutil.process_iter(['pid','name']):
                name=(process.info['name'] or '').lower()
                if name in ['dotnet','ollama'] or 'godot' in name:
                    names.append(process.info)
            item=dict(utc=dt.datetime.now(dt.timezone.utc).isoformat(),elapsedSeconds=now-started,
                      availableBytes=psutil.virtual_memory().available,swapUsedBytes=psutil.swap_memory().used,
                      researchProcesses=names)
            samples.append(item); log.write(json.dumps(item)+'\n'); log.flush()
            if now-started>=120: break
            time.sleep(min(2,120-(now-started)))
    available=min(s['availableBytes'] for s in samples)
    swap_range=max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples)
    idle=all(not s['researchProcesses'] for s in samples)
    admitted=available>=4*GIB and swap_range<=64*1024**2 and idle
    receipt=dict(schema='aijade.ch7.live-repeat-admission.v1',status='ADMITTED' if admitted else 'NOT_ADMITTED_NO_REPEAT',
                 codeCommit=commit,amendment='341a683',sampleSeconds=120,samplingIntervalSeconds=2,samples=len(samples),
                 elapsedSeconds=samples[-1]['elapsedSeconds'],minimumAvailableBytes=available,swapRangeBytes=swap_range,
                 noResearchProcesses=idle,limits=dict(minimumAvailableBytes=4*GIB,maximumSwapRangeBytes=64*1024**2),
                 repeatStarted=False,repeatExitCode=None,heldOutCases=0,formalHardwareQualification=False,
                 interpretation='Exactly one fixed unloaded window and, if admitted, one fresh repeat. System swap origin is not established; this is not causal or device qualification.')
    write(directory/'receipt.json',receipt)
    assert original=={str(p.relative_to(first)):sha(p) for p in first.rglob('*') if p.is_file()}, 'Earlier attempt changed'
    if not admitted:
        print(json.dumps(receipt)); return 0
    for rel,expected in identities['liveSources'].items(): assert sha(repo/rel)==expected
    assert {p.name:sha(p) for p in (repo/'tests/Aijade.Tests/bin/Release/net10.0').glob('*.dll')}==hashes
    env=dict(os.environ); env['AIJADE_GIT_COMMIT']=commit
    command=[sys.executable,str(repo/'experiments/ch7/run_live_manifest_development.py')]
    for key in ['repo','client','model','selection','manifest','scoring','output','dotnet']:
        command.extend(['--'+key,str(getattr(args,key))])
    receipt['repeatStarted']=True; write(directory/'receipt.json',receipt)
    with (directory/'repeat-controller.log').open('x') as log:
        run=subprocess.run(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT)
    receipt['repeatExitCode']=run.returncode; receipt['repeatFinishedAt']=dt.datetime.now(dt.timezone.utc).isoformat()
    assert original=={str(p.relative_to(first)):sha(p) for p in first.rglob('*') if p.is_file()}, 'Earlier attempt changed during repeat'
    receipt['firstAttemptBytesUnchanged']=True; write(directory/'receipt.json',receipt)
    print(json.dumps(receipt)); return run.returncode


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['repo','client','model','selection','manifest','scoring','output','dotnet','first','admission','frozen-build']:
        parser.add_argument('--'+key,type=Path,required=True)
    raise SystemExit(main(parser.parse_args()))
