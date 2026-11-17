"""Independent E5 owned initialization controls; synthetic journal, no live observer."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO=Path(os.environ.get('AIJADE_E5_SOURCE_REPO',str(Path(__file__).resolve().parents[2])))
sys.path.insert(0,str(REPO/'experiments/ch7'))
CURSOR_SOURCE=Path(os.environ.get('AIJADE_E5_CURSOR_SOURCE',str(REPO/'experiments/ch7/newowned_guard_cursor.py')))
sys.path.insert(0,str(CURSOR_SOURCE.parent))
sys.path.insert(0,str(REPO/'tests/shell'))
import process_lifecycle as parser
import lifecycle_audit as oracle
from nested_event_index import EventIndex
from test_nested_event_index import fixture, seal, Q, P, ROOT, SCOPE


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


a=module('e5_audit_controls_subject',Path(os.environ.get('AIJADE_E5_AUDIT_SOURCE',str(REPO/'experiments/ch7/audit_nested_load.py'))))
sys.path.insert(0,str(CURSOR_SOURCE.parent))
import newowned_guard_cursor as cursor
import mac_process_guard_v3 as guard
assert Path(cursor.__file__).resolve()==CURSOR_SOURCE.resolve()
SCRATCH=REPO/'.runtime/nested-initialization-controls'
SCRATCH.mkdir(parents=True,exist_ok=True)


class InitializationAuditControls(unittest.TestCase):
    # Only the synthetic fixture's allowed file root is relocated for Linux CI;
    # the actual parser source/hash and replay validation remain unchanged.
    @mock.patch.object(parser,'BASE',REPO)
    def baseline(self, root, initialization_sequence=2, sample_sequences=(4,5,5)):
        events=fixture();raw=seal(events[:5]+events[6:]);index=EventIndex(raw,oracle._replay,Q,P)
        journal=root/'lifecycle-journal.jsonl';journal.write_bytes(raw);journal.chmod(0o600)
        def view_at(sequence):
            prefix=raw[:index.offsets[sequence]];state=parser.replay_journal(prefix)
            projected=[v for v in state['leases'].values() if v['absence'] is None]
            return dict(schema=parser.VIEW_SCHEMA,runId=state['runId'],journalPath=str(journal),
                journalBytes=len(prefix),journalSha256=hashlib.sha256(prefix).hexdigest(),lastSequence=sequence,
                scopeId=SCOPE,controllerIdentity=copy.deepcopy(ROOT),leases=copy.deepcopy(projected),
                referencedIdentities=[],launchRefusalArtifacts=[],controllers=[v['leaseId'] for v in projected if v['identity']==ROOT])
        first,second,core=cursor.bootstrap_pair(view_at(initialization_sequence))
        core.update(factoryStartedMonotonic=core['startedMonotonic']-.002,
            viewCapturedMonotonic=core['startedMonotonic']-.001,
            recordWriteStartedMonotonic=core['completedMonotonic']+.001)
        path=root/'initialization.json';path.write_bytes(a.canonical(core)+b'\n')
        write=dict(path=str(path),sha256=a.file_sha(path),startedMonotonic=core['recordWriteStartedMonotonic'],
            completedMonotonic=core['recordWriteStartedMonotonic']+.001)
        first.bind_preparation(core,write);second.bind_preparation(core,write)
        receipt=dict(initialization=copy.deepcopy(core),initializationWriteClock=write)
        passport=dict(sourceCommit=Q,policySha256=P,onlineReplayMode=a.REPLAY_MODE,
            onlineReplayInitializationMode=a.INITIALIZATION_MODE,
            onlineReplaySourceSha256=a.file_sha(cursor.__file__),
            sourceFiles={'experiments/ch7/newowned_guard_cursor.py':a.file_sha(cursor.__file__),
                         'experiments/ch7/mac_process_guard_v3.py':a.file_sha(guard.__file__)})
        policy=json.loads((REPO/'configs/research/ch7-mac-nested-copy-engineering-process-policy.json').read_bytes())
        policy.update(onlineReplayMode=a.REPLAY_MODE,onlineReplayInitializationMode=a.INITIALIZATION_MODE,
            onlineReplaySourceSha256=passport['onlineReplaySourceSha256'])
        policy.pop('binaryAuthenticationMode',None);policy.pop('binaryAuthenticationSourceSha256',None)
        rows=[];decisions={}
        for n,sequence in enumerate(sample_sequences):
            view=view_at(sequence);sid=('%032x'%n)
            observation=dict(sampleId=sid,lifecycle=view,onlineReplayMode=a.REPLAY_MODE,
                onlineReplaySourceSha256=passport['onlineReplaySourceSha256'],
                onlineReplayInitializationMode=a.INITIALIZATION_MODE,
                onlineReplayPreparation=first.preparation_reference())
            # Deliberately incomplete synthetic process evidence returns UNKNOWN.
            # Only independent complete-decision/counter semantics are tested;
            # this fixture cannot grant a raw-guard PASS or engineering verdict.
            expected=guard.validate_observation(policy,observation,raw)
            actual_inner=first.evaluate(policy,observation);actual_outer=second.evaluate(policy,observation)
            a.exact(actual_inner,expected,'synthetic inner complete cold decision differs')
            a.exact(actual_outer,expected,'synthetic outer complete cold decision differs')
            self.assertNotEqual(expected['status'],'PASS');decisions[sid]=expected
            rows.append(dict(sampleId=sid,monotonicSeconds=write['completedMonotonic']+1+n,processObservation=observation))
        receipt.update(innerCursor=first.statistics(),outerCursor=second.statistics())
        boundaries=dict(owner=ROOT,scope=SCOPE,earliest=core['factoryStartedMonotonic']-.001,
            latest=write['completedMonotonic']+.001,anchor=core['factoryStartedMonotonic']-.002,budget=15)
        return dict(root=root,journal=journal,index=index,receipt=receipt,passport=passport,
            rows=rows,boundaries=boundaries,decisions=decisions)

    def initial(self, baseline):
        b=baseline
        return a.verify_initialization(b['root'],b['receipt'],b['journal'],b['index'],oracle,parser,
            b['passport'],**b['boundaries'])

    def verify(self, baseline):
        b=baseline;initial=self.initial(b)
        return a.verify_initialization_usage(initial,b['rows'],b['receipt'],b['index'],b['passport'],b['decisions'])

    def rewrite_core(self, baseline, change):
        b=baseline;path=b['root']/'initialization.json';core=a.read(path);before=a.canonical(core)
        change(core);self.assertNotEqual(a.canonical(core),before)
        path.write_bytes(a.canonical(core)+b'\n');b['receipt']['initialization']=copy.deepcopy(core)
        b['receipt']['initializationWriteClock']['sha256']=a.file_sha(path)
        for row in b['rows']:
            row['processObservation']['onlineReplayPreparation']['sha256']=a.file_sha(path)

    def test_01_complete_baseline_counters_include_first_actual_tail(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));result=self.verify(b)
            self.assertEqual(result['actualSamples'],3)
            self.assertGreater(result['firstSampleNewTail']['events'],0)
            self.assertGreater(result['expectedOuterStatistics']['fullPrefixComparedBytes'],b['receipt']['initialization']['prefixBytes'])

    def test_02_canonical_parser_count_boolean_one_cannot_pass_rebound_hashes(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            self.rewrite_core(b,lambda c:c.update(canonicalParserRuns=True))
            with self.assertRaisesRegex(ValueError,'canonical parser population'):self.verify(b)

    def test_03_coherent_bootstrap_wrong_scope_is_not_file_owner(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            def change(c):
                c['scopeId']='9'*32;c['initialView']['scopeId']='9'*32
            self.rewrite_core(b,change)
            with self.assertRaisesRegex(ValueError,'file owner'):self.verify(b)

    def test_04_coherent_future_cutoff_cannot_borrow_completed_wait(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            def change(c):
                c['lastSequence']=5;c['prefixBytes']=b['index'].offsets[5]
                c['prefixSha256']=a.sha(b['journal'].read_bytes()[:c['prefixBytes']])
                c['initialView'].update(lastSequence=c['lastSequence'],journalBytes=c['prefixBytes'],journalSha256=c['prefixSha256'])
                cold=parser.replay_journal(b['journal'].read_bytes()[:c['prefixBytes']]);cold['launchRefusalArtifacts']=[]
                c['innerStatistics'],c['outerStatistics']=a.expected_initial_statistics(
                    c['prefixBytes'],5,a.builtin_container_count(cold),len(cold['leases']),c['innerOwner'],c['outerOwner'])
            self.rewrite_core(b,change)
            for row in b['rows']:
                row['processObservation']['onlineReplayPreparation'].update(
                    prefixBytes=b['receipt']['initialization']['prefixBytes'],
                    prefixSha256=b['receipt']['initialization']['prefixSha256'],lastSequence=5)
            with self.assertRaisesRegex(ValueError,'prefix regressed'):self.verify(b)

    def test_05_write_completion_not_clone_completion_controls_startup_budget(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            b['receipt']['initializationWriteClock']['completedMonotonic']=b['boundaries']['anchor']+15.01
            b['boundaries']['latest']=b['boundaries']['anchor']+16
            with self.assertRaisesRegex(ValueError,'preparation/startup budget'):self.verify(b)

    def test_06_rebound_observation_flag_is_not_allowed(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            self.rewrite_core(b,lambda c:c.update(processObservationPerformed=True))
            with self.assertRaisesRegex(ValueError,'hidden observation'):self.verify(b)

    def test_07_first_post_bootstrap_full_read_and_compare_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            b['receipt']['outerCursor']['fullPrefixComparedBytes']-=b['receipt']['initialization']['prefixBytes']
            with self.assertRaisesRegex(ValueError,'final outer actual prefix/read/compare'):self.verify(b)

    def test_08_first_new_tail_cannot_be_omitted_from_parser_counters(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            omitted=b['rows'][0]['processObservation']['lifecycle']['lastSequence']-b['receipt']['initialization']['lastSequence']
            b['receipt']['innerCursor']['parsedEvents']-=omitted
            b['receipt']['outerCursor']['parsedEvents']-=omitted
            with self.assertRaisesRegex(ValueError,'actual prefix/read/compare/parser'):self.verify(b)

    def test_09_rebound_cached_verdict_is_not_initialization(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            self.rewrite_core(b,lambda c:c.update(verdictGranted=True))
            with self.assertRaisesRegex(ValueError,'cached verdict'):self.verify(b)

    def test_10_legal_other_reference_cannot_replace_actual_scope_artifact(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            b['rows'][0]['processObservation']['onlineReplayPreparation']['path']=str(b['root']/'other'/'initialization.json')
            with self.assertRaisesRegex(ValueError,'reference differs'):self.verify(b)

    def test_11_wrong_inode_cannot_be_claimed_by_matching_logical_path(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            self.rewrite_core(b,lambda c:c['sourceOrigin'].__setitem__(3,c['sourceOrigin'][3]+1))
            with self.assertRaisesRegex(ValueError,'file source origin'):self.verify(b)

    def test_12_post_bootstrap_counter_reset_cannot_hide_initial_cost(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            b['receipt']['innerCursor']['calls']-=1
            b['receipt']['innerCursor']['parsedBytes']-=b['receipt']['initialization']['prefixBytes']
            with self.assertRaisesRegex(ValueError,'actual prefix/read/compare'):self.verify(b)

    def test_19_distinct_owner_pair_and_roles_cannot_be_coherently_aliased(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            def change(c):
                c['outerOwner']['ownerId']=c['innerOwner']['ownerId']
                c['outerStatistics']['ownerId']=c['innerOwner']['ownerId']
            self.rewrite_core(b,change)
            with self.assertRaisesRegex(ValueError,'paired guard owner aliases'):self.verify(b)

    def test_20_raw_foreign_pair_reference_cannot_borrow_valid_prefix(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            b['rows'][0]['processObservation']['onlineReplayPreparation']['pairedOwnerId']='a'*32
            with self.assertRaisesRegex(ValueError,'reference differs'):self.verify(b)

    def test_21_per_evaluation_state_copy_claim_is_not_owned_contract(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            self.rewrite_core(b,lambda c:c.update(perEvaluationFullStateCopies=1))
            with self.assertRaisesRegex(ValueError,'full-state copies'):self.verify(b)

    def test_22_complete_decision_canonical_logical_byte_count_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            b['receipt']['outerCursor']['detachedDecisionCanonicalBytes']-=len(a.canonical(b['decisions'][b['rows'][0]['sampleId']]))
            with self.assertRaisesRegex(ValueError,'final outer actual'):self.verify(b)

    def test_23_private_history_population_must_retain_all_leases(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            b['receipt']['innerCursor']['retainedLeases']-=1
            with self.assertRaisesRegex(ValueError,'final inner actual'):self.verify(b)

    def test_24_guard_predicate_ast_accepts_original_and_rejects_semantic_change(self):
        a.verify_guard_predicate_source(guard.__file__)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            p=Path(d)/'guard.py';text=Path(guard.__file__).read_text()
            changed=text.replace('replay_keys = (', 'replay_keys = tuple((').replace("'onlineReplayPreparation')","'onlineReplayPreparation'))",1)
            self.assertNotEqual(changed,text);p.write_text(changed)
            with self.assertRaisesRegex(ValueError,'predicate AST'):a.verify_guard_predicate_source(p)

    def test_13_supported_type_count_is_alias_aware_and_rejects_foreign_types(self):
        shared=[]
        self.assertEqual(a.builtin_container_count({'a':shared,'b':shared}),2)
        with self.assertRaisesRegex(ValueError,'unsupported'):a.builtin_container_count({'bad':set()})
        loop=[];loop.append(loop)
        with self.assertRaisesRegex(ValueError,'cyclic'):a.builtin_container_count(loop)

    def test_14_existing_finite_history_and_wait_tail_preserve_exact_container_statistics(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d),initialization_sequence=4,sample_sequences=(5,5,5))
            result=self.verify(b)
            self.assertEqual(result['firstSampleNewTail']['events'],1)
            self.assertEqual(result['expectedInnerStatistics']['builtinColdStates'],1)
            self.assertEqual(result['expectedOuterStatistics']['builtinColdStates'],0)

    def set_synthetic_write_end(self, baseline, seconds, budget):
        """Synthetic field-boundary canary, never a measured startup result."""
        b=baseline;before=a.canonical(b['receipt'])
        end=b['boundaries']['anchor']+seconds
        b['receipt']['initializationWriteClock']['completedMonotonic']=end
        b['boundaries'].update(budget=budget,latest=b['boundaries']['anchor']+budget+1)
        for n,row in enumerate(b['rows']):row['monotonicSeconds']=end+1+n
        self.assertNotEqual(a.canonical(b['receipt']),before)

    def test_15_e5_runtime_contract_accepts_fifteen_and_rejects_coherent_old_ten(self):
        value=dict(blocks=4,blockWorkSeconds=120,betweenBlockSeconds=4,parentTailSeconds=4,
            parentMaximumSeconds=600,childStartupMaximumSeconds=15,childCleanupMaximumSeconds=8,
            childWatchdogSeconds=145,alignmentModes=['natural','parent-next-slot','natural','parent-next-slot'])
        a.verify_runtime_contract(value)
        changed=copy.deepcopy(value);changed['childStartupMaximumSeconds']=10
        self.assertNotEqual(a.canonical(changed),a.canonical(value))
        with self.assertRaisesRegex(ValueError,'frozen E5 engineering runtime'):a.verify_runtime_contract(changed)

    def test_16_e5_actual_write_clock_boundary_14_9_is_accepted(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            self.set_synthetic_write_end(b,14.9,15)
            self.assertLess(b['receipt']['initialization']['completedMonotonic']-b['boundaries']['anchor'],10)
            self.assertEqual(self.verify(b)['actualSamples'],3)

    def test_17_e5_actual_write_clock_boundary_15_001_is_refused(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            self.set_synthetic_write_end(b,15.001,15)
            self.assertLess(b['receipt']['initialization']['completedMonotonic']-b['boundaries']['anchor'],10)
            with self.assertRaisesRegex(ValueError,'preparation/startup budget'):self.verify(b)

    def test_18_parent_preparation_actual_write_boundary_remains_nine_hundred(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            b=self.baseline(Path(d));self.verify(b)
            self.set_synthetic_write_end(b,899.9,900)
            self.assertEqual(self.verify(b)['actualSamples'],3)
            self.set_synthetic_write_end(b,900.001,900)
            with self.assertRaisesRegex(ValueError,'preparation/startup budget'):self.verify(b)


if __name__=='__main__':unittest.main()
