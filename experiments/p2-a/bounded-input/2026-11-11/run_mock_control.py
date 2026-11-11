"""Normal RQ-C simulation, checked prefix continuation and fail-closed policy controls."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
from budget_common import ROOT,file_sha,load,write

def rows(path):
    with path.open() as f:return [json.loads(line) for line in f]
def run(dotnet,dll,bank,policy,other_policy,out):
    out.mkdir(parents=True,exist_ok=False)
    common=[str(dotnet),str(dll),'--public-bank',str(bank),'--request-policy',str(policy),'--trials','1','--rounds','1','--tasks','12','--p-correct','1','--save-candidates']
    def invoke(command,target,expected=0):
        with (out/(target+'.stdout.log')).open('wb') as stdout,(out/(target+'.stderr.log')).open('wb') as stderr:
            result=subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr)
        assert result.returncode==expected,(target,result.returncode)
        return result.returncode
    invoke(common+['--out',str(out/'full')],'full')
    directories=list((out/'full').iterdir());assert len(directories)==1;full=directories[0]
    summary=load(full/'summary.json');assert summary['mode']=='simulation' and summary['requestPolicy']['requestsChecked']==0
    actual=rows(full/'trials.jsonl');assert len(actual)==48 and all(row['execOk'] for row in actual)
    cut=out/'prefix-32';cut.mkdir()
    for name in ['trials.jsonl','candidates.jsonl']:
        with (full/name).open() as src,(cut/name).open('w') as dst:
            for _,line in zip(range(32),src):dst.write(line)
    invoke(common+['--resume-from',str(cut/'candidates.jsonl'),'--out',str(out/'resumed')],'resumed')
    resumed=next((out/'resumed').iterdir());continued=load(resumed/'summary.json')
    assert continued['resumed']['replayedSteps']==32 and continued['fingerprint']==summary['fingerprint']
    for name in ['trials.jsonl','candidates.jsonl']:
        def decisions(path):
            data=rows(path)
            for row in data:row.pop('durationMs',None)
            return data
        assert decisions(full/name)==decisions(resumed/name),name
    negative=[]
    def reject(policy_file,label,resume=False):
        command=list(common);command[command.index('--request-policy')+1]=str(policy_file)
        output=out/('reject-'+label)
        if resume:command+=['--resume-from',str(cut/'candidates.jsonl')]
        invoke(command+['--out',str(output)],'reject-'+label,1)
        assert not output.exists(),label
        negative.append({'id':label,'exitCode':1,'outputCreated':False})
    reject(other_policy,'resume-other-policy',True)
    base=load(policy);profile=load(Path(base['exposureFile']))
    mutations=out/'negative-inputs';mutations.mkdir()
    for label in ['invalid-index','wrong-bank','changed-counter']:
        altered=json.loads(json.dumps(base))
        if label=='changed-counter':
            script=mutations/'changed-counter.py';script.write_bytes(Path(base['counter']['script']).read_bytes()+b'\n')
            altered['counter']['script']=str(script)  # keep the original expected hash
        else:
            data=json.loads(json.dumps(profile))
            if label=='invalid-index':data['tasks'][0]['selectedCaseIndices']=[data['tasks'][0]['caseCount']]
            else:data['bankManifestSha256']='0'*64
            path=mutations/(label+'-exposure.json');write(path,data)
            altered.update(exposureFile=str(path),exposureSha256=file_sha(path))
        path=mutations/(label+'-policy.json');write(path,altered);reject(path,label)
    report={'schema':'aijade.p2a.bounded-input.mock-control.v1','status':'PASS','steps':48,'executionsPassed':48,'replayedSteps':32,
            'completeDecisionEqualityWithoutDurations':True,'negativeChecks':negative,'policySha256':file_sha(policy),'pCorrect':1,
            'modelCompletionCalls':0,'externalTokenCounterCalls':0,'scope':'Normal CLI simulation and resume control; no model reliability observations.'}
    write(out/'summary.json',report);print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    for name in ['dotnet','dll','bank','policy','other-policy','out']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.dotnet.resolve(),a.dll.resolve(),a.bank.resolve(),a.policy.resolve(),a.other_policy.resolve(),a.out.resolve())
