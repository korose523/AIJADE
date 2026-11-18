#!/usr/bin/env python3
"""Offline comparison of two completed runs of the ten already known cases."""

import argparse
from datetime import datetime
import json
from pathlib import Path

from audit_retrieval_led import raw, sha
from comparison_manifest import CONDITIONS, require
from finite_construction_binding import decode, exact_int, full_commit, full_sha, typed_equal
from finite_score import score_rows


SOURCE = Path(__file__).resolve().parent
KNOWN = {
    'live-manifest-known-input-v1.json':
        'db660d8d3a8856e0f5fd232b131796b1c242c1e4329ea1eaa0a6b216ad488716',
    'manifest-preparation-2026-11-12/comparison-manifest.json':
        '3516f6074776c5d310f9e2df60a958b997ce8ecf44a3627ffdb8d3b7ff65d0ce',
}
POLICIES = {condition['id']: condition['policy'] for condition in CONDITIONS}
PURPOSE = 'qualification_only'
COMPLETE = 'COMPLETE_FINITE_BLOCK_OBSERVATIONS'
EMPTY_FIELDS = ('inFlightCaseIds', 'unknownCaseIds', 'unattemptedCaseIds',
                'dispositionErrors', 'logCloseErrors')


def known(name):
    body = (SOURCE / name).read_bytes()
    require(sha(body) == KNOWN[name], 'known-case source changed: ' + name)
    return decode(body)


def instant(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.tzinfo is not None, 'missing timestamp zone')
    return stamp


def reuse_decision(observation):
    if observation is None:
        return None
    require(type(observation.get('reason')) is str and observation['reason'],
            'missing reuse reason')
    return {field: observation[field] for field in ('status', 'retrieved', 'executed', 'reason')}


def inspect(root, known_inputs, known_rules):
    report = {'path': str(root), 'files': {}, 'receiptStatus': None,
              'completionBlockers': [], 'evidenceBlockers': []}

    def read(name):
        body = raw(root, name)
        report['files'][name] = sha(body)
        return decode(body)

    try:
        receipt = read('receipt.json')
        report['receiptStatus'] = receipt.get('status')
        report['receiptReason'] = receipt.get('reason')
        report['completedCases'] = receipt.get('completedCases')
        blockers = report['completionBlockers']
        if receipt.get('schema') != 'aijade.ch7.finite-block-receipt.v1':
            blockers.append('unsupported finite-block receipt schema')
        if receipt.get('status') != COMPLETE:
            blockers.append('terminal status is not complete')
        if 'reason' not in receipt or receipt['reason'] is not None:
            blockers.append('missing or adverse terminal reason')
        for field in EMPTY_FIELDS:
            if receipt.get(field) != []:
                blockers.append('missing or nonempty: ' + field)
        for count, expected in [('plannedPairs', 10), ('plannedCases', 20), ('completedCases', 20)]:
            if type(receipt.get(count)) is not int or receipt[count] != expected:
                blockers.append('incorrect terminal count: ' + count)
        for phase in ('flow', 'renderer'):
            exit_code = receipt.get('phases', {}).get(phase, {}).get('exitCode')
            if type(exit_code) is not int or exit_code != 0:
                blockers.append('missing or nonzero ' + phase + ' exit code')
        if blockers:
            return report, None
        finished = instant(receipt['finishedAt'])
        for phase in ('flow', 'renderer'):
            record = receipt['phases'][phase]
            require(instant(record['startedAt']) <= instant(record['endedAt']) <= finished,
                    'incomplete phase chronology: ' + phase)
        require(receipt['purpose'] == PURPOSE and receipt['conditionsMeasured'] == list(POLICIES),
                'qualification scope or conditions changed')
        exact_int(receipt['heldOutCases'], 0, 'held-out cases')
        exact_int(receipt['modelRequests'], 0, 'model requests')
        require(receipt['formalHardwareQualification'] is False, 'unsupported hardware claim')
        commit = full_commit(receipt['codeCommit'])

        runtime = read('runtime-manifest.json')
        contract = read('scoring-manifest.json')
        read('selection.json')
        identity = read('input-identities.json')
        build = read('frozen-build.json')
        require(runtime['purpose'] == identity['purpose'] == PURPOSE, 'unrecognized input scope')
        require(commit == identity['codeCommit'] == build['commit'], 'receipt differs from source identity')
        require(typed_equal(build['files'], identity['binaries']), 'frozen executable hashes differ')
        exact_int(receipt['blockIndex'], runtime['blockIndex'], 'receipt block index')
        byte_fields = {'runtimeManifestSha256': 'runtime-manifest.json',
                       'scoringManifestSha256': 'scoring-manifest.json',
                       'selectionSha256': 'selection.json', 'buildManifestSha256': 'frozen-build.json'}
        for field, name in byte_fields.items():
            require(identity[field] == report['files'][name], 'unbound exact bytes: ' + name)
        require(contract['runtimeManifestSha256'] == identity['runtimeManifestSha256'],
                'scoring and runtime binding differs')
        require(runtime['selectionSha256'] == identity['selectionSha256'], 'selection binding differs')
        require(runtime['constructionFreezeCommit'] == identity['constructionFreezeCommit'],
                'construction identity differs')
        require(typed_equal([case['input'] for case in runtime['cases']], known_inputs),
                'the locked ten known case inputs are required')
        rules = {rule['caseId']: rule for rule in contract['cases']}
        require(len(rules) == len(contract['cases']) and typed_equal(rules, known_rules),
                'the original rule for each known case is required')
        binding = {field: full_sha(identity[field]) for field in (*byte_fields, 'executionPlanSha256',
                   'modelSha256', 'realGodotSha256')}
        binding['codeCommit'] = commit
        report['binding'] = binding
        request = read('renderer-request.json')
        session = request['session']
        require(type(session) is str and session.strip(), 'missing renderer session')
        report['rendererSession'] = session

        rows = read('cases.json')
        scored = score_rows(rows, runtime, contract)
        raw_by_key = {(row['caseId'], row['condition']): row for row in rows}
        planned = {case['input']['caseId']: case for case in runtime['cases']}
        databases, tokens, decisions = set(), set(), {}
        for arm, score in scored['arms'].items():
            for item in score['byCase']:
                key = (item['caseId'], arm)
                row = raw_by_key[key]
                require(row['batch'] == PURPOSE and row['dataOrigin'] == 'known_scenario_qualification'
                        and row['policyVersion'] == POLICIES[arm], 'unbound observation scope or policy')
                require(typed_equal(row['runtimeInput'], planned[key[0]]), 'row differs from declared input')
                database = row['databaseBefore']
                require(typed_equal(database, row['databaseAfter']), 'incomplete database continuity')
                require(type(database['database']) is str and database['database']
                        and type(database['token']) is str and len(database['token']) == 32,
                        'missing database identity')
                databases.add(database['database'])
                tokens.add(database['token'])
                error = item['databaseError']
                require(error is None or (error == 'P0001' and item['window'] == 'post_promotion_authority_write'),
                        'unexpected database error: ' + '/'.join(key))
                durable = row['beforeDelivery']
                for count, rows_name in (('specs', 'specRows'), ('reports', 'reportRows')):
                    require(type(durable[rows_name]) is list, 'missing pre-delivery durable rows')
                    exact_int(durable[count], len(durable[rows_name]), 'pre-delivery ' + count)
                decisions[key] = dict(
                    item,
                    persistedBeforeDelivery={field: durable[field] for field in ('specs', 'reports')},
                    firstReuse=reuse_decision(row['round2']),
                    duplicateReuse=reuse_decision(row['duplicateReuse']),
                    promotionCalls=[{'invocation': call['invocation'], 'accepted': call['serviceResult']['ok']}
                                    for call in row['promotionAttempts']],
                )
        require(len(decisions) == len(databases) == len(tokens) == 20,
                'each of 20 condition records needs an isolated database identity')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
        report['evidenceBlockers'].append(str(error))
        return report, None
    return report, (decisions, databases, tokens)


def compare(first, second):
    """Compare visible judgment data; no backend acceptance or runtime action."""
    first, second = Path(first).resolve(), Path(second).resolve()
    known_inputs = known('live-manifest-known-input-v1.json')['cases']
    known_rules = {rule['caseId']: rule for rule in
                   known('manifest-preparation-2026-11-12/comparison-manifest.json')['cases']}
    attempts, evidence = zip(*(inspect(path, known_inputs, known_rules) for path in (first, second)))
    blockers = []
    result = dict(schema='aijade.ch7.known-repeat-offline-comparison.v1',
                  status='OFFLINE_REPEAT_PAIR_UNSCORABLE', attempts=list(attempts),
                  pairBlockers=blockers, comparableRows=0, differences=[],
                  qualificationDetermined=False, newRunsStarted=0, newHeldoutCases=0)
    receipt_hashes = [attempt['files'].get('receipt.json') for attempt in attempts]
    if first == second or (receipt_hashes[0] is not None and receipt_hashes[0] == receipt_hashes[1]):
        blockers.append('the same attempt cannot serve as both repeats')
    if any(record is None for record in evidence):
        return result
    a, b = attempts
    for field, value in a['binding'].items():
        if b['binding'][field] != value:
            blockers.append('shared run binding differs: ' + field)
    (a_rows, a_databases, a_tokens), (b_rows, b_databases, b_tokens) = evidence
    if a['rendererSession'] == b['rendererSession']:
        blockers.append('renderer sessions are not distinct')
    if a_databases & b_databases or a_tokens & b_tokens:
        blockers.append('database identities or continuity tokens overlap')
    if blockers:
        return result
    result['comparableRows'] = len(a_rows)
    for case, arm in sorted(a_rows):
        key = (case, arm)
        before, after = a_rows[key], b_rows[key]
        differences = {field: [before.get(field), after.get(field)]
                       for field in sorted(before.keys() | after.keys())
                       if not typed_equal(before.get(field), after.get(field))}
        if differences:
            result['differences'].append(dict(caseId=case, condition=arm, fields=differences))
    result['status'] = 'OFFLINE_REPEAT_MISMATCH' if result['differences'] else 'OFFLINE_REPEAT_MATCH'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path)
    parser.add_argument('second', type=Path)
    args = parser.parse_args()
    result = compare(args.first, args.second)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return {'OFFLINE_REPEAT_MATCH': 0, 'OFFLINE_REPEAT_MISMATCH': 1,
            'OFFLINE_REPEAT_PAIR_UNSCORABLE': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
