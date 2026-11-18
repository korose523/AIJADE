#!/usr/bin/env python3
"""Read back the protected Mac preparation without creating launchable material."""

import argparse
import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from finite_construction_binding import decode, full_commit, full_sha
from finite_inputs import ROOT, encoded, qualify
from finite_runtime import require, safe_relative
from freeze_known_repeat_build import content_identity
from known_repeat_acceptance import ACCEPTANCE, APPROVAL_FIELDS, BUILD, DECISION, EVIDENCE_FILES, FREEZE, git, raw
from launch_known_repeats import file_digest, slots
from prepare_known_repeats import ARCHIVED_INPUT_HASHES, INPUT_NAMES, SCOPE_PATH, SCOPE_SHA256


WORKSPACE = ROOT.parent
PROTECTED_COMMIT = '4aa3eaaca0664307171be799511c927cc4e1da1b'
SOURCE_FREEZE = 'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'
SOURCE_FREEZE_SHA = 'aeed1c0a036e71a81196e75e059e1ed4a6688d01b311321d9b4668aa2e40d952'
REVIEW_SHA = '7be7b1542053f426ec2dd4c848e4e97d6dfc355dff9ccb1f4aedbaf9b3bc0242'
RELEASE_SHA = '82b9061639aad117c4b434514a58d504804765e04858c1846a24a5e740e5dfbe'
ARCHIVED_INPUTS = 'experiments/ch7/relocated-runtime-2026-11-16/qualification-inputs/'
WORKLIST = 'experiments/ch7/mac-known-repeats-preparation/worklist.json'
SOURCES = tuple('experiments/ch7/' + name + '.py' for name in (
    'finite_inputs', 'comparison_manifest', 'prepare_known_repeats', 'compare_known_repeats',
    'finite_runtime', 'finite_construction_binding', 'launch_known_repeats', 'freeze_known_repeat_build',
    'known_repeat_acceptance', 'launch_heldout_blocks',
))


def sha(body):
    return hashlib.sha256(body).hexdigest()


def local(path, *, directory=False):
    path = Path(path).absolute()
    require(path.resolve() == path and path.is_relative_to(WORKSPACE), 'expected an exact workspace-local path')
    require(path.is_dir() if directory else path.is_file(), 'missing local directory or file: ' + path.name)
    return path


def match_known_material(archived, actual, implementation):
    """Require exact original data with only implementation-dependent bindings changed."""
    require(set(archived) == set(actual) == set(INPUT_NAMES), 'wrong known input inventory')
    runtime = decode(archived['runtime-manifest.json'])
    score = decode(archived['scoring-manifest.json'])
    original_revision = full_commit(runtime['constructionFreezeCommit'])
    require(score['constructionFreezeCommit'] == original_revision
            and score['runtimeManifestSha256'] == sha(archived['runtime-manifest.json'])
            and score['selectionSha256'] == runtime['selectionSha256'] == sha(archived['selection.json']),
            'archived input bindings disagree')
    runtime['constructionFreezeCommit'] = full_commit(implementation)
    expected_runtime = encoded(runtime)
    score['constructionFreezeCommit'] = implementation
    score['runtimeManifestSha256'] = sha(expected_runtime)
    expected = {
        'runtime-manifest.json': expected_runtime,
        'scoring-manifest.json': encoded(score),
        'selection.json': archived['selection.json'],
    }
    for name in INPUT_NAMES:
        require(actual[name] == expected[name], 'known input content differs beyond revision binding: ' + name)
    return slots(runtime)


def verify_protected_tree(repo):
    require(git(repo, 'rev-parse', 'HEAD').decode().strip() == PROTECTED_COMMIT
            and not git(repo, 'status', '--porcelain'), 'expected the clean protected development checkout')
    freeze = raw(repo, PROTECTED_COMMIT, SOURCE_FREEZE)
    require(sha(freeze) == SOURCE_FREEZE_SHA, 'protected freeze differs from the baseline')
    files = decode(freeze)['files']
    paths = [safe_relative(row['path']) for row in files]
    require(len(paths) == len(set(paths)) == 331, 'protected source file population changed')
    tree = {
        name: metadata.split()
        for entry in git(repo, 'ls-tree', '-rz', PROTECTED_COMMIT).decode().split('\0')
        if entry for metadata, name in (entry.split('\t', 1),)
    }
    for relative, row in zip(paths, files):
        path = local(repo / relative)
        require(tree[relative][1:] == ['blob', row['gitBlobSha1']]
                and path.stat().st_size == row['bytes'] and file_digest(path) == full_sha(row['sha256']),
                'protected source mismatch: ' + relative)
    identities = {}
    for relative in SOURCES:
        protected = raw(repo, PROTECTED_COMMIT, relative)
        require(protected == local(repo / relative).read_bytes() == (ROOT / relative).read_bytes(),
                'offline reader differs from the protected implementation: ' + relative)
        identities[relative] = sha(protected)
    return identities


def verify_bin_dir(directory, expected, expected_count):
    entries = sorted(directory.rglob('*'))
    require(all(not item.is_symlink() and (item.is_dir() or item.is_file()) for item in entries),
            'linked or special release output')
    found = {p.relative_to(directory).as_posix(): p for p in entries if p.is_file()}
    require(found.keys() == expected.keys() and len(found) == expected_count,
            'protected Release file population changed')
    state = {name: content_identity(path) for name, path in found.items()}
    for name, path in found.items():
        row = expected[name]
        require(type(row['bytes']) is int and path.stat().st_size == row['bytes']
                and file_digest(path) == full_sha(row['sha256']), 'protected Release file mismatch: ' + name)
    require(all(not path.is_symlink() and content_identity(path) == state[name] for name, path in found.items())
            and set(found.values()) == {p for p in directory.rglob('*') if p.is_file()},
            'protected Release inventory changed during readback')
    return len(found)


def verify_build(manifest_path):
    body = manifest_path.read_bytes()
    require(sha(body) == RELEASE_SHA, 'historical Release manifest differs from the recorded build')
    manifest = decode(body)
    require(manifest['candidateCommit'] == PROTECTED_COMMIT, 'protected source and built revision differ')
    tests = local(manifest['testsOutputRoot'], directory=True)
    framework = local(manifest['blazorFrameworkOutputRoot'], directory=True)
    test_count = verify_bin_dir(tests, manifest['testsOutput'], 576)
    framework_count = verify_bin_dir(framework, manifest['blazorFrameworkOutput'], 450)
    assembly = local(tests / 'Aijade.Tests.dll')
    revision = '0.1.0+' + PROTECTED_COMMIT
    require(revision.encode() in assembly.read_bytes(), 'the protected test assembly revision is absent')
    return dict(status='HISTORICAL_ENGINEERING_BUILD_READ_BACK', manifestSha256=sha(body),
                embeddedSourceRevision=revision, testOutputFiles=test_count, blazorFrameworkFiles=framework_count,
                testAssemblySha256=file_digest(assembly), qualifiesAsApprovedBuildFreeze=False)


def require_pending_governance(repo, review_pdf):
    scope_body = raw(repo, PROTECTED_COMMIT, SCOPE_PATH)
    require(sha(scope_body) == SCOPE_SHA256 and local(repo / SCOPE_PATH).read_bytes() == scope_body,
            'original Chapter 7 scope record changed')
    scope = decode(scope_body)
    require(file_digest(review_pdf) == REVIEW_SHA == scope['supervisorReview']['sha256'],
            'the supervisor review PDF bytes differ from the scope record')
    require(scope['qualificationPlanReply'] == 'PENDING'
            and scope['qualificationRunUnderRevisedCriteria'] == scope['heldoutComparison'] == scope['table7_3'] == 'NOT_RUN'
            and scope['newConcreteCaseConstruction'] == 'NOT_STARTED' and scope['caseGenerationSeed'] is None,
            'protected preparation scope is not the pending-reply snapshot')
    canonical = (DECISION, BUILD, ACCEPTANCE, FREEZE)
    require(not git(repo, 'ls-tree', '-rz', PROTECTED_COMMIT, '--', *canonical)
            and all(not (repo / name).exists() and not (repo / name).is_symlink() for name in canonical),
            'a formal publication is present; this offline-baseline check is inapplicable')
    return dict(originalReviewSha256=REVIEW_SHA, scopeSha256=SCOPE_SHA256,
                qualificationReplyBound=False, qualificationReplyStatus='PENDING',
                requiredFutureDecisionDigests=list(APPROVAL_FIELDS), absentFormalPublicationPaths=list(canonical),
                macQualification='NOT_RUN', heldoutComparison='NOT_RUN', table7_3='NOT_RUN')


def sources_available(repo, expected, deck):
    rows = {}
    require(len(expected) == 4, 'wrong archived programme-source population')
    for name, digest in expected.items():
        relative = safe_relative(name)
        require(sha(raw(repo, PROTECTED_COMMIT, relative)) == full_sha(digest),
                'archived programme source differs at the frozen Git object: ' + relative)
        source = repo / relative
        present = source.exists() or source.is_symlink()
        if present:
            require(file_digest(local(source)) == digest, 'materialized programme source differs: ' + relative)
        if deck is not None:
            require(file_digest(local(deck / relative)) == digest, 'offline archive deck differs: ' + relative)
        rows[relative] = dict(sha256=digest, protectedGitObjectMatches=True,
                              protectedCheckoutMaterialized=present, separateOfflineDeckMatches=deck is not None)
    return rows


def readback(repo, manifest, review_pdf, scratch, deck=None):
    governance = require_pending_governance(repo, review_pdf)
    sources = verify_protected_tree(repo)
    build = verify_build(manifest)
    archived = {name: raw(repo, PROTECTED_COMMIT, ARCHIVED_INPUTS + name) for name in INPUT_NAMES}
    require({name: sha(body) for name, body in archived.items()} == ARCHIVED_INPUT_HASHES,
            'historical known-condition archive differs')
    with TemporaryDirectory(prefix='known-material-readback-', dir=scratch) as staging:
        output = Path(staging)
        qualify(repo, PROTECTED_COMMIT, output)
        actual = {name: (output / name).read_bytes() for name in INPUT_NAMES}
    ordered = match_known_material(archived, actual, PROTECTED_COMMIT)
    worklist = raw(repo, PROTECTED_COMMIT, WORKLIST)
    slots_expected = [dict(slot=i, caseId=case, condition=arm) for i, (case, arm) in enumerate(ordered, 1)]
    require(decode(worklist)['repeats'] == [
        dict(repeat=i, initialState='isolated', slots=slots_expected, status='NOT_RUN') for i in (1, 2)
    ], 'worklist is not the two exact 20-condition plans')
    dependencies = sources_available(repo, decode(actual['selection.json'])['sources'], deck)
    expected_files = sorted(EVIDENCE_FILES)
    require(not git(repo, 'status', '--porcelain') and git(repo, 'rev-parse', 'HEAD').decode().strip() == PROTECTED_COMMIT,
            'protected checkout changed during readback')
    return dict(schema='aijade.ch7.protected-known-repeat-readback.v1',
                status='OFFLINE_PREPARATION_VERIFIED_NONEXECUTABLE', protectedSourceCommit=PROTECTED_COMMIT,
                protectedSourceFreezeSha256=SOURCE_FREEZE_SHA, protectedSourceFilesVerified=331,
                checkedReaderSourcesSha256=sources, historicalBuild=build, governance=governance,
                known=dict(archivedInputSha256=ARCHIVED_INPUT_HASHES,
                           protectedRevisionReplayedInputSha256={name: sha(body) for name, body in actual.items()},
                           onlyRevisionAndDependentRuntimeHashRebound=True,
                           frozenWorklistSha256=sha(worklist), orderedConditions=slots_expected,
                           slotsPerRepeat=20, repeatsPlanned=2, plannedSlots=40, measuredSlots=0,
                           originalProgrammeSources=dependencies,
                           sparseCheckoutProgrammeSourceCount=sum(
                               row['protectedCheckoutMaterialized'] for row in dependencies.values()),
                           separateOfflineDeckSourceCount=len(dependencies) if deck is not None else 0),
                expectedAcceptanceEvidence=dict(fileCount=len(expected_files), requiredFiles=expected_files,
                                                inventorySha256=sha(encoded(expected_files)),
                                                actualAcceptanceReceiptPresent=False),
                newQualificationRuns=0, newHeldoutCases=0, newHeldoutSeeds=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('protected-repo', 'historical-release-manifest', 'supervisor-review', 'scratch'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--archive-deck')
    args = parser.parse_args()
    try:
        report = readback(local(args.protected_repo, directory=True), local(args.historical_release_manifest),
                          local(args.supervisor_review), local(args.scratch, directory=True),
                          local(args.archive_deck, directory=True) if args.archive_deck else None)
        sys.stdout.buffer.write(encoded(report))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
