"""Input-only matched exposure for both complete banks, before any constructed model observations."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
PREVIOUS=ROOT/'experiments/p2-a/bounded-input/2026-11-11'
sys.path.insert(0,str(PREVIOUS))
from budget_common import Runtime,load,write,file_sha,sha
from run_preparation import bounded,verify_bank

VERSIONS=['listed-v1','whole-task-v2']
SCENARIO=dict(id='compact8k',contextTokens=8192,generationReplyTokens=4096,verificationReplyTokens=256,maxVisibleCases=3,maxInputTokens=512)

def rows(path):
 with path.open() as f:return [json.loads(line) for line in f]

class Prompts:
 def __init__(self,dotnet,dll,bank):
  self.child=subprocess.Popen([str(dotnet),str(dll),'p2-judgment-server','--bank',str(bank)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr)
  self.cache={}
 def get(self,source,task,indices,version):
  key=(source,task,tuple(indices),version)
  if key not in self.cache:
   self.child.stdin.write(json.dumps(dict(source=source,taskId=task,indices=indices,instructionVersion=version),separators=(',',':')).encode()+b'\n');self.child.stdin.flush()
   line=self.child.stdout.readline(8*1024**2+1);assert line.endswith(b'\n') and len(line)<=8*1024**2
   value=json.loads(line);assert value['expectedOutputNoninterference'] and value['selectedCaseIndices']==indices
   assert value['source']==source and value['taskId']==task and value['instructionVersion']==version
   self.cache[key]=value
  return self.cache[key]
 def close(self):
  self.child.stdin.close()
  try:self.child.wait(timeout=15)
  except subprocess.TimeoutExpired:self.child.kill();self.child.wait()
  assert self.child.returncode==0

def select(bank,configs,dotnet,dll,inputs,out):
 out.mkdir(exist_ok=False,parents=True);runtimes={};server=None;queries={};profiles={};decisions={}
 try:
  for model in ['qwen','llama']:runtimes[model]=Runtime(configs/(model+'-counter.json'))
  server=Prompts(dotnet,dll,bank)
  def query(text):
   identity=sha(text.encode())
   if identity not in queries:
    predicted={};chats={}
    for model,runtime in runtimes.items():
     counts,chat=runtime.predict(text);predicted[model]=counts;chats[model]=sha(chat.encode())
    queries[identity]=dict(id='query:'+identity,taskId='matched-selection-query',promptKind='selectionQuery',rawPrompt=text,rawSha256=identity,predictedCounts=predicted,predictedChatSha256=chats)
   return queries[identity]
  def budget(source,task,indices):
   result={}
   for version in VERSIONS:
    prompts=server.get(source,task,indices,version)['prompts']
    for template,text in prompts.items():
     q=query(text)
     for model in runtimes:
      n=q['predictedCounts'][model]['chatWithSpecial'];total=n+4096+256
      result[version+'/'+template+'/'+model]=dict(queryId=q['id'],inputTokens=n,totalWithAllowance=total,fits=total<=8192)
   return result
  for source,expected_tasks in [('builtin',44),('public',422)]:
   catalog=rows(inputs/(source+'-inputs.jsonl'));assert len(catalog)==len({t['taskId'] for t in catalog})==expected_tasks
   identity=catalog[0]['bankManifestSha256'];selected_tasks=[];records=[]
   for task in catalog:
    assert task['source']==source and task['bankManifestSha256']==identity and len(task['cases'])==task['caseCount']
    assert task['inputSha256']==sha((sha(task['instruction'].encode())+'\n'+'\n'.join(c['rawSha256'] for c in task['cases'])+'\n').encode())
    chosen=[];cases=[];initial=budget(source,task['taskId'],[])
    for index,case in enumerate(task['cases']):
     assert case['index']==index and sha(case['rawArgs'].encode())==case['rawSha256'] and sha(case['promptArgs'].encode())==case['promptSha256']
     if len(chosen)==3:cases.append(dict(index=index,reason='MAX_VISIBLE_REACHED'));continue
     q=query(case['promptArgs']);counts={m:q['predictedCounts'][m]['rawNoSpecial'] for m in runtimes}
     if max(counts.values())>512:cases.append(dict(index=index,reason='INPUT_TOKEN_LIMIT',queryId=q['id'],inputTokens=counts));continue
     trial=budget(source,task['taskId'],chosen+[index]);fits=all(v['fits'] for v in trial.values())
     cases.append(dict(index=index,reason='SELECTED' if fits else 'PROMPT_BUDGET',queryId=q['id'],inputTokens=counts,tentativeBudgets=trial))
     if fits:chosen.append(index)
    final=budget(source,task['taskId'],chosen)
    selected_tasks.append(dict(taskId=task['taskId'],caseCount=task['caseCount'],inputSha256=task['inputSha256'],selectedCaseIndices=chosen))
    records.append(dict(taskId=task['taskId'],initialBudgets=initial,decisions=cases,finalBudgets=final,selectedCaseIndices=chosen))
   profiles[source]={};decisions[source]=records
   for version in VERSIONS:
    profile=dict(schema='aijade.p2a.prompt-exposure.v1' if version=='listed-v1' else 'aijade.p2a.prompt-exposure.v2',bankManifestSha256=identity,scenario=SCENARIO,
     modelManifestSha256ByName={runtime.model['model']:runtime.model['manifestSha256'] for runtime in runtimes.values()},tasks=selected_tasks)
    if version!='listed-v1':profile['verifierInstructionVersion']=version
    path=out/(source+'-'+version+'-exposure.json');write(path,profile);profiles[source][version]=str(path)
   write(out/(source+'-decisions.json'),dict(source=source,tasks=records))
  with (out/'selection-queries.jsonl').open('w') as f:
   for identity in sorted(queries):f.write(json.dumps(queries[identity],ensure_ascii=False,separators=(',',':'))+'\n')
  for model,runtime in runtimes.items():
   folder=out/model;folder.mkdir();write(folder/'model-config.json',runtime.model)
   with (folder/'complete.jsonl').open('w') as f:
    for identity in sorted(queries):
     q=queries[identity];chat=runtime.renderer.render(q['rawPrompt']);record={k:q[k] for k in ['id','taskId','promptKind','rawPrompt','rawSha256']}
     record.update(chatPrompt=chat,chatSha256=sha(chat.encode()),templateSha256=runtime.model['effectiveTemplateSha256'],systemSha256=runtime.model['effectiveSystemSha256'])
     f.write(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
  result=dict(schema='aijade.p2.matched-input-selection.v1',tasks=466,banks={'builtin':44,'public':422},selectionQueries=len(queries),rowsPerModel=len(queries),profiles=profiles,
   profilesSha256={source:{version:file_sha(Path(path)) for version,path in values.items()} for source,values in profiles.items()},
   selectionUsedExpectedOutputsOrReferences=False,newModelCompletionCalls=0)
  write(out/'summary.json',result)
 finally:
  if server is not None:server.close()
  for runtime in runtimes.values():runtime.close()

def main(bank,configs,dotnet,dll,python,native,baseline,out):
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(),'Freeze source before matched preparation'
 out.mkdir(parents=True,exist_ok=False);head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 before=verify_bank(bank);builtin=ROOT/'src/Aijade.Research/SkillBench/bench-data.json';builtin_sha=file_sha(builtin)
 results={};execution=dict(executionCodeCommit=head,planCommit=subprocess.check_output(['git','log','--diff-filter=A','--format=%H','--','experiments/plans/2026-11-11-p2-whole-task-judgment-calibration.md'],cwd=ROOT,text=True).strip(),
  bankBefore=before,builtinSha256=builtin_sha,dllSha256=file_sha(dll),driverSha256=file_sha(__file__),legacyBaselineSha256=file_sha(baseline),newModelCompletionCalls=0)
 write(out/'execution.json',execution)
 def update(status='RUNNING'):write(out/'summary.json',dict(schema='aijade.p2.matched-preparation.v1',status=status,results=results,executionCodeCommit=head,newModelCompletionCalls=0))
 process=bounded([dotnet,dll,'p2-judgment-export','--bank',bank,'--out',out/'inputs'],out/'export-process')
 ok=process['exitCode']==0 and process['stop'] is None
 results['export']=dict(status='PASS' if ok else 'FAIL',process=process);update()
 if not ok:update('FAIL');return 1
 assert file_sha(out/'inputs/legacy-builtin-prompts.jsonl')==file_sha(baseline),'Historical 44-task prompt bytes changed'
 process=bounded([dotnet,dll,'p2-bank-prompts','--bank',bank],out/'public-legacy-export')
 ok=process['exitCode']==0 and process['stop'] is None and process['stdoutSha256']=='77cd671180a6b1a1289e2a97447eb5895109edd175157b041e14bb3730a63125'
 results['publicLegacy']=dict(status='PASS' if ok else 'FAIL',process=process);update()
 if not ok:update('FAIL');return 1
 process=bounded([python,HERE/'prepare_matched.py','select','--bank',bank,'--configs',configs,'--dotnet',dotnet,'--dll',dll,'--inputs',out/'inputs','--out',out/'selection'],out/'selection-process')
 ok=process['exitCode']==0 and process['stop'] is None;results['selection']=dict(status='PASS' if ok else 'FAIL',process=process);update()
 if not ok:update('FAIL');return 1
 selection=load(out/'selection/summary.json');n=selection['rowsPerModel']
 for model in ['qwen','llama']:
  folder=out/'native'/model;process=bounded([python,ROOT/'experiments/p2-a/tokenizer-capacity/2026-11-11/tokenize_worker.py','--model-config',out/'selection'/model/'model-config.json',
   '--corpus',out/'selection'/model/'complete.jsonl','--native',native,'--out',folder/'data'],folder)
  path=folder/'data/summary.json';report=load(path) if path.exists() else {}
  ok=process['exitCode']==0 and process['stop'] is None and report.get('status')=='PASS' and report.get('rows')==n
  results['native/'+model]=dict(status='PASS' if ok else 'FAIL',process=process);update()
 if not all(v['status']=='PASS' for v in results.values()):update('FAIL');return 1
 setup=load(configs/'setup.json');policies=out/'policies';policies.mkdir()
 for source in ['builtin','public']:
  for version in VERSIONS:
   exposure=out/'selection'/(source+'-'+version+'-exposure.json')
   for model in ['qwen','llama']:
    counter=configs/(model+'-counter.json');info=load(counter)['modelConfig']
    policy=dict(schema='aijade.p2a.request-policy.v2',exposureFile=str(exposure),exposureSha256=file_sha(exposure),model=info['model'],modelManifestSha256=info['manifestSha256'],
     templateSha256=info['effectiveTemplateSha256'],systemSha256=info['effectiveSystemSha256'],keepAliveSeconds=0,
     counter=dict(executable=setup['pythonExecutable'],executableSha256=setup['pythonSha256'],script=setup['counterScript'],scriptSha256=setup['counterScriptSha256'],config=str(counter),configSha256=file_sha(counter)))
    write(policies/(source+'-'+version+'-'+model+'.json'),policy)
 process=bounded([dotnet,dll,'p2-judgment-controls','--bank',bank,'--builtin-exposure',out/'selection/builtin-whole-task-v2-exposure.json',
  '--public-exposure',out/'selection/public-whole-task-v2-exposure.json','--out',out/'controls'],out/'control-process')
 ok=process['exitCode']==0 and process['stop'] is None;results['controls']=dict(status='PASS' if ok else 'FAIL',process=process)
 after=verify_bank(bank);assert after==before and file_sha(builtin)==builtin_sha;write(out/'bank-after.json',after)
 update('PASS' if ok else 'FAIL');return 0 if ok else 1

if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__);p.add_argument('command',choices=['prepare','select'])
 for name in ['bank','configs','dotnet','dll','out']:p.add_argument('--'+name,type=Path,required=True)
 for name in ['python','native','baseline','inputs']:p.add_argument('--'+name,type=Path)
 a=p.parse_args()
 if a.command=='select':select(a.bank.resolve(),a.configs.resolve(),a.dotnet.resolve(),a.dll.resolve(),a.inputs.resolve(),a.out.resolve())
 else:sys.exit(main(a.bank.resolve(),a.configs.resolve(),a.dotnet.resolve(),a.dll.resolve(),a.python.absolute(),a.native.resolve(),a.baseline.resolve(),a.out.resolve()))
