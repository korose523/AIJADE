"""Trace Mbpp/260 and check its released recurrence independently of prime rank."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

from recover255 import (JAVASCRIPT, PLAN, PRIOR, REFERENCE, canonical, digest_bytes,
                        digest_file, git, source_task, write_json)

GOOGLE_COMMIT = 'f82046ba5aabbbb427dbfd38a254d26bff08b533'
GOOGLE_URL = ('https://github.com/google-research/google-research/blob/'
              + GOOGLE_COMMIT + '/mbpp/mbpp.jsonl')
PAPER_URL = ('https://www.impan.pl/en/publishing-house/journals-and-series/acta-arithmetica/'
             'all/38/2/102667/simple-groups-of-square-order-and-interesting-sequence-of-primes')


def matrix_product(a, b):
    return (a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3],
            a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3])


def companion_term(n):
    n = int(n)
    if n == 0:
        return 1
    product = (1, 0, 0, 1)
    matrix = (2, 1, 1, 0)
    exponent = n - 1
    while exponent:
        if exponent % 2:
            product = matrix_product(product, matrix)
        matrix = matrix_product(matrix, matrix)
        exponent //= 2
    return product[0] + product[1]


def released_rows():
    target = b'"taskId":"Mbpp/260"'
    with gzip.open(REFERENCE / 'runs/attempt-02/pass-1/rows.jsonl.gz', 'rb') as stream:
        for line in stream:
            if target in line:
                row = json.loads(line)
                if row['kind'] == 'case':
                    yield row, digest_bytes(line)


def verify(google_path, paper_path, out):
    problem = source_task('Mbpp/260')
    google = next(row for row in map(json.loads, google_path.open()) if row['task_id'] == 260)
    assert google['text'] == problem['prompt'].splitlines()[1]
    assert '2 * newman_prime(n - 1) + newman_prime(n - 2)' in google['code']
    assert [x.strip() for x in google['test_list']] == [
        'assert newman_prime(3) == 7', 'assert newman_prime(4) == 17', 'assert newman_prime(5) == 41']
    prior = json.loads((JAVASCRIPT / 'results/release/summary.json').read_text())
    old = next(item for item in prior['tasks'] if item['taskId'] == 'Mbpp/260')
    assert old['counts'] == {'PASS': 107}
    raw_inputs = [(part, i, value) for part in ['base', 'plus']
                  for i, value in enumerate(problem[part + '_input'])]
    originals = list(released_rows())
    assert len(originals) == len(raw_inputs) == 107
    rows = []
    for (observed, original_line_sha), (partition, index, args) in zip(originals, raw_inputs):
        assert observed['partition'] == partition and observed['index'] == index and observed['status'] == 'OK'
        assert json.loads(observed['serializedArgsJson']) == args
        n = args[0]
        assert type(n) in [int, bool] and n >= 0
        output = observed['output']
        assert output['t'] == 'int'
        expected = int(output['hex'], 16) if 'hex' in output else int(output['v'])
        value = companion_term(n)
        assert value == expected
        row = {'taskId': 'Mbpp/260', 'case': [partition, index], 'input': observed['input'],
               'releasedOutput': output, 'originalTypedRowSha256': original_line_sha,
               'recurrenceCheck': 'AGREES', 'method': 'binary companion-matrix exponentiation'}
        if type(n) is bool or n < 1:
            row.update(status='OUTSIDE_DOMAIN', reason='One-based mathematical prime rank requires a positive integer argument.')
        else:
            # The first prime in the paper's odd-index sequence is s_3.
            # The n-th prime, if defined, has index at least 2n+1.
            lower = companion_term(2*n + 1)
            assert value < lower
            row.update(status='STATEMENT_CONFLICT',
                       reason='The released s_n is below s_(2n+1), a lower bound for the n-th prime in the odd-index special-number sequence.',
                       primeRankIndexLowerBound=2*n+1,
                       exactLowerBoundSha256=digest_bytes(hex(lower).encode()))
        rows.append(row)
    assert len({tuple(row['case']) for row in rows}) == 107
    counterexamples = []
    for n, left, right in [(6, 9, 11), (9, 7, 199)]:
        assert companion_term(n) == left * right
        actual = [[row['partition'], row['index']] for row, _ in originals
                  if json.loads(row['serializedArgsJson']) == [n]]
        assert actual
        counterexamples.append({'n': n, 'releasedValue': companion_term(n),
                                'factors': [left, right], 'releasedCases': actual})
    summary = {
        'schema': 'aijade.p2a.mbpp260-statement.v1', 'taskId': 'Mbpp/260', 'planCommit': PLAN,
        'priorArchiveCommit': PRIOR, 'executionCodeCommit': git('rev-parse', 'HEAD'),
        'verifiedAt': datetime.now(timezone.utc).isoformat(), 'newModelCalls': 0,
        'originalSource': {'url': GOOGLE_URL, 'commit': GOOGLE_COMMIT,
                           'wholeFileSha256': digest_file(google_path),
                           'taskRecordSha256': digest_bytes(canonical(google).encode())},
        'releaseCodeSha256': digest_bytes((problem['prompt'] + problem['canonical_solution']).encode()),
        'mathematicalSource': {
            'url': PAPER_URL, 'doi': '10.4064/aa-38-2-129-140',
            'authors': ['Morris Newman', 'Daniel Shanks', 'H. C. Williams'],
            'title': 'Simple groups of square order and an interesting sequence of primes',
            'year': 1980, 'journal': 'Acta Arithmetica', 'volume': 38, 'pages': '129-140',
            'pdfSha256': digest_file(paper_path),
            'visuallyCheckedPrintPages': [129, 131],
            'definition': 'The special numbers are s_(2m+1), m >= 0, with s_n = ((1+sqrt(2))^n+(1-sqrt(2))^n)/2. The first prime indices are 3, 5, 7.',
        },
        'caseCount': len(rows), 'recurrenceAgreements': len(rows),
        'semanticCounts': dict(Counter(row['status'] for row in rows)),
        'counterexamples': counterexamples,
        'baseExamples': [{'n': n, 'releasedValue': companion_term(n)} for n in [3, 4, 5]],
        'decision': 'EXCLUDE_STATEMENT_CONFLICT',
        'authorReview': 'PENDING',
        'optionalFutureContract': 'For a nonnegative integer n, return s_n for s_0=s_1=1 and s_n=2*s_(n-1)+s_(n-2). Use a separately named task and exact BigInt output.',
        'sourceAuditMethod': 'AI-assisted source reading, visual primary-paper check and exact integer recomputation.',
    }
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'summary.json', summary)
    with (out / 'cases.jsonl').open('w') as stream:
        for row in rows:
            stream.write(canonical(row) + '\n')
    write_json(out / 'original-task.json', google)
    print(summary['caseCount'], summary['semanticCounts'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('google', type=Path)
    parser.add_argument('paper', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    verify(args.google, args.paper, args.out)
