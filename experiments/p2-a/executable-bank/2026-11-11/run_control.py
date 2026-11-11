"""Normal public RQ-C CLI, interrupted-prefix continuation and identity rejection."""
import argparse,gzip,hashlib,json,os,resource,subprocess,sys
from collections import Counter
from pathlib import Path

CODE=Path(os.environ.get('AIJADE_NEXT', str(Path(__file__).resolve().parents[3]))).resolve()
STAGE=CODE/'experiments/p2-a/executable-bank/2026-11-11'
sys.path.insert(0,str(STAGE))
from export_bank import canonical,write_json,digest_file,load
sys.path.insert(0,str(CODE/'experiments/p2-a/candidate-review/2026-11-11'))
from recover255 import run_bounded


def limits():
    resource.setrlimit(resource.RLIMIT_CPU,(240,240))
    resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))


def main(bank,exe,dll,out):
    out.mkdir(parents=True,exist_ok=False)
    lock=load(STAGE/'input-lock.json')
    assert digest_file(bank)==lock['manifestSha256']
    env={'PATH':str(exe.parent)+os.pathsep+os.defpath,'DOTNET_ROOT':str(exe.parent),'TZ':'UTC','LC_ALL':'C',
         'AIJADE_GIT_COMMIT':subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip()}
    base=[str(exe),str(dll),'--public-bank',str(bank),'--seed','42','--trials','1','--rounds','1','--tasks','12','--p-correct','1','--save-candidates']
    def run(name,command):
        folder=out/name;folder.mkdir()
        proc=run_bounded(command,folder,env,wall=300,rss_limit=4*1024**3,stdout_name='stdout.log',limits=limits)
        write_json(folder/'process.json',proc)
        return proc
    proc=run('full',base+['--out',str(out/'full/run')])
    assert proc['exitCode']==0 and proc['stop'] is None,proc
    full=next((out/'full/run').glob('rq-c-*/summary.json')).parent
    summary=load(full/'summary.json')
    trials=list(map(json.loads,(full/'trials.jsonl').read_text().splitlines()))
    candidates=list(map(json.loads,(full/'candidates.jsonl').read_text().splitlines()))
    assert len(trials)==len(candidates)==48
    assert all(row['execOk'] for row in trials)
    assert all(row['publicBankManifestSha256']==lock['manifestSha256'] and row['runFingerprint']==summary['fingerprint'] for row in trials+candidates)
    split=out/'prefix';split.mkdir()
    for name in ['trials.jsonl','candidates.jsonl']:
        (split/name).write_text('\n'.join((full/name).read_text().splitlines()[:32])+'\n')
    proc2=run('resumed',base+['--resume-from',str(split/'candidates.jsonl'),'--out',str(out/'resumed/run')])
    assert proc2['exitCode']==0 and proc2['stop'] is None,proc2
    resumed=next((out/'resumed/run').glob('rq-c-*/summary.json')).parent
    rs=load(resumed/'summary.json');assert rs['resumed']['replayedSteps']==32
    timing=[]
    for name in ['trials.jsonl','candidates.jsonl']:
        first=list(map(json.loads,(full/name).read_text().splitlines()))
        second=list(map(json.loads,(resumed/name).read_text().splitlines()))
        assert len(first)==len(second)==48
        for i,(a,b) in enumerate(zip(first,second)):
            if name=='trials.jsonl': timing.append({'step':i,'originalMs':a.pop('durationMs'),'resumedMs':b.pop('durationMs')})
            assert a==b,(name,i)
    negatives={}
    changed=out/'manifest-whitespace.json';changed.write_bytes(bank.read_bytes()+b' ')
    definitions={
        'changedManifest':base[:2]+['--public-bank',str(changed)]+base[4:]+['--resume-from',str(split/'candidates.jsonl')],
        'changedDesign':base+['--trials','2','--resume-from',str(split/'candidates.jsonl')],
        'publicToLegacy':base[:2]+base[4:]+['--resume-from',str(split/'candidates.jsonl')],
    }
    for name,command in definitions.items():
        result=run(name,command+['--out',str(out/name/'run')])
        stderr=(out/name/'stderr.log').read_text()
        assert result['exitCode']!=0 and 'different public bank or run fingerprint' in stderr
        assert not (out/name/'run').exists()
        negatives[name]={'rejected':True,'process':result,'outputCreated':False}
    ids=[row['taskId'] for row in trials if row['condition']==trials[0]['condition']]
    assert len(set(ids))==12
    actual=summary['publicBank']['plannedExposurePerTask']
    counts=Counter(ids)
    assert set(actual)=={x['taskId'] for x in load(bank)['tasks']}
    assert all(value==counts[tid] for tid,value in actual.items())
    report={'schema':'aijade.p2a.public-bank.control.v1','newModelCalls':0,
        'normalCli':{'mode':summary['mode'],'steps':len(trials),'executionsPassed':sum(x['execOk'] for x in trials),
                     'manifestSha256':lock['manifestSha256'],'runFingerprint':summary['fingerprint'],
                     'selectedTaskIds':ids,'poolTasks':len(actual),'zeroExposureTasks':sum(x==0 for x in actual.values()),
                     'minExposure':min(actual.values()),'maxExposure':max(actual.values()),'process':proc},
        'resume':{'replayedSteps':32,'decisionsIdentical':True,'timingComparison':'timings preserved separately and excluded only from decision equality','process':proc2},
        'negativeChecks':negatives,'limits':{'wallSeconds':300,'cpuSeconds':240,'sampledRssBytes':4*1024**3,'processOutputBytes':64*1024**2},
        'binarySha256':digest_file(dll),'driverSha256':digest_file(Path(__file__)), 'executionCodeCommit':env['AIJADE_GIT_COMMIT']}
    write_json(out/'summary.json',report);write_json(out/'timing-comparison.json',timing)
    write_json(out/'paths.json',{'full':str(full),'resumed':str(resumed)})
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--bank',type=Path,required=True);p.add_argument('--executable',type=Path,required=True)
    p.add_argument('--dll',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();main(a.bank.resolve(),a.executable.resolve(),a.dll.resolve(),a.out.resolve())
