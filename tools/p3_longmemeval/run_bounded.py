#!/usr/bin/env python3
"""Serial, resource-bounded local phase runner. No live job is restarted by this controller."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psutil

GIB = 1024 ** 3
PLAN = 'a7961cf8cde1de659c2272a664d4c936a50484c4'


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


def run(args):
    assert args.command and args.command[0] != '--'
    assert git(args.repo, 'status', '--porcelain') == '', 'Execution requires a completely clean code/evidence tree.'
    head = git(args.repo, 'rev-parse', 'HEAD')
    assert head == os.environ['AIJADE_GIT_COMMIT']
    assert os.environ.get('DOTNET_PROCESSOR_COUNT') == '2'
    args.output.mkdir(parents=True, exist_ok=True)
    attempt = args.output / args.phase
    attempt.mkdir(exist_ok=False)
    started = time.time()
    followup = args.output / 'followup-start.json'
    if not followup.exists():
        with followup.open('x') as f:
            json.dump(dict(started=started, utc=utc(), planCommit=PLAN), f)
    whole_started = json.loads(followup.read_text())['started']
    initial_swap = psutil.swap_memory().used
    initial = dict(availableBytes=psutil.virtual_memory().available, swapUsedBytes=initial_swap)
    identity = dict(schema='aijade.p3.longmemeval.bounded-phase.v1', phase=args.phase, planCommit=PLAN,
                    codeCommit=head, codeTree=git(args.repo, 'rev-parse', 'HEAD^{tree}'), startedAt=utc(),
                    command=args.command, python=sys.executable, psutil=psutil.__version__, initial=initial,
                    limits=dict(cpuSeconds=28800, wallSeconds=43200, wholeFollowupWallSeconds=86400,
                                ownedFamilyRssBytes=3*GIB, physicalOutputBytes=512*1024**2,
                                minAvailableBytes=768*1024**2, sustainedSeconds=30, maxSwapIncreaseBytes=2*GIB),
                    memoryScope='Sampled process family, sum of RSS including shared mappings. Existing Docker DB is a shared service, not an owned descendant; host available/swap limits still apply.')
    (attempt/'identity.json').write_text(json.dumps(identity, indent=2)+'\n')
    with (attempt/'stdout.log').open('xb') as stdout, (attempt/'stderr.log').open('xb') as stderr, (attempt/'telemetry.jsonl').open('x') as telemetry:
        child = subprocess.Popen(args.command, cwd=args.repo, env=os.environ.copy(), stdout=stdout, stderr=stderr, start_new_session=True)
        root = psutil.Process(child.pid)
        (attempt/'pid.json').write_text(json.dumps(dict(pid=child.pid, createTime=root.create_time(), startedAt=utc()))+'\n')
        observed_cpu = {}
        low_since = swap_since = None
        reason = None
        peak_rss = peak_swap = cpu_total = 0
        minimum_available = initial['availableBytes']
        last_file_check = 0
        while child.poll() is None:
            now = time.time()
            try:
                family = [root] + root.children(recursive=True)
            except psutil.Error:
                family = []
            rss = 0
            for process in family:
                try:
                    key = (process.pid, process.create_time())
                    cpu = process.cpu_times()
                    observed_cpu[key] = max(observed_cpu.get(key, 0), cpu.user + cpu.system)
                    rss += process.memory_info().rss
                except psutil.Error:
                    pass
            cpu_total = sum(observed_cpu.values())
            available = psutil.virtual_memory().available
            swap = psutil.swap_memory().used
            low_since = (low_since if low_since is not None else now) if available < 768*1024**2 else None
            swap_since = (swap_since if swap_since is not None else now) if swap - initial_swap > 2*GIB else None
            peak_rss = max(peak_rss, rss); peak_swap = max(peak_swap, swap-initial_swap); minimum_available = min(minimum_available, available)
            telemetry.write(json.dumps(dict(utc=utc(), elapsedSeconds=now-started, cpuSeconds=cpu_total, ownedFamilyRssBytes=rss,
                                           availableBytes=available, swapUsedBytes=swap, swapIncreaseBytes=swap-initial_swap,
                                           processes=len(family)))+'\n')
            telemetry.flush()
            if cpu_total > 28800: reason = 'cpu-time-limit'
            elif now-started > 43200: reason = 'phase-wall-time-limit'
            elif now-whole_started > 86400: reason = 'whole-followup-wall-time-limit'
            elif rss > 3*GIB: reason = 'sampled-owned-family-rss-limit'
            elif low_since is not None and now-low_since >= 30: reason = 'sustained-low-available-memory'
            elif swap_since is not None and now-swap_since >= 30: reason = 'sustained-swap-increase'
            if now-last_file_check > 10:
                last_file_check = now
                for folder in [attempt, args.measurements]:
                    if folder.exists() and any(p.stat().st_size > 512*1024**2 for p in folder.rglob('*') if p.is_file()):
                        reason = 'physical-file-size-limit'
            if reason:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM)
                    try: child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=10)
                break
            time.sleep(1)
        code = child.wait()
    unchanged = git(args.repo, 'rev-parse', 'HEAD') == head and git(args.repo, 'status', '--porcelain') == ''
    status = 'PASS' if code == 0 and reason is None and unchanged else 'STOPPED' if reason else 'FAIL'
    receipt = dict(identity, finishedAt=utc(), status=status, stopReason=reason, exitCode=code, sourceUnchanged=unchanged,
                   elapsedSeconds=time.time()-started, observedCpuSeconds=cpu_total, maxOwnedFamilyRssBytes=peak_rss,
                   minAvailableBytes=minimum_available, maxSwapIncreaseBytes=peak_swap,
                   logs=[dict(path=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest(), bytes=p.stat().st_size)
                         for p in [attempt/'stdout.log', attempt/'stderr.log', attempt/'telemetry.jsonl']],
                   scientificAcceptance='A successful controller is a bounded execution receipt, not a statistical or manuscript acceptance decision.')
    (attempt/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2), flush=True)
    return 0 if status == 'PASS' else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--out', dest='output', required=True, type=Path)
    parser.add_argument('--measurements', required=True, type=Path)
    parser.add_argument('--phase', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ['--']: args.command = args.command[1:]
    raise SystemExit(run(args))
