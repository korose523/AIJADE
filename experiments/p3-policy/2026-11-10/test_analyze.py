#!/usr/bin/env python3
"""Small non-corpus checks of consequential statistical/capture conventions."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

import analyze as a


class AnalysisChecks(unittest.TestCase):
    def test_unknown_is_bounded_not_a_zero_observation(self):
        low = {'A': [0.0] * 10, 'B': [0.25] * 10}
        high = {'A': [0.5] * 10, 'B': [0.25] * 10}
        r = a.bounded_contrast(low, high, {'A': 1, 'B': -1})
        self.assertIsNone(r['mean'])
        self.assertEqual(r['identificationBounds'], [-0.25, 0.25])
        self.assertNotIn('signFlipP', r)

    def test_conversation_weight_is_independent_of_question_count(self):
        data = {}
        eligible = []
        for c in range(10):
            for q in range(100 if c == 0 else 1):
                data[(c, q, 'A')] = {'prompt': int(c == 0), 'planned': 1}
                eligible.append((c, q, 1))
        values, unknown = a.values(data, 'A', eligible, 'prompt')
        self.assertEqual(unknown, 0)
        self.assertEqual(a.estimate(values)['mean'], 0.1)

    def test_partial_unicode_item_is_not_a_complete_source(self):
        planned = ['first', 'second']
        contents = {'first': 'alpha', 'second': 'emoji 😀 second source'}
        raw = a.HEADER + '- alpha\n- emoji 😀' + a.MARKER
        state, ids = a.observed(raw, planned, contents)
        self.assertEqual(state, 'truncated')
        self.assertEqual(ids, ['first'])

    def test_identical_text_with_distinct_sources_remains_unknown(self):
        state, ids = a.observed(a.HEADER + '- same\n- same', ['A', 'B'], {'A': 'same', 'B': 'same'})
        self.assertEqual(state, 'ambiguous-source')
        self.assertIsNone(ids)

    def test_duplicate_rows_reject_instead_of_replacing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rows.jsonl.gz'
            row = {'c': 0, 'q': 0, 'cell': 'A'}
            with gzip.open(path, 'wt') as f:
                f.write(json.dumps(row) + '\n' + json.dumps(row) + '\n')
            with self.assertRaises(AssertionError):
                a.rows_by_key(path, ['A'], lambda r: r['cell'])

    def test_signed_effect_has_exact_ten_unit_sign_flip(self):
        result = a.contrast([1.0] * 10, [0.0] * 10)
        self.assertEqual(result['mean'], 1)
        self.assertEqual(result['ci95'], [1, 1])
        self.assertEqual(result['signFlipP'], 2 / 1024)

    def test_D_is_absolute_macro_effect_not_mean_absolute_effect(self):
        data = {}
        eligible = []
        for c in range(10):
            own = int(c < 5)
            for cell in a.CELLS:
                data[(c, 0, cell)] = {'hit8': own if cell.endswith('own') else 1 - own, 'planned': 1}
            eligible.append((c, 0, 1))
        result = a.d_effect(data, eligible)
        self.assertEqual(result['D']['mean'], 0)
        self.assertEqual(result['D']['reading'], 'sizes not distinguished on this corpus')


if __name__ == '__main__':
    unittest.main()
