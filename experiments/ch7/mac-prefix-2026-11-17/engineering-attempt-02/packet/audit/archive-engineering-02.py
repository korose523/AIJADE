"""Lossless, exact-population public engineering packet; never alters live originals."""
from pathlib import Path
from datetime import datetime,timezone
import gzip, hashlib, json, os, subprocess, urllib.request

B=Path('/Volumes/Untitled/AIJADE'); C=Path(__file__).parent
W=B/'.runtime/posix/research/ch7-prefix-20261117/worktree'
R=B/'.runtime/posix/runs/ch7-prefix-20261117/engineering-02'
T=C/'attempt-02-packet'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def git(*args,input=None,env=None):return subprocess.check_output(['git',*args],cwd=W,input=input,env=env)
assert not T.exists()
accept_path=C/'analysis/engineering02-acceptance.json';accepted=read(accept_path)
assert accepted['status']=='FULL_EQUAL_LOAD_ENGINEERING_ACCEPTED_NOT_BACKEND_QUALIFIED'
assert accepted['independentEngineeringReplayAccepted'] is True and accepted['backendQualified'] is False
assert git('rev-parse','HEAD').decode().strip()==accepted['sourceCommit']
assert not git('status','--porcelain')
freeze=read(C/'engineering02-freeze-publication.json')['engineeringFreezeCommit']
T.mkdir()
entries=[]
def put(relative,raw,logical=None):
    path=T/relative;assert not path.exists();path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw);path.chmod(0o644)
    entry=dict(path=relative,sha256=sha(raw),sizeBytes=len(raw))
    if logical is not None:entry.update(logicalSha256=sha(logical),logicalSizeBytes=len(logical),encoding='gzip-mtime-zero')
    entries.append(entry)
def copy(source,relative=None):
    source=Path(source);put(relative or source.name,source.read_bytes())
assert {p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file()}==set(accepted['inputFiles'])
for relative,item in sorted(accepted['inputFiles'].items()):
    raw=(R/relative).read_bytes();assert sha(raw)==item['sha256'] and len(raw)==item['sizeBytes']
    prefix='run/engineering-02/'+relative
    if relative.endswith('.jsonl') and raw:
        encoded=gzip.compress(raw,compresslevel=9,mtime=0)
        assert gzip.decompress(encoded)==raw
        put(prefix+'.gz',encoded,raw)
    else:put(prefix,raw)
for name in ('engineering-02-launch.json','engineering-02-launch.terminal.json','engineering-02-launch.log'):
    copy(C/name,'launch/'+name)
for name in ('engineering02-freeze-publication.json','engineering-02-passport.json'):
    copy(C/name,'publication/'+name)
for name in ('independent-equal-load-audit-02.json','independent-equal-load-audit-02-full-raw-replay.json',
             'engineering02-acceptance.json','engineering02-parent-and-cost-review.json',
             'engineering02-parent-and-cost-review.md'):
    copy(C/'analysis'/name,'audit/'+name)
for name in ('accept-engineering-02.py','archive-engineering-02.py'):
    copy(C/name,'audit/'+name)
summary=dict(schema='aijade.ch7.equal-load-engineering-summary.v1',sourceCommit=accepted['sourceCommit'],
    engineeringFreezeCommit=freeze,status=accepted['status'],numbers=accepted['numbers'],
    managedTasks=accepted['managedTasks'],lifecycle=accepted['lifecycle'],
    completePopulation=362,qualificationStarted=False,backendQualified=False,scientificAdmission=False,
    formalHardwareQualification=False,independentHumanReview=False,seedConstructed=False,freshHeldoutCases=0,
    table7_3='NOT_RUN',incidentalConcurrentActivityDisclosed=True)
put('summary.json',(json.dumps(summary,indent=2)+'\n').encode())
put('README.md',b'''# Complete prefix-validation engineering evaluation 02

All 362 original observations (300 settling, 60 admission-like, two engineering
tail) and every finite task are retained. Nonempty JSONL streams are deterministic
gzip, with both physical and logical bytes/SHA256 in packet-manifest.json.
Original launch and terminal records retain their original self-reported status;
the separate acceptance binds full cold replay and independently checked parent
wait evidence. No row, deadline or denominator is replaced after observation.

This is engineering acceptance only. There is no scientific qualification,
model request, business flow, renderer, fresh seed or heldout comparison. Table
7.3 remains NOT_RUN. The earlier refused ten-row engineering attempt and all
older refusals remain in the repository. A small concurrent read-only readiness
review/report write is disclosed in the acceptance and parent/cost review; no
fully idle host or single-component causal speedup is claimed.

The frozen full auditor is in engineering-freeze-02/audit_equal_load.py. Its
original Mac audit checks physical SDK identities; public records replay does not
recheck remote machines or manufacture those SDK files. This packet stores the
actual independent Mac audit, raw data and source/freeze bindings unchanged.
''')
manifest=dict(schema='aijade.ch7.equal-load-engineering-packet.v1',sourceCommit=accepted['sourceCommit'],
    engineeringFreezeCommit=freeze,files=sorted(entries,key=lambda v:v['path']),
    originalRunDirectories=sorted(p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_dir()),
    originalRunFiles=accepted['inputFiles'],mode='100644',qualificationStarted=False,backendQualified=False)
put('packet-manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
assert len(entries)==len(manifest['files'])+1
for row in entries:
    raw=(T/row['path']).read_bytes();assert sha(raw)==row['sha256'] and len(raw)==row['sizeBytes']
    if 'logicalSha256' in row:
        logical=gzip.decompress(raw)
        assert sha(logical)==row['logicalSha256'] and len(logical)==row['logicalSizeBytes']
ref='refs/heads/publication/ch7-prefix-engineering02-accepted-20261117'
assert subprocess.run(['git','show-ref','--verify','--quiet',ref],cwd=W).returncode!=0
index=C/'engineering02-accepted.index';assert not index.exists();env=dict(os.environ,GIT_INDEX_FILE=str(index))
git('read-tree',freeze,env=env)
published=[]
for row in entries:
    raw=(T/row['path']).read_bytes()
    relative='experiments/ch7/mac-prefix-2026-11-17/engineering-attempt-02/packet/'+row['path']
    blob=git('hash-object','-w','--stdin',input=raw,env=env).decode().strip()
    git('update-index','--add','--cacheinfo','100644,'+blob+','+relative,env=env)
    published.append(dict(path=relative,sha256=row['sha256'],sizeBytes=row['sizeBytes']))
tree=git('write-tree',env=env).decode().strip()
commit=git('commit-tree',tree,'-p',freeze,input=b'research(ch7): retain complete equal-load engineering acceptance and original raw population\n',env=env).decode().strip()
git('update-ref',ref,commit,'0'*40,env=env);git('push','origin',ref,env=env)
assert git('ls-remote','origin',ref).decode().split()[0]==commit
for item in published:
    with urllib.request.urlopen('https://raw.githubusercontent.com/korose523/AIJADE/'+commit+'/'+item['path'],timeout=60) as response:raw=response.read()
    assert sha(raw)==item['sha256'] and len(raw)==item['sizeBytes']
index.unlink()
result=dict(status='COMPLETE_ENGINEERING_ACCEPTANCE_AND_ALL_ORIGINAL_ROWS_PUBLIC',publicationCommit=commit,
    sourceCommit=accepted['sourceCommit'],engineeringFreezeCommit=freeze,tree=tree,
    files=published,packetManifestSha256=sha((T/'packet-manifest.json').read_bytes()),
    acceptanceSha256=sha(accept_path.read_bytes()),at=datetime.now(timezone.utc).isoformat(),
    qualificationStarted=False,backendQualified=False,seedConstructed=False,freshHeldoutCases=0)
destination=C/'engineering02-acceptance-publication.json';assert not destination.exists()
destination.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
