"""Bound a model-tokenizer process family and retain every result and failure."""
import argparse,hashlib,json,os,resource,signal,subprocess,time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()
def load(path):return json.loads(path.read_text())
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def limits():
    resource.setrlimit(resource.RLIMIT_CPU,(1200,1200))
    resource.setrlimit(resource.RLIMIT_FSIZE,(512*1024**2,512*1024**2))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
def seconds(value):
    day,clock=(value.split('-',1) if '-' in value else ('0',value));parts=clock.split(':')
    return int(day)*86400+sum(float(value)*60**i for i,value in enumerate(reversed(parts)))


def bounded(command,folder):
    folder.mkdir(parents=True,exist_ok=False)
    env={'PATH':'/usr/bin:/bin:/usr/local/bin','TZ':'UTC','LC_ALL':'C','TOKENIZERS_PARALLELISM':'false'}
    started=time.monotonic();peak=0;cpu_by_pid={};stop=None;samples=0
    with (folder/'stdout.log').open('wb') as out,(folder/'stderr.log').open('wb') as error:
        child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=out,stderr=error,start_new_session=True,preexec_fn=limits)
        while child.poll() is None:
            if time.monotonic()-started>1800:stop='WALL_LIMIT'
            process=subprocess.run(['/bin/ps','-A','-o','pid=,pgid=,rss=,time='],capture_output=True,text=True)
            family=[]
            for line in process.stdout.splitlines():
                parts=line.split()
                if len(parts)==4 and parts[1].isdigit() and int(parts[1])==child.pid:
                    pid=int(parts[0]);rss=int(parts[2])*1024;cpu_by_pid[pid]=max(cpu_by_pid.get(pid,0),seconds(parts[3]));family.append(rss)
            peak=max(peak,sum(family));samples+=1
            if peak>2*1024**3:stop='PROCESS_FAMILY_RSS_LIMIT'
            if sum(cpu_by_pid.values())>1200:stop='PROCESS_FAMILY_CPU_LIMIT'
            if stop:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                break
            time.sleep(.1)
        code=child.wait()
    result={'exitCode':code,'stop':stop,'wallSeconds':time.monotonic()-started,'sampledFamilyPeakRssBytes':peak,
            'sampledFamilyCpuSeconds':sum(cpu_by_pid.values()),'samples':samples,
            'stdoutSha256':digest(folder/'stdout.log'),'stderrSha256':digest(folder/'stderr.log'),
            'limits':{'cpuSeconds':1200,'wallSeconds':1800,'sampledFamilyRssBytes':2*1024**3,'perFileOutputBytes':512*1024**2}}
    write(folder/'process.json',result);return result


def run(inputs,python,native,out,controls_only,controls_from):
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(),'Freeze code before tokenizer measurement'
    out.mkdir(parents=True,exist_ok=False)
    source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    script=HERE/'tokenize_worker.py'
    receipt={'schema':'aijade.p2a.token-capacity.execution.v1','executionCodeCommit':source,'exportInputs':load(inputs/'summary.json'),
             'nativeSha256':digest(native),'workerSha256':digest(script),'pythonSha256':digest(python),'pythonExecutable':str(python),'newCompletionCalls':0,
             'modelCorpusSha256':{model:{name:digest(inputs/model/(name+'.jsonl')) for name in ['controls','complete']} for model in ['qwen','llama']}}
    write(out/'execution.json',receipt);results={}
    if controls_from:
        previous=load(controls_from/'execution.json');control_summary=load(controls_from/'summary.json')
        for key in ['nativeSha256','workerSha256','pythonSha256','modelCorpusSha256']:assert previous[key]==receipt[key],key
        assert control_summary['status']=='PASS' and control_summary['controlsOnly']
        results['controlSource']=str(controls_from)
    names=['controls'] if controls_only else (['complete'] if controls_from else ['controls','complete'])
    for name in names:
        for model in ['qwen','llama']:
            folder=out/name/model
            process=bounded([str(python),str(script),'--model-config',str(inputs/model/'model-config.json'),'--corpus',str(inputs/model/(name+'.jsonl')),
                             '--native',str(native),'--out',str(folder/'data')],folder)
            summary_path=folder/'data/summary.json';summary=load(summary_path) if summary_path.exists() else None
            expected=13 if name=='controls' else 2110
            passed=process['exitCode']==0 and process['stop'] is None and summary and summary.get('status')=='PASS' and summary['rows']==expected
            results[name+'/'+model]={'status':'PASS' if passed else 'FAIL','process':process,'summary':summary,'plannedRows':expected}
            write(out/'summary.json',{'schema':'aijade.p2a.token-capacity.stage.v1','executionCodeCommit':source,'controlsOnly':controls_only,'results':results,'newCompletionCalls':0})
            print(name,model,'PASS' if passed else 'FAIL',summary.get('counts') if summary else None,process['stop'],flush=True)
        if name=='controls' and any(results['controls/'+model]['status']!='PASS' for model in ['qwen','llama']):break
    status='PASS' if all(value['status']=='PASS' for value in results.values() if isinstance(value,dict)) else 'FAIL'
    write(out/'summary.json',{'schema':'aijade.p2a.token-capacity.stage.v1','executionCodeCommit':source,'controlsOnly':controls_only,'results':results,'status':status,'newCompletionCalls':0})


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    for name in ['inputs','python','native','out']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--controls-only',action='store_true');p.add_argument('--controls-from',type=Path)
    # Resolving a venv's interpreter symlink selects the base installation and loses its packages.
    a=p.parse_args();run(a.inputs.resolve(),a.python.absolute(),a.native.resolve(),a.out.resolve(),a.controls_only,a.controls_from.resolve() if a.controls_from else None)
