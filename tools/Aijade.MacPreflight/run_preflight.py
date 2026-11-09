#!/usr/bin/env python3
"""Bounded development preflight; raw replies and failures are retained.

No primary RQ-C runs, model selection by accuracy, or writes to old archives.
Use the project/isolated Python containing psutil for the monitor process.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def api(base, path, body=None, timeout=10):
    request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def http_worker(base, request_path, response_path, timeout):
    started = time.monotonic()
    request = urllib.request.Request(base + '/api/chat', data=Path(request_path).read_bytes(),
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            Path(response_path).write_bytes(raw)
            save(str(response_path) + '.transport.json',
                 {'httpStatus': response.status, 'wallSeconds': time.monotonic() - started, 'completed': True})
        return 0
    except urllib.error.HTTPError as error:
        Path(response_path).write_bytes(error.read())
        save(str(response_path) + '.transport.json',
             {'httpStatus': error.code, 'wallSeconds': time.monotonic() - started, 'completed': False, 'kind': 'HTTP_ERROR'})
        return 1
    except (OSError, ValueError) as error:
        save(str(response_path) + '.transport.json',
             {'httpStatus': None, 'wallSeconds': time.monotonic() - started, 'completed': False,
              'kind': type(error).__name__, 'error': str(error)})
        return 1


def reply_metrics(body, kind, wall):
    if not isinstance(body, dict):
        raise ValueError('Response is not an object')
    if body.get('done') is not True:
        raise ValueError('Response does not establish completion')
    message = body.get('message')
    text = message.get('content') if isinstance(message, dict) else None
    if not isinstance(text, str):
        raise ValueError('Missing message.content')
    values = {}
    for key in ('total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration', 'prompt_eval_count', 'eval_count'):
        value = body.get(key)
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ValueError('Invalid metric: ' + key)
        values[key] = value
    reason = body.get('done_reason')
    duration = values['eval_duration']
    tokens = values['eval_count']
    result = {'completed': True, 'doneReason': reason, 'truncated': reason == 'length', 'empty': not text.strip(),
              'characters': len(text), 'wallSeconds': wall, **values,
              'generationTokensPerSecond': tokens / (duration / 1e9) if tokens and duration else None,
              'wallOutputTokensPerSecond': tokens / wall if tokens and wall else None}
    if kind in ('verifier-A', 'verifier-B', 'format-A'):
        result['verdictPrefixConforming'] = re.match(r'^\s*(?:PASS|FAIL)\b', text, flags=re.IGNORECASE) is not None
        result['singleNonemptyLine'] = len([x for x in text.splitlines() if x.strip()]) == 1
    elif kind in ('generation', 'retry'):
        fence = re.search(r'```(?:js|javascript)[ \t]*\r?\n[\s\S]+?```', text, flags=re.IGNORECASE)
        result['hasJavaScriptCodeFence'] = fence is not None
        result['onlyRequestedCodeFence'] = fence is not None and not (text[:fence.start()] + text[fence.end():]).strip()
    elif kind == 'startup':
        result['readyExactly'] = text.strip() == 'READY'
    return result


class PressureGuard:
    """Elapsed-time bounds; pre-existing swap is not attributed to this model."""
    def __init__(self, baseline_swap):
        self.baseline_swap = baseline_swap
        self.low_since = None
        self.swap_since = None

    def check(self, sample, elapsed):
        if sample['availableBytes'] < 768 * 2**20:
            self.low_since = elapsed if self.low_since is None else self.low_since
        else:
            self.low_since = None
        if sample['swapUsedBytes'] - self.baseline_swap > 2 * 2**30:
            self.swap_since = elapsed if self.swap_since is None else self.swap_since
        else:
            self.swap_since = None
        if self.low_since is not None and elapsed - self.low_since >= 15:
            return 'AVAILABLE_RAM_BELOW_768_MIB_FOR_15_SECONDS'
        if self.swap_since is not None and elapsed - self.swap_since >= 30:
            return 'SWAP_INCREMENT_ABOVE_2_GIB_FOR_30_SECONDS'
        return None


def resource_sample(pid):
    import psutil
    processes = []
    try:
        server = psutil.Process(pid)
        owned = [server, *server.children(recursive=True)]
    except psutil.Error:
        owned = []
    for process in owned:
        try:
            processes.append({'pid': process.pid, 'name': process.name(), 'rssBytes': process.memory_info().rss})
        except psutil.Error:
            pass
    memory = psutil.virtual_memory()
    return {'at': now(), 'availableBytes': memory.available, 'swapUsedBytes': psutil.swap_memory().used,
            'ownedProcessRssBytes': sum(x['rssBytes'] for x in processes), 'processes': processes}


def verify_sources(root, fixture):
    for path, expected in fixture['sourcesSha256'].items():
        if digest(root / path) != expected:
            raise ValueError('Frozen fixture source changed: ' + path)


def unload(base, model):
    # Only the model on this owned private listener, never a production service.
    return api(base, '/api/generate', {'model': model, 'keep_alive': 0, 'stream': False}, timeout=60)


def run(args):
    import psutil
    root, fixtures_path, out = Path(args.repo), Path(args.fixtures), Path(args.out)
    if (out / 'result.json').exists():
        raise FileExistsError('Refusing to overwrite a previous preflight')
    fixture = json.loads(fixtures_path.read_text())
    verify_sources(root, fixture)
    out.mkdir(parents=True, exist_ok=True)
    server_before = api(args.base, '/api/version')
    existing = api(args.base, '/api/ps')
    if existing.get('models'):
        raise RuntimeError('Private listener already has loaded models; refusing to interfere')
    expected = {'qwen2.5-coder:7b-instruct': 'dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364',
                'llama3.1:8b': '46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e'}
    summary = {'kind': 'Mac development capacity and latency preflight', 'startedAt': now(),
               'primaryExperiment': False, 'supervisorApprovalInferred': False, 'fixtureSha256': digest(fixtures_path),
               'harnessSha256': digest(__file__), 'serverBefore': server_before, 'privateEndpoint': args.base,
               'serverLimits': {'maxLoadedModels': 1, 'parallelRequests': 1},
               'resourceSemantics': 'Available RAM and used swap are system snapshots; owned-process RSS includes shared mappings. Existing swap is not attributed to these requests.',
               'host': {'architecture': __import__('platform').machine(), 'physicalCores': psutil.cpu_count(logical=False),
                        'logicalThreads': psutil.cpu_count(), 'totalMemoryBytes': psutil.virtual_memory().total},
               'models': []}
    save(out / 'execution-start.json', summary)
    source_state = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True)
    summary['sourceHead'] = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    summary['sourceTreeDirty'] = bool(source_state.strip())
    active_model = None
    try:
        for model_index, (model, archive_digest) in enumerate(expected.items()):
            model_dir = out / ('qwen7b' if model_index == 0 else 'llama8b')
            model_dir.mkdir()
            tags = api(args.base, '/api/tags')['models']
            identity = next((m for m in tags if m['name'] == model), None)
            if identity is None:
                summary['models'].append({'model': model, 'status': 'MODEL_NOT_AVAILABLE', 'requests': []})
                continue
            active_model = model
            model_start = time.monotonic()
            baseline = resource_sample(args.server_pid)
            guard = PressureGuard(baseline['swapUsedBytes'])
            row = {'model': model, 'identity': identity, 'archiveDigestMatches': identity['digest'] == archive_digest,
                   'startedAt': now(), 'baseline': baseline, 'requests': [], 'status': 'RUNNING',
                   'minAvailableBytes': baseline['availableBytes'], 'maxSwapUsedBytes': baseline['swapUsedBytes'],
                   'peakOwnedProcessRssBytes': baseline['ownedProcessRssBytes']}
            summary['models'].append(row)
            save(model_dir / 'model-show.json', api(args.base, '/api/show', {'model': model}))
            save(out / 'result.partial.json', summary)
            for index, item in enumerate(fixture['items']):
                request_dir = model_dir / item['id']
                request_dir.mkdir()
                body = {'model': model, 'messages': [{'role': 'user', 'content': item['prompt']}],
                        'stream': False, 'keep_alive': 300, 'options': fixture['sampling']}
                save(request_dir / 'request.json', body)
                response_path = request_dir / 'response.json'
                request_start = time.monotonic()
                result = {'id': item['id'], 'kind': item['kind'], 'startedAt': now(),
                          'requestSha256': digest(request_dir / 'request.json')}
                print(json.dumps({'event': 'request-start', 'model': model, 'case': item['id'], 'index': index + 1}, ensure_ascii=False), flush=True)
                with (request_dir / 'worker.log').open('w') as worker_log, (request_dir / 'telemetry.jsonl').open('w') as telemetry:
                    worker = subprocess.Popen([sys.executable, __file__, 'http-worker', '--base', args.base,
                                               '--request', str(request_dir / 'request.json'), '--response', str(response_path), '--timeout', '900'],
                                              stdout=worker_log, stderr=subprocess.STDOUT)
                    stopped = None
                    while True:
                        sample = resource_sample(args.server_pid)
                        sample['requestElapsedSeconds'] = time.monotonic() - request_start
                        telemetry.write(json.dumps(sample) + '\n'); telemetry.flush()
                        row['minAvailableBytes'] = min(row['minAvailableBytes'], sample['availableBytes'])
                        row['maxSwapUsedBytes'] = max(row['maxSwapUsedBytes'], sample['swapUsedBytes'])
                        row['peakOwnedProcessRssBytes'] = max(row['peakOwnedProcessRssBytes'], sample['ownedProcessRssBytes'])
                        stopped = guard.check(sample, time.monotonic() - model_start)
                        if time.monotonic() - request_start > 900:
                            stopped = 'REQUEST_DEADLINE_900_SECONDS'
                        if time.monotonic() - model_start > 3600:
                            stopped = 'MODEL_WINDOW_3600_SECONDS'
                        if worker.poll() is not None:
                            break
                        if stopped:
                            worker.terminate()
                            try:
                                worker.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                worker.kill(); worker.wait()
                            break
                        time.sleep(1)
                result['observedWallSeconds'] = time.monotonic() - request_start
                result['workerExitCode'] = worker.returncode
                if stopped:
                    result['status'] = stopped
                elif worker.returncode != 0:
                    result['status'] = 'TRANSPORT_OR_SERVER_ERROR'
                    result['transport'] = json.loads(Path(str(response_path) + '.transport.json').read_text())
                else:
                    try:
                        response = json.loads(response_path.read_text())
                        transport = json.loads(Path(str(response_path) + '.transport.json').read_text())
                        result['metrics'] = reply_metrics(response, item['kind'], transport['wallSeconds'])
                        result['responseSha256'] = digest(response_path)
                        result['status'] = 'COMPLETED'
                        if result['metrics']['truncated']:
                            result['status'] = 'LENGTH_LIMITED'
                        elif result['metrics']['empty']:
                            result['status'] = 'EMPTY_REPLY'
                    except (ValueError, KeyError) as error:
                        result['status'] = 'INVALID_RESPONSE'; result['error'] = str(error)
                try:
                    result['loadedModelState'] = api(args.base, '/api/ps')
                    loaded = result['loadedModelState'].get('models', [])
                    if result['status'] == 'COMPLETED' and (len(loaded) != 1 or any(m.get('context_length') != 4096 or m.get('digest') != identity['digest'] for m in loaded)):
                        result['status'] = 'CONTEXT_ALLOCATION_NOT_CONFIRMED'
                except (OSError, ValueError) as error:
                    result['stateProbeError'] = str(error)
                    if result['status'] == 'COMPLETED':
                        result['status'] = 'CONTEXT_ALLOCATION_NOT_CONFIRMED'
                row['requests'].append(result)
                save(request_dir / 'measurement.json', result)
                save(out / 'result.partial.json', summary)
                print(json.dumps({'event': 'request-end', 'model': model, 'case': item['id'], 'status': result['status'],
                                  'seconds': round(result['observedWallSeconds'], 3)}, ensure_ascii=False), flush=True)
                if result['status'] not in ('COMPLETED', 'LENGTH_LIMITED', 'EMPTY_REPLY'):
                    row['status'] = 'STOPPED_' + result['status']; break
            else:
                row['status'] = 'REQUEST_SET_COMPLETED'
            row['endedAt'] = now()
            row['seconds'] = time.monotonic() - model_start
            row['swapIncreaseFromModelBaselineBytes'] = row['maxSwapUsedBytes'] - baseline['swapUsedBytes']
            row['unloadResponse'] = unload(args.base, model)
            row['stateAfterUnload'] = api(args.base, '/api/ps')
            if row['stateAfterUnload'].get('models'):
                raise RuntimeError('Owned model did not unload; do not start a second model')
            active_model = None
            save(out / 'result.partial.json', summary)
        summary['serverAfter'] = api(args.base, '/api/version')
        summary['serverVersionUnchanged'] = summary['serverAfter'] == server_before
        summary['endedAt'] = now()
        save(out / 'result.json', summary)
    finally:
        if active_model:
            try:
                unload(args.base, active_model)
            except (OSError, ValueError):
                pass
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    worker = sub.add_parser('http-worker')
    for key in ('base', 'request', 'response'):
        worker.add_argument('--' + key, required=True)
    worker.add_argument('--timeout', type=float, default=900)
    run_parser = sub.add_parser('run')
    for key in ('repo', 'fixtures', 'out'):
        run_parser.add_argument('--' + key, required=True)
    run_parser.add_argument('--base', default='http://127.0.0.1:11509')
    run_parser.add_argument('--server-pid', type=int, required=True)
    args = parser.parse_args()
    if args.command == 'http-worker':
        return http_worker(args.base, args.request, args.response, args.timeout)
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
