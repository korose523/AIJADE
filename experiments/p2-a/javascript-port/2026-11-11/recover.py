"""Recover complete typed references for previously truncated direct tasks on the Mac."""
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parents[1] / 'reference-oracles/2026-11-10'
sys.path.insert(0, str(REFERENCE))
from oracle_core import canonical, digest_file, load_deserializer, read_problems, source_json, typed
from run import ENVIRONMENT, PYTHON, profile


def execute(dataset, problem, target):
    target.mkdir(parents=True)
    output, errors = target/'stdout.jsonl.gz', target/'stderr.log'
    wrapper = HERE/'compact_worker.py'
    policy = profile(output, errors) + f'(allow file-read* (literal {json.dumps(str(wrapper))}))\n'
    profile_path = target/'isolation.sb'
    profile_path.write_text(policy)
    payload_path = target/'input.json'
    payload_path.write_text(source_json({'dataset': dataset, 'problem': problem}))
    command = ['/usr/bin/sandbox-exec', '-f', str(profile_path), str(PYTHON), '-S', '-P', str(wrapper)]
    start = time.monotonic()
    peak = 0
    stop = None
    with payload_path.open('rb') as payload, output.open('wb') as stdout, errors.open('wb') as stderr:
        worker = subprocess.Popen(command, stdin=payload, stdout=stdout, stderr=stderr,
                                  env=ENVIRONMENT, cwd=target, start_new_session=True)
        while worker.poll() is None:
            if time.monotonic() - start > 30:
                stop = 'WALL_LIMIT'
            sample = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(worker.pid)], capture_output=True, text=True)
            if sample.stdout.strip().isdigit():
                peak = max(peak, int(sample.stdout) * 1024)
                if peak > 1024**3:
                    stop = 'RSS_MONITOR_LIMIT'
            if stop:
                os.killpg(worker.pid, signal.SIGKILL)
                break
            time.sleep(.1)
        code = worker.wait()
    receipt = {'taskId': problem['task_id'], 'exitCode': code, 'stop': stop, 'peakRssBytes': peak,
               'wallSeconds': round(time.monotonic()-start, 3), 'inputSha256': digest_file(payload_path),
               'streamSha256': digest_file(output), 'compressedBytes': output.stat().st_size,
               'workerSha256': digest_file(REFERENCE/'worker.py'), 'wrapperSha256': digest_file(wrapper),
               'policySha256': digest_file(profile_path), 'pythonSha256': digest_file(PYTHON),
               'stderrSha256': digest_file(errors)}
    (target/'execution.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


def inspect(dataset, problem, path):
    deserialize, deserializer_sha = load_deserializer(REFERENCE/'upstream')
    originals = []
    for part in ['base', 'plus']:
        raw = problem[part+'_input']
        native = deserialize(problem['task_id'], copy.deepcopy(raw)) if dataset == 'MBPP+' else raw
        originals.extend((part, index, a, b) for index, (a, b) in enumerate(zip(raw, native)))
    count = 0
    exceptions = 0
    end = None
    error = None
    digest = hashlib.sha256()
    try:
        with gzip.open(path, 'rb') as stream:
            for line in stream:
                row = json.loads(line)
                assert end is None and row['taskId'] == problem['task_id']
                if row['kind'] == 'begin':
                    assert count == 0 and row['problemSha256'] == hashlib.sha256(source_json(problem).encode()).hexdigest()
                    assert row['deserializerFunctionSha256'] == deserializer_sha
                    assert row['codeSha256'] == hashlib.sha256((problem['prompt']+problem['canonical_solution']).encode()).hexdigest()
                    continue
                if row['kind'] == 'case':
                    part, index, raw, native = originals[count]
                    assert (row['partition'], row['index']) == (part, index)
                    assert row['serializedArgsJson'] == json.dumps(raw, ensure_ascii=False, separators=(',', ':'))
                    assert row['input'] == typed(native)[0]
                    count += 1
                    exceptions += int(row['status'] != 'OK')
                else:
                    assert row['kind'] == 'end'
                    end = row['nativeAssertions']
                digest.update(line)
    except (EOFError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        error = type(exc).__name__
    return {'planned': len(originals), 'recorded': count, 'exceptions': exceptions, 'nativeAssertions': end,
            'readError': error, 'semanticSha256': digest.hexdigest(),
            'complete': count == len(originals) and end == {'status': 'PASS'} and not exceptions and error is None}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    prior = json.loads((REFERENCE/'summary.json').read_text())
    identities = {r['taskId'] for r in prior['ledger'] if r['staticClass']=='direct' and not r['criteria']['bothPassesComplete']}
    assert identities == {'HumanEval/15', 'Mbpp/255', 'Mbpp/630'}
    order = [(dataset, p) for dataset, p in read_problems(REFERENCE/'inputs') if p['task_id'] in identities]
    fixture = {'task_id': 'HumanEval/compact-fixture', 'entry_point': 'f', 'atol': 0,
               'prompt': 'def f(x):\n', 'canonical_solution': '    return x * 2\n',
               'base_input': [[3]], 'plus_input': [[7]], 'test': 'def check(f):\n    assert f(3) == 6\n'}
    trial = execute('HumanEval+', fixture, out/'qualification')
    assert trial['exitCode'] == 0 and inspect('HumanEval+', fixture, out/'qualification/stdout.jsonl.gz')['complete'], trial
    rows = {tid: [] for tid in identities}
    for pass_id, tasks in [(1, order), (2, list(reversed(order)))]:
        for dataset, p in tasks:
            target = out / f'pass-{pass_id}' / p['task_id'].replace('/', '-')
            rec = execute(dataset, p, target)
            validation = inspect(dataset, p, target/'stdout.jsonl.gz')
            rows[p['task_id']].append({'pass': pass_id, 'path': str(target.relative_to(out)/'stdout.jsonl.gz'),
                                      **rec, **validation})
            print(p['task_id'], pass_id, rec['exitCode'], rec['stop'], validation['recorded'], validation['planned'], flush=True)
    result = {'taskPasses': sum(map(len, rows.values())), 'qualification': trial, 'tasks': {}}
    for tid, passes in rows.items():
        accepted = all(p['complete'] and p['exitCode']==0 for p in passes) and len({p['semanticSha256'] for p in passes})==1
        result['tasks'][tid] = {'accepted': accepted, 'passes': passes}
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
