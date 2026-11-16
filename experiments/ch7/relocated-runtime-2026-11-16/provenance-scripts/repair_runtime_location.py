from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,shutil,subprocess,time,traceback
C=Path(__file__).resolve().parent;BASE=Path('/Volumes/Untitled/AIJADE');STATE=BASE/'.runtime/posix'
first=json.loads((C/'runtime-setup.json').read_text());assert first['status']=='RUNTIME_PRECONDITION_STOP'
shutil.copy2(C/'runtime-setup.json',C/'runtime-setup-first.json');steps=[];env=dict(os.environ)
started=datetime.fromisoformat(first['startedAt']);began=time.monotonic();used=(datetime.now(timezone.utc)-started).total_seconds()
def remaining():return 1800-used-(time.monotonic()-began)
def save(status,**extra):
    (C/'runtime-setup.json').write_text(json.dumps(dict(status=status,planCommit=first['planCommit'],startedAt=first['startedAt'],checkedAt=datetime.now(timezone.utc).isoformat(),elapsedSeconds=1800-remaining(),initialFailureRetained='runtime-setup-first.json',steps=first['steps']+steps,vmStartInvocations=2,qualificationAdmissionStarted=False,**extra),indent=2)+'\n')
def run(name,args,limit=300):
    assert remaining()>0
    p=C/(name+'.log');assert not p.exists()
    with p.open('x') as f:r=subprocess.run(args,cwd=BASE,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=min(limit,remaining()))
    steps.append(dict(name=name,command=args,exitCode=r.returncode,log=str(p.relative_to(BASE))))
    save('RUNTIME_PREPARATION_RUNNING');assert r.returncode==0,(name,r.returncode)
    return p.read_text()
try:
    home=STATE/'colima';home.mkdir(mode=0o700,exist_ok=False)
    moved=[]
    for source,target in [(Path('/Users/mac/.colima/default'),home/'default'),(Path('/Users/mac/.colima/ssh_config'),home/'ssh_config')]:
        assert source.exists() and not target.exists()
        files=[source] if source.is_file() else [p for p in source.rglob('*') if p.is_file()]
        assert files and all(p.stat().st_mtime>=started.timestamp() for p in files),'Do not move unrelated old state.'
        rows=[dict(relative='' if p==source else str(p.relative_to(source)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
        if source.is_dir():shutil.copytree(source,target)
        else:shutil.copy2(source,target)
        for row in rows:
            dest=target if row['relative']=='' else target/row['relative'];assert hashlib.sha256(dest.read_bytes()).hexdigest()==row['sha256']
        if source.is_dir():shutil.rmtree(source)
        else:source.unlink()
        moved.append(dict(source=str(source),destination=str(target),files=rows))
    (C/'colima-path-fallback-relocation.json').write_text(json.dumps(dict(reason='COLIMA_HOME must already exist; otherwise the installed implementation falls back to the existing default home. The first owned VM was stopped before moving only its newly written profile/config.',moves=moved,olderSharedColimaStatePreserved=True),indent=2)+'\n')
    env.update(COLIMA_HOME=str(home),LIMA_HOME=str(STATE/'lima'),COLIMA_CACHE_HOME=str(BASE/'.runtime/cache/colima'),DOCKER_CONFIG=str(BASE/'.runtime/docker'),DOCKER_HOST='unix://'+str(home/'default/docker.sock'))
    shutil.copy2(C/'service-environment.json',C/'service-environment-before-path-repair.json')
    (C/'service-environment.json').write_text(json.dumps({k:env[k] for k in ['COLIMA_HOME','LIMA_HOME','COLIMA_CACHE_HOME','DOCKER_CONFIG','DOCKER_HOST']},indent=2)+'\n')
    run('colima-start-02',['/Users/mac/.local/bin/colima','start','--runtime','docker','--vm-type','vz','--cpus','2','--memory','2','--root-disk','8','--disk','8','--mount','none','--ssh-agent=false','--ssh-config=false','--kubernetes=false','--binfmt=false'],600)
    run('docker-version-after-path-repair',['/Users/mac/.local/bin/docker','version'],30)
    run('postgres-pull',['/Users/mac/.local/bin/docker','pull','ghcr.io/tensorchord/vchord-postgres:pg18-v1.0.0'],300)
    run('redis-pull',['/Users/mac/.local/bin/docker','pull','redis:7-alpine'],180)
    run('postgres-start',['/Users/mac/.local/bin/docker','run','-d','--name','aijade-next-db','-e','POSTGRES_PASSWORD=aijade','-e','POSTGRES_USER=aijade','-e','POSTGRES_DB=aijade','-p','127.0.0.1:55432:5432','--memory','768m','ghcr.io/tensorchord/vchord-postgres:pg18-v1.0.0'],60)
    run('redis-start',['/Users/mac/.local/bin/docker','run','-d','--name','aijade-next-redis','-p','127.0.0.1:56379:6379','--memory','128m','redis:7-alpine'],60)
    ready=False
    for _ in range(30):
        r=subprocess.run(['/Users/mac/.local/bin/docker','exec','aijade-next-db','pg_isready','-U','aijade'],cwd=BASE,env=env,capture_output=True,text=True)
        if r.returncode==0:ready=True;break
        time.sleep(1)
    assert ready
    run('postgres-version-and-extension',['/Users/mac/.local/bin/docker','exec','aijade-next-db','psql','-X','-U','aijade','-d','aijade','-v','ON_ERROR_STOP=1','-Atc',"SELECT version(); SELECT name,default_version FROM pg_available_extensions WHERE name IN ('vector','vchord') ORDER BY name;"],30)
    run('runtime-images',['/Users/mac/.local/bin/docker','inspect','aijade-next-db','aijade-next-redis'],30)
    assert not Path('/Users/mac/.colima/default').exists() and not Path('/Users/mac/.colima/docker.sock').exists()
    save('PROJECT_LOCAL_RUNTIME_READY',stateRoot=str(STATE),sparseImage=str(BASE/'.runtime/aijade-runtime-20261116.sparseimage'),vmCpu=2,vmMemoryGiB=2,newHeldoutCases=0)
    print(json.dumps(dict(status='PROJECT_LOCAL_RUNTIME_READY',elapsedSeconds=1800-remaining())))
except BaseException as e:
    save('RUNTIME_PRECONDITION_STOP',error=type(e).__name__+': '+str(e),traceback=traceback.format_exc());raise
