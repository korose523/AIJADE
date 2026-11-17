"""Functional Python targets for shim-only -S; no collector/API/model/window.

The counterfactual deliberately removes only the shim's -S in a delegated
Popen fixture. It demonstrates that the sitecustomize marker would detect the
old two-startup behavior. Target flags/env and production source stay unchanged.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'experiments/ch7'))
import process_lifecycle as life

TEST_VALUE = 'AIJADE_BOOTSTRAP_CONTROL_VALUE'
MARKER_PATH = 'AIJADE_BOOTSTRAP_CONTROL_MARKER'
EXPECTED_VALUE = 'explicit-bootstrap-fixture-value'
TARGET = (
    "import json,os,sys,psutil;"
    "print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,"
    "no_site=sys.flags.no_site,psutilVersion=psutil.__version__,"
    "testValue=os.environ['AIJADE_BOOTSTRAP_CONTROL_VALUE'],"
    "pid=os.getpid(),parentPid=os.getppid())),flush=True)"
)
CUSTOMIZE = (
    "import json,os,sys\n"
    "with open(os.environ['AIJADE_BOOTSTRAP_CONTROL_MARKER'],'a',encoding='utf-8') as stream:\n"
    " stream.write(json.dumps(dict(pid=os.getpid(),no_site=sys.flags.no_site))+'\\n')\n"
)


@unittest.skipUnless(sys.platform == 'darwin', 'project APFS controlled Python targets')
class ShimBootstrapControls(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='lifecycle-bootstrap-', dir=life.POSIX / 'tmp')
        self.root = Path(self.scratch.name)
        self.customize = self.root / 'sitecustomize.py'
        self.customize.write_text(CUSTOMIZE)
        self.marker = self.root / 'site-startups.jsonl'
        self.parent_env = {key: os.environ.get(key) for key in ('PYTHONPATH', TEST_VALUE, MARKER_PATH)}
        self.parent_prefix = sys.prefix
        self.parent_executable = sys.executable
        self.parent_no_site = sys.flags.no_site
        own = life.identity()
        self.registry = life.Registry(self.root / 'lifecycle-journal.jsonl',
            [(own['pid'], own['createTimeMicros'] / 1000000)],
            source_commit='1' * 40, policy_sha256='2' * 64,
            stage='bootstrap-controlled-python-only', capture_lock_path=self.root / 'capture.lock')

    def tearDown(self):
        for handle in self.registry.handles:
            if handle.process.poll() is None:
                handle.process.kill()
            handle.wait(timeout=2)
        if not self.registry.closed:
            self.registry.close()
        self.scratch.cleanup()

    def evidence(self, name, record):
        directory = os.environ.get('AIJADE_BOOTSTRAP_CONTROLS_DIR')
        if not directory:
            return
        path = Path(directory)
        expected = Path('/Volumes/Untitled/AIJADE/.research/runs/ch7-prefix-20261117')
        self.assertTrue(path.is_absolute() and path.resolve() == path and path.is_relative_to(expected))
        path.mkdir(parents=True, exist_ok=True)
        with (path / (name + '.json')).open('x') as stream:
            json.dump(record, stream, indent=2)
            stream.write('\n')

    def run_target(self, remove_shim_no_site=False):
        env = dict(os.environ, PYTHONPATH=str(self.root), PYTHONDONTWRITEBYTECODE='1')
        env[TEST_VALUE] = EXPECTED_VALUE
        env[MARKER_PATH] = str(self.marker)
        target = [sys.executable, '-B', '-c', TARGET]
        real_popen = subprocess.Popen
        invoked = []

        def recording_popen(arguments, **keywords):
            self.assertEqual(arguments[:3], [sys.executable, '-S', '-B'])
            self.assertEqual(arguments[3], str(REPO / 'experiments/ch7/lifecycle_exec.py'))
            target_index = arguments.index('--')
            self.assertEqual(arguments[target_index + 1:], target)
            self.assertFalse(keywords.get('shell', False))
            self.assertEqual(keywords['env'][TEST_VALUE], EXPECTED_VALUE)
            actual = list(arguments)
            if remove_shim_no_site:
                del actual[1]
            invoked.append(actual)
            return real_popen(actual, **keywords)

        with patch.object(life.subprocess, 'Popen', side_effect=recording_popen):
            result = self.registry.run(target, capture_output=True, timeout=5, check=True, env=env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b'')
        output = json.loads(result.stdout)
        self.assertEqual(output['executable'], self.parent_executable)
        self.assertEqual(output['prefix'], self.parent_prefix)
        self.assertEqual(output['no_site'], 0)
        self.assertEqual(output['psutilVersion'], '7.2.2')
        self.assertEqual(output['testValue'], EXPECTED_VALUE)
        self.assertTrue(all(os.environ.get(key) == value for key, value in self.parent_env.items()),
                        'child-only test environment must not mutate parent environment')
        self.assertEqual((sys.executable, sys.prefix, sys.flags.no_site),
                         (self.parent_executable, self.parent_prefix, self.parent_no_site))
        self.assertEqual(self.parent_no_site, 0)
        markers = [json.loads(line) for line in self.marker.read_text().splitlines()]
        state = self.registry._state()
        finite = [lease for lease in state['leases'].values() if lease['role'] == 'finite']
        self.assertEqual(len(finite), 1)
        lease = finite[0]
        self.assertEqual(lease['identity']['pid'], output['pid'])
        self.assertEqual(lease['parentIdentity'], self.registry.writer)
        self.assertEqual(output['parentPid'], self.registry.writer['pid'])
        self.assertEqual(lease['identityWitnessKind'], 'PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD')
        self.assertLess(lease['registerSeq'], lease['releaseSeq'])
        self.assertLess(lease['releaseSeq'], lease['waitSeq'])
        self.assertEqual(lease['absenceWitnessKind'], 'PARENT_WAIT_REAPED')
        self.assertEqual(lease['exitCode'], 0)
        wait = state['events'][lease['waitSeq'] - 1]
        self.assertEqual(wait['data']['waitSource'], 'Popen.wait')
        final = self.registry.final()
        self.assertEqual(final['status'], 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT')
        self.assertTrue(final['scopeClosed'])
        self.assertEqual(len(invoked), 1)
        self.evidence('without-shim-no-site' if remove_shim_no_site else 'shim-only-no-site',
            dict(controlledTarget=output, markerRows=markers,
                 shimNoSiteEnabled=not remove_shim_no_site, targetFlags=['-B', '-c'],
                 actualPopenPrefix=invoked[0][:4], exactTargetArgvRetained=True,
                 parentEnvironmentUnchanged=True, finiteLease=lease, actualWaitEvent=wait,
                 lifecycleJournalSha256=hashlib.sha256(self.registry.path.read_bytes()).hexdigest(),
                 finalStatus=final['status'], collectorCalls=0, apiCalls=0, modelRequests=0,
                 engineeringWindow=False, qualification=False))
        return output, markers

    def test_01_shim_skips_site_but_execve_target_keeps_venv_site_and_psutil(self):
        output, markers = self.run_target()
        self.assertEqual(markers, [dict(pid=output['pid'], no_site=0)],
                         'only the normal target startup may load sitecustomize')
        self.assertFalse((self.root / '__pycache__').exists(), '-B and original env must prevent pyc writes')

    def test_02_counterfactual_without_shim_S_exposes_two_site_startups(self):
        output, markers = self.run_target(remove_shim_no_site=True)
        self.assertEqual(markers, [dict(pid=output['pid'], no_site=0)] * 2,
                         'counterfactual must show marker predicate distinguishes old shim startup')
        self.assertFalse((self.root / '__pycache__').exists())


if __name__ == '__main__':
    unittest.main()
