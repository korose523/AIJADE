"""Offline v3 adapter controls; mocked delegates cannot qualify a backend.

The real lifecycle/continuity auditors retain their own raw-byte corruption
controls. These tests verify that the finite adapters call them with the correct
archive bytes, scope and version identities rather than a stale live path.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'experiments/ch7'))
import finite_sequence_audit as audit
import finite_runtime
import lifecycle_audit
import finite_rejection_controls


def digest(body):
    return hashlib.sha256(body).hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) + '\n')


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


def identity():
    sources = {path: 'a' * 64 for path in finite_runtime.MAC_LIFECYCLE_SOURCES}
    return dict(codeCommit='1' * 40, implementationCommit='1' * 40,
        repositoryCommit='1' * 40, buildFreezeCommit='2' * 40,
        buildFreezePath=audit.LIFECYCLE_BUILD_FREEZE_PATH, inputPublicationCommit=None,
        dataPublicationManifestPath=None, dataPublicationManifestSha256=None,
        addedDataPaths=[], processPolicyPath='configs/research/policy.json',
        processPolicySha256='b' * 64, observerModuleSha256='a' * 64,
        observerSources=sources, executionPlanSha256=audit.LIFECYCLE_PLAN_SHA256,
        lifecycleScopeId='c' * 32, controllerProcess=dict(pid=42,createTime=1.0),
        purpose='qualification_only')


class LifecycleAdapterControls(unittest.TestCase):
    def setUp(self):
        scratch = REPO / '.runtime/tmp'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='lifecycle-adapter-', dir=scratch)
        self.parent = Path(self.temp.name)
        self.root = self.parent / 'sequence'
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def receipt(self, body):
        return dict(lifecycleJournalSha256=digest(body), lifecycleJournalBytes=len(body),
                    lifecycleJournalPath=str(self.parent / 'old-live-journal.jsonl'))

    def test_versioned_plan_path_keeps_old_decisions_distinct(self):
        self.assertEqual(audit.expected_plan_sha256(identity()), audit.LIFECYCLE_PLAN_SHA256)
        old = dict(buildFreezePath=finite_runtime.MAC_BUILD_FREEZE_PATH)
        self.assertEqual(audit.expected_plan_sha256(old), audit.PLAN_SHA256)
        old['buildFreezePath'] = finite_runtime.MAC_CENSUS_BUILD_FREEZE_PATH
        self.assertEqual(audit.expected_plan_sha256(old), audit.CENSUS_PLAN_SHA256)
        with self.assertRaisesRegex(ValueError, 'unknown execution'):
            audit.expected_plan_sha256(dict(buildFreezePath='other.json'))

    def test_complete_15_source_map_includes_binary_authentication(self):
        value = identity()
        audit._identity(value, 'qualification_only')
        self.assertEqual(len(value['observerSources']), 15)
        self.assertEqual(set(value['observerSources']),set(finite_runtime.MAC_LIFECYCLE_SOURCES))
        self.assertIn('experiments/ch7/binary_authentication.py',value['observerSources'])
        for source in finite_runtime.MAC_LIFECYCLE_SOURCES:
            with self.subTest(missing=source):
                incomplete=identity();incomplete['observerSources'].pop(source)
                with self.assertRaisesRegex(ValueError, 'population'):
                    audit._identity(incomplete, 'qualification_only')
        value = identity()
        value['observerSources']['other.py'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'population'):
            audit._identity(value, 'qualification_only')

    def test_guard_hash_and_dependency_map_must_agree(self):
        value = identity()
        value['observerSources']['experiments/ch7/mac_process_guard_v3.py'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'module/map'):
            audit._identity(value, 'qualification_only')

    def test_cross_block_dependency_substitution_refused(self):
        sequence = identity(); value = copy.deepcopy(sequence)
        audit._same_identity(value, sequence, 'qualification_only')
        value['observerSources']['experiments/ch7/lifecycle_audit.py'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'mixed v3'):
            audit._same_identity(value, sequence, 'qualification_only')

    def test_archive_local_copy_precedes_old_absolute_live_path(self):
        body = b'archive\n'; stale = b'unrelated-live\n'
        receipt = self.receipt(body)
        Path(receipt['lifecycleJournalPath']).write_bytes(stale)
        (self.root / 'lifecycle-journal.jsonl').write_bytes(body)
        self.assertEqual(audit.lifecycle_journal_bytes(self.root, receipt), body)

    def test_parent_archive_copy_precedes_live_path_for_block(self):
        body = b'prefix\n'; extended = body + b'parent-later\n'
        block = self.root / 'block-1'; block.mkdir()
        (self.root / 'lifecycle-journal.jsonl').write_bytes(extended)
        receipt = self.receipt(body)
        self.assertEqual(audit.lifecycle_journal_bytes(block, receipt, prefix=True), body)

    def test_malformed_preferred_copy_cannot_fall_back_to_valid_live(self):
        body = b'original\n'; receipt = self.receipt(body)
        Path(receipt['lifecycleJournalPath']).write_bytes(body)
        (self.root / 'lifecycle-journal.jsonl').write_bytes(b'altered!\n')
        with self.assertRaisesRegex(ValueError, 'bytes/SHA'):
            audit.lifecycle_journal_bytes(self.root, receipt)

    def test_only_missing_archives_allow_original_local_fallback(self):
        body = b'fallback\n'; receipt = self.receipt(body)
        Path(receipt['lifecycleJournalPath']).write_bytes(body)
        self.assertEqual(audit.lifecycle_journal_bytes(self.root, receipt), body)

    def test_prefix_size_sha_and_record_boundary_are_bound(self):
        body = b'one\n'; receipt = self.receipt(body)
        (self.root / 'lifecycle-journal.jsonl').write_bytes(body+b'two\n')
        self.assertEqual(audit.lifecycle_journal_bytes(self.root, receipt, prefix=True), body)
        bad = dict(receipt,lifecycleJournalBytes=3,lifecycleJournalSha256=digest(b'one'))
        with self.assertRaisesRegex(ValueError, 'bytes/SHA'):
            audit.lifecycle_journal_bytes(self.root, bad, prefix=True)
        bad = dict(receipt,lifecycleJournalBytes=100)
        with self.assertRaisesRegex(ValueError, 'truncated'):
            audit.lifecycle_journal_bytes(self.root, bad, prefix=True)
        with self.assertRaisesRegex(ValueError, 'population'):
            audit.lifecycle_journal_bytes(self.root, receipt)

    def test_symbolic_link_is_not_an_archive_copy(self):
        body = b'bound\n'; receipt = self.receipt(body)
        original = Path(receipt['lifecycleJournalPath']); original.write_bytes(body)
        (self.root / 'lifecycle-journal.jsonl').symlink_to(original)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            audit.lifecycle_journal_bytes(self.root, receipt)

    def test_v3_guard_receives_original_bytes_explicitly(self):
        policy = {'kind': audit.LIFECYCLE_KIND}
        with patch.object(finite_runtime, 'validate_mac_observation', return_value={'status':'PASS'}) as delegate:
            audit._process_observation({}, 'b'*64, 'a'*64, policy, lifecycle_journal=b'journal\n')
            self.assertEqual(delegate.call_args.kwargs, {'lifecycle_journal':b'journal\n'})
        with self.assertRaisesRegex(ValueError, 'archived lifecycle'):
            audit._process_observation({}, 'b'*64, 'a'*64, policy)

    def test_legacy_guard_signature_is_unchanged(self):
        with patch.object(finite_runtime, 'validate_mac_observation', return_value={'status':'PASS'}) as delegate:
            audit._process_observation({}, 'b'*64, 'a'*64, {'kind':'mac-observed-idle-daemon-v1'})
            self.assertEqual(delegate.call_args.kwargs, {})
            self.assertEqual(len(delegate.call_args.args), 4)

    def ownership_fixture(self):
        body=b'original-record\n'; receipt=dict(identity(),**self.receipt(body))
        (self.root/'lifecycle-journal.jsonl').write_bytes(body)
        registry=dict(schema='aijade.process-lifecycle-final.v1',
            status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT',scopeId=receipt['lifecycleScopeId'],
            scopeClosed=True,unresolvedFiniteLeases=[],unleasedDiscoveredIdentities=[],
            remainingIdentities=[],knownFiniteLeases=[{'syntheticNonExecutable':True}])
        write(self.root/'owned-process-registry.json',registry)
        receipt['ownedProcessRegistrySha256']=digest((self.root/'owned-process-registry.json').read_bytes())
        return body,receipt,registry

    def test_block_lifecycle_scope_excludes_parent_self(self):
        body,receipt,_=self.ownership_fixture()
        with patch.object(lifecycle_audit,'verify_lifecycle',return_value=dict(
                status='LIFECYCLE_RAW_AUDIT_PASS',cleanupAccepted=True,finiteLeases=1)) as delegate:
            audit._lifecycle_ownership(self.root,receipt,[{'synthetic':True}],{'kind':audit.LIFECYCLE_KIND},scoped=True)
            self.assertEqual(delegate.call_args.args[0],body)
            self.assertEqual(delegate.call_args.kwargs['scope_id'],receipt['lifecycleScopeId'])
            self.assertEqual(delegate.call_args.kwargs['controller'],receipt['controllerProcess'])
            self.assertTrue(delegate.call_args.kwargs['require_cleanup'])

    def test_sequence_lifecycle_requires_entire_journal_closure(self):
        _,receipt,_=self.ownership_fixture()
        with patch.object(lifecycle_audit,'verify_lifecycle',return_value=dict(
                status='LIFECYCLE_RAW_AUDIT_PASS',cleanupAccepted=True,finiteLeases=1)) as delegate:
            audit._lifecycle_ownership(self.root,receipt,[{'synthetic':True}],{'kind':audit.LIFECYCLE_KIND},scoped=False)
            self.assertIsNone(delegate.call_args.kwargs['scope_id'])

    def test_claimed_registry_finite_count_cannot_hide_missing_lease(self):
        _,receipt,_=self.ownership_fixture()
        with patch.object(lifecycle_audit,'verify_lifecycle',return_value=dict(
                status='LIFECYCLE_RAW_AUDIT_PASS',cleanupAccepted=True,finiteLeases=2)):
            with self.assertRaisesRegex(ValueError,'population differs'):
                audit._lifecycle_ownership(self.root,receipt,[{}],{'kind':audit.LIFECYCLE_KIND},scoped=True)

    def test_real_lifecycle_delegate_refusal_is_not_swallowed(self):
        _,receipt,_=self.ownership_fixture()
        with patch.object(lifecycle_audit,'verify_lifecycle',side_effect=ValueError('raw lifecycle witness missing')):
            with self.assertRaisesRegex(ValueError,'witness missing'):
                audit._lifecycle_ownership(self.root,receipt,[{}],{'kind':audit.LIFECYCLE_KIND},scoped=True)

    def test_unresolved_registry_cannot_be_cleared_by_delegate(self):
        _,receipt,registry=self.ownership_fixture()
        registry['remainingIdentities']=[{'syntheticUnresolved':True}]
        write(self.root/'owned-process-registry.json',registry)
        receipt['ownedProcessRegistrySha256']=digest((self.root/'owned-process-registry.json').read_bytes())
        with patch.object(lifecycle_audit,'verify_lifecycle') as delegate:
            with self.assertRaisesRegex(ValueError,'unresolved identities'):
                audit._lifecycle_ownership(self.root,receipt,[{}],{'kind':audit.LIFECYCLE_KIND},scoped=True)
            delegate.assert_not_called()

    def preflight_fixture(self):
        module_path=REPO/'tests/shell/test_phase_continuity.py'
        spec=importlib.util.spec_from_file_location('adapter_phase_fixture',module_path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        fixture=module.Fixture();preflight=fixture.run()
        sequence=identity()
        sequence['sequenceEpochMonotonic']=preflight['phases']['admission']['phaseClock']['endMonotonic']
        for rows in fixture.raw.values():
            for row in rows:
                row['processObservation']['lifecycle']={'scopeId':sequence['lifecycleScopeId']}
        write(self.root/'preflight-continuity.json',preflight)
        jsonl(self.root/'phase-events.jsonl',fixture.events)
        sequence['preflightContinuitySha256']=digest((self.root/'preflight-continuity.json').read_bytes())
        sequence['phaseEventsSha256']=digest((self.root/'phase-events.jsonl').read_bytes())
        for name,phase in preflight['phases'].items():
            write(self.root/name/'receipt.json',dict(phase,**sequence))
            jsonl(self.root/name/'telemetry.jsonl',fixture.raw[name])
        return sequence,fixture

    def test_v3_continuity_replays_idle_rows_and_actual_runtime_handoff(self):
        sequence,fixture=self.preflight_fixture()
        runtime=[{'actualRuntimeNotPlaceholder':True}]
        with patch.object(lifecycle_audit,'verify_continuity',return_value=dict(
                status='CONTINUITY_RAW_AUDIT_PASS',maximumGlobalSampleGapSeconds=2)) as delegate:
            result=audit._admission(self.root,sequence,{'kind':audit.LIFECYCLE_KIND},
                runtime_samples=runtime,lifecycle_journal=b'actual-journal\n')
            self.assertEqual(result['status'],'CONTINUITY_RAW_AUDIT_PASS')
            self.assertEqual(delegate.call_args.kwargs['runtime_samples'],runtime)
            self.assertEqual(delegate.call_args.kwargs['lifecycle_journal'],b'actual-journal\n')
            self.assertEqual(len(delegate.call_args.args[1]['settling']),300)
            self.assertEqual(len(delegate.call_args.args[1]['admission']),60)
            self.assertEqual(delegate.call_args.args[2],fixture.events)

    def test_preflight_anchor_substitution_refused_after_full_delegate(self):
        sequence,_=self.preflight_fixture()
        value=json.loads((self.root/'preflight-continuity.json').read_bytes())
        value['runtimeHandoffAnchor']['lastSampleMonotonic']+=1
        write(self.root/'preflight-continuity.json',value)
        sequence['preflightContinuitySha256']=digest((self.root/'preflight-continuity.json').read_bytes())
        with patch.object(lifecycle_audit,'verify_continuity',return_value=dict(
                status='CONTINUITY_RAW_AUDIT_PASS',maximumGlobalSampleGapSeconds=2)):
            with self.assertRaisesRegex(ValueError,'anchor changed'):
                audit._admission(self.root,sequence,{'kind':audit.LIFECYCLE_KIND},runtime_samples=[{}],lifecycle_journal=b'journal\n')

    def test_idle_scope_substitution_is_not_a_controller_free_phase(self):
        sequence,fixture=self.preflight_fixture()
        changed=copy.deepcopy(fixture.raw['admission'])
        changed[0]['processObservation']['lifecycle']['scopeId']='d'*32
        jsonl(self.root/'admission/telemetry.jsonl',changed)
        with patch.object(lifecycle_audit,'verify_continuity') as delegate:
            with self.assertRaisesRegex(ValueError,'another persistent scope'):
                audit._admission(self.root,sequence,{'kind':audit.LIFECYCLE_KIND},runtime_samples=[{}],lifecycle_journal=b'journal\n')
            delegate.assert_not_called()

    def ancestry_fixture(self):
        prefix=b'block-prefix\n'; full=prefix+b'parent-after-block\n'
        block=self.root/'block-1';block.mkdir()
        local=dict(identity(),lifecycleScopeId='d'*32,controllerProcess=dict(pid=43,createTime=2.0),
                   lifecycleJournalPath=str(self.parent/'never-read-live.jsonl'),
                   lifecycleJournalBytes=len(prefix),lifecycleJournalSha256=digest(prefix))
        sequence=dict(identity(),schema='aijade.ch7.finite-sequence-receipt.v1',
            status='COMPLETE_FINITE_SEQUENCE_OBSERVATIONS',plannedBlocks=1,completedBlocks=1,
            blocks=[local],lifecycleJournalBytes=len(full),lifecycleJournalSha256=digest(full))
        parent_row=dict(monotonicSeconds=10,rssBytes=50,processObservation=dict(
            sampleId='1'*32,lifecycle=dict(scopeId=sequence['lifecycleScopeId'])))
        local_row=dict(monotonicSeconds=11,rssBytes=7,processObservation=dict(
            sampleId='2'*32,lifecycle=dict(scopeId=local['lifecycleScopeId'])))
        write(self.root/'receipt.json',sequence);write(block/'receipt.json',local)
        (self.root/'lifecycle-journal.jsonl').write_bytes(full)
        (block/'lifecycle-journal.jsonl').write_bytes(prefix)
        jsonl(self.root/'process-observations.jsonl',[parent_row])
        jsonl(block/'telemetry.jsonl',[local_row])
        registry=dict(schema='aijade.process-lifecycle-final.v1',
            status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT',scopeId=local['lifecycleScopeId'],
            scopeClosed=True,unresolvedFiniteLeases=[],unleasedDiscoveredIdentities=[],
            remainingIdentities=[],knownFiniteLeases=[{'syntheticNonExecutable':True}])
        write(block/'owned-process-registry.json',registry)
        local['ownedProcessRegistrySha256']=digest((block/'owned-process-registry.json').read_bytes())
        sequence['blocks']=[local]
        write(block/'receipt.json',local);write(self.root/'receipt.json',sequence)
        return block,local,sequence,parent_row,local_row,prefix,full

    def test_complete_context_retains_raw_bytes_and_all_physical_hashes(self):
        block,local,_,parent_row,local_row,_,full=self.ancestry_fixture()
        context=audit.lifecycle_ancestry_context(block,local)
        self.assertEqual(context['journalBytes'],full)
        self.assertEqual(context['samples'],[parent_row,local_row])
        self.assertEqual(set(context['rawStreams']),{'process-observations.jsonl','block-1/telemetry.jsonl'})
        self.assertEqual(len(context['payloads']),5)
        for path,meta in context['payloads'].items():
            self.assertEqual(digest(Path(path).read_bytes()),meta['sha256'])

    def test_scoped_prefix_remains_principal_and_full_context_only_supplies_frames(self):
        block,local,_,parent_row,local_row,prefix,full=self.ancestry_fixture()
        context=audit.lifecycle_ancestry_context(block,local)
        with patch.object(lifecycle_audit,'verify_lifecycle',return_value=dict(
                status='LIFECYCLE_RAW_AUDIT_PASS',cleanupAccepted=True,finiteLeases=1)) as delegate:
            audit._lifecycle_ownership(block,local,[local_row],{'kind':audit.LIFECYCLE_KIND},
                scoped=True,ancestry_context=context)
            self.assertEqual(delegate.call_args.args,(prefix,[local_row]))
            self.assertEqual(delegate.call_args.kwargs['ancestry_samples'],[parent_row,local_row])
            self.assertEqual(delegate.call_args.kwargs['ancestry_journal'],full)
            self.assertEqual(delegate.call_args.kwargs['scope_id'],local['lifecycleScopeId'])

    def test_ancestry_context_cannot_cover_a_changed_local_raw_sample(self):
        block,local,_,_,local_row,_,_=self.ancestry_fixture()
        context=audit.lifecycle_ancestry_context(block,local)
        changed=copy.deepcopy(local_row);changed['rssBytes']+=1
        with patch.object(lifecycle_audit,'verify_lifecycle') as delegate:
            with self.assertRaisesRegex(ValueError,'local raw sample differs'):
                audit._lifecycle_ownership(block,local,[changed],{'kind':audit.LIFECYCLE_KIND},
                    scoped=True,ancestry_context=context)
            delegate.assert_not_called()

    def test_context_parsed_rows_cannot_be_changed_without_original_bytes(self):
        block,local,_,_,local_row,_,_=self.ancestry_fixture()
        context=audit.lifecycle_ancestry_context(block,local)
        context['samples'][0]['rssBytes']+=1
        with self.assertRaisesRegex(ValueError,'parsed samples differ'):
            audit._ancestry_local_samples(context,local,[local_row])

    def test_missing_mother_raw_context_is_a_refusal_not_smaller_scope(self):
        block,local,*_=self.ancestry_fixture()
        (self.root/'process-observations.jsonl').unlink()
        with self.assertRaisesRegex(ValueError,'missing ancestry context payload'):
            audit.lifecycle_ancestry_context(block,local)

    def test_temporary_corruption_baseline_receives_original_complete_context(self):
        block,local,_,parent_row,local_row,prefix,_=self.ancestry_fixture()
        for name in finite_rejection_controls.FILES:
            path=block/name
            if not path.exists():
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text('[]\n')
        write(block/'input-identities.json',dict(processPolicySha256='b'*64))
        write(block/'process-policy.json',dict(kind=audit.LIFECYCLE_KIND))
        seen=[]
        def verify(target,repo,*,ancestry_context=None):
            seen.append(target)
            self.assertEqual(ancestry_context['samples'],[parent_row,local_row])
            if target==block:return {'nonExecutableFixtureOnly':True}
            self.assertEqual((target/'lifecycle-journal.jsonl').read_bytes(),prefix)
            self.assertEqual(json.loads((target/'telemetry.jsonl').read_bytes()),local_row)
            raise ValueError('incomplete disposable fixture baseline, no mutations may be counted')
        with patch.object(finite_rejection_controls,'verify',side_effect=verify):
            with self.assertRaisesRegex(ValueError,'no mutations may be counted'):
                finite_rejection_controls.run(block,REPO)
        self.assertEqual(len(seen),2)

    def real_parser_context(self, *, fake_chain=False):
        # This uses serialized native/API/journal documents and the actual v3
        # validators. The documents remain nonexecutable synthetic fixtures.
        sys.path.insert(0,str(REPO/'tests/shell'))
        import test_lifecycle_audit_raw as full_raw
        fixture,policy=full_raw.ancestry_fixture()
        if fake_chain:
            next(event for event in fixture.events if event['event']=='DISCOVER')['data']['ancestry'][1]['createTimeMicros']=201000000
            full_raw.reproject(fixture)
        block=self.root/'block-1';block.mkdir()
        shared=dict(identity(),codeCommit=full_raw.Q,implementationCommit=full_raw.Q,
            repositoryCommit=full_raw.Q,processPolicySha256=full_raw.P,
            lifecycleScopeId='2'*32,controllerProcess=full_raw.ROOT,
            lifecycleJournalBytes=len(fixture.raw),lifecycleJournalSha256=digest(fixture.raw))
        sequence=dict(shared,schema='aijade.ch7.finite-sequence-receipt.v1',
            status='COMPLETE_FINITE_SEQUENCE_OBSERVATIONS',plannedBlocks=1,completedBlocks=1,blocks=[shared])
        write(self.root/'receipt.json',sequence);write(block/'receipt.json',shared)
        (self.root/'lifecycle-journal.jsonl').write_bytes(fixture.raw)
        # Splitting the original serialized rows into two archived streams tests
        # the context index without replacing the principal resource population.
        jsonl(self.root/'process-observations.jsonl',[fixture.rows[0]])
        jsonl(block/'telemetry.jsonl',[fixture.rows[1]])
        # Native before/after collectors now have ordinary finite leases too.
        # Derive the final producer population from the actual fixture journal,
        # rather than keeping the old one-task fixture assumption.
        finite_leases=[value for value in full_raw.producer.replay_journal(fixture.raw)['leases'].values()
                       if value['role']=='finite']
        registry=dict(schema='aijade.process-lifecycle-final.v1',
            status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT',scopeId='2'*32,scopeClosed=True,
            unresolvedFiniteLeases=[],unleasedDiscoveredIdentities=[],remainingIdentities=[],
            knownFiniteLeases=finite_leases)
        write(self.root/'owned-process-registry.json',registry)
        sequence['ownedProcessRegistrySha256']=digest((self.root/'owned-process-registry.json').read_bytes())
        write(self.root/'receipt.json',sequence)
        context=audit.lifecycle_ancestry_context(self.root,sequence)
        return sequence,context,fixture,policy

    def test_full_native_api_journal_parsers_accept_adapter_context_without_mocks(self):
        sequence,context,fixture,policy=self.real_parser_context()
        result=audit._lifecycle_ownership(self.root,sequence,fixture.rows,policy,
            scoped=False,ancestry_context=context)
        self.assertEqual(result['status'],'LIFECYCLE_RAW_AUDIT_PASS')
        self.assertEqual(result['discoveredOnlyConfirmedAbsentUnknownExit'],1)

    def test_coherently_rebound_fake_ancestry_rejected_by_actual_adapter_replay(self):
        # Establish a fully valid parser baseline first; this mutation rebinds
        # every journal/view hash but leaves the original native parent bytes.
        sys.path.insert(0,str(REPO/'tests/shell'))
        import test_lifecycle_audit_raw as full_raw
        f,p=full_raw.ancestry_fixture()
        lifecycle_audit.verify_lifecycle(f.raw,f.rows,source_commit=full_raw.Q,
            policy_sha256=full_raw.P,policy=p,controller=full_raw.ROOT,
            ancestry_samples=f.rows,ancestry_journal=f.raw)
        sequence,context,fixture,policy=self.real_parser_context(fake_chain=True)
        with self.assertRaises(ValueError):
            audit._lifecycle_ownership(self.root,sequence,fixture.rows,policy,
                scoped=False,ancestry_context=context)


if __name__=='__main__':
    unittest.main()
