#!/usr/bin/env python3
"""Coherent archive-corruption controls; no live/window corruption is run."""
import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit


def safe_write(path, body):
    """Replace a clone's inode; never modify a baseline hard link in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.control-new')
    audit.need(not temporary.exists(), 'STALE_CONTROL_TEMP')
    with temporary.open('xb') as stream:
        stream.write(body)
    temporary.replace(path)


def put(root, logical, body):
    plain, compressed = root / logical, root / (logical + '.gz')
    audit.need(plain.is_file() != compressed.is_file(), 'CONTROL_LOGICAL_REPRESENTATION')
    safe_write(plain if plain.is_file() else compressed,
               body if plain.is_file() else gzip.compress(body, mtime=0))


def alter(root, logical, change):
    value = audit.data(root, logical)
    change(value)
    put(root, logical, json.dumps(value, ensure_ascii=False, indent=2).encode() + b'\n')


def fingerprint(root):
    return {p.relative_to(root).as_posix(): audit.sha(p.read_bytes())
            for p in root.rglob('*') if p.is_file()}


def rebind_manifest(root):
    rows = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path == root / 'manifest.json':
            continue
        body = path.read_bytes()
        row = dict(path=path.relative_to(root).as_posix(), sha256=audit.sha(body), sizeBytes=len(body))
        if path.name.endswith('.gz'):
            logical = gzip.decompress(body)
            row.update(logicalSha256=audit.sha(logical), logicalSizeBytes=len(logical))
        rows.append(row)
    safe_write(root / 'manifest.json', json.dumps(dict(
        schema='aijade.ch7.mac-lifecycle-packet-manifest.v1', files=rows), indent=2).encode() + b'\n')


def copy_file(source, destination):
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def bool_counter(root):
    alter(root, 'qualification/receipt.json', lambda d: d.update(completedConditionRows=False))


def qualification_claim(root):
    alter(root, 'qualification/receipt.json', lambda d: d.update(formalHardwareQualification=True))


def count_last_as_stream_accepted(root):
    alter(root, 'qualification/settling/receipt.json', lambda d: d.update(validatedSamples=294))
    def change(d):
        d['validatedSamples'] = 294
        d['phases']['settling']['validatedSamples'] = 294
    alter(root, 'qualification/preflight-continuity.json', change)


def pretend_empty_admission_ran(root):
    put(root, 'qualification/admission/telemetry.jsonl', b'{}\n')


def unknown_instead_of_unattempted(root):
    def change(d):
        d['unknownCaseIds'], d['unattemptedCaseIds'] = d['unattemptedCaseIds'], []
    alter(root, 'qualification/receipt.json', change)


def lose_last_required_raw(root):
    lines = audit.read(root, 'qualification/settling/telemetry.jsonl').splitlines()
    put(root, 'qualification/settling/telemetry.jsonl', b'\n'.join(lines[:-1]) + b'\n')


def coherently_nonempty_sampled_api(root):
    lines = audit.read(root, 'qualification/settling/telemetry.jsonl').splitlines()
    raw = audit.decode(lines[0]); observation = raw['processObservation']
    import base64
    body = b'{"models":[{"name":"controlled-loaded-model"}]}'
    value = observation['evidence']['api']
    value.update(state='EMPTY', httpStatus=200, modelCount=1, bytes=len(body),
                 bodySha256=audit.sha(body), emptyBodyBase64=base64.b64encode(body).decode())
    observation['idleDaemon']['api'] = copy.deepcopy(value)
    lines[0] = audit.canonical(raw)
    logical = b'\n'.join(lines) + b'\n'
    put(root, 'qualification/settling/telemetry.jsonl', logical)
    alter(root, 'metadata/directory-state.json',
          lambda value: value['files'].update({'settling/telemetry.jsonl': len(logical)}))


def falsely_certify_archived_report(root):
    def change(d):
        d['scope']['fullFiniteDriverQualified'] = True
        d['scope']['formalHardwareQualification'] = True
    alter(root, 'audit/independent-lifecycle-refusal-audit.json', change)


def mutate_frozen_guard_and_rebind(root):
    logical = 'source/experiments/ch7/mac_process_guard_v3.py'
    put(root, logical, audit.read(root, logical) + b'\n# coherent archive source mutation\n')


def mutate_one_old_fact_keep_population(root):
    def change(d):
        name = next(iter(d)); d[name] = 'CONTROLLED_CHANGED_BASELINE_VALUE'
    alter(root, 'metadata/facts-baseline.json', change)


def omit_prepared_empty_admission(root):
    path = root / 'qualification/admission/telemetry.jsonl'
    audit.need(path.is_file(), 'EXPECTED_EMPTY_PREPARED_FILE')
    path.unlink()


def add_source_bound_refusal_sidecar(root):
    safe_write(root / 'qualification/launch-refused-control.json', audit.canonical(dict(
        sourceCommit=audit.Q, policySha256=audit.sha(audit.read(root, 'qualification/process-policy.json')),
        attemptId='1' * 32, cleanupKnown=True, actualExitCode=0)) + b'\n')


CONTROLS = [
    ('boolean_false_as_completed_row_counter', bool_counter, 'TERMINAL_INTEGER'),
    ('qualification_claim_from_terminal_stop', qualification_claim, 'TERMINAL_NOT_QUALIFIED'),
    ('coherent_294_stream_accepted_claim', count_last_as_stream_accepted, 'PARTIAL_INTEGER'),
    ('prepared_empty_admission_relabelled_as_run', pretend_empty_admission_ran, 'ADMISSION_EMPTY_PREPARED_ONLY'),
    ('20_unknown_instead_of_unattempted', unknown_instead_of_unattempted, 'KNOWN20_DISPOSITION'),
    ('last_required_raw_observation_removed', lose_last_required_raw, 'CONTIGUOUS_RAW294'),
    ('sampled_api_actual_body_coherently_nonempty', coherently_nonempty_sampled_api, 'raw replay errors'),
    ('archived_audit_falsely_certifies_qualification', falsely_certify_archived_report, 'ARCHIVED_INDEPENDENT_REPORT_CHANGED'),
    ('frozen_guard_comment_change_manifest_rebound', mutate_frozen_guard_and_rebind, 'SOURCE_GIT_BYTES'),
    ('old_fact_changed_same12352_population', mutate_one_old_fact_keep_population, 'FACTS_BASELINE12352'),
    ('empty_prepared_admission_artifact_omitted', omit_prepared_empty_admission, 'LOGICAL_REPRESENTATION_NOT_UNIQUE'),
    ('extra_cleanup_success_refusal_sidecar', add_source_bound_refusal_sidecar, 'UNEXPECTED_FALLBACK_OR_WORKLOAD_FILE'),
]


def run(root, repo, output):
    audit.need(not output.exists(), 'NEVER_OVERWRITE_CONTROL_RUN')
    output.mkdir(parents=True)
    original = fingerprint(root)
    cache = {}
    result = dict(schema='aijade.ch7.lifecycle-terminal-negative-controls.v1',
        status='RUNNING', originalManifestSha256=audit.sha((root / 'manifest.json').read_bytes()),
        newObservation=False, qualification=False, live19CorruptionControls='NOT_RUN', rows=[])
    for index, (name, mutate, expected) in enumerate(CONTROLS, 1):
        copy_root = output / ('control-' + str(index).zfill(2))
        shutil.copytree(root, copy_root, copy_function=copy_file)
        before = fingerprint(copy_root)
        baseline = audit.audit(copy_root, repo, cache)
        safe_write(output / ('baseline-' + str(index).zfill(2) + '.json'), json.dumps(baseline, indent=2).encode() + b'\n')
        audit.need(baseline['terminalRecordIntegrityAccepted'] is True and baseline['fullQualified'] is False,
                   'CONTROL_BASELINE_MUST_ACCEPT_TERMINAL_RECORD:' + name)
        mutate(copy_root)
        changed_before_rebind = fingerprint(copy_root)
        audit.need(before != changed_before_rebind, 'NO_OP_CONTROL_REFUSED:' + name)
        changed = sorted(k for k in set(before) | set(changed_before_rebind)
                         if before.get(k) != changed_before_rebind.get(k))
        rebind_manifest(copy_root)
        outcome = audit.audit(copy_root, repo, cache)
        safe_write(output / ('negative-' + str(index).zfill(2) + '.json'), json.dumps(outcome, indent=2).encode() + b'\n')
        passed = outcome['terminalRecordIntegrityAccepted'] is False and outcome['fullQualified'] is False and expected in outcome.get('reason', '')
        row = dict(index=index, name=name, baselineAccepted=True, mutationWasEffective=True,
            manifestCoherentlyRebound=True, changedPaths=changed, expectedReason=expected,
            actualReason=outcome.get('reason'), rejected=not outcome['terminalRecordIntegrityAccepted'], passed=passed,
            baselineReplayCache=baseline.get('terminalReplay', {}).get('cache'))
        result['rows'].append(row)
        audit.need(fingerprint(root) == original, 'ORIGINAL_PACKET_CHANGED_BY_CONTROL')
        safe_write(output / 'progress.json', json.dumps(result, indent=2).encode() + b'\n')
        print(json.dumps(row), flush=True)
        audit.need(passed, 'COHERENT_NEGATIVE_NOT_REJECTED_AS_EXPECTED:' + name)
    result.update(status='ALL_COHERENT_TERMINAL_NEGATIVES_REJECTED', controls=len(CONTROLS),
        baselineAccepted=len(CONTROLS), rejected=len(CONTROLS), originalPacketUnchanged=True,
        inProcessSampleCacheEntries=len(cache))
    safe_write(output / 'report.json', json.dumps(result, indent=2).encode() + b'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.repo.resolve(), args.output.resolve())
