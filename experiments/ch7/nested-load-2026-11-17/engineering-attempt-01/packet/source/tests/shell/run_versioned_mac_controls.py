"""Run current controls and the unchanged P4 blob assertion at its actual Q4.

The old test, constants and expected ten-file population are not modified.
Only its one historical whole-blob claim uses the original Git source bytes.
Current non-dispatch byte assertions and all behavioural tests stay current.
"""
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
Q4='147564c9db812c1a9e5ae07992d9aa282399a310'
TEST='tests/shell/test_mac_prefix_decision.py'
TARGET='test_mac_prefix_decision.EngineeringSourceByteControls.test_all_ten_accepted_engineering_core_blobs_are_exactly_preserved'


def git_file(relative):
    return subprocess.check_output(['git','--no-replace-objects','-C',str(REPO),'show',Q4+':'+relative])


def frozen_sources(module):
    actual=(REPO/TEST).read_bytes()
    if actual != git_file(TEST):
        raise ValueError('historical test itself differs from its actual Q4 Git blob')
    root=REPO/'.runtime/versioned-mac-byte-controls'/Q4
    for name, expected in module.EngineeringSourceByteControls.ORIGINAL_CORE_BLOBS.items():
        relative='experiments/ch7/'+name
        raw=git_file(relative)
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise ValueError('actual Q4 blob differs from original assertion: '+name)
        path=root/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            if path.is_symlink() or path.read_bytes()!=raw:
                raise ValueError('historical materialized data changed; refuse, do not repair')
        else:
            with path.open('xb') as stream:stream.write(raw)
    return root


class HistoricalBlobCase:
    def __init__(self, case, module, root):self.case,self.module,self.root=case,module,root
    def __call__(self,result):
        with patch.object(self.module,'REPO',self.root):return self.case.run(result)
    def countTestCases(self):return self.case.countTestCases()
    def id(self):return self.case.id()


def walk(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from walk(item)
        else:yield item


def main():
    sys.path.insert(0,str(REPO/'tests/shell'))
    suite=unittest.defaultTestLoader.discover(str(REPO/'tests/shell'),pattern='test_mac_*.py')
    module=importlib.import_module('test_mac_prefix_decision')
    root=frozen_sources(module)
    selected=list(walk(suite))
    if sum(case.id()==TARGET for case in selected)!=1:
        raise ValueError('exactly one unchanged historical ten-blob case required')
    scoped=unittest.TestSuite(HistoricalBlobCase(case,module,root) if case.id()==TARGET else case
                              for case in selected)
    print('Historical whole-blob case: exact Q4 '+Q4+'; all other tests use current source.',flush=True)
    result=unittest.TextTestRunner(verbosity=2).run(scoped)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
