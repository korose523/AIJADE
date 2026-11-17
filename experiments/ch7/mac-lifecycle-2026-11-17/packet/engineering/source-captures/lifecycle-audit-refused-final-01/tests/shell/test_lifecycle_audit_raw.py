"""Full offline native/API/journal replay without mocking either audit validator.

Native/API documents are synthetic serialized fixtures. No native helper,
observer, subprocess, socket, model or live qualification is called.
"""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'experiments/ch7'))
import lifecycle_audit as audit
import mac_process_guard_v3 as guard
import process_lifecycle as producer
from test_lifecycle_audit_journal import Fixture, Q, P, ROOT
from test_mac_bulk_census import policy as bulk_policy, native, row, graph
from test_mac_process_guard import empty_api, listener


def build_fixture():
    p = bulk_policy()
    p.update(schemaVersion=3, kind='mac-lifecycle-observed-idle-daemon-v3',
        lifecycle=dict(moduleSha256=guard._file_sha(Path(guard.lifecycle_support.__file__)),
            execShimSha256=guard._file_sha(Path(guard.__file__).with_name('lifecycle_exec.py')),
            coordinationLockPath=str(guard.coordination_lock_path(p)), maxLockWaitSeconds=1.25,
            maxObservationSeconds=2.5))
    f = Fixture()
    f.events[2]['data']['shimSha256'] = p['lifecycle']['execShimSha256']
    # Actual exact parent wait is a kernel-reap absence witness, so final helper
    # capture does not demand a recursively endless additional census.
    f.events.pop(5)
    for outer_index, outer in enumerate(f.rows):
        obs = outer['processObservation']; now = outer['monotonicSeconds']
        captured = []
        for phase_index, phase in enumerate(['before', 'after']):
            collector_pid = 500 + outer_index * 2 + phase_index
            extra = [row(5, 1)] + ([row(200, 100)] if outer_index == 0 else [])
            data = native(extra, collector_pid=collector_pid, parent=100)
            next(n for n in data['records'] if n['pid'] == 100)['parentPid'] = 5
            saved = graph(p, data)
            owned = []
            for n in saved['nodes']:
                if n['pid'] not in {100, 200, collector_pid}: continue
                owned.append(dict(pid=n['pid'], createTime=n['createTime'], parentPid=n['parentPid'],
                    rssBytes=4000000 if n['pid'] == collector_pid else 1000,
                    rssSource='native-collector-self' if n['pid'] == collector_pid else 'psutil-live'))
            daemon = {}
            for role, expected in p['daemon'].items():
                daemon[role] = {k:expected[k] for k in ['pid','createTime','parentPid','sha256','argvSha256','commandForm']}
                daemon[role]['executablePathSha256'] = hashlib.sha256(expected['executable'].encode()).hexdigest()
            frame = dict(daemon=daemon, errors=[], processGraph=saved, ownedProcesses=owned,
                         listener=listener(), graphStartedMonotonic=now + .1 * (phase_index + 1),
                         graphCompletedMonotonic=now + .1 * (phase_index + 1) + .01)
            captured.append(frame)
        obs['evidence'] = dict(before=captured[0], api=empty_api(), after=captured[1])
        # Producer fixture projects only actual returned native identities.
        obs['syntheticFrames'] = [dict(nodes=x['processGraph']['nodes']) for x in captured]
        obs['ownedProcesses'] = captured[-1]['ownedProcesses']
        obs['ownedRssBytes'] = outer['rssBytes'] = sum(r['rssBytes'] for r in obs['ownedProcesses'])
        ident = dict(device=1,inode=2,regular=True,singleLink=True,ownedByCurrentUser=True)
        obs.update(policyCanonicalSha256=guard.canonical_sha256(p),
            observerModuleSha256=guard._file_sha(Path(guard.__file__)),
            nativeSourceSha256=p['nativeHelper']['sourceSha256'], nativeHelperSha256=p['nativeHelper']['sha256'],
            preservedV1SourceSha256=guard._file_sha(Path(guard.__file__).with_name('mac_process_guard.py')),
            preservedV2SourceSha256=guard._file_sha(Path(guard.__file__).with_name('mac_process_guard_v2.py')),
            lifecycleModuleSha256=p['lifecycle']['moduleSha256'], lifecyclePolicySha256=P,
            coordinationLock=dict(schema='aijade.lifecycle.capture-lock.v1',state='HELD_AND_RELEASED',
                pathSha256=hashlib.sha256(str(guard.coordination_lock_path(p)).encode()).hexdigest(),
                maxWaitSeconds=1.25,waitSeconds=.001,initialIdentity=ident,finalIdentity=dict(ident)))
    add_native_leases(f,p)
    reproject(f)
    return f, p


def add_native_leases(f,p):
    for outer in f.rows:
        for phase in ['before','after']:
            frame=outer['processObservation']['evidence'][phase]
            raw=frame['processGraph']['nativeCensus']
            import base64,json
            collector=json.loads(base64.b64decode(raw['stdoutBase64']))['collector']
            ident={k:collector[k] for k in ['pid','createTimeMicros','parentPid']}
            lease_id='%032x'%collector['pid'];raw['managedLeaseId']=lease_id
            start=frame['graphStartedMonotonic']
            def event(kind,at,data):
                template=copy.deepcopy(f.events[0]);template.pop('sha256',None)
                template.update(event=kind,monotonicSeconds=at,data=data)
                return template
            f.events += [event('FINITE_REGISTER',start+.001,dict(leaseId=lease_id,role='finite',
                stageId='observer-native-census',identity=ident,parentIdentity=ROOT,
                commandSha256=hashlib.sha256(audit.canonical([p['nativeHelper']['path']])).hexdigest(),
                executableSha256=p['nativeHelper']['sha256'],shimSha256=p['lifecycle']['execShimSha256'],readyMonotonic=start+.0005,
                identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD')),
                event('RELEASE',start+.002,dict(leaseId=lease_id)),
                event('WAIT',start+.009,dict(leaseId=lease_id,identity=ident,exitCode=0,
                      waitSource='Popen.wait',reapedMonotonic=start+.008))]


def ancestry_fixture():
    f,p=build_fixture()
    descendant=dict(pid=250,createTimeMicros=250000000,parentPid=200)
    live=f.rows[0]['processObservation']
    for phase_index,phase in enumerate(['before','after']):
        data=native([row(5,1),row(200,100),row(250,200)],collector_pid=500+phase_index,parent=100)
        next(n for n in data['records'] if n['pid']==100)['parentPid']=5
        lease_id=live['evidence'][phase]['processGraph']['nativeCensus']['managedLeaseId']
        live['evidence'][phase]['processGraph']=graph(p,data)
        live['evidence'][phase]['processGraph']['nativeCensus']['managedLeaseId']=lease_id
        owned=live['evidence'][phase]['ownedProcesses']
        owned.append(dict(pid=250,createTime=250.,parentPid=200,rssBytes=1000,rssSource='psutil-live'))
        owned.sort(key=lambda n:n['pid'])
    live['ownedProcesses']=live['evidence']['after']['ownedProcesses']
    live['ownedRssBytes']=f.rows[0]['rssBytes']=sum(n['rssBytes'] for n in live['ownedProcesses'])
    before=f.events[4]
    discovery=copy.deepcopy(before)
    source=live['evidence']['after']
    discovery.update(event='DISCOVER',monotonicSeconds=13.4,data=dict(identity=descendant,
        ancestry=[descendant,dict(pid=200,createTimeMicros=200000000,parentPid=100),ROOT],scopeId='2'*32,
        sampleId=live['sampleId'],phase='after',nativeStdoutSha256=source['processGraph']['nativeCensus']['stdoutSha256'],
        graphStartedMonotonic=source['graphStartedMonotonic'],graphCompletedMonotonic=source['graphCompletedMonotonic']))
    f.events.insert(4,discovery)
    closed=f.rows[1]['processObservation']['evidence']['after']
    absence=copy.deepcopy(discovery)
    absence.update(event='DISCOVER_ABSENCE',monotonicSeconds=16.1,data=dict(identity=descendant,
        sampleId=f.rows[1]['processObservation']['sampleId'],phase='after',
        nativeStdoutSha256=closed['processGraph']['nativeCensus']['stdoutSha256'],
        graphStartedMonotonic=closed['graphStartedMonotonic'],graphCompletedMonotonic=closed['graphCompletedMonotonic']))
    f.events.insert(-1,absence)
    f.rows[0]['observationCompletedMonotonic']=13.5
    f.rows[1]['observationCompletedMonotonic']=16.2
    reproject(f)
    return f,p


def reproject(f):
    f.events.sort(key=lambda event:event['monotonicSeconds'])
    f.seal(project=False)
    lines=f.raw.splitlines(keepends=True)
    for outer in f.rows:
        obs=outer['processObservation']
        count=sum(e['monotonicSeconds']<=outer['observationCompletedMonotonic'] for e in f.events)
        raw=b''.join(lines[:count]);state=producer.replay_journal(raw)
        refs=sorted({audit.node_identity(n) for phase in ['before','after'] for n in obs['evidence'][phase]['processGraph']['nodes']})
        obs['lifecycle'].update(journalBytes=len(raw),journalSha256=hashlib.sha256(raw).hexdigest(),lastSequence=count,
            referencedIdentities=[list(v) for v in refs],
            leases=[v for v in state['leases'].values() if v['absence'] is None or audit.identity(v['identity']) in refs])


class FullRawLifecycleAuditControls(unittest.TestCase):
    def verify(self,f,p):
        return audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=p,controller=ROOT)

    def native_record(self,f,phase='before'):
        return f.rows[0]['processObservation']['evidence'][phase]['processGraph']['nativeCensus']

    def native_events(self,f,lease_id):
        return [event for event in f.events if event['data'].get('leaseId')==lease_id]

    def test_01_real_parsers_replay_complete_synthetic_native_api_and_journal(self):
        f, p = build_fixture()
        for row_value in f.rows:
            derived = guard.validate_observation(p, row_value['processObservation'], lifecycle_journal=f.raw)
            self.assertEqual(derived['status'], 'PASS', derived['blockers'])
        result = audit.verify_lifecycle(f.raw, f.rows, source_commit=Q, policy_sha256=P, policy=p, controller=ROOT)
        self.assertEqual(result['finiteWaitZero'], 5)
        self.assertTrue(result['cleanupAccepted'])

    def test_02_raw_native_corruption_is_rejected_without_mock_validator(self):
        f, p = build_fixture()
        raw = f.rows[0]['processObservation']['evidence']['before']['processGraph']['nativeCensus']
        raw['stdoutSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'raw v3 process evidence adverse'):
            audit.verify_lifecycle(f.raw, f.rows, source_commit=Q, policy_sha256=P, policy=p, controller=ROOT)

    def test_03_unknown_present_rss_stays_adverse_even_with_exact_parent_wait(self):
        f, p = build_fixture()
        f.rows[0]['processObservation']['evidence']['before']['ownedProcesses'][0]['rssBytes'] = None
        with self.assertRaisesRegex(ValueError, 'raw v3 process evidence adverse'):
            audit.verify_lifecycle(f.raw, f.rows, source_commit=Q, policy_sha256=P, policy=p, controller=ROOT)

    def test_04_empty_api_label_cannot_replace_nonempty_original_body(self):
        f, p = build_fixture()
        f.rows[0]['processObservation']['evidence']['api']['emptyBodyBase64'] = 'eyJtb2RlbHMiOlsieCJdfQ=='
        with self.assertRaisesRegex(ValueError, 'raw v3 process evidence adverse'):
            audit.verify_lifecycle(f.raw, f.rows, source_commit=Q, policy_sha256=P, policy=p, controller=ROOT)

    def test_05_complete_raw_discovered_ancestry_and_unknown_exit_absence(self):
        f,p=ancestry_fixture()
        result=audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=p,controller=ROOT)
        self.assertEqual(result['discoveredOnlyConfirmedAbsentUnknownExit'],1)
        self.assertEqual(result['finiteWaitZero'],5)

    def test_06_coherent_fake_parent_creation_fails_full_native_ancestry_replay(self):
        f,p=ancestry_fixture()
        # Verify the unmodified complete raw baseline first. Then rebind the
        # journal and every view prefix while leaving all original native bytes.
        audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=p,controller=ROOT)
        next(e for e in f.events if e['event']=='DISCOVER')['data']['ancestry'][1]['createTimeMicros']=201000000
        reproject(f)
        with self.assertRaises(ValueError):
            audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=p,controller=ROOT)

    def test_07_native_local_popen_witness_without_managed_binding_is_refused(self):
        f,p=build_fixture();self.verify(f,p)
        self.native_record(f).pop('managedLeaseId')
        # The preserved v2 primitive deliberately still accepts its old local
        # Popen/self witness; v3 requires the additional unified lease binding.
        import mac_process_guard_v2
        mac_process_guard_v2.parse_native_evidence(p,self.native_record(f))
        self.assertNotEqual(guard.validate_observation(p,f.rows[0]['processObservation'],lifecycle_journal=f.raw)['status'],'PASS')
        with self.assertRaises(ValueError):self.verify(f,p)

    def test_08_coherent_native_registration_triplet_omission_is_refused(self):
        f,p=build_fixture();self.verify(f,p)
        lease_id=self.native_record(f)['managedLeaseId']
        f.events=[e for e in f.events if e['data'].get('leaseId')!=lease_id]
        reproject(f)
        with self.assertRaises(ValueError):self.verify(f,p)

    def test_09_coherent_extra_native_argv_is_not_empty_argv(self):
        f,p=build_fixture();self.verify(f,p)
        lease_id=self.native_record(f)['managedLeaseId']
        registered=next(e for e in self.native_events(f,lease_id) if e['event']=='FINITE_REGISTER')
        registered['data']['commandSha256']=hashlib.sha256(audit.canonical([p['nativeHelper']['path'],'--extra'])).hexdigest()
        reproject(f)
        with self.assertRaises(ValueError):self.verify(f,p)

    def test_10_coherent_native_executable_substitution_is_refused(self):
        f,p=build_fixture();self.verify(f,p)
        lease_id=self.native_record(f)['managedLeaseId']
        next(e for e in self.native_events(f,lease_id) if e['event']=='FINITE_REGISTER')['data']['executableSha256']='f'*64
        reproject(f)
        with self.assertRaises(ValueError):self.verify(f,p)

    def test_11_coherent_native_pid_creation_substitution_is_refused(self):
        f,p=build_fixture();self.verify(f,p)
        lease_id=self.native_record(f)['managedLeaseId']
        for event in self.native_events(f,lease_id):
            if 'identity' in event['data']:event['data']['identity']['createTimeMicros']+=1
        reproject(f)
        with self.assertRaises(ValueError):self.verify(f,p)

    def test_12_rebound_native_wait_from_wrong_owner_is_refused_before_projection(self):
        f,p=build_fixture();self.verify(f,p)
        lease_id=self.native_record(f)['managedLeaseId']
        next(e for e in self.native_events(f,lease_id) if e['event']=='WAIT')['writer']=dict(ROOT,parentPid=6)
        f.events.sort(key=lambda e:e['monotonicSeconds']);f.seal(project=False)
        # Invalid wait ownership cannot have a valid producer projection. Preserve
        # the prior claimed projection but rebind actual record prefix hashes,
        # so the rejection reaches event ownership rather than a stale hash.
        lines=f.raw.splitlines(keepends=True)
        for outer in f.rows:
            count=sum(e['monotonicSeconds']<=outer['observationCompletedMonotonic'] for e in f.events)
            prefix=b''.join(lines[:count]);outer['processObservation']['lifecycle'].update(
                journalBytes=len(prefix),journalSha256=hashlib.sha256(prefix).hexdigest(),lastSequence=count)
        with self.assertRaisesRegex(ValueError,'unbound finite terminal wait'):self.verify(f,p)

    def test_13_native_raw_exit_zero_without_actual_wait_is_refused(self):
        f,p=build_fixture();self.verify(f,p)
        lease_id=self.native_record(f)['managedLeaseId']
        f.events=[e for e in f.events if not(e['event']=='WAIT' and e['data'].get('leaseId')==lease_id)]
        reproject(f)
        with self.assertRaises(ValueError):self.verify(f,p)

    def test_14_after_capture_cannot_borrow_before_collector_lease(self):
        f,p=build_fixture();self.verify(f,p)
        self.native_record(f,'after')['managedLeaseId']=self.native_record(f,'before')['managedLeaseId']
        with self.assertRaises(ValueError):self.verify(f,p)

    def test_15_native_source_hash_is_not_repaired_by_valid_wait_and_lease(self):
        f,p=build_fixture();self.verify(f,p)
        self.native_record(f)['sourceSha256Before']='f'*64
        with self.assertRaises(ValueError):self.verify(f,p)

    def test_16_complete_old_native_witness_cannot_escape_by_omitting_all_unified_evidence(self):
        f,p=build_fixture();self.verify(f,p)
        lease_id=self.native_record(f).pop('managedLeaseId')
        f.events=[e for e in f.events if e['data'].get('leaseId')!=lease_id]
        reproject(f)
        import mac_process_guard_v2
        mac_process_guard_v2.parse_native_evidence(p,self.native_record(f))
        self.assertNotEqual(guard.validate_observation(p,f.rows[0]['processObservation'],lifecycle_journal=f.raw)['status'],'PASS')
        with self.assertRaises(ValueError):self.verify(f,p)

    def native_parts(self,f,p):
        obs=f.rows[0]['processObservation']
        state=audit._replay(f.raw[:obs['lifecycle']['journalBytes']],Q,P)
        frame=audit._raw_frames(obs,p)[0]
        return frame,state

    def test_17_independent_native_binding_rejects_coherent_omission_without_guard_precheck(self):
        f,p=build_fixture();frame,state=self.native_parts(f,p)
        lease_id=audit._native_lease(frame,state,ROOT,p)
        self.assertEqual(lease_id,self.native_record(f)['managedLeaseId'])
        f.events=[e for e in f.events if e['data'].get('leaseId')!=lease_id]
        reproject(f);frame,state=self.native_parts(f,p)
        with self.assertRaisesRegex(ValueError,'identity/owner/stage differs'):
            audit._native_lease(frame,state,ROOT,p)

    def test_18_independent_native_binding_rejects_nonempty_argv_without_guard_precheck(self):
        f,p=build_fixture();frame,state=self.native_parts(f,p)
        lease_id=audit._native_lease(frame,state,ROOT,p)
        next(e for e in self.native_events(f,lease_id) if e['event']=='FINITE_REGISTER')['data']['commandSha256']=hashlib.sha256(
            audit.canonical([p['nativeHelper']['path'],''])).hexdigest()
        reproject(f);frame,state=self.native_parts(f,p)
        with self.assertRaisesRegex(ValueError,'frozen empty-argv helper'):
            audit._native_lease(frame,state,ROOT,p)


if __name__ == '__main__':
    unittest.main()
