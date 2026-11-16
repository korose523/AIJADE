"""Closed launch configuration controls; no controller, services or admission launched."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/ch7'))
import launch_frozen_sequence as launcher


class FrozenLauncherControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fixed-launch-control-')
        self.root = Path(self.temp.name)
        self.base_patch = patch.object(launcher, 'BASE', self.root)
        self.base_patch.start()
        fake_sdk = self.root / 'nonexecutable-sdk-fixture'
        fake_sdk.write_text('command-shape fixture only; never executed\n')
        self.config = dict(schema='aijade.ch7.fixed-launch.v1', purpose='qualification_only',
            implementationCommit='a'*40, repositoryCommit='a'*40, buildFreezeCommit='b'*40,
            repo=str(self.root), output=str(self.root/'never-started'), python=str(fake_sdk),
            dotnet=str(fake_sdk), docker=str(fake_sdk), db_container='fixture-db',
            build_freeze_path='experiments/ch7/mac-formal-2026-11-16/frozen-build.json')
        for name in ('client', 'model', 'selection', 'inputs', 'assembly', 'build_manifest', 'godot', 'execution_plan', 'process_policy'):
            self.config[name] = str(self.root/name)

    def tearDown(self):
        self.base_patch.stop()
        self.temp.cleanup()

    def test_qualification_has_exact_six_hundred_seconds_and_fixed_identities(self):
        _, _, args = launcher.command(self.config)
        self.assertEqual(args[args.index('--settle-seconds')+1], '600')
        self.assertEqual(args[args.index('--implementation-commit')+1], 'a'*40)
        self.assertEqual(args[args.index('--build-freeze-commit')+1], 'b'*40)

    def test_formal_has_no_second_settling_or_alternative_window(self):
        self.config['purpose'] = 'confirmed_finite_heldout'
        self.config['data_publication_manifest'] = 'experiments/ch7/finite-heldout/data-publication.json'
        _, _, args = launcher.command(self.config)
        self.assertEqual(args[args.index('--settle-seconds')+1], '0')
        self.assertEqual(args.count('--data-publication-manifest'), 1)

    def test_existing_attempt_and_unowned_output_are_refused_before_launch(self):
        Path(self.config['output']).mkdir()
        with self.assertRaisesRegex(ValueError, 'never relaunch'):
            launcher.command(self.config)
        self.config['output'] = '/tmp/forbidden-launch-fixture'
        with self.assertRaisesRegex(ValueError, 'outside'):
            launcher.command(self.config)

    def test_unknown_scope_and_nonimmutable_identity_are_refused(self):
        self.config['purpose'] = 'retry-until-pass'
        with self.assertRaisesRegex(ValueError, 'unknown launch purpose'):
            launcher.command(self.config)
        self.config['purpose'] = 'qualification_only'
        self.config['implementationCommit'] = 'HEAD'
        with self.assertRaisesRegex(ValueError, 'full immutable'):
            launcher.command(self.config)


if __name__ == '__main__':
    unittest.main()
