"""Exact model/prompt capacity ledger from complete dual-engine token records."""
from pathlib import Path
from collections import Counter
import json,statistics
from audit_streams import opened

CONTEXTS=[4096,8192,16384,32768]
RESERVES=[0,256,1024,2048,4096]
KINDS=['generation','verifierA','verifierB','verifierAWithStub','verifierBWithStub']

def load(path):return json.loads(path.read_text())
def rows(path):
 with opened(path,False) as stream:yield from map(json.loads,stream)


def analyze(complete,inputs,out):
 summary=load(complete/'summary.json');assert summary['status']=='PASS' and not summary['controlsOnly']
 populations={}
 for model in ['qwen','llama']:
  data=list(rows(complete/'complete'/model/'data/measurements.jsonl'))
  source={row['id']:row for row in rows(inputs/model/'complete.jsonl')}
  assert len(data)==len(source)==2110
  assert all(row['status']=='PASS' for row in data)
  assert set(row['id'] for row in data)==set(source)
  assert Counter(row['promptKind'] for row in data)=={kind:422 for kind in KINDS}
  assert all(row['rawSha256']==source[row['id']]['rawSha256'] and row['chatSha256']==source[row['id']]['chatSha256'] and row['templateSha256']==source[row['id']]['templateSha256'] and row['systemSha256']==source[row['id']]['systemSha256'] for row in data)
  populations[model]=data
 stats={};ledger=[];fits={}
 for model,data in populations.items():
  stats[model]={}
  for kind in KINDS:
   records=[row for row in data if row['promptKind']==kind]
   views={}
   for view in ['rawNoSpecial','rawWithSpecial','chatNoSpecial','chatWithSpecial']:
    values=[(row['measurements'][view]['count'],row['taskId']) for row in records]
    views[view]={'minimum':min(values)[0],'minimumTask':min(values)[1],'median':statistics.median(x[0] for x in values),'maximum':max(values)[0],'maximumTask':max(values)[1]}
   overhead=[row['measurements']['chatWithSpecial']['count']-row['measurements']['rawNoSpecial']['count'] for row in records]
   bos=[row['measurements']['chatWithSpecial']['count']-row['measurements']['chatNoSpecial']['count'] for row in records]
   stats[model][kind]={'views':views,'chatOverheadMin':min(overhead),'chatOverheadMax':max(overhead),'completionSpecialDifferenceMin':min(bos),'completionSpecialDifferenceMax':max(bos)}
  for ctx in CONTEXTS:
   for reserve in RESERVES:
    selected={kind:set() for kind in KINDS}
    for row in data:
     if row['measurements']['chatWithSpecial']['count']+reserve<=ctx:selected[row['promptKind']].add(row['taskId'])
    reference=selected['generation']&selected['verifierA']&selected['verifierB']
    empty=selected['generation']&selected['verifierAWithStub']&selected['verifierBWithStub']
    ledger.append({'model':model,'contextTokens':ctx,'outputReserveTokens':reserve,'plannedTasks':422,
                   'promptFitCounts':{kind:len(value) for kind,value in selected.items()},'generationAndBothReferenceFit':len(reference),'generationAndBothEmptyFit':len(empty)})
    fits[(model,ctx,reserve,'reference')]=reference;fits[(model,ctx,reserve,'empty')]=empty
 common=[]
 for ctx in CONTEXTS:
  for reserve in RESERVES:
   for mode in ['reference','empty']:
    shared=fits[('qwen',ctx,reserve,mode)]&fits[('llama',ctx,reserve,mode)]
    common.append({'contextTokens':ctx,'outputReserveTokens':reserve,'candidateProbe':mode,'commonTasks':len(shared),'taskIds':sorted(shared)})
 report={'schema':'aijade.p2a.token-capacity.aggregate.v1','models':2,'tasks':422,'promptKinds':5,'rawPrompts':2110,'modelPromptRows':4220,
         'independentTokenViewsPerRow':4,'tokenViews':16880,'newCompletionCalls':0,'allRowsAgree':True,
         'contextScenarios':CONTEXTS,'outputReserveScenarios':RESERVES,'statistics':stats,'capacityLedger':ledger,'commonModelTaskFits':common,
         'interpretation':'Offline exact-token capacity scenarios. Reference/empty probes are fixed code choices. No live prefill, primary split, N/q/T or device-memory qualification is inferred.'}
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 return report
