#!/usr/bin/env python3
"""Guarded, opt-in product smoke check against an existing exclusive loopback Ollama service. Requires psutil."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import psutil


def api(base, path, body=None):
    request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def sample(start):
    return {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'elapsedSeconds': time.monotonic() - start,
            'availableBytes': psutil.virtual_memory().available, 'swapUsedBytes': psutil.swap_memory().used}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--base', default='http://127.0.0.1:11510')
    parser.add_argument('--out', type=Path, required=True, help='A new engineering output directory; earlier runs are never overwritten')
    parser.add_argument('--warmup', action='store_true', help='Explicit native preload before product requests; requires a nonzero service keep-alive')
    args = parser.parse_args()
    base = args.base.rstrip('/'); uri = urllib.parse.urlsplit(base)
    if uri.scheme != 'http' or uri.hostname not in ['127.0.0.1', 'localhost', '::1'] or uri.path or uri.username:
        raise ValueError('Use an exclusive local HTTP model service with no path or credentials')
    if args.out.exists():
        raise FileExistsError('Refusing to overwrite an earlier check')
    if not os.environ.get('AIJADE_TEST_DATABASE_URL'):
        raise ValueError('AIJADE_TEST_DATABASE_URL must point to an isolated local test database service')
    identity = next(x for x in api(base, '/api/tags')['models'] if x['name'] == args.model)
    if identity['size'] > 5 * 2**30:
        raise ValueError('This bounded development check supports cached models up to 5 GiB only')
    minimum = (3 if identity['size'] <= 1.5 * 2**30 else 7) * 2**30
    root = Path(__file__).resolve().parents[1]; args.out.mkdir(parents=True)
    before = api(base, '/api/ps'); samples = []; start = time.monotonic()
    print(json.dumps({'phase': 'admission', 'model': args.model, 'minimumAvailableGiB': minimum / 2**30}), flush=True)
    while True:
        samples.append(sample(start))
        if samples[-1]['elapsedSeconds'] >= 60:
            break
        time.sleep(1)
    reasons = []
    if before['models'] or api(base, '/api/ps')['models']:
        reasons.append('A model was loaded at the admission boundary')
    if min(x['availableBytes'] for x in samples) < minimum:
        reasons.append('Available RAM did not meet the model-specific development admission')
    if max(x['swapUsedBytes'] for x in samples) - samples[0]['swapUsedBytes'] > 256 * 2**20:
        reasons.append('Swap increased by more than 256 MiB during admission')
    write(args.out / 'admission.json', {'kind': 'product development admission; not hardware qualification',
        'model': identity, 'minimumAvailableBytes': minimum, 'admitted': not reasons, 'reasons': reasons, 'samples': samples})
    if reasons:
        print(json.dumps({'status': 'NOT_ADMITTED', 'reasons': reasons}), flush=True)
        return 2
    dotnet = os.environ.get('AIJADE_DOTNET_BIN') or (str(Path.home() / '.dotnet/dotnet') if (Path.home() / '.dotnet/dotnet').is_file() else shutil.which('dotnet'))
    if not dotnet:
        raise FileNotFoundError('A .NET SDK matching global.json is required')
    env = dict(os.environ, AIJADE_COMPANION_LIVE_MODEL=args.model, AIJADE_COMPANION_LIVE_URL=base,
               AIJADE_COMPANION_LIVE_RECEIPT=str(args.out.resolve() / 'live-model.json'))
    env['DOTNET_ROOT'] = str(Path(dotnet).resolve().parent)
    env['PATH'] = str(Path(dotnet).parent) + os.pathsep + env.get('PATH', '')
    command = [dotnet, 'test', 'tests/Aijade.Tests', '-c', 'Release', '--no-build', '--filter', 'FullyQualifiedName~CompanionLiveTests',
               '--logger', 'trx;LogFileName=live.trx', '--results-directory', str(args.out.resolve() / 'tests')]
    start = time.monotonic(); telemetry = []; reason = None; low = None; swapping = None; process = None
    source_paths = ['src/Aijade.Client/Chat/CompanionRuntime.cs', 'src/Aijade.Client/Chat/ChatContracts.cs',
                    'src/Aijade.Client/Chat/Orchestrator.cs', 'src/Aijade.Client/Companion/CompanionDiary.cs',
                    'src/Aijade.Client/Companion/CompanionSync.cs', 'src/Aijade.Client/Companion/CompanionMediaTurn.cs',
                    'src/Aijade.Server/AijadeServer.cs', 'src/Aijade.Server/Product/CompanionDiary.cs',
                    'src/Aijade.Server/Product/CompanionSync.cs', 'tests/Aijade.Tests/CompanionLiveTests.cs', 'tools/check-companion-live.py']
    artifacts = Path(env.get('AIJADE_ARTIFACTS', root / 'artifacts')) / 'bin'
    write(args.out / 'execution-source.json', {'at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'phase': 'before launching the live test', 'baseCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        'workingTreeModified': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip()),
        'sourceSha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in source_paths},
        'binarySha256': {name: hashlib.sha256((artifacts / name / 'release' / (name + '.dll')).read_bytes()).hexdigest()
                        for name in ['Aijade.Client', 'Aijade.Server', 'Aijade.Tests']}})
    steps = [('product-smoke', command)]
    if args.warmup:
        steps.insert(0, ('model-readiness', [sys.executable, str(Path(__file__).resolve()), '_warmup', base, args.model, str(args.out.resolve())]))
    phases = []
    try:
        with (args.out / 'run.log').open('w') as log:
            for phase, step in steps:
                print(json.dumps({'phase': phase, 'model': args.model}), flush=True)
                process = subprocess.Popen(step, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                phases.append({'name': phase, 'startedSeconds': time.monotonic() - start})
                while process.poll() is None:
                    row = sample(start); row['phase'] = phase; telemetry.append(row); elapsed = row['elapsedSeconds']
                    low = (elapsed if low is None else low) if row['availableBytes'] < 768 * 2**20 else None
                    swapping = (elapsed if swapping is None else swapping) if row['swapUsedBytes'] - samples[-1]['swapUsedBytes'] > 2 * 2**30 else None
                    if low is not None and elapsed - low >= 15: reason = 'AVAILABLE_RAM_BELOW_768_MIB_FOR_15_SECONDS'
                    if swapping is not None and elapsed - swapping >= 30: reason = 'SWAP_INCREMENT_ABOVE_2_GIB_FOR_30_SECONDS'
                    if elapsed >= 600: reason = 'DEVELOPMENT_CHECK_EXCEEDED_600_SECONDS'
                    if reason: break
                    time.sleep(1)
                phases[-1]['exitCode'] = process.poll(); phases[-1]['finishedSeconds'] = time.monotonic() - start
                if reason or process.returncode != 0: break
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
        cleanup_error = None
        try: api(base, '/api/generate', {'model': args.model, 'keep_alive': 0})
        except Exception as error: cleanup_error = type(error).__name__
        write(args.out / 'resource-trace.json', {'scope': 'whole-host available RAM and swap, not attributable model RSS or performance', 'samples': telemetry})
        try: after = api(base, '/api/ps')
        except Exception as error:
            after = None; cleanup_error = cleanup_error or type(error).__name__
        write(args.out / 'run.json', {'kind': 'synthetic product smoke; not primary research', 'model': identity,
            'status': 'STOPPED' if reason else ('PASS' if process is not None and process.returncode == 0 else 'FAILED'),
            'stopReason': reason, 'exitCode': None if process is None else process.returncode,
            'warmupRequested': args.warmup, 'phases': phases,
            'modelUnloadError': cleanup_error, 'after': after,
            'contextRequirement': 'Start the exclusive service with OLLAMA_CONTEXT_LENGTH=4096, OLLAMA_MAX_LOADED_MODELS=1 and OLLAMA_NUM_PARALLEL=1',
            'tempDatabaseNote': 'The test fixture deletes its own database on normal completion; a forcibly stopped process may leave its temporary test database.'})
    print(json.dumps({'phase': 'finished', 'stopReason': reason, 'exitCode': process.returncode}), flush=True)
    return 1 if reason else process.returncode


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '_warmup':
        warm_base, warm_model, warm_out = sys.argv[2:5]
        payload = {'model': warm_model, 'stream': False, 'keep_alive': '10m', 'options': {'num_ctx': 4096}}
        write(Path(warm_out) / 'warmup-request.json', payload)
        request = urllib.request.Request(warm_base + '/api/generate', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=590) as response:
            write(Path(warm_out) / 'warmup-response.json', json.load(response))
    else:
        raise SystemExit(main())
