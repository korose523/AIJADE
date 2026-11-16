"""Controls must fail at an invalid baseline, not count missing evidence as a mutation rejection."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/ch7'))
import finite_rejection_controls as controls


class CorruptionBaselineControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='finite-baseline-control-')
        self.root = Path(self.temp.name)
        for name in controls.FILES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('[]\n')
        (self.root / 'input-identities.json').write_text(json.dumps({'processPolicySha256': 'fixture-only'}))
        for name in ('process-policy.json', 'owned-process-registry.json'):
            (self.root / name).write_text('{"fixtureOnly":true}\n')

    def tearDown(self):
        self.temp.cleanup()

    def test_invalid_primary_stops_before_any_mutation_is_counted(self):
        with patch.object(controls, 'verify', side_effect=ValueError('invalid original')) as verify:
            with self.assertRaisesRegex(ValueError, 'invalid original'):
                controls.run(self.root, ROOT)
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(verify.call_args.args[0], self.root)

    def test_mac_evidence_is_copied_and_disposable_baseline_is_checked_first(self):
        seen = []
        def verify(root, repo):
            seen.append(root)
            if root == self.root:
                return {'fixtureOnly': True}
            for name in ('process-policy.json', 'owned-process-registry.json'):
                self.assertEqual((root / name).read_bytes(), (self.root / name).read_bytes())
            raise ValueError('invalid complete disposable baseline')
        with patch.object(controls, 'verify', side_effect=verify):
            with self.assertRaisesRegex(ValueError, 'invalid complete disposable baseline'):
                controls.run(self.root, ROOT)
        self.assertEqual(len(seen), 2)


if __name__ == '__main__':
    unittest.main()
