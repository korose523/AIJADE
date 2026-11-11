#!/usr/bin/env python3
"""Conversation-level bounds and four fixed paired contrasts, not user-level effects."""
import argparse,collections,gzip,itertools,json,math,random,statistics
from pathlib import Path
STAGES=['candidate','response','echoFiltered','selected','prompt']
CONTRASTS=[('history','static'),('record-after','history'),('record-before','record-after'),('record-between','record-after')]
ARMS=['static','history','record-after','record-before','record-between']
def mean(x):return statistics.fmean(x)
def percentile(x,p):
    x=sorted(x);i=(len(x)-1)*p;lo=math.floor(i);hi=math.ceil(i);return x[lo]+(x[hi]-x[lo])*(i-lo)
def summarize(rows):
    rng=random.Random(20261112);draws=[[rng.randrange(10) for _ in range(10)] for _ in range(10000)]
    frames={
      'annotatedAnswerable':[r for r in rows if r['category']!=5 and r['gold']>0],
      'allAnswerable':[r for r in rows if r['category']!=5],
      'fullyLocatedAnswerable':[r for r in rows if r['category']!=5 and r['gold']>0 and not r['unlocated']],
      'allQuestions':rows}
    result={}
    for frame,items in frames.items():
        arms={};bykey={(r['arm'],r['c'],r['q']):r for r in items}
        for arm in ARMS:
            rr=[r for r in items if r['arm']==arm];macro={};stages={}
            for stage in STAGES:
                values=[[mean(r['metrics'][stage][b] for r in rr if r['c']==c) for b in [0,1]] for c in range(10)]
                macro[stage]=values
                stages[stage]=dict(microBounds=[mean(r['metrics'][stage][b] for r in rr) for b in [0,1]],
                  conversationMeanBounds=[mean(v[b] for v in values) for b in [0,1]],conversationBounds=values)
            arms[arm]=dict(questions=len(rr),stages=stages,
              nativeCutoffTieQueries=sum(r['cutoffTies'] for r in rr),questionsWithCutoffTies=sum(r['cutoffTies']>0 for r in rr),
              promptStates=dict(collections.Counter(r['promptState'] for r in rr)),selectedItems=sum(r['selectedItems'] for r in rr),
              questionItemsSelected=sum(r['questionItemsSelected'] for r in rr),
              suppliedHistoryMessages=sum(r['suppliedHistory'] for r in rr),usedHistoryMessages=sum(r['usedHistory'] for r in rr),
              goldSourceExactTextsInHistory=sum(r['sourceExactTextInHistory'] for r in rr),fallbackQueries=sum(r['fallbackQueries'] for r in rr))
        comparisons=[]
        for a,b in CONTRASTS:
            values=[]
            for c in range(10):
                keys=[(r['c'],r['q']) for r in items if r['arm']==a and r['c']==c]
                differences=[]
                for _,q in keys:
                    aa=bykey[(a,c,q)]['metrics']['prompt'];bb=bykey[(b,c,q)]['metrics']['prompt']
                    differences.append([aa[0]-bb[1],aa[1]-bb[0]])
                values.append([mean(d[i] for d in differences) for i in [0,1]])
            bounds=[mean(v[i] for v in values) for i in [0,1]]
            boots=[[mean(values[c][b] for c in draw) for draw in draws] for b in [0,1]]
            point=all(abs(v[0]-v[1])<1e-15 for v in values)
            p=None
            if point:
                observed=abs(bounds[0]);d=[v[0] for v in values]
                p=sum(abs(sum(s*x for s,x in zip(signs,d))/10)>=observed-1e-15 for signs in itertools.product([-1,1],repeat=10))/1024
            comparisons.append(dict(contrast=a+' minus '+b,conversationDifferences=values,identificationBounds=bounds,
              pointIdentified=point,interval=[percentile(boots[0],.025),percentile(boots[1],.975)],
              intervalKind='conversation-bootstrap percentile interval' if point else 'descriptive resampling envelope of identification bounds',
              exactSignFlipP=p,holmP=None))
        if all(x['exactSignFlipP'] is not None for x in comparisons):
            running=0
            for j,i in enumerate(sorted(range(4),key=lambda i:comparisons[i]['exactSignFlipP'])):
                running=max(running,min(1,(4-j)*comparisons[i]['exactSignFlipP']));comparisons[i]['holmP']=running
        # One paired no-cutoff-tie sensitivity frame shared across all five arms.
        clean=[r for r in items if all(bykey[(arm,r['c'],r['q'])]['cutoffTies']==0 for arm in ARMS)]
        clean_by_arm={arm:[r for r in clean if r['arm']==arm] for arm in ARMS}
        no_tie={arm:dict(questions=len(rr),promptMicroBounds=[mean(r['metrics']['prompt'][i] for r in rr) for i in [0,1]]) for arm,rr in clean_by_arm.items()}
        result[frame]=dict(arms=arms,contrasts=comparisons,pairedNoCutoffTieSensitivity=no_tie)
    return dict(schema='aijade.p3.history-summary.v1',status='DESCRIPTIVE_CONTROLLED_SCRIPT_COMPARISON',
      rows=len(rows),dialogueUnits=10,bootstrapResamples=10000,bootstrapSeed=20261112,signPatterns=1024,frames=result,
      unitAssumptions='Dialogues treated as independent units; exact sign flips require null sign symmetry. Ten dialogue units; scripted benchmark questions and fixed replies are not independent users or natural conversations.',
      uncertainty='Unlocated annotation and absent annotations retain intervals. Ambiguous sources retain prompt intervals. Primary p is null whenever identification is incomplete. Fully located sensitivity is separately labelled.',
      scientificScope='Actual configured text retrieval and complete prompt visibility only; no model use, answer accuracy, genuine contradictions, default fact maintenance, full Web/QQ race probabilities or formal hardware acceptance.')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--metrics',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    rows=[json.loads(x) for x in gzip.decompress(a.metrics.read_bytes()).splitlines()];result=summarize(rows)
    assert not a.out.exists();a.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(rows=result['rows'],arms={k:dict(questions=v['questions'],prompt=v['stages']['prompt']['microBounds']) for k,v in result['frames']['annotatedAnswerable']['arms'].items()})))
