#!/usr/bin/env python3
"""Offline audit of one terminal refusal; never a qualification runner.

Only Git object reads, archive reads and independent replay are permitted.
In-memory guard cache entries bind actual input bytes, never claimed hashes.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import subprocess
import sys
from datetime import datetime

Q = '0c42cc29c64730131466af6b079a900005713cba'
B = 'efbcfa0196cbc69bd24cad5b03f01b5078898b7b'
P = '9f3a5ead4ca63f489399907fe2e2a8d2aecbab68'
PLAN = 'experiments/plans/2026-11-17-ch7-mac-lifecycle-continuity.md'
PLAN_SHA = '1599aa06b81a4a8ea97a36e70f5a76aec5b70eb5c43f8e687c5addfaf5c35c72'
BUILD = 'experiments/ch7/mac-lifecycle-2026-11-17/'
FACT_SHA = 'ad08fc3bd515799523a0f21111f31c2d531379200a25c9f8d62125a477980582'
INPUT_SHA = {
    'selection.json': 'f252859a56df3a736bf6001f571c2f1c6dfbe6ea3398549125213ba8127de98d',
    'runtime-manifest.json': '2ddff5567a7b253d78141da067e26c4952c70b8c806d3db23ca7b8a4df68d2c9',
    'scoring-manifest.json': '6109e74024c369c0636f412bac92759a173a9d07cfdb24f2ffbdd85196abd724',
}
OLD = [
    ('experiments/ch7/mac-formal-2026-11-16/packet', '51d95447adf50e028daddf64b48138000db22fafad45e5d2569687707cd77b6f', 85),
    ('experiments/ch7/mac-census-2026-11-16/packet', '04897ab29eb5eca4b47d4d0aef872777497cd627e4ebcfa99b796f851ff46c1a', 71),
]
CAP = 512 * 1024 * 1024
_GIT = {}
_GUARD_CACHE = {}


class Refused(ValueError):
    pass


def need(test, code):
    if not test:
        raise Refused(code)


def count(value, expected, code):
    need(type(value) is int and value == expected, code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def unique(pairs):
    value = {}
    for k, v in pairs:
        need(k not in value, 'DUPLICATE_JSON_KEY')
        value[k] = v
    return value


def decode(body):
    return json.loads(body, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(Refused('NONFINITE_JSON')))


def relative(value):
    need(type(value) is str and value and '\\' not in value and '\x00' not in value,
         'INVALID_RELATIVE_PATH')
    path = PurePosixPath(value)
    need(not path.is_absolute() and str(path) == value and all(p not in ('.', '..') for p in path.parts),
         'INVALID_RELATIVE_PATH')
    return value


def read(root, name):
    """Exactly one plain or gzip representation, with bounded decompression."""
    relative(name)
    plain, compressed = root / name, root / (name + '.gz')
    need(plain.is_file() != compressed.is_file(), 'LOGICAL_REPRESENTATION_NOT_UNIQUE:' + name)
    physical = plain if plain.is_file() else compressed
    need(not physical.is_symlink(), 'ARCHIVE_SYMLINK')
    with (physical.open('rb') if physical == plain else gzip.open(physical, 'rb')) as stream:
        body = stream.read(CAP + 1)
    need(len(body) <= CAP, 'LOGICAL_BODY_CAP')
    return body


def data(root, name):
    return decode(read(root, name))


def git(repo, commit, name):
    relative(name)
    key = (str(repo.resolve()), commit, name)
    if key not in _GIT:
        result = subprocess.run(['git', '-C', str(repo), 'show', commit + ':' + name],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        need(result.returncode == 0 and len(result.stdout) <= CAP, 'GIT_BLOB_UNAVAILABLE:' + name)
        _GIT[key] = result.stdout
    return _GIT[key]


def git_population(repo, commit, prefix):
    result = subprocess.run(['git', '-C', str(repo), 'ls-tree', '-rz', '--name-only', commit, '--', prefix + '/'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    need(result.returncode == 0, 'GIT_POPULATION_READ_FAILED')
    return {p.decode() for p in result.stdout.split(b'\0') if p}


def manifest_check(root):
    manifest = data(root, 'packet-manifest.json')
    need(set(manifest) == {'schema', 'files'} and manifest['schema'] ==
         'aijade.ch7.mac-lifecycle-packet-manifest.v1', 'MANIFEST_SCHEMA')
    need(type(manifest['files']) is list and manifest['files'], 'MANIFEST_POPULATION')
    paths, logicals = set(), set()
    for row in manifest['files']:
        path = relative(row['path'])
        allowed = {'path', 'sha256', 'sizeBytes'} | ({'logicalSha256', 'logicalSizeBytes'} if path.endswith('.gz') else set())
        need(set(row) == allowed and path != 'packet-manifest.json' and path not in paths, 'MANIFEST_ROW_SCHEMA')
        paths.add(path)
        physical = root / path
        need(physical.is_file() and not physical.is_symlink(), 'MANIFEST_FILE_MISSING:' + path)
        body = physical.read_bytes()
        need(type(row['sizeBytes']) is int and len(body) == row['sizeBytes'] and sha(body) == row['sha256'],
             'PHYSICAL_FILE_MISMATCH:' + path)
        logical = path[:-3] if path.endswith('.gz') else path
        need(logical not in logicals, 'DUPLICATE_LOGICAL_PATH')
        logicals.add(logical)
        if path.endswith('.gz'):
            inflated = read(root, logical)
            need(type(row['logicalSizeBytes']) is int and len(inflated) == row['logicalSizeBytes'] and
                 sha(inflated) == row['logicalSha256'], 'LOGICAL_FILE_MISMATCH:' + path)
    actual = set()
    for path in root.rglob('*'):
        need(not path.is_symlink(), 'ARCHIVE_SYMLINK')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    need(actual == paths | {'packet-manifest.json'}, 'MANIFEST_CLOSED_POPULATION')
    need(not any('launch-refused-' in p or p.endswith('.pmx') or 'authcache' in p.lower()
                 or p.endswith(('flow.json', 'render-receipt.json')) for p in paths), 'UNEXPECTED_FALLBACK_OR_WORKLOAD_FILE')
    return manifest


def source_check(root, repo):
    need(read(root, 'publication/plan.md') == git(repo, P, PLAN) == git(repo, Q, PLAN), 'PLAN_GIT_BYTES')
    need(sha(read(root, 'publication/plan.md')) == PLAN_SHA, 'PLAN_SHA')
    build = data(root, 'publication/frozen-build.json')
    need(build['commit'] == Q and build['formalHardwareQualification'] is False and
         build['independentHumanReview'] is False, 'BUILD_SCOPE')
    for name in ('frozen-build.json', 'native-build.json', 'prepared-renderer-full-tree.json'):
        need(read(root, 'publication/' + name) == git(repo, B, BUILD + name), 'BUILD_GIT_BYTES:' + name)
    policy = read(root, 'qualification/process-policy.json')
    need(policy == git(repo, Q, 'configs/research/ch7-mac-lifecycle-process-policy.json'), 'POLICY_GIT_BYTES')
    sources = build['observerSources']
    need(type(sources) is dict and len(sources) == 14, 'SOURCE_POPULATION14')
    for path, digest in sources.items():
        body = read(root, 'source/' + relative(path))
        need(body == git(repo, Q, path) and sha(body) == digest, 'SOURCE_GIT_BYTES:' + path)
        need((repo / path).read_bytes() == body, 'REPLAY_REPO_NOT_FROZEN_Q:' + path)
    freeze = decode(git(repo, Q, 'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'))
    need(len(freeze['files']) == 331 and len({r['path'] for r in freeze['files']}) == 331, 'PROTECTED_POPULATION331')
    for row in freeze['files']:
        body = git(repo, Q, row['path'])
        need(len(body) == row['bytes'] and sha(body) == row['sha256'] and
             hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == row['gitBlobSha1'],
             'PROTECTED_GIT_BYTES:' + row['path'])
        need(sha((repo / row['path']).read_bytes()) == row['sha256'], 'PROTECTED_REPLAY_REPO_BYTES')
    post = data(root, 'metadata/protected-source-post.json')
    count(post['fileCount'], 331, 'PROTECTED_POST_COUNT')
    need(post['sourceCommit'] == Q and post['readOnly'] is True and
         post['status'] == 'ALL_331_ACTUAL_PROTECTED_SOURCE_BYTES_UNCHANGED' and
         post['files'] == {row['path']: row['sha256'] for row in freeze['files']}, 'PROTECTED_POST_BINDING')
    binary_post = data(root, 'metadata/binary-post.json')
    need(binary_post['sourceCommit'] == Q and binary_post['readOnly'] is True and
         binary_post['status'] == 'ALL_FROZEN_BINARY_DEPENDENCY_AND_OBSERVER_BYTES_UNCHANGED' and
         binary_post['files'] == build['files'] and binary_post['observerSources'] == sources and
         binary_post['nativeHelperSha256'] == build['nativeCensus']['sha256'], 'BINARY_POST_BINDING')
    count(len(binary_post['files']), 576, 'BINARY_POST_POPULATION576')
    old_results = []
    for prefix, digest, count in OLD:
        body = git(repo, Q, prefix + '/packet-manifest.json')
        need(sha(body) == digest, 'HISTORICAL_MANIFEST_SHA')
        old = decode(body)
        need(len(old['files']) == count, 'HISTORICAL_POPULATION')
        expected = {prefix + '/packet-manifest.json'}
        for row in old['files']:
            path = relative(row['path']); expected.add(prefix + '/' + path)
            payload = git(repo, Q, prefix + '/' + path)
            need(sha(payload) == row['sha256'] and len(payload) == row.get('sizeBytes', row.get('bytes')),
                 'HISTORICAL_FILE_SHA:' + path)
        need(git_population(repo, Q, prefix) == expected, 'HISTORICAL_CLOSED_POPULATION')
        old_results.append(dict(path=prefix, payloads=count, manifestSha256=digest))
    facts = read(root, 'metadata/facts-baseline.json')
    need(sha(facts) == FACT_SHA and len(decode(facts)) == 12352, 'FACTS_BASELINE12352')
    return build, decode(policy), dict(protectedSourceFiles=331, historicalPackets=old_results,
        baselineFacts=12352, baselineFactsSha256=FACT_SHA, sources=sources)


def publication_check(root, repo):
    source = data(root, 'publication/source-publication.json')
    build = data(root, 'publication/build-publication.json')
    remote = data(root, 'publication/remote-source.json')
    config = read(root, 'publication/fixed-launch-config.json')
    pre = data(root, 'publication/prelaunch.json')
    launch = data(root, 'publication/launch.json')
    terminal = data(root, 'publication/terminal.json')
    plan = data(root, 'publication/plan-publication.json')
    ci = data(root, 'publication/source-ci.json')
    need(plan['commit'] == P and plan['path'] == PLAN and plan['sha256'] == PLAN_SHA,
         'PLAN_PUBLICATION_RECORD')
    need(ci['headSha'] == Q and ci['conclusion'] == 'success' and ci['status'] == 'completed',
         'SOURCE_CI_NOT_SUCCESSFUL_Q')
    need(source['sourceCommit'] == Q and build['sourceCommit'] == Q and build['buildFreezeCommit'] == B and
         remote['sha'] == Q, 'PUBLICATION_IDENTITIES')
    for commit, trees in ((Q, [source['tree'], remote['tree']]), (B, [build['tree']])):
        actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', commit + '^{tree}'], timeout=30).decode().strip()
        need(all(tree == actual for tree in trees), 'PUBLICATION_GIT_TREE')
    dates = [plan['checkedAt'], source['checkedAt'], build['checkedAt'], launch['startedAt']]
    dates = [datetime.fromisoformat(value.replace('Z', '+00:00')) for value in dates]
    need(all(a < b for a, b in zip(dates, dates[1:])), 'PLAN_SOURCE_BUILD_LAUNCH_ORDER')
    need(source['plan']['commit'] == P, 'PROSPECTIVE_PLAN_PUBLICATION')
    need(launch['implementationCommit'] == Q and launch['repositoryCommit'] == Q and
         launch['buildFreezeCommit'] == B and launch['configSha256'] == sha(config) and
         pre['configSha256'] == sha(config), 'FIXED_LAUNCH_BINDING')
    fixed = decode(config)
    need(fixed['implementationCommit'] == Q and fixed['repositoryCommit'] == Q and
         fixed['buildFreezeCommit'] == B and fixed['purpose'] == 'qualification_only', 'FIXED_LAUNCH_SCOPE')
    need(launch['automaticRetries'] == terminal['automaticRetries'] == 0 and terminal['controllerExitCode'] == 1 and
         terminal['scientificAcceptance'] is False and terminal['receiptStatus'] == 'STOPPED_PRE_BLOCK', 'TERMINAL_LAUNCH_SCOPE')
    count(launch['automaticRetries'], 0, 'LAUNCH_RETRY_INTEGER')
    count(terminal['automaticRetries'], 0, 'TERMINAL_RETRY_INTEGER')
    count(terminal['controllerExitCode'], 1, 'TERMINAL_EXIT_INTEGER')
    for name in ('prelaunch-integrity.json',):
        value = data(root, 'publication/' + name)
        need(value['implementationCommit'] == Q and value['buildFreezeCommit'] == B and
             value['heldoutSeedConstructed'] is False and value['freshHeldoutCases'] == 0, 'NO_NEW_SEED')
    return dict(implementationCommit=Q, buildFreezeCommit=B, planCommit=P, configSha256=sha(config))


def inputs_check(root, receipt):
    for name, digest in INPUT_SHA.items():
        need(sha(read(root, 'inputs/' + name)) == digest, 'KNOWN_INPUT_BYTES:' + name)
    runtime = data(root, 'inputs/runtime-manifest.json')
    selection = data(root, 'inputs/selection.json')
    scoring = data(root, 'inputs/scoring-manifest.json')
    need(runtime['purpose'] == scoring['purpose'] == 'qualification_only' and
         runtime['constructionFreezeCommit'] == scoring['constructionFreezeCommit'] == Q, 'KNOWN_INPUT_SCOPE')
    planned = [row['input']['caseId'] + '/' + arm for row in runtime['cases'] for arm in row['input']['conditions']]
    need(len(runtime['cases']) == 10 and len(planned) == len(set(planned)) == 20 and
         planned == receipt['unattemptedCaseIds'] and receipt['unknownCaseIds'] == receipt['inFlightCaseIds'] == [],
         'KNOWN20_DISPOSITION')
    need(selection['newModelJudgments'] == selection['newHeldoutCases'] == 0 and
         scoring['round2SemanticActCorrectness'] == 'NOT_MEASURED', 'INPUT_NOT_HELDOUT')
    return dict(knownPairs=10, knownConditionRows=20, unattempted=20, freshHeldout=0)


def terminal_shape(root):
    receipt = data(root, 'qualification/receipt.json')
    partial = data(root, 'qualification/settling/receipt.json')
    continuity = data(root, 'qualification/preflight-continuity.json')
    for name in ('completedBlocks', 'completedConditionRows', 'modelRequests'):
        count(receipt[name], 0, 'TERMINAL_INTEGER:' + name)
    for name, expected in (('plannedPairs', 10), ('plannedConditionRows', 20), ('plannedBlocks', 1)):
        count(receipt[name], expected, 'PLANNED_INTEGER:' + name)
    for name, expected in (('samples', 294), ('validatedSamples', 293), ('expectedSamples', 300)):
        count(partial[name], expected, 'PARTIAL_INTEGER:' + name)
    for name, expected in (('samples', 294), ('validatedSamples', 293)):
        count(continuity[name], expected, 'CONTINUITY_INTEGER:' + name)
    need(receipt['status'] == 'STOPPED_PRE_BLOCK' and receipt['measurementStarted'] is False and
         receipt['implementationCommit'] == receipt['repositoryCommit'] == Q and receipt['buildFreezeCommit'] == B,
         'TERMINAL_RECEIPT_IDENTITIES')
    need(receipt['formalHardwareQualification'] is False and receipt['independentHumanReview'] is False and
         receipt['completedBlocks'] == receipt['completedConditionRows'] == receipt['modelRequests'] == 0 and
         receipt['blocks'] == [], 'TERMINAL_NOT_QUALIFIED')
    need(read(root, 'qualification/admission/telemetry.jsonl') == b'', 'ADMISSION_EMPTY_PREPARED_ONLY')
    need(partial['status'] == continuity['status'] == 'PREFLIGHT_REFUSED' and
         partial['samples'] == 294 and partial['validatedSamples'] == 293 and partial['expectedSamples'] == 300,
         'TERMINAL_POPULATION294_293_300')
    need(set(continuity['phases']) == {'settling'} and continuity['samples'] == 294 and
         continuity['validatedSamples'] == 293 and continuity['reasonCode'] == 'INVALID_SAMPLE' and
         continuity['runtimeHandoffAnchor'] is None and continuity['windowReset'] is False, 'NO_ADMISSION_OR_RESET')
    need('raw observation completed after the fixed phase deadline' in continuity['reason'] and
         'raw observation completed after the fixed phase deadline' in receipt['reason'], 'TERMINAL_REFUSAL_REASON')
    raw = read(root, 'qualification/settling/telemetry.jsonl')
    samples = [decode(line) for line in raw.splitlines()]
    events = [decode(line) for line in read(root, 'qualification/phase-events.jsonl').splitlines()]
    need(len(samples) == 294 and len(events) == 295 and [r['globalIndex'] for r in samples] == list(range(294)),
         'CONTIGUOUS_RAW294')
    need(all(type(r['globalIndex']) is int and type(r['rssBytes']) is int for r in samples),
         'SAMPLE_INTEGER_TYPES')
    need([r['streamValidationStatus'] for r in samples] == ['PASS'] * 293 + ['REFUSED'], 'STREAM293_DEADLINE_REFUSED')
    need(all(r['processObservation']['status'] == 'PASS' and r['processObservation']['ownedRoots'] ==
             r['processObservation']['ownedProcesses'] == [] for r in samples), 'PROCESS294_UNLOADED')
    origin = continuity['schedule']['originMonotonic']
    need(all(r['globalScheduledMonotonic'] == origin + 2 * i and r['scheduledSeconds'] == 2 * i
             for i,r in enumerate(samples)), 'ABSOLUTE_SCHEDULE_NO_SKIP')
    need(samples[-1]['monotonicSeconds'] < origin + 600 < samples[-1]['observationCompletedMonotonic'],
         'TERMINAL_DEADLINE_CROSSING')
    need(max(b['monotonicSeconds'] - a['monotonicSeconds'] for a,b in zip(samples,samples[1:])) <= 3,
         'RECORDED_START_GAP')
    need(events[0]['event'] == 'phase-enter' and events[0]['phase'] == 'settling' and
         all(e['event'] == 'sample-written' and e['sampleId'] == s['sampleId'] and e['globalIndex'] == i
             for i,(e,s) in enumerate(zip(events[1:],samples))), 'PHASE_EVENT_POPULATION')
    return receipt, samples, continuity


def directory_check(root, manifest):
    directory = data(root, 'metadata/directory-state.json')
    expected = {}
    for row in manifest['files']:
        if row['path'].startswith('qualification/'):
            logical = row['path'][len('qualification/'):]
            expected[logical[:-3] if logical.endswith('.gz') else logical] = row.get('logicalSizeBytes', row['sizeBytes'])
    need(canonical(directory['files']) == canonical(expected), 'DIRECTORY_LOGICAL_POPULATION')
    count(directory['admissionTelemetryPreparedBytes'], 0, 'PREPARED_EMPTY_ADMISSION_BYTES')
    need(directory['directories'] == ['admission', 'settling'] and directory['blockDirectories'] == [],
         'NO_BLOCK_OR_FLOW_DIRECTORY')
    actual = sorted(p.relative_to(root / 'qualification').as_posix()
                    for p in (root / 'qualification').rglob('*') if p.is_dir())
    need(actual == ['admission', 'settling'], 'UNEXPECTED_PHYSICAL_QUALIFICATION_DIRECTORY')


def replay_check(root, repo, policy, samples, cache):
    # The independent terminal replay module is separately audited and shipped
    # beside this tool. It must never convert runtime qualification into PASS.
    path = Path(__file__).with_name('terminal_replay.py')
    need(path.is_file(), 'INDEPENDENT_TERMINAL_REPLAYER_MISSING')
    spec = importlib.util.spec_from_file_location('aijade_independent_terminal_replay', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.audit_terminal(root=root, repo=repo, cache=cache)


def audit(root, repo, cache=None):
    root, repo = Path(root).resolve(), Path(repo).resolve()
    result = dict(schema='aijade.ch7.lifecycle-terminal-archive-audit.v1',
        terminalRecordIntegrityAccepted=False, fullQualified=False, formalHardwareQualification=False,
        heldoutComparisonComplete=False, independentHumanReview=False)
    try:
        manifest = manifest_check(root)
        build, policy, source = source_check(root, repo)
        publication = publication_check(root, repo)
        receipt, samples, continuity = terminal_shape(root)
        directory_check(root, manifest)
        inputs = inputs_check(root, receipt)
        replay = replay_check(root, repo, policy, samples, _GUARD_CACHE if cache is None else cache)
        need(replay.get('terminalRecordIntegrityAccepted') is True and replay.get('fullQualified') is False,
             'INDEPENDENT_TERMINAL_REPLAY_REFUSED')
        archived = data(root, 'audit/independent-lifecycle-refusal-audit.json')
        computed = replay['independentReplay']
        need(archived['sourceCommit'] == Q and archived['buildFreezeCommit'] == B and archived['planCommit'] == P and
             canonical(archived['numbers']) == canonical(computed['numbers']) and
             canonical(archived['scope']) == canonical(computed['scope']),
             'ARCHIVED_INDEPENDENT_REPORT_CHANGED')
        need(archived['scope']['terminalRecordIntegrityAccepted'] is True and
             archived['scope']['fullFiniteDriverQualified'] is False and
             archived['frozenRuntimeAuditor']['status'] == 'FROZEN_PREDICATE_REFUSAL' and
             'runtime must have one exact local persistent root' in archived['frozenRuntimeAuditor']['error'],
             'RUNTIME_REFUSAL_MISREPRESENTED_AS_QUALIFICATION')
        result.update(status='TERMINAL_REFUSAL_RECORD_INTEGRITY_ACCEPTED_NOT_QUALIFIED',
            terminalRecordIntegrityAccepted=True, payloadFiles=len(manifest['files']),
            manifestSha256=sha(read(root, 'packet-manifest.json')), publication=publication,
            preserved=source, inputs=inputs, terminalReplay=replay,
            recordedProcessPass=294, streamAccepted=293, requiredSettling=300,
            admissionSamples=0, runtimeSamples=0, completedRows=0,
            runtimeQualificationStatus='NOT_RUN', live19CorruptionControls='NOT_RUN')
    except Exception as error:
        result.update(status='ARCHIVE_INTEGRITY_REFUSED', errorClass=type(error).__name__, reason=str(error))
        if hasattr(error, 'terminalReplayFailure'):
            result['terminalReplayFailure'] = error.terminalReplayFailure
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.repo)
    need(not args.output.exists() and args.root.resolve() not in args.output.resolve().parents,
         'OUTPUT_MUST_BE_NEW_AND_OUTSIDE_PACKET')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['terminalRecordIntegrityAccepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
