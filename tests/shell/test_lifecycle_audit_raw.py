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
    f.seal()
    return f, p


def ancestry_fixture():
    f,p=build_fixture()
    descendant=dict(pid=250,createTimeMicros=250000000,parentPid=200)
    live=f.rows[0]['processObservation']
    for phase_index,phase in enumerate(['before','after']):
        data=native([row(5,1),row(200,100),row(250,200)],collector_pid=500+phase_index,parent=100)
        next(n for n in data['records'] if n['pid']==100)['parentPid']=5
        live['evidence'][phase]['processGraph']=graph(p,data)
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
    def test_01_real_parsers_replay_complete_synthetic_native_api_and_journal(self):
        f, p = build_fixture()
        for row_value in f.rows:
            derived = guard.validate_observation(p, row_value['processObservation'], lifecycle_journal=f.raw)
            self.assertEqual(derived['status'], 'PASS', derived['blockers'])
        result = audit.verify_lifecycle(f.raw, f.rows, source_commit=Q, policy_sha256=P, policy=p, controller=ROOT)
        self.assertEqual(result['finiteWaitZero'], 1)
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
        self.assertEqual(result['finiteWaitZero'],1)

    def test_06_coherent_fake_parent_creation_fails_full_native_ancestry_replay(self):
        f,p=ancestry_fixture()
        # Verify the unmodified complete raw baseline first. Then rebind the
        # journal and every view prefix while leaving all original native bytes.
        audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=p,controller=ROOT)
        next(e for e in f.events if e['event']=='DISCOVER')['data']['ancestry'][1]['createTimeMicros']=201000000
        reproject(f)
        with self.assertRaises(ValueError):
            audit.verify_lifecycle(f.raw,f.rows,source_commit=Q,policy_sha256=P,policy=p,controller=ROOT)


if __name__ == '__main__':
    unittest.main()
