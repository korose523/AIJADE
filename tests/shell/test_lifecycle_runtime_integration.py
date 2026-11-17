"""Offline failure/identity controls for v3 integration; no observer or backend."""
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
import finite_runtime as runtime
import run_finite_sequence as sequence


class LifecycleRuntimeControls(unittest.TestCase):
    def setUp(self):
        scratch=REPO/'.runtime/tmp';scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch,prefix='lifecycle-integration-')
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_explicit_new_decision_has_distinct_dispatch_and_dependency_closure(self):
        p={'kind':runtime.MAC_LIFECYCLE_KIND}
        self.assertEqual(runtime.mac_plan(p),runtime.MAC_LIFECYCLE_PLAN)
        self.assertEqual(runtime.mac_build_path(p),runtime.MAC_LIFECYCLE_BUILD_FREEZE_PATH)
        self.assertEqual(runtime.mac_observer(p).__name__,'mac_process_guard_v3')
        self.assertEqual(len(runtime.MAC_LIFECYCLE_SOURCES),15)
        self.assertIn('experiments/ch7/binary_authentication.py',runtime.MAC_LIFECYCLE_SOURCES)
        for rel in runtime.MAC_LIFECYCLE_SOURCES:self.assertTrue((REPO/rel).is_file(),rel)
        self.assertEqual(runtime.mac_observer({'kind':'mac-bulk-observed-idle-daemon-v2'}).__name__,'mac_process_guard_v2')
        self.assertEqual(runtime.mac_observer({'kind':'mac-observed-idle-daemon-v1'}).__name__,'mac_process_guard')
    def test_bound_build_refuses_one_missing_observer_source(self):
        policy={'kind':runtime.MAC_LIFECYCLE_KIND,'nativeHelper':{'path':'fixture','sha256':'a','sourceSha256':'b'}}
        files={name:runtime.sha(REPO/name) for name in runtime.MAC_LIFECYCLE_SOURCES}
        build={'nativeCensus':dict(policy['nativeHelper']),'observerSources':files}
        runtime.validate_mac_build_policy(policy,build)
        files.pop(next(iter(files)))
        with self.assertRaisesRegex(ValueError,'source closure'):runtime.validate_mac_build_policy(policy,build)
    def test_postcleanup_failed_next_tick_always_stops_monitor(self):
        monitor=Mock()
        with patch.object(runtime,'wait_post_cleanup_sample',side_effect=ValueError('missing next scheduled tick')):
            with self.assertRaisesRegex(ValueError,'missing next scheduled tick'):
                runtime.finish_monitored_cleanup(monitor,require_terminal_sample=True)
        monitor.stop.assert_called_once()
    def test_stop_failure_retains_postcleanup_failure(self):
        monitor=Mock();monitor.stop.side_effect=ValueError('invalid raw sample')
        with patch.object(runtime,'wait_post_cleanup_sample',side_effect=ValueError('missing next tick')):
            with self.assertRaises(ValueError) as error:runtime.finish_monitored_cleanup(monitor,True)
        self.assertIn('missing next tick',str(error.exception));self.assertIn('invalid raw sample',str(error.exception))
    def test_registry_manages_git_output_and_mergebase_when_environment_present(self):
        registry=Mock();registry.run.return_value=SimpleNamespace(stdout=b'bound-output',returncode=0)
        with patch.dict(os.environ,{'AIJADE_LIFECYCLE_JOURNAL':'controlled-fixture'}),patch('process_lifecycle.from_environment',return_value=registry):
            self.assertEqual(runtime.managed_check_output(['git','show','bound']),b'bound-output')
            result=runtime.managed_run(['git','merge-base','--is-ancestor','Q','I'])
            self.assertEqual(result.returncode,0)
        self.assertEqual(registry.run.call_count,2)
    def test_terminal_archive_includes_close_after_preblock_refusal(self):
        out=self.root/'attempt';journal=self.root/'attempt-lifecycle.jsonl';journal.write_bytes(b'open\n')
        life=SimpleNamespace(path=journal,scope_id='c'*32,closed=False)
        def close():
            with journal.open('ab') as stream:stream.write(b'close\n')
            life.closed=True
        life.close=close
        args=SimpleNamespace(output=out)
        previous=signal.getsignal(signal.SIGTERM)
        with patch.object(sequence,'setup_lifecycle',return_value=life),patch.object(sequence,'_execute',side_effect=ValueError('raw identity unknown')):
            self.assertEqual(sequence.execute(args),1)
        value=json.loads((out/'receipt.json').read_bytes());raw=journal.read_bytes()
        self.assertEqual((out/'lifecycle-journal.jsonl').read_bytes(),raw)
        self.assertEqual(value['lifecycleJournalSha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['lifecycleJournalBytes'],len(raw))
        self.assertEqual(value['status'],'STOPPED_PRE_BLOCK')
        self.assertFalse(value['measurementStarted']);self.assertEqual(signal.getsignal(signal.SIGTERM),previous)
    def test_progress_uses_existing_idle_raw_stream_without_spawning_reader(self):
        import launch_frozen_sequence as launcher
        out=self.root/'attempt';(out/'settling').mkdir(parents=True)
        (out/'receipt.json').write_text(json.dumps({'status':'PREPARED_NO_MEASUREMENT'}))
        (out/'settling/telemetry.jsonl').write_text(json.dumps({'phase':'settling','elapsedSeconds':28,'availableBytes':6*1024**3})+'\n')
        with patch.object(launcher.subprocess,'Popen',side_effect=AssertionError('no process reader')):
            result=launcher.progress(out)
        self.assertEqual(result['stage'],'PREFLIGHT_SETTLING')
        self.assertEqual(result['latestSample']['elapsedSeconds'],28)
        self.assertEqual(result['completedRows'],0)
    def test_strict_publication_accepts_new_path_only_with_bound_native_source(self):
        q='1'*40;b='2'*40
        binary=self.root/'bin';binary.mkdir()
        dll=binary/'Aijade.Tests.dll';dll.write_bytes(b'non-executable identity fixture 0.1.0+'+q.encode())
        for suffix in ('deps','runtimeconfig'):(binary/('Aijade.Tests.'+suffix+'.json')).write_text('{}')
        helper=self.root/'native-fixture';helper.write_bytes(b'non-executable native identity fixture')
        source=(REPO/'experiments/ch7/mac_bulk_census.c').read_bytes()
        build=dict(status='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION',commit=q,assemblyInformationalVersion='0.1.0+'+q,
            files={p.name:runtime.sha(p) for p in binary.iterdir()},
            nativeCensus={'path':str(helper),'sha256':runtime.sha(helper),'sourceSha256':hashlib.sha256(source).hexdigest()})
        manifest=self.root/'build.json';manifest.write_text(json.dumps(build))
        with patch.object(runtime,'PROJECT_ROOT',self.root),patch.object(runtime,'managed_check_output',return_value=manifest.read_bytes()),patch.object(runtime,'commit_id',return_value=b),patch.object(runtime,'git_bytes',return_value=source):
            result=runtime.validate_build(dll,manifest,q,REPO,b,runtime.MAC_LIFECYCLE_BUILD_FREEZE_PATH,strict_publication=True)
            self.assertEqual(result['commit'],q)
            helper.write_bytes(b'changed native bytes')
            with self.assertRaisesRegex(ValueError,'native helper changed'):
                runtime.validate_build(dll,manifest,q,REPO,b,runtime.MAC_LIFECYCLE_BUILD_FREEZE_PATH,strict_publication=True)
    def test_one_wait_journal_error_cannot_skip_other_owned_cleanup(self):
        first=Mock(pid=101);first.poll.return_value=0;first.wait.side_effect=ValueError('wait journal unknown')
        second=Mock(pid=102);second.poll.return_value=0
        with patch.object(runtime.os,'killpg',side_effect=AssertionError('terminal identity must not be signalled')):
            result=runtime.stop_owned_processes([first,second])
        first.wait.assert_called_once();second.wait.assert_called_once()
        self.assertIn('wait journal unknown',result[0]['errors'][0]);self.assertEqual(result[1]['errors'],[])
    def test_finalization_error_cannot_leave_complete_receipt(self):
        out=self.root/'attempt'
        life=SimpleNamespace(path=self.root/'missing-journal',scope_id='c'*32,closed=False,
                             close=Mock(side_effect=ValueError('scope close unknown')))
        def complete(args):
            out.mkdir();(out/'receipt.json').write_text(json.dumps({'status':'COMPLETE_FINITE_SEQUENCE_OBSERVATIONS','completedConditionRows':20}))
            return 0
        with patch.object(sequence,'setup_lifecycle',return_value=life),patch.object(sequence,'_execute',side_effect=complete):
            self.assertEqual(sequence.execute(SimpleNamespace(output=out)),1)
        value=json.loads((out/'receipt.json').read_bytes())
        self.assertEqual(value['status'],'STOPPED_LIFECYCLE_FINALIZATION_ERROR')
        self.assertEqual(value['completedConditionRows'],20)
        self.assertIn('scope close unknown',value['reason'])
    def test_failed_launch_cleanup_runs_once_and_cannot_accept_even_exit_zero(self):
        output=self.root/'refused'
        registry=SimpleNamespace(scope_id='f'*32,refused_process_records=[{'handle':object(),'attemptId':'e'*32,'ownsProcessGroup':False}],
            cleanup_refused=Mock(return_value=[{'attemptId':'e'*32,'cleanupKnown':True,'actualExitCode':0,'errors':[]}]))
        first=runtime.seal_refused_cleanup(registry,output)
        raw=(output/'launch-refused-process-cleanup.json').read_bytes()
        again=runtime.seal_refused_cleanup(registry,output)
        registry.cleanup_refused.assert_called_once_with(grace_seconds=5.0,wait_seconds=1.0)
        self.assertIs(first,again);self.assertFalse(first['workloadAccepted'])
        self.assertEqual(first['status'],'CLEANED_REFUSED_PROCESSES_NOT_ACCEPTED')
        self.assertEqual((output/'launch-refused-process-cleanup.json').read_bytes(),raw)
    def test_failed_launch_cleanup_exception_is_retained_without_second_signal_batch(self):
        registry=SimpleNamespace(scope_id='f'*32,refused_process_records=[{'handle':object(),'attemptId':'e'*32}],
            cleanup_refused=Mock(side_effect=ValueError('controlled metadata unknown')))
        first=runtime.seal_refused_cleanup(registry,self.root)
        again=runtime.seal_refused_cleanup(registry,self.root)
        registry.cleanup_refused.assert_called_once();self.assertEqual(first['status'],'UNKNOWN')
        self.assertIn('controlled metadata unknown',first['errors'][0]);self.assertIs(first,again)
    def test_sequence_cannot_return_success_after_failed_launch_was_cleaned(self):
        out=self.root/'attempt';journal=self.root/'journal.jsonl';journal.write_bytes(b'initial-refused-fixture\n')
        life=SimpleNamespace(path=journal,scope_id='f'*32,closed=False,
            refused_process_records=[{'handle':object(),'attemptId':'e'*32,'ownsProcessGroup':False}],
            cleanup_refused=Mock(return_value=[{'attemptId':'e'*32,'cleanupKnown':True,'actualExitCode':0,'errors':[]}]))
        def close():life.closed=True
        life.close=close
        def apparent_complete(args):
            out.mkdir();(out/'receipt.json').write_text(json.dumps({'status':'COMPLETE_FINITE_SEQUENCE_OBSERVATIONS','completedConditionRows':20}))
            return 0
        with patch.object(sequence,'setup_lifecycle',return_value=life),patch.object(sequence,'_execute',side_effect=apparent_complete):
            self.assertEqual(sequence.execute(SimpleNamespace(output=out)),1)
        value=json.loads((out/'receipt.json').read_bytes())
        self.assertEqual(value['status'],'STOPPED_REFUSED_LAUNCH');self.assertEqual(value['completedConditionRows'],20)
        self.assertEqual(value['refusedProcessCleanupSha256'],runtime.sha(out/'launch-refused-process-cleanup.json'))
        life.cleanup_refused.assert_called_once()
    def test_existing_output_never_opens_new_lifecycle(self):
        out=self.root/'existing';out.mkdir();p=out/'receipt.json';p.write_bytes(b'{"historical":true}\n')
        with patch.object(sequence,'setup_lifecycle') as setup,patch.object(sequence,'_execute',side_effect=ValueError('no overwrite')):
            self.assertEqual(sequence.execute(SimpleNamespace(output=out)),1)
        setup.assert_not_called();self.assertEqual(p.read_bytes(),b'{"historical":true}\n')


if __name__=='__main__':unittest.main()
