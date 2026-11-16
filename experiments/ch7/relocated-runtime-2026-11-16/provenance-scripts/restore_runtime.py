from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,time,traceback

C=Path(__file__).resolve().parent;BASE=Path('/Volumes/Untitled/AIJADE');STATE=BASE/'.runtime/posix'
published=json.loads((C/'prospective-plan-publication.json').read_text());assert published['status']=='PLAN_ALONE_PUBLIC_BEFORE_IMPLEMENTATION_AND_SERVICE_SETUP'
assert json.loads((C/'permission-precondition.json').read_text())['privateDirectoryModeSupported'] is False
start=time.monotonic();steps=[];env=dict(os.environ);receipt=C/'runtime-setup.json'
def utc():return datetime.now(timezone.utc).isoformat()
def write(status,**extra):
    receipt.write_text(json.dumps(dict(status=status,planCommit=published['commit'],startedAt=began,checkedAt=utc(),elapsedSeconds=time.monotonic()-start,steps=steps,qualificationAdmissionStarted=False,**extra),indent=2)+'\n')
def run(name,args,timeout=300):
    remaining=1800-(time.monotonic()-start);assert remaining>0,'runtime preparation budget exhausted'
    log=C/(name+'.log');assert not log.exists()
    with log.open('x') as f:r=subprocess.run(args,cwd=BASE,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=min(timeout,remaining))
    steps.append(dict(name=name,command=args,exitCode=r.returncode,log=str(log.relative_to(BASE)),endedAt=utc()))
    write('RUNTIME_PREPARATION_RUNNING');assert r.returncode==0,(name,r.returncode)
    return log.read_text()
began=utc();write('RUNTIME_PREPARATION_RUNNING')
try:
    image=BASE/'.runtime/aijade-runtime-20261116.sparseimage';assert not image.exists();STATE.mkdir(exist_ok=False)
    run('runtime-image-create',['hdiutil','create','-size','20g','-type','SPARSE','-fs','APFS','-volname','AIJADE_Runtime',str(image)],120)
    run('runtime-image-attach',['hdiutil','attach','-nobrowse','-mountpoint',str(STATE),str(image)],120)
    assert os.path.ismount(STATE)
    probe=STATE/'private-mode-probe';probe.mkdir(mode=0o700);assert (probe.stat().st_mode&0o777)==0o700;probe.rmdir()
    env.update(COLIMA_HOME=str(STATE/'colima'),LIMA_HOME=str(STATE/'lima'),DOCKER_CONFIG=str(BASE/'.runtime/docker'),
        DOCKER_HOST='unix://'+str(STATE/'colima/default/docker.sock'))
    (C/'service-environment.json').write_text(json.dumps({k:env[k] for k in ['COLIMA_HOME','LIMA_HOME','DOCKER_CONFIG','DOCKER_HOST']},indent=2)+'\n')
    run('colima-start-01',['/Users/mac/.local/bin/colima','start','--runtime','docker','--vm-type','vz','--cpus','2','--memory','2','--root-disk','8','--disk','8',
        '--mount','none','--ssh-agent=false','--ssh-config=false','--kubernetes=false','--binfmt=false'],900)
    run('docker-version',['/Users/mac/.local/bin/docker','version'],30)
    run('postgres-pull',['/Users/mac/.local/bin/docker','pull','ghcr.io/tensorchord/vchord-postgres:pg18-v1.0.0'],300)
    run('redis-pull',['/Users/mac/.local/bin/docker','pull','redis:7-alpine'],180)
    run('postgres-start',['/Users/mac/.local/bin/docker','run','-d','--name','aijade-next-db','-e','POSTGRES_PASSWORD=aijade','-e','POSTGRES_USER=aijade','-e','POSTGRES_DB=aijade',
        '-p','127.0.0.1:55432:5432','--memory','768m','ghcr.io/tensorchord/vchord-postgres:pg18-v1.0.0'],60)
    run('redis-start',['/Users/mac/.local/bin/docker','run','-d','--name','aijade-next-redis','-p','127.0.0.1:56379:6379','--memory','128m','redis:7-alpine'],60)
    # Bounded service startup, distinct from the later single idle admission.
    ready=False
    for _ in range(30):
        r=subprocess.run(['/Users/mac/.local/bin/docker','exec','aijade-next-db','pg_isready','-U','aijade'],env=env,cwd=BASE,capture_output=True,text=True)
        if r.returncode==0:ready=True;break
        time.sleep(1)
    assert ready,'PostgreSQL did not become ready in 30 seconds'
    run('postgres-version-and-extension',['/Users/mac/.local/bin/docker','exec','aijade-next-db','psql','-X','-U','aijade','-d','aijade','-v','ON_ERROR_STOP=1','-Atc',
        "SELECT version(); SELECT name,default_version FROM pg_available_extensions WHERE name IN ('vector','vchord') ORDER BY name;"],30)
    run('runtime-images',['/Users/mac/.local/bin/docker','inspect','aijade-next-db','aijade-next-redis'],30)
    write('PROJECT_LOCAL_RUNTIME_READY',stateRoot=str(STATE),sparseImage=str(image),vmCpu=2,vmMemoryGiB=2,newHeldoutCases=0)
    print(json.dumps(dict(status='PROJECT_LOCAL_RUNTIME_READY',elapsedSeconds=time.monotonic()-start)))
except BaseException as e:
    write('RUNTIME_PRECONDITION_STOP',error=type(e).__name__+': '+str(e),traceback=traceback.format_exc())
    print(receipt.read_text());raise
