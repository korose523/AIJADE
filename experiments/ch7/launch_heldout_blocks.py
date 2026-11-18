#!/usr/bin/env python3
"""Run the separately frozen four-block Chapter 7 measurement on the accepted Mac backend."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from xml.etree.ElementTree import ParseError

from compare_known_repeats import COMPLETE, EMPTY_FIELDS, instant
from finite_construction_binding import (
    KNOWN_REPEAT_BINDING_SCHEMA, SIDECAR, current_backend_before_measurement,
    decode, exact_int, full_commit, full_sha, qualified_backend, typed_equal,
    verify_binding,
)
from finite_runtime import PROJECT_ROOT, require, validate_build, validate_owned_registry, validate_repository_binding
from finite_inputs import BANK
from finite_validate import verify
from known_repeat_acceptance import ACCEPTANCE, BUILD, EVIDENCE, FREEZE, MEASUREMENT_LAUNCHER, PREFIX, ancestor, git, raw
from launch_known_repeats import (
    CONFIG_SCHEMA, LOCAL_PATHS, TOOL_PATHS, ChildStopped, closed, digest, encode,
    file_digest, local_path, read_file, utc, validate_runtime_settings, wait_child, write_receipt,
)
from prepare_known_repeats import INPUT_NAMES, closing_evidence
from run_known_repeat_block import verify_local_database


PURPOSE = 'confirmed_finite_heldout'
PLAN_SCHEMA = 'aijade.ch7.heldout-measurement-plan.v1'
LAUNCH_SCHEMA = 'aijade.ch7.heldout-measurement-launch.v1'
RECEIPT_SCHEMA = 'aijade.ch7.heldout-measurement-receipt.v1'
REAL = 'PROSPECTIVE_HELDOUT_MAC'
SYNTHETIC = 'OFFLINE_SYNTHETIC'
BLOCKS = ('block-1', 'block-2', 'block-3', 'block-4')
INPUT_PREFIX = 'experiments/ch7/finite-heldout/'
SCOPE = {'blocks': 4, 'pairsPerBlock': 10, 'conditionsPerBlock': 20}
ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, AssertionError,
          subprocess.SubprocessError, ParseError, KeyboardInterrupt, ChildStopped)


def preflight_inputs(repo, implementation, inputs, data_manifest, model_sha, plan, expected_plan_sha,
                     *, check_backend=None):
    """Verify Git publications, exact 40-pair derivation and the frozen measurement plan."""
    repo = Path(repo).resolve()
    q = full_commit(implementation)
    d = full_commit(git(repo, 'rev-parse', 'HEAD').decode().strip())
    require(d != q, 'measurement requires separate published input data')
    inputs_path = local_path(inputs, repo, directory=True).relative_to(repo).as_posix()
    plan_path = local_path(plan, repo).relative_to(repo).as_posix()
    manifest_path = local_path(data_manifest, repo).relative_to(repo).as_posix()
    require(all(name.startswith(INPUT_PREFIX) for name in (inputs_path, plan_path, manifest_path)),
            'use the finite held-out publication directory')
    publication = validate_repository_binding(repo, q, d, manifest_path, require_head=True,
                                              additional_data_prefixes=(PREFIX,))

    def published(name):
        require(name in publication['addedDataPaths'], 'missing from the data publication: ' + name)
        body = read_file(repo, name)
        require(body == raw(repo, d, name), 'working data differs from the published bytes: ' + name)
        return body

    plan_body = published(plan_path)
    plan_sha = digest(plan_body)
    require(plan_sha == full_sha(expected_plan_sha), 'measurement plan differs from independently pinned SHA256')
    settings = decode(plan_body)
    closed(settings, ('schema', 'purpose', 'implementationCommit', 'inputsPath',
                      'constructionBindingSha256', 'buildFreezeCommit', 'qualifiedBackendSha256',
                      'watchdog', 'toolsSha256', 'databasePort', *SCOPE), 'incomplete or unknown measurement settings')
    require(settings['schema'] == PLAN_SCHEMA and settings['purpose'] == PURPOSE
            and settings['implementationCommit'] == q and settings['inputsPath'] == inputs_path,
            'measurement plan has a different scope, implementation or input root')
    for key, value in SCOPE.items():
        exact_int(settings[key], value, key)
    validate_runtime_settings(settings)

    binding_body = published(inputs_path + '/' + SIDECAR)
    require(digest(binding_body) == full_sha(settings['constructionBindingSha256']),
            'measurement plan uses a different construction binding')
    binding = decode(binding_body)
    require(binding['schema'] == KNOWN_REPEAT_BINDING_SCHEMA, 'successor construction binding required')
    cf = full_commit(binding['constructionFreezePublicationCommit'])
    a = full_commit(binding['acceptancePublicationCommit'])
    require(d != cf and ancestor(repo, cf, d), 'input publication must descend from the separate construction freeze')
    freeze = verify_binding(repo, q, binding, model_sha)
    require(MEASUREMENT_LAUNCHER in freeze['sources'], 'measurement launcher was not frozen with the approved Q source')
    accepted = decode(raw(repo, a, ACCEPTANCE))
    b = full_commit(accepted['buildFreezeCommit'])
    require(b == settings['buildFreezeCommit'], 'measurement plan differs from the accepted B commit')
    backend = freeze['qualifiedBackend']
    require(digest(encode(backend)) == full_sha(settings['qualifiedBackendSha256']),
            'measurement plan differs from the qualified backend')
    for commit, name in ((b, BUILD), (a, ACCEPTANCE), (cf, FREEZE)):
        require(published(name) == raw(repo, commit, name), 'published evidence changed after its own freeze: ' + name)
    for name, evidence in accepted['evidence'].items():
        require(digest(published(EVIDENCE + name)) == evidence['sha256'],
                'published qualification evidence changed: ' + name)
    if check_backend is not None:
        check_backend(q, b, backend, settings)

    inputs = repo / inputs_path
    bundle = {}
    for entry in inputs.rglob('*'):
        require(not entry.is_symlink() and (entry.is_file() or entry.is_dir()),
                'linked or special item in the frozen input directory')
        if entry.is_file():
            name = entry.relative_to(inputs).as_posix()
            bundle[name] = published(inputs_path + '/' + name)
    declared = {name.removeprefix(inputs_path + '/') for name in publication['addedDataPaths']
                if name.startswith(inputs_path + '/')}
    require(set(bundle) == declared, 'input publication closure differs from local files')
    suitability = verify(repo, inputs)
    require(typed_equal(decode(bundle['suitability-acceptance.json']), suitability), 'recorded suitability differs from exact derivation')

    bank_body = read_file(repo, BANK)
    require(bank_body == raw(repo, q, BANK) == raw(repo, d, BANK), 'held-out candidate bank differs from Q')
    block_hashes = [{'selection.json': digest(bank_body),
                     'runtime-manifest.json': digest(bundle[block + '/runtime-manifest.json']),
                     'scoring-manifest.json': digest(bundle[block + '/scoring-manifest.json'])} for block in BLOCKS]
    return dict(schema=LAUNCH_SCHEMA, purpose=PURPOSE, implementationCommit=q, repositoryCommit=d,
                buildFreezeCommit=b, buildFreezePath=BUILD, backend=backend, executionPlanSha256=plan_sha,
                executionPlanPath=plan_path, inputsPath=inputs_path, inputHashes=block_hashes,
                constructionBindingSha256=digest(binding_body), acceptancePublicationCommit=a,
                constructionFreezePublicationCommit=cf, suitabilitySha256=digest(bundle['suitability-acceptance.json']),
                dataPublicationManifestPath=manifest_path,
                dataPublicationManifestSha256=publication['dataPublicationManifestSha256'],
                operationalWatchdog=settings['watchdog'], **SCOPE)


def block_evidence(root, launch, index, material):
    """Validate the original journal, handoff, owned processes, and database cleanup."""
    terminal = decode(read_file(root, 'receipt.json'))
    require(terminal['schema'] == 'aijade.ch7.finite-block-receipt.v1'
            and terminal['status'] == COMPLETE and terminal['reason'] is None
            and terminal['purpose'] == PURPOSE and terminal['conditionsMeasured'] == ['C1', 'C2']
            and terminal['formalHardwareQualification'] is False, 'incomplete or wrong-scope block terminal')
    for name, expected in (('blockIndex', index), ('heldoutLaunchIndex', index), ('plannedPairs', 10),
                           ('plannedCases', 20), ('completedCases', 20), ('heldOutCases', 10), ('modelRequests', 0)):
        exact_int(terminal[name], expected, name)
    for name in EMPTY_FIELDS:
        require(terminal[name] == [], 'block has adverse dispositions: ' + name)

    identity = decode(read_file(root, 'input-identities.json'))
    exact_int(identity['heldoutLaunchIndex'], index, 'input launch index')
    expected_sha = digest(encode(launch))
    for value in (terminal, identity):
        require(value['codeCommit'] == launch['implementationCommit']
                and value['heldoutLaunchSha256'] == expected_sha, 'block does not bind this launch')
        for key in ('repositoryCommit', 'executionPlanSha256', 'buildFreezeCommit', 'buildFreezePath',
                    'dataPublicationManifestSha256', 'operationalWatchdog'):
            require(typed_equal(value[key], launch[key]), 'block changed the frozen launch identity: ' + key)
    require(digest(read_file(root, 'frozen-build.json')) == launch['backend']['buildManifestSha256'],
            'block copied a different build manifest')
    require({name: digest(body) for name, body in material.items()} == launch['inputHashes'][index],
            'block verification material differs from launch')

    phase_keys = set()
    for name in ('flow', 'renderer'):
        phase = terminal['phases'][name]
        exact_int(phase['exitCode'], 0, name + ' exit')
        require(instant(phase['startedAt']) <= instant(phase['endedAt']) <= instant(terminal['finishedAt']),
                'block phase chronology differs')
        phase_keys.add((phase['pid'], phase['createTime']))
    registry_body = read_file(root, 'owned-process-registry.json')
    require(digest(registry_body) == full_sha(terminal['ownedProcessRegistrySha256']), 'owned process seal differs')
    registry = decode(registry_body)
    samples = [decode(line) for line in read_file(root, 'telemetry.jsonl').splitlines()]
    require(bool(samples), 'owned process telemetry is empty')
    validate_owned_registry(registry, samples)
    registered = {(value['pid'], value['createTime']) for value in registry['explicitlyRegisteredIdentities']}
    require(len(phase_keys) == 2 and phase_keys <= registered, 'flow or renderer start identity escaped registry')
    evidence = closing_evidence(root, material, launch)
    for name in ('frozen-build.json', 'owned-process-registry.json', 'telemetry.jsonl'):
        evidence[name] = digest(read_file(root, name))
    require(evidence['owned-process-registry.json'] == digest(registry_body), 'owned process registry changed during verification')
    return evidence


def execute_blocks(output, launch, invoke, verify_block):
    """Exclusive launcher. A failed or ambiguous block prevents every later launch."""
    require(launch['mode'] in (REAL, SYNTHETIC), 'unknown launch mode')
    for key, expected in SCOPE.items():
        exact_int(launch[key], expected, key)
    output.mkdir(mode=0o700)
    launch_body = encode(launch)
    (output / 'launch.json').write_bytes(launch_body)
    state = dict(schema=RECEIPT_SCHEMA, status='RUNNING_HELDOUT_MEASUREMENT', mode=launch['mode'],
                 launchSha256=digest(launch_body), startedAt=utc(), plannedPairs=40,
                 plannedConditionRows=80, verifiedPairs=0, verifiedConditionRows=0,
                 blocks=[dict(index=index, directory=name, status='UNATTEMPTED')
                         for index, name in enumerate(BLOCKS)])
    write_receipt(output, state)
    try:
        for index, record in enumerate(state['blocks']):
            name = record['directory']
            stage = output / name
            record.update(status='SCHEDULED', startedAt=utc())
            write_receipt(output, state)
            try:
                with (output / (name + '.stdout.log')).open('xb') as stdout, (output / (name + '.stderr.log')).open('xb') as stderr:
                    record['exitCode'] = invoke(index, stage, stdout, stderr)
            except ChildStopped as error:
                record['exitCode'] = error.exit_code
                raise
            finally:
                record['finishedAt'] = utc()
                for log in (name + '.stdout.log', name + '.stderr.log', name + '/receipt.json'):
                    if (output / log).is_file():
                        record.setdefault('attemptFiles', {})[log] = digest(read_file(output, log))
            exact_int(record['exitCode'], 0, 'finite child exit')
            terminal_body = read_file(stage, 'receipt.json')
            require(digest(terminal_body) == record['attemptFiles'][name + '/receipt.json'],
                    'child terminal changed after exit')
            terminal = decode(terminal_body)
            closed_at = instant(terminal['finishedAt'])
            for phase in ('flow', 'renderer'):
                require(instant(record['startedAt']) <= instant(terminal['phases'][phase]['startedAt'])
                        <= closed_at <= instant(record['finishedAt']), 'child phase outside its invocation window')
            evidence = verify_block(index, stage)
            require(type(evidence) is dict and evidence.get('receipt.json') == record['attemptFiles'][name + '/receipt.json'],
                    'verified terminal is not the original child terminal')
            record.update(status='VERIFIED_SYNTHETIC' if launch['mode'] == SYNTHETIC else 'VERIFIED', evidence=evidence)
            state['verifiedPairs'] += 10
            state['verifiedConditionRows'] += 20
            write_receipt(output, state)
        state['status'] = 'COMPLETE_OFFLINE_SYNTHETIC' if launch['mode'] == SYNTHETIC else 'COMPLETE_HELDOUT_MEASUREMENT'
    except ERRORS as error:
        record['status'] = 'STOPPED_UNVERIFIED'
        state.update(status='STOPPED_HELDOUT_MEASUREMENT', reason=type(error).__name__ + ': ' + str(error))
    state['finishedAt'] = utc()
    write_receipt(output, state)
    return state


def live_configuration(args):
    from finite_inputs import ROOT

    repo = ROOT
    workspace = PROJECT_ROOT.resolve()
    require(sys.platform == 'darwin' and sys.version_info >= (3, 11) and sys.flags.optimize == 0,
            'use the original Mac test platform with Python 3.11+ and assertions enabled')
    import psutil
    require(psutil.__version__ == '7.2.2', 'the approved process observer requires psutil 7.2.2')
    config = decode(local_path(args.config, workspace).read_bytes())
    closed(config, ('schema', 'buildFreezeCommit', 'dockerSocket', *LOCAL_PATHS, *TOOL_PATHS),
           'local path configuration is incomplete or unknown')
    require(config['schema'] == CONFIG_SCHEMA, 'wrong local path configuration')
    paths = {key: local_path(config[key], workspace, directory=key == 'client') for key in LOCAL_PATHS}
    socket = Path(config['dockerSocket'])
    require(socket.is_absolute() and socket.resolve() == socket and socket.is_relative_to(workspace),
            'the Docker socket must be exact and within the workspace')
    paths['dockerSocket'] = socket
    for key in TOOL_PATHS:
        path = Path(config[key])
        require(path.is_absolute() and path.resolve() == path and path.is_file() and os.access(path, os.X_OK),
                'explicit installed executable required: ' + key)
        paths[key] = path
    require(all(os.access(paths[key], os.X_OK) for key in ('godot', 'realGodot')), 'Godot executables are not runnable')
    os.environ.update(AIJADE_REAL_GODOT=str(paths['realGodot']),
                      AIJADE_GODOT_SANDBOX_PROFILE=str(paths['sandboxProfile']))
    model_sha = file_digest(paths['model'])
    settings = {}

    def check_backend(q, b, backend, plan):
        require(b == config['buildFreezeCommit'], 'local config does not use the accepted B')
        executables = dict(python=Path(sys.executable).resolve(), **{name: paths[name] for name in TOOL_PATHS})
        for name, path in executables.items():
            require(file_digest(path) == plan['toolsSha256'][name], 'measurement executable bytes changed: ' + name)
        build = validate_build(paths['assembly'], paths['buildManifest'], q, repo, b, BUILD)
        identity_args = SimpleNamespace(client=paths['client'], model=paths['model'], assembly=paths['assembly'],
                                        build_manifest=paths['buildManifest'], godot=paths['godot'],
                                        docker=paths['docker'], db_container=backend['databaseContainer'])
        actual = current_backend_before_measurement(repo, identity_args, build, model_sha)
        require(typed_equal(qualified_backend(actual, closed=True), backend),
                'measurement files do not match the qualified backend')
        settings.update(plan)

    launch = preflight_inputs(repo, args.implementation_commit, args.inputs, args.data_publication_manifest,
                              model_sha, args.measurement_plan, args.expected_plan_sha256,
                              check_backend=check_backend)
    launch['mode'] = REAL
    output = Path(args.output)
    require(output.is_absolute() and output.resolve() == output and output.is_relative_to(workspace)
            and not output.is_relative_to(repo) and output.parent.is_dir(),
            'output must be a fresh project-local directory outside the execution checkout')
    return repo, output, launch, paths, settings


def run_scheduled_block(index, repo, output, launch, paths, settings):
    require(type(index) is int and 0 <= index < len(BLOCKS), 'scheduled block index out of range')
    stage = output / BLOCKS[index]
    launch_body = read_file(output, 'launch.json')
    parent = decode(read_file(output, 'receipt.json'))
    require(launch_body == encode(launch) and parent['launchSha256'] == digest(launch_body)
            and parent['status'] == 'RUNNING_HELDOUT_MEASUREMENT' and parent['mode'] == REAL
            and parent['verifiedConditionRows'] == index * 20
            and [item['status'] for item in parent['blocks']] ==
                ['VERIFIED'] * index + ['SCHEDULED'] + ['UNATTEMPTED'] * (3 - index)
            and not stage.exists() and not stage.is_symlink(), 'block was not scheduled by the current parent')
    for before in parent['blocks'][:index]:
        for name, sha in before['evidence'].items():
            original = output / before['directory']
            require(digest(read_file(original, name)) == sha, 'earlier verified raw evidence changed: ' + name)
    from run_finite_block import main

    verify_local_database(paths, settings, launch['backend'])
    for key in ('AIJADE_LIFECYCLE_JOURNAL', 'AIJADE_FINITE_EPOCH', 'AIJADE_FINITE_SWAP_BASELINE'):
        require(key not in os.environ, 'inherited historical execution state: ' + key)
    os.environ.pop('MOSAIC_SCENE_OUT', None)
    os.environ.update(AIJADE_GIT_COMMIT=launch['implementationCommit'], DOTNET_PROCESSOR_COUNT='2',
                      AIJADE_WORKSPACE_ROOT=str(PROJECT_ROOT.resolve()), AIJADE_GODOT_LOG_DIR=str(stage / 'godot-logs'),
                      AIJADE_FINITE_TIMERS_FILE=str(stage / 'timers.json'))
    inputs = repo / launch['inputsPath'] / BLOCKS[index]
    return main(argparse.Namespace(
        repo=repo, output=stage, client=paths['client'], model=paths['model'], assembly=paths['assembly'],
        build_manifest=paths['buildManifest'], godot=paths['godot'], dotnet=paths['dotnet'], docker=paths['docker'],
        db_container=launch['backend']['databaseContainer'], build_freeze_commit=launch['buildFreezeCommit'],
        build_freeze_path=BUILD, implementation_commit=launch['implementationCommit'],
        data_publication_manifest=launch['dataPublicationManifestPath'], execution_plan=repo / launch['executionPlanPath'],
        selection=repo / BANK, manifest=inputs / 'runtime-manifest.json', scoring=inputs / 'scoring-manifest.json',
        _heldout_watchdog=settings['watchdog'], _heldout_launch_sha=digest(launch_body),
        _heldout_block_index=index,
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation-commit', required=True)
    parser.add_argument('--expected-plan-sha256', required=True)
    for name in ('inputs', 'data-publication-manifest', 'measurement-plan', 'config', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--child-index', type=int, choices=range(len(BLOCKS)), help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        repo, output, launch, paths, settings = live_configuration(args)
        if args.child_index is not None:
            return run_scheduled_block(args.child_index, repo, output, launch, paths, settings)
        watchdog = settings['watchdog']

        def invoke(index, stage, out, err):
            command = [sys.executable, '-B', str(repo / MEASUREMENT_LAUNCHER), *sys.argv[1:], '--child-index', str(index)]
            process = subprocess.Popen(command, cwd=repo, stdout=out, stderr=err, start_new_session=True)
            return wait_child(process, watchdog['blockWallSeconds'] + watchdog['parentAllowanceSeconds'],
                              watchdog['shutdownGraceSeconds'])

        def verify_block(index, stage):
            source = repo / launch['inputsPath'] / BLOCKS[index]
            material = {name: read_file(source, name) for name in INPUT_NAMES if name != 'selection.json'}
            material['selection.json'] = read_file(repo, BANK)
            from finite_audit import verify as audit_block

            evidence = block_evidence(stage, launch, index, material)
            for name in ('build-identity.json', 'renderer.log'):
                evidence[name] = digest(read_file(stage, name))
            report = audit_block(stage, repo)
            for name, sha in evidence.items():
                require(digest(read_file(stage, name)) == sha, 'raw evidence changed during full audit: ' + name)
            report_body = encode(report)
            with (stage / 'dataflow-audit.json').open('xb') as report_file:
                report_file.write(report_body)
            evidence['dataflow-audit.json'] = digest(report_body)
            return evidence

        state = execute_blocks(output, launch, invoke, verify_block)
        print(encode(state).decode(), end='')
        return 0 if state['status'] == 'COMPLETE_HELDOUT_MEASUREMENT' else 1
    except ERRORS as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
