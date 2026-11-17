"""Actual factory and policy/raw binding with small prerecorded fixtures only."""
from pathlib import Path
import copy
import hashlib
import json
import sys
import tempfile
import unittest

B=Path('/Volumes/Untitled/AIJADE');W=B/'.runtime/posix/nested-20261117/worktree'
sys.path.insert(0,str(W/'experiments/ch7'));sys.path.insert(0,str(W/'tests/shell'))
import process_lifecycle as life
import mac_process_guard_v3 as guard
import full_state_clone_cursor as clone
import finite_runtime as runtime
from test_mac_lifecycle_guard import fixture


class CloneGlueControls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=B/'.runtime/posix/tmp',prefix='clone-glue-control-')
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def prepared(self):
        policy,observation,raw=fixture()
        policy.update(onlineReplayMode=clone.MODE,onlineReplaySourceSha256=guard._file_sha(Path(clone.__file__)),
                      onlineReplayInitializationMode=clone.INITIALIZATION_MODE)
        journal=self.root/'journal.jsonl';journal.write_bytes(raw);journal.chmod(0o600)
        view=observation['lifecycle'];view['journalPath']=str(journal)
        registry=object.__new__(life.Registry);registry.sample=lambda:copy.deepcopy(view)
        inner,outer=runtime.online_lifecycle_cursors(policy,lifecycle=registry,preparation_path=self.root/'initialization.json')
        metadata=runtime.lifecycle_cursor_initialization(inner)
        observation.update(policyCanonicalSha256=guard.canonical_sha256(policy),onlineReplayMode=clone.MODE,
            onlineReplaySourceSha256=policy['onlineReplaySourceSha256'],onlineReplayInitializationMode=clone.INITIALIZATION_MODE,
            onlineReplayPreparation=inner['lifecycle_cursor'].preparation_reference())
        return policy,observation,raw,inner,outer,metadata

    def test_actual_factory_writes_one_core_record_and_real_closed_writer_clock(self):
        p,o,raw,inner,outer,metadata=self.prepared()
        path=self.root/'initialization.json';body=path.read_bytes();core=json.loads(body)
        self.assertEqual(core,metadata['initialization'])
        clocks=metadata['initializationWriteClock']
        self.assertEqual(clocks['sha256'],hashlib.sha256(body).hexdigest())
        self.assertLessEqual(core['factoryStartedMonotonic'],core['viewCapturedMonotonic'])
        self.assertLessEqual(core['completedMonotonic'],clocks['startedMonotonic'])
        self.assertLessEqual(clocks['startedMonotonic'],clocks['completedMonotonic'])
        self.assertEqual(runtime.lifecycle_cursor_initialization(outer),metadata)
        self.assertIsNot(inner['lifecycle_cursor']._state,outer['lifecycle_cursor']._state)

    def test_new_raw_guard_is_recomputed_both_runtime_and_original_cold_path(self):
        p,o,raw,inner,outer,metadata=self.prepared()
        for cursor in (None,inner['lifecycle_cursor'],outer['lifecycle_cursor']):
            result=guard.validate_observation(p,o,lifecycle_journal=raw if cursor is None else None,lifecycle_cursor=cursor)
            self.assertEqual(result['status'],'PASS',result)

    def test_wrong_policy_source_initializer_and_legacy_field_substitution_refuse(self):
        p,o,raw,inner,outer,metadata=self.prepared()
        for key,value in [('onlineReplaySourceSha256','0'*64),('onlineReplayInitializationMode','unapproved')]:
            q=copy.deepcopy(p);q[key]=value
            with self.assertRaises(ValueError):guard.validate_policy(q)
        q=copy.deepcopy(p);q['onlineReplayMode']='incremental-exact-prefix-v1'
        with self.assertRaises(ValueError):guard.validate_policy(q)

    def test_wrong_raw_mode_or_preparation_scope_or_cutoff_refuse(self):
        p,o,raw,inner,outer,metadata=self.prepared()
        for kind in ('mode','scope','cutoff','source'):
            bad=copy.deepcopy(o)
            if kind=='mode':bad['onlineReplayMode']='incremental-exact-prefix-v1'
            if kind=='scope':bad['onlineReplayPreparation']['scopeId']='0'*32
            if kind=='cutoff':bad['onlineReplayPreparation']['prefixBytes']=o['lifecycle']['journalBytes']+1
            if kind=='source':bad['onlineReplayPreparation']['cursorSourceSha256']='0'*64
            self.assertNotEqual(guard.validate_observation(p,bad,lifecycle_journal=raw)['status'],'PASS')

    def test_new_policy_cannot_use_old_runtime_cursor_or_unbound_candidate(self):
        p,o,raw,inner,outer,metadata=self.prepared()
        for cursor in (life.ViewCursor(),clone.FullStateCloneCursor()):
            self.assertNotEqual(guard.validate_observation(p,o,lifecycle_journal=raw,lifecycle_cursor=cursor)['status'],'PASS')

    def test_legacy_factory_preserves_old_type_and_does_not_write_initializer(self):
        policy,_,_=fixture();policy['onlineReplayMode']='incremental-exact-prefix-v1'
        inner,outer=runtime.online_lifecycle_cursors(policy,preparation_path=self.root/'initialization.json')
        self.assertIs(type(inner['lifecycle_cursor']),life.ViewCursor)
        self.assertIs(type(outer['lifecycle_cursor']),life.ViewCursor)
        self.assertEqual(runtime.lifecycle_cursor_initialization(inner),{})
        self.assertFalse((self.root/'initialization.json').exists())
        self.assertEqual(len(runtime.lifecycle_observer_sources(policy)),15)
        policy['onlineReplayMode']=clone.MODE
        self.assertEqual(len(runtime.lifecycle_observer_sources(policy)),17)

    def test_new_factory_requires_real_registry_and_fresh_record(self):
        p,o,raw,inner,outer,metadata=self.prepared()
        with self.assertRaises(ValueError):runtime.online_lifecycle_cursors(p)
        registry=object.__new__(life.Registry);registry.sample=lambda:copy.deepcopy(o['lifecycle'])
        with self.assertRaises(ValueError):runtime.online_lifecycle_cursors(p,lifecycle=registry,preparation_path=self.root/'initialization.json')


if __name__=='__main__':unittest.main(verbosity=2)
