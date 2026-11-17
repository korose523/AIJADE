"""Stage only the new explicit native path; no working checkout mutation."""
from pathlib import Path
import ast,hashlib,json,subprocess
B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-native-ready-20261118';W=B/'.runtime/posix/nested-20261117/worktree';D=C/'integration/candidate';Q='48299b12847c11d5a629b0292ea19d57fe771cd4'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def replace(s,a,b):
 assert s.count(a)==1,a[:160]
 return s.replace(a,b)
p=json.loads((B/'.research/runs/ch7-owned-state-20261118/engineering-03-passport.json').read_bytes())
assert p['sourceCommit']==Q
for name,h in p['sourceFiles'].items():
 raw=subprocess.check_output(['git','--no-replace-objects','-C',str(W),'show',Q+':'+name]);assert sha(raw)==h
 dst=D/name;dst.parent.mkdir(parents=True,exist_ok=True);assert not dst.exists();dst.write_bytes(raw)
for name in ['native_exec_registry.py','lifecycle_exec_native.c']:
 raw=(C/'candidate/experiments/ch7'/name).read_bytes();(D/'experiments/ch7'/name).write_bytes(raw)
raw=(C/'listener-evidence/listener_evidence.py').read_bytes();(D/'experiments/ch7/listener_evidence.py').write_bytes(raw)
f=D/'experiments/ch7/mac_process_guard_v3.py';s=f.read_text()
s=replace(s,"    if config['moduleSha256'] != _file_sha(Path(lifecycle_support.__file__)) or config['execShimSha256'] != _file_sha(Path(__file__).with_name('lifecycle_exec.py')):\n        raise ValueError('lifecycle module/shim changed')", "    if config['moduleSha256'] != _file_sha(Path(lifecycle_support.__file__)):\n        raise ValueError('lifecycle module/shim changed')\n    if policy.get('lifecycleExecMode') is not None:\n        module=_native_exec_module(policy)\n        module._policy_binding(policy)\n        _native_listener_module(policy)\n    elif ('nativeExec' in policy or 'listenerEvidence' in policy\n          or config['execShimSha256'] != _file_sha(Path(__file__).with_name('lifecycle_exec.py'))):\n        raise ValueError('lifecycle module/shim changed')")
helpers='''def _native_exec_module(policy):
    import importlib
    if (policy.get('lifecycleExecMode')!='native-ready-release-v1'
            or policy.get('onlineReplayMode')!=OWNED_REPLAY_MODE
            or policy.get('coordinationMode')!=SEGMENTED_MODE):
        raise ValueError('unknown explicit native execution mode')
    module=importlib.import_module('native_exec_registry')
    if Path(module.__file__).resolve()!=Path(__file__).with_name('native_exec_registry.py').resolve():
        raise ValueError('exact colocated native Registry required')
    binding=module._policy_binding(policy)
    if (binding['adapterSourceSha256']!=_file_sha(Path(module.__file__))
            or binding['sourceSha256']!=_file_sha(Path(__file__).with_name('lifecycle_exec_native.c'))):
        raise ValueError('native adapter/source differs from policy')
    for name in ('sourcePath','binaryPath'):
        value=Path(binding[name])
        if not value.is_absolute() or '..' in value.parts or WORKSPACE not in value.parents:
            raise ValueError('native artifact path outside workspace')
    return module


def _native_listener_module(policy):
    import importlib
    module=importlib.import_module('listener_evidence')
    expected=Path(__file__).with_name('listener_evidence.py')
    if Path(module.__file__).resolve()!=expected.resolve():
        raise ValueError('exact colocated listener evidence module required')
    module._policy(policy,_file_sha(expected),_file_sha(Path(__file__)))
    return module


def _read_native_listener(policy,lifecycle):
    """Capture complete original global command; never replay a prior verdict."""
    started=time.monotonic()
    native_module=_native_exec_module(policy);evidence_module=_native_listener_module(policy)
    process=None;out=err=b'';exception=None;native=None;returncode=None
    try:
        if type(lifecycle) is not native_module.NativeExecRegistry:
            raise ValueError('native policy requires actual native Registry')
        remaining=.5-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('listener source checks consumed deadline')
        process=lifecycle.launch(evidence_module.ARGV,stage='observer-listener',
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,ready_timeout=min(lifecycle_support.READY_SECONDS,remaining))
        remaining=.5-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('listener native startup consumed deadline')
        out,err=process.communicate(timeout=remaining)
        returncode=process.returncode
    except Exception as error:
        exception={'class':type(error).__name__,'message':str(error)}
        if process is not None:
            if process.poll() is None:process.kill()
            try:returncode=process.wait(timeout=1)
            except Exception as cleanup_error:
                exception['message']+='; actual owned cleanup unknown: '+type(cleanup_error).__name__
        if process is not None:
            # communicate may have returned partial bytes on TimeoutExpired.
            if isinstance(getattr(error,'output',None),bytes):out=error.output
            if isinstance(getattr(error,'stderr',None),bytes):err=error.stderr
    if process is not None:
        try:native=native_module.evidence_for_handle(process)
        except Exception as error:
            exception={'class':type(error).__name__,'message':'native wait evidence: '+str(error)}
    completed=time.monotonic()
    transcript=dict(schema=evidence_module.SCHEMA,mode=evidence_module.MODE,argv=list(evidence_module.ARGV),
        stdout=evidence_module.encode_capture(out[:evidence_module.MAX_FORENSIC],truncated=len(out)>evidence_module.MAX_FORENSIC,total_bytes=len(out)),
        stderr=evidence_module.encode_capture(err[:evidence_module.MAX_FORENSIC],truncated=len(err)>evidence_module.MAX_FORENSIC,total_bytes=len(err)),
        returnCode=returncode,exception=exception,startedMonotonic=started,
        runCompletedMonotonic=completed,parseCompletedMonotonic=completed,
        sourcePins=dict(adapterSourceSha256=policy['nativeExec']['adapterSourceSha256'],
            shimSourceSha256=policy['nativeExec']['sourceSha256'],shimSha256=policy['nativeExec']['binarySha256'],
            executableSha256=policy['listenerEvidence']['executableSha256'],
            parserSourceSha256=_file_sha(Path(evidence_module.__file__)),callerSourceSha256=_file_sha(Path(__file__))),
        nativeLaunch=native)
    try:evidence_module.parse_global_stdout(out)
    except Exception:pass
    transcript['parseCompletedMonotonic']=time.monotonic()
    return transcript


def _validate_native_listener_frames(policy,observation,state,add):
    module=_native_listener_module(policy)
    for phase in ('before','after'):
        frame=observation['evidence'][phase];listener=frame['listener']
        result=module.verify_transcript(listener.get('transcript'),state,policy,
            parser_source_sha256=_file_sha(Path(module.__file__)),caller_source_sha256=_file_sha(Path(__file__)),
            outer_clock=frame['listenerReadClock'])
        if result['state']!='OBSERVED':
            add('NATIVE_LISTENER_EVIDENCE_UNKNOWN',phase=phase,reasons=result.get('reasons',[]))
        elif listener.get('state')!='OBSERVED' or listener.get('records')!=result['records']:
            add('NATIVE_LISTENER_DERIVED_RESULT_MISMATCH','FAIL',phase=phase)


'''
s=replace(s,'def _clone_cursor_module(policy):',helpers+'def _clone_cursor_module(policy):')
a="    result['listener']=_read_listeners(lifecycle)\n    if daemon_sample is not None:\n        result['listenerReadClock'] = dict(startedMonotonic=listener_started, finishedMonotonic=time.monotonic())"
b="""    if policy.get('lifecycleExecMode') is not None:
        if daemon_sample is None:listener_started=time.monotonic()
        transcript=_read_native_listener(policy,lifecycle)
        module=_native_listener_module(policy)
        preliminary_clock=dict(startedMonotonic=listener_started,finishedMonotonic=time.monotonic())
        result['listener']=module.derive_outcome(transcript,preliminary_clock)
        outer_clock=dict(startedMonotonic=listener_started,finishedMonotonic=time.monotonic())
        if outer_clock['finishedMonotonic']-listener_started>.5:
            reasons=result['listener'].get('reasons',[])
            if 'WHOLE_CALL_DEADLINE_EXCEEDED' not in reasons:reasons=reasons+['WHOLE_CALL_DEADLINE_EXCEEDED']
            result['listener']=dict(state='UNKNOWN',code='LISTENER_EVIDENCE_UNKNOWN',reasons=reasons,records=[])
        result['listener']['transcript']=transcript
        result['listenerReadClock']=outer_clock
    else:
        result['listener']=_read_listeners(lifecycle)
        if daemon_sample is not None:
            result['listenerReadClock'] = dict(startedMonotonic=listener_started, finishedMonotonic=time.monotonic())"""
s=replace(s,a,b)
a="                add('OWNED_REPLAY_OWNER_OR_PREDICATE_MISMATCH', 'FAIL')"
s=replace(s,a,a+"\n            if policy.get('lifecycleExecMode') is not None:\n                _validate_native_listener_frames(policy,observation,state,add)")
ast.parse(s);f.write_text(s)
t=ast.parse(s);node=next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='_guard_decision_from_validated_lifecycle');predicate=sha(ast.dump(node,include_attributes=False).encode());tr=next(n for n in node.body if isinstance(n,ast.Try));core=sha(ast.dump(ast.Module(body=tr.body[3:],type_ignores=[]),include_attributes=False).encode());assert core=='b6bc9b54ba40d04503cbee3ad71ddfe64acdd6724abf47f8f01c50693b49c30b'
f=D/'experiments/ch7/newowned_guard_cursor.py';s=f.read_text();s=replace(s,'81f098fc92bffb77e5c1938e23b5284def002edd91ed130909ec788cafa9a343',predicate);f.write_text(s)
f=D/'experiments/ch7/finite_runtime.py';s=f.read_text();needle='def lifecycle_observer_sources(policy):\n';s=replace(s,needle,needle+"    if policy.get('lifecycleExecMode') is not None:\n        require(policy.get('lifecycleExecMode')=='native-ready-release-v1' and policy.get('onlineReplayMode')=='owned-guard-state-exact-prefix-v1','native execution requires explicit owned observer mode')\n        return tuple(dict.fromkeys(MAC_LIFECYCLE_SOURCES+('experiments/ch7/measured_mac_monitor.py','experiments/ch7/full_state_clone_cursor.py','experiments/ch7/newowned_guard_cursor.py','experiments/ch7/native_exec_registry.py','experiments/ch7/lifecycle_exec_native.c','experiments/ch7/listener_evidence.py')))\n");f.write_text(s)
f=D/'experiments/ch7/run_nested_load.py';s=f.read_text();s=replace(s,"    registry = life.from_environment()\n", "    if policy.get('lifecycleExecMode') is not None:\n        from native_exec_registry import activate_from_environment\n        registry=activate_from_environment(policy)\n    else:\n        registry = life.from_environment()\n")
s=replace(s,"    registry = life.Registry(root/'lifecycle-journal.jsonl', [(controller['pid'],controller['createTime'])],", "    registry_factory=life.Registry\n    if policy.get('lifecycleExecMode') is not None:\n        from native_exec_registry import registry_for_policy\n        registry_factory=lambda *args,**kwargs:registry_for_policy(policy,*args,**kwargs)\n    registry = registry_factory(root/'lifecycle-journal.jsonl', [(controller['pid'],controller['createTime'])],")
f.write_text(s)
rows=[]
for path in sorted((D/'experiments/ch7').glob('*')):
 if path.suffix=='.py':ast.parse(path.read_bytes())
 if path.is_file():rows.append(dict(path=str(path.relative_to(D)),sha256=sha(path.read_bytes())))
out={'status':'NATIVE_INTEGRATION_STAGED_NOT_INSTALLED_NOT_VERIFIED','baseSourceCommit':Q,'predicateAstSha256':predicate,'originalFullCoreAstSha256':core,'files':rows,'newLiveWindows':0,'backendQualified':False}
with (C/'integration/preparation-01.json').open('x') as stream:json.dump(out,stream,indent=2);stream.write('\n')
print(json.dumps({'status':out['status'],'predicateAstSha256':predicate,'sourceFiles':len(rows)},indent=2))
