"""Offline controls for the full finite auditor's distinct successor policy."""

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from finite_audit import heldout_audit_context, verify_resource_thresholds
from finite_runtime import validate_repository_binding
from known_repeat_acceptance import BUILD, SOURCE
from launch_heldout_blocks import LAUNCH_SCHEMA, PLAN_SCHEMA, PURPOSE, REAL, SYNTHETIC
from launch_known_repeats import digest, encode
from prepare_known_repeats import INPUT_NAMES


class SuccessorAuditControls(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='offline-successor-audit-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.repo = root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Offline Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        source = self.repo / SOURCE
        source.parent.mkdir(parents=True)
        source.write_text('# OFFLINE_SYNTHETIC route marker')
        q = self.commit()
        self.stage = root / 'output' / 'block-1'
        self.stage.mkdir(parents=True)
        for name in INPUT_NAMES:
            (self.stage / name).write_bytes(b'OFFLINE_SYNTHETIC contents')
        self.watchdog = dict(blockWallSeconds=35, rendererTimeoutSeconds=30, sustainedResourceSeconds=2,
                             parentAllowanceSeconds=6, shutdownGraceSeconds=3,
                             maxOwnedRssBytes=123, minAvailableBytes=None, maxSwapIncreaseBytes=None)
        plan_path = 'experiments/ch7/finite-heldout/fixture-plan.json'
        publication_path = 'experiments/ch7/finite-heldout/fixture-publication.json'
        plan = self.repo / plan_path
        plan.parent.mkdir(parents=True)
        plan.write_bytes(encode(dict(schema=PLAN_SCHEMA, purpose=PURPOSE, watchdog=self.watchdog,
                                      databasePort=1234, toolsSha256={n: '0' * 64 for n in ('python', 'docker', 'dotnet')})))
        (self.repo / publication_path).write_bytes(encode(dict(schema='aijade.ch7.mac-data-publication.v1',
                                                           implementationCommit=q,
                                                           addedPaths=[plan_path, publication_path])))
        d = self.commit()
        self.identity = {**validate_repository_binding(self.repo, q, d, publication_path), 'buildFreezePath': BUILD}
        self.receipt = self.identity.copy()
        self.launch = dict(schema=LAUNCH_SCHEMA, mode=REAL, implementationCommit=q,
                           dataPublicationManifestPath=publication_path, executionPlanPath=plan_path,
                           executionPlanSha256=digest(plan.read_bytes()), operationalWatchdog=self.watchdog.copy())

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'OFFLINE_SYNTHETIC route inputs')
        return self.git('rev-parse', 'HEAD')

    def check_route(self):
        (self.stage.parent / 'launch.json').write_bytes(encode(self.launch))
        # The end-to-end synthetic test independently uses the real closing parser.
        with patch('launch_heldout_blocks.block_evidence') as closure:
            context = heldout_audit_context(self.stage, self.repo, self.identity, self.receipt, {'blockIndex': 0})
            closure.assert_called_once()
        return context

    def test_watchdog_is_read_from_exact_successor_plan(self):
        self.assertEqual(self.check_route(), (0, self.watchdog))

    def test_rebind_watchdog_plan_or_data_receipt_is_refused(self):
        original = self.launch['executionPlanSha256']
        self.launch['executionPlanSha256'] = '1' * 64
        with self.assertRaisesRegex(ValueError, 'plan or build freeze changed'):
            self.check_route()
        self.launch['executionPlanSha256'] = original
        self.launch['operationalWatchdog']['maxOwnedRssBytes'] = 1200
        with self.assertRaisesRegex(ValueError, 'watchdog changed'):
            self.check_route()
        self.launch['operationalWatchdog'] = self.watchdog.copy()
        self.receipt['dataPublicationManifestSha256'] = '2' * 64
        with self.assertRaisesRegex(ValueError, 'input publication changed'):
            self.check_route()

    def test_synthetic_origin_cannot_enter_full_production_audit(self):
        self.launch['mode'] = SYNTHETIC
        with self.assertRaisesRegex(ValueError, 'original prospective launch'):
            self.check_route()

    def test_resource_trace_replays_frozen_limits_and_window(self):
        telemetry = [dict(elapsedSeconds=moment, rssBytes=150, availableBytes=4 * 1024**3, swapIncreaseBytes=0)
                     for moment in (0, 1, 2)]
        verify_resource_thresholds(telemetry)  # Historical generic limits allow the trace.
        verify_resource_thresholds(telemetry[:2], self.watchdog)
        with self.assertRaisesRegex(ValueError, 'unreported resource stop'):
            verify_resource_thresholds(telemetry, self.watchdog)
        verify_resource_thresholds(telemetry, {**self.watchdog, 'maxOwnedRssBytes': None})


if __name__ == '__main__':
    unittest.main()
