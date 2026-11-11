#!/usr/bin/env python3
"""Serial known-case second-round persisted-act renderer observation. No model calls or held-out cases.

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
PLAN = 'c2f2011'
METHOD = 'Aijade.Tests.ResearchLoopQualificationTests.'


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def idle_admission(output, commit):
    started=time.monotonic(); samples=[]
    with (output/'admission-telemetry.jsonl').open('x') as log:
        while True:
            now=time.monotonic()
            processes=[p.info for p in psutil.process_iter(['pid','name']) if
                       (p.info['name'] or '').lower() in ['dotnet','ollama'] or 'godot' in (p.info['name'] or '').lower()]
            item=dict(utc=utc(),elapsedSeconds=now-started,availableBytes=psutil.virtual_memory().available,
                      swapUsedBytes=psutil.swap_memory().used,researchProcesses=processes)
            samples.append(item); log.write(json.dumps(item)+'\n'); log.flush()
            if now-started>=120: break
            time.sleep(min(2,120-(now-started)))
    minimum=min(s['availableBytes'] for s in samples)
    span=max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples)
    admitted=minimum>=4*GIB and span<=64*1024**2 and all(not s['researchProcesses'] for s in samples)
    result=dict(schema='aijade.ch7.round2-admission.v1',admitted=admitted,codeCommit=commit,plan=PLAN,
                elapsedSeconds=samples[-1]['elapsedSeconds'],samples=len(samples),
                minimumAvailableBytes=minimum,swapRangeBytes=span,
                limits=dict(minimumAvailableBytes=4*GIB,maximumSwapRangeBytes=64*1024**2),
                windowReset=False,researchAttemptsAuthorized=1,formalHardwareQualification=False)
    write(output/'admission.json',result)
    return result


def main(args):
    repo = args.repo.resolve()
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True) == ''
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    assert commit == os.environ['AIJADE_GIT_COMMIT']
    assert os.environ.get('DOTNET_PROCESSOR_COUNT') == '2'
    assert psutil.__version__ == '7.2.2'
    assert sha(args.manifest) == 'db660d8d3a8856e0f5fd232b131796b1c242c1e4329ea1eaa0a6b216ad488716', 'Only the frozen known-development fixture is enabled'
    assert sha(args.manifest) == sha(repo/'experiments/ch7/live-manifest-known-input-v1.json')
    assert sha(args.scoring) == sha(repo/'experiments/ch7/manifest-preparation-2026-11-12/comparison-manifest.json')
    source_freeze = json.loads((repo/'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json').read_text())
    for row in source_freeze['files']:
        assert sha(repo/row['path']) == row['sha256'], 'Previously frozen policy/source changed'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_copy = output / 'renderer-source'
    shutil.copytree(args.client, source_copy,
                    ignore=shutil.ignore_patterns('.godot', 'bin', 'obj', '__pycache__'))
    preset = repo / 'experiments/p1/external-renderer/preset'
    shutil.copytree(preset, output / 'preset')
    shutil.copy2(args.selection, output / 'selection.json')
    shutil.copy2(args.manifest, output / 'runtime-manifest.json')
    shutil.copy2(args.scoring, output / 'window-template.json')
    runtime = json.loads((output / 'runtime-manifest.json').read_text())
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
        planSha256=sha(repo / 'experiments/plans/2026-11-12-ch7-round2-persisted-act.md'),
        runtimeManifestSha256=sha(output/'runtime-manifest.json'), windowTemplateSha256=sha(output/'window-template.json'),
        binaries=binaries, rendererSources=sources, modelSha256=model_sha,
        selectionSha256=sha(output / 'selection.json'),
        benchSha256=sha(repo / 'src/Aijade.Research/SkillBench/bench-data.json'),
        liveSources={p:sha(repo/p) for p in [
            'tests/Aijade.Tests/ResearchLiveManifest.cs', 'tests/Aijade.Tests/ResearchLiveManifestTests.cs',
            'tests/Aijade.Tests/ResearchLiveManifestParserTests.cs', 'experiments/ch7/run_live_manifest_development.py',
            'experiments/ch7/audit_live_manifest.py', 'experiments/ch7/score_live_manifest.py',
            'experiments/ch7/test_live_manifest_scoring.py', 'experiments/ch7/test_live_manifest_rejections.py',
            'experiments/ch7/build_known_live_manifest.py']},
        earlierSourceFreezeSha256=sha(repo/'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json')))
    identities = json.loads((output/'input-identities.json').read_text())
    for rel in ['tests/Aijade.Tests/ResearchPersistedAct.cs', 'tests/Aijade.Tests/ResearchPersistedActTests.cs',
                'tests/Aijade.Tests/ResearchRound2RenderTests.cs', 'experiments/ch7/run_round2_render.py',
                'experiments/ch7/audit_round2_render.py', 'experiments/ch7/test_round2_render_rejections.py']:
        identities['liveSources'][rel] = sha(repo/rel)
    assembly_path = repo/'tests/Aijade.Tests/obj/Release/net10.0/Aijade.Tests.AssemblyInfo.cs'
    assembly = assembly_path.read_text()
    assert '0.1.0+' + commit in assembly, 'Build must carry the actual clean implementation commit'
    identities['assemblyInfo'] = dict(text=assembly, sha256=sha(assembly_path), embeddedGitRevision=commit)
    identities['study'] = 'known_second_round_persisted_act_delivery'
    write(output/'input-identities.json', identities)
    admission = idle_admission(output, commit)
    if not admission['admitted']:
        write(output/'receipt.json', dict(status='NOT_ADMITTED', codeCommit=commit, reason='fixed_idle_window_failed',
             completedCases=0, plannedCases=20, modelRequests=0, heldOutCases=0, formalHardwareQualification=False))
        write(output/'database-cleanup.json', [])
        print(json.dumps(dict(status='NOT_ADMITTED', admission=admission)))
        return 0
    assert binaries == {p.name:sha(p) for p in binary_files}
    env = dict(os.environ)
    env.update(DOTNET_ROOT=str(args.dotnet.parent), DOTNET_CLI_TELEMETRY_OPTOUT='1',
               PATH=str(args.dotnet.parent) + os.pathsep + env.get('PATH', ''))
    session = 'ch7-act-' + output.name
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
        flow = launch('flow', [str(args.dotnet), str(dll), '-method', METHOD +
            'Run_known_development_persisted_act_second_render', '-xml', str(output / 'flow.xml')], repo,
            dict(AIJADE_CH7_ROUND2_RENDER_OUTPUT=str(output), AIJADE_CH7_INPUT=str(output/'selection.json'), AIJADE_CH7_LIVE_CASES=str(output/'runtime-manifest.json'), AIJADE_CH7_SESSION=session))
        request = output / 'renderer-request.json'
        while not request.is_file():
            if flow.poll() is not None:
                phases['flow'].update(exitCode=flow.returncode, endedAt=utc())
                raise RuntimeError('flow_ended_before_renderer_request')
            tick()
        request_body = json.loads(request.read_text())
        assert request_body['session'] == session
        assert request_body['preparedSha256'] == sha(output / 'prepared.json')
        renderer = launch('renderer', [sys.executable, str(source_copy / 'scripts/run-native-mmd-scene.py'),
            '--headless', '--out', str(output / 'client'), '--pmx', str(args.model), '--scale', '0.1',
            '--clip', str(output / 'preset/companion-rest.vmd'), '--pose-mode', 'pmx', '--preserve-signed-linear-weights',
            '--behavior', str(output / 'preset/companion-plan.json'), '--behavior-live', str(port), '--timeout', '400'], source_copy)
        state = output / 'client/aijade-render-state.jsonl'
        context = None
        while context is None:
            if renderer.poll() is not None or flow.poll() is not None:
                raise RuntimeError('owned_process_ended_before_registration')
            if state.is_file():
                with state.open() as stream:
                    first = stream.readline()
                if first.strip():
                    context = json.loads(first).get('renderer_context_id')
            tick()
        write(output / 'renderer-ready.tmp', dict(context=context, port=port, utc=utc()))
        (output / 'renderer-ready.tmp').rename(output / 'renderer-ready.json')
        finish('renderer', renderer)
        write(output / 'renderer-closed.tmp', dict(exitCode=renderer.returncode, utc=utc(), stateSha256=sha(state)))
        (output / 'renderer-closed.tmp').rename(output / 'renderer-closed.json')
        second = output/'round2'
        second_request = second/'renderer-request.json'
        while not second_request.is_file():
            if flow.poll() is not None:
                phases['flow'].update(exitCode=flow.returncode, endedAt=utc())
                raise RuntimeError('flow_ended_before_second_renderer_request')
            tick()
        body = json.loads(second_request.read_text())
        assert body['session'] == session + '-round2'
        assert body['preparedSha256'] == sha(second/'actions-prepared.json')
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', 0))
            second_port = sock.getsockname()[1]
        renderer2 = launch('renderer-round2', [sys.executable, str(source_copy/'scripts/run-native-mmd-scene.py'),
            '--headless', '--out', str(second/'client'), '--pmx', str(args.model), '--scale', '0.1',
            '--clip', str(output/'preset/companion-rest.vmd'), '--pose-mode', 'pmx', '--preserve-signed-linear-weights',
            '--behavior', str(output/'preset/companion-plan.json'), '--behavior-live', str(second_port), '--timeout', '400'],
            source_copy, dict(MOSAIC_SESSION_ID=session+'-round2'))
        state2 = second/'client/aijade-render-state.jsonl'
        context2 = None
        while context2 is None:
            if renderer2.poll() is not None or flow.poll() is not None:
                raise RuntimeError('owned_process_ended_before_second_registration')
            if state2.is_file():
                with state2.open() as stream: first = stream.readline()
                if first.strip(): context2 = json.loads(first).get('renderer_context_id')
            tick()
        write(second/'renderer-ready.tmp', dict(context=context2, port=second_port, utc=utc()))
        (second/'renderer-ready.tmp').rename(second/'renderer-ready.json')
        finish('renderer-round2', renderer2)
        write(second/'renderer-closed.tmp', dict(exitCode=renderer2.returncode, utc=utc(), stateSha256=sha(state2)))
        (second/'renderer-closed.tmp').rename(second/'renderer-closed.json')
        finish('flow', flow)
        actions = json.loads((second/'actions.json').read_text())
        assert [(r['caseId'],r['condition']) for r in actions] == [(p['caseId'],c) for p in runtime['cases'] for c in p['conditions']]
        cases = json.loads((output / 'cases.json').read_text())
        assert len(cases) == 2 * len(runtime['cases'])
        assert [(r['caseId'], r['condition']) for r in cases] == [(p['caseId'], c) for p in runtime['cases'] for c in p['conditions']]
        assert all(r['batch'] == 'live_manifest_known_development' and 'expected' not in r and 'qualified' not in r and 'engineeringExpectationMatched' not in r for r in cases)
        assert all(c['gatewayAttempts'] == 0 for c in cases)
        assert binaries == {p.name: sha(p) for p in binary_files}
        assert sha(args.model) == model_sha
        assert all(sha(repo / relative) == expected for relative, expected in selection['sources'].items())
        assert sources == {rel: sha(source_copy / rel) for rel in sources}
        status = 'COMPLETE_LIVE_MANIFEST_KNOWN_OBSERVATIONS'
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
        cleanup = []
        leases = output / 'database-leases.jsonl'
        for line in leases.read_text().splitlines() if leases.is_file() else []:
            name = json.loads(line)['database']
            assert re.fullmatch(r'aijade_test_[0-9a-f]{32}', name)
            command = [str(Path.home()/'.local/bin/docker'), 'exec', 'aijade-next-db',
                       'psql', '-X', '-U', 'aijade', '-d', 'aijade', '-tAc']
            present = subprocess.check_output(command + ["SELECT count(*) FROM pg_database WHERE datname='" + name + "'"], text=True).strip()
            if present != '0':
                subprocess.run(command + ['DROP DATABASE ' + name + ' WITH (FORCE)'], check=True, capture_output=True)
            remaining = subprocess.check_output(command + ["SELECT count(*) FROM pg_database WHERE datname='" + name + "'"], text=True).strip()
            cleanup.append(dict(database=name, presentAfterProcessExit=int(present), remaining=int(remaining)))
        write(output/'database-cleanup.json', cleanup)
        completed = [r['caseId']+'/'+r['condition'] for r in json.loads((output/'cases.json').read_text())] if (output/'cases.json').is_file() else []
        journal = [json.loads(s) for s in (output/'journal.jsonl').read_text().splitlines()] if (output/'journal.jsonl').is_file() else []
        started_cases = {r['caseId'] for r in journal if '/' in r['caseId']}
        case_ids = [p['caseId']+'/'+c for p in runtime['cases'] for c in p['conditions']]
        write(output / 'receipt.json', dict(schema='aijade.ch7.live-manifest-development-receipt.v1', status=status, reason=reason,
            codeCommit=commit, study='known_second_round_persisted_act_delivery',
            round2Status='OBSERVATIONS_COMPLETE' if status.startswith('COMPLETE') else 'INCOMPLETE_UNKNOWN',
            round2ObservationRows=len(json.loads((output/'round2/actions.json').read_text())) if (output/'round2/actions.json').is_file() else 0,
            finishedAt=utc(), wallSeconds=time.monotonic()-started, ownedCpuSeconds=sum(cpu.values()),
            peak=peaks, phases=phases, plannedCases=2*len(runtime['cases']), plannedPairs=len(runtime['cases']), plannedSharedRenderedIntents=len(runtime['cases']),
            registeredIntentCount=max(0,len((output/'registry.jsonl').read_text().splitlines())-1) if (output/'registry.jsonl').is_file() else 0,
            completedCases=len(json.loads((output/'cases.json').read_text())) if (output/'cases.json').is_file() else 0,
            inFlightCaseIds=[k for k in case_ids if k in started_cases and k not in completed],
            unattemptedCaseIds=[k for k in case_ids if k not in started_cases],
            heldOutCases=0, conditionsMeasured=['C1','C2'], semanticJudgments='AI-assisted; no independent human review',
            formalHardwareQualification=False, modelRequests=0))
    print(json.dumps(dict(status=status, reason=reason, wallSeconds=time.monotonic()-started)))
    return 0 if status.startswith('COMPLETE') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['repo', 'client', 'model', 'selection', 'manifest', 'scoring', 'output', 'dotnet']:
        parser.add_argument('--' + key, type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
