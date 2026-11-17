"""Synthetic source-level controls; no OS observer, model or live workload."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'experiments/ch7'))
import lifecycle_audit as oracle
from nested_event_index import EventIndex, typed_equal

Q='a'*40;P='b'*64
ROOT=dict(pid=100,createTimeMicros=100000000,parentPid=5)
CHILD=dict(pid=200,createTimeMicros=200000000,parentPid=100)
ROOT_LEASE='0'*32; CHILD_LEASE='1'*32; SCOPE='2'*32


def fixture():
    def e(kind,at,data):
        return dict(schema=oracle.LIFECYCLE_SCHEMA,event=kind,monotonicSeconds=at,
            runId='c'*32,writer=copy.deepcopy(ROOT),sourceCommit=Q,policySha256=P,data=data)
    return [
        e('CONTROLLER_REGISTER',10,dict(leaseId=ROOT_LEASE,role='controller',stageId='sequence',
            identity=copy.deepcopy(ROOT),parentIdentity=None,commandSha256='d'*64,
            executableSha256='e'*64,readyMonotonic=9.9)),
        e('SCOPE_OPEN',11,dict(scopeId=SCOPE,controllerIdentity=copy.deepcopy(ROOT),parentLeaseId=None,stageId='sequence')),
        e('FINITE_REGISTER',12,dict(leaseId=CHILD_LEASE,role='finite',stageId='task',
            identity=copy.deepcopy(CHILD),parentIdentity=copy.deepcopy(ROOT),commandSha256='f'*64,
            executableSha256='e'*64,shimSha256='d'*64,readyMonotonic=11.9,
            identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD')),
        e('RELEASE',12.1,dict(leaseId=CHILD_LEASE)),
        e('WAIT',14,dict(leaseId=CHILD_LEASE,identity=copy.deepcopy(CHILD),exitCode=0,waitSource='Popen.wait',reapedMonotonic=13.9)),
        e('ABSENCE',16,dict(identity=copy.deepcopy(CHILD),sampleId='5'*32,phase='after',nativeStdoutSha256='7'*64,graphStartedMonotonic=15.2)),
        e('SCOPE_CLOSE',17,dict(scopeId=SCOPE)),
    ]


def seal(events):
    previous='0'*64; lines=[]
    for seq,original in enumerate(events,1):
        row=copy.deepcopy(original);row.pop('sha256',None)
        row.update(seq=seq,previousSha256=previous)
        row['sha256']=hashlib.sha256(oracle.canonical(row)).hexdigest()
        lines.append(oracle.canonical(row)+b'\n');previous=row['sha256']
    return b''.join(lines)


class EventIndexControls(unittest.TestCase):
    def setUp(self):
        self.events=fixture();self.raw=seal(self.events)
        self.index=EventIndex(self.raw,oracle._replay,Q,P)

    def test_01_every_original_cutoff_matches_preserved_cold_oracle_exactly(self):
        for count in range(1,len(self.events)+1):
            prefix=self.raw[:self.index.offsets[count]]
            actual=self.index.prefix(len(prefix),hashlib.sha256(prefix).hexdigest(),count)[1]
            self.assertTrue(typed_equal(actual,oracle._replay(prefix,Q,P)))

    def test_02_future_wait_and_native_absence_do_not_repair_earlier_prefix(self):
        before=self.index.state(4)['leases'][CHILD_LEASE]
        self.assertIsNone(before['waitSeq']);self.assertIsNone(before['exitCode']);self.assertIsNone(before['absence'])
        waited=self.index.state(5)['leases'][CHILD_LEASE]
        self.assertEqual(waited['absenceWitnessKind'],'PARENT_WAIT_REAPED')
        native=self.index.state(6)['leases'][CHILD_LEASE]
        self.assertEqual(native['absenceWitnessKind'],'COMPLETE_NATIVE_ABSENCE')

    def test_03_boolean_sequence_is_not_integer_one(self):
        prefix=self.raw[:self.index.offsets[1]]
        with self.assertRaisesRegex(ValueError,'cutoff/hash types'):
            self.index.prefix(len(prefix),hashlib.sha256(prefix).hexdigest(),True)

    def test_04_nonboundary_prefix_and_wrong_hash_refuse(self):
        count=self.index.offsets[3]
        with self.assertRaisesRegex(ValueError,'boundary'):
            self.index.prefix(count+1,hashlib.sha256(self.raw[:count+1]).hexdigest(),3)
        with self.assertRaisesRegex(ValueError,'hash differs'):
            self.index.prefix(count,'f'*64,3)

    def test_05_coherently_rehashed_wrong_parent_wait_refuses_old_oracle(self):
        mutated=copy.deepcopy(self.events);mutated[4]['data']['identity']['createTimeMicros']+=1
        changed=seal(mutated);self.assertNotEqual(changed,self.raw)
        with self.assertRaisesRegex(ValueError,'unbound finite terminal wait'):
            EventIndex(changed,oracle._replay,Q,P)

    def test_06_coherently_rehashed_unreleased_wait_refuses(self):
        mutated=copy.deepcopy(self.events);del mutated[3]
        changed=seal(mutated);self.assertNotEqual(changed,self.raw)
        with self.assertRaisesRegex(ValueError,'unbound finite terminal wait'):
            EventIndex(changed,oracle._replay,Q,P)

    def test_07_mutating_returned_lease_snapshot_cannot_poison_versions(self):
        before=self.index.state(4);before['leases'][CHILD_LEASE]['identity']['pid']=999
        self.assertEqual(self.index.state(4)['leases'][CHILD_LEASE]['identity']['pid'],CHILD['pid'])
        self.assertTrue(typed_equal(self.index.state(7),oracle._replay(self.raw,Q,P)))

    def test_08_coherent_source_substitution_is_not_an_index_acceptance(self):
        mutated=copy.deepcopy(self.events)
        for row in mutated:row['sourceCommit']='9'*40
        changed=seal(mutated);self.assertNotEqual(changed,self.raw)
        with self.assertRaisesRegex(ValueError,'frozen source'):
            EventIndex(changed,oracle._replay,Q,P)

    def test_09_scope_close_is_not_projected_back_to_live_scope(self):
        self.assertIsNone(self.index.state(6)['scopes'][SCOPE]['closeSeq'])
        self.assertEqual(self.index.state(7)['scopes'][SCOPE]['closeSeq'],7)


if __name__=='__main__':
    unittest.main()
