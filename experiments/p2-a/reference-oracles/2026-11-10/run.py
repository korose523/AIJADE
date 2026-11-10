"""Mac-only bounded public-reference preparation. Real corpus execution requires --execute."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from oracle_core import canonical, digest_file, read_problems, source_json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PYTHON = Path('/Users/mac/.local/share/uv/python/cpython-3.12.14-macos-x86_64-none/bin/python3.12')
PLAN = 'c97638dec08db3a74d5ac6bd105f8ba5f7e5194c'
ENVIRONMENT = {'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1', 'LC_ALL': 'C', 'TZ': 'UTC'}


def profile(output, stderr):
    runtime = PYTHON.resolve().parent.parent
    quote = lambda p: json.dumps(str(Path(p).resolve()))
    # No user-home, network, process-fork or general write grant.
    return '\n'.join(['(version 1)', '(deny default)', '(allow sysctl-read)', '(allow mach-lookup)', '(allow file-read-metadata)',
                      '(allow process-exec (literal ' + quote(PYTHON) + '))',
                      '(allow file-read* (require-any (subpath "/System") (subpath "/usr/lib") (subpath "/usr/share")',
                      ' (subpath ' + quote(runtime) + ') (subpath ' + quote(HERE) + ')',
                      ' (literal "/") (literal "/dev/null") (literal "/dev/urandom") (literal "/private/etc/localtime")))',
                      '(allow file-write* (require-any (literal ' + quote(output) + ') (literal ' + quote(stderr) + ') (literal "/dev/null")))']) + '\n'


def execute(payload, folder, wall_seconds=30):
    folder.mkdir(parents=True, exist_ok=False)
    output, stderr = folder/'stdout.jsonl', folder/'stderr.log'
    output.touch(); stderr.touch()
    policy = profile(output, stderr)
    (folder/'isolation.sb').write_text(policy)
    command = ['/usr/bin/sandbox-exec', '-f', str(folder/'isolation.sb'), str(PYTHON), '-S', '-P', str(HERE/'worker.py')]
    started = time.monotonic()
    peak_rss = None
    stop = None
    with output.open('wb') as out, stderr.open('wb') as err:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                 cwd=folder, env=ENVIRONMENT, start_new_session=True)
        try:
            child.stdin.write(source_json(payload).encode())
            child.stdin.close()
        except BrokenPipeError:
            stop = 'EARLY_PROCESS_EXIT'
        while child.poll() is None:
            if time.monotonic()-started > wall_seconds:
                stop = 'WALL_TIME_LIMIT'
                os.killpg(child.pid, signal.SIGKILL)
                break
            sample = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(child.pid)], capture_output=True, text=True, check=False)
            values = sample.stdout.split()
            if values and values[0].isdigit():
                rss = int(values[0])*1024
                peak_rss = max(peak_rss or 0, rss)
                if rss > 1024**3:
                    stop = 'RSS_MONITOR_LIMIT'
                    os.killpg(child.pid, signal.SIGKILL)
                    break
            time.sleep(0.1)
        code = child.wait()
    raw = output.read_bytes()
    valid = []
    malformed = False
    for line in raw.splitlines(keepends=True):
        try:
            json.loads(line)
            valid.append(line if line.endswith(b'\n') else line+b'\n')
        except (ValueError, UnicodeDecodeError):
            malformed = True
    result = {'exitCode': code, 'stopReason': stop, 'wallSeconds': round(time.monotonic()-started, 6),
              'peakSampledRssBytes': peak_rss, 'stdoutSha256': hashlib.sha256(raw).hexdigest(),
              'stderrSha256': digest_file(stderr), 'profileSha256': digest_file(folder/'isolation.sb'),
              'command': command, 'malformedPartialOutput': malformed,
              'status': 'COMPLETE' if code == 0 and valid and json.loads(valid[-1]).get('kind') == 'end' and not malformed else 'INCOMPLETE'}
    (folder/'execution.json').write_text(json.dumps(result, indent=2)+'\n')
    return result, b''.join(valid)


def main(args):
    assert sys.platform == 'darwin', 'The native restriction profile is macOS-only'
    assert args.execute, 'Real corpus execution requires explicit --execute'
    assert not args.out.exists(), 'Output already exists; preserve earlier attempts'
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT), 'Execution source must be clean'
    subprocess.run(['git', 'merge-base', '--is-ancestor', PLAN, code], cwd=ROOT, check=True)
    qualification = json.loads(args.qualification.read_text())
    assert qualification['status'] == 'PASS' and qualification['sourceSha256'] == {n: digest_file(HERE/n) for n in ['run.py', 'worker.py', 'oracle_core.py']}
    problems = read_problems(HERE/'inputs')
    args.out.mkdir(parents=True)
    start = time.monotonic()
    receipt = {'schema': 'aijade.p2a.reference.execution.v1', 'planCommit': PLAN, 'executionCodeCommit': code,
               'status': 'RUNNING', 'startedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
               'pythonSha256': digest_file(PYTHON), 'pythonVersion': subprocess.check_output([str(PYTHON), '--version'], env=ENVIRONMENT).decode().strip(),
               'sourceSha256': {n: digest_file(HERE/n) for n in ['run.py', 'worker.py', 'oracle_core.py']},
               'environment': ENVIRONMENT, 'newModelCalls': 0, 'taskPasses': 1084, 'configuredInputCallsPerPass': 165268,
               'globalWallLimitSeconds': 2700, 'limits': {'cpuSecondsPerTask': 15, 'wallSecondsPerTask': 30, 'dataBytesSetting': 512*1024**2, 'rssMonitoringBytes': 1024**3, 'fileBytesPerTask': 64*1024**2}}
    (args.out/'execution.json').write_text(json.dumps(receipt, indent=2)+'\n')
    completed = 0
    stopped = False
    for pass_index in [1, 2]:
        order = problems if pass_index == 1 else list(reversed(problems))
        dest = args.out/f'pass-{pass_index}'
        dest.mkdir()
        with gzip.open(dest/'rows.jsonl.gz', 'wb') as rows, (dest/'tasks.jsonl').open('w') as tasks:
            for dataset, problem in order:
                if time.monotonic()-start > 2700:
                    stopped = True
                    break
                task_id = problem['task_id']
                temporary = dest/'workers'/task_id.replace('/', '-')
                payload = {'dataset': dataset, 'problem': problem}
                result, data = execute(payload, temporary)
                rows.write(data); rows.flush()
                result.update(taskId=task_id, dataset=dataset, passIndex=pass_index,
                              expectedCases=len(problem['base_input'])+len(problem['plus_input']),
                              problemSha256=hashlib.sha256(source_json(problem).encode()).hexdigest())
                tasks.write(canonical(result)+'\n'); tasks.flush()
                completed += 1
                (args.out/'progress.json').write_text(canonical({'completedTaskPasses': completed, 'plannedTaskPasses': 1084,
                                                                'passIndex': pass_index, 'lastTaskId': task_id,
                                                                'lastStatus': result['status'], 'elapsedSeconds': round(time.monotonic()-start, 2)})+'\n')
                if result['exitCode'] != 0 and not data:
                    # Empty corpus output cannot be mistaken for a reference-task failure.
                    stopped = True
                    receipt['infrastructureStopTask'] = task_id
                    break
        if stopped:
            break
    receipt.update(status='STOPPED_PRESERVE_PARTIAL' if stopped else 'ALL_TASK_PASSES_ATTEMPTED_VALIDATE_BEFORE_CLAIMS',
                   completedTaskPasses=completed, wallSeconds=round(time.monotonic()-start, 6),
                   endedAt=dt.datetime.now(dt.timezone.utc).isoformat())
    (args.out/'execution.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(canonical(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    main(parser.parse_args())
