from pathlib import Path
import hashlib,json,subprocess,sys,datetime,os
C=Path(__file__).parent;W=Path('/Volumes/Untitled/AIJADE/.runtime/posix/research/ch7-lifecycle-20261117/worktree');Q=subprocess.check_output(['git','rev-parse','HEAD'],cwd=W,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=W)
paths=sorted(set(W.glob('experiments/ch7/*.py'))|set(W.glob('experiments/ch7/*.c'))|set(W.glob('tests/shell/test*.py'))|set(W.glob('configs/research/*.json')))
def snapshot():return {str(p.relative_to(W)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
before=snapshot();log=C/'all-python-controls-source-bound.log'
with log.open('x') as f:r=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests/shell','-p','test_*.py','-v'],cwd=W,env=dict(os.environ,AIJADE_NATIVE_CONTROLS_ROOT=str(C)),stdout=f,stderr=subprocess.STDOUT)
after=snapshot();assert not subprocess.check_output(['git','status','--porcelain'],cwd=W)
result=dict(commit=Q,checkedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),exitCode=r.returncode,unchanged=before==after,files=before,logSha256=hashlib.sha256(log.read_bytes()).hexdigest(),tail=log.read_text()[-2400:])
(C/'all-python-controls-source-bound.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({**result,'files':len(before)}));assert r.returncode==0 and before==after
