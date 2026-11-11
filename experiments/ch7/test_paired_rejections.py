#!/usr/bin/env python3
"""Seven semantic corruption controls in disposable copies; never edit the measured packet."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from audit_paired_development import verify
from audit_retrieval_led import load, raw, lines, sha


def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def run(root,repo):
    verify(root,repo)
    results=[]
    for name in ['missing-arm','route-code','unequal-inputs','database-continuity','render-seal','hidden-partial-promotion','changed-denominator']:
        with tempfile.TemporaryDirectory(prefix='aijade-paired-rejection-') as temp:
            target=Path(temp)/'packet'
            shutil.copytree(root,target,ignore=shutil.ignore_patterns('renderer-source','*skinning*'))
            rows=load(target,'cases.json');journal=lines(target,'journal.jsonl')
            row=next(r for r in rows if r['caseId']=='H' and r['condition']=='C1')
            if name=='missing-arm':rows.remove(row)
            elif name=='route-code':row['prepared']['codeSha256']='0'*64
            elif name=='unequal-inputs':
                row['initialWrite']['request']['content']+=' '
                row['initialRead']['response']['items'][0]['content']+=' '
                digest=sha(row['initialWrite']['request']['content'].encode())
                row['prepared']['route']['memoryContentSha256']=digest
                prepared=load(target,'prepared.json')
                source=next(r for r in prepared if r['caseId']=='H' and r['condition']=='C1')
                source['route']['memoryContentSha256']=digest
                write(target/'prepared.json',prepared)
                request=load(target,'renderer-request.json');request['preparedSha256']=sha((target/'prepared.json').read_bytes());write(target/'renderer-request.json',request)
                for event in journal:
                    if event['caseId']=='H/C1':
                        replacement={'memory.write.end':row['initialWrite'],'memory.read.end':row['initialRead'],'route.selected':row['prepared']['route'],
                                     'intent.mapped':source,'shared_intent.sent':row['prepared']}.get(event['phase'])
                        if replacement is not None:event['detail']=replacement
            elif name=='database-continuity':row['databaseAfter']['token']='0'*32
            elif name=='render-seal':
                state=raw(target,'client/aijade-render-state.jsonl')
                state=state.replace(b'"applied_params_hash":"',b'"applied_params_hash":"0',1)
                (target/'client/aijade-render-state.jsonl').write_bytes(state)
            elif name=='hidden-partial-promotion':
                row=next(r for r in rows if r['caseId']=='I8' and r['condition']=='C1')
                row['final']['specs']=0
            else:
                scoring=load(target,'scoring.json');scoring['arms']['C1']['scheduledInvalidPromotionOpportunities']=8;write(target/'scoring.json',scoring)
            # Preserve redundant final projections so the audit must follow the
            # causal/raw bindings and fixed contract, rather than a stale copy.
            for r in rows:
                event=next(e for e in journal if e['caseId']==r['caseId']+'/'+r['condition'] and e['phase']=='case.complete')
                event['detail']=r
            write(target/'cases.json',rows)
            (target/'journal.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in journal))
            try:verify(target,repo)
            except (ValueError,KeyError) as error:results.append(dict(control=name,rejected=True,reason=str(error)))
            else:raise AssertionError('corrupted paired packet accepted: '+name)
    return dict(status='PASS',rejectedControls=len(results),results=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.root,args.repo),indent=2))
