"""Reconstruct the executable-bank outcomes from full captured process and case records."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
REVIEW = ROOT / 'experiments/p2-a/candidate-review/2026-11-11/results/review'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        yield from map(json.loads, stream)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            h.update(block)
    return h.hexdigest()


def audit(here):
    results = here / 'results'
    receipt = load(results / 'receipt.json')
    for relative, expected in receipt['artifactSha256'].items():
        assert digest(here / relative) == expected, relative
    lock = load(here / 'input-lock.json')
    bank = load(results / 'bank/manifest.json')
    assert digest(results / 'bank/manifest.json') == lock['manifestSha256']
    assert digest(results / 'bank/candidate-statements.md') == lock['statementBookSha256']
    assert digest(here / 'export_bank.py') == lock['exportSha256']
    execution = load(results / 'replay/execution.json')
    assert execution['manifestSha256'] == lock['manifestSha256']
    assert execution['caseMapContentSha256'] == lock['caseMapContentSha256']
    assert execution['planCommit'] == lock['planCommit']
    assert execution['executionCodeCommit'] == receipt['executionCodeCommit']
    assert execution['newModelCalls'] == lock['newModelCalls'] == 0
    summary = load(results / 'replay/summary.json')
    assert summary['finishedAt']
    tasks = {row['taskId']: row for row in bank['tasks']}
    assert len(tasks) == len(bank['tasks']) == lock['tasks'] == 422
    assert sum(task['caseCount'] for task in tasks.values()) == lock['cases'] == 115185
    assert not {'HumanEval/132', 'Mbpp/255', 'Mbpp/260'} & tasks.keys()
    source = {}
    for row in rows(REVIEW / 'case-decisions.jsonl.gz'):
        if row['proposed']:
            key = (row['proposedCandidateId'], tuple(row['sourceCase']))
            assert key not in source
            source[key] = row
    assert len(source) == 115185
    process_rows = list(rows(results / 'replay/processes.jsonl.gz'))
    process = {row['taskId']: row for row in process_rows}
    assert len(process_rows) == len(process)
    assert len(process) == 422 and set(process) == set(tasks)
    task_summaries = {row['taskId']: row for row in summary['tasks']}
    assert len(task_summaries) == len(summary['tasks']) == 422 and set(task_summaries) == set(tasks)
    observed = {}
    reconstructed = {}
    for tid, row in process.items():
        proc = row['process']
        assert hashlib.sha256(row['stdout'].encode()).hexdigest() == proc['stdoutSha256']
        assert hashlib.sha256(proc['stderr'].encode()).hexdigest() == proc['stderrSha256']
        result = json.loads(row['stdout']) if proc['exitCode'] == 0 and proc['stop'] is None else None
        observed[tid] = result
        if result:
            assert result['taskId'] == tid and result['total'] == tasks[tid]['caseCount']
            assert result['manifestSha256'] == lock['manifestSha256']
            assert len({x['index'] for x in result['failures']}) == len(result['failures'])
            completed = result['passed'] + len(result['failures'])
            assert 0 <= completed <= result['total']
            assert all(0 <= x['index'] < completed for x in result['failures'])
            failures = {x['index']: x for x in result['failures']}
            reconstructed[tid] = [
                'UNKNOWN' if i >= completed else 'ERROR' if i in failures and failures[i].get('error')
                else 'MISMATCH' if i in failures else 'PASS' for i in range(result['total'])]
            for name in ['generation','verifierA','verifierB','verifierAWithStub','verifierBWithStub']:
                item = task_summaries[tid]['promptSizes'][name]
                assert item == result[name]
                assert re.fullmatch('[a-f0-9]{64}', item['sha256'])
                assert 0 < item['utf16Units'] <= item['utf8Bytes']
            assert task_summaries[tid]['expectedOutputNoninterference'] == result['expectedOutputNoninterference']
            assert task_summaries[tid]['tokenizerStatus'] == 'NOT_MEASURED'
        else:
            reconstructed[tid] = ['UNKNOWN'] * tasks[tid]['caseCount']
    counts = Counter()
    per_task = {tid: Counter() for tid in tasks}
    seen = set()
    map_digest = hashlib.sha256()
    next_index = Counter()
    for row in rows(results / 'replay/cases.jsonl.gz'):
        tid = row['taskId']
        key = (tid, tuple(row['sourceCase']))
        assert key not in seen and key in source
        seen.add(key)
        original = source[key]
        assert row['sourceTaskId'] == original['sourceTaskId'] == tasks[tid]['sourceTaskId']
        assert row['inputSha256'] == original['candidateInputSha256']
        assert row['expectedSha256'] == original['candidateExpectedSha256']
        index = row['index']
        assert index == next_index[tid]
        next_index[tid] += 1
        assert row['outcome'] == reconstructed[tid][index]
        counts[row['outcome']] += 1
        per_task[tid][row['outcome']] += 1
        original_map = {key: row[key] for key in ['taskId','sourceTaskId','sourceCase','index','inputSha256','expectedSha256','floatTolerance']}
        canonical = json.dumps(original_map,ensure_ascii=False,sort_keys=True,separators=(',',':')) + '\n'
        map_digest.update(canonical.encode())
    assert seen == set(source)
    assert map_digest.hexdigest() == lock['caseMapContentSha256']
    assert dict(counts) == summary['caseCounts']
    for tid in tasks:
        assert sum(per_task[tid].values()) == tasks[tid]['caseCount']
        assert dict(per_task[tid]) == task_summaries[tid]['caseCounts']
        expect_complete = per_task[tid] == {'PASS':tasks[tid]['caseCount']} and observed[tid] is not None and observed[tid]['error'] is None
        assert task_summaries[tid]['completeAgreement'] == expect_complete
    assert summary['completeAgreementTasks'] == sum(x['completeAgreement'] for x in task_summaries.values())
    assert summary['promptNoninterferenceTasks'] == sum(x['expectedOutputNoninterference'] is True for x in task_summaries.values())
    engineering = load(results / 'engineering/summary.json')
    assert engineering['newModelCalls'] == 0
    assert engineering['normalCli']['mode'] == 'simulation'
    assert engineering['normalCli']['steps'] == 48
    assert engineering['normalCli']['manifestSha256'] == lock['manifestSha256']
    assert engineering['resume']['replayedSteps'] == 32 and engineering['resume']['decisionsIdentical']
    assert all(value['rejected'] for value in engineering['negativeChecks'].values())
    captured = {}
    for group in ['full', 'resumed']:
        captured[group] = {}
        for name in ['trials', 'candidates']:
            records = list(rows(results / f'engineering/{group}/{name}.jsonl.gz'))
            assert len(records) == 48
            assert all(x['publicBankManifestSha256'] == lock['manifestSha256'] and
                       x['runFingerprint'] == engineering['normalCli']['runFingerprint'] for x in records)
            assert all(x['execOk'] for x in records)
            captured[group][name] = records
    for name in ['trials', 'candidates']:
        for first, second in zip(captured['full'][name], captured['resumed'][name]):
            first.pop('durationMs', None)
            second.pop('durationMs', None)
            assert first == second
    trial_rows = captured['full']['trials']
    groups = {}
    for row in trial_rows:
        groups.setdefault(row['condition'], []).append(row['taskId'])
    assert len(groups) == 4
    expected_order = load(results / 'engineering/allocation.json')['firstPublicTrial']
    assert all(value == expected_order for value in groups.values())
    for name, value in engineering['negativeChecks'].items():
        proc = load(results / f'engineering/rejections/{name}/process.json')
        assert proc == value['process'] and proc['exitCode'] != 0
        assert 'different public bank or run fingerprint' in proc['stderr']
        assert not value['outputCreated']
    assert digest(here / 'run_control.py') == engineering['driverSha256']
    aggregate = load(results / 'summary.json')
    assert aggregate['schema'] == 'aijade.p2a.execution-bank.aggregate.v1'
    assert aggregate['tasks'] == 422 and aggregate['cases'] == 115185
    assert aggregate['executionCodeCommit'] == execution['executionCodeCommit']
    assert aggregate['planCommit'] == execution['planCommit']
    assert aggregate['manifestSha256'] == lock['manifestSha256']
    assert aggregate['authorReview'] == 'PENDING' and aggregate['newModelCalls'] == 0
    expected_replay = {
        'completeAgreementTasks': summary['completeAgreementTasks'],
        'passedCases': counts.get('PASS', 0), 'mismatchedCases': counts.get('MISMATCH', 0),
        'errorCases': counts.get('ERROR', 0), 'unknownCases': counts.get('UNKNOWN', 0),
        'promptNoninterferenceTasks': summary['promptNoninterferenceTasks'],
        'maximumSampledRssBytes': max(x['process']['sampledPeakRssBytes'] for x in process.values()),
        'maximumWorkerWallSeconds': max(x['process']['wallSeconds'] for x in process.values()),
    }
    assert aggregate['replay'] == expected_replay
    for name, item in aggregate['promptSizes'].items():
        measured = [(row[name]['utf8Bytes'], tid) for tid, row in observed.items() if row]
        assert item == {
            'minimumUtf8Bytes': min(measured)[0], 'minimumTask': min(measured)[1],
            'medianUtf8Bytes': statistics.median(x[0] for x in measured),
            'maximumUtf8Bytes': max(measured)[0], 'maximumTask': max(measured)[1],
            'tokenizerStatus': 'NOT_MEASURED',
        }
    assert set(aggregate['promptSizes']) == {'generation', 'verifierA', 'verifierB', 'verifierAWithStub', 'verifierBWithStub'}
    assert aggregate['control'] == engineering['normalCli']
    assert aggregate['resume'] == engineering['resume']
    assert aggregate['negativeChecks'] == engineering['negativeChecks']
    assert aggregate['allocation'] == load(results / 'engineering/allocation.json')['scenarios'][-1]
    return {'status':'PASS','tasks':len(tasks),'cases':len(seen),'caseCounts':dict(counts),
            'completeAgreementTasks':summary['completeAgreementTasks'],
            'promptNoninterferenceTasks':summary['promptNoninterferenceTasks'],
            'manifestFiles':len(receipt['artifactSha256']),'authorReview':'PENDING','newModelCalls':0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--directory', type=Path, default=HERE)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory.resolve()),ensure_ascii=False,indent=2))
