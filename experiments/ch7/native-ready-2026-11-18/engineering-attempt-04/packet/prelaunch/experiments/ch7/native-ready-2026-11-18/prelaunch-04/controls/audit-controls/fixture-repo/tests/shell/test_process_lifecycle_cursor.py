"""Pure journal/cursor and local-file fault controls; no process is launched."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

candidate = Path(__file__).with_name('process_lifecycle.py')
if candidate.is_file():
    spec = importlib.util.spec_from_file_location('aijade_lifecycle_cursor_candidate', candidate)
    life = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(life)
else:
    REPO = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(REPO / 'experiments/ch7'))
    import process_lifecycle as life

WRITER = dict(pid=20, createTimeMicros=20000000, parentPid=1)
CHILD = dict(pid=30, createTimeMicros=30000000, parentPid=20)
RUN, SOURCE, POLICY = '1' * 32, '2' * 40, '3' * 64
ROOT_LEASE, FINITE, SCOPE_A, SCOPE_B = 'a' * 32, 'b' * 32, 'c' * 32, 'd' * 32


def events():
    rows = []
    def add(name, data, mono):
        item = dict(schema=life.EVENT_SCHEMA, seq=len(rows) + 1, event=name,
                    monotonicSeconds=mono, runId=RUN, writer=copy.deepcopy(WRITER),
                    sourceCommit=SOURCE, policySha256=POLICY, data=data,
                    previousSha256=rows[-1]['sha256'] if rows else life.ZERO)
        item['sha256'] = life.digest(life.canonical(item)); rows.append(item)
    add('CONTROLLER_REGISTER', dict(leaseId=ROOT_LEASE, role='controller', stageId='test',
        identity=copy.deepcopy(WRITER), parentIdentity=None, commandSha256='4' * 64,
        executableSha256='5' * 64, readyMonotonic=.5), 1.)
    add('SCOPE_OPEN', dict(scopeId=SCOPE_A, controllerIdentity=copy.deepcopy(WRITER),
        parentLeaseId=None, stageId='test'), 2.)
    add('FINITE_REGISTER', dict(leaseId=FINITE, role='finite', stageId='dummy-not-executed',
        identity=copy.deepcopy(CHILD), parentIdentity=copy.deepcopy(WRITER),
        commandSha256='6' * 64, executableSha256='7' * 64, readyMonotonic=2.5,
        shimSha256='8' * 64, identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD'), 3.)
    add('RELEASE', dict(leaseId=FINITE), 4.)
    add('WAIT', dict(leaseId=FINITE, identity=copy.deepcopy(CHILD), exitCode=0,
        waitSource='Popen.wait', reapedMonotonic=4.5), 5.)
    add('SCOPE_OPEN', dict(scopeId=SCOPE_B, controllerIdentity=copy.deepcopy(WRITER),
        parentLeaseId=None, stageId='interleaved-test'), 6.)
    add('SCOPE_CLOSE', dict(scopeId=SCOPE_A), 7.)
    add('SCOPE_CLOSE', dict(scopeId=SCOPE_B), 8.)
    return rows


def raw(rows):
    return b''.join(life.canonical(row) + b'\n' for row in rows)


def rehash(rows):
    rows = copy.deepcopy(rows)
    for index, item in enumerate(rows):
        item['seq'] = index + 1
        item['previousSha256'] = rows[index - 1]['sha256'] if index else life.ZERO
        item['sha256'] = life.digest(life.canonical({k: v for k, v in item.items() if k != 'sha256'}))
    return rows


def view(rows, scope=SCOPE_A, references=()):
    body = raw(rows); state = life.replay_journal(body); wanted = set(references)
    selected = [value for value in state['leases'].values()
                if value['absence'] is None or life.identity_key(value['identity']) in wanted]
    return dict(schema=life.VIEW_SCHEMA, runId=RUN,
        journalPath=str(life.BASE / '.runtime/posix/tmp/offline-cursor-journal.jsonl'),
        journalBytes=len(body), journalSha256=life.digest(body), lastSequence=len(rows),
        scopeId=scope, controllerIdentity=copy.deepcopy(WRITER), leases=copy.deepcopy(selected),
        referencedIdentities=[list(value) for value in sorted(wanted)],
        controllers=[value['leaseId'] for value in selected if value['identity'] == WRITER])


class ViewCursorControls(unittest.TestCase):
    def test_cold_default_and_incremental_states_agree_for_every_prefix(self):
        rows = events(); cursor = life.ViewCursor()
        for count in range(2, 9):
            wanted = ((30, 30000000),)
            v = view(rows[:count], references=wanted)
            self.assertEqual(life.validate_view(v, raw(rows), cursor=cursor), life.validate_view(v, raw(rows)))

    def test_replay_receives_only_new_tail_after_initial_prefix(self):
        rows = events(); cursor = life.ViewCursor()
        original = life.replay_journal
        first, later, body = view(rows[:2]), view(rows[:4]), raw(rows)
        with patch.object(life, 'replay_journal', wraps=original) as replay:
            life.validate_view(first, body, cursor=cursor)
            life.validate_view(later, body, cursor=cursor)
            life.validate_view(later, body, cursor=cursor)
        self.assertEqual([call.args[0] for call in replay.call_args_list], [raw(rows[:2]), raw(rows[2:4])])
        s = cursor.statistics()
        self.assertEqual(s['parsedEvents'], 4)
        self.assertEqual(s['hashUpdatedBytes'], len(raw(rows[:4])))
        self.assertEqual(s['calls'], 3)
        self.assertGreater(s['fullPrefixComparedBytes'], 0)

    def test_same_prefix_does_not_cache_a_projection_pass(self):
        rows = events()[:4]; cursor = life.ViewCursor(); v = view(rows)
        life.validate_view(v, raw(rows), cursor=cursor)
        bad = copy.deepcopy(v); bad['leases'] = []
        with self.assertRaisesRegex(ValueError, 'projection'):
            life.validate_view(bad, raw(rows), cursor=cursor)
        self.assertTrue(cursor.poisoned)
        with self.assertRaisesRegex(ValueError, 'poison'):
            life.validate_view(v, raw(rows), cursor=cursor)

    def test_same_length_coherently_rehashed_old_mutation_poisoned(self):
        rows = events(); cursor = life.ViewCursor()
        life.validate_view(view(rows[:2]), raw(rows), cursor=cursor)
        changed = copy.deepcopy(rows); changed[0]['data']['commandSha256'] = '9' * 64
        changed = rehash(changed); self.assertEqual(len(raw(changed[:2])), len(raw(rows[:2])))
        life.validate_view(view(changed[:4]), raw(changed))  # valid independent cold journal
        with self.assertRaisesRegex(ValueError, 'historical prefix'):
            life.validate_view(view(changed[:4]), raw(changed), cursor=cursor)
        self.assertTrue(cursor.poisoned)

    def test_same_scope_prefix_regression_poisoned(self):
        rows = events(); cursor = life.ViewCursor()
        life.validate_view(view(rows[:4]), raw(rows), cursor=cursor)
        with self.assertRaisesRegex(ValueError, 'regressed'):
            life.validate_view(view(rows[:2]), raw(rows), cursor=cursor)

    def test_cross_scope_old_prefix_is_cold_and_cannot_borrow_later_wait(self):
        rows = events(); cursor = life.ViewCursor()
        latest = life.validate_view(view(rows[:6], SCOPE_B), raw(rows), cursor=cursor)
        self.assertEqual(latest['leases'][FINITE]['exitCode'], 0)
        older = life.validate_view(view(rows[:4]), raw(rows), cursor=cursor)
        self.assertIsNone(older['leases'][FINITE]['waitSeq'])
        self.assertIsNone(older['leases'][FINITE]['absence'])
        self.assertEqual(older, life.validate_view(view(rows[:4]), raw(rows)))
        self.assertEqual(cursor.statistics()['latestPrefixBytes'], len(raw(rows[:6])))
        self.assertEqual(cursor.statistics()['coldOldPrefixReplays'], 1)

    def test_cross_scope_frontiers_reject_only_the_regressing_scope(self):
        rows = events(); cursor = life.ViewCursor()
        life.validate_view(view(rows[:6], SCOPE_B), raw(rows), cursor=cursor)
        life.validate_view(view(rows[:4]), raw(rows), cursor=cursor)
        life.validate_view(view(rows[:7]), raw(rows), cursor=cursor)
        life.validate_view(view(rows[:6], SCOPE_B), raw(rows), cursor=cursor)
        self.assertFalse(cursor.poisoned)
        with self.assertRaisesRegex(ValueError, 'regressed'):
            life.validate_view(view(rows[:4]), raw(rows), cursor=cursor)

    def test_old_snapshot_does_not_change_after_wait_or_close(self):
        rows = events(); cursor = life.ViewCursor()
        old = life.validate_view(view(rows[:4]), raw(rows), cursor=cursor); saved = copy.deepcopy(old)
        life.validate_view(view(rows[:8], references=((30, 30000000),)), raw(rows), cursor=cursor)
        self.assertEqual(old, saved)
        self.assertIsNone(old['leases'][FINITE]['waitSeq'])
        self.assertIsNone(old['scopes'][SCOPE_A]['closeSeq'])

    def test_caller_mutation_never_reaches_cached_state_or_later_snapshot(self):
        rows = events(); cursor = life.ViewCursor(); v = view(rows[:4])
        first = life.validate_view(v, raw(rows), cursor=cursor)
        first['leases'][FINITE]['identity']['pid'] = 999
        first['events'][0]['data']['identity']['pid'] = 998
        first['scopes'][SCOPE_A]['closeSeq'] = 997
        self.assertEqual(life.validate_view(v, raw(rows), cursor=cursor), life.validate_view(v, raw(rows)))

    def test_partial_tail_failure_is_permanent_and_old_snapshot_safe(self):
        rows = events(); cursor = life.ViewCursor()
        old = life.validate_view(view(rows[:2]), raw(rows), cursor=cursor); saved = copy.deepcopy(old)
        broken = copy.deepcopy(rows[:5]); broken[-1]['data']['identity']['createTimeMicros'] += 1
        broken = rehash(broken); v = view(rows[:5]); v.update(journalBytes=len(raw(broken)), journalSha256=life.digest(raw(broken)))
        with self.assertRaises(ValueError): life.validate_view(v, raw(broken), cursor=cursor)
        self.assertEqual(old, saved)
        with self.assertRaisesRegex(ValueError, 'poison'):
            life.validate_view(view(rows[:5]), raw(rows), cursor=cursor)

    def test_partial_record_refuses_and_cannot_be_repaired_in_same_cursor(self):
        rows = events(); cursor = life.ViewCursor(); base = raw(rows[:2])
        life.validate_view(view(rows[:2]), base, cursor=cursor)
        bad = base + b'{partial'; v = view(rows[:2]); v.update(journalBytes=len(bad), journalSha256=life.digest(bad))
        with self.assertRaisesRegex(ValueError, 'truncated'):
            life.validate_view(v, bad, cursor=cursor)
        with self.assertRaisesRegex(ValueError, 'poison'):
            life.validate_view(view(rows[:4]), raw(rows), cursor=cursor)

    def test_declared_digest_change_is_not_a_cache_hit(self):
        rows = events()[:2]; cursor = life.ViewCursor(); v = view(rows)
        life.validate_view(v, raw(rows), cursor=cursor); v['journalSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'prefix differs'):
            life.validate_view(v, raw(rows), cursor=cursor)

    def test_unknown_scope_does_not_grow_a_frontier(self):
        rows = events()[:2]; cursor = life.ViewCursor(); v = view(rows)
        life.validate_view(v, raw(rows), cursor=cursor); v['scopeId'] = 'f' * 32
        with self.assertRaises(KeyError): life.validate_view(v, raw(rows), cursor=cursor)
        self.assertEqual(cursor.statistics()['frontierScopes'], 1)

    def test_invalid_cursor_object_is_not_a_cached_verdict(self):
        rows = events()[:2]
        with self.assertRaisesRegex(ValueError, 'actual lifecycle ViewCursor'):
            life.validate_view(view(rows), raw(rows), cursor={'status': 'PASS'})

    def test_explicit_bytes_bind_logical_path_even_when_bodies_are_identical(self):
        rows = events()[:2]; cursor = life.ViewCursor(); first = view(rows)
        life.validate_view(first, raw(rows), cursor=cursor)
        other = copy.deepcopy(first); other['journalPath'] += '.other-logical-session'
        self.assertEqual(life.validate_view(other, raw(rows)), life.validate_view(first, raw(rows)))
        with self.assertRaisesRegex(ValueError, 'journal replaced'):
            life.validate_view(other, raw(rows), cursor=cursor)
        self.assertTrue(cursor.poisoned)

    def test_archive_bytes_do_not_require_original_logical_path_to_exist(self):
        rows = events()[:2]; v = view(rows)
        v['journalPath'] = str(Path(tempfile.gettempdir()) / 'not-created-lifecycle-logical-root' / 'missing.jsonl')
        with patch.object(life, 'read_journal', side_effect=AssertionError('archive bytes must not read a missing path')):
            self.assertEqual(life.validate_view(v, raw(rows), cursor=life.ViewCursor()),
                             life.validate_view(v, raw(rows)))

    def test_statistics_are_typed_detached_json_not_acceptance(self):
        cursor = life.ViewCursor(); rows = events()[:2]
        life.validate_view(view(rows), raw(rows), cursor=cursor); stats = cursor.statistics()
        json.dumps(stats, allow_nan=False)
        self.assertTrue(all(type(v) is int for k, v in stats.items() if k != 'poisoned'))
        self.assertIs(stats['poisoned'], False); stats['calls'] = -999
        self.assertEqual(cursor.statistics()['calls'], 1)


class ProducerAndFileCursorControls(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='lifecycle-prefix-unit-')
        self.root = Path(self.scratch.name)
        self.patch_base = patch.object(life, 'BASE', self.root); self.patch_base.start()
        self.path = self.root / 'journal.jsonl'; self.path.write_bytes(raw(events()[:2])); self.path.chmod(0o600)

    def tearDown(self):
        self.patch_base.stop(); self.scratch.cleanup()

    def registry(self):
        # Only journal methods are exercised. No identity lookup, Popen, shim,
        # observation or service is touched by this deliberately unstarted owner.
        value = object.__new__(life.Registry)
        value.path = self.path; value._mutex = threading.RLock()
        value._cached_raw = b''; value._cached_state = None; value._cached_inode = None
        value._cached_hasher = hashlib.sha256(); value._cache_poison_reason = None
        value.run_id = RUN; value.writer = copy.deepcopy(WRITER)
        value.source_commit = SOURCE; value.policy_sha256 = POLICY
        return value

    def test_producer_full_read_and_incremental_hash_agree_with_cold(self):
        value = self.registry(); rows = events()
        self.assertEqual(value._state(), life.replay_journal(raw(rows[:2])))
        self.path.write_bytes(raw(rows[:4]))
        self.assertEqual(value._state(), life.replay_journal(raw(rows[:4])))
        self.assertEqual(value._cached_hasher.hexdigest(), life.digest(self.path.read_bytes()))

    def test_producer_replay_only_receives_new_events_after_full_byte_check(self):
        value = self.registry(); value._state(); rows = events()
        original = life.replay_journal
        self.path.write_bytes(raw(rows[:4]))
        with patch.object(life, 'replay_journal', wraps=original) as replay:
            value._state(); value._state()
        self.assertEqual([call.args[0] for call in replay.call_args_list], [raw(rows[2:4])])

    def test_producer_old_mutation_followed_by_valid_tail_permanently_poisoned(self):
        value = self.registry(); value._state(); changed = events(); changed[0]['data']['commandSha256'] = '9' * 64
        self.path.write_bytes(raw(rehash(changed[:4])))
        with self.assertRaisesRegex(ValueError, 'prefix changed'): value._state()
        self.path.write_bytes(raw(events()[:4]))
        with self.assertRaisesRegex(ValueError, 'poison'): value._state()

    def test_producer_truncate_failure_cannot_be_reset_by_private_raw_clear(self):
        value = self.registry(); value._state(); self.path.write_bytes(b'')
        with self.assertRaises(ValueError): value._state()
        value._cached_raw = b''; value._cached_state = None; value._cached_inode = None
        self.path.write_bytes(raw(events()[:2]))
        with self.assertRaisesRegex(ValueError, 'poison'): value._state()

    def test_producer_partial_semantic_tail_failure_cannot_resume(self):
        value = self.registry(); value._state()
        changed = events()[:5]; changed[-1]['data']['identity']['createTimeMicros'] += 1
        self.path.write_bytes(raw(rehash(changed)))
        with self.assertRaises(ValueError): value._state()
        self.path.write_bytes(raw(events()[:5]))
        with self.assertRaisesRegex(ValueError, 'poison'): value._state()
        self.assertTrue(value.cache_poisoned)

    def test_producer_replacement_same_bytes_is_still_adverse(self):
        value = self.registry(); value._state(); replacement = self.root / 'replacement.jsonl'
        replacement.write_bytes(self.path.read_bytes()); replacement.chmod(0o600); os.replace(replacement, self.path)
        with self.assertRaisesRegex(ValueError, 'replaced'): value._state()
        self.assertTrue(value.cache_poisoned)

    def test_partial_append_poisoned_even_if_disk_is_later_repaired(self):
        value = self.registry(); value._state(); original = self.path.read_bytes(); real_write = life.os.write
        with patch.object(life.os, 'write', side_effect=lambda fd, body: real_write(fd, body[:-1])):
            with self.assertRaisesRegex(ValueError, 'partial lifecycle append'):
                value._append('SCOPE_CLOSE', dict(scopeId=SCOPE_A))
        self.path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'poison'): value._state()

    def test_fsync_failure_poisoned_even_when_full_event_reached_disk(self):
        value = self.registry(); value._state()
        with patch.object(life.os, 'fsync', side_effect=OSError('controlled sync failure')):
            with self.assertRaisesRegex(OSError, 'controlled sync failure'):
                value._append('SCOPE_CLOSE', dict(scopeId=SCOPE_A))
        self.assertEqual(life.replay_journal(self.path.read_bytes())['scopes'][SCOPE_A]['closeSeq'], 3)
        with self.assertRaisesRegex(ValueError, 'poison'): value._state()

    def test_append_full_digest_matches_cold_without_rehashing_old_prefix(self):
        value = self.registry(); value._state(); before = self.path.read_bytes()
        value._append('SCOPE_CLOSE', dict(scopeId=SCOPE_A))
        after = self.path.read_bytes(); self.assertTrue(after.startswith(before))
        self.assertEqual(value._state(), life.replay_journal(after))
        self.assertEqual(value._cached_hasher.hexdigest(), life.digest(after))

    def test_file_cursor_detects_atomic_replacement_and_stays_poisoned(self):
        cursor = life.ViewCursor(); v = view(events()[:2]); v['journalPath'] = str(self.path)
        life.validate_view(v, cursor=cursor)
        other = self.root / 'other'; other.write_bytes(self.path.read_bytes()); other.chmod(0o600)
        os.replace(other, self.path)
        with self.assertRaisesRegex(ValueError, 'replaced'): life.validate_view(v, cursor=cursor)
        with self.assertRaisesRegex(ValueError, 'poison'): life.validate_view(v, cursor=cursor)

    def test_file_cursor_reads_actual_old_bytes_instead_of_stat_only(self):
        cursor = life.ViewCursor(); v = view(events()[:2]); v['journalPath'] = str(self.path)
        life.validate_view(v, cursor=cursor); info = self.path.stat()
        changed = events()[:2]; changed[0]['data']['commandSha256'] = '9' * 64
        self.path.write_bytes(raw(rehash(changed))); os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'historical prefix'): life.validate_view(v, cursor=cursor)


if __name__ == '__main__':
    unittest.main()
