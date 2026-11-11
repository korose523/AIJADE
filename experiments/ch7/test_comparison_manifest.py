#!/usr/bin/env python3
"""Instrument controls on existing data and explicit synthetic corruptions, never new study cases."""
import copy
import io
import json
from pathlib import Path
import random
import unittest

from comparison_manifest import score, validate_manifest
from prepare_manifest_instrument import check_original_parity, derive


class ComparisonManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(__file__).resolve().parents[2]
        cls.baseline = derive(cls.repo)

    def setUp(self):
        self.rows, self.manifest, self.aliases, self.original, self.rules = copy.deepcopy(self.baseline)

    def row(self, legacy, condition='C2'):
        return next(r for r in self.rows if r['caseId'] == self.aliases[legacy] and r['condition'] == condition)

    def test_all_original_raw_record_and_arm_scores_match_frozen_scorer(self):
        result = score(self.rows, self.manifest)
        self.assertEqual('PASS', check_original_parity(result, self.original, self.rules, self.aliases)['status'])

    def test_alias_and_all_row_rule_reorders_preserve_keyed_outputs(self):
        expected = score(self.rows, self.manifest)
        remap = {r['caseId']: 'independent_' + str(i) for i, r in enumerate(self.manifest['cases'])}
        for rule in self.manifest['cases']:
            rule['caseId'] = remap[rule['caseId']]
        for row in self.rows:
            row['caseId'] = remap[row['caseId']]
        rng = random.Random(1733)
        rng.shuffle(self.rows)
        rng.shuffle(self.manifest['cases'])
        actual = score(self.rows, self.manifest)
        reverse = {v: k for k, v in remap.items()}
        for condition in ('C1', 'C2'):
            for key in ('arms', 'rowIntegrityDiagnostics'):
                values = actual[key][condition]['byCase'] if key == 'arms' else actual[key][condition]
                for item in values:
                    item['caseId'] = reverse[item['caseId']]
                values.sort(key=lambda i: i['caseId'])
                old = expected[key][condition]['byCase'] if key == 'arms' else expected[key][condition]
                old.sort(key=lambda i: i['caseId'])
        self.assertEqual(expected, actual)

    def test_does_not_depend_on_expected_or_qualification_flags(self):
        expected = score(self.rows, self.manifest)
        for row in self.rows:
            row['expected'] = {'invented': 'not an outcome oracle'}
            row['engineeringExpectationMatched'] = False
            row['semanticMismatchConstructed'] = False
        self.assertEqual(expected, score(self.rows, self.manifest))

    def test_adverse_c2_control_is_scored_instead_of_rejected(self):
        old = copy.deepcopy(self.row('I1', 'C1'))
        old['condition'] = 'C2'
        index = self.rows.index(self.row('I1'))
        self.rows[index] = old
        result = score(self.rows, self.manifest)
        self.assertEqual(1, result['arms']['C2']['invalidDurablePromotions'])
        self.assertEqual(1, result['arms']['C2']['integrityInvalidReuse'])

    def test_reversed_comparison_control_is_scored(self):
        for row in self.rows:
            row['condition'] = 'C1' if row['condition'] == 'C2' else 'C2'
        result = score(self.rows, self.manifest)
        self.assertEqual({'invalidDurablePromotions': 3, 'integrityInvalidReuse': 2}, result['differencesC2MinusC1'])

    def test_first_legal_duplicate_action_is_not_an_error(self):
        result = score(self.rows, self.manifest)
        for condition in ('C1', 'C2'):
            item = next(i for i in result['arms'][condition]['byCase'] if i['caseId'] == self.aliases['I3'])
            self.assertEqual((1, 1, 0, 0), (item['persistedSpecs'], item['round2SandboxExecutions'], item['invalidDurablePromotions'], item['integrityInvalidReuse']))

    def test_pre_revocation_promotion_is_lawful_but_reuse_window_remains(self):
        result = score(self.rows, self.manifest)
        for condition in ('C1', 'C2'):
            item = next(i for i in result['arms'][condition]['byCase'] if i['caseId'] == self.aliases['I7'])
            self.assertEqual((1, 0, 1, 0), (item['persistedSpecs'], item['scheduledInvalidPromotionOpportunities'], item['scheduledInvalidReuseOpportunities'], item['integrityInvalidReuse']))

    def test_transient_ok_before_rollback_is_not_a_durable_promotion(self):
        result = score(self.rows, self.manifest)
        item = next(i for i in result['arms']['C2']['byCase'] if i['caseId'] == self.aliases['I8'])
        self.assertEqual((1, 0, 0), (item['successfulServiceReturns'], item['persistedSpecs'], item['invalidDurablePromotions']))

    def test_denominators_do_not_shrink_when_memory_is_absent(self):
        result = score(self.rows, self.manifest)
        for condition in ('C1', 'C2'):
            self.assertEqual(7, result['arms'][condition]['scheduledInvalidPromotionOpportunities'])
            self.assertEqual(8, result['arms'][condition]['scheduledInvalidReuseOpportunities'])
            self.assertLess(result['arms'][condition]['retrievedAtInvalidReuseWindow'], 8)

    def test_partial_spec_and_report_rows_are_preserved_as_secondary_diagnostics(self):
        row = self.row('H')
        row['final']['reports'] = 0
        row['final']['reportRows'] = []
        result = score(self.rows, self.manifest)
        item = next(i for i in result['rowIntegrityDiagnostics']['C2'] if i['caseId'] == self.aliases['H'])
        self.assertEqual((True, 1, 0), (item['specReportCountMismatch'], item['orphanSpecRows'], item['orphanReportRows']))
        self.assertEqual({'refused_or_incomplete': 1}, result['arms']['C2']['normalOutcomeCounts'])
        row['final']['reports'] = 1
        row['final']['reportRows'] = [{'id': 'report_orphan', 'result': {'evolutionSpecId': 'missing_spec'}}]
        row['final']['specs'] = 0
        row['final']['specRows'] = []
        item = next(i for i in score(self.rows, self.manifest)['rowIntegrityDiagnostics']['C2'] if i['caseId'] == self.aliases['H'])
        self.assertEqual((True, 0, 1), (item['specReportCountMismatch'], item['orphanSpecRows'], item['orphanReportRows']))

    def test_equal_counts_do_not_hide_orphan_linked_rows(self):
        row = self.row('H')
        row['final']['reportRows'][0]['result']['evolutionSpecId'] = 'foreign_spec'
        result = score(self.rows, self.manifest)
        diagnostic = next(i for i in result['rowIntegrityDiagnostics']['C2'] if i['caseId'] == self.aliases['H'])
        self.assertEqual((False, 1, 1), (diagnostic['specReportCountMismatch'], diagnostic['orphanSpecRows'], diagnostic['orphanReportRows']))
        self.assertEqual({'refused_or_incomplete': 1}, result['arms']['C2']['normalOutcomeCounts'])

    def test_unknown_normal_state_is_reported_instead_of_treated_as_safe_acceptance(self):
        self.row('H')['final']['authority'][0]['state'] = 'unknown'
        result = score(self.rows, self.manifest)
        self.assertEqual({'unknown': 1}, result['arms']['C2']['normalOutcomeCounts'])

    def test_renamed_and_repeated_existing_record_checks_are_not_new_data(self):
        rule = next(r for r in self.manifest['cases'] if r['caseId'] == self.aliases['H'])
        repeated = copy.deepcopy(rule)
        repeated['caseId'] = 'extra_existing_control'
        self.manifest['cases'].append(repeated)
        for condition in ('C1', 'C2'):
            row = copy.deepcopy(self.row('H', condition))
            row['caseId'] = repeated['caseId']
            self.rows.append(row)
        self.manifest['casePairs'] = 11
        self.manifest['conditionRows'] = 22
        result = score(self.rows, self.manifest)
        self.assertEqual((11, 22, 0), (result['developmentPairs'], result['conditionRows'], result['heldOutCases']))
        self.assertEqual({'accepted': 2}, result['arms']['C2']['normalOutcomeCounts'])

    def test_semantic_round2_remains_unmeasured(self):
        self.assertEqual('NOT_MEASURED', score(self.rows, self.manifest)['round2SemanticActCorrectness'])
        self.manifest['round2SemanticActCorrectness'] = 'correct'
        with self.assertRaises(ValueError):
            score(self.rows, self.manifest)

    def test_missing_duplicate_incomplete_and_non200_observations_are_not_zero(self):
        for field, value in [('duplicateReuse', None), ('round2', None)]:
            with self.subTest(field=field):
                rows = copy.deepcopy(self.rows)
                next(r for r in rows if r['caseId'] == self.aliases['I3'] and r['condition'] == 'C2')[field] = value
                with self.assertRaises(ValueError):
                    score(rows, self.manifest)
        self.row('I3')['round2']['status'] = 503
        with self.assertRaises(ValueError):
            score(self.rows, self.manifest)

    def test_contract_mutations_are_refused(self):
        mutations = [
            lambda m: m.update(unrecognized=True),
            lambda m: m.update(purpose='heldout'),
            lambda m: m.update(casePairs=True),
            lambda m: m.update(conditionRows=18),
            lambda m: m.update(scheduledInvalidPromotionOpportunitiesPerCondition=6),
            lambda m: m.update(scheduledInvalidReuseOpportunitiesPerCondition=7),
            lambda m: m['conditions'][0].update(policy='weak-baseline'),
            lambda m: m.update(windowRegistrySha256='0' * 64),
            lambda m: m['cases'][0].update(caseId=m['cases'][1]['caseId']),
            lambda m: m['cases'][0].update(expectedC2='pass'),
            lambda m: m['cases'][0].update(allowedSpecs=99),
            lambda m: m['cases'][0].update(promotionOpportunity=True),
            lambda m: m['cases'][0].update(window='future_unregistered_window'),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(control=i):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                with self.assertRaises(ValueError):
                    score(self.rows, manifest)

    def test_raw_missing_duplicate_unknown_and_malformed_controls_are_refused(self):
        def normal(rows):
            return next(r for r in rows if r['caseId'] == self.aliases['H'] and r['condition'] == 'C2')
        def replace(field, value):
            def mutation(rows):
                rows[0][field] = value
            return mutation
        mutations = [
            lambda rows: rows.pop(),
            lambda rows: rows.__setitem__(0, copy.deepcopy(rows[1])),
            replace('caseId', 'unknown'), replace('condition', 'C3'),
            replace('caseId', None), replace('promotionAttempts', None),
            replace('final', None), replace('round2', {'executed': None, 'retrieved': True, 'status': 200}),
            lambda rows: rows[0]['final'].update(specs=True),
            lambda rows: rows[0]['final'].update(specs=-1),
            lambda rows: rows[0]['final'].update(specs=9),
            lambda rows: rows[0]['final'].update(reuseCount=9),
            lambda rows: rows[0]['round2'].update(executed=1),
            lambda rows: rows[0]['round2'].update(retrieved=None),
            lambda rows: rows[0]['round2'].pop('status'),
            lambda rows: normal(rows)['final']['authority'][0].update(state='unobserved'),
            lambda rows: normal(rows)['final']['reportRows'][0].update(result=None),
            lambda rows: normal(rows)['final']['reportRows'][0]['result'].update(evolutionSpecId=[]),
            lambda rows: normal(rows)['promotionAttempts'][0]['serviceResult'].update(ok=1),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(control=i):
                rows = copy.deepcopy(self.rows)
                mutate(rows)
                with self.assertRaises(ValueError):
                    score(rows, self.manifest)

    def test_scoring_is_pure_and_leaves_all_inputs_unchanged(self):
        before = copy.deepcopy((self.rows, self.manifest))
        score(self.rows, self.manifest)
        self.assertEqual(before, (self.rows, self.manifest))


def run():
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ComparisonManifestTests))
    report = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                  failures=len(result.failures), errors=len(result.errors), log=stream.getvalue(),
                  data='Existing archived development rows and explicitly synthetic instrument controls only.',
                  newEmpiricalObservations=0, newHeldOutCases=0)
    return report


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
