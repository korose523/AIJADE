#!/usr/bin/env python3
"""One fixed launch and in-process progress reporting; no model calls or sampling decisions.

Use this long-lived parent rather than spawning progress readers during admission.
The committed sequence owns resource admission, measurements and exact cleanup.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

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
    if stage.startswith('FIXED_'):
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


def execute(config_path):
    config_path = owned(config_path)
    config = json.loads(config_path.read_bytes())
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
    if terminal_path.exists() or log_path.exists():
        raise ValueError('prior attempt artifacts exist')
    record = dict(status='SINGLE_FIXED_SEQUENCE_INVOCATION', startedAt=utc(),
                  configSha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                  implementationCommit=config['implementationCommit'], repositoryCommit=config['repositoryCommit'],
                  buildFreezeCommit=config['buildFreezeCommit'], purpose=config['purpose'],
                  command=args, output=str(output), automaticRetries=0, modelRequests=0)
    with record_path.open('x') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    env = dict(os.environ, AIJADE_GIT_COMMIT=config['implementationCommit'],
               AIJADE_REPOSITORY_COMMIT=config['repositoryCommit'], DOTNET_PROCESSOR_COUNT='2',
               DOCKER_HOST=config['docker_host'], AIJADE_TEST_DATABASE_URL=config['database_url'],
               AIJADE_REAL_GODOT=config['real_godot'], AIJADE_GODOT_SANDBOX_PROFILE=str(owned(config['sandbox_profile'])),
               AIJADE_GODOT_LOG_DIR=str(owned(config['godot_log_dir'])), PYTHONDONTWRITEBYTECODE='1',
               DOTNET_CLI_USE_MSBUILD_SERVER='0', MSBUILDDISABLENODEREUSE='1', UseSharedCompilation='false')
    env.pop('REDIS_URL', None)
    process = None
    reason = None
    start = time.monotonic()
    def interrupted(signum, frame):
        raise RuntimeError('parent signal ' + str(signum))
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        with log_path.open('x') as log:
            process = subprocess.Popen(args, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            print(json.dumps(dict(event='LAUNCHED', pid=process.pid, output=str(output))), flush=True)
            last = -30.0
            while process.poll() is None:
                now = time.monotonic() - start
                if now >= (5700 if config['purpose'] == 'qualification_only' else 5100):
                    raise TimeoutError('fixed parent watchdog exceeded')
                if now - last >= 30:
                    print(json.dumps(progress(output)), flush=True)
                    last = now
                time.sleep(1)
    except BaseException as error:
        reason = type(error).__name__ + ': ' + str(error)
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                reason += '; owned controller cleanup deadline exceeded'
    finally:
        signal.signal(signal.SIGTERM, previous)
        receipt = read(output / 'receipt.json')
        terminal = dict(finishedAt=utc(), controllerExitCode=process.poll() if process is not None else None,
                        elapsedSeconds=time.monotonic() - start, reason=reason, receiptStatus=receipt.get('status') if receipt else 'UNKNOWN',
                        output=str(output), automaticRetries=0, scientificAcceptance=False)
        with terminal_path.open('x') as stream:
            json.dump(terminal, stream, indent=2)
            stream.write('\n')
        print(json.dumps(terminal), flush=True)
    return 0 if terminal['controllerExitCode'] == 0 and terminal['receiptStatus'] == 'COMPLETE_FINITE_SEQUENCE_OBSERVATIONS' else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    options = parser.parse_args()
    try:
        exit_code = execute(options.config)
    except Exception as error:
        refusal = dict(status='PRE_LAUNCH_REFUSED_NO_CHILD_STARTED', at=utc(), reason=type(error).__name__ + ': ' + str(error))
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
