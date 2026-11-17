"""Parent watchdog controls. Popen, identity, signals and handlers are mocked.

No engineering runner, native helper, API, model or other child is executed.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
REAL_MONOTONIC = time.monotonic
import unittest
from unittest import mock

HERE = Path(__file__).parent
SCRATCH = Path(os.environ.get('AIJADE_NATIVE_LAUNCHER_TEST_SCRATCH',str(HERE/'.runtime/launcher-mocks')))
SCRATCH.mkdir(parents=True,exist_ok=True)
SOURCE = HERE / 'launch_nested_load.py'
spec = importlib.util.spec_from_file_location('nested_load_parent', SOURCE)
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeProcess:
    def __init__(self, sequence):
        self.pid = 419001
        self.sequence = list(sequence)
        self.returncode = None
        self.waits = []

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waits.append(timeout)
        value = self.sequence.pop(0) if self.sequence else 'timeout'
        if value == 'timeout':
            raise subprocess.TimeoutExpired(['MOCK_ONLY_NO_CHILD'], timeout)
        if isinstance(value, BaseException):
            raise value
        self.returncode = value
        if hasattr(self,'before_return'):self.before_return()
        return value


class Fixture:
    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory(prefix='parent-launcher-mock-', dir=SCRATCH)
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.output = self.root / 'engineering-output'
        self.launcher = self.root / 'launch_nested_load.py'
        self.launcher.write_bytes(SOURCE.read_bytes())
        self.python = self.root / 'python'
        self.python.write_bytes(b'FIXTURE_PYTHON_NOT_EXECUTED')
        self.wrapper = self.root / 'run-local.sh'
        self.wrapper.write_bytes(b'FIXTURE_WRAPPER_NOT_EXECUTED')
        sources = {}
        names = [*parent.OBSERVERS, parent.RUNNER_RELATIVE,
                 *['tests/shell/source-%02d.py' % index for index in range(3)]]
        for index, name in enumerate(names):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('FIXTURE_SOURCE_%s\n' % index).encode())
            sources[name] = sha(path)
        self.native = self.root / 'native-census'
        self.native.write_bytes(b'FIXTURE_NATIVE_NOT_EXECUTED')
        self.exec_shim=self.root/'native-exec-shim';self.exec_shim.write_bytes(b'FIXTURE_NATIVE_SHIM_NOT_EXECUTED');self.exec_shim.chmod(0o755)
        self.lsof=self.root/'lsof-not-executed';self.lsof.write_bytes(b'FIXTURE_GLOBAL_LSOF_NOT_EXECUTED')
        native_binding=dict(mode='native-ready-release-v1',
            adapterSourceSha256=sources['experiments/ch7/native_exec_registry.py'],
            sourcePath=str(self.repo/'experiments/ch7/lifecycle_exec_native.c'),
            sourceSha256=sources['experiments/ch7/lifecycle_exec_native.c'],
            binaryPath=str(self.exec_shim),binarySha256=sha(self.exec_shim))
        listener_binding=dict(mode='complete-managed-lsof-transcript-v1',
            moduleSha256=sources['experiments/ch7/listener_evidence.py'],command=list(parent.LSOF_ARGV),
            executableSha256=sha(self.lsof),maxSeconds=.5,maxBytes=65536)
        protocol_original=HERE/'testdata/nested-engineering-protocol.fixture.json'
        self.protocol=json.loads(protocol_original.read_bytes())
        self.protocol['runtime']['childStartupMaximumSeconds']=15
        self.protocol.update(onlineReplayMode='owned-guard-state-exact-prefix-v1',onlineReplayInitializationMode='paired-source-verified-owned-state-v1')
        self.protocol['onlineReplaySourceSha256']=sources['experiments/ch7/newowned_guard_cursor.py']
        self.protocol.update(lifecycleExecMode='native-ready-release-v1',nativeExec=copy.deepcopy(native_binding),listenerEvidence=copy.deepcopy(listener_binding))
        self.protocol_path=self.repo/'experiments/plans/mock-nested-protocol.json'
        self.plan_path=self.repo/'experiments/plans/mock-nested-plan.md'
        self.protocol_path.parent.mkdir(parents=True)
        self.protocol_path.write_text(json.dumps(self.protocol))
        self.plan_path.write_text('# MOCK ONLY: never a research plan or frozen source.\n')
        policy = dict(coordinationMode='segmented-census-mutation-v1',
            coordinationSchema='aijade.mac.segmented-census-mutation.v1',
            purpose='engineering_real_nested_only',binaryAuthenticationMode='full-read-exact-bytes-v1',
            onlineReplayMode='owned-guard-state-exact-prefix-v1', onlineReplayInitializationMode='paired-source-verified-owned-state-v1',
            onlineReplaySourceSha256=sources['experiments/ch7/newowned_guard_cursor.py'],
            binaryAuthenticationSourceSha256=sources['experiments/ch7/binary_authentication.py'],
            nativeHelper=dict(path=str(self.native), sha256=sha(self.native),
            sourceSha256=sources['experiments/ch7/mac_bulk_census.c']),
            lifecycleExecMode='native-ready-release-v1',nativeExec=copy.deepcopy(native_binding),listenerEvidence=copy.deepcopy(listener_binding),
            lifecycle=dict(moduleSha256=sources['experiments/ch7/process_lifecycle.py'],
                           execShimSha256=sha(self.exec_shim)))
        policy_path = self.repo / 'configs/engineering-policy.json'
        policy_path.parent.mkdir()
        policy_path.write_text(json.dumps(policy))
        for path in (self.protocol_path,self.plan_path,policy_path):sources[str(path.relative_to(self.repo))]=sha(path)
        self.frozen_blobs={name:(self.repo/name).read_bytes() for name in sources}
        self.git_head='a'*40
        self.git_status=b''
        self.clock_offset=0.0
        self.wait_clock_jump=0.0
        self.preparation_epoch=None
        commands = [dict(arguments=['rev-parse', 'HEAD'], stdoutSha256=hashlib.sha256((self.git_head+'\n').encode()).hexdigest()),
                    dict(arguments=['status', '--porcelain'], stdoutSha256=hashlib.sha256(b'').hexdigest())]
        commands += [dict(arguments=['show', '{SOURCE}:' + name], stdoutSha256=value)
                     for name, value in sources.items()]
        self.data = dict(schema='aijade.ch7.nested-load-passport.v1',purpose='ENGINEERING_ONLY_NOT_QUALIFICATION', repo=str(self.repo),
            output=str(self.output), sourceCommit='a' * 40, sourceFiles=sources,
            onlineReplayMode='owned-guard-state-exact-prefix-v1',
            onlineReplayInitializationMode='paired-source-verified-owned-state-v1',
            onlineReplaySourceSha256=sources['experiments/ch7/newowned_guard_cursor.py'],
            lifecycleExecMode='native-ready-release-v1',nativeExec=copy.deepcopy(native_binding),listenerEvidence=copy.deepcopy(listener_binding),
            observerSources={name: sources[name] for name in parent.OBSERVERS},
            runnerSha256=sources[parent.RUNNER_RELATIVE], launcherSha256=sha(self.launcher),
            runtimeWrapperSha256=sha(self.wrapper), pythonSha256=sha(self.python),
            policyPath='configs/engineering-policy.json', policySha256=sha(policy_path),
            protocolPath=str(self.protocol_path.relative_to(self.repo)),protocolSha256=sha(self.protocol_path),
            planPath=str(self.plan_path.relative_to(self.repo)),planSha256=sha(self.plan_path),
            runtime=copy.deepcopy(self.protocol['runtime']),
            **{key:self.protocol[key] for key in ('prefixPaddingTaskCount','prefixPreparationMaximumSeconds',
               'journalAcceptanceMaximumBytes','minimumDemonstratedPrefixBytes')},preflightCommands=commands)
        self.passport = self.root / 'engineering-04-passport.json'
        self.freeze()
        self.bound = dict(pid=419001, createTime=1700000001.125,
            createTimeMicros=1700000001125000, parentPid=os.getpid(), processGroup=419001)
        self.parent_identity = dict(pid=os.getpid(), createTime=1700000000.0,
            createTimeMicros=1700000000000000, parentPid=101, processGroup=102)
        self.identity_calls = 0
        self.identity_fault = None
        self.receipt_change = None
        self.sequence = [0]
        self.popen_exception = None
        self.popen_objects = []
        for key, value in dict(BASE=self.root, C9=self.root, LAUNCHER_HOME=self.root, RUN=self.output, FIXED_PYTHON=self.python, WRAPPER=self.wrapper,
            NATIVE_BINARY_SHA256=sha(self.exec_shim),LSOF_PATH=self.lsof,LSOF_SHA256=sha(self.lsof),
            RECORD=self.root/'engineering-04-launch.json', LOG=self.root/'engineering-04-launch.log',
            TERMINAL=self.root/'engineering-04-launch.terminal.json', __file__=str(self.launcher)).items():
            patch = mock.patch.object(parent, key, value)
            patch.start(); test.addCleanup(patch.stop)
        patch = mock.patch.object(sys, 'executable', str(self.python))
        patch.start(); test.addCleanup(patch.stop)
        self.popen = mock.Mock(side_effect=self.fake_popen)
        self.kill = mock.Mock()
        for patch in (mock.patch.object(parent.subprocess, 'Popen', self.popen),
                      mock.patch.object(parent.subprocess, 'check_output', side_effect=self.git_output),
                      mock.patch.object(parent.time,'monotonic',side_effect=self.clock),
                      mock.patch.object(parent, 'process_identity', side_effect=self.identity),
                      mock.patch.object(parent.os, 'killpg', self.kill),
                      mock.patch.object(parent.signal, 'signal', return_value=signal.SIG_DFL),
                      mock.patch.object(parent.psutil, '__version__', '7.2.2')):
            patch.start(); test.addCleanup(patch.stop)

    def freeze(self):
        self.passport.write_text(json.dumps(self.data))
        self.expected = sha(self.passport)

    def identity(self, pid):
        if pid == os.getpid():
            return dict(self.parent_identity)
        self.identity_calls += 1
        if self.identity_fault is not None:
            return self.identity_fault(self.identity_calls)
        return dict(self.bound)

    def report(self):
        final = dict(status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT', scopeClosed=True,
            unresolvedFiniteLeases=[], launchRefusals=[], launchRefusalArtifacts=[],
            unleasedDiscoveredIdentities=[], remainingIdentities=[])
        receipt = dict(schema='aijade.ch7.nested-load-result.v1', status='ENGINEERING_REAL_NESTED_LOAD_PASS_PENDING_INDEPENDENT_AUDIT',
            sourceCommit=self.data['sourceCommit'], passportSha256=self.expected,
            runnerSha256=self.data['runnerSha256'], policySha256=self.data['policySha256'],
            sourceFiles=self.data['sourceFiles'], controllerProcess={key:self.bound[key]
                for key in ('pid','createTime','parentPid')}, controllerSysExecutable=str(self.python),
            lifecycleJournalStable=True,originalPreflightObservations=360,
            nestedBlocks=[{'blockIndex':index,'scope':'MOCK_ONLY_NOT_OBSERVATIONS'} for index in range(4)],
            nestedEpochMonotonic=self.clock(),preparationEpochMonotonic=self.preparation_epoch,
            registryFinal=final, errors=[], qualificationStarted=False, backendQualified=False,
            scientificAdmission=False, formalHardwareQualification=False, independentHumanReview=False,
            seedConstructed=False, flowBlocks=0, modelRequests=0, rendererRequests=0,
            freshHeldoutCases=0, automaticRetries=0)
        if self.receipt_change is not None:
            self.receipt_change(receipt)
        return receipt

    def fake_popen(self, argv, **kwargs):
        if self.popen_exception is not None:
            raise self.popen_exception
        assert argv == [str(self.wrapper), str(self.python), '-B',
                        str(self.repo/parent.RUNNER_RELATIVE), '--passport', str(self.passport)]
        assert kwargs['start_new_session'] is True and kwargs['shell'] is False
        assert kwargs['stdin'] == subprocess.DEVNULL and kwargs['stderr'] == subprocess.STDOUT
        assert 'AIJADE_NESTED_PREPARATION_EPOCH' in kwargs['env']
        self.preparation_epoch=float(kwargs['env']['AIJADE_NESTED_PREPARATION_EPOCH'])
        assert self.preparation_epoch<=self.clock()
        self.output.mkdir()
        (self.output/'receipt.json').write_text(json.dumps(self.report()))
        process = FakeProcess(self.sequence)
        process.before_return=lambda:setattr(self,'clock_offset',self.clock_offset+self.wait_clock_jump)
        self.popen_objects.append(process)
        return process

    def clock(self):
        return REAL_MONOTONIC()+self.clock_offset

    def git_output(self,argv,**kwargs):
        assert kwargs.get('cwd')==self.repo, 'mock Git never reads another repository'
        if argv==['git','rev-parse','HEAD']:
            value=(self.git_head+'\n').encode()
        elif argv==['git','status','--porcelain']:
            value=self.git_status
        else:
            assert argv[:3]==['git','--no-replace-objects','show'], 'unexpected command in mock-only fixture'
            prefix=self.data['sourceCommit']+':'
            assert argv[3].startswith(prefix), 'wrong mock source identity'
            value=self.frozen_blobs[argv[3][len(prefix):]]
        return value.decode() if kwargs.get('text') else value

    def run(self):
        return parent.execute(self.passport, self.expected)


class ParentControls(unittest.TestCase):
    def test_01_single_mock_child_delivers_report_without_qualification(self):
        f=Fixture(self); result=f.run()
        self.assertTrue(result['engineeringReportDelivered'])
        self.assertFalse(result['independentEngineeringReplayAccepted'])
        self.assertEqual(result['status'],'ENGINEERING_CONTROLLER_REPORTED_PASS_PENDING_INDEPENDENT_REPLAY')
        self.assertEqual(f.popen.call_count,1); f.kill.assert_not_called()
        self.assertEqual(f.popen_objects[0].waits,[2250])
        self.assertTrue(all(result[key] is False for key in parent.FALSE_GATES))
        self.assertEqual(result['actualParentWaits'][0]['exitCode'],0)

    def test_02_wrong_external_passport_sha_never_spawns(self):
        f=Fixture(self)
        with self.assertRaisesRegex(ValueError,'external frozen'):parent.execute(f.passport,'f'*64)
        f.popen.assert_not_called()

    def test_03_existing_output_never_spawns(self):
        f=Fixture(self);f.output.mkdir()
        with self.assertRaisesRegex(ValueError,'existing engineering output'):f.run()
        f.popen.assert_not_called()

    def test_04_attempt_record_permanently_prevents_retry(self):
        f=Fixture(self);parent.RECORD.write_text('PRESERVED_ATTEMPT')
        with self.assertRaisesRegex(ValueError,'never retry'):f.run()
        self.assertEqual(parent.RECORD.read_text(),'PRESERVED_ATTEMPT');f.popen.assert_not_called()

    def test_05_modified_source_never_spawns(self):
        f=Fixture(self);(f.repo/parent.RUNNER_RELATIVE).write_text('changed')
        with self.assertRaisesRegex(ValueError,'source SHA'):f.run()
        f.popen.assert_not_called()

    def test_06_modified_native_never_spawns(self):
        f=Fixture(self);f.native.write_bytes(b'CHANGED')
        with self.assertRaisesRegex(ValueError,'native helper'):f.run()
        f.popen.assert_not_called()

    def test_07_unsafe_source_path_is_rejected_before_read(self):
        f=Fixture(self);value=f.data['sourceFiles'].pop('tests/shell/source-00.py')
        f.data['sourceFiles']['../outside.py']=value;f.freeze()
        with self.assertRaisesRegex(ValueError,'escapes repository'):f.run()
        f.popen.assert_not_called()

    def test_08_observer_closure_cannot_be_omitted(self):
        f=Fixture(self);f.data['observerSources'].pop(parent.OBSERVERS[0]);f.freeze()
        with self.assertRaisesRegex(ValueError,'closure'):f.run()
        f.popen.assert_not_called()

    def test_09_preflight_cannot_be_changed_to_a_git_push(self):
        f=Fixture(self);f.data['preflightCommands'][0]['arguments']=['push','origin'];f.freeze()
        with self.assertRaisesRegex(ValueError,'read-only Git'):f.run()
        f.popen.assert_not_called()

    def test_10_watchdog_term_records_actual_wait_and_stays_adverse(self):
        f=Fixture(self);f.sequence=['timeout',-15];result=f.run()
        self.assertTrue(result['watchdogTimedOut']);self.assertFalse(result['engineeringReportDelivered'])
        self.assertEqual(f.kill.call_args_list,[mock.call(f.bound['pid'],signal.SIGTERM)])
        self.assertEqual(f.popen_objects[0].waits,[2250,5]);self.assertEqual(result['controllerExitCode'],-15)
        self.assertEqual(f.popen.call_count,1)

    def test_11_second_signal_rechecks_birth_and_waits_after_kill(self):
        f=Fixture(self);f.sequence=['timeout','timeout',-9];result=f.run()
        self.assertEqual(f.kill.call_args_list,[mock.call(f.bound['pid'],signal.SIGTERM),mock.call(f.bound['pid'],signal.SIGKILL)])
        self.assertEqual(f.popen_objects[0].waits,[2250,5,5]);self.assertEqual(result['controllerExitCode'],-9)
        self.assertFalse(result['engineeringReportDelivered'])

    def test_12_reused_pid_is_never_signalled(self):
        f=Fixture(self);f.sequence=['timeout','timeout']
        f.identity_fault=lambda n:dict(f.bound,createTimeMicros=f.bound['createTimeMicros']+(1 if n>1 else 0))
        result=f.run();f.kill.assert_not_called()
        self.assertFalse(result['engineeringReportDelivered']);self.assertIsNone(result['controllerExitCode'])

    def test_13_foreign_group_is_never_signalled(self):
        f=Fixture(self);f.sequence=['timeout','timeout']
        f.identity_fault=lambda n:dict(f.bound,processGroup=71 if n>1 else f.bound['pid'])
        result=f.run();f.kill.assert_not_called();self.assertFalse(result['engineeringReportDelivered'])

    def test_14_unknown_initial_identity_never_authorizes_signals(self):
        f=Fixture(self);f.sequence=['timeout','timeout']
        def unknown(n):raise parent.psutil.AccessDenied(f.bound['pid'])
        f.identity_fault=unknown;result=f.run();f.kill.assert_not_called()
        self.assertIsNone(result['controllerProcess']);self.assertFalse(result['engineeringReportDelivered'])

    def test_15_second_birth_change_prevents_kill_escalation(self):
        f=Fixture(self);f.sequence=['timeout','timeout']
        f.identity_fault=lambda n:dict(f.bound,createTimeMicros=f.bound['createTimeMicros']+(1 if n>=3 else 0))
        result=f.run()
        self.assertEqual(f.kill.call_args_list,[mock.call(f.bound['pid'],signal.SIGTERM)])
        self.assertFalse(result['engineeringReportDelivered'])

    def test_16_unstable_nested_journal_cannot_be_delivered(self):
        f=Fixture(self);f.receipt_change=lambda r:r.update(lifecycleJournalStable=False)
        result=f.run();self.assertFalse(result['engineeringReportDelivered'])
        self.assertTrue(any('nested runner adverse' in e for e in result['errors']))

    def test_17_unknown_lifecycle_cleanup_cannot_be_delivered(self):
        f=Fixture(self);f.receipt_change=lambda r:r['registryFinal'].update(status='UNKNOWN_OR_ADVERSE_OWNED_LIFECYCLE')
        result=f.run();self.assertFalse(result['engineeringReportDelivered'])

    def test_18_nonzero_parent_wait_cannot_be_replaced_by_a_pass_receipt(self):
        f=Fixture(self);f.sequence=[7];result=f.run()
        self.assertEqual(result['controllerExitCode'],7);self.assertFalse(result['engineeringReportDelivered'])

    def test_19_receipt_wrong_controller_birth_is_rejected(self):
        f=Fixture(self);f.receipt_change=lambda r:r['controllerProcess'].update(createTime=1700000002.0)
        result=f.run();self.assertFalse(result['engineeringReportDelivered'])

    def test_20_actual_controller_python_is_required(self):
        f=Fixture(self);f.receipt_change=lambda r:r.update(controllerSysExecutable='/usr/bin/python3')
        result=f.run();self.assertFalse(result['engineeringReportDelivered'])

    def test_21_spawn_failure_has_reserved_record_and_no_retry(self):
        f=Fixture(self);f.popen_exception=OSError('MOCK_SPAWN_FAILURE');result=f.run()
        self.assertEqual(f.popen.call_count,1);f.kill.assert_not_called()
        self.assertTrue(parent.RECORD.is_file() and parent.TERMINAL.is_file())
        self.assertFalse(result['engineeringReportDelivered'])

    def test_22_interrupted_wait_retains_record_and_cleans_only_bound_group(self):
        f=Fixture(self);f.sequence=[RuntimeError('MOCK_INTERRUPT'),-15];result=f.run()
        self.assertTrue(result['actualParentWaits'][0]['interrupted'])
        self.assertEqual(f.kill.call_args_list,[mock.call(f.bound['pid'],signal.SIGTERM)])
        self.assertEqual(result['controllerExitCode'],-15);self.assertFalse(result['engineeringReportDelivered'])


    def rebind_policy(self, fixture, mutate):
        path=fixture.repo/fixture.data['policyPath']
        value=json.loads(path.read_bytes());mutate(value)
        path.write_text(json.dumps(value))
        fixture.data['policySha256']=sha(path)
        self.rebind_source_fixture(fixture,fixture.data['policyPath'])

    def rebind_source_fixture(self,fixture,relative):
        path=fixture.repo/relative
        fixture.data['sourceFiles'][relative]=sha(path)
        fixture.frozen_blobs[relative]=path.read_bytes()
        for command in fixture.data['preflightCommands']:
            if command['arguments']==['show','{SOURCE}:'+relative]:command['stdoutSha256']=sha(path)
        fixture.freeze()

    def test_23_explicit_byte_auth_mode_cannot_fall_back_to_legacy(self):
        f=Fixture(self);self.rebind_policy(f,lambda p:p.pop('binaryAuthenticationMode'))
        with self.assertRaisesRegex(ValueError,'explicit full-read-exact-bytes'):f.run()
        f.popen.assert_not_called()

    def test_24_stat_only_byte_auth_mode_is_refused(self):
        f=Fixture(self);self.rebind_policy(f,lambda p:p.update(binaryAuthenticationMode='stat-only-cache'))
        with self.assertRaisesRegex(ValueError,'explicit full-read-exact-bytes'):f.run()
        f.popen.assert_not_called()

    def test_25_coherent_policy_wrong_source_pin_is_refused(self):
        f=Fixture(self);self.rebind_policy(f,lambda p:p.update(binaryAuthenticationSourceSha256='f'*64))
        with self.assertRaisesRegex(ValueError,'binary authentication source pin'):f.run()
        f.popen.assert_not_called()

    def test_26_missing_auth_source_pin_is_refused(self):
        f=Fixture(self);self.rebind_policy(f,lambda p:p.pop('binaryAuthenticationSourceSha256'))
        with self.assertRaisesRegex(ValueError,'full SHA256'):f.run()
        f.popen.assert_not_called()

    def test_27_other_attempt_passport_path_is_refused_even_with_new_valid_bytes(self):
        f=Fixture(self);old=f.root/'engineering-02-passport.json';old.write_bytes(f.passport.read_bytes())
        with self.assertRaisesRegex(ValueError,'independent nested passport'):parent.execute(old,f.expected)
        f.popen.assert_not_called()

    def test_28_old_attempt_record_is_preserved_and_does_not_reserve_nested_attempt(self):
        f=Fixture(self);old=f.root/'prior-prefix-engineering-launch.json';old.write_text('PRESERVED_PREFIX_ATTEMPT')
        result=f.run();self.assertTrue(result['engineeringReportDelivered'])
        self.assertEqual(old.read_text(),'PRESERVED_PREFIX_ATTEMPT')
        self.assertTrue((f.root/'engineering-04-launch.json').exists())
        self.assertEqual(f.popen.call_count,1)

    def test_29_auth_source_is_required_in_complete_nested_observer_closure(self):
        f=Fixture(self);f.data['observerSources'].pop('experiments/ch7/binary_authentication.py');f.freeze()
        with self.assertRaisesRegex(ValueError,'closure'):f.run()
        f.popen.assert_not_called()

    def test_30_editorconfig_is_not_nested_engineering_source_evidence(self):
        f=Fixture(self);value=f.data['sourceFiles'].pop('tests/shell/source-00.py')
        f.data['sourceFiles']['.editorconfig']=value;f.freeze()
        with self.assertRaisesRegex(ValueError,'complete source closure'):f.run()
        f.popen.assert_not_called()

    def test_31_wrong_mock_git_head_and_dirty_source_never_spawn(self):
        f=Fixture(self);f.git_head='b'*40
        with self.assertRaisesRegex(ValueError,'exact clean Qe HEAD'):f.run()
        f.popen.assert_not_called()

    def test_32_dirty_mock_git_status_never_spawns(self):
        f=Fixture(self);f.git_status=b' M experiments/ch7/run_nested_load.py\n'
        with self.assertRaisesRegex(ValueError,'exact clean Qe HEAD'):f.run()
        f.popen.assert_not_called()

    def test_33_coherently_rebound_working_source_cannot_replace_git_blob(self):
        f=Fixture(self);name=parent.RUNNER_RELATIVE;path=f.repo/name;path.write_bytes(b'REBOUND MOCK SOURCE\n')
        f.data['sourceFiles'][name]=sha(path);f.data['runnerSha256']=sha(path);f.freeze()
        with self.assertRaisesRegex(ValueError,'frozen Qe Git blob'):f.run()
        f.popen.assert_not_called()

    def test_34_protocol_runtime_cannot_disagree_after_outer_hash_rebinding(self):
        f=Fixture(self);value=json.loads(f.protocol_path.read_bytes());value['runtime']['blocks']=3
        f.protocol_path.write_text(json.dumps(value));f.data['protocolSha256']=sha(f.protocol_path)
        self.rebind_source_fixture(f,str(f.protocol_path.relative_to(f.repo)))
        with self.assertRaisesRegex(ValueError,'prospective protocol'):f.run()
        f.popen.assert_not_called()

    def test_35_false_nested_clock_is_not_zero(self):
        f=Fixture(self);f.receipt_change=lambda r:r.update(nestedEpochMonotonic=False)
        result=f.run();self.assertFalse(result['engineeringReportDelivered'])
        self.assertTrue(any('actual nested runtime epoch' in e for e in result['errors']))

    def test_36_actual_enclosing_wait_after600_is_adverse_even_with_pass_report(self):
        f=Fixture(self);f.wait_clock_jump=601.0
        result=f.run();self.assertEqual(result['controllerExitCode'],0)
        self.assertFalse(result['engineeringReportDelivered']);self.assertEqual(f.popen.call_count,1)
        self.assertTrue(any('exceeded 600 seconds' in e for e in result['errors']))

    def test_37_forged_preparation_epoch_cannot_repair_parent_anchor(self):
        f=Fixture(self);f.receipt_change=lambda r:r.update(preparationEpochMonotonic=r['preparationEpochMonotonic']-.5)
        result=f.run();self.assertFalse(result['engineeringReportDelivered'])
        self.assertTrue(any('preparation epoch differs from actual enclosing parent' in e for e in result['errors']))

    def test_38_missing_fourth_block_is_retained_as_incomplete(self):
        f=Fixture(self);f.receipt_change=lambda r:r['nestedBlocks'].pop()
        result=f.run();self.assertFalse(result['engineeringReportDelivered'])
        self.assertTrue(any('four nested blocks' in e for e in result['errors']))

    def test_39_old_362_tail_report_cannot_replace360_plus_nested_population(self):
        f=Fixture(self)
        def change(r):r.pop('originalPreflightObservations');r.update(observations=362,tailObservations=2)
        f.receipt_change=change
        result=f.run();self.assertFalse(result['engineeringReportDelivered'])

    def test_40_scientific_purpose_or_execution_decision_is_not_engineering(self):
        f=Fixture(self);f.data['purpose']='qualification_only';f.freeze()
        with self.assertRaisesRegex(ValueError,'purpose'):f.run()
        f.popen.assert_not_called()

    def test_41_engineering_policy_cannot_carry_scientific_execution_decision(self):
        f=Fixture(self);self.rebind_policy(f,lambda p:p.update(executionDecision='mac-nested-v5'))
        with self.assertRaisesRegex(ValueError,'engineering-only segmented policy'):f.run()
        f.popen.assert_not_called()

    def test_42_protocol_plan_policy_must_be_inside_frozen_source_closure(self):
        f=Fixture(self);relative=f.data['protocolPath'];value=f.data['sourceFiles'].pop(relative)
        f.data['sourceFiles']['tests/shell/replacement.py']=value
        (f.repo/'tests/shell/replacement.py').write_bytes(f.protocol_path.read_bytes())
        f.frozen_blobs['tests/shell/replacement.py']=f.protocol_path.read_bytes();f.freeze()
        with self.assertRaisesRegex(ValueError,'source closure'):f.run()
        f.popen.assert_not_called()

    def test_43_old_cursor_cannot_silently_replace_explicit_owned_mode(self):
        f=Fixture(self);self.rebind_policy(f,lambda p:p.update(onlineReplayMode='incremental-exact-prefix-v1'))
        with self.assertRaisesRegex(ValueError,'owned-state initialization mode'):f.run()
        f.popen.assert_not_called()

    def test_44_cursor_source_hash_cannot_be_rebound_to_another_source(self):
        f=Fixture(self);self.rebind_policy(f,lambda p:p.update(onlineReplaySourceSha256='f'*64))
        with self.assertRaisesRegex(ValueError,'owned-state source pin'):f.run()
        f.popen.assert_not_called()

    def test_45_missing_initialization_mode_cannot_dispatch(self):
        f=Fixture(self);self.rebind_policy(f,lambda p:p.pop('onlineReplayInitializationMode'))
        with self.assertRaisesRegex(ValueError,'owned-state initialization mode'):f.run()
        f.popen.assert_not_called()

    def test_46_coherent_old_startup_budget_cannot_replace_inherited_e5_contract(self):
        f=Fixture(self);value=json.loads(f.protocol_path.read_bytes())
        value['runtime']['childStartupMaximumSeconds']=10
        f.data['runtime']['childStartupMaximumSeconds']=10
        f.protocol_path.write_text(json.dumps(value));f.data['protocolSha256']=sha(f.protocol_path)
        self.rebind_source_fixture(f,str(f.protocol_path.relative_to(f.repo)))
        with self.assertRaisesRegex(ValueError,'fifteen-second startup'):f.run()
        f.popen.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
