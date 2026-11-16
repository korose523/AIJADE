"""Offline sequence controls using deliberately nonexecutable synthetic raw fixtures.

Block closure/Git/process delegates are mocked here; they remain mandatory in the
public auditor. These fixtures have no code/programme/renderer inputs, seed or
fresh operational cases and cannot pass the real finite block auditor. Existing
fixed window definitions and the separate scorer supply numerical controls.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'experiments/ch7'))
import finite_sequence_audit as audit
from finite_score import score_directory

Q, B, I = '1' * 40, '2' * 40, '3' * 40
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def stamp(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, indent=2) + '\n'
    if path.exists() and path.read_text() == body:
        raise AssertionError('no-op synthetic fixture mutation')
    path.write_text(body)


def write_lines(path, values):
    body = ''.join(json.dumps(value) + '\n' for value in values)
    if path.exists() and path.read_text() == body:
        raise AssertionError('no-op synthetic JSONL mutation')
    path.write_text(body)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observation(rss=100):
    return dict(status='PASS', blockers=[], ownedRoots=[dict(pid=9, createTime=1.0)],
                ownedProcesses=[dict(pid=9, createTime=1.0, parentPid=1, rssBytes=rss)])


def sample(position, local=None):
    obs = observation(); obs.update(startedMonotonic=1000 + position + .01,
        finishedMonotonic=1000 + position + .02, sampleId=format(1000000 + position, '032x'))
    return dict(utc=stamp(120 + position), monotonicSeconds=1000 + position,
                sequenceElapsedSeconds=position, elapsedSeconds=position if local is None else local,
                observationCompletedMonotonic=1000 + position + .05,
                rssBytes=100, availableBytes=6 * 1024**3, swapUsedBytes=100,
                swapIncreaseBytes=0, processObservation=obs,
                processPolicySha256=hashlib.sha256(b'{"synthetic":true}\n').hexdigest(), observerModuleSha256='a' * 64)


class SequenceAuditControls(unittest.TestCase):
    def setUp(self):
        scratch = REPO / '.runtime/tmp'; scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='sequence-audit-nonexecutable-', dir=scratch)
        self.scratch = Path(self.temp.name); self.root = self.scratch / 'observations'; self.repo = self.scratch / 'source'
        self.root.mkdir(); self.repo.mkdir()
        self.patches = [patch.object(audit, '_audit_block', side_effect=self.block_delegate),
                        patch.object(audit, '_repository_binding', side_effect=self.binding_delegate),
                        patch.object(audit, '_audit_construction', return_value=dict(status='PASS_ALL_FORTY_BEFORE_MEASUREMENT', casePairs=40, conditionRows=80)),
                        patch.object(audit, '_process_observation', side_effect=self.process_delegate),
                        patch.object(audit, '_ownership', return_value=dict(syntheticNonExecutableDelegate=True))]
        self.mocks = [control.start() for control in self.patches]

    def tearDown(self):
        for control in reversed(self.patches):
            control.stop()
        self.temp.cleanup()

    def process_delegate(self, value, policy, module, configuration):
        if value['status'] != 'PASS' or value['blockers']:
            raise ValueError('synthetic process refusal')

    def binding_delegate(self, repo, q, i, manifest):
        return dict(implementationCommit=q, repositoryCommit=i, inputPublicationCommit=i if i != q else None,
            dataPublicationManifestPath=manifest,
            dataPublicationManifestSha256=sha(repo / manifest) if manifest else None,
            addedDataPaths=['inputs/synthetic-only.json'] if i != q else [])

    def block_delegate(self, root, repo):
        # This is the existing independent numerical implementation, not the new reconstructor.
        score = score_directory(root)
        return dict(status='FINITE_DATAFLOW_AUDIT_PASS', casePairs=10, measuredConditionRows=20,
                    conditionCounts={arm: {k: v for k, v in score['arms'][arm].items() if k != 'byCase'}
                                     for arm in ['C1', 'C2']})

    def load(self, path):
        return json.loads(path.read_text())

    def fixture(self, formal=False):
        blocks = 4 if formal else 1; purpose = 'confirmed_finite_heldout' if formal else 'qualification_only'
        (self.repo / 'policy.json').write_text('{"synthetic":true}\n')
        (self.root / 'process-policy.json').write_bytes((self.repo / 'policy.json').read_bytes())
        (self.repo / 'data.json').write_text('{"syntheticNonExecutable":true}\n')
        shared = dict(codeCommit=Q, implementationCommit=Q, repositoryCommit=I if formal else Q,
            buildFreezeCommit=B, buildFreezePath='new/frozen-build.json',
            inputPublicationCommit=I if formal else None,
            dataPublicationManifestPath='data.json' if formal else None,
            dataPublicationManifestSha256=sha(self.repo / 'data.json') if formal else None,
            addedDataPaths=['inputs/synthetic-only.json'] if formal else [],
            processPolicyPath='policy.json', processPolicySha256=sha(self.repo / 'policy.json'),
            observerModuleSha256='a' * 64, executionPlanSha256=audit.PLAN_SHA256)
        sequence = dict(schema='aijade.ch7.finite-sequence-receipt.v1', status='COMPLETE_FINITE_SEQUENCE_OBSERVATIONS',
            purpose=purpose, plannedBlocks=blocks, completedBlocks=blocks, plannedPairs=10 * blocks,
            plannedConditionRows=20 * blocks, completedConditionRows=20 * blocks,
            inFlightCaseIds=[], unknownCaseIds=[], unattemptedCaseIds=[], blocks=[], modelRequests=0,
            formalHardwareQualification=False, independentHumanReview=False,
            controllerProcess=dict(pid=9, createTime=1.0), blockControllers=[],
            sequenceEpochMonotonic=1000.0, initialSystemSwapUsedBytes=100,
            startedAt=stamp(120), finishedAt=stamp(120 + blocks * 20), wallSeconds=blocks * 20,
            reason=None, **shared)
        registry = audit.window_registry()
        for block_index in range(blocks):
            root = self.root / ('block-' + str(block_index + 1)); root.mkdir()
            (root / 'process-policy.json').write_bytes((self.repo / 'policy.json').read_bytes())
            (root / 'selection.json').write_text('{"syntheticNonExecutable":true}\n')
            runtime = dict(schema='aijade.ch7.live-case-manifest.v2', purpose=purpose, blockIndex=block_index,
                           constructionFreezeCommit=Q, selectionSha256=sha(root / 'selection.json'), cases=[])
            rules = []; rows = []
            for number, (window, definition) in enumerate(registry.items()):
                cid = 'nonexecutable_b%d_%d' % (block_index, number)
                conditions = ['C1', 'C2'] if number < 5 else ['C2', 'C1']
                runtime['cases'].append(dict(input=dict(caseId=cid, conditions=conditions)))
                rule = dict(caseId=cid, **definition); rules.append(rule)
                for arm in conditions:
                    # Legal baseline for each window, plus deliberately adverse C2 integrity outcomes.
                    promoted = definition['allowedSpecs']
                    reused = definition['allowedReuses']
                    if arm == 'C2' and window == 'execution_receipt_intent':
                        promoted = reused = 1
                    ids = [cid + arm + str(i) for i in range(promoted)]
                    state = 'revoked' if window == 'revocation_before_round2' else 'verified' if promoted else 'unknown'
                    duplicate = window == 'duplicate_invocation_2'
                    reuse = dict(status=200, executed=bool(reused), retrieved=bool(reused))
                    # The duplicate control allows one first reuse and refuses its repeated query.
                    final = dict(specs=promoted, reports=promoted, specRows=[dict(id=i) for i in ids],
                        reportRows=[dict(id='report_' + i, result=dict(evolutionSpecId=i)) for i in ids],
                        authority=[dict(state=state, scope='behavior_overlay_pre_solve')], reuseCount=reused, outcomeMemoryCount=promoted)
                    rows.append(dict(caseId=cid, condition=arm,
                        databaseBefore=dict(database='synthetic_db_' + cid + arm), final=final,
                        round2=reuse, duplicateReuse=dict(status=200, executed=False, retrieved=False) if duplicate else None,
                        promotionAttempts=[dict(invocation=i + 1, serviceResult=dict(ok=bool(promoted)))
                                           for i in range(2 if duplicate else 1)], delivery=dict(status=200)))
            write(root / 'runtime-manifest.json', runtime)
            contract = dict(schema='aijade.ch7.finite-scoring-manifest.v1', purpose=purpose,
                constructionFreezeCommit=Q, blockIndex=block_index, runtimeManifestSha256=sha(root / 'runtime-manifest.json'),
                selectionSha256=runtime['selectionSha256'], conditions=[dict(id='C1', policy='strong-local-v1'), dict(id='C2', policy='cross-module-v1')],
                windowRegistrySha256=audit.REGISTRY_SHA256, cases=rules,
                scheduledInvalidPromotionOpportunitiesPerCondition=sum(r['promotionOpportunity'] for r in rules),
                scheduledInvalidReuseOpportunitiesPerCondition=sum(r['reuseOpportunity'] for r in rules),
                round2SemanticActCorrectness='NOT_MEASURED')
            write(root / 'scoring-manifest.json', contract); write(root / 'cases.json', rows)
            identity = dict(shared, purpose=purpose, constructionFreezeCommit=Q,
                controllerProcess=dict(pid=100 + block_index, createTime=2.0 + block_index),
                runtimeManifestSha256=sha(root / 'runtime-manifest.json'), scoringManifestSha256=sha(root / 'scoring-manifest.json'),
                selectionSha256=runtime['selectionSha256'], modelSha256='b' * 64, buildManifestSha256='c' * 64,
                benchSha256='d' * 64, earlierSourceFreezeSha256='e' * 64,
                binaries={'synthetic.dll': '1' * 64}, rendererSources={'synthetic.cs': '2' * 64},
                realGodotSha256='3' * 64, godotWrapperSha256='4' * 64, sandboxProfileSha256='5' * 64,
                databaseContainer='synthetic-not-a-service', preparedRenderer=dict(files={'synthetic.dll': '6' * 64}),
                runtimeRepositoryPath='inputs/block-%d/runtime-manifest.json' % (block_index + 1))
            write(root / 'input-identities.json', identity)
            offset = block_index * 20
            phases = {name: dict(startedAt=stamp(120 + offset + start), endedAt=stamp(120 + offset + end), exitCode=0,
                                pid=200 + block_index * 10 + order, createTime=3.0 + block_index + order / 10)
                      for order, (name, start, end) in enumerate([('prefix', 1, 3), ('renderer', 4, 6), ('flow', 7, 16)])}
            receipt = dict(schema='aijade.ch7.finite-block-receipt.v1', status='COMPLETE_FINITE_BLOCK_OBSERVATIONS',
                controllerProcess=identity['controllerProcess'],
                purpose=purpose, blockIndex=block_index, plannedCases=20, completedCases=20, plannedPairs=10,
                inFlightCaseIds=[], unknownCaseIds=[], unattemptedCaseIds=[], dispositionErrors=[], logCloseErrors=[],
                modelRequests=0, formalHardwareQualification=False, reason=None, sequenceEpochMonotonic=1000.0,
                initialSystemSwapUsedBytes=100, wallSeconds=18, phases=phases, finishedAt=stamp(120 + offset + 18), **shared)
            write(root / 'receipt.json', receipt); sequence['blocks'].append(receipt)
            sequence['blockControllers'].append(dict(blockIndex=block_index, **identity['controllerProcess']))
            write(root / 'database-cleanup.json', [dict(database=r['databaseBefore']['database'], remaining=0, error=None) for r in rows])
            write(root / 'process-cleanup.json', [dict(exitCode=0, errors=[]) for _ in range(2)])
            write_lines(root / 'journal.jsonl', [dict(monotonicTicks=1000000 + offset * 1000 + i + 1, frequency=1000) for i in range(20)])
            write_lines(root / 'telemetry.jsonl', [sample(offset + i, i) for i in range(0, 19, 2)])
        write(self.root / 'receipt.json', sequence)
        write_lines(self.root / 'process-observations.jsonl', [sample(i) for i in range(0, blocks * 20 + 1, 2)])
        for name, duration, origin, clock_origin in ([('settling', 600, -600, 280)] if not formal else []) + [('admission', 120, 0, 880)]:
            (self.root / name).mkdir()
            samples = [dict(utc=stamp(origin + i), elapsedSeconds=i, monotonicSeconds=clock_origin + i,
                observationCompletedMonotonic=clock_origin + i + .05, observationDurationSeconds=.05,
                availableBytes=6 * 1024**3, swapUsedBytes=100,
                processObservation=dict(status='PASS', blockers=[], ownedRoots=[], ownedProcesses=[],
                    startedMonotonic=clock_origin + i + .01, finishedMonotonic=clock_origin + i + .02,
                    sampleId=format(int((clock_origin + i) * 1000), '032x')),
                processPolicySha256=shared['processPolicySha256'], observerModuleSha256=shared['observerModuleSha256']) for i in range(0, duration, 2)]
            write_lines(self.root / name / 'telemetry.jsonl', samples)
            write(self.root / name / 'receipt.json', dict(status='ADMITTED' if name == 'admission' else 'FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION',
                windowReset=False, intervalReset=False, elapsedSeconds=duration, samples=len(samples),
                minimumAvailableBytes=6 * 1024**3, swapRangeBytes=0,
                precedingFixedSettlingSeconds=0 if formal else 600,
                phaseClock=dict(startMonotonic=clock_origin, endMonotonic=clock_origin + duration,
                                requestedSeconds=duration, intervalReset=False), **shared))
        return sequence

    def change_block_receipt(self, index, change):
        path = self.root / ('block-%d/receipt.json' % index); value = self.load(path); change(value); write(path, value)
        sequence = self.load(self.root / 'receipt.json'); sequence['blocks'][index - 1] = value; write(self.root / 'receipt.json', sequence)

    def test_known_qualification_population_and_real_registry_denominators(self):
        self.fixture(); result = audit.verify(self.root, self.repo)
        self.assertTrue(result['strictAccepted']); self.assertEqual(result['measuredConditionRows'], 20)
        self.assertEqual((result['scheduledInvalidPromotionOpportunitiesPerArm'], result['scheduledInvalidReuseOpportunitiesPerArm']), (7, 8))
        self.assertEqual(result['freshFiniteHeldoutPairs'], 0); self.assertEqual(self.mocks[0].call_count, 1)

    def test_formal_population_independent_raw_counts_retain_adverse_c2(self):
        self.fixture(True); result = audit.verify(self.root, self.repo)
        self.assertTrue(result['strictAccepted']); self.assertEqual(result['measuredConditionRows'], 80)
        self.assertEqual((result['scheduledInvalidPromotionOpportunitiesPerArm'], result['scheduledInvalidReuseOpportunitiesPerArm']), (28, 32))
        self.assertEqual(result['differencesC2MinusC1'], dict(invalidDurablePromotions=4, integrityInvalidReuse=4))
        self.assertEqual(result['normalOutcomeCounts'], dict(C1={'accepted': 4}, C2={'accepted': 4}))
        self.assertEqual(result['semanticLimitObservations']['C2']['associatedPromotions'], 4)
        self.assertEqual(result['semanticLimitObservations']['C2']['round2SemanticActCorrectness'], 'NOT_MEASURED')
        self.assertEqual(self.mocks[0].call_count, 4); self.mocks[2].assert_called_once_with(self.repo, self.repo / 'inputs')

    def test_fixtures_cannot_substitute_for_the_real_block_audit(self):
        self.fixture()
        self.patches[0].stop()
        with self.assertRaises((ValueError, KeyError, FileNotFoundError, AssertionError, subprocess.CalledProcessError)):
            audit.verify(self.root, self.repo)

    def test_missing_or_extra_block_is_not_a_smaller_population(self):
        self.fixture(True); shutil.rmtree(self.root / 'block-4')
        with self.assertRaisesRegex(ValueError, 'block directory'): audit.verify(self.root, self.repo)
        (self.root / 'block-4').mkdir(); (self.root / 'block-5').mkdir()
        with self.assertRaisesRegex(ValueError, 'block directory'): audit.verify(self.root, self.repo)

    def test_unknown_disposition_and_stopped_status_never_become_zero(self):
        self.fixture(); path = self.root / 'receipt.json'; original = self.load(path)
        for change in [dict(unknownCaseIds=['unobserved/C2']), dict(status='STOPPED'), dict(completedConditionRows=19)]:
            write(path, dict(original, **change))
            with self.assertRaises(ValueError): audit.verify(self.root, self.repo)

    def test_reordered_embedded_blocks_are_rejected(self):
        self.fixture(True); path = self.root / 'receipt.json'; value = self.load(path)
        value['blocks'][0], value['blocks'][1] = value['blocks'][1], value['blocks'][0]; write(path, value)
        with self.assertRaisesRegex(ValueError, 'embedded block'): audit.verify(self.root, self.repo)

    def test_missing_or_duplicate_condition_rows_are_rejected(self):
        self.fixture(); path = self.root / 'block-1/cases.json'; value = self.load(path)
        write(path, value[:-1])
        with self.assertRaises(ValueError): audit.verify(self.root, self.repo)
        write(path, value[:-1] + [copy.deepcopy(value[0])])
        with self.assertRaises(ValueError): audit.verify(self.root, self.repo)

    def test_coherently_rebound_shrunk_window_is_rejected(self):
        self.fixture(); block = self.root / 'block-1'; value = self.load(block / 'scoring-manifest.json')
        value['scheduledInvalidReuseOpportunitiesPerCondition'] = 7; write(block / 'scoring-manifest.json', value)
        identity = self.load(block / 'input-identities.json'); identity['scoringManifestSha256'] = sha(block / 'scoring-manifest.json'); write(block / 'input-identities.json', identity)
        with self.assertRaises(ValueError): audit.verify(self.root, self.repo)

    def test_inconsistent_q_or_binary_inputs_are_rejected(self):
        self.fixture(True); path = self.root / 'block-2/input-identities.json'; original = self.load(path)
        for change in [dict(implementationCommit='4' * 40), dict(modelSha256='f' * 64)]:
            write(path, dict(original, **change))
            with self.assertRaises(ValueError): audit.verify(self.root, self.repo)

    def test_repository_binding_failure_is_not_silently_ignored(self):
        self.fixture(True); self.mocks[1].side_effect = ValueError('non-data I change')
        with self.assertRaisesRegex(ValueError, 'non-data I'): audit.verify(self.root, self.repo)

    def test_unknown_cleanup_is_rejected(self):
        self.fixture(); path = self.root / 'block-1/database-cleanup.json'; value = self.load(path)
        value[0].update(remaining=None, error='unobserved SQL result'); write(path, value)
        with self.assertRaisesRegex(ValueError, 'cleanup'): audit.verify(self.root, self.repo)

    def test_cross_block_database_reuse_is_rejected(self):
        self.fixture(True); old = self.load(self.root / 'block-1/cases.json')[0]['databaseBefore']['database']
        block = self.root / 'block-2'; rows = self.load(block / 'cases.json'); previous = rows[0]['databaseBefore']['database']
        rows[0]['databaseBefore']['database'] = old; write(block / 'cases.json', rows)
        cleanup = self.load(block / 'database-cleanup.json')
        for value in cleanup:
            if value['database'] == previous: value['database'] = old
        write(block / 'database-cleanup.json', cleanup)
        with self.assertRaisesRegex(ValueError, 'database reused'): audit.verify(self.root, self.repo)

    def test_overlap_and_resource_baseline_reset_are_rejected(self):
        self.fixture(True)
        self.change_block_receipt(2, lambda value: value.update(initialSystemSwapUsedBytes=101))
        with self.assertRaisesRegex(ValueError, 'resource baseline'): audit.verify(self.root, self.repo)
        self.change_block_receipt(2, lambda value: value.update(initialSystemSwapUsedBytes=100))
        self.change_block_receipt(2, lambda value: value['phases']['prefix'].update(startedAt=stamp(125)))
        with self.assertRaisesRegex(ValueError, 'chronology'): audit.verify(self.root, self.repo)

    def test_process_or_api_refusal_is_rejected(self):
        self.fixture(); path = self.root / 'process-observations.jsonl'
        values = [json.loads(line) for line in path.read_text().splitlines()]
        values[2]['processObservation'].update(status='UNKNOWN', blockers=['API read failed']); write_lines(path, values)
        with self.assertRaisesRegex(ValueError, 'process refusal'): audit.verify(self.root, self.repo)

    def test_rss_is_raw_same_time_family_sum_and_swap_is_same_baseline(self):
        self.fixture(); path = self.root / 'process-observations.jsonl'
        values = [json.loads(line) for line in path.read_text().splitlines()]; original = copy.deepcopy(values)
        values[2]['rssBytes'] = 99; write_lines(path, values)
        with self.assertRaisesRegex(ValueError, 'RSS not reconstructed'): audit.verify(self.root, self.repo)
        values = original; values[2]['swapIncreaseBytes'] = 1; write_lines(path, values)
        with self.assertRaisesRegex(ValueError, 'swap baseline'): audit.verify(self.root, self.repo)

    def test_global_sustained_timer_cannot_reset_between_blocks(self):
        self.fixture(True); path = self.root / 'process-observations.jsonl'
        values = [json.loads(line) for line in path.read_text().splitlines()]
        for value in values:
            if 18 <= value['sequenceElapsedSeconds'] <= 50:
                value['rssBytes'] = 2 * 1024**3 + 1
                value['processObservation']['ownedProcesses'][0]['rssBytes'] = value['rssBytes']
        write_lines(path, values)
        with self.assertRaisesRegex(ValueError, 'sustained sequence rss'): audit.verify(self.root, self.repo)

    def test_admission_gap_and_claimed_summary_are_independently_checked(self):
        self.fixture(); path = self.root / 'admission/telemetry.jsonl'
        values = [json.loads(line) for line in path.read_text().splitlines()]
        values[5]['elapsedSeconds'] += 1.1; values[5]['monotonicSeconds'] += 1.1; write_lines(path, values)
        with self.assertRaisesRegex(ValueError, 'admission coverage'): audit.verify(self.root, self.repo)

    def test_block_scorer_total_cannot_replace_raw_reconstruction(self):
        self.fixture(); original = self.block_delegate
        def forged(root, repo):
            result = original(root, repo); result['conditionCounts']['C2']['invalidDurablePromotions'] = 0
            return result
        self.mocks[0].side_effect = forged
        with self.assertRaisesRegex(ValueError, 'independent raw count'): audit.verify(self.root, self.repo)

    def test_fixed_phase_clock_and_settling_transition_are_bound(self):
        self.fixture(); path = self.root / 'admission/receipt.json'; value = self.load(path)
        value['phaseClock']['endMonotonic'] = 1004; value['elapsedSeconds'] = 124; write(path, value)
        with self.assertRaisesRegex(ValueError, 'fixed phase clock'): audit.verify(self.root, self.repo)

    def test_measured_unknown_normal_state_is_reported_separately(self):
        self.fixture(); path = self.root / 'block-1/cases.json'; rows = self.load(path)
        normal = next(row for row in rows if row['caseId'].endswith('_0') and row['condition'] == 'C2')
        normal['final'].update(specs=0, reports=0, specRows=[], reportRows=[], reuseCount=0, outcomeMemoryCount=0,
                               authority=[dict(state='unknown', scope='behavior_overlay_pre_solve')])
        normal['round2'].update(executed=False, retrieved=False); write(path, rows)
        result = audit.verify(self.root, self.repo)
        self.assertEqual(result['normalOutcomeCounts']['C2'], {'unknown': 1})
        self.assertEqual(result['measuredConditionRows'], 20)

    def test_unloaded_phase_cannot_authorize_a_foreign_research_root(self):
        self.fixture(); path = self.root / 'admission/telemetry.jsonl'
        values = [json.loads(line) for line in path.read_text().splitlines()]
        values[0]['processObservation']['ownedRoots'] = [dict(pid=777, createTime=1.0)]
        write_lines(path, values)
        with self.assertRaisesRegex(ValueError, 'unloaded phase'): audit.verify(self.root, self.repo)

    def test_replayed_old_or_duplicate_observer_samples_are_rejected(self):
        self.fixture(); path = self.root / 'process-observations.jsonl'
        values = [json.loads(line) for line in path.read_text().splitlines()]; original = copy.deepcopy(values)
        values[2]['processObservation']['startedMonotonic'] = 1; values[2]['processObservation']['finishedMonotonic'] = 2
        write_lines(path, values)
        with self.assertRaisesRegex(ValueError, 'outside this sample'): audit.verify(self.root, self.repo)
        values = original; values[2]['processObservation']['sampleId'] = values[1]['processObservation']['sampleId']; write_lines(path, values)
        with self.assertRaisesRegex(ValueError, 'duplicate process sample'): audit.verify(self.root, self.repo)

    def test_root_authorization_remembers_descendants_but_rejects_foreign_roots(self):
        self.patches[4].stop()
        root = self.scratch / 'lease-control'; root.mkdir()
        controller = dict(pid=9, createTime=1.0); child = dict(pid=10, createTime=2.0)
        def nodes(parent):
            return [dict(controller, parentPid=1), dict(child, parentPid=parent)]
        samples = []
        for index in range(2):
            obs = dict(ownedRoots=[controller] if index == 0 else [controller, child],
                finishedMonotonic=1000.1 + 2 * index,
                ownedProcesses=[dict(controller, parentPid=1, rssBytes=10), dict(child, parentPid=9 if index == 0 else 1, rssBytes=20)],
                evidence={phase: dict(processGraph=dict(nodes=nodes(9 if index == 0 else 1))) for phase in ['before', 'after']})
            samples.append(dict(processObservation=obs))
        registry = dict(status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT', controllers=[controller],
            knownIdentities=[controller, child], explicitlyRegisteredIdentities=[], remainingIdentities=[],
            retiredIdentities=[dict(child, status='ABSENT', observedCreateTime=None, checkedMonotonic=1003)])
        write(root / 'owned-process-registry.json', registry)
        receipt = dict(controllerProcess=controller, sequenceEpochMonotonic=1000, wallSeconds=10,
                       ownedProcessRegistrySha256=sha(root / 'owned-process-registry.json'))
        accepted = audit._ownership(root, receipt, samples, [])
        self.assertEqual(accepted['witnessedOwnedIdentities'], 2)
        foreign = dict(pid=11, createTime=3.0); samples[1]['processObservation']['ownedRoots'].append(foreign)
        with self.assertRaisesRegex(ValueError, 'unleased'): audit._ownership(root, receipt, samples, [])


if __name__ == '__main__':
    unittest.main()
