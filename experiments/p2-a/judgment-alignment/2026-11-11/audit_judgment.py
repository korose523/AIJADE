"""Model-free reconstruction of both input selections and every constructed observation."""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,hashlib,importlib.util,json,random,re,statistics,sys

HERE=Path(__file__).resolve().parent
ROOT=next((p for p in [HERE,*HERE.parents] if (p/'src/Aijade.Research').is_dir()),None)
if ROOT is None:raise RuntimeError('Run this audit from a complete AIJADE source checkout.')
spec=importlib.util.spec_from_file_location('old_streams',ROOT/'experiments/p2-a/tokenizer-capacity/2026-11-11/audit_streams.py')
streams=importlib.util.module_from_spec(spec);spec.loader.exec_module(streams)
records=streams.records;opened=streams.opened;sha=streams.sha
spec=importlib.util.spec_from_file_location('old_bounded',ROOT/'experiments/p2-a/bounded-input/2026-11-11/audit_bounded.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
VERSIONS=['listed-v1','whole-task-v2']
CRITERION='Judge the complete stated task, including valid inputs not displayed here. PASS means the code satisfies the full specification; FAIL means it does not. Passing only the displayed examples is insufficient.'

def load(p):
 with opened(p,False) as f:return json.load(f)
def logical_sha(p):
 h=hashlib.sha256()
 with opened(p) as stream:
  for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
 return h.hexdigest()
def prompts(task,indices,version,code=''):
 task={**task,'cases':[dict(args=row['promptArgs']) for row in task['cases']]}
 result=old.prompts(task,code,indices)
 if version=='whole-task-v2':
  result['verifierA']=result['verifierA'].replace('For each case, decide whether the code returns the correct result, then give an overall verdict.',CRITERION)
  result['verifierB']=result['verifierB'].replace('Question: does the candidate return the correct output for every one of these inputs?',CRITERION)
 return {'A':result['verifierA'],'B':result['verifierB']}
def audit_preparation(base):
 assert load(base/'summary.json')['status']=='PASS';execution=load(base/'execution.json')
 queries=list(records(base/'selection/selection-queries.jsonl'));assert len({q['id'] for q in queries})==len(queries)
 query_by_sha={q['rawSha256']:q for q in queries};assert len(query_by_sha)==len(queries)
 assert [q['rawSha256'] for q in queries]==sorted(query_by_sha)
 used=set();checks=0;native={};measurements={}
 for model in ['qwen','llama']:
  n=len(queries);native[model]=streams.audit(base/'native'/model/'data',base/'selection'/model/'complete.jsonl',n,model)
  corpus=list(records(base/'selection'/model/'complete.jsonl'));values=list(records(base/'native'/model/'data/measurements.jsonl'))
  cfg=load(base/'selection'/model/'model-config.json');system='You are Qwen, created by Alibaba Cloud. You are a helpful assistant.' if model=='qwen' else ''
  assert sha(system.encode())==cfg['effectiveSystemSha256'];measurements[model]={}
  for q,row,value in zip(queries,corpus,values):
   assert row['id']==value['id']==q['id'] and row['rawPrompt']==q['rawPrompt']
   chat=old.expected_chat(model,system,q['rawPrompt']);assert row['chatPrompt']==chat
   assert sha(q['rawPrompt'].encode())==q['rawSha256'] and row['chatSha256']==q['predictedChatSha256'][model]==sha(chat.encode())
   counts={k:value['measurements'][k]['count'] for k in ['rawNoSpecial','chatWithSpecial']}
   assert counts==q['predictedCounts'][model];measurements[model][q['id']]=counts
 def query(text):
  identity=sha(text.encode());q=query_by_sha[identity];assert q['rawPrompt']==text;used.add(q['id']);return q
 def budgets(task,indices):
  result={}
  for version in VERSIONS:
   for template,text in prompts(task,indices,version).items():
    q=query(text)
    for model in ['qwen','llama']:
     n=measurements[model][q['id']]['chatWithSpecial'];result[version+'/'+template+'/'+model]=dict(queryId=q['id'],inputTokens=n,totalWithAllowance=n+4096+256,fits=n+4096+256<=8192)
  return result
 summary={};catalogs={};statistics_rows={}
 for source,total in [('builtin',44),('public',422)]:
  tasks=list(records(base/'inputs'/(source+'-inputs.jsonl')));assert len(tasks)==len({t['taskId'] for t in tasks})==total;catalogs[source]=tasks
  p1=load(base/'selection'/(source+'-listed-v1-exposure.json'));p2=load(base/'selection'/(source+'-whole-task-v2-exposure.json'))
  assert p1['schema']=='aijade.p2a.prompt-exposure.v1' and 'verifierInstructionVersion' not in p1
  assert p2['schema']=='aijade.p2a.prompt-exposure.v2' and p2['verifierInstructionVersion']=='whole-task-v2'
  assert {k:v for k,v in p2.items() if k not in ['schema','verifierInstructionVersion']}=={k:v for k,v in p1.items() if k!='schema'}
  assert p1['scenario']==old.SCENARIOS['compact8k'] and len(p1['tasks'])==total
  decisions=load(base/'selection'/(source+'-decisions.json'))['tasks'];reasons=Counter();selected=0;duplicates=0;visible_counts=Counter();token_max=0;counter=defaultdict(list)
  for task,profile,record in zip(tasks,p1['tasks'],decisions):
   assert task['source']==source and task['bankManifestSha256']==p1['bankManifestSha256']
   assert len(task['cases'])==task['caseCount'] and [r['index'] for r in task['cases']]==list(range(task['caseCount']))
   for row in task['cases']:
    assert sha(row['rawArgs'].encode())==row['rawSha256'] and sha(row['promptArgs'].encode())==row['promptSha256']
   assert sha((sha(task['instruction'].encode())+'\n'+'\n'.join(row['rawSha256'] for row in task['cases'])+'\n').encode())==task['inputSha256']
   assert record['initialBudgets']==budgets(task,[]);chosen=[];rebuilt=[]
   for index,case in enumerate(task['cases']):
    if len(chosen)==3:decision=dict(index=index,reason='MAX_VISIBLE_REACHED')
    else:
     q=query(case['promptArgs']);counts={model:measurements[model][q['id']]['rawNoSpecial'] for model in ['qwen','llama']};token_max=max(token_max,max(counts.values()))
     if max(counts.values())>512:decision=dict(index=index,reason='INPUT_TOKEN_LIMIT',queryId=q['id'],inputTokens=counts)
     else:
      tentative=budgets(task,chosen+[index]);fits=all(r['fits'] for r in tentative.values())
      decision=dict(index=index,reason='SELECTED' if fits else 'PROMPT_BUDGET',queryId=q['id'],inputTokens=counts,tentativeBudgets=tentative)
      if fits:chosen.append(index)
    rebuilt.append(decision);reasons[decision['reason']]+=1
   assert record['decisions']==rebuilt and record['selectedCaseIndices']==chosen and record['finalBudgets']==budgets(task,chosen)
   assert profile==dict(taskId=task['taskId'],caseCount=task['caseCount'],inputSha256=task['inputSha256'],selectedCaseIndices=chosen)
   selected+=len(chosen);visible_counts[str(len(chosen))]+=1;duplicates+=len(chosen)-len({task['cases'][i]['promptArgs'] for i in chosen})
   for key,value in record['finalBudgets'].items():counter[key].append(value['inputTokens'])
   checks+=1
  summary[source]=dict(tasks=total,fullOracleCases=sum(t['caseCount'] for t in tasks),displayedCases=selected,hiddenCases=sum(t['caseCount'] for t in tasks)-selected,
   visibleCountDistribution=dict(visible_counts),selectedDuplicateDisplayedArgumentRows=duplicates,maximumConsideredRawTokens=token_max,decisionCounts=dict(reasons))
  statistics_rows[source]={k:dict(minimum=min(v),median=statistics.median(v),maximum=max(v)) for k,v in counter.items()}
 assert used=={q['id'] for q in queries}
 # Independently recover the whole historical input formatting from the unchanged export.
 legacy=list(records(base/'inputs/legacy-builtin-prompts.jsonl'));assert len(legacy)==44
 for task,row in zip(catalogs['builtin'],legacy):
  a=row['prompts']['verifierA'];reference=a.split('Candidate code:\n```js\n',1)[1].split('\n```\nYou are given ONLY',1)[0]
  expected=prompts(task,None,'listed-v1',reference);assert row['prompts']['verifierA']==expected['A'] and row['prompts']['verifierB']==expected['B']
 assert logical_sha(base/'inputs/legacy-builtin-prompts.jsonl')=='260bcae3f0539021c6ef4de70fb84e1022ed9b52e32ef09bc492a8c50d909376'
 assert load(base/'public-legacy-export/process.json')['stdoutSha256']=='77cd671180a6b1a1289e2a97447eb5895109edd175157b041e14bb3730a63125'
 assert logical_sha(base/'public-legacy-export/stdout.log')=='77cd671180a6b1a1289e2a97447eb5895109edd175157b041e14bb3730a63125'
 assert load(base/'bank-after.json')==execution['bankBefore']
 controls=load(base/'controls/controls.json')['candidates'];assert len(controls)==4
 for candidate in controls:
  assert logical_sha(base/'controls'/candidate['candidateFile'])==candidate['candidateSha256']
  assert candidate['visible']['ok'] and candidate['visible']['passed']==candidate['visible']['total']==3
  truth=candidate['full'];assert truth['ok']==(candidate['kind']=='positive')
  task=next(t for t in catalogs[candidate['source']] if t['taskId']==candidate['taskId']);assert truth['total']==task['caseCount']
  if candidate['kind']=='limited':assert truth['passed']<truth['total'] and all(r['index'] not in candidate['selectedCaseIndices'] for r in truth['failures'])
 return dict(status='PASS',executionCodeCommit=execution['executionCodeCommit'],selectionQueries=len(queries),selectionQueryViews=len(queries)*8,
  banks=summary,native=native,statistics=statistics_rows,completeTaskDecisions=checks,controls=controls,legacyPromptBytesUnchanged=True,newModelCompletionCalls=0),catalogs

def audit_cli(base):
 summary=load(base/'summary.json');assert summary['status']=='PASS' and len(summary['groups'])==4
 for group in summary['groups']:
  folder=base/(group['source']+'-'+group['instructionVersion']);full=list((folder/'full').iterdir());resumed=list((folder/'resumed').iterdir());assert len(full)==len(resumed)==1
  for name in ['trials.jsonl','candidates.jsonl']:
   a=list(records(full[0]/name));b=list(records(resumed[0]/name));assert len(a)==len(b)==12
   for row in a+b:row.pop('durationMs',None)
   assert a==b
   if name=='trials.jsonl':assert all(row['execOk'] and row['verifierInstructionVersion']==group['instructionVersion'] for row in a)
  assert load(resumed[0]/'summary.json')['resumed']['replayedSteps']==8
  assert load(full[0]/'summary.json')['requestPolicy']['requestsChecked']==0
  assert len(group['negativeChecks'])==5 and all(v['exitCode']==1 and not v['outputCreated'] for v in group['negativeChecks'])
 return dict(status='PASS',steps=48,replayedSteps=32,identityRejections=20,newModelCompletionCalls=0)

def audit_calibration(base,preparation,catalogs):
 attempt=load(base/'attempt.json');execution=load(base/'execution.json');order=load(base/'order.json');assert len(order)==32
 assert logical_sha(base/'order.json')==execution['orderSha256'];assert execution['executionCodeCommit']==attempt['executionCodeCommit']
 keys=[(r['model'],r['candidateId'],r['template'],r['instructionVersion']) for r in order];assert len(set(keys))==32
 assert [r['slot'] for r in order]==list(range(32)) and [r['model'] for r in order]==['qwen']*16+['llama']*16
 for offset in [0,16]:
  assert Counter(order[i]['instructionVersion'] for i in range(offset,offset+16,2))=={'listed-v1':4,'whole-task-v2':4}
  for i in range(offset,offset+16,2):
   assert keys[i][:3]==keys[i+1][:3] and keys[i][-1]!=keys[i+1][-1]
 cells=[];confusion=defaultdict(Counter);by_pair=defaultdict(dict);dispatched=0
 for row in order:
  slot=row['slot'];folder=base/'observations'/f'{slot:02d}';cell={**row,'status':'UNATTEMPTED','pass':None}
  if slot in attempt['completedSlots']:
   observation=load(folder/'observation.json');assert observation['status']=='OBSERVED' and observation['requestsChecked']==1
   ledger=list(records(folder/'requests.jsonl'));assert len([v for v in ledger if v['kind']=='request'])==1
   request=next(v for v in ledger if v['kind']=='request');http=next(v for v in ledger if v['kind']=='http-request');response=next(v for v in ledger if v['kind']=='response')
   assert request['status']=='READY_TO_SEND' and request['inputTokens']+256<=8192
   assert sha(http['rawBody'].encode())==http['sha256'] and sha(response['rawResponse'].encode())==response['sha256']
   body=json.loads(http['rawBody']);raw=json.loads(response['rawResponse']);assert body['keep_alive']==0 and body['options']==dict(temperature=0,seed=3759066737,num_predict=256,num_ctx=8192)
   code_path=preparation/'controls'/(row['candidateId']+'.js')
   with opened(code_path,False) as f:code=f.read()
   assert sha(code.encode())==row['candidateSha256'];task=next(t for t in catalogs[row['source']] if t['taskId']==row['taskId'])
   profile=load(preparation/'selection'/(row['source']+'-'+row['instructionVersion']+'-exposure.json'))
   indices=next(v['selectedCaseIndices'] for v in profile['tasks'] if v['taskId']==row['taskId'])
   text=prompts(task,indices,row['instructionVersion'],code)[row['template']]
   assert body['messages']==[dict(role='user',content=text)] and request['rawPrompt']==text and request['rawSha256']==sha(text.encode())
   assert raw.get('done_reason')!='length' and raw.get('eval_count',0)<=256
   answer=raw['message']['content'].strip();verdict=re.match(r'^(PASS|FAIL)(?=$|[\s:.,;!\-])',answer,re.I);assert verdict
   passed=verdict[1].upper()=='PASS';assert observation['pass']==passed
   cell.update(status='OBSERVED',passVerdict=passed,**{'pass':passed},elapsedSeconds=observation['elapsedSeconds'],offlineInputTokens=request['inputTokens'],
    serverPromptEvalCount=raw.get('prompt_eval_count'),serverEvalCount=raw.get('eval_count'),doneReason=raw.get('done_reason'),rawReply=answer,
    promptCountDelta=None if raw.get('prompt_eval_count') is None else raw['prompt_eval_count']-request['inputTokens'])
   confusion[(row['model'],row['template'],row['instructionVersion'])][('TP' if passed else 'FN') if row['fullOracleTruth'] else ('FP' if passed else 'TN')]+=1
   by_pair[(row['model'],row['candidateId'],row['template'])][row['instructionVersion']]=passed;dispatched+=1
  elif slot==attempt['inFlightSlot']:
   cell['status']='FAILED_IN_FLIGHT';assert not (folder/'observation.json').exists()
   ledger=list(records(folder/'requests.jsonl'));ready=[r for r in ledger if r['kind']=='request']
   bodies=[r for r in ledger if r['kind']=='http-request'];assert len(ready)==len(bodies)==1
   request=ready[0];http=bodies[0];assert request['status']=='READY_TO_SEND' and request['inputTokens']+256<=8192
   assert sha(http['rawBody'].encode())==http['sha256'];body=json.loads(http['rawBody'])
   assert body['keep_alive']==0 and body['options']==dict(temperature=0,seed=3759066737,num_predict=256,num_ctx=8192)
   with opened(preparation/'controls'/(row['candidateId']+'.js'),False) as f:code=f.read()
   assert sha(code.encode())==row['candidateSha256'];task=next(t for t in catalogs[row['source']] if t['taskId']==row['taskId'])
   profile=load(preparation/'selection'/(row['source']+'-'+row['instructionVersion']+'-exposure.json'))
   indices=next(v['selectedCaseIndices'] for v in profile['tasks'] if v['taskId']==row['taskId'])
   expected=prompts(task,indices,row['instructionVersion'],code)[row['template']]
   assert body['messages']==[dict(role='user',content=expected)] and request['rawPrompt']==expected
   assert request['rawSha256']==sha(expected.encode()) and request['verdict'] is None
   cell['offlineInputTokens']=request['inputTokens'];cell['httpBodyRecorded']=True
  cells.append(cell)
 assert len([r for r in cells if r['status']=='OBSERVED'])==attempt['completedObservations']
 assert sum(r['status']!='OBSERVED' for r in cells)==attempt['notCompletedObservations']
 assert attempt['acceptedCompleteCalibration']==(attempt['status']=='COMPLETE' and dispatched==32)
 if attempt['status']=='STOPPED':assert attempt['reason'] and not attempt['acceptedCompleteCalibration']
 telemetry=list(records(base/'resources.jsonl'))
 assert min(r['availableBytes'] for r in telemetry)==attempt['minAvailableBytes'] and max(r['swapUsedBytes'] for r in telemetry)==attempt['maxSwapUsedBytes']
 for admission in attempt['admissions']:
  subset=[r for r in telemetry if r['phase']=='admission/'+admission['model']]
  assert admission['seconds']>=60 and min(r['availableBytes'] for r in subset)==admission['minAvailableBytes']
  assert max(r['swapUsedBytes'] for r in subset)==admission['maxSwapUsedBytes']
  expected=admission['minAvailableBytes']>=7*1024**3 and admission['swapIncrementBytes']<=256*1024**2 and admission['ownedServiceEmptyThroughout']
  assert (admission['status']=='PASS')==expected
 return dict(status='PASS',attempt=attempt,observations=cells,newVerifierCompletions=dispatched,
  finiteConfusionCounts=[dict(model=k[0],template=k[1],instructionVersion=k[2],counts=dict(v)) for k,v in sorted(confusion.items())],
  pairedVerdicts=[dict(model=k[0],candidateId=k[1],template=k[2],verdicts=v,changed=len(v)==2 and len(set(v.values()))>1) for k,v in sorted(by_pair.items())],
  scope='Constructed development controls. No population rate, confidence interval, winner or primary-study acceptance.')

def main(a):
 preparation,catalogs=audit_preparation(a.preparation);cli=audit_cli(a.cli_controls)
 calibration=audit_calibration(a.calibration,a.preparation,catalogs) if a.calibration else None
 result=dict(schema='aijade.p2.whole-task-audit.v1',status='PASS',preparation=preparation,cli=cli,calibration=calibration,
  negativeTokenControls=streams.negative_checks(),primaryExperiment=False)
 a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(status='PASS',queries=preparation['selectionQueries'],banks=preparation['banks'],cli=cli,
  calibration=None if calibration is None else dict(status=calibration['attempt']['status'],completed=calibration['newVerifierCompletions'])),indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__)
 for name in ['preparation','cli-controls','out']:p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--calibration',type=Path);main(p.parse_args())
