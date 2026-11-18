#!/usr/bin/env python3
"""Exercise offline Chapter 7 preparation and delivery integrity on labeled controls."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from audit_retrieval_led import raw, sha
from finite_construction_binding import BACKEND_FIELDS
from prepare_known_repeats import ARCHIVED_INPUTS, IDENTITY_SCHEMA, FLOW_METHOD, check_delivery, slots, worklist
from test_compare_known_repeats import ARCHIVE, derived_fixture, encode, load, update


def packet(index):
    """Add synthetic identity and closure to observations copied from the old archive."""
    data = derived_fixture(index)
    runtime = json.loads(data['runtime-manifest.json'])
    commit = runtime['constructionFreezeCommit']
    backend_details = {
        'modelSha256': '5' * 64, 'realGodotSha256': '4' * 64,
        'godotWrapperSha256': '6' * 64, 'sandboxProfileSha256': '7' * 64,
        'benchSha256': '8' * 64, 'earlierSourceFreezeSha256': '9' * 64,
        'rendererSources': {'project.godot': 'a' * 64},
        'preparedRenderer': {'status': 'PREBUILT_NO_RUNTIME_REBUILD', 'files': {'renderer.dll': 'b' * 64}},
        'databaseContainer': 'synthetic-no-database', 'explicitDockerPath': '/synthetic/non-executable',
    }
    update(data, 'receipt.json', lambda value: value.update(codeCommit=commit))
    update(data, 'frozen-build.json', lambda value: value.update(commit=commit))
    update(data, 'input-identities.json', lambda value: value.update(codeCommit=commit, **backend_details,
           buildManifestSha256=sha(data['frozen-build.json'])))
    identity = json.loads(data['input-identities.json'])
    binding = {'schema': IDENTITY_SCHEMA, 'implementationCommit': commit,
               'executionPlanSha256': identity['executionPlanSha256'],
               'backend': {key: identity[key] for key in BACKEND_FIELDS}}
    receipt = json.loads(data['receipt.json'])
    for n, name in enumerate(('flow', 'renderer'), 1):
        receipt['phases'][name]['pid'] = index * 100 + n
    data['receipt.json'] = encode(receipt)

    historical = ARCHIVE / 'development-02'
    data['prepared.json'] = raw(historical, 'prepared.json')
    session, context = f'synthetic-session-{index}', f'synthetic-context-{index}'
    data['renderer-request.json'] = encode({'session': session, 'preparedSha256': sha(data['prepared.json'])})
    data['renderer-ready.json'] = encode({'context': context})
    state = raw(historical, 'client/aijade-render-state.jsonl').splitlines(keepends=True)
    head = json.loads(state[0])
    head.update(session_id=session, renderer_context_id=context, pmx_sha256=identity['modelSha256'])
    prefix = json.dumps(head).encode() + b'\n' + b''.join(state[1:-1])
    state[-1] = json.dumps({'record': 'end', 'complete': True, 'lines': len(state) - 1,
                           'sha256': sha(prefix)}).encode() + b'\n'
    data['client/aijade-render-state.jsonl'] = prefix + state[-1]
    data['manifest.json'] = encode({'file_sha256': sha(data['client/aijade-render-state.jsonl'])})
    data['renderer-closed.json'] = encode({'exitCode': 0, 'stateSha256': sha(data['client/aijade-render-state.jsonl'])})
    registry = [json.loads(line) for line in raw(historical, 'registry.jsonl').splitlines()]
    registry[0].update(session_id=session, renderer_context_id=context)
    data['registry.jsonl'] = b''.join(json.dumps(row).encode() + b'\n' for row in registry)
    flow = ElementTree.fromstring(raw(historical, 'flow.xml'))
    flow.find('./assembly/collection/test').set('method', FLOW_METHOD)
    data['flow.xml'] = ElementTree.tostring(flow)
    data['process-cleanup.json'] = encode([
        {'pid': phase['pid'], 'exitCode': 0, 'errors': []} for phase in receipt['phases'].values()])
    rows = json.loads(data['cases.json'])
    events = [{'caseId': 'batch', 'phase': 'batch.begin', 'detail': runtime}]
    for row in rows:
        events.append({'caseId': f"{row['caseId']}/{row['condition']}", 'phase': 'case.complete', 'detail': row})
    data['journal.jsonl'] = b''.join(json.dumps(dict(event, sequence=i), ensure_ascii=False).encode() + b'\n'
                                  for i, event in enumerate(events, 1))
    leases = [row['databaseBefore'] for row in rows]
    data['database-leases.jsonl'] = b''.join(json.dumps(lease).encode() + b'\n' for lease in leases)
    data['database-cleanup.json'] = encode([{'database': lease['database'], 'remaining': 0, 'error': None}
                                           for lease in leases])
    return data, binding


def save_packet(path, blobs):
    for name, body in blobs.items():
        output = path / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)


def verify(scratch):
    plan = worklist(scratch)
    prior = load(ARCHIVED_INPUTS / 'runtime-manifest.json')
    assert plan['conditionSlotsPerRepeat'] == 20 and plan['plannedConditionSlots'] == 40
    for attempt in plan['repeats']:
        assert [(row['caseId'], row['condition']) for row in attempt['slots']] == slots(prior)
        assert attempt['status'] == 'NOT_RUN'
    controls = []
    blocked = 'OFFLINE_DELIVERY_BLOCKED'
    ready = 'OFFLINE_DELIVERY_EVIDENCE_READY_FOR_REVIEW'
    old = check_delivery(ARCHIVE / 'development-01', ARCHIVE / 'development-02', b'{}', scratch)
    assert old['status'] == blocked and old['comparison']['comparableRows'] == 0
    controls.append({'case': 'historical stopped/complete archive stays unscorable', 'status': old['status']})

    with TemporaryDirectory(prefix='known-delivery-controls-', dir=scratch) as folder:
        first, second = Path(folder) / 'first', Path(folder) / 'second'
        first_blobs, binding = packet(1)
        base, second_binding = packet(2)
        assert binding == second_binding
        save_packet(first, first_blobs)

        def test(name, expected, change, *, identity=binding, detail=None):
            blobs = dict(base)
            change(blobs)
            save_packet(second, blobs)
            result = check_delivery(first, second, encode(identity), scratch)
            assert result['status'] == expected, (name, result.get('deliveryBlocker'))
            assert result['qualificationDetermined'] is False and result['newHeldoutCases'] == 0
            if detail is not None:
                assert detail in result['deliveryBlocker'], (name, result['deliveryBlocker'])
            controls.append(dict(case=name, status=result['status'], blocker=result.get('deliveryBlocker')))

        test('two synthetic derived packages with complete bindings', ready, lambda _: None)
        test('same observations with a differently nominated plan', blocked, lambda _: None,
             identity=dict(binding, executionPlanSha256='e' * 64), detail='nominated plan')
        test('same observations with a differently nominated backend', blocked, lambda _: None,
             identity=dict(binding, backend=dict(binding['backend'], godotWrapperSha256='e' * 64)),
             detail='nominated backend')
        test('terminal case events differ from summary', blocked, lambda data: data.update(
            {'journal.jsonl': data['journal.jsonl'].splitlines(keepends=True)[0]}), detail='completion events')
        test('prepared bytes differ from request', blocked, lambda data: data.update(
            {'prepared.json': data['prepared.json'] + b' '}), detail='prepared bytes')
        test('renderer stream hash differs from bound manifest', blocked,
             lambda data: update(data, 'manifest.json', lambda obj: obj.update(file_sha256='f' * 64)), detail='manifest hashes')
        test('registered intent replaced independently of case records', blocked,
             lambda data: data.update({'registry.jsonl': data['registry.jsonl'].replace(
                 b'"intent_id": "', b'"intent_id": "different-', 1)}), detail='registered intents')
        test('xUnit result cannot be replaced with a different method', blocked,
             lambda data: data.update({'flow.xml': data['flow.xml'].replace(FLOW_METHOD.encode(), b'OtherMethod')}),
             detail='flow result')
        test('a database lease remains unresolved', blocked,
             lambda data: update(data, 'database-cleanup.json', lambda rows: rows[0].update(remaining=None)),
             detail='final disposals')
        test('matching cases with an unclosed process are blocked', blocked,
             lambda data: update(data, 'process-cleanup.json', lambda rows: rows[0].update(exitCode=1)),
             detail='process closure')

        def shift_reuse(data):
            rows = json.loads(data['cases.json'])
            index = next(i for i, row in enumerate(rows) if row['duplicateReuse'] is not None)
            row = rows[index]
            row['round2'], row['duplicateReuse'] = row['duplicateReuse'], row['round2']
            data['cases.json'] = encode(rows)
            original = list(map(json.loads, data['journal.jsonl'].splitlines()))
            original[index + 1]['detail'] = row
            data['journal.jsonl'] = b''.join(json.dumps(event).encode() + b'\n' for event in original)

        test('closed evidence with different first and duplicate reuse decisions',
             'OFFLINE_DELIVERY_MATCHED_INPUTS_BUT_DIFFERENT_DECISIONS', shift_reuse)

        def replace_selection(data):
            data['selection.json'] += b' '
            digest = sha(data['selection.json'])
            update(data, 'runtime-manifest.json', lambda value: value.update(selectionSha256=digest))
            runtime_hash = sha(data['runtime-manifest.json'])
            update(data, 'scoring-manifest.json', lambda value: value.update(
                selectionSha256=digest, runtimeManifestSha256=runtime_hash))
            update(data, 'input-identities.json', lambda value: value.update(
                selectionSha256=digest, runtimeManifestSha256=runtime_hash,
                scoringManifestSha256=sha(data['scoring-manifest.json'])))

        replace_selection(first_blobs)
        save_packet(first, first_blobs)
        test('same coherently substituted selection in both repeats', blocked, replace_selection,
             detail='known input differs from declared derivation')

    return dict(status='OFFLINE_KNOWN_REPEAT_PREPARATION_CONTROLS_PASS', controls=controls, controlCount=len(controls),
                exactArchivedInputFiles=len(plan['archivedKnownInputHashes']), knownCases=len(prior['cases']),
                repeatSlots=plan['plannedConditionSlots'], qualificationDetermined=False,
                newRunsStarted=0, newHeldoutCases=0, newSeedsDerived=0)


if __name__ == '__main__':
    argument = argparse.ArgumentParser(description=__doc__)
    argument.add_argument('scratch', type=Path)
    print(json.dumps(verify(argument.parse_args().scratch), indent=2))
