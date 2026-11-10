#!/usr/bin/env python3
"""Numerical/text-search cross-check from retained vectors and actual widened API responses.

NumPy float32 products with float64 accumulation independently implement the C# server formula.
This reads existing evidence, makes no model/API calls and does not rewrite tied rankings.
"""
import argparse
import gzip
import json
from pathlib import Path
import re

import numpy as np

from external_policies import Replay


def verify(folder, packet):
    replay = Replay(packet)
    totals = {}
    ties = []
    exact_boundary_ties = 0
    near_boundary_ties = 0
    for mode in ['text', 'embedding']:
        current = None
        checked = 0
        cached = {}
        with gzip.open(folder / mode / ('product-%s.jsonl.gz' % mode), 'rt') as stream:
            for line in stream:
                row = json.loads(line)
                if row['c'] != current:
                    current = row['c']
                    with gzip.open(folder / mode / ('store-%s-%s.json.gz' % (mode, current)), 'rt') as f:
                        store = json.load(f)
                    ids = [r['Id'] for r in store]
                    contents = [r['Content'] for r in store]
                    if mode == 'embedding':
                        matrix = np.array([r['Vector'] for r in store[:2000]], dtype=np.float32)
                        norms = np.sum(matrix * matrix, axis=1, dtype=np.float64)
                    cached.clear()
                pool = set()
                above = set()
                for search in row['searches']:
                    query = search['Query'].strip()
                    if query not in cached:
                        if mode == 'embedding':
                            vector = np.array(replay.get(query), dtype=np.float32)
                            dot = np.sum(matrix * vector, axis=1, dtype=np.float64)
                            denominator = np.sqrt(norms * np.sum(vector * vector, dtype=np.float64))
                            scores = np.divide(dot, denominator, out=np.zeros_like(dot), where=denominator != 0)
                            scores += np.array([.15 if query.casefold() in text.casefold() else 0 for text in contents[:2000]])
                            order = [int(i) for i in np.argsort(-scores, kind='stable') if scores[i] >= .3]
                            cached[query] = (set(ids[:2000]), [ids[i] for i in order], dict(zip(ids[:2000], scores.tolist())))
                        else:
                            regex = re.compile(re.escape(query).replace('%', '.*').replace('_', '.'), re.IGNORECASE | re.DOTALL)
                            matches = [key for key, text in zip(ids, contents) if regex.search(text)]
                            cached[query] = (set(matches), matches, {})
                    candidates, ranked, scores_by_id = cached[query]
                    pool.update(candidates)
                    above.update(ranked)
                    expected = ranked[:search['Limit']]
                    actual = search['Ids']
                    if actual != expected:
                        assert mode == 'embedding' and len(actual) == len(expected)
                        assert all(abs(scores_by_id[a] - scores_by_id[b]) <= 1e-12 for a, b in zip(actual, expected))
                        ties.append({'c': current, 'q': row['q'], 'policy': row['policy'], 'actual': actual, 'numerical': expected})
                    if mode == 'embedding':
                        limit = search['Limit']
                        if len(ranked) > limit:
                            delta = scores_by_id[ranked[limit - 1]] - scores_by_id[ranked[limit]]
                            exact_boundary_ties += delta == 0
                            near_boundary_ties += abs(delta) <= 1e-12
                        for item in json.loads(search['RawBody'])['items']:
                            assert abs(item['score'] - scores_by_id[item['id']]) <= .000050000001
                    checked += 1
                assert pool == set(row['poolIds'])
                assert above == set(row['aboveIds'])
        totals[mode] = checked
    return {'schema': 'aijade.p3.policy.search-crosscheck.v1', 'status': 'PASS' if not ties else 'PASS_WITH_REPORTED_FLOAT_TIES',
            'numpyVersion': np.__version__, 'actualSearchesChecked': totals, 'floatingRankTies': ties,
            'exactTieSearchesAtResponseBoundary': exact_boundary_ties, 'nearTieSearchesAtResponseBoundary1e12': near_boundary_ties,
            'newModelCalls': 0, 'scope': 'Numerical/text predicate cross-check of the same actual inputs and API responses; not independent data or replication.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.folder, args.source)
    with args.out.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'floatingRankTies'}))
