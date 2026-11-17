#!/usr/bin/env python3
"""Metadata-only compatibility amendment; reuse the sole compiled dummy."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time

BASE = Path('/Volumes/Untitled/AIJADE')
ROOT = BASE / '.research/runs/ch7-prefix-20261117/dummy-exec-diagnostic-01'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata(m, command, prefix):
    started = time.monotonic()
    unknown = None
    try:
        result = subprocess.run(command, capture_output=True, timeout=10, check=False)
        stdout, stderr, code, timeout = result.stdout, result.stderr, result.returncode, False
        if code != 0:
            unknown = 'NONZERO_READ_ONLY_METADATA_COMMAND'
    except subprocess.TimeoutExpired as error:
        stdout, stderr, code, timeout = error.stdout or b'', error.stderr or b'', None, True
        unknown = 'READ_ONLY_METADATA_TIMEOUT'
    except OSError as error:
        stdout, stderr, code, timeout = b'', b'', None, False
        unknown = type(error).__name__
    value = dict(command=command, timeoutSeconds=10, startedMonotonic=started,
        completedMonotonic=time.monotonic(), exitCode=code, timedOut=timeout,
        status='UNKNOWN_METADATA' if unknown else 'READ_ONLY_METADATA_READ_COMPLETE',
        unknownReason=unknown, stdout=m.serial(stdout), stderr=m.serial(stderr),
        securityAttributesModified=False)
    m.new(ROOT/(prefix+'.stdout.raw'), stdout)
    m.new(ROOT/(prefix+'.stderr.raw'), stderr)
    m.write(ROOT/(prefix+'.json'), value)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--amendment', type=Path, required=True)
    parser.add_argument('--amendment-sha256', required=True)
    args=parser.parse_args()
    need(args.amendment == ROOT/'metadata-compatibility-amendment.json', 'fixed amendment path')
    need(file_sha(args.amendment) == args.amendment_sha256, 'amendment bytes changed')
    amendment=json.loads(args.amendment.read_bytes())
    need(file_sha(Path(__file__)) == amendment['compatibilityScriptSha256'], 'compatibility source changed')
    original=ROOT/'run-diagnostic.py'
    need(file_sha(original) == amendment['originalScriptSha256']
         and file_sha(ROOT/'plan.json') == amendment['originalPlanSha256'], 'original frozen files changed')
    spec=importlib.util.spec_from_file_location('_frozen_original_dummy_diagnostic', original)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    need(Path(sys.executable).absolute() == m.PYTHON, 'original SDK entry required')
    source=m.ARTIFACTS/'fake-native-helper.c';helper=m.ARTIFACTS/'fake-native-helper'
    need(file_sha(source)==amendment['compiledSourceSha256'] and file_sha(helper)==amendment['compiledHelperSha256'],
         'only the already compiled original helper is authorized')
    need(file_sha(ROOT/'compile.json')==amendment['compileReceiptSha256'], 'single compilation evidence changed')
    need(not (ROOT/'binary-manifest.json').exists()
         and not any((m.ARTIFACTS/('trial-'+str(i))).exists() for i in (1,2,3)), 'dummy sequence already started; never retry')
    plan=json.loads((ROOT/'plan.json').read_bytes())
    before={name:file_sha(m.REPO/name) for name in m.MODULES}
    need(before==plan['sourceFiles'], 'production source changed before fixed sequence')
    m.write(ROOT/'compatibility-started.json', dict(status='RESUME_METADATA_PREPARATION_BEFORE_FIRST_HELPER_EXECUTION',
        at=datetime.now(timezone.utc).isoformat(), amendmentSha256=args.amendment_sha256,
        compilationAttempts=1, helperExecutionsSoFar=0, automaticRetries=0))
    attrs=metadata(m, ['/usr/bin/xattr','-l',str(helper)], 'xattr-readonly-before')
    codesign=metadata(m, ['/usr/bin/codesign','--display','--verbose=4',str(helper)], 'codesign-readonly')
    item=helper.stat()
    manifest=dict(schema='aijade.ch7.dummy-native-binary-freeze.v1',
        status='ONE_COMPILED_DUMMY_FROZEN_BEFORE_FIRST_EXECUTION',
        at=datetime.now(timezone.utc).isoformat(), sourceCommit=m.SOURCE_COMMIT,
        planSha256=amendment['originalPlanSha256'], scriptSha256=amendment['originalScriptSha256'],
        metadataCompatibilityAmendmentSha256=args.amendment_sha256,
        compatibilityScriptSha256=file_sha(Path(__file__)),
        helperSourcePath=str(source), helperSourceSha256=file_sha(source), helperPath=str(helper),
        helperSha256=file_sha(helper), helperBytes=item.st_size, helperMode=stat.S_IMODE(item.st_mode),
        helperDevice=item.st_dev, helperInode=item.st_ino, compileReceiptSha256=file_sha(ROOT/'compile.json'),
        compilationAttempts=1, xattrReadOnlyReceiptSha256=file_sha(ROOT/'xattr-readonly-before.json'),
        codesignReadOnlyReceiptSha256=file_sha(ROOT/'codesign-readonly.json'), sourceFiles=before,
        helperExecutionsBeforeFreeze=0, changedSecurityAttributes=False,
        signedOrResignedByDiagnostic=False, prewarmed=False,
        priorPreparationFailure='AttributeError: fixed SDK os has no listxattr; initial script stopped before manifest/trials.')
    m.write(ROOT/'binary-manifest.json', manifest)
    manifest_sha=file_sha(ROOT/'binary-manifest.json')
    sys.path.insert(0,str(m.REPO/'experiments/ch7'))
    import process_lifecycle as life
    import mac_process_guard_v3 as guard
    need(guard.NATIVE_TIMEOUT==0.5, 'native deadline must remain0.5')
    trials=[];intervals=[]
    for index in (1,2,3):
        if index>1:
            began=time.monotonic();time.sleep(1)
            intervals.append(dict(beforeTrial=index,requestedSeconds=1,startedMonotonic=began,completedMonotonic=time.monotonic()))
        need(file_sha(helper)==manifest['helperSha256'] and file_sha(source)==manifest['helperSourceSha256'], 'frozen dummy changed')
        trial_root=m.ARTIFACTS/('trial-'+str(index));trial_root.mkdir()
        registry=result=coordination=final=state=None
        errors=[];launch_calls=[];call_start=call_end=None
        trial_start=time.monotonic()
        try:
            own=life.identity()
            registry=life.Registry(trial_root/'lifecycle-journal.jsonl',
                [(own['pid'],own['createTimeMicros']/1000000)], stage='dummy-exec-diagnostic-trial-'+str(index),
                source_commit=m.SOURCE_COMMIT,policy_sha256=amendment['originalPlanSha256'],capture_lock_path=trial_root/'capture.lock')
            original_launch=registry.launch

            def timed_launch(*arguments,**keywords):
                record=dict(startedMonotonic=time.monotonic())
                try:
                    handle=original_launch(*arguments,**keywords)
                    record['returnedHandle']=True
                    return handle
                except BaseException as error:
                    record.update(returnedHandle=False,errorClass=type(error).__name__);raise
                finally:
                    record['completedMonotonic']=time.monotonic()
                    record['durationSeconds']=record['completedMonotonic']-record['startedMonotonic']
                    launch_calls.append(record)

            registry.launch=timed_launch
            with life.capture_lock(registry.lock_path) as coordination:
                call_start=time.monotonic();result=guard._run_native(helper,registry);call_end=time.monotonic()
        except BaseException as error:
            call_end=time.monotonic();errors.append(dict(phase='dummy-call',errorClass=type(error).__name__,error=str(error)))
        finally:
            if registry is not None:
                try:final=registry.final()
                except BaseException as error:errors.append(dict(phase='final',errorClass=type(error).__name__,error=str(error)))
                try:registry.close()
                except BaseException as error:errors.append(dict(phase='close',errorClass=type(error).__name__,error=str(error)))
                raw=registry.path.read_bytes();m.new(ROOT/('trial-'+str(index)+'.journal.jsonl'),raw)
                try:state=life.replay_journal(raw)
                except BaseException as error:errors.append(dict(phase='cold-journal-replay',errorClass=type(error).__name__,error=str(error)))
            else:raw=b''
        accepted=(not errors and result is not None and result.get('exitCode')==0 and result.get('cleanupKnown') is True
            and result.get('timedOut') is False and result.get('oversized') is False and result.get('stdout')==m.EXPECTED_STDOUT
            and result.get('stderrBytes')==0 and result.get('durationSeconds',float('inf'))<=0.5 and len(launch_calls)==1
            and final is not None and final.get('status')=='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT'
            and state is not None and len(state['leases'])==2 and not state['launchRefusals'])
        entry=dict(schema='aijade.ch7.dummy-native-exec-trial.v1',index=index,
            status='DUMMY_NATIVE_PLUMBING_PASS' if accepted else 'DUMMY_NATIVE_PLUMBING_REFUSED',
            trialStartedMonotonic=trial_start,callStartedMonotonic=call_start,callCompletedMonotonic=call_end,
            trialCompletedMonotonic=time.monotonic(),nativeDeadlineSeconds=0.5,manifestSha256=manifest_sha,
            helperSha256=file_sha(helper),captureLock=coordination,nativeResult=m.serial(result),
            launchCallTiming=launch_calls,registryFinal=m.serial(final),journalPath=str(trial_root/'lifecycle-journal.jsonl'),
            journalSha256=m.sha(raw),journalBytes=len(raw),journalEvents=len(state['events']) if state else None,
            exactJournalEvents=state['events'] if state else None,errors=errors,stderrPayloadAvailable=False,
            stderrLimit='Original primitive retains stderr count only; compiler/codesign stderr complete.',
            actualSysctlCensus=False,guardObserveInvoked=False,qualification=False)
        m.write(ROOT/('trial-'+str(index)+'.json'),entry);trials.append(entry)
    after_attrs=metadata(m,['/usr/bin/xattr','-l',str(helper)],'xattr-readonly-after')
    after={name:file_sha(m.REPO/name) for name in m.MODULES}
    compile_receipt=json.loads((ROOT/'compile.json').read_bytes())
    summary=dict(schema='aijade.ch7.dummy-native-exec-diagnostic.v1',
        status='THREE_DUMMY_TRIALS_COMPLETE_WITH_REFUSALS' if any(t['status']!='DUMMY_NATIVE_PLUMBING_PASS' for t in trials)
            else 'THREE_DUMMY_PLUMBING_TRIALS_PASS_NOT_QUALIFICATION',checkedAt=datetime.now(timezone.utc).isoformat(),
        sourceCommit=m.SOURCE_COMMIT,planSha256=amendment['originalPlanSha256'],
        originalScriptSha256=amendment['originalScriptSha256'],compatibilityAmendmentSha256=args.amendment_sha256,
        compatibilityScriptSha256=file_sha(Path(__file__)),binaryManifestSha256=manifest_sha,
        helperSha256=file_sha(helper),helperSourceSha256=file_sha(source),
        sourceFilesBefore=before,sourceFilesAfter=after,productionSourceUnchanged=before==after,
        compilationAttempts=1,plannedTrials=3,trialsAttempted=len(trials),intervalSleeps=intervals,nativeDeadlineSeconds=0.5,
        compiledBinaryAgeAtFirstCallSeconds=trials[0]['callStartedMonotonic']-compile_receipt['completedMonotonic'] if trials[0]['callStartedMonotonic'] else None,
        outcomes=[dict(index=t['index'],status=t['status'],nativeResult=t['nativeResult'],launchCallTiming=t['launchCallTiming'],
            journalSha256=t['journalSha256'],errors=t['errors']) for t in trials],
        readOnlyMetadataStatuses=dict(xattrBefore=attrs['status'],codesign=codesign['status'],xattrAfter=after_attrs['status']),
        priorPreparationFailures=[dict(errorClass='AttributeError',operation='os.listxattr',helperExecutions=0,compilations=1)],
        automaticRetries=0,prewarmExecutions=0,securityAttributeMutations=0,engineeringFullLoadStarted=False,
        qualificationStarted=False,actualCensusCalls=0,guardObserveCalls=0,lsofCalls=0,apiCalls=0,
        modelRequests=0,rendererCalls=0,freshCases=0,causalFirstExecutionEffectEstablished=False,
        interpretation='One frozen compile, metadata compatibility pause before first helper execution, and three fixed-order dummy calls. Preparation delay and metadata/cache effects are confounded; no causal Mach-O or syspolicyd claim and no erasure of prior suite refusals.')
    if before!=after or file_sha(helper)!=manifest['helperSha256']:summary['status']='DUMMY_DIAGNOSTIC_IDENTITY_CHANGED_ADVERSE'
    m.write(ROOT/'summary.json',summary)
    print(json.dumps(dict(status=summary['status'],summary=str(ROOT/'summary.json'),
        outcomes=[dict(index=t['index'],status=t['status'],durationSeconds=t['nativeResult'].get('durationSeconds') if t['nativeResult'] else None,
            exitCode=t['nativeResult'].get('exitCode') if t['nativeResult'] else None,
            timedOut=t['nativeResult'].get('timedOut') if t['nativeResult'] else None) for t in trials]),indent=2))
    return 0 if summary['status']=='THREE_DUMMY_PLUMBING_TRIALS_PASS_NOT_QUALIFICATION' else 2


if __name__=='__main__':
    raise SystemExit(main())
