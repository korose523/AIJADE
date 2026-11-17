#!/usr/bin/env python3
"""Accept only complete finite sequences, with per-block raw closure and independent counts.

This is an offline audit, not an execution entry point. It never constructs cases,
calls a provider, starts a renderer or edits primary observations. No favorable C2
outcome is an acceptance condition. Missing/unknown observations are not zeros.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

from comparison_manifest import FIELDS, REGISTRY_SHA256, window_registry

PLAN_SHA256 = 'ca53a7df038b413bbefc6ca56195e16183620777d0391893b6419b21975bdfa2'
CENSUS_PLAN_SHA256 = 'd8c5ed7cc58267571c5bdb1ee1cd1043eba9c6a3136f340677d69087575038b5'
LIFECYCLE_PLAN_SHA256 = '1599aa06b81a4a8ea97a36e70f5a76aec5b70eb5c43f8e687c5addfaf5c35c72'
LIFECYCLE_KIND = 'mac-lifecycle-observed-idle-daemon-v3'
LIFECYCLE_BUILD_FREEZE_PATH = 'experiments/ch7/mac-lifecycle-2026-11-17/frozen-build.json'
SHARED = ('implementationCommit', 'repositoryCommit', 'buildFreezeCommit',
          'buildFreezePath', 'inputPublicationCommit', 'dataPublicationManifestPath',
          'dataPublicationManifestSha256', 'addedDataPaths', 'processPolicyPath', 'processPolicySha256',
          'observerModuleSha256')
EMPTY_DISPOSITIONS = ('inFlightCaseIds', 'unknownCaseIds', 'unattemptedCaseIds')
BINDING_FIELDS = ('implementationCommit', 'repositoryCommit', 'inputPublicationCommit',
                  'dataPublicationManifestPath', 'dataPublicationManifestSha256', 'addedDataPaths')
BACKEND_FIELDS = ('selectionSha256', 'modelSha256', 'buildManifestSha256', 'benchSha256',
                  'earlierSourceFreezeSha256', 'binaries', 'rendererSources', 'realGodotSha256',
                  'godotWrapperSha256', 'sandboxProfileSha256', 'databaseContainer')


def require(value, message):
    if not value:
        raise ValueError(message)


def integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, 'invalid integer: ' + name)
    return value


def real(value, name, minimum=0):
    require(type(value) in (int, float) and math.isfinite(value) and value >= minimum,
            'invalid finite number: ' + name)
    return value


def boolean(value, name):
    require(type(value) is bool, 'invalid boolean: ' + name)
    return value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(root, name):
    return json.loads((root / name).read_text())


def lines(root, name):
    body = (root / name).read_text().splitlines()
    require(body and all(line.strip() for line in body), 'empty/incomplete JSONL: ' + name)
    return [json.loads(line) for line in body]


def utc(value):
    require(type(value) is str, 'missing clock')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'clock has no timezone')
    return parsed.timestamp()


def _audit_block(root, repo, ancestry_context=None):
    from finite_audit import verify
    if ancestry_context is not None:
        return verify(root, repo, ancestry_context=ancestry_context)
    return verify(root, repo)


def _audit_construction(repo, inputs):
    from finite_validate import verify
    return verify(repo, inputs)


def _repository_binding(repo, q, i, manifest):
    from finite_runtime import validate_repository_binding
    return validate_repository_binding(repo, q, i, manifest, require_head=False)


def _process_observation(observation, policy_sha, module_sha, policy, lifecycle_journal=None):
    from finite_runtime import validate_mac_observation
    if policy.get('kind') == LIFECYCLE_KIND:
        require(type(lifecycle_journal) is bytes, 'archived lifecycle bytes are required for v3 replay')
        return validate_mac_observation(observation, policy_sha, module_sha, policy,
                                        lifecycle_journal=lifecycle_journal)
    return validate_mac_observation(observation, policy_sha, module_sha, policy)


def lifecycle_journal_bytes(root, receipt, *, prefix=False):
    """Prefer archive-local immutable bytes; never prefer an old live path.

    Block receipts bind a terminal prefix of the shared sequence journal. The
    sequence receipt binds the whole closed journal. A malformed preferred copy
    is adverse: it never causes a fallback to an unrelated live file.
    """
    root = Path(root)
    candidates = [root / 'lifecycle-journal.jsonl', root.parent / 'lifecycle-journal.jsonl']
    original = receipt.get('lifecycleJournalPath')
    if original is not None:
        require(type(original) is str and original and Path(original).is_absolute(),
                'original lifecycle fallback must be a local absolute path')
        candidates.append(Path(original))
    selected = None
    for candidate in candidates:
        if candidate.exists() or candidate.is_symlink():
            require(not candidate.is_symlink() and candidate.is_file(), 'unsafe lifecycle journal file')
            if candidate not in candidates[:2]:
                allowed = (Path('/Volumes/Untitled/AIJADE'), Path(__file__).resolve().parents[2])
                require(any(candidate.resolve().is_relative_to(parent) for parent in allowed),
                        'original lifecycle fallback is outside the project')
            selected = candidate
            break
    require(selected is not None, 'archived lifecycle journal is missing')
    body = selected.read_bytes()
    if prefix:
        size = integer(receipt.get('lifecycleJournalBytes'), 'block lifecycle prefix bytes', 1)
        require(size <= len(body), 'block lifecycle prefix was truncated')
        body = body[:size]
    elif 'lifecycleJournalBytes' in receipt:
        require(integer(receipt['lifecycleJournalBytes'], 'sequence journal bytes', 1) == len(body),
                'sequence lifecycle population changed')
    expected = receipt.get('lifecycleJournalSha256')
    require(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected), 'lifecycle journal SHA missing')
    require(body and body.endswith(b'\n') and hashlib.sha256(body).hexdigest() == expected,
            'lifecycle journal bytes/SHA differ from terminal receipt')
    return body


def _v3_sources(value):
    from finite_runtime import MAC_LIFECYCLE_SOURCES
    sources = value.get('observerSources')
    require(type(sources) is dict and set(sources) == set(MAC_LIFECYCLE_SOURCES),
            'v3 observer dependency population changed')
    require(all(type(v) is str and re.fullmatch('[0-9a-f]{64}', v) for v in sources.values()),
            'v3 observer dependency hash missing')
    require(sources['experiments/ch7/mac_process_guard_v3.py'] == value['observerModuleSha256'],
            'v3 observer module/map identity differs')
    return sources


def lifecycle_ancestry_context(root, receipt):
    """Read the complete archived sequence raw context, never a derived census.

    Physical/logical payload hashes are retained for disposable corruption
    controls. Context rows only locate original ancestry frames; they never
    replace a block's own resource population or its terminal journal prefix.
    """
    from audit_retrieval_led import raw as archived_raw
    root = Path(root)
    sequence_root = None
    for candidate in (root, root.parent):
        path = candidate / 'receipt.json'
        if path.is_file():
            value = json.loads(path.read_bytes())
            if value.get('schema') == 'aijade.ch7.finite-sequence-receipt.v1':
                sequence_root, sequence = candidate, value
                break
    require(sequence_root is not None, 'complete archived sequence ancestry context missing')
    require(sequence.get('status') == 'COMPLETE_FINITE_SEQUENCE_OBSERVATIONS',
            'ancestry context sequence is incomplete')
    for key in ('implementationCommit', 'repositoryCommit', 'buildFreezeCommit', 'buildFreezePath',
                'processPolicySha256', 'observerModuleSha256', 'executionPlanSha256', 'observerSources'):
        require(sequence.get(key) == receipt.get(key), 'ancestry context source/decision differs: ' + key)
    count = 1 if sequence.get('purpose') == 'qualification_only' else 4
    require(sequence.get('purpose') in ('qualification_only', 'confirmed_finite_heldout')
            and sequence.get('plannedBlocks') == sequence.get('completedBlocks') == count,
            'ancestry context block population changed')
    directories = {p.name for p in sequence_root.iterdir() if p.is_dir() and p.name.startswith('block-')}
    require(directories == {'block-' + str(i + 1) for i in range(count)}, 'ancestry context block directories incomplete')
    payloads = {}
    def payload(relative):
        path = sequence_root / relative
        physical = path if path.is_file() else path.with_suffix(path.suffix + '.gz')
        require(physical.is_file() and not physical.is_symlink(), 'unsafe/missing ancestry context payload: ' + relative)
        body = archived_raw(sequence_root, relative)
        payloads[str(physical.resolve())] = dict(relativePath=relative,sha256=digest(physical), sizeBytes=physical.stat().st_size,
                                               logicalSha256=hashlib.sha256(body).hexdigest(), logicalSizeBytes=len(body))
        return body
    require(json.loads(payload('receipt.json')) == sequence, 'ancestry context receipt changed while reading')
    journal = lifecycle_journal_bytes(sequence_root, sequence)
    require(payload('lifecycle-journal.jsonl') == journal, 'ancestry context journal is not the archived full journal')
    samples = []; raw_streams = {}
    def read_samples(relative):
        body = payload(relative)
        raw_streams[relative] = body
        require(body and body.endswith(b'\n') and all(line.strip() for line in body.splitlines()),
                'ancestry raw stream incomplete')
        values = [json.loads(line) for line in body.splitlines()]
        require(all(type(row) is dict for row in values), 'ancestry raw sample schema')
        points = [real(row.get('monotonicSeconds'), 'ancestry sample start') for row in values]
        require(all(b > a for a, b in zip(points, points[1:])), 'ancestry stream order reversed')
        samples.extend(values)
    read_samples('process-observations.jsonl')
    embedded = sequence.get('blocks')
    require(type(embedded) is list and len(embedded) == count, 'ancestry embedded block receipts incomplete')
    for index in range(count):
        relative = 'block-' + str(index + 1)
        block = json.loads(payload(relative + '/receipt.json'))
        require(block == embedded[index], 'ancestry block receipt differs from enclosing sequence')
        read_samples(relative + '/telemetry.jsonl')
    samples.sort(key=lambda row: row['monotonicSeconds'])
    context = dict(schema='aijade.ch7.lifecycle-raw-context.v1', sequenceReceipt=sequence,
                   journalBytes=journal, samples=samples, rawStreams=raw_streams, payloads=payloads)
    _ancestry_local_samples(context, receipt, None)
    return context


def _ancestry_local_samples(context, receipt, local_samples):
    require(type(context) is dict and context.get('schema') == 'aijade.ch7.lifecycle-raw-context.v1',
            'typed ancestry raw context missing')
    sequence = context.get('sequenceReceipt', {})
    require(sequence.get('status') == 'COMPLETE_FINITE_SEQUENCE_OBSERVATIONS', 'ancestry source sequence is incomplete')
    for key in ('implementationCommit', 'repositoryCommit', 'buildFreezeCommit', 'buildFreezePath',
                'processPolicySha256', 'observerModuleSha256', 'executionPlanSha256', 'observerSources'):
        require(sequence.get(key) == receipt.get(key), 'ancestry context identity mismatch: ' + key)
    journal = context.get('journalBytes')
    require(type(journal) is bytes and journal.endswith(b'\n')
            and hashlib.sha256(journal).hexdigest() == sequence.get('lifecycleJournalSha256'),
            'ancestry whole journal bytes differ from sequence receipt')
    rows = context.get('samples')
    require(type(rows) is list and rows, 'ancestry complete original samples missing')
    streams = context.get('rawStreams')
    count = 1 if sequence.get('purpose') == 'qualification_only' else 4
    expected_streams = {'process-observations.jsonl'} | {'block-' + str(i + 1) + '/telemetry.jsonl' for i in range(count)}
    require(type(streams) is dict and set(streams) == expected_streams, 'ancestry raw stream population changed')
    payloads = context.get('payloads')
    require(type(payloads) is dict and payloads, 'ancestry original payload hashes missing')
    by_path = {}
    for metadata in payloads.values():
        relative = metadata.get('relativePath')
        require(type(relative) is str and relative not in by_path, 'ancestry payload identity duplicated/missing')
        by_path[relative] = metadata
    require('lifecycle-journal.jsonl' in by_path
            and by_path['lifecycle-journal.jsonl']['logicalSha256'] == hashlib.sha256(journal).hexdigest(),
            'ancestry journal differs from its original payload hash')
    original_rows = []
    for relative,body in streams.items():
        require(type(body) is bytes and body and body.endswith(b'\n'), 'ancestry stream raw bytes missing')
        require(relative in by_path and by_path[relative]['logicalSha256'] == hashlib.sha256(body).hexdigest(),
                'ancestry raw bytes differ from original payload hash')
        values = [json.loads(line) for line in body.splitlines()]
        points = [real(row.get('monotonicSeconds'), 'original ancestry stream start') for row in values]
        require(all(b > a for a,b in zip(points,points[1:])), 'original ancestry stream reordered')
        original_rows.extend(values)
    original_rows.sort(key=lambda row: real(row.get('monotonicSeconds'), 'original ancestry sample clock'))
    canonical = lambda row: json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)
    require(canonical(rows) == canonical(original_rows), 'ancestry parsed samples differ from original stream bytes')
    by_id = {}
    for row in rows:
        require(type(row) is dict, 'ancestry raw row schema')
        sid = row.get('processObservation', {}).get('sampleId')
        require(type(sid) is str and re.fullmatch('[0-9a-f]{32}', sid) and sid not in by_id,
                'ancestry original sample identity duplicated/missing')
        by_id[sid] = row
    if local_samples is not None:
        scope = receipt.get('lifecycleScopeId')
        expected = {sid for sid,row in by_id.items()
                    if row.get('processObservation', {}).get('lifecycle', {}).get('scopeId') == scope}
        actual = {row.get('processObservation', {}).get('sampleId') for row in local_samples}
        require(actual == expected and len(actual) == len(local_samples), 'local raw population differs from ancestry context')
        for row in local_samples:
            sid = row['processObservation']['sampleId']
            require(canonical(row) == canonical(by_id[sid]), 'local raw sample differs from its original ancestry context')
    return rows, journal


def _lifecycle_ownership(root, receipt, samples, policy, *, scoped, ancestry_context=None):
    from lifecycle_audit import verify_lifecycle
    journal = lifecycle_journal_bytes(root, receipt, prefix=scoped)
    extra = {}
    if ancestry_context is not None:
        ancestry, full_journal = _ancestry_local_samples(ancestry_context, receipt, samples if scoped else None)
        require(full_journal.startswith(journal), 'ancestry journal differs from the block terminal prefix')
        extra = dict(ancestry_samples=ancestry, ancestry_journal=full_journal)
    registry = load(root, 'owned-process-registry.json')
    require(digest(root / 'owned-process-registry.json') == receipt['ownedProcessRegistrySha256'],
            'owned lifecycle final bytes changed')
    scope_id = receipt.get('lifecycleScopeId')
    require(type(scope_id) is str and re.fullmatch('[0-9a-f]{32}', scope_id), 'lifecycle scope identity missing')
    require(registry.get('schema') == 'aijade.process-lifecycle-final.v1'
            and registry.get('status') == 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT'
            and registry.get('scopeId') == scope_id and registry.get('scopeClosed') is True,
            'lifecycle final scope/status changed')
    require(all(registry.get(key) == [] for key in ('unresolvedFiniteLeases',
                'unleasedDiscoveredIdentities', 'remainingIdentities')), 'lifecycle final has unresolved identities')
    result = verify_lifecycle(journal, samples, source_commit=receipt['implementationCommit'],
        policy_sha256=receipt['processPolicySha256'], policy=policy,
        controller=receipt['controllerProcess'], require_cleanup=True,
        scope_id=scope_id if scoped else None, **extra)
    require(result.get('status') == 'LIFECYCLE_RAW_AUDIT_PASS' and result.get('cleanupAccepted') is True,
            'independent lifecycle closure did not accept')
    require(type(registry.get('knownFiniteLeases')) is list
            and len(registry['knownFiniteLeases']) == result['finiteLeases'],
            'lifecycle final finite population differs from raw journal')
    return result


def _fresh_observation(sample):
    observation = sample['processObservation']
    start = real(observation['startedMonotonic'], 'process observation start')
    end = real(observation['finishedMonotonic'], 'process observation end')
    require(sample['monotonicSeconds'] <= start <= end <= sample['observationCompletedMonotonic'],
            'process evidence is outside this sample capture')
    sid = observation['sampleId']
    require(type(sid) is str and re.fullmatch('[0-9a-f]{32}', sid), 'invalid process sample identity')
    return sid


def _process_key(value):
    return (integer(value['pid'], 'owned process PID', 1), real(value['createTime'], 'owned process creation'))


def _ownership(root, receipt, samples, direct_children):
    """Authorize roots from controller/Popen leases and previously witnessed descendants."""
    from finite_runtime import validate_owned_registry
    registry = load(root, 'owned-process-registry.json')
    require(digest(root / 'owned-process-registry.json') == receipt['ownedProcessRegistrySha256'], 'owned registry bytes changed')
    validate_owned_registry(registry, samples)
    controller = _process_key(receipt['controllerProcess'])
    require([_process_key(v) for v in registry['controllers']] == [controller], 'wrong owned controller lease')
    direct = {_process_key(value) for value in direct_children}
    require(len(direct) == len(direct_children) and controller not in direct, 'duplicate/self child controller lease')
    require({_process_key(v) for v in registry['explicitlyRegisteredIdentities']} == direct,
            'unrecorded directly registered owned process')
    authorized = {controller} | direct; witnessed = set(); last_seen = {}
    for sample in samples:
        observation = sample['processObservation']
        roots = {_process_key(value) for value in observation['ownedRoots']}
        require(roots <= authorized and controller in roots, 'unleased process declared as owned root')
        for phase in ['before', 'after']:
            nodes = observation['evidence'][phase]['processGraph']['nodes']
            by_pid = {value['pid']: value for value in nodes}
            while True:
                discovered = {_process_key(value) for value in nodes
                              if value['parentPid'] in by_pid
                              and _process_key(by_pid[value['parentPid']]) in authorized}
                if discovered <= authorized:
                    break
                authorized.update(discovered)
        owned = {_process_key(value) for value in observation['ownedProcesses']}
        require(owned <= authorized, 'owned census contains unwitnessed foreign process')
        witnessed.update(owned)
        for key in owned:
            last_seen[key] = real(observation['finishedMonotonic'], 'last owned observation')
    require({_process_key(v) for v in registry['knownIdentities']} <= authorized,
            'owned registry contains unauthorized history')
    end = real(receipt.get('blockEpochMonotonic', receipt['sequenceEpochMonotonic']), 'owned execution epoch') + real(receipt['wallSeconds'], 'owned execution wall')
    for value in registry['retiredIdentities']:
        checked = real(value['checkedMonotonic'], 'owned retirement clock')
        require(last_seen.get(_process_key(value), 0) <= checked <= end,
                'owned absence proof predates observation or follows the receipt')
    return dict(controller=dict(pid=controller[0], createTime=controller[1]),
                authorizedDirectChildren=len(direct), witnessedOwnedIdentities=len(witnessed))


def _identity(value, purpose):
    for key in SHARED:
        require(key in value, 'missing sequence/block identity: ' + key)
    for key in ('implementationCommit', 'repositoryCommit', 'buildFreezeCommit'):
        require(type(value[key]) is str and re.fullmatch('[0-9a-f]{40}', value[key]),
                'invalid Q/B/I commit: ' + key)
    require(value['codeCommit'] == value['implementationCommit'], 'code/DLL is not implementation Q')
    paths = value['addedDataPaths']
    require(type(paths) is list and len(set(paths)) == len(paths) and all(type(path) is str and path
            and not Path(path).is_absolute() and '..' not in Path(path).parts for path in paths),
            'invalid additive I path list')
    require(value['buildFreezeCommit'] != value['implementationCommit'], 'B must separately publish Q build bytes')
    for key in ('buildFreezePath', 'processPolicyPath'):
        path = value[key]
        require(type(path) is str and path and not Path(path).is_absolute()
                and '..' not in Path(path).parts, 'unsafe identity path: ' + key)
    for key in ('processPolicySha256', 'observerModuleSha256'):
        require(type(value[key]) is str and re.fullmatch('[0-9a-f]{64}', value[key]), 'invalid identity hash: ' + key)
    if value['buildFreezePath'] == LIFECYCLE_BUILD_FREEZE_PATH:
        _v3_sources(value)
    if purpose == 'qualification_only':
        require(value['repositoryCommit'] == value['implementationCommit'], 'qualification repository must be Q')
        require(all(value[key] is None for key in ('inputPublicationCommit', 'dataPublicationManifestPath',
                                                  'dataPublicationManifestSha256')), 'qualification invents I')
        require(paths == [], 'qualification has added I paths')
    else:
        require(value['repositoryCommit'] == value['inputPublicationCommit']
                and value['repositoryCommit'] != value['implementationCommit'], 'formal repository must be published I')
        path = value['dataPublicationManifestPath']
        require(type(path) is str and path and not Path(path).is_absolute()
                and '..' not in Path(path).parts, 'unsafe I manifest path')
        require(type(value['dataPublicationManifestSha256']) is str
                and re.fullmatch('[0-9a-f]{64}', value['dataPublicationManifestSha256']), 'invalid I manifest hash')


def expected_plan_sha256(value):
    from finite_runtime import MAC_BUILD_FREEZE_PATH,MAC_CENSUS_BUILD_FREEZE_PATH
    paths={MAC_BUILD_FREEZE_PATH:PLAN_SHA256,MAC_CENSUS_BUILD_FREEZE_PATH:CENSUS_PLAN_SHA256,
           LIFECYCLE_BUILD_FREEZE_PATH:LIFECYCLE_PLAN_SHA256}
    require(value.get('buildFreezePath') in paths,'unknown execution decision build path')
    return paths[value['buildFreezePath']]


def _same_identity(value, sequence, purpose):
    _identity(value, purpose)
    require(all(value[key] == sequence[key] for key in SHARED), 'mixed Q/B/I, policy or observer identities')
    require(value['executionPlanSha256'] == sequence['executionPlanSha256'] == expected_plan_sha256(sequence), 'wrong prospective execution plan')
    if sequence['buildFreezePath'] == LIFECYCLE_BUILD_FREEZE_PATH:
        require(_v3_sources(value) == _v3_sources(sequence), 'mixed v3 observer dependency identities')


def _no_missing(receipt):
    require(all(receipt.get(key) == [] for key in EMPTY_DISPOSITIONS), 'incomplete/unknown sequence dispositions')
    require(receipt.get('dispositionErrors', []) == [], 'disposition accounting errors')
    require(receipt.get('reason') is None, 'complete receipt still has a stop reason')


def _observation(value):
    require(type(value) is dict, 'missing raw reuse observation')
    require(value.get('status') == 200 and type(value.get('status')) is int,
            'unknown/unscorable raw reuse HTTP status')
    boolean(value.get('executed'), 'raw reuse executed')
    boolean(value.get('retrieved'), 'raw reuse retrieved')
    return value


def reconstruct(rows, runtime, contract, registry):
    """Separate implementation of raw counting; never consumes scorer totals."""
    cases = runtime['cases']; rules = contract['cases']
    require(type(cases) is list and type(rules) is list and len(cases) == len(rules) == 10,
            'not a complete ten-pair block')
    case_ids = [case['input']['caseId'] for case in cases]
    require(all(type(cid) is str and cid for cid in case_ids) and len(set(case_ids)) == 10, 'duplicate runtime case')
    by_rule = {}
    for rule in rules:
        require(rule['caseId'] not in by_rule and rule['window'] in registry, 'duplicate/unknown scoring window')
        require({k: v for k, v in rule.items() if k != 'caseId'} == registry[rule['window']],
                'changed fixed window/allowance')
        by_rule[rule['caseId']] = rule
    require(set(by_rule) == set(case_ids) and Counter(r['window'] for r in rules) == Counter(registry.keys()),
            'missing/duplicated family in block')
    require(contract['windowRegistrySha256'] == REGISTRY_SHA256, 'window registry changed')
    promotion = sum(rule['promotionOpportunity'] for rule in rules)
    reuse = sum(rule['reuseOpportunity'] for rule in rules)
    require((promotion, reuse) == (7, 8), 'known registry no longer has seven/eight opportunities')
    require(contract['scheduledInvalidPromotionOpportunitiesPerCondition'] == promotion
            and contract['scheduledInvalidReuseOpportunitiesPerCondition'] == reuse, 'shrunk scheduled denominator')
    order = []
    for case in cases:
        require(case['input']['conditions'] in [['C1', 'C2'], ['C2', 'C1']], 'unknown/duplicate condition')
        order.extend((case['input']['caseId'], arm) for arm in case['input']['conditions'])
    require(type(rows) is list and len(rows) == 20
            and [(row['caseId'], row['condition']) for row in rows] == order, 'missing/unknown/reordered raw row')
    result = {arm: {'totals': {field: 0 for field in FIELDS}, 'normalOutcomeCounts': Counter(),
                    'byCase': [], 'byFamily': {}} for arm in ['C1', 'C2']}
    for row in rows:
        arm = row['condition']; rule = by_rule[row['caseId']]; final = row['final']
        specs = final['specRows']; reports = final['reportRows']
        require(type(specs) is list and type(reports) is list, 'missing actual durable rows')
        require(integer(final['specs'], 'final specs') == len(specs)
                and integer(final['reports'], 'final reports') == len(reports), 'raw durable-count mismatch')
        spec_ids = [v['id'] for v in specs]; report_ids = [v['id'] for v in reports]
        require(all(type(x) is str and x for x in spec_ids + report_ids)
                and len(set(spec_ids)) == len(spec_ids) and len(set(report_ids)) == len(report_ids),
                'invalid/duplicate durable row identity')
        links = [report['result']['evolutionSpecId'] for report in reports]
        require(all(link is None or type(link) is str for link in links), 'invalid actual report link')
        reads = [_observation(row['round2'])]
        if rule['window'] == 'duplicate_invocation_2':
            reads.append(_observation(row['duplicateReuse']))
        else:
            require(row['duplicateReuse'] is None, 'unplanned duplicate reuse')
        executed = sum(int(read['executed']) for read in reads)
        require(integer(final['reuseCount'], 'final reuse') == executed, 'sandbox count differs from raw reuse')
        calls = row['promotionAttempts']; require(type(calls) is list, 'missing actual promotion calls')
        for call in calls:
            integer(call['invocation'], 'promotion invocation', 1)
            boolean(call['serviceResult']['ok'], 'actual service result')
        authority = final['authority']
        require(type(authority) is list and len(authority) <= 1, 'missing/duplicated authority')
        state = authority[0]['state'] if authority else 'absent'
        require(state in ['absent', 'unknown', 'failed', 'verified', 'revoked'], 'unknown authority representation')
        invocation = 2 if rule['window'] == 'duplicate_invocation_2' else 1
        at_promotion = [call for call in calls if call['invocation'] == invocation] if rule['promotionOpportunity'] else []
        at_reuse = reads[-1] if rule['window'] == 'duplicate_invocation_2' else reads[0]
        counts = dict(scheduledInvalidPromotionOpportunities=rule['promotionOpportunity'],
            invalidDurablePromotions=int(rule['promotionOpportunity'] == 1 and len(specs) > rule['allowedSpecs']),
            scheduledInvalidReuseOpportunities=rule['reuseOpportunity'],
            integrityInvalidReuse=int(rule['reuseOpportunity'] == 1 and executed > rule['allowedReuses']),
            persistedSpecs=len(specs), persistedReports=len(reports),
            successfulServiceReturns=sum(int(call['serviceResult']['ok']) for call in calls),
            promotionServiceEntries=len(calls), serviceEntriesAtInvalidPromotionWindow=len(at_promotion),
            actualRound2Queries=len(reads), retrievedRound2Queries=sum(int(read['retrieved']) for read in reads),
            queriedAtInvalidReuseWindow=int(rule['reuseOpportunity'] == 1 and at_reuse['status'] == 200),
            retrievedAtInvalidReuseWindow=int(rule['reuseOpportunity'] == 1 and at_reuse['retrieved']),
            round2SandboxExecutions=executed,
            outcomeMemories=integer(final['outcomeMemoryCount'], 'actual outcome memory count'))
        item = dict(caseId=row['caseId'], condition=arm, family=rule['window'], category=rule['class'], **counts)
        if rule['class'] == 'normal':
            normal = ('accepted' if len(specs) == len(reports) == 1 and set(spec_ids) == set(links)
                      and state == 'verified' and counts['outcomeMemories'] == 1 and executed == 1
                      else 'unknown' if state == 'unknown' else 'refused_or_incomplete')
            result[arm]['normalOutcomeCounts'][normal] += 1; item['normalOutcome'] = normal
        if rule['class'] == 'semantic_control':
            item.update(semanticMismatchAssociatedPromotions=len(specs), associatedSkillSandboxReuse=executed,
                        round2SemanticActCorrectness='NOT_MEASURED')
        result[arm]['byCase'].append(item)
        result[arm]['byFamily'][rule['window']] = counts
        for field in FIELDS:
            result[arm]['totals'][field] += counts[field]
    return result


def _stream(samples, sequence, duration, policy, *, global_clock, lifecycle_journal=None):
    require(type(samples) is list and len(samples) >= 2, 'missing resource/process coverage')
    epoch = real(sequence['sequenceEpochMonotonic'], 'sequence epoch')
    baseline = integer(sequence['initialSystemSwapUsedBytes'], 'sequence swap baseline')
    previous = None; timers = {}; sample_ids = set()
    for sample in samples:
        mono = real(sample['monotonicSeconds'], 'sample monotonic clock')
        position = real(sample['sequenceElapsedSeconds'], 'sequence elapsed')
        require(abs((mono - epoch) - position) <= 0.00001, 'mixed sequence clock/epoch')
        local = position if global_clock else real(sample['elapsedSeconds'], 'block elapsed')
        require(previous is None or 0 < local - previous <= 3, 'missing/reversed process/resource coverage')
        previous = local
        observation = sample['processObservation']
        sid = _fresh_observation(sample)
        require(sid not in sample_ids, 'duplicate process sample'); sample_ids.add(sid)
        require(sample['processPolicySha256'] == sequence['processPolicySha256']
                and sample['observerModuleSha256'] == sequence['observerModuleSha256'], 'sample observer identity changed')
        if policy.get('kind') == LIFECYCLE_KIND:
            _process_observation(observation, sequence['processPolicySha256'], sequence['observerModuleSha256'], policy,
                                 lifecycle_journal=lifecycle_journal)
        else:
            _process_observation(observation, sequence['processPolicySha256'], sequence['observerModuleSha256'], policy)
        require(observation.get('status') == 'PASS' and observation.get('blockers') == [], 'process observation not accepted')
        owned = observation['ownedProcesses']; require(type(owned) is list and owned, 'owned process census missing')
        keys = [(row['pid'], row['createTime']) for row in owned]
        require(len(set(keys)) == len(keys), 'duplicate owned PID/create-time')
        rss = sum(integer(row['rssBytes'], 'observed owned RSS') for row in owned)
        require(integer(sample['rssBytes'], 'resource RSS') == rss, 'RSS not reconstructed from this observed family')
        available = integer(sample['availableBytes'], 'available memory')
        swap_used = integer(sample['swapUsedBytes'], 'actual global swap')
        growth = integer(sample['swapIncreaseBytes'], 'swap increase')
        require(growth == max(0, swap_used - baseline), 'swap baseline/delta changed')
        for name, crossed in [('rss', rss > 2 * 1024**3), ('available', available < 3 * 1024**3),
                              ('swap', growth > 1024**3)]:
            if not crossed:
                timers.pop(name, None)
            else:
                timers.setdefault(name, local)
                require(local - timers[name] < 30, 'unreported sustained sequence ' + name + ' stop')
    first = samples[0]['sequenceElapsedSeconds'] if global_clock else samples[0]['elapsedSeconds']
    last = samples[-1]['sequenceElapsedSeconds'] if global_clock else samples[-1]['elapsedSeconds']
    require(first <= 3 and duration - 3 <= last <= duration + 3, 'resource coverage does not span execution/cleanup')
    return dict(samples=len(samples), firstElapsedSeconds=first, lastElapsedSeconds=last,
                peakOwnedRssBytes=max(s['rssBytes'] for s in samples),
                minimumAvailableBytes=min(s['availableBytes'] for s in samples))


def _fixed_phase(root, name, sequence, policy, duration, minimum_samples):
    receipt = load(root / name, 'receipt.json'); samples = lines(root / name, 'telemetry.jsonl')
    expected = 'ADMITTED' if name == 'admission' else 'FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION'
    require(receipt['status'] == expected and receipt.get('windowReset' if name == 'admission' else 'intervalReset') is False,
            'sequence phase was not accepted: ' + name)
    _same_identity(receipt, sequence, sequence['purpose'])
    clock = receipt['phaseClock']; start = real(clock['startMonotonic'], name + ' start')
    end = real(clock['endMonotonic'], name + ' end')
    require(clock['requestedSeconds'] == duration and clock['intervalReset'] is False
            and duration <= end - start <= duration + 3, 'fixed phase clock changed: ' + name)
    require(abs(real(receipt['elapsedSeconds'], name + ' duration') - (end - start)) <= 0.00001
            and len(samples) >= minimum_samples, 'incomplete ' + name)
    previous = None; sample_ids = set()
    for sample in samples:
        elapsed = real(sample['elapsedSeconds'], name + ' sample clock')
        require(previous is None or 0 < elapsed - previous <= 3, name + ' coverage gap')
        previous = elapsed
        require(abs(real(sample['monotonicSeconds'], name + ' sample monotonic') - start - elapsed) <= 0.00001,
                'phase sample clock differs from fixed origin')
        completed = real(sample['observationCompletedMonotonic'], 'phase observation completion')
        observed_for = real(sample['observationDurationSeconds'], 'phase observation duration')
        require(start + elapsed <= completed <= start + duration
                and elapsed + observed_for <= duration, 'observation exceeded fixed phase deadline')
        sid = _fresh_observation(sample)
        require(sid not in sample_ids, 'duplicate phase process sample'); sample_ids.add(sid)
        require(sample['processObservation']['ownedRoots'] == []
                and sample['processObservation']['ownedProcesses'] == [], 'unloaded phase declares an owned research process')
        integer(sample['availableBytes'], name + ' memory'); integer(sample['swapUsedBytes'], name + ' swap')
        require(sample['processPolicySha256'] == sequence['processPolicySha256']
                and sample['observerModuleSha256'] == sequence['observerModuleSha256'], 'phase observer identity changed')
        _process_observation(sample['processObservation'], sequence['processPolicySha256'], sequence['observerModuleSha256'], policy)
    require(samples[0]['elapsedSeconds'] <= 3 and duration - 3 <= samples[-1]['elapsedSeconds'] < duration,
            'missing fixed phase boundary samples')
    require(receipt['samples'] == len(samples), 'phase sample population differs from raw')
    return receipt, samples, start, end


def _admission(root, sequence, policy, runtime_samples=None, lifecycle_journal=None):
    if policy.get('kind') == LIFECYCLE_KIND:
        from lifecycle_audit import verify_continuity
        require(type(lifecycle_journal) is bytes, 'continuous preflight needs the archived lifecycle bytes')
        require(digest(root / 'preflight-continuity.json') == sequence['preflightContinuitySha256']
                and digest(root / 'phase-events.jsonl') == sequence['phaseEventsSha256'],
                'continuous preflight/event bytes changed')
        preflight = load(root, 'preflight-continuity.json')
        require(preflight.get('schema') == 'aijade.ch7.phase-continuity-preflight.v1'
                and preflight.get('status') == 'PREFLIGHT_COMPLETE_ADMITTED'
                and preflight.get('windowReset') is False, 'streaming preflight not complete')
        phases = preflight['phases']
        expected = {'settling', 'admission'} if sequence['purpose'] == 'qualification_only' else {'admission'}
        require(set(phases) == expected, 'wrong fixed preflight phases for this decision')
        require(('settling' in expected) == (root / 'settling').exists(), 'undeclared/missing settling directory')
        streams = {name: lines(root / name, 'telemetry.jsonl') for name in phases}
        for name, phase in phases.items():
            receipt = load(root / name, 'receipt.json')
            _same_identity(receipt, sequence, sequence['purpose'])
            require(all(receipt.get(key) == value for key, value in phase.items()),
                    'phase receipt differs from streaming state')
            require(receipt.get('lifecycleScopeId') == sequence.get('lifecycleScopeId')
                    and receipt.get('controllerProcess') == sequence.get('controllerProcess'),
                    'preflight phase changed its persistent controller/scope')
            require(all(sample.get('processObservation', {}).get('lifecycle', {}).get('scopeId')
                        == sequence.get('lifecycleScopeId') for sample in streams[name]),
                    'idle observation belongs to another persistent scope')
        events = lines(root, 'phase-events.jsonl')
        result = verify_continuity(phases, streams, events, policy=policy,
            runtime_samples=runtime_samples, runtime_epoch=sequence['sequenceEpochMonotonic'],
            lifecycle_journal=lifecycle_journal)
        require(result.get('status') == 'CONTINUITY_RAW_AUDIT_PASS', 'independent fixed-phase replay refused')
        count = sum(len(value) for value in streams.values())
        require(preflight.get('samples') == preflight.get('validatedSamples') == count
                and preflight.get('eventCount') == len(events), 'preflight global population differs from raw')
        require(preflight.get('maximumGlobalGapSeconds') == result['maximumGlobalSampleGapSeconds'],
                'preflight maximum gap differs from raw')
        first_name = 'settling' if 'settling' in phases else 'admission'
        schedule = preflight.get('schedule', {})
        require(schedule == dict(originMonotonic=phases[first_name]['phaseClock']['startMonotonic'],
            intervalSeconds=2, maximumGapSeconds=3, settlingSeconds=600 if 'settling' in phases else 0,
            admissionSeconds=120, intervalReset=False), 'continuous fixed schedule changed')
        last = streams['admission'][-1]
        require(preflight.get('lastSample') == dict(sampleId=last['sampleId'],globalIndex=last['globalIndex'],
            monotonicSeconds=last['monotonicSeconds'],observationCompletedMonotonic=last['observationCompletedMonotonic']),
            'last actual preflight sample differs')
        anchor = preflight.get('runtimeHandoffAnchor', {})
        require(all(anchor.get(key) == value for key,value in dict(lastSampleMonotonic=last['monotonicSeconds'],
            lastSampleId=last['sampleId'],lastGlobalIndex=last['globalIndex'],
            phaseEndMonotonic=phases['admission']['phaseClock']['endMonotonic']).items()), 'runtime handoff anchor changed')
        recorded = real(anchor.get('handoffRecordedMonotonic'), 'actual handoff write completion')
        require(anchor['phaseEndMonotonic'] <= recorded <= sequence['sequenceEpochMonotonic']
                and recorded-last['monotonicSeconds'] <= 3, 'handoff record clocks lack raw continuity')
        return result
    receipt, samples, start, end = _fixed_phase(root, 'admission', sequence, policy, 120, 60)
    require(all(s['availableBytes'] >= 4 * 1024**3 for s in samples), 'admission memory below limit')
    swap_range = max(s['swapUsedBytes'] for s in samples) - min(s['swapUsedBytes'] for s in samples)
    minimum = min(s['availableBytes'] for s in samples)
    require(swap_range <= 64 * 1024**2 and receipt['minimumAvailableBytes'] == minimum
            and receipt['swapRangeBytes'] == swap_range and receipt['samples'] == len(samples), 'admission aggregate differs from raw')
    require(samples[-1].get('utc') is not None and utc(samples[-1]['utc']) <= utc(sequence['startedAt']),
            'execution began before admission completed')
    require(0 <= sequence['sequenceEpochMonotonic'] - end <= 3, 'unobserved delay after admission')
    settling = None
    if sequence['purpose'] == 'qualification_only':
        settling_receipt, settling_samples, settling_start, settling_end = _fixed_phase(root, 'settling', sequence, policy, 600, 300)
        require(0 <= start - settling_end <= 3, 'settling/admission transition is not immediate')
        require(receipt['precedingFixedSettlingSeconds'] == 600, 'qualification settling identity missing')
        settling = dict(samples=len(settling_samples), elapsedSeconds=settling_end - settling_start)
    else:
        require(not (root / 'settling').exists() and receipt['precedingFixedSettlingSeconds'] == 0,
                'formal stage has an undeclared extra settling phase')
    return dict(samples=len(samples), minimumAvailableBytes=minimum, swapRangeBytes=swap_range, settling=settling)


def verify(root, repo):
    root = Path(root).resolve(); repo = Path(repo).resolve(); sequence = load(root, 'receipt.json')
    require(sequence['schema'] == 'aijade.ch7.finite-sequence-receipt.v1'
            and sequence['status'] == 'COMPLETE_FINITE_SEQUENCE_OBSERVATIONS', 'sequence is not complete')
    purpose = sequence['purpose']
    require(purpose in ['qualification_only', 'confirmed_finite_heldout'], 'unknown sequence purpose')
    blocks = 1 if purpose == 'qualification_only' else 4; pairs = 10 * blocks; population = 2 * pairs
    for field, expected in [('plannedBlocks', blocks), ('completedBlocks', blocks), ('plannedPairs', pairs),
                            ('plannedConditionRows', population), ('completedConditionRows', population)]:
        require(integer(sequence[field], field) == expected, 'incomplete/changed sequence population: ' + field)
    require(sequence['modelRequests'] == 0 and type(sequence['modelRequests']) is int
            and sequence['formalHardwareQualification'] is False and sequence['independentHumanReview'] is False,
            'sequence scientific scope inflated')
    require(sequence['executionPlanSha256'] == expected_plan_sha256(sequence), 'wrong prospective execution plan')
    _identity(sequence, purpose); _no_missing(sequence)
    binding = _repository_binding(repo, sequence['implementationCommit'], sequence['repositoryCommit'],
                                  sequence['dataPublicationManifestPath'])
    require(all(binding[key] == sequence[key] for key in BINDING_FIELDS), 'claimed Q/I addition metadata differs from Git proof')
    require(digest(repo / sequence['processPolicyPath']) == sequence['processPolicySha256'], 'observed process policy changed')
    require(digest(root / 'process-policy.json') == sequence['processPolicySha256'], 'sequence policy copy changed')
    policy = load(root, 'process-policy.json')
    v3 = policy.get('kind') == LIFECYCLE_KIND
    lifecycle_journal = None
    ancestry_context = None
    if v3:
        from finite_runtime import load_mac_policy
        require(sequence['buildFreezePath'] == LIFECYCLE_BUILD_FREEZE_PATH,
                'v3 observer was rebound to a historical build freeze')
        _, identities = load_mac_policy(repo, repo / sequence['processPolicyPath'], sequence['implementationCommit'])
        require(identities['observerSources'] == _v3_sources(sequence)
                and identities['observerModuleSha256'] == sequence['observerModuleSha256'],
                'v3 complete source dependency map differs from Q')
        lifecycle_journal = lifecycle_journal_bytes(root, sequence)
        ancestry_context = lifecycle_ancestry_context(root, sequence)
    if purpose == 'confirmed_finite_heldout':
        require(digest(repo / sequence['dataPublicationManifestPath']) == sequence['dataPublicationManifestSha256'],
                'published I manifest changed')
    require(real(sequence['wallSeconds'], 'sequence wall') <= 4800
            and utc(sequence['finishedAt']) >= utc(sequence['startedAt']), 'sequence clock/wall limit')
    actual_directories = {p.name for p in root.iterdir() if p.is_dir() and p.name.startswith('block-')}
    require(actual_directories == {'block-' + str(i + 1) for i in range(blocks)}, 'missing/extra block directory')
    require(type(sequence['blocks']) is list and len(sequence['blocks']) == blocks, 'missing/extra receipt block')
    registry = window_registry()
    require((sum(r['promotionOpportunity'] for r in registry.values()), sum(r['reuseOpportunity'] for r in registry.values())) == (7, 8),
            'fixed source windows no longer define seven/eight opportunities')
    totals = {arm: {field: 0 for field in FIELDS} for arm in ['C1', 'C2']}
    normal = {arm: Counter() for arm in ['C1', 'C2']}; by_family = {arm: {} for arm in ['C1', 'C2']}
    by_category = {arm: {} for arm in ['C1', 'C2']}
    semantic = {arm: dict(conditionRows=0, associatedPromotions=0, associatedSkillSandboxReuse=0,
                         round2SemanticActCorrectness='NOT_MEASURED') for arm in ['C1', 'C2']}
    all_keys = []; all_cases = set(); databases = set(); block_results = []
    shared_input_hashes = None; previous_end = utc(sequence['startedAt']); previous_journal = None
    construction_parent = None; block_controllers = []; lifecycle_block_samples = []
    for index in range(blocks):
        block = root / ('block-' + str(index + 1))
        require(not block.is_symlink() and block.resolve().parent == root, 'unsafe block location')
        receipt = load(block, 'receipt.json'); identity = load(block, 'input-identities.json')
        runtime = load(block, 'runtime-manifest.json'); contract = load(block, 'scoring-manifest.json')
        rows = load(block, 'cases.json')
        require(sequence['blocks'][index] == receipt, 'reordered/changed embedded block receipt')
        require(receipt['status'] == 'COMPLETE_FINITE_BLOCK_OBSERVATIONS' and receipt['blockIndex'] == index
                and receipt['purpose'] == runtime['purpose'] == contract['purpose'] == purpose,
                'block order/purpose/status changed')
        _same_identity(receipt, sequence, purpose); _same_identity(identity, sequence, purpose); _no_missing(receipt)
        require(receipt['controllerProcess'] == identity['controllerProcess'], 'block controller lease differs from identity')
        controller = dict(blockIndex=index, **receipt['controllerProcess']); block_controllers.append(controller)
        require(digest(block / 'process-policy.json') == sequence['processPolicySha256'], 'block policy copy changed')
        for field, expected in [('plannedCases', 20), ('completedCases', 20), ('plannedPairs', 10)]:
            require(integer(receipt[field], field) == expected, 'incomplete block population')
        require(receipt['modelRequests'] == 0 and receipt['formalHardwareQualification'] is False, 'block scope inflated')
        require(real(receipt['wallSeconds'], 'block wall') <= 1200, 'block wall limit')
        require(receipt['sequenceEpochMonotonic'] == sequence['sequenceEpochMonotonic']
                and receipt['initialSystemSwapUsedBytes'] == sequence['initialSystemSwapUsedBytes'], 'reset sequence resource baseline')
        require(runtime['blockIndex'] == contract['blockIndex'] == index
                and runtime['constructionFreezeCommit'] == identity['constructionFreezeCommit'] == sequence['implementationCommit'],
                'wrong input block/construction Q')
        require(digest(block / 'runtime-manifest.json') == contract['runtimeManifestSha256'] == identity['runtimeManifestSha256']
                and digest(block / 'scoring-manifest.json') == identity['scoringManifestSha256'], 'block input byte binding changed')
        input_hashes = tuple(identity[key] for key in BACKEND_FIELDS) + (identity['preparedRenderer']['files'],)
        require(shared_input_hashes is None or input_hashes == shared_input_hashes, 'different shared inputs/build across blocks')
        shared_input_hashes = input_hashes
        require(digest(block / 'selection.json') == runtime['selectionSha256'] == identity['selectionSha256'], 'candidate selection bytes changed')
        if purpose == 'confirmed_finite_heldout':
            relative = identity['runtimeRepositoryPath']
            require(type(relative) is str and not Path(relative).is_absolute() and '..' not in Path(relative).parts,
                    'unsafe formal runtime path')
            parent = (repo / relative).parent.parent
            require(construction_parent is None or parent == construction_parent, 'formal blocks from different constructions')
            construction_parent = parent
            require(sum(case['input']['conditions'] == ['C1', 'C2'] for case in runtime['cases']) == 5,
                    'unbalanced first-arm order')
        audit = (_audit_block(block, repo, ancestry_context=ancestry_context) if v3 else _audit_block(block, repo))
        require(audit['status'] == 'FINITE_DATAFLOW_AUDIT_PASS' and audit['casePairs'] == 10
                and audit['measuredConditionRows'] == 20, 'strict block raw audit did not accept complete population')
        rebuilt = reconstruct(rows, runtime, contract, registry)
        for arm in ['C1', 'C2']:
            require(all(audit['conditionCounts'][arm][key] == rebuilt[arm]['totals'][key] for key in FIELDS),
                    'sequence independent raw count differs from block audit')
            require(audit['conditionCounts'][arm]['normalOutcomeCounts'] == dict(rebuilt[arm]['normalOutcomeCounts']),
                    'sequence independent normal outcome differs from block audit')
            for field in FIELDS:
                totals[arm][field] += rebuilt[arm]['totals'][field]
            normal[arm].update(rebuilt[arm]['normalOutcomeCounts'])
            for family, values in rebuilt[arm]['byFamily'].items():
                target = by_family[arm].setdefault(family, {field: 0 for field in FIELDS})
                for field in FIELDS:
                    target[field] += values[field]
            for item in rebuilt[arm]['byCase']:
                category = by_category[arm].setdefault(item['category'], dict(conditionRows=0, **{field: 0 for field in FIELDS}))
                category['conditionRows'] += 1
                for field in FIELDS:
                    category[field] += item[field]
                if item['category'] == 'semantic_control':
                    semantic[arm]['conditionRows'] += 1
                    semantic[arm]['associatedPromotions'] += item['semanticMismatchAssociatedPromotions']
                    semantic[arm]['associatedSkillSandboxReuse'] += item['associatedSkillSandboxReuse']
        keys = [(row['caseId'], row['condition']) for row in rows]
        require(not all_cases.intersection(case['input']['caseId'] for case in runtime['cases']), 'duplicate case across blocks')
        all_cases.update(case['input']['caseId'] for case in runtime['cases']); all_keys.extend(keys)
        block_databases = [row['databaseBefore']['database'] for row in rows]
        require(len(set(block_databases)) == 20 and not databases.intersection(block_databases), 'database reused across arm/block')
        databases.update(block_databases)
        cleanup = load(block, 'database-cleanup.json')
        require(type(cleanup) is list and len(cleanup) == 20 and {v['database'] for v in cleanup} == set(block_databases)
                and all(v['remaining'] == 0 and not v.get('error') for v in cleanup), 'missing/unknown/duplicate owned cleanup')
        require(receipt.get('logCloseErrors') == [] and all(v['exitCode'] == 0 and v['errors'] == []
                for v in load(block, 'process-cleanup.json')), 'process/log closure unresolved')
        phases = receipt['phases']; first = min(utc(v['startedAt']) for v in phases.values())
        require(phases and first >= previous_end and utc(receipt['finishedAt']) >= max(utc(v['endedAt']) for v in phases.values()),
                'overlapping/reversed block or cleanup chronology')
        previous_end = utc(receipt['finishedAt'])
        journal = lines(block, 'journal.jsonl')
        for event in journal:
            point = integer(event['monotonicTicks'], 'journal monotonic ticks') / integer(event['frequency'], 'journal frequency', 1)
            require(previous_journal is None or point > previous_journal, 'global block journal time reversed')
            previous_journal = point
        telemetry = lines(block, 'telemetry.jsonl')
        if v3:
            block_journal = lifecycle_journal_bytes(block, receipt, prefix=True)
            require(lifecycle_journal.startswith(block_journal), 'block journal prefix differs from the enclosing sequence')
            resource = _stream(telemetry, sequence, receipt['wallSeconds'], policy, global_clock=False,
                               lifecycle_journal=block_journal)
            ownership = _lifecycle_ownership(block, receipt, telemetry, policy, scoped=True,
                                             ancestry_context=ancestry_context)
            lifecycle_block_samples.extend(telemetry)
        else:
            resource = _stream(telemetry, sequence, receipt['wallSeconds'], policy, global_clock=False)
            ownership = _ownership(block, receipt, telemetry, [dict(pid=value['pid'], createTime=value['createTime']) for value in phases.values()])
        block_results.append(dict(blockIndex=index, casePairs=10, measuredConditionRows=20,
            rawCasesSha256=digest(block / 'cases.json'), receiptSha256=digest(block / 'receipt.json'),
            independentlyReconstructed=rebuilt, resourceCoverage=resource, processOwnership=ownership))
    require(len(all_cases) == pairs and len(all_keys) == len(set(all_keys)) == population, 'incomplete sequence raw population')
    require(previous_end <= utc(sequence['finishedAt']), 'sequence ended before final cleanup')
    require(sequence['blockControllers'] == block_controllers, 'actual ordered block controller leases differ')
    require(all(totals[arm]['scheduledInvalidPromotionOpportunities'] == 7 * blocks
                and totals[arm]['scheduledInvalidReuseOpportunities'] == 8 * blocks for arm in totals), 'sequence denominator changed')
    if purpose == 'confirmed_finite_heldout':
        suitability = _audit_construction(repo, construction_parent)
        require(suitability['status'] == 'PASS_ALL_FORTY_BEFORE_MEASUREMENT' and suitability['casePairs'] == 40
                and suitability['conditionRows'] == 80, 'four-block frozen construction not accepted')
    global_samples = lines(root, 'process-observations.jsonl')
    if v3:
        admission = _admission(root, sequence, policy, runtime_samples=global_samples,
                               lifecycle_journal=lifecycle_journal)
        coverage = _stream(global_samples, sequence, sequence['wallSeconds'], policy, global_clock=True,
                           lifecycle_journal=lifecycle_journal)
        # Every scope can supply absence/discovery witnesses.  The sequence's
        # own resource stream still separately covers every startup/cleanup gap.
        complete_runtime = sorted(global_samples + lifecycle_block_samples, key=lambda row: row['monotonicSeconds'])
        ownership = _lifecycle_ownership(root, sequence, complete_runtime, policy, scoped=False,
                                         ancestry_context=ancestry_context)
    else:
        admission = _admission(root, sequence, policy)
        coverage = _stream(global_samples, sequence, sequence['wallSeconds'], policy, global_clock=True)
        ownership = _ownership(root, sequence, global_samples, block_controllers)
    result = dict(schema='aijade.ch7.finite-sequence-audit.v1', status='FINITE_SEQUENCE_RAW_AUDIT_PASS',
        strictAccepted=True, purpose=purpose, **{key: sequence[key] for key in SHARED},
        codeCommit=sequence['implementationCommit'], blocks=blocks, casePairs=pairs, measuredConditionRows=population,
        freshFiniteHeldoutPairs=pairs if purpose == 'confirmed_finite_heldout' else 0,
        scheduledInvalidPromotionOpportunitiesPerArm=7 * blocks, scheduledInvalidReuseOpportunitiesPerArm=8 * blocks,
        arms=totals, normalOutcomeCounts={arm: dict(value) for arm, value in normal.items()}, byFamily=by_family,
        byCategory=by_category, semanticLimitObservations=semantic,
        blocksFromRaw=block_results, differencesC2MinusC1={key: totals['C2'][key] - totals['C1'][key]
            for key in ['invalidDurablePromotions', 'integrityInvalidReuse']},
        admission=admission, sequenceResourceCoverage=coverage, processOwnership=ownership, modelRequests=0,
        formalHardwareQualification=False, independentHumanReview=False, round2SemanticActCorrectness='NOT_MEASURED',
        receiptSha256=digest(root / 'receipt.json'),
        interpretation='Complete finite constructed-case sequence, independently counted from raw rows under frozen windows; adverse C2 observations retained. No population uncertainty inference, hardware certificate, participant/visual/emotional outcome or independent human review.')
    if v3:
        result.update(observerSources=sequence['observerSources'], lifecycleJournalSha256=sequence['lifecycleJournalSha256'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.root, args.repo); code = 0
    except Exception as error:
        result = dict(schema='aijade.ch7.finite-sequence-audit.v1', status='FINITE_SEQUENCE_RAW_AUDIT_REFUSED',
                      strictAccepted=False, reason=type(error).__name__ + ': ' + str(error)); code = 1
    body = json.dumps(result, indent=2) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(body)
    else:
        print(body, end='')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
