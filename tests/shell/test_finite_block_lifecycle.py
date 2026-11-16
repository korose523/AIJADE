"""Offline v3 block wiring/failure controls; no observer or subprocess launch."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'experiments/ch7'))
import run_finite_block as block

BASE = Path('/Volumes/Untitled/AIJADE')


class Registry:
    def __init__(self, path):
        self.path = path
        path.write_bytes(b'synthetic-initial-journal\n')
        self.scope_id = 'a' * 32
        self.closed = False
        self.run = Mock(name='managed_database_run')
        self.final = Mock(return_value=dict(status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT'))
        self.close_error = None

    def close(self):
        if self.close_error:raise self.close_error
        self.path.write_bytes(self.path.read_bytes()+b'synthetic-scope-close\n')
        self.closed = True


class BlockLifecycleControls(unittest.TestCase):
    def setUp(self):
        scratch = BASE / '.runtime/posix/tmp'
        scratch.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='block-v3-controls-',dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = Registry(self.root/'journal.jsonl')
        self.args = SimpleNamespace(output=self.root/'block-1',repo=self.root)

    def invoke(self, main, setup=None):
        with patch.object(block,'setup_lifecycle',side_effect=setup or (lambda *a:self.registry)), \
             patch.object(block,'_main',side_effect=main), contextlib.redirect_stderr(io.StringIO()):
            return block.main(self.args)

    def test_01_lifecycle_setup_precedes_any_block_preflight(self):
        order=[]
        def setup(args,stage):order.append(('setup',stage));return self.registry
        def body(args):
            self.assertIs(args._lifecycle_registry,self.registry)
            order.append(('body',None));args.output.mkdir();block.write(args.output/'receipt.json',dict(status='COMPLETE'))
            return 0
        self.assertEqual(self.invoke(body,setup),0)
        self.assertEqual(order,[('setup','block-1'),('body',None)])
        self.assertTrue(self.registry.closed)

    def test_02_first_actual_git_check_uses_managed_route_after_setup(self):
        order=[]
        def setup(args,stage):order.append('setup');return self.registry
        def managed(*args,**kwargs):order.append('managed-git');raise ValueError('stop before any real preflight')
        with patch.object(block,'setup_lifecycle',side_effect=setup), \
             patch.object(block,'managed_check_output',side_effect=managed), \
             patch.object(block.subprocess,'check_output',side_effect=AssertionError('unmanaged Git forbidden')), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(block.main(self.args),1)
        self.assertEqual(order,['setup','managed-git'])
        self.assertTrue(self.registry.closed)

    def test_03_precondition_failure_closes_scope_and_binds_exact_final_prefix(self):
        def fail(args):raise ValueError('original precondition failure')
        self.assertEqual(self.invoke(fail),1)
        receipt=json.loads((self.args.output/'receipt.json').read_text())
        raw=self.registry.path.read_bytes()
        self.assertEqual(receipt['status'],'STOPPED_PRECONDITION')
        self.assertIn('original precondition failure',receipt['reason'])
        self.assertEqual(receipt['lifecycleJournalBytes'],len(raw))
        self.assertEqual(receipt['lifecycleJournalSha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['lifecycleScopeId'],self.registry.scope_id)
        self.assertEqual(receipt['modelRequests'],0)

    def test_04_setup_failure_stops_before_preflight_or_subprocess(self):
        with patch.object(block,'setup_lifecycle',side_effect=ValueError('policy mismatch')), \
             patch.object(block,'_main') as body, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(block.main(self.args),1)
            body.assert_not_called()

    def test_05_legacy_setup_none_retains_original_uninstrumented_body(self):
        def legacy(args):self.assertIsNone(args._lifecycle_registry);return 0
        self.assertEqual(self.invoke(legacy,lambda *a:None),0)
        self.assertFalse(self.registry.closed)

    def test_06_preexisting_output_is_not_setup_or_rewritten(self):
        self.args.output.mkdir();path=self.args.output/'receipt.json';path.write_bytes(b'original output\n')
        with patch.object(block,'setup_lifecycle') as setup, patch.object(block,'_main',return_value=1):
            self.assertEqual(block.main(self.args),1)
            setup.assert_not_called()
        self.assertEqual(path.read_bytes(),b'original output\n')

    def test_07_v3_launch_registers_same_ready_handle_without_pid_reread(self):
        proc=SimpleNamespace(pid=321)
        registry=Mock();registry.launch.return_value=proc
        registry.register.return_value=dict(identity=dict(createTimeMicros=123456789))
        stream=object();env={'fixture':'value'}
        with patch.object(block.subprocess,'Popen',side_effect=AssertionError('unmanaged launch')), \
             patch.object(block.psutil,'Process',side_effect=AssertionError('PID may already have exited')):
            actual,created=block.launch_owned_process('flow',['fixture','arg'],self.root,env,stream,registry,mac=True,v3=True)
        self.assertIs(actual,proc);self.assertEqual(created,123.456789)
        registry.register.assert_called_once_with(proc)
        self.assertEqual(registry.launch.call_args.kwargs['role'],'finite')
        self.assertEqual(registry.launch.call_args.kwargs['stage'],'flow')
        self.assertIs(registry.launch.call_args.kwargs['env'],env)

    def test_08_legacy_mac_launch_keeps_original_pid_registration(self):
        proc=SimpleNamespace(pid=321);registry=Mock()
        fake=Mock();fake.create_time.return_value=123.5
        with patch.object(block.subprocess,'Popen',return_value=proc),patch.object(block.psutil,'Process',return_value=fake):
            actual,created=block.launch_owned_process('renderer',['fixture'],self.root,{},object(),registry,mac=True,v3=False)
        self.assertIs(actual,proc);self.assertEqual(created,123.5)
        registry.register.assert_called_once_with(321,123.5)
        registry.launch.assert_not_called()

    def test_09_legacy_nonmac_has_no_registry_or_new_identity_read(self):
        proc=SimpleNamespace(pid=321)
        with patch.object(block.subprocess,'Popen',return_value=proc),patch.object(block.psutil,'Process') as identify:
            actual,created=block.launch_owned_process('flow',['fixture'],self.root,{},object(),None,mac=False,v3=False)
        self.assertIs(actual,proc);self.assertIsNone(created);identify.assert_not_called()

    def cleanup(self,process_error=None,database_error=None,monitor_error=None,registry_error=None):
        order=[];monitor=Mock();processes=[SimpleNamespace(pid=1)]
        def stop(roots):
            order.append('process')
            if process_error:raise process_error
            return [dict(pid=1,exitCode=0,errors=[])]
        def db(*args,**kwargs):
            order.append('database');self.assertEqual(kwargs['run'],self.registry.run)
            if database_error:raise database_error
            return []
        def finish(actual,require_terminal_sample):
            order.append('monitor');self.assertIs(actual,monitor);self.assertTrue(require_terminal_sample)
            if monitor_error:raise monitor_error
        def final():
            order.append('registry')
            if registry_error:raise registry_error
            return dict(status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT')
        self.registry.final.side_effect=final
        with patch.object(block,'stop_owned_processes',side_effect=stop), \
             patch.object(block,'cleanup_owned_databases',side_effect=db), \
             patch.object(block,'finish_monitored_cleanup',side_effect=finish):
            result=block.finish_v3_owned_cleanup(processes,self.root/'leases','fixture-docker','fixture',monitor,self.registry)
        return order,result

    def test_10_cleanup_routes_database_commands_and_one_terminal_tick(self):
        order,result=self.cleanup()
        self.assertEqual(order,['process','database','monitor','registry'])
        self.assertEqual(result[-1],[])

    def test_11_process_cleanup_error_does_not_skip_database_monitor_or_registry(self):
        order,result=self.cleanup(process_error=OSError('process cleanup unknown'))
        self.assertEqual(order,['process','database','monitor','registry'])
        self.assertIsNone(result[0][0]['exitCode']);self.assertTrue(result[-1])

    def test_12_database_error_does_not_skip_terminal_tick_and_monitor_stop(self):
        order,result=self.cleanup(database_error=ValueError('database unknown'))
        self.assertEqual(order,['process','database','monitor','registry'])
        self.assertIsNone(result[1][0]['remaining']);self.assertTrue(result[-1])

    def test_13_terminal_tick_or_monitor_error_still_attempts_registry_final(self):
        order,result=self.cleanup(monitor_error=ValueError('next scheduled tick adverse'))
        self.assertEqual(order,['process','database','monitor','registry'])
        self.assertIn('monitor cleanup',result[-1][0])

    def test_14_registry_final_error_retains_explicit_unknown(self):
        order,result=self.cleanup(registry_error=ValueError('unresolved descendant'))
        self.assertEqual(result[2]['status'],'UNKNOWN_OWNED_IDENTITY_ABSENCE')
        self.assertIn('registry cleanup',result[-1][0])

    def test_15_final_scope_failure_cannot_leave_success_receipt(self):
        self.registry.close_error=ValueError('scope close unknown')
        def body(args):
            args.output.mkdir();block.write(args.output/'receipt.json',dict(status='COMPLETE',reason='original context'))
            return 0
        self.assertEqual(self.invoke(body),1)
        receipt=json.loads((self.args.output/'receipt.json').read_text())
        self.assertEqual(receipt['status'],'STOPPED_LIFECYCLE_FINALIZATION_ERROR')
        self.assertIn('original context',receipt['reason'])
        self.assertIn('scope close unknown',receipt['reason'])


if __name__=='__main__':
    unittest.main()
