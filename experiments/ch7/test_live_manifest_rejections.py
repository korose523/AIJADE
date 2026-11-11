#!/usr/bin/env python3
"""Disposable corruptions of a complete actual live packet; preserve every primary byte."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from audit_live_manifest import verify
from audit_retrieval_led import raw, load
from audit_retrieval_suffix import require

FILES=['receipt.json','input-identities.json','runtime-manifest.json','selection.json','window-template.json','cases.json',
       'journal.jsonl','prepared.json','renderer-request.json','renderer-closed.json','manifest.json','registry.jsonl',
       'database-cleanup.json','telemetry.jsonl','client/aijade-render-state.jsonl']


def run(root,repo):
    originals={name:hashlib.sha256(raw(root,name)).hexdigest() for name in FILES}
    controls=[]
    for name in ['missing-arm','retrieved-code','database-token','time-reversal','render-seal','hidden-partial-promotion','changed-window']:
        with tempfile.TemporaryDirectory(prefix='aijade-live-audit-') as temporary:
            target=Path(temporary)
            for relative in FILES:
                path=target/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw(root,relative))
            def save(relative,value): (target/relative).write_text(json.dumps(value,indent=2)+'\n')
            if name=='missing-arm':
                values=load(target,'cases.json'); values.pop(); save('cases.json',values)
            elif name=='retrieved-code':
                values=load(target,'cases.json'); values[0]['prepared']['code']='changed programme'; save('cases.json',values)
            elif name=='database-token':
                values=load(target,'cases.json'); values[0]['databaseAfter']['token']='0'*32; save('cases.json',values)
            elif name=='time-reversal':
                values=[json.loads(s) for s in (target/'journal.jsonl').read_text().splitlines()]
                values[1]['monotonicTicks']=values[0]['monotonicTicks']-1
                (target/'journal.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in values))
            elif name=='render-seal':
                path=target/'client/aijade-render-state.jsonl'; values=[json.loads(s) for s in path.read_text().splitlines()]
                values[-1]['sha256']='0'*64; path.write_text(''.join(json.dumps(v)+'\n' for v in values))
            elif name=='hidden-partial-promotion':
                values=load(target,'cases.json')
                row=next(r for r in values if r['condition']=='C1' and r['runtimeInput']['operations']['failStateWrite'])
                require(row['final']['specs']>0,'partial-promotion control has no observed positive row')
                row['final'].update(specs=0,reports=0,specRows=[],reportRows=[])
                save('cases.json',values)
                journal=[json.loads(s) for s in (target/'journal.jsonl').read_text().splitlines()]
                event=next(j for j in journal if j['caseId']==row['caseId']+'/C1' and j['phase']=='case.complete')
                event['detail']=row
                (target/'journal.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in journal))
            else:
                template=load(target,'window-template.json'); template['cases'][0]['allowedSpecs']=99; save('window-template.json',template)
            try:
                verify(target,repo)
            except (ValueError,KeyError,TypeError) as error:
                controls.append(dict(control=name,rejected=True,reason=type(error).__name__+': '+str(error)))
            else:
                raise AssertionError('Corrupted packet accepted: '+name)
    require(originals=={name:hashlib.sha256(raw(root,name)).hexdigest() for name in FILES},'primary bytes changed by disposable controls')
    return dict(status='PASS',rejectedCorruptions=len(controls),controls=controls,primaryUnchanged=True,newHeldOutCases=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args(); print(json.dumps(run(args.root,args.repo),indent=2))
