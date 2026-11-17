"""Explicit full-state C-clone cursor candidate; no OS observation on import.

Only source-pinned JSON replay constructs the private state. Exact full-prefix
reads/comparisons and every new event validation remain. Marshal bytes are
created and consumed inside this module; no external marshal/pickle input is
accepted. Historical ViewCursor and its complete detached snapshot API stay.
"""
import copy
import hashlib
import marshal
import math
import os
from pathlib import Path
import time
import process_lifecycle as life

MODE='full-state-c-clone-exact-prefix-v1'
INITIALIZATION_MODE='paired-source-verified-journal-prefix-v1'
PARSER_SOURCE_SHA256='93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65'
need=life.need
_hex=life._hex
VIEW_SCHEMA=life.VIEW_SCHEMA
MAX_JOURNAL_BYTES=life.MAX_JOURNAL_BYTES
read_journal=life.read_journal
replay_journal=life.replay_journal
identity_key=life.identity_key


def assert_parser_source():
    need(hashlib.sha256(Path(life.__file__).read_bytes()).hexdigest()==PARSER_SOURCE_SHA256,
         'C-clone cursor requires its exact source-pinned original parser')


def builtin_only(value):
    """Seal exact supported types; reject code, subclasses, sets, cycles and NaN."""
    complete=set();active=set()
    def visit(item):
        kind=type(item)
        if kind in (type(None),bool,int,str):return
        if kind is float:
            need(math.isfinite(item),'nonfinite clone state');return
        need(kind in (dict,list,tuple),'unsupported clone state type')
        ident=id(item)
        need(ident not in active,'cyclic clone state')
        if ident in complete:return
        active.add(ident)
        if kind is dict:
            for key,val in item.items():visit(key);visit(val)
        else:
            for val in item:visit(val)
        active.remove(ident);complete.add(ident)
    visit(value)
    return len(complete)


def clone_builtin_checked(value):
    """For external small fields only; always validate before local roundtrip."""
    builtin_only(value)
    return marshal.loads(marshal.dumps(value,4))


def _detached_sealed_state(value):
    """Private state already sealed from the exact JSON parser and new tail.

    Old mutable values never escape: only a complete detached local C clone is
    returned. Existing private state is updated solely by the pinned parser;
    changed values originate in the newly checked event data, metadata scalars,
    or independently checked/copied external artifact fields.
    """
    return marshal.loads(marshal.dumps(value,4))


class FullStateCloneCursor(life.ViewCursor):
    def __init__(self):
        assert_parser_source()
        super().__init__()
        self._work.update(cCloneSnapshots=0,builtinColdStates=0,builtinTailEvents=0,
                          builtinContainersChecked=0,bootstrapReceivedStates=0)
        self._preparation=None

    def bind_preparation(self,record,write_clock):
        need(self._work['bootstrapReceivedStates']==1 and self._preparation is None,
             'prepared cursor must bind exactly one actual initialization artifact')
        need(type(write_clock) is dict and set(write_clock)=={'path','sha256','startedMonotonic','completedMonotonic'},
             'actual initialization writer envelope required')
        need(record['scopeId'] in self._frontiers and record['prefixBytes']==len(self._raw)
             and record['prefixSha256']==hashlib.sha256(self._raw).hexdigest()
             and record['lastSequence']==self._state['lastSequence'],'initialization cutoff/cache mismatch')
        self._preparation=clone_builtin_checked(dict(initialization=record,initializationWriteClock=write_clock))

    def preparation_metadata(self):
        need(self._preparation is not None,'actual initialization record is not bound')
        return clone_builtin_checked(self._preparation)

    def preparation_reference(self):
        need(self._preparation is not None,'actual initialization record is not bound')
        record=self._preparation['initialization'];writer=self._preparation['initializationWriteClock']
        return dict(path=writer['path'],sha256=writer['sha256'],mode=record['mode'],
            prefixBytes=record['prefixBytes'],prefixSha256=record['prefixSha256'],lastSequence=record['lastSequence'],
            scopeId=record['scopeId'],sourceCommit=record['sourceCommit'],policySha256=record['policySha256'],
            cursorSourceSha256=record['cursorSourceSha256'])

    def _seal_state_types(self,state,prior_sequence):
        if prior_sequence is None:
            checked=builtin_only(state)
            self._work['builtinColdStates']+=1
        else:
            tail=state['events'][prior_sequence:]
            checked=builtin_only(tail)
            self._work['builtinTailEvents']+=len(tail)
        self._work['builtinContainersChecked']+=checked

    def _clone_state(self,state):
        result=_detached_sealed_state(state)
        self._work['cCloneSnapshots']+=1
        return result

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
                state['launchRefusalArtifacts'] = clone_builtin_checked(artifacts)
                self._seal_state_types(state, None if self._state is None or not latest else before)
                snapshot = self._clone_state(state)
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



def bootstrap_pair(view,journal_bytes=None):
    """One journal-only canonical parse, two detached independent private caches.

    This is explicit component initialization, not a process/API sample or a
    granted verdict. Callers must include it in declared preparation/startup
    budgets. Every later cursor validates its own actual complete prefix and
    new tail. Shared immutable raw bytes are not shared mutable replay state.
    """
    started=time.monotonic()
    first=FullStateCloneCursor()
    second_state=first.validate_view(view,journal_bytes)
    canonical=first._state
    first._state=first._clone_state(canonical)
    second=FullStateCloneCursor()
    second._state=second_state
    second._raw=first._raw
    second._hasher=first._hasher.copy()
    second._origin=first._origin
    second._context=first._context
    second._frontiers=clone_builtin_checked(first._frontiers)
    first._work['bootstrapReceivedStates']=1
    second._work['bootstrapReceivedStates']=1
    need(first._state is not second._state and first._hasher is not second._hasher,
         'bootstrap replay/cache state alias')
    record=dict(schema='aijade.lifecycle.c-clone-bootstrap.v1',mode=INITIALIZATION_MODE,
        startedMonotonic=started,completedMonotonic=None,elapsedSeconds=None,
        cursorSourceSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        parserSourceSha256=PARSER_SOURCE_SHA256,canonicalParserRuns=1,detachedCacheCloneOperations=2,
        journalPath=view['journalPath'],sourceOrigin=list(first._origin),initialView=clone_builtin_checked(view),
        prefixBytes=len(first._raw),prefixSha256=hashlib.sha256(first._raw).hexdigest(),
        lastSequence=first._state['lastSequence'],runId=first._state['runId'],
        sourceCommit=first._state['sourceCommit'],policySha256=first._state['policySha256'],
        scopeId=view['scopeId'],controllerIdentity=clone_builtin_checked(view['controllerIdentity']),
        innerStatistics=first.statistics(),outerStatistics=second.statistics(),
        processObservationPerformed=False,nativeApiOrModelRequest=False,verdictGranted=False,
        independentMutableReplayStates=True)
    completed=time.monotonic()
    record.update(completedMonotonic=completed,elapsedSeconds=completed-started)
    return first,second,record
