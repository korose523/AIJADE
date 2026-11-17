#!/usr/bin/env python3
"""One resource-bounded block of the prospectively confirmed finite comparison or known-input qualification. No model calls.

Requires Python 3.11+, psutil 7.2.2, a built clean AIJADE checkout, the prepared
AIJADE-owned Godot backend, a local PMX asset and the archived program selection.
The exact prebuilt renderer tree is copied and verified without a runtime rebuild.
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
from finite_runtime import (validate_build, cleanup_owned_databases, stop_owned_processes, dispositions,
    BUILD_FREEZE_PATH, MAC_PLAN, MAC_PLANS, MAC_LIFECYCLE_SOURCES, mac_observer, mac_plan, mac_build_path, validate_mac_build_policy, validate_repository_binding, load_mac_policy, validate_mac_sample, MacMonitor, OwnedRegistry,
    setup_lifecycle, managed_check_output, finish_monitored_cleanup, seal_refused_cleanup)

GIB = 1024 ** 3
PLAN = '78785a5'
METHOD = 'Aijade.Tests.ResearchLoopQualificationTests.'


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def launch_owned_process(name, command, cwd, env, stream, registry, *, mac, v3):
    if v3:
        process = registry.launch(command, role='finite', stage=name, cwd=cwd, env=env,
                                  stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        lease = registry.register(process)
        created = lease['identity']['createTimeMicros'] / 1000000
    else:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        created = psutil.Process(process.pid).create_time() if mac else None
        if mac:registry.register(process.pid, created)
    return process, created


def finish_v3_owned_cleanup(roots, leases, docker, container, monitor, registry):
    """Attempt every owned cleanup and always stop the existing monitor once.

    The sole post-cleanup sample is its next existing scheduled tick. Failures
    remain explicit; this function never starts a replacement observation.
    """
    errors = []
    try:
        processes = stop_owned_processes(roots)
    except BaseException as error:
        errors.append('process cleanup: ' + type(error).__name__ + ': ' + str(error))
        processes = [dict(pid=p.pid, exitCode=None, errors=[errors[-1]]) for p in roots]
    try:
        databases = cleanup_owned_databases(leases, docker, container, run=registry.run)
    except BaseException as error:
        errors.append('database cleanup: ' + type(error).__name__ + ': ' + str(error))
        databases = [dict(database=None, presentAfterProcessExit=None, remaining=None, error=errors[-1])]
    try:
        refused=seal_refused_cleanup(registry,Path(leases).parent)
        if refused is not None:errors.append('finite launch refused; cleanup cannot confer acceptance')
    except BaseException as error:errors.append('refused-process cleanup: '+type(error).__name__+': '+str(error))
    if monitor is not None:
        try:
            finish_monitored_cleanup(monitor, require_terminal_sample=True)
        except BaseException as error:
            errors.append('monitor cleanup: ' + type(error).__name__ + ': ' + str(error))
    try:
        final = registry.final()
    except BaseException as error:
        errors.append('registry cleanup: ' + type(error).__name__ + ': ' + str(error))
        final = dict(status='UNKNOWN_OWNED_IDENTITY_ABSENCE', error=errors[-1])
    return processes, databases, final, errors


def _main(args):
    lifecycle = getattr(args, '_lifecycle_registry', None)
    v3 = lifecycle is not None
    repo = args.repo.resolve()
    assert managed_check_output(['git', 'status', '--porcelain'], cwd=repo, text=True) == ''
    repository_commit = managed_check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    commit = getattr(args,'implementation_commit',None) or repository_commit
    mac=args.execution_plan.name in MAC_PLANS
    assert mac or commit==repository_commit
    if mac:
        assert args.execution_plan.resolve()==repo/'experiments/plans'/args.execution_plan.name
        assert args.execution_plan.read_bytes()==managed_check_output(['git','show',commit+':experiments/plans/'+args.execution_plan.name],cwd=repo)
    assert commit == os.environ['AIJADE_GIT_COMMIT']
    assert os.environ.get('DOTNET_PROCESSOR_COUNT') == '2'
    assert psutil.__version__ == '7.2.2'
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',args.db_container)
    freeze_path=getattr(args,'build_freeze_path',BUILD_FREEZE_PATH)
    binding=validate_repository_binding(repo,commit,repository_commit,getattr(args,'data_publication_manifest',None),require_head=True) if mac else {}
    build = validate_build(args.assembly,args.build_manifest,commit,repo,args.build_freeze_commit,freeze_path,strict_publication=mac)
    policy=None;process_identity={}
    if mac:
        assert getattr(args,'process_policy',None) is not None
        policy,process_identity=load_mac_policy(repo,args.process_policy,commit)
        assert args.execution_plan.name==mac_plan(policy) and freeze_path==mac_build_path(policy)
        validate_mac_build_policy(policy,build)
        observe=mac_observer(policy).observe
    metadata=dict(binding,buildFreezeCommit=args.build_freeze_commit,buildFreezePath=freeze_path,
                  executionPlanSha256=sha(args.execution_plan),**process_identity) if mac else {}
    if mac:metadata['controllerProcess']=dict(pid=os.getpid(),createTime=psutil.Process().create_time())
    if v3:metadata.update(lifecycleJournalPath=str(lifecycle.path),lifecycleScopeId=lifecycle.scope_id)
    runtime = json.loads(args.manifest.read_text())
    contract = json.loads(args.scoring.read_text())
    assert runtime['purpose'] in ['qualification_only','confirmed_finite_heldout']
    assert runtime['protocolPlanSha256'] == sha(repo/'experiments/plans/2026-11-12-ch7-confirmed-finite-heldout.md')
    assert runtime['selectionSha256'] == sha(args.selection)
    assert contract['runtimeManifestSha256'] == sha(args.manifest)
    assert contract['purpose'] == runtime['purpose']
    if runtime['purpose'] == 'confirmed_finite_heldout':
        assert args.manifest.resolve().is_relative_to(repo)
        assert args.scoring.resolve().is_relative_to(repo)
        for path in [args.manifest,args.scoring,args.selection]:
            original = managed_check_output(['git','show',repository_commit+':'+str(path.resolve().relative_to(repo))],cwd=repo)
            assert hashlib.sha256(original).hexdigest() == sha(path), 'Uncommitted or changed finite input'
        freeze = json.loads((repo/'experiments/ch7/finite-heldout/construction-freeze.json').read_text())
        assert freeze['constructionFreezeCommit'] == runtime['constructionFreezeCommit']
        for relative, digest in freeze['sources'].items():
            assert sha(repo/relative) == digest, 'Construction-frozen source changed'
            original = managed_check_output(['git','show',runtime['constructionFreezeCommit']+':'+relative],cwd=repo)
            assert hashlib.sha256(original).hexdigest() == digest
        suitability = json.loads((args.manifest.parent.parent/'suitability-acceptance.json').read_text())
        assert suitability['status'] == 'PASS_ALL_FORTY_BEFORE_MEASUREMENT'
        if mac:
            assert commit!=repository_commit and runtime['constructionFreezeCommit']==commit
    elif mac:assert commit==repository_commit and runtime['constructionFreezeCommit']==commit
    source_freeze = json.loads((repo/'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json').read_text())
    for row in source_freeze['files']:
        assert sha(repo/row['path']) == row['sha256'], 'Previously frozen policy/source changed'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_copy = output / 'renderer-source'
    # The client was built before the fixed unloaded phase. Retain its exact loaded DLLs.
    shutil.copytree(args.client, source_copy,
                    ignore=shutil.ignore_patterns('.git', '.svn', '__pycache__'))
    prepared_client=json.loads((source_copy/'aijade-prepared-renderer.json').read_text())
    assert prepared_client['status']=='PREBUILT_NO_RUNTIME_REBUILD'
    for relative,digest in prepared_client['files'].items():
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        assert sha(source_copy/relative)==digest, 'Prepared renderer identity changed'
    preset = repo / 'experiments/p1/external-renderer/preset'
    shutil.copytree(preset, output / 'preset')
    shutil.copy2(args.selection, output / 'selection.json')
    shutil.copy2(args.manifest, output / 'runtime-manifest.json')
    shutil.copy2(args.scoring, output / 'scoring-manifest.json')
    shutil.copy2(args.build_manifest, output / 'frozen-build.json')
    if mac:shutil.copy2(args.process_policy,output/'process-policy.json')
    runtime = json.loads((output / 'runtime-manifest.json').read_text())
    selection = json.loads((output / 'selection.json').read_text())
    for relative, expected in selection['sources'].items():
        assert sha(repo / relative) == expected, relative
    dll = args.assembly.resolve()
    binary_files = [dll.parent/relative for relative in sorted(build['files'])]
    binaries = {str(p.relative_to(dll.parent)): sha(p) for p in binary_files}
    sources = {str(p.relative_to(source_copy)): sha(p) for p in source_copy.rglob('*') if p.is_file()
               and not {'.godot','bin','obj','__pycache__'} & set(p.relative_to(source_copy).parts)}
    model_sha = sha(args.model)
    write(output / 'input-identities.json', dict(
        codeCommit=commit, planCommit=managed_check_output(['git', 'rev-parse', PLAN], cwd=repo, text=True).strip(),
        planSha256=sha(repo / 'experiments/plans/2026-11-12-ch7-confirmed-finite-heldout.md'),
        runtimeManifestSha256=sha(output/'runtime-manifest.json'), scoringManifestSha256=sha(output/'scoring-manifest.json'),
        binaries=binaries, rendererSources=sources, modelSha256=model_sha,
        buildManifestSha256=sha(args.build_manifest), assemblyInformationalVersion=build['assemblyInformationalVersion'],
        buildFreezeCommit=args.build_freeze_commit,
        preparedRenderer=prepared_client, explicitAssemblyPath=str(dll),
        explicitDockerPath=str(args.docker), databaseContainer=args.db_container,
        godotWrapperSha256=sha(args.godot), realGodotSha256=sha(Path(os.environ['AIJADE_REAL_GODOT'])),
        sandboxProfileSha256=sha(Path(os.environ['AIJADE_GODOT_SANDBOX_PROFILE'])),
        executionPlanSha256=sha(args.execution_plan),
        selectionSha256=sha(output / 'selection.json'),
        benchSha256=sha(repo / 'src/Aijade.Research/SkillBench/bench-data.json'),
        liveSources={str(p.relative_to(repo)):sha(p) for p in sorted(
            list((repo/'experiments/ch7').glob('finite_*.py')) +
            [repo/'experiments/ch7/run_finite_block.py',repo/'experiments/ch7/run_finite_sequence.py'] +
            [repo/'experiments/ch7/godot_local.py'] +
            list((repo/'tests/Aijade.Tests').glob('ResearchFinite*.cs'))+
            ([repo/'experiments/ch7/mac_process_guard.py'] + ([repo/'experiments/ch7/mac_process_guard_v2.py',repo/'experiments/ch7/mac_bulk_census.c'] if mac_plan(policy)!=MAC_PLAN else []) if mac else []) +
            ([repo/relative for relative in MAC_LIFECYCLE_SOURCES] if v3 else []))},
        constructionFreezeCommit=runtime['constructionFreezeCommit'], purpose=runtime['purpose'],
        runtimeRepositoryPath=str(args.manifest.resolve().relative_to(repo)) if runtime['purpose']=='confirmed_finite_heldout' else None,
        scoringRepositoryPath=str(args.scoring.resolve().relative_to(repo)) if runtime['purpose']=='confirmed_finite_heldout' else None,
        earlierSourceFreezeSha256=sha(repo/'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'),
        **{k:v for k,v in metadata.items() if k not in ['buildFreezeCommit','executionPlanSha256']}))
    env = dict(os.environ)
    env.update(DOTNET_ROOT=str(args.dotnet.parent), DOTNET_CLI_TELEMETRY_OPTOUT='1',
               UseSharedCompilation='false', MSBUILDDISABLENODEREUSE='1', DOTNET_CLI_USE_MSBUILD_SERVER='0',
               PATH=str(args.dotnet.parent) + os.pathsep + env.get('PATH', ''))
    session = 'ch7-finite-' + output.parent.name + '-' + output.name
    env['MOSAIC_SESSION_ID'] = session
    env['AIJADE_PREBUILT_RENDERER'] = '1'
    started = time.monotonic()
    initial_swap = int(os.environ.get('AIJADE_FINITE_SWAP_BASELINE',psutil.swap_memory().used))
    sequence_epoch = float(os.environ.get('AIJADE_FINITE_EPOCH',started))
    timer_file = Path(os.environ['AIJADE_FINITE_TIMERS_FILE'])
    roots = []
    handles = []
    timers = {} if mac else (json.loads(timer_file.read_text()) if timer_file.exists() else {})
    cpu = {}
    phases = {}
    peaks = dict(rssBytes=None if mac else 0, swapIncreaseBytes=0, minAvailableBytes=psutil.virtual_memory().available)
    telemetry = None if mac else (output / 'telemetry.jsonl').open('x')
    planned = [p['input']['caseId']+'/'+c for p in runtime['cases'] for c in p['input']['conditions']]
    write(output/'receipt.json',dict(status='RUNNING',codeCommit=commit,phases={},modelRequests=0))
    reason = None
    status = 'RUNNING'
    monitor=None;owned_registry=None
    if mac:
        peaks['minAvailableBytes']=2**100
        own=[(metadata['controllerProcess']['pid'],metadata['controllerProcess']['createTime'])]
        owned_registry=lifecycle if v3 else OwnedRegistry(own)
        def sample():
            observation=(observe(policy,owned_roots=owned_registry.roots(),lifecycle=lifecycle) if v3 else
                         observe(policy,owned_roots=owned_registry.roots()))
            observation.update(process_identity)
            if not v3:owned_registry.remember(observation)
            rss=observation.get('ownedRssBytes')
            available=psutil.virtual_memory().available;swap_used=psutil.swap_memory().used
            if type(rss) is int:peaks['rssBytes']=max(peaks['rssBytes'] or 0,rss)
            peaks['swapIncreaseBytes']=max(peaks['swapIncreaseBytes'],max(0,swap_used-initial_swap))
            peaks['minAvailableBytes']=min(peaks['minAvailableBytes'],available)
            return dict(utc=utc(),elapsedSeconds=time.monotonic()-started,rssBytes=rss,availableBytes=available,
                        swapUsedBytes=swap_used,processObservation=observation,**process_identity)
        monitor=MacMonitor(output/'telemetry.jsonl',sample,
            lambda item:validate_mac_sample(item,process_identity['processPolicySha256'],process_identity['observerModuleSha256'],policy),
            sequence_epoch,initial_swap,maximum_wall=4800,local_epoch=started).start()

    def launch(name, command, cwd, extra=None):
        stream = (output / (name + '.log')).open('x')
        handles.append(stream)
        proc, created = launch_owned_process(name, command, cwd, dict(env, **(extra or {})), stream,
                                             owned_registry, mac=mac, v3=v3)
        roots.append(proc)
        phases[name] = dict(startedAt=utc(), pid=proc.pid, exitCode=None)
        if mac:phases[name]['createTime']=created
        write(output/'receipt.json',dict(status='RUNNING',codeCommit=commit,phases=phases,modelRequests=0))
        return proc

    def tick():
        now = time.monotonic()
        if mac:
            monitor.check()
            if now-sequence_epoch>4800:raise RuntimeError('overall_wall_limit_stop')
            if now-started>1200:raise RuntimeError('wall_limit_stop')
            time.sleep(.2)
            return
        self_process = psutil.Process()
        family = {(self_process.pid, self_process.create_time()): self_process}
        for root in roots:
            if root.poll() is not None:
                continue
            try:
                parent = psutil.Process(root.pid)
                for child in [parent] + parent.children(recursive=True):
                    family[(child.pid, child.create_time())] = child
            except psutil.Error as error:
                raise RuntimeError('unknown_owned_process_tree: '+type(error).__name__) from error
        rss = 0
        for key, child in family.items():
            try:
                rss += child.memory_info().rss
                t = child.cpu_times()
                cpu[key] = max(cpu.get(key, 0), t.user + t.system)
            except psutil.Error as error:
                raise RuntimeError('unknown_owned_resource_observation: '+type(error).__name__) from error
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
        write(timer_file,timers)
        if now - sequence_epoch > 4800:
            raise RuntimeError('overall_wall_limit_stop')
        if now - started > 1200:
            raise RuntimeError('wall_limit_stop')
        time.sleep(1)

    def finish(name, proc):
        while proc.poll() is None:
            tick()
        phases[name].update(exitCode=proc.returncode, endedAt=utc())
        if proc.returncode != 0:
            raise RuntimeError(name + '_nonzero_exit')

    def interrupted(signum, frame):
        raise RuntimeError('owned_controller_signal_' + str(signum))

    signal.signal(signal.SIGTERM, interrupted)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        flow = launch('flow', [str(args.dotnet), str(dll), '-method', METHOD +
            'Run_finite_manifest_dataflow', '-xml', str(output / 'flow.xml')], repo,
            dict(AIJADE_CH7_FINITE_OUTPUT=str(output), AIJADE_CH7_INPUT=str(output/'selection.json'), AIJADE_CH7_LIVE_CASES=str(output/'runtime-manifest.json'), AIJADE_CH7_SESSION=session, AIJADE_CH7_CONSTRUCTION_FREEZE=runtime['constructionFreezeCommit'], AIJADE_CH7_PLAN_SHA256=runtime['protocolPlanSha256']))
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
            '--godot',str(args.godot),'--dotnet',str(args.dotnet),
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
        finish('flow', flow)
        cases = json.loads((output / 'cases.json').read_text())
        assert len(cases) == 2 * len(runtime['cases'])
        assert [(r['caseId'], r['condition']) for r in cases] == [(p['input']['caseId'], c) for p in runtime['cases'] for c in p['input']['conditions']]
        assert all(r['batch'] == runtime['purpose'] and 'expected' not in r and 'qualified' not in r and 'engineeringExpectationMatched' not in r for r in cases)
        assert all(c['gatewayAttempts'] == 0 for c in cases)
        assert binaries == {str(p.relative_to(dll.parent)): sha(p) for p in binary_files}
        assert sha(args.model) == model_sha
        assert all(sha(repo / relative) == expected for relative, expected in selection['sources'].items())
        assert sources == {rel: sha(source_copy / rel) for rel in sources}
        assert all(sha(source_copy/rel)==digest for rel,digest in prepared_client['files'].items()), 'Renderer rebuilt or changed after admission'
        status = 'COMPLETE_FINITE_BLOCK_OBSERVATIONS'
    except BaseException as error:
        status = 'STOPPED'
        reason = type(error).__name__ + ': ' + str(error)
    finally:
        cleanup_errors=[]
        if v3:
            process_cleanup, cleanup, registry_final, cleanup_errors = finish_v3_owned_cleanup(
                roots, output/'database-leases.jsonl', args.docker, args.db_container, monitor, owned_registry)
        else:
            process_cleanup = stop_owned_processes(roots)
        for name, record in phases.items():
            owned = next(p for p in roots if p.pid==record['pid'])
            record['exitCode'] = owned.poll()
            record.setdefault('endedAt',utc())
        close_errors=[]
        for handle in handles+([telemetry] if telemetry is not None else []):
            try:handle.close()
            except OSError as error:close_errors.append(type(error).__name__+': '+str(error))
        leases = output / 'database-leases.jsonl'
        if not v3:cleanup = cleanup_owned_databases(leases,args.docker,args.db_container)
        if monitor is not None:
            if not v3:
                try:monitor.stop()
                except ValueError as error:
                    status='STOPPED';reason=(reason+'; ' if reason else '')+str(error)
                try:registry_final=owned_registry.final()
                except ValueError as error:registry_final=dict(status='UNKNOWN_OWNED_IDENTITY_ABSENCE',error=str(error))
            write(output/'owned-process-registry.json',registry_final)
            metadata['ownedProcessRegistrySha256']=sha(output/'owned-process-registry.json')
            if v3:
                if (output/'launch-refused-process-cleanup.json').is_file():metadata['refusedProcessCleanupSha256']=sha(output/'launch-refused-process-cleanup.json')
                journal=lifecycle.path.read_bytes()
                metadata.update(lifecycleJournalBytes=len(journal),lifecycleJournalSha256=hashlib.sha256(journal).hexdigest())
            if registry_final['status']!='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT':
                status='STOPPED';reason=(reason+'; ' if reason else '')+'known owned descendant remains or identity unknown'
        if cleanup_errors:
            status='STOPPED';reason=(reason+'; ' if reason else '')+'; '.join(cleanup_errors)
        if time.monotonic()-started>1200:
            status='STOPPED';reason=(reason+'; ' if reason else '')+'block wall limit including cleanup'
        write(output/'database-cleanup.json', cleanup)
        state = dispositions(output,planned,flow_started='flow' in phases)
        if any(r['remaining']!=0 or r['error'] for r in cleanup) or any(r['errors'] or r['exitCode'] is None for r in process_cleanup) or state['dispositionErrors'] or close_errors:
            status='STOPPED';reason=(reason+'; ' if reason else '')+'owned cleanup or disposition unresolved'
        write(output/'process-cleanup.json',process_cleanup)
        write(output / 'receipt.json', dict(schema='aijade.ch7.finite-block-receipt.v1', status=status, reason=reason,
            codeCommit=commit, finishedAt=utc(), wallSeconds=time.monotonic()-started, ownedCpuSeconds=None if mac else sum(cpu.values()),
            peak=peaks, phases=phases, plannedCases=2*len(runtime['cases']), plannedPairs=len(runtime['cases']), plannedSharedRenderedIntents=len(runtime['cases']),
            registeredIntentCount=max(0,len((output/'registry.jsonl').read_text().splitlines())-1) if (output/'registry.jsonl').is_file() else 0,
            completedCases=len(state['completedCaseIds']),
            inFlightCaseIds=state['inFlightCaseIds'],unknownCaseIds=state['unknownCaseIds'],
            unattemptedCaseIds=state['unattemptedCaseIds'],dispositionErrors=state['dispositionErrors'],logCloseErrors=close_errors,
            heldOutCases=len(runtime['cases']) if runtime['purpose']=='confirmed_finite_heldout' else 0, purpose=runtime['purpose'], blockIndex=runtime['blockIndex'],
            initialSystemSwapUsedBytes=initial_swap, sequenceEpochMonotonic=sequence_epoch, conditionsMeasured=['C1','C2'], semanticJudgments='AI-assisted; no independent human review',
            formalHardwareQualification=False, modelRequests=0,**dict(metadata,**({'blockEpochMonotonic':started} if mac else {}))))
    print(json.dumps(dict(status=status, reason=reason, wallSeconds=time.monotonic()-started)))
    return 0 if status.startswith('COMPLETE') else 1


def main(args):
    existed=args.output.exists()
    lifecycle=None
    try:
        if not existed:lifecycle=setup_lifecycle(args,args.output.name)
        args._lifecycle_registry=lifecycle
        return _main(args)
    except BaseException as error:
        if not existed:
            args.output.mkdir(parents=True,exist_ok=True)
            path=args.output/'receipt.json'
            try:receipt=json.loads(path.read_text())
            except (OSError,ValueError):receipt={}
            started=bool(receipt.get('phases',{}).get('flow'))
            receipt.update(status='STOPPED_CONTROLLER_ERROR' if started else 'STOPPED_PRECONDITION',reason=type(error).__name__+': '+str(error),finishedAt=utc(),
                           measurementStarted=started,modelRequests=0,phases=receipt.get('phases',{}))
            write(path,receipt)
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        return 1
    finally:
        if lifecycle is not None:
            try:
                refused=seal_refused_cleanup(lifecycle,args.output)
                if not lifecycle.closed:lifecycle.close()
                if not existed:
                    path=args.output/'receipt.json'
                    if path.is_file():
                        receipt=json.loads(path.read_text())
                        journal=lifecycle.path.read_bytes()
                        receipt.update(lifecycleJournalPath=str(lifecycle.path),lifecycleScopeId=lifecycle.scope_id,
                                       lifecycleJournalBytes=len(journal),lifecycleJournalSha256=hashlib.sha256(journal).hexdigest())
                        if refused is not None:
                            receipt['refusedProcessCleanupSha256']=sha(args.output/'launch-refused-process-cleanup.json')
                            receipt['status']='STOPPED_REFUSED_LAUNCH'
                        write(path,receipt)
                        if refused is not None:return 1
            except BaseException as error:
                if not existed:
                    args.output.mkdir(parents=True,exist_ok=True)
                    path=args.output/'receipt.json'
                    try:receipt=json.loads(path.read_text())
                    except (OSError,ValueError):receipt={}
                    detail='lifecycle finalization: '+type(error).__name__+': '+str(error)
                    receipt.update(status='STOPPED_LIFECYCLE_FINALIZATION_ERROR',
                                   reason=(receipt.get('reason')+'; ' if receipt.get('reason') else '')+detail,
                                   finishedAt=utc(),modelRequests=0,lifecycleScopeId=lifecycle.scope_id,
                                   lifecycleJournalPath=str(lifecycle.path))
                    write(path,receipt)
                print(type(error).__name__+': '+str(error),file=sys.stderr)
                return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['repo', 'client', 'model', 'selection', 'manifest', 'scoring', 'output', 'dotnet','assembly','build-manifest','godot','docker','execution-plan']:
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--db-container',required=True)
    parser.add_argument('--build-freeze-commit',required=True)
    parser.add_argument('--implementation-commit')
    parser.add_argument('--build-freeze-path',default=BUILD_FREEZE_PATH)
    parser.add_argument('--data-publication-manifest')
    parser.add_argument('--process-policy',type=Path)
    raise SystemExit(main(parser.parse_args()))
