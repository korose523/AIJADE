#!/usr/bin/env python3
"""Independent offline audit of one engineering 300+60+2 equal-load record.

Never call observe(), a native helper, an API, a model, or a renderer here.
The full independent lifecycle parser remains the executed-Q implementation;
this tool does not optimize it or borrow the producer's incremental state.
The final runner/passport binding is deliberately explicit and fail-closed.
"""
import argparse
import ast
import base64
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
import traceback

BASE = Path('/Volumes/Untitled/AIJADE')
FULL_AUDITOR_SHA256 = 'ffbf69965dd68bcdbf1f7b67ab6e2bda31839ee80ca176a8bc3f9ba2fd77bfef'
TOOL_SHA256 = {
    'git': '7f30f076d0e9c38f772a76449fca9da8cf97f6a3d43b94c90a00e4f9ce7ad39e',
    'lsof': 'ef5e67978fb8f8bcd32927789811462dd1b3773b8ad6322b67a491d2b5733b3a',
}
PRESERVED_SOURCES = {
    'experiments/ch7/mac_process_guard.py': 'be8df86b47f382f663eab4f22553025a41661326695d112cfc30ffbe1c677d87',
    'experiments/ch7/mac_process_guard_v2.py': '85fe287e32b2c3741bcc84dbc0c393f7d798c25bbfd0140f71db4611ede21fc6',
    'experiments/ch7/mac_bulk_census.c': '22bb68d79e62a3ef40177988621c3d69c6195427c891879186534578e465d003',
    'experiments/ch7/lifecycle_audit.py': FULL_AUDITOR_SHA256,
}
FILES = {
    'settling': 'settling/telemetry.jsonl',
    'admission': 'admission/telemetry.jsonl',
    'tail': 'tail/telemetry.jsonl',
    'phaseEvents': 'phase-events.jsonl',
    'serviceEvents': 'service-events.jsonl',
    'tailEvents': 'tail/events.jsonl',
    'passport': 'engineering-passport.json',
    'journal': 'lifecycle-journal.jsonl',
    'policy': 'process-policy.json',
    'preflight': 'preflight-continuity.json',
    'receipt': 'receipt.json',
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def read(path):
    return decode(Path(path).read_bytes())


def jsonl(path):
    raw = Path(path).read_bytes()
    require(not raw or raw.endswith(b'\n'), 'unterminated JSONL: ' + str(path))
    result = []
    for line in raw.splitlines():
        require(line.strip(), 'blank original JSONL row: ' + str(path))
        result.append(decode(line))
    return result


def real(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, label)
    return value


def integer(value, label):
    require(type(value) is int and value >= 0, label)
    return value


def same(left, right, label):
    require(abs(real(left, label) - real(right, label)) <= 1e-6, label)


def typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(typed_equal(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def relative(value):
    require(type(value) is str and value and '\\' not in value and '\x00' not in value, 'relative path type')
    path = Path(value)
    require(not path.is_absolute() and '..' not in path.parts and path.as_posix() == value, 'unsafe relative path')
    return path


def file_table(root):
    result = {}
    for directory, directories, filenames in os.walk(root, followlinks=False):
        require(all(not (Path(directory) / name).is_symlink() for name in directories), 'symlink directory in run')
        for name in filenames:
            path = Path(directory) / name
            require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), 'nonregular input artifact')
            result[path.relative_to(root).as_posix()] = dict(sha256=file_sha(path), sizeBytes=path.stat().st_size)
    return dict(sorted(result.items()))


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo)


def load_protocol(args, receipt):
    """Bind the explicit runner/passport contract; never accept alias guesses."""
    require(args.passport_sha256 == file_sha(args.passport), 'actual pre-run passport SHA differs')
    passport = read(args.passport)
    require(passport['schema'] == 'aijade.ch7.equal-load-passport.v1', 'frozen passport schema')
    require(Path(passport['repo']).resolve() == args.repo.resolve()
            and Path(passport['output']).resolve() == args.root.resolve(), 'actual repo/output passport binding')
    require((args.root / FILES['passport']).read_bytes() == args.passport.read_bytes(), 'executed passport bytes differ')
    require(receipt['schema'] == 'aijade.ch7.equal-load-result.v1'
            and receipt['status'] == 'ENGINEERING_EQUAL_LOAD_PASS', 'complete engineering run not accepted')
    require(receipt['sourceCommit'] == passport['sourceCommit']
            and receipt['passportSha256'] == args.passport_sha256
            and receipt['runnerSha256'] == passport['runnerSha256']
            and receipt['policySha256'] == passport['policySha256']
            and typed_equal(receipt['sourceFiles'], passport['sourceFiles']), 'receipt/passport source identity')
    require(receipt['errors'] == [] and type(receipt['observations']) is int and receipt['observations'] == 362
            and type(receipt['tailObservations']) is int and receipt['tailObservations'] == 2,
            'complete engineering receipt population/errors')
    require(receipt['lifecycleJournalStable'] is True and receipt['tailThreadJoined'] is True,
            'journal/thread is not terminal and stable')
    controller = receipt['controllerProcess']
    require(type(controller) is dict and set(controller) == {'pid', 'createTime', 'parentPid'}
            and type(controller['pid']) is int and controller['pid'] > 1
            and type(controller['parentPid']) is int and controller['parentPid'] >= 0
            and real(controller['createTime'], 'controller kernel creation time') > 0,
            'exact controller receipt identity types')
    require(type(passport['pythonPath']) is str and Path(passport['pythonPath']).is_absolute()
            and type(passport['pythonSha256']) is str
            and receipt['controllerSysExecutable'] == passport['pythonPath']
            and file_sha(Path(passport['pythonPath'])) == passport['pythonSha256'],
            'actual controller interpreter differs from frozen passport')
    false_fields = ('qualificationStarted', 'backendQualified', 'scientificAdmission',
                    'formalHardwareQualification', 'independentHumanReview', 'seedConstructed')
    zero_fields = ('flowBlocks', 'modelRequests', 'rendererRequests', 'freshHeldoutCases', 'automaticRetries')
    require(all(receipt[key] is False for key in false_fields)
            and all(type(receipt[key]) is int and receipt[key] == 0 for key in zero_fields),
            'scientific/flow/model/heldout/seed/retry gate changed')
    require(type(passport['sourceFiles']) is dict and type(passport['observerSources']) is dict
            and all(passport['sourceFiles'][key] == value for key, value in passport['observerSources'].items()),
            'observer source manifest')
    commands = passport['preflightCommands']
    executed = receipt['preflightCommands']
    require(type(commands) is list and type(executed) is list and len(commands) == len(executed) == 30,
            'complete source-proof Git population')
    argv = []
    for expected, actual in zip(commands, executed):
        arguments = expected['arguments']
        require(type(arguments) is list and arguments and all(type(value) is str for value in arguments), 'Git arguments')
        command = ['git', *[value.replace('{SOURCE}', passport['sourceCommit']) for value in arguments]]
        require(typed_equal(actual['command'], command) and actual['stdoutSha256'] == expected['stdoutSha256']
                and type(actual['exitCode']) is int and actual['exitCode'] == 0,
                'actual source-bound Git command/result differs')
        require(real(actual['startedMonotonic'], 'Git actual start')
                <= real(actual['completedMonotonic'], 'Git actual completion')
                <= real(receipt['originMonotonic'], 'phase origin'), 'Git proof extends into measured phase')
        argv.append(command)
    final = receipt['registryFinal']
    require(final['schema'] == 'aijade.process-lifecycle-final.v1'
            and final['status'] == 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT'
            and final['scopeClosed'] is True and all(final[key] == [] for key in (
                'unresolvedFiniteLeases', 'launchRefusals', 'launchRefusalArtifacts',
                'localDiscoveredIdentities', 'unleasedDiscoveredIdentities', 'remainingIdentities')),
            'terminal registry is unknown/adverse/not closed')
    return dict(sourceCommit=passport['sourceCommit'], sourceFiles=passport['sourceFiles'],
                observerSources=passport['observerSources'], processPolicySha256=passport['policySha256'],
                processPolicyPath=passport['policyPath'], runScriptPath='experiments/ch7/run_equal_load.py',
                runScriptSha256=passport['runnerSha256'], sourceProofGitCommands=argv,
                executedGitCommands=executed, toolExecutableSha256=TOOL_SHA256,
                completeServices=receipt['services'], registryFinal=final,
                controllerProcess=controller, controllerSysExecutable=passport['pythonPath'],
                controllerExecutableSha256=passport['pythonSha256'], lifecycleJournalStable=True,
                lifecycleJournalSha256=receipt['lifecycleJournalSha256'],
                lifecycleJournalBytes=integer(receipt['lifecycleJournalBytes'], 'complete journal bytes'),
                lifecycleScopeId=final['scopeId'], tailPhaseEnteredMonotonic=receipt['tailPhaseEnteredMonotonic'],
                tailThreadJoined=receipt['tailThreadJoined'], tailThreadJoinedMonotonic=receipt['tailThreadJoinedMonotonic'],
                scope={key: receipt[key] for key in false_fields + zero_fields})


def verify_sources(repo, context, policy_raw):
    source = context['sourceCommit']
    require(type(source) is str and len(source) == 40, 'frozen engineering source identity')
    proof = context['sourceFiles']
    require(type(proof) is dict and set(PRESERVED_SOURCES) <= set(proof), 'complete expected source manifest')
    actual = []
    for name, expected in proof.items():
        path = repo / relative(name)
        require(path.is_file() and not path.is_symlink(), 'source file missing/nonregular')
        raw = path.read_bytes()
        require(sha(raw) == expected and raw == git(repo, 'show', source + ':' + name), 'frozen source differs: ' + name)
        if name in PRESERVED_SOURCES:
            require(expected == PRESERVED_SOURCES[name], 'protected oracle/legacy source was changed: ' + name)
        actual.append(dict(path=name, sha256=expected, sizeBytes=len(raw)))
    require(context['processPolicySha256'] == sha(policy_raw)
            and policy_raw == git(repo, 'show', source + ':' + context['processPolicyPath']), 'frozen policy bytes')
    run_script = relative(context['runScriptPath'])
    require(str(run_script) in proof and proof[str(run_script)] == context['runScriptSha256'], 'runner source manifest binding')
    return actual


def verify_controller_identity(state, context, final_view):
    """Bind receipt birth/parent and frozen interpreter to actual journal self."""
    controller = context['controllerProcess']
    require(type(controller['pid']) is int and controller['pid'] > 1
            and type(controller['parentPid']) is int and controller['parentPid'] >= 0,
            'controller PID/parent types')
    bound = dict(pid=controller['pid'],
                 createTimeMicros=round(real(controller['createTime'], 'controller birth') * 1000000),
                 parentPid=controller['parentPid'])
    first = state['events'][0]
    require(first['event'] == 'CONTROLLER_REGISTER'
            and typed_equal(first['writer'], bound)
            and typed_equal(first['data']['identity'], bound)
            and first['data']['executableSha256'] == context['controllerExecutableSha256']
            and typed_equal(final_view['controllerIdentity'], bound)
            and typed_equal(state['scopes'][context['lifecycleScopeId']]['controllerIdentity'], bound),
            'controller PID/kernel birth/parent/interpreter differs from actual registered writer')
    return bound


def full_raw_replay(root, repo, context, policy, journal, rows, audit, guard):
    """Replay all actual rows with the unchanged independent full parser."""
    source = context['sourceCommit']
    policy_sha = context['processPolicySha256']
    complete = audit._replay(journal, source, policy_sha)
    require(not complete['launchRefusals'], 'verified launch refusal remains adverse')
    require(not list(root.rglob('launch-refused-*.json')), 'fallback refusal artifact remains adverse')
    finite = [v for v in complete['leases'].values() if v['role'] == 'finite']
    require(all(v['releaseSeq'] is not None and v['waitSeq'] is not None
                and type(v['exitCode']) is int and v['exitCode'] == 0
                and v['absence'] is not None for v in finite), 'finite task unresolved/nonzero/not reaped')
    require(all(v['identityWitnessKind'] == 'PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD'
                and v['shimSha256'] == policy['lifecycle']['execShimSha256'] for v in finite), 'finite parent-kernel/shim witness')
    require(all(v['closeSeq'] is not None for v in complete['scopes'].values()), 'persistent scope not closed')
    require(not complete['discovered'], 'unexpected discovered descendants in this declared no-work equal-load run')
    by_scope = {}
    native_ids = set()
    sample_ids = set()
    decisions = Counter()
    errors = []
    started = time.monotonic()
    for index, outer in enumerate(rows):
        try:
            obs = outer['processObservation']
            # This frozen helper invokes the complete cold guard and then
            # checks its actual outer envelope. No producer cursor is supplied.
            decision = audit._validate_sample(outer, policy, journal)
            decisions[decision['status']] += 1
            require(decision['status'] == obs['status'] == 'PASS' and decision['blockers'] == obs['blockers'] == [],
                    'raw process/native/API guard adverse or differs')
            require(outer['processPolicySha256'] == policy_sha
                    and outer['observerModuleSha256'] == context['sourceFiles']['experiments/ch7/mac_process_guard_v3.py']
                    and typed_equal(outer['observerSources'], context['observerSources']), 'original sample source/policy binding')
            sid = audit.sample_id(outer)
            require(sid not in sample_ids, 'duplicate original sample ID')
            sample_ids.add(sid)
            view = obs['lifecycle']
            audit._no_refusal_artifacts(view)
            size = integer(view['journalBytes'], 'actual journal prefix size')
            require(0 < size <= len(journal) and journal[:size].endswith(b'\n'), 'missing/truncated prefix')
            prefix = journal[:size]
            require(sha(prefix) == view['journalSha256'], 'actual prefix SHA differs')
            state = audit._replay(prefix, source, policy_sha)
            require(integer(view['lastSequence'], 'actual view sequence type') == len(state['events'])
                    and state['runId'] == view['runId'], 'prefix context differs')
            scope = state['scopes'][view['scopeId']]
            require(scope['closeSeq'] is None and scope['controllerIdentity'] == view['controllerIdentity'], 'sample scope absent/closed/changed')
            key = (state['runId'], view['scopeId'], *audit.identity(view['controllerIdentity']))
            previous = by_scope.get(key)
            if previous is not None:
                require(size >= previous['bytes'] and outer['monotonicSeconds'] >= previous['completed'],
                        'same-scope prefix regression/overlapping calls')
            by_scope[key] = dict(bytes=size, completed=outer['observationCompletedMonotonic'])
            frames = audit._raw_frames(obs, policy)
            refs = sorted({audit.node_identity(node) for frame in frames for node in frame['nodes']})
            require(typed_equal(view['referencedIdentities'], [list(v) for v in refs]), 'native referenced identity closure')
            projected = [v for v in state['leases'].values() if v['absence'] is None or audit.identity(v['identity']) in refs]
            require(typed_equal(view['leases'], projected), 'active/reference lease view differs from full independent replay')
            require(typed_equal(view['controllers'], [v['leaseId'] for v in projected if v['identity'] == view['controllerIdentity']]),
                    'controller lease view differs')
            for frame in frames:
                lease_id = audit._native_lease(frame, state, view['controllerIdentity'], policy)
                require(type(lease_id) is str and len(lease_id) == 32 and lease_id not in native_ids,
                        'native capture lease absent/reused')
                native_ids.add(lease_id)
            api = obs['evidence']['api']
            body = base64.b64decode(api['emptyBodyBase64'], validate=True)
            require(decode(body) == {'models': []} and sha(body) == api['bodySha256'], 'sampled API is not explicitly empty')
            if index < 360:
                require(obs['ownedRoots'] == obs['ownedProcesses'] == decision['ownedProcesses'] == []
                        and type(outer['rssBytes']) is int and outer['rssBytes'] == decision['ownedRssBytes'] == 0,
                        'idle sample has unknown/nonempty research-owned RSS')
            else:
                require(type(obs['ownedRoots']) is list and len(obs['ownedRoots']) == 1
                        and type(outer['rssBytes']) is int and outer['rssBytes'] == decision['ownedRssBytes'],
                        'tail sample lacks exact owned-root RSS')
        except Exception as error:
            errors.append(dict(index=index, sampleId=outer.get('sampleId'), error=type(error).__name__ + ': ' + str(error),
                               traceback=traceback.format_exc()))
        if (index + 1) % 25 == 0 or index + 1 == len(rows):
            print(json.dumps(dict(stage='INDEPENDENT_FULL_RAW_REPLAY', samples=index + 1,
                                 errors=len(errors), seconds=time.monotonic() - started)), flush=True)
    require(not errors, 'full raw replay failed; retain errors: ' + json.dumps(errors, ensure_ascii=False))
    require(len(native_ids) == 2 * len(rows), 'native capture population')
    return complete, dict(samples=len(rows), guardDecisions=dict(decisions), nativeCaptures=len(native_ids),
                          scopes=len(by_scope), fullReplayErrors=errors)


def classify_tasks(repo, context, policy, state):
    tree = ast.parse((repo / 'experiments/ch7/mac_process_guard_v3.py').read_text())
    listener = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_read_listeners')
    commands = [ast.literal_eval(node) for node in ast.walk(listener) if isinstance(node, ast.List)
                and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == '/usr/sbin/lsof']
    require(len(commands) == 1, 'unique source-bound listener command')
    listener_sha = sha(canonical(commands[0]))
    native_sha = sha(canonical([policy['nativeHelper']['path']]))
    expected_git = Counter(sha(canonical(command)) for command in context['sourceProofGitCommands'])
    require(sum(expected_git.values()) == 30, 'expected preflight real Git command population')
    observed_git = Counter()
    git_leases = []
    kinds = Counter()
    for lease in state['leases'].values():
        if lease['role'] != 'finite':
            continue
        if lease['stageId'] == 'observer-native-census':
            require(lease['commandSha256'] == native_sha and lease['executableSha256'] == policy['nativeHelper']['sha256'],
                    'native command/helper identity')
            kinds['native'] += 1
        elif lease['commandSha256'] == listener_sha:
            require(lease['executableSha256'] == context['toolExecutableSha256']['lsof'], 'listener executable identity')
            kinds['listener'] += 1
        else:
            require(lease['executableSha256'] == context['toolExecutableSha256']['git'], 'undeclared finite executable')
            observed_git[lease['commandSha256']] += 1
            git_leases.append(lease)
            kinds['git'] += 1
    require(observed_git == expected_git, 'actual preflight Git argv multiplicity differs')
    require(len(git_leases) == len(context['executedGitCommands']) == 30, 'actual Git lease population')
    for lease, recorded in zip(git_leases, context['executedGitCommands']):
        require(lease['commandSha256'] == sha(canonical(recorded['command']))
                and recorded['startedMonotonic'] <= lease['readyMonotonic'] <= lease['registerMonotonic']
                <= lease['releaseMonotonic'] <= lease['reapedMonotonic'] <= recorded['completedMonotonic'],
                'actual Git launch/release/parent-wait time is not bound to recorded command')
    require(kinds['native'] == kinds['listener'] == 724, 'actual native/listener complete362 population')
    return dict(kinds, finite=sum(kinds.values()), actualParentWaitZero=sum(
        value['role'] == 'finite' and type(value['exitCode']) is int and value['exitCode'] == 0
        for value in state['leases'].values()))


def verify_services(rows, phase_events, tail_events, service_events, complete_services, origin):
    require(type(complete_services) is list and len(complete_services) == 362
            and len(service_events) == 362, 'complete service event/receipt population')
    written = {(event['phase'], event['globalIndex']): event for event in phase_events if event['event'] == 'sample-written'}
    require(len(written) == 360, 'phase event exact idle writer population')
    require(len(tail_events) == 2 and all(type(event) is dict
            and event['schema'] == 'aijade.ch7.equal-load-tail-event.v1'
            and event['event'] == 'sample-written' and event['phase'] == 'tail' for event in tail_events),
            'complete original tail writer event population/schema')
    written.update({('tail', event['globalIndex']): event for event in tail_events})
    require(len(written) == 362, 'duplicate/unbound original tail writer event')
    disk_fields = {'sampleId', 'globalIndex', 'phase', 'scheduledMonotonic', 'deadlineMonotonic',
                   'sampleStartedMonotonic', 'callbackStartedMonotonic',
                   'phaseEventWriteCompletedMonotonic', 'startLatenessSeconds'}
    receipt_fields = disk_fields | {'diagnosticWriteCompletedMonotonic', 'callbackCompletedMonotonic',
                                    'serviceCompletedMonotonic', 'fullServiceSeconds'}
    results = []
    ids = set()
    previous_completion = None
    for index, (row, event, completed) in enumerate(zip(rows, service_events, complete_services)):
        require(type(event) is dict and set(event) == disk_fields and type(completed) is dict
                and set(completed) == receipt_fields
                and typed_equal(event, {key: completed[key] for key in disk_fields}),
                'original service diagnostic differs from receipt extension')
        sid = row['sampleId']
        require(sid not in ids and event['sampleId'] == completed['sampleId'] == sid
                and type(event['globalIndex']) is int and type(completed['globalIndex']) is int
                and event['globalIndex'] == completed['globalIndex'] == index, 'service sample identity/order')
        ids.add(sid)
        require(type(row['globalIndex']) is int and row['globalIndex'] == index, 'raw original global index')
        target = origin + index * 2
        start = real(row['monotonicSeconds'], 'actual service start')
        captured = real(row['observationCompletedMonotonic'], 'actual observation completion')
        validating = real(row['validatorStartedMonotonic'], 'actual validation start')
        validated = real(row['validatorCompletedMonotonic'], 'actual validation completion')
        writing = real(row['writerStartedMonotonic'], 'actual raw write start')
        callback_started = real(event['callbackStartedMonotonic'], 'actual phase-event callback start')
        phase_write_completed = real(event['phaseEventWriteCompletedMonotonic'], 'actual phase-event flush return')
        diagnostic_completed = real(completed['diagnosticWriteCompletedMonotonic'], 'actual diagnostic flush return')
        callback_completed = real(completed['callbackCompletedMonotonic'], 'actual full event callback return')
        service_completed = real(completed['serviceCompletedMonotonic'], 'actual service diagnostic flush return')
        same(service_completed, callback_completed, 'actual callback return/service endpoint binding')
        same(event['scheduledMonotonic'], target, 'service fixed absolute 2-second target')
        same(event['sampleStartedMonotonic'], start, 'service actual start binding')
        same(event['startLatenessSeconds'], start - target, 'actual start lateness binding')
        same(completed['fullServiceSeconds'], service_completed - start, 'actual complete service duration')
        if index < 360:
            same(row['globalScheduledMonotonic'], target, 'fixed absolute 2-second schedule')
        else:
            require(type(row['phaseIndex']) is int and row['phaseIndex'] == index - 360,
                    'original tail fixed slot index')
            same(row['scheduledSeconds'], index * 2, 'tail absolute nominal seconds')
            same(row['elapsedSeconds'], start - origin - 720, 'tail actual elapsed without origin reset')
        same(row['observationDurationSeconds'], captured - start, 'actual observation duration')
        require(0 <= start - target <= .5, 'engineering scheduled-start lateness exceeds0.5seconds')
        require(row['streamValidationStatus'] == 'PASS' and 'streamValidationError' not in row, 'streaming acceptance adverse')
        phase = 'settling' if index < 300 else 'admission' if index < 360 else 'tail'
        require(row['phase'] == event['phase'] == completed['phase'] == phase, 'actual engineering phase label')
        original = written[(phase, index)]
        require(original['sampleId'] == sid, 'original writer sample binding')
        written_at = real(original['writerCompletedMonotonic'], 'original actual raw writer completion')
        same(original['monotonicSeconds'], written_at, 'original writer event actual time')
        for key in ('validatorStartedMonotonic', 'validatorCompletedMonotonic', 'writerStartedMonotonic'):
            same(original[key], row[key], 'writer event/raw actual clock')
        require(start <= captured <= validating <= validated <= writing <= written_at
                <= callback_started <= phase_write_completed <= diagnostic_completed <= callback_completed
                <= service_completed, 'full-service actual processing chronology')
        require(service_completed - start <= 2, 'engineering complete service exceeds2seconds')
        deadline = origin + (600 if index < 300 else 720 if index < 360 else 724)
        same(event['deadlineMonotonic'], deadline, 'service fixed phase deadline')
        require(service_completed <= deadline, 'complete service crosses fixed phase deadline')
        if previous_completion is not None:
            require(previous_completion <= start and 0 < start - rows[index - 1]['monotonicSeconds'] <= 3,
                    'service overlap/actual global gap')
        previous_completion = service_completed
        results.append(dict(sampleId=sid, globalIndex=index, phase=phase, nominal=target - origin,
                            start=start - origin, fullServiceSeconds=service_completed - start,
                            latenessSeconds=start - target, completion=service_completed - origin))
    return results


def main(args):
    root = args.root.resolve()
    repo = args.repo.resolve()
    output = args.output.resolve()
    require(os.path.commonpath((str(BASE), str(output))) == str(BASE), 'output must remain in AIJADE')
    require(not output.exists() and root not in output.parents, 'never overwrite or add the audit to original run')
    before = file_table(root)
    require(set(FILES.values()) <= set(before), 'missing required equal-load original files')
    receipt = read(root / FILES['receipt'])
    context = load_protocol(args, receipt)
    policy_raw = (root / FILES['policy']).read_bytes()
    policy = decode(policy_raw)
    proof = verify_sources(repo, context, policy_raw)
    journal = (root / FILES['journal']).read_bytes()
    require(journal.endswith(b'\n') and len(journal) <= 16 * 1024**2, 'journal boundary/cap')
    require(sha(journal) == context['lifecycleJournalSha256'] and len(journal) == context['lifecycleJournalBytes'],
            'final closed journal bytes')
    settling = jsonl(root / FILES['settling'])
    admission = jsonl(root / FILES['admission'])
    tail = jsonl(root / FILES['tail'])
    phase_events = jsonl(root / FILES['phaseEvents'])
    service_events = jsonl(root / FILES['serviceEvents'])
    tail_events = jsonl(root / FILES['tailEvents'])
    require((len(settling), len(admission), len(tail)) == (300, 60, 2), 'complete300+60+2 original population')
    rows = settling + admission + tail
    preflight = read(root / FILES['preflight'])
    sys.path.insert(0, str(repo / 'experiments/ch7'))
    import lifecycle_audit as audit
    import mac_process_guard_v3 as guard
    require(file_sha(Path(audit.__file__)) == FULL_AUDITOR_SHA256, 'unoptimized independent auditor changed')
    require(file_sha(Path(guard.__file__)) == context['sourceFiles']['experiments/ch7/mac_process_guard_v3.py'], 'loaded frozen guard differs')
    state, raw_result = full_raw_replay(root, repo, context, policy, journal, rows, audit, guard)
    checkpoint = output.with_name(output.stem + '-full-raw-replay.json')
    require(not checkpoint.exists(), 'retain earlier complete raw-replay checkpoint')
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps(dict(schema='aijade.ch7.equal-load-full-replay-checkpoint.v1',
        status='COMPLETE_ORIGINAL_RAW_REPLAY_PASS', inputFiles=before, sourceFiles=proof,
        passportSha256=file_sha(args.passport), auditScriptSha256=file_sha(Path(__file__)),
        rawReplay=raw_result, journalSha256=sha(journal), journalBytes=len(journal)), indent=2) + '\n')
    actual_finite = [value for value in state['leases'].values() if value['role'] == 'finite']
    require(typed_equal(context['registryFinal']['knownFiniteLeases'], actual_finite),
            'terminal finite population differs from independent complete journal replay')
    final_view = context['registryFinal']['lifecycleView']
    require(integer(final_view['journalBytes'], 'terminal journal prefix byte type') == len(journal)
            and final_view['journalSha256'] == sha(journal)
            and integer(final_view['lastSequence'], 'terminal journal sequence type') == len(state['events'])
            and final_view['runId'] == state['runId']
            and final_view['scopeId'] == context['lifecycleScopeId'], 'terminal registry prefix differs')
    bound_controller = verify_controller_identity(state, context, final_view)
    tasks = classify_tasks(repo, context, policy, state)
    continuity = audit.verify_continuity(preflight['phases'], {'settling': settling, 'admission': admission},
                                         phase_events, policy=policy, lifecycle_journal=journal)
    origin = real(receipt['originMonotonic'], 'actual global origin')
    same(origin, preflight['schedule']['originMonotonic'], 'actual global origin binding')
    services = verify_services(rows, phase_events, tail_events, service_events, context['completeServices'], origin)
    try:
        idle_result = audit.verify_lifecycle(journal, settling + admission,
            source_commit=context['sourceCommit'], policy_sha256=context['processPolicySha256'],
            policy=policy, controller=receipt['controllerProcess'])
        raise ValueError('unexpected runtime-only acceptance of unloaded roots: ' + repr(idle_result))
    except Exception as error:
        idle_domain = dict(error=type(error).__name__ + ': ' + str(error), traceback=traceback.format_exc())
        require('runtime must have one exact local persistent root' in str(error), 'unexpected runtime-only idle predicate result')
    entered = real(context['tailPhaseEnteredMonotonic'], 'actual engineering tail entry')
    admission_end = preflight['phases']['admission']['phaseClock']['endMonotonic']
    require(admission_end <= entered <= tail[0]['monotonicSeconds']
            and 0 <= entered - admission_end <= 3
            and 0 < tail[0]['monotonicSeconds'] - admission[-1]['monotonicSeconds'] <= 3,
            'actual idle/tail handoff gap or order')
    require(real(context['completeServices'][359]['callbackCompletedMonotonic'], 'last idle complete callback return') <= entered,
            'tail starts before last admission sample event callback')
    needs_ancestry_context = any(event['event'] in ('DISCOVER', 'ABSENCE', 'DISCOVER_ABSENCE') for event in state['events'])
    tail_result = audit.verify_lifecycle(journal, tail, source_commit=context['sourceCommit'],
        policy_sha256=context['processPolicySha256'], policy=policy, controller=receipt['controllerProcess'],
        require_cleanup=True, scope_id=context['lifecycleScopeId'],
        ancestry_samples=settling + admission if needs_ancestry_context else None, ancestry_journal=journal)
    require(context['tailThreadJoined'] is True and real(context['tailThreadJoinedMonotonic'], 'actual tail join')
            >= services[-1]['completion'] + origin, 'tail thread not actually joined after complete service')
    require(before == file_table(root) and all(file_sha(repo / row['path']) == row['sha256'] for row in proof),
            'original artifact/source bytes changed during independent audit')
    report = dict(schema='aijade.ch7.prefix-equal-load-independent-audit.v1',
        status='ENGINEERING_EQUAL_LOAD_RAW_AUDIT_PASS_NOT_QUALIFIED', checkedAt=datetime.now(timezone.utc).isoformat(),
        sourceCommit=context['sourceCommit'], passportSha256=file_sha(args.passport), auditScriptSha256=file_sha(Path(__file__)),
        inputFiles=before, sourceFiles=proof, rawReplay=raw_result, continuity=continuity,
        fullRawReplayCheckpoint=dict(path=str(checkpoint), sha256=file_sha(checkpoint)),
        idleRuntimeApiDomainRefusal=idle_domain, tailRuntimeEvidenceAudit=tail_result, managedTasks=tasks,
        controllerIdentity=bound_controller, controllerSysExecutable=context['controllerSysExecutable'],
        controllerExecutableSha256=context['controllerExecutableSha256'], lifecycleJournalStable=True,
        parentControllerTerminalEvidence='NOT_SUPPLIED_NOT_CHECKED; parent-launcher verification is outside this audit',
        tailAncestryContextRequired=needs_ancestry_context,
        services=services, numbers=dict(samples=len(rows), settlingSamples=300, admissionSamples=60, tailSamples=2,
            nativeCaptures=raw_result['nativeCaptures'], finiteTasks=tasks['finite'], parentWaitZero=tasks['actualParentWaitZero'],
            maximumFullServiceSeconds=max(v['fullServiceSeconds'] for v in services),
            maximumLatenessSeconds=max(v['latenessSeconds'] for v in services),
            lastServiceCompletedSeconds=services[-1]['completion']),
        scope=context['scope'], noNewObservation=True, independentHumanReview=False,
        interpretation='Engineering equal-load identity/clock/raw-evidence audit only; no formal admission, complete backend qualification, known-case result, model request, renderer, seed or held-out observation.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(status=report['status'], path=str(output), sha256=file_sha(output))), flush=True)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--passport', type=Path, required=True)
    parser.add_argument('--passport-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    try:
        raise SystemExit(main(parser.parse_args()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
