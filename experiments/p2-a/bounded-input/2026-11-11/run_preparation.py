"""Bounded complete preparation, native checks and real-guard/synthetic-HTTP controls."""
import argparse,datetime,hashlib,json,os,resource,signal,subprocess,sys,time
from pathlib import Path
from budget_common import HERE,ROOT,TOKENIZER,Renderer,file_sha,load,write,sha

def cpu_seconds(value):
    day,clock=(value.split('-',1) if '-' in value else ('0',value));parts=clock.split(':')
    return int(day)*86400+sum(float(v)*60**i for i,v in enumerate(reversed(parts)))
def limits():
    resource.setrlimit(resource.RLIMIT_CPU,(1200,1200));resource.setrlimit(resource.RLIMIT_FSIZE,(512*1024**2,512*1024**2));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
def family(pgid):
    text=subprocess.check_output(['/bin/ps','-A','-o','pid=,pgid=,rss=,time='],text=True);result=[]
    for line in text.splitlines():
        fields=line.split()
        if len(fields)==4 and int(fields[1])==pgid:result.append((int(fields[0]),int(fields[2])*1024,cpu_seconds(fields[3])))
    return result
def bounded(command,folder):
    folder.mkdir(parents=True,exist_ok=False);started=time.monotonic();peak=0;cpu={};stop=None;samples=0
    env={'PATH':'/usr/bin:/bin:/usr/local/bin','LC_ALL':'C','TZ':'UTC','TOKENIZERS_PARALLELISM':'false'}
    with (folder/'stdout.log').open('wb') as out,(folder/'stderr.log').open('wb') as err:
        child=subprocess.Popen([str(value) for value in command],cwd=ROOT,env=env,stdout=out,stderr=err,start_new_session=True,preexec_fn=limits)
        while child.poll() is None:
            current=family(child.pid);peak=max(peak,sum(row[1] for row in current));samples+=1
            for pid,_,seconds in current:cpu[pid]=max(cpu.get(pid,0),seconds)
            if peak>2*1024**3:stop='FAMILY_RSS_LIMIT'
            if sum(cpu.values())>1200:stop='FAMILY_CPU_LIMIT'
            if time.monotonic()-started>1800:stop='WALL_LIMIT'
            if stop:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                break
            time.sleep(.1)
        code=child.wait()
    remaining=family(child.pid)
    if remaining:
        # A terminated parent does not count as a completed process family.
        stop=stop or 'DESCENDANTS_REMAINED'
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    result={'pid':child.pid,'exitCode':code,'stop':stop,'wallSeconds':time.monotonic()-started,'sampledFamilyPeakRssBytes':peak,
            'sampledFamilyCpuSeconds':sum(cpu.values()),'samples':samples,'remainingAfterParent':remaining,
            'stdoutSha256':file_sha(folder/'stdout.log'),'stderrSha256':file_sha(folder/'stderr.log'),'environment':env,
            'limits':{'cpuSeconds':1200,'wallSeconds':1800,'sampledFamilyRssBytes':2*1024**3,'physicalFileBytes':512*1024**2}}
    write(folder/'process.json',result);return result

def verify_bank(bank):
    data=load(bank);folder=bank.parent;files={data['runtime']['file']:data['runtime']['sha256']}
    for row in data['tasks']:files[row['taskFile']]=row['taskSha256'];files[row['referenceFile']]=row['referenceSha256']
    for name,expected in files.items():assert file_sha(folder/name)==expected,('changed bank file',name)
    return {'manifestSha256':file_sha(bank),'files':files}

def make_policies(selection,configs,out):
    out.mkdir(exist_ok=False);setup=load(configs/'setup.json')
    for scenario in ['compact4k','compact8k']:
        profile=selection/scenario/'exposure.json'
        for model in ['qwen','llama']:
            runtime=configs/(model+'-counter.json');info=load(runtime)['modelConfig']
            data={'schema':'aijade.p2a.request-policy.v1','exposureFile':str(profile),'exposureSha256':file_sha(profile),
                  'model':info['model'],'modelManifestSha256':info['manifestSha256'],'templateSha256':info['effectiveTemplateSha256'],'systemSha256':info['effectiveSystemSha256'],
                  'counter':{'executable':setup['pythonExecutable'],'executableSha256':setup['pythonSha256'],'script':setup['counterScript'],
                             'scriptSha256':setup['counterScriptSha256'],'config':str(runtime),'configSha256':file_sha(runtime)}}
            write(out/(scenario+'-'+model+'.json'),data)

def prepare_controls(configs,out):
    out.mkdir(exist_ok=False);fixtures=load(TOKENIZER/'controls.json');assert len(fixtures)==15
    for model in ['qwen','llama']:
        cfg=load(configs/(model+'-counter.json'));info=cfg['modelConfig'];folder=out/model;folder.mkdir()
        write(folder/'model-config.json',info)
        renderer=Renderer(cfg['renderer']['path'],cfg['template']['path'],cfg['system']['path'],model)
        try:
            with (folder/'controls.jsonl').open('w') as dst:
                for fixture in fixtures:
                    raw=fixture['text'];chat=renderer.render(raw)
                    value={'id':'control:'+fixture['id'],'taskId':fixture['id'],'promptKind':'control','rawPrompt':raw,'rawSha256':sha(raw.encode()),
                           'chatPrompt':chat,'chatSha256':sha(chat.encode()),'templateSha256':info['effectiveTemplateSha256'],'systemSha256':info['effectiveSystemSha256']}
                    dst.write(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n')
        finally:renderer.close()

def main(bank,configs,dotnet,dll,rqc_dll,python,native,out):
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(),'Freeze source before complete preparation'
    out.mkdir(parents=True,exist_ok=False);head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    before=verify_bank(bank);assert before['manifestSha256']=='5592614a78d6e9ca0ecd19ab3684cbd455880aba7a0ecafe4689a73a19dab2bf'
    execution={'schema':'aijade.p2a.bounded-input.execution.v1','executionCodeCommit':head,'startedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'planCommit':subprocess.check_output(['git','log','--diff-filter=A','--format=%H','--','experiments/plans/2026-11-11-p2-a-bounded-input-exposure.md'],cwd=ROOT,text=True).strip(),
               'amendmentCommit':subprocess.check_output(['git','log','--diff-filter=A','--format=%H','--','experiments/plans/2026-11-11-p2-a-request-guard-receipts.md'],cwd=ROOT,text=True).strip(),
               'memoryLifecycleAmendmentCommit':subprocess.check_output(['git','log','--diff-filter=A','--format=%H','--','experiments/plans/2026-11-11-p2-a-probe-memory-lifecycle.md'],cwd=ROOT,text=True).strip(),
               'bankBefore':before,'dllSha256':file_sha(dll),'rqcDllSha256':file_sha(rqc_dll),'nativeSha256':file_sha(native),'pythonExecutable':str(python),'pythonSha256':file_sha(python),
               'driverSha256':file_sha(__file__),'selectionCodeSha256':file_sha(HERE/'select_exposure.py'),
               'oldWorkerSha256':file_sha(TOKENIZER/'tokenize_worker.py'),'newModelCompletionCalls':0}
    write(out/'execution.json',execution);results={}
    def update(status='RUNNING'):
        write(out/'summary.json',{'schema':'aijade.p2a.bounded-input.stage.v1','executionCodeCommit':head,'status':status,'results':results,'newModelCompletionCalls':0})
    def worker(name,model,inputs,rows):
        folder=out/name/model
        process=bounded([python,TOKENIZER/'tokenize_worker.py','--model-config',inputs/model/'model-config.json','--corpus',inputs/model/('controls.jsonl' if name=='controls' else 'complete.jsonl'),
                         '--native',native,'--out',folder/'data'],folder)
        p=folder/'data/summary.json';data=load(p) if p.exists() else None
        passed=process['exitCode']==0 and process['stop'] is None and data and data.get('status')=='PASS' and data['rows']==rows
        results[name+'/'+model]={'status':'PASS' if passed else 'FAIL','plannedRows':rows,'process':process,'summary':data};update()
        print(name,model,'PASS' if passed else 'FAIL',data.get('counts') if data else None,flush=True)
        return passed
    legacy=bounded([dotnet,dll,'p2-bank-prompts','--bank',bank],out/'legacy-export')
    legacy_matches=legacy['exitCode']==0 and legacy['stop'] is None and legacy['stdoutSha256']=='77cd671180a6b1a1289e2a97447eb5895109edd175157b041e14bb3730a63125'
    results['legacy-export']={'status':'PASS' if legacy_matches else 'FAIL','process':legacy};update()
    if not legacy_matches:update('FAIL');return 1
    prepare_controls(configs,out/'control-inputs')
    controls=[worker('controls',model,out/'control-inputs',15) for model in ['qwen','llama']]
    if not all(controls):update('FAIL');return 1
    process=bounded([python,HERE/'select_exposure.py','--bank',bank,'--configs',configs,'--dotnet',dotnet,'--dll',dll,'--out',out/'selection'],out/'selection-process')
    passed=process['exitCode']==0 and process['stop'] is None and (out/'selection/summary.json').exists()
    results['selection']={'status':'PASS' if passed else 'FAIL','process':process};update()
    if not passed:update('FAIL');return 1
    n=load(out/'selection/summary.json')['completeRowsPerModel']
    complete=[worker('complete',model,out/'selection',n) for model in ['qwen','llama']]
    if not all(complete):update('FAIL');return 1
    make_policies(out/'selection',configs,out/'policies')
    for scenario in ['compact4k','compact8k']:
        for model in ['qwen','llama']:
            folder=out/'policy-probes'/(scenario+'-'+model)
            process=bounded([dotnet,dll,'p2-budget-check','--bank',bank,'--policy',out/'policies'/(scenario+'-'+model+'.json'),'--out',folder/'data'],folder)
            path=folder/'data/summary.json';report=load(path) if path.exists() else None
            passed=process['exitCode']==0 and process['stop'] is None and report and report['status']=='PASS'
            results['policy-probe/'+scenario+'/'+model]={'status':'PASS' if passed else 'FAIL','process':process};update()
            print('policy-probe',scenario,model,'PASS' if passed else 'FAIL',flush=True)
        folder=out/'mock-controls'/scenario
        other='compact8k' if scenario=='compact4k' else 'compact4k'
        process=bounded([python,HERE/'run_mock_control.py','--dotnet',dotnet,'--dll',rqc_dll,'--bank',bank,
                         '--policy',out/'policies'/(scenario+'-qwen.json'),'--other-policy',out/'policies'/(other+'-qwen.json'),'--out',folder/'data'],folder)
        path=folder/'data/summary.json';report=load(path) if path.exists() else None
        passed=process['exitCode']==0 and process['stop'] is None and report and report['status']=='PASS'
        results['mock/'+scenario]={'status':'PASS' if passed else 'FAIL','process':process};update()
        print('mock',scenario,'PASS' if passed else 'FAIL',flush=True)
    after=verify_bank(bank);assert after==before;write(out/'bank-after.json',after)
    passed=all(value['status']=='PASS' for value in results.values());update('PASS' if passed else 'FAIL')
    return 0 if passed else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    for name in ['bank','configs','dotnet','dll','rqc-dll','python','native','out']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();sys.exit(main(a.bank.resolve(),a.configs.resolve(),a.dotnet.resolve(),a.dll.resolve(),a.rqc_dll.resolve(),a.python.absolute(),a.native.resolve(),a.out.resolve()))
