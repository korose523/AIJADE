#!/usr/bin/env python3
"""Read-only replay of the single 2026-11-17 lifecycle qualification refusal.

Accepts a logical materialization of the original qualification directory. No
observer, native helper, socket, renderer, model or new window is invoked.
"""
import argparse
import copy
import gzip
import tempfile
import ast
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

Q = '0c42cc29c64730131466af6b079a900005713cba'
B = 'efbcfa0196cbc69bd24cad5b03f01b5078898b7b'
P = '9f3a5ead4ca63f489399907fe2e2a8d2aecbab68'
PLAN = 'experiments/plans/2026-11-17-ch7-mac-lifecycle-continuity.md'
PLAN_SHA = '1599aa06b81a4a8ea97a36e70f5a76aec5b70eb5c43f8e687c5addfaf5c35c72'
BUILD = 'experiments/ch7/mac-lifecycle-2026-11-17/frozen-build.json'
POLICY = 'configs/research/ch7-mac-lifecycle-process-policy.json'
RUN = Path('/Volumes/Untitled/AIJADE/.research/runs/ch7-lifecycle-20261117')
ORIGINAL_REPLAY_SHA = '0f47334b9aaf88447af4da3770f4848eefc655b039b93536df9427f09f7e3503'
TOOL_SHA = {'git':'7f30f076d0e9c38f772a76449fca9da8cf97f6a3d43b94c90a00e4f9ce7ad39e',
            'lsof':'ef5e67978fb8f8bcd32927789811462dd1b3773b8ad6322b67a491d2b5733b3a'}


def sha(raw):return hashlib.sha256(raw).hexdigest()
def file_sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()
def unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('duplicate JSON key')
        value[key]=item
    return value
def decode(raw):return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def read(path):return decode(path.read_bytes())
def rows(path):
    with path.open('rb') as stream:
        for line in stream:
            if line.strip():yield decode(line)
def need(ok,message):
    if not ok:raise ValueError(message)
def same(a,b,label):need(type(a) in (int,float) and type(b) in (int,float) and abs(a-b)<=.000001,label)
def canonical(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def git(repo,*args):return subprocess.check_output(['git',*args],cwd=repo)



_CACHE_STATS={'hits':0,'fresh':0}

def _sample(outer,policy,journal,receipt,guard,audit):
    observation=outer['processObservation'];ids=[]
    decision=guard.validate_observation(policy,observation,lifecycle_journal=journal)
    need(decision['status']==observation['status']=='PASS' and decision['blockers']==observation['blockers']==[],
         'raw process/API/collector decision adverse or differs')
    need(observation['ownedRoots']==observation['ownedProcesses']==[] and decision['ownedRssBytes']==outer['rssBytes']==0,
         'unloaded research-owned population/RSS differs')
    need(outer['processPolicySha256']==receipt['processPolicySha256'] and outer['observerSources']==receipt['observerSources'],
         'sample source/policy binding changed')
    audit._validate_sample(outer,policy,journal)
    view=observation['lifecycle'];need(not view.get('launchRefusalArtifacts',[]),'sample refusal artifact')
    raw_frames=audit._raw_frames(observation,policy)
    prefix_state=audit._replay(journal[:view['journalBytes']],Q,receipt['processPolicySha256'])
    need(len(prefix_state['events'])==view['lastSequence'] and sha(journal[:view['journalBytes']])==view['journalSha256'],
         'actual original journal prefix differs')
    for frame in raw_frames:
        lease_id=audit._native_lease(frame,prefix_state,view['controllerIdentity'],policy)
        ids.append(lease_id)
    api=observation['evidence']['api'];body=base64.b64decode(api['emptyBodyBase64'],validate=True)
    need(decode(body)=={'models':[]} and sha(body)==api['bodySha256'],'original sampled API body not explicitly empty')
    return dict(decision=decision,nativeLeaseIds=ids,sourceFrames=len(raw_frames),apiEmpty=True,prefixBytes=view['journalBytes'])

def run(args,cache=None):
    if cache is None:cache={}
    _CACHE_STATS.update(hits=0,fresh=0)
    root=args.root.resolve();repo=args.repo.resolve();output=args.output.resolve()
    need(not output.exists(),'never overwrite an earlier independent audit')
    output.parent.mkdir(parents=True,exist_ok=True)
    paths=sorted(p for p in root.rglob('*') if p.is_file())
    before={p.relative_to(root).as_posix():dict(sha256=file_sha(p),sizeBytes=p.stat().st_size) for p in paths}
    receipt=read(root/'receipt.json');preflight=read(root/'preflight-continuity.json')
    policy_raw=(root/'process-policy.json').read_bytes();policy=decode(policy_raw)
    journal=(root/'lifecycle-journal.jsonl').read_bytes();events=list(rows(root/'phase-events.jsonl'))
    need(receipt['codeCommit']==receipt['implementationCommit']==receipt['repositoryCommit']==Q,'measured Q identity')
    need(receipt['buildFreezeCommit']==B and receipt['executionPlanSha256']==PLAN_SHA,'B/plan receipt identity')
    need(sha(policy_raw)==receipt['processPolicySha256'] and policy_raw==git(repo,'show',Q+':'+POLICY),'exact Q policy bytes')
    need(sha(journal)==receipt['lifecycleJournalSha256'] and len(journal)==receipt['lifecycleJournalBytes'],'complete final journal bytes')
    need(sha((repo/PLAN).read_bytes())==PLAN_SHA and git(repo,'show',P+':'+PLAN)==(repo/PLAN).read_bytes(),'public plan bytes')
    source_proofs=[]
    for name,expected in receipt['observerSources'].items():
        raw=(repo/name).read_bytes()
        need(sha(raw)==expected and raw==git(repo,'show',Q+':'+name),'frozen Q source differs: '+name)
        source_proofs.append(dict(path=name,sha256=expected))
    build_raw=git(repo,'show',B+':'+BUILD);build=decode(build_raw)
    need(build['commit']==Q and build['assemblyInformationalVersion']=='0.1.0+'+Q,'actual build implementation')
    need(build['observerSources']==receipt['observerSources'],'B observer source bindings')
    if args.build_manifest:
        need(args.build_manifest.read_bytes()==build_raw,'materialized B metadata differs from Git object')
    sys.path.insert(0,str(repo/'experiments/ch7'))
    import mac_process_guard_v3 as guard
    import lifecycle_audit as audit
    need(file_sha(Path(guard.__file__))==receipt['observerModuleSha256'],'loaded frozen observer')
    need(file_sha(Path(audit.__file__))==receipt['observerSources']['experiments/ch7/lifecycle_audit.py'],'loaded frozen independent auditor')
    state=audit._replay(journal,Q,receipt['processPolicySha256'])
    need(not state['launchRefusals'],'launch refusal remains adverse')
    finite=[v for v in state['leases'].values() if v['role']=='finite']
    need(all(v['releaseSeq'] is not None and v['waitSeq'] is not None and v['exitCode']==0
             and v['absence']['witnessKind']=='PARENT_WAIT_REAPED' for v in finite),'unresolved/nonzero managed task')
    need(all(s['closeSeq'] is not None for s in state['scopes'].values()),'unclosed controller scope')
    need(not state['discovered'],'unexpected discovered research descendant in unloaded phase')
    fallback_paths=set(root.glob('launch-refused-*.json'))
    original_journal=Path(receipt['lifecycleJournalPath'])
    # On the physical run, also inspect the exact original journal directory.
    # A portable materialized packet is checked by its enclosing archive closure.
    if original_journal.parent==root.parent:
        fallback_paths.update(original_journal.parent.glob('launch-refused-*.json'))
    need(not fallback_paths,'fallback launch-refusal artifact exists')
    need(all(v.get('identityWitnessKind')=='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD'
             and v['shimSha256']==policy['lifecycle']['execShimSha256'] for v in finite),'parent kernel/shim identity witness')
    listener_function=next(n for n in ast.parse((repo/'experiments/ch7/mac_process_guard_v3.py').read_text()).body
                           if isinstance(n,ast.FunctionDef) and n.name=='_read_listeners')
    listener_commands=[ast.literal_eval(n) for n in ast.walk(listener_function) if isinstance(n,ast.List)
                       and n.elts and isinstance(n.elts[0],ast.Constant) and n.elts[0].value=='/usr/sbin/lsof']
    need(len(listener_commands)==1,'unique source-bound listener command')
    native_cmd=sha(canonical([policy['nativeHelper']['path']]))
    listener_cmd=sha(canonical(listener_commands[0]))
    roles=Counter();unclassified=[]
    for lease in finite:
        if lease['stageId']=='observer-native-census':
            need(lease['commandSha256']==native_cmd and lease['executableSha256']==policy['nativeHelper']['sha256'],'native source-bound command')
            roles['native']+=1
        elif lease['commandSha256']==listener_cmd:
            need(lease['executableSha256']==TOOL_SHA['lsof'],'listener executable identity anchor')
            roles['listener']+=1
        elif lease['executableSha256']==TOOL_SHA['git']:
            roles['git']+=1
        else:
            unclassified.append(lease['leaseId'])
    need(not unclassified,'unclassified managed preflight executable')
    observations=[];decisions=Counter();api_empty=0;native_ids=set();prefix_previous=-1;source_frames=0
    started=time.monotonic();replay_errors=[]
    for index,outer in enumerate(rows(root/'settling/telemetry.jsonl')):
        observations.append(outer);observation=outer['processObservation']
        try:
            key=sha(canonical(dict(outer=outer,actualFullJournalSha256=sha(journal),
                actualPrefixSha256=sha(journal[:outer['processObservation']['lifecycle']['journalBytes']]),
                actualPolicySha256=sha(policy_raw),actualSources=source_proofs,
                adapterSha256=file_sha(Path(__file__)),originalReplaySourceSha256=ORIGINAL_REPLAY_SHA)))
            if key in cache:
                evaluated=copy.deepcopy(cache[key]);_CACHE_STATS['hits']+=1
            else:
                evaluated=_sample(outer,policy,journal,receipt,guard,audit)
                cache[key]=copy.deepcopy(evaluated);_CACHE_STATS['fresh']+=1
            decision=evaluated['decision'];decisions[decision['status']]+=1
            need(evaluated['prefixBytes']>=prefix_previous,'single unloaded scope prefix reversal')
            prefix_previous=evaluated['prefixBytes']
            for lease_id in evaluated['nativeLeaseIds']:
                need(lease_id not in native_ids,'reused native capture lease');native_ids.add(lease_id)
            source_frames+=evaluated['sourceFrames'];api_empty+=int(evaluated['apiEmpty'])
        except Exception as error:
            replay_errors.append(dict(index=index,sampleId=outer.get('sampleId'),error=type(error).__name__+': '+str(error),traceback=traceback.format_exc()))
        if (index+1)%25==0 or index==293:
            print(json.dumps(dict(stage='FULL_RAW_REPLAY',completed=index+1,errors=len(replay_errors),seconds=time.monotonic()-started)),flush=True)
    checkpoint=dict(schema='aijade.ch7.lifecycle-independent-replay-checkpoint.v1',
        inputFiles=before,sourceProofs=source_proofs,rawRows=len(observations),decisions=dict(decisions),apiEmpty=api_empty,
        nativeCaptureLeases=len(native_ids),sourceFrames=source_frames,errors=replay_errors,roleCounts=dict(roles),
        journalEvents=len(state['events']),finiteLeases=len(finite))
    checkpoint_path=output.with_name(output.stem+'-raw-replay-checkpoint.json')
    need(not checkpoint_path.exists(),'retain previous complete replay checkpoint')
    checkpoint_path.write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2)+'\n')
    need(not replay_errors,'raw replay errors preserved in checkpoint')
    # Invoke the frozen acceptance auditor on ALL original rows, without changing
    # idle roots into runtime roots. Its expected domain refusal is retained.
    try:
        accepted=audit.verify_lifecycle(journal,observations,source_commit=Q,policy_sha256=receipt['processPolicySha256'],
            policy=policy,controller=receipt['controllerProcess'])
        runtime_predicate=dict(status='UNEXPECTED_ACCEPTANCE',result=accepted)
    except Exception as error:
        runtime_predicate=dict(status='FROZEN_PREDICATE_REFUSAL',error=type(error).__name__+': '+str(error),
            traceback=traceback.format_exc(),sourceSha256=file_sha(Path(audit.__file__)))
        print(runtime_predicate['traceback'],flush=True)
    need(runtime_predicate['status']=='FROZEN_PREDICATE_REFUSAL'
         and 'runtime must have one exact local persistent root' in runtime_predicate['error'],
         'unexpected frozen lifecycle-auditor result; preserve original error')
    phase=preflight['phases']['settling'];origin=phase['phaseClock']['startMonotonic'];deadline=origin+600
    need(set(preflight['phases'])=={'settling'} and preflight['status']=='PREFLIGHT_REFUSED','unexpected phase population/status')
    need(len(events)==len(observations)+1 and events[0]['event']=='phase-enter','complete partial event population')
    need(events[0]['actualStartMonotonic']==events[0]['monotonicSeconds']==origin,'actual phase origin')
    starts=[];completes=[];written=[];lateness=[];ids=set();stream=Counter()
    for index,outer in enumerate(observations):
        need(type(outer['globalIndex']) is int and outer['globalIndex']==index and outer['phase']=='settling','original slot/phase identity')
        need(outer['sampleId'] not in ids and outer['sampleId']==outer['processObservation']['sampleId'],'original sample IDs')
        ids.add(outer['sampleId']);at=outer['monotonicSeconds'];completed=outer['observationCompletedMonotonic']
        same(outer['globalScheduledMonotonic'],origin+index*2,'original global schedule altered')
        same(outer['scheduledSeconds'],index*2,'original local schedule altered')
        same(outer['elapsedSeconds'],at-origin,'original local elapsed differs')
        same(outer['observationDurationSeconds'],completed-at,'actual observation duration differs')
        event=events[index+1]
        need(event['schema']=='aijade.ch7.phase-continuity-event.v1' and event['eventIndex']==index+1
             and event['event']=='sample-written' and event['globalIndex']==index and event['sampleId']==outer['sampleId']
             and event['phase']=='settling','actual sample/writer event binding')
        for key in ['writerStartedMonotonic','validatorStartedMonotonic','validatorCompletedMonotonic']:
            same(event[key],outer[key],'writer event/raw actual time differs')
        same(event['monotonicSeconds'],event['writerCompletedMonotonic'],'actual writer completion differs')
        need(origin<=at<=completed<=outer['validatorStartedMonotonic']<=outer['validatorCompletedMonotonic']
             <=outer['writerStartedMonotonic']<=event['writerCompletedMonotonic'],'actual original processing chronology')
        need(not starts or at>starts[-1],'actual sample order')
        need(not written or written[-1]<=at,'single-scope actual observation/write overlap')
        starts.append(at);completes.append(completed);written.append(event['writerCompletedMonotonic'])
        lateness.append(at-outer['globalScheduledMonotonic']);stream[outer['streamValidationStatus']]+=1
    gaps=[b-a for a,b in zip(starts,starts[1:])]
    need(all(0<gap<=3 for gap in gaps),'actual adjacent raw sample gap exceeds frozen3seconds')
    validated=[r for r in observations if r['streamValidationStatus']=='PASS']
    refused=[r for r in observations if r['streamValidationStatus']!='PASS']
    need(len(refused)==1 and refused[0] is observations[-1] and completes[-1]>deadline
         and all(t<=deadline for t in completes[:-1]),'last deadline refusal differs from raw evidence')
    need(refused[0]['streamValidationStatus']=='REFUSED'
         and refused[0]['streamValidationError']=='ValueError: raw observation completed after the fixed phase deadline',
         'actual refusal reason changed')
    need(phase['samples']==len(observations) and phase['validatedSamples']==len(validated)
         and phase['expectedSamples']==300 and preflight['samples']==len(observations)
         and preflight['validatedSamples']==len(validated),'partial aggregate count differs')
    need(phase['phaseClock']['endMonotonic'] is None and phase['elapsedSeconds'] is None
         and phase['coverage']['coverageComplete'] is False and preflight['runtimeHandoffAnchor'] is None,'partial phase falsely completed')
    same(phase['coverage']['maximumGapSeconds'],max(gaps),'recorded coverage gap differs')
    same(phase['coverage']['lastElapsedSeconds'],starts[-1]-origin,'recorded last sample differs')
    same(preflight['refusedAtMonotonic'],written[-1]+(preflight['refusedAtMonotonic']-written[-1]),'finite refusal clock')
    need(written[-1]<=preflight['refusedAtMonotonic']<=state['events'][-1]['monotonicSeconds'],'terminal refusal/close chronology')
    need(phase['minimumAvailableBytes']==min(r['availableBytes'] for r in validated)
         and phase['swapRangeBytes']==max(r['swapUsedBytes'] for r in validated)-min(r['swapUsedBytes'] for r in validated),
         'stream-accepted resource aggregate differs')
    admission=list(rows(root/'admission/telemetry.jsonl'))
    need(not admission and not any(e.get('phase')=='admission' or e.get('toPhase')=='admission' for e in events),'admission unexpectedly started')
    need(receipt['status']=='STOPPED_PRE_BLOCK' and receipt['measurementStarted'] is False
         and not receipt['blocks'] and receipt['completedBlocks']==receipt['completedConditionRows']==0,'runtime/block scope differs')
    need(not receipt['unknownCaseIds'] and not receipt['inFlightCaseIds'] and receipt['modelRequests']==0,'condition dispositions differ')
    input_dir=args.inputs.resolve() if args.inputs else next((p for p in [root.parent/'inputs',RUN/'qualification-inputs'] if p.is_dir()),None)
    need(input_dir is not None,'explicit known input directory required')
    manifest=read(input_dir/'runtime-manifest.json')
    planned=[c['input']['caseId']+'/'+arm for c in manifest['cases'] for arm in c['input']['conditions']]
    need(manifest['purpose']=='qualification_only' and manifest['constructionFreezeCommit']==Q
         and len(manifest['cases'])==10 and planned==receipt['unattemptedCaseIds'],'actual known input/disposition population differs')
    need(not list(root.glob('block-*')),'block output unexpectedly exists')
    numbers=dict(samples=len(observations),validatedSamples=len(validated),refusedSamples=len(refused),expectedSamples=300,
        missingExpectedSamples=300-len(observations),settlingRequestedSeconds=600,
        observerPassSamples=decisions['PASS'],observerUnknownSamples=decisions['UNKNOWN'],observerFailSamples=decisions['FAIL'],
        firstStart=starts[0]-origin,lastStart=starts[-1]-origin,lastCompleted=completes[-1]-origin,
        finalNominal=observations[-1]['scheduledSeconds'],finalLateness=lateness[-1],maximumScheduledStartLateness=max(lateness),
        scheduledStartLatenessOver3Samples=sum(x>3 for x in lateness),maximumGapSeconds=max(gaps),
        lastDeadlineOverrunSeconds=completes[-1]-deadline,terminalRefusalElapsedSeconds=preflight['refusedAtMonotonic']-origin,
        settlingMinimumAvailableBytes=min(r['availableBytes'] for r in observations),
        acceptedMinimumAvailableBytes=min(r['availableBytes'] for r in validated),
        settlingSwapMinimumBytes=min(r['swapUsedBytes'] for r in observations),settlingSwapMaximumBytes=max(r['swapUsedBytes'] for r in observations),
        settlingSwapRangeBytes=max(r['swapUsedBytes'] for r in observations)-min(r['swapUsedBytes'] for r in observations),
        maximumObservationDurationSeconds=max(r['observationDurationSeconds'] for r in observations),
        maximumIdleResearchOwnedRssBytes=max(r['rssBytes'] for r in observations),
        apiExplicitEmptySamples=api_empty,nativeCaptures=source_frames,managedNativeLeases=roles['native'],
        listenerLeases=roles['listener'],gitPreflightLeases=roles['git'],journalEvents=len(state['events']),
        managedFiniteLeases=len(finite),actualParentWaitZero=sum(v['exitCode']==0 for v in finite),
        controllerScopes=len(state['scopes']),closedControllerScopes=sum(v['closeSeq'] is not None for v in state['scopes'].values()),
        launchRefusals=len(state['launchRefusals']),fallbackRefusalArtifacts=len(fallback_paths),
        admissionSamples=len(admission),plannedKnownPairs=len(manifest['cases']),plannedConditionRows=len(planned),
        completedConditionRows=0,unknownConditionRows=0,unattemptedConditionRows=len(planned),completedBlocks=0,
        rendererSessions=0,modelRequests=0,freshHeldoutCases=0)
    after={p.relative_to(root).as_posix():dict(sha256=file_sha(p),sizeBytes=p.stat().st_size) for p in sorted(root.rglob('*')) if p.is_file()}
    need(before==after,'original terminal artifact bytes changed during independent replay')
    need(all(file_sha(repo/row['path'])==row['sha256'] for row in source_proofs),'frozen source changed during replay')
    scope=dict(terminalRecordIntegrityAccepted=True,settlingCompleted=False,admissionStarted=False,qualificationStarted=False,
        fullFiniteDriverQualified=False,formalHardwareQualification=False,heldoutComparisonComplete=False,
        independentHumanReview=False,currentProductInheritsResearchQualification=False,freshHeldoutCases=0,
        constructionSeedCreated=False,table7_3='NOT_RUN')
    report=dict(schema='aijade.ch7.mac-lifecycle-refusal-audit.v1',status='INDEPENDENT_TERMINAL_REFUSAL_AUDIT_PASS',
        checkedAt=datetime.now(timezone.utc).isoformat(),sourceCommit=Q,buildFreezeCommit=B,planCommit=P,planSha256=PLAN_SHA,
        numbers=numbers,scope=scope,inputFiles=before,inputFileTableSha256=sha(canonical(before)),
        sourceProofs=source_proofs,buildManifestSha256=sha(build_raw),policySha256=sha(policy_raw),
        knownInputs=[dict(path=str(p),sha256=file_sha(p)) for p in sorted(input_dir.glob('*.json'))],
        frozenRuntimeAuditor=runtime_predicate,rawReplayCheckpoint=dict(path=str(checkpoint_path),sha256=file_sha(checkpoint_path)),
        interpretation=['All294 original process/native/API samples replay PASS. The final sample is rejected by the fixed600second completion deadline; this is not a collector FAIL.',
        'Only293 samples were streaming-validated;294raw observations do not meet the required300. No phase-end receipt or admission transition is invented.',
        'Actual adjacent start gaps remain<=3seconds, while the fixed nominal2second grid accumulates lateness. This separate diagnostic is preserved, not substituted for the recorded terminal cause.',
        'Settling resource/API figures describe sampled settling only. They are neither admission acceptance nor continuous whole-machine inactivity or hardware reliability.',
        'The frozen verify_lifecycle runtime acceptance API requires a persistent runtime root and rejects the unchanged unloaded roots. Original error and source SHA are retained; idle evidence integrity was separately replayed in full.',
        'All20 known conditions remain unattempted. No renderer, model request, fresh case, construction seed, heldout result or successful qualification is inferred.'],
        limitations=['No independent human review; this is AI-assisted deterministic raw replay.',
        'Native/Git/listener waits are engineering identity/cleanup evidence, not successful scientific trajectories.',
        'Portable archive callers must materialize exact logical bytes and supply frozen Q sources/known inputs; no raw or verifier changes are made.'],
        noNewObservation=True,noRetry=True,originalBytesUnchanged=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],output=str(output),sha256=file_sha(output),numbers=numbers),ensure_ascii=False,indent=2),flush=True)
    return 0


def audit_terminal(*,root,repo,cache):
    """Materialize exactly one logical representation; no live service access."""
    root=Path(root);manifest=read(root/'packet-manifest.json')
    with tempfile.TemporaryDirectory(prefix='.terminal-replay-',dir=root.parent) as scratch:
        scratch=Path(scratch);logical=scratch/'qualification';logical.mkdir()
        for row in manifest['files']:
            rel=row['path']
            if not rel.startswith('qualification/'):continue
            destination=logical/rel[len('qualification/'):].removesuffix('.gz')
            destination.parent.mkdir(parents=True,exist_ok=True)
            need(not destination.exists(),'duplicate logical archive entry')
            opener=gzip.open if rel.endswith('.gz') else open
            with opener(root/rel,'rb') as stream:body=stream.read(512*1024*1024+1)
            need(len(body)<=512*1024*1024,'logical qualification byte cap')
            destination.write_bytes(body)
        output=scratch/'results'/'terminal-replay.json'
        args=argparse.Namespace(root=logical,repo=Path(repo),output=output,
            inputs=root/'inputs',build_manifest=root/'publication'/'frozen-build.json')
        try:
            run(args,cache=cache)
        except Exception as error:
            checkpoint=output.with_name(output.stem+'-raw-replay-checkpoint.json')
            if checkpoint.is_file():
                error.terminalReplayFailure=read(checkpoint)
            raise
        result=read(output)
        return dict(terminalRecordIntegrityAccepted=result['scope']['terminalRecordIntegrityAccepted'],
            fullQualified=result['scope']['fullFiniteDriverQualified'],independentReplay=result,
            cache=dict(_CACHE_STATS),originalReplaySourceSha256=ORIGINAL_REPLAY_SHA,
            adapterSha256=file_sha(Path(__file__)),noNewObservation=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--inputs',type=Path)
    parser.add_argument('--build-manifest',type=Path)
    try:raise SystemExit(run(parser.parse_args()))
    except Exception:
        traceback.print_exc();raise SystemExit(1)
