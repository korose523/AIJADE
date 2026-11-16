from pathlib import Path
import hashlib,json,subprocess,sys,time
C=Path(__file__).resolve().parent;W=C/'worktree'
paths=sorted(set(W.glob('experiments/ch7/*.py'))|set(W.glob('tests/shell/test*.py'))|set(W.glob('configs/research/*.json')))
def snapshot():return {str(p.relative_to(W)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
before=snapshot();log=C/'python-controls-source-bound-portable.log'
with log.open('x') as f:r=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests/shell','-p','test_*.py','-v'],cwd=W,stdout=f,stderr=subprocess.STDOUT)
after=snapshot();status={'exitCode':r.returncode,'unchanged':before==after,'files':before,'logSha256':hashlib.sha256(log.read_bytes()).hexdigest(),'logTail':log.read_text()[-1800:]}
(C/'python-controls-source-bound-portable.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status|{'files':len(before)}));assert r.returncode==0 and before==after
