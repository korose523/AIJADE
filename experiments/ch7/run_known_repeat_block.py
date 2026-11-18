#!/usr/bin/env python3
"""Explicit reply-bound child entry for the known-only finite block."""

import argparse
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlsplit

from finite_construction_binding import decode, typed_equal
from finite_runtime import PROJECT_ROOT, require
from launch_known_repeats import (
    BUILD_PATH, REAL, REPEATS, ROOT, arguments, digest, encode, known_material,
    launch_record, live_configuration, local_path, read_file,
)


def verify_local_database(paths, plan, backend):
    """Bind the existing test URL to the explicitly approved local Docker port."""
    url = urlsplit(os.environ.get('AIJADE_TEST_DATABASE_URL', ''))
    require(url.scheme in ('postgres', 'postgresql') and url.hostname in ('127.0.0.1', 'localhost', '::1')
            and url.port == plan['databasePort'], 'the approved local test database URL is required')
    socket = paths['dockerSocket']
    require(stat.S_ISSOCK(socket.stat().st_mode), 'the project Docker endpoint is not a socket')
    os.environ.pop('DOCKER_CONTEXT', None)
    os.environ['DOCKER_HOST'] = 'unix://' + str(socket)
    result = subprocess.run(
        [str(paths['docker']), 'port', backend['databaseContainer'], '5432/tcp'],
        capture_output=True, text=True, check=True, timeout=10)
    require(any(re.fullmatch(r'(?:127\.0\.0\.1|0\.0\.0\.0|\[::1?\]):' + str(url.port), line)
                for line in result.stdout.splitlines()), 'Docker bound a different database port')


def enter(args):
    approval, plan, plan_path, b, paths = live_configuration(args)
    workspace = PROJECT_ROOT.resolve()
    output = local_path(args.output, workspace, directory=True)
    scratch = local_path(args.scratch, workspace, directory=True)
    require(1 <= args.index <= 2, 'repeat index is outside the approved scope')
    approval_snapshot = read_file(output, 'approval.json')
    require(digest(approval_snapshot) == args.expected_approval_sha256,
            'parent approval snapshot differs from independent digest')
    launch_body = read_file(output, 'launch.json')
    launch = decode(launch_body)
    material = known_material(approval['implementationCommit'], scratch)
    expected = launch_record(approval, args.expected_approval_sha256, b, material, REAL)
    require(typed_equal(expected, launch) and encode(expected) == launch_body,
            'child launch record does not match actual approved inputs')
    parent = decode(read_file(output, 'receipt.json'))
    name = REPEATS[args.index - 1]
    stage = output / name
    require(parent['status'] == 'RUNNING_KNOWN_REPEAT_LAUNCH' and parent['launchSha256'] == digest(launch_body)
            and type(parent['completedRepeats']) is int and parent['completedRepeats'] == args.index - 1
            and len(parent['repeats']) == args.index
            and parent['repeats'][-1]['directory'] == name
            and 'exitCode' not in parent['repeats'][-1]
            and not stage.exists() and not stage.is_symlink(),
            'child is not the single scheduled new run')
    for filename, body in material.items():
        require(read_file(output, 'inputs/' + filename) == body, 'parent froze different known material')
    verify_local_database(paths, plan, approval['backend'])
    for key in ('AIJADE_LIFECYCLE_JOURNAL', 'AIJADE_FINITE_EPOCH', 'AIJADE_FINITE_SWAP_BASELINE'):
        require(key not in os.environ, 'unexpected inherited historical execution state: ' + key)
    os.environ.pop('MOSAIC_SCENE_OUT', None)
    os.environ.update(AIJADE_GIT_COMMIT=approval['implementationCommit'], DOTNET_PROCESSOR_COUNT='2',
                      AIJADE_WORKSPACE_ROOT=str(workspace), AIJADE_GODOT_LOG_DIR=str(stage/'godot-logs'),
                      AIJADE_REAL_GODOT=str(paths['realGodot']),
                      AIJADE_GODOT_SANDBOX_PROFILE=str(paths['sandboxProfile']),
                      AIJADE_FINITE_TIMERS_FILE=str(stage/'timers.json'))
    from run_finite_block import main
    return main(argparse.Namespace(
        repo=ROOT, output=stage, client=paths['client'], model=paths['model'], assembly=paths['assembly'],
        build_manifest=paths['buildManifest'], godot=paths['godot'], dotnet=paths['dotnet'], docker=paths['docker'],
        db_container=approval['backend']['databaseContainer'], build_freeze_commit=b, build_freeze_path=BUILD_PATH,
        implementation_commit=approval['implementationCommit'], execution_plan=plan_path,
        selection=output/'inputs/selection.json', manifest=output/'inputs/runtime-manifest.json',
        scoring=output/'inputs/scoring-manifest.json',
        _known_repeat_watchdog=plan['watchdog'], _known_repeat_launch_sha=digest(launch_body),
        _known_repeat_index=args.index,
    ))


def cli():
    parser = arguments()
    parser.add_argument('--index', type=int, choices=(1, 2), required=True)
    try:
        return enter(parser.parse_args())
    except (OSError, ValueError, TypeError, ImportError, KeyError, AttributeError, subprocess.SubprocessError) as error:
        print(f'Known block refused: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
