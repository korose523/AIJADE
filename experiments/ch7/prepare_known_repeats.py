#!/usr/bin/env python3
"""Prepare the existing Chapter 7 known-case worklist and check future delivery bytes offline."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from audit_retrieval_led import raw, sha
from compare_known_repeats import compare
from finite_construction_binding import decode, exact_int, full_commit, full_sha, qualified_backend, typed_equal
from finite_inputs import ROOT, qualify, require


SCOPE_PATH = 'experiments/ch7/heldout-scope-correction-20261117.json'
SCOPE_SHA256 = '8cbaeac5da50948a1d729c5a8236de31e17f6e3a3a36485f93124dd840546b2a'
ARCHIVED_INPUTS = ROOT / 'experiments/ch7/relocated-runtime-2026-11-16/qualification-inputs'
INPUT_NAMES = ('runtime-manifest.json', 'scoring-manifest.json', 'selection.json')
ARCHIVED_INPUT_HASHES = dict(zip(INPUT_NAMES, (
    '03cd928f12dda15abf08a01d13d564ebe1fba3e21cd5686a5b628dd8ed4b4d67',
    'f4b800a37063b2689cbbfb9fcc75e4747cd37ff36f742e9a571b67b1b6cfab1d',
    'f252859a56df3a736bf6001f571c2f1c6dfbe6ea3398549125213ba8127de98d',
)))
FLOW_METHOD = 'Run_finite_manifest_dataflow'
IDENTITY_SCHEMA = 'aijade.ch7.known-repeats-expected-identity.v1'


def known_inputs(commit, scratch):
    """Use the existing derivation in a disposable directory without a runtime or case generation."""
    with TemporaryDirectory(prefix='known-input-derivation-', dir=scratch) as temp:
        output = Path(temp)
        qualify(ROOT, full_commit(commit), output)
        inputs = {name: (output / name).read_bytes() for name in INPUT_NAMES}
    selection = decode(inputs['selection.json'])
    for relative, digest in selection['sources'].items():
        path = (ROOT / relative).resolve()
        require(path.is_relative_to(ROOT) and sha(path.read_bytes()) == digest,
                'archived program/test source changed: ' + relative)
    return inputs


def slots(runtime):
    order = [(item['input']['caseId'], arm) for item in runtime['cases']
             for arm in item['input']['conditions']]
    require(len(order) == len(set(order)) == 20, 'known case/condition population')
    return order


def worklist(scratch):
    scope_body = (ROOT / SCOPE_PATH).read_bytes()
    require(sha(scope_body) == SCOPE_SHA256, 'the November 17 decision record changed')
    scope = decode(scope_body)
    archived = {name: (ARCHIVED_INPUTS / name).read_bytes() for name in INPUT_NAMES}
    require({name: sha(body) for name, body in archived.items()} == ARCHIVED_INPUT_HASHES,
            'historical known input bytes changed')
    runtime = decode(archived['runtime-manifest.json'])
    require(runtime['purpose'] == 'qualification_only', 'historical input scope changed')
    require(known_inputs(runtime['constructionFreezeCommit'], scratch) == archived,
            'historical known inputs do not exactly rederive')
    order = [dict(slot=i, caseId=case, condition=arm) for i, (case, arm) in enumerate(slots(runtime), 1)]
    return dict(schema='aijade.ch7.mac-known-repeats-worklist.v1',
                status='OFFLINE_WORKLIST_PREPARED', decisionRecordSha256=SCOPE_SHA256,
                supervisorQualificationReply=scope['qualificationPlanReply'],
                criteria=['casewise matching under the same condition', 'complete observations without timeout or runtime error'],
                archivedKnownInputHashes=ARCHIVED_INPUT_HASHES,
                archivedInputCommit=runtime['constructionFreezeCommit'],
                boundProgramSources=decode(archived['selection.json'])['sources'],
                repeats=[dict(repeat=i, initialState='isolated', slots=order, status='NOT_RUN') for i in (1, 2)],
                conditionSlotsPerRepeat=len(order), plannedConditionSlots=2 * len(order),
                executionPlanFreeze='PENDING_REPLY', approvedDriverBinding='PENDING_REPLY',
                qualificationDetermined=False, table7_3=scope['table7_3'],
                newRunsStarted=0, newHeldoutCases=0, newSeedsDerived=0)


def closing_evidence(root, expected_inputs, expected_identity):
    """Bind one block's output to its inputs, original handoff bytes and terminal witnesses."""
    hashes = {}

    def read(name):
        body = raw(root, name)
        hashes[name] = sha(body)
        return body

    for name, expected in expected_inputs.items():
        require(read(name) == expected, 'known input differs from declared derivation: ' + name)
    identity = decode(read('input-identities.json'))
    commit = expected_identity['implementationCommit']
    require(identity['codeCommit'] == identity['constructionFreezeCommit'] == commit,
            'block implementation differs from the nominated implementation')
    require(identity['executionPlanSha256'] == full_sha(expected_identity['executionPlanSha256']),
            'block execution plan differs from the nominated plan')
    require(typed_equal(qualified_backend(identity), qualified_backend(expected_identity['backend'], closed=True)),
            'block backend differs from the nominated backend')

    runtime = decode(expected_inputs['runtime-manifest.json'])
    order = slots(runtime)
    cases = decode(read('cases.json'))
    prepared = decode(read('prepared.json'))
    for rows in (cases, prepared):
        require([(row['caseId'], row['condition']) for row in rows] == order,
                'case and condition order differs from the known manifest')
    require(all(type(row['gatewayAttempts']) is int and row['gatewayAttempts'] == 0 for row in cases),
            'unexpected or missing model request count')
    journal = [decode(line) for line in read('journal.jsonl').splitlines()]
    require(all(type(row['sequence']) is int and row['sequence'] == i for i, row in enumerate(journal, 1)),
            'journal event sequence is incomplete or reordered')
    starts = [row['detail'] for row in journal if (row['caseId'], row['phase']) == ('batch', 'batch.begin')]
    require(len(starts) == 1 and typed_equal(starts[0], runtime), 'journal began with different inputs')
    terminals = [(row['caseId'], row['detail']) for row in journal if row['phase'] == 'case.complete']
    require(typed_equal(terminals, [(f'{case}/{arm}', row) for (case, arm), row in zip(order, cases)]),
            'case rows differ from the original completion events')

    request = decode(read('renderer-request.json'))
    require(request['preparedSha256'] == hashes['prepared.json'], 'renderer did not receive the captured prepared bytes')
    state = read('client/aijade-render-state.jsonl').splitlines(keepends=True)
    require(len(state) >= 3, 'renderer stream has no state records')
    head, end = decode(state[0]), decode(state[-1])
    require(head['record'] == 'header' and end['record'] == 'end' and end['complete'] is True,
            'renderer stream lacks a complete closing record')
    exact_int(end['lines'], len(state) - 1, 'renderer line count')
    require(end['sha256'] == sha(b''.join(state[:-1])), 'renderer stream has an invalid closing seal')
    require(head['pmx_sha256'] == identity['modelSha256'] and head['presented_frame_observed'] is False,
            'renderer asset or observation scope differs')
    ready = decode(read('renderer-ready.json'))
    registry = [decode(line) for line in read('registry.jsonl').splitlines()]
    require(len(registry) == 11, 'registry must contain one header and ten intent records')
    require(head['session_id'] == request['session'] == registry[0]['session_id']
            and head['renderer_context_id'] == ready['context'] == registry[0]['renderer_context_id'],
            'renderer session or context differs across handoff files')
    intents = {}
    for row in cases:
        case, intent = row['caseId'], row['prepared']['intentId']
        require(type(intent) is str and intent and intents.setdefault(case, intent) == intent,
                'matched conditions do not share their actual intent')
    require(len(set(intents.values())) == 10 and
            [item['intent_id'] for item in registry[1:]] == list(intents.values()),
            'registered intents differ from ordered case observations')
    closed = decode(read('renderer-closed.json'))
    exact_int(closed['exitCode'], 0, 'renderer closing exit code')
    require(closed['stateSha256'] == decode(read('manifest.json'))['file_sha256']
            == hashes['client/aijade-render-state.jsonl'], 'renderer close and manifest hashes differ')

    xml = ElementTree.fromstring(read('flow.xml'))
    assemblies = xml.findall('assembly')
    tests = xml.findall('./assembly/collection/test')
    require(xml.tag == 'assemblies' and len(assemblies) == len(tests) == 1,
            'expected one captured xUnit flow result')
    require(tests[0].get('method') == FLOW_METHOD and tests[0].get('result') == 'Pass'
            and all(assemblies[0].get(field) == value for field, value in
                    [('total', '1'), ('passed', '1'), ('failed', '0'), ('errors', '0'), ('skipped', '0'), ('not-run', '0')]),
            'finite flow result missing or not passed')
    receipt = decode(read('receipt.json'))
    pids = {receipt['phases'][name]['pid'] for name in ('flow', 'renderer')}
    processes = decode(read('process-cleanup.json'))
    require(len(processes) == len(pids) == 2 and {item['pid'] for item in processes} == pids
            and all(type(item['exitCode']) is int and item['exitCode'] == 0 and item['errors'] == [] for item in processes),
            'flow or renderer process closure was not observed')
    database_ids = {row['databaseBefore']['database'] for row in cases}
    leases = [decode(line) for line in read('database-leases.jsonl').splitlines()]
    databases = decode(read('database-cleanup.json'))
    require(len(database_ids) == len(leases) == len(databases) == 20
            and {row['database'] for row in leases} == {row['database'] for row in databases} == database_ids
            and all(type(row['remaining']) is int and row['remaining'] == 0 and row['error'] is None for row in databases),
            'case database leases or final disposals are incomplete')
    return hashes


def check_delivery(first, second, binding_body, scratch):
    match = compare(first, second)
    report = dict(schema='aijade.ch7.known-repeats-offline-delivery.v1',
                  status='OFFLINE_DELIVERY_BLOCKED', comparison=match,
                  expectedIdentitySha256=sha(binding_body), deliveryChecks=[],
                  qualificationDetermined=False, table7_3='NOT_RUN',
                  newRunsStarted=0, newHeldoutCases=0, newSeedsDerived=0)
    if match['comparableRows'] != 20:
        return report
    try:
        binding = decode(binding_body)
        require(set(binding) == {'schema', 'implementationCommit', 'executionPlanSha256', 'backend'}
                and binding['schema'] == IDENTITY_SCHEMA, 'invalid independent expected-identity schema')
        known = known_inputs(binding['implementationCommit'], scratch)
        for root, compared in zip((first, second), match['attempts']):
            files = closing_evidence(root, known, binding)
            require(all(files[name] == digest for name, digest in compared['files'].items() if name in files),
                    'compared evidence changed during the closure check')
            report['deliveryChecks'].append(dict(block=str(root), files=files))
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, ElementTree.ParseError) as error:
        report['deliveryBlocker'] = str(error)
        return report
    if match['differences']:
        report['status'] = 'OFFLINE_DELIVERY_MATCHED_INPUTS_BUT_DIFFERENT_DECISIONS'
    else:
        report['status'] = 'OFFLINE_DELIVERY_EVIDENCE_READY_FOR_REVIEW'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True, help='existing project-local temporary directory')
    sub = parser.add_subparsers(dest='mode', required=True)
    sub.add_parser('worklist')
    delivery = sub.add_parser('check-delivery')
    delivery.add_argument('first', type=Path)
    delivery.add_argument('second', type=Path)
    delivery.add_argument('--expected-identity', type=Path, required=True)
    args = parser.parse_args()
    scratch = args.scratch.resolve()
    if not scratch.is_dir() or not scratch.is_relative_to(ROOT.parent):
        parser.error('--scratch must be an existing AIJADE-local directory')
    if args.mode == 'check-delivery':
        if any(not path.resolve().is_relative_to(ROOT.parent)
               for path in (args.first, args.second, args.expected_identity)):
            parser.error('delivery and expected-identity paths must be inside AIJADE')
        if not args.expected_identity.is_file():
            parser.error('--expected-identity must be an existing file')
    result = (worklist(scratch) if args.mode == 'worklist' else
              check_delivery(args.first, args.second, args.expected_identity.read_bytes(), scratch))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return {'OFFLINE_DELIVERY_BLOCKED': 2,
            'OFFLINE_DELIVERY_MATCHED_INPUTS_BUT_DIFFERENT_DECISIONS': 1}.get(result['status'], 0)


if __name__ == '__main__':
    raise SystemExit(main())
