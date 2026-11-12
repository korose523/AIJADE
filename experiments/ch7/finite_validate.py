#!/usr/bin/env python3
"""Check the complete fresh construction against the public freeze before any measurement."""
import argparse
import collections
import json
from pathlib import Path
import subprocess

from comparison_manifest import require, REGISTRY_SHA256
from finite_inputs import BANK, FAMILIES, bank, derive_suite, sha


def signature(c):
    x=c['input'];op=x['operations']
    return (x['taskId'],x['codeSha256'],x['requestedAct'],op['execution'],op['mapperActOverride'],
            op['receiptCaseId']!=x['caseId'],op['assetVersionOverride'] is not None,op['claimedStage'],
            op['repeatOutcome'],op['revokeBeforeReuse'],op['failStateWrite'],c['replayAt'],c['revokeAt'],c['failurePoint'])


def verify(repo,inputs):
    construction=json.loads((inputs/'construction.json').read_text());freeze=construction['constructionFreezeCommit']
    freeze_receipt=json.loads((repo/'experiments/ch7/finite-heldout/construction-freeze.json').read_text())
    require(freeze_receipt['constructionFreezeCommit']==freeze,'different construction freeze')
    for rel,digest in freeze_receipt['sources'].items():
        require(sha((repo/rel).read_bytes())==digest,'construction source changed: '+rel)
        require(sha(subprocess.check_output(['git','show',freeze+':'+rel],cwd=repo))==digest,'source not in public freeze')
    require(json.loads((repo/BANK).read_text())==bank(repo),'candidate rule/label drift')
    expected=derive_suite(repo,freeze,construction['modelSha256'])
    observed={str(p.relative_to(inputs)) for p in inputs.rglob('*') if p.is_file() and p.name!='suitability-acceptance.json'}
    require(observed==set(expected),'missing/extra construction files')
    checks=[]
    for rel,value in expected.items():
        require(json.loads((inputs/rel).read_text())==value,'construction differs from frozen derivation: '+rel)
        checks.append('exact frozen derivation: '+rel)
    old=json.loads((repo/'experiments/ch7/live-manifest-known-input-v1.json').read_text())
    old_signatures={signature(dict(input=c,replayAt='before_delivery' if c['operations']['repeatOutcome'] else 'none',
                                  revokeAt='after_delivery' if c['operations']['revokeBeforeReuse'] else 'none',
                                  failurePoint='authority_before' if c['operations']['failStateWrite'] else 'none')) for c in old['cases']}
    all_cases=[];all_rules=[];promotion=reuse=0;families=collections.defaultdict(list)
    for b in range(4):
        directory=inputs/('block-'+str(b+1));runtime=json.loads((directory/'runtime-manifest.json').read_text());contract=json.loads((directory/'scoring-manifest.json').read_text())
        require(runtime['purpose']==contract['purpose']=='confirmed_finite_heldout' and runtime['blockIndex']==contract['blockIndex']==b,'block/scope mismatch')
        require(contract['runtimeManifestSha256']==sha((directory/'runtime-manifest.json').read_bytes()),'unbound block scoring')
        require(contract['windowRegistrySha256']==REGISTRY_SHA256,'registry changed')
        ids={c['input']['caseId'] for c in runtime['cases']};rules={r['caseId']:r for r in contract['cases']}
        require(len(ids)==10 and ids==set(rules),'block population')
        require(collections.Counter(r['window'] for r in rules.values())==collections.Counter(FAMILIES),'one declared family per block')
        require(sum(c['input']['conditions']==['C1','C2'] for c in runtime['cases'])==5 and sum(c['input']['conditions']==['C2','C1'] for c in runtime['cases'])==5,'first-arm balance')
        for c in runtime['cases']:
            x=c['input'];require(x['operations']['receiptCaseId'] in ids,'dangling receipt')
            require(signature(c) not in old_signatures,'input merely renames an old scenario')
            require(not {'class','family','window','expected','qualified'} & set(c),'labels in runtime')
            families[rules[x['caseId']]['window']].append((x['taskId'],x['codeSha256']))
        promotion+=contract['scheduledInvalidPromotionOpportunitiesPerCondition'];reuse+=contract['scheduledInvalidReuseOpportunitiesPerCondition']
        all_cases+=runtime['cases'];all_rules+=contract['cases'];checks.append('complete balanced block '+str(b+1))
    require(len(all_cases)==len({c['input']['caseId'] for c in all_cases})==40,'suite unique population')
    require(promotion==28 and reuse==32,'suite scheduled denominator')
    require(all(len(v)==len(set(v))==4 for v in families.values()),'four concrete programme variants per family')
    require(len({signature(c) for c in all_cases})==40,'duplicate concrete operational signatures')
    checks+=['40 distinct programme/operation combinations; 80 scheduled condition rows','four distinct programme bindings per family',
             '28 promotion and 32 reuse opportunities per arm','none of the 40 signatures equals a previous development signature']
    return dict(status='PASS_ALL_FORTY_BEFORE_MEASUREMENT',constructionFreezeCommit=freeze,
                constructionSha256=sha((inputs/'construction.json').read_bytes()),checks=checks,
                casePairs=40,conditionRows=80,independentHumanReview=False,investigatorBlinding=False,
                interpretation='AI-assisted generator and source/schema suitability checks; finite variants inside eight known integrity families, not independent fault-population samples or human semantic approval.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path);a=p.parse_args()
    result=json.dumps(verify(a.repo,a.inputs),indent=2)+'\n'
    if a.output:
        require(not a.output.exists(),'never overwrite suitability acceptance');a.output.write_text(result)
    else:print(result,end='')
