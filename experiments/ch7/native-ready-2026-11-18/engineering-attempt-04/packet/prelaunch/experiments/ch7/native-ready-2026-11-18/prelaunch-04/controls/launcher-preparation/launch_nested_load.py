#!/usr/bin/env python3
"""One fixed engineering child and an identity-bound parent watchdog.

This file has no qualification, renderer, model, input-construction or retry
entry point. A runner-reported PASS is delivered pending independent replay.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import time

import psutil

BASE = Path('/Volumes/Untitled/AIJADE')
C9 = BASE / '.research/runs/ch7-native-ready-20261118'
LAUNCHER_HOME = C9 / 'launcher-preparation'
FIXED_PYTHON = BASE / '.runtime/python-envs/p2-tokenizer/bin/python'
WRAPPER = BASE / '.runtime/run-local.sh'
RUNNER_RELATIVE = 'experiments/ch7/run_nested_load.py'
RECORD = C9 / 'engineering-04-launch.json'
LOG = C9 / 'engineering-04-launch.log'
TERMINAL = C9 / 'engineering-04-launch.terminal.json'
RUN = BASE / '.runtime/posix/runs/ch7-native-ready-20261118/engineering-04'
WATCHDOG_SECONDS = 2250
SIGNAL_WAIT_SECONDS = 5
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
NATIVE_MODE = 'native-ready-release-v1'
NATIVE_BINARY_SHA256 = 'c8e678bd28e5511c7209172d7df3281c79fd28c3be4bbe1f731f4bcc8b6d45aa'
LSOF_PATH = Path('/usr/sbin/lsof')
LSOF_SHA256 = 'ef5e67978fb8f8bcd32927789811462dd1b3773b8ad6322b67a491d2b5733b3a'
LSOF_ARGV = ['/usr/sbin/lsof', '-nP', '-iTCP:11434', '-sTCP:LISTEN', '-FpfPtTn']
DEVELOPMENT_BASIS = dict(status='NATIVE_READY_COMPONENT_NOT_ALL_PASS', legacyComplete=10,
    nativeComplete=9, attemptsPerHalf=10, firstNativeWholeSeconds=0.5640400309930556,
    componentResultSha256='f121da1060acc9959dfdfe0a4c5d075cc009d88d7c8958df81dc23246d454c0e',
    sameArtifactFirstPerRunUse='First of existing30 Git proofs within900 preparation; child first use within30 proofs/15 startup.',
    additionalWarmup=False, listenerDeadlineExemption=False, coldArtifactFirstEverExecutionClaim=False,
    qualificationGranted=False, fullNestedEngineeringStillRequired=True)
OBSERVERS = tuple('experiments/ch7/' + name for name in (
    'mac_process_guard_v3.py', 'process_lifecycle.py', 'lifecycle_exec.py',
    'phase_continuity.py', 'lifecycle_audit.py', 'mac_process_guard.py',
    'mac_process_guard_v2.py', 'mac_bulk_census.c', 'finite_runtime.py',
    'run_finite_sequence.py', 'run_finite_block.py', 'finite_audit.py',
    'finite_sequence_audit.py', 'godot_local.py', 'binary_authentication.py', 'measured_mac_monitor.py', 'full_state_clone_cursor.py', 'newowned_guard_cursor.py', 'native_exec_registry.py', 'lifecycle_exec_native.c', 'listener_evidence.py'))
FALSE_GATES = dict(scientificAcceptance=False, qualificationStarted=False,
    backendQualified=False, scientificAdmission=False,
    formalHardwareQualification=False, independentHumanReview=False,
    authorApproval=False, heldoutComparisonComplete=False,
    currentProductInheritsResearchQualification=False,
    seedConstructed=False, qualificationInvokedByLauncher=False,
    rendererInvokedByLauncher=False, modelInvokedByLauncher=False)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def stable_binary_sha(path, *, native=False):
    """Complete byte read with before/after/current metadata; never execute."""
    path=Path(path)
    need(path.is_absolute() and path==path.resolve() and not path.is_symlink(), 'native/lsof binary canonical path')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(descriptor)
        need(stat.S_ISREG(before.st_mode), 'native/lsof binary must be regular')
        if native:
            need(before.st_uid==os.getuid() and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o755,
                 'native binary owner/link/exact0755 mode differs')
        value=hashlib.sha256()
        while block:=os.read(descriptor,1024*1024):value.update(block)
        after=os.fstat(descriptor);current=os.stat(path,follow_symlinks=False)
        def identity(item):return (item.st_dev,item.st_ino,item.st_size,item.st_mtime_ns,item.st_mode,item.st_uid,item.st_nlink)
        need(identity(before)==identity(after)==identity(current), 'native/lsof binary changed during complete read')
        return value.hexdigest()
    finally:os.close(descriptor)


def native_bindings(policy,protocol,passport,repo,sources,observers):
    """One exact native/listener contract, all three published inputs agree."""
    need(all(value.get('lifecycleExecMode')==NATIVE_MODE for value in (policy,protocol,passport)),
         'explicit three-way native exec mode required')
    fields={'mode','adapterSourceSha256','sourcePath','sourceSha256','binaryPath','binarySha256'}
    bindings=[value.get('nativeExec') for value in (policy,protocol,passport)]
    need(all(type(value) is dict and set(value)==fields for value in bindings)
         and bindings[0]==bindings[1]==bindings[2], 'closed three-way native exec binding differs')
    native=bindings[0]
    need(native['mode']==NATIVE_MODE, 'native binding mode differs')
    for field in ('adapterSourceSha256','sourceSha256','binarySha256'):hash_value(native[field])
    adapter='experiments/ch7/native_exec_registry.py';source='experiments/ch7/lifecycle_exec_native.c'
    need(native['adapterSourceSha256']==sources[adapter]==observers[adapter]==file_sha(repo/adapter),
         'native adapter source pin differs')
    need(canonical_path(native['sourcePath'])==repo/source and native['sourceSha256']==sources[source]
         ==observers[source]==file_sha(repo/source), 'native C source pin/path differs')
    binary=canonical_path(native['binaryPath'])
    need(stable_binary_sha(binary,native=True)==native['binarySha256']==NATIVE_BINARY_SHA256,
         'actual native binary fixed SHA differs')
    need(policy.get('lifecycle',{}).get('execShimSha256')==native['binarySha256'],
         'native lifecycle shim pin differs; legacy fallback forbidden')
    fields={'mode','moduleSha256','command','executableSha256','maxSeconds','maxBytes'}
    bindings=[value.get('listenerEvidence') for value in (policy,protocol,passport)]
    need(all(type(value) is dict and set(value)==fields for value in bindings)
         and bindings[0]==bindings[1]==bindings[2], 'closed three-way listener evidence differs')
    listener=bindings[0];module='experiments/ch7/listener_evidence.py'
    need(listener['mode']=='complete-managed-lsof-transcript-v1' and type(listener['command']) is list
         and listener['command']==LSOF_ARGV and all(type(v) is str for v in listener['command'])
         and type(listener['maxSeconds']) is float and listener['maxSeconds']==.5
         and type(listener['maxBytes']) is int and listener['maxBytes']==65536,
         'unchanged global listener argv/whole deadline/cap required')
    need(hash_value(listener['moduleSha256'])==sources[module]==observers[module]==file_sha(repo/module),
         'listener transcript source pin differs')
    need(hash_value(listener['executableSha256'])==LSOF_SHA256==stable_binary_sha(LSOF_PATH),
         'actual global lsof fixed executable SHA differs')
    return {adapter,source,module}


def unique(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, 'duplicate JSON key')
        value[key] = item
    return value


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def canonical_path(value):
    path = Path(value)
    need(path.is_absolute() and path == path.resolve() and path.is_relative_to(BASE),
         'noncanonical or outside-AIJADE path')
    need(not any(item.is_symlink() for item in (path, *path.parents)), 'symlink path')
    return path


def relative(value):
    need(type(value) is str and value and '\\' not in value
         and not any(ord(char) < 32 for char in value), 'unsafe relative source path')
    path = PurePosixPath(value)
    need(not path.is_absolute() and all(part not in ('', '.', '..') for part in value.split('/')),
         'source path escapes repository')
    return value


def hash_value(value):
    need(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, 'full SHA256 required')
    return value


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def exclusive(path):
    path = canonical_path(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    need(stat.S_ISREG(os.fstat(fd).st_mode), 'exclusive artifact is not regular')
    return fd


def save_fd(fd, path, value):
    opened, current = os.fstat(fd), os.stat(path, follow_symlinks=False)
    need((opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino), 'owned record path replaced')
    body = json_bytes(value)
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    offset = 0
    while offset < len(body):
        written = os.write(fd, body[offset:])
        need(written > 0, 'record write incomplete')
        offset += written
    os.fsync(fd)


def save_new(path, value):
    fd = exclusive(path)
    try:
        save_fd(fd, path, value)
    finally:
        os.close(fd)


def process_identity(pid):
    process = psutil.Process(pid)
    created = process.create_time()
    need(type(created) in (int, float) and math.isfinite(created) and created > 0, 'unknown birth identity')
    return dict(pid=pid, createTime=created, createTimeMicros=round(created * 1000000),
                parentPid=process.ppid(), processGroup=os.getpgid(pid))


def preflight(passport_path, expected_sha):
    path = canonical_path(passport_path)
    need(path == C9 / 'engineering-04-passport.json', 'one independent nested passport required; never reuse another attempt')
    need(path.is_file(), 'passport missing')
    raw = path.read_bytes()
    need(digest(raw) == hash_value(expected_sha), 'passport differs from external frozen SHA256')
    passport = decode(raw)
    need(passport.get('schema') == 'aijade.ch7.nested-load-passport.v1', 'engineering passport schema')
    need(passport.get('purpose')=='ENGINEERING_ONLY_NOT_QUALIFICATION', 'explicit engineering passport purpose required')
    need(re.fullmatch('[0-9a-f]{40}', passport.get('sourceCommit', '')) is not None, 'full engineering source commit required')
    repo, output = canonical_path(passport['repo']), canonical_path(passport['output'])
    need(repo.is_dir() and not output.exists(), 'missing repo or existing engineering output')
    need(output == RUN, 'one independent owned-state engineering output required')
    need(not any(path.exists() for path in (RECORD, LOG, TERMINAL)), 'attempt artifacts exist; never retry')
    need(Path(__file__).resolve() == LAUNCHER_HOME / 'launch_nested_load.py', 'unexpected launcher location')
    need(file_sha(Path(__file__)) == hash_value(passport['launcherSha256']), 'launcher source differs')
    need(file_sha(canonical_path(WRAPPER)) == hash_value(passport['runtimeWrapperSha256']), 'runtime wrapper differs')
    # Keep the venv entry path, not its resolved SDK target, as executable argv.
    need(FIXED_PYTHON.is_file() and file_sha(FIXED_PYTHON) == hash_value(passport['pythonSha256']), 'fixed Python differs')
    need(Path(sys.executable).absolute() == FIXED_PYTHON and psutil.__version__ == '7.2.2', 'launcher must use frozen project Python and psutil')
    sources = passport['sourceFiles']
    need(type(sources) is dict and len(sources) >= 22 and RUNNER_RELATIVE in sources
         and '.editorconfig' not in sources, 'complete source closure for nested engineering required')
    need({passport['planPath'],passport['protocolPath'],passport['policyPath']} <= set(sources),
         'prospective plan/protocol/policy absent from exact Qe source closure')
    for name, expected in sources.items():
        need(file_sha(canonical_path(repo / relative(name))) == hash_value(expected), 'source SHA differs: ' + name)
    need(subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==passport['sourceCommit']
         and subprocess.check_output(['git','status','--porcelain'],cwd=repo)==b'',
         'exact clean Qe HEAD required before launch')
    for name in sources:
        need((repo/name).read_bytes()==subprocess.check_output(
            ['git','--no-replace-objects','show',passport['sourceCommit']+':'+name],cwd=repo),
            'actual source differs from frozen Qe Git blob: '+name)
    protocol_path=canonical_path(repo/relative(passport['protocolPath']))
    plan_path=canonical_path(repo/relative(passport['planPath']))
    need(file_sha(protocol_path)==passport['protocolSha256']
         and file_sha(plan_path)==passport['planSha256'],'prospective plan/protocol byte identity')
    protocol=decode(protocol_path.read_bytes())
    need(passport['runtime']==protocol['runtime']
         and passport['prefixPaddingTaskCount']==protocol['prefixPaddingTaskCount']
         and passport['prefixPreparationMaximumSeconds']==protocol['prefixPreparationMaximumSeconds']
         and passport['journalAcceptanceMaximumBytes']==protocol['journalAcceptanceMaximumBytes']
         and passport['minimumDemonstratedPrefixBytes']==protocol['minimumDemonstratedPrefixBytes']
         and WATCHDOG_SECONDS==protocol['outerWatchdogSeconds'],'passport differs from prospective protocol')
    need(protocol['runtime']['childStartupMaximumSeconds']==15,
         'E6 retains the explicit fifteen-second startup acceptance budget')
    observers = passport['observerSources']
    need(type(observers) is dict and set(observers) == set(OBSERVERS)
         and all(sources.get(name) == expected for name, expected in observers.items()), 'observer dependency closure differs')
    runner = canonical_path(repo / RUNNER_RELATIVE)
    need(file_sha(runner) == hash_value(passport['runnerSha256']) == sources[RUNNER_RELATIVE], 'runner differs')
    policy_path = canonical_path(repo / relative(passport['policyPath']))
    policy_raw = policy_path.read_bytes()
    need(digest(policy_raw) == hash_value(passport['policySha256']), 'policy raw bytes differ')
    policy = decode(policy_raw)
    auth_relative = 'experiments/ch7/binary_authentication.py'
    need(policy.get('binaryAuthenticationMode') == 'full-read-exact-bytes-v1',
         'nested engineering requires explicit full-read-exact-bytes binary authentication mode')
    need(policy.get('coordinationMode')=='segmented-census-mutation-v1'
         and policy.get('coordinationSchema')=='aijade.mac.segmented-census-mutation.v1'
         and policy.get('purpose')=='engineering_real_nested_only'
         and 'executionDecision' not in policy, 'explicit engineering-only segmented policy required')
    owned_relative='experiments/ch7/newowned_guard_cursor.py'
    need(policy.get('onlineReplayMode')=='owned-guard-state-exact-prefix-v1'
         and policy.get('onlineReplayInitializationMode')=='paired-source-verified-owned-state-v1'
         and protocol.get('onlineReplayMode')==policy['onlineReplayMode']
         and protocol.get('onlineReplayInitializationMode')==policy['onlineReplayInitializationMode']
         and passport.get('onlineReplayMode')==policy['onlineReplayMode']
         and passport.get('onlineReplayInitializationMode')==policy['onlineReplayInitializationMode'],
         'explicit owned-state initialization mode required')
    need(hash_value(policy.get('onlineReplaySourceSha256'))==sources[owned_relative]
         ==observers[owned_relative]==file_sha(canonical_path(repo/owned_relative))
         ==hash_value(protocol.get('onlineReplaySourceSha256'))
         ==hash_value(passport.get('onlineReplaySourceSha256')),
         'owned-state source pin differs')
    native_proof_sources=native_bindings(policy,protocol,passport,repo,sources,observers)
    auth_pin = hash_value(policy.get('binaryAuthenticationSourceSha256'))
    need(auth_pin == sources[auth_relative] == observers[auth_relative]
         == file_sha(canonical_path(repo / auth_relative)), 'binary authentication source pin differs')
    native = policy['nativeHelper']
    need(file_sha(canonical_path(native['path'])) == hash_value(native['sha256']), 'native helper differs')
    need(file_sha(repo / 'experiments/ch7/mac_bulk_census.c') == hash_value(native['sourceSha256']), 'native C source differs')
    need(file_sha(repo/'experiments/ch7/process_lifecycle.py')==hash_value(policy['lifecycle']['moduleSha256']),
         'lifecycle source differs')
    commands = passport['preflightCommands']
    need(type(commands) is list and len(commands) == 30, 'preflight30 commands required')
    for item in commands:
        need(type(item) is dict and set(item) == {'arguments', 'stdoutSha256'}, 'preflight command schema')
        args = item['arguments']
        need(type(args) is list and args and all(type(value) is str and value
             and not any(ord(char) < 32 for char in value) for value in args), 'preflight argv')
        need(args[0] in ('rev-parse', 'status', 'show'), 'preflight must be an allowed read-only Git command')
        hash_value(item['stdoutSha256'])
    shows = [item for item in commands if item['arguments'][0] == 'show']
    metadata = [item for item in commands if item['arguments'][0] != 'show']
    need(len(shows)==28 and {tuple(item['arguments']) for item in metadata}=={
         ('status','--porcelain'),('rev-parse','HEAD')} and len(metadata)==2,
         'exact two metadata and twenty-eight source proof commands required')
    proved = set()
    for item in shows:
        args=item['arguments']
        need(len(args)==2 and args[1].startswith('{SOURCE}:'), 'exact source-proof Git show form required')
        name=relative(args[1][len('{SOURCE}:'):])
        need(name not in proved and sources.get(name)==item['stdoutSha256'],
             'distinct actual source proof hashes required')
        proved.add(name)
    need(owned_relative in proved, 'owned-state source must be proved by an actual Git show command')
    need(native_proof_sources <= proved, 'all three native/listener source modules require actual Git show proofs')
    for item in metadata:
        wanted=digest(b'') if item['arguments'][0]=='status' else digest((passport['sourceCommit']+'\n').encode())
        need(item['stdoutSha256']==wanted, 'exact metadata proof digest required')
    command = [str(WRAPPER), str(FIXED_PYTHON), '-B', str(runner), '--passport', str(path)]
    return dict(passport=passport, passportPath=path, passportRaw=raw, repo=repo,
                output=output, command=command)


def wait_owned(process, seconds, waits):
    record = dict(source='Popen.wait', timeoutSeconds=seconds, startedMonotonic=time.monotonic())
    try:
        code = process.wait(timeout=seconds)
        need(type(code) is int, 'parent wait returned unknown exit code')
        record.update(completedMonotonic=time.monotonic(), timedOut=False, exitCode=code)
        waits.append(record)
        return code
    except subprocess.TimeoutExpired:
        record.update(completedMonotonic=time.monotonic(), timedOut=True, exitCode=None)
        waits.append(record)
        raise
    except BaseException as error:
        record.update(completedMonotonic=time.monotonic(), timedOut=False, exitCode=None,
                      interrupted=True, errorClass=type(error).__name__)
        waits.append(record)
        raise


def signal_owned_group(process, bound, number, actions):
    action = dict(signal=number, signalName=signal.Signals(number).name,
                  startedMonotonic=time.monotonic(), sent=False)
    try:
        need(bound is not None and process.pid == bound['pid'], 'controller identity was never bound')
        need(process.poll() is None, 'owned controller already exited; do not signal a recycled group')
        current = process_identity(process.pid)
        need(current['createTimeMicros'] == bound['createTimeMicros']
             and current['parentPid'] == os.getpid()
             and current['parentPid'] == bound['parentPid']
             and current['processGroup'] == process.pid == bound['processGroup'],
             'current controller birth/parent/self-process-group differs')
        action['identityRechecked'] = current
        os.killpg(process.pid, number)
        action.update(sent=True, completedMonotonic=time.monotonic())
        actions.append(action)
        return True
    except (ValueError, OSError, psutil.Error) as error:
        action.update(completedMonotonic=time.monotonic(), error=type(error).__name__ + ': ' + str(error))
        actions.append(action)
        return False


def stop_owned(process, bound, waits, actions):
    """At most TERM then KILL, each with fresh exact ownership checks."""
    sent = signal_owned_group(process, bound, signal.SIGTERM, actions)
    try:
        return wait_owned(process, SIGNAL_WAIT_SECONDS, waits)
    except subprocess.TimeoutExpired:
        if not sent:
            return None
    if not signal_owned_group(process, bound, signal.SIGKILL, actions):
        return None
    try:
        return wait_owned(process, SIGNAL_WAIT_SECONDS, waits)
    except subprocess.TimeoutExpired:
        return None


def read_report(context, bound, exit_code):
    path = canonical_path(context['output'] / 'receipt.json')
    need(path.is_file() and path.stat().st_size <= MAX_RECEIPT_BYTES, 'nested receipt missing or oversized')
    original=path.read_bytes();receipt=decode(original);p=context['passport']
    need(receipt.get('schema')=='aijade.ch7.nested-load-result.v1','nested receipt schema')
    need(bound is not None and exit_code==0,'unknown controller identity or nonzero actual wait')
    need(receipt.get('sourceCommit')==p['sourceCommit']
         and receipt.get('passportSha256')==digest(context['passportRaw'])
         and receipt.get('runnerSha256')==p['runnerSha256']
         and receipt.get('policySha256')==p['policySha256']
         and receipt.get('sourceFiles')==p['sourceFiles'],'nested source identities differ')
    controller=receipt['controllerProcess'];created=controller.get('createTime')
    need(type(created) in (int,float) and math.isfinite(created)
         and controller.get('pid')==bound['pid'] and round(created*1000000)==bound['createTimeMicros']
         and controller.get('parentPid')==bound['parentPid'],'actual nested controller identity differs')
    need(receipt.get('controllerSysExecutable')==str(FIXED_PYTHON),'nested interpreter entry differs')
    need(receipt.get('status')=='ENGINEERING_REAL_NESTED_LOAD_PASS_PENDING_INDEPENDENT_AUDIT'
         and receipt.get('errors')==[] and receipt.get('lifecycleJournalStable') is True,
         'nested runner adverse/unknown')
    need(receipt.get('originalPreflightObservations')==360 and len(receipt.get('nestedBlocks',[]))==4,
         'complete original idle and four nested blocks required')
    final=receipt['registryFinal']
    need(final.get('status')=='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT'
         and final.get('scopeClosed') is True
         and all(final.get(key)==[] for key in ('unresolvedFiniteLeases','launchRefusals',
             'launchRefusalArtifacts','unleasedDiscoveredIdentities','remainingIdentities')),
         'nested lifecycle terminal adverse')
    for key in ('qualificationStarted','backendQualified','scientificAdmission',
                'formalHardwareQualification','independentHumanReview','seedConstructed'):
        need(receipt.get(key) is False,'unsupported scientific gate '+key)
    for key in ('flowBlocks','modelRequests','rendererRequests','freshHeldoutCases','automaticRetries'):
        need(type(receipt.get(key)) is int and receipt[key]==0,'nonzero forbidden operation '+key)
    epoch=receipt['nestedEpochMonotonic']
    need(type(epoch) in (int,float) and math.isfinite(epoch) and epoch>=0,'actual nested runtime epoch')
    preparation=receipt['preparationEpochMonotonic']
    need(type(preparation) in (int,float) and math.isfinite(preparation)
         and 0 <= preparation <= epoch, 'actual enclosing-parent preparation epoch')
    return dict(path=str(path),sha256=digest(original),sizeBytes=len(original),runnerStatus=receipt['status'],
        controllerSysExecutable=receipt['controllerSysExecutable'],lifecycleJournalStable=True,
        nestedEpochMonotonic=epoch,
        preparationEpochMonotonic=preparation,
        interpretation='Real producer report only; complete independent nested raw replay is required.')


def execute(passport_path, expected_sha):
    context = preflight(passport_path, expected_sha)
    parent = process_identity(os.getpid())
    parent.update(sysExecutable=sys.executable, resolvedSysExecutable=str(Path(sys.executable).resolve()))
    record = dict(schema='aijade.ch7.nested-load-parent-launch.v1', status='EXCLUSIVE_ATTEMPT_RESERVED',
        startedAt=utc(), sourceCommit=context['passport']['sourceCommit'], passportPath=str(context['passportPath']),
        passportSha256=digest(context['passportRaw']), launcherSha256=file_sha(Path(__file__)),
        runtimeWrapperSha256=file_sha(WRAPPER), pythonEntry=str(FIXED_PYTHON), pythonSha256=file_sha(FIXED_PYTHON),
        command=context['command'], cwd=str(context['repo']), output=str(context['output']),
        parentProcess=parent, controllerProcess=None, startNewSession=True,
        watchdogSeconds=WATCHDOG_SECONDS, automaticRetries=0, developmentComponentBasis=DEVELOPMENT_BASIS, **FALSE_GATES)
    record_fd = exclusive(RECORD)
    save_fd(record_fd, RECORD, record)
    process = bound = report = exit_code = None
    waits, actions, errors = [], [], []
    timed_out = False
    started = time.monotonic()
    previous_handlers = {}

    def interrupted(number, frame):
        raise RuntimeError('parent interrupted by signal ' + str(number))

    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[number] = signal.signal(number, interrupted)
        log_fd = exclusive(LOG)
        with os.fdopen(log_fd, 'wb') as log:
            env = dict(os.environ, DOTNET_PROCESSOR_COUNT='2', PYTHONDONTWRITEBYTECODE='1',
                       PYTHONNOUSERSITE='1', AIJADE_GIT_COMMIT=context['passport']['sourceCommit'])
            for key in list(env):
                if key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE') or key.startswith(('AIJADE_LIFECYCLE_', 'AIJADE_FINITE_', 'AIJADE_NESTED_')):
                    env.pop(key, None)
            preparation_epoch=time.monotonic()
            env['AIJADE_NESTED_PREPARATION_EPOCH']=str(preparation_epoch)
            record['preparationEpochMonotonic']=preparation_epoch
            record['status'] = 'SPAWN_ATTEMPTED_NO_RETRY'
            save_fd(record_fd, RECORD, record)
            process = subprocess.Popen(context['command'], cwd=context['repo'], env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, shell=False, close_fds=True)
            record['controllerPidFromPopen'] = process.pid
            try:
                bound = process_identity(process.pid)
                need(bound['parentPid'] == os.getpid() and bound['processGroup'] == process.pid,
                     'launched child parent/session identity unknown')
                record.update(status='CONTROLLER_IDENTITY_BOUND', controllerProcess=bound)
            except (ValueError, OSError, psutil.Error) as error:
                bound = None
                errors.append('controller identity unknown: ' + type(error).__name__ + ': ' + str(error))
                record['status'] = 'CONTROLLER_IDENTITY_UNKNOWN_ADVERSE'
            save_fd(record_fd, RECORD, record)
            try:
                exit_code = wait_owned(process, WATCHDOG_SECONDS, waits)
            except subprocess.TimeoutExpired:
                timed_out = True
                errors.append('fixed2250-second parent watchdog expired')
                exit_code = stop_owned(process, bound, waits, actions)
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
        if process is not None and not any(type(row.get('exitCode')) is int for row in waits):
            try:
                exit_code = stop_owned(process, bound, waits, actions)
            except BaseException as cleanup_error:
                errors.append('parent cleanup ' + type(cleanup_error).__name__ + ': ' + str(cleanup_error))
    finally:
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)
        try:
            report = read_report(context, bound, exit_code)
            need(report['preparationEpochMonotonic']==record.get('preparationEpochMonotonic'),
                 'runner preparation epoch differs from actual enclosing parent')
            need(waits and waits[-1].get('timedOut') is False
                 and waits[-1].get('source')=='Popen.wait'
                 and 0 <= waits[-1]['completedMonotonic']-report['nestedEpochMonotonic'] <= 600,
                 'complete nested runtime through actual enclosing Popen.wait exceeded 600 seconds')
        except (ValueError, KeyError, TypeError, OSError) as error:
            errors.append('report delivery adverse: ' + type(error).__name__ + ': ' + str(error))
        # Even a later successful child report never repairs a watchdog refusal.
        delivered = not errors and not timed_out and report is not None and exit_code == 0
        terminal = dict(schema='aijade.ch7.nested-load-parent-terminal.v1',
            status='ENGINEERING_CONTROLLER_REPORTED_PASS_PENDING_INDEPENDENT_REPLAY' if delivered else 'ENGINEERING_PARENT_LAUNCH_ADVERSE',
            finishedAt=utc(), sourceCommit=context['passport']['sourceCommit'],
            passportSha256=digest(context['passportRaw']), launcherSha256=record['launcherSha256'],
            launchRecordPath=str(RECORD), launchRecordSha256=file_sha(RECORD),
            logPath=str(LOG), logSha256=file_sha(LOG) if LOG.is_file() else None,
            output=str(context['output']), parentProcess=parent, controllerProcess=bound,
            controllerPidFromPopen=process.pid if process is not None else None,
            actualParentWaitSource='Popen.wait' if waits else None, actualParentWaits=waits,
            controllerExitCode=exit_code, watchdogTimedOut=timed_out, watchdogActions=actions,
            elapsedSeconds=time.monotonic() - started, runnerReport=report,
            errors=errors, automaticRetries=0, engineeringReportDelivered=delivered,
            independentEngineeringReplayAccepted=False, wholeProcessGroupCleanupClaimed=False,
            table7_3='NOT_RUN', developmentComponentBasis=DEVELOPMENT_BASIS, **FALSE_GATES)
        try:
            save_new(TERMINAL, terminal)
        finally:
            os.close(record_fd)
    return terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--passport', type=Path, required=True)
    parser.add_argument('--passport-sha256', required=True, help='Externally frozen exact passport byte SHA256.')
    args = parser.parse_args()
    try:
        result = execute(args.passport, args.passport_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['engineeringReportDelivered'] else 2
    except (ValueError, KeyError, TypeError, OSError, psutil.Error) as error:
        print(json.dumps(dict(status='ENGINEERING_PRE_LAUNCH_REFUSED_NO_RETRY',
            error=type(error).__name__ + ': ' + str(error), automaticRetries=0,
            **FALSE_GATES), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
