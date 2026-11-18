"""Offline integration of the Chapter 7 publication gates using invented data only."""

from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import finite_construction_binding as binding
import finite_inputs
import finite_validate
import known_repeat_acceptance as gate
import launch_known_repeats as known
import prepare_known_repeats as delivery
from finite_runtime import MAC_LIFECYCLE_SOURCES


ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path('/Volumes/Untitled/AIJADE')
PLAN = gate.PREFIX + 'execution-plan.json'
OLD = 'experiments/ch7/live-manifest-known-input-v1.json'
SELECTION = 'experiments/ch7/2026-11-12/selection.json'
SYNTHETIC = 'OFFLINE_SYNTHETIC'
LABEL = 'synthetic fixture; no hardware or research outcomes'


def save(root, relative, body):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body if isinstance(body, bytes) else known.encode(body))
    return path


def terminal_time(second):
    return f'2026-01-01T00:00:{second:02d}Z'


class SyntheticPublication:
    def __init__(self, base):
        self.base = base
        self.repo = base / 'synthetic-repo'
        self.repo.mkdir()
        self.git('init', '-q', '--template=')
        self.write_implementation()
        self.q = self.commit('Q synthetic implementation and supervisor surrogate')
        build = {
            'status': 'CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION',
            'commit': self.q, 'assemblyInformationalVersion': '0.1.0+' + self.q,
            'files': {'synthetic.dll': gate.digest(b'synthetic non-executable assembly')},
        }
        self.build = known.encode(build)
        save(self.repo, gate.BUILD, self.build)
        self.b = self.commit('B synthetic build')
        self.backend = {
            'modelSha256': gate.digest(b'synthetic model placeholder'),
            'realGodotSha256': '2'*64, 'godotWrapperSha256': '3'*64,
            'sandboxProfileSha256': '4'*64, 'rendererSources': {'synthetic.godot': '5'*64},
            'preparedRenderer': {'status': 'PREBUILT_NO_RUNTIME_REBUILD', 'files': {'synthetic.dll': '6'*64}},
            'binaries': build['files'], 'buildManifestSha256': gate.digest(self.build),
            'benchSha256': '8'*64, 'earlierSourceFreezeSha256': '9'*64,
            'databaseContainer': 'synthetic-no-database', 'explicitDockerPath': '/synthetic/not-executable',
        }
        self.approval = known.encode({
            'schema': known.APPROVAL_SCHEMA, 'status': known.APPROVED,
            'implementationCommit': self.q, 'backend': self.backend,
            **{field: self.decision[field] for field in gate.APPROVAL_FIELDS},
        })
        self.approval_sha = gate.digest(self.approval)
        self.evidence = self.repo / gate.EVIDENCE
        self.write_known_packet()
        self.acceptance = known.encode({
            'schema': gate.ACCEPTANCE_SCHEMA, 'status': gate.QUALIFIED,
            'implementationCommit': self.q, 'acceptedAt': terminal_time(20),
            'approvalSha256': self.approval_sha, 'buildFreezeCommit': self.b,
            'qualifiedBackend': self.backend, 'evidence': gate.inventory(self.evidence),
        })
        self.a_sha = gate.digest(self.acceptance)
        save(self.repo, gate.ACCEPTANCE, self.acceptance)
        self.a = self.commit('A synthetic acceptance, isolated test only')

    def git(self, *args):
        env = {**os.environ, 'GIT_AUTHOR_DATE': terminal_time(0), 'GIT_COMMITTER_DATE': terminal_time(0)}
        return subprocess.check_output(
            ['git', '-c', 'user.name=AIJADE offline fixture', '-c', 'user.email=fixture@example.invalid',
             '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args],
            cwd=self.repo, env=env, stderr=subprocess.PIPE,
        ).decode().strip()

    def commit(self, label):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', label)
        return self.git('rev-parse', 'HEAD')

    def write_implementation(self):
        # Copy the asserted source closure, replacing every scenario/candidate artifact.
        synthesized = {OLD, SELECTION, finite_inputs.BANK, gate.DECISION, PLAN,
                       'experiments/ch7/manifest-preparation-2026-11-12/comparison-manifest.json',
                       'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'}
        sources = set(binding.EXTRA_SOURCES) | set(gate.ADDITIONAL_SOURCES) | set(MAC_LIFECYCLE_SOURCES)
        sources.update(str(p.relative_to(ROOT)) for p in (ROOT/'experiments/ch7').glob('finite_*.py'))
        successor_launcher = 'experiments/ch7/launch_heldout_blocks.py'
        if (ROOT/successor_launcher).is_file():
            sources.add(successor_launcher)
        for path in sorted(sources - synthesized):
            save(self.repo, path, (ROOT/path).read_bytes())

        task_rows, candidate_rows = [], []
        for index in range(8):
            exec_ok = index < 4
            shared = dict(skillId=f'synthetic-skill-{index}', reused=False, execOk=exec_ok)
            task_rows.append(dict(shared, condition='sv1-ef0', round=0, attempt=0,
                                  taskId=f'synthetic-task-{index}', selfVerdict='pass' if exec_ok else 'fail'))
            candidate_rows.append(dict(shared, code=f'function synthetic() {{ return {index}; }}'))
        archive = 'experiments/rq-c/redo/rq-c-s42-ollama-t30-r5/'
        sources = {}
        for name, rows in (('trials', task_rows), ('candidates', candidate_rows)):
            path = archive + name + '.jsonl'
            data = b''.join((json.dumps(row) + '\n').encode() for row in rows)
            save(self.repo, path, data)
            sources[path] = gate.digest(data)
        save(self.repo, SELECTION, dict(sources=sources))
        save(self.repo, finite_inputs.BANK, finite_inputs.bank(self.repo))

        self.known_cases = [
            dict(caseId=f'synthetic-known-{i}', conditions=['C1', 'C2'] if i < 5 else ['C2', 'C1'],
                 taskId='synthetic-prior-distinct', codeSha256='e'*64, requestedAct='inform',
                 operations=dict(execution='run', mapperActOverride=None, receiptCaseId=f'synthetic-known-{i}',
                                 assetVersionOverride=None, claimedStage='behavior_overlay_pre_solve',
                                 repeatOutcome=False, revokeBeforeReuse=False, failStateWrite=False))
            for i in range(10)
        ]
        save(self.repo, OLD, dict(cases=self.known_cases, fixture=LABEL))
        save(self.repo, 'experiments/ch7/manifest-preparation-2026-11-12/comparison-manifest.json',
             dict(cases=[dict(caseId=c['caseId'], **finite_inputs.window_registry()[family])
                         for c, family in zip(self.known_cases, finite_inputs.FAMILIES)]))
        save(self.repo, 'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json', dict(fixture=LABEL))
        plan = known.encode(dict(
            schema=known.PLAN_SCHEMA, purpose='qualification_only', repeats=2, conditionSlotsPerRepeat=20,
            databasePort=5432,
            watchdog=dict(blockWallSeconds=60, rendererTimeoutSeconds=20, sustainedResourceSeconds=6,
                          parentAllowanceSeconds=10, shutdownGraceSeconds=4, maxOwnedRssBytes=None,
                          minAvailableBytes=None, maxSwapIncreaseBytes=None),
            toolsSha256={tool: 'f'*64 for tool in ('python', 'docker', 'dotnet')},
        ))
        known.parse_execution_plan(plan)
        save(self.repo, PLAN, plan)
        self.decision = dict(schema=gate.DECISION_SCHEMA, status=known.APPROVED, executionPlanPath=PLAN,
                             executionPlanSha256=gate.digest(plan), qualificationPlanSha256=gate.digest(LABEL.encode()),
                             replySha256=gate.digest(b'invented supervisor surrogate in isolated Git fixture'))
        save(self.repo, gate.DECISION, self.decision)

    def write_known_packet(self):
        material = {
            'runtime-manifest.json': known.encode(dict(cases=[dict(input=case) for case in self.known_cases])),
            'scoring-manifest.json': known.encode(dict(fixture=LABEL)),
            'selection.json': known.encode(dict(fixture=LABEL)),
        }
        launch = known.launch_record(binding.decode(self.approval), self.approval_sha, self.b, material, SYNTHETIC)
        launch_bytes = known.encode(launch)
        save(self.evidence, 'approval.json', self.approval)
        save(self.evidence, 'launch.json', launch_bytes)
        for name, data in material.items():
            save(self.evidence, 'inputs/' + name, data)
        entries = []
        for index, offset in ((1, 1), (2, 10)):
            name = f'repeat-{index}'
            packet = self.evidence / name
            log = save(self.evidence, name + '.log', b'OFFLINE_SYNTHETIC\n')
            phases = {name: dict(pid=100 * index + i, createTime=float(i), exitCode=0,
                                 startedAt=terminal_time(offset + 1), endedAt=terminal_time(offset + 2))
                      for i, name in enumerate(('flow', 'renderer'), 1)}
            phase_ids = [{field: phase[field] for field in ('pid', 'createTime')} for phase in phases.values()]
            controller = dict(pid=index * 100, createTime=0.0)
            registry = save(packet, 'owned-process-registry.json', dict(
                status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT',
                controllers=[controller], explicitlyRegisteredIdentities=phase_ids,
                knownIdentities=[controller, *phase_ids], remainingIdentities=[],
                retiredIdentities=[dict(process, status='ABSENT', observedCreateTime=None) for process in phase_ids],
            ))
            metadata = dict(knownRepeatIndex=index, knownRepeatLaunchSha256=gate.digest(launch_bytes))
            save(packet, 'input-identities.json', dict(
                self.backend, **metadata, buildFreezeCommit=self.b, buildFreezePath=gate.BUILD,
                executionPlanSha256=self.decision['executionPlanSha256'], purpose='qualification_only',
                codeCommit=self.q, constructionFreezeCommit=self.q,
            ))
            save(packet, 'telemetry.jsonl',
                 (json.dumps(dict(processObservation=dict(ownedProcesses=phase_ids))) + '\n').encode())
            runtime = binding.decode(material['runtime-manifest.json'])
            write_closing_packet(packet, runtime, self.backend, phases, make_rows(runtime, []))
            save(packet, 'frozen-build.json', self.build)
            for relative, data in material.items():
                save(packet, relative, data)
            save(packet, 'receipt.json', dict(
                **metadata, **{field: [] for field in known.EMPTY_FIELDS},
                schema='aijade.ch7.finite-block-receipt.v1', status=known.COMPLETE, reason=None,
                plannedPairs=10, plannedCases=20, completedCases=20, heldOutCases=0, modelRequests=0,
                blockIndex=0, purpose='qualification_only', conditionsMeasured=['C1', 'C2'],
                codeCommit=self.q, formalHardwareQualification=False, phases=phases,
                ownedProcessRegistrySha256=gate.digest(registry.read_bytes()), finishedAt=terminal_time(offset + 3),
            ))
            entries.append(dict(index=index, exitCode=0, directory=name, startedAt=terminal_time(offset),
                                finishedAt=terminal_time(offset + 4), logSha256=gate.digest(log.read_bytes()),
                                blockReceiptSha256=known.block_evidence(packet, launch, index)))
        save(self.evidence, 'receipt.json', dict(
            schema=known.RECEIPT_SCHEMA, status=known.LAUNCHED, launchSha256=gate.digest(launch_bytes),
            qualificationDetermined=False, completedRepeats=2, plannedRepeats=2, repeats=entries,
            startedAt=terminal_time(0), finishedAt=terminal_time(15),
        ))

    @contextmanager
    def trust_fixture_only(self):
        # Let the actual read-only Git/qualification gate reopen the synthesized
        # launch. Only the physical Mac recognition and physical sweep are stubs.
        def physical_boundary(first, second, identity, scratch):
            if not all(path.is_relative_to(self.base) for path in (first, second, scratch)):
                raise AssertionError('synthetic trust escaped the isolated temporary repository')
            identity = binding.decode(identity)
            if identity['backend'] != self.backend:
                raise AssertionError('synthetic trust used an unrecognized backend')
            inputs = {name: (first/name).read_bytes() for name in delivery.INPUT_NAMES}
            for packet in (first, second):
                delivery.closing_evidence(packet, inputs, identity)
            return {'status': 'OFFLINE_DELIVERY_EVIDENCE_READY_FOR_REVIEW'}

        with patch.object(gate, 'PRODUCTION', SYNTHETIC), patch.object(delivery, 'ROOT', self.repo), \
             patch.object(delivery, 'check_delivery', side_effect=physical_boundary):
            yield

    def freeze(self):
        freeze = gate.draft_freeze(self.repo, self.q, self.a, self.a_sha, terminal_time(25))
        frozen = save(self.repo, gate.FREEZE, freeze)
        self.cf = self.commit('CF synthetic construction freeze after A')
        self.link = dict(schema=gate.BINDING_SCHEMA, implementationCommit=self.q,
                         acceptancePublicationCommit=self.a, acceptanceSha256=self.a_sha,
                         constructionFreezePublicationCommit=self.cf,
                         constructionFreezeSha256=gate.digest(frozen.read_bytes()))
        self.link_path = save(self.base, binding.SIDECAR, self.link)

    def construct(self, output, sidecar=None):
        # The Mac uses its literal project root. Portable CI only translates that
        # one path constant to the designated project-local test directory.
        def fixture_path(value):
            path = Path(value)
            return self.base if path == PROJECT_ROOT else path

        self.git('checkout', '-q', '--detach', self.q)
        try:
            cross_platform = (nullcontext() if self.base.is_relative_to(PROJECT_ROOT)
                              else patch.object(finite_inputs, 'Path', side_effect=fixture_path))
            with cross_platform:
                return finite_inputs.construct(self.repo, self.q, self.backend['modelSha256'], output,
                                               construction_binding_path=sidecar)
        finally:
            self.git('checkout', '-q', '--detach', self.cf if hasattr(self, 'cf') else self.a)


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = ROOT / '.runtime'
        scratch.mkdir(exist_ok=True)
        temporary = TemporaryDirectory(prefix='four-block-e2e-synthetic-', dir=scratch)
        cls.addClassCleanup(temporary.cleanup)
        cls.base = Path(temporary.name).resolve()
        cls.fixture = SyntheticPublication(cls.base)

    def test_complete_synthetic_origin_refused_by_unmodified_formal_intake(self):
        f = self.fixture
        launch, terminal = known.verify_launched_pair(f.evidence, f.approval, f.approval_sha)
        self.assertEqual((launch['launchMode'], terminal['completedRepeats']), (SYNTHETIC, 2))
        self.assertFalse(terminal['qualificationDetermined'])
        with self.assertRaisesRegex(ValueError, 'only an actual approved Mac launch'):
            gate.verify_acceptance(f.repo, f.q, f.a, f.a_sha, f.base)

    def test_missing_decision_acceptance_and_freeze_cannot_construct(self):
        f = self.fixture
        output = self.base / 'never-construct'
        with self.assertRaisesRegex(ValueError, 'published acceptance and construction freeze'):
            f.construct(output)
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(ValueError, 'separate publication'):
            gate.verify_binding(f.repo, f.q, dict(
                schema=gate.BINDING_SCHEMA, implementationCommit=f.q,
                acceptancePublicationCommit=f.a, acceptanceSha256=f.a_sha,
                constructionFreezePublicationCommit=f.a, constructionFreezeSha256='a'*64,
            ))
        with self.assertRaises(subprocess.CalledProcessError):
            gate.verify_acceptance(f.repo, f.q, f.b, 'a'*64, f.base)
        pristine = f.git('rev-parse', 'HEAD')
        try:
            (f.repo / gate.DECISION).unlink()
            missing_q = f.commit('Synthetic Q successor without decision')
            with self.assertRaises(subprocess.CalledProcessError):
                gate.approved_decision(f.repo, missing_q)
        finally:
            f.git('checkout', '-q', '--detach', pristine)

    def test_synthetic_publication_to_four_isolated_child_blocks(self):
        # This synthesis uses only the isolated fixture Q as its identifier seed.
        import launch_heldout_blocks as heldout
        from finite_score import score_directory

        f = self.fixture
        inputs_relative = 'experiments/ch7/finite-heldout/synthetic-inputs'
        plan_relative = 'experiments/ch7/finite-heldout/synthetic-measurement-plan.json'
        manifest_relative = 'experiments/ch7/finite-heldout/synthetic-data-publication.json'
        temporary_inputs = self.base / 'synthetic-construction'
        inputs = f.repo / inputs_relative
        data_manifest = f.repo / manifest_relative
        plan = f.repo / plan_relative

        def preflight(expected_plan_sha):
            return heldout.preflight_inputs(f.repo, f.q, inputs, data_manifest,
                                            f.backend['modelSha256'], plan, expected_plan_sha)

        with f.trust_fixture_only():
            f.freeze()
            self.assertTrue(gate.ancestor(f.repo, f.a, f.cf))
            model_substitution = dict(f.link, constructionFreezeSha256='0' * 64)
            substituted = save(f.base, 'synthetic-substituted-binding.json', model_substitution)
            with self.assertRaisesRegex(ValueError, 'published freeze SHA differs'):
                f.construct(self.base/'refused-substitution', substituted)
            self.assertFalse((self.base/'refused-substitution').exists())
            f.construct(temporary_inputs, f.link_path)
            suitability = finite_validate.verify(f.repo, temporary_inputs)
            self.assertEqual(suitability['status'], 'PASS_ALL_FORTY_BEFORE_MEASUREMENT')
            self.assertEqual((suitability['casePairs'], suitability['conditionRows']), (40, 80))
            save(temporary_inputs, 'suitability-acceptance.json', suitability)
            self.assertFalse(inputs.exists())
            shutil.copytree(temporary_inputs, inputs)
            qualification_plan = binding.decode((f.repo/PLAN).read_bytes())
            save(f.repo, plan_relative, dict(
                schema='aijade.ch7.heldout-measurement-plan.v1', purpose='confirmed_finite_heldout',
                implementationCommit=f.q, buildFreezeCommit=f.b, inputsPath=inputs_relative,
                constructionBindingSha256=gate.digest((inputs/binding.SIDECAR).read_bytes()),
                qualifiedBackendSha256=gate.digest(known.encode(f.backend)),
                blocks=4, pairsPerBlock=10, conditionsPerBlock=20,
                watchdog=qualification_plan['watchdog'], toolsSha256=qualification_plan['toolsSha256'],
                databasePort=qualification_plan['databasePort'],
            ))
            expected_plan_sha = gate.digest(plan.read_bytes())
            # Merely placing the exact bytes in the worktree does not create D.
            with self.assertRaises((ValueError, OSError, subprocess.CalledProcessError)):
                preflight(expected_plan_sha)
            f.git('add', '-A')
            paths = f.git('diff', '--cached', '--name-only', f.q).splitlines()
            save(f.repo, manifest_relative, dict(
                schema='aijade.ch7.mac-data-publication.v1', implementationCommit=f.q,
                addedPaths=sorted([*paths, manifest_relative]),
            ))
            d = f.commit('D synthetic measurement inputs only')
            self.assertTrue(gate.ancestor(f.repo, f.cf, d))
            with self.assertRaisesRegex(ValueError, '(?i)(plan|sha|digest)'):
                preflight('0'*64)
            plan_bytes = plan.read_bytes()
            try:
                plan.write_bytes(plan_bytes + b' ')
                with self.assertRaisesRegex(ValueError, '(?i)(dirty|plan|sha|digest|changed)'):
                    preflight(expected_plan_sha)
            finally:
                plan.write_bytes(plan_bytes)
            case_path = inputs/'block-2'/'runtime-manifest.json'
            original_case = case_path.read_bytes()
            try:
                case_path.write_bytes(original_case + b' ')
                with self.assertRaisesRegex(ValueError, '(?i)(dirty|input|sha|digest|changed)'):
                    preflight(expected_plan_sha)
            finally:
                case_path.write_bytes(original_case)
            validated = preflight(expected_plan_sha)

        self.assertEqual(len({f.q, f.b, f.a, f.cf, d}), 5)
        self.assertFalse(f.git('remote'))

        def run(behavior, root):
            calls = []
            observed = []

            launch = dict(validated, mode=SYNTHETIC)

            def materials(index):
                source = inputs / f'block-{index + 1}'
                filenames = ('runtime-manifest.json', 'scoring-manifest.json')
                return {**{name: (source/name).read_bytes() for name in filenames},
                        'selection.json': (f.repo/finite_inputs.BANK).read_bytes()}

            def invoke(index, block, stdout, stderr):
                calls.append(index)
                command = [sys.executable, '-B', __file__, '--synthetic-child',
                           str(inputs / f'block-{index + 1}'), str(f.repo / finite_inputs.BANK),
                           str(f.repo / gate.BUILD), str(block), behavior]
                return subprocess.run(command, stdout=stdout, stderr=stderr, check=False).returncode

            def verify(index, block):
                evidence = heldout.block_evidence(block, launch, index, materials(index))
                result = score_directory(block)
                self.assertEqual(result['blockIndex'], index)
                self.assertEqual((result['casePairs'], result['measuredConditionRows']), (10, 20))
                rows = binding.decode((block/'cases.json').read_bytes())
                observed.extend((r['caseId'], r['condition']) for r in rows)
                for arm in ('C1', 'C2'):
                    self.assertEqual(result['arms'][arm]['scheduledInvalidPromotionOpportunities'], 7)
                    self.assertEqual(result['arms'][arm]['scheduledInvalidReuseOpportunities'], 8)
                return evidence

            result = heldout.execute_blocks(root, launch, invoke, verify)
            return result, calls, observed

        completed, calls, observed = run('complete', self.base / 'synthetic-complete')
        self.assertEqual(calls, [0, 1, 2, 3])
        self.assertEqual(len(observed), 80)
        self.assertEqual(len(set(observed)), 80)
        self.assertEqual(len({case_id for case_id, _ in observed}), 40)
        self.assertTrue(all(sum(arm == k for _, arm in observed) == 40 for k in ('C1', 'C2')))
        self.assert_result(completed, 'complete', 4)

        adverse = {
            'interrupted': 'finite child exit',
            'zero-exit-partial': 'receipt.json',
            'substituted-terminal': 'block does not bind this launch',
            'stale-terminal': 'outside its invocation window',
        }
        for behavior, reason in adverse.items():
            with self.subTest(behavior=behavior):
                output = self.base / ('synthetic-' + behavior)
                stopped, calls, observed = run(behavior, output)
                self.assertEqual(calls, [0, 1, 2])
                self.assertEqual(len(observed), 40)
                self.assert_result(stopped, 'stopped', 2)
                self.assertIn(reason, stopped['reason'])
                self.assertEqual(stopped['blocks'][2]['status'], 'STOPPED_UNVERIFIED')
                self.assertEqual(stopped['blocks'][3]['status'], 'UNATTEMPTED')
                snapshot = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
                self.assertTrue(snapshot)
                self.assertFalse((output/'block-4').exists())
                with self.assertRaises((OSError, ValueError)):
                    run('complete', output)
                self.assertEqual(snapshot, {p.relative_to(output): p.read_bytes()
                                            for p in output.rglob('*') if p.is_file()})

    def assert_result(self, result, state, completed):
        self.assertIn(state, result['status'].lower())
        self.assertEqual((result['verifiedPairs'], result['verifiedConditionRows']),
                         (completed * 10, completed * 20))
        self.assertEqual(result['mode'], SYNTHETIC)


def json_line(value):
    return (json.dumps(value, separators=(',', ':')) + '\n').encode()


def make_rows(runtime, rules):
    empty_read = dict(status=200, retrieved=False, executed=False)
    repetition = {r['caseId'] for r in rules if r['window'] == 'duplicate_invocation_2'}
    return [
        dict(caseId=case_id, condition=condition, gatewayAttempts=0,
             final=dict(specs=0, reports=0, specRows=[], reportRows=[], reuseCount=0,
                        authority=[], outcomeMemoryCount=0),
             round2=empty_read, duplicateReuse=empty_read if case_id in repetition else None,
             promotionAttempts=[], delivery=dict(status='SYNTHETIC_PLACEHOLDER'),
             prepared=dict(intentId='synthetic-intent-' + case_id),
             databaseBefore=dict(database=f'synthetic-lease-{i}'))
        for i, (case_id, condition) in enumerate(known.slots(runtime))
    ]


def write_closing_packet(root, runtime, backend, phases, rows):
    save(root, 'cases.json', rows)
    prepared = save(root, 'prepared.json', [
        dict(caseId=r['caseId'], condition=r['condition'], **r['prepared']) for r in rows
    ])
    events = [dict(caseId='batch', phase='batch.begin', detail=runtime)]
    events.extend(dict(caseId=r['caseId'] + '/' + r['condition'], phase='case.complete', detail=r)
                  for r in rows)
    save(root, 'journal.jsonl', b''.join(json_line(dict(event, sequence=i))
                                        for i, event in enumerate(events, 1)))
    session = 'synthetic-session'
    context = 'synthetic-renderer-context'
    save(root, 'renderer-request.json', dict(session=session, preparedSha256=gate.digest(prepared.read_bytes())))
    save(root, 'renderer-ready.json', dict(context=context))
    header = dict(session_id=session, renderer_context_id=context)
    stream = b''.join([json_line(dict(header, record='header', pmx_sha256=backend['modelSha256'],
                                      presented_frame_observed=False)), json_line(dict(record='synthetic-state'))])
    stream += json_line(dict(record='end', complete=True, lines=2, sha256=gate.digest(stream)))
    save(root, 'client/aijade-render-state.jsonl', stream)
    save(root, 'manifest.json', dict(file_sha256=gate.digest(stream)))
    save(root, 'renderer-closed.json', dict(exitCode=0, stateSha256=gate.digest(stream)))
    intents = list(dict.fromkeys(row['prepared']['intentId'] for row in rows))
    save(root, 'registry.jsonl', json_line(header) + b''.join(json_line(dict(intent_id=i)) for i in intents))
    save(root, 'flow.xml', ('<assemblies><assembly total="1" passed="1" failed="0" errors="0" '
                           'skipped="0" not-run="0"><collection>'
                           f'<test method="{delivery.FLOW_METHOD}" result="Pass" />'
                           '</collection></assembly></assemblies>\n').encode())
    save(root, 'process-cleanup.json', [dict(pid=p['pid'], exitCode=0, errors=[]) for p in phases.values()])
    leases = [r['databaseBefore'] for r in rows]
    save(root, 'database-leases.jsonl', b''.join(json_line(lease) for lease in leases))
    save(root, 'database-cleanup.json', [dict(lease, remaining=0, error=None) for lease in leases])


def synthetic_child(source, selection, build, output, behavior):
    """Pure file-writing process. It cannot start a backend or a model."""
    launch_body = (output.parent/'launch.json').read_bytes()
    launch = binding.decode(launch_body)
    if launch['mode'] != SYNTHETIC:
        raise ValueError('the fixture child requires a synthetic parent')
    runtime_name = 'runtime-manifest.json'
    scoring_name = 'scoring-manifest.json'
    runtime_bytes = (source/runtime_name).read_bytes()
    scoring_bytes = (source/scoring_name).read_bytes()
    runtime = binding.decode(runtime_bytes)
    contract = binding.decode(scoring_bytes)
    index = runtime['blockIndex']
    output.mkdir(parents=True, exist_ok=True)
    print(f'{SYNTHETIC} block {index + 1}', flush=True)
    save(output, runtime_name, runtime_bytes)
    save(output, scoring_name, scoring_bytes)
    save(output, 'selection.json', selection.read_bytes())
    rows = make_rows(runtime, contract['cases'])
    if index == 2 and behavior in ('interrupted', 'zero-exit-partial'):
        save(output, 'cases.json', rows[:7])
        return 9 if behavior == 'interrupted' else 0
    started = terminal_time(1) if index == 2 and behavior == 'stale-terminal' else known.utc()
    phases = {name: dict(pid=(index + 1)*100 + i, createTime=float(i), exitCode=0,
                         startedAt=started, endedAt=known.utc())
              for i, name in enumerate(('flow', 'renderer'), 1)}
    write_closing_packet(output, runtime, launch['backend'], phases, rows)
    processes = [{k: phase[k] for k in ('pid', 'createTime')} for phase in phases.values()]
    controller = dict(pid=(index + 1)*100, createTime=0.0)
    registry = save(output, 'owned-process-registry.json', dict(
        status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT',
        controllers=[controller], explicitlyRegisteredIdentities=processes,
        knownIdentities=[controller, *processes], remainingIdentities=[],
        retiredIdentities=[dict(process, status='ABSENT', observedCreateTime=None) for process in processes],
    ))
    save(output, 'telemetry.jsonl', json_line(dict(processObservation=dict(ownedProcesses=processes))))
    save(output, 'frozen-build.json', build.read_bytes())
    common = {key: launch[key] for key in ('repositoryCommit', 'executionPlanSha256', 'buildFreezeCommit',
                                          'buildFreezePath', 'dataPublicationManifestSha256',
                                          'operationalWatchdog')}
    common.update(codeCommit=launch['implementationCommit'], heldoutLaunchIndex=index,
                  heldoutLaunchSha256=gate.digest(launch_body))
    terminal_binding = dict(common)
    if index == 2 and behavior == 'substituted-terminal':
        terminal_binding['heldoutLaunchSha256'] = '0'*64
    save(output, 'receipt.json', dict(
        terminal_binding, **{field: [] for field in known.EMPTY_FIELDS},
        schema='aijade.ch7.finite-block-receipt.v1', status=known.COMPLETE, reason=None,
        completedCases=len(rows), purpose=launch['purpose'], conditionsMeasured=['C1', 'C2'],
        formalHardwareQualification=False, blockIndex=index, plannedPairs=10, plannedCases=20,
        heldOutCases=10, modelRequests=0, phases=phases, finishedAt=known.utc(),
        ownedProcessRegistrySha256=gate.digest(registry.read_bytes()),
    ))
    save(output, 'input-identities.json', dict(
        common, **launch['backend'], constructionFreezeCommit=runtime['constructionFreezeCommit'],
        runtimeManifestSha256=gate.digest(runtime_bytes), scoringManifestSha256=gate.digest(scoring_bytes),
    ))
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 7 and sys.argv[1] == '--synthetic-child':
        raise SystemExit(synthetic_child(*(Path(path) for path in sys.argv[2:6]), sys.argv[6]))
    unittest.main()
