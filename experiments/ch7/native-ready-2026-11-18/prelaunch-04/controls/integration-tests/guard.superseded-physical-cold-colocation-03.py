#!/usr/bin/env python3
"""Versioned lifecycle-aware Mac evidence; neither a census nor a wait journal is whole-machine history.

Public API: build_policy(app_pid, serve_pid), observe(policy, owned_roots=()),
validate_observation(policy, observation). No service is stopped or reconfigured.
Policy argv hashes bind the complete command without publishing its arguments.
The returned PID/parent/time/category graph omits unrelated process names.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import selectors
import socket
import stat
import subprocess
import time
import uuid
import process_lifecycle as lifecycle_support

SCHEMA = 3
KIND = 'mac-lifecycle-observed-idle-daemon-v3'
SEGMENTED_MODE = 'segmented-census-mutation-v1'
SEGMENTED_SCHEMA = 'aijade.mac.segmented-census-mutation.v1'
CLONE_REPLAY_MODE = 'full-state-c-clone-exact-prefix-v1'
CLONE_INITIALIZATION_MODE = 'paired-source-verified-journal-prefix-v1'
OWNED_REPLAY_MODE = 'owned-guard-state-exact-prefix-v1'
OWNED_INITIALIZATION_MODE = 'paired-source-verified-owned-state-v1'
API_URL = 'http://127.0.0.1:11434/api/ps'
MAX_API_BYTES = 65536
MAX_API_SECONDS = 0.5
WORKSPACE = Path('/Volumes/Untitled/AIJADE')
CENSUS_SOURCE = Path(__file__).with_name('mac_bulk_census.c')
CENSUS_SCHEMA = 'aijade.mac.bulk-census.v1'
MAX_CENSUS_BYTES = 4 * 1024 * 1024
MAX_KERNEL_BYTES = 16 * 1024 * 1024
NATIVE_TIMEOUT = 0.5
CLOCK_ENVELOPE_TOLERANCE = 0.002
LOCK_WAIT_SECONDS = 0.5
LOCK_HOLD_SECONDS = 1.0


def canonical_sha256(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _pid(value):
    return type(value) is int and value > 1


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _file_sha(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('not a regular executable')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        after = os.fstat(stream.fileno())
    current = os.stat(path, follow_symlinks=False)
    fields = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if fields(before) != fields(after) or fields(after) != fields(current):
        raise ValueError('executable changed during observation')
    return digest.hexdigest()


def validate_policy(policy):
    """Raise ValueError for an unsafe or incomplete predeclared policy."""
    if not isinstance(policy, dict) or type(policy.get('schemaVersion')) is not int or policy['schemaVersion'] != SCHEMA or policy.get('kind') != KIND:
        raise ValueError('policy schema/kind')
    mode = policy.get('coordinationMode')
    if mode not in (None, SEGMENTED_MODE):
        raise ValueError('unrecognized capture coordination mode')
    if (policy.get('coordinationSchema') != SEGMENTED_SCHEMA if mode == SEGMENTED_MODE
            else 'coordinationSchema' in policy):
        raise ValueError('capture coordination schema/mode mismatch')
    if policy.get('onlineReplayMode') not in (None, 'incremental-exact-prefix-v1', CLONE_REPLAY_MODE, OWNED_REPLAY_MODE):
        raise ValueError('unrecognized online journal replay mode')
    if policy.get('onlineReplayMode') == OWNED_REPLAY_MODE:
        _owned_cursor_module(policy)
    elif policy.get('onlineReplayMode') == CLONE_REPLAY_MODE:
        _clone_cursor_module(policy)
    elif any(key in policy for key in ('onlineReplaySourceSha256','onlineReplayInitializationMode')):
        raise ValueError('legacy replay policy cannot select C-clone initialization fields')
    if policy.get('binaryAuthenticationMode') not in (None, 'full-read-exact-bytes-v1'):
        raise ValueError('unrecognized binary authentication mode')
    if policy.get('binaryAuthenticationMode') is not None:
        expected_source=policy.get('binaryAuthenticationSourceSha256')
        if not _hex(expected_source) or expected_source != _file_sha(Path(__file__).with_name('binary_authentication.py')):
            raise ValueError('binary authentication source differs from policy')
    daemon = policy.get('daemon')
    if not isinstance(daemon, dict) or set(daemon) != {'app', 'serve'}:
        raise ValueError('policy must bind exactly app and serve')
    for role in ('app', 'serve'):
        item = daemon[role]
        if not isinstance(item, dict) or not _pid(item.get('pid')) or not _finite(item.get('createTime')) or item['createTime'] <= 0:
            raise ValueError('invalid daemon PID/creation time')
        if type(item.get('parentPid')) is not int or item['parentPid'] < 1:
            raise ValueError('invalid parent identity')
        path = item.get('executable')
        if not isinstance(path, str) or not Path(path).is_absolute() or any(c in path for c in ('\x00', '\n', '\r')) or '..' in Path(path).parts:
            raise ValueError('invalid executable path')
        if not _hex(item.get('sha256')) or not _hex(item.get('argvSha256')):
            raise ValueError('missing executable or complete-command hash')
        if item.get('commandForm') != ('gui' if role == 'app' else 'serve'):
            raise ValueError('unsupported command form')
    if daemon['app']['pid'] == daemon['serve']['pid'] or daemon['serve']['parentPid'] != daemon['app']['pid'] or daemon['serve']['createTime'] < daemon['app']['createTime']:
        raise ValueError('daemon parent identity')
    listener = policy.get('listener')
    if not isinstance(listener, dict) or type(listener.get('port')) is not int or type(listener.get('pid')) is not int or listener != {'address': '127.0.0.1', 'port': 11434, 'pid': daemon['serve']['pid']}:
        raise ValueError('only the declared serve IPv4 loopback listener is allowed')
    api = policy.get('api')
    if not isinstance(api, dict) or api.get('url') != API_URL or not _finite(api.get('timeoutSeconds')) or not 0 < api['timeoutSeconds'] <= MAX_API_SECONDS:
        raise ValueError('unsafe API endpoint/deadline')
    if type(api.get('maxBytes')) is not int or not 1 <= api['maxBytes'] <= MAX_API_BYTES:
        raise ValueError('unsafe API response cap')
    helper = policy.get('nativeHelper')
    if not isinstance(helper, dict) or set(helper) != {'path', 'sha256', 'sourceSha256'} or not _hex(helper['sha256']) or not _hex(helper['sourceSha256']):
        raise ValueError('native helper identity missing')
    path = helper['path']
    if not isinstance(path, str) or not Path(path).is_absolute() or '..' in Path(path).parts:
        raise ValueError('native helper path unsafe')
    try: Path(path).relative_to(WORKSPACE)
    except ValueError as error: raise ValueError('native helper outside workspace') from error
    config = policy.get('lifecycle')
    if not isinstance(config,dict) or set(config) != {'moduleSha256','execShimSha256','coordinationLockPath','maxLockWaitSeconds','maxObservationSeconds'}:
        raise ValueError('lifecycle policy identity missing')
    if config['moduleSha256'] != _file_sha(Path(lifecycle_support.__file__)):
        raise ValueError('lifecycle module/shim changed')
    if policy.get('lifecycleExecMode') is not None:
        module=_native_exec_module(policy)
        module._policy_binding(policy)
        _native_listener_module(policy)
    elif ('nativeExec' in policy or 'listenerEvidence' in policy
          or config['execShimSha256'] != _file_sha(Path(__file__).with_name('lifecycle_exec.py'))):
        raise ValueError('lifecycle module/shim changed')
    if config['coordinationLockPath'] != str(coordination_lock_path(policy)) or config['maxLockWaitSeconds'] != 1.25 or config['maxObservationSeconds'] != 2.5:
        raise ValueError('lifecycle observation coordination changed')
    canonical_sha256(policy)


def _native_exec_module(policy):
    import importlib
    if (policy.get('lifecycleExecMode')!='native-ready-release-v1'
            or policy.get('onlineReplayMode')!=OWNED_REPLAY_MODE
            or policy.get('coordinationMode')!=SEGMENTED_MODE):
        raise ValueError('unknown explicit native execution mode')
    module=importlib.import_module('native_exec_registry')
    if Path(module.__file__).resolve()!=Path(__file__).with_name('native_exec_registry.py').resolve():
        raise ValueError('exact colocated native Registry required')
    binding=module._policy_binding(policy)
    if Path(binding['sourcePath'])!=Path(__file__).with_name('lifecycle_exec_native.c'):
        raise ValueError('exact colocated native C source required')
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
    process=None;out=err=b'';exception=None;native=None;returncode=None;communicated=False
    def record_error(error,label):
        nonlocal exception
        detail=label+': '+type(error).__name__+': '+str(error)
        if exception is None:exception={'class':type(error).__name__,'message':detail}
        else:exception['message']+='; '+detail
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
        communicated=True
        returncode=process.returncode
    except Exception as error:
        record_error(error,'capture')
        # TimeoutExpired only carries a prefix, not the complete pipe stream.
        # Retain it before any cleanup operation can fail independently.
        if isinstance(getattr(error,'output',None),bytes):out=error.output
        if isinstance(getattr(error,'stderr',None),bytes):err=error.stderr
        if process is not None:
            try:
                if process.poll() is None:process.kill()
            except Exception as cleanup_error:record_error(cleanup_error,'owned cleanup signal')
            try:returncode=process.wait(timeout=1)
            except Exception as cleanup_error:record_error(cleanup_error,'actual owned cleanup wait')
    if process is not None:
        try:native=native_module.evidence_for_handle(process)
        except Exception as error:record_error(error,'native wait evidence')
    completed=time.monotonic()
    transcript=dict(schema=evidence_module.SCHEMA,mode=evidence_module.MODE,argv=list(evidence_module.ARGV),
        stdout=evidence_module.encode_capture(out[:evidence_module.MAX_FORENSIC],truncated=not communicated or len(out)>evidence_module.MAX_FORENSIC,total_bytes=len(out) if communicated else None),
        stderr=evidence_module.encode_capture(err[:evidence_module.MAX_FORENSIC],truncated=not communicated or len(err)>evidence_module.MAX_FORENSIC,total_bytes=len(err) if communicated else None),
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


def _clone_cursor_module(policy):
    import importlib
    expected=Path(__file__).with_name('full_state_clone_cursor.py')
    value=policy.get('onlineReplaySourceSha256')
    if (not _hex(value) or value!=_file_sha(expected)
            or policy.get('onlineReplayInitializationMode')!=CLONE_INITIALIZATION_MODE):
        raise ValueError('C-clone cursor source/initialization differs from policy')
    module=importlib.import_module('full_state_clone_cursor')
    if (Path(module.__file__).resolve()!=expected.resolve() or module.MODE!=CLONE_REPLAY_MODE
            or module.INITIALIZATION_MODE!=CLONE_INITIALIZATION_MODE):
        raise ValueError('wrong actual C-clone cursor module')
    return module


def _owned_cursor_module(policy):
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


def _lifecycle_view(policy,view,journal,cursor):
    if policy.get('onlineReplayMode')==CLONE_REPLAY_MODE:
        module=_clone_cursor_module(policy)
        if cursor is not None:
            if type(cursor) is not module.FullStateCloneCursor:
                raise ValueError('new policy requires its exact source-bound C-clone cursor')
            cursor.preparation_reference()
            return cursor.validate_view(view,journal)
        # Offline replay remains the complete original cold parser, with no
        # initialization state or cached runtime verdict borrowed.
        return lifecycle_support.validate_view(view,journal)
    return lifecycle_support.validate_view(view,journal,cursor=cursor)


def _command_form(executable, argv):
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
        return 'unknown'
    if Path(argv[0]).name.lower() != Path(executable).name.lower():
        return 'unknown'
    if len(argv) == 1 and Path(executable).name == 'Ollama':
        return 'gui'
    if len(argv) == 2 and argv[1] == 'serve' and Path(executable).name.lower() == 'ollama':
        return 'serve'
    return 'unknown'


def _read_identity(pid, *, binary_authenticator=None):
    import psutil
    process = psutil.Process(pid)
    created = process.create_time()
    executable, argv, parent = process.exe(), process.cmdline(), process.ppid()
    binary = (_file_sha(executable) if binary_authenticator is None else binary_authenticator.sha256(executable))
    if psutil.Process(pid).create_time() != created:
        raise ValueError('PID reused during identity observation')
    return {'pid': pid, 'createTime': created, 'parentPid': parent, 'executable': executable,
            'sha256': binary, 'argvSha256': canonical_sha256(argv), 'commandForm': _command_form(executable, argv)}


def new_binary_authenticator(policy):
    """No prewarm: bind expected files; first actual snapshot authenticates them."""
    if policy.get('binaryAuthenticationMode') is None:
        return None
    if policy.get('binaryAuthenticationMode') != 'full-read-exact-bytes-v1':
        raise ValueError('binary authentication mode')
    validate_policy(policy)
    from binary_authentication import BinaryAuthenticator
    expected = {item['executable']:item['sha256'] for item in policy['daemon'].values()}
    return BinaryAuthenticator(expected)


def _check_binary_authenticator(policy, value):
    mode = policy.get('binaryAuthenticationMode')
    if mode is None:
        if value is not None: raise ValueError('binary authenticator without explicit policy')
        return
    if mode != 'full-read-exact-bytes-v1':
        raise ValueError('binary authentication mode')
    from binary_authentication import BinaryAuthenticator
    if type(value) is not BinaryAuthenticator:
        raise ValueError('actual full-read binary authenticator required')
    expected = {item['executable']:item['sha256'] for item in policy['daemon'].values()}
    if value.bindings() != expected:
        raise ValueError('binary authenticator policy bindings differ')


def build_policy(app_pid, serve_pid, helper_path):
    """Read fixed PIDs only; no API/model calls or process mutations."""
    helper_path = Path(helper_path)
    if helper_path.is_symlink() or not helper_path.is_file() or not os.access(helper_path, os.X_OK):
        raise ValueError('native helper must be an existing regular executable')
    helper_path = helper_path.resolve(strict=True)
    helper_path.relative_to(WORKSPACE)
    policy = {'schemaVersion': SCHEMA, 'kind': KIND,
              'daemon': {'app': _read_identity(app_pid), 'serve': _read_identity(serve_pid)},
              'listener': {'address': '127.0.0.1', 'port': 11434, 'pid': serve_pid},
              'api': {'url': API_URL, 'timeoutSeconds': MAX_API_SECONDS, 'maxBytes': MAX_API_BYTES},
              'nativeHelper': {'path': str(helper_path), 'sha256': _file_sha(helper_path), 'sourceSha256': _file_sha(CENSUS_SOURCE)}}
    policy['lifecycle'] = {'moduleSha256':_file_sha(Path(lifecycle_support.__file__)),
        'execShimSha256':_file_sha(Path(__file__).with_name('lifecycle_exec.py')),
        'coordinationLockPath':str(coordination_lock_path(policy)),
        'maxLockWaitSeconds':1.25,'maxObservationSeconds':2.5}
    validate_policy(policy)
    return policy


def _category(name):
    name = name.lower()
    if name == 'dotnet': return 'dotnet'
    if 'godot' in name: return 'godot'
    if name == 'runner' or 'llama' in name: return 'ollama'
    return 'other'


def _run_native(path,lifecycle):
    """One owned child, immutable empty argv suffix, bounded pipes and deadline."""
    started = time.monotonic()
    result = {'spawnedHelperPid': None, 'observerPid': os.getpid(), 'exitCode': None,
              'timedOut': False, 'oversized': False, 'cleanupKnown': False,
              'stdout': b'', 'stderrBytes': 0,'managedLeaseId':None}
    process = None
    selector = selectors.DefaultSelector()
    output, error_bytes = bytearray(), 0
    try:
        remaining=started+NATIVE_TIMEOUT-time.monotonic()
        if remaining<=0:raise TimeoutError('native setup deadline')
        process = lifecycle.launch([str(path)],stage='observer-native-census',
                                  ready_timeout=min(lifecycle_support.READY_SECONDS,remaining),
                                  stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False)
        result['spawnedHelperPid'] = process.pid
        result['managedLeaseId']=process.lease_id
        for stream, kind in ((process.stdout, 'stdout'), (process.stderr, 'stderr')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, kind)
        while selector.get_map():
            remaining = started + NATIVE_TIMEOUT - time.monotonic()
            if remaining <= 0:
                result['timedOut'] = True; break
            events = selector.select(remaining)
            if not events:
                result['timedOut'] = True; break
            for key, _ in events:
                limit = MAX_CENSUS_BYTES + 1 - len(output) if key.data == 'stdout' else 4097 - error_bytes
                block = os.read(key.fileobj.fileno(), max(1, min(65536, limit)))
                if not block:
                    selector.unregister(key.fileobj); continue
                if key.data == 'stdout': output.extend(block)
                else: error_bytes += len(block)
                if len(output) > MAX_CENSUS_BYTES or error_bytes > 4096:
                    result['oversized'] = True; break
            if result['oversized']: break
        if process.poll() is None and not result['timedOut'] and not result['oversized']:
            try: process.wait(timeout=max(0.001, started + NATIVE_TIMEOUT - time.monotonic()))
            except subprocess.TimeoutExpired: result['timedOut'] = True
    except Exception as error:
        result['errorClass'] = type(error).__name__
        if time.monotonic()-started>=NATIVE_TIMEOUT:result['timedOut']=True
        if hasattr(error,'lifecycleRefusal'):
            result['launchRefusal']=error.lifecycleRefusal
            result['spawnedHelperPid']=error.lifecycleRefusal.get('spawnedPid')
        if hasattr(error,'lifecycleRefusalPath'):result['launchRefusalPath']=error.lifecycleRefusalPath
    finally:
        selector.close()
        if process is not None:
            if process.process.poll() is None: process.kill()  # only this exact identity-ready owned collector
            try:
                result['exitCode'] = process.wait(timeout=0.2)
                result['cleanupKnown'] = True
            except Exception as error:
                result['cleanupKnown'] = False
                result['cleanupErrorClass']=type(error).__name__
            for stream in (process.stdout, process.stderr):
                if stream is not None: stream.close()
        result['stdout'], result['stderrBytes'] = bytes(output), error_bytes
        result['durationSeconds'] = time.monotonic() - started
    return result


def _positive_int(value, zero=False):
    return type(value) is int and value >= (0 if zero else 1)


def _capacity(base, abi):
    cap = MAX_KERNEL_BYTES // abi * abi
    desired = max((base * 3 + 1) // 2, base + 64 * abi)
    return min(cap, (desired + abi - 1) // abi * abi)


def _created(microseconds):
    return microseconds // 1000000 + (microseconds % 1000000) / 1000000.0


def _lock_path(helper):
    return WORKSPACE / '.runtime/posix/locks' / ('mac-census-' + _sha_bytes(str(helper).encode()) + '.lock')


@contextmanager
def _capture_lock(helper):
    import fcntl
    path = _lock_path(helper)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.resolve() != path.parent.absolute(): raise ValueError('capture lock ancestor linked')
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    acquired = False
    started = time.monotonic()
    def identity():
        current, named = os.fstat(descriptor), path.lstat()
        if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_uid != os.getuid() or (current.st_dev, current.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError('capture lock identity/ownership changed')
        return {'device': current.st_dev, 'inode': current.st_ino, 'regular': True,
                'singleLink': True, 'ownedByCurrentUser': True}
    metadata = {'schema': 'aijade.mac.capture-lock.v1', 'state': 'UNKNOWN', 'pathSha256': _sha_bytes(str(path).encode()),
                'maxWaitSeconds': LOCK_WAIT_SECONDS, 'maxHoldSeconds': LOCK_HOLD_SECONDS}
    try:
        initial = identity()
        metadata['initialIdentity'] = initial
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True; break
            except BlockingIOError:
                remaining = started + LOCK_WAIT_SECONDS - time.monotonic()
                if remaining <= 0: raise TimeoutError('capture lock wait deadline')
                time.sleep(min(0.005, remaining))
        held = time.monotonic()
        metadata.update({'waitSeconds': held - started, 'initialIdentity': initial, 'state': 'HELD'})
        if metadata['waitSeconds'] > LOCK_WAIT_SECONDS or identity() != initial:
            raise ValueError('capture lock acquisition unknown')
        yield metadata
        metadata.update({'heldSeconds': time.monotonic() - held, 'finalIdentity': identity()})
        if metadata['heldSeconds'] > LOCK_HOLD_SECONDS or metadata['finalIdentity'] != initial:
            raise ValueError('capture lock hold/identity unknown')
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        acquired = False
        metadata['state'] = 'HELD_AND_RELEASED'
    except BaseException as error:
        metadata.update({'state': 'UNKNOWN', 'failureClass': type(error).__name__,
                         'elapsedSeconds': time.monotonic() - started})
        error.captureLockMetadata = metadata
        raise
    finally:
        if acquired: fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def parse_native_evidence(policy, evidence):
    """Pure replay of released-lock evidence; no helper execution/live Mac."""
    expected = policy['nativeHelper']
    lock = evidence.get('captureLock')
    if not isinstance(lock, dict) or lock.get('schema') != 'aijade.mac.capture-lock.v1' or lock.get('state') != 'HELD_AND_RELEASED' or lock.get('pathSha256') != _sha_bytes(str(_lock_path(expected['path'])).encode()) or lock.get('maxWaitSeconds') != LOCK_WAIT_SECONDS or lock.get('maxHoldSeconds') != LOCK_HOLD_SECONDS:
        raise ValueError('native capture lock unknown')
    if not _finite(lock.get('waitSeconds')) or not 0 <= lock['waitSeconds'] <= LOCK_WAIT_SECONDS or not _finite(lock.get('heldSeconds')) or not 0 <= lock['heldSeconds'] <= LOCK_HOLD_SECONDS:
        raise ValueError('native capture lock deadline')
    initial = lock.get('initialIdentity')
    if not isinstance(initial, dict) or initial != lock.get('finalIdentity') or not _positive_int(initial.get('device'), zero=True) or not _positive_int(initial.get('inode')) or any(initial.get(key) is not True for key in ('regular', 'singleLink', 'ownedByCurrentUser')):
        raise ValueError('native capture lock identity')
    return _parse_native_payload(policy, evidence)


def _parse_native_payload(policy, evidence):
    expected = policy['nativeHelper']
    for field, wanted in [('helperSha256Before', expected['sha256']), ('helperSha256After', expected['sha256']),
                          ('sourceSha256Before', expected['sourceSha256']), ('sourceSha256After', expected['sourceSha256'])]:
        if evidence.get(field) != wanted: raise ValueError('native helper/source substituted')
    if evidence.get('exitCode') != 0 or type(evidence.get('exitCode')) is not int or evidence.get('cleanupKnown') is not True or evidence.get('timedOut') is not False or evidence.get('oversized') is not False or type(evidence.get('stderrBytes')) is not int or evidence['stderrBytes'] != 0 or not _pid(evidence.get('spawnedHelperPid')) or not _positive_int(evidence.get('observerPid')):
        raise ValueError('native subprocess adverse')
    elapsed = evidence.get('durationSeconds')
    if not _finite(elapsed) or not 0 <= elapsed <= NATIVE_TIMEOUT: raise ValueError('native total deadline')
    if evidence.get('observerClockKind') != 'python.time.monotonic': raise ValueError('native observer clock provenance')
    encoded = evidence.get('stdoutBase64')
    if not isinstance(encoded, str) or len(encoded) > ((MAX_CENSUS_BYTES + 2) // 3) * 4: raise ValueError('native output cap')
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > MAX_CENSUS_BYTES or type(evidence.get('stdoutBytes')) is not int or evidence['stdoutBytes'] != len(raw) or evidence.get('stdoutSha256') != _sha_bytes(raw): raise ValueError('native raw bytes mismatch')
    data = json.loads(raw, object_pairs_hook=_json_unique)
    if data.get('schema') != CENSUS_SCHEMA or data.get('status') != 'OK': raise ValueError('native kernel response adverse')
    expected_fields = {'schema', 'status', 'recordCount', 'returnedBytes', 'abiRecordBytes', 'sizeQueryBytes',
                       'initialCapacityBytes', 'capacityBytes', 'readAttempts', 'enomemGrowths', 'maxCapacityBytes',
                       'maxReadAttempts', 'maxOutputBytes', 'startedMonotonicNs', 'finishedMonotonicNs', 'clockKind',
                       'nameField', 'commandNameMaxBytes', 'categoryRule', 'atLimitCount', 'recordsSortedByPid',
                       'notAtomicMachineHistory', 'collector', 'readHistory', 'attemptCapacities', 'readErrnos', 'records'}
    if set(data) != expected_fields: raise ValueError('native protocol field set unknown')
    for field in ('recordCount', 'returnedBytes', 'abiRecordBytes', 'sizeQueryBytes', 'initialCapacityBytes', 'capacityBytes',
                  'readAttempts', 'enomemGrowths', 'maxCapacityBytes', 'maxReadAttempts', 'maxOutputBytes',
                  'startedMonotonicNs', 'finishedMonotonicNs', 'commandNameMaxBytes', 'atLimitCount'):
        if not _positive_int(data.get(field), zero=True): raise ValueError('native integer metadata missing')
    abi, returned, count = data.get('abiRecordBytes'), data.get('returnedBytes'), data.get('recordCount')
    if not _positive_int(abi) or abi > 65536 or not _positive_int(returned) or returned > MAX_KERNEL_BYTES or not _positive_int(count) or returned != abi * count:
        raise ValueError('empty/truncated/misaligned native response')
    if data.get('maxCapacityBytes') != MAX_KERNEL_BYTES or data.get('maxReadAttempts') != 3 or data.get('maxOutputBytes') != MAX_CENSUS_BYTES:
        raise ValueError('native collection bounds changed')
    query, history = data.get('sizeQueryBytes'), data.get('readHistory')
    if not _positive_int(query) or query > MAX_KERNEL_BYTES or not isinstance(history, list) or not 1 <= len(history) <= 3:
        raise ValueError('native read history invalid')
    capacity = _capacity(query, abi)
    for key in ('attemptCapacities', 'readErrnos'):
        if not isinstance(data.get(key), list) or any(type(value) is not int for value in data[key]):
            raise ValueError('native history summary types')
    capacities, errors = [], []
    for index, attempt in enumerate(history):
        if not isinstance(attempt, dict) or set(attempt) != {'capacityBytes', 'returnedBytes', 'result', 'errno'}:
            raise ValueError('native read record incomplete')
        if any(type(attempt[key]) is not int for key in attempt): raise ValueError('native read record types')
        if attempt['capacityBytes'] != capacity or not _positive_int(attempt['returnedBytes'], zero=True) or attempt['returnedBytes'] > MAX_KERNEL_BYTES:
            raise ValueError('native capacity history invalid')
        capacities.append(capacity); errors.append(attempt['errno'])
        if index == len(history) - 1:
            if attempt['result'] != 0 or attempt['errno'] != 0 or attempt['returnedBytes'] != returned or returned > capacity:
                raise ValueError('native last read did not complete')
        else:
            if attempt['result'] != -1 or attempt['errno'] != 12: raise ValueError('only ENOMEM may grow')
            grown = _capacity(max(capacity, attempt['returnedBytes']), abi)
            if grown <= capacity: raise ValueError('native capacity cannot grow')
            capacity = grown
    if data.get('initialCapacityBytes') != capacities[0] or data.get('capacityBytes') != capacities[-1] or data.get('readAttempts') != len(history) or data.get('enomemGrowths') != len(history) - 1 or data.get('attemptCapacities') != capacities or data.get('readErrnos') != errors:
        raise ValueError('native history summaries disagree')
    start, finish = data.get('startedMonotonicNs'), data.get('finishedMonotonicNs')
    if not _positive_int(start, zero=True) or not _positive_int(finish, zero=True) or finish < start:
        raise ValueError('native clock invalid')
    native_duration = (finish - start) / 1000000000
    if native_duration > NATIVE_TIMEOUT or native_duration > elapsed + CLOCK_ENVELOPE_TOLERANCE or data.get('clockKind') != 'clock_gettime.CLOCK_MONOTONIC':
        raise ValueError('native duration outside envelope')
    if data.get('notAtomicMachineHistory') is not True or data.get('recordsSortedByPid') is not True or data.get('nameField') != 'kinfo_proc.p_comm' or data.get('categoryRule') != 'ascii-casefold-kinfo-comm-v1' or not _positive_int(data.get('commandNameMaxBytes')):
        raise ValueError('native name/clock semantics unknown')
    records = data.get('records')
    if not isinstance(records, list) or len(records) != count: raise ValueError('native population missing')
    nodes, seen, at_limit = [], set(), 0
    for item in records:
        if not isinstance(item, dict) or set(item) != {'pid', 'parentPid', 'createTimeMicros', 'category', 'commandNameAtLimit'}:
            raise ValueError('native row schema')
        pid, parent, created = item['pid'], item['parentPid'], item['createTimeMicros']
        if not _positive_int(pid, zero=True) or pid > 2147483647 or pid in seen or not _positive_int(parent, zero=True) or parent > 2147483647 or not _positive_int(created, zero=pid == 0) or created > 9223372036854775807 or item['category'] not in ('other', 'dotnet', 'godot', 'ollama') or type(item['commandNameAtLimit']) is not bool:
            raise ValueError('duplicate/invalid/unknown native identity')
        seen.add(pid); at_limit += item['commandNameAtLimit']
        nodes.append({'pid': pid, 'parentPid': parent, 'createTime': _created(created), 'createTimeMicros': created,
                      'category': item['category'], 'commandNameAtLimit': item['commandNameAtLimit']})
    if [x['pid'] for x in nodes] != sorted(seen) or data.get('atLimitCount') != at_limit:
        raise ValueError('native ordering/name population mismatch')
    collector = data.get('collector')
    if not isinstance(collector, dict) or set(collector) != {'pid', 'parentPid', 'createTimeMicros', 'rssBytes'} or any(not _positive_int(collector[key]) for key in collector) or collector['pid'] != evidence.get('spawnedHelperPid') or collector['parentPid'] != evidence.get('observerPid'):
        raise ValueError('native self RSS identity unknown')
    self_row = next((x for x in nodes if x['pid'] == collector['pid']), None)
    if self_row is None or any(self_row[key] != collector[key] for key in ('parentPid', 'createTimeMicros')):
        raise ValueError('native self row missing/reused')
    return nodes, collector


def _read_processes(policy,lifecycle):
    expected = policy['nativeHelper']
    graph = {'schema': 'aijade.mac.bulk-process-graph.v2', 'nodes': [], 'errors': [], 'nativeCensus': {}}
    evidence = graph['nativeCensus']
    try:
        evidence['helperSha256Before'] = _file_sha(expected['path'])
        evidence['sourceSha256Before'] = _file_sha(CENSUS_SOURCE)
        if evidence['helperSha256Before'] != expected['sha256'] or evidence['sourceSha256Before'] != expected['sourceSha256']:
            raise ValueError('native helper/source changed before execution')
        with _capture_lock(expected['path']) as lock:
            evidence['captureLock'] = lock
            result = _run_native(expected['path'],lifecycle)
            raw = result.pop('stdout')
            evidence.update(result)
            evidence.update({'stdoutBase64': base64.b64encode(raw).decode('ascii'), 'stdoutSha256': _sha_bytes(raw), 'stdoutBytes': len(raw),
                             'helperSha256After': _file_sha(expected['path']), 'sourceSha256After': _file_sha(CENSUS_SOURCE),
                             'observerClockKind': 'python.time.monotonic'})
            # Validate the raw payload while held; never fabricate a release
            # witness. Public replay also requires the actual release below.
            graph['nodes'], _ = _parse_native_payload(policy, evidence)
        graph['nodes'], _ = parse_native_evidence(policy, evidence)
    except Exception as error:
        if hasattr(error, 'captureLockMetadata'): evidence['captureLock'] = error.captureLockMetadata
        graph['errors'].append({'code': 'BULK_CENSUS_UNKNOWN', 'errorClass': type(error).__name__})
    return graph


def _owned_ids(nodes, roots):
    # Missing required roots keep the valid partial forest for diagnosis only.
    by_pid = {x['pid']:x for x in nodes}
    members = {root['pid'] for root in roots if root['pid'] in by_pid and by_pid[root['pid']]['createTime']==root['createTime']}
    while True:
        extra={x['pid'] for x in nodes if x['parentPid'] in members and x['pid'] not in members}
        if not extra:return members
        members.update(extra)


def coordination_lock_path(policy):
    return lifecycle_support.coordination_lock_path(policy)


def _absence_time(value):
    if value.get('witnessKind')=='PARENT_WAIT_REAPED':return value['reapedMonotonic']
    return value['graphCompletedMonotonic']


def _typed_members(nodes,roots,state,controller,frame,collector,add,phase):
    by_pid={x['pid']:x for x in nodes}
    members=_owned_ids(nodes,roots)
    leases={lifecycle_support.identity_key(v['identity']):v for v in state['leases'].values()}
    local={lifecycle_support.identity_key(controller)} if roots else set()
    family=set(local)
    while True:
        extra={key for key,value in leases.items() if value['parentIdentity'] is not None and lifecycle_support.identity_key(value['parentIdentity']) in family}
        if extra <= family:break
        family.update(extra)
    for root in roots:
        node=by_pid.get(root['pid'])
        if node is None:add('PERSISTENT_CONTROLLER_MISSING',phase=phase,pid=root['pid'])
        elif node['createTime']!=root['createTime']:add('PERSISTENT_CONTROLLER_PID_REUSED','FAIL',phase=phase,pid=root['pid'])
        elif node['parentPid']!=controller['parentPid']:add('PERSISTENT_CONTROLLER_PARENT_CHANGED','FAIL',phase=phase,pid=root['pid'])
    completed=frame['graphCompletedMonotonic'];started=frame['graphStartedMonotonic']
    for key in family:
        lease=leases.get(key)
        if lease is None:
            add('CONTROLLER_LEASE_MISSING',phase=phase);continue
        node=by_pid.get(key[0]);present=node is not None and lifecycle_support.key_from_node(node)==key
        if present:
            if lease['absence'] is not None and _absence_time(lease['absence'])<=started:
                add('REAPPEARED_OWNED_IDENTITY','FAIL',phase=phase,pid=node['pid'])
            if node['parentPid'] != lease['identity']['parentPid']:add('OWNED_PARENT_CHANGED','FAIL',phase=phase,pid=node['pid'])
            if node['pid'] not in members:add('OWNED_ANCESTRY_ESCAPE','FAIL',phase=phase,pid=node['pid'])
            if lease['waitSeq'] is not None and lease['reapedMonotonic']<=started:add('REAPED_IDENTITY_PRESENT','FAIL',phase=phase,pid=node['pid'])
        elif lease['role']=='finite' and lease.get('releaseMonotonic',float('inf'))<=started:
            if node is not None and lease['absence'] is None:add('OWNED_PID_REUSED','FAIL',phase=phase,pid=key[0])
            if lease['waitSeq'] is None or lease['reapedMonotonic']>completed:
                add('ABSENT_EXIT_STATUS_UNKNOWN',phase=phase,pid=key[0])
        if lease['role']=='finite' and lease['waitSeq'] is not None and lease['exitCode']!=0:
            add('FINITE_NONZERO_OR_SIGNAL_EXIT','FAIL',phase=phase,pid=key[0])
    # A census-proven descendant is recorded as discovered, never promoted to a
    # persistent lease or declared a normally completed task. Its live RSS and
    # ancestry remain mandatory; eventual complete absence is cleanup evidence.
    if roots:
        for key,value in state['discovered'].items():
            if key in leases:continue
            # The shared journal includes sibling scopes. Responsibility follows
            # original, validated ancestry, including a parent-observed process
            # whose chain passes through this local controller. A malformed or
            # missing chain is adverse, never permission to omit an identity.
            try:
                chain=value.get('ancestry')
                if type(chain) is not list or len(chain)<2:raise ValueError('discovery ancestry missing')
                keys=[lifecycle_support.identity_key(item) for item in chain]
                scope=state['scopes'][value['scopeId']]
                if (chain[0]!=value['identity'] or keys[0]!=key
                    or chain[-1]!=scope['controllerIdentity']
                    or len(keys)!=len(set(keys))
                    or not all(a['parentPid']==b['pid'] and b['createTimeMicros']<=a['createTimeMicros']
                               for a,b in zip(chain,chain[1:]))):
                    raise ValueError('discovery ancestry binding')
            except (KeyError,TypeError,ValueError):
                add('DISCOVERED_ANCESTRY_INVALID','FAIL',phase=phase,pid=key[0]);continue
            if not family.intersection(keys):continue
            node=by_pid.get(key[0])
            if node is not None and lifecycle_support.key_from_node(node)==key:
                if value.get('absence') is not None and _absence_time(value['absence'])<=started:
                    add('DISCOVERED_IDENTITY_REAPPEARED','FAIL',phase=phase,pid=key[0])
                if node['parentPid']!=value['identity']['parentPid']:add('DISCOVERED_PARENT_CHANGED','FAIL',phase=phase,pid=key[0])
                if node['pid'] not in members:add('DISCOVERED_ANCESTRY_ESCAPE','FAIL',phase=phase,pid=key[0])
            elif node is not None and value.get('absence') is None:
                add('DISCOVERED_PID_REUSED','FAIL',phase=phase,pid=key[0])
    return members


def _read_rss(node):
    import psutil
    process = psutil.Process(node['pid'])
    if process.create_time() != node['createTime']:
        raise ValueError('owned PID reused')
    rss = process.memory_info().rss
    if psutil.Process(node['pid']).create_time() != node['createTime']:
        raise ValueError('owned PID reused during RSS read')
    return rss


def _read_listeners(lifecycle):
    """macOS system connection enumeration may require root; lsof is bounded."""
    try:
        started = time.monotonic()
        result = lifecycle.run(['/usr/sbin/lsof', '-nP', '-iTCP:11434', '-sTCP:LISTEN', '-FpfPtTn'],
                                capture_output=True, timeout=0.5, check=False)
        if time.monotonic()-started > 0.5 or result.returncode != 0 or result.stderr or len(result.stdout) > MAX_API_BYTES:
            return {'state': 'UNKNOWN', 'code': 'LISTENER_ENUMERATION_UNKNOWN'}
        records, process_pid, current = [], None, None
        def flush():
            if current is not None: records.append(dict(current))
        for line in result.stdout.decode('ascii').splitlines():
            if not line: continue
            code, value = line[0], line[1:]
            if code == 'p':
                flush(); current = None; process_pid = int(value)
            elif code == 'f':
                flush(); current = {'pid': process_pid}
            elif current is not None and code in ('P', 't', 'n'):
                current[{'P': 'protocol', 't': 'family', 'n': 'endpoint'}[code]] = value
            elif current is not None and code == 'T' and value.startswith('ST='):
                current['socketState'] = value[3:]
        flush()
        return {'state': 'OBSERVED', 'records': records}
    except Exception as error:
        return {'state': 'UNKNOWN', 'code': 'LISTENER_READ_UNKNOWN', 'errorClass': type(error).__name__}


def _json_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate API JSON key')
        result[key] = value
    return result


class _MemorySocket:
    def __init__(self, raw): self.raw = raw
    def makefile(self, *args, **kwargs): return io.BytesIO(self.raw)


def _read_api(config):
    """Direct IPv4 socket, no proxy/redirect, one absolute wall-time deadline."""
    started, raw = time.monotonic(), bytearray()
    timeout, cap = config['timeoutSeconds'], config['maxBytes']
    deadline = started + timeout
    answer = {'state': 'UNKNOWN', 'code': 'API_READ_UNKNOWN'}
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0: raise TimeoutError('total API deadline')
        return value
    try:
        with socket.create_connection(('127.0.0.1', 11434), timeout=remaining()) as connection:
            connection.settimeout(remaining())
            connection.sendall(b'GET /api/ps HTTP/1.1\r\nHost: 127.0.0.1:11434\r\nAccept: application/json\r\nConnection: close\r\n\r\n')
            header_end, content_length = -1, None
            while True:
                connection.settimeout(remaining())
                block = connection.recv(min(8192, cap + 12288 - len(raw) + 1))
                if not block: break
                raw.extend(block)
                if len(raw) > cap + 12288: raise ValueError('response cap')
                if header_end < 0:
                    header_end = raw.find(b'\r\n\r\n')
                    if header_end < 0 and len(raw) > 8192: raise ValueError('header cap')
                    if header_end >= 0:
                        if header_end > 8192: raise ValueError('header cap')
                        headers = http.client.parse_headers(io.BytesIO(bytes(raw).split(b'\r\n', 1)[1][:header_end]))
                        length = headers.get('Content-Length')
                        if length is not None:
                            if headers.get('Transfer-Encoding') is not None: raise ValueError('ambiguous HTTP framing')
                            content_length = int(length)
                            if not 0 <= content_length <= cap: raise ValueError('body cap')
                if header_end >= 0 and content_length is not None and len(raw) >= header_end + 4 + content_length:
                    if len(raw) != header_end + 4 + content_length: raise ValueError('trailing HTTP data')
                    break
        if header_end < 0 or (content_length is not None and len(raw) != header_end + 4 + content_length):
            raise ValueError('incomplete HTTP response framing')
        response = http.client.HTTPResponse(_MemorySocket(bytes(raw)))
        response.begin()
        if response.status != 200:
            answer = {'state': 'UNKNOWN', 'code': 'API_HTTP_STATUS', 'httpStatus': response.status}
        else:
            body = response.read(cap + 1)
            if len(body) > cap: raise ValueError('decoded body cap')
            parsed = json.loads(body, object_pairs_hook=_json_unique)
            answer = {'state': 'UNKNOWN', 'code': 'API_SCHEMA_UNKNOWN', 'httpStatus': 200,
                      'bytes': len(body), 'bodySha256': _sha_bytes(body)}
            if isinstance(parsed, dict) and set(parsed) == {'models'} and isinstance(parsed['models'], list):
                answer.update({'state': 'EMPTY' if not parsed['models'] else 'NONEMPTY', 'modelCount': len(parsed['models'])})
                answer.pop('code', None)
                if not parsed['models']:
                    answer['emptyBodyBase64'] = base64.b64encode(body).decode('ascii')
        remaining()
    except Exception as error:
        answer = {'state': 'UNKNOWN', 'code': 'API_READ_UNKNOWN', 'errorClass': type(error).__name__}
    answer['durationSeconds'] = time.monotonic() - started
    return answer


def _normalize_roots(roots):
    result = []
    for root in roots:
        if isinstance(root, dict): pid, created = root['pid'], root['createTime']
        else: pid, created = root
        if not _pid(pid) or not _finite(created) or created <= 0 or any(x['pid'] == pid for x in result):
            raise ValueError('invalid or duplicate owned root')
        result.append({'pid': pid, 'createTime': created})
    return sorted(result, key=lambda x: x['pid'])


def _daemon_snapshot(policy, *, binary_authenticator=None):
    """Read actual daemon identities and complete executable bytes, without a mutation lock."""
    result = dict(daemon={}, errors=[])
    started = time.monotonic()
    for role in ('app', 'serve'):
        try:
            item = (_read_identity(policy['daemon'][role]['pid']) if binary_authenticator is None else
                    _read_identity(policy['daemon'][role]['pid'], binary_authenticator=binary_authenticator))
            item['executablePathSha256'] = _sha_bytes(item.pop('executable').encode())
            result['daemon'][role] = item
        except Exception as error:
            result['errors'].append({'code':'DAEMON_IDENTITY_READ_UNKNOWN','role':role,'errorClass':type(error).__name__})
    result['daemonIdentityReadClock'] = dict(startedMonotonic=started, finishedMonotonic=time.monotonic())
    return result


def _snapshot(policy, roots, lifecycle, *, binary_authenticator=None, daemon_sample=None):
    graph_started=time.monotonic()
    graph=_read_processes(policy,lifecycle)
    result={'processGraph':graph,'daemon':{},'ownedProcesses':[],'errors':[],
            'graphStartedMonotonic':graph_started,'graphCompletedMonotonic':time.monotonic()}
    collector=None
    if not graph['errors']:
        try:_,collector=parse_native_evidence(policy,graph['nativeCensus'])
        except Exception:result['errors'].append({'code':'NATIVE_COLLECTOR_WITNESS_UNKNOWN'})
    if daemon_sample is None:
        for role in ('app','serve'):
            try:
                item=(_read_identity(policy['daemon'][role]['pid']) if binary_authenticator is None else
                      _read_identity(policy['daemon'][role]['pid'],binary_authenticator=binary_authenticator))
                item['executablePathSha256']=_sha_bytes(item.pop('executable').encode());result['daemon'][role]=item
            except Exception as error:result['errors'].append({'code':'DAEMON_IDENTITY_READ_UNKNOWN','role':role,'errorClass':type(error).__name__})
    else:
        result['daemon'] = daemon_sample['daemon']
        result['errors'].extend(daemon_sample['errors'])
        result['daemonIdentityReadClock'] = daemon_sample['daemonIdentityReadClock']
        rss_started = time.monotonic()
    members=_owned_ids(graph['nodes'],roots)
    for node in graph['nodes']:
        if node['pid'] not in members:continue
        try:
            exact=collector is not None and node['pid']==collector['pid'] and node['createTimeMicros']==collector['createTimeMicros'] and node['parentPid']==collector['parentPid']
            rss=collector['rssBytes'] if exact else _read_rss(node)
            result['ownedProcesses'].append({key:node[key] for key in ('pid','createTime','parentPid')} |
                {'rssBytes':rss,'rssSource':'native-collector-self' if exact else 'psutil-live'})
        except Exception as error:
            result['errors'].append({'code':'OWNED_PROCESS_RSS_UNKNOWN','pid':node['pid'],'errorClass':type(error).__name__})
    result['ownedProcesses'].sort(key=lambda x:x['pid'])
    if daemon_sample is not None:
        result['ownedRssReadClock'] = dict(startedMonotonic=rss_started, finishedMonotonic=time.monotonic())
        listener_started = time.monotonic()
    if policy.get('lifecycleExecMode') is not None:
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
            result['listenerReadClock'] = dict(startedMonotonic=listener_started, finishedMonotonic=time.monotonic())
    return result


def _validate_segmented_coordination(policy, observation, start, end, add):
    """Validate recorded per-snapshot exclusion, never invent a whole-observation lock."""
    if (observation.get('coordinationMode') != SEGMENTED_MODE
            or observation.get('coordinationSchema') != SEGMENTED_SCHEMA
            or 'coordinationLock' in observation):
        add('SEGMENTED_COORDINATION_SCHEMA_OR_MODE_MISMATCH', 'FAIL')
        return
    locks = observation.get('coordinationLocks')
    if type(locks) is not dict or set(locks) != {'before', 'after'}:
        add('SEGMENTED_COORDINATION_LOCK_POPULATION_MISMATCH', 'FAIL')
        return
    clocks = {}
    identities = []
    path_sha = _sha_bytes(str(coordination_lock_path(policy)).encode())
    for phase in ('before', 'after'):
        lock = locks[phase]
        if (type(lock) is not dict or lock.get('schema') != 'aijade.lifecycle.capture-lock.v1'
                or lock.get('state') != 'HELD_AND_RELEASED' or lock.get('pathSha256') != path_sha
                or lock.get('maxWaitSeconds') != 1.25 or lock.get('nested') is not False):
            add('SEGMENTED_COORDINATION_LOCK_UNKNOWN', 'FAIL', phase=phase)
            continue
        initial, final = lock.get('initialIdentity'), lock.get('finalIdentity')
        if (type(initial) is not dict or initial != final
                or type(initial.get('device')) is not int or initial['device'] < 0
                or type(initial.get('inode')) is not int or initial['inode'] <= 0
                or any(initial.get(k) is not True for k in ('regular','singleLink','ownedByCurrentUser'))):
            add('SEGMENTED_COORDINATION_LOCK_IDENTITY_UNKNOWN', 'FAIL', phase=phase)
            continue
        identities.append(initial)
        requested, acquired, released, wait = (lock.get(key) for key in
            ('requestStartedMonotonic','acquiredMonotonic','releasedMonotonic','waitSeconds'))
        if (not all(_finite(value) for value in (requested,acquired,released,wait))
                or not start <= requested <= acquired <= released <= end or not 0 <= wait <= acquired-requested <= 1.25
                or acquired-requested > 1.25
                or released-acquired > 1.25):
            add('SEGMENTED_COORDINATION_LOCK_CLOCK_UNKNOWN', 'FAIL', phase=phase)
            continue
        frame = observation['evidence'][phase]
        frame_clocks = []
        for name in ('daemonIdentityReadClock','ownedRssReadClock','listenerReadClock'):
            value = frame.get(name)
            if (type(value) is not dict or set(value) != {'startedMonotonic','finishedMonotonic'}
                    or not all(_finite(value.get(key)) for key in value)
                    or not start <= value['startedMonotonic'] <= value['finishedMonotonic'] <= end):
                add('SEGMENTED_SNAPSHOT_CLOCK_UNKNOWN', 'FAIL', phase=phase, clock=name)
                break
            frame_clocks.append(value)
        if len(frame_clocks) != 3:
            continue
        daemon, rss, listener = frame_clocks
        began, completed = frame.get('graphStartedMonotonic'), frame.get('graphCompletedMonotonic')
        if (not all(_finite(value) for value in (began,completed))
                or not daemon['finishedMonotonic'] <= requested <= acquired <= began <= completed
                    <= rss['startedMonotonic'] <= rss['finishedMonotonic']
                    <= listener['startedMonotonic'] <= listener['finishedMonotonic'] <= released):
            add('SEGMENTED_SNAPSHOT_OUTSIDE_MUTATION_LOCK', 'FAIL', phase=phase)
            continue
        clocks[phase] = dict(daemon=daemon, acquired=acquired, released=released)
    if len(identities) == 2 and identities[0] != identities[1]:
        add('SEGMENTED_COORDINATION_LOCK_REPLACED_BETWEEN_PHASES', 'FAIL')
    api = observation.get('segmentedApiClock')
    if (type(api) is not dict or set(api) != {'startedMonotonic','finishedMonotonic'}
            or not all(_finite(api.get(key)) for key in api)
            or not start <= api['startedMonotonic'] <= api['finishedMonotonic'] <= end
            or api['finishedMonotonic']-api['startedMonotonic'] > policy['api']['timeoutSeconds']):
        add('SEGMENTED_API_CLOCK_UNKNOWN', 'FAIL')
    elif len(clocks) == 2:
        if not (clocks['before']['released'] <= api['startedMonotonic'] <= api['finishedMonotonic']
                <= clocks['after']['daemon']['startedMonotonic']):
            add('SEGMENTED_BEFORE_API_AFTER_ORDER_MISMATCH', 'FAIL')
        duration = observation['evidence']['api'].get('durationSeconds')
        if not _finite(duration) or duration > api['finishedMonotonic']-api['startedMonotonic']:
            add('SEGMENTED_API_DURATION_OUTSIDE_ENVELOPE', 'FAIL')


def _decision(blockers, owned=None):
    status = 'FAIL' if any(x['severity'] == 'FAIL' for x in blockers) else 'UNKNOWN' if blockers else 'PASS'
    rows = owned if owned is not None else []
    return {'status': status, 'blockers': blockers, 'ownedProcesses': rows,
            'ownedRssBytes': sum(x['rssBytes'] for x in rows) if status == 'PASS' and owned is not None else None}


def _guard_decision_from_validated_lifecycle(policy, observation, state):
    """Recompute from recorded facts, not claimed PASS or derived RSS totals."""
    blockers = []

    def add(code, severity='UNKNOWN', **fields):
        blockers.append({'code': code, 'severity': severity, **fields})
    try:
        replay_keys = ('onlineReplayMode', 'onlineReplaySourceSha256', 'onlineReplayInitializationMode', 'onlineReplayPreparation')
        if policy.get('onlineReplayMode') in (CLONE_REPLAY_MODE, OWNED_REPLAY_MODE):
            if observation.get('onlineReplayMode') != policy['onlineReplayMode'] or observation.get('onlineReplaySourceSha256') != policy['onlineReplaySourceSha256'] or observation.get('onlineReplayInitializationMode') != policy['onlineReplayInitializationMode']:
                add('CLONE_REPLAY_MODE_OR_SOURCE_MISMATCH', 'FAIL')
            reference = observation.get('onlineReplayPreparation')
            keys = {'path', 'sha256', 'mode', 'prefixBytes', 'prefixSha256', 'lastSequence', 'scopeId', 'sourceCommit', 'policySha256', 'cursorSourceSha256'}
            if policy.get('onlineReplayMode') == OWNED_REPLAY_MODE:
                keys |= {'ownerId', 'ownerRole', 'pairedOwnerId', 'guardPredicateAstSha256'}
            if type(reference) is not dict or set(reference) != keys or reference.get('mode') != policy['onlineReplayInitializationMode'] or (not _hex(reference.get('sha256'))) or (not _hex(reference.get('prefixSha256'))) or (reference.get('cursorSourceSha256') != policy['onlineReplaySourceSha256']) or (type(reference.get('prefixBytes')) is not int) or (not 0 < reference['prefixBytes'] <= observation['lifecycle']['journalBytes']) or (type(reference.get('lastSequence')) is not int) or (not 0 < reference['lastSequence'] <= observation['lifecycle']['lastSequence']) or (reference.get('scopeId') != observation['lifecycle']['scopeId']) or (reference.get('sourceCommit') != state['sourceCommit']) or (reference.get('policySha256') != state['policySha256']) or (type(reference.get('path')) is not str) or (not Path(reference['path']).is_absolute()) or ('..' in Path(reference['path']).parts) or (WORKSPACE not in Path(reference['path']).parents) or (Path(reference['path']).name != 'initialization.json'):
                add('CLONE_REPLAY_PREPARATION_CONTEXT_MISMATCH', 'FAIL')
        elif any((key in observation for key in replay_keys)):
            add('LEGACY_REPLAY_MODE_SUBSTITUTION', 'FAIL')
        if policy.get('onlineReplayMode') == OWNED_REPLAY_MODE:
            reference = observation.get('onlineReplayPreparation')
            if type(reference) is not dict or reference.get('ownerRole') != 'inner' or (not lifecycle_support._hex(reference.get('ownerId'), 32)) or (not lifecycle_support._hex(reference.get('pairedOwnerId'), 32)) or (reference.get('ownerId') == reference.get('pairedOwnerId')) or (reference.get('guardPredicateAstSha256') != _owned_cursor_module(policy).GUARD_PREDICATE_AST_SHA256):
                add('OWNED_REPLAY_OWNER_OR_PREDICATE_MISMATCH', 'FAIL')
            if policy.get('lifecycleExecMode') is not None:
                _validate_native_listener_frames(policy,observation,state,add)
        if policy.get('binaryAuthenticationMode') is not None:
            if observation.get('binaryAuthenticationMode') != policy['binaryAuthenticationMode']:
                add('BINARY_AUTHENTICATION_MODE_MISMATCH', 'FAIL')
            if not observation.get('binaryAuthenticationModuleSha256') == _file_sha(Path(__file__).with_name('binary_authentication.py')) == policy['binaryAuthenticationSourceSha256']:
                add('BINARY_AUTHENTICATION_SOURCE_MISMATCH', 'FAIL')
            work = observation.get('binaryAuthenticationWork')
            if type(work) is not dict or not work or (not all((type(v) is int and v >= 0 for v in work.values()))):
                add('BINARY_AUTHENTICATION_WORK_UNKNOWN')
        if state['launchRefusals']:
            add('LAUNCH_REFUSED', 'FAIL')
        if state.get('launchRefusalArtifacts'):
            add('LAUNCH_REFUSED_ARTIFACT_PRESENT', 'FAIL')
        controller = observation['lifecycle']['controllerIdentity']
        all_native_identities = set()
        if observation.get('lifecycleModuleSha256') != policy['lifecycle']['moduleSha256']:
            add('LIFECYCLE_MODULE_IDENTITY_MISMATCH', 'FAIL')
        if observation.get('preservedV2SourceSha256') != _file_sha(Path(__file__).with_name('mac_process_guard_v2.py')):
            add('PRESERVED_V2_IDENTITY_MISMATCH', 'FAIL')
        if observation.get('lifecyclePolicySha256') != state['policySha256']:
            add('LIFECYCLE_POLICY_CONTEXT_MISMATCH', 'FAIL')
        if not isinstance(observation, dict) or observation.get('schemaVersion') != SCHEMA:
            raise ValueError('observation schema')
        if observation.get('policyCanonicalSha256') != canonical_sha256(policy):
            add('POLICY_HASH_MISMATCH', 'FAIL')
        if observation.get('observerModuleSha256') != _file_sha(Path(__file__)):
            add('OBSERVER_IDENTITY_MISMATCH', 'FAIL')
        if observation.get('nativeSourceSha256') != policy['nativeHelper']['sourceSha256'] or _file_sha(CENSUS_SOURCE) != policy['nativeHelper']['sourceSha256']:
            add('NATIVE_SOURCE_IDENTITY_MISMATCH', 'FAIL')
        if observation.get('nativeHelperSha256') != policy['nativeHelper']['sha256']:
            add('NATIVE_HELPER_IDENTITY_MISMATCH', 'FAIL')
        if observation.get('preservedV1SourceSha256') != _file_sha(Path(__file__).with_name('mac_process_guard.py')):
            add('PRESERVED_V1_IDENTITY_MISMATCH', 'FAIL')
        if not isinstance(observation.get('sampleId'), str) or len(observation['sampleId']) != 32 or any((c not in '0123456789abcdef' for c in observation['sampleId'])):
            add('SAMPLE_ID_MISSING')
        start, end = (observation.get('startedMonotonic'), observation.get('finishedMonotonic'))
        if not _finite(start) or not _finite(end) or start < 0 or (end < start) or (end - start > 2.5):
            add('SAMPLE_CLOCK_UNKNOWN')
        roots = _normalize_roots(observation['ownedRoots'])
        if roots and (len(roots) != 1 or roots[0]['pid'] != controller['pid'] or round(roots[0]['createTime'] * 1000000) != controller['createTimeMicros']):
            add('LOCAL_CONTROLLER_ROOT_BINDING_MISMATCH', 'FAIL')
        if policy.get('coordinationMode') == SEGMENTED_MODE:
            _validate_segmented_coordination(policy, observation, start, end, add)
        else:
            if any((key in observation for key in ('coordinationMode', 'coordinationSchema', 'coordinationLocks', 'segmentedApiClock'))):
                add('LEGACY_COORDINATION_MODE_SUBSTITUTION', 'FAIL')
            lock = observation['coordinationLock']
            if lock.get('schema') != 'aijade.lifecycle.capture-lock.v1' or lock.get('state') != 'HELD_AND_RELEASED' or lock.get('pathSha256') != _sha_bytes(str(coordination_lock_path(policy)).encode()) or (lock.get('maxWaitSeconds') != 1.25):
                add('WHOLE_OBSERVATION_LOCK_UNKNOWN')
            elif not _finite(lock.get('waitSeconds')) or not 0 <= lock['waitSeconds'] <= 1.25 or lock.get('initialIdentity') != lock.get('finalIdentity') or (type(lock['initialIdentity'].get('device')) is not int) or (lock['initialIdentity']['device'] < 0) or (type(lock['initialIdentity'].get('inode')) is not int) or (lock['initialIdentity']['inode'] <= 0) or any((lock['initialIdentity'].get(k) is not True for k in ('regular', 'singleLink', 'ownedByCurrentUser'))):
                add('WHOLE_OBSERVATION_LOCK_IDENTITY_OR_WAIT_UNKNOWN')
        expected_pids = {x['pid'] for x in policy['daemon'].values()}
        if expected_pids.intersection((x['pid'] for x in roots)):
            add('DAEMON_CANNOT_BE_OWNED', 'FAIL')
        evidence = observation['evidence']
        owned_after = []
        owned_before = []
        for phase in ('before', 'after'):
            sample = evidence[phase]
            if not isinstance(sample.get('daemon'), dict) or set(sample['daemon']) != {'app', 'serve'}:
                raise ValueError('daemon evidence coverage')
            if not isinstance(sample.get('errors'), list):
                raise ValueError('missing snapshot error coverage')
            if sample.get('errors'):
                add('SNAPSHOT_READ_UNKNOWN', phase=phase)
            graph = sample['processGraph']
            if not isinstance(graph.get('errors'), list):
                raise ValueError('missing process error coverage')
            if graph.get('errors'):
                add('PROCESS_READ_UNKNOWN', phase=phase)
            if not _finite(sample.get('graphStartedMonotonic')) or not _finite(sample.get('graphCompletedMonotonic')) or (not start <= sample['graphStartedMonotonic'] <= sample['graphCompletedMonotonic'] <= end):
                raise ValueError('native graph Python clock envelope')
            nodes = graph.get('nodes')
            if graph.get('schema') != 'aijade.mac.bulk-process-graph.v2' or not isinstance(nodes, list):
                raise ValueError('missing versioned bulk census')
            collector = None
            try:
                raw_nodes, collector = parse_native_evidence(policy, graph['nativeCensus'])
                if raw_nodes != nodes:
                    add('BULK_DERIVED_POPULATION_MISMATCH', 'FAIL', phase=phase)
            except Exception:
                add('BULK_EVIDENCE_UNKNOWN', phase=phase)
            if collector is not None:
                native_lease = state['leases'].get(graph['nativeCensus'].get('managedLeaseId'))
                expected_identity = {key: collector[key] for key in ('pid', 'createTimeMicros', 'parentPid')}
                if native_lease is None or native_lease['role'] != 'finite' or native_lease['stageId'] != 'observer-native-census' or (native_lease['identity'] != expected_identity) or (native_lease['parentIdentity'] != controller) or (collector['parentPid'] != graph['nativeCensus']['observerPid']) or (native_lease['commandSha256'] != canonical_sha256([policy['nativeHelper']['path']])) or (native_lease['executableSha256'] != policy['nativeHelper']['sha256']) or (native_lease['releaseSeq'] is None) or (native_lease['waitSeq'] is None) or (native_lease['exitCode'] != 0) or (native_lease.get('absenceWitnessKind') != 'PARENT_WAIT_REAPED') or (native_lease['reapedMonotonic'] > sample['graphCompletedMonotonic']):
                    add('NATIVE_MANAGED_LIFECYCLE_BINDING_MISMATCH', 'FAIL', phase=phase)
            by_pid = {}
            for node in nodes:
                pid = node['pid']
                if type(pid) is not int or pid < 0 or pid in by_pid or (type(node.get('parentPid')) is not int) or (node['parentPid'] < 0) or (not _finite(node.get('createTime'))) or (node['createTime'] < 0) or (node.get('category') not in ('other', 'dotnet', 'godot', 'ollama')):
                    raise ValueError('invalid process evidence')
                by_pid[pid] = node
            for node in nodes:
                parent = by_pid.get(node['parentPid'])
                if parent and parent['createTime'] > node['createTime']:
                    add('PROCESS_PARENT_IDENTITY_UNKNOWN', phase=phase, pid=node['pid'])
                if node['parentPid'] > 0 and parent is None:
                    add('PROCESS_PARENT_COVERAGE_UNKNOWN', phase=phase, pid=node['pid'])
                seen, ancestor = ({node['pid']}, node['parentPid'])
                while ancestor > 0 and ancestor in by_pid:
                    if ancestor in seen:
                        add('PROCESS_ANCESTRY_CYCLE', phase=phase, pid=node['pid'])
                        break
                    seen.add(ancestor)
                    ancestor = by_pid[ancestor]['parentPid']
            all_native_identities.update((lifecycle_support.key_from_node(x) for x in nodes))
            members = _typed_members(nodes, roots, state, controller, sample, collector, add, phase)
            for role, expected in policy['daemon'].items():
                actual = sample['daemon'].get(role)
                if not isinstance(actual, dict):
                    add('DAEMON_IDENTITY_UNKNOWN', phase=phase, role=role)
                    continue
                if type(actual.get('pid')) is not int or type(actual.get('parentPid')) is not int or (not _finite(actual.get('createTime'))):
                    raise ValueError('daemon evidence types')
                wanted = {key: expected[key] for key in ('pid', 'createTime', 'parentPid', 'sha256', 'argvSha256', 'commandForm')}
                wanted['executablePathSha256'] = _sha_bytes(expected['executable'].encode())
                if actual != wanted:
                    add('DAEMON_IDENTITY_MISMATCH', 'FAIL', phase=phase, role=role)
                node = by_pid.get(expected['pid'])
                if not node:
                    add('DAEMON_CENSUS_MISSING', phase=phase, role=role)
                elif any((node[key] != expected[key] for key in ('createTime', 'parentPid'))) or node['category'] != 'ollama':
                    add('DAEMON_CENSUS_MISMATCH', 'FAIL', phase=phase, role=role)
            descendants = set(expected_pids)
            while True:
                new = {x['pid'] for x in nodes if x['parentPid'] in descendants and x['pid'] not in descendants}
                if not new:
                    break
                descendants.update(new)
            for pid in sorted(descendants - expected_pids):
                add('UNEXPECTED_DAEMON_DESCENDANT', 'FAIL', phase=phase, pid=pid)
            for node in nodes:
                if node['category'] == 'ollama' and node['pid'] not in expected_pids:
                    add('UNKNOWN_OLLAMA_OR_RUNNER', 'FAIL', phase=phase, pid=node['pid'])
                if node['category'] in ('dotnet', 'godot') and node['pid'] not in members:
                    add('FOREIGN_RESEARCH_PROCESS', 'FAIL', phase=phase, pid=node['pid'])
            rows = sample['ownedProcesses']
            if not isinstance(rows, list) or {x['pid'] for x in rows} != members or len(rows) != len(members):
                add('OWNED_RSS_COVERAGE_INCOMPLETE', phase=phase)
            else:
                for row in rows:
                    if type(row.get('rssBytes')) is not int or row['rssBytes'] < 0 or any((row[key] != by_pid[row['pid']][key] for key in ('createTime', 'parentPid'))):
                        add('OWNED_RSS_IDENTITY_UNKNOWN', phase=phase)
                    if row.get('rssSource') == 'native-collector-self':
                        if collector is None or row['pid'] != collector['pid'] or by_pid[row['pid']].get('createTimeMicros') != collector['createTimeMicros'] or (row['parentPid'] != collector['parentPid']) or (row['rssBytes'] != collector['rssBytes']):
                            add('NATIVE_SELF_RSS_WITNESS_UNKNOWN', phase=phase)
                    elif row.get('rssSource') != 'psutil-live' or (collector is not None and row['pid'] == collector['pid']):
                        add('OWNED_RSS_SOURCE_UNKNOWN', phase=phase)
            if phase == 'before':
                owned_before = rows
            else:
                owned_after = rows
                for previous in owned_before:
                    still_present = by_pid.get(previous['pid'])
                    if still_present and still_present['createTime'] == previous['createTime'] and (still_present['parentPid'] != previous['parentPid']) and (previous['pid'] not in members):
                        add('OWNED_PROCESS_REPARENTED_OUTSIDE_CLOSURE', 'FAIL', phase=phase, pid=previous['pid'])
            listener = sample['listener']
            if not isinstance(listener, dict):
                raise ValueError('listener evidence type')
            if listener.get('state') != 'OBSERVED':
                add('LISTENER_OBSERVATION_UNKNOWN', phase=phase)
            elif not isinstance(listener.get('records'), list) or len(listener['records']) != 1 or (not isinstance(listener['records'][0], dict)) or (type(listener['records'][0].get('pid')) is not int) or (listener['records'] != [{'pid': policy['listener']['pid'], 'protocol': 'TCP', 'family': 'IPv4', 'endpoint': '127.0.0.1:11434', 'socketState': 'LISTEN'}]):
                add('LISTENER_IDENTITY_MISMATCH', 'FAIL', phase=phase)
        if observation['lifecycle']['referencedIdentities'] != [list(x) for x in sorted(all_native_identities)]:
            add('LIFECYCLE_REFERENCED_IDENTITY_POPULATION_MISMATCH', 'FAIL')
        api = evidence['api']
        duration = api.get('durationSeconds')
        if not _finite(duration) or duration < 0 or duration > policy['api']['timeoutSeconds']:
            add('API_DEADLINE_UNKNOWN')
        if api.get('state') == 'NONEMPTY':
            add('MODEL_LOADED', 'FAIL')
        elif api.get('state') != 'EMPTY':
            add('API_IDLE_UNKNOWN')
        else:
            try:
                if not isinstance(api.get('emptyBodyBase64'), str) or len(api['emptyBodyBase64']) > (policy['api']['maxBytes'] + 2) // 3 * 4:
                    raise ValueError('empty API evidence cap')
                raw = base64.b64decode(api['emptyBodyBase64'], validate=True)
                parsed = json.loads(raw, object_pairs_hook=_json_unique)
                if parsed != {'models': []} or set(parsed) != {'models'} or type(api.get('httpStatus')) is not int or (api['httpStatus'] != 200) or (type(api.get('modelCount')) is not int) or (api['modelCount'] != 0) or (type(api.get('bytes')) is not int) or (api['bytes'] != len(raw)) or (len(raw) > policy['api']['maxBytes']) or (api.get('bodySha256') != _sha_bytes(raw)):
                    raise ValueError('empty API evidence changed')
            except Exception:
                add('API_EMPTY_EVIDENCE_INVALID', 'FAIL')
        if observation.get('ownedProcesses') != owned_after:
            add('DERIVED_OWNED_PROCESS_LIST_MISMATCH', 'FAIL')
        decision = _decision(blockers, owned_after if all((type(x.get('rssBytes')) is int and x['rssBytes'] >= 0 for x in owned_after)) else [])
        if 'status' in observation and observation['status'] != decision['status']:
            add('CLAIMED_STATUS_MISMATCH', 'FAIL')
        if 'ownedRssBytes' in observation and observation['ownedRssBytes'] != decision['ownedRssBytes']:
            add('DERIVED_RSS_SUM_MISMATCH', 'FAIL')
        return _decision(blockers, decision['ownedProcesses'])
    except Exception:
        add('OBSERVATION_SCHEMA_OR_POLICY_UNKNOWN')
        return _decision(blockers)


def validate_observation(policy,observation,lifecycle_journal=None,*,lifecycle_cursor=None):
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


def observe(policy, owned_roots=(), lifecycle=None, *, lifecycle_cursor=None, binary_authenticator=None):
    """Bounded before/API/after with explicit whole or segmented mutation exclusion."""
    started=time.monotonic()
    result={'schemaVersion':SCHEMA,'sampleId':uuid.uuid4().hex,'startedMonotonic':started,
            'observerModuleSha256':None,'ownedProcesses':[]}
    try:
        validate_policy(policy)
        if not isinstance(lifecycle,lifecycle_support.Registry):raise ValueError('actual registry required for capture')
        if str(lifecycle.lock_path)!=str(coordination_lock_path(policy)):raise ValueError('registry/capture lock differs')
        _check_binary_authenticator(policy,binary_authenticator)
        lifecycle.bind_policy(policy)
        roots=_normalize_roots(owned_roots)
        if policy.get('onlineReplayMode')==OWNED_REPLAY_MODE:
            module=_owned_cursor_module(policy)
            if type(lifecycle_cursor) is not module.OwnedGuardCursor or lifecycle_cursor.owner_role!='inner':
                raise ValueError('exact inner owned guard cursor required for observation')
            result.update(onlineReplayMode=OWNED_REPLAY_MODE,onlineReplaySourceSha256=policy['onlineReplaySourceSha256'],
                onlineReplayInitializationMode=OWNED_INITIALIZATION_MODE,
                onlineReplayPreparation=lifecycle_cursor.preparation_reference())
        elif policy.get('onlineReplayMode')==CLONE_REPLAY_MODE:
            module=_clone_cursor_module(policy)
            if type(lifecycle_cursor) is not module.FullStateCloneCursor:
                raise ValueError('actual new cursor required for C-clone observation')
            result.update(onlineReplayMode=CLONE_REPLAY_MODE,onlineReplaySourceSha256=policy['onlineReplaySourceSha256'],
                onlineReplayInitializationMode=CLONE_INITIALIZATION_MODE,
                onlineReplayPreparation=lifecycle_cursor.preparation_reference())
        result.update(observerModuleSha256=_file_sha(Path(__file__)),nativeSourceSha256=_file_sha(CENSUS_SOURCE),
            nativeHelperSha256=policy['nativeHelper']['sha256'],preservedV1SourceSha256=_file_sha(Path(__file__).with_name('mac_process_guard.py')),
            preservedV2SourceSha256=_file_sha(Path(__file__).with_name('mac_process_guard_v2.py')),
            lifecycleModuleSha256=_file_sha(Path(lifecycle_support.__file__)),lifecyclePolicySha256=lifecycle.policy_sha256,
            observerClockKind='python.time.monotonic',bulkNameScope='kinfo_proc.p_comm; at-limit flags retained; not full executable names',
            policyCanonicalSha256=canonical_sha256(policy),ownedRoots=roots)
        options = {'binary_authenticator':binary_authenticator} if binary_authenticator is not None else {}
        if policy.get('coordinationMode') == SEGMENTED_MODE:
            result.update(coordinationMode=SEGMENTED_MODE, coordinationSchema=SEGMENTED_SCHEMA, coordinationLocks={})
            def segmented_snapshot(phase):
                daemon = _daemon_snapshot(policy, **options)
                requested = time.monotonic()
                with lifecycle_support.capture_lock(coordination_lock_path(policy)) as coordination:
                    coordination['requestStartedMonotonic'] = requested
                    result['coordinationLocks'][phase] = coordination
                    frame = _snapshot(policy, roots, lifecycle, daemon_sample=daemon, **options)
                return frame
            before = segmented_snapshot('before')
            api_started = time.monotonic()
            api = _read_api(policy['api'])
            result['segmentedApiClock'] = dict(startedMonotonic=api_started, finishedMonotonic=time.monotonic())
            after = segmented_snapshot('after')
            refs={lifecycle_support.key_from_node(x) for frame in (before,after) for x in frame['processGraph']['nodes']}
            result.update(evidence={'before':before,'api':api,'after':after},ownedProcesses=after['ownedProcesses'],
                          lifecycle=lifecycle.sample(refs))
        else:
            with lifecycle_support.capture_lock(coordination_lock_path(policy)) as coordination:
                result['coordinationLock']=coordination
                before=_snapshot(policy,roots,lifecycle,**options)
                api=_read_api(policy['api'])
                after=_snapshot(policy,roots,lifecycle,**options)
                refs={lifecycle_support.key_from_node(x) for frame in (before,after) for x in frame['processGraph']['nodes']}
                result.update(evidence={'before':before,'api':api,'after':after},ownedProcesses=after['ownedProcesses'],
                              lifecycle=lifecycle.sample(refs))
        result['finishedMonotonic']=time.monotonic()
        # remember independently parses native evidence and reconstructs the
        # exact local ancestry. Recording those facts is not a PASS grant and
        # never repairs unknown RSS/API evidence. Avoid full-history replay twice.
        lifecycle.remember(result)
        result['lifecycle']=lifecycle.sample(refs)
        if binary_authenticator is not None:
            result.update(binaryAuthenticationMode=policy['binaryAuthenticationMode'],
                binaryAuthenticationModuleSha256=_file_sha(Path(__file__).with_name('binary_authentication.py')),
                binaryAuthenticationWork=binary_authenticator.statistics())
        result['finishedMonotonic']=time.monotonic()
        decision=validate_observation(policy,result,lifecycle_cursor=lifecycle_cursor)
    except Exception as error:
        result['finishedMonotonic']=time.monotonic()
        decision=_decision([{'code':'OBSERVER_READ_UNKNOWN','severity':'UNKNOWN','errorClass':type(error).__name__}])
    result['finishedMonotonic']=time.monotonic()
    if result['finishedMonotonic']-started>2.5:
        decision=_decision(decision['blockers']+[{'code':'WHOLE_OBSERVATION_BUDGET_EXCEEDED','severity':'UNKNOWN'}],
                           decision.get('ownedProcesses'))
    result.update({key:decision[key] for key in ('status','blockers','ownedRssBytes')})
    result['idleDaemon']={'status':decision['status'],'api':result.get('evidence',{}).get('api',{'state':'UNKNOWN'})}
    return result
