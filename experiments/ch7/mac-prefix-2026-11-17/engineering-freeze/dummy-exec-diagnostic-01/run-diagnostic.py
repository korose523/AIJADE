#!/usr/bin/env python3
"""Exactly one C compilation and three frozen dummy native-plumbing trials.

Never invokes a real census, observer, listener, API, model or renderer.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
import time

import psutil

BASE = Path('/Volumes/Untitled/AIJADE')
EVIDENCE = BASE / '.research/runs/ch7-prefix-20261117/dummy-exec-diagnostic-01'
ARTIFACTS = BASE / '.runtime/posix/research/ch7-prefix-20261117/dummy-exec-diagnostic-01'
REPO = BASE / '.runtime/posix/research/ch7-prefix-20261117/worktree'
PYTHON = BASE / '.runtime/python-envs/p2-tokenizer/bin/python'
SOURCE_COMMIT = '19f40f923d61d0200bdb26aa79f5e0d962ee7863'
C_SOURCE = ('#define _POSIX_C_SOURCE 200809L\n#include <stdio.h>\n#include <time.h>\n'
            'int main(int argc,char **argv){(void)argv;if(argc!=1)return 8;'
            'fputs("synthetic-native-fixture\\n",stdout);return 0;}\n').encode()
EXPECTED_STDOUT = b'synthetic-native-fixture\n'
MODULES = ('experiments/ch7/mac_process_guard_v3.py', 'experiments/ch7/process_lifecycle.py',
           'experiments/ch7/lifecycle_exec.py', 'tests/shell/test_mac_lifecycle_native.py')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    return sha(Path(path).read_bytes())


def new(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write(path, value):
    new(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def serial(value):
    if isinstance(value, bytes):
        return dict(encoding='base64', data=base64.b64encode(value).decode(), sizeBytes=len(value), sha256=sha(value))
    if isinstance(value, dict):
        return {key: serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(item) for item in value]
    return value


def attributes(path):
    value = dict(path=str(path), readOnly=True, attributes=[])
    try:
        for name in sorted(os.listxattr(path)):
            raw = os.getxattr(path, name)
            value['attributes'].append(dict(name=name, **serial(raw)))
        value['status'] = 'READ_COMPLETE'
    except OSError as error:
        value.update(status='READ_UNKNOWN', errorClass=type(error).__name__, error=str(error))
    item = path.stat()
    value['stat'] = dict(sizeBytes=item.st_size, mode=stat.S_IMODE(item.st_mode),
                         device=item.st_dev, inode=item.st_ino, modifiedNs=item.st_mtime_ns)
    return value


def command_record(command, timeout, prefix):
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        stdout, stderr, code, timed_out = result.stdout, result.stderr, result.returncode, False
    except subprocess.TimeoutExpired as error:
        stdout, stderr, code, timed_out = error.stdout or b'', error.stderr or b'', None, True
    completed = time.monotonic()
    new(EVIDENCE / (prefix + '.stdout.raw'), stdout)
    new(EVIDENCE / (prefix + '.stderr.raw'), stderr)
    value = dict(command=command, timeoutSeconds=timeout, startedMonotonic=started,
        completedMonotonic=completed, durationSeconds=completed-started,
        exitCode=code, timedOut=timed_out, stdout=serial(stdout), stderr=serial(stderr))
    write(EVIDENCE / (prefix + '.json'), value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    need(args.plan == EVIDENCE / 'plan.json', 'fixed prospective plan required')
    plan_raw = args.plan.read_bytes()
    need(sha(plan_raw) == args.plan_sha256, 'plan differs from external frozen bytes')
    plan = json.loads(plan_raw)
    need(plan['scriptSha256'] == file_sha(Path(__file__)), 'diagnostic script changed')
    need(plan['helperSourceSha256'] == sha(C_SOURCE), 'dummy source changed')
    need(Path(sys.executable).absolute() == PYTHON and psutil.__version__ == '7.2.2', 'fixed SDK environment')
    need(plan['trials'] == [1, 2, 3] and plan['betweenTrialsSeconds'] == 1
         and plan['nativeDeadlineSeconds'] == 0.5, 'frozen trial protocol differs')
    need(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip() == SOURCE_COMMIT, 'source HEAD differs')
    need(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO), 'source checkout is dirty')
    source_proof = {}
    for relative in MODULES:
        raw = (REPO / relative).read_bytes()
        need(sha(raw) == plan['sourceFiles'][relative], 'source hash differs: ' + relative)
        need(raw == subprocess.check_output(['git', 'show', SOURCE_COMMIT + ':' + relative], cwd=REPO), 'source Git blob differs')
        source_proof[relative] = sha(raw)
    need(file_sha(Path(plan['compiler'])) == plan['compilerSha256'], 'compiler entry changed')
    write(EVIDENCE / 'started.json', dict(status='ONE_FROZEN_THREE_TRIAL_DIAGNOSTIC_STARTED',
        at=utc(), planSha256=args.plan_sha256, scriptSha256=file_sha(Path(__file__)),
        sourceCommit=SOURCE_COMMIT, automaticRetries=0))
    ARTIFACTS.mkdir(parents=True, exist_ok=False)
    source, helper = ARTIFACTS / 'fake-native-helper.c', ARTIFACTS / 'fake-native-helper'
    new(source, C_SOURCE)
    compilation = command_record([plan['compiler'], '-std=c11', '-O1', str(source), '-o', str(helper)],
                                 30, 'compile')
    if compilation['exitCode'] != 0 or compilation['timedOut'] or not helper.is_file():
        write(EVIDENCE / 'summary.json', dict(status='DUMMY_DIAGNOSTIC_COMPILE_REFUSED_NO_TRIALS',
            planSha256=args.plan_sha256, sourceCommit=SOURCE_COMMIT, compilationAttempts=1,
            trialsAttempted=0, nativeDeadlineSeconds=0.5, engineeringFullLoadStarted=False,
            qualificationStarted=False, automaticRetries=0))
        return 2
    before_attributes = attributes(helper)
    write(EVIDENCE / 'helper-attributes-before.json', before_attributes)
    codesign = command_record(['/usr/bin/codesign', '--display', '--verbose=4', str(helper)], 10, 'codesign-readonly')
    # No helper execution occurs before this immutable binary manifest exists.
    manifest = dict(schema='aijade.ch7.dummy-native-binary-freeze.v1',
        status='ONE_COMPILED_DUMMY_FROZEN_BEFORE_FIRST_EXECUTION', at=utc(),
        sourceCommit=SOURCE_COMMIT, planSha256=args.plan_sha256, scriptSha256=file_sha(Path(__file__)),
        helperSourcePath=str(source), helperSourceSha256=file_sha(source),
        helperPath=str(helper), helperSha256=file_sha(helper), helperBytes=helper.stat().st_size,
        compileReceiptSha256=file_sha(EVIDENCE/'compile.json'), compilationAttempts=1,
        attributesBeforeSha256=file_sha(EVIDENCE/'helper-attributes-before.json'),
        codesignReadOnlyReceiptSha256=file_sha(EVIDENCE/'codesign-readonly.json'),
        sourceFiles=source_proof, helperExecutionsBeforeFreeze=0,
        changedSecurityAttributes=False, signedOrResignedByDiagnostic=False, prewarmed=False)
    write(EVIDENCE / 'binary-manifest.json', manifest)
    manifest_sha = file_sha(EVIDENCE / 'binary-manifest.json')
    sys.path.insert(0, str(REPO / 'experiments/ch7'))
    import process_lifecycle as life
    import mac_process_guard_v3 as guard
    need(guard.NATIVE_TIMEOUT == 0.5, 'production native deadline must remain0.5')
    trials, intervals = [], []
    for index in (1, 2, 3):
        if index > 1:
            began = time.monotonic()
            time.sleep(1)
            intervals.append(dict(beforeTrial=index, requestedSeconds=1,
                startedMonotonic=began, completedMonotonic=time.monotonic()))
        need(file_sha(helper) == manifest['helperSha256'] and file_sha(source) == manifest['helperSourceSha256'],
             'frozen dummy bytes changed; no substituted execution')
        trial_root = ARTIFACTS / ('trial-' + str(index))
        trial_root.mkdir()
        registry = None
        result = None
        coordination = None
        errors = []
        final = None
        state = None
        launch_calls = []
        call_start = call_end = None
        trial_start = time.monotonic()
        try:
            own = life.identity()
            registry = life.Registry(trial_root/'lifecycle-journal.jsonl',
                [(own['pid'], own['createTimeMicros']/1000000)],
                stage='dummy-exec-diagnostic-trial-'+str(index), source_commit=SOURCE_COMMIT,
                policy_sha256=args.plan_sha256, capture_lock_path=trial_root/'capture.lock')
            original_launch = registry.launch

            def timed_launch(*arguments, **keywords):
                # Exactly one unchanged delegation; only memory/clock bookkeeping.
                record = dict(startedMonotonic=time.monotonic())
                try:
                    handle = original_launch(*arguments, **keywords)
                    record['returnedHandle'] = True
                    return handle
                except BaseException as error:
                    record.update(returnedHandle=False, errorClass=type(error).__name__)
                    raise
                finally:
                    record['completedMonotonic'] = time.monotonic()
                    record['durationSeconds'] = record['completedMonotonic'] - record['startedMonotonic']
                    launch_calls.append(record)

            registry.launch = timed_launch
            with life.capture_lock(registry.lock_path) as coordination:
                call_start = time.monotonic()
                result = guard._run_native(helper, registry)
                call_end = time.monotonic()
        except BaseException as error:
            call_end = time.monotonic()
            errors.append(dict(phase='dummy-call', errorClass=type(error).__name__, error=str(error)))
        finally:
            if registry is not None:
                # The primitive normally reaps its exact handle. Do not replace
                # an unknown wait with a guessed successful exit.
                try:
                    final = registry.final()
                except BaseException as error:
                    errors.append(dict(phase='final', errorClass=type(error).__name__, error=str(error)))
                try:
                    registry.close()
                except BaseException as error:
                    errors.append(dict(phase='close', errorClass=type(error).__name__, error=str(error)))
                raw = registry.path.read_bytes()
                new(EVIDENCE / ('trial-'+str(index)+'.journal.jsonl'), raw)
                try:
                    state = life.replay_journal(raw)
                except BaseException as error:
                    errors.append(dict(phase='cold-journal-replay', errorClass=type(error).__name__, error=str(error)))
            else:
                raw = b''
        accepted = (not errors and result is not None and result.get('exitCode') == 0
            and result.get('cleanupKnown') is True and result.get('timedOut') is False
            and result.get('oversized') is False and result.get('stdout') == EXPECTED_STDOUT
            and result.get('stderrBytes') == 0 and result.get('durationSeconds', float('inf')) <= 0.5
            and final is not None and final.get('status') == 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT'
            and state is not None and len(state['leases']) == 2 and len(state['launchRefusals']) == 0)
        entry = dict(schema='aijade.ch7.dummy-native-exec-trial.v1', index=index,
            status='DUMMY_NATIVE_PLUMBING_PASS' if accepted else 'DUMMY_NATIVE_PLUMBING_REFUSED',
            trialStartedMonotonic=trial_start, callStartedMonotonic=call_start, callCompletedMonotonic=call_end,
            trialCompletedMonotonic=time.monotonic(), nativeDeadlineSeconds=0.5,
            manifestSha256=manifest_sha, helperSha256=file_sha(helper),
            captureLock=coordination, nativeResult=serial(result), registryFinal=serial(final),
            launchCallTiming=launch_calls,
            journalPath=str(trial_root/'lifecycle-journal.jsonl'), journalSha256=sha(raw),
            journalBytes=len(raw), journalEvents=len(state['events']) if state else None,
            exactJournalEvents=state['events'] if state else None, errors=errors,
            stderrPayloadAvailable=False,
            stderrLimit='Unchanged _run_native preserves stderr byte count, not stderr payload; compiler/codesign stderr is retained in full.',
            actualSysctlCensus=False, guardObserveInvoked=False, qualification=False)
        write(EVIDENCE / ('trial-'+str(index)+'.json'), entry)
        trials.append(entry)
    write(EVIDENCE / 'helper-attributes-after.json', attributes(helper))
    after = {relative:file_sha(REPO/relative) for relative in MODULES}
    same_source = after == source_proof
    summary = dict(schema='aijade.ch7.dummy-native-exec-diagnostic.v1',
        status='THREE_DUMMY_TRIALS_COMPLETE_WITH_REFUSALS' if any(t['status'] != 'DUMMY_NATIVE_PLUMBING_PASS' for t in trials)
            else 'THREE_DUMMY_PLUMBING_TRIALS_PASS_NOT_QUALIFICATION',
        checkedAt=utc(), sourceCommit=SOURCE_COMMIT, planSha256=args.plan_sha256,
        scriptSha256=file_sha(Path(__file__)), binaryManifestSha256=manifest_sha,
        helperSha256=file_sha(helper), helperSourceSha256=file_sha(source),
        sourceFilesBefore=source_proof, sourceFilesAfter=after, productionSourceUnchanged=same_source,
        compilationAttempts=1, plannedTrials=3, trialsAttempted=len(trials),
        intervalSleeps=intervals, nativeDeadlineSeconds=0.5,
        outcomes=[dict(index=t['index'], status=t['status'], nativeResult=t['nativeResult'],
            journalSha256=t['journalSha256'], errors=t['errors']) for t in trials],
        automaticRetries=0, prewarmExecutions=0, securityAttributeMutations=0,
        engineeringFullLoadStarted=False, qualificationStarted=False, actualCensusCalls=0,
        guardObserveCalls=0, lsofCalls=0, apiCalls=0, modelRequests=0, rendererCalls=0,
        freshCases=0, causalFirstExecutionEffectEstablished=False,
        interpretation='Fixed-order repeated measurements of one newly compiled dummy. Order-associated timing cannot establish a Mach-O first-execution cause; prior failures remain adverse.')
    if not same_source or file_sha(helper) != manifest['helperSha256']:
        summary['status'] = 'DUMMY_DIAGNOSTIC_IDENTITY_CHANGED_ADVERSE'
    write(EVIDENCE / 'summary.json', summary)
    print(json.dumps(dict(status=summary['status'], summary=str(EVIDENCE/'summary.json'),
        outcomes=[dict(index=t['index'], status=t['status'], durationSeconds=t['nativeResult'].get('durationSeconds') if t['nativeResult'] else None,
            exitCode=t['nativeResult'].get('exitCode') if t['nativeResult'] else None,
            timedOut=t['nativeResult'].get('timedOut') if t['nativeResult'] else None) for t in trials]), indent=2))
    return 0 if summary['status'] == 'THREE_DUMMY_PLUMBING_TRIALS_PASS_NOT_QUALIFICATION' else 2


if __name__ == '__main__':
    raise SystemExit(main())
