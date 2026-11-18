#!/usr/bin/env python3
"""Exercise the two-repeat parent with child subprocesses that only write labeled fixtures."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import launch_known_repeats as launch
from finite_construction_binding import decode
from run_known_repeat_block import verify_local_database
from test_prepare_known_repeats import packet, save_packet, update


def fixture(output, index, behavior):
    parent = decode((output/'launch.json').read_bytes())
    if behavior == 'missing':
        return 0
    data, _ = packet(index)
    if behavior == 'reordered':
        update(data, 'cases.json', lambda rows: rows.reverse())
    if behavior == 'failed-closure':
        update(data, 'database-cleanup.json', lambda rows: rows[0].update(remaining=1))
    if behavior == 'changed-input':
        data['selection.json'] += b' '
    metadata = dict(buildFreezeCommit=parent['buildFreezeCommit'], buildFreezePath=parent['buildFreezePath'],
                    knownRepeatLaunchSha256=launch.digest(launch.encode(parent)), knownRepeatIndex=index)
    update(data, 'input-identities.json', lambda doc: doc.update(metadata))

    recorded = decode(data['receipt.json'])
    own = {'pid': index * 100, 'createTime': float(index * 100)}
    phases = [{'pid': phase['pid'], 'createTime': float(phase['pid'])} for phase in recorded['phases'].values()]
    descendant = {'pid': index * 100 + 3, 'createTime': float(index * 100 + 3)}
    maybe_remaining = [descendant] if behavior == 'open-descendant' else []
    data['owned-process-registry.json'] = launch.encode({
        'status': 'OWNED_IDENTITIES_REMAIN' if maybe_remaining else 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT',
        'controllers': [own], 'explicitlyRegisteredIdentities': phases,
        'knownIdentities': [own, *phases, descendant],
        'retiredIdentities': [{**identity, 'status': 'ABSENT', 'observedCreateTime': None}
                              for identity in (phases if maybe_remaining else [*phases, descendant])],
        'remainingIdentities': maybe_remaining,
    })
    data['telemetry.jsonl'] = launch.encode({
        'processObservation': {'ownedProcesses': [own, *phases, descendant]}}).replace(b'\n', b' ') + b'\n'

    def terminal(doc):
        now = launch.utc()
        doc.update(metadata, finishedAt=now,
                   ownedProcessRegistrySha256=launch.digest(data['owned-process-registry.json']))
        for phase in doc['phases'].values():
            phase.update(startedAt=now, endedAt=now, createTime=float(phase['pid']))
        if behavior in ('stopped', 'exit-failure'):
            doc.update(status='STOPPED', reason='synthetic stopped child')
    update(data, 'receipt.json', terminal)
    save_packet(output/launch.REPEATS[index-1], data)
    print(f'SYNTHETIC fixture repeat {index}')
    return 3 if behavior == 'exit-failure' else 0


class LaunchControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_root = launch.ROOT/'.runtime/known-launch-tests'
        cls.fixture_root.mkdir(parents=True, exist_ok=True)
        data, binding = packet(1)
        cls.material = {name: data[name] for name in launch.INPUT_NAMES}
        cls.approval = launch.encode({
            **binding, 'schema': launch.APPROVAL_SCHEMA, 'status': launch.APPROVED,
            'qualificationPlanSha256': 'a'*64, 'replySha256': 'b'*64,
        })
        cls.approval_sha = launch.digest(cls.approval)
        cls.record = launch.launch_record(decode(cls.approval), cls.approval_sha, '3'*40, cls.material, launch.SYNTHETIC)

    def setUp(self):
        self.tmp = TemporaryDirectory(prefix='known-launch-', dir=self.fixture_root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'attempt'
        self.calls = []

    def run_with(self, **modes):
        def child(index, log):
            self.calls.append(index)
            command = [sys.executable, '-B', __file__, '--fixture-child', str(self.root), str(index),
                       modes.get(str(index), 'complete')]
            return subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False).returncode
        return launch.execute_repeats(self.root, self.material, self.record, child, approval_body=self.approval)

    def assert_stops_on_first(self, behavior, reason):
        result = self.run_with(**{'1': behavior})
        self.assertEqual(self.calls, [1])
        self.assertFalse((self.root/'repeat-2').exists())
        self.assertEqual(result['status'], 'STOPPED_KNOWN_REPEAT_LAUNCH')
        self.assertFalse(result['qualificationDetermined'])
        self.assertIn(reason, result['reason'])
        self.assertTrue((self.root/'repeat-1.log').is_file())

    def test_two_exact_known_repeats_finish_without_qualifying(self):
        state = self.run_with()
        if state['status'] != launch.LAUNCHED:
            for n in launch.REPEATS:
                path = self.root / (n + '.log')
                if path.is_file():
                    print(path.read_text())
        self.assertEqual(state['status'], launch.LAUNCHED, state.get('reason'))
        self.assertEqual(self.calls, [1, 2])
        record, terminal = launch.verify_launched_pair(self.root, self.approval, self.approval_sha)
        self.assertEqual(record['launchMode'], launch.SYNTHETIC)
        self.assertEqual((self.root/'approval.json').read_bytes(), self.approval)
        self.assertEqual(record['approvalSha256'], self.approval_sha)
        self.assertEqual(terminal['completedRepeats'], 2)
        self.assertFalse(terminal['qualificationDetermined'])
        for name in launch.REPEATS:
            cases = decode((self.root/name/'cases.json').read_bytes())
            self.assertEqual([(row['caseId'], row['condition']) for row in cases],
                             launch.slots(decode(self.material['runtime-manifest.json'])))

    def test_nonzero_child_preserves_original_terminal_and_refuses_second(self):
        self.assert_stops_on_first('exit-failure', 'child exit')
        self.assertEqual(decode((self.root/'repeat-1/receipt.json').read_bytes())['status'], 'STOPPED')

    def test_zero_exit_does_not_make_stopped_terminal_complete(self):
        self.assert_stops_on_first('stopped', 'block terminal is incomplete')

    def test_zero_exit_without_original_terminal_is_refused(self):
        self.assert_stops_on_first('missing', 'receipt.json')

    def test_reordered_case_evidence_is_refused(self):
        self.assert_stops_on_first('reordered', 'condition order')

    def test_modified_known_bytes_are_refused(self):
        self.assert_stops_on_first('changed-input', 'frozen known inputs')

    def test_failed_owned_cleanup_refuses_second(self):
        self.assert_stops_on_first('failed-closure', 'disposals are incomplete')

    def test_reaped_roots_with_owned_descendant_present_refuse_second(self):
        self.assert_stops_on_first('open-descendant', 'cleanup is unknown')
        self.assertEqual(decode((self.root/'repeat-1/receipt.json').read_bytes())['status'], launch.COMPLETE)

    def test_parent_watchdog_reaps_a_synthetic_child_and_refuses_completion(self):
        def child(_index, log):
            process = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(120)'],
                                       stdout=log, stderr=subprocess.STDOUT)
            return launch.wait_child(process, 0.1, 1)
        started = time.monotonic()
        result = launch.execute_repeats(self.root, self.material, self.record, child, approval_body=self.approval)
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(result['status'], 'STOPPED_KNOWN_REPEAT_LAUNCH')
        self.assertEqual(result['completedRepeats'], 0)
        self.assertIn('parent watchdog expired', result['reason'])
        self.assertIsInstance(result['repeats'][0]['exitCode'], int)

    def test_partial_second_attempt_never_resumes_as_complete(self):
        state = self.run_with(**{'2': 'stopped'})
        self.assertEqual(state['completedRepeats'], 1)
        whole = (self.root/'receipt.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_with()
        self.assertEqual(whole, (self.root/'receipt.json').read_bytes())
        self.assertEqual(self.calls, [1, 2])
        with self.assertRaisesRegex(ValueError, 'complete terminal'):
            launch.verify_launched_pair(self.root, self.approval, self.approval_sha)

    def test_changed_digest_only_approval_snapshot_is_refused(self):
        self.assertEqual(self.run_with()['status'], launch.LAUNCHED)
        (self.root/'approval.json').write_bytes(self.approval + b' ')
        with self.assertRaisesRegex(ValueError, 'approval snapshot differs'):
            launch.verify_launched_pair(self.root, self.approval, self.approval_sha)

    def test_changed_child_log_cannot_rebind_a_complete_run(self):
        self.assertEqual(self.run_with()['status'], launch.LAUNCHED)
        (self.root/'repeat-2.log').write_text('synthetic mutated\n')
        with self.assertRaisesRegex(ValueError, 'closure differs'):
            launch.verify_launched_pair(self.root, self.approval, self.approval_sha)

    def test_wrong_independent_reply_digest_blocks_real_cli_before_output(self):
        parent = self.root.parent
        approval = parent/'approval.json'
        approval.write_bytes(self.approval)
        real = launch.ROOT/'experiments/ch7/launch_known_repeats.py'
        args = [sys.executable, '-B', str(real), '--approval', str(approval),
                '--expected-approval-sha256', '0'*64, '--original-reply', str(parent/'reply'),
                '--qualification-plan', str(parent/'plan'), '--config', str(parent/'config'),
                '--scratch', str(parent), '--output', str(self.root)]
        # On a portable CI checkout the real CLI refuses outside the production root even earlier.
        result = subprocess.run(args, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertRegex(result.stderr, 'independently recorded digest|exact project-local path')
        self.assertFalse(self.root.exists())

    def test_pending_reply_cannot_enter_approved_mode(self):
        approval = decode(self.approval)
        approval['status'] = 'PENDING'
        body = launch.encode(approval)
        with self.assertRaisesRegex(ValueError, 'confirmed supervisor reply'):
            launch.approval_record(body, launch.digest(body))

    def test_historical_admission_fields_are_not_executable_as_new_plan(self):
        plan = {
            'schema': launch.PLAN_SCHEMA, 'purpose': 'qualification_only', 'repeats': 2,
            'conditionSlotsPerRepeat': 20, 'databasePort': 55432,
            'watchdog': {'blockWallSeconds': 31, 'rendererTimeoutSeconds': 19, 'sustainedResourceSeconds': 3,
                         'parentAllowanceSeconds': 4, 'shutdownGraceSeconds': 2,
                         'maxOwnedRssBytes': None, 'minAvailableBytes': None, 'maxSwapIncreaseBytes': None},
            'toolsSha256': {name: 'c'*64 for name in ('python', 'docker', 'dotnet')},
        }
        self.assertEqual(launch.parse_execution_plan(launch.encode(plan))['watchdog']['blockWallSeconds'], 31)
        with self.assertRaisesRegex(ValueError, 'execution plan fields'):
            launch.parse_execution_plan(launch.encode(dict(plan, settleSeconds=600, admissionSeconds=120)))

    def test_remote_database_is_refused_before_docker_call(self):
        with patch.dict(os.environ, {'AIJADE_TEST_DATABASE_URL': 'postgresql://example.invalid:55432/aijade'}):
            with self.assertRaisesRegex(ValueError, 'approved local test database'):
                verify_local_database({}, {'databasePort': 55432}, {})


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--fixture-child':
        raise SystemExit(fixture(Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]))
    unittest.main()
