"""Independently check the candidate join, retained cases and lossless reference stream."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
from itertools import combinations_with_replacement
import json
from pathlib import Path

from recover255 import (CHUNK, HERE, JAVASCRIPT, REFERENCE, ROOT, canonical, digest_bytes,
                        digest_file, read_jsonl, source_task, validate_archive, write_json)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def check_case_decisions(cases, tasks, original, semantic, variants, variant_exclusions):
    expected_keys = set(original)
    observed_keys = {(row['sourceTaskId'], tuple(row['sourceCase'])) for row in cases}
    assert len(cases) == len(observed_keys) and observed_keys == expected_keys
    for row in cases:
        tid, identity = row['sourceTaskId'], tuple(row['sourceCase'])
        decision = tasks[tid]
        candidate_id = decision['proposedCandidateId']
        original_row = original[(tid, identity)]
        assert row['authorDecision'] == 'PENDING' and row['releasedJintOutcome'] == original_row['outcome']
        expected_include = decision['proposed']
        if expected_include and tid in variant_exclusions:
            expected_include = identity not in variant_exclusions[tid]
            source = variants.get((candidate_id, identity))
        else:
            state = semantic.get((tid, identity), {}).get('status')
            expected_include = expected_include and state in (None, 'AGREES')
            source = original_row
        assert row['proposed'] == expected_include
        if expected_include:
            assert source and source['outcome'] == row['candidateJintOutcome'] == 'PASS'
            assert row['proposedCandidateId'] == candidate_id
            assert source['inputSha256'] == row['candidateInputSha256']
            assert source['expectedSha256'] == row['candidateExpectedSha256']
        else:
            assert row['proposedCandidateId'] is None


def check_decisions(decisions, source_ids):
    observed = {row['sourceTaskId']: row for row in decisions}
    assert len(observed) == len(decisions) and set(observed) == source_ids
    assert all(row['authorDecision'] == 'PENDING' for row in decisions)
    return observed


def check_reference(directory):
    rows = validate_archive(directory)
    counts = []
    for row in rows:
        arguments = row['typedArguments']['items']
        pool = arguments[0]['items']
        length = arguments[1]
        width = int(length['v'])
        assert width == row['tupleArity']
        alphabet = {canonical(value): index for index, value in enumerate(row['alphabet'])}
        token_pool = [alphabet[canonical(value)] for value in pool]
        digest = hashlib.sha256()
        block = bytearray()
        total = 0
        for values in combinations_with_replacement(token_pool, width):
            block.extend(values)
            total += 1
            if len(block) >= CHUNK:
                digest.update(block)
                block.clear()
        digest.update(block)
        assert total == row['tupleCount']
        assert digest.hexdigest() == row['valueStreamSha256']
        counts.append(total)
    return {'caseRows': len(rows), 'tuples': sum(counts), 'allCaseStreamsDecodedAndRecomputed': True}


def expect_rejection(fn):
    try:
        fn()
    except AssertionError:
        return
    raise AssertionError('The deliberately corrupted record was accepted.')


def verify(packet, output):
    receipt = load(packet / 'receipt.json')
    for name, expected in receipt['artifactSha256'].items():
        assert digest_file(HERE / name) == expected, name
    for name, expected in receipt['priorDependencySha256'].items():
        assert digest_file(ROOT / name) == expected, name
    review = packet / 'review'
    summary = load(review / 'summary.json')
    decisions = list(read_jsonl(review / 'task-decisions.jsonl'))
    screen = load(ROOT / 'experiments/p2-a/evalplus-compatibility.json')
    static = {row['taskId']: row for dataset in screen['datasets'].values() for row in dataset['perTask']}
    tasks = check_decisions(decisions, set(static))
    direct = {tid for tid in static if static[tid]['class'] == 'direct'}
    excluded = {'Mbpp/255', 'Mbpp/260', 'HumanEval/132'}
    assert {tid for tid, row in tasks.items() if row['proposed']} == direct - excluded
    for tid, row in tasks.items():
        assert row['staticClass'] == static[tid]['class'] and row['staticReasons'] == static[tid]['reasons']
    variant_specs = list(read_jsonl(JAVASCRIPT / 'results/variants/statements.jsonl'))
    variant_exclusions = {row['releaseTaskId']: set(map(tuple, row['excludedSourceCases'])) for row in variant_specs}
    semantic = {(row['taskId'], tuple(row['case'])): row
                for row in read_jsonl(JAVASCRIPT / 'results/semantic/semantic-cases.jsonl.gz')}
    original = {(row['taskId'], tuple(row['case'])): row
                for row in read_jsonl(JAVASCRIPT / 'results/release/cases.jsonl.gz')}
    variants = {(row['taskId'], tuple(row['case'])): row
                for row in read_jsonl(JAVASCRIPT / 'results/variants/cases.jsonl.gz')}
    cases = list(read_jsonl(review / 'case-decisions.jsonl.gz'))
    check_case_decisions(cases, tasks, original, semantic, variants, variant_exclusions)
    statements = list(read_jsonl(review / 'candidate-statements.jsonl'))
    proposed_ids = {row['proposedCandidateId'] for row in decisions if row['proposed']}
    assert len(statements) == len(proposed_ids) and {row['taskId'] for row in statements} == proposed_ids
    for row in statements:
        assert row['authorDecision'] == 'PENDING'
        assert row['statementSha256'] == digest_bytes(row['statement'].encode())
        task = tasks[row['sourceTaskId']]
        assert row['taskId'] == task['proposedCandidateId'] and task['proposed']
        expected = [case['sourceCase'] for case in cases
                    if case['sourceTaskId'] == row['sourceTaskId'] and case['proposed']]
        assert task['retainedCaseIds'] == expected
        assert row['retainedBaseCases'] == sum(part == 'base' for part, _ in expected)
        assert row['retainedPlusCases'] == sum(part == 'plus' for part, _ in expected)
    assert summary['sourceTasks'] == len(tasks) == 542
    assert summary['candidateTasks'] == len(statements)
    assert summary['candidateCases'] == sum(row['proposed'] for row in cases)
    assert summary['taskDispositions'] == dict(Counter(row['disposition'] for row in decisions))
    assert summary['caseDispositions'] == dict(Counter(row['decision'] for row in cases))
    assert summary['formalAuthorReview'] == 'PENDING' and summary['newModelCalls'] == 0

    reference = check_reference(packet / 'recovery')
    native = load(packet / 'recovery/summary.json')
    assert native['status'] == 'PASS' and reference['caseRows'] == native['caseRows'] == 112
    for route in ['native', 'successor']:
        record = native['passes'][route]
        assert record['exitCode'] == 0 and not record['stop']
        assert record['stdoutSha256'] == digest_file(packet / 'recovery/values.gz')
        assert record['catalogSha256'] == digest_file(packet / 'recovery/cases.jsonl')
    jint = load(packet / 'jint255/summary.json')
    assert len(jint['cases']) == 112 and len({tuple(row['case']) for row in jint['cases']}) == 112
    assert jint['caseOutcomes'] == dict(Counter(row['outcome'] for row in jint['cases']))
    assert not jint['completeAgreement'] and jint['candidateDecision'] == 'EXCLUDE_BOUNDED_JINT_COVERAGE'
    processes = list(read_jsonl(packet / 'jint255/processes.jsonl.gz'))
    assert len(processes) == sum(row['outcome'] != 'TRANSPORT_LIMIT' for row in jint['cases'])
    for row in processes:
        assert digest_bytes(row['stdout'].encode()) == row['process']['stdoutSha256']
        assert digest_bytes(row['stderr'].encode()) == row['process']['stderrSha256']
    nsw = list(read_jsonl(packet / 'nsw260/cases.jsonl'))
    nsw_summary = load(packet / 'nsw260/summary.json')
    assert nsw_summary['semanticCounts'] == dict(Counter(row['status'] for row in nsw))
    assert nsw_summary['caseCount'] == nsw_summary['recurrenceAgreements'] == len(nsw) == 107
    for row in nsw:
        argument = row['input']['items'][0]
        ordinal = int(argument['v'])
        a, b = 1, 1
        for _ in range(ordinal):
            a, b = b, 2*b + a
        observed = row['releasedOutput']
        expected = int(observed['hex'], 16) if 'hex' in observed else int(observed['v'])
        assert a == expected
        assert row['status'] == ('OUTSIDE_DOMAIN' if argument['t'] == 'bool' or ordinal < 1 else 'STATEMENT_CONFLICT')
    blocked_ids = {row['taskId'] for row in read_jsonl(JAVASCRIPT / 'results/blocked-tasks.jsonl')}
    recount = Counter(row['semanticStatus'] for row in cases if row['sourceTaskId'] in blocked_ids)
    assert summary['updatedBlockedSemanticCounts'] == dict(recount)

    sample = next(i for i, row in enumerate(cases) if row['proposed'])
    changed = cases.copy()
    changed[sample] = {**changed[sample], 'candidateExpectedSha256': '0'*64}
    expect_rejection(lambda: check_case_decisions(changed, tasks, original, semantic, variants, variant_exclusions))
    excluded_index = next(i for i, row in enumerate(cases) if row['sourceTaskId'] == 'Mbpp/255')
    changed = cases.copy()
    changed[excluded_index] = {**changed[excluded_index], 'proposed': True}
    expect_rejection(lambda: check_case_decisions(changed, tasks, original, semantic, variants, variant_exclusions))
    expect_rejection(lambda: check_decisions(decisions[:-1], set(static)))
    result = {'status': 'PASS', 'verifiedAt': datetime.now(timezone.utc).isoformat(),
              'candidateTasks': summary['candidateTasks'], 'candidateCases': summary['candidateCases'],
              'sourceTasks': len(tasks), 'directCaseRows': len(cases), 'reference': reference,
              'negativeChecks': ['changed_expected_hash', 'included_excluded_task', 'missing_task'],
              'artifactCount': len(receipt['artifactSha256']),
              'priorDependencyCount': len(receipt['priorDependencySha256']),
              'authorReview': summary['formalAuthorReview']}
    if output:
        write_json(output, result)
    print(canonical(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--packet', type=Path, default=HERE / 'results')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    verify(args.packet, args.out)
