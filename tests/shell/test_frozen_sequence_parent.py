"""Mock-only scientific parent controls. No runtime child or signal is real."""
from contextlib import ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('scientific_parent_tested', REPO / 'experiments/ch7/launch_frozen_sequence.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)


class Clock:
    def __init__(self, jump=1):
        self.now, self.jump = 0.0, jump

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += self.jump


class Child:
    def __init__(self, polls=(0,), waits=()):
        self.pid = 12345
        self.returncode = None
        self.polls, self.waits = list(polls), list(waits)
        self.calls = []

    def poll(self):
        self.calls.append(('poll', None))
        if self.returncode is not None:
            return self.returncode
        value = self.polls.pop(0) if self.polls else None
        if isinstance(value, BaseException):
            raise value
        if value is not None:
            self.returncode = value
        return value

    def wait(self, timeout=None):
        self.calls.append(('wait', timeout))
        if self.returncode is not None:
            return self.returncode
        value = self.waits.pop(0) if self.waits else 'timeout'
        if value == 'timeout':
            raise subprocess.TimeoutExpired('mock child only', timeout)
        self.returncode = value
        return value


class ScientificParentTests(unittest.TestCase):
    def setUp(self):
        directory = REPO / '.runtime/test-tmp'
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='scientific-parent-', dir=directory)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.output = self.root / 'output'
        self.sdk = self.root / 'fake-sdk'; self.sdk.write_text('never executable\n')
        self.python = self.root / 'venv/bin/python'
        self.python.parent.mkdir(parents=True)
        self.python.symlink_to(self.sdk)
        self.record = self.root / 'launch.json'
        self.config_path = self.root / 'fixed.json'
        self.config = dict(schema='aijade.ch7.fixed-launch.v1', purpose='qualification_only',
            implementationCommit='a' * 40, repositoryCommit='c' * 40, buildFreezeCommit='b' * 40,
            repo=str(self.repo), output=str(self.output), python=str(self.python),
            dotnet=str(self.sdk), docker=str(self.sdk), db_container='mock-db',
            build_freeze_path='experiments/ch7/mac-prefix-v4-2026-11-17/frozen-build.json',
            launch_record=str(self.record), docker_host='unix:///mock-not-used',
            database_url='fixture-not-a-real-connection', real_godot='0',
            sandbox_profile=str(self.root / 'sandbox'), godot_log_dir=str(self.root / 'godot-logs'))
        for key in ('client', 'model', 'selection', 'inputs', 'assembly', 'build_manifest',
                    'godot', 'execution_plan', 'process_policy'):
            self.config[key] = str(self.root / key)
        self.config_path.write_text(json.dumps(self.config))
        self.child = Child()
        self.clock = Clock()
        self.started = []
        self.git_mode = 'valid'
        self.identity_mode = 'valid'
        self.identity_reads = 0
        self.stack = ExitStack()
        # Failed mock-call assertions must never render a real inherited secret.
        self.stack.enter_context(mock.patch.dict(parent.os.environ,
            {'PATH': '/fixture-not-used', 'REDIS_URL': 'fixture-remove', 'AIJADE_MOCK_ONLY': 'true'}, clear=True))
        self.stack.enter_context(mock.patch.object(parent, 'BASE', self.root))
        self.stack.enter_context(mock.patch.object(parent.time, 'monotonic', side_effect=self.clock.monotonic))
        self.stack.enter_context(mock.patch.object(parent.time, 'sleep', side_effect=self.clock.sleep))
        self.stack.enter_context(mock.patch.object(parent.signal, 'signal', return_value=signal.SIG_DFL))
        self.stack.enter_context(mock.patch.object(parent, 'process_identity', side_effect=self.identity))
        self.stack.enter_context(mock.patch.object(parent.subprocess, 'check_output', side_effect=self.git))
        self.spawn = self.stack.enter_context(mock.patch.object(parent.subprocess, 'Popen', side_effect=self.popen))
        self.kill = self.stack.enter_context(mock.patch.object(parent.os, 'kill'))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def identity(self, pid):
        if pid == os.getpid():
            return dict(pid=pid, createTime=100.0, createTimeMicros=100000000, parentPid=2, processGroup=pid)
        self.identity_reads += 1
        birth = 200.0
        if self.identity_mode == 'unknown':
            raise ValueError('controlled birth unknown')
        if self.identity_mode == 'reuse_after_launch' and self.identity_reads > 2:
            birth = 201.0
        if self.identity_mode == 'reuse_before_kill' and self.identity_reads > 4:
            birth = 201.0
        if self.identity_mode == 'unknown_cleanup' and self.identity_reads > 2:
            raise PermissionError('controlled identity read denied')
        group = pid + 1 if self.identity_mode == 'wrong_group' else pid
        return dict(pid=pid, createTime=birth, createTimeMicros=round(birth * 1000000),
                    parentPid=os.getpid(), processGroup=group)

    def git(self, command, **kwargs):
        if command[1] == 'rev-parse':
            return ('f' * 40 if self.git_mode == 'mixed_head' else self.config['repositoryCommit']) + '\n'
        if command[1] == 'status':
            return b'M tracked\n' if self.git_mode == 'dirty' else b''
        if self.git_mode == 'mixed_source':
            return b'wrong source generation'
        if self.git_mode == 'mutate_config':
            self.config_path.write_text('{}')
        return Path(parent.__file__).read_bytes()

    def popen(self, args, **kwargs):
        self.started.append((args, kwargs))
        self.output.mkdir()
        (self.output / 'receipt.json').write_text(json.dumps({'status': 'COMPLETE_FINITE_SEQUENCE_OBSERVATIONS'}))
        return self.child

    def execute(self):
        with redirect_stdout(io.StringIO()):
            code = parent.execute(self.config_path)
        return code, json.loads(self.record.with_suffix('.terminal.json').read_text())

    def test_normal_poll_reap_then_wait_is_explicitly_cached(self):
        code, result = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(result['controllerExitCode'], 0)
        self.assertEqual(result['terminalStatusProvenance'], 'Popen.poll')
        event = result['processEvidence']['terminalPolls'][0]
        self.assertFalse(event['returncodeKnownBeforeCall'])
        wait = result['processEvidence']['waitCalls'][0]
        self.assertTrue(wait['reapedBeforeThisCall'])
        self.assertEqual(wait['provenance'], 'CACHED_RETURN_AFTER_PRIOR_TERMINAL_STATUS')
        self.assertFalse(wait['independentKernelWaitClaimed'])
        self.assertEqual(result['controllerProcess']['processGroup'], self.child.pid)
        self.kill.assert_not_called()

    def test_scientific_watchdog_is5700_and_target_venv_argv0_is_preserved(self):
        _, result = self.execute()
        args, kwargs = self.started[0]
        self.assertEqual(result['watchdogSeconds'], 5700)
        self.assertEqual(args[0], str(self.python))
        self.assertNotEqual(args[0], str(self.sdk))
        self.assertTrue(kwargs['start_new_session'])
        self.assertEqual(kwargs['env']['DOTNET_PROCESSOR_COUNT'], '2')
        self.assertFalse('REDIS_URL' in kwargs['env'])
        self.assertEqual(args[args.index('--settle-seconds') + 1], '600')

    def test_formal_watchdog_is5100_and_has_no_new_settling(self):
        self.config['purpose'] = 'confirmed_finite_heldout'
        self.config_path.write_text(json.dumps(self.config))
        _, result = self.execute()
        self.assertEqual(result['watchdogSeconds'], 5100)
        args = self.started[0][0]
        self.assertEqual(args[args.index('--settle-seconds') + 1], '0')

    def watchdog(self):
        self.child = Child(polls=(None, None, None, None, None, None, None))
        self.clock.jump = 5701

    def test_watchdog_term_wait60_is_adverse_even_if_child_then_exits0(self):
        self.watchdog(); self.child.waits = [0]
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertTrue(result['intervention'])
        self.assertEqual(result['controllerExitCode'], 0)
        self.kill.assert_called_once_with(self.child.pid, signal.SIGTERM)
        waits = result['processEvidence']['waitCalls']
        self.assertEqual(waits[-1]['timeoutSeconds'], 60)
        self.assertFalse(waits[-1]['reapedBeforeThisCall'])
        self.assertFalse(result['wholeProcessGroupCleanupClaimed'])

    def test_term_timeout_then_reverified_kill_wait5(self):
        self.watchdog(); self.child.waits = ['timeout', -9]
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertEqual(self.kill.call_args_list, [mock.call(self.child.pid, signal.SIGTERM), mock.call(self.child.pid, signal.SIGKILL)])
        self.assertEqual([x['timeoutSeconds'] for x in result['processEvidence']['waitCalls']], [60, 5])
        self.assertEqual(result['cleanup']['status'], 'CONTROLLER_TERMINAL_AFTER_SIGNAL')
        self.assertFalse(result['unresolved'])

    def test_kill_timeout_remains_explicitly_unresolved(self):
        self.watchdog(); self.child.waits = ['timeout', 'timeout']
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertTrue(result['unresolved'])
        self.assertEqual(result['cleanup']['status'], 'CONTROLLER_UNRESOLVED_AFTER_TERM_AND_KILL')
        self.assertTrue(result['controllerLogMayStillGrow'])

    def test_reused_pid_is_not_signaled(self):
        self.watchdog(); self.identity_mode = 'reuse_after_launch'
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.kill.assert_not_called()
        self.assertTrue(result['unresolved'])
        self.assertEqual(result['cleanup']['status'], 'IDENTITY_UNKNOWN_NOT_SIGNALED')

    def test_unknown_cleanup_identity_is_not_signaled(self):
        self.watchdog(); self.identity_mode = 'unknown_cleanup'
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.kill.assert_not_called()
        self.assertTrue(result['unresolved'])

    def test_reuse_after_term_timeout_forbids_the_kill(self):
        self.watchdog(); self.child.waits = ['timeout']
        self.identity_mode = 'reuse_before_kill'
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.kill.assert_called_once_with(self.child.pid, signal.SIGTERM)
        self.assertEqual(result['cleanup']['status'], 'IDENTITY_UNKNOWN_NOT_SIGNALED')
        self.assertTrue(result['unresolved'])

    def test_unknown_birth_at_launch_stays_adverse_without_signal(self):
        self.child = Child(polls=(None,))
        self.identity_mode = 'unknown'
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertIsNone(result['controllerProcess'])
        self.assertEqual(result['cleanup']['status'], 'IDENTITY_UNBOUND_NOT_SIGNALED')
        self.assertTrue(result['unresolved'])
        self.kill.assert_not_called()

    def test_unknown_birth_does_not_resolve_merely_because_poll_returns0(self):
        self.identity_mode = 'unknown'
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertEqual(result['controllerExitCode'], 0)
        self.assertTrue(result['childIdentityUnresolved'])
        self.assertTrue(result['unresolved'])
        self.kill.assert_not_called()

    def test_wrong_group_is_not_ownership(self):
        self.child = Child(polls=(None,))
        self.identity_mode = 'wrong_group'
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertIsNone(result['controllerProcess'])
        self.kill.assert_not_called()

    def test_interrupt_uses_same_identity_term_and_remains_adverse(self):
        self.child = Child(polls=(KeyboardInterrupt(), None, None), waits=(-15,))
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertIn('KeyboardInterrupt', result['reason'])
        self.kill.assert_called_once_with(self.child.pid, signal.SIGTERM)

    def test_every_existing_artifact_refuses_without_overwrite_or_launch(self):
        for path in [self.record, self.record.with_suffix('.terminal.json'), self.record.with_suffix('.controller.log')]:
            with self.subTest(path=path):
                path.write_text('old original')
                with self.assertRaisesRegex(ValueError, 'prior attempt'):
                    self.execute()
                self.assertEqual(path.read_text(), 'old original')
                self.spawn.assert_not_called()
                path.unlink()

    def test_mixed_source_dirty_and_mixed_head_are_prelaunch_refusals(self):
        for mode in ['mixed_source', 'dirty', 'mixed_head']:
            self.git_mode = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.execute()
            self.spawn.assert_not_called()

    def test_config_byte_change_after_preflight_refuses(self):
        self.git_mode = 'mutate_config'
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            self.execute()
        self.spawn.assert_not_called()

    def test_nonzero_normal_exit_is_adverse_without_any_signal(self):
        self.child = Child(polls=(7,))
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertEqual(result['controllerExitCode'], 7)
        self.assertFalse(result['intervention'])
        self.kill.assert_not_called()

    def test_wait_helper_does_not_claim_prior_poll_when_none_occurred(self):
        evidence = dict(pollCalls=0, terminalPolls=[], waitCalls=[], terminalStatusSource=None)
        child = Child(waits=(0,))
        code = parent.wait_status(child, evidence, 60, 'controlled wait')
        self.assertEqual(code, 0)
        self.assertEqual(evidence['terminalStatusSource'], 'Popen.wait')
        self.assertFalse(evidence['waitCalls'][0]['reapedBeforeThisCall'])
        self.assertFalse(evidence['waitCalls'][0]['independentKernelWaitClaimed'])

    def test_boolean_exit_cannot_be_successful_zero(self):
        self.child = Child(polls=(False,))
        code, result = self.execute()
        self.assertEqual(code, 2)
        self.assertTrue(result['intervention'])

    def test_progress_is_only_original_parent_function_no_new_worker(self):
        self.child = Child(polls=(None, None, 0))
        self.clock.jump = 31
        with mock.patch.object(parent, 'progress', return_value={'stage': 'mock'}) as progress:
            self.execute()
        self.assertEqual(progress.call_count, 2)
        self.assertEqual(self.spawn.call_count, 1)

    def test_launch_and_terminal_bind_exact_config_bytes_and_launch_hash(self):
        raw = self.config_path.read_bytes()
        _, result = self.execute()
        record = json.loads(self.record.read_bytes())
        self.assertEqual(result['configSha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(record['configSha256'], result['configSha256'])
        self.assertEqual(result['launchRecordSha256'], hashlib.sha256(self.record.read_bytes()).hexdigest())
        self.assertEqual(result['logSha256'], hashlib.sha256(self.record.with_suffix('.controller.log').read_bytes()).hexdigest())


class KernelIdentityTests(unittest.TestCase):
    def test_unknown_birth_rejects_before_ownership(self):
        process = mock.Mock()
        process.create_time.return_value = None
        process.ppid.return_value = 10
        with mock.patch.object(parent.psutil, 'Process', return_value=process), \
                mock.patch.object(parent.os, 'getpgid', return_value=30):
            with self.assertRaisesRegex(ValueError, 'birth'):
                parent.process_identity(30)

    def test_second_kernel_birth_change_is_not_same_pid_ownership(self):
        first, second = mock.Mock(), mock.Mock()
        first.create_time.return_value = 100.0
        first.ppid.return_value = 10
        second.create_time.return_value = 101.0
        with mock.patch.object(parent.psutil, 'Process', side_effect=[first, second]), \
                mock.patch.object(parent.os, 'getpgid', return_value=30):
            with self.assertRaisesRegex(ValueError, 'reused'):
                parent.process_identity(30)


if __name__ == '__main__':
    unittest.main()
