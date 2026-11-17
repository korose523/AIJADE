"""Apply only the authorized owned-guard paths after E4 negative publication.

No Git action, old parser/clone mutation, binary-auth overwrite or live launch.
"""
from pathlib import Path
import ast
import hashlib
import json

B=Path('/Volumes/Untitled/AIJADE')
C=Path(__file__).resolve().parent
W=B/'.runtime/posix/nested-20261117/worktree'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    receipt=C/'owned-source-application.json'
    if receipt.exists():raise FileExistsError('retain original source application receipt')
    names=('mac_process_guard_v3.py','finite_runtime.py','run_nested_load.py','newowned_guard_cursor.py')
    for name in names:
        target=W/'experiments/ch7'/name
        baseline=C/'baseline/experiments/ch7'/name
        if baseline.exists():
            if target.read_bytes()!=baseline.read_bytes():raise ValueError('owned source target changed: '+name)
        elif target.exists():raise ValueError('new owned module already exists')
    pins={name:sha((W/'experiments/ch7'/name).read_bytes()) for name in ('binary_authentication.py','process_lifecycle.py','full_state_clone_cursor.py')}
    if pins['process_lifecycle.py']!='93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65' or pins['full_state_clone_cursor.py']!='0da9588655714d23db401b3424f45379689421898d85256b2506d674fee5e584':
        raise ValueError('legacy parser/complete-return clone changed')
    unit=(C/'test_owned_guard_cursor.py').read_text()
    start=unit.index("C=Path(__file__).resolve().parent")
    end=unit.index('\n\ndef typed',start)
    header="""REPO=Path(__file__).resolve().parents[2]
P=REPO/'experiments/ch7'
sys.path.insert(0,str(P))
sys.path.insert(0,str(REPO/'tests/shell'))
import process_lifecycle as life
import newowned_guard_cursor as owned
import mac_process_guard_v3 as guard
import full_state_clone_cursor as legacy
spec=importlib.util.spec_from_file_location('owned_test_journal_fixtures',REPO/'tests/shell/test_process_lifecycle_cursor.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
"""
    unit=unit[:start]+header+unit[end:]
    unit=unit.replace("C/'FIXTURE-ONLY/initialization.json'","life.BASE/'.runtime/posix/tmp/OWNED-FIXTURE-ONLY/initialization.json'")
    node=next(n for n in ast.parse(unit).body if isinstance(n,ast.FunctionDef) and n.name=='policy')
    lines=unit.splitlines(keepends=True)
    policy="""def policy():
    from test_mac_lifecycle_guard import policy as original_policy
    result=original_policy()
    result.update(coordinationMode=guard.SEGMENTED_MODE,coordinationSchema=guard.SEGMENTED_SCHEMA,
        onlineReplayMode=owned.MODE,onlineReplayInitializationMode=owned.INITIALIZATION_MODE,
        onlineReplaySourceSha256=hashlib.sha256((P/'newowned_guard_cursor.py').read_bytes()).hexdigest(),
        binaryAuthenticationMode='full-read-exact-bytes-v1',
        binaryAuthenticationSourceSha256=guard._file_sha(P/'binary_authentication.py'))
    return result
"""
    unit=''.join(lines[:node.lineno-1])+policy+''.join(lines[node.end_lineno:])
    # Freeze the original exact complete decision core as a semantic guardrail.
    core_sha=json.loads((C/'owned-source-preparation.json').read_bytes())['originalFullDecisionCoreAstSha256']
    method="""    def test_original_qe3_complete_decision_core_ast_is_unchanged(self):
        import ast
        source=(P/'mac_process_guard_v3.py').read_text()
        predicate=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)
                       and n.name=='_guard_decision_from_validated_lifecycle')
        branch=next(n for n in predicate.body if isinstance(n,ast.Try))
        core=ast.Module(body=branch.body[3:],type_ignores=[])
        self.assertEqual(hashlib.sha256(ast.dump(core,include_attributes=False).encode()).hexdigest(),CORE_SHA)

""".replace('CORE_SHA',repr(core_sha))
    unit=unit.replace('class OwnedGuardControls(unittest.TestCase):','class OwnedGuardControls(unittest.TestCase):\n'+method)
    ast.parse(unit)
    portable=C/'candidate/tests/shell/test_owned_guard_cursor.py'
    portable.parent.mkdir(parents=True,exist_ok=True);portable.write_text(unit)
    target_test=W/'tests/shell/test_owned_guard_cursor.py'
    if target_test.exists():raise ValueError('new portable owned test already exists')
    saved=C/'actual-w5-before-owned-application'
    saved.mkdir()
    changes=[]
    for name in names:
        target=W/'experiments/ch7'/name
        before=target.read_bytes() if target.exists() else None
        if before is not None:(saved/name).write_bytes(before)
        after=(C/'candidate/experiments/ch7'/name).read_bytes()
        ast.parse(after.decode());target.write_bytes(after)
        changes.append(dict(path='experiments/ch7/'+name,beforeSha256=None if before is None else sha(before),afterSha256=sha(after)))
    target_test.write_bytes(portable.read_bytes())
    changes.append(dict(path='tests/shell/test_owned_guard_cursor.py',beforeSha256=None,afterSha256=sha(portable.read_bytes())))
    after_pins={name:sha((W/'experiments/ch7'/name).read_bytes()) for name in pins}
    if pins!=after_pins:raise ValueError('unowned binary/parser/clone changed while applying')
    result=dict(schema='aijade.ch7.owned-guard-source-application.v1',
        status='AUTHORIZED_OWNED_SOURCE_AND_PORTABLE_TEST_ONLY_APPLIED_NO_COMMIT_NO_WINDOW',
        precondition='Root confirmed E4 immutable negative publication e77afa10ff4cd0c81ea41ec8ec7db3de4b02db71',
        paths=changes,preservedOtherSourcePins=pins,preservedAfterPins=after_pins,
        binaryAuthenticationSourceWasNotOverwritten=True,portablePolicyPinsActualW5BinarySource=True,
        parserAndLegacyCloneUnchanged=True,gitMutation=False,liveWindow=False,docsModified=False,
        scientificDecisionActivated=False,seedConstructed=False,heldoutRun=False)
    receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],paths=len(changes),actualBinarySourceSha256=pins['binary_authentication.py'])))


if __name__=='__main__':main()
