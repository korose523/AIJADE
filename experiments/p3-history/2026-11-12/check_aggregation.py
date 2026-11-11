#!/usr/bin/env python3
"""Separate aggregation cross-check using explicit sums and exact integer sign enumeration."""
import argparse,gzip,json,math
from pathlib import Path
def main(a):
    rows=[json.loads(s) for s in gzip.decompress(a.metrics.read_bytes()).splitlines()];s=json.loads(a.summary.read_text());checks=0
    for name,frame in s['frames'].items():
        def include(r):
            return name=='allQuestions' or (r['category']!=5 and (name=='allAnswerable' or r['gold']>0) and (name!='fullyLocatedAnswerable' or r['unlocated']==0))
        source=[r for r in rows if include(r)]
        for arm,report in frame['arms'].items():
            rr=[r for r in source if r['arm']==arm];assert len(rr)==report['questions'];checks+=1
            for stage,values in report['stages'].items():
                for b in range(2):
                    micro=sum(r['metrics'][stage][b] for r in rr)/len(rr)
                    macro=sum(sum(r['metrics'][stage][b] for r in rr if r['c']==c)/sum(r['c']==c for r in rr) for c in range(10))/10
                    assert abs(micro-values['microBounds'][b])<1e-12 and abs(macro-values['conversationMeanBounds'][b])<1e-12;checks+=2
        for report in frame['contrasts']:
            aa,bb=report['contrast'].split(' minus ');computed=[]
            for c in range(10):
                arows={r['q']:r for r in source if r['arm']==aa and r['c']==c};brows={r['q']:r for r in source if r['arm']==bb and r['c']==c}
                computed.append([sum(arows[q]['metrics']['prompt'][b]-brows[q]['metrics']['prompt'][1-b] for q in arows)/len(arows) for b in range(2)])
            assert all(abs(x-y)<1e-12 for actual,expected in zip(computed,report['conversationDifferences']) for x,y in zip(actual,expected));checks+=1
            if report['pointIdentified']:
                d=[x[0] for x in computed];observed=abs(sum(d));count=0
                for mask in range(1024):
                    value=sum((1 if mask&(1<<i) else -1)*d[i] for i in range(10))
                    count+=abs(value)>=observed-1e-14
                assert count/1024==report['exactSignFlipP'];checks+=1
            else:assert report['exactSignFlipP'] is None and report['holmP'] is None
    receipt=dict(status='SEPARATE_AGGREGATION_CHECK_PASS',checks=checks,rows=len(rows),scope='Independent sums, per-conversation differences and exact-sign enumerations; raw reconstruction is separate.')
    a.out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['metrics','summary','out']:p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
