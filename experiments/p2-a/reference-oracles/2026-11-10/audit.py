"""Audit the public reference packet without running any canonical solution or model."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from analyze import analyze
from verify import verify

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def checked_path(relative):
    path = (HERE/relative).resolve()
    assert path.is_relative_to(HERE.resolve()), 'Artifact path escapes packet'
    return path


def audit(expected_summary_sha=None):
    receipt = json.loads((HERE/'receipt.json').read_text())
    assert receipt['schema'] == 'aijade.p2a.reference.receipt.v1'
    assert receipt['newModelCalls'] == 0 and receipt['runRoot'] == 'runs/attempt-02'
    summary_path = checked_path(receipt['summary'])
    if expected_summary_sha is not None:
        assert sha(summary_path) == expected_summary_sha, 'Unexpected summary identity'
    for name, expected in receipt['artifactSha256'].items():
        assert sha(checked_path(name)) == expected, 'Changed artifact: '+name
    for commit in [receipt['planCommit'], receipt['inputOrderAmendmentCommit']]:
        subprocess.run(['git', 'merge-base', '--is-ancestor', commit, receipt['executionCodeCommit']], cwd=ROOT, check=True)
    for name, expected in receipt['sourceSha256'].items():
        relative = str((HERE/name).relative_to(ROOT))
        original = subprocess.check_output(['git', 'show', receipt['executionCodeCommit']+':'+relative], cwd=ROOT)
        assert hashlib.sha256(original).hexdigest() == sha(HERE/name) == expected
    protected = json.loads((HERE/'protected-inputs.json').read_text())['sha256']
    assert len(protected) == receipt['protectedFiles']
    for name, expected in protected.items():
        assert sha(ROOT/name) == expected, 'Changed protected file: '+name
    for item in json.loads((HERE/'raw-compression.json').read_text()):
        h = hashlib.sha256()
        path = checked_path(item['path'])
        assert sha(path) == item['compressedSha256']
        with gzip.open(path, 'rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                h.update(block)
        assert h.hexdigest() == item['uncompressedSha256']
    summary = json.loads(summary_path.read_text())
    assert analyze(checked_path(receipt['runRoot'])) == summary, 'Public-copy reanalysis differs'
    independent = verify(checked_path(receipt['runRoot']), summary_path)
    assert independent == json.loads((HERE/'independent-validation.json').read_text())
    bank = json.loads((HERE/'bank/receipt.json').read_text())
    assert bank['summarySha256'] == sha(summary_path)
    for name, expected in bank['artifactSha256'].items():
        assert sha(checked_path('bank/'+name)) == expected
    ready = {r['taskId'] for r in summary['ledger'] if r['readyAmongStaticDirect']}
    with gzip.open(HERE/'bank/statements-only.json.gz', 'rt') as stream:
        statements = json.load(stream)
    assert len(statements) == len(ready) == bank['tasks']
    assert {r['taskId'] for r in statements} == ready
    counts = {task: 0 for task in ready}
    with gzip.open(HERE/'bank/oracle-only.jsonl.gz', 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            assert row['taskId'] in ready
            counts[row['taskId']] += 1
    assert counts == bank['taskCaseCounts'] and sum(counts.values()) == bank['cases']
    assert len(receipt['excludedRuns']) == 1 and receipt['excludedRuns'][0]['runRoot'] == 'runs/attempt-01'
    return {'status': 'PASS', 'executionCodeCommit': receipt['executionCodeCommit'],
        'artifactFiles': len(receipt['artifactSha256']), 'protectedFiles': len(protected),
        'acceptedTaskPasses': independent['taskPasses'], 'acceptedCaseRows': independent['caseRows'],
        'preparedTasks': bank['tasks'], 'preparedCases': bank['cases'], 'newModelCalls': 0,
        'checks': ['manifest hashes', 'plan/amendment ancestry', 'frozen measuring source', 'protected inputs',
            'lossless incomplete stdout', 'public-copy strict reanalysis', 'independent recomputation',
            'statement/oracle separation and counts', 'whole first-attempt exclusion'],
        'scope': 'Computational consistency only; no independent semantic audit, JavaScript port, device qualification or verifier study.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--expected-summary-sha')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = audit(args.expected_summary_sha)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
