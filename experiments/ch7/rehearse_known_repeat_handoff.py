#!/usr/bin/env python3
"""Rehearse the known-condition Q/B/repeats handoff on disposable synthetic fixtures."""

import argparse
from pathlib import Path
from shutil import copyfile, copytree
import subprocess
import sys
from tempfile import TemporaryDirectory

import known_repeat_acceptance as acceptance
import launch_known_repeats as launch
from finite_construction_binding import decode
from finite_runtime import require, validate_build
from freeze_known_repeat_build import prepare_build_publication
from preflight_known_repeat_readback import (
    PROTECTED_COMMIT, RELEASE_SHA, REVIEW_SHA, SOURCE_FREEZE, SOURCE_FREEZE_SHA, match_known_material,
)
from prepare_known_repeats import ARCHIVED_INPUT_HASHES, ARCHIVED_INPUTS, check_delivery, known_inputs
from test_launch_known_repeats import __file__ as FIXTURE_CHILD
from test_prepare_known_repeats import packet


COMPLETE_FIXTURE = 'synthetic-complete'
CHANGED_FIXTURE = 'synthetic-decision-difference'
STOPPED_FIXTURE = 'synthetic-stopped'


def git(repo, *args):
    return acceptance.git(repo, '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
                          '-c', 'user.name=AIJADE Offline Fixture', '-c', 'user.email=fixture@example.invalid',
                          *args).decode().strip()


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def refused(check, expected):
    try:
        check()
    except ValueError as error:
        require(expected in str(error), 'unexpected refusal: ' + str(error))
        return str(error)
    raise ValueError('expected refusal: ' + expected)


def anchor_fixture_source(repo, protected, decision_path, plan_path):
    require(git(protected, 'rev-parse', 'HEAD') == PROTECTED_COMMIT, 'wrong protected source checkout')
    objects = Path(git(protected, 'rev-parse', '--path-format=absolute', '--git-path', 'objects')).resolve(strict=True)
    require(objects.is_dir() and objects.is_relative_to(launch.ROOT.parent) and '\n' not in str(objects),
            'protected object store must be workspace-local')
    write(repo / '.git/objects/info/alternates', (str(objects) + '\n').encode())
    git(repo, 'update-ref', 'HEAD', PROTECTED_COMMIT)
    git(repo, 'config', 'core.sparseCheckout', 'true')
    git(repo, 'config', 'core.sparseCheckoutCone', 'false')
    write(repo / '.git/info/sparse-checkout',
          ''.join('/' + path + '\n' for path in (decision_path, plan_path, acceptance.BUILD)).encode())
    git(repo, 'read-tree', '-m', '-u', PROTECTED_COMMIT)
    require(not git(repo, 'status', '--porcelain'), 'fixture did not start from the exact protected tree')


def inherited_source(repo, q, decision_path, plan_path):
    require(git(repo, 'rev-parse', q + '^') == PROTECTED_COMMIT
            and set(git(repo, 'diff', '--name-status', '--no-renames', PROTECTED_COMMIT, q).splitlines())
            == {'A\t' + decision_path, 'A\t' + plan_path},
            'fixture Q changed the protected source outside its two additions')
    freeze = acceptance.raw(repo, q, SOURCE_FREEZE)
    require(launch.digest(freeze) == SOURCE_FREEZE_SHA, 'fixture Q inherited the wrong source freeze')
    protected_paths = [row['path'] for row in decode(freeze)['files']]
    programmes = decode((ARCHIVED_INPUTS / 'selection.json').read_bytes())['sources']
    require(len(set(protected_paths)) == 331 and len(programmes) == 4, 'protected or archive population changed')
    paths = sorted(set(protected_paths) | programmes.keys())
    before = acceptance.git(repo, 'ls-tree', '-rz', PROTECTED_COMMIT, '--', *paths)
    after = acceptance.git(repo, 'ls-tree', '-rz', q, '--', *paths)
    require(before == after and before.count(b'\0') == len(paths), 'fixture source blobs differ from protected revision')
    return dict(parentCommit=PROTECTED_COMMIT, inheritedProtectedFiles=331, inheritedKnownProgrammeFiles=4,
                inheritedGitTreeSubsetSha256=launch.digest(before), changes=['fixture decision', 'fixture execution plan'])


def frozen_fixture(root, protected):
    repo = root / 'fixture-source'
    repo.mkdir()
    git(repo, 'init', '-q', '--template=', '--object-format=sha1')
    plan_path = acceptance.PREFIX + 'offline-fixture-plan.json'
    if protected is not None:
        anchor_fixture_source(repo, protected, acceptance.DECISION, plan_path)
    plan = launch.encode(dict(
        schema=launch.PLAN_SCHEMA, purpose='qualification_only', repeats=2, conditionSlotsPerRepeat=20,
        databasePort=15432,
        toolsSha256={name: launch.digest(('OFFLINE_SYNTHETIC ' + name).encode())
                     for name in ('python', *launch.TOOL_PATHS)},
        watchdog=dict(blockWallSeconds=60, rendererTimeoutSeconds=30, sustainedResourceSeconds=10,
                      parentAllowanceSeconds=30, shutdownGraceSeconds=10,
                      maxOwnedRssBytes=None, minAvailableBytes=None, maxSwapIncreaseBytes=None),
    ))
    plan_copy = root / 'synthetic-qualification-plan.txt'
    reply = root / 'synthetic-reply.txt'
    write(plan_copy, b'OFFLINE_SYNTHETIC qualification plan. No authorization.')
    original_reply = b'OFFLINE_SYNTHETIC reply fixture. No authorization.'
    write(reply, original_reply)
    hashes = dict(executionPlanSha256=launch.digest(plan), qualificationPlanSha256=launch.file_digest(plan_copy),
                  replySha256=launch.file_digest(reply))
    write(repo / plan_path, plan)
    write(repo / acceptance.DECISION, launch.encode(dict(
        schema=acceptance.DECISION_SCHEMA, status=launch.APPROVED, executionPlanPath=plan_path, **hashes)))
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'OFFLINE_SYNTHETIC prospective implementation fixture')
    q = git(repo, 'rev-parse', 'HEAD')
    require(not git(repo, 'remote'), 'fixture Git unexpectedly has a remote')
    lineage = inherited_source(repo, q, acceptance.DECISION, plan_path) if protected is not None else None

    assembly = root / 'synthetic-build/Aijade.Tests.dll'
    dependency = assembly.parent / 'lib/Reference.dll'
    write(assembly, b'OFFLINE_SYNTHETIC plain text, unsigned and non-executable. 0.1.0+' + q.encode())
    write(dependency, b'OFFLINE_SYNTHETIC dependency')
    for extension in ('.deps.json', '.runtimeconfig.json'):
        write(assembly.with_suffix(extension), b'{}\n')

    write(reply, b'OFFLINE_SYNTHETIC different private reply')
    reply_rejection = refused(lambda: prepare_build_publication(repo, q, assembly, reply, plan_copy),
                             'private original differs: replySha256')
    require(not (repo / acceptance.BUILD).exists(), 'build freeze appeared under a different reply')
    write(reply, original_reply)
    manifest = prepare_build_publication(repo, q, assembly, reply, plan_copy)
    git(repo, 'add', acceptance.BUILD)
    git(repo, 'commit', '-qm', 'OFFLINE_SYNTHETIC build freeze fixture')
    b = git(repo, 'rev-parse', 'HEAD')
    require(git(repo, 'rev-parse', b + '^') == q
            and git(repo, 'diff', '--name-only', q, b) == acceptance.BUILD, 'wrong fixture B chronology')
    build = validate_build(assembly, manifest, q, repo, b, acceptance.BUILD)
    original_dependency = dependency.read_bytes()
    write(dependency, b'OFFLINE_SYNTHETIC changed dependency')
    build_rejection = refused(lambda: validate_build(assembly, manifest, q, repo, b, acceptance.BUILD),
                              'build binary/dependency bytes changed')
    write(dependency, original_dependency)
    validate_build(assembly, manifest, q, repo, b, acceptance.BUILD)
    return repo, q, b, manifest.read_bytes(), build['files'], hashes, lineage, (reply_rejection, build_rejection)


def bind_packet(folder, material, record, build_body, *, change_decision=False):
    for name, body in material.items():
        write(folder / name, body)
    write(folder / 'frozen-build.json', build_body)
    receipt = folder / 'receipt.json'
    write(receipt, launch.encode(dict(decode(receipt.read_bytes()), codeCommit=record['implementationCommit'])))
    keys = dict(codeCommit=record['implementationCommit'], constructionFreezeCommit=record['implementationCommit'],
                executionPlanSha256=record['executionPlanSha256'], **record['backend'])
    for field, name in (('runtimeManifestSha256', 'runtime-manifest.json'),
                        ('scoringManifestSha256', 'scoring-manifest.json'), ('selectionSha256', 'selection.json')):
        keys[field] = launch.digest(material[name])
    identity = folder / 'input-identities.json'
    write(identity, launch.encode(dict(decode(identity.read_bytes()), **keys)))

    cases_path, journal = folder / 'cases.json', folder / 'journal.jsonl'
    cases = decode(cases_path.read_bytes())
    events = [decode(line) for line in journal.read_bytes().splitlines()]
    events[0]['detail'] = decode(material['runtime-manifest.json'])
    if change_decision:
        index = next(i for i, row in enumerate(cases) if row['duplicateReuse'] is not None)
        row = cases[index]
        row['round2'], row['duplicateReuse'] = row['duplicateReuse'], row['round2']
        events[index + 1]['detail'] = row
        write(cases_path, launch.encode(cases))
    write(journal, b''.join(launch.encode(row).replace(b'\n', b' ') + b'\n' for row in events))


def run_pair(parent, material, record, approval, build_body, *, early_stop=False, mismatch=False):
    started = []

    def child(index, log):
        started.append(index)
        mode = 'reordered' if early_stop and index == 1 else 'complete'
        result = subprocess.run([sys.executable, '-B', FIXTURE_CHILD, '--fixture-child',
                                 str(parent), str(index), mode], stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode == 0:
            bind_packet(parent / launch.REPEATS[index - 1], material, record, build_body,
                        change_decision=mismatch and index == 2)
        return result.returncode

    terminal = launch.execute_repeats(parent, material, record, child, approval_body=approval)
    return started, terminal


def rehearse(root, protected=None):
    repo, q, b, build_body, binaries, hashes, lineage, rejected = frozen_fixture(root, protected)
    reply_rejection, build_rejection = rejected
    material = known_inputs(q, root)
    archived = {name: (ARCHIVED_INPUTS / name).read_bytes() for name in launch.INPUT_NAMES}
    require({name: launch.digest(body) for name, body in archived.items()} == ARCHIVED_INPUT_HASHES,
            'known condition archive hash changed')
    order = match_known_material(archived, material, q)
    # The existing child packet supplies fixture-only renderer/DB identities and copies archived decisions.
    _, fixture = packet(1)
    backend = dict(fixture['backend'], buildManifestSha256=launch.digest(build_body), binaries=binaries)
    approval = launch.encode(dict(schema=launch.APPROVAL_SCHEMA, status=launch.APPROVED,
                                  implementationCommit=q, backend=backend, **hashes))
    approval_sha = launch.digest(approval)
    record = launch.launch_record(decode(approval), approval_sha, b, material, launch.SYNTHETIC)
    binding = launch.encode(dict(schema=acceptance.EXPECTED_IDENTITY, implementationCommit=q,
                                 executionPlanSha256=hashes['executionPlanSha256'], backend=backend))

    def delivery(parent):
        return check_delivery(*(parent / name for name in launch.REPEATS), binding, root)

    complete = root / COMPLETE_FIXTURE
    started, terminal = run_pair(complete, material, record, approval, build_body)
    require(started == [1, 2] and terminal['status'] == launch.LAUNCHED, 'fixture repeats stopped: ' + str(terminal))
    checked_record, checked_terminal = launch.verify_launched_pair(complete, approval, approval_sha)
    require(checked_record == record and checked_terminal == terminal, 'fixture terminal readback differs')
    for name in launch.REPEATS:
        require((complete / name / 'frozen-build.json').read_bytes() == build_body,
                'fixture repeat did not bind the exact Git B')
    matched = delivery(complete)
    require(matched['status'] == 'OFFLINE_DELIVERY_EVIDENCE_READY_FOR_REVIEW'
            and matched['comparison']['comparableRows'] == 20
            and matched['comparison']['differences'] == [], 'complete fixture deliveries did not match')
    inventory = acceptance.inventory(complete)
    formal_rejection = refused(lambda: acceptance.audit_evidence(repo, q, complete, approval_sha, root),
                               'only an actual approved Mac launch is eligible')

    changed = root / CHANGED_FIXTURE
    started, changed_terminal = run_pair(changed, material, record, approval, build_body, mismatch=True)
    require(started == [1, 2] and changed_terminal['status'] == launch.LAUNCHED,
            'decision difference failed structural closure: ' + str(changed_terminal))
    disagreement = delivery(changed)
    require(disagreement['status'] == 'OFFLINE_DELIVERY_MATCHED_INPUTS_BUT_DIFFERENT_DECISIONS'
            and disagreement['comparison']['comparableRows'] == 20
            and len(disagreement['comparison']['differences']) == 1, 'expected one aligned decision disagreement')

    stopped = root / STOPPED_FIXTURE
    started, stop = run_pair(stopped, material, record, approval, build_body, early_stop=True)
    require(started == [1] and stop['status'] == 'STOPPED_KNOWN_REPEAT_LAUNCH'
            and stop['completedRepeats'] == 0 and 'block condition order was changed' in stop['reason']
            and not (stopped / launch.REPEATS[1]).exists(), 'stopped first repeat entered the next phase')
    stopped_rejection = refused(lambda: launch.verify_launched_pair(stopped, approval, approval_sha),
                                 'two-repeat launch lacks a complete terminal receipt')
    require(not git(repo, 'status', '--porcelain')
            and all(not (repo / path).exists() for path in (acceptance.ACCEPTANCE, acceptance.FREEZE)),
            'fixture unexpectedly modified the frozen source or published later stages')
    report = dict(
        schema='aijade.ch7.known-repeat-handoff-rehearsal.v1',
        status='OFFLINE_SYNTHETIC_HANDOFF_VERIFIED', launchMode=launch.SYNTHETIC,
        rehearsalScriptSha256=launch.file_digest(Path(__file__)),
        fixture=dict(repository='DISPOSABLE_NO_REMOTE', implementationCommit=q, buildFreezeCommit=b,
                     planSha256=hashes['executionPlanSha256'], buildFreezeSha256=launch.digest(build_body),
                     buildFileCount=len(binaries), knownInputSha256=record['knownInputHashes'],
                     evidenceFileCount=len(inventory), evidenceInventorySha256=launch.digest(
                         launch.encode(dict(sorted(inventory.items()))))),
        complete=dict(repeats=terminal['completedRepeats'], conditionsPerRepeat=len(order),
                      pairedConditionsCompared=matched['comparison']['comparableRows'], differingConditions=0,
                      deliveryStatus=matched['status']),
        controls=dict(changedReply=reply_rejection, changedDependency=build_rejection,
                      changedAlignedDecision=disagreement['status'], differingAlignedConditions=1,
                      differingDecisionFields=sorted(disagreement['comparison']['differences'][0]['fields']),
                      stoppedFirstRepeat=stop['reason'], stoppedBeforeSecond=True, stoppedPair=stopped_rejection,
                      formalAcceptance=formal_rejection),
        archivedKnownInputSha256=ARCHIVED_INPUT_HASHES,
        onlyRevisionAndDependentRuntimeHashRebound=True,
        actualQualification='NOT_RUN', actualHeldout40Pairs='NOT_RUN',
        qualificationDetermined=False, formalAcceptancePublished=False,
        newQualificationRuns=0, newHeldoutCases=0, newHeldoutSeeds=0, realModelRequests=0,
    )
    if lineage is not None:
        report['fixture']['protectedSourceLineage'] = lineage
    return report


def protected_reference(path):
    body = path.read_bytes()
    receipt = decode(body)
    known, build, governance = (receipt[name] for name in ('known', 'historicalBuild', 'governance'))
    require(receipt['schema'] == 'aijade.ch7.protected-known-repeat-readback.v1'
            and receipt['status'] == 'OFFLINE_PREPARATION_VERIFIED_NONEXECUTABLE'
            and receipt['protectedSourceCommit'] == PROTECTED_COMMIT
            and receipt['protectedSourceFreezeSha256'] == SOURCE_FREEZE_SHA
            and receipt['protectedSourceFilesVerified'] == 331
            and known['archivedInputSha256'] == ARCHIVED_INPUT_HASHES
            and known['slotsPerRepeat'] == 20 and known['measuredSlots'] == 0
            and known['separateOfflineDeckSourceCount'] == 4
            and build['manifestSha256'] == RELEASE_SHA and build['qualifiesAsApprovedBuildFreeze'] is False
            and governance['originalReviewSha256'] == REVIEW_SHA
            and governance['qualificationReplyBound'] is False
            and governance['macQualification'] == governance['table7_3'] == 'NOT_RUN'
            and all(receipt[name] == 0 for name in ('newQualificationRuns', 'newHeldoutCases', 'newHeldoutSeeds')),
            'protected reference requires the pending, fully anchored readback')
    return dict(readbackReceiptSha256=launch.digest(body), sourceCommit=PROTECTED_COMMIT,
                sourceFreezeSha256=SOURCE_FREEZE_SHA, sourceFilesVerified=331,
                historicalBuildManifestSha256=RELEASE_SHA,
                historicalBuildTestOutputFiles=build['testOutputFiles'],
                historicalBuildBlazorFiles=build['blazorFrameworkFiles'],
                historicalBuildQualifiesAsApprovedFreeze=False, supervisorReviewSha256=REVIEW_SHA,
                supervisorQualificationReply=governance['qualificationReplyStatus'],
                knownProgramSourceCountInProtectedCheckout=known['sparseCheckoutProgrammeSourceCount'],
                knownProgramSourceCountInSeparateArchiveDeck=known['separateOfflineDeckSourceCount'],
                protectedRevisionKnownInputSha256=known['protectedRevisionReplayedInputSha256'])


def retain_fixture_receipts(source, destination):
    """Copy the original fixture receipt trees, excluding fixture Git and private reply."""
    destination.mkdir()
    stages = {}
    for name in (COMPLETE_FIXTURE, CHANGED_FIXTURE, STOPPED_FIXTURE):
        original = source / name
        copy = destination / name
        copytree(original, copy, copy_function=copyfile)
        files = {}
        for path in sorted(original.rglob('*')):
            if path.is_file():
                relative = path.relative_to(original).as_posix()
                digest = launch.file_digest(path)
                require(launch.file_digest(copy / relative) == digest, 'retained fixture bytes differ: ' + relative)
                files[relative] = dict(sha256=digest, sizeBytes=path.stat().st_size)
        stages[name] = files
    manifest = launch.encode(dict(schema='aijade.ch7.synthetic-receipt-inventory.v1', stages=stages))
    write(destination / 'inventory.json', manifest)
    return launch.digest(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--protected-readback', type=Path, help='optional output of preflight_known_repeat_readback.py')
    parser.add_argument('--protected-repo', type=Path, help='optional read-only 4aa3eaa object store')
    parser.add_argument('--retain-evidence', type=Path, help='optional new local directory for fixture receipts')
    args = parser.parse_args()
    try:
        scratch = args.scratch.resolve(strict=True)
        require(scratch.is_dir() and scratch.is_relative_to(launch.ROOT.parent),
                'use an existing workspace-local scratch directory with hardlink support')
        protected = None
        if args.protected_repo is not None:
            protected = args.protected_repo.resolve(strict=True)
            require(protected.is_dir() and protected.is_relative_to(launch.ROOT.parent),
                    'protected checkout must be workspace-local')
        retained = None
        if args.retain_evidence is not None:
            retained = args.retain_evidence.resolve()
            require(retained.is_relative_to(launch.ROOT.parent) and retained.parent.is_dir()
                    and not retained.exists(), 'fixture receipt destination must be a new workspace-local directory')
        with TemporaryDirectory(prefix='offline-synthetic-known-handoff-', dir=scratch) as folder:
            report = rehearse(Path(folder), protected)
            if retained is not None:
                report['localFixtureReceiptInventorySha256'] = retain_fixture_receipts(Path(folder), retained)
        if args.protected_readback is not None:
            path = args.protected_readback.resolve(strict=True)
            require(path.is_relative_to(launch.ROOT.parent), 'readback must be workspace-local')
            report['protectedReadOnlyReference'] = protected_reference(path)
        sys.stdout.buffer.write(launch.encode(report))
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
