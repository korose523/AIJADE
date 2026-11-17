#!/usr/bin/env python3
"""One passport-bound real nested engineering load; never a backend experiment.

Both sequence and block controllers run the exact new production measured
monitor. Every command is registered and actually waited by its direct owner.
The independent offline auditor, not this controller's PASS, accepts evidence.
"""
from pathlib import Path
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import time

import psutil

BASE = Path('/Volumes/Untitled/AIJADE')
SCHEMA = 'aijade.ch7.nested-load-passport.v1'
FALSE_FLAGS = ('qualificationStarted', 'backendQualified', 'scientificAdmission',
               'formalHardwareQualification', 'independentHumanReview', 'seedConstructed')
ZERO_FLAGS = ('flowBlocks', 'modelRequests', 'rendererRequests', 'freshHeldoutCases', 'automaticRetries')


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def clock():
    return time.monotonic()


def flags():
    return {**{key: False for key in FALSE_FLAGS}, **{key: 0 for key in ZERO_FLAGS}}


def strict_path(value):
    original = Path(value)
    resolved = original.resolve()
    need(original.is_absolute() and original == resolved and resolved.is_relative_to(BASE)
         and not any(p.is_symlink() for p in (original, *original.parents)), 'canonical project path required')
    return resolved


def load(passport_path):
    passport_path = strict_path(passport_path)
    raw = passport_path.read_bytes()
    p = json.loads(raw)
    need(p['schema'] == SCHEMA, 'nested passport schema')
    repo, root = strict_path(p['repo']), strict_path(p['output'])
    need(p['runnerSha256'] == sha(Path(__file__).read_bytes()), 'actual nested runner source')
    need(len(p['sourceCommit']) == 40 and all(c in '0123456789abcdef' for c in p['sourceCommit']), 'source Q')
    for name, expected in p['sourceFiles'].items():
        path = strict_path(repo / name)
        need(path.is_relative_to(repo) and sha(path.read_bytes()) == expected, 'frozen source SHA: ' + name)
    need(p['sourceFiles']['experiments/ch7/run_nested_load.py'] == p['runnerSha256'], 'runner in source closure')
    need(sys.executable == p['pythonPath'] and sha(Path(sys.executable).resolve().read_bytes()) == p['pythonSha256'],
         'actual source-bound interpreter')
    need(psutil.__version__ == '7.2.2' and os.environ.get('DOTNET_PROCESSOR_COUNT') == '2', 'fixed runtime/processor identity')
    runtime = p['runtime']
    need(runtime['blocks'] == 4 and runtime['blockWorkSeconds'] == 120
         and runtime['betweenBlockSeconds'] == 4 and runtime['parentTailSeconds'] == 4,
         'fixed full nested topology')
    need(runtime['alignmentModes'] == ['natural','parent-next-slot','natural','parent-next-slot'],
         'fixed natural/adversarial alignment population')
    need(runtime['parentMaximumSeconds'] == 600 and runtime['childStartupMaximumSeconds'] == 15
         and runtime['childCleanupMaximumSeconds'] == 8 and runtime['childWatchdogSeconds'] == 145,
         'fixed engineering wall/cleanup bounds')
    need(type(p['prefixPaddingTaskCount']) is int and p['prefixPaddingTaskCount'] == 2500,
         'fixed bounded real prefix task population')
    need(p['prefixPreparationMaximumSeconds'] == 900, 'fixed source/prefix preparation deadline')
    need(type(p['journalAcceptanceMaximumBytes']) is int
         and 0 < p['journalAcceptanceMaximumBytes'] <= 16*1024**2 - 512*1024,
         'prefix envelope must retain >=512KiB cleanup reserve inside unchanged 16MiB hard ceiling')
    need(p['minimumDemonstratedPrefixBytes'] == 14*1024**2, 'fixed minimum observed long-prefix envelope')
    need(len(p['preflightCommands']) == 30, 'thirty exact source-proof commands per controller')
    sys.path.insert(0, str(repo/'experiments/ch7'))
    import mac_process_guard_v3 as guard
    import process_lifecycle as life
    from finite_runtime import validate_mac_sample, finish_monitored_cleanup, seal_refused_cleanup
    from measured_mac_monitor import MeasuredMacMonitor
    policy_raw = (repo/p['policyPath']).read_bytes()
    need(sha(policy_raw) == p['policySha256'], 'frozen policy bytes')
    policy = json.loads(policy_raw)
    guard.validate_policy(policy)
    need(policy.get('coordinationMode') == 'segmented-census-mutation-v1'
         and policy.get('coordinationSchema') == 'aijade.mac.segmented-census-mutation.v1',
         'new explicit segmented protocol required')
    need(policy.get('onlineReplayMode')=='full-state-c-clone-exact-prefix-v1'
         and policy.get('onlineReplayInitializationMode')=='paired-source-verified-journal-prefix-v1',
         'new explicitly prepared C-clone cursor protocol required')
    need(sha(Path(policy['nativeHelper']['path']).read_bytes()) == policy['nativeHelper']['sha256'], 'native helper bytes')
    ident = dict(processPolicyPath=p['policyPath'], processPolicySha256=sha(policy_raw),
                 observerModuleSha256=sha(Path(guard.__file__).read_bytes()), observerSources=p['observerSources'])
    return p, raw, repo, root, policy, policy_raw, ident, guard, life, validate_mac_sample, finish_monitored_cleanup, MeasuredMacMonitor, seal_refused_cleanup


def commands(registry, passport, repo, count, *, padding=False, records=None, deadline=None):
    result = [] if records is None else records
    for index in range(count):
        need(deadline is None or clock() < deadline, 'fixed source/prefix preparation deadline exhausted')
        expected = passport['preflightCommands'][index % 30]
        command = ['git', *[arg.replace('{SOURCE}', passport['sourceCommit']) for arg in expected['arguments']]]
        start = clock()
        record = dict(index=index, padding=padding, command=command, startedMonotonic=start, status='STARTED')
        result.append(record)
        try:
            child = registry.run(command, cwd=repo, capture_output=True, timeout=10, check=True)
            record.update(completedMonotonic=clock(), stdoutSha256=sha(child.stdout), exitCode=child.returncode)
            need(record['stdoutSha256'] == expected['stdoutSha256'], 'actual source-bound Git stdout differs')
            need(deadline is None or clock() <= deadline, 'source/prefix command exceeded fixed preparation deadline')
            record['status'] = 'COMPLETE'
        except BaseException as error:
            record.update(status='REFUSED', completedMonotonic=clock(), error=type(error).__name__+': '+str(error))
            raise
    return result


def callbacks(registry, guard, life, policy, ident, validator, preparation_path):
    from finite_runtime import online_lifecycle_cursors, lifecycle_cursor_initialization
    inner_options,outer_options=online_lifecycle_cursors(policy,lifecycle=registry,preparation_path=preparation_path)
    inner,outer=inner_options['lifecycle_cursor'],outer_options['lifecycle_cursor']
    authenticator=inner_options.get('binary_authenticator')
    initialization=lifecycle_cursor_initialization(inner_options)
    def observed(owned=True):
        process = guard.observe(policy, owned_roots=registry.roots() if owned else [], lifecycle=registry,
                                lifecycle_cursor=inner, binary_authenticator=authenticator)
        process.update(ident)
        return dict(utc=datetime.now(timezone.utc).isoformat(), availableBytes=psutil.virtual_memory().available,
                    swapUsedBytes=psutil.swap_memory().used, rssBytes=process.get('ownedRssBytes'),
                    processObservation=process, **ident)
    def validate(item):
        validator(item, ident['processPolicySha256'], ident['observerModuleSha256'], policy, lifecycle_cursor=outer)
    return observed, validate, inner, outer, authenticator, initialization


def wait_until(deadline, monitor):
    while clock() < deadline:
        monitor.check()
        time.sleep(min(.05, max(0, deadline-clock())))
    monitor.check()


def parent_identity():
    p = psutil.Process()
    return dict(pid=p.pid, createTime=p.create_time(), parentPid=p.ppid())


def child(passport_path, index):
    python_entry = clock()
    loaded = load(passport_path)
    p, raw, repo, root, policy, policy_raw, ident, guard, life, validator, finish, Monitor, seal_refused = loaded
    need(type(index) is int and 0 <= index < 4, 'block index')
    block = root/('block-'+str(index+1))
    block.mkdir()
    registry = life.from_environment()
    need(registry is not None and registry.source_commit == p['sourceCommit']
         and registry.policy_sha256 == p['policySha256'] and registry.parent_lease_id is not None,
         'actual inherited source-bound parent lease required')
    registry.activate()
    parent_lease = registry._lease(registry.parent_lease_id)
    started = parent_lease['releaseMonotonic']
    need(type(started) in (int,float) and started <= python_entry, 'actual parent release/startup anchor')
    errors, monitor, final = [], None, None
    proof = []
    cleanup_anchor = None
    ready_started = ready_completed = None
    alignment = None
    observed=validate=inner=outer=authenticator=None
    initialization={}
    def interrupted(signum, frame):
        raise RuntimeError('owned_engineering_child_signal_'+str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    try:
        commands(registry, p, repo, 30, records=proof, deadline=started+p['runtime']['childStartupMaximumSeconds'])
        observed,validate,inner,outer,authenticator,initialization=callbacks(registry,guard,life,policy,ident,validator,block/'initialization.json')
        need(clock()-started <= p['runtime']['childStartupMaximumSeconds'], 'actual child source startup exceeded fixed bound')
        epoch = float(os.environ['AIJADE_NESTED_EPOCH'])
        baseline = int(os.environ['AIJADE_NESTED_SWAP_BASELINE'])
        parent_origin = float(os.environ['AIJADE_NESTED_PARENT_ORIGIN'])
        wait_began = clock()
        mode = p['runtime']['alignmentModes'][index]
        target = (parent_origin+2*(math.floor((wait_began-parent_origin)/2)+1)
                  if mode == 'parent-next-slot' else None)
        if target is not None:
            while clock() < target:
                need(clock() < started+p['runtime']['childStartupMaximumSeconds'],
                     'alignment wait exceeded actual startup bound')
                time.sleep(min(.001,max(0,target-clock())))
        alignment = dict(mode=mode,parentMonitorOriginMonotonic=parent_origin,
            plannedAlignTargetMonotonic=target,waitStartedMonotonic=wait_began,waitCompletedMonotonic=clock())
        monitor = Monitor(block/'telemetry.jsonl', observed, validate, epoch, baseline,
            block/'resource-timers.json', maximum_wall=600, local_epoch=started,
            diagnostic_path=block/'service-events.jsonl', maximum_service_seconds=2).start()
        origin_deadline = clock()+1
        while monitor.schedule_origin is None:
            need(clock() <= origin_deadline, 'actual child monitor thread did not enter')
            time.sleep(.001)
        ready_started = clock()
        write(block/'ready.json', dict(schema='aijade.ch7.nested-child-ready.v1', blockIndex=index,
            controllerProcess=parent_identity(), lifecycleScopeId=registry.scope_id,
            parentLeaseId=registry.parent_lease_id, monitorOriginMonotonic=monitor.schedule_origin,
            sourceStartupStartedMonotonic=started, pythonEntryMonotonic=python_entry,
            readyWriteStartedMonotonic=ready_started, engineeringAlignment=alignment,
            sourceCommit=p['sourceCommit']))
        ready_completed = clock()
        need(ready_completed-started <= p['runtime']['childStartupMaximumSeconds'],
             'actual parent-release to ready-file flush exceeded child startup bound')
        wait_until(monitor.schedule_origin+p['runtime']['blockWorkSeconds'], monitor)
        cleanup_anchor = clock()
        finish(monitor, require_terminal_sample=True)
        if index == 3:
            need(monitor.samples[-1]['processObservation']['lifecycle']['journalBytes'] >= p['minimumDemonstratedPrefixBytes'],
                 'last block actual observed prefix did not demonstrate frozen minimum')
        need(clock()-cleanup_anchor <= p['runtime']['childCleanupMaximumSeconds'], 'actual child cleanup exceeded fixed bound')
        monitor = None
    except BaseException as error:
        errors.append(type(error).__name__+': '+str(error))
    finally:
        try:
            if seal_refused(registry, block) is not None:
                errors.append('finite launch refused; cleanup cannot confer engineering acceptance')
        except BaseException as error:
            errors.append('refused-process cleanup '+type(error).__name__+': '+str(error))
        if monitor is not None:
            try:
                monitor.stop()
            except BaseException as error:
                errors.append('monitor cleanup '+type(error).__name__+': '+str(error))
        try:
            need(monitor is None or not monitor.thread.is_alive(), 'UNKNOWN_MONITOR_THREAD: journal not terminal')
            final = registry.final()
            need(final['status'] == 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' and final['scopeClosed'] is True
                 and all(final[k] == [] for k in ('unresolvedFiniteLeases','launchRefusals','launchRefusalArtifacts',
                                               'unleasedDiscoveredIdentities','remainingIdentities')),
                 'actual child lifecycle remains adverse')
        except BaseException as error:
            errors.append('registry cleanup '+type(error).__name__+': '+str(error))
        receipt = dict(schema='aijade.ch7.nested-load-child.v1', blockIndex=index,
            status='NESTED_CHILD_COMPLETE' if not errors else 'NESTED_CHILD_REFUSED',
            sourceCommit=p['sourceCommit'], passportSha256=sha(raw), controllerProcess=parent_identity(),
            scopeId=registry.scope_id, parentLeaseId=registry.parent_lease_id,
            startedMonotonic=started, pythonEntryMonotonic=python_entry,
            readyWriteStartedMonotonic=ready_started, readyWriteCompletedMonotonic=ready_completed,
            readyFileSha256=sha((block/'ready.json').read_bytes()) if (block/'ready.json').exists() else None,
            engineeringAlignment=alignment,
            cleanupStartedMonotonic=cleanup_anchor, completedMonotonic=clock(),
            preflightCommands=proof, registryFinal=final, errors=errors,
            lifecycleJournalStable=monitor is None or not monitor.thread.is_alive(),
            innerCursor=inner.statistics() if inner is not None else None, outerCursor=outer.statistics() if outer is not None else None,
            binaryAuthenticationWork=authenticator.statistics() if authenticator is not None else None, **initialization, **flags())
        write(block/'receipt.json', receipt)
    need(not errors, 'real nested child refused; no replacement')


def main(passport_path):
    loaded = load(passport_path)
    p, raw, repo, root, policy, policy_raw, ident, guard, life, validator, finish, Monitor, seal_refused = loaded
    preparation_epoch=float(os.environ['AIJADE_NESTED_PREPARATION_EPOCH'])
    need(math.isfinite(preparation_epoch) and 0<=preparation_epoch<=clock(),
         'actual external parent preparation epoch required')
    need(not root.exists(), 'never overwrite one engineering attempt')
    root.mkdir(parents=True)
    for name in ('settling','admission'):
        (root/name).mkdir()
    (root/'engineering-passport.json').write_bytes(raw)
    (root/'process-policy.json').write_bytes(policy_raw)
    controller = parent_identity()
    registry = life.Registry(root/'lifecycle-journal.jsonl', [(controller['pid'],controller['createTime'])],
        stage='nested-load-sequence', source_commit=p['sourceCommit'], policy_sha256=p['policySha256'],
        capture_lock_path=guard.coordination_lock_path(policy)).activate()
    observed=validate=inner=outer=authenticator=None
    initialization={}
    errors, proofs, padding, blocks, preflight_services = [], [], [], [], []
    monitor, active, final, preflight, epoch, baseline = None, None, None, None, None, None
    phases = []
    block_waits = []
    origin = None
    def event(name, **fields):
        item = dict(schema='aijade.ch7.nested-load-stage-event.v1', event=name, monotonicSeconds=clock(), **fields)
        phases.append(item)
        with (root/'stage-events.jsonl').open('a') as stream:
            stream.write(json.dumps(item, allow_nan=False)+'\n');stream.flush()
        return item['monotonicSeconds']
    def interrupted(signum, frame):
        raise RuntimeError('owned_engineering_parent_signal_'+str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    try:
        preparing = event('source-prefix-preparation-enter', observationsActive=False,
                          externalPreparationEpochMonotonic=preparation_epoch)
        preparation_deadline = preparation_epoch+p['prefixPreparationMaximumSeconds']
        commands(registry, p, repo, 30, records=proofs, deadline=preparation_deadline)
        commands(registry, p, repo, p['prefixPaddingTaskCount'], padding=True, records=padding, deadline=preparation_deadline)
        observed,validate,inner,outer,authenticator,initialization=callbacks(registry,guard,life,policy,ident,validator,root/'initialization.json')
        need(clock()<=preparation_deadline, 'actual cursor initialization exceeded fixed source/prefix preparation deadline')
        event('prefix-preload-complete', actualTasks=len(padding), journalBytes=registry.path.stat().st_size)
        from phase_continuity import run_preflight, PreflightRefused
        rows = {}
        with ExitStack() as stack:
            streams = {name:stack.enter_context((root/name/'telemetry.jsonl').open('x')) for name in ('settling','admission')}
            phase_stream = stack.enter_context((root/'phase-events.jsonl').open('x'))
            service_stream = stack.enter_context((root/'preflight-service-events.jsonl').open('x'))
            def writer(name):
                def save(item):
                    rows[item['sampleId']] = item
                    streams[name].write(json.dumps(item, allow_nan=False)+'\n');streams[name].flush()
                return save
            def phase_event(item):
                nonlocal origin
                if item['event'] == 'phase-enter' and item['phase'] == 'settling':
                    origin = item['monotonicSeconds']
                phase_stream.write(json.dumps(item, allow_nan=False)+'\n');phase_stream.flush()
                if item['event'] == 'sample-written':
                    r = rows.pop(item['sampleId'])
                    provisional = dict(sampleId=r['sampleId'], globalIndex=r['globalIndex'], phase=r['phase'],
                        scheduledMonotonic=origin+2*r['globalIndex'], actualStartMonotonic=r['monotonicSeconds'],
                        phaseEventWriteCompletedMonotonic=clock())
                    service_stream.write(json.dumps(provisional, allow_nan=False)+'\n');service_stream.flush()
                    provisional['diagnosticWriteCompletedMonotonic'] = clock()
                    preflight_services.append(provisional)
            def completed(item, done):
                last = preflight_services[-1]
                need(last['sampleId'] == item['sampleId'], 'full preflight service identity')
                last.update(serviceCompletedMonotonic=done, fullServiceSeconds=done-item['monotonicSeconds'])
                target = origin+2*item['globalIndex']
                deadline = origin+(600 if item['globalIndex'] < 300 else 720)
                need(0 <= item['monotonicSeconds']-target <= .5 and done-item['monotonicSeconds'] <= 2
                     and done <= deadline, 'complete preflight service/lateness/fixed phase exceeded')
            try:
                preflight = run_preflight(lambda:observed(False), validate,
                    {name:writer(name) for name in streams}, event_writer=phase_event,
                    settling_seconds=600, service_observer=completed)
            except PreflightRefused as error:
                preflight = error.result
                raise
        need(preflight['status'] == 'PREFLIGHT_COMPLETE_ADMITTED' and len(preflight_services) == 360,
             'full original preflight refused')
        epoch, baseline = clock(), psutil.swap_memory().used
        event('nested-runtime-enter', sequenceEpochMonotonic=epoch)
        monitor = Monitor(root/'process-observations.jsonl', observed, validate, epoch, baseline,
            root/'resource-timers.json', maximum_wall=p['runtime']['parentMaximumSeconds'],
            previous_sample_monotonic=preflight['runtimeHandoffAnchor']['lastSampleMonotonic'],
            diagnostic_path=root/'service-events.jsonl', maximum_service_seconds=2).start()
        origin_deadline=clock()+1
        while monitor.schedule_origin is None:
            need(clock()<=origin_deadline,'actual parent monitor thread did not enter')
            time.sleep(.001)
        env = dict(os.environ, AIJADE_NESTED_EPOCH=str(epoch), AIJADE_NESTED_SWAP_BASELINE=str(baseline),
                   AIJADE_NESTED_PARENT_ORIGIN=str(monitor.schedule_origin))
        for index in range(4):
            need(clock()-epoch < p['runtime']['parentMaximumSeconds'], 'parent fixed runtime wall exhausted')
            event('block-launch-enter', blockIndex=index)
            command = [sys.executable, '-B', str(Path(__file__)), '--passport', str(passport_path), '--child-index', str(index)]
            block_started = clock()
            with (root/('block-'+str(index+1)+'-controller.log')).open('x') as log:
                active = registry.launch(command, role='finite', stage='nested-block-'+str(index+1),
                    cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                while active.poll() is None:
                    monitor.check()
                    need(clock()-block_started <= p['runtime']['childWatchdogSeconds'], 'real child fixed watchdog exceeded')
                    need(clock()-epoch < p['runtime']['parentMaximumSeconds'], 'parent fixed runtime deadline exceeded')
                    time.sleep(.05)
                active.wait(timeout=1.25)
                wait_returned = clock()
                waited_lease = registry._lease(active.lease_id)
            block = json.loads((root/('block-'+str(index+1))/'receipt.json').read_bytes())
            blocks.append(block)
            need(active.returncode == 0 and block['status'] == 'NESTED_CHILD_COMPLETE', 'real child refused; no later block/retry')
            need(waited_lease['reapedMonotonic'] >= block['cleanupStartedMonotonic']
                 and waited_lease['reapedMonotonic']-block['cleanupStartedMonotonic'] <= p['runtime']['childCleanupMaximumSeconds'],
                 'child cleanup budget must include final receipt, process exit and actual parent wait')
            block_waits.append(dict(blockIndex=index, leaseId=active.lease_id,
                identity=waited_lease['identity'], parentIdentity=waited_lease['parentIdentity'],
                reapedMonotonic=waited_lease['reapedMonotonic'], waitReturnedMonotonic=wait_returned))
            active = None
            event('block-parent-wait-complete', blockIndex=index, exitCode=0)
            monitor.check()
            need(registry.path.stat().st_size <= p['journalAcceptanceMaximumBytes'], 'accepted measured prefix envelope exceeded')
            if index < 3:
                start_gap = event('between-block-enter', blockIndex=index)
                wait_until(start_gap+p['runtime']['betweenBlockSeconds'], monitor)
                event('between-block-exit', blockIndex=index)
        start_tail = event('parent-cleanup-tail-enter')
        wait_until(start_tail+p['runtime']['parentTailSeconds'], monitor)
        finish(monitor, require_terminal_sample=True)
        need(monitor.samples[-1]['processObservation']['lifecycle']['journalBytes'] >= p['minimumDemonstratedPrefixBytes'],
             'last parent actual observed prefix did not demonstrate frozen minimum')
        monitor = None
        event('parent-monitor-joined')
        need(clock()-epoch <= p['runtime']['parentMaximumSeconds'], 'complete parent runtime exceeded frozen bound')
    except BaseException as error:
        errors.append(type(error).__name__+': '+str(error))
    finally:
        if active is not None and active.poll() is None:
            errors.append('active child requires adverse bounded cleanup')
            try:
                lease = registry.register(active)
                expected = lease['identity']
                actual = life.identity(active.pid)
                need(actual == expected, 'unknown active child identity; signal forbidden')
                active.send_signal(signal.SIGTERM)
                try:
                    active.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    need(life.identity(active.pid) == expected, 'unknown child identity before kill; signal forbidden')
                    active.kill();active.wait(timeout=5)
            except BaseException as error:
                errors.append('owned child cleanup '+type(error).__name__+': '+str(error))
        try:
            if seal_refused(registry, root) is not None:
                errors.append('finite launch refused; cleanup cannot confer engineering acceptance')
        except BaseException as error:
            errors.append('refused-process cleanup '+type(error).__name__+': '+str(error))
        if monitor is not None:
            try:
                monitor.stop()
            except BaseException as error:
                errors.append('parent monitor cleanup '+type(error).__name__+': '+str(error))
        try:
            need(monitor is None or not monitor.thread.is_alive(), 'UNKNOWN_MONITOR_THREAD: journal not terminal')
            final = registry.final()
            need(final['status'] == 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' and final['scopeClosed'] is True
                 and all(final[k] == [] for k in ('unresolvedFiniteLeases','launchRefusals','launchRefusalArtifacts',
                                               'unleasedDiscoveredIdentities','remainingIdentities')),
                 'actual parent lifecycle remains adverse')
        except BaseException as error:
            errors.append('parent registry cleanup '+type(error).__name__+': '+str(error))
        journal = registry.path.read_bytes()
        if len(journal) > p['journalAcceptanceMaximumBytes']:
            errors.append('complete terminal journal exceeded frozen engineering prefix envelope')
        if len(journal) < p['minimumDemonstratedPrefixBytes']:
            errors.append('complete terminal journal did not reach frozen minimum prefix envelope')
        if preflight is not None:
            write(root/'preflight-continuity.json', preflight)
        receipt = dict(schema='aijade.ch7.nested-load-result.v1',
            status='ENGINEERING_REAL_NESTED_LOAD_PASS_PENDING_INDEPENDENT_AUDIT' if not errors else 'ENGINEERING_REAL_NESTED_LOAD_REFUSED',
            checkedAt=datetime.now(timezone.utc).isoformat(), sourceCommit=p['sourceCommit'],
            passportSha256=sha(raw), runnerSha256=sha(Path(__file__).read_bytes()), sourceFiles=p['sourceFiles'],
            preparationEpochMonotonic=preparation_epoch,
            policySha256=p['policySha256'], controllerProcess=controller, controllerSysExecutable=sys.executable,
            preflightCommands=proofs, prefixPaddingCommands=padding, preflightServices=preflight_services,
            originalPreflightObservations=len(preflight_services), nestedBlocks=blocks,
            blockWaits=block_waits,
            nestedEpochMonotonic=epoch, nestedInitialSwapUsedBytes=baseline,
            nestedTerminalMonotonic=clock(), stageEvents=phases,
            lifecycleJournalPath=str(registry.path), lifecycleJournalSha256=sha(journal), lifecycleJournalBytes=len(journal),
            registryFinal=final, errors=errors, lifecycleJournalStable=monitor is None or not monitor.thread.is_alive(),
            innerCursor=inner.statistics() if inner is not None else None, outerCursor=outer.statistics() if outer is not None else None,
            binaryAuthenticationWork=authenticator.statistics() if authenticator is not None else None, **initialization, **flags())
        write(root/'receipt.json', receipt)
        print(json.dumps({k:v for k,v in receipt.items() if k not in ('sourceFiles','preflightCommands','prefixPaddingCommands',
              'preflightServices','nestedBlocks','stageEvents','registryFinal')}, allow_nan=False), flush=True)
    need(not errors, 'complete real nested engineering workload refused; retain and stop')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--passport', type=Path, required=True)
    parser.add_argument('--child-index', type=int)
    args = parser.parse_args()
    if args.child_index is not None:
        child(args.passport, args.child_index)
    else:
        main(args.passport)
