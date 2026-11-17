#!/usr/bin/env python3
"""One fixed launch and in-process progress reporting; no model calls or sampling decisions.

Use this long-lived parent rather than spawning progress readers during admission.
The committed sequence owns resource admission, measurements and exact cleanup.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from contextlib import ExitStack

import psutil

BASE = Path('/Volumes/Untitled/AIJADE').resolve()


def utc():
    return datetime.now(timezone.utc).isoformat()


def owned(value):
    path = Path(value).resolve()
    if not path.is_relative_to(BASE):
        raise ValueError('project path outside the authorized root')
    return path


def read(path):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None


def progress(output):
    receipt = read(output / 'receipt.json') or {}
    stage = receipt.get('status', 'CONTROLLER_PRECONDITION')
    telemetry = None
    if stage.startswith('FIXED_') or (not receipt.get('startedAt') and
            any((output/phase/'telemetry.jsonl').is_file() for phase in ('settling','admission'))):
        candidates = [output / 'admission/telemetry.jsonl', output / 'settling/telemetry.jsonl']
    else:
        candidates = sorted(output.glob('block-*/telemetry.jsonl'), reverse=True)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 2 * 1024 * 1024))
                lines = stream.read().splitlines()
            for line in reversed(lines):
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                telemetry = {'file': str(path.relative_to(output)), **{key: value.get(key) for key in ('elapsedSeconds', 'availableBytes', 'swapUsedBytes', 'rssBytes')}}
                if not receipt.get('startedAt') and value.get('phase') in ('settling','admission'):
                    stage='PREFLIGHT_'+value['phase'].upper()
                break
        except OSError:
            pass
        if telemetry is not None:
            break
    return dict(at=utc(), stage=stage, completedRows=receipt.get('completedConditionRows', 0),
                completedBlocks=receipt.get('completedBlocks', 0), latestSample=telemetry)


def command(config):
    if config.get('schema') != 'aijade.ch7.fixed-launch.v1':
        raise ValueError('unknown fixed launch schema')
    for key in ('implementationCommit', 'repositoryCommit', 'buildFreezeCommit'):
        if re.fullmatch(r'[0-9a-f]{40}', config.get(key, '')) is None:
            raise ValueError('full immutable commit required')
    purpose = config.get('purpose')
    if purpose not in ('qualification_only', 'confirmed_finite_heldout'):
        raise ValueError('unknown launch purpose')
    repo, output = owned(config['repo']), owned(config['output'])
    if output.exists():
        raise ValueError('never relaunch or overwrite an attempt')
    # Preserve the project venv entry path: resolving its SDK symlink would
    # discard that environment's psutil installation and import context.
    python = Path(config['python']).absolute()
    if not python.is_relative_to(BASE) or '..' in python.parts or not python.is_file():
        raise ValueError('explicit project Python environment required')
    args = [str(python), str(repo / 'experiments/ch7/run_finite_sequence.py')]
    fields = ('repo', 'client', 'model', 'selection', 'inputs', 'output', 'assembly', 'build-manifest', 'godot', 'execution-plan', 'process-policy')
    for key in fields:
        args += ['--' + key, str(owned(config[key.replace('-', '_')]))]
    for key in ('dotnet', 'docker'):
        path = Path(config[key]).resolve()
        if not path.is_file():
            raise ValueError('missing explicit installed executable: ' + key)
        args += ['--' + key, str(path)]
    for key, value in {'db-container': config['db_container'], 'build-freeze-commit': config['buildFreezeCommit'],
                       'build-freeze-path': config['build_freeze_path'], 'implementation-commit': config['implementationCommit']}.items():
        args += ['--' + key, value]
    if config.get('data_publication_manifest') is not None:
        args += ['--data-publication-manifest', config['data_publication_manifest']]
    args += ['--settle-seconds', '600' if purpose == 'qualification_only' else '0']
    return repo, output, args


def process_identity(pid):
    """Read kernel identity twice; no name-based ownership or cached PID proof."""
    if type(pid) is not int or pid <= 1:
        raise ValueError('invalid owned process PID')
    process = psutil.Process(pid)
    created = process.create_time()
    parent, group = process.ppid(), os.getpgid(pid)
    if type(created) not in (int, float) or not math.isfinite(created) or created <= 0:
        raise ValueError('process birth identity unknown')
    if type(parent) is not int or parent <= 0 or type(group) is not int or group <= 0:
        raise ValueError('process parent/group identity unknown')
    if psutil.Process(pid).create_time() != created:
        raise ValueError('process PID reused during identity read')
    return dict(pid=pid, createTime=created, createTimeMicros=round(created * 1000000),
                parentPid=parent, processGroup=group)


def bind_child(process, parent_pid):
    first, second = process_identity(process.pid), process_identity(process.pid)
    if first != second or first['parentPid'] != parent_pid or first['processGroup'] != process.pid:
        raise ValueError('launched child birth/parent/new-session group differs')
    return first


def poll_status(process, evidence):
    before = process.returncode
    started = time.monotonic()
    code = process.poll()
    evidence['pollCalls'] += 1
    if code is not None and type(code) is not int:
        raise ValueError('controller poll returned noninteger terminal status')
    if code is not None:
        evidence['terminalPolls'].append(dict(source='Popen.poll', startedMonotonic=started,
            completedMonotonic=time.monotonic(), returncodeKnownBeforeCall=before is not None,
            exitCode=code, provenance='CACHED_TERMINAL_STATUS' if before is not None
                else 'TERMINAL_STATUS_FIRST_OBTAINED_BY_POPEN_POLL',
            independentKernelWaitClaimed=False))
        if evidence['terminalStatusSource'] is None:
            evidence['terminalStatusSource'] = 'Popen.poll' if before is None else 'Popen.cached_returncode'
    return code


def wait_status(process, evidence, timeout, purpose):
    before = process.returncode
    item = dict(source='Popen.wait', purpose=purpose, timeoutSeconds=timeout,
                startedMonotonic=time.monotonic(), returncodeKnownBeforeCall=before is not None,
                reapedBeforeThisCall=before is not None, independentKernelWaitClaimed=False)
    try:
        code = process.wait(timeout=timeout)
        if type(code) is not int:
            raise ValueError('controller wait returned noninteger terminal status')
    except subprocess.TimeoutExpired:
        item.update(completedMonotonic=time.monotonic(), timedOut=True, exitCode=None,
                    provenance='NO_TERMINAL_RETURN_TIMEOUT')
        evidence['waitCalls'].append(item)
        raise
    except BaseException as error:
        item.update(completedMonotonic=time.monotonic(), timedOut=False, exitCode=None,
                    errorClass=type(error).__name__, provenance='WAIT_RETURN_UNKNOWN')
        evidence['waitCalls'].append(item)
        raise
    item.update(completedMonotonic=time.monotonic(), timedOut=False, exitCode=code,
                provenance='CACHED_RETURN_AFTER_PRIOR_TERMINAL_STATUS' if before is not None
                    else 'ACTUAL_POPEN_WAIT_RETURN_WITHOUT_PRIOR_TERMINAL_STATUS')
    evidence['waitCalls'].append(item)
    if evidence['terminalStatusSource'] is None:
        evidence['terminalStatusSource'] = 'Popen.wait' if before is None else 'Popen.cached_returncode'
    return code


def cleanup_child(process, identity, evidence):
    """Bounded PID-only cleanup. Identity uncertainty never licenses a signal."""
    result = dict(status='UNKNOWN', signals=[], unresolved=True, wholeProcessGroupCleanupClaimed=False,
                  target='EXACT_OWNED_CONTROLLER_PID_ONLY')
    if poll_status(process, evidence) is not None:
        wait_status(process, evidence, 0, 'cleanup already-terminal cached return')
        result.update(status='CONTROLLER_ALREADY_TERMINAL', unresolved=False)
        return result
    if identity is None:
        result.update(status='IDENTITY_UNBOUND_NOT_SIGNALED', reason='no bound child birth/parent/group')
        return result
    for sig, timeout in ((signal.SIGTERM, 60), (signal.SIGKILL, 5)):
        if poll_status(process, evidence) is not None:
            wait_status(process, evidence, 0, 'cleanup terminal cached return')
            result.update(status='CONTROLLER_TERMINAL', unresolved=False)
            return result
        try:
            observed = bind_child(process, os.getpid())
            if observed != identity:
                raise ValueError('owned child identity changed before signal')
        except BaseException as error:
            result.update(status='IDENTITY_UNKNOWN_NOT_SIGNALED',
                          reason=type(error).__name__ + ': ' + str(error))
            return result
        action = dict(signal=int(sig), signalName=sig.name, targetPid=identity['pid'],
                      identityBeforeSignal=observed, startedMonotonic=time.monotonic(),
                      wholeProcessGroupCleanupClaimed=False)
        result['signals'].append(action)
        try:
            os.kill(identity['pid'], sig)
            action['signalCallReturned'] = True
        except OSError as error:
            action.update(signalCallReturned=False, errorClass=type(error).__name__)
        action['completedMonotonic'] = time.monotonic()
        try:
            wait_status(process, evidence, timeout, 'after ' + sig.name)
        except subprocess.TimeoutExpired:
            continue
        except BaseException as error:
            result.update(status='WAIT_UNKNOWN_AFTER_SIGNAL', reason=type(error).__name__ + ': ' + str(error))
            return result
        result.update(status='CONTROLLER_TERMINAL_AFTER_SIGNAL', unresolved=False)
        return result
    result['status'] = 'CONTROLLER_UNRESOLVED_AFTER_TERM_AND_KILL'
    return result


def write_owned(stream, value):
    """Update only the descriptor this invocation exclusively created."""
    stream.seek(0)
    json.dump(value, stream, indent=2)
    stream.write('\n')
    stream.truncate()
    stream.flush()


def execute(config_path):
    config_path = owned(config_path)
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    repo, output, args = command(config)
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip() != config['repositoryCommit']:
        raise ValueError('repository I is not HEAD')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo):
        raise ValueError('dirty execution checkout')
    if subprocess.check_output(['git', 'show', config['implementationCommit'] + ':experiments/ch7/launch_frozen_sequence.py'], cwd=repo) != Path(__file__).read_bytes():
        raise ValueError('launch source differs from Q')
    record_path = owned(config['launch_record'])
    terminal_path = record_path.with_suffix('.terminal.json')
    log_path = record_path.with_suffix('.controller.log')
    if any(path.exists() or path.is_symlink() for path in (record_path, terminal_path, log_path)):
        raise ValueError('prior attempt artifacts exist')
    if config_path.read_bytes() != config_bytes:
        raise ValueError('fixed configuration changed before launch')
    watchdog = 5700 if config['purpose'] == 'qualification_only' else 5100
    record = dict(schema='aijade.ch7.fixed-sequence-parent-launch.v2',
                  status='SINGLE_FIXED_SEQUENCE_INVOCATION', startedAt=utc(),
                  configSha256=hashlib.sha256(config_bytes).hexdigest(),
                  implementationCommit=config['implementationCommit'], repositoryCommit=config['repositoryCommit'],
                  buildFreezeCommit=config['buildFreezeCommit'], purpose=config['purpose'],
                  command=args, output=str(output), automaticRetries=0, modelRequests=0,
                  parentProcess=process_identity(os.getpid()), controllerProcess=None,
                  childIdentityStatus='NOT_LAUNCHED', startNewSession=True,
                  watchdogSeconds=watchdog, termWaitSeconds=60, killWaitSeconds=5,
                  wholeProcessGroupCleanupClaimed=False)
    env = dict(os.environ, AIJADE_GIT_COMMIT=config['implementationCommit'],
               AIJADE_REPOSITORY_COMMIT=config['repositoryCommit'], DOTNET_PROCESSOR_COUNT='2',
               DOCKER_HOST=config['docker_host'], AIJADE_TEST_DATABASE_URL=config['database_url'],
               AIJADE_REAL_GODOT=config['real_godot'], AIJADE_GODOT_SANDBOX_PROFILE=str(owned(config['sandbox_profile'])),
               AIJADE_GODOT_LOG_DIR=str(owned(config['godot_log_dir'])), PYTHONDONTWRITEBYTECODE='1',
               DOTNET_CLI_USE_MSBUILD_SERVER='0', MSBUILDDISABLENODEREUSE='1', UseSharedCompilation='false')
    env.pop('REDIS_URL', None)
    process = None
    child_identity = None
    reason = None
    cleanup = None
    intervention = False
    evidence = dict(pollCalls=0, terminalPolls=[], waitCalls=[], terminalStatusSource=None)
    start = time.monotonic()
    def interrupted(signum, frame):
        raise RuntimeError('parent signal ' + str(signum))
    previous = {}
    with ExitStack() as stack:
        launch_stream = stack.enter_context(record_path.open('x'))
        write_owned(launch_stream, record)
        log = stack.enter_context(log_path.open('x'))
        terminal_stream = stack.enter_context(terminal_path.open('x'))
        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, interrupted)
            if config_path.read_bytes() != config_bytes:
                raise ValueError('fixed configuration changed before Popen')
            process = subprocess.Popen(args, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            record['controllerPidFromPopen'] = process.pid
            record['childIdentityStatus'] = 'BINDING_STARTED'
            write_owned(launch_stream, record)
            child_identity = bind_child(process, record['parentProcess']['pid'])
            record.update(controllerProcess=child_identity, childIdentityStatus='KERNEL_BIRTH_PARENT_GROUP_BOUND',
                          identityBoundAt=utc())
            write_owned(launch_stream, record)
            print(json.dumps(dict(event='LAUNCHED', pid=process.pid, output=str(output))), flush=True)
            last = -30.0
            while True:
                code = poll_status(process, evidence)
                if code is not None:
                    wait_status(process, evidence, 0, 'normal terminal cached return after poll')
                    break
                now = time.monotonic() - start
                if now >= watchdog:
                    raise TimeoutError('fixed parent watchdog exceeded')
                if now - last >= 30:
                    print(json.dumps(progress(output)), flush=True)
                    last = now
                time.sleep(1)
        except BaseException as error:
            reason = type(error).__name__ + ': ' + str(error)
            intervention = True
            if process is not None:
                try:
                    cleanup = cleanup_child(process, child_identity, evidence)
                except BaseException as cleanup_error:
                    cleanup = dict(status='CLEANUP_EVIDENCE_UNKNOWN', unresolved=True, signals=[],
                        reason=type(cleanup_error).__name__ + ': ' + str(cleanup_error),
                        wholeProcessGroupCleanupClaimed=False)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            receipt = read(output / 'receipt.json')
            if not isinstance(receipt, dict):
                receipt = None
            code = process.returncode if process is not None else None
            complete = bool(child_identity is not None and not intervention and reason is None
                and type(code) is int and code == 0
                and receipt and receipt.get('status') == 'COMPLETE_FINITE_SEQUENCE_OBSERVATIONS')
            terminal = dict(schema='aijade.ch7.fixed-sequence-parent-terminal.v2',
                status='CONTROLLER_COMPLETE_PENDING_INDEPENDENT_AUDIT' if complete else 'PARENT_ADVERSE_OR_UNRESOLVED',
                finishedAt=utc(), configSha256=record['configSha256'],
                implementationCommit=config['implementationCommit'], repositoryCommit=config['repositoryCommit'],
                buildFreezeCommit=config['buildFreezeCommit'], purpose=config['purpose'],
                launchRecordPath=str(record_path), launchRecordSha256=hashlib.sha256(record_path.read_bytes()).hexdigest(),
                logPath=str(log_path), controllerExitCode=code, controllerProcess=child_identity,
                controllerPidFromPopen=process.pid if process is not None else None,
                childIdentityStatus=record['childIdentityStatus'], parentProcess=record['parentProcess'],
                elapsedSeconds=time.monotonic() - start, reason=reason,
                receiptStatus=receipt.get('status') if receipt else 'UNKNOWN', output=str(output),
                intervention=intervention, cleanup=cleanup,
                childIdentityUnresolved=bool(process is not None and child_identity is None),
                unresolved=bool(process is not None and (child_identity is None or type(code) is not int)),
                terminalStatusProvenance=evidence['terminalStatusSource'], processEvidence=evidence,
                watchdogSeconds=watchdog, automaticRetries=0, scientificAcceptance=False,
                backendQualified=False, formalHardwareQualification=False,
                independentHumanReview=False, authorApproval=False, heldoutComparisonComplete=False,
                controllerLogMayStillGrow=bool(process is not None and type(code) is not int),
                wholeProcessGroupCleanupClaimed=False)
            log.flush()
            terminal['logSha256'] = hashlib.sha256(log_path.read_bytes()).hexdigest()
            write_owned(terminal_stream, terminal)
            print(json.dumps(terminal), flush=True)
    return 0 if complete else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    options = parser.parse_args()
    try:
        exit_code = execute(options.config)
    except Exception as error:
        # A recording exception can occur after Popen. Do not mislabel every
        # escaped error as proof that no child was started.
        refusal = dict(status='PARENT_LAUNCH_OR_RECORDING_REFUSED_CHILD_STATE_UNKNOWN',
                       at=utc(), reason=type(error).__name__ + ': ' + str(error),
                       childStarted=None, unresolved=True, scientificAcceptance=False)
        try:
            source = owned(options.config)
            name = source.with_suffix('.precondition-error-' + str(time.time_ns()) + '.json')
            with name.open('x') as stream:
                json.dump(refusal, stream, indent=2)
                stream.write('\n')
            refusal['record'] = str(name)
        except (OSError, ValueError):
            refusal['record'] = None
        print(json.dumps(refusal), flush=True)
        exit_code = 2
    raise SystemExit(exit_code)
