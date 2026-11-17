"""Warm journal caches must never cache a process/native/API/RSS verdict.

All evidence comes from the existing offline v3 fixture and real parsers. No
observer, native executable, listener query, model or network call is invoked.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'experiments/ch7'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import finite_runtime
import mac_process_guard_v3 as guard
import process_lifecycle as life
from test_mac_lifecycle_guard import fixture


class WarmCursorRawEvidenceControls(unittest.TestCase):
    def decision(self, policy, observation, journal, cursor=None):
        return guard.validate_observation(policy, observation,
                                          lifecycle_journal=journal,
                                          lifecycle_cursor=cursor)

    def warm(self):
        policy, observation, journal = fixture()
        cold = self.decision(policy, observation, journal)
        self.assertEqual(cold['status'], 'PASS', cold)
        cursor = life.ViewCursor()
        warm = self.decision(policy, observation, journal, cursor)
        self.assertEqual(warm, cold)
        self.assertEqual(cursor.statistics()['parsedEvents'], len(journal.splitlines()))
        self.assertFalse(cursor.poisoned)
        return policy, observation, journal, cursor

    def assert_unchanged_prefix_rechecked(self, policy, original, changed, journal, cursor,
                                        expected_code, expected_status=None):
        before = cursor.statistics()
        self.assertEqual(changed['lifecycle']['journalBytes'], len(journal))
        self.assertEqual(changed['lifecycle']['journalSha256'], hashlib.sha256(journal).hexdigest())
        self.assertEqual(changed['lifecycle'], original['lifecycle'])
        reference = self.decision(policy, changed, journal)
        observed = self.decision(policy, changed, journal, cursor)
        self.assertNotEqual(reference['status'], 'PASS', reference)
        self.assertEqual(observed, reference)
        if expected_status is not None:
            self.assertEqual(observed['status'], expected_status, observed)
        self.assertIn(expected_code, [item['code'] for item in observed['blockers']])
        after = cursor.statistics()
        self.assertEqual(after['calls'], before['calls'] + 1)
        self.assertEqual(after['parsedEvents'], before['parsedEvents'])
        self.assertEqual(after['hashUpdatedBytes'], before['hashUpdatedBytes'])
        self.assertEqual(after['latestPrefixBytes'], len(journal))
        self.assertFalse(cursor.poisoned, 'non-journal evidence must not corrupt the journal cache')
        self.assertEqual(self.decision(policy, original, journal, cursor)['status'], 'PASS')
        return observed

    def test_warm_exact_journal_baseline_reuses_parse_but_revalidates_sample(self):
        policy, original, journal, cursor = self.warm()
        before = cursor.statistics()
        again = self.decision(policy, copy.deepcopy(original), journal, cursor)
        self.assertEqual(again['status'], 'PASS', again)
        after = cursor.statistics()
        self.assertEqual(after['calls'], before['calls'] + 1)
        self.assertEqual(after['parsedEvents'], before['parsedEvents'])
        self.assertEqual(after['hashUpdatedBytes'], before['hashUpdatedBytes'])
        self.assertGreater(after['fullPrefixReadBytes'], before['fullPrefixReadBytes'])
        self.assertGreater(after['fullPrefixComparedBytes'], before['fullPrefixComparedBytes'])

    def test_warm_cursor_rejects_nonempty_actual_api_body_with_rebound_hash(self):
        policy, original, journal, cursor = self.warm()
        changed = copy.deepcopy(original)
        body = b'{"models":[{"name":"controlled-loaded-model"}]}'
        changed['evidence']['api'].update(
            emptyBodyBase64=base64.b64encode(body).decode(),
            bodySha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        self.assert_unchanged_prefix_rechecked(policy, original, changed, journal, cursor,
                                               'API_EMPTY_EVIDENCE_INVALID', 'FAIL')

    def test_warm_cursor_reparses_actual_native_stdout_with_rebound_hash(self):
        policy, original, journal, cursor = self.warm()
        changed = copy.deepcopy(original)
        evidence = changed['evidence']['before']['processGraph']['nativeCensus']
        payload = json.loads(base64.b64decode(evidence['stdoutBase64'], validate=True))
        target = next(row for row in payload['records'] if row['pid'] == 20)
        self.assertEqual(target['parentPid'], 1)
        target['parentPid'] = 0
        body = (json.dumps(payload, separators=(',', ':')) + '\n').encode()
        evidence.update(stdoutBase64=base64.b64encode(body).decode(),
                        stdoutSha256=hashlib.sha256(body).hexdigest(), stdoutBytes=len(body))
        self.assert_unchanged_prefix_rechecked(policy, original, changed, journal, cursor,
                                               'BULK_DERIVED_POPULATION_MISMATCH', 'FAIL')

    def test_warm_cursor_unknown_present_rss_stays_null_after_valid_journal(self):
        policy, original, journal, cursor = self.warm()
        changed = copy.deepcopy(original)
        owned = changed['evidence']['after']['ownedProcesses']
        target = next(row for row in owned if row['pid'] == 20)
        target['rssBytes'] = None
        changed['ownedProcesses'] = copy.deepcopy(owned)
        observed = self.assert_unchanged_prefix_rechecked(
            policy, original, changed, journal, cursor, 'OWNED_RSS_IDENTITY_UNKNOWN', 'UNKNOWN')
        self.assertIsNone(observed['ownedRssBytes'])

    def test_warm_cursor_rechecks_projection_even_when_prefix_is_identical(self):
        policy, original, journal, cursor = self.warm()
        changed = copy.deepcopy(original)
        self.assertGreater(len(changed['lifecycle']['leases']), 1)
        changed['lifecycle']['leases'].pop()
        before = cursor.statistics()
        reference = self.decision(policy, changed, journal)
        observed = self.decision(policy, changed, journal, cursor)
        self.assertNotEqual(reference['status'], 'PASS', reference)
        self.assertEqual(observed, reference)
        self.assertIn('OBSERVATION_SCHEMA_OR_POLICY_UNKNOWN',
                      [item['code'] for item in observed['blockers']])
        self.assertEqual(cursor.statistics()['parsedEvents'], before['parsedEvents'])
        self.assertEqual(cursor.statistics()['hashUpdatedBytes'], before['hashUpdatedBytes'])
        self.assertTrue(cursor.poisoned, 'a false view projection must not reuse a prior favorable view')

    def test_online_inner_and_outer_cursors_are_independent_instances(self):
        policy, observation, journal = fixture()
        policy['onlineReplayMode'] = 'incremental-exact-prefix-v1'
        observation['policyCanonicalSha256'] = guard.canonical_sha256(policy)
        inner_args, outer_args = finite_runtime.online_lifecycle_cursors(policy)
        self.assertEqual(set(inner_args), {'lifecycle_cursor'})
        self.assertEqual(set(outer_args), {'lifecycle_cursor'})
        inner, outer = inner_args['lifecycle_cursor'], outer_args['lifecycle_cursor']
        self.assertIsNot(inner, outer)
        self.assertEqual(self.decision(policy, observation, journal, inner)['status'], 'PASS')
        self.assertEqual(outer.statistics()['calls'], 0)
        self.assertEqual(self.decision(policy, observation, journal, outer)['status'], 'PASS')
        altered = copy.deepcopy(observation)
        altered['lifecycle']['leases'].pop()
        self.assertNotEqual(self.decision(policy, altered, journal, inner)['status'], 'PASS')
        self.assertTrue(inner.poisoned)
        self.assertFalse(outer.poisoned)
        self.assertEqual(self.decision(policy, observation, journal, outer)['status'], 'PASS')

    def test_none_mode_retains_cold_path_for_baseline_and_changed_evidence(self):
        policy, observation, journal = fixture()
        self.assertEqual(finite_runtime.online_lifecycle_cursors(policy), ({}, {}))
        self.assertEqual(finite_runtime.online_lifecycle_cursors(None), ({}, {}))
        implicit = guard.validate_observation(policy, observation, lifecycle_journal=journal)
        explicit = self.decision(policy, observation, journal, None)
        self.assertEqual(implicit['status'], 'PASS', implicit)
        self.assertEqual(implicit, explicit)
        changed = copy.deepcopy(observation)
        changed['evidence']['api']['modelCount'] = True
        implicit_bad = guard.validate_observation(policy, changed, lifecycle_journal=journal)
        explicit_bad = self.decision(policy, changed, journal, None)
        self.assertNotEqual(implicit_bad['status'], 'PASS', implicit_bad)
        self.assertEqual(implicit_bad, explicit_bad)


if __name__ == '__main__':
    unittest.main()
