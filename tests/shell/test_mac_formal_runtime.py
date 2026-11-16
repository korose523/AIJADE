"""Offline Q/B/I, deadline and unknown-observation controls; no study cases or services."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
import finite_runtime as runtime
import finite_inputs


class FormalRuntimeControls(unittest.TestCase):
    def setUp(self):
        scratch=REPO/'.runtime/tmp';scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='mac-formal-offline-',dir=scratch)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.git('init','-q');self.git('config','user.name','Offline Fixture');self.git('config','user.email','fixture@example.invalid')
        (self.repo/'source.txt').write_text('immutable Q fixture\n')
        self.q=self.commit('Q fixture')

    def tearDown(self):self.temp.cleanup()

    def git(self,*args):return subprocess.check_output(['git',*args],cwd=self.repo,stderr=subprocess.DEVNULL).decode().strip()

    def commit(self,message):
        self.git('add','.');self.git('commit','-qm',message)
        return self.git('rev-parse','HEAD')

    def data_publication(self,extra=None,declare=None):
        path='experiments/ch7/mac-formal-2026-11-16/data-publication.json'
        data={'experiments/ch7/finite-heldout/offline-fixture.json':'{"fixture":true}\n'}
        if extra:data.update(extra)
        names=sorted([path,*data]) if declare is None else declare
        manifest={'schema':'aijade.ch7.mac-data-publication.v1','implementationCommit':self.q,'addedPaths':names}
        data[path]=json.dumps(manifest)
        for name,text in data.items():
            target=self.repo/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
        return self.commit('I fixture'),path

    def build_publication(self):
        build=self.root/'build';build.mkdir()
        assembly=build/'Aijade.Tests.dll';assembly.write_bytes(('fixture 0.1.0+'+self.q).encode())
        assembly.with_suffix('.deps.json').write_text('{}')
        assembly.with_suffix('.runtimeconfig.json').write_text('{}')
        manifest={'status':'CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION','commit':self.q,
                  'assemblyInformationalVersion':'0.1.0+'+self.q,
                  'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in build.iterdir()}}
        path=self.repo/runtime.MAC_BUILD_FREEZE_PATH;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(manifest));b=self.commit('B metadata fixture')
        return assembly,path,b

    def test_safe_freeze_path(self):
        self.assertEqual(runtime.safe_relative(runtime.MAC_BUILD_FREEZE_PATH),runtime.MAC_BUILD_FREEZE_PATH)
        for value in ['../outside.json','/absolute.json','C:\\x.json','a/../b','a//b','a/./b']:
            with self.subTest(value=value),self.assertRaises(ValueError):runtime.safe_relative(value)

    def test_q_without_i_retains_legacy_identity(self):
        result=runtime.validate_repository_binding(self.repo,self.q,self.q,require_head=True)
        self.assertIsNone(result['inputPublicationCommit']);self.assertEqual(result['addedDataPaths'],[])

    def test_i_exact_declared_additions(self):
        i,path=self.data_publication()
        result=runtime.validate_repository_binding(self.repo,self.q,i,path,require_head=True)
        self.assertEqual(result['implementationCommit'],self.q);self.assertEqual(result['repositoryCommit'],i)
        self.assertEqual(result['inputPublicationCommit'],i);self.assertEqual(len(result['addedDataPaths']),2)

    def test_modified_q_is_refused(self):
        (self.repo/'source.txt').write_text('changed Q\n');i,path=self.data_publication()
        with self.assertRaisesRegex(ValueError,'modified, removed or renamed'):runtime.validate_repository_binding(self.repo,self.q,i,path)

    def test_deleted_q_is_refused(self):
        (self.repo/'source.txt').unlink();i,path=self.data_publication()
        with self.assertRaisesRegex(ValueError,'modified, removed or renamed'):runtime.validate_repository_binding(self.repo,self.q,i,path)

    def test_added_executable_i_is_refused(self):
        i,path=self.data_publication({'experiments/ch7/finite-heldout/injected.py':'raise RuntimeError()'})
        with self.assertRaisesRegex(ValueError,'file type'):runtime.validate_repository_binding(self.repo,self.q,i,path)

    def test_added_nondata_path_is_refused(self):
        i,path=self.data_publication({'src/unqualified.json':'{}'})
        with self.assertRaisesRegex(ValueError,'non-data'):runtime.validate_repository_binding(self.repo,self.q,i,path)

    def test_added_data_executable_mode_is_refused(self):
        i,path=self.data_publication()
        target=self.repo/'experiments/ch7/finite-heldout/offline-fixture.json'
        self.git('update-index','--chmod=+x',str(target.relative_to(self.repo)))
        self.git('commit','-qm','invalid executable data fixture');i=self.git('rev-parse','HEAD')
        with self.assertRaisesRegex(ValueError,'non-executable'):runtime.validate_repository_binding(self.repo,self.q,i,path)

    def test_i_requires_complete_manifest_and_clean_head(self):
        i,path=self.data_publication(declare=['experiments/ch7/mac-formal-2026-11-16/data-publication.json'])
        with self.assertRaisesRegex(ValueError,'declared additions'):runtime.validate_repository_binding(self.repo,self.q,i,path)
        with self.assertRaisesRegex(ValueError,'HEAD differs'):runtime.validate_repository_binding(self.repo,self.q,self.q,require_head=True)

    def test_explicit_new_build_freeze_and_wrong_q(self):
        assembly,manifest,b=self.build_publication()
        value=runtime.validate_build(assembly,manifest,self.q,self.repo,b,runtime.MAC_BUILD_FREEZE_PATH,True)
        self.assertEqual(value['commit'],self.q)
        with self.assertRaisesRegex(ValueError,'wrong committed build'):runtime.validate_build(assembly,manifest,'0'*40)
        with self.assertRaisesRegex(ValueError,'unsafe'):runtime.validate_build(assembly,manifest,self.q,self.repo,b,'../freeze.json')

    def test_changed_binary_or_extra_dependency_is_refused(self):
        assembly,manifest,b=self.build_publication()
        assembly.write_bytes(assembly.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'bytes changed'):runtime.validate_build(assembly,manifest,self.q,self.repo,b,runtime.MAC_BUILD_FREEZE_PATH,True)
        (assembly.parent/'unexpected.dll').write_bytes(b'fixture')
        with self.assertRaisesRegex(ValueError,'population'):runtime.validate_build(assembly,manifest,self.q,self.repo,b,runtime.MAC_BUILD_FREEZE_PATH,True)

    def test_changed_b_manifest_bytes_are_refused(self):
        assembly,manifest,b=self.build_publication()
        manifest.write_bytes(manifest.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'public build freeze differs'):
            runtime.validate_build(assembly,manifest,self.q,self.repo,b,runtime.MAC_BUILD_FREEZE_PATH,True)

    def test_fixed_phase_uses_anchored_deadlines(self):
        now=[1000.0];written=[]
        def clock():return now[0]
        def sleep(seconds):now[0]+=seconds
        def sample():now[0]+=.25;return {'fixture':True}
        samples,phase=runtime.fixed_phase(120,sample,written.append,clock,sleep)
        self.assertEqual(len(samples),60);self.assertEqual(phase['endMonotonic']-phase['startMonotonic'],120)
        self.assertEqual([s['scheduledSeconds'] for s in samples],list(range(0,120,2)))
        self.assertTrue(runtime.validate_coverage(samples,120,60)['coverageComplete'])

    def test_missing_gap_and_deadline_coverage_are_adverse(self):
        samples=[{'elapsedSeconds':float(i)} for i in range(0,120,2)]
        for bad in [samples[:-1],samples[:10]+samples[12:]]:
            with self.assertRaises(ValueError):runtime.validate_coverage(bad,120,60)
        bad=copy.deepcopy(samples);bad[5]['elapsedSeconds']=bad[4]['elapsedSeconds']
        with self.assertRaises(ValueError):runtime.validate_coverage(bad,120,60)
        bad=copy.deepcopy(samples);bad[-1]['observationDurationSeconds']=3
        with self.assertRaises(ValueError):runtime.validate_coverage(bad,120,60)

    def test_observer_validation_is_recomputed_and_rss_not_trusted(self):
        guard=types.SimpleNamespace(validate_observation=lambda policy,obs:{'status':'PASS','blockers':[],'ownedRssBytes':17})
        observation={'status':'PASS','blockers':[],'ownedProcesses':[],'processPolicySha256':'p','observerModuleSha256':'m'}
        sample={'processObservation':observation,'processPolicySha256':'p','observerModuleSha256':'m','rssBytes':17}
        with patch.dict(sys.modules,{'mac_process_guard':guard}):
            runtime.validate_mac_sample(sample,'p','m',{})
            with self.assertRaisesRegex(ValueError,'RSS'):runtime.validate_mac_sample(dict(sample,rssBytes=0),'p','m',{})
        bad=types.SimpleNamespace(validate_observation=lambda policy,obs:{'status':'UNKNOWN','blockers':['fixture']})
        with patch.dict(sys.modules,{'mac_process_guard':bad}),self.assertRaisesRegex(ValueError,'independently'):runtime.validate_mac_sample(sample,'p','m',{})

    def test_external_acceptance_exact_publication_before_construction(self):
        relative='experiments/ch7/mac-formal-2026-11-16/qualification-acceptance.json'
        value={'status':'QUALIFIED_BEFORE_FRESH_CASE_CONSTRUCTION','implementationCommit':self.q}
        raw=json.dumps(value).encode();target=self.repo/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        a=self.commit('A acceptance fixture');external=self.root/'acceptance.json';external.write_bytes(raw)
        self.git('checkout','--detach','-q',self.q)
        with patch.object(finite_inputs,'derive_suite',return_value={}) as derive:
            binding=finite_inputs.construct(self.repo,self.q,'0'*64,self.root/'no-cases',external,a,relative)
            self.assertEqual(binding['acceptancePublicationCommit'],a);derive.assert_called_once()
        self.assertFalse((self.root/'no-cases').exists())
        external.write_bytes(raw+b' ')
        with patch.object(finite_inputs,'derive_suite') as derive,self.assertRaisesRegex(ValueError,'exact Git bytes'):
            finite_inputs.construct(self.repo,self.q,'0'*64,self.root/'no-cases',external,a,relative)
        derive.assert_not_called()

    def test_unknown_observation_is_recorded_without_fabricated_rss(self):
        path=self.root/'unknown.jsonl'
        def missing():raise OSError('offline missing observation')
        monitor=runtime.MacMonitor(path,missing,lambda item:None,time.monotonic(),0).start()
        deadline=time.monotonic()+1
        while not monitor.errors and time.monotonic()<deadline:time.sleep(.005)
        with self.assertRaisesRegex(ValueError,'observation failed'):monitor.stop()
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        self.assertIn('observationError',rows[0]);self.assertNotIn('rssBytes',rows[0])

    def test_reparented_owned_identity_is_retained_until_known_absent(self):
        current={1:10.0,2:20.0}
        registry=runtime.OwnedRegistry([(1,10.0)],lookup=lambda pid:current.get(pid))
        registry.remember({'ownedProcesses':[{'pid':1,'createTime':10.0},{'pid':2,'createTime':20.0}]})
        self.assertEqual(registry.roots(),[(1,10.0),(2,20.0)])
        self.assertEqual(registry.final()['status'],'OWNED_IDENTITIES_REMAIN')
        current.pop(2)
        final=registry.final();self.assertEqual(final['status'],'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT')
        samples=[{'processObservation':{'ownedProcesses':[{'pid':1,'createTime':10.0},{'pid':2,'createTime':20.0}]}}]
        runtime.validate_owned_registry(final,samples)
        bad=copy.deepcopy(final);bad['retiredIdentities']=[]
        with self.assertRaisesRegex(ValueError,'absence proof'):runtime.validate_owned_registry(bad,samples)

    def test_pid_reuse_does_not_authorize_the_new_process(self):
        current={1:10.0,2:20.0}
        registry=runtime.OwnedRegistry([(1,10.0)],lookup=lambda pid:current.get(pid))
        registry.register(2,20.0);current[2]=21.0
        self.assertEqual(registry.roots(),[(1,10.0)])
        final=registry.final();self.assertEqual(final['retiredIdentities'][0]['status'],'PID_REUSED_OLD_IDENTITY_ABSENT')
        runtime.validate_owned_registry(final,[{'processObservation':{'ownedProcesses':[{'pid':1,'createTime':10.0}]}}])

    def test_unknown_owned_identity_cannot_retire_as_absent(self):
        def lookup(pid):
            if pid==2:raise ValueError('unknown PID fixture')
            return 10.0
        registry=runtime.OwnedRegistry([(1,10.0)],lookup=lookup);registry.register(2,20.0)
        with self.assertRaisesRegex(ValueError,'unknown PID'):registry.final()
        self.assertIn((2,20.0),registry.active)


if __name__=='__main__':unittest.main()
