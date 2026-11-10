"""Consequential type, comparison and missing-data conventions; no corpus code runs."""
import copy
import hashlib
import json
import math
from pathlib import Path
import unittest

from analyze import validate_rows
from oracle_core import (canonical, comparator_requirements, js_value, load_deserializer,
                         SAFE_INT, source_json, typed)

HERE = Path(__file__).resolve().parent


def fixture():
    p = {'task_id': 'Artificial/0', 'prompt': '', 'canonical_solution': 'def solve(x): return x',
         'entry_point': 'solve', 'base_input': [[1]], 'plus_input': [], 'atol': 0}
    _, fn = load_deserializer(HERE/'upstream')
    records = [
        {'kind': 'begin', 'taskId': p['task_id'], 'dataset': 'HumanEval+',
         'problemSha256': hashlib.sha256(canonical(p).encode()).hexdigest(),
         'codeSha256': hashlib.sha256(p['canonical_solution'].encode()).hexdigest(),
         'deserializerFunctionSha256': fn, 'comparatorRequirements': [], 'hashSeed': '0',
         'namespacePerPartition': True, 'argumentsDeepcopiedPerCall': True},
        {'kind': 'case', 'taskId': p['task_id'], 'dataset': 'HumanEval+', 'partition': 'base', 'index': 0,
         'serializedArgsJson': '[1]', 'input': typed([1])[0], 'inputFlags': [], 'status': 'OK',
         'output': typed(1)[0], 'outputFlags': []},
        {'kind': 'end', 'taskId': p['task_id'], 'counts': {'base': 1, 'plus': 0}, 'nativeAssertions': {'status': 'PASS'}},
    ]
    return p, records


class ReferenceChecks(unittest.TestCase):
    def test_null_boolean_and_number_never_collapse(self):
        tags = [typed(x)[0] for x in [None, True, 1]]
        self.assertEqual(len({canonical(x) for x in tags}), 3)
        self.assertIsNone(js_value(tags[0]))
        self.assertIs(type(js_value(tags[1])), bool)
        self.assertIs(type(js_value(tags[2])), int)

    def test_extreme_integer_preserved_and_not_projected(self):
        value = 2**20000
        tag, flags = typed(value)
        self.assertEqual(int(tag['hex'], 16), value)
        self.assertIn('integer-outside-js-exact-range', flags)
        with self.assertRaises(ValueError):
            js_value(tag)
        self.assertEqual(js_value(typed(SAFE_INT)[0]), SAFE_INT)

    def test_nonfinite_never_becomes_successful_null(self):
        for value in [float('nan'), float('inf'), -float('inf')]:
            tag, flags = typed(value)
            self.assertIn('nonfinite-float', flags)
            self.assertNotEqual(tag, typed(None)[0])
            with self.assertRaises(ValueError):
                js_value(tag)

    def test_release_infinity_survives_source_transport_but_not_record_coercion(self):
        restored = json.loads(source_json({'input': [float('inf')]}))
        self.assertTrue(math.isinf(restored['input'][0]))
        with self.assertRaises(ValueError):
            canonical(restored)
        tag, flags = typed(restored['input'])
        self.assertIn('nonfinite-float', flags)
        canonical(tag)

    def test_tuple_projection_is_declared_but_set_and_object_keys_are_blocked(self):
        self.assertEqual(js_value(typed((1, 2))[0]), [1, 2])
        for value in [{1, 2}, {1: 'numeric key'}, 2+3j]:
            with self.assertRaises(ValueError):
                js_value(typed(value)[0])

    def test_official_type_restoration_not_raw_json_calling(self):
        restore, _ = load_deserializer(HERE/'upstream')
        args = restore('Mbpp/2', [[[1], [2]]])[0]
        self.assertTrue(all(type(x) is tuple for x in args))
        args = restore('Mbpp/124', [['1.0', '2+3j']])[0]
        self.assertIs(type(args[0]), float)
        self.assertIs(type(args[1]), complex)

    def test_missing_complete_case_rejects_but_interrupted_prefix_stays_missing(self):
        p, records = fixture()
        with self.assertRaises(AssertionError):
            validate_rows([records[0], records[-1]], 'HumanEval+', p)
        result = validate_rows([records[0]], 'HumanEval+', p, complete=False)
        self.assertEqual(result['missingCases'], 1)
        self.assertEqual(result['nativeAssertions']['status'], 'NOT_REACHED')
        self.assertFalse(result['jsonProjectionRepresentable'])

    def test_duplicate_case_and_changed_input_reject(self):
        p, records = fixture()
        with self.assertRaises(AssertionError):
            validate_rows([records[0], records[1], records[1], records[-1]], 'HumanEval+', p)
        changed = copy.deepcopy(records)
        changed[1]['serializedArgsJson'] = '[true]'
        with self.assertRaises(AssertionError):
            validate_rows(changed, 'HumanEval+', p)

    def test_unsupported_equal_type_labels_are_not_value_agreement(self):
        p, records = fixture()
        records[1]['output'] = {'t': 'unsupported', 'pythonType': 're.Match'}
        records[1]['outputFlags'] = ['unsupported-value']
        result = validate_rows(records, 'HumanEval+', p)
        self.assertFalse(result['allValuesComparable'])
        self.assertFalse(result['jsonProjectionRepresentable'])

    def test_base_assertion_failure_does_not_relabel_reference_calls(self):
        p, records = fixture()
        records[-1]['nativeAssertions'] = {'status': 'FAIL', 'error': {'type': 'AssertionError', 'message': ''}}
        result = validate_rows(records, 'HumanEval+', p)
        self.assertEqual(result['states'], {'OK': 1})
        self.assertEqual(result['nativeAssertions']['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
