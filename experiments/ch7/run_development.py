#!/usr/bin/env python3
"""Serial, resource-bounded Chapter 7 development batch. No model calls or held-out cases.

Requires Python 3.11+, psutil 7.2.2, a built clean AIJADE checkout, the existing
MOSAIC client source copy, a local PMX asset and the archived two-program selection.
The source copy is copied again before building; the original checkout is read-only.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

import psutil

GIB = 1024 ** 3
PLAN = 'aed0795'
METHOD = 'Aijade.Tests.ResearchLoopQualificationTests.'


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main(args):
    repo = args.repo.resolve()
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True) == ''
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    assert commit == os.environ['AIJADE_GIT_COMMIT']
    assert os.environ.get('DOTNET_PROCESSOR_COUNT') == '2'
    assert psutil.__version__ == '7.2.2'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_copy = output / 'renderer-source'
    shutil.copytree(args.client, source_copy,
                    ignore=shutil.ignore_patterns('.godot', 'bin', 'obj', '__pycache__'))
    preset = repo / 'experiments/p1/external-renderer/preset'
    shutil.copytree(preset, output / 'preset')
    shutil.copy2(args.selection, output / 'selection.json')
    selection = json.loads((output / 'selection.json').read_text())
    for relative, expected in selection['sources'].items():
        assert sha(repo / relative) == expected, relative
    dll = repo / 'tests/Aijade.Tests/bin/Release/net10.0/Aijade.Tests.dll'
    binary_files = sorted(dll.parent.glob('*.dll'))
    binaries = {p.name: sha(p) for p in binary_files}
    sources = {str(p.relative_to(source_copy)): sha(p) for p in source_copy.rglob('*') if p.is_file()}
    model_sha = sha(args.model)
    write(output / 'input-identities.json', dict(
        codeCommit=commit, planCommit=subprocess.check_output(['git', 'rev-parse', PLAN], cwd=repo, text=True).strip(),
        planSha256=sha(repo / 'experiments/plans/2026-11-12-ch7-adapter-qualification.md'),
        binaries=binaries, rendererSources=sources, modelSha256=model_sha,
        selectionSha256=sha(output / 'selection.json'),
        benchSha256=sha(repo / 'src/Aijade.Research/SkillBench/bench-data.json')))
    env = dict(os.environ)
    env.update(DOTNET_ROOT=str(args.dotnet.parent), DOTNET_CLI_TELEMETRY_OPTOUT='1',
               PATH=str(args.dotnet.parent) + os.pathsep + env.get('PATH', ''))
    session = 'ch7-dev-' + output.name
    env['MOSAIC_SESSION_ID'] = session
    started = time.monotonic()
    initial_swap = psutil.swap_memory().used
    roots = []
    handles = []
    timers = {}
    cpu = {}
    phases = {}
    peaks = dict(rssBytes=0, swapIncreaseBytes=0, minAvailableBytes=psutil.virtual_memory().available)
    telemetry = (output / 'telemetry.jsonl').open('x')
    reason = None
    status = 'RUNNING'

    def launch(name, command, cwd, extra=None):
        stream = (output / (name + '.log')).open('x')
        handles.append(stream)
        proc = subprocess.Popen(command, cwd=cwd, env=dict(env, **(extra or {})),
                                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        roots.append(proc)
        phases[name] = dict(startedAt=utc(), pid=proc.pid, exitCode=None)
        return proc

    def tick():
        now = time.monotonic()
        family = {}
        for root in roots:
            if root.poll() is not None:
                continue
            try:
                parent = psutil.Process(root.pid)
                for child in [parent] + parent.children(recursive=True):
                    family[(child.pid, child.create_time())] = child
            except psutil.Error:
                pass
        rss = 0
        for key, child in family.items():
            try:
                rss += child.memory_info().rss
                t = child.cpu_times()
                cpu[key] = max(cpu.get(key, 0), t.user + t.system)
            except psutil.Error:
                pass
        available = psutil.virtual_memory().available
        swap = max(0, psutil.swap_memory().used - initial_swap)
        peaks['rssBytes'] = max(peaks['rssBytes'], rss)
        peaks['swapIncreaseBytes'] = max(peaks['swapIncreaseBytes'], swap)
        peaks['minAvailableBytes'] = min(peaks['minAvailableBytes'], available)
        telemetry.write(json.dumps(dict(utc=utc(), elapsedSeconds=now-started, rssBytes=rss,
                                       availableBytes=available, swapIncreaseBytes=swap)) + '\n')
        telemetry.flush()
        for name, crossed in [('rss', rss > 2*GIB), ('available', available < 3*GIB), ('swap', swap > GIB)]:
            if not crossed:
                timers.pop(name, None)
            else:
                timers.setdefault(name, now)
                if now - timers[name] >= 30:
                    raise RuntimeError(name + '_sustained_resource_stop')
        if now - started > 1200:
            raise RuntimeError('wall_limit_stop')
        time.sleep(1)

    def finish(name, proc):
        while proc.poll() is None:
            tick()
        phases[name].update(exitCode=proc.returncode, endedAt=utc())
        if proc.returncode != 0:
            raise RuntimeError(name + '_nonzero_exit')

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        renderer = launch('renderer', [sys.executable, str(source_copy / 'scripts/run-native-mmd-scene.py'),
            '--headless', '--out', str(output / 'client'), '--pmx', str(args.model), '--scale', '0.1',
            '--clip', str(output / 'preset/companion-rest.vmd'), '--pose-mode', 'pmx', '--preserve-signed-linear-weights',
            '--behavior', str(output / 'preset/companion-plan.json'), '--behavior-live', str(port), '--timeout', '400'], source_copy)
        state = output / 'client/aijade-render-state.jsonl'
        context = None
        while context is None:
            if renderer.poll() is not None:
                raise RuntimeError('renderer_ended_before_registration')
            if state.is_file():
                with state.open() as stream:
                    first = stream.readline()
                if first.strip():
                    context = json.loads(first).get('renderer_context_id')
            tick()
        prepare = launch('prepare', [str(args.dotnet), str(dll), '-method', METHOD +
            'Prepare_archived_executions_and_register_before_render_dispatch', '-xml', str(output / 'prepare.xml')], repo,
            dict(AIJADE_CH7_PREPARE=str(output), AIJADE_CH7_INPUT=str(output/'selection.json'),
                 AIJADE_CH7_SESSION=session, AIJADE_CH7_CONTEXT=context, AIJADE_CH7_PORT=str(port)))
        finish('prepare', prepare)
        finish('renderer', renderer)
        qualify = launch('qualify', [str(args.dotnet), str(dll), '-method', METHOD +
            'Qualify_ten_declared_cases_on_the_staged_C2_path', '-xml', str(output / 'qualify.xml')], repo,
            dict(AIJADE_CH7_RUN=str(output)))
        finish('qualify', qualify)
        cases = json.loads((output / 'cases.json').read_text())
        assert len(cases) == 10 and all(c['qualified'] for c in cases)
        assert all(c['gatewayAttempts'] == 0 for c in cases)
        assert binaries == {p.name: sha(p) for p in binary_files}
        assert sha(args.model) == model_sha
        assert all(sha(repo / relative) == expected for relative, expected in selection['sources'].items())
        assert sources == {rel: sha(source_copy / rel) for rel in sources}
        status = 'PASS_DEVELOPMENT_QUALIFICATION_ONLY'
    except Exception as error:
        status = 'STOPPED'
        reason = type(error).__name__ + ': ' + str(error)
    finally:
        for root in roots:
            if root.poll() is None:
                os.killpg(root.pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while any(root.poll() is None for root in roots) and time.monotonic() < deadline:
            time.sleep(.1)
        for root in roots:
            if root.poll() is None:
                os.killpg(root.pid, signal.SIGKILL)
        for handle in handles:
            handle.close()
        telemetry.close()
        write(output / 'receipt.json', dict(schema='aijade.ch7.development-receipt.v1', status=status, reason=reason,
            codeCommit=commit, finishedAt=utc(), wallSeconds=time.monotonic()-started, ownedCpuSeconds=sum(cpu.values()),
            peak=peaks, phases=phases, plannedCases=10,
            completedCases=len(json.loads((output/'cases.json').read_text())) if (output/'cases.json').is_file() else 0,
            heldOutCases=0, conditionsMeasured=['C2'], semanticJudgments='AI-assisted; no independent human review',
            formalHardwareQualification=False, modelRequests=0))
    print(json.dumps(dict(status=status, reason=reason, wallSeconds=time.monotonic()-started)))
    return 0 if status.startswith('PASS') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['repo', 'client', 'model', 'selection', 'output', 'dotnet']:
        parser.add_argument('--' + key, type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
