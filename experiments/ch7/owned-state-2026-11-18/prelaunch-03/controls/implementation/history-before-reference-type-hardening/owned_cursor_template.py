"""Guard-owned canonical journal state; only detached decisions leave a cursor.

No process/API/native/model query occurs on import or during journal evaluation.
The legacy complete-return cursor and parser remain separate, source-pinned APIs.
"""
import ast
import hashlib
import importlib
import json
import marshal
import os
from pathlib import Path
import threading
import time
import uuid
import process_lifecycle as life
import full_state_clone_cursor as clone_support

MODE='owned-guard-state-exact-prefix-v1'
INITIALIZATION_MODE='paired-source-verified-owned-state-v1'
PARSER_SOURCE_SHA256='93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65'
LEGACY_CLONE_SOURCE_SHA256='0da9588655714d23db401b3424f45379689421898d85256b2506d674fee5e584'
GUARD_PREDICATE_AST_SHA256=__GUARD_PREDICATE_AST_SHA256__
need=life.need
_hex=life._hex
VIEW_SCHEMA=life.VIEW_SCHEMA
MAX_JOURNAL_BYTES=life.MAX_JOURNAL_BYTES
read_journal=life.read_journal
replay_journal=life.replay_journal
identity_key=life.identity_key
clone_builtin_checked=clone_support.clone_builtin_checked
builtin_only=clone_support.builtin_only


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _bind_guard():
    module=importlib.import_module('mac_process_guard_v3')
    expected=Path(__file__).with_name('mac_process_guard_v3.py')
    need(Path(module.__file__).resolve()==expected.resolve(),'exact colocated guard required')
    tree=ast.parse(expected.read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
              and n.name=='_guard_decision_from_validated_lifecycle')
    digest=hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
    predicate=getattr(module,node.name)
    need(digest==GUARD_PREDICATE_AST_SHA256 and predicate.__globals__ is module.__dict__
         and predicate.__closure__ is None,'fixed source-owned pure guard predicate required')
    return module,predicate,predicate.__code__,_file_sha(expected)


def _clone_private_state(value):
    """One initialization clone of already sealed local canonical state only."""
    return marshal.loads(marshal.dumps(value,4))


class OwnedGuardCursor:
    """No complete-state return API, arbitrary predicate argument or verdict cache."""
    def __init__(self,role):
        need(role in ('inner','outer'),'explicit independent guard-owner role required')
        need(_file_sha(life.__file__)==PARSER_SOURCE_SHA256,'exact original canonical parser required')
        need(_file_sha(clone_support.__file__)==LEGACY_CLONE_SOURCE_SHA256,'legacy clone support must remain unchanged')
        self.__mutex=threading.RLock()
        self.__raw=b''
        self.__state=None
        self.__hasher=hashlib.sha256()
        self.__origin=None
        self.__context=None
        self.__frontiers={}
        self.__poison_reason=None
        self.__preparation=None
        self.__owner_id=uuid.uuid4().hex
        self.__role=role
        self.__born=time.monotonic()
        self.__guard,self.__predicate,self.__predicate_code,self.__guard_sha=_bind_guard()
        self.__work=dict(calls=0,parsedEvents=0,parsedBytes=0,fullPrefixReadBytes=0,
            fullPrefixComparedBytes=0,hashUpdatedBytes=0,coldOldPrefixReplays=0,
            snapshotCopies=0,failures=0,builtinColdStates=0,builtinTailEvents=0,
            builtinContainersChecked=0,bootstrapReceivedStates=0,initializationStateClones=0,
            privateStateValidations=0,guardEvaluations=0,detachedDecisionCopies=0,
            detachedDecisionBytes=0)

    @property
    def poisoned(self):
        with self.__mutex:return self.__poison_reason is not None

    @property
    def owner_role(self):
        return self.__role

    def statistics(self):
        with self.__mutex:
            return dict(self.__work,latestPrefixBytes=len(self.__raw),
                frontierScopes=len(self.__frontiers),poisoned=self.__poison_reason is not None,
                retainedEvents=0 if self.__state is None else len(self.__state['events']),
                retainedLeases=0 if self.__state is None else len(self.__state['leases']),
                ownerId=self.__owner_id,ownerRole=self.__role)

    def __usable(self):
        need(self.__poison_reason is None,'owned guard cursor permanently poisoned: '+str(self.__poison_reason))

    def __seal_state_types(self,state,prior_sequence):
        if prior_sequence is None:
            checked=builtin_only(state)
            self.__work['builtinColdStates']+=1
        else:
            tail=state['events'][prior_sequence:]
            checked=builtin_only(tail)
            self.__work['builtinTailEvents']+=len(tail)
        self.__work['builtinContainersChecked']+=checked

    # The generated private advance below preserves the exact original prefix,
    # tail, projection, context, regression and permanent-poison predicates.
    __ADVANCE_METHOD__

    def bind_preparation(self,record,write_clock):
        with self.__mutex:
            self.__usable()
            need(self.__work['bootstrapReceivedStates']==1 and self.__preparation is None,
                 'one actual owned-state initialization artifact required')
            need(type(write_clock) is dict and set(write_clock)=={'path','sha256','startedMonotonic','completedMonotonic'},
                 'actual owned-state initialization write envelope required')
            expected_owner=record['innerOwner'] if self.__role=='inner' else record['outerOwner']
            need(expected_owner['ownerId']==self.__owner_id and expected_owner['role']==self.__role
                 and expected_owner['bornMonotonic']==self.__born,'initialization owner birth/role differs')
            need(record['scopeId'] in self.__frontiers and record['prefixBytes']==len(self.__raw)
                 and record['prefixSha256']==self.__hasher.hexdigest()
                 and record['lastSequence']==self.__state['lastSequence']
                 and record['sourceCommit']==self.__state['sourceCommit']
                 and record['policySha256']==self.__state['policySha256']
                 and record['guardPredicateAstSha256']==GUARD_PREDICATE_AST_SHA256,
                 'initialization cutoff/source/scope/predicate differs')
            need(write_clock['startedMonotonic']<=write_clock['completedMonotonic']
                 and write_clock['startedMonotonic']>=record['completedMonotonic'],
                 'initialization writer placement differs')
            self.__preparation=clone_builtin_checked(dict(initialization=record,initializationWriteClock=write_clock))

    def preparation_metadata(self):
        with self.__mutex:
            need(self.__preparation is not None,'actual owned-state initialization is not bound')
            return clone_builtin_checked(self.__preparation)

    def __reference(self,role):
        need(self.__preparation is not None,'actual owned-state initialization is not bound')
        record=self.__preparation['initialization'];writer=self.__preparation['initializationWriteClock']
        owner=record['innerOwner'] if role=='inner' else record['outerOwner']
        paired=record['outerOwner'] if role=='inner' else record['innerOwner']
        return dict(path=writer['path'],sha256=writer['sha256'],mode=record['mode'],
            prefixBytes=record['prefixBytes'],prefixSha256=record['prefixSha256'],lastSequence=record['lastSequence'],
            scopeId=record['scopeId'],sourceCommit=record['sourceCommit'],policySha256=record['policySha256'],
            cursorSourceSha256=record['cursorSourceSha256'],ownerId=owner['ownerId'],ownerRole=role,
            pairedOwnerId=paired['ownerId'],guardPredicateAstSha256=record['guardPredicateAstSha256'])

    def preparation_reference(self):
        with self.__mutex:return self.__reference(self.__role)

    def evaluate(self,policy,observation,lifecycle_journal=None):
        """Validate this actual prefix, evaluate privately, detach only the decision."""
        with self.__mutex:
            self.__usable()
            need(self.__preparation is not None,'actual owned-state initialization is not bound')
            need(self.__guard._guard_decision_from_validated_lifecycle is self.__predicate
                 and self.__predicate.__code__ is self.__predicate_code,
                 'source-owned guard predicate was replaced at runtime')
            self.__guard.validate_policy(policy)
            need(policy.get('onlineReplayMode')==MODE and
                 policy.get('onlineReplayInitializationMode')==INITIALIZATION_MODE and
                 policy.get('onlineReplaySourceSha256')==_file_sha(__file__),
                 'exact new owned-state mode/source/init required')
            # A raw observation is produced by the declared inner owner. Both
            # independent validators bind that same producer, not a foreign pair.
            need(observation.get('onlineReplayPreparation')==self.__reference('inner'),
                 'owned-state observation producer/pair reference differs')
            state=self.__advance(observation['lifecycle'],lifecycle_journal)
            self.__work['guardEvaluations']+=1
            result=self.__predicate(policy,observation,state)
            # Full history never leaves this object. Only the original complete
            # decision (including every blocker and owned process) is detached.
            detached=clone_builtin_checked(result)
            self.__work['detachedDecisionCopies']+=1
            self.__work['detachedDecisionBytes']+=len(marshal.dumps(detached,4))
            return detached


def bootstrap_pair(view,journal_bytes=None):
    """One canonical parse retained by first owner, one clone for second owner."""
    started=time.monotonic()
    first=OwnedGuardCursor('inner')
    with first._OwnedGuardCursor__mutex:
        first._OwnedGuardCursor__advance(view,journal_bytes)
        first._OwnedGuardCursor__work['bootstrapReceivedStates']=1
        second=OwnedGuardCursor('outer')
        second._OwnedGuardCursor__state=_clone_private_state(first._OwnedGuardCursor__state)
        second._OwnedGuardCursor__raw=first._OwnedGuardCursor__raw
        second._OwnedGuardCursor__hasher=first._OwnedGuardCursor__hasher.copy()
        second._OwnedGuardCursor__origin=first._OwnedGuardCursor__origin
        second._OwnedGuardCursor__context=first._OwnedGuardCursor__context
        second._OwnedGuardCursor__frontiers=clone_builtin_checked(first._OwnedGuardCursor__frontiers)
        second._OwnedGuardCursor__work['bootstrapReceivedStates']=1
        second._OwnedGuardCursor__work['initializationStateClones']=1
        state=first._OwnedGuardCursor__state
        need(state is not second._OwnedGuardCursor__state and
             first._OwnedGuardCursor__hasher is not second._OwnedGuardCursor__hasher,
             'independent private owners cannot alias mutable replay state or hasher')
        owner=lambda cursor:dict(ownerId=cursor._OwnedGuardCursor__owner_id,role=cursor._OwnedGuardCursor__role,
            bornMonotonic=cursor._OwnedGuardCursor__born,scopeId=view['scopeId'],
            controllerIdentity=clone_builtin_checked(view['controllerIdentity']))
        record=dict(schema='aijade.lifecycle.owned-guard-bootstrap.v1',mode=INITIALIZATION_MODE,
            startedMonotonic=started,completedMonotonic=None,elapsedSeconds=None,
            cursorSourceSha256=_file_sha(__file__),parserSourceSha256=PARSER_SOURCE_SHA256,
            legacyCloneSourceSha256=LEGACY_CLONE_SOURCE_SHA256,
            guardPredicateAstSha256=GUARD_PREDICATE_AST_SHA256,guardSourceSha256=first._OwnedGuardCursor__guard_sha,
            canonicalParserRuns=1,detachedCacheCloneOperations=1,
            journalPath=view['journalPath'],sourceOrigin=list(first._OwnedGuardCursor__origin),
            initialView=clone_builtin_checked(view),prefixBytes=len(first._OwnedGuardCursor__raw),
            prefixSha256=first._OwnedGuardCursor__hasher.hexdigest(),lastSequence=state['lastSequence'],
            runId=state['runId'],sourceCommit=state['sourceCommit'],policySha256=state['policySha256'],
            scopeId=view['scopeId'],controllerIdentity=clone_builtin_checked(view['controllerIdentity']),
            innerOwner=owner(first),outerOwner=owner(second),innerStatistics=first.statistics(),outerStatistics=second.statistics(),
            processObservationPerformed=False,nativeApiOrModelRequest=False,verdictGranted=False,
            independentMutableReplayStates=True,completeCanonicalHistoryRetained=True,
            perEvaluationFullStateCopies=0)
    completed=time.monotonic()
    record.update(completedMonotonic=completed,elapsedSeconds=completed-started)
    return first,second,record
