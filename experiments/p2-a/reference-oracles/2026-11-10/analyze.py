"""Validate raw reference coverage/types and compare the two fixed process passes."""
import argparse
from collections import Counter, defaultdict
import copy
import gzip
import hashlib
import json
from pathlib import Path

from oracle_core import (canonical, comparator_requirements, count_types, digest_file,
                         js_value, load_deserializer, read_problems, source_json, typed)

HERE = Path(__file__).resolve().parent


def read_jsonl(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            yield line.encode(), json.loads(line)


def validate_rows(records, dataset, problem, complete=True):
    """Also used on artificial rejection cases; never calls a canonical function."""
    task_id = problem['task_id']
    expected_hash = hashlib.sha256(source_json(problem).encode()).hexdigest()
    assert records and records[0]['kind'] == 'begin'
    begin = records[0]
    assert begin['taskId'] == task_id and begin['dataset'] == dataset and begin['problemSha256'] == expected_hash
    assert begin['codeSha256'] == hashlib.sha256((problem['prompt']+problem['canonical_solution']).encode()).hexdigest()
    deserialize, fn_sha = load_deserializer(HERE/'upstream')
    assert begin['deserializerFunctionSha256'] == fn_sha
    assert begin['comparatorRequirements'] == comparator_requirements(dataset, problem, HERE/'upstream')
    assert begin['hashSeed'] == '0' and begin['namespacePerPartition'] and begin['argumentsDeepcopiedPerCall']
    expected = []
    for partition in ['base', 'plus']:
        raw = copy.deepcopy(problem[partition+'_input'])
        native = deserialize(task_id, copy.deepcopy(raw)) if dataset == 'MBPP+' else copy.deepcopy(raw)
        expected.extend((partition, i, raw[i], native[i]) for i in range(len(raw)))
    rows = [r for r in records[1:] if r['kind'] == 'case']
    ends = [r for r in records[1:] if r['kind'] == 'end']
    assert all(r['kind'] in ['case', 'end'] for r in records[1:])
    assert len(rows) <= len(expected) and len(ends) <= 1
    if complete:
        assert len(rows) == len(expected) and len(ends) == 1 and records[-1]['kind'] == 'end'
        assert ends[0]['counts'] == {'base': len(problem['base_input']), 'plus': len(problem['plus_input'])}
    flags, root_types, nested_types, statuses = Counter(), Counter(), Counter(), Counter()
    representable = True
    comparable = True
    semantic = hashlib.sha256()
    for record, (partition, index, raw, native) in zip(rows, expected):
        assert record['taskId'] == task_id and record['dataset'] == dataset
        assert record['partition'] == partition and record['index'] == index, 'Missing, duplicate or reordered case'
        assert record['serializedArgsJson'] == json.dumps(raw, ensure_ascii=False, separators=(',', ':'))
        native_tag, native_flags = typed(native)
        assert record['input'] == native_tag and record['inputFlags'] == sorted(native_flags)
        statuses[record['status']] += 1
        for flag in record['inputFlags']+record['outputFlags']:
            flags[flag] += 1
        try:
            js_value(record['input'])
            if record['status'] == 'OK':
                js_value(record['output'])
            else:
                assert record['status'] == 'REFERENCE_EXCEPTION' and 'error' in record
                representable = False
        except ValueError:
            representable = False
        if record['status'] == 'OK':
            tag = record['output']
            root_types[tag['t']] += 1
            nested = count_types(tag)
            nested_types.update(nested)
            if nested['unsupported'] or nested['cycle']:
                comparable = False
        semantic.update((canonical(record)+'\n').encode())
    native_assertions = ends[0]['nativeAssertions'] if ends else {'status': 'NOT_REACHED'}
    semantic.update(canonical(native_assertions).encode())
    return {'taskId': task_id, 'dataset': dataset, 'caseRows': len(rows), 'expectedCases': len(expected),
            'missingCases': len(expected)-len(rows), 'states': dict(statuses), 'flags': dict(flags),
            'rootOutputTypes': dict(root_types), 'nestedOutputTypes': dict(nested_types),
            'nativeAssertions': native_assertions, 'allValuesComparable': comparable,
            'jsonProjectionRepresentable': representable and len(rows) == len(expected),
            'comparatorRequirements': begin['comparatorRequirements'], 'semanticSha256': semantic.hexdigest()}


def one_pass(folder, order):
    tasks = [row for _, row in read_jsonl(folder/'tasks.jsonl')]
    assert [t['taskId'] for t in tasks] == [p['task_id'] for _, p in order[:len(tasks)]]
    out = {}
    pending = []
    cursor = 0

    def finish(records, index):
        assert index < len(tasks)
        execution = tasks[index]
        dataset, problem = order[index]
        assert records[0][1]['taskId'] == execution['taskId'] == problem['task_id']
        if not execution['malformedPartialOutput']:
            actual = hashlib.sha256(b''.join(raw for raw, _ in records)).hexdigest()
            assert actual == execution['stdoutSha256'], 'Changed raw task stream'
        result = validate_rows([row for _, row in records], dataset, problem, execution['status'] == 'COMPLETE')
        result['execution'] = execution
        return result

    for raw, row in read_jsonl(folder/'rows.jsonl.gz'):
        if row['kind'] == 'begin':
            if pending:
                result = finish(pending, cursor)
                out[result['taskId']] = result
                cursor += 1
                pending = []
            assert row['taskId'] not in out, 'Duplicate task'
        assert pending or row['kind'] == 'begin'
        assert not pending or row['taskId'] == pending[0][1]['taskId']
        pending.append((raw, row))
    if pending:
        result = finish(pending, cursor)
        out[result['taskId']] = result
    assert len(tasks) == len(out)
    return out


def analyze(folder):
    folder = Path(folder)
    order = read_problems(HERE/'inputs')
    execution = json.loads((folder/'execution.json').read_text())
    assert execution['schema'] == 'aijade.p2a.reference.execution.v1'
    assert execution['newModelCalls'] == 0
    assert execution['inputOrderAmendmentCommit'] == '9c755f06ad3ccd9e3ed9d86e633e535cb5002a4f'
    passes = {str(n): one_pass(folder/f'pass-{n}', order if n == 1 else list(reversed(order))) for n in [1, 2] if (folder/f'pass-{n}').exists()}
    screen = json.loads((HERE.parents[1]/'evalplus-compatibility.json').read_text())['datasets']
    classes = {r['taskId']: r['class'] for ds in screen.values() for r in ds['perTask']}
    ledger = []
    by_dataset = {}
    for dataset, problem in order:
        task_id = problem['task_id']
        a, b = passes.get('1', {}).get(task_id), passes.get('2', {}).get(task_id)
        complete = bool(a and b and a['execution']['status'] == b['execution']['status'] == 'COMPLETE')
        comparable = bool(a and b and a['allValuesComparable'] and b['allValuesComparable'])
        equal = (a['semanticSha256'] == b['semanticSha256']) if complete and comparable else None
        criteria = {'bothPassesComplete': complete,
                    'noReferenceExceptions': bool(a and b and not a['states'].get('REFERENCE_EXCEPTION') and not b['states'].get('REFERENCE_EXCEPTION')),
                    'nativeBaseAssertionsPass': bool(a and b and a['nativeAssertions']['status'] == b['nativeAssertions']['status'] == 'PASS'),
                    'repeatSemanticsEqual': equal is True,
                    'jsonProjectionRepresentable': bool(a and b and a['jsonProjectionRepresentable'] and b['jsonProjectionRepresentable']),
                    'noUnresolvedComparator': bool(a and b and not a['comparatorRequirements'] and not a['flags'].get('flat-float-output-needs-upstream-tolerance') and not b['flags'].get('flat-float-output-needs-upstream-tolerance'))}
        row = {'dataset': dataset, 'taskId': task_id, 'staticClass': classes[task_id], 'criteria': criteria,
               'mechanicalPreparationCriteriaMet': all(criteria.values()),
               'readyAmongStaticDirect': classes[task_id] == 'direct' and all(criteria.values()),
               'repeatComparison': equal, 'passes': {'1': a, '2': b}}
        ledger.append(row)
        stats = by_dataset.setdefault(dataset, {'tasks': 0, 'staticClasses': {}, 'bothPassesComplete': 0, 'sameComparableSemantics': 0,
                                               'mechanicalPreparationCriteriaMet': 0, 'readyAmongStaticDirect': 0, 'perPass': {}})
        stats['tasks'] += 1
        category = stats['staticClasses'].setdefault(classes[task_id], {'tasks': 0, 'ready': 0})
        category['tasks'] += 1; category['ready'] += int(row['readyAmongStaticDirect'])
        stats['bothPassesComplete'] += int(complete)
        stats['sameComparableSemantics'] += int(equal is True)
        stats['mechanicalPreparationCriteriaMet'] += int(row['mechanicalPreparationCriteriaMet'])
        stats['readyAmongStaticDirect'] += int(row['readyAmongStaticDirect'])
        for n, result in [('1', a), ('2', b)]:
            sums = stats['perPass'].setdefault(n, {'attemptedTasks': 0, 'completeTasks': 0, 'cases': 0, 'referenceExceptions': 0,
                                                'nativeAssertionsPass': 0, 'nativeAssertionsFail': 0,
                                                'missingCases': 0, 'rootOutputTypes': Counter(), 'flags': Counter()})
            if result:
                sums['attemptedTasks'] += 1; sums['completeTasks'] += int(result['execution']['status'] == 'COMPLETE')
                sums['cases'] += result['caseRows']; sums['missingCases'] += result['missingCases']
                sums['referenceExceptions'] += result['states'].get('REFERENCE_EXCEPTION', 0)
                sums['nativeAssertionsPass'] += int(result['nativeAssertions']['status'] == 'PASS')
                sums['nativeAssertionsFail'] += int(result['nativeAssertions']['status'] == 'FAIL')
                sums['rootOutputTypes'].update(result['rootOutputTypes']); sums['flags'].update(result['flags'])
            else:
                sums['missingCases'] += len(problem['base_input'])+len(problem['plus_input'])
    return {'schema': 'aijade.p2a.reference.summary.v1', 'executionCodeCommit': execution['executionCodeCommit'],
            'planCommit': execution['planCommit'], 'sourceExecutionStatus': execution['status'], 'newModelCalls': 0,
            'inputOrderAmendmentCommit': execution['inputOrderAmendmentCommit'],
            'taskCount': len(order), 'plannedInputCallsPerPass': 165268, 'datasets': by_dataset, 'ledger': ledger,
            'scope': 'Finite Python reference/preparation ledger; not a JavaScript port, independent semantic oracle, device qualification, model pilot or verifier-rate estimate.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.folder)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'datasets': result['datasets'], 'scope': result['scope']}, indent=2))
