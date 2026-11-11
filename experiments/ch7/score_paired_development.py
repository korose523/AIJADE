#!/usr/bin/env python3
"""Frozen-window descriptive scoring. No qualification flag supplies an outcome."""
import argparse
import json
from pathlib import Path

from audit_retrieval_suffix import require
from audit_retrieval_led import load, raw, sha

CONTRACT_SHA256 = 'edaadb5fb69a2e00ca202136273546a79aeece346dfd4caa6096579ccb7f0681'
LAYOUT_SHA256 = '6445f4ec57df37f5081be5142236b54193e4ef5694daa38e0d5a0219fb3b0f1b'
IDS = ['H', 'I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I7', 'I8', 'S1']


def score(rows, contract):
    require(len(rows) == 20 and {(r['caseId'], r['condition']) for r in rows} == {(i, c) for i in IDS for c in ['C1', 'C2']}, 'missing/duplicate case or arm')
    rules = contract['cases']
    require([r['caseId'] for r in rules] == IDS, 'scoring case order')
    require(sum(r['promotionOpportunity'] for r in rules) == contract['scheduledInvalidPromotionOpportunitiesPerCondition'] == 7, 'promotion opportunity denominator')
    require(sum(r['reuseOpportunity'] for r in rules) == contract['scheduledInvalidReuseOpportunitiesPerCondition'] == 8, 'reuse opportunity denominator')
    arms = {}
    for condition in ['C1', 'C2']:
        by_case = []
        for rule in rules:
            row = next(r for r in rows if r['caseId'] == rule['caseId'] and r['condition'] == condition)
            final = row['final']
            specs = final['specs']; reports = final['reports']
            require(len(final['specRows']) == specs and len(final['reportRows']) == reports, 'persisted count/row mismatch')
            reads = [row['round2']] + ([row['duplicateReuse']] if row['duplicateReuse'] is not None else [])
            executed = sum(r['executed'] is True for r in reads)
            require(executed == final['reuseCount'], 'reuse count/raw execution mismatch')
            calls = row['promotionAttempts']
            at_promotion_window = [p for p in calls if p['invocation'] == (2 if rule['window'] == 'duplicate_invocation_2' else 1)] if rule['promotionOpportunity'] else []
            at_reuse_window = row['duplicateReuse'] if rule['window'] == 'duplicate_invocation_2' else row['round2']
            authority = final['authority']
            state = authority[0]['state'] if authority else 'absent'
            # Only persisted rows count. In particular, I8's transient service
            # Ok=true before a caller-owned rollback contributes no promotion.
            invalid_promotion = int(rule['promotionOpportunity'] == 1 and specs > rule['allowedSpecs'])
            invalid_reuse = int(rule['reuseOpportunity'] == 1 and executed > rule['allowedReuses'])
            item = dict(caseId=rule['caseId'],window=rule['window'],category=rule['class'],
                        scheduledInvalidPromotionOpportunities=rule['promotionOpportunity'], invalidDurablePromotions=invalid_promotion,
                        scheduledInvalidReuseOpportunities=rule['reuseOpportunity'], integrityInvalidReuse=invalid_reuse,
                        persistedSpecs=specs,persistedReports=reports,authorityState=state,
                        successfulServiceReturns=sum(p.get('serviceResult',{}).get('ok') is True for p in calls),
                        promotionServiceEntries=len(calls),serviceEntriesAtInvalidPromotionWindow=len(at_promotion_window),
                        actualRound2Queries=len(reads),retrievedRound2Queries=sum(r['retrieved'] is True for r in reads),
                        queriedAtInvalidReuseWindow=int(rule['reuseOpportunity'] == 1 and at_reuse_window['status'] == 200),
                        retrievedAtInvalidReuseWindow=int(rule['reuseOpportunity'] == 1 and at_reuse_window['retrieved'] is True),
                        round2SandboxExecutions=executed,outcomeMemories=final['outcomeMemoryCount'],
                        deliveryStatus=row['delivery']['status'],databaseError=row['databaseErrorCode'])
            if rule['class'] == 'normal':
                item['normalOutcome'] = 'accepted' if specs == 1 and state == 'verified' and final['outcomeMemoryCount'] == 1 and executed == 1 else 'unknown' if state == 'unknown' else 'refused_or_incomplete'
            if rule['class'] == 'semantic_control':
                item['semanticMismatchAssociatedPromotions'] = specs
                item['associatedSkillSandboxReuse'] = executed
                item['round2SemanticActCorrectness'] = 'NOT_MEASURED'
            if rule['caseId'] == 'I6':
                item['storedScopeClaimsPixels'] = any('pixels_observed' in a['scope'] for a in authority)
            by_case.append(item)
        fields = ['scheduledInvalidPromotionOpportunities','invalidDurablePromotions','scheduledInvalidReuseOpportunities','integrityInvalidReuse',
                  'persistedSpecs','persistedReports','successfulServiceReturns','promotionServiceEntries','serviceEntriesAtInvalidPromotionWindow',
                  'actualRound2Queries','retrievedRound2Queries','queriedAtInvalidReuseWindow','retrievedAtInvalidReuseWindow','round2SandboxExecutions','outcomeMemories']
        arms[condition] = {k:sum(r[k] for r in by_case) for k in fields}
        arms[condition]['normalOutcome'] = next(r['normalOutcome'] for r in by_case if r['category'] == 'normal')
        arms[condition]['byCase'] = by_case
    return dict(schema='aijade.ch7.paired-development-score.v1',developmentPairs=10,conditionRows=20,heldOutCases=0,
                arms=arms,differencesC2MinusC1={k:arms['C2'][k]-arms['C1'][k] for k in ['invalidDurablePromotions','integrityInvalidReuse']},
                round2SemanticActCorrectness='NOT_MEASURED',
                interpretation='Finite known-case contract counts; no independent population sample, statistical superiority, causal effect estimate, semantic round-2 action or formal hardware qualification.')


def score_directory(root):
    require(sha(raw(root,'scoring-contract.json')) == CONTRACT_SHA256,'frozen scoring contract changed')
    require(sha(raw(root,'layout.json')) == LAYOUT_SHA256,'frozen paired layout changed')
    return score(load(root,'cases.json'),load(root,'scoring-contract.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=score_directory(args.root)
    text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output: args.output.write_text(text)
    else: print(text,end='')
