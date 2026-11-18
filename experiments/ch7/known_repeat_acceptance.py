#!/usr/bin/env python3
"""Bind two approved known-condition repeats to the future held-out gate.

This module reads evidence only. It does not launch the backend or derive cases.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from finite_construction_binding import (
    KNOWN_REPEAT_BINDING_SCHEMA as BINDING_SCHEMA,
    KNOWN_REPEAT_DECISION as DECISION,
    KNOWN_REPEAT_FREEZE_SCHEMA as FREEZE_SCHEMA,
    KNOWN_REPEAT_SOURCE as SOURCE,
    decode, digest, full_commit, full_sha, known_repeat_required as required,
    qualified_backend, source_paths, typed_equal,
)
from finite_runtime import require, safe_relative


PREFIX = 'experiments/ch7/mac-known-repeats-qualification/'
LAUNCHER = 'experiments/ch7/launch_known_repeats.py'
BUILD = PREFIX + 'frozen-build.json'
ACCEPTANCE = PREFIX + 'qualification-acceptance.json'
FREEZE = PREFIX + 'construction-freeze.json'
EVIDENCE = PREFIX + 'qualification-evidence/'
ACCEPTANCE_SCHEMA = 'aijade.ch7.known-repeat-acceptance.v1'
DECISION_SCHEMA = 'aijade.ch7.known-repeat-decision.v1'
EXPECTED_IDENTITY = 'aijade.ch7.known-repeats-expected-identity.v1'
PRODUCTION = 'PROSPECTIVE_KNOWN_MAC'
QUALIFIED = 'QUALIFIED_BEFORE_FRESH_CASE_CONSTRUCTION'
APPROVAL_FIELDS = ('executionPlanSha256', 'qualificationPlanSha256', 'replySha256')
KNOWN_INPUTS = ('runtime-manifest.json', 'scoring-manifest.json', 'selection.json')
BLOCK_FILES = (
    *KNOWN_INPUTS, 'receipt.json', 'input-identities.json', 'frozen-build.json',
    'cases.json', 'prepared.json', 'journal.jsonl', 'renderer-request.json',
    'renderer-ready.json', 'renderer-closed.json', 'registry.jsonl', 'manifest.json',
    'client/aijade-render-state.jsonl', 'flow.xml', 'process-cleanup.json',
    'database-leases.jsonl', 'database-cleanup.json', 'owned-process-registry.json', 'telemetry.jsonl',
)
EVIDENCE_FILES = frozenset({
    'approval.json', 'launch.json', 'receipt.json',
    *(f'inputs/{name}' for name in KNOWN_INPUTS),
    *(f'repeat-{i}.log' for i in (1, 2)),
    *(f'repeat-{i}/{name}' for i in (1, 2) for name in BLOCK_FILES),
})
ADDITIONAL_SOURCES = {
    SOURCE, LAUNCHER, DECISION, 'experiments/ch7/run_known_repeat_block.py',
    'experiments/ch7/prepare_known_repeats.py',
    'experiments/ch7/compare_known_repeats.py', 'experiments/ch7/audit_retrieval_led.py',
    'experiments/ch7/audit_retrieval_suffix.py', 'experiments/ch7/score_paired_development.py',
    'experiments/ch7/live-manifest-known-input-v1.json',
    'experiments/ch7/manifest-preparation-2026-11-12/comparison-manifest.json',
}


def git(repo, *args):
    # Ignore replace refs so a local alias cannot substitute an immutable freeze.
    return subprocess.check_output(['git', '--no-replace-objects', *args], cwd=repo)


def raw(repo, commit, path):
    return git(repo, 'show', full_commit(commit) + ':' + safe_relative(path))


def ancestor(repo, first, later):
    return subprocess.run(
        ['git', '--no-replace-objects', 'merge-base', '--is-ancestor', full_commit(first), full_commit(later)],
        cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def keys(value, expected, name):
    require(type(value) is dict and set(value) == set(expected), 'unexpected ' + name + ' fields')


def moment(value):
    require(type(value) is str, 'expected a zoned timestamp')
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(instant.tzinfo is not None, 'timestamp must identify a timezone')
    return instant


def parent_closed_at(terminal):
    finished = terminal['finishedAt']
    require(moment(terminal['repeats'][-1]['finishedAt']) <= moment(finished),
            'parent closure predates the final child terminal')
    return finished


def approved_decision(repo, implementation):
    require(required(repo, implementation), 'a successor implementation commit is required')
    decision = decode(raw(repo, implementation, DECISION))
    keys(decision, {'schema', 'status', 'executionPlanPath', *APPROVAL_FIELDS}, 'approved decision')
    require(decision['schema'] == DECISION_SCHEMA and decision['status'] == 'SUPERVISOR_REPLY_CONFIRMED',
            'the supervisor reply has not been confirmed in the frozen decision')
    plan = safe_relative(decision['executionPlanPath'])
    require(plan.startswith(PREFIX), 'approved execution plan must use the successor prefix')
    require(digest(raw(repo, implementation, plan)) == full_sha(decision['executionPlanSha256']),
            'execution plan differs from the agreed decision')
    for name in APPROVAL_FIELDS:
        full_sha(decision[name])
    return decision


def verify_approval(approval_body, expected_approval_sha256, decision, implementation):
    require(digest(approval_body) == full_sha(expected_approval_sha256), 'approval digest mismatch')
    approval = decode(approval_body)
    keys(approval, {'schema', 'status', 'implementationCommit', 'backend', *APPROVAL_FIELDS}, 'approval')
    require(approval['schema'] == 'aijade.ch7.known-repeat-approval.v1'
            and approval['status'] == 'SUPERVISOR_REPLY_CONFIRMED'
            and approval['implementationCommit'] == implementation,
            'approval belongs to another implementation or scope')
    require(all(approval[name] == decision[name] for name in APPROVAL_FIELDS),
            'approval, plan, and supervisor reply identities differ')
    qualified_backend(approval['backend'], closed=True)
    return approval


def bytes_at(root, name):
    path = root / safe_relative(name)
    require(path.resolve() == path.absolute() and path.is_file(), 'missing or redirected evidence: ' + name)
    return path.read_bytes()


def inventory(root):
    result = {}
    for name in sorted(EVIDENCE_FILES):
        body = bytes_at(root, name)
        result[name] = {'sha256': digest(body), 'sizeBytes': len(body)}
    return result


def audit_evidence(repo, implementation, directory, approval_digest, scratch):
    """Recheck both packets and return the bytes/identity needed for acceptance review."""
    from launch_known_repeats import verify_launched_pair
    from prepare_known_repeats import ROOT as DELIVERY_ROOT, check_delivery

    directory = Path(directory).resolve()
    decision = approved_decision(repo, implementation)
    approval_body = bytes_at(directory, 'approval.json')
    approval = verify_approval(approval_body, approval_digest, decision, implementation)
    evidence = inventory(directory)
    launch, terminal = verify_launched_pair(directory, approval_body, approval_digest)
    require(launch.get('launchMode') == PRODUCTION, 'only an actual approved Mac launch is eligible')
    require(Path(repo).resolve() == DELIVERY_ROOT, 'run the evidence reader from the same checkout')
    require(terminal['status'] == 'COMPLETE_KNOWN_REPEAT_LAUNCH', 'the launcher did not close both repeats')
    require(terminal['launchSha256'] == evidence['launch.json']['sha256'], 'terminal does not bind launch bytes')
    build_commit = full_commit(launch.get('buildFreezeCommit'))
    require(launch.get('buildFreezePath') == BUILD and build_commit != implementation
            and ancestor(repo, implementation, build_commit),
            'build must be published at the successor path after the approved implementation')
    build_bytes = raw(repo, build_commit, BUILD)
    backend = approval['backend']
    build = decode(build_bytes)
    require(digest(build_bytes) == backend['buildManifestSha256']
            and build.get('commit') == implementation
            and build.get('assemblyInformationalVersion') == '0.1.0+' + implementation
            and build.get('status') == 'CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION'
            and typed_equal(build.get('files'), backend['binaries']),
            'observed backend did not use the frozen implementation build')
    for repeat in ('repeat-1', 'repeat-2'):
        block = decode(bytes_at(directory, f'{repeat}/input-identities.json'))
        require(block.get('buildFreezeCommit') == build_commit and block.get('buildFreezePath') == BUILD
                and bytes_at(directory, f'{repeat}/frozen-build.json') == build_bytes,
                'observed block differs from the nominated build publication')
    identity = json.dumps({
        'schema': EXPECTED_IDENTITY, 'implementationCommit': implementation,
        'executionPlanSha256': approval['executionPlanSha256'], 'backend': backend,
    }, sort_keys=True, allow_nan=False).encode()
    delivery = check_delivery(directory / 'repeat-1', directory / 'repeat-2', identity, scratch)
    require(delivery['status'] == 'OFFLINE_DELIVERY_EVIDENCE_READY_FOR_REVIEW',
            'complete original delivery and equal casewise decisions required')
    require(inventory(directory) == evidence, 'qualification evidence changed during inspection')
    return {
        'status': 'READY_FOR_QUALIFICATION_ACCEPTANCE_REVIEW',
        'implementationCommit': implementation,
        'approvalSha256': approval_digest,
        'buildFreezeCommit': build_commit,
        'lastFinishedAt': parent_closed_at(terminal),
        'qualifiedBackend': backend,
        'evidence': evidence,
        'qualificationDetermined': False,
    }


def tracked_files(repo, commit, prefix):
    result = {}
    for row in git(repo, 'ls-tree', '-rz', full_commit(commit), '--', prefix).split(b'\0'):
        if not row:
            continue
        meta, full_path = row.decode().split('\t', 1)
        mode, kind, _ = meta.split()
        require(full_path.startswith(prefix), 'evidence outside its canonical prefix')
        result[full_path.removeprefix(prefix)] = (mode, kind)
    return result


def materialize_evidence(repo, publication, evidence, target):
    keys(evidence, EVIDENCE_FILES, 'complete evidence reference')
    tracked = tracked_files(repo, publication, EVIDENCE)
    require(set(tracked) == EVIDENCE_FILES and all(v == ('100644', 'blob') for v in tracked.values()),
            'publication requires the complete regular evidence file population')
    for name, ref in evidence.items():
        keys(ref, {'sha256', 'sizeBytes'}, 'evidence file reference')
        body = raw(repo, publication, EVIDENCE + name)
        require(type(ref['sizeBytes']) is int and len(body) == ref['sizeBytes']
                and digest(body) == full_sha(ref['sha256']), 'published evidence differs: ' + name)
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def verify_acceptance(repo, implementation, publication, expected_digest, scratch):
    require(ancestor(repo, implementation, publication), 'acceptance must descend from the approved implementation')
    contents = raw(repo, publication, ACCEPTANCE)
    require(digest(contents) == full_sha(expected_digest), 'accepted qualification SHA differs')
    value = decode(contents)
    keys(value, {
        'schema', 'status', 'implementationCommit', 'acceptedAt', 'approvalSha256',
        'buildFreezeCommit', 'qualifiedBackend', 'evidence',
    }, 'qualification acceptance')
    require(value['schema'] == ACCEPTANCE_SCHEMA and value['status'] == QUALIFIED
            and value['implementationCommit'] == implementation, 'a matching qualification acceptance is required')
    require(value['buildFreezeCommit'] != publication and ancestor(repo, value['buildFreezeCommit'], publication),
            'qualification acceptance does not follow the frozen build publication')
    with TemporaryDirectory(prefix='known-repeat-evidence-', dir=scratch) as temp:
        directory = Path(temp)
        materialize_evidence(repo, publication, value['evidence'], directory)
        audited = audit_evidence(repo, implementation, directory, value['approvalSha256'], scratch)
    require(audited['buildFreezeCommit'] == value['buildFreezeCommit']
            and typed_equal(audited['qualifiedBackend'], value['qualifiedBackend'])
            and typed_equal(audited['evidence'], value['evidence']),
            'qualification acceptance changed the audited build or evidence')
    require(moment(audited['lastFinishedAt']) <= moment(value['acceptedAt']),
            'qualification acceptance predates its completed evidence')
    return value


def construction_sources(repo, implementation, decision):
    expected = source_paths(repo, implementation) | ADDITIONAL_SOURCES | {decision['executionPlanPath']}
    return {path: digest(raw(repo, implementation, path)) for path in sorted(expected)}


def verify_binding(repo, implementation, binding, model_sha=None):
    """Require approved Q, an accepted real pair, and a later independent freeze."""
    keys(binding, {
        'schema', 'implementationCommit', 'acceptancePublicationCommit', 'acceptanceSha256',
        'constructionFreezePublicationCommit', 'constructionFreezeSha256',
    }, 'known-repeat construction binding')
    require(binding['schema'] == BINDING_SCHEMA and binding['implementationCommit'] == implementation,
            'known-repeat implementation requires its own published construction binding')
    decision = approved_decision(repo, implementation)
    freeze_commit = full_commit(binding['constructionFreezePublicationCommit'])
    accepted_commit = full_commit(binding['acceptancePublicationCommit'])
    require(freeze_commit != accepted_commit and ancestor(repo, accepted_commit, freeze_commit),
            'the construction freeze must be a separate publication after qualification acceptance')
    freeze_body = raw(repo, freeze_commit, FREEZE)
    require(digest(freeze_body) == full_sha(binding['constructionFreezeSha256']), 'published freeze SHA differs')
    freeze = decode(freeze_body)
    keys(freeze, {
        'schema', 'constructionFreezeCommit', 'frozenAt', 'executionPlanSha256',
        'qualificationAcceptance', 'qualifiedBackend', 'modelSha256', 'sources', 'candidateBankSha256',
    }, 'known-repeat construction freeze')
    require(freeze['schema'] == FREEZE_SCHEMA and freeze['constructionFreezeCommit'] == implementation
            and freeze['executionPlanSha256'] == decision['executionPlanSha256'],
            'construction freeze uses different implementation or approved execution plan')
    pointer = {name: binding[name] for name in ('acceptancePublicationCommit', 'acceptanceSha256')}
    require(typed_equal(freeze['qualificationAcceptance'], pointer), 'freeze does not bind the accepted qualifier')
    backend = qualified_backend(freeze['qualifiedBackend'], closed=True)
    require(freeze['modelSha256'] == backend['modelSha256'] and
            (model_sha is None or full_sha(model_sha) == backend['modelSha256']), 'qualified model differs')
    sources = freeze['sources']
    expected = construction_sources(repo, implementation, decision)
    keys(sources, expected, 'construction source closure')
    for path, expected_sha in sources.items():
        require(expected[path] == full_sha(expected_sha)
                and digest(bytes_at(Path(repo).resolve(), path)) == expected_sha,
                'construction source does not match approved Q: ' + path)
    require(freeze['candidateBankSha256'] == sources['experiments/ch7/finite-heldout/candidate-bank.json'],
            'candidate bank is missing from the qualified construction freeze')
    acceptance = verify_acceptance(repo, implementation, accepted_commit, binding['acceptanceSha256'],
                                   Path(repo).resolve().parent)
    require(moment(acceptance['acceptedAt']) <= moment(freeze['frozenAt'])
            and typed_equal(acceptance['qualifiedBackend'], backend), 'freeze changed the accepted backend or chronology')
    return freeze


def draft_freeze(repo, implementation, publication, acceptance_digest, frozen_at):
    decision = approved_decision(repo, implementation)
    accepted = verify_acceptance(repo, implementation, publication, acceptance_digest, repo.parent)
    require(moment(accepted['acceptedAt']) <= moment(frozen_at), 'freeze cannot predate acceptance')
    backend = accepted['qualifiedBackend']
    sources = construction_sources(repo, implementation, decision)
    return {
        'schema': FREEZE_SCHEMA, 'constructionFreezeCommit': implementation, 'frozenAt': frozen_at,
        'executionPlanSha256': decision['executionPlanSha256'],
        'qualificationAcceptance': {
            'acceptancePublicationCommit': publication, 'acceptanceSha256': acceptance_digest,
        },
        'qualifiedBackend': backend, 'modelSha256': backend['modelSha256'],
        'sources': sources, 'candidateBankSha256': sources['experiments/ch7/finite-heldout/candidate-bank.json'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--implementation', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('--evidence-directory', type=Path, required=True)
    inspect.add_argument('--trusted-approval-sha256', required=True)
    freeze = commands.add_parser('draft-freeze')
    freeze.add_argument('--acceptance-publication', required=True)
    freeze.add_argument('--acceptance-sha256', required=True)
    freeze.add_argument('--frozen-at', required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        q = full_commit(args.implementation)
        if args.command == 'inspect':
            data = args.evidence_directory.resolve()
            require(data.is_dir() and data.is_relative_to(repo.parent), 'supply project-local evidence')
            result = audit_evidence(repo, q, data, args.trusted_approval_sha256, repo.parent)
        else:
            result = draft_freeze(repo, q, full_commit(args.acceptance_publication),
                                  args.acceptance_sha256, args.frozen_at)
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(2, f'qualification binding rejected: {error}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
