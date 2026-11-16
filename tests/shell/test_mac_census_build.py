"""Native source/bytes/B binding corruption controls; no native invocation."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO/'experiments/ch7'))
import finite_runtime as r
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
class NativeBuildBinding(unittest.TestCase):
    def setUp(self):
        tmp=REPO/'.runtime/tmp';tmp.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=tmp);self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.git('init','-q');self.git('config','user.name','Offline Fixture');self.git('config','user.email','fixture@example.invalid')
        source=self.repo/'experiments/ch7/mac_bulk_census.c';source.parent.mkdir(parents=True);source.write_bytes(b'original fixture source')
        self.q=self.commit('Q');self.helper=self.root/'helper';self.helper.write_bytes(b'native fixture binary')
        directory=self.root/'build';directory.mkdir();self.dll=directory/'Aijade.Tests.dll';self.dll.write_bytes(('fixture 0.1.0+'+self.q).encode())
        self.dll.with_suffix('.deps.json').write_bytes(b'{}');self.dll.with_suffix('.runtimeconfig.json').write_bytes(b'{}')
        self.data=dict(status='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION',commit=self.q,assemblyInformationalVersion='0.1.0+'+self.q,
            files={p.name:sha(p) for p in directory.iterdir()},nativeCensus=dict(path=str(self.helper),sha256=sha(self.helper),sourceSha256=sha(source)))
        self.path=self.repo/r.MAC_CENSUS_BUILD_FREEZE_PATH;self.path.parent.mkdir(parents=True);self.save();self.b=self.commit('B')
    def tearDown(self):self.temp.cleanup()
    def git(self,*args):return subprocess.check_output(['git',*args],cwd=self.repo,stderr=subprocess.DEVNULL).decode().strip()
    def commit(self,m):self.git('add','.');self.git('commit','-qm',m);return self.git('rev-parse','HEAD')
    def save(self):self.path.write_text(json.dumps(self.data))
    def validate(self):
        with patch.object(r,'PROJECT_ROOT',self.root):return r.validate_build(self.dll,self.path,self.q,self.repo,self.b,r.MAC_CENSUS_BUILD_FREEZE_PATH,True)
    def test_complete_native_binding_passes(self):self.assertEqual(self.validate()['commit'],self.q)
    def test_changed_helper_bytes_rejected(self):
        self.helper.write_bytes(b'replaced native binary')
        with self.assertRaisesRegex(ValueError,'native helper'):self.validate()
    def test_native_source_edits_rejected_even_if_helper_same(self):
        (self.repo/'experiments/ch7/mac_bulk_census.c').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source differs'):self.validate()
    def test_lexical_dotdot_escape_rejected(self):
        self.data['nativeCensus']['path']=str(self.root/'build/../helper');self.save();self.b=self.commit('invalid B')
        with self.assertRaisesRegex(ValueError,'native helper'):self.validate()
    def test_symlink_helper_rejected(self):
        link=self.root/'link';link.symlink_to(self.helper);self.data['nativeCensus']['path']=str(link);self.save();self.b=self.commit('invalid B')
        with self.assertRaisesRegex(ValueError,'native helper'):self.validate()
    def test_unpublished_native_rebinding_rejected(self):
        self.data['nativeCensus']['sha256']='0'*64;self.save()
        with self.assertRaisesRegex(ValueError,'public build freeze differs'):self.validate()
if __name__=='__main__':unittest.main()
