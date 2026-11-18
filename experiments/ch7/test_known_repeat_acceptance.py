"""Offline controls for the successor gate, using named synthetic data only."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import finite_construction_binding as historical
from finite_inputs import construct
import known_repeat_acceptance as gate


Q, B, A, F = ('1' * 40, '2' * 40, '3' * 40, '4' * 40)
PLAN = gate.PREFIX + 'execution-plan.json'
PLAN_BYTES = b'{"fixture":"offline synthetic execution plan"}\n'
BANK = 'experiments/ch7/finite-heldout/candidate-bank.json'


def body(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def backend():
    return {
        'modelSha256': '1' * 64,
        'realGodotSha256': '2' * 64,
        'godotWrapperSha256': '3' * 64,
        'sandboxProfileSha256': '4' * 64,
        'rendererSources': {'fixture.godot': '5' * 64},
        'preparedRenderer': {'status': 'PREBUILT_NO_RUNTIME_REBUILD', 'files': {'fixture.dll': '6' * 64}},
        'binaries': {'fixture-test.dll': '7' * 64},
        'buildManifestSha256': '8' * 64,
        'benchSha256': '9' * 64,
        'earlierSourceFreezeSha256': 'a' * 64,
        'databaseContainer': 'offline-synthetic-no-database',
        'explicitDockerPath': '/offline-synthetic/does-not-run',
    }


def decision():
    return {
        'schema': gate.DECISION_SCHEMA, 'status': 'SUPERVISOR_REPLY_CONFIRMED',
        'executionPlanPath': PLAN, 'executionPlanSha256': gate.digest(PLAN_BYTES),
        'qualificationPlanSha256': 'b' * 64, 'replySha256': 'c' * 64,
    }


def approval():
    return {
        'schema': 'aijade.ch7.known-repeat-approval.v1',
        'status': 'SUPERVISOR_REPLY_CONFIRMED',
        'implementationCommit': Q, 'backend': backend(),
        **{name: decision()[name] for name in gate.APPROVAL_FIELDS},
    }


class GateControls(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / '.runtime'
        scratch.mkdir(exist_ok=True)
        temporary = TemporaryDirectory(prefix='known-repeat-acceptance-fixtures-', dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.repo.joinpath(BANK).parent.mkdir(parents=True)
        self.repo.joinpath(BANK).write_text('this is a synthetic candidate bank placeholder')
        self.sources = {BANK: gate.digest(self.repo.joinpath(BANK).read_bytes())}
        self.acceptance = {'acceptedAt': '2026-11-18T09:00:00Z', 'qualifiedBackend': backend()}
        self.link = {
            'schema': gate.BINDING_SCHEMA, 'implementationCommit': Q,
            'acceptancePublicationCommit': A, 'acceptanceSha256': 'd' * 64,
            'constructionFreezePublicationCommit': F, 'constructionFreezeSha256': '',
        }
        self.freeze = {
            'schema': gate.FREEZE_SCHEMA, 'constructionFreezeCommit': Q,
            'frozenAt': '2026-11-18T09:01:00Z', 'executionPlanSha256': gate.digest(PLAN_BYTES),
            'qualificationAcceptance': {n: self.link[n] for n in ('acceptancePublicationCommit', 'acceptanceSha256')},
            'qualifiedBackend': backend(), 'modelSha256': backend()['modelSha256'],
            'sources': dict(self.sources), 'candidateBankSha256': self.sources[BANK],
        }

    def bound_freeze(self, mutate=None, *, expected_error=None):
        if mutate is not None:
            mutate(self.freeze)
        raw_freeze = body(self.freeze)
        self.link['constructionFreezeSha256'] = gate.digest(raw_freeze)
        with patch.object(gate, 'approved_decision', return_value=decision()), \
             patch.object(gate, 'ancestor', side_effect=lambda _repo, source, later: (source, later) == (A, F)), \
             patch.object(gate, 'raw', return_value=raw_freeze), \
             patch.object(gate, 'construction_sources', return_value=self.sources), \
             patch.object(gate, 'verify_acceptance', return_value=self.acceptance) as accepted:
            if expected_error is None:
                self.assertEqual(gate.verify_binding(self.repo, Q, self.link), self.freeze)
                accepted.assert_called_once()
            else:
                with self.assertRaisesRegex(ValueError, expected_error):
                    gate.verify_binding(self.repo, Q, self.link)

    def test_complete_freeze_checks_structure_against_verified_acceptance(self):
        # The positive acceptance return is explicit mocking. No synthetic packet
        # is accepted by the real qualification reader in this test.
        self.bound_freeze()

    def test_frozen_implementation_cannot_skip_successor_decision(self):
        new_tree = gate.SOURCE.encode() + b'\n'
        with patch.object(historical, 'git_bytes', return_value=new_tree):
            self.assertTrue(gate.required(self.repo, Q))
        with patch.object(historical, 'known_repeat_required', return_value=True):
            with self.assertRaisesRegex(ValueError, 'published construction binding'):
                historical.load_construction_freeze(self.repo, Q, self.repo)
            with self.assertRaisesRegex(ValueError, 'known-repeat construction binding'):
                historical.verify_binding(self.repo, Q, {'schema': 'aijade.ch7.published-construction-binding.v1'})

    def test_historical_dispatch_does_not_import_the_successor(self):
        with patch.object(historical, 'git_bytes', return_value=b''), \
             patch.object(historical, 'new_decision_required', return_value=False), \
             patch.dict(sys.modules, {'known_repeat_acceptance': None}):
            self.assertFalse(historical.known_repeat_required(self.repo, Q))
            with self.assertRaisesRegex(ValueError, 'prefix construction requires'):
                historical.verify_binding(self.repo, Q, {'schema': 'historical-fixture'})

    def test_actual_constructor_refuses_before_a_seed_or_file_exists(self):
        output = self.repo / 'no-fresh-cases'
        with patch('finite_inputs.subprocess.check_output', side_effect=['', Q + '\n']), \
             patch.object(historical, 'known_repeat_required', return_value=True), \
             patch('finite_inputs.derive_suite') as derive:
            with self.assertRaisesRegex(ValueError, 'published acceptance and construction freeze'):
                construct(self.repo, Q, backend()['modelSha256'], output)
        derive.assert_not_called()
        self.assertFalse(output.exists())

    def test_pending_decision_and_substituted_plan_are_rejected(self):
        changed = dict(decision(), status='PENDING_SUPERVISOR_REPLY')
        with patch.object(gate, 'required', return_value=True), \
             patch.object(gate, 'raw', return_value=body(changed)):
            with self.assertRaisesRegex(ValueError, 'reply has not been confirmed'):
                gate.approved_decision(self.repo, Q)
        with patch.object(gate, 'required', return_value=True), \
             patch.object(gate, 'raw', side_effect=[body(decision()), b'altered plan']):
            with self.assertRaisesRegex(ValueError, 'plan differs'):
                gate.approved_decision(self.repo, Q)

    def test_approval_sha_and_reply_sha_are_independent_checks(self):
        raw_approval = body(approval())
        self.assertEqual(gate.verify_approval(raw_approval, gate.digest(raw_approval), decision(), Q), approval())
        with self.assertRaisesRegex(ValueError, 'approval digest mismatch'):
            gate.verify_approval(raw_approval, 'e' * 64, decision(), Q)
        with self.assertRaisesRegex(ValueError, 'reply identities differ'):
            gate.verify_approval(raw_approval, gate.digest(raw_approval), dict(decision(), replySha256='e' * 64), Q)

    def test_complete_synthetic_launcher_origin_cannot_qualify(self):
        from test_launch_known_repeats import LaunchControls
        from launch_known_repeats import LAUNCHED

        LaunchControls.setUpClass()
        control = LaunchControls('test_two_exact_known_repeats_finish_without_qualifying')
        control.setUp()
        self.addCleanup(control.doCleanups)
        receipt = control.run_with()
        self.assertEqual(receipt['status'], LAUNCHED, receipt.get('reason'))
        self.assertEqual(set(gate.inventory(control.root)), gate.EVIDENCE_FILES)
        described = gate.decode(control.approval)
        expected_decision = {name: described[name] for name in gate.APPROVAL_FIELDS}
        with patch.object(gate, 'approved_decision', return_value=expected_decision):
            with self.assertRaisesRegex(ValueError, 'actual approved Mac launch'):
                gate.audit_evidence(self.repo, described['implementationCommit'], control.root,
                                    control.approval_sha, self.repo)

    def test_draft_freeze_reuses_accepted_backend_and_exact_public_pointer(self):
        with patch.object(gate, 'approved_decision', return_value=decision()), \
             patch.object(gate, 'verify_acceptance', return_value=self.acceptance) as accepted, \
             patch.object(gate, 'construction_sources', return_value=self.sources):
            result = gate.draft_freeze(self.repo, Q, A, 'd' * 64, self.freeze['frozenAt'])
            self.assertEqual(result, self.freeze)
            accepted.assert_called_once_with(self.repo, Q, A, 'd' * 64, self.repo.parent)

    def test_published_evidence_cannot_omit_records_or_rebind_bytes(self):
        corpus = {name: body({'offlineFixture': name}) for name in gate.EVIDENCE_FILES}
        manifest = {name: {'sha256': gate.digest(value), 'sizeBytes': len(value)} for name, value in corpus.items()}
        tracked = dict.fromkeys(corpus, ('100644', 'blob'))
        stage = self.repo / 'evidence'
        stage.mkdir()
        with patch.object(gate, 'tracked_files', return_value=tracked), \
             patch.object(gate, 'raw', side_effect=lambda _r, _c, name: corpus[name.removeprefix(gate.EVIDENCE)]):
            gate.materialize_evidence(self.repo, A, manifest, stage)
            self.assertEqual(gate.inventory(stage), manifest)
            with self.assertRaisesRegex(ValueError, 'complete evidence reference'):
                gate.materialize_evidence(self.repo, A, {n: m for n, m in manifest.items() if n != 'repeat-2/receipt.json'}, stage)
            corpus['repeat-2/receipt.json'] = b'coherently named but replaced terminal'
            with self.assertRaisesRegex(ValueError, 'published evidence differs'):
                gate.materialize_evidence(self.repo, A, manifest, stage)
            tracked['repeat-2/receipt.json'] = ('120000', 'blob')
            with self.assertRaisesRegex(ValueError, 'regular evidence file population'):
                gate.materialize_evidence(self.repo, A, manifest, stage)

    def test_acceptance_waits_for_parent_terminal_after_last_child(self):
        child_finish = '2026-11-18T09:00:00Z'
        parent_finish = '2026-11-18T09:00:02Z'
        terminal = {'finishedAt': parent_finish, 'repeats': [{'finishedAt': child_finish}]}
        proof = {'lastFinishedAt': gate.parent_closed_at(terminal), 'buildFreezeCommit': B,
                 'qualifiedBackend': backend(), 'evidence': {}}
        self.assertEqual(proof['lastFinishedAt'], parent_finish)
        with self.assertRaisesRegex(ValueError, 'parent closure predates'):
            gate.parent_closed_at(dict(terminal, finishedAt='2026-11-18T08:59:59Z'))
        value = {'schema': gate.ACCEPTANCE_SCHEMA, 'status': gate.QUALIFIED,
                 'implementationCommit': Q, 'approvalSha256': 'd' * 64,
                 'acceptedAt': '2026-11-18T09:00:01Z', 'buildFreezeCommit': B,
                 'qualifiedBackend': backend(), 'evidence': {}}
        with patch.object(gate, 'ancestor', return_value=True), \
             patch.object(gate, 'materialize_evidence'), \
             patch.object(gate, 'audit_evidence', return_value=proof), \
             patch.object(gate, 'raw', side_effect=lambda *_: body(value)):
            with self.assertRaisesRegex(ValueError, 'acceptance predates its completed evidence'):
                gate.verify_acceptance(self.repo, Q, A, gate.digest(body(value)), self.repo)
            value['acceptedAt'] = parent_finish
            self.assertEqual(gate.verify_acceptance(self.repo, Q, A, gate.digest(body(value)), self.repo), value)

    def test_freeze_cannot_be_same_commit_as_qualified_acceptance(self):
        self.link['constructionFreezePublicationCommit'] = A
        self.bound_freeze(expected_error='separate publication after')

    def test_freeze_cannot_precede_the_repeats(self):
        self.bound_freeze(lambda freeze: freeze.update(frozenAt='2026-11-18T08:00:00Z'),
                          expected_error='accepted backend or chronology')

    def test_qualified_backend_and_source_closure_cannot_change(self):
        self.bound_freeze(lambda freeze: freeze['qualifiedBackend'].update(realGodotSha256='f' * 64),
                          expected_error='accepted backend or chronology')
        self.bound_freeze(lambda freeze: freeze['sources'].clear(), expected_error='construction source closure')

    def test_measurement_rechecks_actual_backend_for_successor_freeze(self):
        accepted = dict(self.freeze)
        actual = dict(backend(), realGodotSha256='f' * 64)
        with patch.object(historical, 'load_construction_freeze', return_value=accepted), \
             patch.object(historical, 'current_backend_before_measurement', return_value=actual):
            with self.assertRaisesRegex(ValueError, 'actual backend before measurement differs'):
                historical.load_measurement_construction_freeze(
                    self.repo, Q, self.repo, backend()['modelSha256'], object(), {})


if __name__ == '__main__':
    unittest.main()
