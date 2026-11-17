"""Run current controls and unchanged historical byte assertions at actual Q4.

The old test, constants and expected ten-file population are not modified.
The historical ten-blob and 34-function claims use original Git source bytes.
Thirty-three current function bodies must still match their original constants;
the explicitly versioned cursor factory has separate current behaviour controls.
No historical golden hash is replaced to match the new implementation.
Current E5 binary bytes and owned predicate/API claims have separate checks.
"""
import ast
import hashlib
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(os.environ.get('AIJADE_VERSIONED_CONTROL_REPO',str(Path(__file__).resolve().parents[2]))).resolve()
Q4='147564c9db812c1a9e5ae07992d9aa282399a310'
TEST='tests/shell/test_mac_prefix_decision.py'
TARGET='test_mac_prefix_decision.EngineeringSourceByteControls.test_all_ten_accepted_engineering_core_blobs_are_exactly_preserved'
FUNCTION_TARGET='test_mac_prefix_decision.EngineeringSourceByteControls.test_every_existing_non_dispatch_runtime_function_preserves_original_bytes'
HISTORICAL_TARGETS={TARGET,FUNCTION_TARGET}
CURRENT_BINARY_SHA='b87fd94186c805ca7639d3e7ac4cc2ca93c4319a194ab6c3932ee221710bc4d4'
ORIGINAL_BINARY_SHA='f2e1be6ea2adea1a5f90516c1a519cfaa1f249c2c9929a3375eb58b543a5926f'
POLICY_FIXTURE_PREFIX='test_mac_prefix_decision.PrefixQPolicyControls.'
POLICY_FIXTURE_CONFIG='configs/research/ch7-mac-prefix-v2-process-policy.json'
CURRENT_PREDICATE_AST_SHA='81f098fc92bffb77e5c1938e23b5284def002edd91ed130909ec788cafa9a343'
NATIVE_PREDICATE_AST_SHA='abc29b40650ffecaacfb3d601c2736504a06c491a1494329d494d9cdb50bb6bb'
ORIGINAL_GUARD_CORE_AST_SHA='b6bc9b54ba40d04503cbee3ad71ddfe64acdd6724abf47f8f01c50693b49c30b'


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


def current_prefix_fixture_policy(module):
    """Derive only the fresh synthetic fixture's current authenticator pin.

    The unchanged fixture copies current observer sources into its own new Git
    repository. Its retained config still names the old binary implementation.
    Current source identity is explicit here; neither original config bytes nor
    production validation is modified and no research qualification is granted.
    """
    original=module.policy
    def derived():
        value=original()
        if value['binaryAuthenticationSourceSha256']!=ORIGINAL_BINARY_SHA:
            raise ValueError('retained original policy fixture identity changed')
        current=hashlib.sha256((REPO/'experiments/ch7/binary_authentication.py').read_bytes()).hexdigest()
        if current!=CURRENT_BINARY_SHA:
            raise ValueError('current synthetic policy fixture authenticator source changed')
        value['binaryAuthenticationSourceSha256']=current
        return value
    return derived


class CurrentPrefixPolicyFixtureCase:
    def __init__(self,case,module):self.case,self.module=case,module
    def __call__(self,result):
        with patch.object(self.module,'policy',current_prefix_fixture_policy(self.module)):
            return self.case.run(result)
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


class CurrentOwnedGuardSourceControls(unittest.TestCase):
    """New-version assertions, separate from unchanged Q4 golden claims."""
    def test_current_binary_and_legacy_complete_state_sources_are_explicit(self):
        expected={'binary_authentication.py':CURRENT_BINARY_SHA,
            'process_lifecycle.py':'93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65',
            'full_state_clone_cursor.py':'0da9588655714d23db401b3424f45379689421898d85256b2506d674fee5e584'}
        for name,digest in expected.items():
            with self.subTest(currentSource=name):
                self.assertEqual(hashlib.sha256((REPO/'experiments/ch7'/name).read_bytes()).hexdigest(),digest)

    def test_current_synthetic_policy_adapter_changes_only_actual_binary_source_pin(self):
        module=importlib.import_module('test_mac_prefix_decision')
        self.assertEqual((REPO/POLICY_FIXTURE_CONFIG).read_bytes(),git_file(POLICY_FIXTURE_CONFIG))
        original=module.policy();derived=current_prefix_fixture_policy(module)()
        self.assertEqual(original['binaryAuthenticationSourceSha256'],ORIGINAL_BINARY_SHA)
        self.assertEqual(derived['binaryAuthenticationSourceSha256'],CURRENT_BINARY_SHA)
        changed={key for key in original if original[key]!=derived[key]}
        self.assertEqual(changed,{'binaryAuthenticationSourceSha256'})
        self.assertEqual(set(original),set(derived))

    def test_current_owned_predicate_and_original_full_decision_core_ast_are_pinned(self):
        tree=ast.parse((REPO/'experiments/ch7/mac_process_guard_v3.py').read_bytes())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
            and n.name=='_guard_decision_from_validated_lifecycle')
        self.assertEqual(hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest(),CURRENT_PREDICATE_AST_SHA)
        branch=next(n for n in node.body if isinstance(n,ast.Try))
        original=ast.Module(body=branch.body[3:],type_ignores=[])
        self.assertEqual(hashlib.sha256(ast.dump(original,include_attributes=False).encode()).hexdigest(),ORIGINAL_GUARD_CORE_AST_SHA)

    def test_owned_public_api_exposes_decisions_and_cold_route_remains_present(self):
        tree=ast.parse((REPO/'experiments/ch7/mac_process_guard_v3.py').read_bytes())
        public=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_observation')
        names=[arg.arg for arg in public.args.args+public.args.kwonlyargs]
        self.assertEqual(names,['policy','observation','lifecycle_journal','lifecycle_cursor'])
        calls=[n.func for n in ast.walk(public) if isinstance(n,ast.Call)]
        self.assertTrue(any(isinstance(n,ast.Attribute) and n.attr=='evaluate' for n in calls))
        self.assertTrue(any(isinstance(n,ast.Name) and n.id=='_lifecycle_view' for n in calls))
        self.assertTrue(any(isinstance(n,ast.Name) and n.id=='_guard_decision_from_validated_lifecycle' for n in calls))
        owned=ast.parse((REPO/'experiments/ch7/newowned_guard_cursor.py').read_bytes())
        owner=next(n for n in owned.body if isinstance(n,ast.ClassDef) and n.name=='OwnedGuardCursor')
        self.assertEqual(owner.bases,[])
        methods={n.name for n in owner.body if isinstance(n,ast.FunctionDef)}
        self.assertIn('evaluate',methods);self.assertNotIn('validate_view',methods)


class CurrentNativeGuardSourceControls(unittest.TestCase):
    """New native prefix assertion; the original E5 predicate remains separate."""
    def test_current_native_predicate_and_owned_constant_match_without_changing_old_core(self):
        tree=ast.parse((REPO/'experiments/ch7/mac_process_guard_v3.py').read_bytes())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                  and n.name=='_guard_decision_from_validated_lifecycle')
        self.assertEqual(hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest(),NATIVE_PREDICATE_AST_SHA)
        branch=next(n for n in node.body if isinstance(n,ast.Try))
        self.assertEqual(hashlib.sha256(ast.dump(ast.Module(body=branch.body[3:],type_ignores=[]),include_attributes=False).encode()).hexdigest(),ORIGINAL_GUARD_CORE_AST_SHA)
        owned=ast.parse((REPO/'experiments/ch7/newowned_guard_cursor.py').read_bytes())
        assignment=next(n for n in owned.body if isinstance(n,ast.Assign) and any(
            isinstance(t,ast.Name) and t.id=='GUARD_PREDICATE_AST_SHA256' for t in n.targets))
        self.assertEqual(ast.literal_eval(assignment.value),NATIVE_PREDICATE_AST_SHA)


def main():
    scratch=REPO/'.runtime/scoped-control-tmp';scratch.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(scratch);os.environ['TMPDIR']=str(scratch)
    sys.path.insert(0,str(REPO/'tests/shell'))
    suite=unittest.defaultTestLoader.discover(str(REPO/'tests/shell'),pattern='test_mac_*.py')
    module=importlib.import_module('test_mac_prefix_decision')
    root=frozen_sources(module)
    selected=list(walk(suite))
    if any(sum(case.id()==target for case in selected)!=1 for target in HISTORICAL_TARGETS):
        raise ValueError('exactly one unchanged case for each historical byte assertion required')
    fixture_cases=[case for case in selected if case.id().startswith(POLICY_FIXTURE_PREFIX)]
    if not fixture_cases:
        raise ValueError('explicit current synthetic prefix policy fixture population absent')
    scoped=unittest.TestSuite(HistoricalBlobCase(case,module,root) if case.id() in HISTORICAL_TARGETS else
        CurrentPrefixPolicyFixtureCase(case,module) if case.id().startswith(POLICY_FIXTURE_PREFIX) else case
        for case in selected)
    scoped.addTest(CurrentUnchangedFunctionBytes())
    from versioned_nested_scope import materialize_e5_source,verify_materialized_e5
    e5_root=materialize_e5_source(REPO)
    for case in walk(unittest.defaultTestLoader.loadTestsFromTestCase(CurrentOwnedGuardSourceControls)):
        if case.id().endswith('.test_current_owned_predicate_and_original_full_decision_core_ast_are_pinned'):
            scoped.addTest(HistoricalBlobCase(case,sys.modules[__name__],e5_root))
        else:scoped.addTest(case)
    scoped.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(CurrentNativeGuardSourceControls))
    print('Historical ten-blob/34-function claims: exact Q4 '+Q4+
          '; current33 unchanged bodies checked separately; original E5 predicate81f uses all48 frozen sources; current native predicateabc and setup/factory behaviour have separate controls.'+
          ' Current fresh-Git prefix fixtures='+str(len(fixture_cases))+
          ' derive only binary source f2e -> actualb87 inside each case; original configs/tests/production predicates unchanged.',flush=True)
    result=unittest.TextTestRunner(verbosity=2).run(scoped)
    verify_materialized_e5(e5_root)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
