#!/usr/bin/env python3
"""Reconstruct the eight actual synthetic qualification requests without services or inference."""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def verify(root, repo):
    sys.path.insert(0, str(repo/'tools/p3_longmemeval'))
    spec = importlib.util.spec_from_file_location('lme_qualification_product_analysis', repo/'tools/p3_longmemeval/analyze_product.py')
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
    rows, hashes = [], []
    for fixture, query, queries, state, observed in [
        ('ordinary', 'quartz', ['quartz'], 'truncated', []),
        ('fallback', 'quartz unrelatedword?', ['quartz unrelatedword?', 'unrelatedword', 'quartz'], 'ambiguous-source', None),
    ]:
        folder = root/fixture
        def load(suffix, lines=False):
            path = folder/('question-000-'+suffix)
            raw = path.read_bytes()
            hashes.append(dict(path=fixture+'/'+path.name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)))
            text = gzip.decompress(raw).decode('utf-8')
            return [json.loads(line) for line in text.splitlines()] if lines else json.loads(text)
        store_rows = load('store.json.gz')
        store = {r['Id']: r for r in store_rows}
        writes = load('writes.jsonl.gz', True)
        captures = load('captures.json.gz')
        boundaries = load('raw-boundaries.jsonl.gz', True)
        assert len(store) == len(store_rows) == len(writes) == 70
        assert {w['packId'] for w in writes} == set(store)
        for write in writes:
            assert 200 <= write['status'] < 300
            assert write['request']['content'] == store[write['packId']]['Content']
        assert all(not r['HasVector'] and r['Owner'] == 'test-user' for r in store_rows)
        assert len(captures) == len(boundaries) == 4
        assert [r['policy'] for r in captures] == observer.POLICIES
        assert len({r['storeSha256'] for r in captures}) == 1
        for row, boundary in zip(captures, boundaries):
            assert row['completed'] and boundary['completed']
            assert row['completionCaptures'] == boundary['CompletionCaptures'] == 1
            assert row['completionBody'] == boundary['CompletionBody'] and row['rawSystem'] == boundary['SystemMessage']
            assert observer.sha(row['completionBody']) == row['completionBodySha256']
            assert observer.sha(row['rawSystem']) == row['systemSha256']
            body = json.loads(row['completionBody'])
            assert [m['content'] for m in body['messages'] if m['role'] == 'user'] == [query]
            assert not [m for m in body['messages'] if m['role'] == 'assistant']
            assert [m['content'] for m in body['messages'] if m['role'] == 'system'] == [row['rawSystem']]
            assert [s['Query'] for s in row['searches']] == queries
            assert [s['query'] for s in row['poolQueries']] == queries
            assert all(s['Status'] == 200 and s['Limit'] == int(row['policy'].split('-')[0]) for s in row['searches'])
            actual_state, actual_ids = observer.observe(row['rawSystem'], row['plannedIds'], store)
            assert actual_state == row['state'] == state
            assert actual_ids == row['observedIds'] == observed
            assert row['rawTruncationMarker'] and observer.MARKER in row['rawSystem']
            rows.append(dict(fixture=fixture, policy=row['policy'], state=state,
                             fullItems=None if observed is None else len(observed), searches=len(queries)))
    return dict(status='PASS', actualRequests=len(rows), writes=140, rows=rows, inputFiles=hashes,
                independentHumanReview=False, newServiceCalls=0, newModelCalls=0,
                scope='Independent observation of persisted actual synthetic C# qualification requests. No corpus outcome or answer-quality claim.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = verify(args.qualification, args.repo)
    if args.out:
        assert not args.out.exists(), 'Preserve prior qualification reports.'
        args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
