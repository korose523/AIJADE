#!/usr/bin/env python3
"""Independent complete offline audit of a source-frozen real nested load.

No collector/API/model/renderer runs here. The original independent full
lifecycle oracle is preserved and applied to the final and declared key
prefixes. A separately implemented version index validates every original
prefix/view, and the actual frozen guard cold-replays EVERY raw observation.
"""
import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

BASE = Path('/Volumes/Untitled/AIJADE')
ORACLE_SHA = 'ffbf69965dd68bcdbf1f7b67ab6e2bda31839ee80ca176a8bc3f9ba2fd77bfef'
PARSER_SHA = '93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65'
REPLAY_MODE = 'owned-guard-state-exact-prefix-v1'
INITIALIZATION_MODE = 'paired-source-verified-owned-state-v1'
LEGACY_CLONE_SHA = '0da9588655714d23db401b3424f45379689421898d85256b2506d674fee5e584'
GUARD_PREDICATE_AST_SHA = '81f098fc92bffb77e5c1938e23b5284def002edd91ed130909ec788cafa9a343'
GUARD_ORIGINAL_CORE_AST_SHA = 'b6bc9b54ba40d04503cbee3ad71ddfe64acdd6724abf47f8f01c50693b49c30b'


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate original JSON key')
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite original JSON')))


def read(path):
    return decode(Path(path).read_bytes())


def jsonl(path):
    raw = Path(path).read_bytes()
    need(raw and raw.endswith(b'\n'), 'missing/truncated original JSONL: '+str(path))
    return [decode(line) for line in raw.splitlines()]


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def files(root):
    table = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        need(all(not (Path(directory)/name).is_symlink() for name in dirs), 'symlink original directory')
        for name in names:
            path = Path(directory)/name
            need(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), 'nonregular original artifact')
            table[path.relative_to(root).as_posix()] = dict(sha256=file_sha(path), bytes=path.stat().st_size)
    return dict(sorted(table.items()))


def integer(value, label):
    need(type(value) is int and value >= 0, label)
    return value


def real(value, label):
    need(type(value) in (int,float) and math.isfinite(value) and value >= 0, label)
    return value


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo)


def no_science(receipt):
    false = ('qualificationStarted','backendQualified','scientificAdmission','formalHardwareQualification',
             'independentHumanReview','seedConstructed')
    zero = ('flowBlocks','modelRequests','rendererRequests','freshHeldoutCases','automaticRetries')
    need(all(receipt[k] is False for k in false)
         and all(type(receipt[k]) is int and receipt[k] == 0 for k in zero), 'engineering scope promoted or typed zero changed')


def verify_command_records(records, expected_commands, source, count, padding, owner, state, end_boundary):
    need(type(records) is list and len(records)==count, 'complete original source-command population')
    actual=[v for v in state['leases'].values() if v['role']=='finite' and v['parentIdentity']==owner
            and v['commandSha256'] in {sha(canonical(['git',*[arg.replace('{SOURCE}',source) for arg in e['arguments']]]))
                                     for e in expected_commands}]
    # Caller combines parent proof+padding so the complete owner sequence has
    # one actual lease per original command record, including repeated argv.
    need(len(actual)==count,'actual source-command parent lease population')
    for index,(record,lease) in enumerate(zip(records,actual)):
        expected=expected_commands[index%30]
        command=['git',*[arg.replace('{SOURCE}',source) for arg in expected['arguments']]]
        local_index=index-30 if padding=='combined-parent' and index>=30 else index
        expected_padding=(index>=30) if padding=='combined-parent' else padding
        need(type(record['index']) is int and record['index']==local_index and record['padding'] is expected_padding
             and record['status']=='COMPLETE' and record['command']==command
             and record['stdoutSha256']==expected['stdoutSha256']
             and type(record['exitCode']) is int and record['exitCode']==0,
             'frozen command/actual stdout/exit/index differs')
        need(record['startedMonotonic']<=lease['readyMonotonic']<=lease['registerMonotonic']
             <=lease['releaseMonotonic']<=lease['reapedMonotonic']<=record['completedMonotonic']<=end_boundary,
             'actual source command launch/release/parent-wait clock binding')


def verify_numeric_context(events):
    def ident(value):
        need(type(value) is dict and set(value)=={'pid','createTimeMicros','parentPid'}
             and type(value['pid']) is int and 1<value['pid']<=999999
             and type(value['parentPid']) is int and 0<value['parentPid']<=999999
             and type(value['createTimeMicros']) is int and 0<value['createTimeMicros']<=9999999999999999,
             'actual managed identity exceeds frozen conditional serialization context')
    def stamp(value):
        need(type(value) in (int,float) and math.isfinite(value) and 0<=value<=1e9
             and len(canonical(value))<=24, 'actual event clock exceeds frozen conditional serialization context')
    for event in events:
        need(type(event['seq']) is int and 0<event['seq']<=20000, 'actual sequence exceeds fixed serialized context')
        ident(event['writer']);stamp(event['monotonicSeconds'])
        data=event['data']
        for key in ('identity','parentIdentity','controllerIdentity'):
            if key in data and data[key] is not None:
                ident(data[key])
        for key in ('readyMonotonic','reapedMonotonic'):
            if key in data:
                stamp(data[key])
        if event['event']=='FINITE_REGISTER':
            stage=data['stageId']
            need(type(stage) is str and 0<len(stage.encode('ascii'))<=22,
                 'finite stage exceeds declared ASCII serialization context')
    return dict(maximumManagedPid=999999,maximumManagedParentPid=999999,
        maximumBirthMicros=9999999999999999,maximumEventSequence=20000,
        maximumMonotonicSeconds=1e9,maximumClockJsonTokenCharacters=24,maximumFiniteStageAsciiBytes=22)


def controller_identity(receipt):
    owner=receipt['controllerProcess']
    need(type(owner) is dict and set(owner)=={'pid','createTime','parentPid'}
         and type(owner['pid']) is int and owner['pid']>1
         and type(owner['parentPid']) is int and owner['parentPid']>0,
         'stream receipt controller identity schema/types')
    birth=real(owner['createTime'],'stream receipt controller kernel birth')
    need(birth>0,'stream receipt controller kernel birth missing')
    return dict(pid=owner['pid'],createTimeMicros=round(birth*1000000),parentPid=owner['parentPid'])


def verify_scope_owner(view, scope, owner):
    bound=view.get('controllerIdentity')
    need(type(scope) is str and len(scope)==32 and view.get('scopeId')==scope
         and type(bound) is dict and set(bound)==set(owner)
         and all(type(bound[k]) is int for k in bound) and bound==owner,
         'original raw lifecycle scope/controller differs from its file owner')


def verify_child_epoch_anchor(terminal, child, parent_lease):
    need(terminal['localEpochMonotonic']==child['startedMonotonic']==parent_lease['releaseMonotonic'],
         'child local epoch/startup differs from actual parent release')


def verify_loaded_module(module, repo, source_files):
    path=Path(module.__file__).resolve()
    need(path.is_relative_to(repo),'loaded audit dependency outside actual source repository')
    name=path.relative_to(repo).as_posix()
    need(name in source_files and file_sha(path)==source_files[name], 'loaded audit dependency source identity mismatch')
    return name


def exact(value, expected, message):
    """JSON comparisons must not equate bool with int or int with float."""
    need(type(value) is type(expected), message)
    if type(value) is dict:
        need(set(value) == set(expected), message)
        for key in expected:
            exact(value[key], expected[key], message)
    elif type(value) is list:
        need(len(value) == len(expected), message)
        for item, wanted in zip(value, expected):
            exact(item, wanted, message)
    else:
        need(value == expected, message)


def verify_runtime_contract(runtime):
    """E5 retains the prospectively declared15s startup and all other bounds."""
    expected = dict(blocks=4, blockWorkSeconds=120, betweenBlockSeconds=4,
        parentTailSeconds=4, parentMaximumSeconds=600, childStartupMaximumSeconds=15,
        childCleanupMaximumSeconds=8, childWatchdogSeconds=145,
        alignmentModes=['natural','parent-next-slot','natural','parent-next-slot'])
    exact(runtime, expected, 'frozen E5 engineering runtime changed')
    return expected


def builtin_container_count(value):
    """Independent supported-type/alias count, with no candidate clone code."""
    seen, active = set(), set()
    pending = [(value, False)]
    while pending:
        item, exiting = pending.pop()
        kind = type(item)
        if kind in (type(None), bool, int, str):
            continue
        if kind is float:
            need(math.isfinite(item), 'nonfinite canonical initialization state')
            continue
        need(kind in (dict, list, tuple), 'unsupported canonical initialization state')
        identity = id(item)
        if exiting:
            active.remove(identity)
            seen.add(identity)
            continue
        need(identity not in active, 'cyclic canonical initialization state')
        if identity in seen:
            continue
        active.add(identity)
        pending.append((item, True))
        children = [v for pair in item.items() for v in pair] if kind is dict else list(item)
        pending.extend((v, False) for v in reversed(children))
    return len(seen)


def expected_initial_statistics(prefix_bytes, sequence, containers, leases, inner_owner, outer_owner):
    common = dict(calls=0, parsedEvents=0, parsedBytes=0, fullPrefixReadBytes=0,
        fullPrefixComparedBytes=0, hashUpdatedBytes=0, coldOldPrefixReplays=0,
        snapshotCopies=0, failures=0, builtinColdStates=0, builtinTailEvents=0,
        builtinContainersChecked=0, bootstrapReceivedStates=1, initializationStateClones=0,
        privateStateValidations=0, guardEvaluations=0, detachedDecisionCopies=0,
        detachedDecisionCanonicalBytes=0, latestPrefixBytes=prefix_bytes, frontierScopes=1,
        poisoned=False, retainedEvents=sequence, retainedLeases=leases)
    outer = dict(common, initializationStateClones=1,ownerId=outer_owner['ownerId'],ownerRole='outer')
    inner = dict(common, calls=1, parsedEvents=sequence, parsedBytes=prefix_bytes,
        fullPrefixReadBytes=prefix_bytes, hashUpdatedBytes=prefix_bytes,
        builtinColdStates=1,builtinContainersChecked=containers,privateStateValidations=1,
        ownerId=inner_owner['ownerId'],ownerRole='inner')
    return inner, outer


def verify_guard_predicate_source(guard_path):
    tree=ast.parse(Path(guard_path).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
        and n.name=='_guard_decision_from_validated_lifecycle')
    need(sha(ast.dump(node,include_attributes=False).encode())==GUARD_PREDICATE_AST_SHA,
         'fixed owned guard decision predicate AST differs')
    branch=next(n for n in node.body if isinstance(n,ast.Try))
    original_core=ast.Module(body=branch.body[3:],type_ignores=[])
    need(sha(ast.dump(original_core,include_attributes=False).encode())==GUARD_ORIGINAL_CORE_AST_SHA,
         'original complete guard decision core AST differs')
    return dict(predicateAstSha256=GUARD_PREDICATE_AST_SHA,originalCoreAstSha256=GUARD_ORIGINAL_CORE_AST_SHA)


def verify_initialization(scope_root, receipt, journal_path, index, oracle, parser,
                          passport, *, owner, scope, earliest, latest, anchor,
                          budget):
    """Audit one real initialization, without executing the online candidate.

    A single original-parser cold replay establishes exact initial counters.
    Its logical state is crosschecked with the separate unchanged oracle and
    historical index; each later sample still undergoes independent raw replay.
    """
    path = scope_root/'initialization.json'
    raw = path.read_bytes()
    core = decode(raw)
    exact(receipt['initialization'], core, 'receipt/core initialization differs')
    write = receipt['initializationWriteClock']
    need(type(write) is dict and set(write) == {'startedMonotonic','completedMonotonic','sha256','path'}
         and write['sha256'] == sha(raw) and write['path'] == str(path),
         'actual initialization write bytes/path binding')
    factory = real(core['factoryStartedMonotonic'], 'actual initialization factory start')
    captured = real(core['viewCapturedMonotonic'], 'actual initialization view capture')
    began = real(core['startedMonotonic'], 'actual bootstrap start')
    ended = real(core['completedMonotonic'], 'actual bootstrap completion')
    write_began = real(write['startedMonotonic'], 'actual initialization write start')
    write_ended = real(write['completedMonotonic'], 'actual initialization write completion')
    need(anchor <= earliest <= factory <= captured <= began <= ended <= write_began <= write_ended <= latest
         and write_began == core['recordWriteStartedMonotonic']
         and ended-began == core['elapsedSeconds'] and write_ended-anchor <= budget,
         'full initialization factory/view/clone/write placement or preparation/startup budget')
    exact(core['canonicalParserRuns'], 1, 'bootstrap canonical parser population')
    exact(core['detachedCacheCloneOperations'], 1, 'bootstrap detached cache clone population')
    exact(core['processObservationPerformed'], False, 'bootstrap hidden observation')
    exact(core['nativeApiOrModelRequest'], False, 'bootstrap native/API/model request')
    exact(core['verdictGranted'], False, 'bootstrap cached verdict')
    exact(core['independentMutableReplayStates'], True, 'bootstrap mutable-state detachment claim')
    need(core['schema'] == 'aijade.lifecycle.owned-guard-bootstrap.v1'
         and core['mode'] == passport['onlineReplayInitializationMode'] == INITIALIZATION_MODE
         and passport['onlineReplayMode'] == REPLAY_MODE
         and core['cursorSourceSha256'] == passport['sourceFiles']['experiments/ch7/newowned_guard_cursor.py']
         == passport['onlineReplaySourceSha256']
         and core['parserSourceSha256'] == PARSER_SHA
         and core['legacyCloneSourceSha256']==LEGACY_CLONE_SHA
         and core['guardSourceSha256']==passport['sourceFiles']['experiments/ch7/mac_process_guard_v3.py']
         and core['guardPredicateAstSha256']==GUARD_PREDICATE_AST_SHA,
         'initialization mode/source identity mismatch')
    exact(core['completeCanonicalHistoryRetained'], True, 'initializer discarded complete canonical history')
    exact(core['perEvaluationFullStateCopies'], 0, 'owned evaluation reports full-state copies')
    owners=[core['innerOwner'],core['outerOwner']]
    for expected_role,owner_record in zip(('inner','outer'),owners):
        need(type(owner_record) is dict and set(owner_record)=={'ownerId','role','bornMonotonic','scopeId','controllerIdentity'}
             and type(owner_record['ownerId']) is str and len(owner_record['ownerId'])==32
             and all(c in '0123456789abcdef' for c in owner_record['ownerId'])
             and owner_record['role']==expected_role,'actual independent owned cursor identity/role')
        verify_scope_owner(owner_record,scope,owner)
        need(began<=real(owner_record['bornMonotonic'],'actual guard owner birth')<=ended,'guard owner born outside actual bootstrap')
    need(owners[0]['ownerId']!=owners[1]['ownerId']
         and owners[0]['bornMonotonic']<=owners[1]['bornMonotonic'],'paired guard owner aliases or birth order differs')
    view = core['initialView']
    verify_scope_owner(view, scope, owner)
    verify_scope_owner(core, scope, owner)
    need(view['journalPath'] == core['journalPath'] == str(journal_path), 'initialization journal path differs')
    prefix, indexed = index.prefix(core['prefixBytes'], core['prefixSha256'], core['lastSequence'])
    exact(view['journalBytes'], len(prefix), 'initialization view byte boundary differs')
    exact(view['lastSequence'], core['lastSequence'], 'initialization view event boundary differs')
    need(view['journalSha256'] == sha(prefix) == core['prefixSha256']
         and view['runId'] == core['runId'] == indexed['runId']
         and core['sourceCommit'] == passport['sourceCommit']
         and core['policySha256'] == passport['policySha256'], 'initialization original prefix/context differs')
    independent = oracle._replay(prefix, passport['sourceCommit'], passport['policySha256'])
    need(independent['events'][-1]['monotonicSeconds'] <= captured,
         'initialization prefix contains an event after actual view capture')
    exact(indexed, independent, 'initialization prefix independent oracle/index differs')
    cold = parser.replay_journal(prefix)
    for name in independent:
        exact(cold[name], independent[name], 'initialization canonical parser/independent oracle differs: '+name)
    projected = [v for v in independent['leases'].values() if v['absence'] is None]
    exact(view['referencedIdentities'], [], 'journal-only initialization has process references')
    exact(view['launchRefusalArtifacts'], [], 'initialization includes refused launch')
    exact(view['leases'], projected, 'initialization exact lease projection differs')
    exact(view['controllers'], [v['leaseId'] for v in projected if v['identity'] == owner],
          'initialization controller projection differs')
    live_scope = independent['scopes'][scope]
    need(live_scope['closeSeq'] is None and live_scope['controllerIdentity'] == owner,
         'initialization scope not open or owner differs')
    node = journal_path.stat(follow_symlinks=False)
    expected_source_origin = ['file', str(journal_path), node.st_dev, node.st_ino]
    exact(core['sourceOrigin'], expected_source_origin, 'initialization actual file source origin differs')
    cold['launchRefusalArtifacts'] = []
    containers = builtin_container_count(cold)
    initial_inner, initial_outer = expected_initial_statistics(len(prefix), core['lastSequence'], containers,len(independent['leases']),*owners)
    exact(core['innerStatistics'], initial_inner, 'initial inner parser/clone/full-read statistics differs')
    exact(core['outerStatistics'], initial_outer, 'initial outer parser/clone/full-read statistics differs')
    return dict(core=core, writeClock=write, path=str(path), sha256=sha(raw),
        independentCanonicalContainerCount=containers, initialInnerStatistics=initial_inner,
        initialOuterStatistics=initial_outer, prefixIndependentColdReplay=True)


def verify_initialization_usage(initial, rows, receipt, index, passport, decisions):
    """Derive all cumulative cursor costs from every actual original cutoff.

    No producer counter is used to form expectations. In particular, the first
    later callback must physically read the whole prefix, compare all bootstrap
    bytes and independently parse the newly appended tail in both cursors.
    """
    core = initial['core']
    need(type(rows) is list and rows, 'initialization has no subsequent actual samples')
    previous_bytes, previous_seq = core['prefixBytes'], core['lastSequence']
    inner, outer = dict(initial['initialInnerStatistics']), dict(initial['initialOuterStatistics'])
    reference = dict(path=initial['path'], sha256=initial['sha256'], mode=INITIALIZATION_MODE,
        prefixBytes=core['prefixBytes'],prefixSha256=core['prefixSha256'],lastSequence=core['lastSequence'],
        sourceCommit=core['sourceCommit'],policySha256=core['policySha256'],scopeId=core['scopeId'],
        cursorSourceSha256=core['cursorSourceSha256'],ownerId=core['innerOwner']['ownerId'],ownerRole='inner',
        pairedOwnerId=core['outerOwner']['ownerId'],guardPredicateAstSha256=GUARD_PREDICATE_AST_SHA)
    first_tail = None
    for position, row in enumerate(rows):
        observation = row['processObservation']
        view = observation['lifecycle']
        need(observation['onlineReplayMode'] == passport['onlineReplayMode'] == REPLAY_MODE
             and observation['onlineReplaySourceSha256'] == passport['onlineReplaySourceSha256']
             and observation['onlineReplayInitializationMode'] == INITIALIZATION_MODE,
             'original raw online replay source/mode differs')
        exact(observation['onlineReplayPreparation'], reference, 'original raw initialization reference differs')
        need(row['monotonicSeconds'] >= initial['writeClock']['completedMonotonic']
             and view['scopeId'] == core['scopeId'], 'sample predates initialization write or changes scope')
        prefix, state = index.prefix(view['journalBytes'],view['journalSha256'],view['lastSequence'])
        count, sequence = len(prefix), view['lastSequence']
        need(count >= previous_bytes and sequence >= previous_seq, 'post-initialization prefix regressed')
        tail_bytes, tail_events = count-previous_bytes, sequence-previous_seq
        if position == 0:
            need(tail_bytes > 0 and tail_events > 0, 'first post-bootstrap sample did not validate actual new tail')
            first_tail = dict(bytes=tail_bytes,events=tail_events)
        checked = builtin_container_count(state['events'][previous_seq:sequence])
        decision=decisions[row['sampleId']]
        need(type(decision) is dict and set(decision)=={'status','blockers','ownedProcesses','ownedRssBytes'},
             'complete independently cold-replayed decision required for canonical byte counter')
        logical_bytes=len(canonical(decision))
        for stats in (inner, outer):
            stats['calls'] += 1
            stats['fullPrefixReadBytes'] += count
            stats['fullPrefixComparedBytes'] += previous_bytes
            stats['parsedEvents'] += tail_events
            stats['parsedBytes'] += tail_bytes
            stats['hashUpdatedBytes'] += tail_bytes
            stats['privateStateValidations'] += 1
            stats['guardEvaluations'] += 1
            stats['detachedDecisionCopies'] += 1
            stats['detachedDecisionCanonicalBytes'] += logical_bytes
            stats['retainedEvents'] = sequence
            stats['retainedLeases'] = len(state['leases'])
            stats['builtinTailEvents'] += tail_events
            stats['builtinContainersChecked'] += checked
            stats['latestPrefixBytes'] = count
        previous_bytes, previous_seq = count, sequence
    exact(receipt['innerCursor'], inner, 'final inner actual prefix/read/compare/parser/clone counter population differs')
    exact(receipt['outerCursor'], outer, 'final outer actual prefix/read/compare/parser/clone counter population differs')
    return dict(initializationPath=initial['path'],initializationSha256=initial['sha256'],
        initialPrefixBytes=core['prefixBytes'],initialSequence=core['lastSequence'],actualSamples=len(rows),
        firstSampleNewTail=first_tail,expectedInnerStatistics=inner,expectedOuterStatistics=outer,
        allOriginalPrefixesFullyReadAndCompared=True,allActualNewTailEventsIncluded=True,
        innerOwnerId=core['innerOwner']['ownerId'],outerOwnerId=core['outerOwner']['ownerId'],
        completeCanonicalHistoryRetained=True,perEvaluationFullStateCopies=0,
        decisionByteScope='Canonical JSON logical bytes derived from independent complete cold decisions; not physical marshal bytes.')


def verify_stream(prefix, root, receipt, measured, *, maximum_seconds, slots_maximum, epoch, baseline):
    raw_path = root/(prefix+'telemetry.jsonl' if prefix else 'process-observations.jsonl')
    diag_path = root/(prefix+'service-events.jsonl')
    terminal_path = diag_path.with_suffix('.terminal.json')
    raw, diag, terminal = jsonl(raw_path), diag_path.read_bytes(), read(terminal_path)
    derived = measured.validate_terminal(terminal, raw, diag, maximum_seconds=maximum_seconds)
    # Independent recomputation in addition to the frozen monitor's validator.
    services = terminal['services']
    origin = real(terminal['scheduleOriginMonotonic'], 'actual original monitor origin')
    stopped = real(terminal['stopRequestedMonotonic'], 'actual stop request')
    need(integer(terminal['expectedSlotCount'],'expected slot count') == math.ceil((stopped-origin)/2)
         and len(raw) <= slots_maximum, 'declared exact stream population/envelope')
    need(terminal['epochMonotonic'] == epoch, 'shared sequence origin was reset')
    if prefix:
        need(terminal['localEpochMonotonic']==receipt['startedMonotonic'], 'child local epoch differs from actual release/startup anchor')
        need(receipt['scopeId']==receipt['registryFinal']['scopeId'], 'child receipt and terminal registry scope differ')
    else:
        need(terminal['localEpochMonotonic']==epoch, 'parent local epoch differs from sequence epoch')
    scope=receipt['registryFinal']['scopeId']
    owner=controller_identity(receipt)
    previous_end = None
    timers = {}
    ids = set()
    for index, (row, service, line) in enumerate(zip(raw, services, diag.splitlines(keepends=True))):
        verify_scope_owner(row['processObservation']['lifecycle'],scope,owner)
        need(type(row['monitorSlotIndex']) is int and type(service['slotIndex']) is int
             and row['monitorSlotIndex'] == service['slotIndex'] == index, 'independent original slot order/types')
        start = real(row['monotonicSeconds'], 'actual original stream start')
        end = real(service['serviceCompletedMonotonic'], 'full measured service end')
        need(previous_end is None or previous_end <= start, 'same-scope measured callbacks overlap')
        previous_end = end
        target = origin+2*index
        need(service['startLatenessSeconds'] == start-target
             and end == service['diagnosticWriterCompletedMonotonic'], 'independent service/diagnostic/actual lateness binding')
        need(row['sequenceElapsedSeconds'] == start-epoch
             and row['elapsedSeconds'] == start-terminal['localEpochMonotonic'], 'independent actual elapsed clocks')
        provisional = decode(line)
        need(canonical(provisional)+b'\n' == line, 'diagnostic not exact canonical flushed bytes')
        sid = row['processObservation']['sampleId']
        need(sid not in ids, 'original stream sample duplicated')
        ids.add(sid)
        need(integer(row['swapUsedBytes'],'actual swap') >= 0
             and row['swapIncreaseBytes'] == max(0,row['swapUsedBytes']-baseline), 'shared actual swap baseline changed')
        for name, crossed in [('rss', integer(row['rssBytes'],'actual RSS') > 2*1024**3),
                              ('available', integer(row['availableBytes'],'actual available') < 3*1024**3),
                              ('swap', row['swapIncreaseBytes'] > 1024**3)]:
            if not crossed:
                timers.pop(name, None)
            else:
                timers.setdefault(name, start)
                need(start-timers[name] < 30, 'independently reconstructed sustained resource stop')
    need(stopped-raw[-1]['monotonicSeconds'] <= 2.5, 'unobserved terminal monitor prefix')
    timer_path = root/(prefix+'resource-timers.json')
    need(read(timer_path) == timers, 'final sustained resource timers differ from complete raw stream')
    need(terminal['status'] == 'COMPLETE_MEASURED_MONITOR_SERVICES' and terminal['errors'] == []
         and terminal['threadAlive'] is False, 'actual monitor terminal adverse')
    return raw, terminal, dict(derived, originalRawPath=str(raw_path), originalDiagnosticPath=str(diag_path))


def main(args):
    root, repo, output = args.root.resolve(), args.repo.resolve(), args.output.resolve()
    need(root.is_relative_to(BASE) and repo.is_relative_to(BASE) and output.is_relative_to(BASE)
         and not output.exists() and root not in output.parents, 'project/exclusive audit output boundary')
    before = files(root)
    need(file_sha(args.passport) == args.passport_sha256, 'pre-run published passport SHA differs')
    passport = read(args.passport)
    need(passport['schema'] == 'aijade.ch7.nested-load-passport.v1'
         and Path(passport['repo']).resolve() == repo and Path(passport['output']).resolve() == root,
         'actual source/output passport binding')
    need((root/'engineering-passport.json').read_bytes() == Path(args.passport).read_bytes(), 'executed passport changed')
    receipt = read(root/'receipt.json')
    no_science(receipt)
    need(receipt['schema'] == 'aijade.ch7.nested-load-result.v1'
         and receipt['status'] == 'ENGINEERING_REAL_NESTED_LOAD_PASS_PENDING_INDEPENDENT_AUDIT'
         and receipt['errors'] == [] and receipt['lifecycleJournalStable'] is True
         and receipt['passportSha256'] == args.passport_sha256, 'controller completion is not a complete stable engineering candidate')
    need(passport['prefixPaddingTaskCount'] == 2500 and passport['prefixPreparationMaximumSeconds']==900
         and passport['minimumDemonstratedPrefixBytes'] == 14*1024**2, 'frozen engineering workload changed')
    verify_runtime_contract(passport['runtime'])
    source = passport['sourceCommit']
    need(receipt['sourceCommit'] == source and receipt['policySha256'] == passport['policySha256'], 'actual source/policy context')
    need(receipt['sourceFiles'] == passport['sourceFiles'], 'frozen source population differs')
    proof = []
    audit_relative='experiments/ch7/audit_nested_load.py'
    essentials={audit_relative,'experiments/ch7/nested_event_index.py','experiments/ch7/run_nested_load.py',
                'experiments/ch7/measured_mac_monitor.py','experiments/ch7/mac_process_guard_v3.py',
                'experiments/ch7/lifecycle_audit.py','experiments/ch7/process_lifecycle.py',
                'experiments/ch7/full_state_clone_cursor.py','experiments/ch7/newowned_guard_cursor.py'}
    need(essentials<=set(passport['sourceFiles']), 'complete producer-checked audit/observer source map required')
    need(Path(__file__).resolve()==repo/audit_relative and file_sha(Path(__file__))==passport['auditScriptSha256']
         ==passport['sourceFiles'][audit_relative], 'actual audit executable source identity mismatch')
    for name, expected in passport['sourceFiles'].items():
        path = repo/name
        need(path.resolve().is_relative_to(repo) and not path.is_symlink()
             and sha(path.read_bytes()) == expected
             and path.read_bytes() == git(repo, 'show', source+':'+name), 'frozen Git/source bytes differ: '+name)
        proof.append(dict(path=name,sha256=expected))
    need(sha((repo/'experiments/ch7/lifecycle_audit.py').read_bytes()) == ORACLE_SHA, 'preserved independent oracle changed')
    sys.path.insert(0, str(repo/'experiments/ch7'))
    import lifecycle_audit as oracle
    import mac_process_guard_v3 as guard
    import measured_mac_monitor as measured
    import nested_event_index as index_module
    import process_lifecycle as canonical_parser
    import full_state_clone_cursor as clone_module
    import newowned_guard_cursor as owned_module
    from nested_event_index import EventIndex, typed_equal
    need(sha(Path(oracle.__file__).read_bytes()) == ORACLE_SHA, 'wrong loaded independent cold oracle')
    for module in (oracle,guard,measured,index_module,canonical_parser,clone_module,owned_module):
        verify_loaded_module(module,repo,passport['sourceFiles'])
    need(file_sha(canonical_parser.__file__)==PARSER_SHA and file_sha(clone_module.__file__)==LEGACY_CLONE_SHA,
         'original canonical parser or legacy complete-return clone source changed')
    predicate_proof=verify_guard_predicate_source(guard.__file__)
    policy = read(root/'process-policy.json')
    need(file_sha(root/'process-policy.json') == passport['policySha256']
         and (root/'process-policy.json').read_bytes() == git(repo, 'show', source+':'+passport['policyPath']), 'actual policy bytes')
    need(policy['onlineReplayMode']==passport['onlineReplayMode']==REPLAY_MODE
         and policy['onlineReplaySourceSha256']==passport['onlineReplaySourceSha256']
         ==passport['sourceFiles']['experiments/ch7/newowned_guard_cursor.py']
         and policy['onlineReplayInitializationMode']==passport['onlineReplayInitializationMode']==INITIALIZATION_MODE,
         'frozen explicit E5 online replay source/initialization identity')
    journal=(root/'lifecycle-journal.jsonl').read_bytes()
    need(passport['minimumDemonstratedPrefixBytes'] <= len(journal) == receipt['lifecycleJournalBytes'] and sha(journal) == receipt['lifecycleJournalSha256']
         and len(journal) <= passport['journalAcceptanceMaximumBytes'] <= 16*1024**2-512*1024, 'bounded complete journal envelope')
    index = EventIndex(journal, oracle._replay, source, passport['policySha256'])
    complete=index.state(len(index.events))
    numeric_context=verify_numeric_context(complete['events'])
    finite=[v for v in complete['leases'].values() if v['role']=='finite']
    need(all(v['releaseSeq'] is not None and v['waitSeq'] is not None and type(v['exitCode']) is int and v['exitCode']==0
             and v.get('absence') is not None for v in finite), 'incomplete/adverse actual finite parent waits')
    need(all(s['closeSeq'] is not None for s in complete['scopes'].values()) and len(complete['scopes'])==5,
         'all five actual controller scopes must close')
    need(typed_equal(receipt['registryFinal']['knownFiniteLeases'], finite), 'parent final finite population differs from independent cold state')
    settling, admission = jsonl(root/'settling/telemetry.jsonl'),jsonl(root/'admission/telemetry.jsonl')
    need((len(settling),len(admission)) == (300,60), 'complete fixed unloaded population')
    epoch=receipt['nestedEpochMonotonic'];baseline=integer(receipt['nestedInitialSwapUsedBytes'],'original global swap baseline')
    parent_rows,parent_terminal,parent_stream=verify_stream('',root,receipt,measured,
        maximum_seconds=600,slots_maximum=300,epoch=epoch,baseline=baseline)
    streams=[('parent',parent_rows,parent_terminal)]
    child_rows=[];child_terminals=[];block_results=[]
    need(len(receipt['nestedBlocks']) == len(receipt['blockWaits']) == 4, 'four exact nested blocks and parent waits')
    parent_scope=receipt['registryFinal']['scopeId']
    parent_identity=complete['scopes'][parent_scope]['controllerIdentity']
    root_record=complete['events'][0]
    need(root_record['event']=='CONTROLLER_REGISTER' and root_record['data']['identity']==parent_identity
         and parent_identity['pid']==receipt['controllerProcess']['pid']
         and parent_identity['createTimeMicros']==round(receipt['controllerProcess']['createTime']*1000000)
         and root_record['data']['executableSha256']==passport['pythonSha256'], 'actual parent process/source interpreter identity')
    preflight_clock=read(root/'preflight-continuity.json')['schedule']['originMonotonic']
    verify_command_records(receipt['preflightCommands']+receipt['prefixPaddingCommands'],passport['preflightCommands'],
        source,2530,'combined-parent',parent_identity,complete,preflight_clock)
    parent_initialization=verify_initialization(root,receipt,root/'lifecycle-journal.jsonl',index,oracle,
        canonical_parser,passport,owner=parent_identity,scope=parent_scope,
        earliest=receipt['prefixPaddingCommands'][-1]['completedMonotonic'], latest=preflight_clock,
        anchor=receipt['preparationEpochMonotonic'],budget=900)
    initialization_populations=[(parent_initialization,settling+admission+parent_rows,receipt)]
    stage_events=jsonl(root/'stage-events.jsonl')
    block_launches=[e for e in stage_events if e['event']=='block-launch-enter']
    need(len(block_launches)==4 and [e['blockIndex'] for e in block_launches]==[0,1,2,3],
         'complete actual block launch stage population')
    for n in range(4):
        block=root/('block-'+str(n+1));child=read(block/'receipt.json');ready=read(block/'ready.json')
        no_science(child)
        need(typed_equal(child,receipt['nestedBlocks'][n]) and child['blockIndex']==n
             and child['status']=='NESTED_CHILD_COMPLETE' and child['errors']==[] and child['lifecycleJournalStable'] is True,
             'actual original child receipt differs/adverse')
        rows, terminal, stream=verify_stream('block-'+str(n+1)+'/',root,child,measured,
            maximum_seconds=128,slots_maximum=64,epoch=epoch,baseline=baseline)
        child_rows.append(rows);child_terminals.append(terminal);streams.append(('child-'+str(n+1),rows,terminal))
        scope=complete['scopes'][child['scopeId']];lease=complete['leases'][child['parentLeaseId']]
        verify_child_epoch_anchor(terminal,child,lease)
        wait=receipt['blockWaits'][n]
        need(lease['stageId']=='nested-block-'+str(n+1) and lease['parentIdentity']==parent_identity
             and scope['controllerIdentity']==lease['identity'] and scope['parentLeaseId']==child['parentLeaseId']
             and child['controllerProcess']['pid']==lease['identity']['pid'], 'actual nested child parent/birth/scope')
        need(wait['leaseId']==child['parentLeaseId'] and wait['identity']==lease['identity']
             and wait['parentIdentity']==parent_identity and wait['reapedMonotonic']==lease['reapedMonotonic']
             and lease['reapedMonotonic']<=wait['waitReturnedMonotonic'], 'actual parent wait source envelope')
        need(child['startedMonotonic']==ready['sourceStartupStartedMonotonic']==lease['releaseMonotonic']
             <=child['pythonEntryMonotonic']<=child['readyWriteStartedMonotonic']
             <=child['readyWriteCompletedMonotonic']
             and child['readyWriteCompletedMonotonic']-lease['releaseMonotonic']<=15
             and child['readyFileSha256']==file_sha(block/'ready.json')
             and ready['readyWriteStartedMonotonic']==child['readyWriteStartedMonotonic'],
             'full parent-release/import/source/monitor/ready-flush startup budget')
        verify_command_records(child['preflightCommands'],passport['preflightCommands'],source,30,False,
            lease['identity'],complete,child['readyWriteStartedMonotonic'])
        child_initialization=verify_initialization(block,child,root/'lifecycle-journal.jsonl',index,oracle,
            canonical_parser,passport,owner=lease['identity'],scope=child['scopeId'],
            earliest=child['preflightCommands'][-1]['completedMonotonic'],
            latest=child['engineeringAlignment']['waitStartedMonotonic'],
            anchor=lease['releaseMonotonic'],budget=15)
        need(child_initialization['writeClock']['completedMonotonic']<=terminal['scheduleOriginMonotonic']
             <=child['readyWriteStartedMonotonic']<=child['readyWriteCompletedMonotonic']
             and child['readyWriteCompletedMonotonic']-lease['releaseMonotonic']<=15,
             'child initialization/monitor/full ready-write startup placement')
        initialization_populations.append((child_initialization,rows,child))
        need(child['cleanupStartedMonotonic']>=terminal['scheduleOriginMonotonic']+120
             and rows[-1]['monotonicSeconds']>=child['cleanupStartedMonotonic']
             and lease['reapedMonotonic']-child['cleanupStartedMonotonic']<=8,
             'child complete cleanup/receipt/actual reap budget')
        alignment=child['engineeringAlignment']
        need(typed_equal(alignment,ready['engineeringAlignment'])
             and alignment['mode']==passport['runtime']['alignmentModes'][n]
             and alignment['parentMonitorOriginMonotonic']==parent_terminal['scheduleOriginMonotonic']
             and child['preflightCommands'][-1]['completedMonotonic']<=alignment['waitStartedMonotonic']
             <=alignment['waitCompletedMonotonic']<=terminal['scheduleOriginMonotonic'],
             'engineering phase alignment/source-startup timing')
        if n in (1,3):
            target=parent_terminal['scheduleOriginMonotonic']+2*(math.floor(
                (alignment['waitStartedMonotonic']-parent_terminal['scheduleOriginMonotonic'])/2)+1)
            need(alignment['plannedAlignTargetMonotonic']==target
                 <=alignment['waitCompletedMonotonic']<=terminal['scheduleOriginMonotonic']<=target+.5,
                 'predeclared adverse next-parent-slot alignment')
        else:
            need(alignment['plannedAlignTargetMonotonic'] is None,'natural block received hidden alignment')
        # Whole parent coverage must include import/source startup and final reap.
        need(parent_rows[0]['monotonicSeconds']<=lease['releaseMonotonic']
             and parent_rows[-1]['monotonicSeconds']>=lease['reapedMonotonic'], 'parent monitor omits actual child lifetime')
        overlaps=sum(a['sampleStartedMonotonic']<b['serviceCompletedMonotonic']
            and b['sampleStartedMonotonic']<a['serviceCompletedMonotonic']
            for a in parent_terminal['services'] for b in terminal['services'])
        need(overlaps>=1,'real nested stream service overlap never exercised')
        peer_requests=sum(a['acquiredMonotonic']<=b['requestStartedMonotonic']<a['releasedMonotonic']
            for parent_row in parent_rows for child_row in rows
            for a in parent_row['processObservation']['coordinationLocks'].values()
            for b in child_row['processObservation']['coordinationLocks'].values())
        peer_requests+=sum(b['acquiredMonotonic']<=a['requestStartedMonotonic']<b['releasedMonotonic']
            for parent_row in parent_rows for child_row in rows
            for a in parent_row['processObservation']['coordinationLocks'].values()
            for b in child_row['processObservation']['coordinationLocks'].values())
        if n in (1,3):
            need(peer_requests>=1,'predeclared aligned block did not exercise actual cross-stream lock contention')
        launch_stage=real(block_launches[n]['monotonicSeconds'],'actual block launch stage entry')
        need(parent_rows[0]['monotonicSeconds']<=launch_stage<=lease['readyMonotonic']<=lease['releaseMonotonic'],
             'actual launch-stage/ready/release order or parent coverage')
        block_results.append(dict(blockIndex=n, stream=stream, actualServiceOverlaps=overlaps,
            crossStreamRequestsDuringPeerHeldLock=peer_requests,engineeringAlignment=alignment,
            releaseMonotonic=lease['releaseMonotonic'], actualReapedMonotonic=lease['reapedMonotonic'],
            launchStageEnteredMonotonic=launch_stage,
            preReleaseSecondsFromLaunchStage=lease['releaseMonotonic']-launch_stage,
            actualElapsedThroughParentWaitFromLaunchStage=wait['waitReturnedMonotonic']-launch_stage,
            launchStageClockScope='Includes the stage record writer before the runner watchdog anchor; descriptive actual overhead, not a replacement watchdog or total-completion certificate.'))
    all_rows=settling+admission+parent_rows+[r for rows in child_rows for r in rows]
    need(len(all_rows)<=916, 'complete frozen maximum original observation population')
    need(parent_rows[-1]['processObservation']['lifecycle']['journalBytes'] >= passport['minimumDemonstratedPrefixBytes']
         and child_rows[-1][-1]['processObservation']['lifecycle']['journalBytes'] >= passport['minimumDemonstratedPrefixBytes'],
         'last parent/block4 actual observed prefix did not reach the frozen minimum')
    native_ids=set();sample_ids=set();per_scope={};max_prefix=0;checkpoint_sequences=set();cold_decisions={}
    # Actual first/last idle, every child last and sequence last are independent
    # old-oracle baseline crosschecks. All other original rows use the separate
    # exact version index, never a production PASS cache.
    for row in [settling[0],admission[-1],parent_rows[-1],*[rows[-1] for rows in child_rows]]:
        checkpoint_sequences.add(row['processObservation']['lifecycle']['lastSequence'])
    started=time.monotonic()
    for n,row in enumerate(all_rows):
        observation=row['processObservation'];view=observation['lifecycle']
        decision=oracle._validate_sample(row,policy,journal)
        need(decision['status']==observation['status']=='PASS' and decision['blockers']==observation['blockers']==[], 'original raw guard adverse')
        sid=oracle.sample_id(row);need(sid not in sample_ids,'global original sample identity reused');sample_ids.add(sid)
        cold_decisions[sid]=decision
        need(row['observerModuleSha256']==passport['sourceFiles']['experiments/ch7/mac_process_guard_v3.py']
             and row['processPolicySha256']==passport['policySha256'] and row['observerSources']==passport['observerSources'],
             'original observer source closure mismatch')
        prefix,state=index.prefix(view['journalBytes'],view['journalSha256'],view['lastSequence'])
        max_prefix=max(max_prefix,len(prefix))
        scope=state['scopes'][view['scopeId']]
        need(scope['closeSeq'] is None and scope['controllerIdentity']==view['controllerIdentity'], 'sample persistent scope wrong/closed')
        previous=per_scope.get(view['scopeId'])
        need(previous is None or (view['journalBytes']>=previous[0] and row['monotonicSeconds']>=previous[1]),
             'scope prefix reversal or impossible same-scope overlapping capture')
        per_scope[view['scopeId']]=(view['journalBytes'],row['observationCompletedMonotonic'])
        frames=oracle._raw_frames(observation,policy)
        refs=sorted({oracle.node_identity(node) for frame in frames for node in frame['nodes']})
        projected=[v for v in state['leases'].values() if v['absence'] is None or oracle.identity(v['identity']) in refs]
        need(typed_equal(view['referencedIdentities'],[list(v) for v in refs]) and typed_equal(view['leases'],projected)
             and typed_equal(view['controllers'],[v['leaseId'] for v in projected if v['identity']==view['controllerIdentity']]),
             'exact independent original prefix view projection')
        for frame in frames:
            lease_id=oracle._native_lease(frame,state,view['controllerIdentity'],policy)
            need(lease_id not in native_ids,'original native lease reused across captures');native_ids.add(lease_id)
        if n<360:
            verify_scope_owner(view,parent_scope,parent_identity)
            need(observation['ownedRoots']==observation['ownedProcesses']==[] and row['rssBytes']==0, 'idle roots/RSS changed')
        else:
            need(len(observation['ownedRoots'])==1 and type(row['rssBytes']) is int, 'actual runtime owned roots/RSS absent')
        if (n+1)%25==0 or n+1==len(all_rows):
            print(json.dumps(dict(stage='COMPLETE_NESTED_RAW_AND_PREFIX_REPLAY',samples=n+1,total=len(all_rows),seconds=time.monotonic()-started)),flush=True)
    need(len(native_ids)==2*len(all_rows),'complete original native capture population')
    initialization_results=[verify_initialization_usage(initial,rows,owner_receipt,index,passport,cold_decisions)
        for initial,rows,owner_receipt in initialization_populations]
    owner_ids=[result[key] for result in initialization_results for key in ('innerOwnerId','outerOwnerId')]
    need(len(owner_ids)==len(set(owner_ids))==10,'independent cursor owner identity reused across scopes')
    crosschecks=[]
    for sequence in sorted(checkpoint_sequences):
        prefix=journal[:index.offsets[sequence]]
        cold=oracle._replay(prefix,source,passport['policySha256'])
        need(typed_equal(cold,index.state(sequence)),'old complete cold oracle and independent version index disagree at original sample cutoff')
        crosschecks.append(dict(sequence=sequence,bytes=len(prefix),sha256=sha(prefix),exactTypedStateMatch=True))
    continuity=oracle.verify_continuity(read(root/'preflight-continuity.json')['phases'],
        {'settling':settling,'admission':admission},jsonl(root/'phase-events.jsonl'),policy=policy,
        runtime_samples=parent_rows,runtime_epoch=epoch,lifecycle_journal=journal)
    services=receipt['preflightServices'];disk_services=jsonl(root/'preflight-service-events.jsonl')
    need(len(services)==len(disk_services)==360,'complete original preflight service population')
    origin=read(root/'preflight-continuity.json')['schedule']['originMonotonic']
    for n,(row,service,disk) in enumerate(zip(settling+admission,services,disk_services)):
        expected={k:v for k,v in service.items() if k not in ('diagnosticWriteCompletedMonotonic','serviceCompletedMonotonic','fullServiceSeconds')}
        need(typed_equal(expected,disk) and service['sampleId']==row['sampleId'] and service['globalIndex']==n,
             'actual preflight diagnostic/raw binding')
        start=row['monotonicSeconds'];done=service['serviceCompletedMonotonic']
        need(service['scheduledMonotonic']==origin+2*n and service['actualStartMonotonic']==start
             and 0<=start-(origin+2*n)<=.5 and service['fullServiceSeconds']==done-start<=2
             and service['phaseEventWriteCompletedMonotonic']<=service['diagnosticWriteCompletedMonotonic']<=done
             and done<=origin+(600 if n<300 else 720), 'full preflight service and fixed deadline')
    events=stage_events
    need(typed_equal(events,receipt['stageEvents']), 'actual stage event stream differs')
    preparing=[e for e in events if e['event']=='source-prefix-preparation-enter']
    prepared=[e for e in events if e['event']=='prefix-preload-complete']
    preparation_epoch=real(receipt['preparationEpochMonotonic'],'actual externally anchored preparation start')
    need(len(preparing)==len(prepared)==1 and preparing[0]['observationsActive'] is False
         and preparing[0]['externalPreparationEpochMonotonic']==preparation_epoch
         <=preparing[0]['monotonicSeconds']<=receipt['preflightCommands'][0]['startedMonotonic']
         and receipt['prefixPaddingCommands'][-1]['completedMonotonic']<=prepared[0]['monotonicSeconds']<=preflight_clock
         and parent_initialization['writeClock']['completedMonotonic']<=prepared[0]['monotonicSeconds']
         and prepared[0]['monotonicSeconds']-preparation_epoch<=900
         and prepared[0]['actualTasks']==2500, 'explicit unobserved engineering preparation boundary')
    gaps=[e for e in events if e['event']=='between-block-enter'];ends=[e for e in events if e['event']=='between-block-exit']
    need(len(gaps)==len(ends)==3,'all actual between-block stages required')
    for n,(a,b) in enumerate(zip(gaps,ends)):
        wait=receipt['blockWaits'][n]['reapedMonotonic']
        next_launch=next(e['monotonicSeconds'] for e in events if e['event']=='block-launch-enter' and e['blockIndex']==n+1)
        need(wait<=a['monotonicSeconds'] and b['monotonicSeconds']-a['monotonicSeconds']>=4
             and b['monotonicSeconds']<=next_launch
             and any(wait<=row['monotonicSeconds']<=next_launch for row in parent_rows), 'between-block actual parent coverage/gap')
    tail=next(e['monotonicSeconds'] for e in events if e['event']=='parent-cleanup-tail-enter')
    need(parent_rows[-1]['monotonicSeconds']>=tail+4
         and receipt['nestedTerminalMonotonic']-epoch<=600, 'full parent cleanup tail and internal terminal budget')
    # Exact managed task multiplicities and original parent WAIT event binding.
    listener_tree=ast.parse((repo/'experiments/ch7/mac_process_guard_v3.py').read_text())
    listener=next(n for n in listener_tree.body if isinstance(n,ast.FunctionDef) and n.name=='_read_listeners')
    argv=[ast.literal_eval(n) for n in ast.walk(listener) if isinstance(n,ast.List) and n.elts
          and isinstance(n.elts[0],ast.Constant) and n.elts[0].value=='/usr/sbin/lsof']
    need(len(argv)==1,'unique frozen source listener argv')
    kinds=Counter();commands=Counter();native_sha=sha(canonical([policy['nativeHelper']['path']]));listener_sha=sha(canonical(argv[0]))
    git_rows=receipt['preflightCommands']+receipt['prefixPaddingCommands']+[r for c in receipt['nestedBlocks'] for r in c['preflightCommands']]
    need(len(receipt['preflightCommands'])==30 and len(receipt['prefixPaddingCommands'])==2500
         and all(len(c['preflightCommands'])==30 for c in receipt['nestedBlocks']), 'exact actual source/padding Git population')
    expected_git=Counter(sha(canonical(r['command'])) for r in git_rows)
    for lease in finite:
        event=complete['events'][lease['waitSeq']-1]
        need(event['event']=='WAIT' and event['data']['waitSource']=='Popen.wait'
             and event['writer']==lease['parentIdentity'] and event['data']['identity']==lease['identity'], 'actual direct-owner terminal wait evidence')
        command=lease['commandSha256'];binary=lease['executableSha256']
        if command==native_sha:
            need(binary==policy['nativeHelper']['sha256'],'native executable bytes');kinds['native']+=1
        elif command==listener_sha:
            need(binary==passport['toolExecutableSha256']['lsof'],'listener executable bytes');kinds['listener']+=1
        elif command in expected_git:
            need(binary==passport['toolExecutableSha256']['git'],'Git executable bytes');commands[command]+=1;kinds['git']+=1
        elif lease['stageId'] in ['nested-block-'+str(i) for i in range(1,5)]:
            need(binary==passport['pythonSha256'],'actual child interpreter bytes');kinds['child']+=1
        else:
            raise ValueError('undeclared real finite task')
    need(commands==expected_git and kinds['native']==kinds['listener']==2*len(all_rows)
         and kinds['git']==2650 and kinds['child']==4 and len(finite)==4*len(all_rows)+2654<=6318,
         'complete original managed finite population')
    chain_bytes={};nonfinite_bytes=0
    for line,event in zip(journal.splitlines(keepends=True),complete['events']):
        if event['event'] in ('FINITE_REGISTER','RELEASE','WAIT'):
            chain_bytes.setdefault(event['data']['leaseId'],[]).append(len(line))
        else:
            nonfinite_bytes+=len(line)
    need(len(chain_bytes)==len(finite) and all(len(v)==3 and sum(v)<=2560 for v in chain_bytes.values())
         and nonfinite_bytes<=65536 and 6318*2560+65536+524288<16*1024**2,
         'actual event size/task/cleanup-reserve envelope')
    need(before==files(root) and all(file_sha(repo/r['path'])==r['sha256'] for r in proof), 'original source or artifacts changed during audit')
    report=dict(schema='aijade.ch7.real-nested-independent-audit.v1',
        status='ENGINEERING_REAL_NESTED_RAW_AUDIT_PASS_NOT_BACKEND_QUALIFIED', checkedAt=datetime.now(timezone.utc).isoformat(),
        sourceCommit=source,passportSha256=args.passport_sha256,auditScriptSha256=file_sha(Path(__file__)),
        inputFiles=before,sourceFiles=proof,parentStream=parent_stream,blocks=block_results,
        numbers=dict(samples=len(all_rows),idleSamples=360,parentRuntimeSamples=len(parent_rows),
            childRuntimeSamples=sum(map(len,child_rows)),nativeCaptures=len(native_ids),finiteTasks=len(finite),
            actualParentWaitZero=len(finite),journalEvents=len(complete['events']),journalBytes=len(journal),
            maximumObservedPrefixBytes=max_prefix,maximumFiniteChainBytes=max(map(sum,chain_bytes.values())),nonFiniteEventBytes=nonfinite_bytes),
        continuity=continuity,independentOldOraclePrefixCrosschecks=crosschecks,
        initializationAudits=initialization_results,ownedGuardPredicateProof=predicate_proof,
        initializationMethod='One source-pinned canonical replay retained by inner owner plus one detached initialization clone for outer owner; no per-evaluation state-return copies; all actual prefixes/tails, owner references and complete decision canonical logical bytes independently reconstructed.',
        actualNumericContextVerified=numeric_context,
        indexingMethod='Independent historical event versions; final and key-prefix exact typed comparison to unchanged full cold oracle; every raw sample cold guard and exact original prefix hash/view.',
        parentControllerTerminalEvidence='SEPARATE_IDENTITY_BOUND_LAUNCHER_REQUIRED_NOT_CHECKED_BY_THIS_SCRIPT',
        additionalChildLocalTimerFileIo=True,productionChildTimerFileWriter=False,
        unobservedPrefixPreparation=dict(explicitEngineeringPreparation=True,
            externalPreparationEpochMonotonic=preparation_epoch,
            actualControllerStageEntryMonotonic=preparing[0]['monotonicSeconds'],completedMonotonic=prepared[0]['monotonicSeconds']),
        interpretation='Finite source-frozen engineering prefix/topology envelope only; no 4800-second worst-case certificate and no backend, hardware, human or heldout qualification.',
        **{k:False for k in ('backendQualified','formalHardwareQualification','independentHumanReview','seedConstructed','heldoutComparisonComplete')})
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(status=report['status'],path=str(output),sha256=file_sha(output))),flush=True)
    return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--passport',type=Path,required=True)
    parser.add_argument('--passport-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(parser.parse_args()))
