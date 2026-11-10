"""Replay prepared task ports through Jint or through Node for development diagnosis."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import tempfile
import time

from prepare import HERE, canonical, digest_file, filename, write_json

ROOT = HERE.parents[3]
PLAN = '612e909d6c3ef72f73d786455d4bbaf9fc3ad18e'
TRANSPORT = '225b7f9432bfbf7a682109aa371a51131ae3fc7d'
WALL_SECONDS = 30
CPU_SECONDS = 15
TOTAL_SECONDS = 45 * 60


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64*1024**2, 64*1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def task_run(command):
    started = time.monotonic()
    timed_out = False
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run(command, stdout=out, stderr=err, cwd=HERE, timeout=WALL_SECONDS,
                                    env={'PATH': '/usr/bin:/bin:/usr/local/bin', 'TZ': 'UTC', 'LC_ALL':'C'}, preexec_fn=limits)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(), err.read()
    return {'exitCode':exit_code,'wallTimeout':timed_out,'seconds':round(time.monotonic()-started,4),
            'stdoutSha256':hashlib.sha256(stdout).hexdigest(),'stderrSha256':hashlib.sha256(stderr).hexdigest(),
            'stdout':stdout.decode(errors='replace'),'stderr':stderr.decode(errors='replace')}


def replay(args):
    pack=args.pack.resolve()
    ports=args.ports.resolve()
    out=args.out.resolve()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest=json.loads((pack/'manifest.json').read_text())
    population=manifest.get('population','development')
    inventory=manifest['tasks']
    if args.final:
        assert not args.only and args.engine=='jint' and not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
        subprocess.run(['git','merge-base','--is-ancestor',PLAN,head],cwd=ROOT,check=True)
        subprocess.run(['git','merge-base','--is-ancestor',TRANSPORT,head],cwd=ROOT,check=True)
        lock=json.loads((HERE/'input-lock.json').read_text())[population]
        assert len(inventory)==lock['tasks']
        assert digest_file(pack/'manifest.json')==lock['packSha256'] and digest_file(ports/'ports.json')==lock['portsSha256']
        if 'amendmentCommit' in manifest:
            subprocess.run(['git','merge-base','--is-ancestor',manifest['amendmentCommit'],head],cwd=ROOT,check=True)
    emitted={r['taskId']:r for r in json.loads((ports/'ports.json').read_text())}
    out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'source'
    snapshot.mkdir()
    runtime=snapshot/'python-semantics.js'
    shutil.copyfile(HERE/runtime.name,runtime)
    node_helper=snapshot/'node-replay.cjs'
    shutil.copyfile(HERE/node_helper.name,node_helper)
    source_names=['prepare.py','compile_ports.py','replay.py','python-semantics.js','node-replay.cjs','JintReplay/Program.cs',
                  'JintReplay/JintReplay.csproj','../../../../src/Aijade.Research/SkillBench/Sandbox.cs',
                  '../../../../src/Aijade.Research/SkillBench/Bench.cs','../../../../src/Aijade.Research/RqC/Backends.cs',
                  '../../../../Directory.Packages.props']
    if args.final:
        source_names.append('input-lock.json')
    receipt={'planCommit':PLAN,'transportAmendmentCommit':TRANSPORT,'executionCodeCommit':head,'engine':args.engine,'final':args.final,
        'population':population,'amendmentCommit':manifest.get('amendmentCommit'),
        'sourceSha256':{n:digest_file(HERE/n) for n in source_names},'executableSha256':digest_file(args.executable),
        'jintReplaySha256':digest_file(args.dll) if args.dll else None,
        'jintAssemblySha256':digest_file(args.dll.parent/'Jint.dll') if args.dll else None,
        'researchAssemblySha256':digest_file(args.dll.parent/'Aijade.Research.dll') if args.dll else None,
        'packSha256':digest_file(pack/'manifest.json'),'portsSha256':digest_file(ports/'ports.json'),
        'startedAt':datetime.now(timezone.utc).isoformat(),'newModelCalls':0,
        'limits':{'cpuSecondsPerTask':CPU_SECONDS,'wallSecondsPerTask':WALL_SECONDS,'totalSeconds':TOTAL_SECONDS}}
    write_json(out/'execution.json',receipt)
    tasks=[]
    start=time.monotonic()
    with gzip.open(out/'cases.jsonl.gz','wt',encoding='utf-8') as raw, gzip.open(out/'processes.jsonl.gz','wt',encoding='utf-8') as processes:
        for item in inventory:
            tid=item['taskId']
            if args.only and tid not in args.only:
                continue
            cases=pack/'cases'/(filename(tid)+'.json')
            port=emitted[tid]
            assert digest_file(cases)==item['taskFileSha256']
            record={key:value for key,value in item.items() if key not in ['caseKeys','statement','contract']}
            record['port']=port
            result={}
            process=None
            if time.monotonic()-start>TOTAL_SECONDS:
                error='TOTAL_TIME_LIMIT'
            elif port['status']!='EMITTED':
                error='PORT_NOT_EMITTED'
            else:
                code=ports/(filename(tid)+'.js')
                assert digest_file(code)==port['sha256']
                entry=args.dll if args.engine=='jint' else node_helper
                process=task_run(list(map(str,[args.executable,entry,cases,runtime,code])))
                processes.write(canonical({'taskId':tid,**process})+'\n')
                if process['exitCode']==0:
                    try:
                        result=json.loads(process['stdout'])
                        assert result['taskId']==tid and result['total']==item['projected']
                        error=result.get('error')
                    except (ValueError, KeyError, AssertionError, TypeError):
                        result={}
                        error='INVALID_PROCESS_RECORD'
                else:
                    error='WALL_LIMIT' if process['wallTimeout'] else f"PROCESS_EXIT_{process['exitCode']}"
            by_failure={f['index']:f for f in result.get('failures',[])}
            assert len(by_failure)==len(result.get('failures',[]))
            observed=result.get('passed',0)+len(by_failure)
            assert observed<=item['projected'] and set(by_failure).issubset(range(observed))
            assert error or observed==item['projected']
            counts=Counter()
            for index,case in enumerate(item['caseKeys']):
                failure=by_failure.get(index)
                outcome='UNKNOWN' if index>=observed else 'ERROR' if failure and failure.get('error') else 'MISMATCH' if failure else 'PASS'
                counts[outcome]+=1
                raw.write(canonical({'taskId':tid,**case,'outcome':outcome,**({'failure':failure} if failure else {})})+'\n')
            for case in item.get('missingCases',[]):
                counts['MISSING_REFERENCE']+=1
                raw.write(canonical({'taskId':tid,'case':case,'outcome':'MISSING_REFERENCE'})+'\n')
            for case in item.get('unprojectable',[]):
                counts['UNPROJECTABLE']+=1
                raw.write(canonical({'taskId':tid,**case,'outcome':'UNPROJECTABLE'})+'\n')
            if args.final:
                assert sum(counts.values())==item['planned']
            record.update(status='AGREES' if not error and counts['PASS']==item['planned'] and not item['projectionCollisions'] else 'BLOCKED',
                          counts=dict(counts),executionError=error,firstDisagreements=list(by_failure.values())[:4],
                          durationMs=result.get('durationMs'),processSeconds=process['seconds'] if process else None)
            tasks.append(record)
            if record['status']!='AGREES' or len(tasks)%25==0:
                print(len(tasks),tid,record['status'],dict(counts),error or '',flush=True)
    stats=Counter()
    for task in tasks:
        stats.update(task['counts'])
    summary={'engine':args.engine,'population':population,'taskCount':len(tasks),'agreeingTasks':sum(t['status']=='AGREES' for t in tasks),
             'caseCounts':dict(stats),'plannedCases':sum(t['planned'] for t in tasks),'tasks':tasks}
    write_json(out/'summary.json',summary)
    receipt.update(endedAt=datetime.now(timezone.utc).isoformat(),wallSeconds=round(time.monotonic()-start,4),
                   taskCount=len(tasks),artifactSha256={str(p.relative_to(out)):digest_file(p) for p in out.rglob('*')
                                                       if p.is_file() and p.name!='execution.json'})
    write_json(out/'execution.json',receipt)
    print({k:v for k,v in summary.items() if k!='tasks'},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--engine',choices=['jint','node'],required=True)
    parser.add_argument('--executable',type=Path,required=True)
    parser.add_argument('--dll',type=Path)
    parser.add_argument('--pack',type=Path,required=True)
    parser.add_argument('--ports',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--only',nargs='+')
    parser.add_argument('--final',action='store_true')
    a=parser.parse_args()
    if a.engine=='jint' and not a.dll:
        parser.error('--dll is required for Jint')
    replay(a)
