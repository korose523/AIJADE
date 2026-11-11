"""Actual normal-CLI simulation and prefix replay for both banks and instruction versions."""
import argparse,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT/'experiments/p2-a/bounded-input/2026-11-11'))
from budget_common import load,write,file_sha

def rows(path):return [json.loads(line) for line in path.read_text().splitlines()]
def run(dotnet,dll,bank,policies,out):
 out.mkdir(parents=True,exist_ok=False);reports=[]
 for source in ['builtin','public']:
  for version,other in [('listed-v1','whole-task-v2'),('whole-task-v2','listed-v1')]:
   folder=out/(source+'-'+version);folder.mkdir();policy=policies/(source+'-'+version+'-qwen.json')
   common=[str(dotnet),str(dll),'--request-policy',str(policy),'--trials','1','--rounds','1','--tasks','3','--p-correct','1','--save-candidates']
   if source=='public':common+=['--public-bank',str(bank)]
   def invoke(command,label,expected=0):
    with (folder/(label+'.stdout.log')).open('wb') as stdout,(folder/(label+'.stderr.log')).open('wb') as stderr:
     result=subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr)
    assert result.returncode==expected,(source,version,label,result.returncode)
   invoke(common+['--out',str(folder/'full')],'full');full=next((folder/'full').iterdir())
   summary=load(full/'summary.json');assert summary['mode']=='simulation' and summary['requestPolicy']['requestsChecked']==0
   actual=rows(full/'trials.jsonl');assert len(actual)==12 and all(row['execOk'] for row in actual)
   assert all(row['verifierInstructionVersion']==version for row in actual)
   cut=folder/'prefix-8';cut.mkdir()
   for name in ['trials.jsonl','candidates.jsonl']:(cut/name).write_text(''.join((full/name).read_text().splitlines(keepends=True)[:8]))
   invoke(common+['--resume-from',str(cut/'candidates.jsonl'),'--out',str(folder/'resumed')],'resumed')
   resumed=next((folder/'resumed').iterdir());continued=load(resumed/'summary.json');assert continued['resumed']['replayedSteps']==8
   assert continued['fingerprint']==summary['fingerprint']
   for name in ['trials.jsonl','candidates.jsonl']:
    a=rows(full/name);b=rows(resumed/name)
    for row in a+b:row.pop('durationMs',None)
    assert a==b,(source,version,name)
   negative=[];mutations=folder/'negative-inputs';mutations.mkdir();base=load(policy)
   for label in ['other-version-resume','seed-resume','wrong-bank','changed-counter','invalid-index']:
    command=list(common);altered=json.loads(json.dumps(base))
    if label=='other-version-resume':path=policies/(source+'-'+other+'-qwen.json')
    elif label=='seed-resume':path=policy;command+=['--seed','2']
    else:
     if label=='changed-counter':
      changed=mutations/'changed-counter.py';changed.write_bytes(Path(base['counter']['script']).read_bytes()+b'\n');altered['counter']['script']=str(changed)
     else:
      profile=load(Path(base['exposureFile']))
      if label=='wrong-bank':profile['bankManifestSha256']='0'*64
      else:profile['tasks'][0]['selectedCaseIndices']=[profile['tasks'][0]['caseCount']]
      profile_path=mutations/(label+'-exposure.json');write(profile_path,profile);altered.update(exposureFile=str(profile_path),exposureSha256=file_sha(profile_path))
     path=mutations/(label+'-policy.json');write(path,altered)
    command[command.index('--request-policy')+1]=str(path)
    if label.endswith('resume'):command+=['--resume-from',str(cut/'candidates.jsonl')]
    target=folder/('reject-'+label);invoke(command+['--out',str(target)],'reject-'+label,1)
    assert not target.exists();negative.append(dict(id=label,exitCode=1,outputCreated=False))
   reports.append(dict(source=source,instructionVersion=version,policySha256=file_sha(policy),steps=12,replayedSteps=8,completeDecisionEqualityWithoutDurations=True,negativeChecks=negative))
 report=dict(schema='aijade.p2.matched-cli-controls.v1',status='PASS',groups=reports,steps=48,replayedSteps=32,identityRejections=20,newModelCompletionCalls=0,externalTokenCounterCalls=0)
 write(out/'summary.json',report);print(json.dumps(report,indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__)
 for key in ['dotnet','dll','bank','policies','out']:p.add_argument('--'+key,type=Path,required=True)
 a=p.parse_args();run(a.dotnet.resolve(),a.dll.resolve(),a.bank.resolve(),a.policies.resolve(),a.out.resolve())
