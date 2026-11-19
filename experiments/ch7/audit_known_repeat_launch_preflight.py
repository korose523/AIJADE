#!/usr/bin/env python3
"""Check the protected source and optional exact approval binding without launching Chapter 7."""

import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys
from urllib.parse import urlsplit

import launch_known_repeats as launch
from finite_construction_binding import decode
from finite_runtime import require, safe_relative
from known_repeat_acceptance import ACCEPTANCE, BUILD, DECISION, FREEZE, git, raw
from preflight_known_repeat_readback import (
    ARCHIVED_INPUTS, PROTECTED_COMMIT, SOURCE_FREEZE, SOURCE_FREEZE_SHA, SOURCES, local,
)
from prepare_known_repeats import ARCHIVED_INPUT_HASHES


def tracked_blobs(repo, commit, paths):
    matched = {}
    for entry in git(repo, 'ls-tree', '-rz', commit, '--', *paths).split(b'\0'):
        if not entry:
            continue
        metadata, path = entry.decode().split('\t', 1)
        _, kind, blob = metadata.split()
        require(kind == 'blob' and path not in matched, 'unexpected protected Git tree entry')
        matched[path] = blob
    return matched


def physical_sources(repo, digests):
    missing = []
    for relative, digest in digests.items():
        path = repo / relative
        if not path.exists() and not path.is_symlink():
            missing.append(relative)
            continue
        require(path.resolve() == path and path.is_file() and launch.file_digest(path) == digest,
                'resolved file differs from the protected source: ' + relative)
    return sorted(missing)


def check_sources(repo):
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    git(repo, 'merge-base', '--is-ancestor', PROTECTED_COMMIT, head)
    require(not git(repo, 'status', '--porcelain'), 'checkout must be clean')
    freeze = raw(repo, PROTECTED_COMMIT, SOURCE_FREEZE)
    require(launch.digest(freeze) == SOURCE_FREEZE_SHA and raw(repo, head, SOURCE_FREEZE) == freeze,
            'protected source freeze differs')
    rows = {safe_relative(row['path']): row for row in decode(freeze)['files']}
    require(len(rows) == 331, 'protected source population changed')
    selection = raw(repo, PROTECTED_COMMIT, ARCHIVED_INPUTS + 'selection.json')
    require(launch.digest(selection) == ARCHIVED_INPUT_HASHES['selection.json'], 'archived selection differs')
    programmes = {safe_relative(name): digest for name, digest in decode(selection)['sources'].items()}
    require(len(programmes) == 4, 'archived programme file population changed')
    require(tracked_blobs(repo, head, sorted(rows)) == {name: row['gitBlobSha1'] for name, row in rows.items()},
            'protected Git blobs differ')
    archived_blobs = tracked_blobs(repo, PROTECTED_COMMIT, sorted(programmes))
    require(archived_blobs.keys() == programmes.keys()
            and tracked_blobs(repo, head, sorted(programmes)) == archived_blobs, 'archived programme Git blobs differ')
    readers = {}
    for name in SOURCES:
        protected = raw(repo, PROTECTED_COMMIT, name)
        require(raw(repo, head, name) == protected == (launch.ROOT / name).read_bytes(),
                'preflight reader differs from the baseline: ' + name)
        readers[name] = launch.digest(protected)
    missing_protected = physical_sources(repo, {name: row['sha256'] for name, row in rows.items()})
    missing_programmes = physical_sources(repo, programmes)
    files = tracked_blobs(repo, head, (DECISION, BUILD, ACCEPTANCE, FREEZE))
    return dict(checkoutCommit=head, ancestorProtectedCommit=PROTECTED_COMMIT, sourceFreezeSha256=SOURCE_FREEZE_SHA,
                protectedGitFilesMatched=331, protectedPhysicalFilesMatched=331-len(missing_protected),
                protectedPhysicalMissing=missing_protected, programmeGitFilesMatched=4,
                programmePhysicalFilesMatched=4-len(missing_programmes), programmePhysicalMissing=missing_programmes,
                readerFilesSha256=readers, canonicalPathsAtCheckout={name: name in files
                                                                      for name in (DECISION, BUILD, ACCEPTANCE, FREEZE)})


def passive_database(socket, port=None):
    socket_state = 'NOT_NOMINATED'
    if socket is not None:
        workspace = launch.PROJECT_ROOT.resolve()
        require(socket.is_absolute() and socket.resolve() == socket and socket.is_relative_to(workspace),
                'Docker endpoint must be exact and workspace-local')
        try:
            socket_state = 'SOCKET_EXISTS_UNCONTACTED' if stat.S_ISSOCK(socket.stat().st_mode) else 'NOT_A_SOCKET'
        except FileNotFoundError:
            socket_state = 'SOCKET_ABSENT'
    url_state = 'NOT_PROVISIONED_IN_AUDIT_SHELL'
    value = os.environ.get('AIJADE_TEST_DATABASE_URL')
    if value:
        try:
            uri = urlsplit(value)
            acceptable = (uri.scheme in ('postgres', 'postgresql')
                          and uri.hostname in ('127.0.0.1', 'localhost', '::1') and uri.port is not None)
            url_state = ('LOCAL_PORT_FORM_UNBOUND' if port is None else 'APPROVED_LOCAL_PORT_FORM'
                         if uri.port == port else 'WRONG_PORT') if acceptable else 'INVALID_LOCAL_FORM'
        except ValueError:
            url_state = 'INVALID_LOCAL_FORM'
    return dict(socket=socket_state, testDatabaseUrl=url_state, containerPortMapping='NOT_QUERIED')


def audit(args):
    repo = local(args.checkout, directory=True)
    plan = local(args.qualification_plan)
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    source = check_sources(repo)
    report = dict(schema='aijade.ch7.readonly-mac-launch-preflight.v1',
                  status='APPROVAL_BINDING_NOT_VERIFIED', approvalBindingVerified=False, checkout=source,
                  reviewedPlanSha256=launch.file_digest(plan), database=passive_database(args.candidate_socket),
                  runtimeAvailability='NOT_QUERIED', runtimeProcessesStarted=0,
                  newQualificationRuns=0, heldoutPairsCreated=0, heldoutSeedsDerived=0)
    supplied = [args.approval, args.expected_approval_sha256, args.original_reply, args.config]
    if any(supplied):
        require(all(supplied), 'all private approval binding inputs are required together')
        require(source['checkoutCommit'] != PROTECTED_COMMIT and not source['protectedPhysicalMissing']
                and not source['programmePhysicalMissing'], 'approved Q must materialize all protected and programme sources')
        # Use this audited preflight reader against Q's read-only paths and Git.
        original_root = launch.ROOT
        try:
            launch.ROOT = repo
            approval, execution, _, build, paths = launch.live_configuration(args)
        finally:
            launch.ROOT = original_root
        report.update(status='EXACT_APPROVAL_BINDING_READ_BACK', approvalBindingVerified=True,
                      approvalSha256=args.expected_approval_sha256, implementationCommit=approval['implementationCommit'],
                      executionPlanSha256=approval['executionPlanSha256'], buildFreezeCommit=build,
                      buildManifestSha256=approval['backend']['buildManifestSha256'],
                      database=passive_database(paths['dockerSocket'], execution['databasePort']))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('checkout', 'qualification-plan', 'approval', 'original-reply', 'config', 'candidate-socket'):
        parser.add_argument('--' + name, type=Path, required=name in ('checkout', 'qualification-plan'))
    parser.add_argument('--expected-approval-sha256')
    args = parser.parse_args()
    try:
        sys.stdout.buffer.write(launch.encode(audit(args)))
    except (OSError, ValueError, KeyError, TypeError, ImportError, subprocess.SubprocessError) as error:
        print(f'Static launch preflight refused: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
