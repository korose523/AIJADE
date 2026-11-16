#!/usr/bin/env python3
"""Offline-only v3 lifecycle/phase audit. Historical v1/v2 records are not inputs.

This module does not observe processes, run commands, infer missing measurements,
or grant hardware or held-out qualification. Every acceptance is reconstructed
from the supplied original records; claimed summaries are checked afterwards.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


EVENT_SCHEMA = 'aijade.ch7.phase-continuity-event.v1'
LIFECYCLE_SCHEMA = 'aijade.process-lifecycle-event.v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def real(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'invalid finite nonnegative clock/value: ' + label)
    return value


def integer(value, label):
    require(type(value) is int and value >= 0, 'invalid integer: ' + label)
    return value


def same(a, b, label):
    require(abs(real(a, label) - real(b, label)) <= 0.000001, 'clock/summary mismatch: ' + label)


def sample_id(row):
    observed = row.get('processObservation', {}).get('sampleId')
    value = row.get('sampleId', observed)
    require(type(value) is str and len(value) == 32 and all(c in '0123456789abcdef' for c in value),
            'missing actual sample identity')
    require(observed is None or value == observed, 'sample identity projection mismatch')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def hex_value(value, size=64):
    return type(value) is str and len(value) == size and all(c in '0123456789abcdef' for c in value)


def identity(value):
    require(type(value) is dict and set(value) == {'pid', 'createTimeMicros', 'parentPid'}, 'lifecycle identity schema')
    require(type(value['pid']) is int and value['pid'] > 1 and type(value['createTimeMicros']) is int
            and value['createTimeMicros'] > 0 and type(value['parentPid']) is int and value['parentPid'] > 0,
            'lifecycle identity values')
    return value['pid'], value['createTimeMicros']


def node_identity(node):
    require(type(node.get('createTimeMicros')) is int and node['createTimeMicros'] > 0,
            'native exact creation identity missing')
    return node['pid'], node['createTimeMicros']


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate lifecycle JSON key')
        result[key] = value
    return result


def _journal_bytes(value):
    raw = value if type(value) is bytes else Path(value).read_bytes()
    require(type(raw) is bytes and 0 < len(raw) <= 16 * 1024**2 and raw.endswith(b'\n'),
            'lifecycle journal missing/truncated/over cap')
    return raw


def _replay(raw, source_commit, policy_sha256):
    """Independent event/state reconstruction; never call the producer replayer."""
    require(hex_value(source_commit, 40) and hex_value(policy_sha256), 'lifecycle expected source identity')
    events = []; leases = {}; scopes = {}; discovered = {}; previous = '0' * 64; last = -1
    context = None
    for line in raw.splitlines():
        event = json.loads(line, object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite lifecycle JSON')))
        require(type(event) is dict and set(event) == {'schema', 'seq', 'event', 'monotonicSeconds', 'runId',
                'writer', 'sourceCommit', 'policySha256', 'data', 'previousSha256', 'sha256'}, 'lifecycle event schema')
        require(event['schema'] == LIFECYCLE_SCHEMA and type(event['seq']) is int
                and event['seq'] == len(events) + 1 and event['previousSha256'] == previous,
                'lifecycle sequence/hash chain omitted/reordered')
        require(hex_value(event['sha256']) and event['sha256'] == hashlib.sha256(canonical({k:v for k,v in event.items() if k != 'sha256'})).hexdigest(),
                'lifecycle event bytes changed')
        now = real(event['monotonicSeconds'], 'lifecycle event clock')
        require(now >= last, 'lifecycle event chronology reversed')
        require(event['sourceCommit'] == source_commit and event['policySha256'] == policy_sha256
                and hex_value(event['runId'], 32), 'lifecycle frozen source/policy/run mismatch')
        require(context is None or event['runId'] == context, 'lifecycle run changed')
        context = event['runId']
        writer = identity(event['writer']); data = event['data']; kind = event['event']
        require(type(data) is dict, 'lifecycle data schema')
        writer_leases = [v for v in leases.values() if identity(v['identity']) == writer]
        authorized_writer = any(v['role'] == 'controller' or (v['releaseSeq'] is not None and v['waitSeq'] is None)
                                for v in writer_leases)
        if kind in ('CONTROLLER_REGISTER', 'FINITE_REGISTER'):
            key = data['leaseId']; ident = identity(data['identity'])
            require(hex_value(key, 32) and key not in leases and not any(identity(v['identity']) == ident for v in leases.values()),
                    'lifecycle duplicate lease/identity')
            require(type(data.get('stageId')) is str and data['stageId'] and hex_value(data.get('commandSha256'))
                    and hex_value(data.get('executableSha256')) and real(data.get('readyMonotonic'), 'identity ready') <= now,
                    'source-bound identity-ready launch witness missing')
            if kind == 'CONTROLLER_REGISTER':
                require(not events and data.get('role') == 'controller' and data['identity'] == event['writer']
                        and data.get('parentIdentity') is None, 'only initial self controller registration permitted')
            else:
                require(data.get('role') == 'finite' and authorized_writer and data.get('parentIdentity') == event['writer']
                        and data['identity']['parentPid'] == event['writer']['pid'] and hex_value(data.get('shimSha256')),
                        'finite task lacks exact authorized direct-parent/ready shim witness')
            leases[key] = dict(data, registerSeq=event['seq'], registerMonotonic=now,
                               releaseSeq=None, waitSeq=None, exitCode=None, absence=None)
        else:
            require(authorized_writer, 'unleased/terminated writer supplied lifecycle evidence')
            if kind == 'RELEASE':
                lease = leases[data['leaseId']]
                require(lease['role'] == 'finite' and lease['parentIdentity'] == event['writer']
                        and lease['releaseSeq'] is None and lease['waitSeq'] is None, 'invalid finite ready release')
                lease['releaseSeq'] = event['seq']
                lease['releaseMonotonic'] = now
            elif kind == 'WAIT':
                lease = leases[data['leaseId']]
                require(lease['role'] == 'finite' and lease['parentIdentity'] == event['writer']
                        and lease['identity'] == data.get('identity') and lease['releaseSeq'] is not None
                        and lease['waitSeq'] is None and type(data.get('exitCode')) is int
                        and data.get('waitSource') == 'Popen.wait', 'unbound finite terminal wait')
                reaped = real(data.get('reapedMonotonic'), 'actual wait completion')
                released = events[lease['releaseSeq'] - 1]['monotonicSeconds']
                require(released <= reaped <= now, 'wait predates actual release')
                lease.update(waitSeq=event['seq'], exitCode=data['exitCode'], reapedMonotonic=reaped)
                lease['absence'] = dict(witnessKind='PARENT_WAIT_REAPED', identity=lease['identity'],
                    parentIdentity=lease['parentIdentity'], eventSeq=event['seq'], reapedMonotonic=reaped,
                    exitCode=data['exitCode'])
                lease['absenceWitnessKind'] = 'PARENT_WAIT_REAPED'
            elif kind == 'DISCOVER':
                key = identity(data['identity'])
                chain = data.get('ancestry')
                require(type(chain) is list and len(chain) >= 2, 'discovery source-bound ancestry missing')
                keys = [identity(v) for v in chain]
                require(chain[0] == data['identity'] and chain[-1] == event['writer']
                        and len(keys) == len(set(keys)) and len({v['pid'] for v in chain}) == len(chain)
                        and all(child['parentPid'] == parent['pid'] for child, parent in zip(chain, chain[1:])),
                        'discovery ancestry identity/order/parent mismatch')
                scope = scopes.get(data.get('scopeId'))
                require(scope is not None and scope['controllerIdentity'] == event['writer'] and scope['closeSeq'] is None,
                        'discovery source scope absent/closed/wrong writer')
                require(hex_value(data.get('sampleId'), 32) and data.get('phase') in ('before','after')
                        and hex_value(data.get('nativeStdoutSha256')), 'discovery source native witness missing')
                require(real(data.get('graphStartedMonotonic'), 'discovery graph start')
                        <= real(data.get('graphCompletedMonotonic'), 'discovery graph completion') <= now,
                        'discovery source native chronology')
                discovered.setdefault(key, dict(data, eventSeq=event['seq']))
            elif kind in ('ABSENCE', 'DISCOVER_ABSENCE'):
                key = identity(data['identity'])
                require(hex_value(data.get('sampleId'), 32) and data.get('phase') in ('before', 'after')
                        and hex_value(data.get('nativeStdoutSha256')), 'absence native witness missing')
                real(data.get('graphStartedMonotonic'), 'absence graph clock')
                found = [v for v in leases.values() if identity(v['identity']) == key]
                require(found or key in discovered, 'absence identity never registered or discovered')
                require((kind == 'ABSENCE' and bool(found)) or (kind == 'DISCOVER_ABSENCE' and key in discovered and not found),
                        'managed wait absence and discovered-only absence cannot be substituted')
                for lease in found:
                    require(lease['role'] == 'finite' and lease['waitSeq'] is not None,
                            'absence cannot retire persistent root or replace actual wait')
                    lease['absence'] = dict(data, eventSeq=event['seq'], witnessKind='COMPLETE_NATIVE_ABSENCE')
                    lease['absenceWitnessKind'] = 'COMPLETE_NATIVE_ABSENCE'
                if key in discovered:
                    discovered[key]['absence'] = dict(data, eventSeq=event['seq'], witnessKind='COMPLETE_NATIVE_ABSENCE')
                    if kind == 'DISCOVER_ABSENCE':
                        discovered[key]['exitStatus'] = 'UNKNOWN'
            elif kind == 'SCOPE_OPEN':
                key = data['scopeId']
                require(hex_value(key, 32) and key not in scopes and data.get('controllerIdentity') == event['writer'],
                        'scope does not bind exact local self')
                parent = data.get('parentLeaseId')
                if parent is not None:
                    require(parent in leases and leases[parent]['role'] == 'finite' and leases[parent]['identity'] == event['writer']
                            and leases[parent]['releaseSeq'] is not None and leases[parent]['waitSeq'] is None,
                            'nested scope has no actual live parent finite lease')
                else:
                    require(any(v['role'] == 'controller' for v in writer_leases), 'root scope lacks controller lease')
                require(type(data.get('stageId')) is str and data['stageId'], 'scope active stage missing')
                scopes[key] = dict(data, openSeq=event['seq'], closeSeq=None)
            elif kind == 'SCOPE_CLOSE':
                scope = scopes[data['scopeId']]
                require(scope['controllerIdentity'] == event['writer'] and scope['closeSeq'] is None, 'scope closed by wrong writer/twice')
                scope['closeSeq'] = event['seq']
            else:
                raise ValueError('unknown lifecycle event: ' + str(kind))
        events.append(event); previous = event['sha256']; last = now
    return dict(events=events, leases=leases, scopes=scopes, discovered=discovered, runId=context)


def _raw_frames(observation, policy):
    """Recover native node populations independently of the claimed projection."""
    from mac_process_guard_v2 import parse_native_evidence
    result = []
    for phase in ('before', 'after'):
        frame = observation['evidence'][phase]; graph = frame['processGraph']
        require(frame.get('errors') == [] and graph.get('errors') == [], 'incomplete native frame cannot prove closure/absence')
        nodes, collector = parse_native_evidence(policy, graph['nativeCensus'])
        require(nodes == graph.get('nodes'), 'native derived process population changed')
        start = real(frame.get('graphStartedMonotonic'), 'graph actual start')
        end = real(frame.get('graphCompletedMonotonic'), 'graph actual completion')
        require(observation['startedMonotonic'] <= start <= end <= observation['finishedMonotonic'], 'native graph clock envelope')
        require(len({v['pid'] for v in nodes}) == len(nodes), 'native duplicate PID')
        result.append(dict(phase=phase, nodes=nodes, rows=frame['ownedProcesses'],
                           collector=collector, nativeSha256=graph['nativeCensus']['stdoutSha256'],
                           graphStartedMonotonic=start, graphCompletedMonotonic=end))
    return result


def verify_lifecycle(journal, samples, *, source_commit, policy_sha256, policy,
                     controller=None, require_cleanup=True, scope_id=None,
                     ancestry_samples=None, ancestry_journal=None):
    """Replay complete source-bound journal, sample prefixes, membership and exit proof.

    ``samples`` are original outer telemetry rows, not scorer summaries. The
    caller supplies the archived journal bytes/path explicitly, so relocation
    never depends on a formerly live absolute journal path in a sample.
    """
    raw = _journal_bytes(journal); state = _replay(raw, source_commit, policy_sha256)
    expected_shim = policy.get('lifecycle', {}).get('execShimSha256')
    require(hex_value(expected_shim), 'frozen identity-ready shim policy missing')
    require(all(v.get('shimSha256') == expected_shim for v in state['leases'].values() if v['role'] == 'finite'),
            'finite launch shim differs from frozen source-bound policy')
    require(type(samples) is list and samples, 'lifecycle audit needs complete original observations')
    first = state['events'][0]
    root = first['data']['identity'] if scope_id is None else state['scopes'][scope_id]['controllerIdentity']
    local_key = identity(root)
    included_keys = {local_key}
    while True:
        new = {identity(v['identity']) for v in state['leases'].values()
               if v.get('parentIdentity') is not None and identity(v['parentIdentity']) in included_keys}
        if new <= included_keys: break
        included_keys.update(new)
    if controller is not None:
        micros = controller.get('createTimeMicros')
        if micros is None:
            micros = round(real(controller.get('createTime'), 'controller creation') * 1000000)
        require((controller.get('pid'), micros) == identity(root), 'journal root differs from bound controller receipt')
    frames = {}; sample_ids = set(); seen_prefix_bytes = -1; peak = 0; observations = []; observed_owned = set()
    context_observations = {}
    context_rows = {}
    prior_sample_start = -1
    for outer in samples:
        observation = outer.get('processObservation')
        require(type(observation) is dict, 'missing original v3 observation')
        sid = sample_id(outer)
        require(sid not in sample_ids, 'duplicate lifecycle sample identity')
        sample_ids.add(sid)
        actual_start = real(outer.get('monotonicSeconds'), 'lifecycle actual sample start')
        require(actual_start > prior_sample_start, 'lifecycle original sample chronology reversed/duplicated')
        prior_sample_start = actual_start
        _validate_sample(outer, policy, raw)
        captured = _raw_frames(observation, policy)
        view = observation.get('lifecycle', {})
        require(view.get('schema') == 'aijade.process-lifecycle-view.v1', 'missing lifecycle view')
        size = integer(view.get('journalBytes'), 'journal prefix bytes')
        require(0 < size <= len(raw) and size >= seen_prefix_bytes and raw[:size].endswith(b'\n'),
                'journal prefix omitted/reversed/truncated')
        prefix = raw[:size]
        require(hashlib.sha256(prefix).hexdigest() == view.get('journalSha256'), 'actual journal prefix differs')
        local = _replay(prefix, source_commit, policy_sha256)
        require(view.get('lastSequence') == len(local['events']) and view.get('runId') == local['runId'], 'view journal context differs')
        scope = local['scopes'].get(view.get('scopeId'))
        require(scope is not None and scope['closeSeq'] is None and scope['controllerIdentity'] == view.get('controllerIdentity'),
                'sample local persistent scope missing/closed/changed')
        require(scope_id is None or view['scopeId'] == scope_id, 'sample belongs to another local lifecycle scope')
        refs = sorted({node_identity(node) for frame in captured for node in frame['nodes']})
        require(view.get('referencedIdentities') == [list(x) for x in refs], 'view native identity coverage differs')
        projected = [v for v in local['leases'].values() if v['absence'] is None or identity(v['identity']) in refs]
        require(view.get('leases') == projected, 'view omitted/changed active lifecycle leases')
        require(view.get('controllers') == [v['leaseId'] for v in projected if v['identity'] == view['controllerIdentity']],
                'view local controller lease projection differs')
        known = {identity(v['identity']):v for v in local['leases'].values()}
        roots = observation.get('ownedRoots')
        require(type(roots) is list and len(roots) == 1, 'runtime must have one exact local persistent root')
        wanted_root = (roots[0]['pid'], round(real(roots[0].get('createTime'), 'sample root creation') * 1000000))
        require(wanted_root == identity(view['controllerIdentity']), 'sample persistent root differs from active scope')
        for frame in captured:
            by_pid = {n['pid']:n for n in frame['nodes']}
            require(wanted_root[0] in by_pid and node_identity(by_pid[wanted_root[0]]) == wanted_root,
                    'required persistent controller missing/reused')
            require(by_pid[wanted_root[0]]['parentPid'] == view['controllerIdentity']['parentPid'], 'persistent controller parent changed')
            members = {wanted_root[0]}
            while True:
                added = {n['pid'] for n in frame['nodes'] if n['parentPid'] in members and n['pid'] not in members}
                if not added: break
                members.update(added)
            observed_owned.update(node_identity(by_pid[pid]) for pid in members)
            family = {wanted_root}
            while True:
                added = {key for key, lease in known.items() if lease.get('parentIdentity') is not None
                         and identity(lease['parentIdentity']) in family}
                if added <= family: break
                family.update(added)
            present_identities = {node_identity(n) for n in frame['nodes']}
            for key in family:
                lease = known[key]
                if lease['role'] == 'finite' and lease.get('releaseMonotonic', float('inf')) <= frame['graphStartedMonotonic'] and key not in present_identities:
                    require(key[0] not in by_pid or lease['absence'] is not None,
                            'active registered PID reused without its own terminal absence')
                    require(lease['waitSeq'] is not None and lease['reapedMonotonic'] <= frame['graphCompletedMonotonic'],
                            'absent managed identity has no actual terminal wait by this frame')
            rows = frame['rows']
            require(type(rows) is list and len(rows) == len(members) and {r['pid'] for r in rows} == members,
                    'whole-owned RSS membership unknown')
            for node in frame['nodes']:
                key = node_identity(node)
                if key in known:
                    require(node['parentPid'] == known[key]['identity']['parentPid'], 'actual registered process parent changed')
                    lease = known[key]
                    if lease['waitSeq'] is not None:
                        require(frame['graphStartedMonotonic'] < lease['reapedMonotonic'],
                                'reaped managed identity is still present in a later raw census')
                for old_key, lease in known.items():
                    if old_key[0] == node['pid'] and old_key != key and lease['absence'] is None:
                        raise ValueError('active registered PID reused without its own terminal absence')
                if key in state['discovered']:
                    require(node['parentPid'] == state['discovered'][key]['identity']['parentPid'], 'actual discovered process parent changed')
            for row in rows:
                key = (row['pid'], round(real(row.get('createTime'), 'RSS creation') * 1000000))
                require(node_identity(by_pid[row['pid']]) == key and row['parentPid'] == by_pid[row['pid']]['parentPid']
                        and type(row.get('rssBytes')) is int and row['rssBytes'] >= 0, 'present owned RSS unknown/identity mismatch')
                collector = frame.get('collector')
                native_self = collector is not None and key == (collector['pid'], collector['createTimeMicros'])
                require(key in known or native_self or key in state['discovered'],
                        'unrecorded discovered descendant lacks append-only ancestry evidence')
                if key in known and known[key]['role'] == 'finite':
                    require(known[key]['releaseSeq'] is not None, 'finite process observed before identity-ready release')
            frames[(sid, frame['phase'])] = frame
        require(observation.get('ownedProcesses') == captured[-1]['rows'], 'claimed owned process list differs from raw after')
        total = sum(r['rssBytes'] for r in captured[-1]['rows'])
        require(observation.get('ownedRssBytes') == total and outer.get('rssBytes') == total, 'whole-owned RSS sum differs')
        peak = max(peak, total); seen_prefix_bytes = size; observations.append((observation, captured))
        context_observations[sid] = observation
        context_rows[sid] = canonical(outer)
    context_raw = raw if ancestry_journal is None else _journal_bytes(ancestry_journal)
    require(context_raw.startswith(raw), 'ancestry journal does not preserve exact principal cutoff prefix')
    context_state = _replay(context_raw, source_commit, policy_sha256)
    require(context_state['runId'] == state['runId'], 'ancestry journal belongs to another run')
    require(ancestry_samples is None or type(ancestry_samples) is list, 'ancestry sample population schema')
    for outer in ancestry_samples or []:
        sid = sample_id(outer); observation = outer.get('processObservation')
        if sid in context_observations:
            require(canonical(outer) == context_rows[sid], 'conflicting original ancestry sample identity')
            continue
        _validate_sample(outer, policy, context_raw)
        captured = _raw_frames(observation, policy)
        for frame in captured:
            frames[(sid,frame['phase'])] = frame
        context_observations[sid] = observation
        context_rows[sid] = canonical(outer)
    # Every principal discovery is independently bound to its actual raw parent
    # chain BEFORE any local-scope exclusion. A plausible claimed chain cannot
    # shrink cleanup responsibility. Supplemental raw rows supply evidence only,
    # never the principal scope's RSS/count or later cleanup state.
    ancestry_keys = {}
    for event in state['events']:
        if event['event'] != 'DISCOVER': continue
        data = event['data']; key = identity(data['identity'])
        frame = frames.get((data['sampleId'],data['phase']))
        original = context_observations.get(data['sampleId'])
        require(frame is not None and original is not None and frame['nativeSha256'] == data['nativeStdoutSha256'],
                'discovery lacks original complete native ancestry frame')
        require(original.get('lifecycle',{}).get('scopeId') == data['scopeId']
                and original['lifecycle'].get('controllerIdentity') == event['writer'],
                'discovery source sample scope/writer mismatch')
        same(data['graphStartedMonotonic'],frame['graphStartedMonotonic'],'discovery original graph start')
        same(data['graphCompletedMonotonic'],frame['graphCompletedMonotonic'],'discovery original graph completion')
        require(event['monotonicSeconds'] >= frame['graphCompletedMonotonic'], 'discovery journal predates raw frame')
        by_pid = {n['pid']:n for n in frame['nodes']}
        require(key[0] in by_pid and node_identity(by_pid[key[0]]) == key,
                'discovery target missing/reused in original native frame')
        chain = []; current = by_pid[key[0]]; visited = set()
        while True:
            current_key = node_identity(current)
            require(current_key not in visited, 'raw discovery ancestry cycle')
            visited.add(current_key)
            chain.append(dict(pid=current['pid'],createTimeMicros=current['createTimeMicros'],parentPid=current['parentPid']))
            if current_key == identity(event['writer']): break
            parent = by_pid.get(current['parentPid'])
            require(parent is not None and parent['createTimeMicros'] <= current['createTimeMicros'],
                    'raw discovery ancestry incomplete/reused parent')
            current = parent
        require(chain == data['ancestry'], 'claimed discovery ancestry differs from original native parent chain')
        ancestry_keys.setdefault(key,set()).update(identity(v) for v in chain)
    responsible_discovered = {key for key, keys in ancestry_keys.items()
                              if scope_id is None or bool(keys & included_keys)}
    for event in state['events']:
        if event['event'] in ('ABSENCE', 'DISCOVER_ABSENCE'):
            data = event['data']; frame = frames.get((data['sampleId'], data['phase']))
            key = identity(data['identity'])
            if scope_id is not None and (key == local_key or (key not in included_keys and key not in responsible_discovered)):
                continue  # The enclosing sequence independently verifies its complete global raw population.
            require(frame is not None and frame['nativeSha256'] == data['nativeStdoutSha256'], 'absence lacks bound original complete native frame')
            require(key not in {node_identity(n) for n in frame['nodes']}, 'absence identity is present in raw census')
            same(data.get('graphStartedMonotonic'), frame['graphStartedMonotonic'], 'absence original graph start')
            require(event['monotonicSeconds'] >= frame['graphCompletedMonotonic'], 'absence journal predates actual frame')
            if event['event'] == 'DISCOVER_ABSENCE':
                same(data.get('graphCompletedMonotonic'), frame['graphCompletedMonotonic'], 'discovered absence graph completion')
                require(key in responsible_discovered, 'discovered absence has no validated owned ancestry')
                require(not any(key in {node_identity(n) for n in f['nodes']}
                                and f['graphStartedMonotonic'] > frame['graphCompletedMonotonic']
                                for f in frames.values()), 'discovered old identity reappeared after confirmed absence')
            for lease in state['leases'].values():
                if identity(lease['identity']) == key:
                    waited = state['events'][lease['waitSeq'] - 1]
                    require(frame['graphStartedMonotonic'] >= waited['data']['reapedMonotonic'], 'absence frame predates actual finite wait')
        elif event['event'] == 'DISCOVER':
            key = identity(event['data']['identity'])
            require(key in ancestry_keys, 'discovery has no validated source-bound raw ancestry')
    finite = [v for v in state['leases'].values() if v['role'] == 'finite'
              and (scope_id is None or identity(v['identity']) in included_keys - {local_key})]
    discovered_only = {key:v for key,v in state['discovered'].items()
                       if key not in {identity(v['identity']) for v in state['leases'].values()}
                       and key in responsible_discovered}
    if require_cleanup:
        require(all(v['waitSeq'] is not None and v['exitCode'] == 0 and v['absence'] is not None for v in finite),
                'finite task unresolved/nonzero/unconfirmed absent at cleanup')
        require(all(s['closeSeq'] is not None for s in state['scopes'].values()
                    if scope_id is None or identity(s['controllerIdentity']) in included_keys),
                'persistent scope not closed after monitor cleanup')
        require(all(v.get('absence') is not None and v.get('exitStatus') == 'UNKNOWN' for v in discovered_only.values()),
                'discovered-only descendant cleanup absence unconfirmed; no exit status may be inferred')
    return dict(status='LIFECYCLE_RAW_AUDIT_PASS', journalBytes=len(raw), journalSha256=hashlib.sha256(raw).hexdigest(),
                events=len(state['events']), observations=len(samples), finiteLeases=len(finite),
                finiteWaitZero=sum(v['exitCode'] == 0 for v in finite), peakObservedOwnedRssBytes=peak,
                discoveredOnlyConfirmedAbsentUnknownExit=len(discovered_only), scopeId=scope_id,
                cleanupAccepted=bool(require_cleanup), independentHumanReview=False, formalHardwareQualification=False)


def _validate_sample(row, policy, lifecycle_journal=None):
    # Lazy import: offline callers never trigger observer/OS collection. The
    # versioned guard replays native/API/listener/identity bytes, not status alone.
    import mac_process_guard_v3 as guard
    observation = row.get('processObservation')
    require(type(observation) is dict and observation.get('schemaVersion') == 3,
            'v3 original observation required')
    decision = guard.validate_observation(policy, observation, lifecycle_journal=lifecycle_journal)
    require(decision.get('status') == 'PASS', 'raw v3 process evidence adverse')
    require(type(decision.get('ownedRssBytes')) is int and decision['ownedRssBytes'] >= 0,
            'whole-owned RSS unknown')
    require(row.get('rssBytes') == decision['ownedRssBytes'], 'sample RSS differs from independent replay')
    require(real(row.get('monotonicSeconds'), 'sample clock') <= real(observation.get('startedMonotonic'), 'observer start')
            <= real(observation.get('finishedMonotonic'), 'observer finish')
            <= real(row.get('observationCompletedMonotonic'), 'sample completion'),
            'raw observer clock outside actual sample envelope')
    require(row['observationCompletedMonotonic'] - row['monotonicSeconds'] <= 2.5,
            'complete v3 observation including postprocessing exceeds2.5seconds')
    return decision


def verify_continuity(phases, streams, events, *, policy, runtime_samples=None, runtime_epoch=None,
                      lifecycle_journal=None):
    """Rebuild accepted fixed idle phases and actual global timing from raw rows.

    ``phases`` is run_preflight(...)["phases"], ``streams`` maps each phase to
    its original ordered JSONL rows and ``events`` is the complete event stream.
    If runtime_samples is supplied it must be nonempty; the runtime handoff is
    checked against its first *actual* observation, never a handoff placeholder.
    """
    require(type(phases) is dict and set(phases) in ({'admission'}, {'settling', 'admission'}),
            'unexpected fixed phase population')
    order = ['settling', 'admission'] if 'settling' in phases else ['admission']
    require(type(streams) is dict and set(streams) == set(phases), 'phase raw population mismatch')
    require(type(events) is list and events, 'missing actual phase events')
    written = {}; enter = {}; exit_events = {}; boundaries = []
    previous_event = -1
    for index, event in enumerate(events):
        require(type(event) is dict and event.get('schema') == EVENT_SCHEMA,
                'unknown phase event schema')
        require(event.get('eventIndex') == index, 'phase event index omitted/reordered/duplicated')
        stamp = real(event.get('monotonicSeconds'), 'event clock')
        require(stamp >= previous_event, 'phase event chronology reversed')
        previous_event = stamp
        kind = event.get('event')
        if kind == 'sample-written':
            key = (event.get('phase'), integer(event.get('globalIndex'), 'event global index'))
            require(key not in written, 'duplicate sample-written event')
            written[key] = event
            same(stamp, event.get('writerCompletedMonotonic'), 'writer completion event')
        elif kind == 'phase-enter':
            name = event.get('phase')
            require(name == order[0] and name not in enter and index == 0,
                    'unexpected or duplicate phase entry')
            same(stamp, event.get('actualStartMonotonic'), 'actual phase entry')
            enter[name] = event
        elif kind == 'phase-boundary':
            require(order == ['settling', 'admission'] and not boundaries,
                    'unexpected phase boundary')
            require(event.get('fromPhase') == 'settling' and event.get('toPhase') == 'admission',
                    'wrong phase boundary direction')
            same(stamp, event.get('actualEntryMonotonic'), 'actual phase switch')
            phase_exit = real(event.get('actualExitMonotonic'), 'actual phase exit')
            require(0 <= stamp - phase_exit <= 3, 'actual phase exit/entry gap exceeds3')
            boundaries.append(event)
        elif kind == 'phase-exit':
            name = event.get('phase')
            require(name == order[-1] and name not in exit_events and index == len(events) - 1,
                    'unexpected or duplicate terminal phase exit')
            same(stamp, event.get('actualEndMonotonic'), 'actual final phase exit')
            exit_events[name] = event
        else:
            raise ValueError('adverse or unknown phase event: ' + str(kind))
    require(set(enter) == {order[0]} and set(exit_events) == {order[-1]}, 'missing phase endpoints')
    require(len(boundaries) == len(order) - 1, 'missing phase boundary event')
    global_rows = []; identities = set(); result = {}; offset = 0
    origin = real(phases[order[0]]['phaseClock'].get('startMonotonic'), 'global phase origin')
    for position, name in enumerate(order):
        summary = phases[name]; clock = summary.get('phaseClock', {})
        requested = 600 if name == 'settling' else 120
        count = requested // 2
        expected_status = 'ADMITTED' if name == 'admission' else 'FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION'
        require(summary.get('status') == expected_status, 'fixed phase not accepted')
        require(clock.get('requestedSeconds') == requested and clock.get('intervalReset') is False,
                'phase duration/reset contract changed')
        start = real(clock.get('startMonotonic'), 'phase start')
        end = real(clock.get('endMonotonic'), 'phase end')
        require(requested <= end - start <= requested + 3, 'fixed phase shortened/extended')
        same(summary.get('elapsedSeconds'), end - start, 'phase elapsed')
        if position == 0:
            same(start, enter[name]['actualStartMonotonic'], 'entry/receipt binding')
        if name == order[-1]:
            same(end, exit_events[name]['actualEndMonotonic'], 'exit/receipt binding')
        if name == 'settling':
            same(end, boundaries[0]['actualExitMonotonic'], 'settling boundary binding')
        elif position:
            same(start, boundaries[0]['actualEntryMonotonic'], 'admission boundary binding')
            gap = start - phases['settling']['phaseClock']['endMonotonic']
            require(0 <= gap <= 3, 'settling/admission phase boundary gap exceeds3')
        rows = streams[name]
        require(type(rows) is list and len(rows) == count, 'fixed scheduled sample population incomplete/extra')
        available = []; swap = []; starts = []
        for local_index, row in enumerate(rows):
            require(type(row) is dict and row.get('phase') == name, 'raw phase label changed')
            require(row.get('streamValidationStatus') == 'PASS' and 'streamValidationError' not in row,
                    'recorded streaming validation was not accepted')
            index = offset + local_index
            require(row.get('globalIndex') == index, 'global sample index omitted/reordered/duplicated')
            identity = sample_id(row)
            require(identity not in identities, 'duplicated original sample identity')
            identities.add(identity)
            stamp = real(row.get('monotonicSeconds'), 'actual sample start')
            completed = real(row.get('observationCompletedMonotonic'), 'actual observation completion')
            validating = real(row.get('validatorStartedMonotonic'), 'actual validator start')
            validated = real(row.get('validatorCompletedMonotonic'), 'actual validator completion')
            writing = real(row.get('writerStartedMonotonic'), 'actual writer start')
            event = written.get((name, index))
            require(event is not None and event.get('sampleId') == identity, 'raw sample missing exact writer completion event')
            written_at = real(event.get('writerCompletedMonotonic'), 'actual writer completion')
            for key in ('writerStartedMonotonic', 'validatorStartedMonotonic', 'validatorCompletedMonotonic'):
                same(event.get(key), row.get(key), 'raw/writer event ' + key)
            require(start <= stamp <= completed <= validating <= validated <= writing <= written_at <= start + requested,
                    'sample/validation/write unfinished outside fixed deadline or chronology')
            require(written_at <= end, 'sample write after phase end')
            same(row.get('elapsedSeconds'), stamp - start, 'sample local elapsed')
            same(row.get('observationDurationSeconds'), completed - stamp, 'observation actual duration')
            same(row.get('scheduledSeconds'), local_index * 2, 'local scheduled slot')
            same(row.get('globalScheduledMonotonic'), origin + index * 2, 'global fixed scheduled slot')
            require(stamp >= row['globalScheduledMonotonic'], 'actual sample backdated before global schedule')
            require(0 <= stamp - row['globalScheduledMonotonic'] <= 3, 'global scheduled slot missed')
            decision = _validate_sample(row, policy, lifecycle_journal)
            require(not decision.get('ownedProcesses') and decision['ownedRssBytes'] == 0,
                    'idle phase contains research-owned process')
            available.append(integer(row.get('availableBytes'), 'available memory'))
            swap.append(integer(row.get('swapUsedBytes'), 'actual swap used'))
            if name == 'admission':
                require(available[-1] >= 4 * 1024**3, 'admission available memory below4GiB')
            starts.append(stamp)
            global_rows.append((stamp, written_at, name, identity, index))
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        require(all(0 < gap <= 3 for gap in gaps), 'within-phase actual sample gap exceeds3')
        require(starts[0] - start <= 3 and end - starts[-1] <= 3, 'phase endpoint uncovered')
        if name == 'admission':
            require(max(swap) - min(swap) <= 64 * 1024**2, 'phase swap range exceeds64MiB')
        derived = dict(samples=len(rows), maximumGapSeconds=max(gaps, default=0),
                       firstElapsedSeconds=starts[0] - start, lastElapsedSeconds=starts[-1] - start,
                       coverageComplete=True)
        require(summary.get('samples') == len(rows), 'phase summary sample population mismatch')
        require(summary.get('validatedSamples') == len(rows) and summary.get('expectedSamples') == count,
                'phase streaming validation population differs')
        coverage = summary.get('coverage', {})
        require(set(coverage) == set(derived), 'phase coverage schema mismatch')
        for key, value in derived.items():
            if type(value) is bool:
                require(coverage[key] is value, 'phase coverage complete mismatch')
            else:
                same(coverage[key], value, 'coverage ' + key)
        require(summary.get('minimumAvailableBytes') == min(available) and summary.get('swapRangeBytes') == max(swap) - min(swap),
                'phase resource summary differs from complete raw population')
        result[name] = dict(derived, minimumAvailableBytes=min(available), swapRangeBytes=max(swap) - min(swap))
        offset += count
    require(len(written) == len(global_rows), 'extra/unbound sample-written event')
    global_gaps = []
    for before, after in zip(global_rows, global_rows[1:]):
        gap = after[0] - before[0]
        require(0 < gap <= 3, 'cross-phase actual sample start gap exceeds3')
        require(before[1] <= after[0], 'next sample begins before prior validation/write completes')
        global_gaps.append(gap)
    handoff = None
    if runtime_samples is not None:
        require(type(runtime_samples) is list and runtime_samples, 'runtime handoff lacks actual first sample')
        epoch = real(runtime_epoch, 'actual runtime epoch')
        end = phases['admission']['phaseClock']['endMonotonic']
        require(0 <= epoch - end <= 3, 'admission/runtime phase boundary gap exceeds3')
        first = runtime_samples[0]
        first_at = real(first.get('monotonicSeconds'), 'actual first runtime sample')
        require(first_at >= epoch and 0 < first_at - global_rows[-1][0] <= 3,
                'admission/runtime actual sample gap exceeds3')
        require(sample_id(first) not in identities, 'runtime duplicates idle observation')
        _validate_sample(first, policy, lifecycle_journal)
        handoff = dict(phaseBoundaryGapSeconds=epoch - end,
                       actualSampleStartGapSeconds=first_at - global_rows[-1][0])
    return dict(status='CONTINUITY_RAW_AUDIT_PASS', phases=result, samples=len(global_rows),
                maximumGlobalSampleGapSeconds=max(global_gaps, default=0), runtimeHandoff=handoff,
                independentHumanReview=False, formalHardwareQualification=False)
