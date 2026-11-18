#!/usr/bin/env python3
"""Synthetic controls for known-condition byte equivalence."""

import unittest

from finite_construction_binding import decode
from finite_inputs import encoded
from preflight_known_repeat_readback import match_known_material, sha


ORIGINAL = 'a' * 40
REBOUND = 'b' * 40


def synthetic(revision, *, changed_operation=False, changed_score=False, changed_programme=False):
    selection = encoded({'fixture': 'SYNTHETIC', 'programmes': [1, 3 if changed_programme else 2]})
    runtime = encoded({
        'constructionFreezeCommit': revision,
        'selectionSha256': sha(selection),
        'cases': [
            {'input': {'caseId': f'synthetic-{index}', 'conditions': ['C1', 'C2'],
                       'operations': {'use': changed_operation if index == 0 else False}}}
            for index in range(10)
        ],
    })
    scoring = encoded({
        'constructionFreezeCommit': revision,
        'selectionSha256': sha(selection),
        'runtimeManifestSha256': sha(runtime),
        'scoreRules': [2 if changed_score else 1],
    })
    return {'selection.json': selection, 'runtime-manifest.json': runtime, 'scoring-manifest.json': scoring}


class KnownMaterialPreflightTests(unittest.TestCase):
    def test_accepts_only_a_revision_rebind(self):
        order = match_known_material(synthetic(ORIGINAL), synthetic(REBOUND), REBOUND)
        self.assertEqual(order[:2], [('synthetic-0', 'C1'), ('synthetic-0', 'C2')])
        self.assertEqual(len(order), 20)

    def test_rejects_changed_input_operation_with_same_case_order_and_coherent_digests(self):
        with self.assertRaisesRegex(ValueError, 'content differs beyond revision binding'):
            match_known_material(synthetic(ORIGINAL), synthetic(REBOUND, changed_operation=True), REBOUND)

    def test_rejects_changed_score_when_runtime_bytes_match(self):
        with self.assertRaisesRegex(ValueError, 'content differs beyond revision binding: scoring-manifest.json'):
            match_known_material(synthetic(ORIGINAL), synthetic(REBOUND, changed_score=True), REBOUND)

    def test_rejects_changed_selected_programme_with_coherent_input_digests(self):
        with self.assertRaisesRegex(ValueError, 'content differs beyond revision binding'):
            match_known_material(synthetic(ORIGINAL), synthetic(REBOUND, changed_programme=True), REBOUND)

    def test_rejects_missing_input_even_if_other_bytes_match(self):
        material = synthetic(REBOUND)
        del material['scoring-manifest.json']
        with self.assertRaisesRegex(ValueError, 'wrong known input inventory'):
            match_known_material(synthetic(ORIGINAL), material, REBOUND)

    def test_rejects_old_scoring_binding_under_new_revision(self):
        material = synthetic(REBOUND)
        old = decode(synthetic(ORIGINAL)['scoring-manifest.json'])
        old['constructionFreezeCommit'] = REBOUND
        material['scoring-manifest.json'] = encoded(old)
        with self.assertRaisesRegex(ValueError, 'content differs beyond revision binding: scoring-manifest.json'):
            match_known_material(synthetic(ORIGINAL), material, REBOUND)


if __name__ == '__main__':
    unittest.main()
