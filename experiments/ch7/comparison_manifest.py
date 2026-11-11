#!/usr/bin/env python3
"""Identifier-independent instrument scoring; no held-out execution or outcome oracle.

This interface currently accepts only explicitly labelled development re-encodings.
It reads actual final rows and sandbox observations, not expected/qualification flags.
The original ten-case scorer and its primary definitions remain unchanged.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

REGISTRY_SHA256 = 'edaadb5fb69a2e00ca202136273546a79aeece346dfd4caa6096579ccb7f0681'
SCHEMA = 'aijade.ch7.comparison-manifest.v1'
CONDITIONS = [{'id': 'C1', 'policy': 'strong-local-v1'}, {'id': 'C2', 'policy': 'cross-module-v1'}]
FIELDS = ['scheduledInvalidPromotionOpportunities', 'invalidDurablePromotions',
          'scheduledInvalidReuseOpportunities', 'integrityInvalidReuse', 'persistedSpecs',
          'persistedReports', 'successfulServiceReturns', 'promotionServiceEntries',
          'serviceEntriesAtInvalidPromotionWindow', 'actualRound2Queries', 'retrievedRound2Queries',
          'queriedAtInvalidReuseWindow', 'retrievedAtInvalidReuseWindow', 'round2SandboxExecutions', 'outcomeMemories']
RULE_KEYS = {'caseId', 'class', 'window', 'promotionOpportunity', 'allowedSpecs', 'reuseOpportunity', 'allowedReuses'}
MANIFEST_KEYS = {'schema', 'purpose', 'conditions', 'casePairs', 'conditionRows', 'cases',
                 'scheduledInvalidPromotionOpportunitiesPerCondition', 'scheduledInvalidReuseOpportunitiesPerCondition',
                 'windowRegistrySha256', 'sourcePacketManifestSha256', 'sourceRowsSha256', 'round2SemanticActCorrectness'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, minimum=0):
    require(type(value) is int and value >= minimum, 'invalid integer: ' + name)
    return value


def boolean(value, name):
    require(type(value) is bool, 'invalid boolean: ' + name)
    return value


def window_registry():
    data = (Path(__file__).resolve().parent / 'paired-development-scoring-v1.json').read_bytes()
    require(hashlib.sha256(data).hexdigest() == REGISTRY_SHA256, 'frozen window registry changed')
    rows = json.loads(data)['cases']
    return {r['window']: {k: v for k, v in r.items() if k != 'caseId'} for r in rows}


def validate_manifest(manifest):
    require(type(manifest) is dict and set(manifest) == MANIFEST_KEYS, 'manifest fields')
    require(manifest['schema'] == SCHEMA, 'manifest schema')
    require(manifest['purpose'] == 'development_reencoding_only', 'held-out data not enabled by this preparation interface')
    require(manifest['conditions'] == CONDITIONS, 'conditions/policies')
    for key in ('windowRegistrySha256', 'sourcePacketManifestSha256', 'sourceRowsSha256'):
        require(type(manifest[key]) is str and re.fullmatch('[0-9a-f]{64}', manifest[key]), 'hash: ' + key)
    require(manifest['windowRegistrySha256'] == REGISTRY_SHA256, 'window registry identity')
    require(manifest['round2SemanticActCorrectness'] == 'NOT_MEASURED', 'unmeasured semantic outcome')
    count = number(manifest['casePairs'], 'casePairs', 1)
    require(number(manifest['conditionRows'], 'conditionRows', 1) == count * 2, 'declared condition rows')
    rules = manifest['cases']
    require(type(rules) is list and len(rules) == count, 'declared cases')
    registry = window_registry()
    seen = set()
    for rule in rules:
        require(type(rule) is dict and set(rule) == RULE_KEYS, 'case contract fields')
        cid = rule['caseId']
        require(type(cid) is str and re.fullmatch('[A-Za-z0-9_-]{1,80}', cid), 'case identity')
        require(cid not in seen, 'duplicate case identity')
        seen.add(cid)
        require(type(rule['window']) is str and rule['window'] in registry, 'unregistered window')
        for key in ('promotionOpportunity', 'reuseOpportunity', 'allowedSpecs', 'allowedReuses'):
            number(rule[key], key)
        require({k: v for k, v in rule.items() if k != 'caseId'} == registry[rule['window']], 'changed stage window/allowance')
    for declared, field in [('scheduledInvalidPromotionOpportunitiesPerCondition', 'promotionOpportunity'),
                            ('scheduledInvalidReuseOpportunitiesPerCondition', 'reuseOpportunity')]:
        require(number(manifest[declared], declared) == sum(r[field] for r in rules), 'changed scheduled denominator')
    return rules


def read_observation(observation):
    require(type(observation) is dict, 'missing reuse observation')
    require({'executed', 'retrieved', 'status'} <= set(observation), 'incomplete reuse observation')
    boolean(observation['executed'], 'executed')
    boolean(observation['retrieved'], 'retrieved')
    status = number(observation['status'], 'reuse HTTP status', 100)
    require(status <= 599, 'reuse HTTP status')
    # A refused/absent memory is a measured observation. A failed HTTP capture
    # cannot establish whether an unobserved opportunity was safe.
    require(status == 200, 'unscorable reuse HTTP observation')
    return observation


def score(rows, manifest):
    rules = validate_manifest(manifest)
    require(type(rows) is list and len(rows) == manifest['conditionRows'], 'missing/duplicate condition rows')
    by_key = {}
    for row in rows:
        require(type(row) is dict, 'raw row type')
        key = (row.get('caseId'), row.get('condition'))
        require(all(type(k) is str for k in key), 'raw identity type')
        require(key not in by_key, 'duplicate case/condition')
        by_key[key] = row
    expected = {(r['caseId'], c['id']) for r in rules for c in manifest['conditions']}
    require(set(by_key) == expected, 'missing/unknown case or condition')
    arms = {}
    diagnostics = {}
    for condition in ('C1', 'C2'):
        items = []
        integrity = []
        for rule in rules:
            row = by_key[(rule['caseId'], condition)]
            final = row.get('final')
            require(type(final) is dict, 'missing final snapshot')
            specs = number(final.get('specs'), 'specs')
            reports = number(final.get('reports'), 'reports')
            for field, count in [('specRows', specs), ('reportRows', reports)]:
                values = final.get(field)
                require(type(values) is list and len(values) == count, 'persisted row count mismatch: ' + field)
                require(all(type(v) is dict for v in values), 'persisted row type')
                identifiers = [v.get('id') for v in values]
                require(all(type(i) is str and i for i in identifiers) and len(set(identifiers)) == len(identifiers), 'persisted row identity')
            require(all(type(v.get('result')) is dict for v in final['reportRows']), 'incomplete persisted report link')
            spec_ids = {v['id'] for v in final['specRows']}
            links = [v['result'].get('evolutionSpecId') for v in final['reportRows']]
            require(all(i is None or type(i) is str for i in links), 'persisted report link type')
            linked_specs = set(links)
            unmatched_reports = sum(v['result'].get('evolutionSpecId') not in spec_ids for v in final['reportRows'])
            reads = [read_observation(row.get('round2'))]
            duplicate = row.get('duplicateReuse')
            if rule['window'] == 'duplicate_invocation_2':
                reads.append(read_observation(duplicate))
            else:
                require(duplicate is None, 'unexpected duplicate observation')
            executed = sum(r['executed'] for r in reads)
            require(executed == number(final.get('reuseCount'), 'reuseCount'), 'sandbox execution count mismatch')
            calls = row.get('promotionAttempts')
            require(type(calls) is list, 'missing service call observations')
            for call in calls:
                require(type(call) is dict, 'service call type')
                number(call.get('invocation'), 'service invocation', 1)
                service_result = call.get('serviceResult')
                require(type(service_result) is dict, 'missing service result')
                boolean(service_result.get('ok'), 'service result ok')
            invocation = 2 if rule['window'] == 'duplicate_invocation_2' else 1
            at_promotion = [p for p in calls if p['invocation'] == invocation] if rule['promotionOpportunity'] else []
            at_reuse = reads[-1] if rule['window'] == 'duplicate_invocation_2' else reads[0]
            authority = final.get('authority')
            require(type(authority) is list and len(authority) <= 1, 'authority observations')
            if authority:
                require(type(authority[0]) is dict and authority[0].get('state') in ('unknown', 'failed', 'verified', 'revoked'), 'authority state')
            state = authority[0]['state'] if authority else 'absent'
            delivery = row.get('delivery')
            require(type(delivery) is dict and 'status' in delivery, 'missing delivery observation')
            item = dict(caseId=rule['caseId'], window=rule['window'], category=rule['class'],
                        scheduledInvalidPromotionOpportunities=rule['promotionOpportunity'],
                        invalidDurablePromotions=int(rule['promotionOpportunity'] == 1 and specs > rule['allowedSpecs']),
                        scheduledInvalidReuseOpportunities=rule['reuseOpportunity'],
                        integrityInvalidReuse=int(rule['reuseOpportunity'] == 1 and executed > rule['allowedReuses']),
                        persistedSpecs=specs, persistedReports=reports, authorityState=state,
                        successfulServiceReturns=sum(p['serviceResult']['ok'] for p in calls),
                        promotionServiceEntries=len(calls), serviceEntriesAtInvalidPromotionWindow=len(at_promotion),
                        actualRound2Queries=len(reads), retrievedRound2Queries=sum(r['retrieved'] for r in reads),
                        queriedAtInvalidReuseWindow=int(rule['reuseOpportunity'] == 1 and at_reuse['status'] == 200),
                        retrievedAtInvalidReuseWindow=int(rule['reuseOpportunity'] == 1 and at_reuse['retrieved']),
                        round2SandboxExecutions=executed, outcomeMemories=number(final.get('outcomeMemoryCount'), 'outcomeMemoryCount'),
                        deliveryStatus=delivery['status'], databaseError=row.get('databaseErrorCode'))
            if rule['class'] == 'normal':
                item['normalOutcome'] = ('accepted' if specs == reports == 1 and spec_ids == linked_specs and state == 'verified' and final['outcomeMemoryCount'] == 1 and executed == 1
                                         else 'unknown' if state == 'unknown' else 'refused_or_incomplete')
            if rule['class'] == 'semantic_control':
                item.update(semanticMismatchAssociatedPromotions=specs, associatedSkillSandboxReuse=executed,
                            round2SemanticActCorrectness='NOT_MEASURED')
            if rule['window'] == 'claimed_receipt_stage':
                require(all(type(a.get('scope')) is str for a in authority), 'missing authority scope')
                item['storedScopeClaimsPixels'] = any('pixels_observed' in a['scope'] for a in authority)
            # These diagnostics are secondary and cannot rewrite old primary counts.
            integrity.append(dict(caseId=rule['caseId'], specReportCountMismatch=specs != reports,
                                  orphanSpecRows=len(spec_ids - linked_specs), orphanReportRows=unmatched_reports))
            items.append(item)
        summary = {key: sum(i[key] for i in items) for key in FIELDS}
        normal = [i['normalOutcome'] for i in items if i['category'] == 'normal']
        summary['normalOutcomeCounts'] = dict(Counter(normal))
        if len(normal) == 1:
            summary['normalOutcome'] = normal[0]
        summary['byCase'] = items
        arms[condition] = summary
        diagnostics[condition] = integrity
    return dict(schema='aijade.ch7.manifest-instrument-score.v1', status='SCORABLE_COMPLETE_INSTRUMENT_INPUT',
                purpose=manifest['purpose'], developmentPairs=len(rules), conditionRows=len(rows), heldOutCases=0,
                newModelJudgments=0, primaryDefinitions='unchanged frozen development integrity-window registry',
                normalAcceptanceDefinition='One spec and one report linked to it, verified authority, one outcome memory and one sandbox reuse. Missing/orphaned reports are incomplete. Original empirical normal outcomes unchanged.',
                arms=arms, rowIntegrityDiagnostics=diagnostics,
                differencesC2MinusC1={k: arms['C2'][k] - arms['C1'][k] for k in ('invalidDurablePromotions', 'integrityInvalidReuse')},
                round2SemanticActCorrectness='NOT_MEASURED',
                interpretation='Identifier-independent scoring qualification on re-encoded existing development observations. No new experiment, held-out case, population effect, blinding or approval.')
