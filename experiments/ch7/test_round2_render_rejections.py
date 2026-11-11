#!/usr/bin/env python3
"""Coherently edited disposable controls, never edits the measured packet."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile

from audit_retrieval_led import raw, load
from audit_retrieval_suffix import require
from audit_round2_render import verify
from test_live_manifest_rejections import FILES as BASE_FILES

FILES=BASE_FILES+['admission.json','admission-telemetry.jsonl','round2/actions-prepared.json',
 'round2/actions-dispatched.json','round2/actions.json','round2/journal.jsonl','round2/renderer-request.json',
 'round2/renderer-closed.json','round2/manifest.json','round2/registry.jsonl',
 'round2/receipt-dispositions.json','round2/client/aijade-render-state.jsonl']


def run(root,repo):
    original={f:hashlib.sha256(raw(root,f)).hexdigest() for f in FILES}
    controls=[]
    names=['wrong-persisted-act','changed-database-source-row','missing-observed-receipt',
           'foreign-receipt','changed-receipt-hash','second-time-reversal',
           'dispatch-after-refusal','omitted-condition','changed-request-reference']
    for name in names:
        with tempfile.TemporaryDirectory(prefix='aijade-round2-negative-') as temporary:
            target=Path(temporary)
            for rel in FILES:
                p=target/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw(root,rel))
            def save(rel,value): (target/rel).write_text(json.dumps(value,indent=2)+'\n')
            data=[load(target,'round2/'+f) for f in ['actions-prepared.json','actions-dispatched.json','actions.json']]
            journal=[json.loads(x) for x in raw(target,'round2/journal.jsonl').splitlines()]
            eligible=[i for i,r in enumerate(data[2]) if r['receipt'] is not None]
            require(len(eligible)>=2,'no observed second witnesses for corruption controls')
            index=eligible[0]
            if name=='second-time-reversal':
                journal[1]['monotonicTicks']=journal[0]['monotonicTicks']-1
            elif name=='omitted-condition':
                for values in data:values.pop()
            else:
                if name=='dispatch-after-refusal':
                    index=next(i for i,r in enumerate(data[2]) if r['disposition']=='reuse_refused')
                for values in data:
                    row=values[index]
                    if name=='wrong-persisted-act':
                        row['persistedAct']='inform' if row['persistedAct']!='inform' else 'celebrate'
                    elif name=='changed-database-source-row':
                        spec=copy.deepcopy(row['specification'])
                        spec['proposal']['candidateParams']['emotion.preset']='inform'
                        text=json.dumps(spec)
                        row.update(specification=spec,specText=text,specTextSha256=hashlib.sha256(text.encode()).hexdigest())
                    elif name=='changed-request-reference':
                        row['requestedActReference']='celebrate'
                    elif name=='dispatch-after-refusal':
                        row['dispatched']=True
                        row['mappedIntent']=copy.deepcopy(data[2][eligible[0]]['mappedIntent'])
                row=data[2][index]
                if name=='missing-observed-receipt':
                    row.update(receipt=None,disposition='render_unknown',importPosts=[])
                elif name=='foreign-receipt':
                    row['receipt']['renderRef']=data[2][eligible[1]]['receipt']['renderRef']
                elif name=='changed-receipt-hash':
                    row['receipt']['appliedParamsHash']='0'*64
                key=row['caseId']+'/'+row['condition']
                for event in journal:
                    if event['caseId']!=key:continue
                    if event['phase']=='selection.end':event['detail']=copy.deepcopy(data[0][index])
                    elif event['phase']=='intent.sent':event['detail']=copy.deepcopy(data[1][index])
                    elif event['phase']=='case.complete':event['detail']=copy.deepcopy(data[2][index])
            for filename,values in zip(['actions-prepared.json','actions-dispatched.json','actions.json'],data):
                save('round2/'+filename,values)
            # Rebind the preparation handoff so controls reach cross-source checks.
            handoff=load(target,'round2/renderer-request.json')
            handoff['preparedSha256']=hashlib.sha256(raw(target,'round2/actions-prepared.json')).hexdigest()
            save('round2/renderer-request.json',handoff)
            (target/'round2/journal.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in journal))
            try:verify(target,repo)
            except (ValueError,KeyError,TypeError,StopIteration) as error:
                controls.append(dict(control=name,rejected=True,reason=type(error).__name__+': '+str(error)))
            else:raise AssertionError('Corrupted second observation accepted: '+name)
    require(original=={f:hashlib.sha256(raw(root,f)).hexdigest() for f in FILES},'primary packet changed')
    return dict(status='PASS',rejectedCorruptions=len(controls),controls=controls,primaryUnchanged=True,newHeldOutCases=0)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--repo',type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.root,a.repo),indent=2))
