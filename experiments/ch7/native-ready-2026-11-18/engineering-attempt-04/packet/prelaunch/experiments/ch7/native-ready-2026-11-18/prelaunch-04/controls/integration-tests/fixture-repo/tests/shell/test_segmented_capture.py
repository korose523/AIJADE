"""Offline raw-evidence and real-thread/fake-reader coordination controls.

No census, daemon, listener, model, renderer or business subprocess is invoked.
The real-thread controls use actual local flock exclusion with fake readers;
they are not a live nested-load or scientific qualification.
"""
import copy
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'experiments/ch7'))
import process_lifecycle as life
import mac_process_guard_v3 as guard
from test_mac_lifecycle_guard import fixture, journal_events, rehash


def segmented_fixture(**kwargs):
    p, o, raw = fixture(**kwargs)
    p.update(coordinationMode=guard.SEGMENTED_MODE, coordinationSchema=guard.SEGMENTED_SCHEMA)
    o['policyCanonicalSha256'] = guard.canonical_sha256(p)
    original = o.pop('coordinationLock')
    o.update(coordinationMode=guard.SEGMENTED_MODE, coordinationSchema=guard.SEGMENTED_SCHEMA,
             coordinationLocks={}, segmentedApiClock=dict(startedMonotonic=100.3, finishedMonotonic=100.31))
    for phase, base in [('before', 100.), ('after', 100.6)]:
        lock = copy.deepcopy(original)
        lock.update(nested=False, requestStartedMonotonic=base+.075,
                    acquiredMonotonic=base+.08, releasedMonotonic=base+.2)
        o['coordinationLocks'][phase] = lock
        frame = o['evidence'][phase]
        frame.update(daemonIdentityReadClock=dict(startedMonotonic=base+.01, finishedMonotonic=base+.07),
            ownedRssReadClock=dict(startedMonotonic=base+.12, finishedMonotonic=base+.13),
            listenerReadClock=dict(startedMonotonic=base+.14, finishedMonotonic=base+.19))
    # Existing API fixture duration is a declared .01 s; the actual envelope is
    # slightly wider so floating point representation cannot invert containment.
    o['segmentedApiClock']['finishedMonotonic'] = 100.32
    return p, o, raw


class SegmentedEvidenceControls(unittest.TestCase):
    def decision(self, p, o, raw, **options):
        return guard.validate_observation(p, o, lifecycle_journal=raw, **options)

    def assert_refused(self, p, o, raw, code=None):
        result = self.decision(p, o, raw)
        self.assertNotEqual(result['status'], 'PASS', result)
        if code:
            self.assertIn(code, [row['code'] for row in result['blockers']], result)

    def test_legacy_complete_evidence_still_passes_unchanged(self):
        p, o, raw = fixture()
        self.assertEqual(self.decision(p, o, raw)['status'], 'PASS')
        self.assertNotIn('coordinationMode', p)
        self.assertNotIn('coordinationLocks', o)

    def test_segmented_complete_evidence_passes_independent_cold_replay(self):
        p, o, raw = segmented_fixture()
        result = self.decision(p, o, raw)
        self.assertEqual(result['status'], 'PASS', result)
        self.assertEqual(result['ownedRssBytes'], 4001000)

    def test_legal_task_reaped_between_actual_native_frames_still_passes(self):
        p, o, raw = segmented_fixture(finite=True)
        result = self.decision(p, o, raw)
        self.assertEqual(result['status'], 'PASS', result)
        state = life.replay_journal(raw)
        self.assertEqual(state['leases']['6'*32]['absenceWitnessKind'], 'PARENT_WAIT_REAPED')

    def test_missing_actual_wait_is_not_repaired_by_segmented_mode(self):
        p, o, raw = segmented_fixture(finite=True, wait=False)
        self.assert_refused(p, o, raw, 'ABSENT_EXIT_STATUS_UNKNOWN')

    def test_actual_launch_and_zero_wait_entirely_between_native_frames_is_valid(self):
        events = journal_events(finite=True)
        events[2]['monotonicSeconds'] = 100.35
        events[2]['data']['readyMonotonic'] = 100.34
        events[3]['monotonicSeconds'] = 100.36
        p, o, raw = segmented_fixture(events=rehash(events))
        result = self.decision(p, o, raw)
        self.assertEqual(result['status'], 'PASS', result)
        self.assertFalse(any(node['pid'] == 30 for phase in ('before','after')
                             for node in o['evidence'][phase]['processGraph']['nodes']))
        lease = life.replay_journal(raw)['leases']['6'*32]
        self.assertGreater(lease['registerMonotonic'], o['evidence']['before']['graphCompletedMonotonic'])
        self.assertLess(lease['reapedMonotonic'], o['evidence']['after']['graphStartedMonotonic'])

    def test_exact_mode_and_coordination_schema_are_mandatory(self):
        for key, value in [('coordinationMode', None), ('coordinationMode', 'whole-observation'),
                           ('coordinationSchema', None), ('coordinationSchema', 'v2-unapproved')]:
            with self.subTest(key=key, value=value):
                p, o, raw = segmented_fixture()
                o[key] = value
                self.assert_refused(p, o, raw, 'SEGMENTED_COORDINATION_SCHEMA_OR_MODE_MISMATCH')

    def test_legacy_policy_cannot_reinterpret_segmented_raw_record(self):
        p, o, raw = segmented_fixture()
        p.pop('coordinationMode'); p.pop('coordinationSchema')
        o['policyCanonicalSha256'] = guard.canonical_sha256(p)
        # Even restoring a plausible whole lock cannot hide the raw new mode.
        o['coordinationLock'] = copy.deepcopy(o['coordinationLocks']['before'])
        self.assert_refused(p, o, raw, 'LEGACY_COORDINATION_MODE_SUBSTITUTION')

    def test_segmented_policy_rejects_legacy_raw_or_fabricated_whole_lock(self):
        p, o, raw = fixture()
        p.update(coordinationMode=guard.SEGMENTED_MODE, coordinationSchema=guard.SEGMENTED_SCHEMA)
        o['policyCanonicalSha256'] = guard.canonical_sha256(p)
        self.assert_refused(p, o, raw, 'SEGMENTED_COORDINATION_SCHEMA_OR_MODE_MISMATCH')
        p, o, raw = segmented_fixture()
        o['coordinationLock'] = copy.deepcopy(o['coordinationLocks']['before'])
        self.assert_refused(p, o, raw, 'SEGMENTED_COORDINATION_SCHEMA_OR_MODE_MISMATCH')

    def test_policy_unknown_or_mixed_mode_schema_refuses(self):
        for change in ({'coordinationMode':'new-unreviewed'}, {'coordinationSchema':'v2'},
                       {'coordinationMode':None, 'coordinationSchema':guard.SEGMENTED_SCHEMA}):
            p, o, raw = segmented_fixture(); p.update(change)
            with self.assertRaises(ValueError):
                guard.validate_policy(p)

    def test_phase_population_replaced_lock_and_nested_alias_refuse(self):
        for kind in ('missing', 'extra', 'inode', 'nested', 'state', 'path'):
            with self.subTest(kind=kind):
                p, o, raw = segmented_fixture()
                if kind == 'missing': o['coordinationLocks'].pop('after')
                if kind == 'extra': o['coordinationLocks']['cached'] = copy.deepcopy(o['coordinationLocks']['before'])
                if kind == 'inode':
                    for key in ('initialIdentity','finalIdentity'):
                        o['coordinationLocks']['after'][key]['inode'] += 1
                if kind == 'nested': o['coordinationLocks']['after']['nested'] = True
                if kind == 'state': o['coordinationLocks']['after']['state'] = 'HELD'
                if kind == 'path': o['coordinationLocks']['after']['pathSha256'] = '0'*64
                self.assert_refused(p, o, raw)

    def test_native_rss_or_listener_work_outside_actual_short_lock_refuses(self):
        for key, subkey in [('graphStartedMonotonic', None), ('ownedRssReadClock','finishedMonotonic'),
                            ('listenerReadClock','finishedMonotonic')]:
            with self.subTest(key=key):
                p, o, raw = segmented_fixture()
                frame = o['evidence']['before']
                if subkey: frame[key][subkey] = 100.21
                else: frame[key] = 100.07
                self.assert_refused(p, o, raw, 'SEGMENTED_SNAPSHOT_OUTSIDE_MUTATION_LOCK')

    def test_daemon_read_must_finish_before_its_own_phase_lock(self):
        p, o, raw = segmented_fixture()
        o['evidence']['before']['daemonIdentityReadClock']['finishedMonotonic'] = 100.09
        self.assert_refused(p, o, raw, 'SEGMENTED_SNAPSHOT_OUTSIDE_MUTATION_LOCK')

    def test_daemon_api_phase_order_cannot_be_retimed(self):
        p, o, raw = segmented_fixture()
        o['evidence']['after']['daemonIdentityReadClock'].update(startedMonotonic=100.25, finishedMonotonic=100.27)
        self.assert_refused(p, o, raw, 'SEGMENTED_BEFORE_API_AFTER_ORDER_MISMATCH')

    def test_original_wait_hold_and_whole_capture_bounds_refuse(self):
        for change in ('wait', 'hold', 'whole', 'api'):
            with self.subTest(change=change):
                p, o, raw = segmented_fixture()
                if change == 'wait': o['coordinationLocks']['before']['waitSeconds'] = 1.25001
                if change == 'hold':
                    o['coordinationLocks']['after']['releasedMonotonic'] = 102.
                    o['finishedMonotonic'] = 102.1
                if change == 'whole': o['finishedMonotonic'] = 102.50001
                if change == 'api': o['segmentedApiClock']['finishedMonotonic'] = 100.9
                self.assert_refused(p, o, raw)

    def test_actual_request_clock_cannot_be_omitted_or_hidden_by_claimed_wait(self):
        for kind in ('missing', 'early', 'late', 'unbounded'):
            with self.subTest(kind=kind):
                p, o, raw = segmented_fixture()
                lock = o['coordinationLocks']['after']
                if kind == 'missing': lock.pop('requestStartedMonotonic')
                if kind == 'early': lock['requestStartedMonotonic'] = 100.6
                if kind == 'late': lock['requestStartedMonotonic'] = 100.69
                if kind == 'unbounded':
                    lock['requestStartedMonotonic'] = 100.1
                    lock['acquiredMonotonic'] = 101.4
                    lock['releasedMonotonic'] = 101.5
                    lock['waitSeconds'] = .001
                    o['finishedMonotonic'] = 102.
                self.assert_refused(p, o, raw)

    def test_same_prefix_view_mutation_is_not_cached_pass(self):
        p, o, raw = segmented_fixture(); cursor = life.ViewCursor()
        self.assertEqual(self.decision(p, o, raw, lifecycle_cursor=cursor)['status'], 'PASS')
        o['lifecycle']['leases'] = []
        self.assertNotEqual(self.decision(p, o, raw, lifecycle_cursor=cursor)['status'], 'PASS')
        self.assertTrue(cursor.poisoned)

    def test_older_scope_prefix_cannot_replace_latest_validated_view(self):
        p, o, raw = segmented_fixture(); cursor = life.ViewCursor()
        self.assertEqual(self.decision(p, o, raw, lifecycle_cursor=cursor)['status'], 'PASS')
        prior = b''.join(raw.splitlines(keepends=True)[:2])
        old = life.replay_journal(prior)
        o['lifecycle'].update(journalBytes=len(prior), journalSha256=life.digest(prior),
            lastSequence=2, leases=list(old['leases'].values()))
        self.assertNotEqual(self.decision(p, o, raw, lifecycle_cursor=cursor)['status'], 'PASS')
        self.assertTrue(cursor.poisoned)

    def test_unknown_rss_listener_api_and_nonzero_wait_remain_adverse(self):
        for kind in ('rss','listener','api','wait'):
            with self.subTest(kind=kind):
                p, o, raw = segmented_fixture(finite=(kind == 'wait'), exit_code=-15 if kind == 'wait' else 0)
                if kind == 'rss': o['evidence']['after']['ownedProcesses'][0]['rssBytes'] = None
                if kind == 'listener': o['evidence']['before']['listener']['records'] = []
                if kind == 'api': o['evidence']['api']['modelCount'] = True
                self.assert_refused(p, o, raw)


class FakeRegistry(life.Registry):
    def __init__(self, lock):
        self.lock_path = lock; self.policy_sha256 = '3'*64
        self.sample_calls = 0; self.remember_calls = 0

    def bind_policy(self, policy): self.bound = policy

    def sample(self, refs=()):
        if str(self.lock_path) in getattr(life._locks, 'active', {}):
            raise AssertionError('large lifecycle view copied under mutation lock')
        self.sample_calls += 1
        return {'offlineFake':True}

    def remember(self, record):
        if str(self.lock_path) in getattr(life._locks, 'active', {}):
            raise AssertionError('postprocessing under mutation lock')
        self.remember_calls += 1


@unittest.skipUnless(sys.platform == 'darwin', 'actual project APFS/flock fake-reader control')
class RealThreadFakeReaderControls(unittest.TestCase):
    def test_two_scope_readers_and_finite_dispatch_share_only_short_actual_sections(self):
        scratch = life.POSIX/'tmp'; scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='segmented-capture-control-', dir=scratch) as directory:
            lock = Path(directory)/'capture.lock'
            p, _, _ = segmented_fixture()
            started = threading.Barrier(3)
            reading = threading.Barrier(3)
            release_readers = threading.Event()
            outcomes = []; errors = []; active = 0; maximum_active = 0; identity_calls = []
            counter_lock = threading.Lock()

            def held(): return str(lock) in getattr(life._locks, 'active', {})
            def identity(pid, **unused):
                self.assertFalse(held(), 'complete daemon read must not block finite dispatch')
                first = not getattr(threading.current_thread(), 'entered_fake_daemon_read', False)
                identity_calls.append(pid)
                if first:
                    threading.current_thread().entered_fake_daemon_read = True
                    reading.wait(timeout=2)
                    self.assertTrue(release_readers.wait(timeout=2))
                expected = next(copy.deepcopy(row) for row in p['daemon'].values() if row['pid'] == pid)
                expected.pop('executablePathSha256', None)
                return expected
            def graph(policy, registry):
                nonlocal active, maximum_active
                self.assertTrue(held(), 'native graph was read outside real exclusion')
                with counter_lock: active += 1; maximum_active = max(maximum_active, active)
                time.sleep(.004)
                with counter_lock: active -= 1
                return {'schema':'aijade.mac.bulk-process-graph.v2','nodes':[],'errors':[],'nativeCensus':{}}
            def listeners(registry):
                self.assertTrue(held(), 'listener was read outside real exclusion')
                time.sleep(.002)
                return {'state':'OBSERVED','records':[]}
            def api(config):
                self.assertFalse(held(), 'API must not extend the mutation critical section')
                return {'state':'EMPTY','durationSeconds':0.0}
            def timing_only(policy, observation, **unused):
                blockers = []
                def add(code, severity='UNKNOWN', **fields): blockers.append(dict(code=code,severity=severity,**fields))
                guard._validate_segmented_coordination(policy, observation,
                    observation['startedMonotonic'], observation['finishedMonotonic'], add)
                if blockers: raise AssertionError(blockers)
                return dict(status='PASS',blockers=[],ownedRssBytes=0)
            def run_reader():
                try:
                    registry = FakeRegistry(lock); started.wait(timeout=2)
                    result = guard.observe(p, lifecycle=registry)
                    outcomes.append((result,registry))
                except BaseException as error: errors.append(error)
            with patch.object(guard,'validate_policy'), patch.object(guard,'coordination_lock_path',return_value=lock), \
                    patch.object(guard,'_read_identity',side_effect=identity), \
                    patch.object(guard,'_read_processes',side_effect=graph), \
                    patch.object(guard,'parse_native_evidence',return_value=([],None)), \
                    patch.object(guard,'_read_listeners',side_effect=listeners), \
                    patch.object(guard,'_read_api',side_effect=api), \
                    patch.object(guard,'validate_observation',side_effect=timing_only):
                threads = [threading.Thread(target=run_reader) for _ in range(2)]
                for thread in threads: thread.start()
                started.wait(timeout=2); reading.wait(timeout=2)
                # Both actual reader threads are inside unfinished fake full
                # daemon reads. Dispatch must obtain the actual flock before
                # allowing either read to finish; no flaky speed threshold.
                try:
                    with life.capture_lock(lock):
                        self.assertFalse(release_readers.is_set())
                        release_readers.set()
                finally:
                    release_readers.set()
                for thread in threads: thread.join(timeout=3); self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(outcomes), 2)
            self.assertEqual(maximum_active, 1)
            self.assertEqual(len(identity_calls), 8)  # four complete fake reads per scope, no shared cached PASS
            for result, registry in outcomes:
                self.assertEqual(result['status'], 'PASS', result)
                self.assertEqual(registry.sample_calls, 2)
                self.assertEqual(registry.remember_calls, 1)
                self.assertEqual(set(result['coordinationLocks']), {'before','after'})
                self.assertNotIn('coordinationLock', result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
