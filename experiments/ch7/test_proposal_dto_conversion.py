import copy
import unittest

from audit_paired_development import wire_proposal_of_dto


class DiagnosticProposalConversionTests(unittest.TestCase):
    def setUp(self):
        self.dto=dict(proposalId='p',sessionId='s',inputHash='hash',anchorKind=0,anchorVerified=True,
                      candidateParams={'emotion.preset':'comfort'},confidence=.9,renderRef='ctx:1',
                      appliedParamsHash='applied',assetVersionHash='asset',evidenceHash=None,claimText=None)
        self.wire={k:copy.deepcopy(v) for k,v in self.dto.items() if v is not None}
        self.wire['anchorKind']='shadow_params'

    def test_exact_conversion_keeps_every_value_and_does_not_mutate_input(self):
        before=copy.deepcopy(self.dto)
        result=wire_proposal_of_dto(self.dto)
        self.assertEqual(result,self.wire)
        result['candidateParams']['emotion.preset']='celebrate'
        self.assertEqual(self.dto,before)

    def test_evidence_enum_and_non_null_optional_fields_are_preserved(self):
        value=copy.deepcopy(self.dto)
        value.update(anchorKind=1,evidenceHash='evidence',claimText='claim')
        result=wire_proposal_of_dto(value)
        self.assertEqual(result['anchorKind'],'evidence')
        self.assertEqual(result['evidenceHash'],'evidence')
        self.assertEqual(result['claimText'],'claim')

    def test_unknown_enum_unknown_field_and_missing_field_fail_closed(self):
        for enum in [2,-1,True,'shadow_params']:
            with self.subTest(enum=enum),self.assertRaises(ValueError):wire_proposal_of_dto(dict(self.dto,anchorKind=enum))
        with self.assertRaises(ValueError):wire_proposal_of_dto(dict(self.dto,ignored='value'))
        value=copy.deepcopy(self.dto);del value['inputHash']
        with self.assertRaises(ValueError):wire_proposal_of_dto(value)

    def test_substantive_tampering_remains_a_full_object_mismatch(self):
        for field,value in [('inputHash','different'),('anchorKind',1),('anchorVerified',False),('confidence',.1),
                            ('candidateParams',{'emotion.preset':'celebrate'}),('claimText','unexpected claim')]:
            with self.subTest(field=field):
                changed=copy.deepcopy(self.dto);changed[field]=value
                self.assertNotEqual(wire_proposal_of_dto(changed),self.wire)


if __name__=='__main__':unittest.main()
