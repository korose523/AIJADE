#!/usr/bin/env python3
"""Pure scoring controls from old rows and synthetic changes, not fresh live observations."""
import copy
import io
import json
from pathlib import Path
import unittest

from build_known_live_manifest import construct
from prepare_manifest_instrument import derive
from score_live_manifest import score_rows


class LiveScoringTests(unittest.TestCase):
    def setUp(self):
        self.repo=Path(__file__).resolve().parents[2]
        self.runtime,_=construct(self.repo)
        self.rows,self.template,_,_,_=derive(self.repo)

    def test_only_numerical_calculator_fields_are_propagated(self):
        result=score_rows(self.rows,self.runtime,self.template)
        self.assertEqual({'arms','differencesC2MinusC1','rowIntegrityDiagnostics','normalAcceptanceDefinition','round2SemanticActCorrectness'},set(result))
        self.assertEqual({'invalidDurablePromotions':-3,'integrityInvalidReuse':-2},result['differencesC2MinusC1'])

    def test_adverse_and_reversed_results_are_not_censored(self):
        rule=next(r for r in self.template['cases'] if r['window']=='execution_receipt_intent')
        source=copy.deepcopy(next(r for r in self.rows if (r['caseId'],r['condition'])==(rule['caseId'],'C1')))
        source['condition']='C2'
        index=next(i for i,r in enumerate(self.rows) if (r['caseId'],r['condition'])==(rule['caseId'],'C2'))
        self.rows[index]=source
        self.assertEqual(1,score_rows(self.rows,self.runtime,self.template)['arms']['C2']['invalidDurablePromotions'])
        for row in self.rows: row['condition']='C2' if row['condition']=='C1' else 'C1'
        self.assertGreater(score_rows(self.rows,self.runtime,self.template)['differencesC2MinusC1']['invalidDurablePromotions'],0)

    def test_non_ten_case_window_projection_is_supported_without_new_data_claim(self):
        case=self.runtime['cases'][0]
        self.runtime['cases']=[case]
        self.template['cases']=[r for r in self.template['cases'] if r['caseId']==case['caseId']]
        self.template.update(casePairs=1,conditionRows=2,
                             scheduledInvalidPromotionOpportunitiesPerCondition=self.template['cases'][0]['promotionOpportunity'],
                             scheduledInvalidReuseOpportunitiesPerCondition=self.template['cases'][0]['reuseOpportunity'])
        self.rows=[r for r in self.rows if r['caseId']==case['caseId']]
        self.assertEqual(1,len(score_rows(self.rows,self.runtime,self.template)['arms']['C1']['byCase']))

    def test_scope_missing_arms_and_unbound_windows_are_refused(self):
        with self.assertRaises(ValueError): score_rows(self.rows[:-1],self.runtime,self.template)
        changed=copy.deepcopy(self.runtime); changed['purpose']='heldout'
        with self.assertRaises(ValueError): score_rows(self.rows,changed,self.template)
        changed=copy.deepcopy(self.runtime); changed['cases'][0]['caseId']='unbound'
        with self.assertRaises(ValueError): score_rows(self.rows,changed,self.template)

    def test_expected_flags_are_not_used_and_inputs_are_not_mutated(self):
        expected=score_rows(self.rows,self.runtime,self.template)
        for row in self.rows:
            row['expected']={'invented':'not evidence'}; row['engineeringExpectationMatched']=False
        before=copy.deepcopy((self.rows,self.runtime,self.template))
        self.assertEqual(expected,score_rows(self.rows,self.runtime,self.template))
        self.assertEqual(before,(self.rows,self.runtime,self.template))


def run():
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LiveScoringTests))
    return dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                log=stream.getvalue(),scope='Existing-row/synthetic instrument controls; no actual new measurement.',newHeldOutCases=0)


if __name__=='__main__':
    result=run(); print(json.dumps(result,indent=2)); raise SystemExit(0 if result['status']=='PASS' else 1)
