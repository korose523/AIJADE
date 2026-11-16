from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess
C=Path(__file__).resolve().parent;W=C/'worktree';frozen=C/'frozen-build.json'
build=json.loads(frozen.read_text());source=build['commit'];path='experiments/ch7/relocated-runtime-2026-11-16/frozen-build.json'
def git(*args,**kwargs):return subprocess.check_output(['git',*args],cwd=W,**kwargs)
assert git('rev-parse','HEAD',text=True).strip()==source and git('status','--porcelain',text=True)==''
env=dict(os.environ,GIT_INDEX_FILE=str(C/'build-freeze.index'));assert not Path(env['GIT_INDEX_FILE']).exists()
subprocess.run(['git','read-tree',source],cwd=W,env=env,check=True)
blob=git('hash-object','-w',str(frozen),text=True).strip()
subprocess.run(['git','update-index','--add','--cacheinfo','100644,'+blob+','+path],cwd=W,env=env,check=True)
tree=git('write-tree',text=True,env=env).strip()
body=C/'build-freeze-commit-message.txt';body.write_text('Freeze actual relocated build identities before the single known-input admission\n\nExecution remains on source '+source+'. This evidence-only child commit adds the measured assembly/dependency identities without changing the execution worktree or its embedded source revision.\n')
commit=git('commit-tree',tree,'-p',source,'-F',str(body),text=True).strip()
branch='evidence/ch7-relocated-build-20261116';subprocess.run(['git','update-ref','refs/heads/'+branch,commit,'0'*40],cwd=W,check=True)
assert git('diff-tree','--no-commit-id','--name-only','-r',commit,text=True).splitlines()==[path]
subprocess.run(['git','push','origin',branch],cwd=W,check=True)
remote=json.loads(subprocess.check_output(['gh','api','repos/korose523/AIJADE/git/ref/heads/'+branch],cwd=W))
assert remote['object']['sha']==commit and git('show',commit+':'+path)==frozen.read_bytes()
assert git('rev-parse','HEAD',text=True).strip()==source and git('status','--porcelain',text=True)==''
receipt=dict(status='ACTUAL_BINARY_IDENTITIES_PUBLIC_BEFORE_ADMISSION',checkedAt=datetime.now(timezone.utc).isoformat(),
             sourceCommit=source,buildFreezeCommit=commit,evidenceBranch=branch,path=path,blob=blob,
             frozenBuildSha256=hashlib.sha256(frozen.read_bytes()).hexdigest(),dependencyFiles=len(build['files']),
             worktreeSourceRevisionUnchanged=True,qualificationWindowStarted=False)
(C/'binary-freeze-publication.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
