"""One bounded, cold-request constructed calibration on an owned Ollama listener.

The complete order is written before service startup. A stopped attempt never has a
complete accepted summary; no skip, retry or relaxation is implemented.
"""
import argparse,datetime,hashlib,json,os,platform,random,socket,subprocess,sys,time,urllib.request
from pathlib import Path
import psutil

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3];GIB=1024**3
sys.path.insert(0,str(ROOT/'experiments/p2-a/bounded-input/2026-11-11'))
from budget_common import load,write,file_sha

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def api(base,path,timeout=2):
 with urllib.request.urlopen(base+path,timeout=timeout) as response:return json.load(response)
def processes(roots):
 found={}
 for root in roots:
  if root is None:continue
  try:values=[psutil.Process(root.pid),*psutil.Process(root.pid).children(recursive=True)]
  except psutil.Error:continue
  for value in values:
   try:found[value.pid]=dict(pid=value.pid,name=value.name(),rssBytes=value.memory_info().rss)
   except psutil.Error:pass
 return list(found.values())
def main(a):
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(),'Freeze source before calibration'
 assert load(a.preparation/'summary.json')['status']=='PASS'
 assert load(a.cli_controls/'summary.json')['status']=='PASS'
 a.out.mkdir(parents=True,exist_ok=False);head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 controls=load(a.preparation/'controls/controls.json')['candidates'];assert len(controls)==4
 rng=random.Random(20261111);order=[]
 for model in ['qwen','llama']:
  pairs=[(candidate,template) for candidate in controls for template in ['A','B']];rng.shuffle(pairs)
  first=['listed-v1']*4+['whole-task-v2']*4;rng.shuffle(first)
  for (candidate,template),version in zip(pairs,first):
   for scope in [version,'whole-task-v2' if version=='listed-v1' else 'listed-v1']:
    policy=a.preparation/'policies'/(candidate['source']+'-'+scope+'-'+model+'.json')
    candidate_path=a.preparation/'controls'/candidate['candidateFile']
    assert file_sha(candidate_path)==candidate['candidateSha256']
    order.append(dict(slot=len(order),model=model,source=candidate['source'],taskId=candidate['taskId'],candidateId=candidate['id'],
     candidateFile=str(candidate_path),candidateSha256=candidate['candidateSha256'],kind=candidate['kind'],template=template,
     instructionVersion=scope,policyFile=str(policy),policySha256=file_sha(policy),fullOracleTruth=candidate['full']['ok'],displayedCaseTruth=candidate['visible']['ok']))
 assert len(order)==32;write(a.out/'order.json',order)
 execution=dict(schema='aijade.p2.constructed-calibration-execution.v1',executionCodeCommit=head,startedAt=now(),
  planCommit='d51af6a3550d2f07dd07c8bc9ce8fe0658b9a74e',driverSha256=file_sha(__file__),orderSha256=file_sha(a.out/'order.json'),
  dotnetDllSha256=file_sha(a.dll),ollamaSha256=file_sha(a.ollama),psutilVersion=psutil.__version__,pythonVersion=sys.version,
  preparationExecutionSha256=file_sha(a.preparation/'execution.json'),cliControlsSummarySha256=file_sha(a.cli_controls/'summary.json'),
  architecture=platform.machine(),totalMemoryBytes=psutil.virtual_memory().total,
  limits=dict(admissionSeconds=60,admissionAvailableBytes=7*GIB,admissionSwapIncrementBytes=256*1024**2,
   requestSeconds=180,calibrationSeconds=3600,ownedRssBytes=9*GIB,ownedRssDuration=10,lowAvailableBytes=GIB,
   lowAvailableDuration=30,swapIncrementBytes=2*GIB,swapIncrementDuration=30,unloadSeconds=30),
  resourceSemantics='System available RAM/used swap snapshots; family RSS includes shared mappings and the owned server, request client and their children. Pre-existing swap is not attributed to this work.',primaryExperiment=False)
 write(a.out/'execution.json',execution)
 base='http://127.0.0.1:'+str(a.port);server=None;client=None;completed=[];inflight=None;reason=None;baseline=None;telemetry=[];admissions=[];start=time.monotonic();above={}
 log=(a.out/'resources.jsonl').open('w');serverlog=(a.out/'ollama.log').open('wb')
 def sample(phase):
  nonlocal baseline
  values=processes([server,client]);row=dict(at=now(),elapsedSeconds=time.monotonic()-start,phase=phase,slot=inflight,
   availableBytes=psutil.virtual_memory().available,swapUsedBytes=psutil.swap_memory().used,
   ownedFamilyRssBytes=sum(v['rssBytes'] for v in values),processes=values)
  if baseline is None:baseline=row
  log.write(json.dumps(row,separators=(',',':'))+'\n');log.flush();telemetry.append(row)
  conditions={'OWNED_RSS_LIMIT':(row['ownedFamilyRssBytes']>9*GIB,10),'LOW_AVAILABLE_LIMIT':(row['availableBytes']<GIB,30),
   'SWAP_INCREMENT_LIMIT':(row['swapUsedBytes']-baseline['swapUsedBytes']>2*GIB,30)}
  for label,(condition,seconds) in conditions.items():
   if condition:
    above.setdefault(label,time.monotonic())
    if time.monotonic()-above[label]>=seconds:raise RuntimeError(label)
   else:above.pop(label,None)
  if time.monotonic()-start>3600:raise RuntimeError('CALIBRATION_WALL_LIMIT')
  return row
 def no_loaded_models():return api(base,'/api/ps')['models']==[]
 def terminate_owned(root):
  if root is None:return
  try:children=psutil.Process(root.pid).children(recursive=True)
  except psutil.Error:children=[]
  for value in children:
   try:value.terminate()
   except psutil.Error:pass
  if root.poll() is None:root.terminate()
  _,alive=psutil.wait_procs(children,timeout=5)
  for value in alive:
   try:value.kill()
   except psutil.Error:pass
  try:root.wait(timeout=5)
  except subprocess.TimeoutExpired:root.kill();root.wait(timeout=5)
 try:
  with socket.socket() as test:test.bind(('127.0.0.1',a.port))
  env=os.environ.copy();env.update(OLLAMA_HOST='127.0.0.1:'+str(a.port),OLLAMA_MODELS=str(a.models),OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_NUM_PARALLEL='1',OLLAMA_NO_CLOUD='1')
  server=subprocess.Popen([str(a.ollama),'serve'],cwd=a.out,env=env,stdout=serverlog,stderr=subprocess.STDOUT,start_new_session=True)
  service_start=time.monotonic()
  while True:
   if server.poll() is not None:raise RuntimeError('OWNED_SERVICE_EXIT')
   try:identity=api(base,'/api/version');break
   except Exception:
    if time.monotonic()-service_start>30:raise RuntimeError('OWNED_SERVICE_START_TIMEOUT')
    time.sleep(.5)
  write(a.out/'service-identity.json',dict(pid=server.pid,baseUrl=base,version=identity,tags=api(base,'/api/tags'),modelsPath=str(a.models)))
  for model in ['qwen','llama']:
   admission_start=time.monotonic();first_sample=sample('admission/'+model);minimum=first_sample['availableBytes'];maximum=first_sample['swapUsedBytes'];empty=True
   while time.monotonic()-admission_start<60:
    row=sample('admission/'+model);minimum=min(minimum,row['availableBytes']);maximum=max(maximum,row['swapUsedBytes']);empty=empty and no_loaded_models();time.sleep(1)
   passed=minimum>=7*GIB and maximum-first_sample['swapUsedBytes']<=256*1024**2 and empty
   admission=dict(model=model,seconds=time.monotonic()-admission_start,minAvailableBytes=minimum,baselineSwapUsedBytes=first_sample['swapUsedBytes'],
    maxSwapUsedBytes=maximum,swapIncrementBytes=maximum-first_sample['swapUsedBytes'],ownedServiceEmptyThroughout=empty,status='PASS' if passed else 'FAIL')
   admissions.append(admission);write(a.out/'admissions.json',admissions)
   if not passed:raise RuntimeError('UNLOADED_ADMISSION_FAILED/'+model)
   for slot in [v for v in order if v['model']==model]:
    inflight=slot['slot'];target=a.out/'observations'/f'{inflight:02d}';target.parent.mkdir(exist_ok=True)
    assert file_sha(slot['candidateFile'])==slot['candidateSha256'] and file_sha(slot['policyFile'])==slot['policySha256']
    command=[str(a.dotnet),str(a.dll),'p2-judgment-call','--bank',str(a.bank),'--source',slot['source'],'--task-id',slot['taskId'],
     '--candidate',slot['candidateFile'],'--candidate-sha256',slot['candidateSha256'],'--policy',slot['policyFile'],'--template',slot['template'],
     '--base',base,'--out',str(target),'--completed',str(len(completed))]
    with (target.parent/(f'{inflight:02d}.stdout.log')).open('wb') as stdout,(target.parent/(f'{inflight:02d}.stderr.log')).open('wb') as stderr:
     request_start=time.monotonic();client=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
     while client.poll() is None:
      sample('request/'+model)
      if time.monotonic()-request_start>180:raise RuntimeError('REQUEST_WALL_TIMEOUT')
      if server.poll() is not None:raise RuntimeError('OWNED_SERVICE_EXIT')
      time.sleep(.5)
     if client.returncode!=0:raise RuntimeError('REQUEST_FAILED/'+str(inflight)+'/'+str(client.returncode))
    observation=load(target/'observation.json');assert observation['status']=='OBSERVED' and observation['requestsChecked']==1
    completed.append(inflight);inflight=None;client=None;unload_start=time.monotonic()
    while not no_loaded_models():
     sample('unload/'+model)
     if time.monotonic()-unload_start>30:raise RuntimeError('OWNED_MODEL_UNLOAD_TIMEOUT')
     time.sleep(.5)
 except Exception as error:reason=type(error).__name__+': '+str(error)
 finally:
  terminate_owned(client);terminate_owned(server);log.close();serverlog.close()
  status='COMPLETE' if reason is None and len(completed)==32 else 'STOPPED'
  report=dict(schema='aijade.p2.constructed-calibration-attempt.v1',status=status,reason=reason,executionCodeCommit=head,
   completedSlots=completed,inFlightSlot=inflight,unattemptedSlots=[v['slot'] for v in order if v['slot'] not in completed and v['slot']!=inflight],
   plannedObservations=32,completedObservations=len(completed),inFlightObservations=int(inflight is not None),
   notCompletedObservations=32-len(completed),admissions=admissions,wallSeconds=time.monotonic()-start,endedAt=now(),
   initialUnloadedBaseline=baseline,minAvailableBytes=min((v['availableBytes'] for v in telemetry),default=None),
   maxSwapUsedBytes=max((v['swapUsedBytes'] for v in telemetry),default=None),
   maxOwnedFamilyRssBytes=max((v['ownedFamilyRssBytes'] for v in telemetry),default=None),
   acceptedCompleteCalibration=status=='COMPLETE',newGenerationCalls=0,primaryExperiment=False)
  write(a.out/'attempt.json',report);print(json.dumps(report,indent=2),flush=True)
 return 0 if report['status']=='COMPLETE' else 1

if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__)
 for key in ['preparation','cli-controls','dotnet','dll','bank','models','ollama','out']:p.add_argument('--'+key,type=Path,required=True)
 p.add_argument('--port',type=int,default=11511);a=p.parse_args();sys.exit(main(a))
