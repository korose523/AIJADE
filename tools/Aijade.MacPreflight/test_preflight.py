"""Fault cases for the measurement boundary, without models or network access."""
import json
from pathlib import Path
import tempfile
import unittest

from run_preflight import PressureGuard, digest, reply_metrics, verify_sources


class MeasurementBoundaryTests(unittest.TestCase):
    def test_incomplete_response_does_not_become_success(self):
        with self.assertRaises(ValueError):
            reply_metrics({'message': {'content': 'PASS'}}, 'format-A', 1)

    def test_malformed_message_does_not_become_empty_success(self):
        with self.assertRaises(ValueError):
            reply_metrics({'done': True, 'message': []}, 'format-A', 1)

    def test_length_limit_is_retained_as_censoring(self):
        result = reply_metrics({'done': True, 'done_reason': 'length', 'message': {'content': '```js\n'}}, 'generation', 1)
        self.assertTrue(result['truncated'])
        self.assertFalse(result['hasJavaScriptCodeFence'])
        self.assertIsNone(result['generationTokensPerSecond'])

    def test_nonfinite_time_is_not_a_numeric_measurement(self):
        with self.assertRaises(ValueError):
            reply_metrics({'done': True, 'message': {'content': 'PASS'}, 'eval_duration': float('nan')}, 'format-A', 1)

    def test_short_memory_dip_does_not_abort_and_sustained_dip_does(self):
        guard = PressureGuard(9 * 2**30)
        low = {'availableBytes': 100 * 2**20, 'swapUsedBytes': 9 * 2**30}
        self.assertIsNone(guard.check(low, 0))
        self.assertIsNone(guard.check(low, 14.9))
        self.assertEqual(guard.check(low, 15), 'AVAILABLE_RAM_BELOW_768_MIB_FOR_15_SECONDS')
        self.assertIsNone(guard.check({**low, 'availableBytes': 2 * 2**30}, 16))
        self.assertIsNone(guard.check(low, 17))

    def test_preexisting_swap_is_not_an_increment(self):
        guard = PressureGuard(9 * 2**30)
        baseline = {'availableBytes': 2 * 2**30, 'swapUsedBytes': 9 * 2**30}
        self.assertIsNone(guard.check(baseline, 1000))
        large = {**baseline, 'swapUsedBytes': 12 * 2**30}
        self.assertIsNone(guard.check(large, 1001))
        self.assertEqual(guard.check(large, 1031), 'SWAP_INCREMENT_ABOVE_2_GIB_FOR_30_SECONDS')

    def test_source_change_is_refused_before_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'prompt-builder.cs'
            path.write_text('frozen')
            fixture = {'sourcesSha256': {path.name: digest(path)}}
            verify_sources(root, fixture)
            path.write_text('modified')
            with self.assertRaises(ValueError):
                verify_sources(root, fixture)

    def test_prefix_rule_rejects_substrings_and_keeps_separate_line_flag(self):
        result = reply_metrics({'done': True, 'message': {'content': 'PASSAGE'}}, 'format-A', 1)
        self.assertFalse(result['verdictPrefixConforming'])
        result = reply_metrics({'done': True, 'message': {'content': 'PASS\nreason'}}, 'format-A', 1)
        self.assertTrue(result['verdictPrefixConforming'])
        self.assertFalse(result['singleNonemptyLine'])


if __name__ == '__main__':
    unittest.main()
