"""Typed public-reference records; no corpus code is executed by this module."""
import ast
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

SAFE_INT = 2**53 - 1
DATASETS = {
    'HumanEval+': ('HumanEvalPlus-v0.1.10.jsonl.gz', '272720b90ac375502c8ed23cd791c2a93dfb22a911641a494da74a426c09f101', 164, 1570, 122683),
    'MBPP+': ('MbppPlus-v0.2.0.jsonl.gz', 'af43697e8791c4c149bdfd6b489d8b5412507551ac20e28a439f650b8225db63', 378, 1174, 39841),
}
PIN = '26d6d00bb1fd0fa37f39c99d5290da67891d1c5e'


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def source_json(value):
    """Preserve release input constants (Mbpp/404 includes infinity); records stay strictly typed JSON."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=True)


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(part)
    return result.hexdigest()


def read_problems(folder):
    result = []
    for dataset, (name, expected, tasks, base, plus) in DATASETS.items():
        path = Path(folder)/name
        assert digest_file(path) == expected, 'Corpus digest mismatch: ' + name
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            rows = [json.loads(line) for line in stream]
        assert len(rows) == len({r['task_id'] for r in rows}) == tasks
        assert sum(len(r['base_input']) for r in rows) == base
        assert sum(len(r['plus_input']) for r in rows) == plus
        result.extend((dataset, row) for row in sorted(rows, key=lambda r: int(r['task_id'].split('/')[1])))
    return result


def load_deserializer(upstream):
    """Compile only the pinned function AST; the module's download/import code never runs."""
    path = Path(upstream)/'mbpp.py'
    source = path.read_text()
    module = ast.parse(source)
    fn = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'mbpp_deserialize_inputs')
    selected = ast.Module(body=[fn], type_ignores=[])
    scope = {}
    exec(compile(selected, str(path), 'exec'), scope)
    return scope[fn.name], digest_bytes(ast.get_source_segment(source, fn).encode())


def special_comparators(upstream):
    """Read literal lists from the official source, without importing its evaluator."""
    source = (Path(upstream)/'_special_oracle.py').read_text()
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return values


def comparator_requirements(dataset, problem, upstream):
    entry = problem['entry_point']
    labels = []
    special = special_comparators(upstream)
    if problem['atol']:
        labels.append('declared-float-tolerance')
    if dataset == 'MBPP+':
        if entry in special['MBPP_OUTPUT_NOT_NONE_TASKS']:
            labels.append('output-is-not-None')
        if entry in special['MBPP_OUTPUT_SET_EQ_TASKS']:
            labels.append('set-equality')
        if entry in ['are_equivalent', 'sum_div', 'surface_Area', 'digit_distance_nums']:
            labels.append('task-specific-oracle')
    if dataset == 'HumanEval+' and entry == 'find_zero':
        labels.append('polynomial-root-oracle')
    return labels


def typed(value, ancestors=None):
    """Preserve Python types. A label without a value is explicitly noncomparable."""
    if ancestors is None:
        ancestors = set()
    kind = type(value)
    flags = set()
    if value is None:
        return {'t': 'none'}, flags
    if kind is bool:
        return {'t': 'bool', 'v': value}, flags
    if kind is int:
        if abs(value) > SAFE_INT:
            flags.add('integer-outside-js-exact-range')
            return {'t': 'int', 'hex': hex(value)}, flags
        return {'t': 'int', 'v': str(value)}, flags
    if kind is float:
        if not math.isfinite(value):
            flags.add('nonfinite-float')
        return {'t': 'float', 'hex': value.hex()}, flags
    if kind is str:
        if any(ord(c) > 0xFFFF for c in value):
            flags.add('astral-string')
        return {'t': 'str', 'v': value}, flags
    if kind is complex:
        return {'t': 'complex', 'real': value.real.hex(), 'imag': value.imag.hex()}, {'complex-value'}
    if kind not in [list, tuple, set, frozenset, dict]:
        return {'t': 'unsupported', 'pythonType': kind.__module__ + '.' + kind.__qualname__}, {'unsupported-value'}
    if id(value) in ancestors:
        return {'t': 'cycle'}, {'cyclic-value'}
    ancestors = ancestors | {id(value)}
    if kind is dict:
        items = []
        for key, item in value.items():
            key_, f1 = typed(key, ancestors)
            item_, f2 = typed(item, ancestors)
            flags |= f1 | f2
            if type(key) is not str:
                flags.add('nonstring-dict-key')
            items.append([key_, item_])
        return {'t': 'dict', 'items': sorted(items, key=lambda x: canonical(x[0]))}, flags
    items = []
    for item in value:
        encoded, child_flags = typed(item, ancestors)
        flags |= child_flags
        items.append(encoded)
    if kind in [set, frozenset]:
        flags.add('set-value')
        items.sort(key=canonical)
    return {'t': kind.__name__, 'items': items}, flags


def js_value(tag):
    """Declared JSON projection only; this does not prove a JavaScript port correct."""
    kind = tag['t']
    if kind == 'none':
        return None
    if kind in ['str', 'bool']:
        return tag['v']
    if kind == 'int':
        value = int(tag['v']) if 'v' in tag else int(tag['hex'], 16)
        if abs(value) > SAFE_INT:
            raise ValueError('unsafe integer')
        return value
    if kind == 'float':
        value = float.fromhex(tag['hex'])
        if not math.isfinite(value):
            raise ValueError('nonfinite')
        return value
    if kind in ['list', 'tuple']:
        return [js_value(item) for item in tag['items']]
    if kind == 'dict':
        if any(key['t'] != 'str' for key, _ in tag['items']):
            raise ValueError('nonstring dict key')
        return {key['v']: js_value(item) for key, item in tag['items']}
    raise ValueError('unsupported JSON projection: ' + kind)


def count_types(tag):
    result = Counter([tag['t']])
    if tag['t'] == 'dict':
        for key, item in tag['items']:
            result.update(count_types(key))
            result.update(count_types(item))
    else:
        for item in tag.get('items', []):
            result.update(count_types(item))
    return result
