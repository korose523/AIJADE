#!/usr/bin/env python3
"""Cross-check actual embedding responses with NumPy, without calling a model.

Uses float32 products and float64 accumulation, matching the documented scalar formula.
Numerical ties are reported separately; actual captured ordering is never rewritten.
Usage: verify_embeddings.py EMBEDDING_RUN_DIR --out REPORT.json
"""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np


def open_raw(path):
    if not path.exists():
        path = path.with_name(path.name + '.gz')
    return gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()


def verify(folder):
    with open_raw(folder/'product-path-v2-shared-memory-only-embedding.json') as stream:
        data = json.load(stream)
    checked = 0
    ties = []
    upstream_requests = 0
    inputs_embedded = 0
    conversation = None
    with open_raw(folder/'embeddings-shared-memory-only-embedding.jsonl') as journal:
        for row in data['rows']:
            if conversation != row['c']:
                conversation = row['c']
                with gzip.open(folder/('store-shared-memory-only-embedding-%s.json.gz' % conversation), 'rt') as f:
                    store = json.load(f)[:2000]
                ids = [p['Id'] for p in store]
                content = [p['Content'].casefold() for p in store]
                matrix = np.array([p['Vector'] for p in store], dtype=np.float32)
                assert matrix.ndim == 2 and matrix.shape[1] == 768 and np.isfinite(matrix).all()
                norms = np.sum(matrix*matrix, axis=1, dtype=np.float64)
                consumed = 0
            vectors = {}
            while consumed < row['embeddingRequestsSoFar']:
                event = json.loads(next(journal))
                assert event['status'] == 200
                batch = event['input']['input']
                response = json.loads(event['response'])
                assert len(response['data']) == len(batch)
                for item in response['data']:
                    vectors[batch[item['index']]] = np.array(item['embedding'], dtype=np.float32)
                consumed += 1
                upstream_requests += 1
                inputs_embedded += len(batch)
            for trace in row['searchTrace']:
                query = trace['query'].strip()
                vector = vectors[query]
                assert vector.shape == (768,) and np.isfinite(vector).all()
                dot = np.sum(matrix*vector, axis=1, dtype=np.float64)
                denominator = np.sqrt(norms*np.sum(vector*vector, dtype=np.float64))
                scores = np.divide(dot, denominator, out=np.zeros_like(dot), where=denominator != 0)
                scores += np.array([0.15 if query.casefold() in text else 0.0 for text in content])
                order = [int(i) for i in np.argsort(-scores, kind='stable') if scores[i] >= 0.3][:6]
                expected = [ids[i] for i in order]
                actual_items = json.loads(trace['rawBody'])['items']
                actual = [p['id'] for p in actual_items]
                if actual != expected:
                    # Only rank positions indistinguishable within double-accumulation rounding can differ.
                    assert len(actual) == len(expected)
                    for a, b in zip(actual, expected):
                        assert abs(float(scores[ids.index(a)]-scores[ids.index(b)])) <= 1e-12, (row['c'], row['q'], a, b)
                    ties.append({'c': row['c'], 'q': row['q'], 'query': query, 'actual': actual, 'numpy': expected})
                for item in actual_items:
                    assert abs(float(scores[ids.index(item['id'])])-item['score']) <= 0.000050000001
                checked += 1
        assert not journal.read().strip(), 'unassociated upstream responses remain'
    assert len(data['rows']) == 1986
    return {'schema': 'aijade.p3e.numpy-vector-crosscheck.v1', 'status': 'PASS' if not ties else 'PASS_WITH_REPORTED_FLOAT_TIES',
            'numpyVersion': np.__version__, 'questions': len(data['rows']), 'serverSearchesChecked': checked,
            'actualUpstreamHttpRequests': upstream_requests, 'inputsEmbedded': inputs_embedded,
            'floatingRankTies': ties, 'newModelCalls': 0,
            'scope': 'Numerical recomputation from the same captured vectors and store snapshots; not independent data, human coding or answer evaluation.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.folder)
    with args.out.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result))
