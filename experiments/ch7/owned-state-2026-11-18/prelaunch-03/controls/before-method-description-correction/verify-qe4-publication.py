from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import urllib.request
import urllib.parse

B=Path('/Volumes/Untitled/AIJADE')
C=Path(__file__).parent
W=B/'.runtime/posix/nested-20261117/worktree'
Q=json.loads((C/'source-freeze-qe4.json').read_text())['commit']
S='e77afa10ff4cd0c81ea41ec8ec7db3de4b02db71'
branch='research/ch7-nested-20261117'
def git(*args):return subprocess.check_output(['git','--no-replace-objects','-C',str(W),*args])
assert git('rev-parse','HEAD').decode().strip()==Q and not git('status','--porcelain')
remote=git('ls-remote','--heads','origin','refs/heads/'+branch).decode().split()
assert remote==[Q,'refs/heads/'+branch]
names=[v.decode() for v in git('diff','--name-only','-z',S,Q).split(b'\0') if v]
def check(name):
    expected=git('show',Q+':'+name)
    url='https://raw.githubusercontent.com/korose523/AIJADE/'+Q+'/'+urllib.parse.quote(name,safe='/')
    with urllib.request.urlopen(url,timeout=45) as response:
        raw=response.read(2*1024*1024+1)
    assert raw==expected and len(raw)<=2*1024*1024,name
    return dict(path=name,url=url,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(check,names))
out=dict(status='REMOTE_QE_REF_AND_ALL_CHANGED_GIT_BLOBS_VERIFIED',sourceCommit=Q,
    baselineCommit=S,branch=branch,files=rows,changedFiles=len(rows),
    engineeringWindowStarted=False,backendQualified=False,seedConstructed=False)
path=C/'source-qe4-publication.json'
with path.open('x') as stream:json.dump(out,stream,indent=2);stream.write('\n')
print(json.dumps(dict(status=out['status'],sourceCommit=Q,files=len(rows),receipt=str(path)),indent=2))
