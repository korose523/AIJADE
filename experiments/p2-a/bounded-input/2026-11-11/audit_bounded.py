"""Model-free audit of the complete exposure population and native token streams."""
from pathlib import Path
from collections import Counter
import argparse,copy,hashlib,importlib.util,json,statistics,sys

HERE=Path(__file__).resolve().parent
ROOT=next((p for p in [HERE,*HERE.parents] if (p/'src/Aijade.Research').is_dir()),None)
if ROOT is None: raise RuntimeError('Run this audit from a complete AIJADE source checkout.')
OLD=ROOT/'experiments/p2-a/tokenizer-capacity/2026-11-11'
spec=importlib.util.spec_from_file_location('token_stream_audit',OLD/'audit_streams.py')
streams=importlib.util.module_from_spec(spec);spec.loader.exec_module(streams)
records=streams.records;opened=streams.opened;sha=streams.sha
SCENARIOS={
 'compact4k':dict(id='compact4k',contextTokens=4096,generationReplyTokens=2048,verificationReplyTokens=256,maxVisibleCases=3,maxInputTokens=512),
 'compact8k':dict(id='compact8k',contextTokens=8192,generationReplyTokens=4096,verificationReplyTokens=256,maxVisibleCases=3,maxInputTokens=512)}
KINDS=['generation','verifierA','verifierB','verifierAWithStub','verifierBWithStub']
STUB='function solve() {}'
BANK='5592614a78d6e9ca0ecd19ab3684cbd455880aba7a0ecafe4689a73a19dab2bf'

def load(p):
 with opened(p,False) as f:return json.load(f)
def file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024**2),b''):h.update(block)
 return h.hexdigest()
def logical_sha(p):
 h=hashlib.sha256()
 with opened(p) as f:
  for block in iter(lambda:f.read(1024**2),b''):h.update(block)
 return h.hexdigest()
def indexed(p):
 result={}
 for row in records(p):
  assert row['id'] not in result,'duplicate row'
  result[row['id']]=row
 return result

def expected_chat(model,system,prompt):
 if model=='qwen':return (f'<|im_start|>system\n{system}<|im_end|>\n' if system else '')+f'<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n'
 assert model=='llama' and not system
 return f'<|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n'

def prompts(task,code,indices):
 instruction=task['instruction'];cases=task['cases'];n=task['caseCount']
 gen='\n'.join(['You are an expert JavaScript programmer.','Implement the following function. Task: '+instruction,
  'Respond with ONLY a single fenced JavaScript code block (```js ... ```)','that defines the top-level callable `solve`.',
  'Do not include any explanation outside the code block.'])
 notice=[] if indices is None else [
  f'Only {len(indices)} of {n} oracle inputs are displayed. The complete oracle is withheld. Judge the full specification, not only these examples.' if indices else
  f'No test inputs are displayed (0 of {n}). The complete oracle is withheld. Judge the full specification from the code.']
 visible=range(n) if indices is None else indices
 a='\n'.join(['You are verifying a JavaScript solution against a task.','Task: '+instruction,'Candidate code:','```js',code,'```']+notice+[
  'You are given ONLY the inputs of the test cases, never the expected outputs:',
  '\n'.join(f"  case {i}: args = {cases[i]['args']} (expected WITHHELD)" for i in visible),
  'For each case, decide whether the code returns the correct result, then give an overall verdict.',
  'Respond with a single line: either "PASS" or "FAIL", followed by a short reason.'])
 b='\n'.join(['Task: '+instruction,'A candidate solution:','```js',code,'```']+notice+[
  'Test inputs (the expected outputs are not shown):',
  '\n'.join(f"  {i+1}. {cases[i]['args']}" for i in visible),
  'Question: does the candidate return the correct output for every one of these inputs?',
  'Answer on one line that starts with PASS (it does) or FAIL (it does not), then give a brief justification.'])
 return dict(generation=gen,verifierA=a,verifierB=b)

def validate_inputs(rows):
 assert len(rows)==len({r['task']['taskId'] for r in rows})==422
 assert sum(r['task']['caseCount'] for r in rows)==115185
 for row in rows:
  assert set(row)=={'manifestSha256','task'} and row['manifestSha256']==BANK
  t=row['task'];assert set(t)=={'taskId','instruction','caseCount','inputSha256','cases'}
  assert len(t['cases'])==t['caseCount']
  assert [c['index'] for c in t['cases']]==list(range(t['caseCount']))
  assert all(set(c)=={'index','args','sha256'} and sha(c['args'].encode())==c['sha256'] for c in t['cases'])
  assert sha((sha(t['instruction'].encode())+'\n'+'\n'.join(c['sha256'] for c in t['cases'])+'\n').encode())==t['inputSha256']

def validate_profile(profile,tasks,key):
 assert profile['schema']=='aijade.p2a.prompt-exposure.v1' and profile['bankManifestSha256']==BANK
 assert profile['scenario']==SCENARIOS[key]
 assert len(profile['tasks'])==422
 for expected,row in zip(tasks,profile['tasks']):
  assert set(row)=={'taskId','caseCount','inputSha256','selectedCaseIndices'}
  assert all(row[k]==expected[k] for k in ['taskId','caseCount','inputSha256'])
  indices=row['selectedCaseIndices'];assert len(indices)<=3 and indices==sorted(set(indices))
  assert all(type(i) is int and 0<=i<row['caseCount'] for i in indices),'invalid visible index'

def validate_query(query,counts):
 identity=sha(query['rawPrompt'].encode());assert query['id']=='query:'+identity and query['rawSha256']==identity
 for model in ['qwen','llama']:
  actual=counts[model][query['id']]
  predicted=query['predictedCounts'][model]
  assert set(predicted)=={'rawNoSpecial','chatWithSpecial'}
  assert all(n==actual['counts'][v] for v,n in predicted.items()),'selection used inaccurate token prediction'
  assert query['predictedChatSha256'][model]==actual['chatSha256']

def verify_process(p):
 assert p['exitCode']==0 and p['stop'] is None and not p['remainingAfterParent']
 assert p['limits']==dict(cpuSeconds=1200,wallSeconds=1800,sampledFamilyRssBytes=2147483648,physicalFileBytes=536870912)
 assert p['wallSeconds']<1800 and p['sampledFamilyCpuSeconds']<=1200 and p['sampledFamilyPeakRssBytes']<=2147483648
 assert 'DOTNET_GCHeapHardLimit' not in p['environment']

def audit(attempt):
 stage=load(attempt/'summary.json');assert stage['status']=='PASS' and stage['newModelCompletionCalls']==0
 execution=load(attempt/'execution.json');assert execution['executionCodeCommit']==stage['executionCodeCommit']
 assert execution['newModelCompletionCalls']==0 and execution['bankBefore']==load(attempt/'bank-after.json')
 assert execution['bankBefore']['manifestSha256']==BANK and len(execution['bankBefore']['files'])==845
 assert len(stage['results'])==12
 for name,value in stage['results'].items():assert value['status']=='PASS',name;verify_process(value['process'])
 assert logical_sha(attempt/'legacy-export/stdout.log')=='77cd671180a6b1a1289e2a97447eb5895109edd175157b041e14bb3730a63125'
 selection=attempt/'selection';sel=load(selection/'summary.json');u=sel['selectionQueries'];total=4220+u
 assert sel['sourceCodeCommit']==execution['executionCodeCommit'] and sel['tasks']==422 and sel['cases']==115185
 assert sel['modelProfileRows']==8440 and sel['profileTokenViews']==33760 and sel['profilePromptForms']==4220
 assert sel['selectionUsedReferenceOrExpectedOutputs'] is False and sel['newCompletionCalls']==0
 raw=list(records(selection/'input-only.jsonl'));validate_inputs(raw);tasks=[r['task'] for r in raw]
 assert logical_sha(selection/'input-only.jsonl')==sel['inputOnlySha256']
 assert logical_sha(selection/'raw-prompts.jsonl')==sel['rawPromptsSha256']
 assert logical_sha(selection/'selection-queries.jsonl')==sel['selectionQueriesSha256']
 profiles={s:load(selection/s/'exposure.json') for s in SCENARIOS}
 for s,p in profiles.items():validate_profile(p,tasks,s);assert file_sha(selection/s/'exposure.json')==sel['scenarioProfiles'][s]
 forms=indexed(selection/'raw-prompts.jsonl');assert len(forms)==4220
 queries=indexed(selection/'selection-queries.jsonl');assert len(queries)==u
 canonical={**forms,**queries};assert len(canonical)==total
 checks={};counts={}
 for model in ['qwen','llama']:
  checks[model]={'controls':streams.audit(attempt/'controls'/model/'data',attempt/'control-inputs'/model/'controls.jsonl',15,model),
    'complete':streams.audit(attempt/'complete'/model/'data',selection/model/'complete.jsonl',total,model)}
  counts[model]={}
  cfg=load(selection/model/'model-config.json')
  assert all(profile['modelManifestSha256ByName'][cfg['model']]==cfg['manifestSha256'] for profile in profiles.values())
  snapshot=OLD/'records/model-snapshot'/model
  system=(snapshot/'system.txt').read_text()
  assert sha(system.encode())==cfg['effectiveSystemSha256']
  assert file_sha(snapshot/'template.txt')==cfg['effectiveTemplateSha256']
  for row in records(selection/model/'complete.jsonl'):
   original=canonical[row['id']]
   assert all(row[k]==original[k] for k in ['rawPrompt','rawSha256','taskId','promptKind'])
   assert row['chatPrompt']==expected_chat(model,system,row['rawPrompt'])
  fixtures={'control:'+r['id']:r['text'] for r in load(OLD/'controls.json')}
  for row in records(attempt/'control-inputs'/model/'controls.jsonl'):
   assert row['rawPrompt']==fixtures[row['id']] and row['chatPrompt']==expected_chat(model,system,row['rawPrompt'])
  for family in ['controls','complete']:
   summary=load(attempt/family/model/'data/summary.json')
   assert summary['newCompletionCalls']==0 and summary['modelFileStateBefore']==summary['modelFileStateAfter']==cfg['modelFileState']
   assert summary['modelBlobSha256']==cfg['modelBlobSha256'] and summary['ggufMetadataSha256']==cfg['ggufMetadataSha256']
  for row in records(attempt/'complete'/model/'data/measurements.jsonl'):
   counts[model][row['id']]={'counts':{v:r['count'] for v,r in row['measurements'].items()},'chatSha256':row['chatSha256']}
  assert len(counts[model])==total
 for row in queries.values():validate_query(row,counts)
 query_by_text={r['rawPrompt']:r for r in queries.values()};assert len(query_by_text)==u
 used=set()
 def q(text):
  row=query_by_text[text];used.add(row['id']);return row
 def budget(task,indices,s):
  p=prompts(task,STUB,indices);result={}
  for kind in ['verifierA','verifierB']:
   query=q(p[kind])
   for m in ['qwen','llama']:
    n=counts[m][query['id']]['counts']['chatWithSpecial'];allot=n+s['generationReplyTokens']+s['verificationReplyTokens']
    result[m+'/'+kind+'WithStub']=dict(queryId=query['id'],inputTokens=n,totalWithAllowance=allot,fits=allot<=s['contextTokens'])
  return result
 exposure={}
 for key,s in SCENARIOS.items():
  decisions=load(selection/key/'selection.json');assert decisions['scenario']==s and len(decisions['tasks'])==422
  reasons=Counter();visible=Counter();duplicates=0;max_input=0
  for task,profile,record in zip(tasks,profiles[key]['tasks'],decisions['tasks']):
   assert record['taskId']==task['taskId'] and record['initialBudgets']==budget(task,[],s)
   selected=[];expected=[]
   for case in task['cases']:
    index=case['index']
    if len(selected)==3:expected.append(dict(index=index,reason='MAX_VISIBLE_REACHED'));continue
    query=q(case['args']);c={m:counts[m][query['id']]['counts']['rawNoSpecial'] for m in ['qwen','llama']}
    max_input=max(max_input,*c.values())
    if max(c.values())>512:expected.append(dict(index=index,reason='INPUT_TOKEN_LIMIT',queryId=query['id'],inputTokens=c));continue
    envelope=budget(task,selected+[index],s);fits=all(r['fits'] for r in envelope.values())
    expected.append(dict(index=index,reason='SELECTED' if fits else 'PROMPT_BUDGET',queryId=query['id'],inputTokens=c,tentativeBudgets=envelope))
    if fits:selected.append(index)
   final=budget(task,selected,s)
   assert record['decisions']==expected and record['selectedCaseIndices']==selected==profile['selectedCaseIndices']
   assert record['finalBudgets']==final and record['zeroVisible']==(not selected)
   assert record['planningEnvelopeFits']==all(r['fits'] for r in final.values())
   reasons.update(r['reason'] for r in expected);visible[len(selected)]+=1
   duplicates+=len(selected)-len({task['cases'][i]['args'] for i in selected})
  exposure[key]=dict(visibleCountDistribution={str(k):v for k,v in sorted(visible.items())},decisions=dict(reasons),
    displayedCases=sum(k*v for k,v in visible.items()),hiddenCases=115185-sum(k*v for k,v in visible.items()),
    selectedDuplicateArgumentRows=duplicates,maximumConsideredRawInputTokens=max_input,
    planningEnvelopeTasks=sum(r['planningEnvelopeFits'] for r in decisions['tasks']))
 assert used==set(queries),'unexplained selection query'
 old={r['taskId']:r for r in records(OLD/'records/inputs-02/raw-prompts.jsonl.xz')};assert len(old)==422
 for task in tasks:
  value=old[task['taskId']]['prompts'];a=value['verifierA'];prefix='Candidate code:\n```js\n';suffix='\n```\nYou are given ONLY the inputs'
  assert a.count(prefix)==1 and a.count(suffix)==1;reference=a.split(prefix,1)[1].split(suffix,1)[0]
  for bounded in [False,True]:
   for key in (SCENARIOS if bounded else ['full']):
    indices=next(r['selectedCaseIndices'] for r in profiles[key]['tasks'] if r['taskId']==task['taskId']) if bounded else None
    p=prompts(task,reference,indices);stub=prompts(task,STUB,indices)
    p.update(verifierAWithStub=stub['verifierA'],verifierBWithStub=stub['verifierB'])
    if not bounded:assert p==value,'historical all-input prompt changed'
    else:
     for kind,text in p.items():
      row=forms[key+':'+task['taskId']+':'+kind]
      assert row['rawPrompt']==text and row['rawSha256']==sha(text.encode()),'independent builder byte mismatch'
      assert row['selectedCaseIndices']==indices and row['fullOracleCases']==task['caseCount'] and row['taskId']==task['taskId']
 stats={};fit=[]
 for key,s in SCENARIOS.items():
  stats[key]={}
  for model in ['qwen','llama']:
   stats[key][model]={}
   for kind in KINDS:
    v=[counts[model][key+':'+t['taskId']+':'+kind]['counts']['chatWithSpecial'] for t in tasks]
    stats[key][model][kind]=dict(minimum=min(v),median=statistics.median(v),maximum=max(v))
  for candidate,kinds in [('reference',['verifierA','verifierB']),('empty',['verifierAWithStub','verifierBWithStub'])]:
   ids=[t['taskId'] for t in tasks if all(counts[m][key+':'+t['taskId']+':generation']['counts']['chatWithSpecial']+s['generationReplyTokens']<=s['contextTokens'] and
     all(counts[m][key+':'+t['taskId']+':'+k]['counts']['chatWithSpecial']+s['verificationReplyTokens']<=s['contextTokens'] for k in kinds) for m in ['qwen','llama'])]
   fit.append(dict(scenario=key,candidateProbe=candidate,tasks=len(ids),taskIds=ids))
 probes=0;dispatches=0;boundary_pairs=0;failure_counts=Counter();mocksteps=0;resumed=0;rejects=[]
 for key in SCENARIOS:
  for model in ['qwen','llama']:
   base=attempt/'policy-probes'/(key+'-'+model)/'data';summary=load(base/'summary.json');policy=load(attempt/'policies'/(key+'-'+model+'.json'))
   assert summary['status']=='PASS' and summary['newModelCompletionCalls']==0 and len(summary['probes'])==18
   assert summary['managedHeapHardLimitEnvironment'] is None and summary['gcConfiguration']['GCHeapHardLimit']==0
   assert summary['betweenFixtureCollection'].startswith('Forced blocking compacting full-generation collection')
   assert summary['policySha256']==file_sha(attempt/'policies'/(key+'-'+model+'.json'))
   assert policy['exposureSha256']==file_sha(selection/key/'exposure.json')
   for construction in summary['construction']:
    if 'atBoundaryTokens' in construction:
     cap=SCENARIOS[key]['generationReplyTokens' if construction['id']=='generation' else 'verificationReplyTokens']
     assert construction['atBoundaryTokens']+cap==SCENARIOS[key]['contextTokens'] and construction['overBoundaryTokens']==construction['atBoundaryTokens']+1
     boundary_pairs+=1
   for probe in summary['probes']:
    folder=base/probe['id'];rows=list(records(folder/'requests.jsonl'));requests=[r for r in rows if r['kind']=='request'];responses=[r for r in rows if r['kind']=='response']
    assert len(requests)==1 and probe['passed'] and probe['noAcceptedRunSummary'] and not (folder/'summary.json').exists()
    request=requests[0];assert sha(request['rawPrompt'].encode())==request['rawSha256']
    expected=probe['expectedStatus'];dispatch=0 if expected in ['CONTEXT_OVERFLOW','COUNTER_ERROR'] else 1
    assert probe['syntheticHttpDispatches']==dispatch
    if expected:
     assert probe['actualStatus']==expected
     inc=load(folder/'incomplete-run.json');assert inc['status']==expected and inc['verdict'] is None and inc['completedSteps']==0 and inc['plannedSteps']==inc['notCompletedSteps']==48
     failure_counts[expected]+=1
    else:assert probe['actualStatus']=='FITTING_SYNTHETIC_RESPONSE' and not (folder/'incomplete-run.json').exists()
    if expected!='COUNTER_ERROR':
     assert request['crossEngineAgreement'] is True
     assert (request['inputTokens']+request['replyTokens']<=request['contextTokens'])==(expected!='CONTEXT_OVERFLOW')
    identity=load(folder/'token-counter.identity.json')
    assert identity['policyIdentityMatched']==(probe['id']!='changed-counter-identity')
    if probe['id'] not in ['changed-counter-identity','malformed-counter']:
     assert identity['nativeExecutableSha256']==execution['nativeSha256'] and identity['modelManifestSha256']==policy['modelManifestSha256']
    for r in responses:assert sha(r['rawResponse'].encode())==r['sha256']
    probes+=1;dispatches+=dispatch
  base=attempt/'mock-controls'/key/'data';summary=load(base/'summary.json')
  assert summary['status']=='PASS' and summary['steps']==summary['executionsPassed']==48 and summary['replayedSteps']==32
  assert summary['pCorrect']==1
  assert summary['completeDecisionEqualityWithoutDurations'] and summary['modelCompletionCalls']==summary['externalTokenCounterCalls']==0
  full=next((base/'full').iterdir());continued=next((base/'resumed').iterdir())
  for name in ['trials.jsonl','candidates.jsonl']:
   a=list(records(full/name));b=list(records(continued/name));assert len(a)==len(b)==48
   for x,y in zip(a,b):x.pop('durationMs',None);y.pop('durationMs',None);assert x==y
  assert len(summary['negativeChecks'])==4 and all(r['exitCode']==1 and not r['outputCreated'] for r in summary['negativeChecks'])
  mocksteps+=48;resumed+=32;rejects+=summary['negativeChecks']
 negative=streams.negative_checks()
 def reject(label,call):
  try:call()
  except (AssertionError,KeyError,ValueError):negative.append(label)
  else:raise AssertionError('negative evidence control accepted: '+label)
 p=copy.deepcopy(profiles['compact4k']);p['tasks'][0]['selectedCaseIndices']=[p['tasks'][0]['caseCount']]
 reject('out-of-range-visibility',lambda:validate_profile(p,tasks,'compact4k'))
 p=copy.deepcopy(profiles['compact4k']);p['tasks'][0]['inputSha256']='0'*64
 reject('changed-input-identity',lambda:validate_profile(p,tasks,'compact4k'))
 query=copy.deepcopy(next(iter(queries.values())));query['predictedCounts']['qwen']['chatWithSpecial']+=1
 reject('incorrect-selection-count',lambda:validate_query(query,counts))
 query=copy.deepcopy(next(iter(queries.values())));query['rawPrompt']+='\n'
 reject('changed-query-bytes',lambda:validate_query(query,counts))
 reject('missing-input-task',lambda:validate_inputs(raw[:-1]))
 shared=all(forms['compact4k:'+t['taskId']+':'+k]['rawPrompt']==forms['compact8k:'+t['taskId']+':'+k]['rawPrompt'] for t in tasks for k in KINDS)
 return dict(schema='aijade.p2a.bounded-input.aggregate.v1',status='PASS',executionCodeCommit=execution['executionCodeCommit'],planCommit=execution['planCommit'],amendmentCommit=execution['amendmentCommit'],memoryLifecycleAmendmentCommit=execution['memoryLifecycleAmendmentCommit'],
  tasks=422,fullOracleCases=115185,bankFiles=845,scenarios=SCENARIOS,profilePromptForms=4220,modelProfileRows=8440,profileTokenViews=33760,
  selectionQueries=u,selectionQueryRows=u*2,selectionQueryViews=u*8,controls=30,controlViews=120,totalCompleteRows=2*total,totalCompleteViews=8*total,
  streamAudits=checks,selection=exposure,statistics=stats,commonModelTaskFits=fit,policyProbes=probes,syntheticHttpDispatches=dispatches,
  exactBoundaryPairs=boundary_pairs,failureStatusCounts=dict(failure_counts),mockSteps=mocksteps,replayedPrefixSteps=resumed,identityRejections=len(rejects),negativeEvidenceChecks=negative,
  originalLegacyExportUnchanged=True,fullOracleUnchanged=True,independentPromptReconstruction=True,allTokenViewsAgree=True,sharedPromptBytesAcrossScenarios=shared,
  newModelCompletionCalls=0,authorTaskReview='PENDING',primaryDesignSelection='PENDING',deviceQualification='PENDING',
  inferenceBoundary='Vocabulary/tokenizer and in-process synthetic HTTP controls only; no model completions, reliability outcomes or device qualification.')

if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__);p.add_argument('--attempt',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 result=audit(a.attempt);a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ['commonModelTaskFits','streamAudits']},ensure_ascii=False,indent=2))
