"""Coherent interleaved scope prefixes; no actual capture or process launch."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'experiments/ch7'))
import lifecycle_audit as audit
import process_lifecycle as producer
from test_lifecycle_audit_journal import Fixture,Q,P,POLICY,ROOT,CHILD,L1,SCOPE,rss,fake_sample

NESTED='3'*32


def project(f,row,count,scope,controller):
    raw=b''.join(f.raw.splitlines(keepends=True)[:count]);state=producer.replay_journal(raw)
    obs=row['processObservation'];refs=sorted({audit.node_identity(n) for frame in obs['syntheticFrames'] for n in frame['nodes']})
    leases=[v for v in state['leases'].values() if v['absence'] is None or audit.identity(v['identity']) in refs]
    obs['lifecycle']=dict(schema='aijade.process-lifecycle-view.v1',runId='c'*32,journalPath='/unused/synthetic-journal.jsonl',
        journalBytes=len(raw),journalSha256=hashlib.sha256(raw).hexdigest(),lastSequence=count,
        scopeId=scope,controllerIdentity=controller,leases=leases,
        controllers=[v['leaseId'] for v in leases if v['identity']==controller],referencedIdentities=[list(v) for v in refs])


def setup_scopes():
    f=Fixture();f.events.pop(5)  # Exact parent WAIT already proves managed kernel absence.
    opened=copy.deepcopy(f.events[1]);opened.update(event='SCOPE_OPEN',monotonicSeconds=12.2,writer=CHILD,
        data=dict(scopeId=NESTED,controllerIdentity=CHILD,parentLeaseId=L1,stageId='block-1'))
    closed=copy.deepcopy(opened);closed.update(event='SCOPE_CLOSE',monotonicSeconds=13.8,data=dict(scopeId=NESTED))
    f.events += [opened,closed];f.events.sort(key=lambda e:e['monotonicSeconds']);f.seal()
    return f


def interleaved_fixture():
    f=setup_scopes()
    # A starts first, but actual capture and final prefix occur after B.
    a=copy.deepcopy(f.rows[1]);a['monotonicSeconds']=13.;a['observationCompletedMonotonic']=14.4
    obs=a['processObservation'];obs.update(startedMonotonic=13.001,finishedMonotonic=14.3)
    for i,frame in enumerate(obs['syntheticFrames']):
        frame['graphStartedMonotonic']=14.1+i*.1;frame['graphCompletedMonotonic']=14.11+i*.1
    b=copy.deepcopy(f.rows[0]);b['monotonicSeconds']=13.05;b['observationCompletedMonotonic']=13.4
    obs=b['processObservation'];obs.update(startedMonotonic=13.051,finishedMonotonic=13.35,
        ownedRoots=[dict(pid=CHILD['pid'],createTime=CHILD['createTimeMicros']/1000000)])
    for i,frame in enumerate(obs['syntheticFrames']):
        frame['graphStartedMonotonic']=13.15+i*.1;frame['graphCompletedMonotonic']=13.16+i*.1
        frame['rows']=[rss(CHILD,50)]
    obs['ownedProcesses']=[rss(CHILD,50)];obs['ownedRssBytes']=b['rssBytes']=50
    project(f,a,7,SCOPE,ROOT);project(f,b,5,NESTED,CHILD)
    f.rows=[a,b]
    return f


class ScopePrefixAuditControls(unittest.TestCase):
    def setUp(self):
        self.sample=patch.object(audit,'_validate_sample',side_effect=fake_sample)
        self.frames=patch.object(audit,'_raw_frames',side_effect=lambda obs,policy:copy.deepcopy(obs['syntheticFrames']))
        self.sample.start();self.frames.start();self.addCleanup(self.sample.stop);self.addCleanup(self.frames.stop)

    def verify(self,f):
        return audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=POLICY,controller=ROOT)

    def test_01_cross_scope_outer_order_may_have_true_prefix_inversion(self):
        f=interleaved_fixture()
        a,b=f.rows
        self.assertLess(a['monotonicSeconds'],b['monotonicSeconds'])
        self.assertGreater(a['processObservation']['lifecycle']['journalBytes'],b['processObservation']['lifecycle']['journalBytes'])
        self.assertGreater(a['processObservation']['syntheticFrames'][0]['graphStartedMonotonic'],
                           b['processObservation']['syntheticFrames'][-1]['graphCompletedMonotonic'])
        self.assertEqual(self.verify(f)['status'],'LIFECYCLE_RAW_AUDIT_PASS')

    def test_02_same_scope_real_prefix_rollback_is_still_refused(self):
        f=setup_scopes();a=copy.deepcopy(f.rows[0]);b=copy.deepcopy(a)
        b['monotonicSeconds']=13.4;b['observationCompletedMonotonic']=13.75
        obs=b['processObservation'];obs['sampleId']='e'*32
        obs.update(startedMonotonic=13.401,finishedMonotonic=13.7)
        for i,frame in enumerate(obs['syntheticFrames']):
            frame['graphStartedMonotonic']=13.5+i*.1;frame['graphCompletedMonotonic']=13.51+i*.1
        # Both actual prefixes contain the same live task/register/release and
        # parent scope. Only the nested sibling scope-open suffix is rolled back.
        project(f,a,5,SCOPE,ROOT);project(f,b,4,SCOPE,ROOT);f.rows=[a,b]
        with self.assertRaisesRegex(ValueError,'prefix reversed within the same verified scope'):self.verify(f)

    def test_03_relabelled_duplicate_capture_cannot_overlap_same_scope_calls(self):
        f=setup_scopes();a=copy.deepcopy(f.rows[0]);b=copy.deepcopy(a)
        a['processObservation']['startedMonotonic']=13.01
        b['processObservation']['startedMonotonic']=13.01
        b['monotonicSeconds']=13.005;b['processObservation']['sampleId']='e'*32
        project(f,a,5,SCOPE,ROOT);project(f,b,5,SCOPE,ROOT);f.rows=[a,b]
        with self.assertRaisesRegex(ValueError,'same-scope original observation calls overlap'):self.verify(f)


if __name__=='__main__':unittest.main()
