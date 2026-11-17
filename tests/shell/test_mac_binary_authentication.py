"""Offline integration of exact byte authentication with live identity fields.

Only small project-local fake Ollama files are read. psutil process identity is
mocked, while the authenticator, policy checks and archived-evidence parsers are
real. No observer, native collector, listener, API or model is invoked.
"""
import copy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'experiments/ch7'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import binary_authentication as binary
import finite_runtime
import mac_process_guard_v3 as guard
import process_lifecycle as life
import test_mac_lifecycle_guard as lifecycle_fixtures


class MacBinaryAuthenticationIntegrationControls(unittest.TestCase):
    def setUp(self):
        scratch_parent = REPO / '.runtime/tmp'
        scratch_parent.mkdir(parents=True, exist_ok=True)
        self.scratch = tempfile.TemporaryDirectory(
            prefix='mac-binary-auth-integration-', dir=scratch_parent)
        self.addCleanup(self.scratch.cleanup)
        base = Path(self.scratch.name)
        self.paths = {'app': base / 'gui/Ollama', 'serve': base / 'cli/ollama'}
        self.specs = {}
        for role, pid, parent, payload in (
                ('app', 10, 1, b'controlled-gui-binary-001'),
                ('serve', 11, 10, b'controlled-serve-binary-001')):
            path = self.paths[role]
            path.parent.mkdir()
            path.write_bytes(payload)
            self.specs[pid] = dict(created=float(pid), parent=parent,
                                   executable=str(path),
                                   argv=[str(path)] + (['serve'] if role == 'serve' else []))
        self.policy = lifecycle_fixtures.policy()
        self.policy['daemon'] = {
            role: self.identity(pid) for role, pid in (('app', 10), ('serve', 11))}
        self.module_sha = guard._file_sha(Path(binary.__file__))
        self.policy.update(binaryAuthenticationMode='full-read-exact-bytes-v1',
                           binaryAuthenticationSourceSha256=self.module_sha)
        guard.validate_policy(self.policy)

    def process(self, pid):
        spec = self.specs[pid]
        return SimpleNamespace(create_time=lambda: spec['created'],
                               ppid=lambda: spec['parent'],
                               exe=lambda: spec['executable'],
                               cmdline=lambda: list(spec['argv']))

    def identity(self, pid, authenticator=None):
        with patch('psutil.Process', side_effect=self.process):
            return guard._read_identity(pid, binary_authenticator=authenticator)

    def authenticator(self):
        value = guard.new_binary_authenticator(self.policy)
        self.assertIs(type(value), binary.BinaryAuthenticator)
        guard._check_binary_authenticator(self.policy, value)
        return value

    def raw_fixture(self, active=True):
        policy = copy.deepcopy(self.policy)
        if not active:
            policy.pop('binaryAuthenticationMode')
            policy.pop('binaryAuthenticationSourceSha256')
        # Only substitute the fixture's declarative policy; all native/API/journal
        # parsing below remains real and uses the original synthetic raw bytes.
        with patch.object(lifecycle_fixtures, 'policy', return_value=policy):
            policy, observation, journal = lifecycle_fixtures.fixture()
        if active:
            observation.update(binaryAuthenticationMode=policy['binaryAuthenticationMode'],
                               binaryAuthenticationModuleSha256=self.module_sha,
                               binaryAuthenticationWork=self.authenticator().statistics())
        decision = guard.validate_observation(policy, observation,
                                              lifecycle_journal=journal)
        self.assertEqual(decision['status'], 'PASS', decision)
        return policy, observation, journal

    def test_cold_and_cached_complete_identities_match_and_each_hit_reads_eof(self):
        authenticator = self.authenticator()
        expected_keys = {'pid', 'createTime', 'parentPid', 'executable', 'sha256',
                         'argvSha256', 'commandForm'}
        for pid in (10, 11):
            cold = self.identity(pid)
            self.assertEqual(set(cold), expected_keys)
            self.assertEqual(self.identity(pid, authenticator), cold)
        first = authenticator.statistics()
        for pid in (10, 11):
            self.assertEqual(self.identity(pid, authenticator), self.identity(pid))
        second = authenticator.statistics()
        self.assertEqual(first['approvedFiles'], 2)
        self.assertEqual(second['cacheMatchReads'] - first['cacheMatchReads'], 2)
        self.assertEqual(second['fullFileReads'] - first['fullFileReads'], 2)
        expected_bytes = sum(path.stat().st_size for path in self.paths.values())
        self.assertEqual(second['physicalReadBytes'] - first['physicalReadBytes'], expected_bytes)
        self.assertEqual(second['sha256Computations'], first['sha256Computations'])

    def test_stable_same_size_change_with_restored_mtime_returns_actual_cold_sha(self):
        authenticator = self.authenticator()
        original = self.identity(10, authenticator)
        path = self.paths['app']
        original_stat = path.stat()
        changed = bytearray(path.read_bytes())
        changed[-1] ^= 1
        path.write_bytes(changed)
        os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        self.assertEqual(path.stat().st_size, original_stat.st_size)
        self.assertEqual(path.stat().st_mtime_ns, original_stat.st_mtime_ns)
        cold = self.identity(10)
        warm = self.identity(10, authenticator)
        self.assertEqual(warm, cold)
        self.assertEqual(warm['sha256'], hashlib.sha256(changed).hexdigest())
        self.assertNotEqual(warm['sha256'], original['sha256'])
        self.assertEqual(authenticator.bindings()[str(path)], original['sha256'])
        # A second changed read must not approve the altered bytes as baseline.
        self.assertEqual(self.identity(10, authenticator), cold)
        self.assertEqual(authenticator.statistics()['cacheMismatchReads'], 2)
        self.assertEqual(authenticator.statistics()['approvedFiles'], 1)

    def test_cache_does_not_freeze_parent_command_or_birth_fields(self):
        authenticator = self.authenticator()
        original = self.identity(11, authenticator)
        self.specs[11].update(parent=99, argv=[str(self.paths['serve']), 'runner'])
        current = self.identity(11, authenticator)
        self.assertEqual(current, self.identity(11))
        self.assertEqual(current['sha256'], original['sha256'])
        self.assertEqual(current['parentPid'], 99)
        self.assertEqual(current['commandForm'], 'unknown')
        self.assertNotEqual(current['argvSha256'], original['argvSha256'])
        first = self.process(11)
        reused = SimpleNamespace(create_time=lambda: 999.)
        with patch('psutil.Process', side_effect=[first, reused]):
            with self.assertRaisesRegex(ValueError, 'PID reused'):
                guard._read_identity(11, binary_authenticator=authenticator)

    def test_factory_constructs_only_inner_authenticator_without_binary_prewarm(self):
        policy = copy.deepcopy(self.policy)
        policy['onlineReplayMode'] = 'incremental-exact-prefix-v1'
        original_open = os.open
        forbidden = {str(path) for path in self.paths.values()}
        def open_without_daemons(path, *args, **kwargs):
            if os.fspath(path) in forbidden:
                raise AssertionError('factory must not prewarm daemon bytes')
            return original_open(path, *args, **kwargs)
        with patch.object(binary.os, 'open', side_effect=open_without_daemons):
            inner, outer = finite_runtime.online_lifecycle_cursors(policy)
        self.assertEqual(set(inner), {'lifecycle_cursor', 'binary_authenticator'})
        self.assertEqual(set(outer), {'lifecycle_cursor'})
        self.assertIsNot(inner['lifecycle_cursor'], outer['lifecycle_cursor'])
        authenticator = inner['binary_authenticator']
        self.assertIs(type(authenticator), binary.BinaryAuthenticator)
        self.assertEqual(authenticator.statistics()['calls'], 0)
        self.assertEqual(authenticator.statistics()['approvedBytes'], 0)
        self.assertEqual(authenticator.statistics()['openedFiles'], 0)

    def test_none_mode_retains_cold_policy_and_rejects_unsolicited_authenticator(self):
        policy = copy.deepcopy(self.policy)
        policy.pop('binaryAuthenticationMode')
        policy.pop('binaryAuthenticationSourceSha256')
        guard.validate_policy(policy)
        self.assertIsNone(guard.new_binary_authenticator(policy))
        self.assertEqual(finite_runtime.online_lifecycle_cursors(policy), ({}, {}))
        self.assertEqual(finite_runtime.online_lifecycle_cursors(None), ({}, {}))
        guard._check_binary_authenticator(policy, None)
        with self.assertRaisesRegex(ValueError, 'without explicit policy'):
            guard._check_binary_authenticator(policy, self.authenticator())
        self.raw_fixture(active=False)

    def test_unknown_mode_is_refused_by_policy_factory_and_instance_check(self):
        policy = copy.deepcopy(self.policy)
        policy['binaryAuthenticationMode'] = 'claimed-hash-only'
        for action in (lambda: guard.validate_policy(policy),
                       lambda: guard.new_binary_authenticator(policy),
                       lambda: finite_runtime.online_lifecycle_cursors(policy),
                       lambda: guard._check_binary_authenticator(policy, self.authenticator())):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    action()

    def test_actual_class_and_exact_policy_bindings_are_required(self):
        authenticator = self.authenticator()
        class Subclass(binary.BinaryAuthenticator):
            pass
        wrong_values = (None, SimpleNamespace(bindings=authenticator.bindings),
                        life.ViewCursor(), Subclass(authenticator.bindings()),
                        binary.BinaryAuthenticator({str(self.paths['app']): 'f' * 64}))
        for value in wrong_values:
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(ValueError):
                    guard._check_binary_authenticator(self.policy, value)
        # A detached binding copy cannot mutate the instance's frozen context.
        detached = authenticator.bindings()
        detached[str(self.paths['app'])] = 'f' * 64
        guard._check_binary_authenticator(self.policy, authenticator)

    def test_missing_or_incorrect_policy_source_pin_is_refused(self):
        for value in (None, 'f' * 64, True):
            policy = copy.deepcopy(self.policy)
            if value is None:
                policy.pop('binaryAuthenticationSourceSha256')
            else:
                policy['binaryAuthenticationSourceSha256'] = value
            with self.subTest(pin=value):
                with self.assertRaisesRegex(ValueError, 'source differs from policy'):
                    guard.validate_policy(policy)
                with self.assertRaises(ValueError):
                    guard.new_binary_authenticator(policy)

    def test_real_offline_parsers_accept_pinned_raw_and_reject_mode_or_source_mismatch(self):
        policy, observation, journal = self.raw_fixture()
        for field, value, code in (
                ('binaryAuthenticationMode', None, 'BINARY_AUTHENTICATION_MODE_MISMATCH'),
                ('binaryAuthenticationModuleSha256', 'f' * 64, 'BINARY_AUTHENTICATION_SOURCE_MISMATCH')):
            changed = copy.deepcopy(observation)
            changed[field] = value
            with self.subTest(field=field):
                result = guard.validate_observation(policy, changed, lifecycle_journal=journal)
                self.assertEqual(result['status'], 'FAIL', result)
                self.assertIn(code, [row['code'] for row in result['blockers']])
                self.assertIsNone(result['ownedRssBytes'])

    def test_invalid_diagnostic_work_is_unknown_not_zero_or_pass(self):
        policy, observation, journal = self.raw_fixture()
        for value in (None, {}, {'calls': True}, {'calls': -1}, {'calls': 1.0}):
            changed = copy.deepcopy(observation)
            changed['binaryAuthenticationWork'] = value
            with self.subTest(work=value):
                result = guard.validate_observation(policy, changed, lifecycle_journal=journal)
                self.assertEqual(result['status'], 'UNKNOWN', result)
                self.assertIn('BINARY_AUTHENTICATION_WORK_UNKNOWN',
                              [row['code'] for row in result['blockers']])
                self.assertIsNone(result['ownedRssBytes'])

    def test_binary_authentication_metadata_does_not_cache_other_evidence_verdict(self):
        policy, observation, journal = self.raw_fixture()
        changed = copy.deepcopy(observation)
        changed['evidence']['api']['modelCount'] = True
        result = guard.validate_observation(policy, changed, lifecycle_journal=journal)
        self.assertNotEqual(result['status'], 'PASS', result)
        self.assertIsNone(result['ownedRssBytes'])
        self.assertEqual(guard.validate_observation(policy, observation,
                                                  lifecycle_journal=journal)['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
