#!/usr/bin/env python3
"""Reject semantically corrupted disposable copies, after ordinary byte/manifest checks."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from audit_retrieval_led import verify, load


def run(root, repo):
    verify(root, repo)
    results = []
    for name in ['phase-order', 'retrieved-code', 'database-continuity', 'missing-case', 'revoked-positive-reuse']:
        with tempfile.TemporaryDirectory(prefix='aijade-flow-rejection-') as temp:
            copy = Path(temp) / 'packet'
            shutil.copytree(root, copy, ignore=shutil.ignore_patterns('renderer-source', '*skinning*'))
            rows = load(copy, 'cases.json')
            journal = load_journal(copy)
            if name == 'phase-order':
                a = next(j for j in journal if j['caseId'] == 'H' and j['phase'] == 'memory.read.begin')
                b = next(j for j in journal if j['caseId'] == 'H' and j['phase'] == 'execution.begin')
                a['phase'], b['phase'] = b['phase'], a['phase']
            elif name == 'retrieved-code':
                rows[0]['prepared']['codeSha256'] = '0' * 64
            elif name == 'database-continuity':
                rows[0]['databaseAfter']['token'] = '0' * 32
            elif name == 'missing-case':
                rows.pop()
            else:
                row = next(r for r in rows if r['caseId'] == 'I7')
                row['round2']['executed'] = True
                row['final']['reuseCount'] = 1
            # Keep final journal projections coherent so checks cannot rely only on
            # a stale redundant JSON copy. Other causal links remain as observed.
            for row in rows:
                event = next(j for j in journal if j['caseId'] == row['caseId'] and j['phase'] == 'case.complete')
                event['detail'] = row
            (copy/'cases.json').write_text(json.dumps(rows) + '\n')
            (copy/'journal.jsonl').write_text(''.join(json.dumps(j)+'\n' for j in journal))
            try:
                verify(copy, repo)
            except (ValueError, KeyError) as error:
                results.append(dict(control=name, rejected=True, reason=str(error)))
            else:
                raise AssertionError('corrupted packet accepted: ' + name)
    return dict(status='PASS', rejectedControls=len(results), results=results)


def load_journal(root):
    from audit_retrieval_led import lines
    return lines(root, 'journal.jsonl')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.repo), indent=2))
