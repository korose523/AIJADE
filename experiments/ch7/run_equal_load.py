#!/usr/bin/env python3
"""One source-bound engineering load; never a scientific qualification runner."""
from pathlib import Path
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

import psutil

BASE = Path('/Volumes/Untitled/AIJADE')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, item):
    with path.open('x') as stream:
        stream.write(json.dumps(item, indent=2, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--passport', type=Path, required=True)
    args = parser.parse_args()
    passport_raw = args.passport.read_bytes()
    passport = json.loads(passport_raw)
    need(passport['schema'] == 'aijade.ch7.equal-load-passport.v1', 'passport schema')
    repo = Path(passport['repo']).resolve()
    root = Path(passport['output']).resolve()
    need(repo.is_relative_to(BASE) and root.is_relative_to(BASE), 'workspace boundary')
    need(not root.exists(), 'never overwrite an engineering attempt')
    need(sha(Path(__file__).read_bytes()) == passport['runnerSha256'], 'runner identity')
    source = passport['sourceCommit']
    for relative, expected in passport['sourceFiles'].items():
        raw = (repo / relative).read_bytes()
        need(sha(raw) == expected, 'source file SHA: ' + relative)
    need(psutil.__version__ == '7.2.2' and os.environ.get('DOTNET_PROCESSOR_COUNT') == '2', 'runtime environment')
    sys.path.insert(0, str(repo / 'experiments/ch7'))
    import mac_process_guard_v3 as guard
    import process_lifecycle as life
    from finite_runtime import validate_mac_sample
    from phase_continuity import run_preflight, PreflightRefused
    policy_raw = (repo / passport['policyPath']).read_bytes()
    need(sha(policy_raw) == passport['policySha256'], 'policy identity')
    policy = json.loads(policy_raw)
    guard.validate_policy(policy)
    need(sha(Path(policy['nativeHelper']['path']).read_bytes()) == policy['nativeHelper']['sha256'], 'native binary identity')
    ident = dict(processPolicyPath=passport['policyPath'], processPolicySha256=sha(policy_raw),
                 observerModuleSha256=sha(Path(guard.__file__).read_bytes()), observerSources=passport['observerSources'])
    root.mkdir(parents=True)
    for name in ('settling', 'admission', 'tail'):
        (root / name).mkdir()
    (root / 'process-policy.json').write_bytes(policy_raw)
    (root / 'engineering-passport.json').write_bytes(passport_raw)
    controller = dict(pid=os.getpid(), createTime=psutil.Process().create_time(), parentPid=os.getppid())
    registry = life.Registry(root / 'lifecycle-journal.jsonl', [(controller['pid'], controller['createTime'])],
        stage='equal-load-engineering-only', source_commit=source, policy_sha256=sha(policy_raw),
        capture_lock_path=guard.coordination_lock_path(policy)).activate()
    inner_cursor = life.ViewCursor()
    outer_cursor = life.ViewCursor()
    errors, services, commands, tail_rows = [], [], [], []
    preflight = None
    origin = None
    active = None
    final = None
    joined = False
    tail_entered = None
    tail_joined = None
    tail_thread = None
    tail_stop = threading.Event()
    try:
        need(len(passport['preflightCommands']) == 30, 'fixed preflight finite population')
        for item in passport['preflightCommands']:
            command = ['git', *[v.replace('{SOURCE}', source) for v in item['arguments']]]
            began = time.monotonic()
            result = registry.run(command, cwd=repo, capture_output=True, timeout=10, check=True)
            completed = time.monotonic()
            need(sha(result.stdout) == item['stdoutSha256'], 'source-bound Git result differs')
            commands.append(dict(command=command, stdoutSha256=sha(result.stdout), startedMonotonic=began,
                                 completedMonotonic=completed, exitCode=result.returncode))
        with ExitStack() as stack:
            streams = {name: stack.enter_context((root / name / 'telemetry.jsonl').open('x'))
                       for name in ('settling', 'admission', 'tail')}
            event_stream = stack.enter_context((root / 'phase-events.jsonl').open('x'))
            tail_events = stack.enter_context((root / 'tail/events.jsonl').open('x'))
            service_stream = stack.enter_context((root / 'service-events.jsonl').open('x'))

            def observed(owned_roots=None):
                nonlocal active
                process = guard.observe(policy, owned_roots=owned_roots or [], lifecycle=registry, lifecycle_cursor=inner_cursor)
                process.update(ident)
                active = dict(sampleId=process['sampleId'])
                return dict(utc=datetime.now(timezone.utc).isoformat(), availableBytes=psutil.virtual_memory().available,
                            swapUsedBytes=psutil.swap_memory().used, processObservation=process,
                            rssBytes=process.get('ownedRssBytes'), **ident)

            def validate(item):
                validate_mac_sample(item, ident['processPolicySha256'], ident['observerModuleSha256'],
                                    policy, lifecycle_cursor=outer_cursor)

            raw_rows = {}

            def raw_writer(name):
                def save(item):
                    raw_rows[item['sampleId']] = item
                    streams[name].write(json.dumps(item, allow_nan=False) + '\n')
                    streams[name].flush()
                return save

            def event_writer(item):
                nonlocal origin
                began = time.monotonic()
                if item['event'] == 'phase-enter' and item['phase'] == 'settling':
                    origin = item['monotonicSeconds']
                event_target = tail_events if item.get('phase') == 'tail' else event_stream
                event_target.write(json.dumps(item, allow_nan=False) + '\n')
                event_target.flush()
                event_completed = time.monotonic()
                if item['event'] == 'sample-written':
                    raw = raw_rows.pop(item['sampleId'])
                    index = raw['globalIndex']
                    target = origin + index * 2
                    deadline = origin + (600 if index < 300 else 720 if index < 360 else 724)
                    entry = dict(sampleId=item['sampleId'], globalIndex=index, phase=item['phase'],
                        scheduledMonotonic=target, deadlineMonotonic=deadline, sampleStartedMonotonic=raw['monotonicSeconds'],
                        callbackStartedMonotonic=began, phaseEventWriteCompletedMonotonic=event_completed,
                        startLatenessSeconds=raw['monotonicSeconds'] - target)
                    service_stream.write(json.dumps(entry, allow_nan=False) + '\n')
                    service_stream.flush()
                    entry['diagnosticWriteCompletedMonotonic'] = time.monotonic()
                    services.append(entry)

            def service_completed(raw, completed):
                    entry = services[-1]
                    need(entry['sampleId'] == raw['sampleId'], 'actual callback completion sample identity')
                    entry.update(callbackCompletedMonotonic=completed, serviceCompletedMonotonic=completed,
                                 fullServiceSeconds=completed - raw['monotonicSeconds'])
                    need(0 <= entry['startLatenessSeconds'] <= .5, 'engineering start lateness exceeded .5 seconds')
                    need(entry['fullServiceSeconds'] <= 2, 'engineering full service exceeded two seconds')
                    need(completed <= entry['deadlineMonotonic'], 'engineering complete service exceeded fixed phase deadline')

            try:
                preflight = run_preflight(observed, validate, {name:raw_writer(name) for name in ('settling','admission')},
                                          event_writer=event_writer, settling_seconds=600, service_observer=service_completed)
            except PreflightRefused as error:
                preflight = error.result
                raise
            need(preflight['status'] == 'PREFLIGHT_COMPLETE_ADMITTED', 'engineering preflight incomplete')
            previous = preflight['runtimeHandoffAnchor']['lastSampleMonotonic']
            tail_entered = time.monotonic()

            def tail_work():
                nonlocal previous
                try:
                    for index in (360, 361):
                        if tail_stop.is_set():
                            return
                        target = origin + index * 2
                        remaining = target - time.monotonic()
                        if remaining > 0:
                            time.sleep(remaining)
                        began = time.monotonic()
                        need(target <= began < origin + 724 and 0 < began - previous <= 3, 'tail schedule/continuity')
                        row = observed(registry.roots())
                        completed = time.monotonic()
                        row.update(sampleId=row['processObservation']['sampleId'], globalIndex=index, phase='tail',
                            phaseIndex=index-360, monotonicSeconds=began, observationCompletedMonotonic=completed,
                            observationDurationSeconds=completed-began, scheduledSeconds=index*2,
                            elapsedSeconds=began-origin-720)
                        row['validatorStartedMonotonic'] = time.monotonic()
                        validation_error = None
                        try:
                            validate(row)
                        except BaseException as error:
                            validation_error = error
                        row.update(validatorCompletedMonotonic=time.monotonic(), streamValidationStatus='REFUSED' if validation_error else 'PASS')
                        if validation_error is not None:
                            row['streamValidationError'] = type(validation_error).__name__ + ': ' + str(validation_error)
                        row['writerStartedMonotonic'] = time.monotonic()
                        raw_writer('tail')(row)
                        written = time.monotonic()
                        event_writer(dict(schema='aijade.ch7.equal-load-tail-event.v1', event='sample-written',phase='tail',
                            globalIndex=index,sampleId=row['sampleId'],monotonicSeconds=written,
                            writerStartedMonotonic=row['writerStartedMonotonic'], writerCompletedMonotonic=written,
                            validatorStartedMonotonic=row['validatorStartedMonotonic'],validatorCompletedMonotonic=row['validatorCompletedMonotonic']))
                        service_completed(row, time.monotonic())
                        tail_rows.append(row)
                        if validation_error is not None:
                            raise validation_error
                        previous = began
                except BaseException as error:
                    errors.append('tail ' + type(error).__name__ + ': ' + str(error))

            thread = threading.Thread(target=tail_work, name='aijade-engineering-fixed-handoff')
            tail_thread = thread
            thread.start()
            thread.join(timeout=max(0, origin + 727 - time.monotonic()))
            joined = not thread.is_alive()
            tail_joined = time.monotonic()
            if not joined:
                errors.append('fixed tail deadline refused; entering bounded cleanup only')
                tail_stop.set()
                thread.join(timeout=10)
                joined = not thread.is_alive()
                tail_joined = time.monotonic()
            need(joined, 'fixed tail thread did not join')
            need(not errors and len(tail_rows) == 2 and len(services) == 362, 'engineering tail incomplete')
            need([v['globalIndex'] for v in services] == list(range(362)) and
                 len({v['sampleId'] for v in services}) == 362, 'engineering complete unique sample population')
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        try:
            need(tail_thread is None or not tail_thread.is_alive(), 'UNKNOWN_THREAD_CLEANUP: controller journal is not stable')
            final = registry.final()
            need(final['status'] == 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' and final['scopeClosed'] is True and
                 all(final[k] == [] for k in ('unresolvedFiniteLeases','launchRefusals','launchRefusalArtifacts',
                                              'unleasedDiscoveredIdentities','remainingIdentities')), 'terminal lifecycle not accepted')
        except BaseException as error:
            errors.append('final ' + type(error).__name__ + ': ' + str(error))
        try:
            if tail_thread is None or not tail_thread.is_alive():
                registry.close()
        except BaseException as error:
            errors.append('close ' + type(error).__name__ + ': ' + str(error))
        journal = registry.path.read_bytes()
        if preflight is not None:
            write(root / 'preflight-continuity.json', preflight)
        gates = dict(qualificationStarted=False, backendQualified=False, scientificAdmission=False, formalHardwareQualification=False,
                     independentHumanReview=False, flowBlocks=0, modelRequests=0, rendererRequests=0, freshHeldoutCases=0, seedConstructed=False)
        receipt = dict(schema='aijade.ch7.equal-load-result.v1', status='ENGINEERING_EQUAL_LOAD_PASS' if not errors else 'ENGINEERING_EQUAL_LOAD_REFUSED',
            checkedAt=datetime.now(timezone.utc).isoformat(), sourceCommit=source, passportSha256=sha(passport_raw),
            runnerSha256=sha(Path(__file__).read_bytes()), policySha256=sha(policy_raw), sourceFiles=passport['sourceFiles'],
            controllerProcess=controller, controllerSysExecutable=sys.executable,
            originMonotonic=origin, observations=len(services), tailObservations=len(tail_rows), tailThreadJoined=joined,
            tailPhaseEnteredMonotonic=tail_entered, tailThreadJoinedMonotonic=tail_joined,
            lifecycleJournalStable=tail_thread is None or not tail_thread.is_alive(),
            preflightCommands=commands, services=services, innerCursor=inner_cursor.statistics(), outerCursor=outer_cursor.statistics(),
            registryFinal=final, lifecycleJournalPath=str(registry.path), lifecycleJournalBytes=len(journal), lifecycleJournalSha256=sha(journal),
            errors=errors, automaticRetries=0, **gates)
        write(root / 'receipt.json', receipt)
        print(json.dumps({k:v for k,v in receipt.items() if k not in ('services','sourceFiles','preflightCommands','registryFinal')}), flush=True)
    need(receipt['status'] == 'ENGINEERING_EQUAL_LOAD_PASS', 'full engineering window refused; retain and stop')


if __name__ == '__main__':
    main()
