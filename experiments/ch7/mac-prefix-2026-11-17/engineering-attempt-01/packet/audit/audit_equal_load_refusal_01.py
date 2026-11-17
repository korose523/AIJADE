#!/usr/bin/env python3
"""Cold read-only replay of engineering-01's preserved service-budget refusal.

This does not call the complete-362 acceptance entry point. No observation,
native helper, API, model, renderer, new window or source mutation is invoked.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

BASE = Path('/Volumes/Untitled/AIJADE')
C4 = BASE / '.research/runs/ch7-prefix-20261117'
SOURCE = 'b5af85f7a1b5f1da3ceeda0a9c1a64393a0e3efb'
FREEZE = 'bb2c25b808c1c3f604e081b5fa4da4d4f76af84d'
PASSPORT_SHA = '5755e4942768002eed52762a432c947bc6279ac945fcc8d7f9d0bb579da939e2'
ACCEPTANCE_TOOL_SHA = '049b347a3a6265cb6f9a096c6c5db633934b4863bf78d4d9a81c777e36aeec64'
FREEZE_PREFIX = 'experiments/ch7/mac-prefix-2026-11-17/engineering-freeze/'


def load_helpers():
    path = Path(__file__).with_name('audit_equal_load.py')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == ACCEPTANCE_TOOL_SHA,
            'never change the pre-window acceptance tool to accept a refusal')
    spec = importlib.util.spec_from_file_location('equal_load_frozen_helpers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(value, message):
    if not value:
        raise ValueError(message)


def run(args):
    h = load_helpers()
    root = args.root.resolve()
    repo = args.repo.resolve()
    output = args.output.resolve()
    require(not output.exists() and root not in output.parents, 'never overwrite an earlier artifact')
    initial = h.read(args.snapshot)
    before = h.file_table(root)
    require(h.typed_equal(before, initial['inputFiles']), 'initial original-file SHA snapshot differs')
    passport_raw = args.passport.read_bytes()
    passport = h.decode(passport_raw)
    receipt = h.read(root / 'receipt.json')
    publication = h.read(args.publication)
    launch_raw = args.launch.read_bytes()
    launch = h.decode(launch_raw)
    terminal = h.read(args.parent_terminal)
    require(h.sha(passport_raw) == PASSPORT_SHA
            and (root / 'engineering-passport.json').read_bytes() == passport_raw, 'executed exact passport bytes')
    require(passport['schema'] == 'aijade.ch7.equal-load-passport.v1'
            and passport['purpose'] == 'ENGINEERING_ONLY_NOT_QUALIFICATION'
            and passport['sourceCommit'] == SOURCE, 'engineering passport identity/purpose')
    require(publication['sourceCommit'] == SOURCE and publication['engineeringFreezeCommit'] == FREEZE
            and publication['passportSha256'] == PASSPORT_SHA, 'pre-window freeze identity')
    frozen = {}
    for row in publication['files']:
        relative = h.relative(row['path']).as_posix()
        require(relative not in frozen, 'duplicate frozen publication path')
        raw = h.git(repo, 'show', FREEZE + ':' + relative)
        require(h.sha(raw) == row['sha256'] and type(row['bytes']) is int and len(raw) == row['bytes'],
                'immutable freeze Git blob differs: ' + relative)
        frozen[relative] = row
    require(frozen[FREEZE_PREFIX + 'engineering-passport.json']['sha256'] == PASSPORT_SHA
            and frozen[FREEZE_PREFIX + 'audit_equal_load.py']['sha256'] == ACCEPTANCE_TOOL_SHA
            and frozen[FREEZE_PREFIX + 'launch_equal_load.py']['sha256'] == passport['launcherSha256'],
            'freeze passport/auditor/launcher closure')
    require(datetime.fromisoformat(publication['at']) <= datetime.fromisoformat(launch['startedAt']),
            'recorded freeze publication is not before fixed launch')
    require(receipt['schema'] == 'aijade.ch7.equal-load-result.v1'
            and receipt['status'] == 'ENGINEERING_EQUAL_LOAD_REFUSED'
            and receipt['sourceCommit'] == SOURCE and receipt['passportSha256'] == PASSPORT_SHA,
            'original adverse engineering receipt')
    require(receipt['lifecycleJournalStable'] is True and receipt['tailThreadJoined'] is False
            and receipt['tailPhaseEnteredMonotonic'] is None and receipt['tailThreadJoinedMonotonic'] is None,
            'unstarted tail must not be called joined or measured')
    require(receipt['tailObservations'] == 0 and type(receipt['tailObservations']) is int, 'no tail observations')
    require(receipt['runnerSha256'] == passport['runnerSha256']
            and receipt['policySha256'] == passport['policySha256']
            and h.typed_equal(receipt['sourceFiles'], passport['sourceFiles']), 'receipt/source binding')
    require(len(passport['sourceFiles']) == 28 and len(passport['observerSources']) == 14
            and all(passport['sourceFiles'][key] == value for key, value in passport['observerSources'].items()),
            'source28/observer14 population')
    policy_raw = (root / 'process-policy.json').read_bytes()
    policy = h.decode(policy_raw)
    context = dict(sourceCommit=SOURCE, sourceFiles=passport['sourceFiles'], observerSources=passport['observerSources'],
        processPolicySha256=passport['policySha256'], processPolicyPath=passport['policyPath'],
        runScriptPath='experiments/ch7/run_equal_load.py', runScriptSha256=passport['runnerSha256'])
    sources = h.verify_sources(repo, context, policy_raw)
    for key in ('plan', 'protocol'):
        raw = h.git(repo, 'show', SOURCE + ':' + passport[key + 'Path'])
        require(h.sha(raw) == passport[key + 'Sha256'], 'actual frozen engineering ' + key)
    protocol = h.decode(h.git(repo, 'show', SOURCE + ':' + passport['protocolPath']))
    require(set(before) == set(protocol['files']), 'complete original run file closure')
    require(protocol['population'] == dict(settling=300, admissionLike=60, tail=2, total=362,
        native=724, listener=724, apiReads=362, onlineDecisions=724, preflightGit=30, finite=1478),
        'original planned engineering population changed')
    require(receipt['controllerSysExecutable'] == passport['pythonPath']
            and h.file_sha(Path(passport['pythonPath'])) == passport['pythonSha256'], 'actual controller interpreter')
    require(h.file_sha(BASE / '.runtime/run-local.sh') == passport['runtimeWrapperSha256']
            and h.file_sha(C4 / 'launch_equal_load.py') == passport['launcherSha256'], 'actual frozen launcher/wrapper')
    native_path = Path(policy['nativeHelper']['path'])
    native_before = h.file_sha(native_path)
    require(native_before == policy['nativeHelper']['sha256'] == protocol['nativePreparation']['sha256']
            and policy['nativeHelper']['sourceSha256'] == protocol['nativePreparation']['sourceSha256'],
            'actual prepared native binary/source bytes')

    journal = (root / 'lifecycle-journal.jsonl').read_bytes()
    require(h.sha(journal) == receipt['lifecycleJournalSha256']
            and type(receipt['lifecycleJournalBytes']) is int and len(journal) == receipt['lifecycleJournalBytes'],
            'exact complete terminal journal bytes')
    rows = h.jsonl(root / 'settling/telemetry.jsonl')
    admission = h.jsonl(root / 'admission/telemetry.jsonl')
    tail = h.jsonl(root / 'tail/telemetry.jsonl')
    tail_events = h.jsonl(root / 'tail/events.jsonl')
    events = h.jsonl(root / 'phase-events.jsonl')
    service_events = h.jsonl(root / 'service-events.jsonl')
    complete_services = receipt['services']
    preflight = h.read(root / 'preflight-continuity.json')
    require(rows and len(rows) < 300 and not admission and not tail and not tail_events, 'actual stopped/unstarted populations')
    require(type(receipt['observations']) is int and receipt['observations'] == len(rows)
            and len(service_events) == len(complete_services) == len(rows), 'actual raw/service population')
    sys.path.insert(0, str(repo / 'experiments/ch7'))
    import lifecycle_audit as audit
    import mac_process_guard_v3 as guard
    require(h.file_sha(Path(audit.__file__)) == h.FULL_AUDITOR_SHA256, 'independent full parser changed')
    require(h.file_sha(Path(guard.__file__)) == passport['sourceFiles']['experiments/ch7/mac_process_guard_v3.py'],
            'loaded frozen guard changed')
    # Reuse only the pre-window tool's per-original-row cold predicates, never
    # its main/load_protocol/complete362 acceptance or any claimed PASS.
    state, raw_replay = h.full_raw_replay(root, repo, context, policy, journal, rows, audit, guard)
    finite = [value for value in state['leases'].values() if value['role'] == 'finite']
    final = receipt['registryFinal']
    require(final['status'] == 'ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' and final['scopeClosed'] is True
            and all(final[key] == [] for key in ('unresolvedFiniteLeases', 'launchRefusals', 'launchRefusalArtifacts',
                'localDiscoveredIdentities', 'unleasedDiscoveredIdentities', 'remainingIdentities'))
            and h.typed_equal(final['knownFiniteLeases'], finite), 'terminal lifecycle source population differs')
    final_view = final['lifecycleView']
    require(type(final_view['journalBytes']) is int and final_view['journalBytes'] == len(journal)
            and type(final_view['lastSequence']) is int and final_view['lastSequence'] == len(state['events'])
            and final_view['journalSha256'] == h.sha(journal) and final_view['runId'] == state['runId'],
            'terminal scope/prefix differs')
    context.update(controllerProcess=receipt['controllerProcess'], controllerExecutableSha256=passport['pythonSha256'],
                   lifecycleScopeId=final['scopeId'])
    controller = h.verify_controller_identity(state, context, final_view)
    require(len(state['scopes']) == 1 and state['scopes'][final['scopeId']]['closeSeq'] is not None,
            'actual local controller scope not closed')

    # Exact native/listener argv/executable and all30 actual source-proof tasks.
    import ast
    tree = ast.parse((repo / 'experiments/ch7/mac_process_guard_v3.py').read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_read_listeners')
    listener_commands = [ast.literal_eval(node) for node in ast.walk(function) if isinstance(node, ast.List)
        and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == '/usr/sbin/lsof']
    require(len(listener_commands) == 1, 'unique exact listener command')
    native_command = h.sha(h.canonical([policy['nativeHelper']['path']]))
    listener_command = h.sha(h.canonical(listener_commands[0]))
    kinds = Counter()
    git_leases = []
    for lease in finite:
        require(lease['parentIdentity'] == controller and type(lease['exitCode']) is int and lease['exitCode'] == 0,
                'finite task not exact controller-owned/zero waited')
        if lease['stageId'] == 'observer-native-census':
            require(lease['commandSha256'] == native_command and lease['executableSha256'] == native_before, 'native exact command')
            kinds['native'] += 1
        elif lease['commandSha256'] == listener_command:
            require(lease['executableSha256'] == h.TOOL_SHA256['lsof'], 'listener executable')
            kinds['listener'] += 1
        else:
            require(lease['executableSha256'] == h.TOOL_SHA256['git'], 'unexpected managed finite executable')
            kinds['git'] += 1
            git_leases.append(lease)
    require(kinds['native'] == kinds['listener'] == 2 * len(rows) and kinds['git'] == 30,
            'actual finite workload population differs')
    expected_commands = passport['preflightCommands']
    observed_commands = receipt['preflightCommands']
    require(len(expected_commands) == len(observed_commands) == len(git_leases) == 30, 'preflight exact30 population')
    origin = h.real(receipt['originMonotonic'], 'actual origin')
    for expected, actual, lease in zip(expected_commands, observed_commands, git_leases):
        command = ['git', *[value.replace('{SOURCE}', SOURCE) for value in expected['arguments']]]
        require(h.typed_equal(command, actual['command']) and actual['stdoutSha256'] == expected['stdoutSha256']
                and type(actual['exitCode']) is int and actual['exitCode'] == 0
                and lease['commandSha256'] == h.sha(h.canonical(command)), 'actual source-proof Git result binding')
        require(actual['startedMonotonic'] <= lease['readyMonotonic'] <= lease['registerMonotonic']
                <= lease['releaseMonotonic'] <= lease['reapedMonotonic'] <= actual['completedMonotonic'] <= origin,
                'actual Git ready/release/wait clock outside source-proof command')

    require(preflight['status'] == 'PREFLIGHT_REFUSED' and set(preflight['phases']) == {'settling'}, 'retained phase refusal')
    phase = preflight['phases']['settling']
    require(phase['status'] == 'PREFLIGHT_REFUSED' and phase['phaseClock']['requestedSeconds'] == 600
            and phase['phaseClock']['intervalReset'] is False and phase['phaseClock']['endMonotonic'] is None
            and phase['elapsedSeconds'] is None and phase['coverage']['coverageComplete'] is False
            and preflight['runtimeHandoffAnchor'] is None and preflight['windowReset'] is False,
            'incomplete phase cannot be completed or reset')
    h.same(phase['phaseClock']['startMonotonic'], origin, 'phase actual origin')
    require(len(events) == len(rows) + 1 and events[0]['event'] == 'phase-enter'
            and events[0]['phase'] == 'settling', 'complete partial original phase events')
    h.same(events[0]['actualStartMonotonic'], origin, 'actual phase entry')
    disk_fields = {'sampleId', 'globalIndex', 'phase', 'scheduledMonotonic', 'deadlineMonotonic',
        'sampleStartedMonotonic', 'callbackStartedMonotonic', 'phaseEventWriteCompletedMonotonic', 'startLatenessSeconds'}
    extension = {'diagnosticWriteCompletedMonotonic', 'callbackCompletedMonotonic', 'serviceCompletedMonotonic', 'fullServiceSeconds'}
    services = []
    for index, (row, event, disk, complete) in enumerate(zip(rows, events[1:], service_events, complete_services)):
        require(type(row['globalIndex']) is int and row['globalIndex'] == index and row['phase'] == 'settling'
                and row['streamValidationStatus'] == 'PASS' and 'streamValidationError' not in row,
                'original raw pre-callback verdict/slot changed')
        require(event['schema'] == 'aijade.ch7.phase-continuity-event.v1' and type(event['eventIndex']) is int
                and event['eventIndex'] == index + 1 and event['event'] == 'sample-written'
                and type(event['globalIndex']) is int and event['globalIndex'] == index
                and event['sampleId'] == row['sampleId'] and event['phase'] == 'settling', 'raw/writer exact event binding')
        require(set(disk) == disk_fields and set(complete) == disk_fields | extension
                and h.typed_equal(disk, {key: complete[key] for key in disk_fields})
                and type(disk['globalIndex']) is int and disk['globalIndex'] == index
                and disk['sampleId'] == row['sampleId'] and disk['phase'] == 'settling', 'service original/receipt extension binding')
        start = h.real(row['monotonicSeconds'], 'actual capture start')
        end = h.real(complete['serviceCompletedMonotonic'], 'actual callback-return endpoint')
        h.same(row['globalScheduledMonotonic'], origin + index * 2, 'fixed global schedule')
        h.same(row['scheduledSeconds'], index * 2, 'fixed local slot')
        h.same(row['elapsedSeconds'], start - origin, 'actual local elapsed')
        h.same(row['observationDurationSeconds'], row['observationCompletedMonotonic'] - start, 'actual observation duration')
        for key in ('validatorStartedMonotonic', 'validatorCompletedMonotonic', 'writerStartedMonotonic'):
            h.same(event[key], row[key], 'actual raw/event ' + key)
        h.same(event['monotonicSeconds'], event['writerCompletedMonotonic'], 'actual writer completion')
        h.same(disk['scheduledMonotonic'], origin + index * 2, 'service fixed target')
        h.same(disk['deadlineMonotonic'], origin + 600, 'fixed settling deadline')
        h.same(disk['sampleStartedMonotonic'], start, 'service original sample start')
        h.same(disk['startLatenessSeconds'], start - origin - index * 2, 'actual scheduled-start lateness')
        h.same(complete['callbackCompletedMonotonic'], end, 'callback-return/service endpoint')
        h.same(complete['fullServiceSeconds'], end - start, 'actual full service duration')
        require(start <= row['observationCompletedMonotonic'] <= row['validatorStartedMonotonic']
            <= row['validatorCompletedMonotonic'] <= row['writerStartedMonotonic'] <= event['writerCompletedMonotonic']
            <= disk['callbackStartedMonotonic'] <= disk['phaseEventWriteCompletedMonotonic']
            <= complete['diagnosticWriteCompletedMonotonic'] <= end <= origin + 600,
            'complete original processing chronology/fixed deadline')
        require(0 <= disk['startLatenessSeconds'] <= .5, 'start-lateness threshold is a different refusal')
        if index:
            require(services[-1]['serviceCompletedMonotonic'] <= start
                    and 0 < start - rows[index - 1]['monotonicSeconds'] <= 3, 'actual sample/service order or gap')
        services.append(dict(complete, observationSeconds=row['observationDurationSeconds'],
            validationSeconds=row['validatorCompletedMonotonic'] - row['validatorStartedMonotonic'],
            rawWriteSeconds=event['writerCompletedMonotonic'] - row['writerStartedMonotonic']))
    require(all(value['fullServiceSeconds'] <= 2 for value in services[:-1])
            and services[-1]['fullServiceSeconds'] > 2, 'first retained strict service-budget refusal differs')
    require(preflight['reasonCode'] == 'PREFLIGHT_CALLBACK_FAILED'
            and preflight['reason'] == 'ValueError: engineering full service exceeded two seconds'
            and receipt['errors'] == ['PreflightRefused: PREFLIGHT_CALLBACK_FAILED: ValueError: engineering full service exceeded two seconds'],
            'original precise refusal reason')
    h.same(preflight['refusedAtMonotonic'], services[-1]['serviceCompletedMonotonic'], 'actual service-hook refusal clock')
    for value in (phase['samples'], preflight['samples']):
        require(type(value) is int and value == len(rows), 'partial raw population differs')
    for value in (phase['validatedSamples'], preflight['validatedSamples']):
        require(type(value) is int and value == len(rows) - 1, 'phase post-callback validated population differs')
    require(type(phase['expectedSamples']) is int and phase['expectedSamples'] == 300, 'fixed300 denominator')
    accepted = rows[:-1]
    require(phase['minimumAvailableBytes'] == min(row['availableBytes'] for row in accepted)
            and phase['swapRangeBytes'] == max(row['swapUsedBytes'] for row in accepted) - min(row['swapUsedBytes'] for row in accepted),
            'phase accepted-prefix resource aggregate differs')
    gaps = [after['monotonicSeconds'] - before_row['monotonicSeconds'] for before_row, after in zip(rows, rows[1:])]
    h.same(phase['coverage']['maximumGapSeconds'], max(gaps), 'actual partial coverage maximum gap')
    h.same(phase['coverage']['lastElapsedSeconds'], rows[-1]['monotonicSeconds'] - origin, 'actual last start')
    try:
        audit.verify_lifecycle(journal, rows, source_commit=SOURCE, policy_sha256=passport['policySha256'],
                               policy=policy, controller=receipt['controllerProcess'])
        raise ValueError('unexpected runtime-only idle acceptance')
    except Exception as error:
        idle_refusal = dict(error=type(error).__name__ + ': ' + str(error), traceback=traceback.format_exc())
        require('runtime must have one exact local persistent root' in str(error), 'unexpected frozen idle predicate result')

    # Parent Popen.wait exit1 is an adverse controller outcome, not a finite
    # helper wait0 and not an absence claim about every machine process.
    require(launch['schema'] == 'aijade.ch7.equal-load-parent-launch.v1'
            and terminal['schema'] == 'aijade.ch7.equal-load-parent-terminal.v1'
            and launch['sourceCommit'] == terminal['sourceCommit'] == SOURCE
            and launch['passportSha256'] == terminal['passportSha256'] == PASSPORT_SHA
            and launch['launcherSha256'] == terminal['launcherSha256'] == passport['launcherSha256']
            and terminal['launchRecordSha256'] == h.sha(launch_raw)
            and terminal['logSha256'] == h.file_sha(C4 / 'engineering-launch.log'), 'actual parent launch/terminal bytes')
    require(h.typed_equal(launch['parentProcess'], terminal['parentProcess'])
            and h.typed_equal(launch['controllerProcess'], terminal['controllerProcess']), 'parent/controller identity changed')
    recorded_controller = launch['controllerProcess']
    require(recorded_controller['pid'] == controller['pid'] == launch['controllerPidFromPopen'] == terminal['controllerPidFromPopen']
            and recorded_controller['createTimeMicros'] == controller['createTimeMicros']
            and recorded_controller['parentPid'] == controller['parentPid'] == launch['parentProcess']['pid'], 'actual controller birth/parent')
    require(terminal['actualParentWaitSource'] == 'Popen.wait' and len(terminal['actualParentWaits']) == 1,
            'actual parent wait missing/duplicated')
    parent_wait = terminal['actualParentWaits'][0]
    require(parent_wait['source'] == 'Popen.wait' and parent_wait['timedOut'] is False
            and type(parent_wait['exitCode']) is int and parent_wait['exitCode'] == 1
            and type(terminal['controllerExitCode']) is int and terminal['controllerExitCode'] == 1
            and terminal['watchdogTimedOut'] is False and terminal['watchdogActions'] == []
            and parent_wait['startedMonotonic'] <= state['events'][0]['monotonicSeconds']
            <= state['events'][-1]['monotonicSeconds'] <= parent_wait['completedMonotonic'], 'actual adverse parent wait/close chronology')
    require(terminal['status'] == 'ENGINEERING_PARENT_LAUNCH_ADVERSE'
            and terminal['engineeringReportDelivered'] is False
            and terminal['independentEngineeringReplayAccepted'] is False
            and terminal['wholeProcessGroupCleanupClaimed'] is False, 'parent adverse scope changed')
    for key, value in protocol['scientificGates'].items():
        require(h.typed_equal(receipt[key], value), 'scientific gate/type changed: ' + key)
    require(receipt['automaticRetries'] == passport['automaticRetries'] == 0
            and type(receipt['automaticRetries']) is int and type(passport['automaticRetries']) is int,
            'no retry authorization')
    for key in ('scientificAcceptance', 'qualificationStarted', 'backendQualified', 'scientificAdmission',
                'formalHardwareQualification', 'independentHumanReview', 'authorApproval', 'heldoutComparisonComplete',
                'currentProductInheritsResearchQualification', 'seedConstructed', 'qualificationInvokedByLauncher',
                'rendererInvokedByLauncher', 'modelInvokedByLauncher'):
        require(launch[key] is False and terminal[key] is False, 'parent scientific boundary: ' + key)
    require(terminal['table7_3'] == 'NOT_RUN', 'held-out table remains not run')

    numbers = dict(rawSamples=len(rows), rawStreamPassSamples=sum(row['streamValidationStatus'] == 'PASS' for row in rows),
        phaseValidatedSamples=phase['validatedSamples'], observerPassSamples=raw_replay['guardDecisions'].get('PASS', 0),
        observerUnknownSamples=raw_replay['guardDecisions'].get('UNKNOWN', 0), observerFailSamples=raw_replay['guardDecisions'].get('FAIL', 0),
        plannedSettlingSamples=300, missingSettlingSamples=300 - len(rows), plannedAdmissionSamples=60,
        admissionSamples=0, missingAdmissionSamples=60, plannedTailSamples=2, tailSamples=0, missingTailSamples=2,
        plannedTotalSamples=362, missingTotalSamples=362 - len(rows), journalEvents=len(state['events']),
        finiteLeases=len(finite), finiteActualParentWaitZero=sum(type(value['exitCode']) is int and value['exitCode'] == 0 for value in finite),
        nativeCalls=kinds['native'], listenerCalls=kinds['listener'], preflightGitCalls=kinds['git'],
        apiExplicitEmptySamples=len(rows), controllerScopes=len(state['scopes']), closedControllerScopes=sum(value['closeSeq'] is not None for value in state['scopes'].values()),
        launchRefusals=len(state['launchRefusals']), serviceOverBudgetSamples=sum(value['fullServiceSeconds'] > 2 for value in services),
        maximumFullServiceSeconds=max(value['fullServiceSeconds'] for value in services),
        lastFullServiceSeconds=services[-1]['fullServiceSeconds'], lastServiceExcessSeconds=services[-1]['fullServiceSeconds'] - 2,
        maximumStartLatenessSeconds=max(value['startLatenessSeconds'] for value in services), maximumActualStartGapSeconds=max(gaps),
        lastNominalSeconds=rows[-1]['scheduledSeconds'], lastStartSeconds=rows[-1]['monotonicSeconds'] - origin,
        lastObservationCompletedSeconds=rows[-1]['observationCompletedMonotonic'] - origin,
        lastServiceCompletedSeconds=services[-1]['serviceCompletedMonotonic'] - origin,
        lastObservationSeconds=services[-1]['observationSeconds'], lastValidationSeconds=services[-1]['validationSeconds'],
        lastRawWriteSeconds=services[-1]['rawWriteSeconds'], settlingMinimumAvailableBytes=min(row['availableBytes'] for row in rows),
        settlingSwapRangeBytes=max(row['swapUsedBytes'] for row in rows) - min(row['swapUsedBytes'] for row in rows),
        maximumIdleResearchOwnedRssBytes=max(row['rssBytes'] for row in rows), controllerActualParentWaitExitCode=parent_wait['exitCode'],
        modelRequests=0, rendererRequests=0, flowBlocks=0, freshHeldoutCases=0)
    require(len(state['events']) == 3 + 3 * len(finite), 'complete controller/open/finite/close journal population')
    require(h.typed_equal(before, h.file_table(root)) and native_before == h.file_sha(native_path)
            and all(h.file_sha(repo / value['path']) == value['sha256'] for value in sources), 'original inputs/source/native changed during replay')
    for name, record in initial['externalFiles'].items():
        require(h.file_sha(C4 / name) == record['sha256'], 'external frozen input changed during replay: ' + name)
    report = dict(schema='aijade.ch7.prefix-engineering-refusal-audit.v1',
        status='INDEPENDENT_ENGINEERING_REFUSAL_TERMINAL_AUDIT_PASS', sourceCommit=SOURCE, engineeringFreezeCommit=FREEZE,
        passportSha256=PASSPORT_SHA, auditScriptSha256=h.file_sha(Path(__file__)), frozenAcceptanceToolSha256=ACCEPTANCE_TOOL_SHA,
        inputSnapshot=dict(path=str(args.snapshot), sha256=h.file_sha(args.snapshot)), inputFiles=before,
        sourceFiles=sources, nativeBinarySha256=native_before, numbers=numbers,
        scope=dict(terminalRecordIntegrityAccepted=True, engineeringAccepted=False, engineeringComplete=False,
            scientificAcceptance=False, qualificationStarted=False, fullFiniteDriverQualified=False, backendQualified=False,
            scientificAdmission=False, formalHardwareQualification=False, independentHumanReview=False,
            heldoutComparisonComplete=False, admissionPhaseStarted=False, tailPhaseStarted=False,
            newFormalQualificationPlanCreatedByThisRun=False, seedConstructed=False, table7_3='NOT_RUN'),
        services=services, missingPlannedTicks=dict(settling=list(range(len(rows), 300)), admission=list(range(300, 360)), tail=[360, 361]),
        frozenRuntimeIdlePredicate=idle_refusal, actualParentWait=parent_wait,
        originalControllerExitCode=terminal['controllerExitCode'],
        interpretation=[
            'All original process/native/API records are cold-replayed; their PASS is distinct from the engineering complete-service ceiling.',
            'The final raw streamValidationStatus remains PASS because it was written before the service callback failed. The post-callback phase validated count excludes that final row; neither original label is rewritten.',
            'The complete-service threshold is2seconds, while the unchanged whole-observation bound is2.5seconds. This is not a native/API collector FAIL or the600second phase deadline refusal.',
            'The parent controller actually exits1 and is reaped by its actual parent. Its adverse status remains separate from all70 successful finite helper waits and does not imply whole-machine process-group cleanup.',
            'Unattempted engineering slots are not known-case trajectories. No admission/tail window, new qualification plan, seed, model verdict, rendered act or held-out data is added.'],
        noNewObservation=True, noRetry=True, originalBytesUnchanged=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(status=report['status'], output=str(output), sha256=h.file_sha(output), numbers=numbers), indent=2), flush=True)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=BASE / '.runtime/posix/runs/ch7-prefix-20261117/engineering-01')
    parser.add_argument('--repo', type=Path, default=BASE / '.runtime/posix/research/ch7-prefix-20261117/worktree')
    parser.add_argument('--passport', type=Path, default=C4 / 'engineering-01-passport.json')
    parser.add_argument('--publication', type=Path, default=C4 / 'engineering-freeze-publication.json')
    parser.add_argument('--launch', type=Path, default=C4 / 'engineering-launch.json')
    parser.add_argument('--parent-terminal', type=Path, default=C4 / 'engineering-launch.terminal.json')
    parser.add_argument('--snapshot', type=Path, default=C4 / 'analysis/equal-load-refusal-01-inputs.json')
    parser.add_argument('--output', type=Path, default=C4 / 'analysis/independent-equal-load-refusal-audit-01.json')
    try:
        raise SystemExit(run(parser.parse_args()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
