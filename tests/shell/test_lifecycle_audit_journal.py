"""Coherently rebound offline journals/raw projections; no actual processes."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'experiments/ch7'))
import lifecycle_audit as a
import process_lifecycle as producer

Q = 'a' * 40
P = 'b' * 64
POLICY = {'synthetic':True, 'lifecycle':{'execShimSha256':'d' * 64}}
ROOT = dict(pid=100, createTimeMicros=100000000, parentPid=5)
CHILD = dict(pid=200, createTimeMicros=200000000, parentPid=100)
L0 = '0' * 32
L1 = '1' * 32
SCOPE = '2' * 32


def node(ident):
    return dict(ident, createTime=ident['createTimeMicros'] / 1000000, category='other')


def rss(ident, value):
    return dict(pid=ident['pid'], createTime=ident['createTimeMicros'] / 1000000,
                parentPid=ident['parentPid'], rssBytes=value, rssSource='psutil-live')


class Fixture:
    def __init__(self):
        self.events = []
        def add(kind, at, data, writer=ROOT):
            self.events.append(dict(schema=a.LIFECYCLE_SCHEMA, event=kind, monotonicSeconds=at,
                runId='c' * 32, writer=copy.deepcopy(writer), sourceCommit=Q, policySha256=P, data=data))
        add('CONTROLLER_REGISTER', 10, dict(leaseId=L0, role='controller', stageId='sequence',
            identity=ROOT, parentIdentity=None, commandSha256='d' * 64, executableSha256='e' * 64, readyMonotonic=9.9))
        add('SCOPE_OPEN', 11, dict(scopeId=SCOPE, controllerIdentity=ROOT, parentLeaseId=None, stageId='sequence'))
        add('FINITE_REGISTER', 12, dict(leaseId=L1, role='finite', stageId='task', identity=CHILD,
            parentIdentity=ROOT, commandSha256='f' * 64, executableSha256='e' * 64,
            shimSha256='d' * 64, readyMonotonic=11.9,
            identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD'))
        add('RELEASE', 12.1, dict(leaseId=L1))
        add('WAIT', 14, dict(leaseId=L1, identity=CHILD, exitCode=0, waitSource='Popen.wait', reapedMonotonic=13.9))
        add('ABSENCE', 16, dict(identity=CHILD, sampleId='5' * 32, phase='after', nativeStdoutSha256='7' * 64,
                                graphStartedMonotonic=15.2))
        add('SCOPE_CLOSE', 17, dict(scopeId=SCOPE))
        self.rows = [self.observation(13, '4' * 32, True), self.observation(15, '5' * 32, False)]
        self.seal()

    def observation(self, now, sid, child):
        rows = [rss(ROOT, 100)] + ([rss(CHILD, 50)] if child else [])
        nodes = [node(ROOT)] + ([node(CHILD)] if child else [])
        frames = [dict(phase=phase, nodes=copy.deepcopy(nodes), rows=copy.deepcopy(rows), collector=None,
            nativeSha256=('6' if phase == 'before' else '7') * 64,
            graphStartedMonotonic=now + .1 * (i + 1), graphCompletedMonotonic=now + .1 * (i + 1) + .01)
            for i, phase in enumerate(['before', 'after'])]
        observation = dict(schemaVersion=3, sampleId=sid, startedMonotonic=now, finishedMonotonic=now + .3,
            ownedRoots=[dict(pid=ROOT['pid'], createTime=ROOT['createTimeMicros'] / 1000000)],
            ownedProcesses=rows, ownedRssBytes=sum(x['rssBytes'] for x in rows), syntheticFrames=frames, syntheticValid=True)
        return dict(processObservation=observation, monotonicSeconds=now, observationCompletedMonotonic=now + .3,
                    rssBytes=observation['ownedRssBytes'])

    def seal(self, project=True):
        previous = '0' * 64; lines = []
        for seq, event in enumerate(self.events, 1):
            event['seq'] = seq; event['previousSha256'] = previous
            event.pop('sha256', None)
            event['sha256'] = hashlib.sha256(a.canonical(event)).hexdigest()
            lines.append(a.canonical(event) + b'\n'); previous = event['sha256']
        self.raw = b''.join(lines)
        if project:
            for row in self.rows:
                prefix_count = sum(e['monotonicSeconds'] <= row['monotonicSeconds'] for e in self.events)
                prefix = b''.join(lines[:prefix_count]); state = producer.replay_journal(prefix)
                obs = row['processObservation']
                refs = sorted({a.node_identity(n) for f in obs['syntheticFrames'] for n in f['nodes']})
                leases = [v for v in state['leases'].values() if v['absence'] is None or a.identity(v['identity']) in refs]
                obs['lifecycle'] = dict(schema='aijade.process-lifecycle-view.v1', runId='c' * 32,
                    journalPath='/Volumes/Untitled/AIJADE/.runtime/posix/tmp/synthetic-only.jsonl',
                    journalBytes=len(prefix), journalSha256=hashlib.sha256(prefix).hexdigest(), lastSequence=prefix_count,
                    scopeId=SCOPE, controllerIdentity=ROOT, leases=leases, controllers=[L0],
                    referencedIdentities=[list(x) for x in refs])


def fake_sample(row, policy, journal=None):
    if row['processObservation'].get('syntheticValid') is not True:
        raise ValueError('synthetic native/API evidence adverse')
    return dict(status='PASS', ownedRssBytes=row['rssBytes'])


class LifecycleJournalAuditControls(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.sample_patch = patch.object(a, '_validate_sample', side_effect=fake_sample)
        self.frame_patch = patch.object(a, '_raw_frames', side_effect=lambda obs, policy:copy.deepcopy(obs['syntheticFrames']))
        self.sample_patch.start(); self.frame_patch.start()
        self.addCleanup(self.sample_patch.stop); self.addCleanup(self.frame_patch.stop)

    def audit(self):
        return a.verify_lifecycle(self.fixture.raw, self.fixture.rows, source_commit=Q,
                                  policy_sha256=P, policy=POLICY, controller=ROOT)

    def test_01_complete_launch_wait_native_absence_and_cleanup(self):
        result = self.audit()
        self.assertEqual(result['finiteLeases'], 1)
        self.assertEqual(result['finiteWaitZero'], 1)
        self.assertEqual(result['peakObservedOwnedRssBytes'], 150)
        self.assertTrue(result['cleanupAccepted'])
        self.assertFalse(result['formalHardwareQualification'])

    def test_02_original_event_hash_tamper_refuses(self):
        self.fixture.raw = self.fixture.raw.replace(b'"exitCode":0', b'"exitCode":2')
        with self.assertRaisesRegex(ValueError, 'bytes changed'): self.audit()

    def test_03_coherently_rebound_source_substitution_refuses(self):
        for event in self.fixture.events: event['sourceCommit'] = '9' * 40
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'frozen source'): self.audit()

    def test_04_nonzero_actual_wait_is_retained_adverse(self):
        self.fixture.events[4]['data']['exitCode'] = 7
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'nonzero'): self.audit()

    def test_05_absence_cannot_replace_missing_wait(self):
        self.fixture.events[4]['event'] = 'DISCOVER'
        self.fixture.events[4]['data'] = dict(identity=CHILD,ancestry=[CHILD,ROOT],scopeId=SCOPE,
            sampleId='4'*32,phase='after',nativeStdoutSha256='7'*64,
            graphStartedMonotonic=13.2,graphCompletedMonotonic=13.21)
        self.fixture.seal(project=False)
        with self.assertRaisesRegex(ValueError, 'replace actual wait'): self.audit()

    def test_06_parent_wait_identity_cannot_be_substituted(self):
        self.fixture.events[4]['data']['identity'] = dict(CHILD, createTimeMicros=200000001)
        self.fixture.seal(project=False)
        with self.assertRaisesRegex(ValueError, 'unbound finite terminal'): self.audit()

    def test_07_wait_before_release_is_not_repaired_by_zero_exit(self):
        self.fixture.events[4]['data']['reapedMonotonic'] = 12
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'predates actual release'): self.audit()

    def test_08_absence_requires_the_saved_native_frame_hash(self):
        self.fixture.events[5]['data']['nativeStdoutSha256'] = '9' * 64
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'bound original complete native frame'): self.audit()

    def test_09_absence_frame_must_follow_bound_actual_wait(self):
        frame = self.fixture.rows[1]['processObservation']['syntheticFrames'][1]
        frame['graphStartedMonotonic'] = 13.8
        self.fixture.events[5]['data']['graphStartedMonotonic'] = 13.8
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'predates actual finite wait'): self.audit()

    def test_10_still_present_identity_is_not_absent_after_wait(self):
        obs = self.fixture.rows[1]['processObservation']
        for frame in obs['syntheticFrames']:
            frame['nodes'].append(node(CHILD)); frame['rows'].append(rss(CHILD,50))
        obs['ownedProcesses'] = copy.deepcopy(obs['syntheticFrames'][1]['rows'])
        obs['ownedRssBytes'] = self.fixture.rows[1]['rssBytes'] = 150
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'reaped managed identity is still present'): self.audit()

    def test_11_missing_persistent_root_refuses_without_fake_reparent(self):
        obs = self.fixture.rows[1]['processObservation']
        for frame in obs['syntheticFrames']: frame['nodes'] = []; frame['rows'] = []
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'persistent controller missing'): self.audit()

    def test_12_actual_changed_parent_is_rejected_from_native_graph(self):
        obs = self.fixture.rows[0]['processObservation']
        for frame in obs['syntheticFrames']:
            frame['nodes'][1]['parentPid'] = 99
            frame['rows'] = [frame['rows'][0]]
        obs['ownedProcesses'] = [obs['ownedProcesses'][0]]
        obs['ownedRssBytes'] = self.fixture.rows[0]['rssBytes'] = 100
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'registered process parent changed'): self.audit()

    def test_13_present_rss_unknown_never_zero_filled_by_wait0(self):
        self.fixture.rows[0]['processObservation']['syntheticFrames'][0]['rows'][1]['rssBytes'] = None
        with self.assertRaisesRegex(ValueError, 'RSS unknown'): self.audit()

    def test_14_pid_reuse_does_not_inherit_finite_lease(self):
        obs = self.fixture.rows[0]['processObservation']
        reused = dict(CHILD, createTimeMicros=300000000)
        for frame in obs['syntheticFrames']:
            frame['nodes'][1] = node(reused); frame['rows'][1] = rss(reused,50)
        obs['ownedProcesses'][1] = rss(reused,50)
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'active registered PID reused'): self.audit()

    def test_15_dropping_active_view_lease_is_rejected(self):
        self.fixture.rows[0]['processObservation']['lifecycle']['leases'].pop()
        with self.assertRaisesRegex(ValueError, 'omitted/changed active'): self.audit()

    def test_16_unknown_or_truncated_journal_is_not_a_favorable_prefix(self):
        self.fixture.raw = self.fixture.raw[:-1]
        with self.assertRaisesRegex(ValueError, 'truncated'): self.audit()

    def test_17_exact_parent_kernel_reap_closes_managed_identity_without_extra_census(self):
        self.fixture.events.pop(5)
        self.fixture.seal()
        result = self.audit()
        self.assertTrue(result['cleanupAccepted'])
        self.assertEqual(result['finiteWaitZero'], 1)

    def test_18_root_controller_receipt_binding_is_independent(self):
        with self.assertRaisesRegex(ValueError, 'bound controller receipt'):
            a.verify_lifecycle(self.fixture.raw, self.fixture.rows, source_commit=Q, policy_sha256=P,
                               policy=POLICY, controller=dict(ROOT,pid=999))

    def test_19_unbound_new_controller_cannot_adopt_foreign_pid(self):
        self.fixture.events[2]['event'] = 'CONTROLLER_REGISTER'
        self.fixture.seal(project=False)
        with self.assertRaisesRegex(ValueError, 'only initial self controller'): self.audit()

    def test_20_native_api_validator_is_called_for_every_original_sample(self):
        self.fixture.rows[1]['processObservation']['syntheticValid'] = False
        with self.assertRaisesRegex(ValueError, 'native/API evidence adverse'): self.audit()

    def discovered_fixture(self):
        grandchild = dict(pid=300, createTimeMicros=300000000, parentPid=200)
        obs = self.fixture.rows[0]['processObservation']
        for frame in obs['syntheticFrames']:
            frame['nodes'].append(node(grandchild)); frame['rows'].append(rss(grandchild, 25))
        obs['ownedProcesses'] = copy.deepcopy(obs['syntheticFrames'][1]['rows'])
        obs['ownedRssBytes'] = self.fixture.rows[0]['rssBytes'] = 175
        template = copy.deepcopy(self.fixture.events[4])
        template.update(event='DISCOVER', monotonicSeconds=13.4,
            data=dict(identity=grandchild,ancestry=[grandchild,CHILD,ROOT],scopeId=SCOPE,
                      sampleId='4'*32,phase='after',nativeStdoutSha256='7'*64,
                      graphStartedMonotonic=13.2,graphCompletedMonotonic=13.21))
        self.fixture.events.insert(4, template)
        absence = copy.deepcopy(self.fixture.events[-2])
        absence.update(event='DISCOVER_ABSENCE', monotonicSeconds=16.1,
            data=dict(identity=grandchild, sampleId='5' * 32, phase='after', nativeStdoutSha256='7' * 64,
                      graphStartedMonotonic=15.2, graphCompletedMonotonic=15.21))
        self.fixture.events.insert(-1, absence)
        self.fixture.seal()
        return grandchild

    def test_21_discovered_only_absence_is_not_finite_success_or_wait_zero(self):
        self.discovered_fixture()
        result = self.audit()
        self.assertEqual(result['finiteWaitZero'], 1)
        self.assertEqual(result['discoveredOnlyConfirmedAbsentUnknownExit'], 1)

    def test_22_discovered_only_without_native_absence_stays_unresolved(self):
        self.discovered_fixture()
        self.fixture.events.pop(-2)
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'absence unconfirmed'): self.audit()

    def test_23_discovery_cannot_adopt_foreign_unobserved_identity(self):
        self.discovered_fixture()
        foreign = dict(pid=999,createTimeMicros=999000000,parentPid=99)
        self.fixture.events[4]['data']['identity'] = foreign
        self.fixture.events[4]['data']['ancestry'] = [foreign,dict(pid=99,createTimeMicros=150000000,parentPid=100),ROOT]
        self.fixture.events[-2]['data']['identity'] = foreign
        obs = self.fixture.rows[0]['processObservation']
        for frame in obs['syntheticFrames']:
            frame['nodes'].pop(); frame['rows'].pop()
        obs['ownedProcesses'].pop()
        obs['ownedRssBytes'] = self.fixture.rows[0]['rssBytes'] = 150
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'discovery target missing/reused in original native frame'): self.audit()

    def test_24_local_block_cleanup_does_not_forge_its_parent_wait(self):
        nested_scope = '3' * 32
        self.fixture.events = self.fixture.events[:4]
        opened = copy.deepcopy(self.fixture.events[1])
        opened.update(event='SCOPE_OPEN', monotonicSeconds=12.2, writer=CHILD,
            data=dict(scopeId=nested_scope, controllerIdentity=CHILD, parentLeaseId=L1, stageId='block-1'))
        closed = copy.deepcopy(opened)
        closed.update(event='SCOPE_CLOSE', monotonicSeconds=13.8, data=dict(scopeId=nested_scope))
        self.fixture.events.extend([opened, closed])
        self.fixture.rows = self.fixture.rows[:1]
        obs = self.fixture.rows[0]['processObservation']
        for frame in obs['syntheticFrames']: frame['rows'] = [rss(CHILD,50)]
        obs['ownedProcesses'] = [rss(CHILD,50)]
        obs['ownedRoots'] = [dict(pid=CHILD['pid'],createTime=CHILD['createTimeMicros']/1000000)]
        obs['ownedRssBytes'] = self.fixture.rows[0]['rssBytes'] = 50
        self.fixture.seal()
        obs['lifecycle'].update(scopeId=nested_scope,controllerIdentity=CHILD,controllers=[L1])
        result = a.verify_lifecycle(self.fixture.raw, self.fixture.rows, source_commit=Q,
            policy_sha256=P, policy=POLICY, controller=CHILD, scope_id=nested_scope)
        self.assertTrue(result['cleanupAccepted'])
        self.assertEqual(result['finiteWaitZero'], 0)
        # Enclosing sequence still cannot claim complete cleanup or finite wait0.
        with self.assertRaisesRegex(ValueError, 'unresolved/nonzero'):
            self.audit()

    def test_25_coherently_rebound_parent_creation_cannot_forge_ancestry(self):
        self.discovered_fixture()
        self.fixture.events[4]['data']['ancestry'][1] = dict(CHILD,createTimeMicros=201000000)
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'claimed discovery ancestry differs from original native parent chain'):
            self.audit()

    def scoped_discovery(self, belongs_to_child):
        grandchild = self.discovered_fixture()
        nested_scope = '3' * 32
        opened = copy.deepcopy(self.fixture.events[1])
        opened.update(event='SCOPE_OPEN',monotonicSeconds=12.2,writer=CHILD,
            data=dict(scopeId=nested_scope,controllerIdentity=CHILD,parentLeaseId=L1,stageId='block-1'))
        closed = copy.deepcopy(opened)
        closed.update(event='SCOPE_CLOSE',monotonicSeconds=13.8,data=dict(scopeId=nested_scope))
        self.fixture.events.insert(4,opened)
        self.fixture.events.insert(6,closed)
        parent = self.fixture.rows[0]
        cleanup = self.fixture.rows[1]
        if not belongs_to_child:
            grandchild = dict(grandchild,parentPid=ROOT['pid'])
            for event in self.fixture.events:
                if event['event'] == 'DISCOVER':
                    event['data'].update(identity=grandchild,ancestry=[grandchild,ROOT])
                elif event['event'] == 'DISCOVER_ABSENCE':event['data']['identity']=grandchild
            for frame in parent['processObservation']['syntheticFrames']:
                frame['nodes'][-1] = node(grandchild);frame['rows'][-1] = rss(grandchild,25)
            parent['processObservation']['ownedProcesses'][-1]=rss(grandchild,25)
        local = copy.deepcopy(parent)
        local['monotonicSeconds'] += .05;local['observationCompletedMonotonic'] += .05
        obs=local['processObservation'];obs['sampleId']='6'*32
        obs['startedMonotonic'] += .05;obs['finishedMonotonic'] += .05
        obs['ownedRoots']=[dict(pid=CHILD['pid'],createTime=CHILD['createTimeMicros']/1000000)]
        for frame in obs['syntheticFrames']:
            frame['graphStartedMonotonic'] += .05;frame['graphCompletedMonotonic'] += .05
            frame['rows']=[rss(CHILD,50)]+([rss(grandchild,25)] if belongs_to_child else [])
        obs['ownedProcesses']=copy.deepcopy(obs['syntheticFrames'][-1]['rows'])
        obs['ownedRssBytes']=local['rssBytes']=sum(r['rssBytes'] for r in obs['ownedProcesses'])
        self.fixture.rows=[parent,local,cleanup]
        self.fixture.seal()
        obs['lifecycle'].update(scopeId=nested_scope,controllerIdentity=CHILD,controllers=[L1])
        principal=b''.join(self.fixture.raw.splitlines(keepends=True)[:7])
        return principal,local,[parent,cleanup],nested_scope

    def test_26_parent_owned_sibling_does_not_block_local_scope_cleanup(self):
        principal,local,context,scope=self.scoped_discovery(False)
        result=a.verify_lifecycle(principal,[local],source_commit=Q,policy_sha256=P,policy=POLICY,
            controller=CHILD,scope_id=scope,ancestry_samples=context,ancestry_journal=self.fixture.raw)
        self.assertTrue(result['cleanupAccepted'])
        self.assertEqual(result['discoveredOnlyConfirmedAbsentUnknownExit'],0)

    def test_27_parent_first_discovered_block_descendant_remains_local_responsibility(self):
        principal,local,context,scope=self.scoped_discovery(True)
        with self.assertRaisesRegex(ValueError,'absence unconfirmed'):
            a.verify_lifecycle(principal,[local],source_commit=Q,policy_sha256=P,policy=POLICY,
                controller=CHILD,scope_id=scope,ancestry_samples=context,ancestry_journal=self.fixture.raw)

    def test_28_missing_parent_source_frame_cannot_shrink_local_responsibility(self):
        principal,local,context,scope=self.scoped_discovery(True)
        with self.assertRaisesRegex(ValueError,'discovery lacks original complete native ancestry frame'):
            a.verify_lifecycle(principal,[local],source_commit=Q,policy_sha256=P,policy=POLICY,
                controller=CHILD,scope_id=scope)

    def test_29_coherent_fake_chain_excluding_block_is_rejected_before_scope_filter(self):
        principal,local,context,scope=self.scoped_discovery(True)
        event=next(e for e in self.fixture.events if e['event']=='DISCOVER')
        event['data']['ancestry'][1]=dict(CHILD,createTimeMicros=201000000)
        self.fixture.seal()
        # Rebuild exact principal prefix and local view against all rebound bytes.
        local=self.fixture.rows[1]
        local['processObservation']['lifecycle'].update(scopeId=scope,controllerIdentity=CHILD,controllers=[L1])
        principal=b''.join(self.fixture.raw.splitlines(keepends=True)[:7])
        context=[self.fixture.rows[0],self.fixture.rows[2]]
        with self.assertRaisesRegex(ValueError,'claimed discovery ancestry differs from original native parent chain'):
            a.verify_lifecycle(principal,[local],source_commit=Q,policy_sha256=P,policy=POLICY,
                controller=CHILD,scope_id=scope,ancestry_samples=context,ancestry_journal=self.fixture.raw)

    def test_30_context_same_observer_id_cannot_change_outer_raw_record(self):
        changed=copy.deepcopy(self.fixture.rows[0])
        changed['rssBytes']+=1
        with self.assertRaisesRegex(ValueError,'conflicting original ancestry sample identity'):
            a.verify_lifecycle(self.fixture.raw,self.fixture.rows,source_commit=Q,policy_sha256=P,policy=POLICY,
                controller=ROOT,ancestry_samples=[changed],ancestry_journal=self.fixture.raw)


if __name__ == '__main__':
    unittest.main()
