"""Run current controls and unchanged historical byte assertions at actual Q4.

The old test, constants and expected ten-file population are not modified.
The historical ten-blob and 34-function claims use original Git source bytes.
Thirty-three current function bodies must still match their original constants;
the explicitly versioned cursor factory has separate current behaviour controls.
No historical golden hash is replaced to match the new implementation.
"""
import ast
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
FUNCTION_TARGET='test_mac_prefix_decision.EngineeringSourceByteControls.test_every_existing_non_dispatch_runtime_function_preserves_original_bytes'
HISTORICAL_TARGETS={TARGET,FUNCTION_TARGET}


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
    runtime_relative='experiments/ch7/finite_runtime.py'
    raw=git_file(runtime_relative)
    path=root/runtime_relative
    if path.exists():
        if path.is_symlink() or path.read_bytes()!=raw:
            raise ValueError('historical runtime materialization changed; refuse, do not repair')
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


class CurrentUnchangedFunctionBytes(unittest.TestCase):
    def runTest(self):
        module=importlib.import_module('test_mac_prefix_decision')
        expected=module.EngineeringSourceByteControls.ORIGINAL_RUNTIME_FUNCTIONS
        self.assertEqual(len(expected),34)
        body=(REPO/'experiments/ch7/finite_runtime.py').read_bytes()
        lines=body.splitlines(keepends=True)
        actual={}
        def collect(nodes,prefix=''):
            for node in nodes:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    start=min([node.lineno]+[d.lineno for d in node.decorator_list])-1
                    actual[prefix+node.name]=hashlib.sha256(b''.join(lines[start:node.end_lineno])).hexdigest()
                elif isinstance(node,ast.ClassDef):collect(node.body,prefix+node.name+'.')
        collect(ast.parse(body).body)
        changed='online_lifecycle_cursors'
        self.assertIn(changed,expected)
        self.assertNotEqual(actual.get(changed),expected[changed],
            'the new cursor factory is explicitly versioned and tested separately')
        for name,digest in expected.items():
            if name!=changed:
                with self.subTest(currentFunction=name):self.assertEqual(actual.get(name),digest)


def main():
    sys.path.insert(0,str(REPO/'tests/shell'))
    suite=unittest.defaultTestLoader.discover(str(REPO/'tests/shell'),pattern='test_mac_*.py')
    module=importlib.import_module('test_mac_prefix_decision')
    root=frozen_sources(module)
    selected=list(walk(suite))
    if any(sum(case.id()==target for case in selected)!=1 for target in HISTORICAL_TARGETS):
        raise ValueError('exactly one unchanged case for each historical byte assertion required')
    scoped=unittest.TestSuite(HistoricalBlobCase(case,module,root) if case.id() in HISTORICAL_TARGETS else case
                              for case in selected)
    scoped.addTest(CurrentUnchangedFunctionBytes())
    print('Historical ten-blob/34-function claims: exact Q4 '+Q4+
          '; current 33 unchanged bodies checked separately; new cursor factory has current controls.',flush=True)
    result=unittest.TextTestRunner(verbosity=2).run(scoped)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
