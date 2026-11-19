#!/usr/bin/env python3
"""Verify a complete protected checkout and prepare freeze materials pending approval."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from audit_known_repeat_launch_preflight import check_sources
from finite_construction_binding import decode
from finite_inputs import ROOT, qualify
from finite_runtime import require
from known_repeat_acceptance import BUILD, DECISION, git, raw
from launch_known_repeats import digest, encode, file_digest
from preflight_known_repeat_readback import (
    ARCHIVED_INPUTS, PROTECTED_COMMIT, local, match_known_material,
    require_pending_governance, verify_build,
)
from prepare_known_repeats import ARCHIVED_INPUT_HASHES, INPUT_NAMES


WORKSPACE = ROOT.parent
PLAN_SHA256 = 'fc91f7ee56dd4878bc3d3715d97bd59e167060a5abca29a4a143f0d9b89771bb'
PRIOR_READINESS = ROOT / 'experiments/ch7/mac-formal-launch-readiness-20261119.json'


def new_path(value):
    path = Path(value).absolute()
    require(path.resolve() == path and path.is_relative_to(WORKSPACE)
            and path.parent.is_dir() and not path.exists(),
            'use a new workspace-local destination under an existing directory')
    return path


def write_new(path, value):
    with path.open('xb') as stream:
        stream.write(encode(value))


def check_hardlink(parent):
    """Verify the filesystem primitive of the later B publisher without issuing B."""
    with TemporaryDirectory(prefix='hardlink-check-', dir=parent) as scratch:
        origin, link = Path(scratch) / 'origin', Path(scratch) / 'link'
        origin.write_bytes(b'PREAPPROVAL FILESYSTEM CHECK')
        os.link(origin, link)
        return os.path.samefile(origin, link) and link.read_bytes() == origin.read_bytes()


def prepare(args):
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    source = local(args.protected_repo, directory=True)
    stage, output = local(args.staging, directory=True), new_path(args.output)
    require(stage != output and not stage.is_relative_to(output) and not output.is_relative_to(stage)
            and not stage.is_relative_to(source) and not output.is_relative_to(source)
            and not stage.is_relative_to(ROOT) and not output.is_relative_to(ROOT),
            'staging and evidence must be isolated from both source checkouts')
    review, plan = local(args.supervisor_review), local(args.qualification_plan)
    require(file_digest(plan) == PLAN_SHA256, 'one-page qualification plan bytes changed')
    governance = require_pending_governance(source, review)
    before = check_sources(source)
    require(before['checkoutCommit'] == PROTECTED_COMMIT and not before['protectedPhysicalMissing'],
            'expected the complete protected baseline')
    archived = {name: raw(source, PROTECTED_COMMIT, ARCHIVED_INPUTS + name) for name in INPUT_NAMES}
    require({name: digest(body) for name, body in archived.items()} == ARCHIVED_INPUT_HASHES,
            'archived known-input bytes differ')
    programmes = decode(archived['selection.json'])['sources']
    build_path = local(args.historical_release_manifest)
    build = verify_build(build_path)
    inventory = decode(build_path.read_bytes())
    require(check_hardlink(stage.parent), 'the staging filesystem did not preserve hardlink identity')
    staged = check_sources(stage)
    require(staged['checkoutCommit'] == PROTECTED_COMMIT
            and staged['protectedPhysicalFilesMatched'] == 331 and staged['programmePhysicalFilesMatched'] == 4,
            'staged checkout does not materialize every exact protected and programme file')
    fixture_rows = {}
    for path, sha in sorted(programmes.items()):
        body = raw(source, PROTECTED_COMMIT, path)
        material = stage / path
        require(digest(body) == sha and material.read_bytes() == body, 'staged programme bytes differ: ' + path)
        fixture_rows[path] = dict(sha256=sha, bytes=len(body), gitAndTrackedPathMatch=True)

    output.mkdir(mode=0o700)
    known = output / 'known-qualification-inputs-preapproval'
    qualify(stage, PROTECTED_COMMIT, known)
    actual = {name: (known / name).read_bytes() for name in INPUT_NAMES}
    order = match_known_material(archived, actual, PROTECTED_COMMIT)
    candidate_plan = output / 'one-page-qualification-plan.original.pdf'
    shutil.copyfile(plan, candidate_plan)
    require(file_digest(candidate_plan) == PLAN_SHA256, 'private reviewed PDF copy differs')
    candidate_b = output / 'protected-release-build-preapproval-inventory.json'
    write_new(candidate_b, dict(
        schema='aijade.ch7.protected-release-byte-inventory.v1', status='ENGINEERING_BUILD_PREAPPROVAL_CANDIDATE',
        sourceCommitVerified=PROTECTED_COMMIT, launchEligible=False, formalBuildFreeze=False,
        approvedSuccessorAssemblyRequired=True, engineeringBuild=build,
        testsOutputRoot=inventory['testsOutputRoot'], testsOutput=inventory['testsOutput'],
        blazorFrameworkOutputRoot=inventory['blazorFrameworkOutputRoot'],
        blazorFrameworkOutput=inventory['blazorFrameworkOutput'],
    ))
    prior = decode(PRIOR_READINESS.read_bytes())
    require(prior['comparisonBasis']['sourcePlanSha256']['onePageQualificationPlan'] == PLAN_SHA256,
            'candidate tooling snapshot refers to another qualification plan')
    candidate_q = output / 'qualification-implementation-preapproval-inputs.json'
    write_new(candidate_q, dict(
        schema='aijade.ch7.qualification-preapproval-materials.v1', status='PENDING_SUPERVISOR_REPLY',
        sourceBaseCommit=PROTECTED_COMMIT, checkoutPath=str(stage), purpose='qualification_only',
        qualificationPlanSha256=PLAN_SHA256, replySha256=None, executionPlanSha256=None,
        eventualDecisionPath=DECISION, eventualBuildFreezePath=BUILD,
        prospectivePlan=dict(repeats=2, conditionSlotsPerRepeat=20, frozenExecutionSettings=None,
                             candidateToolSha256=prior['existingComponents']['candidateToolSha256']),
        futureInputs=['original supervisor reply', 'approved operational settings', 'clean successor Q',
                      'fresh Release binaries embedding Q', 'separate B and private approval binding'],
    ))
    require(require_pending_governance(stage, review) == governance and check_sources(source) == before,
            'formal stages appeared or the original protected checkout changed')
    require(check_sources(stage) == staged, 'the verified APFS staging checkout changed')
    return dict(
        schema='aijade.ch7.mac-qualification-materials-preparation.v1', status='PREAPPROVAL_MATERIALS_READY',
        sourceCommit=PROTECTED_COMMIT, reusedExistingIsolatedStaging=True, stagingClean=True,
        stagingModified=False, stagingRemoteQueried=False, engineeringBuildBytesCopied=False,
        stagingHardlinkCapabilityVerified=True, protectedSourceFreezeSha256=staged['sourceFreezeSha256'],
        protectedFilesVerified=331, originalProtectedWorktreeUnchanged=True,
        originalProtectedProgrammeCount=before['programmePhysicalFilesMatched'], stagedProgrammeCount=4,
        exactProgrammeFiles=fixture_rows, archivedKnownInputSha256=ARCHIVED_INPUT_HASHES,
        stagedKnownInputSha256={name: digest(body) for name, body in actual.items()},
        knownOrdering=dict(conditionsPerRepeat=len(order), plannedRepeats=2, measuredConditions=0),
        governance=governance, reviewedPlanSha256=PLAN_SHA256, candidateEngineeringBuild=build,
        privatePreapprovalInputsSha256=file_digest(candidate_q), privateBuildInventorySha256=file_digest(candidate_b),
        sourceFreezePreparation='ORIGINAL_REPLY_AND_OPERATIONAL_PLAN_PENDING', officialQOrBPublished=False,
        realQualificationRuns=0, newHeldoutPairs=0, newHeldoutSeeds=0, researchProcessesStarted=0,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('protected-repo', 'staging', 'output', 'supervisor-review',
                 'qualification-plan', 'historical-release-manifest'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        sys.stdout.buffer.write(encode(prepare(args)))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(f'Preapproval preparation stopped: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
