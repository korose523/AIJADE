#!/usr/bin/env python3
"""Finite-set scoring with actual provenance. The unchanged old calculator supplies numerical fields only."""
import argparse
import copy
import json
from pathlib import Path

from audit_retrieval_led import load, raw, sha
from comparison_manifest import CONDITIONS, REGISTRY_SHA256, SCHEMA, require, score as calculate, window_registry


def score_rows(rows, runtime, contract):
    required={'schema','purpose','constructionFreezeCommit','blockIndex','runtimeManifestSha256','selectionSha256',
              'conditions','windowRegistrySha256','cases','scheduledInvalidPromotionOpportunitiesPerCondition',
              'scheduledInvalidReuseOpportunitiesPerCondition','round2SemanticActCorrectness'}
    require(type(contract) is dict and set(contract)==required, 'finite scoring fields')
    require(contract['schema']=='aijade.ch7.finite-scoring-manifest.v1', 'finite scoring schema')
    require(runtime['purpose'] in ['qualification_only','confirmed_finite_heldout'], 'finite scope')
    require(runtime['schema']=='aijade.ch7.live-case-manifest.v2', 'runtime schema')
    for key in ['purpose','constructionFreezeCommit','blockIndex','selectionSha256']:
        require(contract[key]==runtime[key], 'scoring/runtime identity '+key)
    require(contract['conditions']==CONDITIONS and contract['windowRegistrySha256']==REGISTRY_SHA256, 'frozen condition/registry')
    case_ids=[c['input']['caseId'] for c in runtime['cases']]
    require(len(case_ids)==len(set(case_ids))==len(contract['cases']), 'finite identities')
    require(set(case_ids)=={c['caseId'] for c in contract['cases']}, 'finite scoring case population')
    require(len(rows)==len(case_ids)*2, 'finite row population')
    template=dict(schema=SCHEMA,purpose='development_reencoding_only',conditions=copy.deepcopy(CONDITIONS),
                  casePairs=len(case_ids),conditionRows=len(rows),cases=copy.deepcopy(contract['cases']),
                  scheduledInvalidPromotionOpportunitiesPerCondition=contract['scheduledInvalidPromotionOpportunitiesPerCondition'],
                  scheduledInvalidReuseOpportunitiesPerCondition=contract['scheduledInvalidReuseOpportunitiesPerCondition'],
                  windowRegistrySha256=REGISTRY_SHA256,
                  sourcePacketManifestSha256=contract['runtimeManifestSha256'],sourceRowsSha256=sha(json.dumps(rows,sort_keys=True).encode()),
                  round2SemanticActCorrectness=contract['round2SemanticActCorrectness'])
    result=calculate(rows,template)
    # No origin, purpose, sample label or interpretation from the internal v1 calculator is propagated.
    return {k:result[k] for k in ['arms','differencesC2MinusC1','rowIntegrityDiagnostics','normalAcceptanceDefinition','round2SemanticActCorrectness']}


def independently_aggregate(rows, contract):
    """Separately count raw durable/reuse observations and fixed finite opportunities."""
    registry=window_registry();rules={r['caseId']:r for r in contract['cases']};by_arm={}
    require(len(rules)==len(contract['cases']), 'duplicate rules')
    for rule in rules.values():
        require({k:v for k,v in rule.items() if k!='caseId'}==registry[rule['window']], 'altered rule')
    for arm in ['C1','C2']:
        population=[r for r in rows if r['condition']==arm]
        require(len(population)==len(rules) and {r['caseId'] for r in population}==set(rules), 'independent population')
        by_case={}
        for row in population:
            rule=rules[row['caseId']];f=row['final'];reads=[row['round2']]
            if row['duplicateReuse'] is not None: reads.append(row['duplicateReuse'])
            by_case[row['caseId']]=dict(
                invalidDurablePromotions=int(bool(rule['promotionOpportunity']) and len(f['specRows'])>rule['allowedSpecs']),
                integrityInvalidReuse=int(bool(rule['reuseOpportunity']) and sum(r['executed'] for r in reads)>rule['allowedReuses']),
                persistedSpecs=len(f['specRows']),persistedReports=len(f['reportRows']),
                round2SandboxExecutions=sum(r['executed'] for r in reads),
                successfulServiceReturns=sum(r['serviceResult']['ok'] for r in row['promotionAttempts']),
                promotionServiceEntries=len(row['promotionAttempts']),actualRound2Queries=len(reads),
                retrievedRound2Queries=sum(r['retrieved'] for r in reads),outcomeMemories=f['outcomeMemoryCount'],
                scheduledInvalidPromotionOpportunities=rule['promotionOpportunity'],scheduledInvalidReuseOpportunities=rule['reuseOpportunity'])
        by_arm[arm]=dict(byCase=by_case,totals={key:sum(c[key] for c in by_case.values()) for key in next(iter(by_case.values()))})
    return by_arm


def score_directory(root):
    receipt=load(root,'receipt.json');identity=load(root,'input-identities.json')
    runtime=load(root,'runtime-manifest.json');contract=load(root,'scoring-manifest.json');rows=load(root,'cases.json')
    require(receipt['status']=='COMPLETE_FINITE_BLOCK_OBSERVATIONS', 'incomplete finite block')
    require(sha(raw(root,'runtime-manifest.json'))==contract['runtimeManifestSha256']==identity['runtimeManifestSha256'], 'runtime hash')
    require(sha(raw(root,'scoring-manifest.json'))==identity['scoringManifestSha256'], 'scoring hash')
    require(receipt['completedCases']==len(rows), 'actual complete rows')
    values=score_rows(rows,runtime,contract);independent=independently_aggregate(rows,contract);checks=0
    for arm in ['C1','C2']:
        for key,value in independent[arm]['totals'].items():
            require(values['arms'][arm][key]==value,'independent aggregate mismatch');checks+=1
        for row in values['arms'][arm]['byCase']:
            for key,value in independent[arm]['byCase'][row['caseId']].items():
                require(row[key]==value,'independent per-case mismatch');checks+=1
    return dict(schema='aijade.ch7.finite-score.v1',status='COMPLETE_FINITE_BLOCK_SCORED',purpose=runtime['purpose'],
                codeCommit=receipt['codeCommit'],constructionFreezeCommit=runtime['constructionFreezeCommit'],
                actualRowsSha256=sha(raw(root,'cases.json')),receiptSha256=sha(raw(root,'receipt.json')),
                runtimeManifestSha256=identity['runtimeManifestSha256'],scoringManifestSha256=identity['scoringManifestSha256'],
                blockIndex=runtime['blockIndex'],casePairs=len(runtime['cases']),measuredConditionRows=len(rows),
                freshFiniteHeldoutPairs=len(runtime['cases']) if runtime['purpose']=='confirmed_finite_heldout' else 0,
                modelRequests=0,independentAggregationChecks=checks,independentHumanReview=False,**values,
                interpretation='Actual finite constructed-case observations; same-investigator AI-assisted design/audit, no investigator blinding, population uncertainty inference, natural-dialogue outcome or formal device certificate.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path);a=p.parse_args()
    data=json.dumps(score_directory(a.root),indent=2)+'\n'
    if a.output:a.output.write_text(data)
    else:print(data,end='')
