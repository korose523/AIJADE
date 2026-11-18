#!/usr/bin/env python3
"""Record the approved Q prebuilt assembly and complete dependency directory for B publication."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

from finite_construction_binding import full_commit
from finite_inputs import ROOT
from finite_runtime import PROJECT_ROOT, require
from known_repeat_acceptance import BUILD, approved_decision, git, raw
from launch_known_repeats import digest, encode, file_digest, local_path, parse_execution_plan, utc


def content_identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def capture_build(assembly, implementation):
    """Freeze the exact prebuilt bytes without invoking an executable or service."""
    q = full_commit(implementation)
    require(assembly.name == 'Aijade.Tests.dll' and assembly.is_file() and not assembly.is_symlink(), 'explicit test assembly required')
    revision = '0.1.0+' + q
    require(revision.encode() in assembly.read_bytes(), 'prebuilt test assembly does not contain the approved revision')
    files = {}
    snapshots = {}
    for item in sorted(assembly.parent.rglob('*')):
        require(not item.is_symlink() and (item.is_file() or item.is_dir()), 'linked or special build entry')
        if item.is_file():
            snapshots[item] = content_identity(item)
            files[item.relative_to(assembly.parent).as_posix()] = file_digest(item)
    require(len({name.casefold() for name in files}) == len(files), 'case-colliding build paths')
    require(all(not item.is_symlink() and content_identity(item) == initial for item, initial in snapshots.items())
            and set(snapshots) == {item for item in assembly.parent.rglob('*') if item.is_file()},
            'build files changed during freeze')
    require(revision.encode() in assembly.read_bytes(), 'prebuilt test assembly revision changed during freeze')
    require({assembly.name, 'Aijade.Tests.deps.json', 'Aijade.Tests.runtimeconfig.json'} <= files.keys(),
            'prebuilt assembly runtime or dependency manifest is missing')
    return dict(status='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION', commit=q,
                assemblyInformationalVersion=revision, checkedAt=utc(), files=files)


def prepare_build_publication(repo, implementation, assembly, original_reply, qualification_plan):
    """Write a new canonical B manifest from a clean approved Q checkout."""
    q = full_commit(implementation)
    require(git(repo, 'rev-parse', 'HEAD').decode().strip() == q
            and not git(repo, 'status', '--porcelain'), 'use the clean approved Q checkout')
    decision = approved_decision(repo, q)
    parse_execution_plan(raw(repo, q, decision['executionPlanPath']))
    for path, field in ((original_reply, 'replySha256'), (qualification_plan, 'qualificationPlanSha256')):
        body = path.read_bytes()
        require(bool(body) and digest(body) == decision[field], 'private original differs: ' + field)
    output = Path(repo) / BUILD
    require(not output.exists() and output.resolve() == output, 'B publication path already exists or is linked')
    require(not assembly.is_relative_to(repo), 'prebuilt binaries must be outside the source checkout')
    build = capture_build(assembly, q)
    require(git(repo, 'rev-parse', 'HEAD').decode().strip() == q
            and not git(repo, 'status', '--porcelain'), 'Q changed during build freeze')
    # An interrupted capture cannot publish a partial JSON document as B.
    pending = output.with_suffix('.json.pending')
    with pending.open('xb') as stream:
        stream.write(encode(build))
        stream.flush()
        os.fsync(stream.fileno())
    os.link(pending, output)
    pending.unlink()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation-commit', required=True)
    for name in ('assembly', 'original-reply', 'qualification-plan'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        workspace = PROJECT_ROOT.resolve()
        output = prepare_build_publication(ROOT, args.implementation_commit,
                                           local_path(args.assembly, workspace),
                                           local_path(args.original_reply, workspace),
                                           local_path(args.qualification_plan, workspace))
        print(output)
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
