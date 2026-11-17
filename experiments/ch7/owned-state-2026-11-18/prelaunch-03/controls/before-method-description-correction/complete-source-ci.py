"""Retain actual source CI only after completed successful matching Git head."""
from pathlib import Path
import hashlib,json,subprocess
C=Path(__file__).resolve().parent
q=json.loads((C/'source-freeze-qe4.json').read_bytes())['commit']
run='44137267049';gh='/Users/mac/.local/bin/gh'
raw=subprocess.check_output([gh,'run','view',run,'--repo','korose523/AIJADE','--json','databaseId,headSha,status,conclusion,url,name,workflowName,createdAt,startedAt,updatedAt,jobs'])
v=json.loads(raw)
assert v['headSha']==q and v['databaseId']==int(run)
assert v['status']=='completed' and v['conclusion']=='success', 'actual source CI not completed successfully'
assert all(j['status']=='completed' and j['conclusion']=='success' for j in v['jobs'])
log=subprocess.check_output([gh,'run','view',run,'--repo','korose523/AIJADE','--log'])
assert b'3.12.14' in log and b'setup-python' in log
with (C/'source-qe4-ci-full.log').open('xb') as f:f.write(log)
v['completeLogSha256']=hashlib.sha256(log).hexdigest();v['completeLogPath']=str(C/'source-qe4-ci-full.log')
v['localInterpretation']='Actual cross-platform source/control CI, not real Mac nested-load or backend qualification.'
with (C/'source-qe4-ci.json').open('x') as f:json.dump(v,f,indent=2);f.write('\n')
print(json.dumps({k:v[k] for k in ['databaseId','headSha','status','conclusion','url','completeLogSha256']},indent=2))
