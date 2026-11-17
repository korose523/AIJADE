"""Stage the guard-owned E5 implementation; never edit W5, D or old packets."""
from pathlib import Path
import ast
import copy
import difflib
import hashlib
import json

B=Path('/Volumes/Untitled/AIJADE')
C=Path(__file__).resolve().parent
W=B/'.runtime/posix/nested-20261117/worktree'
SRC=W/'experiments/ch7'
OUT=C/'candidate/experiments/ch7'
MODE='owned-guard-state-exact-prefix-v1'
INIT='paired-source-verified-owned-state-v1'


def replace(text,old,new,count=1):
    if text.count(old)!=count:raise ValueError('source anchor changed: '+old[:100])
    return text.replace(old,new)


def node(text,name):
    return next(n for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name)


def body(text,name):
    n=node(text,name)
    return ''.join(text.splitlines(keepends=True)[n.lineno-1:n.end_lineno])


def substitute_function(text,name,new):
    n=node(text,name);lines=text.splitlines(keepends=True)
    return ''.join(lines[:n.lineno-1])+new.rstrip()+'\n'+''.join(lines[n.end_lineno:])


def digest(value):return hashlib.sha256(value).hexdigest()


def main():
    if (OUT/'newowned_guard_cursor.py').exists():raise FileExistsError('preserve previous candidate generation')
    names=('mac_process_guard_v3.py','finite_runtime.py','run_finite_sequence.py','run_finite_block.py','run_nested_load.py',
           'process_lifecycle.py','full_state_clone_cursor.py','measured_mac_monitor.py','binary_authentication.py',
           'mac_process_guard.py','mac_process_guard_v2.py','mac_bulk_census.c','lifecycle_exec.py',
           'phase_continuity.py','nested_event_index.py')
    original={name:(SRC/name).read_bytes() for name in names}
    if digest(original['process_lifecycle.py'])!='93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65':
        raise ValueError('canonical parser changed')
    if digest(original['full_state_clone_cursor.py'])!='0da9588655714d23db401b3424f45379689421898d85256b2506d674fee5e584':
        raise ValueError('legacy complete-return clone changed')
    texts={name:raw.decode() for name,raw in original.items()}
    guard=texts['mac_process_guard_v3.py']
    old_node=node(guard,'validate_observation')
    old_try=next(n for n in old_node.body if isinstance(n,ast.Try))
    original_core=ast.Module(body=copy.deepcopy(old_try.body[4:]),type_ignores=[])
    # The complete decision core, helper calls, original exception handling and
    # every FAIL/UNKNOWN branch after replay-mode binding are unchanged AST.
    private=copy.deepcopy(old_node)
    private.name='_guard_decision_from_validated_lifecycle'
    private.args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=x) for x in ('policy','observation','state')],
        vararg=None,kwonlyargs=[],kw_defaults=[],kwarg=None,defaults=[])
    private.body=copy.deepcopy(old_node.body[:old_node.body.index(old_try)])+[copy.deepcopy(old_try)]
    private_try=private.body[-1]
    private_try.body=copy.deepcopy(old_try.body[2:])
    replay=private_try.body[1]
    replay.test=ast.parse("policy.get('onlineReplayMode') in (CLONE_REPLAY_MODE,OWNED_REPLAY_MODE)",mode='eval').body
    class RewriteBinding(ast.NodeTransformer):
        def visit_Name(self,n):
            if n.id=='CLONE_REPLAY_MODE':return ast.copy_location(ast.Subscript(value=ast.Name(id='policy',ctx=ast.Load()),slice=ast.Constant('onlineReplayMode'),ctx=ast.Load()),n)
            if n.id=='CLONE_INITIALIZATION_MODE':return ast.copy_location(ast.Subscript(value=ast.Name(id='policy',ctx=ast.Load()),slice=ast.Constant('onlineReplayInitializationMode'),ctx=ast.Load()),n)
            return n
    # Only the replay binding branch is generalized; all remaining branches are exact.
    replay.body=[RewriteBinding().visit(x) for x in replay.body]
    keyassign=next(x for x in replay.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='keys' for t in x.targets))
    pos=replay.body.index(keyassign)+1
    replay.body[pos:pos]=ast.parse("""if policy.get('onlineReplayMode')==OWNED_REPLAY_MODE:
    keys|={'ownerId','ownerRole','pairedOwnerId','guardPredicateAstSha256'}
""").body
    private_try.body.insert(2,ast.parse("""if policy.get('onlineReplayMode')==OWNED_REPLAY_MODE:
    reference=observation.get('onlineReplayPreparation')
    if (type(reference) is not dict or reference.get('ownerRole')!='inner'
        or not lifecycle_support._hex(reference.get('ownerId'),32)
        or not lifecycle_support._hex(reference.get('pairedOwnerId'),32)
        or reference.get('ownerId')==reference.get('pairedOwnerId')
        or reference.get('guardPredicateAstSha256')!=_owned_cursor_module(policy).GUARD_PREDICATE_AST_SHA256):
        add('OWNED_REPLAY_OWNER_OR_PREDICATE_MISMATCH','FAIL')
""").body[0])
    actual_core=ast.Module(body=private_try.body[3:],type_ignores=[])
    if ast.dump(original_core,include_attributes=False)!=ast.dump(actual_core,include_attributes=False):
        raise ValueError('original complete guard decision core AST changed')
    ast.fix_missing_locations(private)
    private_source=ast.unparse(private)
    predicate_hash=digest(ast.dump(private,include_attributes=False).encode())
    wrapper='''def validate_observation(policy,observation,lifecycle_journal=None,*,lifecycle_cursor=None):
    """Recompute recorded evidence; owned mode returns only private-state decisions."""
    try:
        if policy.get('onlineReplayMode')==OWNED_REPLAY_MODE and lifecycle_cursor is not None:
            module=_owned_cursor_module(policy)
            if type(lifecycle_cursor) is not module.OwnedGuardCursor:
                raise ValueError('exact owned guard cursor required')
            return lifecycle_cursor.evaluate(policy,observation,lifecycle_journal)
        validate_policy(policy)
        state=_lifecycle_view(policy,observation['lifecycle'],lifecycle_journal,lifecycle_cursor)
        return _guard_decision_from_validated_lifecycle(policy,observation,state)
    except Exception:
        return _decision([{'code':'OBSERVATION_SCHEMA_OR_POLICY_UNKNOWN','severity':'UNKNOWN'}])
'''
    guard=substitute_function(guard,'validate_observation',private_source+'\n\n\n'+wrapper)
    guard=replace(guard,"CLONE_INITIALIZATION_MODE = 'paired-source-verified-journal-prefix-v1'",
        "CLONE_INITIALIZATION_MODE = 'paired-source-verified-journal-prefix-v1'\nOWNED_REPLAY_MODE = '"+MODE+"'\nOWNED_INITIALIZATION_MODE = '"+INIT+"'")
    guard=replace(guard,"(None, 'incremental-exact-prefix-v1', CLONE_REPLAY_MODE)",
        "(None, 'incremental-exact-prefix-v1', CLONE_REPLAY_MODE, OWNED_REPLAY_MODE)")
    guard=replace(guard,"    if policy.get('onlineReplayMode') == CLONE_REPLAY_MODE:\n        _clone_cursor_module(policy)",
        "    if policy.get('onlineReplayMode') == OWNED_REPLAY_MODE:\n        _owned_cursor_module(policy)\n    elif policy.get('onlineReplayMode') == CLONE_REPLAY_MODE:\n        _clone_cursor_module(policy)")
    helper='''def _owned_cursor_module(policy):
    import importlib
    expected=Path(__file__).with_name('newowned_guard_cursor.py')
    if (not _hex(policy.get('onlineReplaySourceSha256'))
        or policy['onlineReplaySourceSha256']!=_file_sha(expected)
        or policy.get('onlineReplayInitializationMode')!=OWNED_INITIALIZATION_MODE):
        raise ValueError('owned guard cursor source/initialization differs from policy')
    module=importlib.import_module('newowned_guard_cursor')
    if (Path(module.__file__).resolve()!=expected.resolve() or module.MODE!=OWNED_REPLAY_MODE
        or module.INITIALIZATION_MODE!=OWNED_INITIALIZATION_MODE):
        raise ValueError('wrong actual owned guard module')
    return module


'''
    guard=replace(guard,'def _lifecycle_view(policy,view,journal,cursor):',helper+'def _lifecycle_view(policy,view,journal,cursor):')
    guard=replace(guard,"        if policy.get('onlineReplayMode')==CLONE_REPLAY_MODE:\n            module=_clone_cursor_module(policy)",
        "        if policy.get('onlineReplayMode')==OWNED_REPLAY_MODE:\n            module=_owned_cursor_module(policy)\n            if type(lifecycle_cursor) is not module.OwnedGuardCursor or lifecycle_cursor.owner_role!='inner':\n                raise ValueError('exact inner owned guard cursor required for observation')\n            result.update(onlineReplayMode=OWNED_REPLAY_MODE,onlineReplaySourceSha256=policy['onlineReplaySourceSha256'],\n                onlineReplayInitializationMode=OWNED_INITIALIZATION_MODE,\n                onlineReplayPreparation=lifecycle_cursor.preparation_reference())\n        elif policy.get('onlineReplayMode')==CLONE_REPLAY_MODE:\n            module=_clone_cursor_module(policy)")
    texts['mac_process_guard_v3.py']=guard
    # Adapt only the private state path of the exact legacy validated cursor.
    clone_tree=ast.parse(texts['full_state_clone_cursor.py'])
    cls=next(n for n in clone_tree.body if isinstance(n,ast.ClassDef) and n.name=='FullStateCloneCursor')
    advance=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='validate_view')
    lines=texts['full_state_clone_cursor.py'].splitlines(keepends=True)
    method=''.join(lines[advance.lineno-1:advance.end_lineno])
    method=replace(method,'def validate_view(self, view, journal_bytes=None):','def __advance(self, view, journal_bytes=None):')
    for name in ('mutex','work','usable','origin','frontiers','raw','hasher','state','context','seal_state_types','poison_reason'):
        method=method.replace('self._'+name,'self.__'+name)
    method=replace(method,'                snapshot = self._clone_state(state)\n','')
    method=replace(method,"                self.__work['snapshotCopies'] += 1", "                self.__work['privateStateValidations'] += 1")
    method=replace(method,'                return snapshot','                return state')
    template=(C/'owned_cursor_template.py').read_text()
    owned=replace(template,'__GUARD_PREDICATE_AST_SHA256__',repr(predicate_hash))
    owned=replace(owned,'    __ADVANCE_METHOD__',method.rstrip())
    texts['newowned_guard_cursor.py']=owned
    runtime=texts['finite_runtime.py']
    runtime=replace(runtime,"def lifecycle_observer_sources(policy):\n", "def lifecycle_observer_sources(policy):\n    if policy.get('onlineReplayMode')=='"+MODE+"':\n        return tuple(dict.fromkeys(MAC_LIFECYCLE_SOURCES+('experiments/ch7/measured_mac_monitor.py','experiments/ch7/full_state_clone_cursor.py','experiments/ch7/newowned_guard_cursor.py')))\n")
    runtime=replace(runtime,"require(policy.get('onlineReplayMode')!='full-state-c-clone-exact-prefix-v1',",
        "require(policy.get('onlineReplayMode') not in ('full-state-c-clone-exact-prefix-v1','"+MODE+"'),")
    oldbranch="        if policy['onlineReplayMode']=='full-state-c-clone-exact-prefix-v1':"
    ownedbranch="""        if policy['onlineReplayMode']=='owned-guard-state-exact-prefix-v1':
            started=time.monotonic()
            from process_lifecycle import Registry, project_path
            require(isinstance(lifecycle,Registry) and preparation_path is not None,
                    'owned guard requires actual journal-only preparation before observation')
            mac_observer(policy).validate_policy(policy)
            from newowned_guard_cursor import bootstrap_pair
            path=project_path(preparation_path)
            require(path.name=='initialization.json' and path.parent.is_dir() and not path.exists(),
                    'new exclusive owned guard initialization artifact required')
            view=lifecycle.sample()
            captured=time.monotonic()
            first,second,record=bootstrap_pair(view)
            record.update(factoryStartedMonotonic=started,viewCapturedMonotonic=captured,
                          recordWriteStartedMonotonic=time.monotonic())
            raw=(json.dumps(record,sort_keys=True,indent=2,allow_nan=False)+'\\n').encode()
            with path.open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            completed=time.monotonic()
            write_clock=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),
                startedMonotonic=record['recordWriteStartedMonotonic'],completedMonotonic=completed)
            first.bind_preparation(record,write_clock);second.bind_preparation(record,write_clock)
            inner['lifecycle_cursor'],outer['lifecycle_cursor']=first,second
        elif policy['onlineReplayMode']=='full-state-c-clone-exact-prefix-v1':"""
    runtime=replace(runtime,oldbranch,ownedbranch)
    runtime=replace(runtime,"    if cursor is None or type(cursor).__name__!='FullStateCloneCursor':return {}",
        "    if cursor is not None and type(cursor).__name__=='OwnedGuardCursor':\n        from newowned_guard_cursor import OwnedGuardCursor\n        require(type(cursor) is OwnedGuardCursor,'exact source-bound owned guard cursor required')\n        return cursor.preparation_metadata()\n    if cursor is None or type(cursor).__name__!='FullStateCloneCursor':return {}")
    texts['finite_runtime.py']=runtime
    runner=texts['run_nested_load.py']
    runner=replace(runner,"need(policy.get('onlineReplayMode')=='full-state-c-clone-exact-prefix-v1'\n         and policy.get('onlineReplayInitializationMode')=='paired-source-verified-journal-prefix-v1',",
        "need((policy.get('onlineReplayMode'),policy.get('onlineReplayInitializationMode')) in (\n         ('full-state-c-clone-exact-prefix-v1','paired-source-verified-journal-prefix-v1'),\n         ('owned-guard-state-exact-prefix-v1','paired-source-verified-owned-state-v1')),")
    texts['run_nested_load.py']=runner
    OUT.mkdir(parents=True)
    records=[]
    for name,text in texts.items():
        ast.parse(text)
        (OUT/name).write_text(text)
        if name in original:
            old=C/'baseline/experiments/ch7'/name;old.parent.mkdir(parents=True,exist_ok=True);old.write_bytes(original[name])
            diff=C/'diffs'/(name+'.diff');diff.parent.mkdir(parents=True,exist_ok=True)
            diff.write_text(''.join(difflib.unified_diff(original[name].decode().splitlines(keepends=True),text.splitlines(keepends=True),fromfile='Q8231/'+name,tofile='E5-STAGED/'+name)))
        records.append(dict(path='experiments/ch7/'+name,beforeSha256=None if name not in original else digest(original[name]),
                            stagedSha256=digest(text.encode()),changed=name not in original or original[name]!=text.encode()))
    report=dict(schema='aijade.ch7.owned-guard-source-preparation.v1',status='STAGED_ONLY_NOT_LIVE_NOT_SCIENTIFIC_QUALIFICATION',
        files=records,mode=MODE,initializationMode=INIT,guardPredicateAstSha256=predicate_hash,
        originalFullDecisionCoreAstSha256=digest(ast.dump(original_core,include_attributes=False).encode()),
        stagedFullDecisionCoreAstSha256=digest(ast.dump(actual_core,include_attributes=False).encode()),
        originalCoreAstExactlyEqual=True,legacyCloneBytesUnchanged=True,canonicalParserBytesUnchanged=True,
        perEvaluationFullStateClones=0,initialCanonicalParses=1,initialStateClones=1,
        oldApiCompleteReturnPreserved=True,newApiStateReturn=False,worktreeEdited=False,docsEdited=False,
        nativeApiModelQueries=0,scientificDecisionActivated=False,heldoutRun=False)
    (C/'owned-source-preparation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],files=len(records),predicateAstSha256=predicate_hash)))


if __name__=='__main__':main()
