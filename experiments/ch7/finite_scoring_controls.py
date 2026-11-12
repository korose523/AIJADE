#!/usr/bin/env python3
"""Pure existing-row/synthetic controls; these create no new empirical or held-out cases."""
import copy
import json
from pathlib import Path

from build_known_live_manifest import construct
from comparison_manifest import require
from finite_inputs import scoring
from finite_score import score_rows, independently_aggregate
from prepare_manifest_instrument import derive


def run(repo):
    old,_=construct(repo);rows,template,*_=derive(repo)
    runtime=dict(schema='aijade.ch7.live-case-manifest.v2',purpose='qualification_only',constructionFreezeCommit='b'*40,
                 selectionSha256=old['selectionSha256'],blockIndex=0,cases=[dict(input=c,replayAt='before_delivery' if c['operations']['repeatOutcome'] else 'none',
                 revokeAt='after_delivery' if c['operations']['revokeBeforeReuse'] else 'none',failurePoint='authority_before' if c['operations']['failStateWrite'] else 'none') for c in old['cases']])
    contract=scoring(runtime,template['cases'],'a'*64);result=score_rows(rows,runtime,contract);checks=[]
    require(result['differencesC2MinusC1']==dict(invalidDurablePromotions=-3,integrityInvalidReuse=-2),'old numerical projection changed')
    checks.append('old complete finite numerical projection unchanged')
    aggregate=independently_aggregate(rows,contract)
    for arm in ['C1','C2']:
        for field,value in aggregate[arm]['totals'].items():require(value==result['arms'][arm][field],'independent raw aggregation')
    checks.append('independent original-row aggregates agree')
    adverse=copy.deepcopy(rows);foreign=next(r['caseId'] for r in contract['cases'] if r['window']=='execution_receipt_intent')
    positive=copy.deepcopy(next(r for r in adverse if r['caseId']==foreign and r['condition']=='C1'));positive['condition']='C2'
    adverse[next(i for i,r in enumerate(adverse) if r['caseId']==foreign and r['condition']=='C2')]=positive
    require(score_rows(adverse,runtime,contract)['arms']['C2']['invalidDurablePromotions']==1,'adverse C2 censored')
    checks.append('complete adverse C2 remains scoreable')
    for r in adverse:r['condition']='C2' if r['condition']=='C1' else 'C1'
    require(score_rows(adverse,runtime,contract)['differencesC2MinusC1']['invalidDurablePromotions']>0,'reversed result censored')
    checks.append('reversed finite contrast remains scoreable')
    controls=[]
    for name in ['missing-arm','duplicate-arm','changed-window','changed-denominator','unknown-field','unbound-rule','wrong-origin','wrong-scope']:
        rr,rt,cc=copy.deepcopy((rows,runtime,contract))
        if name=='missing-arm':rr.pop()
        elif name=='duplicate-arm':rr[-1]=copy.deepcopy(rr[0])
        elif name=='changed-window':cc['cases'][0]['allowedSpecs']+=1
        elif name=='changed-denominator':cc['scheduledInvalidReuseOpportunitiesPerCondition']+=1
        elif name=='unknown-field':cc['expectedC2Better']=True
        elif name=='unbound-rule':cc['cases'][0]['caseId']='missing'
        elif name=='wrong-origin':cc['constructionFreezeCommit']='c'*40
        else:rt['purpose']=cc['purpose']='invented'
        try:score_rows(rr,rt,cc)
        except (ValueError,TypeError,KeyError) as error:controls.append(dict(control=name,rejected=True,reason=str(error)))
        else:raise AssertionError('bad finite scoring input accepted: '+name)
    return dict(status='PASS',checks=checks,rejectedCorruptions=controls,newHeldoutCases=0,newEmpiricalObservations=0,
                interpretation='Existing observations and explicit synthetic modifications only; not a new comparison result.')


if __name__=='__main__':print(json.dumps(run(Path(__file__).resolve().parents[2]),indent=2))
