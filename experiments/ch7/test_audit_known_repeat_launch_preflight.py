"""Verify refusal and passive status boundaries of the Chapter 7 launch preflight."""

from argparse import Namespace
import os
import unittest
from unittest.mock import patch

import audit_known_repeat_launch_preflight as audit


class ReadOnlyLaunchPreflight(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)
        self.args = Namespace(checkout='synthetic-checkout', qualification_plan='synthetic-plan',
                              approval=None, expected_approval_sha256=None, original_reply=None, config=None,
                              candidate_socket=None)
        self.source = dict(checkoutCommit='1'*40, protectedPhysicalMissing=[], programmePhysicalMissing=[])
        for name, value in (('local', None), ('check_sources', self.source), ('passive_database', {})):
            mocked = patch.object(audit, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        digest = patch.object(audit.launch, 'file_digest', return_value='2'*64)
        digest.start()
        self.addCleanup(digest.stop)

    def test_pending_private_inputs_do_not_validate_or_start_anything(self):
        with patch.object(audit.launch, 'live_configuration') as validator:
            state = audit.audit(self.args)
            validator.assert_not_called()
        self.assertEqual(state['status'], 'APPROVAL_BINDING_NOT_VERIFIED')
        self.assertFalse(state['approvalBindingVerified'])
        self.assertEqual(state['runtimeAvailability'], 'NOT_QUERIED')
        self.assertEqual((state['newQualificationRuns'], state['heldoutPairsCreated'], state['heldoutSeedsDerived']), (0, 0, 0))

    def test_partial_private_inputs_stop_before_binding(self):
        self.args.expected_approval_sha256 = '3'*64
        with patch.object(audit.launch, 'live_configuration') as validator:
            with self.assertRaisesRegex(ValueError, 'required together'):
                audit.audit(self.args)
            validator.assert_not_called()

    def test_sparse_future_checkout_stops_before_binding(self):
        self.args.approval = 'synthetic-private-approval'
        self.args.expected_approval_sha256 = '3'*64
        self.args.original_reply = 'synthetic-private-reply'
        self.args.config = 'synthetic-local-config'
        self.source['programmePhysicalMissing'] = ['synthetic-missing-programme']
        with patch.object(audit.launch, 'live_configuration') as validator:
            with self.assertRaisesRegex(ValueError, 'materialize all'):
                audit.audit(self.args)
            validator.assert_not_called()


class PassiveDatabaseMetadata(unittest.TestCase):
    def test_loopback_url_shape_recorded_without_contact_or_secret(self):
        for value, expected in (
            ('', 'NOT_PROVISIONED_IN_AUDIT_SHELL'),
            ('postgresql://127.0.0.1:15432/test', 'APPROVED_LOCAL_PORT_FORM'),
            ('postgresql://127.0.0.1:15433/test', 'WRONG_PORT'),
            ('postgresql://example.invalid:15432/test', 'INVALID_LOCAL_FORM'),
            ('postgresql://localhost:invalid/test', 'INVALID_LOCAL_FORM'),
        ):
            with self.subTest(expected=expected), patch.dict(os.environ, {'AIJADE_TEST_DATABASE_URL': value}):
                state = audit.passive_database(None, 15432)
                self.assertEqual(state, {'socket': 'NOT_NOMINATED', 'testDatabaseUrl': expected,
                                         'containerPortMapping': 'NOT_QUERIED'})


if __name__ == '__main__':
    unittest.main()
