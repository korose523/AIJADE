#!/usr/bin/env python3
"""Check the offline comparison with retained observations and labeled synthetic controls."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from audit_retrieval_led import sha
from compare_known_repeats import COMPLETE, compare
from score_live_manifest import score_directory


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / 'live-manifest-2026-11-12/attempts'
INPUTS = HERE / 'relocated-runtime-2026-11-16/qualification-inputs'


def load(path):
    return json.loads(path.read_bytes())


def encode(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def derived_fixture(index):
    """Wrap existing v1 rows in a synthetic v2 envelope, with no new observation."""
    data = {name: (INPUTS / name).read_bytes() for name in
            ('runtime-manifest.json', 'scoring-manifest.json', 'selection.json')}
    runtime = json.loads(data['runtime-manifest.json'])
    rows = load(ARCHIVE / 'development-02/cases.json')
    planned = {row['input']['caseId']: row for row in runtime['cases']}
    for number, row in enumerate(rows):
        # Synthetic, disjoint identities exercise the report's isolation checks.
        database = dict(database=f'synthetic_{index}_{number}', token=f'{index:02x}{number:030x}')
        row.update(runtimeInput=planned[row['caseId']], batch='qualification_only',
                   dataOrigin='known_scenario_qualification', databaseBefore=database,
                   databaseAfter=deepcopy(database))
    date = f'2000-01-0{index}T'
    code = '1' * 40
    binaries = {'synthetic-test.dll': '2' * 64}
    data.update({
        'cases.json': encode(rows),
        'renderer-request.json': encode(dict(session=f'synthetic-repeat-{index}')),
        'frozen-build.json': encode(dict(commit=code, files=binaries)),
        'receipt.json': encode(dict(
            schema='aijade.ch7.finite-block-receipt.v1', status=COMPLETE,
            reason=None, inFlightCaseIds=[], unknownCaseIds=[], unattemptedCaseIds=[],
            dispositionErrors=[], logCloseErrors=[], plannedPairs=10, plannedCases=20,
            completedCases=20, codeCommit=code, purpose=runtime['purpose'],
            blockIndex=runtime['blockIndex'], heldOutCases=0, modelRequests=0,
            formalHardwareQualification=False,
            conditionsMeasured=['C1', 'C2'], finishedAt=date + '00:00:05Z',
            phases={name: dict(exitCode=0, startedAt=date + '00:00:00Z',
                               endedAt=date + '00:00:04Z')
                    for name in ('flow', 'renderer')},
        )),
    })
    data['input-identities.json'] = encode(dict(
        purpose=runtime['purpose'], codeCommit=code,
        constructionFreezeCommit=runtime['constructionFreezeCommit'],
        runtimeManifestSha256=sha(data['runtime-manifest.json']),
        scoringManifestSha256=sha(data['scoring-manifest.json']),
        selectionSha256=sha(data['selection.json']),
        binaries=binaries, buildManifestSha256=sha(data['frozen-build.json']), executionPlanSha256='3' * 64,
        realGodotSha256='4' * 64, modelSha256='5' * 64,
    ))
    return data


def update(data, name, change):
    value = json.loads(data[name])
    change(value)
    data[name] = encode(value)


def verify(output_root):
    complete = ARCHIVE / 'development-02'
    archived_score = score_directory(complete)
    assert archived_score == load(complete / 'scoring.json')
    older = compare(ARCHIVE / 'development-01', complete)
    assert older['status'] == 'OFFLINE_REPEAT_PAIR_UNSCORABLE'
    assert all('unsupported finite-block receipt schema' in row['completionBlockers']
               for row in older['attempts'])
    controls = []

    with TemporaryDirectory(prefix='known-repeats-controls-', dir=output_root) as temp:
        first, second = (Path(temp) / f'synthetic-{i}' for i in (1, 2))
        for folder, index in ((first, 1), (second, 2)):
            folder.mkdir()
            for name, raw_bytes in derived_fixture(index).items():
                (folder / name).write_bytes(raw_bytes)
        original = derived_fixture(2)

        def control(name, expected, change, expected_detail=None):
            data = dict(original)
            change(data)
            for filename, body in data.items():
                (second / filename).write_bytes(body)
            result = compare(first, second)
            assert result['status'] == expected, (name, result)
            assert result['qualificationDetermined'] is False and result['newRunsStarted'] == 0
            assert result['comparableRows'] == (0 if expected == unscorable else 20)
            detail = result['pairBlockers'] + result['attempts'][1]['completionBlockers'] + result['attempts'][1]['evidenceBlockers']
            if expected_detail is not None:
                assert any(expected_detail in message for message in detail), (name, detail)
            controls.append(dict(control=name, status=result['status'],
                                 comparableRows=result['comparableRows'],
                                 differences=result['differences'], blockers=detail))
            return result

        match, mismatch, unscorable = 'OFFLINE_REPEAT_MATCH', 'OFFLINE_REPEAT_MISMATCH', 'OFFLINE_REPEAT_PAIR_UNSCORABLE'
        control('complete archived-derived rows, including controlled refusals', match, lambda data: None)
        control('raw array order changes, keyed decisions retained', match,
                lambda data: update(data, 'cases.json', list.reverse))

        def exchange_reuse_positions(rows):
            row = next(row for row in rows if row['duplicateReuse'] is not None)
            row['round2'], row['duplicateReuse'] = row['duplicateReuse'], row['round2']

        moved = control('same counts, different first and duplicate reuse decisions', mismatch,
                        lambda data: update(data, 'cases.json', exchange_reuse_positions))
        assert len(moved['differences']) == 1
        assert {'firstReuse', 'duplicateReuse'} <= set(moved['differences'][0]['fields'])

        def remove_early_promotion(rows):
            snapshot = next(row['beforeDelivery'] for row in rows if row['beforeDelivery']['specs'] == 1)
            snapshot.update(specs=0, reports=0, specRows=[], reportRows=[])

        early = control('same final rows, different durable promotion at delivery', mismatch,
                        lambda data: update(data, 'cases.json', remove_early_promotion))
        assert len(early['differences']) == 1
        assert set(early['differences'][0]['fields']) == {'persistedBeforeDelivery'}
        control('timeout receipt retained despite all visible rows', unscorable,
                lambda data: update(data, 'receipt.json',
                                    lambda r: r.update(status='STOPPED', reason='synthetic timeout')),
                'terminal status is not complete')
        control('apparently complete with an unknown case disposition', unscorable,
                lambda data: update(data, 'receipt.json', lambda r: r['unknownCaseIds'].append('synthetic')),
                'unknownCaseIds')
        control('apparently complete with a renderer error', unscorable,
                lambda data: update(data, 'receipt.json', lambda r: r['phases']['renderer'].update(exitCode=2)),
                'renderer exit code')
        control('missing case', unscorable,
                lambda data: update(data, 'cases.json', lambda r: r.pop()), 'finite row population')
        control('duplicate case/condition hides a missing slot', unscorable,
                lambda data: update(data, 'cases.json', lambda r: r.__setitem__(0, r[1])),
                'duplicate case/condition')
        control('unscorable reuse error with complete receipt', unscorable,
                lambda data: update(data, 'cases.json', lambda r: r[0]['round2'].update(status=504)),
                'unscorable reuse HTTP observation')
        control('unplanned database error', unscorable,
                lambda data: update(data, 'cases.json', lambda r: r[0].update(databaseErrorCode='P0001')),
                'unexpected database error')
        control('same nominal inputs, selection bytes altered', unscorable,
                lambda data: data.update({'selection.json': data['selection.json'] + b' '}),
                'unbound exact bytes: selection.json')
        control('changed executable hash map', unscorable,
                lambda data: update(data, 'input-identities.json', lambda r: r.update(binaries={})),
                'frozen executable hashes differ')
        control('changed execution plan binding', unscorable,
                lambda data: update(data, 'input-identities.json', lambda r: r.update(executionPlanSha256='6' * 64)),
                'shared run binding differs: executionPlanSha256')
        control('renderer session reused', unscorable,
                lambda data: update(data, 'renderer-request.json', lambda r: r.update(session='synthetic-repeat-1')),
                'renderer sessions are not distinct')
        control('copied row database set reuses first attempt', unscorable,
                lambda data: data.update({'cases.json': (first / 'cases.json').read_bytes()}),
                'database identities or continuity tokens overlap')
        control('copied receipt is no second attempt', unscorable,
                lambda data: data.update({'receipt.json': (first / 'receipt.json').read_bytes()}),
                'same attempt cannot serve as both repeats')
        control('duplicate JSON keys in receipt', unscorable,
                lambda data: data.update({'receipt.json': b'{"status":"STOPPED","status":"COMPLETE"}'}),
                'duplicate JSON key')

    return dict(status='OFFLINE_COMPARATOR_CONTROLS_PASS',
                historicalValidation=dict(
                    purpose='Recomputed exact archived v1 score; this is one historical complete attempt only.',
                    completeV1ScoredRows=archived_score['measuredConditionRows'],
                    completeV1CasesSha256=archived_score['actualRowsSha256'],
                    olderPairDisposition=older['status'],
                    retainedReceipts=[dict(status=row['receiptStatus'], reason=row['receiptReason'],
                                           receiptSha256=row['files']['receipt.json'])
                                      for row in older['attempts']]),
                syntheticControlCount=len(controls), syntheticControls=controls,
                comparatorSha256=sha((HERE / 'compare_known_repeats.py').read_bytes()),
                testSha256=sha(Path(__file__).read_bytes()), newEmpiricalObservations=0,
                newRunsStarted=0, newHeldoutCases=0, qualificationDetermined=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact_root', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.artifact_root), indent=2, ensure_ascii=False, allow_nan=False))
