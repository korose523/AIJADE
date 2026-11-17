"""Offline ownership/mutation/replay controls; no OS observation or subprocess."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import marshal
import sys
import time
import unittest
from unittest.mock import patch

C=Path(__file__).resolve().parent
P=C/'candidate/experiments/ch7'
W=Path('/Volumes/Untitled/AIJADE/.runtime/posix/nested-20261117/worktree')
sys.path.insert(0,str(P))
import process_lifecycle as life
import newowned_guard_cursor as owned
import mac_process_guard_v3 as guard
import full_state_clone_cursor as legacy
spec=importlib.util.spec_from_file_location('owned_test_journal_fixtures',W/'tests/shell/test_process_lifecycle_cursor.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


def typed(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return set(a)==set(b) and all(typed(a[k],b[k]) for k in a)
    if type(a) in (list,tuple):return len(a)==len(b) and all(typed(x,y) for x,y in zip(a,b))
    return a==b


def mutable_ids(value,seen=None):
    if seen is None:seen=set()
    result=set()
    if type(value) not in (dict,list,tuple) or id(value) in seen:return result
    seen.add(id(value))
    if type(value) in (dict,list):result.add(id(value))
    for item in (value.values() if type(value) is dict else value):result|=mutable_ids(item,seen)
    return result


def pair(rows=None):
    rows=fixture.events()[:4] if rows is None else rows
    v=fixture.view(rows)
    first,second,record=owned.bootstrap_pair(v,fixture.raw(rows))
    now=time.monotonic()
    writer=dict(path=str(C/'FIXTURE-ONLY/initialization.json'),sha256='f'*64,
                startedMonotonic=now,completedMonotonic=now+.0001)
    first.bind_preparation(record,writer);second.bind_preparation(record,writer)
    return first,second,record,v,fixture.raw(rows)


def policy():
    path=Path('/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-nested-copy-20261118/engineering-02/process-policy.json')
    result=json.loads(path.read_bytes())
    result.update(onlineReplayMode=owned.MODE,onlineReplayInitializationMode=owned.INITIALIZATION_MODE,
                  onlineReplaySourceSha256=hashlib.sha256((P/'newowned_guard_cursor.py').read_bytes()).hexdigest())
    result.pop('binaryAuthenticationMode',None);result.pop('binaryAuthenticationSourceSha256',None)
    return result


def minimal(first,v):
    return dict(lifecycle=copy.deepcopy(v),onlineReplayMode=owned.MODE,
        onlineReplayInitializationMode=owned.INITIALIZATION_MODE,
        onlineReplaySourceSha256=hashlib.sha256((P/'newowned_guard_cursor.py').read_bytes()).hexdigest(),
        onlineReplayPreparation=first.preparation_reference())


class OwnedGuardControls(unittest.TestCase):
    def test_actual_bootstrap_is_one_parse_one_clone_and_independent_private_owners(self):
        with patch.object(owned,'replay_journal',wraps=life.replay_journal) as replay, patch.object(
                owned,'_clone_private_state',wraps=owned._clone_private_state) as clone:
            a,b,r,v,raw=pair()
        self.assertEqual(replay.call_count,1);self.assertEqual(clone.call_count,1)
        self.assertEqual(r['canonicalParserRuns'],1);self.assertEqual(r['detachedCacheCloneOperations'],1)
        self.assertEqual(a.statistics()['initializationStateClones'],0)
        self.assertEqual(b.statistics()['initializationStateClones'],1)
        self.assertNotEqual(r['innerOwner']['ownerId'],r['outerOwner']['ownerId'])
        self.assertTrue(mutable_ids(a._OwnedGuardCursor__state).isdisjoint(mutable_ids(b._OwnedGuardCursor__state)))
        self.assertIsNot(a._OwnedGuardCursor__hasher,b._OwnedGuardCursor__hasher)
        self.assertTrue(mutable_ids(a._OwnedGuardCursor__frontiers).isdisjoint(mutable_ids(b._OwnedGuardCursor__frontiers)))
        self.assertIs(r['verdictGranted'],False)

    def test_no_public_complete_state_or_arbitrary_predicate_api(self):
        a,*_=pair()
        self.assertFalse(hasattr(a,'validate_view'))
        with self.assertRaises(TypeError):a.evaluate({}, {}, state={})
        with self.assertRaises(TypeError):a.evaluate({}, {}, predicate=lambda *_:{})

    def test_same_prefix_still_revalidates_and_executes_complete_predicate(self):
        a,b,_,v,raw=pair();p=policy();obs=minimal(a,v)
        expected=guard.validate_observation(p,obs,raw)
        before=a.statistics()
        first=a.evaluate(p,obs,raw);second=a.evaluate(p,obs,raw)
        self.assertTrue(typed(first,expected));self.assertTrue(typed(second,expected))
        after=a.statistics()
        self.assertEqual(after['guardEvaluations']-before['guardEvaluations'],2)
        self.assertEqual(after['fullPrefixReadBytes']-before['fullPrefixReadBytes'],2*len(raw))
        self.assertEqual(after['fullPrefixComparedBytes']-before['fullPrefixComparedBytes'],2*len(raw))
        self.assertEqual(after['snapshotCopies'],0)
        self.assertEqual(after['detachedDecisionCopies'],2)
        self.assertEqual(after['detachedDecisionCanonicalBytes'],2*len(life.canonical(expected)))
        self.assertNotIn('detachedDecisionBytes',after)
        self.assertEqual(b.statistics()['guardEvaluations'],0)

    def test_detached_decision_mutation_never_changes_input_private_state_or_other_owner(self):
        a,b,_,v,raw=pair();p=policy();obs=minimal(a,v);saved=copy.deepcopy(obs)
        first=a.evaluate(p,obs,raw);first['blockers'].append(dict(code='caller',severity='FAIL'))
        second=a.evaluate(p,obs,raw);third=b.evaluate(p,obs,raw)
        self.assertEqual(obs,saved);self.assertTrue(typed(second,third))
        self.assertFalse(any(x['code']=='caller' for x in second['blockers']))
        self.assertTrue(mutable_ids(first).isdisjoint(mutable_ids(a._OwnedGuardCursor__state)))
        self.assertTrue(mutable_ids(second).isdisjoint(mutable_ids(obs)))

    def test_new_tail_is_validated_independently_for_each_owner(self):
        a,b,_,v,raw=pair();rows=fixture.events();later=fixture.view(rows)
        p=policy();obs=minimal(a,later)
        with patch.object(owned,'replay_journal',wraps=life.replay_journal) as replay:
            first=a.evaluate(p,obs,fixture.raw(rows));second=b.evaluate(p,obs,fixture.raw(rows))
        self.assertEqual([call.args[0] for call in replay.call_args_list],[fixture.raw(rows[4:]),fixture.raw(rows[4:])])
        self.assertTrue(typed(first,second))
        self.assertEqual(a.statistics()['retainedEvents'],8);self.assertEqual(b.statistics()['retainedEvents'],8)

    def test_same_length_coherent_historical_mutation_poisons(self):
        a,b,_,v,raw=pair();rows=fixture.events()[:4];rows[0]['data']['commandSha256']='9'*64
        rows=fixture.rehash(rows);changed=fixture.view(rows)
        obs=minimal(a,changed)
        with self.assertRaisesRegex(ValueError,'historical prefix'):a.evaluate(policy(),obs,fixture.raw(rows))
        self.assertTrue(a.poisoned);self.assertFalse(b.poisoned)
        with self.assertRaisesRegex(ValueError,'poison'):a.evaluate(policy(),minimal(a,v),raw)

    def test_regression_and_invalid_projection_poison_without_cache_pass(self):
        for variant in ('regress','projection'):
            with self.subTest(variant=variant):
                a,b,_,v,raw=pair();bad=copy.deepcopy(v)
                if variant=='regress':bad=fixture.view(fixture.events()[:2])
                else:bad['leases']=[]
                with self.assertRaises(ValueError):a.evaluate(policy(),minimal(a,bad),raw)
                self.assertTrue(a.poisoned);self.assertFalse(b.poisoned)

    def test_old_interleaved_prefix_cold_replay_cannot_borrow_future_wait(self):
        a,b,_,v,raw=pair();rows=fixture.events()
        latest=a._OwnedGuardCursor__advance(fixture.view(rows,fixture.SCOPE_B),fixture.raw(rows))
        self.assertEqual(latest['leases'][fixture.FINITE]['exitCode'],0)
        older=a._OwnedGuardCursor__advance(v,fixture.raw(rows))
        self.assertIsNone(older['leases'][fixture.FINITE]['waitSeq'])
        self.assertTrue(typed(older,life.validate_view(v,fixture.raw(rows))))
        self.assertEqual(a.statistics()['coldOldPrefixReplays'],1)

    def test_owner_pair_role_scope_and_source_reference_substitutions_refuse(self):
        a,b,_,v,raw=pair();other,_,_,_,_=pair()
        for label,value in [('ownerId','e'*32),('pairedOwnerId','d'*32),('ownerRole','outer'),
                            ('scopeId','f'*32),('sourceCommit','c'*40),('policySha256','b'*64)]:
            with self.subTest(label=label):
                obs=minimal(a,v);obs['onlineReplayPreparation'][label]=value
                with self.assertRaisesRegex(ValueError,'producer/pair'):a.evaluate(policy(),obs,raw)
        obs=minimal(other,v)
        with self.assertRaisesRegex(ValueError,'producer/pair'):b.evaluate(policy(),obs,raw)

    def test_numerically_equal_reference_scalar_type_changes_refuse(self):
        a,b,_,v,raw=pair()
        for field in ('prefixBytes','lastSequence'):
            obs=minimal(a,v);obs['onlineReplayPreparation'][field]=float(obs['onlineReplayPreparation'][field])
            with self.assertRaisesRegex(ValueError,'producer/pair'):a.evaluate(policy(),obs,raw)
        self.assertFalse(owned._typed_equal(1,True));self.assertFalse(owned._typed_equal(1,1.0))
        self.assertFalse(owned._typed_equal([1],(1,)))

    def test_mode_source_initialization_and_runtime_predicate_replacement_refuse(self):
        a,b,_,v,raw=pair();obs=minimal(a,v)
        for field,value in [('onlineReplayMode','incremental-exact-prefix-v1'),
                            ('onlineReplaySourceSha256','0'*64),('onlineReplayInitializationMode','foreign')]:
            with self.subTest(field=field):
                p=policy();p[field]=value
                with self.assertRaises(ValueError):a.evaluate(p,obs,raw)
        with patch.object(guard,'_guard_decision_from_validated_lifecycle',return_value={'status':'PASS'}):
            with self.assertRaisesRegex(ValueError,'replaced'):a.evaluate(policy(),obs,raw)

    def test_legacy_complete_return_cursor_and_parser_bytes_remain_exact(self):
        self.assertEqual(hashlib.sha256((P/'full_state_clone_cursor.py').read_bytes()).hexdigest(),owned.LEGACY_CLONE_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256((P/'process_lifecycle.py').read_bytes()).hexdigest(),owned.PARSER_SOURCE_SHA256)
        rows=fixture.events();v=fixture.view(rows);cursor=legacy.FullStateCloneCursor()
        actual=cursor.validate_view(v,fixture.raw(rows));expected=life.validate_view(v,fixture.raw(rows))
        self.assertTrue(typed(actual,expected));self.assertIn('events',actual)


if __name__=='__main__':unittest.main(verbosity=2)
