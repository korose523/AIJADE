#!/usr/bin/env python3
"""Run two independently isolated known-case blocks after a verified reply and freeze."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import signal
from pathlib import Path
import subprocess
import sys

from compare_known_repeats import COMPLETE, EMPTY_FIELDS, instant
from finite_construction_binding import decode, exact_int, full_commit, full_sha, qualified_backend, typed_equal
from finite_runtime import PROJECT_ROOT, require, safe_relative, validate_build, validate_owned_registry
from prepare_known_repeats import IDENTITY_SCHEMA, INPUT_NAMES, ROOT, closing_evidence, known_inputs, slots, worklist


PREFIX = 'experiments/ch7/mac-known-repeats-qualification/'
DECISION_PATH = PREFIX + 'decision.json'
BUILD_PATH = PREFIX + 'frozen-build.json'
APPROVAL_SCHEMA = 'aijade.ch7.known-repeat-approval.v1'
PLAN_SCHEMA = 'aijade.ch7.known-repeat-execution-plan.v1'
CONFIG_SCHEMA = 'aijade.ch7.known-repeat-local-config.v1'
DECISION_SCHEMA = 'aijade.ch7.known-repeat-decision.v1'
LAUNCH_SCHEMA = 'aijade.ch7.known-repeat-launch-inputs.v1'
RECEIPT_SCHEMA = 'aijade.ch7.known-repeat-launch-receipt.v1'
APPROVED = 'SUPERVISOR_REPLY_CONFIRMED'
LAUNCHED = 'COMPLETE_KNOWN_REPEAT_LAUNCH'
REAL = 'PROSPECTIVE_KNOWN_MAC'
SYNTHETIC = 'OFFLINE_SYNTHETIC'
REPEATS = ('repeat-1', 'repeat-2')
TOOL_PATHS = ('docker', 'dotnet')
LOCAL_PATHS = ('client', 'model', 'assembly', 'buildManifest', 'godot', 'realGodot', 'sandboxProfile')
RESOURCE_FIELDS = ('maxOwnedRssBytes', 'minAvailableBytes', 'maxSwapIncreaseBytes')
APPROVAL_HASHES = ('executionPlanSha256', 'qualificationPlanSha256', 'replySha256')


def digest(body):
    return sha256(body).hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        result = sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def read_file(root, name):
    root = Path(root).absolute()
    path = root / safe_relative(name)
    require(path.resolve() == path and path.is_file(), 'missing or redirected evidence: ' + name)
    return path.read_bytes()


def utc():
    return datetime.now(timezone.utc).isoformat()


def closed(value, fields, message):
    require(type(value) is dict and set(value) == set(fields), message)


def approval_record(body, expected_sha):
    require(digest(body) == full_sha(expected_sha), 'approval differs from the independently recorded digest')
    approval = decode(body)
    closed(approval, ('schema', 'status', 'implementationCommit', 'backend', *APPROVAL_HASHES),
           'approval fields are incomplete or unknown')
    require(approval['schema'] == APPROVAL_SCHEMA and approval['status'] == APPROVED,
            'confirmed supervisor reply is required')
    full_commit(approval['implementationCommit'])
    for name in APPROVAL_HASHES:
        full_sha(approval[name])
    qualified_backend(approval['backend'], closed=True)
    return approval


def parse_execution_plan(body):
    plan = decode(body)
    closed(plan, ('schema', 'purpose', 'repeats', 'conditionSlotsPerRepeat', 'watchdog', 'toolsSha256', 'databasePort'),
           'execution plan fields are incomplete or unknown')
    require(plan['schema'] == PLAN_SCHEMA and plan['purpose'] == 'qualification_only', 'wrong known-repeat scope')
    exact_int(plan['repeats'], 2, 'known repeats')
    exact_int(plan['conditionSlotsPerRepeat'], 20, 'condition slots per repeat')
    validate_runtime_settings(plan)
    return plan


def validate_runtime_settings(plan):
    """Validate explicitly frozen tools and watchdog limits for a finite block."""
    require(type(plan['databasePort']) is int and 1 <= plan['databasePort'] <= 65535, 'invalid local database port')
    watchdog = plan['watchdog']
    closed(watchdog, ('blockWallSeconds', 'rendererTimeoutSeconds', 'sustainedResourceSeconds',
                      'parentAllowanceSeconds', 'shutdownGraceSeconds', *RESOURCE_FIELDS),
           'operational watchdog settings must be explicit')
    for key in ('blockWallSeconds', 'rendererTimeoutSeconds', 'sustainedResourceSeconds',
                'parentAllowanceSeconds', 'shutdownGraceSeconds'):
        require(type(watchdog[key]) is int and watchdog[key] > 0, 'positive integer required: ' + key)
    require(watchdog['rendererTimeoutSeconds'] <= watchdog['blockWallSeconds']
            and watchdog['sustainedResourceSeconds'] <= watchdog['blockWallSeconds'],
            'renderer or resource watchdog exceeds the block limit')
    for key in RESOURCE_FIELDS:
        require(watchdog[key] is None or (type(watchdog[key]) is int and watchdog[key] >= 0),
                'invalid approved resource threshold: ' + key)
    closed(plan['toolsSha256'], ('python', *TOOL_PATHS), 'runtime executable hashes are incomplete')
    for value in plan['toolsSha256'].values():
        full_sha(value)


def git(*args):
    return subprocess.check_output(['git', '--no-replace-objects', *args], cwd=ROOT)


def local_path(value, workspace, directory=False):
    path = Path(value)
    require(path.is_absolute() and path.resolve() == path and path.is_relative_to(workspace),
            'exact project-local path required')
    require(path.is_dir() if directory else path.is_file(), 'missing project file or directory: ' + path.name)
    return path


def renderer_sources(path):
    return {str(file.relative_to(path)): file_digest(file) for file in path.rglob('*')
            if file.is_file() and not {'.git', '.svn', '.godot', 'bin', 'obj', '__pycache__'} & set(file.relative_to(path).parts)}


def live_configuration(args):
    """Validate supplied bytes, Q/B, tools and original backend before creating output."""
    workspace = PROJECT_ROOT.resolve()
    require(sys.flags.optimize == 0, 'assertions must remain enabled for the finite block engine')
    approval_body = local_path(args.approval, workspace).read_bytes()
    approval = approval_record(approval_body, args.expected_approval_sha256)
    for field, source in (('replySha256', args.original_reply), ('qualificationPlanSha256', args.qualification_plan)):
        body = local_path(source, workspace).read_bytes()
        require(bool(body) and digest(body) == approval[field], 'private original bytes differ: ' + field)
    require(sys.platform == 'darwin', 'the Mac qualification requires a Darwin host')
    require(sys.version_info >= (3, 11), 'the actual finite block requires Python 3.11 or newer')
    import psutil
    require(psutil.__version__ == '7.2.2', 'the actual finite block requires psutil 7.2.2')
    q = approval['implementationCommit']
    require(git('rev-parse', 'HEAD').decode().strip() == q and not git('status', '--porcelain'),
            'launch from the clean, approved Q checkout')
    decision_body = git('show', q + ':' + DECISION_PATH)
    require(read_file(ROOT, DECISION_PATH) == decision_body, 'working decision differs from approved Q')
    decision = decode(decision_body)
    closed(decision, ('schema', 'status', 'executionPlanPath', *APPROVAL_HASHES),
           'tracked decision marker fields are incomplete')
    require(decision['schema'] == DECISION_SCHEMA and decision['status'] == APPROVED,
            'Q must contain the confirmed reply marker')
    require(all(decision[key] == approval[key] for key in APPROVAL_HASHES),
            'approved materials differ from tracked decision')
    relative = safe_relative(decision['executionPlanPath'])
    require(relative.startswith(PREFIX), 'execution plan is outside the qualification decision')
    plan_body = git('show', q + ':' + relative)
    require(read_file(ROOT, relative) == plan_body and digest(plan_body) == approval['executionPlanSha256'],
            'actual execution plan differs from approval')
    plan = parse_execution_plan(plan_body)
    config = decode(local_path(args.config, workspace).read_bytes())
    closed(config, ('schema', 'buildFreezeCommit', 'dockerSocket', *LOCAL_PATHS, *TOOL_PATHS), 'local bindings are incomplete or unknown')
    require(config['schema'] == CONFIG_SCHEMA, 'unsupported local config')
    b = full_commit(config['buildFreezeCommit'])
    require(b != q, 'B must be a separate committed build freeze')
    git('merge-base', '--is-ancestor', q, b)
    paths = {key: local_path(config[key], workspace, directory=(key == 'client')) for key in LOCAL_PATHS}
    socket = Path(config['dockerSocket'])
    require(socket.is_absolute() and socket.resolve() == socket and socket.is_relative_to(workspace),
            'the Docker socket must be exact and within the project')
    paths['dockerSocket'] = socket
    for key in TOOL_PATHS:
        path = Path(config[key])
        require(path.is_absolute() and path.resolve() == path and path.is_file()
                and os.access(path, os.X_OK), 'explicit installed executable required: ' + key)
        paths[key] = path
    for key, path in {'python': Path(sys.executable).resolve(), **{key: paths[key] for key in TOOL_PATHS}}.items():
        require(file_digest(path) == plan['toolsSha256'][key], 'approved executable bytes changed: ' + key)
    require(all(os.access(paths[key], os.X_OK) for key in ('godot', 'realGodot')), 'Godot executables are not runnable')
    build = validate_build(paths['assembly'], paths['buildManifest'], q, ROOT, b, BUILD_PATH)
    for path in paths['client'].rglob('*'):
        require(not path.is_symlink(), 'prepared renderer contains a symbolic link')
    prepared = decode(read_file(paths['client'], 'aijade-prepared-renderer.json'))
    actual = {
        'modelSha256': file_digest(paths['model']),
        'realGodotSha256': file_digest(paths['realGodot']),
        'godotWrapperSha256': file_digest(paths['godot']),
        'sandboxProfileSha256': file_digest(paths['sandboxProfile']),
        'rendererSources': renderer_sources(paths['client']),
        'preparedRenderer': prepared,
        'binaries': build['files'],
        'buildManifestSha256': file_digest(paths['buildManifest']),
        'benchSha256': file_digest(ROOT / 'src/Aijade.Research/SkillBench/bench-data.json'),
        'earlierSourceFreezeSha256': file_digest(ROOT / 'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'),
        'databaseContainer': approval['backend']['databaseContainer'],
        'explicitDockerPath': str(paths['docker']),
    }
    require(typed_equal(qualified_backend(actual, closed=True), approval['backend']), 'approved backend identity differs')
    for name, expected in prepared['files'].items():
        require(digest(read_file(paths['client'], name)) == expected, 'prepared runtime file changed: ' + name)
    return approval, plan, ROOT / relative, b, paths


def known_material(implementation, scratch):
    prior = worklist(scratch)
    material = known_inputs(implementation, scratch)
    frozen_slots = [(item['caseId'], item['condition']) for item in prior['repeats'][0]['slots']]
    require(slots(decode(material['runtime-manifest.json'])) == frozen_slots, 'known condition order changed')
    return material


def launch_record(approval, approval_sha, b, material, mode):
    return dict(schema=LAUNCH_SCHEMA, launchMode=mode, approvalSha256=full_sha(approval_sha),
                implementationCommit=approval['implementationCommit'], buildFreezeCommit=full_commit(b),
                buildFreezePath=BUILD_PATH, backend=approval['backend'],
                knownInputHashes={key: digest(value) for key, value in material.items()},
                repeatDirectories=list(REPEATS), **{key: approval[key] for key in APPROVAL_HASHES})


def block_evidence(root, launch, index):
    """Check original terminal evidence before allowing another block to start."""
    body = read_file(root, 'receipt.json')
    receipt = decode(body)
    require(receipt['schema'] == 'aijade.ch7.finite-block-receipt.v1'
            and receipt['status'] == COMPLETE and receipt['reason'] is None, 'block terminal is incomplete')
    for key, expected in (('plannedPairs', 10), ('plannedCases', 20), ('completedCases', 20),
                          ('heldOutCases', 0), ('modelRequests', 0), ('blockIndex', 0)):
        exact_int(receipt[key], expected, key)
    for key in EMPTY_FIELDS:
        require(receipt[key] == [], 'block has adverse dispositions: ' + key)
    require(receipt['purpose'] == 'qualification_only' and receipt['conditionsMeasured'] == ['C1', 'C2']
            and receipt['codeCommit'] == launch['implementationCommit']
            and receipt['formalHardwareQualification'] is False, 'block terminal scope differs')
    for name in ('flow', 'renderer'):
        phase = receipt['phases'][name]
        exact_int(phase['exitCode'], 0, name + ' exit')
        require(instant(phase['startedAt']) <= instant(phase['endedAt']) <= instant(receipt['finishedAt']),
                'block phase clock is invalid')
    registry_body = read_file(root, 'owned-process-registry.json')
    require(digest(registry_body) == full_sha(receipt['ownedProcessRegistrySha256']), 'owned process registry differs')
    registry = decode(registry_body)
    samples = [decode(line) for line in read_file(root, 'telemetry.jsonl').splitlines()]
    validate_owned_registry(registry, samples)
    phases = {(receipt['phases'][name]['pid'], receipt['phases'][name]['createTime']) for name in ('flow', 'renderer')}
    registered = {(value['pid'], value['createTime']) for value in registry['explicitlyRegisteredIdentities']}
    require(len(phases) == 2 and phases <= registered, 'flow/renderer start identities escaped the process registry')
    identity = decode(read_file(root, 'input-identities.json'))
    require(all(identity[key] == launch[key] for key in ('executionPlanSha256', 'buildFreezeCommit', 'buildFreezePath')),
            'block identity differs from launch plan/build')
    require(identity['knownRepeatLaunchSha256'] == digest(encode(launch))
            and receipt['knownRepeatLaunchSha256'] == identity['knownRepeatLaunchSha256'],
            'block is not bound to this exact launch')
    exact_int(identity['knownRepeatIndex'], index, 'block launch index')
    exact_int(receipt['knownRepeatIndex'], index, 'terminal launch index')
    require(identity['codeCommit'] == identity['constructionFreezeCommit'] == launch['implementationCommit']
            and identity['purpose'] == 'qualification_only'
            and typed_equal(qualified_backend(identity), launch['backend']), 'block backend or source differs')
    require(digest(read_file(root, 'frozen-build.json')) == launch['backend']['buildManifestSha256'],
            'block build manifest bytes differ from launch')
    for name, expected in launch['knownInputHashes'].items():
        require(digest(read_file(root, name)) == expected, 'block did not consume the frozen known inputs: ' + name)
    runtime = decode(read_file(root, 'runtime-manifest.json'))
    cases = decode(read_file(root, 'cases.json'))
    require([(item['caseId'], item['condition']) for item in cases] == slots(runtime), 'block condition order was changed')
    require(all(type(item['gatewayAttempts']) is int and item['gatewayAttempts'] == 0 for item in cases),
            'block used a model or failed to record attempts')
    return digest(body)


def verify_launched_pair(root, approval_body, expected_approval_sha256):
    root = Path(root).absolute()
    approval = approval_record(approval_body, expected_approval_sha256)
    require(read_file(root, 'approval.json') == approval_body, 'private digest-only approval snapshot differs')
    launch_body = read_file(root, 'launch.json')
    launch = decode(launch_body)
    require(launch_body == encode(launch), 'noncanonical launch bytes')
    require(launch['schema'] == LAUNCH_SCHEMA and launch['launchMode'] in (REAL, SYNTHETIC)
            and launch['approvalSha256'] == expected_approval_sha256
            and launch['repeatDirectories'] == list(REPEATS) and launch['buildFreezePath'] == BUILD_PATH,
            'wrong launch preparation record')
    require(launch['implementationCommit'] == approval['implementationCommit']
            and typed_equal(launch['backend'], approval['backend'])
            and all(launch[key] == approval[key] for key in APPROVAL_HASHES), 'launch preparation differs from approval')
    full_commit(launch['buildFreezeCommit'])
    closed(launch['knownInputHashes'], INPUT_NAMES, 'wrong frozen input population')
    for key, expected in launch['knownInputHashes'].items():
        require(digest(read_file(root, 'inputs/' + key)) == full_sha(expected), 'parent frozen input was changed: ' + key)
    receipt = decode(read_file(root, 'receipt.json'))
    require(receipt['schema'] == RECEIPT_SCHEMA and receipt['status'] == LAUNCHED
            and receipt['launchSha256'] == digest(launch_body) and receipt['qualificationDetermined'] is False,
            'two-repeat launch lacks a complete terminal receipt')
    exact_int(receipt['completedRepeats'], 2, 'completed repeats')
    exact_int(receipt['plannedRepeats'], 2, 'planned repeats')
    require(len(receipt['repeats']) == 2, 'unexpected repeat receipt count')
    previous = instant(receipt['startedAt'])
    for i, (name, record) in enumerate(zip(REPEATS, receipt['repeats']), 1):
        exact_int(record['index'], i, 'repeat index')
        exact_int(record['exitCode'], 0, 'child exit')
        require(record['directory'] == name and record['blockReceiptSha256'] == block_evidence(root / name, launch, i)
                and record['logSha256'] == digest(read_file(root, name + '.log')), 'repeat closure differs from launch receipt')
        started, finished = instant(record['startedAt']), instant(record['finishedAt'])
        child = decode(read_file(root / name, 'receipt.json'))
        require(previous <= started <= instant(child['finishedAt']) <= finished <= instant(receipt['finishedAt'])
                and all(started <= instant(p['startedAt']) for p in child['phases'].values()),
                'repeat windows overlap or lack ordered terminal observations')
        previous = finished
    return launch, receipt


def write_receipt(root, value):
    with (root / '.receipt.tmp').open('xb') as stream:
        stream.write(encode(value))
    (root / '.receipt.tmp').replace(root / 'receipt.json')


def execute_repeats(root, material, launch, runner, *, approval_body):
    """Exclusive parent that runs each child once and retains any stop evidence."""
    approval_record(approval_body, launch['approvalSha256'])
    root.mkdir(mode=0o700)
    with (root / 'approval.json').open('xb') as stream:
        stream.write(approval_body)
    inputs = root / 'inputs'
    inputs.mkdir()
    for key, value in material.items():
        (inputs / key).write_bytes(value)
    body = encode(launch)
    (root / 'launch.json').write_bytes(body)
    state = dict(schema=RECEIPT_SCHEMA, status='RUNNING_KNOWN_REPEAT_LAUNCH',
                 launchSha256=digest(body), startedAt=utc(), completedRepeats=0,
                 plannedRepeats=2, qualificationDetermined=False, repeats=[])
    write_receipt(root, state)
    try:
        for i, name in enumerate(REPEATS, 1):
            record = dict(index=i, directory=name, startedAt=utc())
            state['repeats'].append(record)
            write_receipt(root, state)
            try:
                with (root / (name + '.log')).open('xb') as output:
                    record['exitCode'] = runner(i, output)
            except ChildStopped as error:
                record['exitCode'] = error.exit_code
                raise
            finally:
                record['finishedAt'] = utc()
                record['logSha256'] = digest(read_file(root, name + '.log'))
                if (root / name / 'receipt.json').is_file():
                    record['blockReceiptSha256'] = digest(read_file(root / name, 'receipt.json'))
            exact_int(record['exitCode'], 0, 'child exit')
            record['blockReceiptSha256'] = block_evidence(root / name, launch, i)
            identity = {key: launch[key] for key in ('implementationCommit', 'executionPlanSha256', 'backend')}
            closing_evidence(root / name, material, {'schema': IDENTITY_SCHEMA, **identity})
            state['completedRepeats'] += 1
            write_receipt(root, state)
        state['status'] = LAUNCHED
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError, KeyboardInterrupt, ChildStopped) as error:
        state.update(status='STOPPED_KNOWN_REPEAT_LAUNCH', reason=type(error).__name__ + ': ' + str(error))
    state['finishedAt'] = utc()
    write_receipt(root, state)
    return state


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--expected-approval-sha256', required=True)
    parser.add_argument('--original-reply', type=Path, required=True)
    parser.add_argument('--qualification-plan', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    return parser


class ChildStopped(RuntimeError):
    def __init__(self, reason, exit_code):
        super().__init__(reason)
        self.exit_code = exit_code


def wait_child(process, timeout, grace):
    try:
        return process.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        reason = 'approved parent watchdog expired' if isinstance(error, subprocess.TimeoutExpired) else 'parent interrupted'
        if process.poll() is None:
            process.terminate()
        try:
            exit_code = process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                process.kill()
            try:
                exit_code = process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                raise ChildStopped(reason + '; child absence unknown after forced stop', None) from error
            reason += '; forced stop after cleanup grace, descendant absence unverified'
        raise ChildStopped(reason, exit_code) from error


def run_child(args, index, output, watchdog):
    command = [sys.executable, '-B', str(ROOT / 'experiments/ch7/run_known_repeat_block.py'), '--index', str(index)]
    for key, value in vars(args).items():
        command += ['--' + key.replace('_', '-'), str(value)]
    process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    return wait_child(process, watchdog['blockWallSeconds'] + watchdog['parentAllowanceSeconds'],
                      watchdog['shutdownGraceSeconds'])


def main():
    args = arguments().parse_args()
    try:
        approval, plan, _, b, _ = live_configuration(args)
        scratch = local_path(args.scratch, PROJECT_ROOT.resolve(), directory=True)
        output = args.output
        local_path(output.parent, PROJECT_ROOT.resolve(), directory=True)
        require(output.resolve() == output and not output.exists(), 'output exists or is redirected; no resume')
        material = known_material(approval['implementationCommit'], scratch)
        launch = launch_record(approval, args.expected_approval_sha256, b, material, REAL)
        def interrupt(signum, frame):
            raise KeyboardInterrupt(f'launch interrupted by signal {signum}')

        previous_handler = signal.signal(signal.SIGTERM, interrupt)
        try:
            state = execute_repeats(output, material, launch,
                                    lambda i, stream: run_child(args, i, stream, plan['watchdog']),
                                    approval_body=args.approval.read_bytes())
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
        if state['status'] == LAUNCHED:
            verify_launched_pair(output, args.approval.read_bytes(), args.expected_approval_sha256)
        print(json.dumps({'status': state['status'], 'completedRepeats': state['completedRepeats'],
                          'qualificationDetermined': False, 'reason': state.get('reason')}))
        return 0 if state['status'] == LAUNCHED else 1
    except (OSError, ValueError, TypeError, ImportError, KeyError, AttributeError, subprocess.SubprocessError) as error:
        print(f'Launch refused: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
