"""Build task and case inclusion proposals from the pinned preparation evidence."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sys

from recover255 import (HERE, JAVASCRIPT, PLAN, PRIOR, REFERENCE, ROOT, canonical,
                        digest_bytes, digest_file, git, read_jsonl, source_task, write_json)

sys.path.insert(0, str(JAVASCRIPT))
from prepare import source_statement
from oracle_core import read_problems

DOMAIN_NOTES = {
    'HumanEval/8': 'Each list element represents an integer. Boolean elements are excluded.',
    'HumanEval/55': 'The ordinal is a nonnegative integer value. Boolean inputs are excluded.',
    'HumanEval/63': 'The ordinal is a nonnegative integer value. Boolean inputs are excluded.',
    'Mbpp/17': 'The side is a finite nonnegative numeric value. Boolean inputs are excluded.',
    'Mbpp/80': 'The ordinal is a nonnegative integer value. Boolean inputs are excluded.',
    'Mbpp/145': 'The input is a nonempty sequence of finite numeric values. Boolean elements are excluded.',
    'Mbpp/171': 'The side is a finite nonnegative numeric value. Boolean inputs are excluded.',
    'Mbpp/234': 'The side is a finite nonnegative numeric value. Boolean inputs are excluded.',
    'Mbpp/264': 'Human age is a finite nonnegative numeric value. Boolean inputs are excluded.',
    'Mbpp/266': 'The side is a finite nonnegative numeric value. Boolean inputs are excluded.',
    'Mbpp/268': 'The ordinal is a positive integer value. Boolean inputs are excluded.',
    'Mbpp/271': 'The count is a nonnegative integer value. Boolean inputs are excluded.',
    'Mbpp/274': 'The exponent is a positive integer value. Boolean inputs are excluded.',
    'Mbpp/441': 'The side is a finite nonnegative numeric value. Boolean inputs are excluded.',
    'Mbpp/577': 'The factorial argument is a nonnegative integer value. Boolean inputs are excluded.',
    'Mbpp/592': 'The ordinal is a positive integer value. Boolean inputs are excluded.',
    'Mbpp/597': 'Both finite numeric arrays are sorted in nondecreasing order. The rank is an integer value from one through their combined length. Boolean inputs are excluded.',
    'Mbpp/608': 'The ordinal is a nonnegative integer value. Boolean inputs are excluded.',
    'Mbpp/752': 'The ordinal is a nonnegative integer value. Boolean inputs are excluded.',
    'Mbpp/767': 'The list and target contain finite numeric values. Boolean values are excluded.',
    'Mbpp/785': 'The input string is a literal tuple of integers. Boolean tuple members are excluded.',
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def artifact_hashes():
    receipt = load(JAVASCRIPT / 'results/receipt.json')
    for name, expected in receipt['artifactSha256'].items():
        assert digest_file(JAVASCRIPT / name) == expected, name
    return len(receipt['artifactSha256'])


def build(pack, recovery, jint, nsw, out):
    frozen = load(JAVASCRIPT / 'results/release/execution.json')
    assert digest_file(pack / 'manifest.json') == frozen['packSha256']
    assert artifact_hashes() > 100
    manifest = load(pack / 'manifest.json')
    specs = {row['taskId']: row for row in manifest['tasks']}
    release = {row['taskId']: row for row in load(JAVASCRIPT / 'results/release/summary.json')['tasks']}
    blocked = {row['taskId']: row for row in read_jsonl(JAVASCRIPT / 'results/blocked-tasks.jsonl')}
    semantic_rows = list(read_jsonl(JAVASCRIPT / 'results/semantic/semantic-cases.jsonl.gz'))
    semantic = {(row['taskId'], tuple(row['case'])): row for row in semantic_rows}
    assert len(semantic_rows) == len(semantic) == 9113
    release_cases = list(read_jsonl(JAVASCRIPT / 'results/release/cases.jsonl.gz'))
    case_index = {(row['taskId'], tuple(row['case'])): row for row in release_cases}
    assert len(case_index) == len(release_cases) == 116753
    variant_specs = {row['releaseTaskId']: row for row in read_jsonl(JAVASCRIPT / 'results/variants/statements.jsonl')}
    variant_tasks = {row['releaseTaskId']: row for row in load(JAVASCRIPT / 'results/variants/summary.json')['tasks']}
    variant_cases = {(row['taskId'], tuple(row['case'])): row
                     for row in read_jsonl(JAVASCRIPT / 'results/variants/cases.jsonl.gz')}
    screen = load(ROOT / 'experiments/p2-a/evalplus-compatibility.json')
    classes = {row['taskId']: row for dataset in screen['datasets'].values() for row in dataset['perTask']}
    problems = read_problems(REFERENCE / 'inputs')
    assert len(problems) == len(classes) == 542
    recovered = load(recovery / 'summary.json')
    assert recovered['status'] == 'PASS' and recovered['recoveredPlusCases'] == 109
    bounded = load(jint / 'summary.json')
    assert len(bounded['cases']) == 112 and not bounded['completeAgreement']
    nsw_summary = load(nsw / 'summary.json')
    nsw_rows = {tuple(row['case']): row for row in read_jsonl(nsw / 'cases.jsonl')}
    assert nsw_summary['caseCount'] == len(nsw_rows) == 107
    new_255_rows = {tuple(row['case']): row for row in read_jsonl(recovery / 'native/cases.jsonl')}
    new_255_jint = {tuple(row['case']): row for row in bounded['cases']}
    assert len(new_255_rows) == len(new_255_jint) == 112

    decisions, statements, case_decisions = [], [], []
    updated_semantics = Counter()
    for dataset, problem in problems:
        tid = problem['task_id']
        static = classes[tid]
        spec = specs.get(tid)
        _, original_statement, _ = source_statement(problem)
        all_ids = [(part, i) for part in ['base', 'plus']
                   for i in range(len(problem[part + '_input']))]
        decision = {
            'sourceTaskId': tid, 'dataset': dataset, 'entryPoint': problem['entry_point'],
            'originalStatement': original_statement, 'staticClass': static['class'],
            'staticReasons': static['reasons'], 'releasedCases': len(all_ids),
            'proposedCandidateId': None, 'proposed': False, 'authorDecision': 'PENDING',
            'retainedCaseIds': [], 'excludedCaseIds': [], 'reasonCodes': [], 'evidence': [],
            'focusedCaseSemantics': 'AI_ASSISTED' if tid in blocked else 'AUTHOR_REVIEW_PENDING',
        }
        if static['class'] != 'direct':
            decision.update(disposition='EXCLUDE_OUTSIDE_PORT_POPULATION',
                            reasonCodes=['STATIC_' + item for item in static['reasons']],
                            explanation='Outside the fixed direct-port population. The recorded type or comparator conditions require a separate adapter or audit.')
            decision['evidence'] = ['experiments/p2-a/evalplus-compatibility.json']
            decisions.append(decision)
            continue
        assert spec and len(all_ids) == release[tid]['planned']
        decision['evidence'] = ['javascript-port/2026-11-11/results/release/cases.jsonl.gz']
        decision['callingContract'] = spec['contract']
        decision['mode'] = spec['mode']
        decision['releasedJintCounts'] = release[tid]['counts']
        decision['originalStatementSha256'] = spec['originalStatementSha256']
        assert not spec['projectionCollisions']
        if tid == 'Mbpp/255':
            disposition = 'EXCLUDE_BOUNDED_JINT_COVERAGE'
            reasons = ['FULL_REFERENCE_RECOVERED', 'INCOMPLETE_BOUNDED_JINT_CONFORMANCE']
            explanation = 'All 109 missing plus references are restored. The full original case set exceeds the declared transport or sandbox limits. The entire task is excluded from this proposal.'
        elif tid == 'Mbpp/260':
            disposition = 'EXCLUDE_STATEMENT_CONFLICT'
            reasons = ['RECURRENCE_IS_NOT_PRIME_RANK']
            explanation = 'The original Google prompt asks for prime rank. Its implementation and examples evaluate a different recurrence-index task. Exact matrix recomputation confirms the released values and the rank contradiction.'
        elif tid == 'HumanEval/132':
            disposition = 'EXCLUDE_STATEMENT_AMBIGUITY'
            reasons = ['SUBSEQUENCE_CONTIGUITY_AMBIGUITY']
            explanation = 'The linear contiguous interpretation has its own 1,014-case engineering result. The released wording says subsequence, with 30 differing outputs under an arbitrary-subsequence reading.'
        elif tid in variant_specs:
            disposition = 'REVIEW_EXACT_VARIANT'
            reasons = ['EXACT_MATHEMATICAL_SPECIFICATION', 'SEPARATE_VARIANT_IDENTITY']
            explanation = 'A separately identified exact arithmetic variant preserves the stated mathematical intent and has complete frozen Jint agreement. Its own domain exclusions and expected values remain explicit.'
        else:
            assert release[tid]['status'] == 'AGREES'
            assert release[tid]['counts'] == {'PASS': len(all_ids)}
            assert spec['projected'] == len(all_ids)
            outside = [identity for identity in all_ids
                       if semantic.get((tid, identity), {}).get('status') == 'OUTSIDE_DOMAIN']
            disposition = 'REVIEW_DOMAIN_FILTERED' if outside else 'REVIEW_RELEASED'
            reasons = ['COMPLETE_JINT_CONFORMANCE', 'COLLISION_FREE_PROJECTION']
            explanation = 'The proposed statement and calling contract are paired with complete frozen released-case agreement and task-specific value projection.'
            if outside:
                assert tid in DOMAIN_NOTES, tid
                reasons.append('EXPLICIT_DOMAIN_FILTER')
                explanation += ' Retain only cases satisfying the explicit proposed domain. Record each excluded original identity and its domain reason.'
        proposed = disposition.startswith('REVIEW_')
        candidate_id = variant_specs[tid]['taskId'] if tid in variant_specs else tid
        decision.update(disposition=disposition, reasonCodes=reasons, explanation=explanation,
                        proposed=proposed, proposedCandidateId=candidate_id if proposed else None)
        for identity in all_ids:
            original = case_index[(tid, identity)]
            old_semantic = semantic.get((tid, identity))
            semantic_status = old_semantic['status'] if old_semantic else 'AUTHOR_REVIEW_PENDING'
            domain_reason = old_semantic.get('detail', '') if old_semantic else ''
            source = original
            if tid == 'Mbpp/255':
                native = new_255_rows[identity]
                length_type = native['typedArguments']['items'][1]['t']
                semantic_status = 'OUTSIDE_DOMAIN' if length_type == 'bool' else 'AGREES'
                domain_reason = 'A mathematical combination length excludes boolean arguments.' if length_type == 'bool' else ''
            elif tid == 'Mbpp/260':
                semantic_status = nsw_rows[identity]['status']
                domain_reason = nsw_rows[identity]['reason']
            if tid in blocked:
                updated_semantics[semantic_status] += 1
            include = proposed
            case_reason = disposition
            if disposition == 'REVIEW_EXACT_VARIANT':
                include = identity not in map(tuple, variant_specs[tid]['excludedSourceCases'])
                case_reason = 'EXACT_VARIANT' if include else 'OUTSIDE_DOMAIN'
                if include:
                    source = variant_cases[(candidate_id, identity)]
                    assert source['outcome'] == 'PASS'
            elif tid in blocked and proposed:
                include = semantic_status == 'AGREES'
                case_reason = 'RELEASED_IN_DOMAIN' if include else semantic_status
                assert semantic_status in ['AGREES', 'OUTSIDE_DOMAIN'], (tid, identity)
            row = {
                'sourceTaskId': tid, 'sourceCase': list(identity),
                'proposedCandidateId': candidate_id if include else None,
                'proposed': include, 'decision': case_reason, 'semanticStatus': semantic_status,
                'reason': domain_reason if not include else '',
                'releasedJintOutcome': original['outcome'],
                'authorDecision': 'PENDING',
            }
            if include:
                row.update(candidateInputSha256=source['inputSha256'],
                           candidateExpectedSha256=source['expectedSha256'],
                           candidateJintOutcome=source['outcome'])
                assert source['outcome'] == 'PASS'
                decision['retainedCaseIds'].append(list(identity))
            else:
                decision['excludedCaseIds'].append(list(identity))
            if tid == 'Mbpp/255':
                row.update(referenceStatus='RECOVERED', recoveredValueStreamSha256=new_255_rows[identity]['valueStreamSha256'],
                           targetedJintOutcome=new_255_jint[identity]['outcome'])
            case_decisions.append(row)
        assert len(decision['retainedCaseIds']) + len(decision['excludedCaseIds']) == len(all_ids)
        if proposed:
            retained_partitions = {item[0] for item in decision['retainedCaseIds']}
            assert 'base' in retained_partitions
            if problem['plus_input']:
                assert 'plus' in retained_partitions
            else:
                decision['coverageNote'] = 'The pinned release contains base cases only.'
            if disposition == 'REVIEW_EXACT_VARIANT':
                variant = variant_specs[tid]
                statement, contract = variant['statement'], variant['contract']
                assert len(decision['retainedCaseIds']) == variant_tasks[tid]['planned']
                decision['evidence'].append('javascript-port/2026-11-11/results/variants/cases.jsonl.gz')
            else:
                statement, contract = spec['statement'], spec['contract']
                if tid in blocked:
                    statement += '\n' + blocked[tid]['semanticRule']
                if tid in DOMAIN_NOTES and decision['excludedCaseIds']:
                    statement += '\n' + DOMAIN_NOTES[tid]
            statements.append({'taskId': candidate_id, 'sourceTaskId': tid, 'statement': statement,
                               'contract': contract, 'proposedDisposition': disposition,
                               'authorDecision': 'PENDING',
                               'retainedBaseCases': sum(part == 'base' for part, _ in decision['retainedCaseIds']),
                               'retainedPlusCases': sum(part == 'plus' for part, _ in decision['retainedCaseIds']),
                               'statementSha256': digest_bytes(statement.encode())})
        decision['retainedCases'] = len(decision['retainedCaseIds'])
        decision['excludedCases'] = len(decision['excludedCaseIds'])
        decisions.append(decision)

    assert len(decisions) == len({row['sourceTaskId'] for row in decisions}) == 542
    assert len(case_decisions) == len({(row['sourceTaskId'], tuple(row['sourceCase'])) for row in case_decisions}) == 116753
    assert len(statements) == len({row['taskId'] for row in statements}) == sum(row['proposed'] for row in decisions)
    assert all(not row['proposed'] for row in decisions if row['sourceTaskId'] in ['Mbpp/255', 'Mbpp/260', 'HumanEval/132'])
    summary = {
        'schema': 'aijade.p2a.candidate-review.v1', 'planCommit': PLAN, 'priorArchiveCommit': PRIOR,
        'preparationCodeCommit': git('rev-parse', 'HEAD'),
        'createdAt': datetime.now(timezone.utc).isoformat(), 'newModelCalls': 0,
        'sourceTasks': len(decisions), 'directTasks': len(specs),
        'outsidePortPopulation': sum(row['staticClass'] != 'direct' for row in decisions),
        'candidateTasks': len(statements), 'candidateCases': sum(row['proposed'] for row in case_decisions),
        'excludedTasks': sum(not row['proposed'] for row in decisions),
        'directTaskExclusions': [row['sourceTaskId'] for row in decisions if row['staticClass'] == 'direct' and not row['proposed']],
        'taskDispositions': dict(Counter(row['disposition'] for row in decisions)),
        'caseDispositions': dict(Counter(row['decision'] for row in case_decisions)),
        'sourceTasksPerDataset': dict(Counter(row['dataset'] for row in decisions)),
        'candidateTasksPerDataset': dict(Counter(row['dataset'] for row in decisions if row['proposed'])),
        'previouslyBlockedTasks': len(blocked),
        'previouslyBlockedProposed': sum(row['proposed'] for row in decisions if row['sourceTaskId'] in blocked),
        'updatedBlockedSemanticCounts': dict(updated_semantics),
        'updatedBlockedSemanticCases': sum(updated_semantics.values()),
        'referenceRecovery': {'status': recovered['status'], 'cases': recovered['caseRows'],
                              'recoveredPlusCases': recovered['recoveredPlusCases'],
                              'totalTuples': recovered['totalTuples'],
                              'totalTupleElements': recovered['totalTupleElements'],
                              'compressedBytes': recovered['passes']['native']['compressedBytes'],
                              'nativeWallSeconds': recovered['passes']['native']['wallSeconds'],
                              'nativePeakRssBytes': recovered['passes']['native']['sampledPeakRssBytes'],
                              'executionCodeCommit': recovered['executionCodeCommit']},
        'mbpp255Jint': {'caseOutcomes': bounded['caseOutcomes'], 'completeAgreement': bounded['completeAgreement'],
                        'executionCodeCommit': bounded['executionCodeCommit']},
        'mbpp260': {'semanticCounts': nsw_summary['semanticCounts'],
                    'recurrenceAgreements': nsw_summary['recurrenceAgreements'],
                    'executionCodeCommit': nsw_summary['executionCodeCommit']},
        'formalAuthorReview': 'PENDING', 'difficultyPilot': 'NOT_RUN', 'precisionDesign': 'NOT_RUN',
        'scope': 'AI-assisted inclusion proposals and finite preparation checks. Author decisions are pending for every task.',
        'sourceSha256': {p.name: digest_file(p) for p in HERE.glob('*.py')},
    }
    assert summary['updatedBlockedSemanticCases'] == 9113
    out.mkdir(parents=True, exist_ok=False)
    for name, rows in [('task-decisions.jsonl', decisions), ('candidate-statements.jsonl', statements)]:
        with (out / name).open('w', encoding='utf-8') as stream:
            for row in rows:
                stream.write(canonical(row) + '\n')
    with gzip.open(out / 'case-decisions.jsonl.gz', 'wt', encoding='utf-8') as stream:
        for row in case_decisions:
            stream.write(canonical(row) + '\n')
    with (out / 'task-review.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        fields = ['sourceTaskId', 'dataset', 'entryPoint', 'staticClass', 'disposition', 'proposedCandidateId',
                  'releasedCases', 'retainedCases', 'excludedCases', 'focusedCaseSemantics', 'explanation', 'authorDecision']
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        writer.writerows(decisions)
    lines = [
        '# P2-A 候选任务逐题核读表', '',
        '每行对应一项原始任务。候选为作者核读提案，作者决定均待填写。完整题面和调用约定位于 candidate-statements.jsonl，纳入用例与逐条排除理由位于 task-decisions.jsonl 和 case-decisions.jsonl.gz。', '',
        '| 原任务 | 提案 | 纳入 / 原用例 | 依据 | 作者决定 |',
        '|---|---|---:|---|---|',
    ]
    for row in decisions:
        retained = row.get('retainedCases', 0)
        basis = ', '.join(row['staticReasons'] if row['staticClass'] != 'direct' else row['reasonCodes'])
        lines.append(f"| {row['sourceTaskId']} | {row['disposition']} | {retained} / {row['releasedCases']} | {basis} | 待核读 |")
    (out / 'task-review.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write_json(out / 'summary.json', summary)
    print(summary['candidateTasks'], summary['candidateCases'], summary['taskDispositions'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--pack', type=Path, required=True)
    parser.add_argument('--recovery', type=Path, required=True)
    parser.add_argument('--jint', type=Path, required=True)
    parser.add_argument('--nsw', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build(args.pack, args.recovery, args.jint, args.nsw, args.out)
