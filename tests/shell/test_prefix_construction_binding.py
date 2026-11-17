"""Binding controls with real disposable Git objects; no seed/case derivation."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments/ch7'))
import finite_construction_binding as binding
import finite_inputs
import finite_audit
from finite_runtime import MAC_LIFECYCLE_SOURCES


class PublishedConstructionBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch=ROOT/'.runtime/tmp';scratch.mkdir(parents=True,exist_ok=True)
        cls.temporary=tempfile.TemporaryDirectory(prefix='aijade-prefix-binding-control-',dir=scratch)
        cls.base=Path(cls.temporary.name);cls.repo=cls.base/'repo';cls.repo.mkdir()
        cls.git('init','-q')
        cls.git('config','user.name','AIJADE binding control')
        cls.git('config','user.email','fixture@aijade.invalid')
        sources=set(binding.EXTRA_SOURCES)|set(MAC_LIFECYCLE_SOURCES)|{
            'experiments/ch7/finite_inputs.py','experiments/ch7/finite_validate.py',
            'experiments/ch7/finite_construction_binding.py'}
        for path in sources:cls.save(path,b'CONTROL_FIXTURE_SOURCE_ONLY\n')
        cls.save(binding.PLAN,(ROOT/binding.PLAN).read_bytes())
        cls.save(binding.POLICY,cls.encode(dict(kind='mac-lifecycle-observed-idle-daemon-v3',executionDecision=binding.DECISION)))
        cls.q=cls.commit('fixture implementation; not an AIJADE qualified implementation')
        cls.sources={p:binding.digest((cls.repo/p).read_bytes()) for p in binding.source_paths(cls.repo,cls.q)}
        observers={p:cls.sources[p] for p in MAC_LIFECYCLE_SOURCES}
        build=dict(status='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION',commit=cls.q,
                   assemblyInformationalVersion='0.1.0+'+cls.q,observerSources=observers,
                   files={'Aijade.Tests.dll':'1'*64,'Aijade.Tests.deps.json':'2'*64})
        cls.save(binding.BUILD,cls.encode(build));cls.b=cls.commit('fixture build identities only; no compiled binary')
        common=dict(implementationCommit=cls.q,repositoryCommit=cls.q,buildFreezeCommit=cls.b,
                    buildFreezePath=binding.BUILD,observerSources=observers,modelRequests=0,
                    processPolicyPath=binding.POLICY,processPolicySha256=binding.digest((cls.repo/binding.POLICY).read_bytes()),
                    observerModuleSha256=observers['experiments/ch7/mac_process_guard_v3.py'])
        cls.backend=dict(modelSha256='a'*64,realGodotSha256='b'*64,godotWrapperSha256='c'*64,
            sandboxProfileSha256='d'*64,rendererSources={'fixture-source.cs':'e'*64},
            preparedRenderer={'status':'PREBUILT_NO_RUNTIME_REBUILD',
                'files':{'.godot/fixture-renderer.dll':'f'*64},'fixtureNumericMetadata':1.0},
            binaries=copy.deepcopy(build['files']),buildManifestSha256=binding.digest(cls.encode(build)),
            benchSha256='3'*64,
            earlierSourceFreezeSha256=cls.sources['experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'],
            databaseContainer='fixture-qualified-database',explicitDockerPath='/fixture/qualified/docker')
        input_identity=dict(common,codeCommit=cls.q,purpose='qualification_only',
                            executionPlanSha256=binding.PLAN_SHA,**cls.backend)
        sequence=dict(common,schema='aijade.ch7.finite-sequence-receipt.v1',status='COMPLETE_FINITE_SEQUENCE_OBSERVATIONS',
            purpose='qualification_only',formalHardwareQualification=False,independentHumanReview=False,
            executionPlanSha256=binding.PLAN_SHA,plannedBlocks=1,completedBlocks=1,plannedPairs=10,
            plannedConditionRows=20,completedConditionRows=20,inFlightCaseIds=[],unknownCaseIds=[],
            unattemptedCaseIds=[],dispositionErrors=[],reason=None)
        sequence_raw=cls.encode(sequence)
        audit=dict(common,schema='aijade.ch7.finite-sequence-audit.v1',status='FINITE_SEQUENCE_RAW_AUDIT_PASS',
            strictAccepted=True,purpose='qualification_only',formalHardwareQualification=False,independentHumanReview=False,
            casePairs=10,measuredConditionRows=20,freshFiniteHeldoutPairs=0,blocks=1,
            receiptSha256=binding.digest(sequence_raw),blocksFromRaw=[{'syntheticBindingFixture':True,
                'blockIndex':0,'receiptSha256':'4'*64}],
            processOwnership={'cleanupAccepted':True})
        block=dict(common,status='FINITE_DATAFLOW_AUDIT_PASS',executionPlanSha256=binding.PLAN_SHA,
            casePairs=10,measuredConditionRows=20,freshFiniteHeldoutPairs=0,processLifecycle={'cleanupAccepted':True},
            inputIdentitiesSha256=binding.digest(cls.encode(input_identity)),qualifiedBackend=copy.deepcopy(cls.backend))
        controls=dict(status='PASS',primaryUnchanged=True,ancestryContextPrimaryUnchanged=True,
            rejectedCorruptions=19,completeBaselineChecks=20,
            ancestryContextFiles={'/fixture/known-run/receipt.json':binding.digest(sequence_raw),
                                 '/fixture/known-run/block-1/receipt.json':'4'*64},
            controls=[dict(control=n,rejected=True,reason='Synthetic binding fixture, no empirical control run') for n in binding.CONTROL_NAMES])
        cls.records=dict(sequenceReceipt=sequence,sequenceAudit=audit,blockAudit=block,
                         blockInputIdentities=input_identity,corruptionControls=controls)
        cls.acceptance=dict(schema='aijade.ch7.prefix-qualification-acceptance.v1',
            status='QUALIFIED_BEFORE_FRESH_CASE_CONSTRUCTION',executionDecision=binding.DECISION,
            implementationCommit=cls.q,buildFreezeCommit=cls.b,buildFreezePath=binding.BUILD,
            buildManifestSha256=binding.digest(cls.encode(build)),executionPlanSha256=binding.PLAN_SHA,
            acceptedAt='2026-11-17T00:00:00+00:00',formalHardwareQualification=False,independentHumanReview=False,
            authorApproval=False,heldoutComparisonComplete=False,seedConstructed=False)
        cls.freeze=dict(schema='aijade.ch7.prefix-construction-freeze.v1',executionDecision=binding.DECISION,
            constructionFreezeCommit=cls.q,executionPlanSha256=binding.PLAN_SHA,buildFreezeCommit=cls.b,
            buildFreezePath=binding.BUILD,frozenAt='2026-11-17T00:01:00+00:00',modelSha256='a'*64,
            qualifiedBackend=copy.deepcopy(cls.backend),
            sources=cls.sources,candidateBankSha256=cls.sources['experiments/ch7/finite-heldout/candidate-bank.json'])
        cls.original_binding=cls.publish(cls.records,cls.acceptance,cls.freeze)
        cls.cf=cls.original_binding['constructionFreezePublicationCommit']

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    @classmethod
    def git(cls,*args):
        return subprocess.check_output(['git','-c','commit.gpgsign=false',*args],cwd=cls.repo,stderr=subprocess.PIPE)

    @staticmethod
    def encode(value):return (json.dumps(value,indent=2)+'\n').encode()

    @classmethod
    def save(cls,path,raw):
        target=cls.repo/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)

    @classmethod
    def commit(cls,message):
        cls.git('add','--all');cls.git('commit','--allow-empty','-qm',message)
        return cls.git('rev-parse','HEAD').decode().strip()

    @classmethod
    def publish(cls,records,acceptance,freeze,*,rebind=True):
        records=copy.deepcopy(records);acceptance=copy.deepcopy(acceptance);freeze=copy.deepcopy(freeze);refs={}
        if rebind:
            sequence_sha=binding.digest(cls.encode(records['sequenceReceipt']))
            records['sequenceAudit']['receiptSha256']=sequence_sha
            records['blockAudit']['inputIdentitiesSha256']=binding.digest(cls.encode(records['blockInputIdentities']))
            context=records['corruptionControls'].get('ancestryContextFiles',{})
            if '/fixture/known-run/receipt.json' in context:context['/fixture/known-run/receipt.json']=sequence_sha
            if '/fixture/known-run/block-1/receipt.json' in context:
                context['/fixture/known-run/block-1/receipt.json']=records['sequenceAudit']['blocksFromRaw'][0].get('receiptSha256')
        for name,value in records.items():
            path=binding.PREFIX+'fixture-evidence/'+name+'.json';raw=cls.encode(value);cls.save(path,raw)
            refs[name]=dict(path=path,sha256=binding.digest(raw),sizeBytes=len(raw))
        acceptance['evidence']=refs;raw=cls.encode(acceptance);cls.save(binding.ACCEPTANCE,raw)
        a=cls.commit('synthetic qualification-binding fixture, no experiment')
        result=dict(schema='aijade.ch7.published-construction-binding.v1',executionDecision=binding.DECISION,
            implementationCommit=cls.q,acceptancePublicationCommit=a,acceptanceRepositoryPath=binding.ACCEPTANCE,
            acceptanceSha256=binding.digest(raw))
        freeze['qualificationAcceptance']={k:result[k] for k in ('acceptancePublicationCommit','acceptanceRepositoryPath','acceptanceSha256')}
        raw=cls.encode(freeze);cls.save(binding.FREEZE,raw)
        cf=cls.commit('synthetic construction-freeze fixture, no seed')
        result.update(constructionFreezePublicationCommit=cf,constructionFreezeRepositoryPath=binding.FREEZE,
                      constructionFreezeSha256=binding.digest(raw))
        return result

    def setUp(self):self.git('checkout','-qf','--detach',self.cf)

    def valid(self):
        return binding.verify_binding(self.repo,self.q,self.original_binding,'a'*64)

    def test_complete_public_objects_are_bound_before_any_derivation(self):
        self.assertEqual(self.valid()['sources'],self.sources)
        accepted=binding.accepted_qualification(self.repo,self.q,
            self.original_binding['acceptancePublicationCommit'],binding.ACCEPTANCE,
            self.original_binding['acceptanceSha256'])
        self.assertTrue(binding.typed_equal(accepted['qualifiedBackend'],self.backend))
        self.assertNotIn('selectionSha256',accepted['qualifiedBackend'])

    def test_p4_block_export_binds_original_raw_bytes_and_audited_identity(self):
        directory=self.base/'offline-block-export';directory.mkdir(exist_ok=True)
        identity=copy.deepcopy(self.records['blockInputIdentities'])
        identity['selectionSha256']='9'*64
        raw=self.encode(identity);path=directory/'input-identities.json';path.write_bytes(raw)
        exported=finite_audit.prefix_backend_evidence(directory,identity)
        self.assertEqual(exported['inputIdentitiesSha256'],binding.digest(raw))
        self.assertTrue(binding.typed_equal(exported['qualifiedBackend'],self.backend))
        path.write_bytes(raw+b' ')
        self.assertNotEqual(finite_audit.prefix_backend_evidence(directory,identity)['inputIdentitiesSha256'],
                            exported['inputIdentitiesSha256'])
        changed=copy.deepcopy(identity);changed['modelSha256']='9'*64
        path.write_bytes(self.encode(changed))
        with self.assertRaisesRegex(ValueError,'changed during offline audit'):
            finite_audit.prefix_backend_evidence(directory,identity)

    def test_actual_formal_backend_is_compared_to_qualified_cf_after_raw_audit(self):
        directory=self.base/'offline-formal-export';directory.mkdir(exist_ok=True)
        identity=copy.deepcopy(self.records['blockInputIdentities'])
        path=directory/'input-identities.json';path.write_bytes(self.encode(identity))
        original=finite_audit.prefix_backend_evidence(directory,identity,expected_backend=self.backend)
        self.assertTrue(binding.typed_equal(original['qualifiedBackend'],self.backend))
        for field in ('realGodotSha256','modelSha256','explicitDockerPath','databaseContainer'):
            changed=copy.deepcopy(identity)
            if field=='explicitDockerPath':changed[field]='/fixture/another/docker'
            elif field=='databaseContainer':changed[field]='another-database'
            else:changed[field]='9'*64
            path.write_bytes(self.encode(changed))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'actual formal backend differs'):
                finite_audit.prefix_backend_evidence(directory,changed,expected_backend=self.backend)

    def test_another_valid_complete_controls_run_cannot_qualify_this_attempt(self):
        self.valid()
        records=copy.deepcopy(self.records)
        other=records['corruptionControls']
        other['ancestryContextFiles']={'/fixture/another-run/receipt.json':'7'*64,
            '/fixture/another-run/block-1/receipt.json':'8'*64}
        # The complete nineteen-control report is independently associated with
        # that other run; only using it for our accepted run is invalid.
        binding.control_attempt_binding(other,'7'*64,'8'*64)
        changed=self.publish(records,self.acceptance,self.freeze,rebind=False)
        with self.assertRaisesRegex(ValueError,'different sequence/block attempt'):
            binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_controls_mother_block_hash_and_parent_directory_are_both_bound(self):
        for mode in ('mother','block','different-parent','missing'):
            with self.subTest(mode=mode):
                self.git('checkout','-qf','--detach',self.cf);self.valid();records=copy.deepcopy(self.records)
                context=records['corruptionControls']['ancestryContextFiles']
                if mode=='mother':context['/fixture/known-run/receipt.json']='7'*64
                elif mode=='block':context['/fixture/known-run/block-1/receipt.json']='8'*64
                elif mode=='different-parent':
                    context['/fixture/another-parent/block-1/receipt.json']=context.pop('/fixture/known-run/block-1/receipt.json')
                else:records['corruptionControls'].pop('ancestryContextFiles')
                changed=self.publish(records,self.acceptance,self.freeze,rebind=False)
                with self.assertRaisesRegex(ValueError,'ancestry context|different sequence/block attempt'):
                    binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_coherent_cf_backend_and_asset_replacement_cannot_change_known_backend(self):
        for key in binding.BACKEND_FIELDS:
            with self.subTest(field=key):
                self.git('checkout','-qf','--detach',self.cf);self.valid();freeze=copy.deepcopy(self.freeze)
                backend=freeze['qualifiedBackend'];value=backend[key];caller='a'*64
                if key=='modelSha256':backend[key]=freeze['modelSha256']=caller='9'*64
                elif key=='databaseContainer':backend[key]='another-qualified-database'
                elif key=='explicitDockerPath':backend[key]='/fixture/another/docker'
                elif key=='preparedRenderer':backend[key]['files']['.godot/fixture-renderer.dll']='9'*64
                elif type(value) is dict:backend[key][next(iter(value))]='9'*64
                else:backend[key]='9'*64
                changed=self.publish(self.records,self.acceptance,freeze)
                with self.assertRaisesRegex(ValueError,'qualified actual backend or asset'):
                    binding.verify_binding(self.repo,self.q,changed,caller)

    def test_backend_types_cannot_be_equal_only_through_python_numeric_coercion(self):
        self.valid();freeze=copy.deepcopy(self.freeze)
        freeze['qualifiedBackend']['preparedRenderer']['fixtureNumericMetadata']=1
        self.assertEqual(freeze['qualifiedBackend'],self.backend)
        self.assertFalse(binding.typed_equal(freeze['qualifiedBackend'],self.backend))
        changed=self.publish(self.records,self.acceptance,freeze)
        with self.assertRaisesRegex(ValueError,'qualified actual backend or asset'):
            binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_actual_input_identity_publication_and_new_audit_export_are_required(self):
        for mode in ('missing-ref','hash','missing-backend','backend-mismatch'):
            with self.subTest(mode=mode):
                self.git('checkout','-qf','--detach',self.cf);self.valid();records=copy.deepcopy(self.records)
                if mode=='missing-ref':records.pop('blockInputIdentities')
                elif mode=='hash':records['blockAudit']['inputIdentitiesSha256']='9'*64
                elif mode=='missing-backend':records['blockAudit'].pop('qualifiedBackend')
                else:records['blockAudit']['qualifiedBackend']['modelSha256']='9'*64
                if mode=='missing-ref':
                    # Build the deliberately incomplete public A directly;
                    # the ordinary fixture publisher expects all five refs.
                    value=copy.deepcopy(self.acceptance);value['evidence']={}
                    for name,record in records.items():
                        path=binding.PREFIX+'fixture-evidence/'+name+'.json';raw=self.encode(record);self.save(path,raw)
                        value['evidence'][name]=dict(path=path,sha256=binding.digest(raw),sizeBytes=len(raw))
                    raw=self.encode(value);self.save(binding.ACCEPTANCE,raw);a=self.commit('missing identity reference fixture')
                    changed=dict(self.original_binding,acceptancePublicationCommit=a,acceptanceSha256=binding.digest(raw))
                else:changed=self.publish(records,self.acceptance,self.freeze,rebind=False)
                with self.assertRaises(ValueError):binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_coherently_rebound_input_identity_still_requires_actual_q_b_p4_and_sources(self):
        for key,value in [('implementationCommit','0'*40),('repositoryCommit','0'*40),
                          ('buildFreezeCommit','0'*40),('executionPlanSha256','0'*64),
                          ('processPolicySha256','0'*64),('observerSources',{})]:
            with self.subTest(field=key):
                self.git('checkout','-qf','--detach',self.cf);self.valid();records=copy.deepcopy(self.records)
                records['blockInputIdentities'][key]=value
                changed=self.publish(records,self.acceptance,self.freeze)
                with self.assertRaisesRegex(ValueError,'input identity|policy/source generation'):
                    binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_even_coherent_audit_identity_and_cf_cannot_substitute_published_b_files(self):
        for key in ('binaries','buildManifestSha256'):
            with self.subTest(field=key):
                self.git('checkout','-qf','--detach',self.cf);self.valid()
                records=copy.deepcopy(self.records);freeze=copy.deepcopy(self.freeze)
                replacement={'Aijade.Tests.dll':'9'*64} if key=='binaries' else '9'*64
                records['blockInputIdentities'][key]=replacement
                records['blockAudit']['qualifiedBackend'][key]=replacement
                freeze['qualifiedBackend'][key]=replacement
                changed=self.publish(records,self.acceptance,freeze)
                with self.assertRaisesRegex(ValueError,'published B files'):
                    binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_closed_backend_tuple_rejects_missing_extra_and_invalid_types(self):
        self.valid()
        for mode in ('missing','extra','bool-hash','empty-files','bad-status','nonfinite'):
            value=copy.deepcopy(self.backend)
            if mode=='missing':value.pop('realGodotSha256')
            elif mode=='extra':value['selectionSha256']='9'*64
            elif mode=='bool-hash':value['modelSha256']=True
            elif mode=='empty-files':value['binaries']={}
            elif mode=='bad-status':value['preparedRenderer']['status']='REBUILT_DURING_WINDOW'
            else:value['preparedRenderer']['fixtureNumericMetadata']=float('inf')
            with self.subTest(mode=mode),self.assertRaises(ValueError):binding.qualified_backend(value,closed=True)

    def test_status_alone_cannot_replace_complete_evidence(self):
        self.valid();value=copy.deepcopy(self.acceptance);value['evidence']={}
        raw=self.encode(value);self.save(binding.ACCEPTANCE,raw);a=self.commit('fixture missing actual audit references')
        changed=dict(self.original_binding,acceptancePublicationCommit=a,acceptanceSha256=binding.digest(raw))
        with self.assertRaisesRegex(ValueError,'complete qualification evidence'):
            binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_real_success_schema_may_omit_adverse_only_disposition_errors(self):
        self.valid();records=copy.deepcopy(self.records)
        records['sequenceReceipt'].pop('dispositionErrors')
        records['sequenceAudit']['receiptSha256']=binding.digest(self.encode(records['sequenceReceipt']))
        changed=self.publish(records,self.acceptance,self.freeze)
        self.assertEqual(binding.verify_binding(self.repo,self.q,changed,'a'*64)['constructionFreezeCommit'],self.q)
        for value in (None,['fixture-unresolved']):
            self.git('checkout','-qf','--detach',self.cf);self.valid();records=copy.deepcopy(self.records)
            records['sequenceReceipt']['dispositionErrors']=value
            records['sequenceAudit']['receiptSha256']=binding.digest(self.encode(records['sequenceReceipt']))
            changed=self.publish(records,self.acceptance,self.freeze)
            with self.assertRaisesRegex(ValueError,'disposition errors'):
                binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_coherently_rebound_bad_known_audits_are_rejected(self):
        mutations=(('sequenceReceipt','completedConditionRows',19),('sequenceReceipt','plannedPairs',True),
            ('sequenceReceipt','unknownCaseIds',['fixture-unknown']),('sequenceReceipt','executionPlanSha256','0'*64),
            ('sequenceAudit','measuredConditionRows',19),('sequenceAudit','strictAccepted',1),
            ('sequenceAudit','purpose','confirmed_finite_heldout'),('sequenceAudit','freshFiniteHeldoutPairs',1),
            ('blockAudit','casePairs',9),('blockAudit','processLifecycle',{'cleanupAccepted':False}),
            ('corruptionControls','completeBaselineChecks',19),('corruptionControls','rejectedCorruptions',True),
            ('corruptionControls','primaryUnchanged',False),('corruptionControls','ancestryContextPrimaryUnchanged',False))
        for name,key,value in mutations:
            with self.subTest(name=name,key=key):
                self.git('checkout','-qf','--detach',self.cf);self.valid()
                records=copy.deepcopy(self.records);records[name][key]=value
                if name=='sequenceReceipt':
                    records['sequenceAudit']['receiptSha256']=binding.digest(self.encode(records[name]))
                changed=self.publish(records,self.acceptance,self.freeze)
                with self.assertRaises((ValueError,KeyError,TypeError)):
                    binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_control_name_omission_and_duplicate_rebound(self):
        for mode in ('missing','duplicate','not-rejected'):
            self.git('checkout','-qf','--detach',self.cf);self.valid();records=copy.deepcopy(self.records)
            rows=records['corruptionControls']['controls']
            if mode=='missing':rows.pop()
            elif mode=='duplicate':rows[-1]=copy.deepcopy(rows[0])
            else:rows[0]['rejected']=False
            changed=self.publish(records,self.acceptance,self.freeze)
            with self.assertRaisesRegex(ValueError,'nineteen'):
                binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_closed_binding_missing_extra_and_wrong_identities(self):
        self.valid()
        for key in self.original_binding:
            changed=dict(self.original_binding);changed.pop(key)
            with self.assertRaises(ValueError):binding.verify_binding(self.repo,self.q,changed,'a'*64)
        for key,value in (('extra',True),('executionDecision','unknown'),('implementationCommit','0'*40),
                          ('constructionFreezeRepositoryPath','../escape.json'),('constructionFreezeSha256','0'*64)):
            changed=dict(self.original_binding);changed[key]=value
            with self.assertRaises(ValueError):binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_source_omission_asset_and_chronology_cannot_be_rebound(self):
        for mode in ('source','model','early-freeze','bank'):
            self.git('checkout','-qf','--detach',self.cf);self.valid();freeze=copy.deepcopy(self.freeze)
            if mode=='source':freeze['sources'].pop('experiments/ch7/finite_inputs.py')
            elif mode=='model':freeze['modelSha256']='b'*64
            elif mode=='early-freeze':freeze['frozenAt']='2026-11-16T00:00:00+00:00'
            else:freeze['candidateBankSha256']='0'*64
            changed=self.publish(self.records,self.acceptance,freeze)
            with self.assertRaises(ValueError):binding.verify_binding(self.repo,self.q,changed,'a'*64)

    def test_working_source_change_refuses_same_public_freeze(self):
        self.valid();self.save('experiments/ch7/finite_inputs.py',b'changed fixture source\n')
        with self.assertRaisesRegex(ValueError,'construction source differs'):
            binding.verify_binding(self.repo,self.q,self.original_binding,'a'*64)

    def test_new_q_requires_sidecar_and_never_falls_back_to_legacy(self):
        inputs=self.base/'missing-sidecar';inputs.mkdir(exist_ok=True)
        with self.assertRaisesRegex(ValueError,'missing its published construction binding'):
            binding.load_construction_freeze(self.repo,self.q,inputs,'a'*64)

    def test_new_construct_rejects_missing_gate_before_derive(self):
        self.git('checkout','-qf','--detach',self.q)
        with patch.object(finite_inputs,'derive_suite',side_effect=AssertionError('no real seed allowed')) as derive:
            with self.assertRaisesRegex(ValueError,'public A and construction-freeze'):
                finite_inputs.construct(self.repo,self.q,'a'*64,self.base/'no-output')
            derive.assert_not_called()

    def test_bound_construct_reserves_single_output_without_real_seed(self):
        self.git('checkout','-qf','--detach',self.q)
        sidecar=self.base/'binding-input.json';sidecar.write_bytes(self.encode(self.original_binding))
        output=self.base/'one-fixture-output'
        # Map only the production Mac boundary to this disposable fixture for
        # portable Linux CI; production path validation remains unchanged.
        def fixture_path(value):
            return self.base if str(value)=='/Volumes/Untitled/AIJADE' else Path(value)
        with patch.object(finite_inputs,'Path',side_effect=fixture_path), \
             patch.object(finite_inputs,'derive_suite',return_value={'fixture-only.json':{'synthetic':True}}) as derive:
            result=finite_inputs.construct(self.repo,self.q,'a'*64,output,construction_binding_path=sidecar)
            self.assertTrue(result['seedDerivedOnlyAfterPublishedConstructionFreeze'])
            self.assertEqual(binding.decode((output/binding.SIDECAR).read_bytes()),self.original_binding)
            derive.assert_called_once()
            with self.assertRaisesRegex(ValueError,'single use'):
                finite_inputs.construct(self.repo,self.q,'a'*64,output,construction_binding_path=sidecar)
            self.assertEqual(derive.call_count,1)

    def test_duplicate_json_and_nonfinite_refuse(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
            with self.assertRaises(ValueError):binding.decode(raw)


if __name__=='__main__':unittest.main()
