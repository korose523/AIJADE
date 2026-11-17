"""Offline P4 dispatch and original-byte controls; no observer or case execution.

Fixture Git objects are local, synthetic source/publication bindings. Passing
these controls grants neither known-input nor heldout scientific acceptance.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'experiments/ch7'))
import finite_runtime as runtime
import finite_sequence_audit as audit


def digest(body):
    return hashlib.sha256(body).hexdigest()


def policy():
    value = json.loads((REPO / 'configs/research/ch7-mac-prefix-v2-process-policy.json').read_bytes())
    value['executionDecision'] = runtime.MAC_PREFIX_DECISION
    return value


def identity(formal=False):
    sources = {path: runtime.sha(REPO / path) for path in runtime.MAC_LIFECYCLE_SOURCES}
    prefix = runtime.MAC_PREFIX_DATA_PREFIX
    return dict(codeCommit='1' * 40, implementationCommit='1' * 40,
        repositoryCommit=('3' if formal else '1') * 40, buildFreezeCommit='2' * 40,
        buildFreezePath=runtime.MAC_PREFIX_BUILD_FREEZE_PATH,
        inputPublicationCommit='3' * 40 if formal else None,
        dataPublicationManifestPath=prefix + 'data-publication.json' if formal else None,
        dataPublicationManifestSha256='d' * 64 if formal else None,
        addedDataPaths=[prefix + 'data-publication.json', prefix + 'inputs.json'] if formal else [],
        processPolicyPath=runtime.MAC_PREFIX_POLICY_PATH, processPolicySha256='b' * 64,
        observerModuleSha256=sources['experiments/ch7/mac_process_guard_v3.py'],
        observerSources=sources, executionPlanSha256=runtime.MAC_PREFIX_PLAN_SHA256)


class PrefixDecisionControls(unittest.TestCase):
    def test_new_decision_retains_kind_but_selects_new_plan_and_build(self):
        value = policy()
        self.assertEqual(value['kind'], runtime.MAC_LIFECYCLE_KIND)
        self.assertEqual(runtime.mac_plan(value), runtime.MAC_PREFIX_PLAN)
        self.assertEqual(runtime.mac_build_path(value), runtime.MAC_PREFIX_BUILD_FREEZE_PATH)
        runtime.validate_mac_execution_identity(value, identity())
        self.assertEqual(audit.expected_plan_sha256(identity()), runtime.MAC_PREFIX_PLAN_SHA256)
        audit._identity(identity(), 'qualification_only')

    def test_old_v1_v2_v3_plan_mappings_are_unchanged(self):
        for value, plan, build, sha in [
            ({}, runtime.MAC_PLAN, runtime.MAC_BUILD_FREEZE_PATH, audit.PLAN_SHA256),
            ({'kind': 'mac-bulk-observed-idle-daemon-v2'}, runtime.MAC_CENSUS_PLAN,
             runtime.MAC_CENSUS_BUILD_FREEZE_PATH, audit.CENSUS_PLAN_SHA256),
            ({'kind': runtime.MAC_LIFECYCLE_KIND}, runtime.MAC_LIFECYCLE_PLAN,
             runtime.MAC_LIFECYCLE_BUILD_FREEZE_PATH, audit.LIFECYCLE_PLAN_SHA256)]:
            with self.subTest(plan=plan):
                self.assertEqual(runtime.mac_plan(value), plan)
                self.assertEqual(runtime.mac_build_path(value), build)
                self.assertEqual(audit.expected_plan_sha256({'buildFreezePath': build}), sha)

    def test_unknown_explicit_decision_and_mixed_observer_kind_refuse(self):
        for decision in [None, '', 'mac-prefix-v3', 'mac-prefix-v5', True]:
            with self.subTest(decision=decision), self.assertRaisesRegex(ValueError, 'execution decision'):
                runtime.mac_plan(dict(policy(), executionDecision=decision))
        for kind in [None, 'mac-observed-idle-daemon-v1', 'mac-bulk-observed-idle-daemon-v2']:
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'execution decision'):
                runtime.mac_plan(dict(policy(), kind=kind))

    def test_missing_decision_cannot_use_new_build_or_new_policy_path(self):
        value = policy(); value.pop('executionDecision')
        with self.assertRaisesRegex(ValueError, 'build-freeze path'):
            runtime.validate_mac_execution_identity(value, identity())
        old = dict(identity(), buildFreezePath=runtime.MAC_LIFECYCLE_BUILD_FREEZE_PATH)
        with self.assertRaisesRegex(ValueError, 'explicit execution decision'):
            runtime.validate_mac_execution_identity(value, old)

    def test_new_decision_cannot_use_any_historical_build_path(self):
        for path in [runtime.BUILD_FREEZE_PATH, runtime.MAC_BUILD_FREEZE_PATH,
                     runtime.MAC_CENSUS_BUILD_FREEZE_PATH, runtime.MAC_LIFECYCLE_BUILD_FREEZE_PATH]:
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'build-freeze path'):
                runtime.validate_mac_execution_identity(policy(), dict(identity(), buildFreezePath=path))

    def test_new_policy_path_and_exact_published_plan_sha_are_mandatory(self):
        for field, bad in [('processPolicyPath', 'configs/research/old.json'),
                           ('executionPlanSha256', audit.LIFECYCLE_PLAN_SHA256),
                           ('executionPlanSha256', '0' * 64)]:
            altered = dict(identity(), **{field: bad})
            with self.subTest(field=field), self.assertRaises(ValueError):
                runtime.validate_mac_execution_identity(policy(), altered)
            with self.assertRaises(ValueError): audit._identity(altered, 'qualification_only')

    def test_new_formal_additions_require_only_new_data_prefix(self):
        value = identity(formal=True)
        runtime.validate_mac_execution_identity(policy(), value)
        audit._identity(value, 'confirmed_finite_heldout')
        for path in ['experiments/ch7/finite-heldout/injected.json',
                     'experiments/ch7/mac-lifecycle-2026-11-17/injected.json']:
            bad = copy.deepcopy(value); bad['addedDataPaths'].append(path)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'data prefix'):
                runtime.validate_mac_execution_identity(policy(), bad)
            with self.assertRaisesRegex(ValueError, 'data prefix'):
                audit._identity(bad, 'confirmed_finite_heldout')
        bad = dict(value, dataPublicationManifestPath='experiments/ch7/finite-heldout/publication.json')
        with self.assertRaisesRegex(ValueError, 'manifest escaped'):
            runtime.validate_mac_execution_identity(policy(), bad)

    def test_new_decision_preserves_distinct_q_b_i_roles(self):
        value = identity()
        for key in ['buildFreezeCommit', 'repositoryCommit']:
            bad = dict(value, **{key: value['implementationCommit'] if key == 'buildFreezeCommit' else '3' * 40})
            with self.subTest(key=key), self.assertRaises(ValueError): audit._identity(bad, 'qualification_only')
        with self.assertRaises(ValueError): audit._identity(identity(), 'confirmed_finite_heldout')
        with self.assertRaises(ValueError): audit._identity(identity(formal=True), 'qualification_only')

    def test_all_15_observer_sources_and_guard_pin_are_required(self):
        value = identity()
        self.assertEqual(len(value['observerSources']), 15)
        for path in runtime.MAC_LIFECYCLE_SOURCES:
            bad = copy.deepcopy(value); bad['observerSources'].pop(path)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'population'):
                audit._identity(bad, 'qualification_only')
        bad = copy.deepcopy(value); bad['observerModuleSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'module/map'):
            audit._identity(bad, 'qualification_only')

    def test_cross_block_old_new_decisions_and_source_substitutions_refuse(self):
        value = identity(); audit._same_identity(copy.deepcopy(value), value, 'qualification_only')
        for field, bad in [('buildFreezePath', runtime.MAC_LIFECYCLE_BUILD_FREEZE_PATH),
                           ('processPolicyPath', 'configs/research/old.json'),
                           ('executionPlanSha256', audit.LIFECYCLE_PLAN_SHA256)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit._same_identity(dict(value, **{field: bad}), value, 'qualification_only')
        bad = copy.deepcopy(value); bad['observerSources']['experiments/ch7/lifecycle_audit.py'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'mixed v3'):
            audit._same_identity(bad, value, 'qualification_only')

    def test_unknown_build_path_is_never_a_plan_dispatch_fallback(self):
        with self.assertRaisesRegex(ValueError, 'unknown execution'):
            audit.expected_plan_sha256(dict(buildFreezePath='experiments/ch7/unknown/frozen-build.json'))

    def test_published_p4_original_bytes_match_constant(self):
        self.assertEqual(runtime.sha(REPO / 'experiments/plans' / runtime.MAC_PREFIX_PLAN), runtime.MAC_PREFIX_PLAN_SHA256)


class PrefixQPolicyControls(unittest.TestCase):
    def setUp(self):
        scratch = REPO / '.runtime/tmp'; scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='prefix-dispatch-offline-', dir=scratch)
        self.repo = Path(self.temp.name)
        self.git('init', '-q'); self.git('config', 'user.name', 'Offline P4 Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        for relative in [*runtime.MAC_LIFECYCLE_SOURCES, 'experiments/plans/' + runtime.MAC_PREFIX_PLAN]:
            target = self.repo / relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO / relative).read_bytes())
        self.path = self.repo / runtime.MAC_PREFIX_POLICY_PATH
        self.write_policy(policy()); self.q = self.commit()

    def tearDown(self): self.temp.cleanup()

    def git(self, *arguments):
        return subprocess.check_output(['git', *arguments], cwd=self.repo, stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.git('add', '.'); self.git('commit', '-qm', 'offline P4 binding fixture')
        return self.git('rev-parse', 'HEAD')

    def write_policy(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(value, indent=2) + '\n')

    def load(self, q=None): return runtime.load_mac_policy(self.repo, self.path, q or self.q)

    def test_exact_q_policy_and_complete_source_closure_pass_without_observe(self):
        actual, binding = self.load()
        self.assertEqual(actual, policy())
        self.assertEqual(binding['processPolicyPath'], runtime.MAC_PREFIX_POLICY_PATH)
        self.assertEqual(binding['processPolicySha256'], runtime.sha(self.path))
        self.assertEqual(binding['observerSources'], {path: runtime.sha(self.repo / path) for path in runtime.MAC_LIFECYCLE_SOURCES})
        self.assertEqual(len(binding['observerSources']), 15)

    def test_policy_byte_mutation_refuses_even_when_json_is_equivalent(self):
        self.load()
        self.path.write_bytes(self.path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'policy differs from Q'): self.load()

    def test_missing_decision_in_canonical_new_policy_refuses(self):
        value = policy(); value.pop('executionDecision'); self.write_policy(value)
        q = self.commit()
        with self.assertRaisesRegex(ValueError, 'path/execution decision'): self.load(q)

    def test_explicit_new_decision_in_other_policy_path_refuses(self):
        alternate = self.repo / 'configs/research/alternate.json'; alternate.write_bytes(self.path.read_bytes())
        q = self.commit()
        with self.assertRaisesRegex(ValueError, 'path/execution decision'):
            runtime.load_mac_policy(self.repo, alternate, q)

    def test_q_plan_mutation_cannot_rebind_the_published_plan_constant(self):
        self.load()
        path = self.repo / 'experiments/plans' / runtime.MAC_PREFIX_PLAN
        path.write_bytes(path.read_bytes() + b'changed decision\n'); q = self.commit()
        with self.assertRaisesRegex(ValueError, 'published decision'): self.load(q)

    def test_local_plan_mutation_refuses_even_when_q_plan_is_original(self):
        self.load()
        path = self.repo / 'experiments/plans' / runtime.MAC_PREFIX_PLAN
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'published decision'): self.load()

    def test_every_uncommitted_source_mutation_refuses(self):
        self.load()
        for relative in runtime.MAC_LIFECYCLE_SOURCES:
            path = self.repo / relative; before = path.read_bytes()
            try:
                path.write_bytes(before + b'\n/* offline altered binding */\n')
                with self.subTest(path=relative), self.assertRaises(ValueError): self.load()
            finally: path.write_bytes(before)
        self.load()

    def test_new_decision_cannot_disable_either_accepted_online_mode(self):
        for field in ['onlineReplayMode', 'binaryAuthenticationMode']:
            value = policy(); value.pop(field); self.write_policy(value); q = self.commit()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'accepted replay/authentication modes'):
                self.load(q)

    def test_wrong_binary_authentication_source_pin_refuses(self):
        value = policy(); value['binaryAuthenticationSourceSha256'] = '0' * 64
        self.write_policy(value); q = self.commit()
        with self.assertRaisesRegex(ValueError, 'authentication source differs'): self.load(q)

    def test_wrong_lifecycle_module_pin_refuses(self):
        value = policy(); value['lifecycle']['moduleSha256'] = '0' * 64
        self.write_policy(value); q = self.commit()
        with self.assertRaisesRegex(ValueError, 'module/shim changed'): self.load(q)

    def test_new_build_15_source_population_hashes_and_native_identity_close(self):
        value = policy()
        build = dict(nativeCensus=copy.deepcopy(value['nativeHelper']),
                     observerSources={path: runtime.sha(REPO / path) for path in runtime.MAC_LIFECYCLE_SOURCES})
        runtime.validate_mac_build_policy(value, build)
        for mutation in ['missing', 'extra', 'hash', 'native']:
            bad = copy.deepcopy(build)
            if mutation == 'missing': bad['observerSources'].pop('experiments/ch7/binary_authentication.py')
            elif mutation == 'extra': bad['observerSources']['unfrozen.py'] = 'a' * 64
            elif mutation == 'hash': bad['observerSources']['experiments/ch7/finite_audit.py'] = '0' * 64
            else: bad['nativeCensus']['sha256'] = '0' * 64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                runtime.validate_mac_build_policy(value, bad)

    def build_fixture(self, *, outside_native=False):
        build_directory = self.repo / '.fixture-build'; build_directory.mkdir()
        assembly = build_directory / 'Aijade.Tests.dll'
        assembly.write_bytes(('nonexecutable fixture 0.1.0+' + self.q).encode())
        assembly.with_suffix('.deps.json').write_text('{}')
        assembly.with_suffix('.runtimeconfig.json').write_text('{}')
        helper = (self.repo.parent if outside_native else self.repo) / ('fixture-native-' + self.q)
        helper.write_bytes(b'nonexecutable native-identity fixture; never launched\n')
        self.addCleanup(lambda: helper.unlink(missing_ok=True))
        frozen = dict(status='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION', commit=self.q,
            assemblyInformationalVersion='0.1.0+' + self.q,
            files={p.name: runtime.sha(p) for p in build_directory.iterdir()},
            nativeCensus=dict(path=str(helper), sha256=runtime.sha(helper),
                sourceSha256=runtime.sha(self.repo / 'experiments/ch7/mac_bulk_census.c')))
        manifest = self.repo / runtime.MAC_PREFIX_BUILD_FREEZE_PATH
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(frozen, indent=2) + '\n')
        return assembly, manifest, self.commit()

    def test_new_strict_b_publication_path_verifies_original_git_and_binary_bytes(self):
        assembly, manifest, b = self.build_fixture()
        # Map the production authorized boundary only for this fixture; its
        # outside-root negative below proves the boundary remains active on CI.
        with patch.object(runtime, 'PROJECT_ROOT', self.repo):
            result = runtime.validate_build(assembly, manifest, self.q, self.repo, b,
                runtime.MAC_PREFIX_BUILD_FREEZE_PATH, strict_publication=True)
            self.assertEqual(result['commit'], self.q)
            manifest.write_bytes(manifest.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'public build freeze differs'):
                runtime.validate_build(assembly, manifest, self.q, self.repo, b,
                    runtime.MAC_PREFIX_BUILD_FREEZE_PATH, strict_publication=True)

    def test_new_strict_b_publication_does_not_relax_native_root_boundary(self):
        assembly, manifest, b = self.build_fixture(outside_native=True)
        with patch.object(runtime, 'PROJECT_ROOT', self.repo), self.assertRaisesRegex(ValueError, 'outside project'):
            runtime.validate_build(assembly, manifest, self.q, self.repo, b,
                runtime.MAC_PREFIX_BUILD_FREEZE_PATH, strict_publication=True)

    def test_lifecycle_setup_recognizes_new_plan_without_changing_registry_protocol(self):
        args = SimpleNamespace(execution_plan=Path(runtime.MAC_PREFIX_PLAN), process_policy=self.path,
                               output=self.repo / 'unstarted-output')
        registry = Mock(); guard = Mock()
        guard.coordination_lock_path.return_value = self.repo / 'fixture.lock'
        with patch.dict(os.environ, {'AIJADE_GIT_COMMIT': self.q, 'AIJADE_LIFECYCLE_JOURNAL': ''}), \
                patch.object(runtime, 'mac_observer', return_value=guard), \
                patch('process_lifecycle.Registry', return_value=registry) as factory:
            self.assertIs(runtime.setup_lifecycle(args, 'sequence'), registry)
        factory.assert_called_once(); registry.activate.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['source_commit'], self.q)
        self.assertEqual(factory.call_args.kwargs['policy_sha256'], runtime.sha(self.path))
        self.assertEqual(factory.call_args.kwargs['stage'], 'sequence')

    def test_lifecycle_setup_rejects_missing_new_decision_before_registry_opens(self):
        value = policy(); value.pop('executionDecision'); self.write_policy(value)
        args = SimpleNamespace(execution_plan=Path(runtime.MAC_PREFIX_PLAN), process_policy=self.path,
                               output=self.repo / 'unstarted-output')
        with patch('process_lifecycle.Registry') as factory, self.assertRaisesRegex(ValueError, 'decision/plan mismatch'):
            runtime.setup_lifecycle(args, 'sequence')
        factory.assert_not_called()


class EngineeringSourceByteControls(unittest.TestCase):
    # Frozen from accepted E02 source 51cf34be49a6ac955481d89e2a2691f3c7c981c5.
    # Decorators and all original line bytes are included, rather than AST dumps.
    ORIGINAL_RUNTIME_FUNCTIONS = {'sha': '2cc0fde0e63eccef63730c984e5ea35748e8cf8c3d1af9bcd94b20e8ee8bc525',
     'require': '3c0757518ce0496b4a485c0c8a7ed35ae7977af6cb36de2d0ec7da3a0665a82d',
     'safe_relative': 'e9579a8501672c2d1907cbe746fda899cbca905ae0e73df7233398a04998310e',
     'managed_check_output': '9fe0123dcdd3f170a743eb1071f75cc5cb5a57fba13772f68b437411ab622a32',
     'managed_run': 'f92e0f5f5db0aafabdb4a2d47ca57b35e749476f59d8cf5ddb13d8a1ea6b9c5d',
     'git_bytes': 'afa70aa17a79b04c8a1a82496f0223a4e4cc1cbae4e584bd438b5a87f4c87a90',
     'wait_post_cleanup_sample': 'c7fcaf6e794f884785e99dd2e5e1290499023ae4e3904ac6bb9551c69da5e1d1',
     'seal_refused_cleanup': 'acd1b37e4a7da8073aed62a0ca6a3fb43b34a440d8f5f355190b530fbb833a3c',
     'finish_monitored_cleanup': 'ac1d0f967f1e7d53b6153dcf520d8d7b5db8a8354e7912f5aa61d019763d6c2e',
     'commit_id': '314d93d6ebcbd9203859a91ec7a2e4ee5a24cb4593a024aabdf0681684ae1bb7',
     'changed_paths': '5eb1a17988e23de02eb1febef7ba88ef610bc167d737ecb0ce6a4cee0c985108',
     'validate_repository_binding': '63271b56a5180675ca9d861252eeaba28f6c73d467afbdb32effdc1f1542376b',
     'mac_observer': '3847e9fc10172d0841376a9d09e2f9e8cc6217fd07df98e15c1a01860326ee71',
     'validate_mac_observation': 'dc3f55c0aeb85e0743c8a7c02425d4ad4b04802f2f4a1fcca3ea64d8b548d97c',
     'validate_mac_sample': 'edf2609065dfd87c502cd864126e895a6fe91b0adc5ae474b64d4ea8d2454eb1',
     'online_lifecycle_cursors': '96c238c0b0a0d51d1fdb9246c6555aa94522669d85792acba661835333c40330',
     'validate_coverage': 'efb195a2773b60e378e1addaf58566827cc9414d384357df9a7350e30150e1a6',
     'fixed_phase': '249e899b5872c75fa4d305d7eb78d82381044b175a9eb2b50de198a2c7a9fdf7',
     'MacMonitor.__init__': 'bcd2587de7f37c9a06c4c0aa298ff4e2c8af67784b37a58c31df40c7c75c5b20',
     'MacMonitor.start': '8c5bec9369784357ff4dce72ac561f71b12141987efd3f771cca444bd9d87bcb',
     'MacMonitor._run': '7c82611e50e3d3547e7e5dfd5992d807d0c8312f39e955b6e5fcada43d352e23',
     'MacMonitor.check': 'fa3d790d8155340da128f970206a6554b2cfe096644872cea819574a6d798059',
     'MacMonitor.stop': '373c7d62f760ea7ac54b8ee616d67d3a0d8639a88e96415a23d7551c48b86e2c',
     'OwnedRegistry.__init__': '542e54d143a29771e2baad6ee1dc0bf9f34cbf1b3e9921d89f999baf3281b10b',
     'OwnedRegistry._lookup': '454e87a73087ce3e13f9be737543eb249178deab1f2d35e7f1eaf99941c056d5',
     'OwnedRegistry.roots': '70162b708b147d188ac54f2487a5652dda13821aaaf8ce973462347902c8416c',
     'OwnedRegistry.remember': 'b299d27981aed95dea532587e71cff8c7260879b444492f7bc2b9e760f5c9ff2',
     'OwnedRegistry.register': 'b65d708c55e6e2f4fd4d178d9556e1fdde2f3ef9ce0b7bd682ee94acd4723b31',
     'OwnedRegistry.final': 'da4bed665ac6b396c20148332a7743f31bc2ca59daf3bf11e896f6f1be238e29',
     'validate_owned_registry': '34f55b5ac2b6f94df6e48af76020e83a532552a4485340afe04d929090f0f867',
     'cleanup_owned_databases': 'ad42246498db3f9833321d68c48cff229c0e0fddcd2f1da868b7724ae3b93e8d',
     'stop_owned_processes': 'baf022cf437b52a1567af913a4cb49c0eee4a21a9e8dd61b721bdaefd0869150',
     'dispositions': 'f3ed968c473386c7c226b452b47612d9eeb2a14e1316b9bba73eb3f38e0f9d5e',
     'read_block_receipt': 'ec5e15721883750045274bdf5cab615f44e6a4a631ecb922a141dee33facb710'}
    ORIGINAL_CORE_BLOBS = {'mac_process_guard_v3.py': '6da78ff6884a2390d5fa8a291237d5ff57dedf451445653711f586ed11d68629',
     'process_lifecycle.py': '93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65',
     'lifecycle_exec.py': 'ecd60bb498802a220d5e2217cabda8dd3fcd601a77ed5dacb2417a3ecc998bc3',
     'binary_authentication.py': 'f2e1be6ea2adea1a5f90516c1a519cfaa1f249c2c9929a3375eb58b543a5926f',
     'phase_continuity.py': '2b1fbb6cf1438179cfdb6cb9cf5cf8f252d095cd72d4ec0f6ff3afdda8854e83',
     'lifecycle_audit.py': 'ffbf69965dd68bcdbf1f7b67ab6e2bda31839ee80ca176a8bc3f9ba2fd77bfef',
     'mac_process_guard.py': 'be8df86b47f382f663eab4f22553025a41661326695d112cfc30ffbe1c677d87',
     'mac_process_guard_v2.py': '85fe287e32b2c3741bcc84dbc0c393f7d798c25bbfd0140f71db4611ede21fc6',
     'mac_bulk_census.c': '22bb68d79e62a3ef40177988621c3d69c6195427c891879186534578e465d003',
     'godot_local.py': '7a710ee6e03418a6b243e6c4c531ea98759ca39d6c42f61cb0ea34bce9483ed3'}

    def test_every_existing_non_dispatch_runtime_function_preserves_original_bytes(self):
        body = (REPO / 'experiments/ch7/finite_runtime.py').read_bytes()
        source_lines = body.splitlines(keepends=True)
        actual = {}
        def collect(nodes, prefix=''):
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
                    actual[prefix + node.name] = digest(b''.join(source_lines[start:node.end_lineno]))
                elif isinstance(node, ast.ClassDef): collect(node.body, prefix + node.name + '.')
        collect(ast.parse(body).body)
        for name, expected in self.ORIGINAL_RUNTIME_FUNCTIONS.items():
            with self.subTest(function=name): self.assertEqual(actual.get(name), expected)

    def test_all_ten_accepted_engineering_core_blobs_are_exactly_preserved(self):
        for name, expected in self.ORIGINAL_CORE_BLOBS.items():
            with self.subTest(source=name): self.assertEqual(runtime.sha(REPO / 'experiments/ch7' / name), expected)


if __name__ == '__main__': unittest.main()
