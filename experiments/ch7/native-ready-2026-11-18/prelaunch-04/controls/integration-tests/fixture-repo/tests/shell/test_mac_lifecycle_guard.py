"""Offline v3 evidence fixtures; no native/API/listener invocation."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
import process_lifecycle as life
import mac_process_guard_v3 as guard
from test_mac_bulk_census import policy as bulk_policy, native, graph, row
from test_mac_process_guard import listener, empty_api


def policy():
    p=bulk_policy();p.update(schemaVersion=3,kind=guard.KIND)
    p['lifecycle']=dict(moduleSha256=guard._file_sha(Path(life.__file__)),
        execShimSha256=guard._file_sha(REPO/'experiments/ch7/lifecycle_exec.py'),
        coordinationLockPath=str(guard.coordination_lock_path(p)),maxLockWaitSeconds=1.25,maxObservationSeconds=2.5)
    return p


def journal_events(finite=False,wait=True,exit_code=0):
    writer=dict(pid=20,createTimeMicros=20000000,parentPid=1)
    events=[]
    def add(name,data,mono):
        e=dict(schema=life.EVENT_SCHEMA,seq=len(events)+1,event=name,monotonicSeconds=mono,runId='1'*32,
            writer=writer,sourceCommit='2'*40,policySha256='3'*64,data=data,
            previousSha256=events[-1]['sha256'] if events else life.ZERO)
        e['sha256']=life.digest(life.canonical(e));events.append(e)
    add('CONTROLLER_REGISTER',dict(leaseId='4'*32,role='controller',stageId='sequence',identity=writer,
        parentIdentity=None,commandSha256='a'*64,executableSha256='b'*64,readyMonotonic=.5),1.)
    add('SCOPE_OPEN',dict(scopeId='5'*32,controllerIdentity=writer,parentLeaseId=None,stageId='sequence'),2.)
    if finite:
        child=dict(pid=30,createTimeMicros=30000000,parentPid=20)
        add('FINITE_REGISTER',dict(leaseId='6'*32,role='finite',stageId='driver',identity=child,
            parentIdentity=writer,commandSha256='c'*64,executableSha256='d'*64,readyMonotonic=2.5),3.)
        add('RELEASE',dict(leaseId='6'*32),4.)
        if wait:add('WAIT',dict(leaseId='6'*32,identity=child,exitCode=exit_code,
                              waitSource='Popen.wait',reapedMonotonic=100.5),100.55)
    return events


def raw_events(events):return b''.join(life.canonical(x)+b'\n' for x in events)


def rehash(events):
    events=copy.deepcopy(events)
    for i,e in enumerate(events):
        e['seq']=i+1;e['previousSha256']=events[i-1]['sha256'] if i else life.ZERO
        e['sha256']=life.digest(life.canonical({k:v for k,v in e.items() if k!='sha256'}))
    return events


def native_journal_events(events,p):
    """Finite helper leases matching the two serialized native self witnesses."""
    events=copy.deepcopy(events);writer=events[0]['writer']
    for pid,lid,start in [(500,'c'*32,100.1),(501,'d'*32,100.7)]:
        ident=dict(pid=pid,createTimeMicros=pid*1000000,parentPid=20)
        rows=[('FINITE_REGISTER',dict(leaseId=lid,role='finite',stageId='observer-native-census',identity=ident,
            parentIdentity=writer,commandSha256=guard.canonical_sha256([p['nativeHelper']['path']]),
            executableSha256=p['nativeHelper']['sha256'],readyMonotonic=start+.0005),start+.001),
            ('RELEASE',dict(leaseId=lid),start+.002),
            ('WAIT',dict(leaseId=lid,identity=ident,exitCode=0,waitSource='Popen.wait',reapedMonotonic=start+.008),start+.009)]
        for name,data,mono in rows:
            events.append(dict(schema=life.EVENT_SCHEMA,seq=0,event=name,monotonicSeconds=mono,runId='1'*32,
                writer=writer,sourceCommit='2'*40,policySha256='3'*64,data=data,previousSha256=life.ZERO,sha256=life.ZERO))
    return rehash(sorted(events,key=lambda x:x['monotonicSeconds']))


def fixture(finite=False,wait=True,exit_code=0,extra_before=(),extra_after=(),events=None,owned=True):
    p=policy();events=native_journal_events(events or journal_events(finite,wait,exit_code),p);raw=raw_events(events)
    before_extra=[row(30,20)] if finite else []
    before=graph(p,native(extra=tuple(before_extra)+tuple(extra_before)))
    after=graph(p,native(extra=tuple(extra_after),collector_pid=501))
    before['nativeCensus']['managedLeaseId']='c'*32
    after['nativeCensus']['managedLeaseId']='d'*32
    def frame(g,start):
        members=guard._owned_ids(g['nodes'],[dict(pid=20,createTime=20.)]) if owned else set()
        rows=[dict(pid=n['pid'],createTime=n['createTime'],parentPid=n['parentPid'],
                   rssBytes=4000000 if n['pid'] in (500,501) else 1000,
                   rssSource='native-collector-self' if n['pid'] in (500,501) else 'psutil-live')
              for n in g['nodes'] if n['pid'] in members]
        daemons={}
        for k,v in p['daemon'].items():
            v=copy.deepcopy(v);v['executablePathSha256']=guard._sha_bytes(v.pop('executable').encode());daemons[k]=v
        return dict(processGraph=g,daemon=daemons,ownedProcesses=rows,errors=[],listener=listener(),
                    graphStartedMonotonic=start,graphCompletedMonotonic=start+.01)
    b,a=frame(before,100.1),frame(after,100.7)
    state=life.replay_journal(raw);refs=sorted({life.key_from_node(n) for g in (before,after) for n in g['nodes']})
    selected=[v for v in state['leases'].values() if v['absence'] is None or life.identity_key(v['identity']) in refs]
    view=dict(schema=life.VIEW_SCHEMA,runId='1'*32,journalPath=str(life.POSIX/'tmp/offline-v3-events.jsonl'),
        journalBytes=len(raw),journalSha256=life.digest(raw),lastSequence=len(events),scopeId='5'*32,
        controllerIdentity=events[0]['writer'],leases=selected,referencedIdentities=[list(v) for v in refs],controllers=['4'*32])
    lockid=dict(device=1,inode=2,regular=True,singleLink=True,ownedByCurrentUser=True)
    o=dict(schemaVersion=3,sampleId='7'*32,startedMonotonic=100.,finishedMonotonic=101.,
        observerModuleSha256=guard._file_sha(Path(guard.__file__)),nativeSourceSha256=p['nativeHelper']['sourceSha256'],
        nativeHelperSha256=p['nativeHelper']['sha256'],preservedV1SourceSha256=guard._file_sha(REPO/'experiments/ch7/mac_process_guard.py'),
        preservedV2SourceSha256=guard._file_sha(REPO/'experiments/ch7/mac_process_guard_v2.py'),
        lifecycleModuleSha256=p['lifecycle']['moduleSha256'],lifecyclePolicySha256='3'*64,
        policyCanonicalSha256=guard.canonical_sha256(p),ownedRoots=[dict(pid=20,createTime=20.)] if owned else [],
        ownedProcesses=a['ownedProcesses'],lifecycle=view,evidence=dict(before=b,after=a,api=empty_api()),
        coordinationLock=dict(schema='aijade.lifecycle.capture-lock.v1',state='HELD_AND_RELEASED',
            pathSha256=guard._sha_bytes(str(guard.coordination_lock_path(p)).encode()),maxWaitSeconds=1.25,
            waitSeconds=.001,initialIdentity=lockid,finalIdentity=dict(lockid),acquiredMonotonic=100.001,releasedMonotonic=100.99))
    return p,o,raw


def discovered_fixture():
    p,o,_=fixture(extra_before=(row(40,20),))
    events=native_journal_events(journal_events(),p);ident=dict(pid=40,createTimeMicros=40000000,parentPid=20)
    for name,phase,mono in [('DISCOVER','before',101.1),('DISCOVER_ABSENCE','after',101.2)]:
        frame=o['evidence'][phase]
        e=dict(schema=life.EVENT_SCHEMA,seq=len(events)+1,event=name,monotonicSeconds=mono,
            runId='1'*32,writer=events[0]['writer'],sourceCommit='2'*40,policySha256='3'*64,
            data=dict(identity=ident,sampleId=o['sampleId'],phase=phase,
                nativeStdoutSha256=frame['processGraph']['nativeCensus']['stdoutSha256'],
                graphStartedMonotonic=frame['graphStartedMonotonic'],graphCompletedMonotonic=frame['graphCompletedMonotonic']),
            previousSha256=events[-1]['sha256'])
        if name=='DISCOVER':e['data'].update(scopeId='5'*32,ancestry=[ident,events[0]['writer']])
        e['sha256']=life.digest(life.canonical(e));events.append(e)
    raw=raw_events(events);state=life.replay_journal(raw)
    o['lifecycle'].update(journalBytes=len(raw),journalSha256=life.digest(raw),lastSequence=len(events))
    o['finishedMonotonic']=102.
    return p,o,raw


class LifecycleGuardControls(unittest.TestCase):
    def decision(self,p,o,raw):return guard.validate_observation(p,o,lifecycle_journal=raw)
    def test_stable_persistent_and_exact_native_self(self):
        p,o,r=fixture();d=self.decision(p,o,r)
        self.assertEqual(d['status'],'PASS',d);self.assertEqual(d['ownedRssBytes'],4001000)
    def test_before_present_after_zero_wait_absent_is_not_reappearance(self):
        p,o,r=fixture(finite=True);d=self.decision(p,o,r)
        self.assertEqual(d['status'],'PASS',d)
        self.assertTrue(life.replay_journal(r)['leases']['6'*32]['absenceWitnessKind']=='PARENT_WAIT_REAPED')
    def test_idle_registry_does_not_authorize_owned_processes(self):
        p,o,r=fixture(owned=False);d=self.decision(p,o,r)
        self.assertEqual(d['status'],'PASS',d);self.assertEqual(d['ownedProcesses'],[])
    def test_missing_finite_without_wait_is_unknown_not_zero(self):
        p,o,r=fixture(finite=True,wait=False);d=self.decision(p,o,r)
        self.assertEqual(d['status'],'UNKNOWN',d);self.assertIsNone(d['ownedRssBytes'])
        self.assertIn('ABSENT_EXIT_STATUS_UNKNOWN',[v['code'] for v in d['blockers']])
    def test_real_child_reappearance_after_reap_is_fail(self):
        p,o,r=fixture(finite=True,extra_after=(row(30,20),));d=self.decision(p,o,r)
        self.assertEqual(d['status'],'FAIL',d)
    def test_zero_wait_does_not_repair_present_unknown_rss(self):
        p,o,r=fixture(finite=True);o['evidence']['before']['ownedProcesses']=[x for x in o['evidence']['before']['ownedProcesses'] if x['pid']!=30]
        o['evidence']['before']['errors']=[dict(code='OWNED_PROCESS_RSS_UNKNOWN',pid=30,errorClass='NoSuchProcess')]
        d=self.decision(p,o,r);self.assertEqual(d['status'],'UNKNOWN',d);self.assertIsNone(d['ownedRssBytes'])
    def test_nonzero_terminal_result_is_adverse(self):
        p,o,r=fixture(finite=True,exit_code=-15);self.assertEqual(self.decision(p,o,r)['status'],'FAIL')
    def test_changed_real_parent_is_rejected(self):
        p,o,r=fixture(finite=True,extra_after=(row(30,1),));self.assertEqual(self.decision(p,o,r)['status'],'FAIL')
    def test_direct_register_cannot_be_deleted_from_projected_view(self):
        p,o,r=fixture(finite=True);o['lifecycle']['leases']=o['lifecycle']['leases'][:1]
        self.assertNotEqual(self.decision(p,o,r)['status'],'PASS')
    def test_wrong_wait_owner_even_with_rehashed_journal_is_rejected(self):
        events=journal_events(True);events[-1]['writer']=dict(pid=31,createTimeMicros=31000000,parentPid=20)
        with self.assertRaises(ValueError):life.replay_journal(raw_events(rehash(events)))
    def test_pid_only_or_wrong_creation_wait_is_rejected(self):
        events=journal_events(True);events[-1]['data']['identity']=dict(events[-1]['data']['identity'])
        events[-1]['data']['identity']['createTimeMicros']+=1
        with self.assertRaises(ValueError):life.replay_journal(raw_events(rehash(events)))
    def test_wrong_api_listener_or_native_witness_still_adverse(self):
        for change in ('api','listener','native'):
            with self.subTest(change=change):
                p,o,r=fixture()
                if change=='api':o['evidence']['api']['modelCount']=True
                if change=='listener':o['evidence']['after']['listener']['records'][0]['pid']=999
                if change=='native':o['evidence']['before']['processGraph']['nativeCensus']['exitCode']=1
                self.assertNotEqual(self.decision(p,o,r)['status'],'PASS')
    def test_whole_budget_includes_postprocessing(self):
        p,o,r=fixture();o['finishedMonotonic']=102.50001
        self.assertNotEqual(self.decision(p,o,r)['status'],'PASS')
    def test_parent_cascade_is_not_inferred_from_missing_root(self):
        p,o,r=fixture();o['ownedRoots']=[dict(pid=99,createTime=99.)]
        d=self.decision(p,o,r);self.assertNotEqual(d['status'],'PASS')
        self.assertNotIn('OWNED_PROCESS_REPARENTED_OUTSIDE_CLOSURE',[b['code'] for b in d['blockers']])
    def test_event_order_and_truncation_refuse(self):
        events=journal_events(True)
        with self.assertRaises(ValueError):life.replay_journal(raw_events(events)[:-1])
        events[2],events[3]=events[3],events[2]
        with self.assertRaises(ValueError):life.replay_journal(raw_events(rehash(events)))
    def test_discovered_absence_is_cleanup_only_with_unknown_exit(self):
        p,o,r=discovered_fixture();d=self.decision(p,o,r)
        self.assertEqual(d['status'],'PASS',d)
        found=life.replay_journal(r)['discovered'][(40,40000000)]
        self.assertEqual(found['exitStatus'],'UNKNOWN')
        self.assertEqual(found['absence']['witnessKind'],'COMPLETE_NATIVE_ABSENCE')
        self.assertNotIn('exitCode',found)
    def test_discovered_later_reappearance_is_refused(self):
        p,old,r=discovered_fixture();_,o,_=fixture(extra_before=(row(40,20),),extra_after=(row(40,20),))
        o['lifecycle']=copy.deepcopy(old['lifecycle'])
        refs=sorted({life.key_from_node(n) for phase in ('before','after') for n in o['evidence'][phase]['processGraph']['nodes']})
        o['lifecycle']['referencedIdentities']=[list(x) for x in refs]
        o['sampleId']='8'*32;o.update(startedMonotonic=110.,finishedMonotonic=111.)
        for frame in (o['evidence']['before'],o['evidence']['after']):
            frame['graphStartedMonotonic']+=10;frame['graphCompletedMonotonic']+=10
        self.assertEqual(self.decision(p,o,r)['status'],'FAIL')
    def test_direct_registration_is_not_suppressed_by_prior_discovery(self):
        events=journal_events(True);discovery=copy.deepcopy(events[2])
        ident=copy.deepcopy(events[2]['data']['identity'])
        discovery.update(event='DISCOVER',monotonicSeconds=2.6,data=dict(identity=ident,scopeId='5'*32,
            ancestry=[ident,events[0]['writer']],sampleId='7'*32,phase='before',nativeStdoutSha256='a'*64,
            graphStartedMonotonic=2.1,graphCompletedMonotonic=2.2))
        events.insert(2,discovery);state=life.replay_journal(raw_events(rehash(events)))
        self.assertIn('6'*32,state['leases']);self.assertIn((30,30000000),state['discovered'])
    def test_missing_native_managed_lease_is_adverse(self):
        p,o,r=fixture();o['evidence']['before']['processGraph']['nativeCensus'].pop('managedLeaseId')
        self.assertEqual(self.decision(p,o,r)['status'],'FAIL')
    def test_wrong_native_lease_pid_or_stage_or_argv_is_adverse(self):
        for field in ('identity','stageId','commandSha256','executableSha256'):
            p,o,r=fixture();events=[json.loads(line) for line in r.splitlines()]
            event=next(v for v in events if v['event']=='FINITE_REGISTER' and v['data']['leaseId']=='c'*32)
            if field=='identity':
                # Change a release target to the other valid finite helper rather
                # than relying on a broken journal hash to reject substitution.
                o['evidence']['before']['processGraph']['nativeCensus']['managedLeaseId']='d'*32
                changed=r
            else:
                event['data'][field]='wrong-stage' if field=='stageId' else 'e'*64
                events=rehash(events);changed=raw_events(events);state=life.replay_journal(changed)
                o['lifecycle'].update(journalBytes=len(changed),journalSha256=life.digest(changed),lastSequence=len(events),
                    leases=[v for v in state['leases'].values() if v['absence'] is None or
                            life.identity_key(v['identity']) in {tuple(x) for x in o['lifecycle']['referencedIdentities']}])
            self.assertEqual(self.decision(p,o,changed)['status'],'FAIL',field)
    def test_refused_unknown_birth_with_zero_cleanup_cannot_become_success(self):
        p,o,r=fixture();events=[json.loads(line) for line in r.splitlines()]
        e=copy.deepcopy(events[-1]);e.update(event='LAUNCH_REFUSED',monotonicSeconds=100.8)
        e['data']=dict(attemptId='e'*32,stageId='controlled-refusal',commandSha256='a'*64,executableSha256='b'*64,
            spawnedPid=31,readyBytes=0,readySha256=life.digest(b''),identityReads=[],identityStatus='UNKNOWN',
            registeredLeaseId=None,errorClass='ControlledIdentityFailure',actualExitCode=0,cleanupKnown=True,
            waitSource='Popen.wait',startedMonotonic=100.75,cleanupCompletedMonotonic=100.79)
        events=rehash(events+[e]);changed=raw_events(events);state=life.replay_journal(changed)
        o['lifecycle'].update(journalBytes=len(changed),journalSha256=life.digest(changed),lastSequence=len(events),
            leases=[v for v in state['leases'].values() if v['absence'] is None or
                    life.identity_key(v['identity']) in {tuple(x) for x in o['lifecycle']['referencedIdentities']}])
        d=self.decision(p,o,changed);self.assertEqual(d['status'],'FAIL')
        self.assertIn('LAUNCH_REFUSED',[v['code'] for v in d['blockers']])
        self.assertNotIn('e'*32,state['leases'])
    def test_refusal_fallback_artifact_marker_remains_adverse(self):
        p,o,r=fixture();o['lifecycle']['launchRefusalArtifacts']=[dict(path=str(life.POSIX/'tmp/launch-refused-fixture.json'),sha256='a'*64)]
        self.assertEqual(self.decision(p,o,r)['status'],'FAIL')


class DiscoveredScopeResponsibilityControls(unittest.TestCase):
    """Pure ownership projection; no observer/process/API calls."""
    def facts(self,parent_discovered=False):
        parent=dict(pid=10,createTimeMicros=10000000,parentPid=1)
        block=dict(pid=20,createTimeMicros=20000000,parentPid=10)
        descendant=dict(pid=40,createTimeMicros=40000000,parentPid=20)
        def node(i):return dict(pid=i['pid'],parentPid=i['parentPid'],
            createTime=i['createTimeMicros']/1000000,createTimeMicros=i['createTimeMicros'])
        chain=[descendant,block,parent] if parent_discovered else [descendant,block]
        scope_controller=parent if parent_discovered else block
        state=dict(leases={'local':dict(identity=block,parentIdentity=None,role='controller',absence=None,waitSeq=None)},
            scopes={'scope':dict(controllerIdentity=scope_controller)},
            discovered={(40,40000000):dict(identity=descendant,scopeId='scope',ancestry=chain)})
        return block,state,[node(parent),node(block),node(descendant)]
    def check(self,block,state,nodes):
        blockers=[]
        members=guard._typed_members(nodes,[dict(pid=block['pid'],createTime=block['createTimeMicros']/1000000)],
            state,block,dict(graphStartedMonotonic=100.,graphCompletedMonotonic=100.1),None,
            lambda code,severity='UNKNOWN',**fields:blockers.append(dict(code=code,severity=severity,**fields)),'before')
        return members,blockers
    def test_parent_only_live_sibling_is_outside_local_discovery_responsibility(self):
        block,state,nodes=self.facts(parent_discovered=True)
        sibling=dict(pid=40,createTimeMicros=40000000,parentPid=10)
        value=state['discovered'][(40,40000000)]
        value.update(identity=sibling,ancestry=[sibling,state['scopes']['scope']['controllerIdentity']])
        nodes[-1]['parentPid']=10
        members,blockers=self.check(block,state,nodes)
        self.assertEqual(members,{20});self.assertEqual(blockers,[])
    def test_parent_first_discovered_block_descendant_remains_local_responsibility(self):
        block,state,nodes=self.facts(parent_discovered=True)
        members,blockers=self.check(block,state,nodes)
        self.assertEqual(members,{20,40});self.assertEqual(blockers,[])
        nodes[-1]['parentPid']=1
        _,blockers=self.check(block,state,nodes)
        self.assertIn('DISCOVERED_ANCESTRY_ESCAPE',[v['code'] for v in blockers])
    def test_local_real_escape_and_parent_change_still_fail(self):
        block,state,nodes=self.facts();nodes[-1]['parentPid']=1
        _,blockers=self.check(block,state,nodes);codes={v['code'] for v in blockers}
        self.assertTrue({'DISCOVERED_ANCESTRY_ESCAPE','DISCOVERED_PARENT_CHANGED'}<=codes)
        self.assertTrue(all(v['severity']=='FAIL' for v in blockers))
    def test_local_reappearance_still_fails(self):
        block,state,nodes=self.facts()
        state['discovered'][(40,40000000)]['absence']=dict(witnessKind='COMPLETE_NATIVE_ABSENCE',graphCompletedMonotonic=99.)
        _,blockers=self.check(block,state,nodes)
        self.assertIn('DISCOVERED_IDENTITY_REAPPEARED',[v['code'] for v in blockers])
    def test_local_pid_reuse_still_fails(self):
        block,state,nodes=self.facts();nodes[-1].update(createTime=41.,createTimeMicros=41000000)
        _,blockers=self.check(block,state,nodes)
        self.assertIn('DISCOVERED_PID_REUSED',[v['code'] for v in blockers])
    def test_missing_or_invalid_ancestry_is_adverse_not_a_scope_exemption(self):
        for change in ('missing','empty','type','edge','cycle','endpoint','identity','scope','creation'):
            with self.subTest(change=change):
                block,state,nodes=self.facts();value=state['discovered'][(40,40000000)]
                if change=='missing':value.pop('ancestry')
                elif change=='empty':value['ancestry']=[]
                elif change=='type':value['ancestry']='not-a-chain'
                elif change=='edge':value['ancestry'][0]=dict(value['identity'],parentPid=1)
                elif change=='cycle':value['ancestry'].append(copy.deepcopy(value['ancestry'][0]))
                elif change=='endpoint':value['ancestry'][-1]=dict(pid=10,createTimeMicros=10000000,parentPid=1)
                elif change=='identity':value['identity']=dict(value['identity'],createTimeMicros=40000001)
                elif change=='scope':value['scopeId']='unknown'
                elif change=='creation':value['ancestry'][-1]=dict(value['ancestry'][-1],createTimeMicros=50000000)
                _,blockers=self.check(block,state,nodes)
                self.assertIn('DISCOVERED_ANCESTRY_INVALID',[v['code'] for v in blockers])


if __name__=='__main__':unittest.main()
