"""Materialize the reviewed P2-A proposal with exact task, case and reference identities."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
P2A = HERE.parents[1]
JAVASCRIPT = P2A / 'javascript-port/2026-11-11'
REVIEW = P2A / 'candidate-review/2026-11-11'
sys.path.insert(0, str(JAVASCRIPT))
from prepare import canonical, digest_file, filename, make_ports, prepare, write_json
from variants import prepare_variants


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        yield from map(json.loads, stream)


def prepared_inputs(work):
    release, ports = work / 'rebuilt-release', work / 'rebuilt-ports'
    variant, variant_ports = work / 'rebuilt-variants', work / 'rebuilt-variant-ports'
    work.mkdir(parents=True, exist_ok=True)
    if not release.exists():
        prepare(release, JAVASCRIPT / 'results/recovery')
    if not ports.exists():
        make_ports(release, ports)
    if not variant.exists():
        if variant_ports.exists():
            raise ValueError('Variant preparation is partial. Use a fresh work directory.')
        prepare_variants(JAVASCRIPT / 'results/semantic', variant, variant_ports)
    locks = load(JAVASCRIPT / 'input-lock.json')
    for pack, source, population in [
        (release, ports, 'static_direct_425'),
        (variant, variant_ports, 'exact_arithmetic_variants_4'),
    ]:
        lock = locks[population]
        assert digest_file(pack / 'manifest.json') == lock['packSha256']
        assert digest_file(source / 'ports.json') == lock['portsSha256']
    return release, ports, variant, variant_ports


def export(work, out):
    release, ports, variant, variant_ports = prepared_inputs(work)
    statements = list(rows(REVIEW / 'results/review/candidate-statements.jsonl'))
    decisions = list(rows(REVIEW / 'results/review/task-decisions.jsonl'))
    proposed = {row['proposedCandidateId']: row for row in decisions if row['proposed']}
    assert len(proposed) == len(statements) == 422
    cases = {}
    for row in rows(REVIEW / 'results/review/case-decisions.jsonl.gz'):
        if row['proposed']:
            cases[(row['proposedCandidateId'], tuple(row['sourceCase']))] = row
    assert len(cases) == 115185
    release_tasks = {row['taskId']: row for row in load(release / 'manifest.json')['tasks']}
    variant_tasks = {row['taskId']: row for row in load(variant / 'manifest.json')['tasks']}
    source_ports = {row['taskId']: row for row in load(ports / 'ports.json')}
    source_variants = {row['taskId']: row for row in load(variant_ports / 'ports.json')}
    out.mkdir(parents=True, exist_ok=False)
    for directory in ['cases', 'references']:
        (out / directory).mkdir()
    runtime = JAVASCRIPT / 'results/release/source/python-semantics.js'
    original_receipt = load(JAVASCRIPT / 'results/receipt.json')
    assert digest_file(runtime) == original_receipt['artifactSha256']['results/release/source/python-semantics.js']
    shutil.copyfile(runtime, out / 'runtime.js')
    manifest = {
        'schema': 'aijade.p2a.execution-bank.v1', 'authorReview': 'PENDING',
        'sourceArchiveCommit': '49e86ba10be22d816e9b438c8801ff1c25d04da0',
        'proposalSha256': digest_file(REVIEW / 'results/review/summary.json'),
        'candidateStatementsSha256': digest_file(REVIEW / 'results/review/candidate-statements.jsonl'),
        'candidateDecisionsSha256': digest_file(REVIEW / 'results/review/case-decisions.jsonl.gz'),
        'runtime': {'file': 'runtime.js', 'sha256': digest_file(runtime)}, 'tasks': [],
    }
    book = [
        '# P2-A candidate statements for author review', '',
        'This book contains the 422 proposed statements and calling contracts. Author decisions are pending. '
        'The sortable task checklist and per-case decisions remain in the candidate-review archive. '
        'Each task defines a top-level solve callable and receives freshly parsed arguments.', '',
    ]
    with gzip.open(out / 'case-map.jsonl.gz', 'wt', encoding='utf-8') as mapped:
        for statement in statements:
            tid = statement['taskId']
            decision = proposed[tid]
            exact = tid in variant_tasks
            pack, source = (variant, variant_ports) if exact else (release, ports)
            inventory = variant_tasks[tid] if exact else release_tasks[tid]
            origin = source_variants[tid] if exact else source_ports[tid]
            stem = filename(tid)
            fixture_path = pack / 'cases' / (stem + '.json')
            assert digest_file(fixture_path) == inventory['taskFileSha256']
            original = load(fixture_path)
            assert len(original['cases']) == len(inventory['caseKeys'])
            keyed = {tuple(key['case']): (key, case) for key, case in zip(inventory['caseKeys'], original['cases'])}
            retained = decision['retainedCaseIds']
            chosen = []
            for index, identity in enumerate(retained):
                expected = cases[(tid, tuple(identity))]
                key, case = keyed[tuple(identity)]
                input_sha = hashlib.sha256(case['args'].encode()).hexdigest()
                expected_sha = hashlib.sha256(case['expected'].encode()).hexdigest()
                tolerance = case.get('publicFloatTolerance', False)
                assert input_sha == key['inputSha256'] == expected['candidateInputSha256']
                assert expected_sha == key['expectedSha256'] == expected['candidateExpectedSha256']
                assert tolerance == key['floatTolerance']
                assert expected['candidateJintOutcome'] == 'PASS'
                chosen.append(case)
                mapped.write(canonical({
                    'taskId': tid, 'sourceTaskId': decision['sourceTaskId'], 'sourceCase': identity,
                    'index': index, 'inputSha256': input_sha, 'expectedSha256': expected_sha,
                    'floatTolerance': tolerance,
                }) + '\n')
            fixture = {
                'taskId': tid, 'statement': statement['statement'], 'contract': statement['contract'], 'cases': chosen,
            }
            target = out / 'cases' / (stem + '.json')
            target.write_text(canonical(fixture) + '\n', encoding='utf-8')
            reference = source / (stem + '.js')
            assert digest_file(reference) == origin['sha256']
            target_reference = out / 'references' / reference.name
            shutil.copyfile(reference, target_reference)
            manifest['tasks'].append({
                'taskId': tid, 'sourceTaskId': decision['sourceTaskId'], 'dataset': decision['dataset'],
                'taskFile': str(target.relative_to(out)), 'taskSha256': digest_file(target),
                'referenceFile': str(target_reference.relative_to(out)),
                'referenceSha256': digest_file(target_reference), 'caseCount': len(chosen),
                'retainedBaseCases': statement['retainedBaseCases'], 'retainedPlusCases': statement['retainedPlusCases'],
                'statementSha256': statement['statementSha256'], 'proposedDisposition': decision['disposition'],
            })
            book.extend([
                '## ' + tid, '', statement['statement'], '', statement['contract'], '',
                f"Source task {decision['sourceTaskId']}. Retained base cases {statement['retainedBaseCases']}. "
                f"Retained extended cases {statement['retainedPlusCases']}.", '',
            ])
    assert len(manifest['tasks']) == 422 and sum(row['caseCount'] for row in manifest['tasks']) == 115185
    content_digest = hashlib.sha256()
    with gzip.open(out / 'case-map.jsonl.gz', 'rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            content_digest.update(block)
    manifest['caseMapContentSha256'] = content_digest.hexdigest()
    manifest['datasetCounts'] = dict(Counter(row['dataset'] for row in manifest['tasks']))
    (out / 'candidate-statements.md').write_text('\n'.join(book), encoding='utf-8')
    manifest['statementBookSha256'] = digest_file(out / 'candidate-statements.md')
    write_json(out / 'manifest.json', manifest)
    print('Exported', len(manifest['tasks']), 'tasks and', len(cases), 'cases.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    export(args.work.resolve(), args.out.resolve())
