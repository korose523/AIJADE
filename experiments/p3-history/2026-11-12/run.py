#!/usr/bin/env python3
"""One non-resettable admission and one bounded serial history study attempt."""
import argparse,datetime as dt,gzip,hashlib,json,os,re,signal,subprocess,time
from pathlib import Path
import psutil

GIB=1024**3
PLAN='4acf473'
def sha(p):return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
def utc():return dt.datetime.now(dt.timezone.utc).isoformat()
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def main(a):
    repo=a.repo.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    assert subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)==''
    assert commit==os.environ['AIJADE_GIT_COMMIT'] and os.environ['DOTNET_PROCESSOR_COUNT']=='2'
    assert psutil.__version__=='7.2.2'
    assert sha(a.corpus)=='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
    freeze=json.loads(a.freeze.read_text());assert freeze['commit']==commit
    dll=repo/'tests/Aijade.Tests/bin/Release/net10.0/Aijade.Tests.dll'
    binaries={p.name:sha(p) for p in dll.parent.glob('*.dll')}
    assert binaries==freeze['binaries']
    assert '0.1.0+'+commit in freeze['assemblyInfoText']
    for row in json.loads((repo/'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json').read_text())['files']:
        assert sha(repo/row['path'])==row['sha256']
    write(out/'input-identities.json',freeze)
    started=time.monotonic();samples=[]
    with (out/'admission-telemetry.jsonl').open('x') as log:
        while True:
            now=time.monotonic();remaining=120-(now-started)
            procs=[p.info for p in psutil.process_iter(['pid','name']) if
                   (p.info['name'] or '').lower() in ['dotnet','ollama'] or 'godot' in (p.info['name'] or '').lower()]
            row=dict(utc=utc(),elapsedSeconds=now-started,availableBytes=psutil.virtual_memory().available,
                     swapUsedBytes=psutil.swap_memory().used,researchProcesses=procs)
            samples.append(row);log.write(json.dumps(row)+'\n');log.flush()
            if remaining<=0:break
            time.sleep(min(2,remaining))
    admission=dict(elapsedSeconds=samples[-1]['elapsedSeconds'],samples=len(samples),windowReset=False,
      minimumAvailableBytes=min(s['availableBytes'] for s in samples),
      swapRangeBytes=max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples),
      allResearchProcessesAbsent=all(not s['researchProcesses'] for s in samples))
    admission['admitted']=admission['minimumAvailableBytes']>=4*GIB and admission['swapRangeBytes']<=64*1024**2 and admission['allResearchProcessesAbsent']
    write(out/'admission.json',admission)
    if not admission['admitted']:
        write(out/'controller-receipt.json',dict(status='NOT_ADMITTED',codeCommit=commit,modelCalls=0,formalHardwareQualification=False))
        write(out/'database-cleanup.json',[]);print('NOT_ADMITTED',flush=True);return
    assert binaries=={p.name:sha(p) for p in dll.parent.glob('*.dll')}
    env=dict(os.environ,AIJADE_P3_HISTORY_OUT=str(out),AIJADE_P3E_CORPUS=str(a.corpus.resolve()),AIJADE_P3_HISTORY_PLAN=freeze['planCommit'])
    command=[str(a.dotnet),str(dll),'-method','Aijade.Tests.ProductHistoryRecordingTests.Complete_controlled_history_and_recording_trajectories','-xml',str(out/'flow.xml')]
    write(out/'launch.json',dict(utc=utc(),command=command,codeCommit=commit,processors=2,expectedTrajectories=50,expectedRows=9930))
    started=time.monotonic();initialSwap=psutil.swap_memory().used;timers={};reason=None
    peaks=dict(rssBytes=0,swapIncreaseBytes=0,minAvailableBytes=psutil.virtual_memory().available)
    with (out/'flow.log').open('x') as log,(out/'telemetry.jsonl').open('x') as telemetry:
        proc=subprocess.Popen(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            while proc.poll() is None:
                now=time.monotonic();rss=0
                try:
                    root=psutil.Process(proc.pid)
                    for p in [root]+root.children(recursive=True):
                        try:rss+=p.memory_info().rss
                        except psutil.Error:pass
                except psutil.Error:pass
                available=psutil.virtual_memory().available;swap=max(0,psutil.swap_memory().used-initialSwap)
                peaks['rssBytes']=max(peaks['rssBytes'],rss);peaks['swapIncreaseBytes']=max(peaks['swapIncreaseBytes'],swap)
                peaks['minAvailableBytes']=min(peaks['minAvailableBytes'],available)
                telemetry.write(json.dumps(dict(utc=utc(),elapsedSeconds=now-started,rssBytes=rss,availableBytes=available,swapIncreaseBytes=swap))+'\n');telemetry.flush()
                for name,crossed in [('rss',rss>2*GIB),('available',available<3*GIB),('swap',swap>GIB)]:
                    if not crossed:timers.pop(name,None)
                    else:
                        timers.setdefault(name,now)
                        if now-timers[name]>=30:raise RuntimeError(name+'_sustained_30s_stop')
                if now-started>=3600:raise RuntimeError('wall_3600s_stop')
                time.sleep(1)
            if proc.returncode:raise RuntimeError('flow_nonzero_exit')
        except Exception as error:reason=type(error).__name__+': '+str(error)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=10)
    cleanup=[]
    lease=out/'database-leases.jsonl'
    for line in lease.read_text().splitlines() if lease.exists() else []:
        row=json.loads(line);name=row['database'];assert re.fullmatch('aijade_test_[0-9a-f]{32}',name)
        command=[str(a.docker),'exec','aijade-next-db','psql','-U','aijade','-d','aijade','-At','-v','ON_ERROR_STOP=1','-c']
        check=subprocess.run(command+["SELECT count(*) FROM pg_database WHERE datname='"+name+"'"],capture_output=True,text=True,check=True)
        existed=check.stdout.strip()!='0'
        if existed:subprocess.run(command+['DROP DATABASE '+name+' WITH (FORCE)'],capture_output=True,text=True,check=True)
        final=subprocess.run(command+["SELECT count(*) FROM pg_database WHERE datname='"+name+"'"],capture_output=True,text=True,check=True)
        cleanup.append(dict(database=name,wasPresent=existed,absent=final.stdout.strip()=='0'))
    write(out/'database-cleanup.json',cleanup)
    closures=[]
    for p in sorted(out.glob('c*/*.gz')):
        try:
            with gzip.open(p,'rb') as z:
                while z.read(1024*1024):pass
            closed=True
        except (EOFError,OSError):closed=False
        closures.append(dict(path=str(p.relative_to(out)),sha256=sha(p),footerValid=closed))
    write(out/'gzip-closure.json',closures)
    unchanged=binaries=={p.name:sha(p) for p in dll.parent.glob('*.dll')}
    progress=json.loads((out/'batch-progress.json').read_text()) if (out/'batch-progress.json').exists() else None
    result=dict(status='COMPLETE' if reason is None and unchanged else 'STOPPED',reason=reason,codeCommit=commit,
      pid=proc.pid,exitCode=proc.returncode,wallSeconds=time.monotonic()-started,peaks=peaks,progress=progress,
      binariesUnchanged=unchanged,ownedProcessExited=not psutil.pid_exists(proc.pid),newModelCalls=0,formalHardwareQualification=False)
    write(out/'controller-receipt.json',result);print(json.dumps(result),flush=True)
    if result['status']!='COMPLETE':raise SystemExit(1)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['repo','out','freeze','corpus','dotnet','docker']:p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
