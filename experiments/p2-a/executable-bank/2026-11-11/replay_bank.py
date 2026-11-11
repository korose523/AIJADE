"""Replay the complete materialized proposal through the normal experiment CLI."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import resource
import subprocess
import sys

from export_bank import HERE, ROOT, REVIEW, canonical, digest_file, load, rows, write_json

sys.path.insert(0, str(REVIEW))
from recover255 import run_bounded

PLAN = 'eae8aca'


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def replay(bank, executable, dll, out, final):
    manifest = load(bank / 'manifest.json')
    if final:
        assert not git('status', '--porcelain')
        subprocess.run(['git', 'merge-base', '--is-ancestor', PLAN, 'HEAD'], cwd=ROOT, check=True)
        lock = load(HERE / 'input-lock.json')
        assert digest_file(bank / 'manifest.json') == lock['manifestSha256']
        assert manifest['caseMapContentSha256'] == lock['caseMapContentSha256']
    assert len(manifest['tasks']) == 422 and sum(task['caseCount'] for task in manifest['tasks']) == 115185
    by_task = {}
    for row in rows(bank / 'case-map.jsonl.gz'):
        by_task.setdefault(row['taskId'], []).append(row)
    assert set(by_task) == {task['taskId'] for task in manifest['tasks']}
    out.mkdir(parents=True, exist_ok=False)
    sources = [
        'src/Aijade.Research/SkillBench/PublicBenchBank.cs',
        'src/Aijade.Research/SkillBench/PublicBankCheck.cs',
        'src/Aijade.Research/SkillBench/TaskAllocation.cs',
        'src/Aijade.Research/SkillBench/Sandbox.cs',
        'src/Aijade.Research/RqC/Backends.cs',
        'src/Aijade.Research/RqC/Harness.cs',
        'src/Aijade.Research/RqC/RqcRunner.cs',
        'tools/Aijade.Experiments/Program.cs',
    ]
    receipt = {
        'schema': 'aijade.p2a.execution-bank.replay.v1', 'planCommit': git('rev-parse', PLAN),
        'executionCodeCommit': git('rev-parse', 'HEAD'), 'final': final,
        'startedAt': datetime.now(timezone.utc).isoformat(), 'newModelCalls': 0,
        'manifestSha256': digest_file(bank / 'manifest.json'),
        'caseMapContentSha256': manifest['caseMapContentSha256'],
        'executableSha256': digest_file(executable), 'cliAssemblySha256': digest_file(dll),
        'jintAssemblySha256': digest_file(dll.parent / 'Jint.dll'),
        'researchAssemblySha256': digest_file(dll.parent / 'Aijade.Research.dll'),
        'sourceSha256': {name: digest_file(ROOT / name) for name in sources},
        'driverSha256': digest_file(__file__),
        'limits': {'cpuSecondsPerTask': 15, 'wallSecondsPerTask': 30,
                   'sampledRssBytes': 2 * 1024**3, 'processOutputBytes': 64 * 1024**2,
                   'sandboxMilliseconds': 2000, 'sandboxAllocationBytes': 512 * 1024**2},
    }
    write_json(out / 'execution.json', receipt)
    summary = {
        'schema': 'aijade.p2a.execution-bank.summary.v1', 'tasks': [], 'caseCounts': {},
        'plannedTasks': 422, 'plannedCases': 115185, 'executionCodeCommit': receipt['executionCodeCommit'],
        'manifestSha256': receipt['manifestSha256'], 'newModelCalls': 0, 'authorReview': 'PENDING',
    }
    overall = Counter()
    with gzip.open(out / 'cases.jsonl.gz', 'wt', encoding='utf-8') as cases, \
            gzip.open(out / 'processes.jsonl.gz', 'wt', encoding='utf-8') as processes:
        for number, entry in enumerate(manifest['tasks'], 1):
            tid = entry['taskId']
            mapped = by_task[tid]
            assert len(mapped) == entry['caseCount']
            assert [row['index'] for row in mapped] == list(range(len(mapped)))
            folder = out / 'workers' / tid.replace('/', '-')
            folder.mkdir(parents=True)
            process = run_bounded(
                [str(executable), str(dll), 'p2-bank-check', '--bank', str(bank / 'manifest.json'), '--task', tid],
                folder, {'PATH': '/usr/bin:/bin:/usr/local/bin', 'TZ': 'UTC', 'LC_ALL': 'C'},
                wall=30, stdout_name='stdout.json', limits=limits)
            stdout = (folder / 'stdout.json').read_text(encoding='utf-8', errors='replace')
            record = {'taskId': tid, 'process': process, 'stdout': stdout}
            processes.write(canonical(record) + '\n')
            processes.flush()
            observed = None
            reason = process['stop']
            if process['exitCode'] == 0 and reason is None:
                try:
                    observed = json.loads(stdout)
                    assert observed['taskId'] == tid and observed['total'] == len(mapped)
                    assert observed['manifestSha256'] == receipt['manifestSha256']
                    assert isinstance(observed['expectedOutputNoninterference'], bool)
                except (ValueError, KeyError, TypeError, AssertionError):
                    reason = 'INVALID_PROCESS_RECORD'
                    observed = None
            else:
                reason = reason or f"PROCESS_EXIT_{process['exitCode']}"
            failures = {row['index']: row for row in observed['failures']} if observed else {}
            assert not observed or len(failures) == len(observed['failures'])
            completed = observed['passed'] + len(failures) if observed else 0
            assert 0 <= completed <= len(mapped)
            assert all(0 <= index < completed for index in failures)
            assert not observed or observed['error'] or completed == len(mapped)
            counts = Counter()
            for source in mapped:
                index = source['index']
                failure = failures.get(index)
                outcome = ('UNKNOWN' if index >= completed else
                           'ERROR' if failure and failure.get('error') else 'MISMATCH' if failure else 'PASS')
                row = {**source, 'outcome': outcome}
                if failure:
                    row['failure'] = failure
                cases.write(canonical(row) + '\n')
                counts[outcome] += 1
            cases.flush()
            overall.update(counts)
            task = {
                'taskId': tid, 'sourceTaskId': entry['sourceTaskId'], 'dataset': entry['dataset'],
                'plannedCases': len(mapped), 'caseCounts': dict(counts),
                'processReason': reason, 'executionError': observed.get('error') if observed else None,
                'completeAgreement': counts == {'PASS': len(mapped)} and reason is None and observed['error'] is None,
                'expectedOutputNoninterference': observed['expectedOutputNoninterference'] if observed else None,
            }
            if observed:
                task['durationMs'] = observed['durationMs']
                task['promptSizes'] = {name: observed[name] for name in [
                    'generation', 'verifierA', 'verifierB', 'verifierAWithStub', 'verifierBWithStub']}
                task['referenceCodeUtf8Bytes'] = observed['referenceCodeUtf8Bytes']
                task['tokenizerStatus'] = observed['tokenizerStatus']
            summary['tasks'].append(task)
            summary['caseCounts'] = dict(overall)
            summary['completeAgreementTasks'] = sum(row['completeAgreement'] for row in summary['tasks'])
            summary['promptNoninterferenceTasks'] = sum(row['expectedOutputNoninterference'] is True for row in summary['tasks'])
            write_json(out / 'summary.json', summary)
            print(number, tid, dict(counts), reason or '', flush=True)
    assert sum(overall.values()) == 115185 and len(summary['tasks']) == 422
    summary['finishedAt'] = datetime.now(timezone.utc).isoformat()
    write_json(out / 'summary.json', summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--bank', type=Path, required=True)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--dll', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--final', action='store_true')
    args = parser.parse_args()
    replay(args.bank.resolve(), args.executable.resolve(), args.dll.resolve(), args.out.resolve(), args.final)
