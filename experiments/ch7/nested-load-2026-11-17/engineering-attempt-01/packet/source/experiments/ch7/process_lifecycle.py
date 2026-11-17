#!/usr/bin/env python3
"""AIJADE-owned, identity-ready subprocess leases and replayable evidence.

No observation/model call occurs on import or final(). A missing identity is not
an exit status; only the direct owner's Popen.wait records a terminal outcome.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid

BASE = Path('/Volumes/Untitled/AIJADE')
POSIX = BASE / '.runtime/posix'
EVENT_SCHEMA = 'aijade.process-lifecycle-event.v1'
VIEW_SCHEMA = 'aijade.process-lifecycle-view.v1'
MAX_JOURNAL_BYTES = 16 * 1024 * 1024
MAX_LOCK_WAIT = 1.25
READY_SECONDS = 1.0
ZERO = '0' * 64
_locks = threading.local()
_env_registry = None
_env_registry_lock = threading.RLock()


def _synchronized(function):
    def wrapped(self,*args,**kwargs):
        with self._mutex:return function(self,*args,**kwargs)
    return wrapped


def need(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def _hex(value, size=64):
    return type(value) is str and len(value) == size and all(c in '0123456789abcdef' for c in value)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def identity(pid=None):
    import psutil
    process = psutil.Process(os.getpid() if pid is None else pid)
    before = process.create_time()
    parent = process.ppid()
    need(psutil.Process(process.pid).create_time() == before, 'identity reused while reading')
    return dict(pid=process.pid, createTimeMicros=round(before * 1000000), parentPid=parent)


def identity_key(value):
    need(type(value) is dict and set(value) == {'pid', 'createTimeMicros', 'parentPid'}, 'identity schema')
    need(type(value['pid']) is int and value['pid'] > 1
         and type(value['createTimeMicros']) is int and value['createTimeMicros'] > 0
         and type(value['parentPid']) is int and value['parentPid'] > 0, 'identity values')
    return value['pid'], value['createTimeMicros']


def key_from_node(node):
    micros = node.get('createTimeMicros')
    if micros is None:
        need(_number(node.get('createTime')), 'node creation time missing')
        micros = round(node['createTime'] * 1000000)
    return node['pid'], micros


def project_path(value):
    original = Path(value)
    need(original.is_absolute() and '..' not in original.parts, 'absolute canonical project path required')
    resolved = original.resolve()
    need(resolved == original and (resolved == BASE or BASE in resolved.parents), 'path outside project or symlink')
    need(not any(p.is_symlink() for p in (original, *original.parents)), 'symlink in lifecycle path')
    return original


def coordination_lock_path(policy):
    key = digest(str(Path(policy['nativeHelper']['path']).resolve()).encode())
    return POSIX / 'locks' / ('mac-lifecycle-' + key + '.lock')


def _open_owned(path, flags, mode=0o600):
    path = project_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, flags | os.O_NOFOLLOW, mode)
    item = os.fstat(fd)
    try:
        need(stat.S_ISREG(item.st_mode) and item.st_uid == os.getuid() and item.st_nlink == 1
             and not item.st_mode & 0o077, 'unsafe lifecycle file owner/type/mode/link count')
        actual = os.stat(path, follow_symlinks=False)
        need((item.st_dev, item.st_ino) == (actual.st_dev, actual.st_ino), 'lifecycle file replaced')
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def capture_lock(path, timeout=MAX_LOCK_WAIT):
    """Reentrant only within this exact thread; never silently bypass a peer."""
    path = project_path(path)
    need(POSIX in path.parents and _number(timeout) and 0 < timeout <= MAX_LOCK_WAIT,
         'capture lock must be project APFS with bounded timeout')
    active = getattr(_locks, 'active', {})
    token = str(path)
    if token in active:
        yield dict(pathSha256=digest(token.encode()), waitSeconds=0.0, nested=True)
        return
    started = time.monotonic()
    fd = _open_owned(path, os.O_RDWR | os.O_CREAT)
    acquired = False
    metadata = dict(schema='aijade.lifecycle.capture-lock.v1',pathSha256=digest(token.encode()),
                    maxWaitSeconds=MAX_LOCK_WAIT,state='UNKNOWN')
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() - started >= timeout:
                    raise ValueError('lifecycle capture lock timeout')
                time.sleep(min(0.005, timeout - (time.monotonic() - started)))
        active[token] = fd
        _locks.active = active
        item=os.fstat(fd)
        ident=dict(device=item.st_dev,inode=item.st_ino,regular=True,singleLink=True,ownedByCurrentUser=True)
        metadata.update(waitSeconds=time.monotonic()-started,acquiredMonotonic=time.monotonic(),
                        nested=False,initialIdentity=ident,state='HELD')
        yield metadata
        item=os.stat(path,follow_symlinks=False)
        final=dict(device=item.st_dev,inode=item.st_ino,regular=stat.S_ISREG(item.st_mode),
                   singleLink=item.st_nlink==1,ownedByCurrentUser=item.st_uid==os.getuid())
        need(final==ident,'whole observation lock identity changed')
        metadata.update(finalIdentity=final,releasedMonotonic=time.monotonic(),state='HELD_AND_RELEASED')
    finally:
        if acquired:
            active.pop(token, None)
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate journal JSON key')
        result[key] = value
    return result


def replay_journal(raw, _prior=None):
    """Validate exact hash/order and source-bound launch/release/wait state."""
    need(type(raw) is bytes and len(raw) <= MAX_JOURNAL_BYTES, 'journal bytes/cap')
    need(not raw or raw.endswith(b'\n'), 'truncated journal record')
    if _prior is None:
        events,leases,discovered,scopes=[],{},{},{}
        refusals=[]
        identity_index={}
        previous,prior_mono,context=ZERO,-1.0,None
    else:
        events,leases,discovered,scopes=(_prior[k] for k in ('events','leases','discovered','scopes'))
        identity_index=_prior['identityIndex']
        refusals=_prior['launchRefusals']
        previous=events[-1]['sha256'] if events else ZERO
        prior_mono=events[-1]['monotonicSeconds'] if events else -1.0
        context=(_prior['runId'],_prior['sourceCommit'],_prior['policySha256']) if events else None
    for line in raw.splitlines():
        event = json.loads(line, object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite journal')))
        fields = {'schema','seq','event','monotonicSeconds','runId','writer','sourceCommit',
                  'policySha256','data','previousSha256','sha256'}
        need(type(event) is dict and set(event) == fields and event['schema'] == EVENT_SCHEMA, 'journal schema')
        need(type(event['seq']) is int and event['seq'] == len(events)+1
             and event['previousSha256'] == previous, 'journal order/hash chain')
        payload = {k:v for k,v in event.items() if k != 'sha256'}
        need(_hex(event['sha256']) and digest(canonical(payload)) == event['sha256'], 'journal hash changed')
        need(_number(event['monotonicSeconds']) and event['monotonicSeconds'] >= prior_mono, 'journal time reversal')
        identity_key(event['writer'])
        need(_hex(event['runId'],32) and _hex(event['sourceCommit'],40)
             and _hex(event['policySha256']), 'journal source context')
        current = (event['runId'],event['sourceCommit'],event['policySha256'])
        need(context is None or current == context, 'journal context changed')
        context = current
        data, name = event['data'], event['event']
        need(type(data) is dict, 'journal event data')
        if name in ('CONTROLLER_REGISTER','FINITE_REGISTER'):
            lease_id = data['leaseId']; ident = data['identity']; identity_key(ident)
            need(_hex(lease_id,32) and lease_id not in leases and data['role'] in ('controller','finite'), 'duplicate/invalid lease')
            need(type(data['stageId']) is str and data['stageId'] and _hex(data['commandSha256'])
                 and _hex(data['executableSha256']) and _number(data['readyMonotonic'])
                 and data['readyMonotonic'] <= event['monotonicSeconds'], 'launch witness')
            if name == 'CONTROLLER_REGISTER':
                need(data['role'] == 'controller' and ident == event['writer'], 'root registration is not self')
            else:
                identity_key(data['parentIdentity'])
                need(data['parentIdentity'] == event['writer'] and ident['parentPid'] == event['writer']['pid'], 'launch parent mismatch')
                owner_id=identity_index.get(identity_key(event['writer']))
                need(owner_id is not None and leases[owner_id].get('exitCode') is None,
                     'unowned writer launched a child')
            need(identity_key(ident) not in identity_index,'identity has multiple launch leases')
            leases[lease_id] = dict(data, registerSeq=event['seq'],registerMonotonic=event['monotonicSeconds'],releaseSeq=None,
                                    waitSeq=None, exitCode=None, absence=None)
            identity_index[identity_key(ident)]=lease_id
        elif name == 'RELEASE':
            need(data.get('leaseId') in leases,'release before launch')
            lease = leases[data['leaseId']]
            need(lease['role'] == 'finite' and lease['parentIdentity'] == event['writer']
                 and lease['releaseSeq'] is None and lease['waitSeq'] is None, 'invalid exec release')
            lease['releaseSeq'] = event['seq']
            lease['releaseMonotonic'] = event['monotonicSeconds']
        elif name == 'WAIT':
            need(data.get('leaseId') in leases,'wait before launch')
            lease = leases[data['leaseId']]
            need(lease['role'] == 'finite' and lease['parentIdentity'] == event['writer']
                 and lease['identity'] == data['identity'] and lease['releaseSeq'] is not None
                 and lease['waitSeq'] is None and type(data['exitCode']) is int
                 and data['waitSource'] == 'Popen.wait' and _number(data['reapedMonotonic'])
                 and data['reapedMonotonic'] <= event['monotonicSeconds'], 'unbound/duplicate wait result')
            lease.update(waitSeq=event['seq'], exitCode=data['exitCode'],
                         reapedMonotonic=data['reapedMonotonic'])
            # waitpid has reaped this exact directly launched identity. This is
            # absence evidence, including for the last sampling instrument; it
            # does not repair a missing RSS measurement or prove useful work.
            lease['absence']=dict(witnessKind='PARENT_WAIT_REAPED',identity=lease['identity'],
                parentIdentity=lease['parentIdentity'],eventSeq=event['seq'],
                reapedMonotonic=data['reapedMonotonic'],exitCode=data['exitCode'])
            lease['absenceWitnessKind']='PARENT_WAIT_REAPED'
        elif name == 'DISCOVER':
            key = identity_key(data['identity'])
            chain=data.get('ancestry')
            need(type(chain) is list and len(chain)>=2 and chain[0]==data['identity']
                 and chain[-1]==event['writer'],'discovery ancestry endpoints')
            keys=[identity_key(v) for v in chain]
            need(len(keys)==len(set(keys)) and all(a['parentPid']==b['pid']
                 and b['createTimeMicros']<=a['createTimeMicros'] for a,b in zip(chain,chain[1:])),
                 'discovery ancestry edges')
            need(data.get('scopeId') in scopes and scopes[data['scopeId']]['controllerIdentity']==event['writer'],
                 'discovery scope binding')
            need(_hex(data.get('sampleId'),32) and data.get('phase') in ('before','after')
                 and _hex(data.get('nativeStdoutSha256')) and _number(data.get('graphStartedMonotonic'))
                 and _number(data.get('graphCompletedMonotonic'))
                 and data['graphStartedMonotonic']<=data['graphCompletedMonotonic']<=event['monotonicSeconds'],
                 'discovery raw source clock/identity')
            discovered.setdefault(key, dict(data, eventSeq=event['seq']))
        elif name in ('ABSENCE','DISCOVER_ABSENCE'):
            key = identity_key(data['identity'])
            need(_hex(data['sampleId'],32) and data['phase'] in ('before','after')
                 and _hex(data['nativeStdoutSha256']), 'absence witness missing')
            need(_number(data.get('graphStartedMonotonic')) and _number(data.get('graphCompletedMonotonic'))
                 and data['graphStartedMonotonic']<=data['graphCompletedMonotonic']<=event['monotonicSeconds'],
                 'absence graph clock/writer order')
            found = [leases[identity_index[key]]] if key in identity_index else []
            need(name=='ABSENCE' or not found,'discovered absence cannot close a managed lease')
            need(name=='ABSENCE' or key in discovered,'unknown discovered identity absence')
            for lease in found:
                need(lease['role'] == 'finite' and lease['waitSeq'] is not None,
                     'absence does not replace controller/finite wait')
                need(_number(data.get('graphStartedMonotonic'))
                     and data['graphStartedMonotonic'] >= lease['reapedMonotonic'],
                     'absence frame predates actual wait')
                lease['absence'] = dict(data, eventSeq=event['seq'],witnessKind='COMPLETE_NATIVE_ABSENCE')
                lease['absenceWitnessKind']='COMPLETE_NATIVE_ABSENCE'
            if key in discovered:
                discovered[key]['absence'] = dict(data,eventSeq=event['seq'],witnessKind='COMPLETE_NATIVE_ABSENCE')
                discovered[key]['exitStatus']='UNKNOWN'
        elif name == 'SCOPE_OPEN':
            need(_hex(data['scopeId'],32) and data['scopeId'] not in scopes
                 and data['controllerIdentity'] == event['writer'], 'invalid scope open')
            identity_key(data['controllerIdentity'])
            if data.get('parentLeaseId') is not None:
                need(leases[data['parentLeaseId']]['identity'] == event['writer'], 'scope parent lease mismatch')
            else:
                owner_id=identity_index.get(identity_key(event['writer']))
                need(owner_id is not None and leases[owner_id]['role']=='controller', 'scope has no controller lease')
            scopes[data['scopeId']] = dict(data, openSeq=event['seq'], closeSeq=None)
        elif name == 'SCOPE_CLOSE':
            scope = scopes[data['scopeId']]
            need(scope['controllerIdentity'] == event['writer'] and scope['closeSeq'] is None, 'invalid scope close')
            scope['closeSeq'] = event['seq']
        elif name == 'LAUNCH_REFUSED':
            owner_id=identity_index.get(identity_key(event['writer']))
            need(owner_id is not None and leases[owner_id]['exitCode'] is None,'unowned refused-launch writer')
            need(_hex(data.get('attemptId'),32) and type(data.get('stageId')) is str and data['stageId']
                 and not any(v['attemptId']==data['attemptId'] for v in refusals),'refused attempt identity')
            for field in ('commandSha256','executableSha256'):
                need(data.get(field) is None or _hex(data[field]),'refused attempt command witness')
            pid=data.get('spawnedPid')
            need(pid is None or (type(pid) is int and pid>1),'refused spawned PID')
            need(type(data.get('readyBytes')) is int and 0<=data['readyBytes']<=4097
                 and _hex(data.get('readySha256')) and type(data.get('errorClass')) is str
                 and data['errorClass'] and type(data.get('cleanupKnown')) is bool,'refused ready/error witness')
            reads=data.get('identityReads')
            need(type(reads) is list and len(reads)<=2,'refused identity read population')
            for item in reads:
                identity_key(item);need(item['pid']==pid and item['parentPid']==event['writer']['pid'],
                                        'refused kernel identity does not bind spawned child')
            need(data.get('identityStatus') in ('UNKNOWN','BOUND'),'refused identity status')
            if data['identityStatus']=='BOUND':need(len(reads)==2 and reads[0]==reads[1],'refused bound identity not proven')
            registered=data.get('registeredLeaseId')
            need(registered is None or (registered==data['attemptId'] and registered in leases
                 and leases[registered]['role']=='finite' and leases[registered]['identity']['pid']==pid
                 and leases[registered]['parentIdentity']==event['writer']),'refused registration link')
            if data.get('actualExitCode') is not None:
                need(type(data['actualExitCode']) is int and data['cleanupKnown'] is True
                     and data.get('waitSource')=='Popen.wait' and pid is not None,'refused actual wait witness')
            else:need(data.get('waitSource') is None,'refused wait status unknown')
            need(_number(data.get('startedMonotonic')) and _number(data.get('cleanupCompletedMonotonic'))
                 and data['startedMonotonic']<=data['cleanupCompletedMonotonic']<=event['monotonicSeconds'],
                 'refused launch/cleanup clocks')
            refusals.append(dict(data,eventSeq=event['seq'],writer=event['writer']))
        else:
            raise ValueError('unknown lifecycle event')
        events.append(event); previous=event['sha256']; prior_mono=event['monotonicSeconds']
    return dict(events=events,leases=leases,discovered=discovered,scopes=scopes,identityIndex=identity_index,launchRefusals=refusals,
                runId=context[0] if context else None,sourceCommit=context[1] if context else None,
                policySha256=context[2] if context else None,lastSequence=len(events),
                bytes=len(raw),sha256=digest(raw))


def read_journal(path, limitBytes=None):
    fd = _open_owned(path, os.O_RDONLY)
    started=time.monotonic()
    try:
        while True:
            try:fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB);break
            except BlockingIOError:
                need(time.monotonic()-started<MAX_LOCK_WAIT,'journal read lock timeout');time.sleep(.002)
        with os.fdopen(os.dup(fd),'rb') as stream:
            raw=stream.read(MAX_JOURNAL_BYTES+1 if limitBytes is None else limitBytes)
    finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
    need(len(raw) <= MAX_JOURNAL_BYTES and (limitBytes is None or len(raw)==limitBytes), 'journal missing/capped prefix')
    return raw


def _validate_view_cold(view, journal_bytes=None):
    need(type(view) is dict and view.get('schema') == VIEW_SCHEMA, 'lifecycle view schema')
    count = view['journalBytes']
    need(type(count) is int and 0 < count <= MAX_JOURNAL_BYTES, 'journal prefix size')
    if journal_bytes is None:
        raw = read_journal(view['journalPath'],count)
    elif isinstance(journal_bytes,(str,Path)):
        raw = read_journal(journal_bytes,count)
    else:
        need(type(journal_bytes) is bytes and len(journal_bytes)>=count, 'journal replay bytes missing')
        raw = journal_bytes[:count]
    state = replay_journal(raw)
    need(state['sha256'] == view['journalSha256'] and state['lastSequence'] == view['lastSequence']
         and state['runId'] == view['runId'], 'journal view prefix differs')
    scope = state['scopes'][view['scopeId']]
    need(view['controllerIdentity'] == scope['controllerIdentity'], 'view scope controller differs')
    wanted={tuple(v) for v in view['referencedIdentities']}
    need(len(wanted)==len(view['referencedIdentities']),'duplicate referenced identity')
    expected=[v for v in state['leases'].values() if v['absence'] is None or identity_key(v['identity']) in wanted]
    need(view['leases']==expected and view['controllers']==[v['leaseId'] for v in expected
         if v['identity']==view['controllerIdentity']],'lifecycle lease view projection differs')
    state['launchRefusalArtifacts']=view.get('launchRefusalArtifacts',[])
    need(type(state['launchRefusalArtifacts']) is list,'refused-launch artifact population')
    return state


class ViewCursor:
    """Incremental journal replay, retaining exact reads/comparisons.

    This caches journal state, never an observation verdict. Only the newest
    full prefix/state is retained. Older prefixes from another scope replay
    cold after exact comparison; a scope's own prefix may never regress.
    Returned states are deep detached snapshots, including historical events.
    """
    def __init__(self):
        self._mutex = threading.RLock()
        self._raw = b''
        self._state = None
        self._hasher = hashlib.sha256()
        self._origin = None
        self._context = None
        self._frontiers = {}
        self._poison_reason = None
        self._work = dict(calls=0, parsedEvents=0, parsedBytes=0,
                          fullPrefixReadBytes=0, fullPrefixComparedBytes=0,
                          hashUpdatedBytes=0, coldOldPrefixReplays=0,
                          snapshotCopies=0, failures=0)

    @property
    def poisoned(self):
        with self._mutex:
            return self._poison_reason is not None

    def statistics(self):
        """Typed diagnostics only; never an acceptance or timing shortcut."""
        with self._mutex:
            return dict(self._work, latestPrefixBytes=len(self._raw),
                        frontierScopes=len(self._frontiers),
                        poisoned=self._poison_reason is not None)

    def _usable(self):
        need(self._poison_reason is None,
             'lifecycle view cursor permanently poisoned: ' + str(self._poison_reason))

    def validate_view(self, view, journal_bytes=None):
        with self._mutex:
            self._work['calls'] += 1
            try:
                self._usable()
                need(type(view) is dict and view.get('schema') == VIEW_SCHEMA, 'lifecycle view schema')
                count = view['journalBytes']
                need(type(count) is int and 0 < count <= MAX_JOURNAL_BYTES, 'journal prefix size')
                source = view['journalPath'] if journal_bytes is None else journal_bytes
                if isinstance(source, (str, Path)):
                    raw = read_journal(source, count)
                    item = os.stat(source, follow_symlinks=False)
                    origin = ('file', str(Path(source)), item.st_dev, item.st_ino)
                else:
                    need(type(source) is bytes and len(source) >= count, 'journal replay bytes missing')
                    raw = source[:count]
                    logical = view['journalPath']
                    need(type(logical) is str and Path(logical).is_absolute(), 'absolute logical journal path required')
                    # Bytes supplied by an archive need not exist at their
                    # original path; the logical session still cannot switch.
                    origin = ('bytes', logical)
                self._work['fullPrefixReadBytes'] += len(raw)
                need(self._origin is None or self._origin == origin, 'lifecycle cursor journal replaced')
                scope_id = view['scopeId']
                need(_hex(scope_id, 32), 'lifecycle view scope identity')
                previous = self._frontiers.get(scope_id)
                need(previous is None or count >= previous['bytes'], 'lifecycle scope prefix regressed')
                compared = min(len(self._raw), count)
                self._work['fullPrefixComparedBytes'] += compared
                need(raw[:compared] == self._raw[:compared], 'lifecycle cursor historical prefix changed')
                latest = count >= len(self._raw)
                if latest:
                    tail = raw[len(self._raw):]
                    candidate_hash = self._hasher.copy()
                    candidate_hash.update(tail)
                    before = self._state['lastSequence'] if self._state is not None else 0
                    if self._state is None:
                        state = replay_journal(raw)
                    elif tail:
                        state = replay_journal(tail, self._state)
                    else:
                        state = self._state
                    self._work['parsedEvents'] += state['lastSequence'] - before
                    self._work['parsedBytes'] += len(tail)
                    self._work['hashUpdatedBytes'] += len(tail)
                    state.update(bytes=count, sha256=candidate_hash.hexdigest())
                else:
                    # A legal older prefix from a different/interleaved scope
                    # must never borrow newer WAIT/close data from latest state.
                    state = replay_journal(raw)
                    self._work['coldOldPrefixReplays'] += 1
                    self._work['parsedEvents'] += state['lastSequence']
                    self._work['parsedBytes'] += len(raw)
                    self._work['hashUpdatedBytes'] += len(raw)
                context = (state['runId'], state['sourceCommit'], state['policySha256'])
                need(self._context is None or self._context == context, 'lifecycle cursor context changed')
                need(state['sha256'] == view['journalSha256'] and state['lastSequence'] == view['lastSequence']
                     and state['runId'] == view['runId'], 'journal view prefix differs')
                scope = state['scopes'][scope_id]
                need(view['controllerIdentity'] == scope['controllerIdentity'], 'view scope controller differs')
                wanted = {tuple(value) for value in view['referencedIdentities']}
                need(len(wanted) == len(view['referencedIdentities']), 'duplicate referenced identity')
                expected = [value for value in state['leases'].values()
                            if value['absence'] is None or identity_key(value['identity']) in wanted]
                need(view['leases'] == expected and view['controllers'] == [value['leaseId'] for value in expected
                     if value['identity'] == view['controllerIdentity']], 'lifecycle lease view projection differs')
                artifacts = view.get('launchRefusalArtifacts', [])
                need(type(artifacts) is list, 'refused-launch artifact population')
                state['launchRefusalArtifacts'] = copy.deepcopy(artifacts)
                snapshot = copy.deepcopy(state)
                # Commit cache metadata only after the entire view and snapshot
                # succeed. A partially mutated replay is unusable on any error.
                if latest:
                    self._raw, self._state, self._hasher = raw, state, candidate_hash
                self._origin, self._context = origin, context
                self._frontiers[scope_id] = dict(bytes=count, sha256=state['sha256'],
                                                lastSequence=state['lastSequence'])
                # Each frontier names an actual SCOPE_OPEN in the <=16MiB
                # validated journal, so no unbounded synthetic frontier store.
                need(len(self._frontiers) <= len(self._state['scopes']), 'cursor scope frontier bound')
                self._work['snapshotCopies'] += 1
                return snapshot
            except BaseException as error:
                self._work['failures'] += 1
                if self._poison_reason is None:
                    self._poison_reason = type(error).__name__ + ': ' + str(error)
                raise


def validate_view(view, journal_bytes=None, *, cursor=None):
    if cursor is None:
        return _validate_view_cold(view, journal_bytes)
    need(type(cursor) is ViewCursor, 'actual lifecycle ViewCursor required')
    return cursor.validate_view(view, journal_bytes)


class ManagedProcess:
    def __init__(self, registry, process, lease_id):
        self.registry,self.process,self.lease_id = registry,process,lease_id
        self._done = threading.Event();self._error=None
        self._reaper = threading.Thread(target=self._reap,name='aijade-finite-reaper',daemon=True)
        self._reaper.start()

    def _reap(self):
        try:
            code=self.process.wait()
            self.registry._append('WAIT',dict(leaseId=self.lease_id,identity=self.registry._lease(self.lease_id)['identity'],
                exitCode=code,waitSource='Popen.wait',reapedMonotonic=time.monotonic()))
        except BaseException as error:self._error=error
        finally:self._done.set()

    @property
    def pid(self):return self.process.pid
    @property
    def returncode(self):return self.process.returncode
    @property
    def stdout(self):return self.process.stdout
    @property
    def stderr(self):return self.process.stderr
    @property
    def stdin(self):return self.process.stdin
    def poll(self):
        if self._done.is_set():
            if self._error:raise ValueError('finite wait evidence unknown') from self._error
            return self.process.returncode
        # Kernel liveness and metadata completion are separate. Never report an
        # already reaped PID as alive and invite a cleanup signal to a reused PID.
        return self.process.poll()
    def wait(self,timeout=None):
        if not self._done.wait(timeout):raise subprocess.TimeoutExpired(self.process.args,timeout)
        if self._error:raise ValueError('finite wait evidence unknown') from self._error
        return self.process.returncode
    def communicate(self,input=None,timeout=None):
        out,err=self.process.communicate(input=input,timeout=timeout)
        self.wait(timeout=timeout)
        return out,err
    def send_signal(self,value):return self.process.send_signal(value)
    def terminate(self):return self.process.terminate()
    def kill(self):return self.process.kill()


class Registry:
    def __init__(self,journal_path,roots=(),*,stage='runtime',source_commit,policy_sha256,
                 run_id=None,capture_lock_path=None,parent_lease_id=None):
        self.path=project_path(journal_path);self.stage=stage;self.writer=identity()
        self.source_commit=source_commit;self.policy_sha256=policy_sha256
        need(_hex(source_commit,40) and _hex(policy_sha256),'registry source identity missing')
        self.run_id=run_id or uuid.uuid4().hex
        self.lock_path=project_path(capture_lock_path or (POSIX/'locks'/('lifecycle-'+digest(str(self.path).encode())+'.lock')))
        self._mutex=threading.RLock();self.handles=[];self.scope_id=uuid.uuid4().hex;self.closed=False
        self._cached_raw=b'';self._cached_state=None;self._cached_inode=None;self._policy=None
        self._cached_hasher=hashlib.sha256();self._cache_poison_reason=None
        self.refused_processes=[];self.refused_process_records=[];self.launch_refusal_records=[]
        fd=_open_owned(self.path,os.O_RDWR|os.O_CREAT);os.close(fd)
        state=self._state()
        if state['events']:
            need((state['runId'],state['sourceCommit'],state['policySha256'])==
                 (self.run_id,source_commit,policy_sha256),'registry attach context differs')
        self._roots=[]
        for pid,created in roots:
            need(pid==self.writer['pid'] and round(created*1000000)==self.writer['createTimeMicros'], 'only exact local self may be persistent')
            self._roots.append((pid,created))
        existing=[(k,v) for k,v in state['leases'].items() if v['identity']==self.writer]
        if not existing:
            need(not state['events'] and parent_lease_id is None,'unregistered nested controller')
            root_id=uuid.uuid4().hex
            self._append('CONTROLLER_REGISTER',dict(leaseId=root_id,role='controller',stageId=stage,identity=self.writer,
                parentIdentity=None,commandSha256=digest(canonical(sys.argv)),executableSha256=digest(Path(sys.executable).resolve().read_bytes()),
                readyMonotonic=time.monotonic()))
            self.parent_lease_id=None
        else:
            need(parent_lease_id in [k for k,_ in existing], 'nested scope parent lease missing')
            self.parent_lease_id=parent_lease_id
        self._append('SCOPE_OPEN',dict(scopeId=self.scope_id,controllerIdentity=self.writer,parentLeaseId=self.parent_lease_id,stageId=stage))

    @property
    def cache_poisoned(self):
        return self._cache_poison_reason is not None

    def _require_cache_usable(self):
        need(self._cache_poison_reason is None,
             'lifecycle producer cache permanently poisoned: '+str(self._cache_poison_reason))

    def _poison_cache(self,error):
        if self._cache_poison_reason is None:
            self._cache_poison_reason=type(error).__name__+': '+str(error)

    def _sync(self,raw,inode=None):
        try:
            self._require_cache_usable()
            if inode is not None:
                need(self._cached_inode is None or self._cached_inode==inode,'lifecycle journal replaced')
            need(type(raw) is bytes and len(raw)>=len(self._cached_raw)
                 and raw[:len(self._cached_raw)]==self._cached_raw,
                 'lifecycle journal truncated, rewound or prefix changed')
            tail=raw[len(self._cached_raw):]
            hasher=hashlib.sha256() if self._cached_state is None else self._cached_hasher.copy()
            hasher.update(tail)
            if self._cached_state is None:state=replay_journal(raw)
            elif tail:state=replay_journal(tail,self._cached_state)
            else:state=self._cached_state
            state.update(bytes=len(raw),sha256=hasher.hexdigest())
            self._cached_raw,self._cached_state,self._cached_hasher=raw,state,hasher
            if inode is not None:self._cached_inode=inode
            return self._cached_state
        except BaseException as error:
            self._poison_cache(error);raise
    def _state(self):
        with self._mutex:
            try:
                self._require_cache_usable()
                raw=read_journal(self.path);item=os.stat(self.path,follow_symlinks=False)
                return self._sync(raw,(item.st_dev,item.st_ino))
            except BaseException as error:
                self._poison_cache(error);raise
    def _lease(self,lease_id):return self._state()['leases'][lease_id]

    def _append(self,name,data):
        with self._mutex:
            fd=None;locked=False
            try:
                self._require_cache_usable()
                fd=_open_owned(self.path,os.O_RDWR)
                started=time.monotonic()
                while True:
                    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);locked=True;break
                    except BlockingIOError:
                        need(time.monotonic()-started<MAX_LOCK_WAIT,'journal lock timeout');time.sleep(.002)
                with os.fdopen(os.dup(fd),'rb') as stream:raw=stream.read(MAX_JOURNAL_BYTES+1)
                item=os.fstat(fd);state=self._sync(raw,(item.st_dev,item.st_ino))
                event=dict(schema=EVENT_SCHEMA,seq=state['lastSequence']+1,event=name,monotonicSeconds=time.monotonic(),
                    runId=self.run_id,writer=self.writer,sourceCommit=self.source_commit,policySha256=self.policy_sha256,
                    data=data,previousSha256=state['events'][-1]['sha256'] if state['events'] else ZERO)
                event['sha256']=digest(canonical(event));new=canonical(event)+b'\n'
                need(len(raw)+len(new)<=MAX_JOURNAL_BYTES,'journal cap exceeded')
                state=replay_journal(new,state);self._cached_state=state
                hasher=self._cached_hasher.copy();hasher.update(new)
                os.lseek(fd,0,os.SEEK_END);need(os.write(fd,new)==len(new),'partial lifecycle append');os.fsync(fd)
                self._cached_raw=raw+new;self._cached_hasher=hasher
                state.update(bytes=len(raw)+len(new),sha256=hasher.hexdigest())
                return event
            except BaseException as error:
                self._poison_cache(error);raise
            finally:
                if fd is not None:
                    try:
                        try:
                            if locked:fcntl.flock(fd,fcntl.LOCK_UN)
                        finally:os.close(fd)
                    except BaseException as error:
                        self._poison_cache(error);raise

    def environment(self):
        return dict(AIJADE_LIFECYCLE_JOURNAL=str(self.path),AIJADE_LIFECYCLE_SOURCE_COMMIT=self.source_commit,
            AIJADE_LIFECYCLE_POLICY_SHA256=self.policy_sha256,AIJADE_LIFECYCLE_RUN_ID=self.run_id,
            AIJADE_LIFECYCLE_CAPTURE_LOCK=str(self.lock_path),AIJADE_LIFECYCLE_STAGE=self.stage,
            AIJADE_LIFECYCLE_PARENT_LEASE=self.parent_lease_id or '')

    def activate(self):
        global _env_registry
        need(self.writer==identity(),'cannot activate another process registry')
        with _env_registry_lock:
            _env_registry=self;os.environ.update(self.environment())
        return self

    def bind_policy(self,policy):
        need(str(coordination_lock_path(policy))==str(self.lock_path),'registry policy capture lock mismatch')
        self._policy=copy.deepcopy(policy)
        return self

    def roots(self):
        need(not self.closed,'local persistent scope closed')
        return list(self._roots)

    def register(self,process,**unused):
        need(isinstance(process,ManagedProcess) and process.registry is self,'only an identity-ready owned handle may register')
        return self._lease(process.lease_id)

    def launch(self,command,*,role='finite',stage=None,ready_timeout=None,**kwargs):
        attempt_id=uuid.uuid4().hex;started=time.monotonic()
        process=None;registered=False;released=False;launched=False;raw=bytearray();reads=[];owns_group=False
        ready_r=ready_w=gate_r=gate_w=-1;executable_sha=None;command_sha=None
        contexts=ExitStack()
        try:
            self._require_cache_usable()
            need(not self.closed,'cannot launch after local persistent scope closes')
            need(role in ('finite','controller') and type(command) in (list,tuple) and command
                 and all(type(x) is str and '\x00' not in x for x in command),'finite command schema')
            command_sha=digest(canonical(list(command)))
            need(not kwargs.get('shell') and not kwargs.get('preexec_fn') and not kwargs.get('pass_fds'), 'unsupported subprocess escape')
            need(type(kwargs.get('start_new_session',False)) is bool,'start_new_session must be explicit boolean')
            owns_group=kwargs.get('start_new_session',False)
            ready_budget=READY_SECONDS if ready_timeout is None else ready_timeout
            need(_number(ready_budget) and 0<ready_budget<=READY_SECONDS,'identity-ready deadline invalid')
            env=dict(os.environ if kwargs.get('env') is None else kwargs.pop('env'))
            env.update(self.environment());env['AIJADE_LIFECYCLE_STAGE']=stage or self.stage
            executable=shutil.which(command[0],path=env.get('PATH')) if not Path(command[0]).is_absolute() else command[0]
            need(executable is not None,'finite executable missing')
            # Preserve virtualenv argv0; hash its actual executable target.
            executable=Path(executable).absolute();executable_sha=digest(executable.resolve(strict=True).read_bytes())
            env['AIJADE_LIFECYCLE_PARENT_LEASE']=attempt_id
            shim=Path(__file__).with_name('lifecycle_exec.py')
            contexts.enter_context(capture_lock(self.lock_path))
            ready_r,ready_w=os.pipe();gate_r,gate_w=os.pipe()
            process=subprocess.Popen([sys.executable,'-S','-B',str(shim),str(ready_w),str(gate_r),'--',str(executable),*command[1:]],
                env=env,pass_fds=(ready_w,gate_r),**kwargs)
            os.close(ready_w);ready_w=-1;os.close(gate_r);gate_r=-1
            selected=selectors.DefaultSelector();selected.register(ready_r,selectors.EVENT_READ)
            deadline=time.monotonic()+ready_budget
            try:
                while b'\n' not in raw:
                    remaining=deadline-time.monotonic();need(remaining>0,'identity-ready timeout')
                    need(selected.select(remaining),'identity-ready timeout')
                    block=os.read(ready_r,4097-len(raw));need(block,'identity-ready EOF')
                    raw.extend(block);need(len(raw)<=4096,'identity-ready cap')
            finally:selected.close()
            ready=json.loads(bytes(raw),object_pairs_hook=_unique)
            need(set(ready)=={'pid','parentPid','readyMonotonic'} and type(ready['pid']) is int
                 and ready['pid']==process.pid and ready['parentPid']==self.writer['pid']
                 and _number(ready['readyMonotonic']),'identity-ready report mismatch')
            # The exact Popen child stays behind its gate for both kernel reads.
            first=identity(process.pid);identity_key(first);reads.append(first)
            second=identity(process.pid);identity_key(second);reads.append(second)
            need(first['parentPid']==self.writer['pid'] and second==first
                 and time.monotonic()<=deadline,'identity-ready kernel identity/deadline mismatch')
            self._append('FINITE_REGISTER',dict(leaseId=attempt_id,role='finite',stageId=stage or self.stage,
                identity=first,parentIdentity=self.writer,commandSha256=command_sha,executableSha256=executable_sha,
                readyMonotonic=ready['readyMonotonic'],shimSha256=digest(shim.read_bytes()),
                identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD'))
            registered=True
            self._append('RELEASE',dict(leaseId=attempt_id));released=True
            os.write(gate_w,b'1')
            handle=ManagedProcess(self,process,attempt_id);self.handles.append(handle);launched=True;return handle
        except BaseException as error:
            exit_code=None;cleanup_known=process is None
            if process is not None:
                self.refused_processes.append(process)
                self.refused_process_records.append(dict(handle=process,attemptId=attempt_id,ownsProcessGroup=owns_group))
                try:
                    if process.poll() is None:process.kill()
                    exit_code=process.wait(timeout=.5);cleanup_known=True
                except BaseException:cleanup_known=False
            data=dict(attemptId=attempt_id,stageId=stage if type(stage) is str and stage else self.stage,
                commandSha256=command_sha,executableSha256=executable_sha,
                spawnedPid=process.pid if process is not None else None,readyBytes=len(raw),readySha256=digest(bytes(raw)),
                ownsProcessGroup=owns_group,
                identityReads=reads,identityStatus='BOUND' if len(reads)==2 and reads[0]==reads[1] else 'UNKNOWN',
                registeredLeaseId=attempt_id if registered else None,errorClass=type(error).__name__,
                actualExitCode=exit_code,cleanupKnown=cleanup_known,waitSource='Popen.wait' if exit_code is not None else None,
                startedMonotonic=started,cleanupCompletedMonotonic=time.monotonic())
            self.launch_refusal_records.append(dict(data,writer=self.writer))
            try:
                if registered and released and exit_code is not None:
                    lease=self._lease(attempt_id)
                    if lease['waitSeq'] is None:
                        self._append('WAIT',dict(leaseId=attempt_id,identity=lease['identity'],exitCode=exit_code,
                            waitSource='Popen.wait',reapedMonotonic=data['cleanupCompletedMonotonic']))
                self._append('LAUNCH_REFUSED',data)
            except BaseException as journal_error:
                artifact=self.path.with_name('launch-refused-'+attempt_id+'.json')
                document=dict(schema='aijade.process-lifecycle-launch-refusal.v1',runId=self.run_id,writer=self.writer,
                    sourceCommit=self.source_commit,policySha256=self.policy_sha256,data=data,
                    journalAppendErrorClass=type(journal_error).__name__,qualificationAdverse=True)
                try:
                    fd=_open_owned(artifact,os.O_WRONLY|os.O_CREAT|os.O_EXCL)
                    try:os.write(fd,canonical(document)+b'\n');os.fsync(fd)
                    finally:os.close(fd)
                    error.lifecycleRefusalPath=str(artifact)
                except BaseException:pass
            try:error.lifecycleRefusal=data
            except BaseException:pass
            raise
        finally:
            if process is not None and not launched:
                for stream in (process.stdin,process.stdout,process.stderr):
                    if stream is not None:stream.close()
            for fd in (ready_r,ready_w,gate_r,gate_w):
                if fd>=0:os.close(fd)
            contexts.close()

    def run(self,command,*,input=None,capture_output=False,timeout=None,check=False,**kwargs):
        if input is not None:need('stdin' not in kwargs,'stdin/input conflict');kwargs['stdin']=subprocess.PIPE
        if capture_output:
            need('stdout' not in kwargs and 'stderr' not in kwargs,'capture_output conflict')
            kwargs.update(stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        process=self.launch(command,**kwargs)
        try:out,err=process.communicate(input=input,timeout=timeout)
        except BaseException:
            if process.poll() is None:process.kill()
            process.wait(timeout=1)
            raise
        result=subprocess.CompletedProcess(command,process.returncode,out,err)
        if check:result.check_returncode()
        return result

    def wait(self,process,timeout=None):return process.wait(timeout)

    def cleanup_refused(self,grace_seconds=5.0,wait_seconds=1.0):
        """Bounded owned-handle cleanup, never reconstruct a handle from a PID.

        A known kernel reap is direct-child absence only. Group/descendant
        absence still belongs to the observed ownership ledger, and every
        refused launch remains adverse even after successful cleanup.
        """
        need(_number(grace_seconds) and 0<=grace_seconds<=5
             and _number(wait_seconds) and 0<=wait_seconds<=1,'refused cleanup budget')
        with self._mutex:items=list(self.refused_process_records)
        started=time.monotonic();deadline=started+grace_seconds;final_deadline=deadline+wait_seconds
        records=[]
        def send(item,row,sig):
            process=item['handle']
            if process.poll() is not None:return
            if item['ownsProcessGroup']:
                need(os.getpgid(process.pid)==process.pid and os.getsid(process.pid)==process.pid,
                     'refused child is not the owned live session/group leader')
                os.killpg(process.pid,sig)
            else:process.send_signal(sig)
            row['termSent' if sig==signal.SIGTERM else 'killSent']=True
        for item in items:
            process=item['handle'];row=dict(attemptId=item['attemptId'],pid=process.pid,
                ownsProcessGroup=item['ownsProcessGroup'],termSent=False,killSent=False,
                actualExitCode=process.poll(),cleanupKnown=False,errors=[],startedMonotonic=started,
                groupMembersAbsentNotInferred=True)
            try:send(item,row,signal.SIGTERM)
            except (OSError,ValueError) as error:row['errors'].append(type(error).__name__+': '+str(error))
            records.append(row)
        while any(item['handle'].poll() is None for item in items) and time.monotonic()<deadline:
            time.sleep(min(.01,max(0,deadline-time.monotonic())))
        for item,row in zip(items,records):
            process=item['handle']
            try:
                send(item,row,signal.SIGKILL)
                row['actualExitCode']=process.wait(timeout=max(0,final_deadline-time.monotonic()))
                row['cleanupKnown']=True
            except (OSError,ValueError,subprocess.SubprocessError) as error:
                row['errors'].append(type(error).__name__+': '+str(error))
            row.update(waitSource='Popen.wait' if row['cleanupKnown'] else None,
                       finishedMonotonic=time.monotonic(),qualificationAdverse=True)
        return records

    def _refusal_artifacts(self):
        rows=[]
        for path in sorted(self.path.parent.glob('launch-refused-*.json')):
            fd=_open_owned(path,os.O_RDONLY)
            with os.fdopen(fd,'rb') as stream:raw=stream.read(65537)
            need(len(raw)<=65536,'refused-launch artifact cap')
            item=json.loads(raw,object_pairs_hook=_unique)
            need(item.get('runId')==self.run_id and item.get('sourceCommit')==self.source_commit
                 and item.get('policySha256')==self.policy_sha256,'refused-launch artifact context mismatch')
            rows.append(dict(path=str(path),sha256=digest(raw)))
        return rows

    def sample(self,identities=()):
        with self._mutex:
            state=self._state();wanted=set(identities)
            leases=copy.deepcopy([v for v in state['leases'].values() if v['absence'] is None or identity_key(v['identity']) in wanted])
            return dict(schema=VIEW_SCHEMA,runId=self.run_id,journalPath=str(self.path),journalBytes=len(self._cached_raw),
                journalSha256=state['sha256'],lastSequence=state['lastSequence'],scopeId=self.scope_id,
                controllerIdentity=self.writer,leases=leases,referencedIdentities=[list(v) for v in sorted(wanted)],
                launchRefusalArtifacts=self._refusal_artifacts(),
                controllers=[v['leaseId'] for v in leases if v['identity']==self.writer])

    @_synchronized
    def remember(self,observation):
        """Retain discovery and complete native-graph absence; never invent waits."""
        need(self._policy is not None,'native policy must be bound before remembering frames')
        import mac_process_guard_v3 as guard
        state=self._state();known={identity_key(v['identity']):v for v in state['leases'].values()}
        roots=guard._normalize_roots(observation['ownedRoots'])
        need(not roots or (len(roots)==1 and roots[0]['pid']==self.writer['pid']
             and round(roots[0]['createTime']*1000000)==self.writer['createTimeMicros']),
             'observation local persistent root differs from exact self')
        graphs=[]
        for phase in ('before','after'):
            frame=observation.get('evidence',{}).get(phase,{})
            graph=frame.get('processGraph',{})
            if graph.get('errors') or not graph.get('nativeCensus',{}).get('stdoutSha256'):continue
            try:
                parsed,collector=guard.parse_native_evidence(self._policy,graph['nativeCensus'])
                if parsed!=graph.get('nodes'):continue
            except Exception:continue
            nodes=graph.get('nodes');need(type(nodes) is list,'missing complete process nodes')
            present={key_from_node(v):v for v in nodes};graphs.append((phase,graph,present))
            members=guard._owned_ids(parsed,roots);by_pid={v['pid']:v for v in parsed}
            for row in parsed:
                if row['pid'] not in members:continue
                if row['pid']==collector['pid'] and key_from_node(row)==(collector['pid'],collector['createTimeMicros']):continue
                ident=dict(pid=row['pid'],createTimeMicros=row['createTimeMicros'],parentPid=row['parentPid'])
                key=identity_key(ident)
                if key not in known and key not in state['discovered']:
                    ancestry=[];cursor=row;seen=set()
                    while True:
                        current=dict(pid=cursor['pid'],createTimeMicros=cursor['createTimeMicros'],parentPid=cursor['parentPid'])
                        need(identity_key(current) not in seen,'discovery ancestry cycle')
                        seen.add(identity_key(current));ancestry.append(current)
                        if identity_key(current)==identity_key(self.writer):break
                        need(cursor['parentPid'] in by_pid,'discovery root ancestry incomplete')
                        cursor=by_pid[cursor['parentPid']]
                    self._append('DISCOVER',dict(identity=ident,sampleId=observation['sampleId'],phase=phase,
                        scopeId=self.scope_id,ancestry=ancestry,
                        nativeStdoutSha256=graph['nativeCensus']['stdoutSha256'],
                        graphStartedMonotonic=frame['graphStartedMonotonic'],
                        graphCompletedMonotonic=frame['graphCompletedMonotonic']))
        # The observer validates native evidence before calling remember. The
        # independent audit additionally binds each ABSENCE to that saved frame.
        for lease in state['leases'].values():
            if lease['role']!='finite' or lease['waitSeq'] is None or lease['absence'] is not None:continue
            key=identity_key(lease['identity'])
            for phase,graph,present in reversed(graphs):
                frame=observation['evidence'][phase]
                if key not in present and frame.get('graphStartedMonotonic',-1)>=lease['reapedMonotonic']:
                    self._append('ABSENCE',dict(identity=lease['identity'],sampleId=observation['sampleId'],phase=phase,
                        nativeStdoutSha256=graph['nativeCensus']['stdoutSha256'],
                        graphStartedMonotonic=frame['graphStartedMonotonic'],
                        graphCompletedMonotonic=frame['graphCompletedMonotonic']));break
        for key,value in list(state['discovered'].items()):
            if key in known or value.get('absence') is not None:continue
            for phase,graph,present in reversed(graphs):
                if key not in present:
                    frame=observation['evidence'][phase]
                    self._append('DISCOVER_ABSENCE',dict(identity=value['identity'],sampleId=observation['sampleId'],phase=phase,
                        nativeStdoutSha256=graph['nativeCensus']['stdoutSha256'],
                        graphStartedMonotonic=frame['graphStartedMonotonic'],
                        graphCompletedMonotonic=frame['graphCompletedMonotonic']));break

    @_synchronized
    def close(self):
        if not self.closed:self._append('SCOPE_CLOSE',dict(scopeId=self.scope_id));self.closed=True

    def final(self):
        for handle in self.handles:
            if handle.process.returncode is not None:handle.wait(timeout=MAX_LOCK_WAIT)
        state=self._state();mine={identity_key(self.writer)};changed=True
        while changed:
            before=len(mine)
            mine.update(identity_key(v['identity']) for v in state['leases'].values()
                        if v['parentIdentity'] is not None and identity_key(v['parentIdentity']) in mine)
            changed=len(mine)!=before
        finite=[v for v in state['leases'].values() if identity_key(v['identity']) in mine and v['role']=='finite'
                and v['identity']!=self.writer]
        unknown=[v for v in finite if v['waitSeq'] is None or v['absence'] is None or v['exitCode']!=0]
        all_managed={identity_key(v['identity']) for v in state['leases'].values()}
        local_discovered=[v for key,v in state['discovered'].items() if key not in all_managed and
                          (not v.get('ancestry') or any(identity_key(i) in mine for i in v['ancestry']))]
        unleased=[v for v in local_discovered if v.get('absence') is None]
        refusals=[v for v in state['launchRefusals'] if identity_key(v['writer']) in mine]
        if self.launch_refusal_records and not refusals:refusals=copy.deepcopy(self.launch_refusal_records)
        artifacts=self._refusal_artifacts()
        self.close()
        return dict(schema='aijade.process-lifecycle-final.v1',status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT'
                    if not unknown and not unleased and not refusals and not artifacts else 'UNKNOWN_OR_ADVERSE_OWNED_LIFECYCLE',
                    scopeId=self.scope_id,scopeClosed=True,knownFiniteLeases=finite,unresolvedFiniteLeases=unknown,
                    launchRefusals=refusals,
                    launchRefusalArtifacts=artifacts,
                    localDiscoveredIdentities=local_discovered,
                    unleasedDiscoveredIdentities=unleased,remainingIdentities=[v['identity'] for v in unknown],
                    lifecycleView=self.sample())


def from_environment():
    global _env_registry
    with _env_registry_lock:
        path=os.environ.get('AIJADE_LIFECYCLE_JOURNAL')
        if not path:return None
        if _env_registry is None or _env_registry.writer['pid']!=os.getpid():
            current=identity()
            _env_registry=Registry(path,[(current['pid'],current['createTimeMicros']/1000000)],
                stage=os.environ['AIJADE_LIFECYCLE_STAGE'],source_commit=os.environ['AIJADE_LIFECYCLE_SOURCE_COMMIT'],
                policy_sha256=os.environ['AIJADE_LIFECYCLE_POLICY_SHA256'],run_id=os.environ['AIJADE_LIFECYCLE_RUN_ID'],
                capture_lock_path=os.environ['AIJADE_LIFECYCLE_CAPTURE_LOCK'],
                parent_lease_id=os.environ['AIJADE_LIFECYCLE_PARENT_LEASE'])
        return _env_registry


def run(command,**kwargs):
    registry=from_environment();need(registry is not None,'lifecycle environment is required')
    return registry.run(command,**kwargs)
