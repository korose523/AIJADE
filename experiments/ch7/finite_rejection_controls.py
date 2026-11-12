#!/usr/bin/env python3
"""Disposable raw corruptions, with coherent rebinding controls and no-op detection."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile

from finite_audit import verify
from audit_retrieval_led import raw, load
from comparison_manifest import require

FILES=['receipt.json','input-identities.json','runtime-manifest.json','selection.json','scoring-manifest.json','cases.json',
       'journal.jsonl','prepared.json','renderer-request.json','renderer-closed.json','manifest.json','registry.jsonl',
       'database-cleanup.json','telemetry.jsonl','client/aijade-render-state.jsonl','build-identity.json']


def run(root,repo):
    originals={n:hashlib.sha256(raw(root,n)).hexdigest() for n in FILES};controls=[]
    names=['missing-arm','duplicate-arm','retrieved-code','database-token','time-reversal','render-seal',
           'hidden-durable-rows-coherent','changed-window-rebound','changed-denominator-rebound','failure-witness-coherent',
           'replay-observation-coherent','unplanned-probe-coherent','embedded-build-revision','runtime-rebound',
           'missing-owned-lease','provider-attempt-coherent']
    for name in names:
        with tempfile.TemporaryDirectory(prefix='aijade-finite-audit-control-') as temporary:
            target=Path(temporary)
            for rel in FILES:
                path=target/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw(root,rel))
            def save(rel,value):(target/rel).write_text(json.dumps(value,indent=2)+'\n')
            def digest(rel):return hashlib.sha256((target/rel).read_bytes()).hexdigest()
            def bind_row(row):
                journal=[json.loads(l) for l in (target/'journal.jsonl').read_text().splitlines()]
                match=next(j for j in journal if j['caseId']==row['caseId']+'/'+row['condition'] and j['phase']=='case.complete')
                match['detail']=copy.deepcopy(row)
                (target/'journal.jsonl').write_text(''.join(json.dumps(j)+'\n' for j in journal))
            rows=load(target,'cases.json')
            if name=='missing-arm':rows.pop();save('cases.json',rows)
            elif name=='duplicate-arm':rows[-1]=copy.deepcopy(rows[0]);save('cases.json',rows)
            elif name=='retrieved-code':rows[0]['prepared']['code']='changed programme';save('cases.json',rows)
            elif name=='database-token':rows[0]['databaseAfter']['token']='0'*32;save('cases.json',rows)
            elif name=='time-reversal':
                journal=[json.loads(l) for l in (target/'journal.jsonl').read_text().splitlines()];journal[1]['monotonicTicks']=journal[0]['monotonicTicks']-1
                (target/'journal.jsonl').write_text(''.join(json.dumps(j)+'\n' for j in journal))
            elif name=='render-seal':
                values=[json.loads(l) for l in (target/'client/aijade-render-state.jsonl').read_text().splitlines()]
                values[-1]['sha256']='0'*64;(target/'client/aijade-render-state.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in values))
            elif name=='hidden-durable-rows-coherent':
                row=next(r for r in rows if r['condition']=='C1' and r['runtimeInput']['input']['operations']['failStateWrite'])
                require(row['final']['specs']>0,'control must use genuinely observed durable rows')
                row['final'].update(specs=0,reports=0,specRows=[],reportRows=[]);save('cases.json',rows);bind_row(row)
            elif name in ['changed-window-rebound','changed-denominator-rebound']:
                value=load(target,'scoring-manifest.json')
                if name=='changed-window-rebound':value['cases'][0]['allowedSpecs']+=1
                else:value['scheduledInvalidReuseOpportunitiesPerCondition']+=1
                save('scoring-manifest.json',value)
                identity=load(target,'input-identities.json');identity['scoringManifestSha256']=digest('scoring-manifest.json');save('input-identities.json',identity)
            elif name=='failure-witness-coherent':
                row=next(r for r in rows if r['databaseErrorWitness'] is not None);row['databaseErrorWitness']['specs']+=1
                save('cases.json',rows);bind_row(row)
            elif name=='replay-observation-coherent':
                row=next(r for r in rows if r['duplicateCommit'] is not None)
                row['operationTrace'][0]['at']='after_duplicate_reuse' if row['operationTrace'][0]['at']!='after_duplicate_reuse' else 'before_delivery'
                save('cases.json',rows);bind_row(row)
            elif name=='unplanned-probe-coherent':
                row=next(r for r in rows if not r['operationTrace']);row['operationTrace'].append(dict(operation='authority_probe',response=None))
                save('cases.json',rows);bind_row(row)
            elif name=='embedded-build-revision':
                value=load(target,'build-identity.json');value['informationalVersion']='0.1.0+'+'0'*40;save('build-identity.json',value)
            elif name=='runtime-rebound':
                value=load(target,'runtime-manifest.json');value['cases'][0]['input']['requestedAct']='celebrate' if value['cases'][0]['input']['requestedAct']!='celebrate' else 'comfort'
                save('runtime-manifest.json',value);identity=load(target,'input-identities.json');identity['runtimeManifestSha256']=digest('runtime-manifest.json')
                contract=load(target,'scoring-manifest.json');contract['runtimeManifestSha256']=digest('runtime-manifest.json');save('scoring-manifest.json',contract)
                identity['scoringManifestSha256']=digest('scoring-manifest.json');save('input-identities.json',identity)
            elif name=='missing-owned-lease':value=load(target,'database-cleanup.json');value.pop();save('database-cleanup.json',value)
            else:rows[0]['gatewayAttempts']=1;save('cases.json',rows);bind_row(rows[0])
            require(any(digest(n)!=originals[n] for n in FILES),'no-op mutation cannot count as rejected corruption')
            try:verify(target,repo)
            except (ValueError,KeyError,TypeError,AssertionError) as error:controls.append(dict(control=name,rejected=True,reason=type(error).__name__+': '+str(error)))
            else:raise AssertionError('corrupted finite packet accepted: '+name)
    require(originals=={n:hashlib.sha256(raw(root,n)).hexdigest() for n in FILES},'primary data changed by controls')
    return dict(status='PASS',rejectedCorruptions=len(controls),controls=controls,primaryUnchanged=True,
                interpretation='Disposable instrument controls; no added empirical or independent human observations.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--repo',type=Path,required=True);a=p.parse_args()
    print(json.dumps(run(a.root,a.repo),indent=2))
