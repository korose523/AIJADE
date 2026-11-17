"""Structured adverse launch evidence, never an actual spawn or observation."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'experiments/ch7'))
import lifecycle_audit as audit
from test_lifecycle_audit_journal import Fixture,Q,P,POLICY,ROOT


def refusal_fixture(spawned=True):
    f=Fixture()
    data=dict(attemptId='f'*32,stageId='observer-native-census',commandSha256='d'*64,
        executableSha256='e'*64,spawnedPid=999 if spawned else None,readyBytes=0,
        readySha256=hashlib.sha256(b'').hexdigest(),ownsProcessGroup=False,
        identityReads=[],identityStatus='UNKNOWN',registeredLeaseId=None,errorClass='TimeoutError',
        actualExitCode=0 if spawned else None,cleanupKnown=True,waitSource='Popen.wait' if spawned else None,
        startedMonotonic=16.1,cleanupCompletedMonotonic=16.4)
    event=copy.deepcopy(f.events[-1]);event.update(event='LAUNCH_REFUSED',monotonicSeconds=16.5,data=data)
    f.events.insert(-1,event);f.seal()
    return f,event


class RefusedLaunchAuditControls(unittest.TestCase):
    def parse(self,f):return audit._replay(f.raw,Q,P)
    def verify(self,f):return audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=POLICY,controller=ROOT)

    def test_01_known_wait_zero_cleans_unknown_birth_but_never_qualifies_it(self):
        f,event=refusal_fixture()
        state=self.parse(f)
        self.assertEqual(len(state['launchRefusals']),1)
        self.assertEqual(state['launchRefusals'][0]['actualExitCode'],0)
        self.assertEqual(state['launchRefusals'][0]['identityStatus'],'UNKNOWN')
        self.assertNotIn(event['data']['attemptId'],state['leases'])
        self.assertEqual(len(state['leases']),2)
        with self.assertRaisesRegex(ValueError,'LAUNCH_REFUSED evidence verified; qualification remains adverse'):
            self.verify(f)

    def test_02_refusal_before_popen_has_no_invented_pid_or_terminal_wait(self):
        f,event=refusal_fixture(False)
        self.assertIsNone(self.parse(f)['launchRefusals'][0]['spawnedPid'])
        with self.assertRaisesRegex(ValueError,'qualification remains adverse'):self.verify(f)

    def test_03_coherent_bound_label_cannot_hide_two_different_kernel_births(self):
        f,event=refusal_fixture()
        event['data'].update(identityStatus='BOUND',identityReads=[dict(pid=999,createTimeMicros=999000000,parentPid=100),
            dict(pid=999,createTimeMicros=999000001,parentPid=100)])
        f.seal()
        with self.assertRaisesRegex(ValueError,'identity status overstates'):self.parse(f)

    def test_04_kernel_reads_cannot_refer_to_a_different_actual_popen_pid(self):
        f,event=refusal_fixture()
        event['data']['identityReads']=[dict(pid=998,createTimeMicros=999000000,parentPid=100)]
        f.seal()
        with self.assertRaisesRegex(ValueError,'not bound to actual child'):self.parse(f)

    def test_05_cleanup_unknown_cannot_claim_actual_wait_zero(self):
        f,event=refusal_fixture();event['data']['cleanupKnown']=False;f.seal()
        with self.assertRaisesRegex(ValueError,'actual wait/cleanup witness invalid'):self.parse(f)

    def test_06_empty_ready_payload_cannot_have_another_digest(self):
        f,event=refusal_fixture();event['data']['readySha256']='f'*64;f.seal()
        with self.assertRaisesRegex(ValueError,'empty refused ready-byte digest'):self.parse(f)

    def test_07_refused_cleanup_time_cannot_postdate_its_journal_event(self):
        f,event=refusal_fixture();event['data']['cleanupCompletedMonotonic']=16.6;f.seal()
        with self.assertRaisesRegex(ValueError,'cleanup chronology invalid'):self.parse(f)

    def test_08_unknown_birth_cannot_link_an_unrelated_registered_lease(self):
        f,event=refusal_fixture();event['data']['registeredLeaseId']='1'*32;f.seal()
        with self.assertRaisesRegex(ValueError,'not the exact bound attempt'):self.parse(f)

    def test_09_sidecar_marker_is_explicitly_adverse_without_journal_refusal(self):
        f=Fixture()
        f.rows[0]['processObservation']['lifecycle']['launchRefusalArtifacts']=[dict(
            path='/Volumes/Untitled/AIJADE/.runtime/posix/tmp/launch-refused-'+'f'*32+'.json',sha256='d'*64)]
        with self.assertRaisesRegex(ValueError,'fallback artifact is adverse'):self.verify(f)

    def test_10_torn_refusal_record_is_not_a_valid_favorable_prefix(self):
        f,event=refusal_fixture();f.raw=f.raw[:-7]
        with self.assertRaisesRegex(ValueError,'truncated'):self.verify(f)

    def test_11_successful_finite_lease_requires_parent_kernel_ready_witness_kind(self):
        f=Fixture();f.events[2]['data']['identityWitnessKind']='CHILD_SELF_REPORTED';f.seal()
        with self.assertRaisesRegex(ValueError,'parent-held-ready kernel witness'):self.parse(f)

    def test_12_parent_kernel_marker_does_not_waive_frozen_shim_source_sha(self):
        f=Fixture();f.events[2]['data']['shimSha256']='e'*64;f.seal()
        with self.assertRaisesRegex(ValueError,'shim differs from frozen'):self.verify(f)

    def test_13_full_native_guard_replay_is_adverse_after_known_refusal(self):
        from test_lifecycle_audit_raw import build_fixture,reproject
        import mac_process_guard_v3 as guard
        f,p=build_fixture()
        _,event=refusal_fixture()
        f.events.append(event)
        f.rows[1]['observationCompletedMonotonic']=16.6
        reproject(f)
        state=self.parse(f)
        self.assertEqual(len(state['launchRefusals']),1)
        decision=guard.validate_observation(p,f.rows[1]['processObservation'],lifecycle_journal=f.raw)
        self.assertEqual(decision['status'],'FAIL')
        self.assertIn('LAUNCH_REFUSED',[b['code'] for b in decision['blockers']])
        with self.assertRaisesRegex(ValueError,'qualification remains adverse'):
            audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=p,controller=ROOT)


if __name__=='__main__':unittest.main()
