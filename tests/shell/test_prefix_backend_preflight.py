"""Synthetic CF file fixtures only; no renderer/SDK/model/process invocation."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT
import sys
sys.path.insert(0,str(ROOT/'experiments/ch7'))
import finite_construction_binding as candidate
collect=candidate.current_backend_before_measurement


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def encode(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def typed(a,b):return json.dumps(a,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(b,sort_keys=True,separators=(',',':'),allow_nan=False)


class CurrentBackendSyntheticControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch=ROOT/'.runtime/tmp';scratch.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(prefix='synthetic-cf-backend-',dir=scratch)
        cls.root=Path(cls.temp.name);cls.repo=cls.root/'repo';cls.client=cls.root/'synthetic-client'
        def put(path,raw):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);return path
        cls.put=staticmethod(put)
        rows=[]
        for i in range(331):
            path=put(cls.repo/('src/synthetic-protected-%03d.txt'%i),('SYNTHETIC_PROTECTED_FILE_%d\n'%i).encode())
            rows.append(dict(path=path.relative_to(cls.repo).as_posix(),bytes=path.stat().st_size,
                             sha256=sha(path),gitBlobSha1='1'*40))
        cls.freeze=put(cls.repo/'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json',
                       encode(dict(schema='SYNTHETIC_SOURCE_FREEZE_NOT_AN_ACTUAL_STUDY',files=rows)))
        cls.bench=put(cls.repo/'src/Aijade.Research/SkillBench/bench-data.json',b'{"syntheticFixture":true}\n')
        cls.wrapper=put(cls.repo/'synthetic-godot-wrapper.py',b'# SYNTHETIC_NOT_EXECUTED\n')
        cls.engine=put(cls.root/'synthetic-engine-not-executable',b'SYNTHETIC_GODOT_BYTES_NO_SDK\n')
        cls.profile=put(cls.root/'synthetic-sandbox.sb',b'; SYNTHETIC_PROFILE_NOT_EXECUTED\n')
        cls.model=put(cls.root/'synthetic-model.fake',b'SYNTHETIC_ASSET_NOT_A_MODEL\n')
        cls.assembly=put(cls.root/'synthetic-binaries/Aijade.Tests.dll',b'SYNTHETIC_DLL_NOT_EXECUTABLE\n')
        deps=put(cls.assembly.parent/'Aijade.Tests.deps.json',b'{"syntheticDependency":true}\n')
        cls.build=dict(status='SYNTHETIC_BUILD_NOT_A_REAL_FREEZE',files={p.name:sha(p) for p in [cls.assembly,deps]})
        cls.build_manifest=put(cls.root/'synthetic-build-manifest.json',encode(cls.build))
        put(cls.client/'project.godot',b'; SYNTHETIC_PROJECT_NO_ENGINE_CALL\n')
        put(cls.client/'src/client.cs',b'// SYNTHETIC_SOURCE_NO_BUILD\n')
        runtime=put(cls.client/'.godot/runtime.dll',b'SYNTHETIC_PREPARED_DLL_NOT_EXECUTABLE\n')
        for name in ('.git/noise','.svn/noise','__pycache__/noise','.godot/cache.txt','bin/cache.txt','obj/cache.txt'):
            put(cls.client/name,b'SYNTHETIC_IGNORED_CACHE\n')
        cls.marker=put(cls.client/'aijade-prepared-renderer.json',encode(dict(status='PREBUILT_NO_RUNTIME_REBUILD',
            files={'.godot/runtime.dll':sha(runtime)},syntheticFixture=True,fixtureNumericMetadata=1.0)))
        cls.args=SimpleNamespace(assembly=cls.assembly,build_manifest=cls.build_manifest,client=cls.client,
            model=cls.model,godot=cls.wrapper,db_container='synthetic-db-not-running',
            docker=Path('/synthetic/not-executed/docker'))
        cls.model_sha=sha(cls.model)
        with patch.dict(os.environ,{'AIJADE_REAL_GODOT':str(cls.engine),'AIJADE_GODOT_SANDBOX_PROFILE':str(cls.profile)}):
            cls.baseline=collect(cls.repo,cls.args,cls.build,cls.model_sha)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.changed={};self.created=[];self.args=copy.copy(self.__class__.args);self.build=copy.deepcopy(self.__class__.build)
        self.env=patch.dict(os.environ,{'AIJADE_REAL_GODOT':str(self.engine),'AIJADE_GODOT_SANDBOX_PROFILE':str(self.profile)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.no_process=patch.object(subprocess,'Popen',side_effect=AssertionError('no process invocation permitted'))
        self.no_process.start()
        self.addCleanup(self.no_process.stop)
        self.assertTrue(typed(self.current(),self.baseline),'complete real-hash baseline must pass before each mutation')

    def tearDown(self):
        for path in self.created:
            if path.exists() or path.is_symlink():path.unlink()
        for path,raw in self.changed.items():
            if path.is_symlink():path.unlink()
            path.write_bytes(raw)
        self.no_process.stop();self.env.stop()

    def mutate(self,path,raw):
        if path not in self.changed:self.changed[path]=path.read_bytes()
        path.write_bytes(raw)

    def current(self,model_sha=None):return collect(self.repo,self.args,self.build,model_sha or self.model_sha)

    def assert_drift_rejected(self):
        # This is the exact required CF caller comparison, not a fake qualified
        # study record. The collector cannot know a prior accepted container.
        try:actual=self.current()
        except (ValueError,OSError,KeyError):return
        self.assertFalse(typed(actual,self.baseline),'changed actual backend must not match the frozen tuple')

    def test_closed12_fields_match_current_source_declaration(self):
        path=ROOT/'experiments/ch7/finite_construction_binding.py'
        tree=ast.parse(path.read_bytes());node=next(n for n in tree.body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name)and t.id=='BACKEND_FIELDS' for t in n.targets))
        self.assertEqual(set(self.current()),set(ast.literal_eval(node.value)))
        self.assertIs(type(self.current()['preparedRenderer']['fixtureNumericMetadata']),float)

    def test_measurement_entry_requires_actual_arguments_and_all_twelve_fields(self):
        freeze=dict(schema='aijade.ch7.prefix-construction-freeze.v1',qualifiedBackend=self.baseline)
        with patch.object(candidate,'load_construction_freeze',return_value=freeze):
            for args,build in ((None,self.build),(self.args,None)):
                with self.assertRaisesRegex(ValueError,'mandatory before measurement'):
                    candidate.load_measurement_construction_freeze(self.repo,'fixture-Q',self.root,
                                                                  self.model_sha,args,build)
            self.assertEqual(candidate.load_measurement_construction_freeze(self.repo,'fixture-Q',self.root,
                self.model_sha,self.args,self.build),freeze)
            self.mutate(self.engine,b'SYNTHETIC_CHANGED_ENGINE_NOT_EXECUTED\n')
            with self.assertRaisesRegex(ValueError,'before measurement differs'):
                candidate.load_measurement_construction_freeze(self.repo,'fixture-Q',self.root,
                    self.model_sha,self.args,self.build)

    def test_offline_metadata_loader_is_not_used_as_the_measurement_entry(self):
        runner=(ROOT/'experiments/ch7/run_finite_block.py').read_text()
        self.assertIn('from finite_construction_binding import load_measurement_construction_freeze',runner)
        self.assertIn('sha(args.model),args,build)',runner)
        with patch.object(candidate,'load_construction_freeze',return_value={'legacyFixture':True}), \
             patch.object(candidate,'current_backend_before_measurement',side_effect=AssertionError('legacy fixture must retain old path')):
            self.assertEqual(candidate.load_measurement_construction_freeze(self.repo,'legacy-fixture-Q',self.root,
                None,None,None),{'legacyFixture':True})

    def test_sources_equal_actual_copytree_then_original_rglob_filter(self):
        copied=self.root/'synthetic-reference-copy'
        shutil.copytree(self.client,copied,ignore=shutil.ignore_patterns('.git','.svn','__pycache__'))
        try:
            reference={p.relative_to(copied).as_posix():sha(p) for p in copied.rglob('*') if p.is_file()
                and not {'.godot','bin','obj','__pycache__'}&set(p.relative_to(copied).parts)}
            self.assertEqual(self.current()['rendererSources'],reference)
            self.assertEqual(len(reference),3)
            self.assertNotIn('.godot/runtime.dll',reference)
        finally:shutil.rmtree(copied)

    def test_engine_bytes_drift_changes_actual_tuple(self):
        self.mutate(self.engine,b'SYNTHETIC_CHANGED_ENGINE\n');self.assert_drift_rejected()

    def test_wrapper_and_sandbox_drift_are_both_detected(self):
        self.mutate(self.wrapper,b'# SYNTHETIC_CHANGED_WRAPPER\n');self.assert_drift_rejected()
        self.mutate(self.profile,b'; SYNTHETIC_CHANGED_PROFILE\n');self.assert_drift_rejected()

    def test_marker_entire_json_and_float_type_are_not_normalized(self):
        marker=json.loads(self.marker.read_bytes());marker['fixtureNumericMetadata']=1
        self.mutate(self.marker,encode(marker));self.assert_drift_rejected()

    def test_prepared_runtime_dll_bytes_must_match_actual_marker(self):
        self.mutate(self.client/'.godot/runtime.dll',b'SYNTHETIC_CHANGED_RUNTIME_DLL\n')
        with self.assertRaisesRegex(ValueError,'prepared renderer file changed'):self.current()

    def test_coherently_rebound_runtime_and_marker_still_change_cf_tuple(self):
        dll=self.client/'.godot/runtime.dll';self.mutate(dll,b'SYNTHETIC_CHANGED_AND_REBOUND\n')
        marker=json.loads(self.marker.read_bytes());marker['files']['.godot/runtime.dll']=sha(dll)
        self.mutate(self.marker,encode(marker));self.assert_drift_rejected()

    def test_client_source_population_and_protected331_drift_are_not_cached(self):
        path=self.client/'new-synthetic-source.cs';path.write_bytes(b'// SYNTHETIC_EXTRA\n');self.created.append(path)
        self.assert_drift_rejected()
        self.mutate(self.repo/'src/synthetic-protected-000.txt',b'SYNTHETIC_PROTECTED_DRIFT\n')
        with self.assertRaisesRegex(ValueError,'prior protected source changed'):self.current()

    def test_actual_binaries_are_checked_from_assembly_parent(self):
        self.mutate(self.assembly,b'SYNTHETIC_RUNTIME_DLL_DRIFT\n')
        with self.assertRaisesRegex(ValueError,'published binary bytes changed'):self.current()

    def test_build_object_must_equal_entire_actual_build_manifest(self):
        self.build['files']['Aijade.Tests.dll']='f'*64
        with self.assertRaisesRegex(ValueError,'build object differs'):self.current()

    def test_container_and_docker_identity_drift_are_cf_mismatches(self):
        self.args.db_container='synthetic-other-db';self.assert_drift_rejected()
        self.args.db_container=self.__class__.args.db_container
        self.args.docker=Path('/synthetic/other/not-executed/docker');self.assert_drift_rejected()

    def test_model_and_bench_actual_bytes_are_bound(self):
        self.mutate(self.model,b'SYNTHETIC_CHANGED_ASSET\n')
        with self.assertRaisesRegex(ValueError,'runner model SHA'):self.current()
        actual=self.current(model_sha=sha(self.model));self.assertFalse(typed(actual,self.baseline))
        self.mutate(self.model,b'SYNTHETIC_ASSET_NOT_A_MODEL\n')
        self.mutate(self.bench,b'{"syntheticBenchChanged":true}\n');self.assert_drift_rejected()

    def test_incomplete331_population_and_boolean_size_refuse(self):
        freeze=json.loads(self.freeze.read_bytes());freeze['files'].pop();self.mutate(self.freeze,encode(freeze))
        with self.assertRaisesRegex(ValueError,'prior331'):self.current()
        freeze=json.loads(self.changed[self.freeze]);freeze['files'][0]['bytes']=True
        self.mutate(self.freeze,encode(freeze))
        with self.assertRaisesRegex(ValueError,'size/Git identity type'):self.current()

    def test_unsafe_relative_paths_and_linked_data_refuse(self):
        marker=json.loads(self.marker.read_bytes());marker['files']={'../synthetic-model.fake':'f'*64}
        self.mutate(self.marker,encode(marker))
        with self.assertRaisesRegex(ValueError,'relative file path'):self.current()
        self.marker.write_bytes(self.changed[self.marker])
        original=self.engine.read_bytes();self.changed[self.engine]=original;self.engine.unlink();self.engine.symlink_to(self.model)
        with self.assertRaisesRegex(ValueError,'linked data path'):self.current()

    def test_file_mutation_during_read_is_not_an_old_digest_pass(self):
        original=os.fstat;calls=[0]
        def changed_during_read(fd):
            calls[0]+=1
            if calls[0]==2:
                self.mutate(self.build_manifest,self.build_manifest.read_bytes()+b' ')
                current=self.build_manifest.stat();os.utime(self.build_manifest,ns=(current.st_atime_ns,current.st_mtime_ns+1000000))
            return original(fd)
        with patch.object(os,'fstat',side_effect=changed_during_read):
            with self.assertRaisesRegex(ValueError,'file changed during read'):self.current()

    def test_directory_as_data_refuses_without_leaking_the_open_descriptor(self):
        self.args.godot=self.root;opened=[];original=os.open
        def opening(path,*args,**kwargs):
            fd=original(path,*args,**kwargs)
            if Path(path)==self.root:opened.append(fd)
            return fd
        with patch.object(os,'open',side_effect=opening):
            with self.assertRaises((ValueError,OSError)):self.current()
        self.assertEqual(len(opened),1)
        with self.assertRaises(OSError):os.fstat(opened[0])

    def test_duplicate_marker_json_is_not_silently_last_value_wins(self):
        self.mutate(self.marker,b'{"status":"PREBUILT_NO_RUNTIME_REBUILD","status":"PREBUILT_NO_RUNTIME_REBUILD","files":{}}')
        with self.assertRaisesRegex(ValueError,'duplicate JSON key'):self.current()


if __name__=='__main__':unittest.main(verbosity=2)
