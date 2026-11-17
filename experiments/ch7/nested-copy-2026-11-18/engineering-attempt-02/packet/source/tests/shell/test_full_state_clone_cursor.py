"""Pure journal, alias and typed C-clone controls; never an OS observer call."""
from pathlib import Path
import copy
import math
import sys
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
sys.path.insert(0,str(REPO/'tests/shell'))
import process_lifecycle as life
import full_state_clone_cursor as candidate
from test_process_lifecycle_cursor import events, raw, view, rehash, SCOPE_A, SCOPE_B
from cursor_clone_probe_support import typed_equal, assert_mutable_detached


class FullStateCloneControls(unittest.TestCase):
    def test_every_original_prefix_matches_legacy_complete_detached_contract(self):
        rows=events();cursor=candidate.FullStateCloneCursor()
        for count in range(2,9):
            value=view(rows[:count],references=((30,30000000),))
            actual=cursor.validate_view(value,raw(rows))
            expected=life.validate_view(value,raw(rows))
            self.assertTrue(typed_equal(actual,expected))
            self.assertEqual(set(actual),set(expected))
            assert_mutable_detached(cursor._state,actual)

    def test_returned_mutation_preserves_internal_aliases_but_not_cache_aliases(self):
        rows=events()[:5];cursor=candidate.FullStateCloneCursor();v=view(rows,references=((30,30000000),))
        first=cursor.validate_view(v,raw(rows))
        event=next(e for e in first['events'] if e['event']=='FINITE_REGISTER')
        lease=next(v for v in first['leases'].values() if v['role']=='finite')
        self.assertIs(event['data']['identity'],lease['identity'])
        event['data']['identity']['pid']=999
        second=cursor.validate_view(v,raw(rows))
        self.assertEqual(next(v for v in second['leases'].values() if v['role']=='finite')['identity']['pid'],30)
        self.assertTrue(typed_equal(second,life.validate_view(v,raw(rows))))

    def test_new_tail_is_checked_independently_and_old_scope_uses_its_own_prefix(self):
        rows=events();cursor=candidate.FullStateCloneCursor()
        cursor.validate_view(view(rows[:4]),raw(rows))
        cursor.validate_view(view(rows,scope=SCOPE_B),raw(rows))
        older=cursor.validate_view(view(rows[:4]),raw(rows))
        self.assertTrue(typed_equal(older,life.validate_view(view(rows[:4]),raw(rows))))
        stats=cursor.statistics()
        self.assertEqual(stats['parsedEvents'],12)
        self.assertEqual(stats['builtinColdStates'],2)
        self.assertEqual(stats['builtinTailEvents'],4)
        self.assertEqual(stats['coldOldPrefixReplays'],1)

    def test_rehashed_old_mutation_and_scope_regression_poison(self):
        rows=events();cursor=candidate.FullStateCloneCursor()
        cursor.validate_view(view(rows[:4]),raw(rows))
        changed=copy.deepcopy(rows);changed[0]['data']['commandSha256']='9'*64;changed=rehash(changed)
        with self.assertRaisesRegex(ValueError,'historical prefix'):cursor.validate_view(view(changed),raw(changed))
        self.assertTrue(cursor.poisoned)
        with self.assertRaisesRegex(ValueError,'poison'):cursor.validate_view(view(rows),raw(rows))
        cursor=candidate.FullStateCloneCursor();cursor.validate_view(view(rows),raw(rows))
        with self.assertRaisesRegex(ValueError,'regressed'):cursor.validate_view(view(rows[:4]),raw(rows))

    def test_same_prefix_changed_view_is_not_cached_verdict(self):
        rows=events();cursor=candidate.FullStateCloneCursor();v=view(rows)
        cursor.validate_view(v,raw(rows));bad=copy.deepcopy(v);bad['leases']=[]
        with self.assertRaisesRegex(ValueError,'projection'):cursor.validate_view(bad,raw(rows))
        self.assertTrue(cursor.poisoned)

    def test_unsupported_types_or_cycles_never_reach_marshal_load(self):
        class ChildDict(dict):pass
        cyclic=[];cyclic.append(cyclic)
        values=[set(),(lambda:None).__code__,ChildDict(x=1),float('nan'),float('inf'),b'external marshal bytes',cyclic,object()]
        for value in values:
            with self.subTest(kind=type(value).__name__),patch.object(candidate.marshal,'loads') as loads:
                with self.assertRaises(ValueError):candidate.clone_builtin_checked(value)
                loads.assert_not_called()

    def test_artifact_type_violation_poisons_without_executing_hooks(self):
        class Hook:
            def __deepcopy__(self,memo):raise AssertionError('untrusted deepcopy hook ran')
        rows=events();v=view(rows);v['launchRefusalArtifacts']=[Hook()]
        cursor=candidate.FullStateCloneCursor()
        with self.assertRaisesRegex(ValueError,'unsupported'):cursor.validate_view(v,raw(rows))
        self.assertTrue(cursor.poisoned)

    def test_exact_parser_source_is_mandatory(self):
        with patch.object(candidate,'PARSER_SOURCE_SHA256','0'*64):
            with self.assertRaisesRegex(ValueError,'source-pinned'):candidate.FullStateCloneCursor()

    def test_paired_bootstrap_is_one_parse_and_two_detached_mutable_states(self):
        rows=events();v=view(rows[:4])
        with patch.object(candidate,'replay_journal',wraps=life.replay_journal) as replay, \
             patch.object(candidate,'_detached_sealed_state',wraps=candidate._detached_sealed_state) as cloning:
            inner,outer,record=candidate.bootstrap_pair(v,raw(rows))
        self.assertEqual(replay.call_count,1)
        self.assertEqual(cloning.call_count,2)
        self.assertEqual(inner.statistics()['cCloneSnapshots'],2)
        self.assertEqual(outer.statistics()['cCloneSnapshots'],0)
        self.assertEqual(record['canonicalParserRuns'],1)
        self.assertEqual(record['detachedCacheCloneOperations'],2)
        self.assertIs(record['verdictGranted'],False)
        self.assertIs(record['processObservationPerformed'],False)
        self.assertEqual(record['prefixBytes'],len(raw(rows[:4])))
        self.assertTrue(typed_equal(record['initialView'],v))
        assert_mutable_detached(inner._state,outer._state)
        self.assertIsNot(inner._hasher,outer._hasher)
        before=outer.statistics()
        first=inner.validate_view(view(rows),raw(rows))
        self.assertEqual(outer.statistics(),before)
        second=outer.validate_view(view(rows),raw(rows))
        self.assertTrue(typed_equal(first,second))
        self.assertEqual(inner.statistics()['parsedEvents'],8)
        self.assertEqual(outer.statistics()['parsedEvents'],4)
        first['events'][0]['data']['stageId']='caller mutation'
        self.assertNotEqual(first['events'][0]['data']['stageId'],second['events'][0]['data']['stageId'])


if __name__=='__main__':unittest.main(verbosity=2)
