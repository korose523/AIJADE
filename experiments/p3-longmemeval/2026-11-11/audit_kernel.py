#!/usr/bin/env python3
"""Independent numerical reconstruction from raw/sufficient case records; no new retrieval or model call."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

B = 10000
COMPONENTS = ['similarity','strength','recency','context']
MODE = {0:'additive',1:'standardized'}


class CompatRandom:
    """Seeded System.Random compatibility generator; .NET Foundation MIT implementation, algorithm port.

    Source: dotnet/runtime v10.0.3, System/Random.CompatImpl.cs (CompatPrng).
    Original copyright .NET Foundation and contributors, MIT. Retain source attribution when distributing.
    """
    def __init__(self,seed):
        m=2147483647
        def i32(x):return ((x+2**31)%2**32)-2**31
        a=[0]*56; subtraction=m if seed == -2**31 else abs(seed)
        mj=i32(161803398-subtraction);a[55]=mj;mk=1;ii=0
        for _ in range(1,55):
            ii+=21
            if ii>=55:ii-=55
            a[ii]=mk;mk=i32(mj-mk)
            if mk<0:mk+=m
            mj=a[ii]
        for _ in range(4):
            for i in range(1,56):
                n=i+30
                if n>=55:n-=55
                a[i]=i32(a[i]-a[1+n])
                if a[i]<0:a[i]+=m
        self.a=a;self.i=0;self.j=21
    def next(self,n):
        self.i=self.i+1 if self.i<55 else 1;self.j=self.j+1 if self.j<55 else 1
        value=self.a[self.i]-self.a[self.j]
        if value==2147483647:value-=1
        if value<0:value+=2147483647
        self.a[self.i]=value
        return int((value*(1.0/2147483647))*n)


def audit(kernel,inputs,output):
    receipt=json.loads((kernel/'kernel-receipt.json').read_text())
    assert receipt['status']=='complete-after-legacy-numeric-reconstruction'
    assert json.loads((kernel/'legacy-comparison.json').read_text())['status']=='PASS'
    journal=kernel/'kernel-cases.jsonl'
    if not journal.exists():journal=kernel/'kernel-cases.jsonl.gz'
    h=hashlib.sha256();records=[]
    with (gzip.open(journal,'rb') if journal.suffix=='.gz' else journal.open('rb')) as f:
        for line in f:h.update(line);records.append(json.loads(line))
    assert h.hexdigest()==receipt['journalSha256']
    with gzip.open(inputs/'eligibility.jsonl.gz','rt') as f:source=[json.loads(line) for line in f]
    byid={q['questionId']:q for q in source}
    assert len(records)==479 and sum(r['answerable'] for r in records)==470
    assert {r['questionId'] for r in records}=={r['questionId'] for r in source if r['legacyMarked']}
    for r in records:
        q=byid[r['questionId']]
        assert q['rawIndex']==r['rawIndex'] and q['answerable']==r['answerable'] and len(q['turns'])==r['episodes']
        assert len(r['weights'])==3 and len(r['gating'])==4 and len(r['delivery'])==4
        assert {(g['mode'],g['penaltyOff']) for g in r['gating']}=={(0,False),(0,True),(1,False),(1,True)}
        gold=set(q['markedIds']) | {'fact_'+i for i in q['markedIds']}
        assert all(x['gold']==(x['id'] in gold) for x in r['components'])
        assert all(x['gold']==(x['id'] in gold) for d in r['delivery'] for x in d['head'])
    output.mkdir(parents=True,exist_ok=True)
    comparisons=[]
    def eq(actual,expected,path):
        actual=float(actual);expected=float(expected)
        assert math.isfinite(actual) and math.isfinite(expected)
        assert abs(actual-expected)<=1e-9,(path,actual,expected)
        comparisons.append(dict(path=path,actual=actual,recomputed=expected))
    for frame,rows in [('legacy-marked-v1',records),('answerable-v2',[r for r in records if r['answerable']])]:
        reports={p.name:json.loads(p.read_text()) for p in (kernel/frame).glob('*.json')}
        n=len(rows)
        rng=CompatRandom(0x5eed2026)
        indices=np.fromiter((rng.next(n) for _ in range(B*n)),dtype=np.int32,count=B*n).reshape(B,n)
        flip_rng=CompatRandom(0x51f7)
        flips=np.fromiter((-1 if flip_rng.next(2)==0 else 1 for _ in range(B*n)),dtype=np.int8,count=B*n).reshape(B,n)
        np.savez_compressed(output/(frame+'-resampling.npz'),indices=indices,signs=flips)
        for variant,name in enumerate(['published','pool150RankOnly','wholeStore']):
            target=reports['pool-check.json'][name]
            eq(target['questions'],sum(r['weights'][variant]['questions'] for r in rows),frame+'/'+name+'/questions')
            eq(target['poolCoverage'],np.mean([r['weights'][variant]['poolCoverage'] for r in rows]),frame+'/'+name+'/coverage')
            for arm,values in target['recallByWeights'].items():
                for k,value in values.items():
                    v=np.mean([r['weights'][variant]['recallByWeights'][arm][k] for r in rows])
                    eq(value,v,frame+'/'+name+'/'+arm+'/'+k)
                    if variant==0:eq(reports['replication.json']['recallByWeights'][arm][k],v,frame+'/replication/'+arm+'/'+k)
            dated=np.array([r['weights'][variant]['recencyBias']['scanned']-r['weights'][variant]['recencyBias']['evidenceMissing'] for r in rows])
            for k,value in target['recencyBias'].items():
                v=np.average([r['weights'][variant]['recencyBias'][k] for r in rows],weights=dated)
                eq(value,v,frame+'/'+name+'/bias/'+k)
                if variant==0:eq(reports['replication.json']['recencyBias'][k],v,frame+'/replication/bias/'+k)
        scale_rows=[];all_pool=[]
        for r in rows:
            c=r['components'];v=np.array([[x[k] for k in COMPONENTS] for x in c]);all_pool.extend(v)
            gold=np.array([x['gold'] for x in c],dtype=bool)
            if not gold.any():continue
            top=np.argsort(-(v*np.array([1,.6,.3,.4])).sum(axis=1),kind='stable')[:8]
            scale_rows.append(dict(gold=v[gold].mean(axis=0),additiveTop8=v[top].mean(axis=0),pool=v.mean(axis=0),poolSd=v.std(axis=0,ddof=0)))
        scales=reports['component-scales.json'];eq(scales['questions'],len(scale_rows),frame+'/scales/questions')
        for group in ['gold','additiveTop8','pool','poolSd']:
            mean=np.array([r[group] for r in scale_rows]).mean(axis=0)
            for k,value in zip(COMPONENTS,mean):eq(scales[group][k],value,frame+'/scales/'+group+'/'+k)
        pooled=np.array(all_pool).std(axis=0,ddof=0)
        for k,v in zip(COMPONENTS,pooled):eq(reports['diagnostics.json']['pooledComponentSd'][k],v,frame+'/pooledSd/'+k)
        for target in reports['delivery-check.json']['rows']:
            cells=[next(c for c in r['delivery'] if MODE[c['mode']]==target['mode'] and c['penalty']==target['conflictPenalty']) for r in rows]
            tops=[c['head'][:8] for c in cells];slots=sum(len(c) for c in tops)
            eq(target['recall8Macro'],np.mean([any(v['gold'] and v['score']>c['floor'] for v in c['head'][:8]) for c in cells]),frame+'/delivery/recall')
            eq(target['penalizedShareOfTop8'],sum(v['conflict'] for c in tops for v in c)/slots if slots else 0,frame+'/delivery/penalized')
            eq(target['goldPenalizedShare'],np.mean([any(v['gold'] and v['conflict'] for v in c['head']) for c in cells]),frame+'/delivery/gold')
        def contrast(target,a,b,path,micro=False):
            a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float);d=a-b
            eq(target['a'],a.mean(),path+'/a');eq(target['b'],b.mean(),path+'/b');eq(target['difference'],a.mean()-b.mean() if micro else d.mean(),path+'/difference')
            values=(a[indices].mean(axis=1)-b[indices].mean(axis=1)) if micro else d[indices].mean(axis=1)
            values.sort();eq(target['bootstrap95'][0],values[int(.025*(B-1))],path+'/lo');eq(target['bootstrap95'][1],values[math.ceil(.975*(B-1))],path+'/hi')
            p=(int((np.abs((flips*d).mean(axis=1))>=abs(d.mean())-1e-12).sum())+1)/(B+1)
            eq(target['signFlipP'],p,path+'/p');eq(target['units'],n,path+'/units')
            eq(target['unitsPositive'],int((d>0).sum()),path+'/positive');eq(target['unitsNegative'],int((d<0).sum()),path+'/negative')
            return p
        for variant,target in [(0,reports['replication.json']['contrasts'][0]),(0,reports['pool-check.json']['contrasts'][0]),(2,reports['pool-check.json']['contrasts'][1])]:
            contrast(target,[r['weights'][variant]['recallByWeights']['sim-only']['8'] for r in rows],
                     [r['weights'][variant]['recallByWeights']['current']['8'] for r in rows],frame+'/weights/'+target['key'],micro=True)
        predicted=[]
        for penalty_off,file in [(False,'replication.json'),(True,'gating-penalty-off.json')]:
            for target in reports[file]['contrasts']:
                if not target['key'].startswith('gating'):continue
                salience='predicted' if 'predicted' in target['key'] else 'oracle';mode='standardized' if 'standardized' in target['key'] else 'additive'
                cells=[next(c for c in r['gating'] if MODE[c['mode']]==mode and c['penaltyOff']==penalty_off)['conditions'] for r in rows]
                p=contrast(target,[c[salience+'-ON']['recall']['8'] for c in cells],[c[salience+'-OFF']['recall']['8'] for c in cells],frame+'/'+file+'/'+target['key'])
                if salience=='predicted':predicted.append((p,penalty_off,target['key']))
        running=0
        for rank,(p,off,key) in enumerate(sorted(predicted,key=lambda x:x[0])):
            running=max(running,min(1,(4-rank)*p));row=next(c for c in reports['diagnostics.json']['predictedGatingHolmFamily'] if c['key']==key and c['penaltyOff']==off)
            eq(row['holmP'],running,frame+'/holm/'+key+'/'+str(off))
    result=dict(status='PASS',numericalComparisons=len(comparisons),tolerance=1e-9,frames=['legacy-marked-v1','answerable-v2'],
                independentImplementation='Python/NumPy from raw component, delivery-head and sufficient case records; independent seeded .NET compatibility RNG port',
                interpretation='Numerical reconstruction only. Shared histories prevent independent-question/population inference; no new human labels or model outputs.',
                source='https://github.com/dotnet/runtime/blob/v10.0.3/src/libraries/System.Private.CoreLib/src/System/Random.CompatImpl.cs',numpy=np.__version__)
    (output/'kernel-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    with gzip.open(output/'kernel-numeric-comparisons.json.gz','xt') as f:json.dump(comparisons,f,separators=(',',':'))
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--kernel',type=Path,required=True);parser.add_argument('--inputs',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();audit(args.kernel,args.inputs,args.out)
