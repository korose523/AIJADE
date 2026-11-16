#!/usr/bin/env python3
"""Offline replay of the one refused Mac settling attempt; never launches a study.

Usage: python3 -B mac_formal_refusal_audit.py --root packet --repo LOCAL_GIT --controls
Q/B/plan objects must already exist locally. --content-only supports collection
before packet-manifest.json is finalized and does not claim packet integrity.
No service, model, renderer, process inspection or credential request is made.
"""
import argparse
import base64
from collections import Counter
import copy
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

Q='fe0fa07c655224fdeed32556cd31ce4022126037'
B='795b23d7e69a8b59396b84199bd7429451ecbb4f'
P='0c3f3cc922e940c97628837476946526659d936e'
PLAN='experiments/plans/2026-11-16-ch7-mac-formal-backend.md'
PLAN_SHA='ca53a7df038b413bbefc6ca56195e16183620777d0391893b6419b21975bdfa2'
BUILD='experiments/ch7/mac-formal-2026-11-16/frozen-build.json'
BUILD_SHA='a3ba1aa6ebfc93a8ec5132570931fbe45e17193ccfc93e6ec3a0a0fddf71fc38'
POLICY='configs/research/ch7-mac-process-policy.json'
OBSERVER='experiments/ch7/mac_process_guard.py'
POLICY_SHA='6c677d370a0d86c52b63c4f37af171f3f2f88b344e9743c59a4d8ebc70d0d659'
OBSERVER_SHA='be8df86b47f382f663eab4f22553025a41661326695d112cfc30ffbe1c677d87'
MANIFEST='packet-manifest.json'
MANIFEST_SCHEMA='aijade.ch7.mac-formal-packet-manifest.v1'
RAW_FILES={'qualification/receipt.json','qualification/process-policy.json',
           'qualification/settling/receipt.json','qualification/settling/telemetry.jsonl'}
SCOPE=dict(admissionStarted=False,qualificationStarted=False,fullFiniteDriverQualified=False,
           heldoutComparisonComplete=False,freshHeldoutCases=0,table7_3='NOT_RUN',
           formalHardwareQualification=False,independentHumanReview=False)
_GIT_CACHE={}


def need(value,message):
    if not value:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    value={}
    for name,item in pairs:
        need(name not in value,'duplicate JSON key');value[name]=item
    return value


def decode(raw):return json.loads(raw,object_pairs_hook=unique)


def relative(path):
    need(type(path) is str and path and not path.startswith('/') and '\\' not in path and ':' not in path,'unsafe packet path')
    need(all(part not in ('','.','..') and not any(ord(c)<32 for c in part) for part in path.split('/')),'unsafe packet path')
    return path


def utc(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    need(result.tzinfo is not None,'missing timezone');return result.timestamp()


class Access:
    def __init__(self,root,overrides=None):self.root=Path(root).resolve();self.overrides=overrides or {}
    def names(self):
        names=set()
        for path in self.root.rglob('*'):
            need(not path.is_symlink(),'packet symlink is prohibited')
            if path.is_file():names.add(path.relative_to(self.root).as_posix())
        for path,data in self.overrides.items():
            relative(path)
            if data is None:names.discard(path)
            else:names.add(path)
        return names
    def stored(self,path):
        relative(path)
        if path in self.overrides:
            need(self.overrides[path] is not None,'missing packet file: '+path);return self.overrides[path]
        target=self.root/path
        need(target.is_file() and not target.is_symlink(),'missing packet file: '+path)
        return target.read_bytes()
    def raw(self,path):
        names=self.names() if path in self.overrides or path+'.gz' in self.overrides else None
        direct=(path in names) if names is not None else (self.root/path).is_file()
        compressed=(path+'.gz' in names) if names is not None else (self.root/(path+'.gz')).is_file()
        need(direct != compressed,'missing or ambiguous logical packet file: '+path)
        return self.stored(path) if direct else gzip.decompress(self.stored(path+'.gz'))
    def json(self,path):return decode(self.raw(path))


def git(repo,commit,path):
    relative(path);key=(str(Path(repo).resolve()),commit,path)
    if key not in _GIT_CACHE:
        _GIT_CACHE[key]=subprocess.check_output(['git','show',commit+':'+path],cwd=repo,stderr=subprocess.DEVNULL)
    return _GIT_CACHE[key]


def guard_module(repo):
    path=Path(repo).resolve()/OBSERVER;raw=git(repo,Q,OBSERVER)
    need(path.is_file() and not path.is_symlink() and path.read_bytes()==raw and sha(raw)==OBSERVER_SHA,'current observer file is not the exact Q observer')
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('aijade_frozen_refusal_observer',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def verify_manifest(access):
    value=access.json(MANIFEST)
    need(value.get('schema')==MANIFEST_SCHEMA,'wrong packet manifest schema')
    rows=value['files']
    need(type(rows) is list and rows,'missing packet manifest population')
    names=[]
    for row in rows:
        path=relative(row['path']);need(path!=MANIFEST,'manifest may not list itself');names.append(path)
        raw=access.stored(path);size=row.get('sizeBytes',row.get('bytes',row.get('size')))
        need(type(size) is int and len(raw)==size and sha(raw)==row['sha256'],'stored packet identity differs: '+path)
        if 'logicalSha256' in row or 'logicalSizeBytes' in row:
            need(path.endswith('.gz'),'logical compression identity on a non-gzip file')
            logical=gzip.decompress(raw)
            need(sha(logical)==row.get('logicalSha256') and len(logical)==row.get('logicalSizeBytes'),'lossless logical identity differs: '+path)
    need(len(names)==len(set(names))==len({name.casefold() for name in names}),'duplicate packet manifest path')
    need(set(names)==access.names()-{MANIFEST},'packet file closure differs')
    return dict(status='PACKET_STORED_AND_LOGICAL_BYTES_VERIFIED',files=len(names),manifestSha256=sha(access.stored(MANIFEST)))


def known_inputs(access,repo):
    old=decode(git(repo,Q,'experiments/ch7/live-manifest-known-input-v1.json'))
    source=decode(git(repo,Q,'experiments/ch7/2026-11-12/selection.json'))
    pool=dict(schema='aijade.ch7.archived-candidate-bank.v1',programs=[source['usable'],source['unusable']],
              sources=source['sources'],newModelJudgments=0,newHeldoutCases=0,
              interpretation='The same two programmes as the old development inputs, not the new candidate pool.')
    selection=access.json('qualification-inputs/selection.json');need(selection==pool,'qualification selection is not the original two programs')
    runtime=access.json('qualification-inputs/runtime-manifest.json')
    expected=[dict(input=copy.deepcopy(case),replayAt='before_delivery' if case['operations']['repeatOutcome'] else 'none',
                   revokeAt='after_delivery' if case['operations']['revokeBeforeReuse'] else 'none',
                   failurePoint='authority_before' if case['operations']['failStateWrite'] else 'none') for case in old['cases']]
    need(runtime['purpose']=='qualification_only' and runtime['constructionFreezeCommit']==Q and runtime['blockIndex']==0
         and runtime['cases']==expected and len(expected)==10,'qualification inputs changed or fresh inputs substituted')
    need(runtime['selectionSha256']==sha(access.raw('qualification-inputs/selection.json')),'qualification selection hash differs')
    need(runtime['protocolPlanSha256']==sha(git(repo,Q,'experiments/plans/2026-11-12-ch7-confirmed-finite-heldout.md')),'confirmed original protocol changed')
    scoring=access.json('qualification-inputs/scoring-manifest.json')
    need(scoring['runtimeManifestSha256']==sha(access.raw('qualification-inputs/runtime-manifest.json'))
         and scoring['purpose']=='qualification_only' and scoring['constructionFreezeCommit']==Q,'known input scoring binding changed')
    need(scoring['scheduledInvalidPromotionOpportunitiesPerCondition']==7 and scoring['scheduledInvalidReuseOpportunitiesPerCondition']==8,'known opportunity windows changed')
    return [case['input']['caseId']+'/'+arm for case in runtime['cases'] for arm in case['input']['conditions']]


def verify_build(access,repo):
    raw=access.raw('frozen-build.json');build=decode(raw)
    need(raw==git(repo,B,BUILD) and sha(raw)==BUILD_SHA,'actual Q/B binary freeze differs; the old 666 build is not the actual binary')
    need(build['commit']==Q and build['assemblyInformationalVersion']=='0.1.0+'+Q
         and build['status']=='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION','build was relabeled or unqualified')
    need(len(build['files'])==576 and all(re.fullmatch('[0-9a-f]{64}',value) for value in build['files'].values()),'binary dependency population differs')
    outcomes=Counter();bank_cases=[];placement=[]
    for entry in build['trx']:
        raw=access.raw('engineering/build-attempt-02/default-regression/'+entry['file'])
        need(sha(raw)==entry['sha256'],'actual build TRX bytes differ')
        tree=ET.fromstring(raw);namespace={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
        rows=tree.findall('.//t:UnitTestResult',namespace);counts=Counter(row.get('outcome') for row in rows)
        need(dict(counts)==entry['individualOutcomes'],'individual test outcomes differ from bound build')
        outcomes.update(counts)
        bank_cases += [row for row in rows if 'Frozen_candidate_bank_execution_matches_original_labels_without_replacement' in row.get('testName','')]
        placement += [row for row in rows if 'Finite_operation_placements_use_actual_known_evidence_and_preserve_full_observations' in row.get('testName','')]
    need(outcomes==Counter(Passed=684,NotExecuted=67),'default test population differs')
    need(len(bank_cases)==1 and bank_cases[0].get('outcome')=='Passed','eight-program default control was not executed')
    need(len(placement)==12 and all(row.get('outcome')=='Passed' for row in placement),'placement control population differs')
    actual=access.json('engineering/build-attempt-02/candidate-bank-control.json')
    bank=decode(git(repo,Q,'experiments/ch7/finite-heldout/candidate-bank.json'))['programs']
    need(len(actual)==len(bank)==8,'eight original candidate programs were not retained')
    for row,original in zip(actual,bank):
        need(row['taskId']==original['taskId'] and row['codeSha256']==original['codeSha256']
             and row['archivedExecutionOk'] is original['trial']['execOk']
             and row['actualExecution']['ok'] is original['trial']['execOk'],'candidate was replaced or relabeled')
    return build


def audit_core(access,repo):
    names=access.names();raw_names={name[:-3] if name.endswith('.gz') else name for name in names if name.startswith('qualification/')}
    need(raw_names==RAW_FILES,'unexpected admission/block/renderer/database/raw file is present or missing')
    for directory in (access.root/'qualification').rglob('*'):
        if directory.is_dir():need(directory.relative_to(access.root).as_posix() in ['qualification/settling','qualification/admission'],'unexpected raw measurement directory')
    receipt=access.json('qualification/receipt.json');settling=access.json('qualification/settling/receipt.json')
    policy_raw=access.raw('qualification/process-policy.json');policy=decode(policy_raw)
    need(policy_raw==git(repo,Q,POLICY) and sha(policy_raw)==POLICY_SHA,'process policy differs from Q')
    plan=access.raw('plan.md');need(plan==git(repo,P,PLAN)==git(repo,Q,PLAN) and sha(plan)==PLAN_SHA,'prospective plan source differs')
    protected=decode(git(repo,Q,'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'))['files']
    need(len(protected)==331,'protected source population differs')
    for row in protected:need(sha(git(repo,Q,row['path']))==row['sha256'],'Q changed a protected historical research blob')
    build=verify_build(access,repo);planned=known_inputs(access,repo)
    identity={'implementationCommit':Q,'repositoryCommit':Q,'codeCommit':Q,'buildFreezeCommit':B,'buildFreezePath':BUILD,
              'inputPublicationCommit':None,'dataPublicationManifestPath':None,'dataPublicationManifestSha256':None,
              'addedDataPaths':[],'executionPlanSha256':PLAN_SHA,'processPolicyPath':POLICY,
              'processPolicySha256':POLICY_SHA,'observerModuleSha256':OBSERVER_SHA}
    for value in (receipt,settling):need(all(value.get(key)==wanted for key,wanted in identity.items()),'Q/B/I/plan/policy/source identity differs')
    need(receipt['status']=='STOPPED_PRE_BLOCK' and settling['status']=='SETTLING_OBSERVATION_REFUSED','refusal was changed into admission or measurement')
    need(receipt['purpose']=='qualification_only' and receipt['plannedPairs']==10 and receipt['plannedBlocks']==1
         and receipt['plannedConditionRows']==20 and receipt['completedConditionRows']==receipt['completedBlocks']==0,'refused population changed')
    need(receipt['unattemptedCaseIds']==planned and receipt['inFlightCaseIds']==receipt['unknownCaseIds']==receipt['blocks']==[],'hidden measured or unknown condition rows')
    need(receipt['modelRequests']==0 and receipt['formalHardwareQualification'] is False and receipt['independentHumanReview'] is False
         and receipt['measurementStarted'] is False and settling['measurementStarted'] is False,'scope was promoted')
    need(receipt['reason']=='ValueError: process observation adverse or unknown'
         and settling['reason']=='process observation adverse or unknown','terminal refusal reason differs')
    phase=settling['phaseClock'];need(phase['requestedSeconds']==settling['requestedSeconds']==600
         and phase['intervalReset'] is False and settling['intervalReset'] is False,'settling phase reset or relabeled')
    elapsed=phase['endMonotonic']-phase['startMonotonic']
    need(abs(elapsed-settling['elapsedSeconds'])<1e-9 and 600<=elapsed<603,'fixed settling clock differs')
    raw=access.raw('qualification/settling/telemetry.jsonl');parts=raw.splitlines()
    need(len(parts)==settling['samples']==300 and all(line.strip() for line in parts),'complete 300-sample settling trace required')
    samples=[decode(line) for line in parts];guard=guard_module(repo);statuses=Counter();codes=Counter();read_classes=Counter();details=[]
    api_empty=0;read_and_coverage=0;coverage_only=0;sample_ids=set();gap=0;previous=None
    for index,sample in enumerate(samples):
        clock=sample['elapsedSeconds'];mono=sample['monotonicSeconds'];completed=sample['observationCompletedMonotonic']
        need(0<=clock<600 and abs(mono-phase['startMonotonic']-clock)<1e-8
             and sample['scheduledSeconds']==2*index,'unanchored or changed sample schedule')
        need(completed>=mono and completed<=phase['startMonotonic']+600
             and abs(sample['observationDurationSeconds']-(completed-mono))<.001,'sample completion coverage differs')
        if previous is not None:need(0<clock-previous<=3,'missing or reversed sample coverage');gap=max(gap,clock-previous)
        previous=clock
        obs=sample['processObservation']
        need(sample['processPolicySha256']==POLICY_SHA and sample['observerModuleSha256']==OBSERVER_SHA
             and obs['processPolicySha256']==POLICY_SHA and obs['observerModuleSha256']==OBSERVER_SHA,'sample source/policy differs')
        need(obs['ownedRoots']==obs['ownedProcesses']==[] and sample['rssBytes']==0,'idle phase falsely authorizes a runtime tree')
        replay=guard.validate_observation(policy,obs)
        need(replay['status']==obs['status'] and replay['blockers']==obs['blockers'],'recorded observer decision differs from exact Q replay')
        need(obs['idleDaemon']['status']==obs['status'] and obs['idleDaemon']['api']==obs['evidence']['api'],'derived idle daemon evidence changed')
        need(obs['sampleId'] not in sample_ids,'duplicate observation sample');sample_ids.add(obs['sampleId'])
        statuses[replay['status']]+=1;codes.update(row['code'] for row in replay['blockers'])
        api=obs['evidence']['api'];body=base64.b64decode(api['emptyBodyBase64'],validate=True)
        need(api['state']=='EMPTY' and api['httpStatus']==200 and api['modelCount']==0
             and decode(body)=={'models':[]} and api['bytes']==len(body) and api['bodySha256']==sha(body)
             and 0<=api['durationSeconds']<=policy['api']['timeoutSeconds'],'API was not a fresh bounded explicit empty response')
        api_empty+=1
        if replay['status']!='PASS':
            kind={row['code'] for row in replay['blockers']}
            need(kind<={'PROCESS_READ_UNKNOWN','PROCESS_COVERAGE_INCOMPLETE'} and 'PROCESS_COVERAGE_INCOMPLETE' in kind,'unexplained refusal category')
            if 'PROCESS_READ_UNKNOWN' in kind:read_and_coverage+=1
            else:coverage_only+=1
            snapshots=[]
            for when in ('before','after'):
                graph=obs['evidence'][when]['processGraph'];initial=set(graph['enumeratedPids']);final=set(graph['endPids']);nodes={row['pid'] for row in graph['nodes']}
                errors=graph['errors'];read_classes.update(row['errorClass'] for row in errors)
                if initial!=final or initial!=nodes:
                    snapshots.append(dict(phase=when,missingReadPids=sorted(initial-nodes),departedPids=sorted(initial-final),arrivedPids=sorted(final-initial),readErrors=errors))
            details.append(dict(sampleIndex=index,elapsedSeconds=clock,blockerCodes=[row['code'] for row in replay['blockers']],snapshots=snapshots))
    need(samples[0]['elapsedSeconds']<=3 and 600-samples[-1]['elapsedSeconds']<=3,'phase endpoint coverage missing')
    need(statuses['UNKNOWN']>0 and statuses['FAIL']==0 and read_classes.keys()<={'NoSuchProcess'},'refusal cause was rewritten')
    coverage=settling['coverage'];need(coverage['samples']==300 and coverage['coverageComplete'] is True and abs(coverage['maximumGapSeconds']-gap)<1e-9,'claimed coverage differs')
    plan_pub=access.json('publication/plan.json');impl_pub=access.json('publication/implementation.json');build_pub=access.json('publication/binary-freeze.json')
    launch=access.json('publication/launch.json');terminal=access.json('publication/terminal.json')
    need(plan_pub['commit']==P and plan_pub['sha256']==PLAN_SHA and plan_pub['changedFiles']==[PLAN],'plan was not published alone')
    need(impl_pub['implementationCommit']==Q and impl_pub['protectedResearchFiles']==331,'published Q differs')
    need(build_pub['sourceCommit']==Q and build_pub['buildFreezeCommit']==B and build_pub['buildFreezePath']==BUILD
         and build_pub['frozenBuildSha256']==BUILD_SHA and build_pub['remoteBytesIdentical'] is True,'published B differs')
    need(launch['implementationCommit']==launch['repositoryCommit']==Q and launch['buildFreezeCommit']==B
         and launch['automaticRetries']==launch['modelRequests']==0 and launch['purpose']=='qualification_only','launch was repeated or rebound')
    need(terminal['controllerExitCode']==1 and terminal['receiptStatus']=='STOPPED_PRE_BLOCK'
         and terminal['automaticRetries']==0 and terminal['scientificAcceptance'] is False and terminal['reason'] is None,'terminal state differs')
    need(utc(plan_pub['verifiedAt'])<utc(build['checkedAt'])<utc(build_pub['verifiedAt'])<utc(launch['startedAt'])
         <utc(samples[0]['utc'])<utc(receipt['finishedAt'])<=utc(terminal['finishedAt']),'prospective source/build/phase ordering differs')
    args=launch['command']
    def option(name):need(args.count(name)==1,'missing or duplicate launch option');return args[args.index(name)+1]
    need(option('--implementation-commit')==Q and option('--build-freeze-commit')==B and option('--build-freeze-path')==BUILD
         and option('--settle-seconds')=='600','actual launch options differ')
    need(option('--build-manifest').endswith('/build-attempt-02/frozen-build.json'),'unused first build was substituted')
    exit_check=access.json('audit/controller-exit.json');controller=receipt['controllerProcess']
    need(controller==settling['controllerProcess'] and exit_check['pid']==controller['pid'] and exit_check['createTime']==controller['createTime'],'owned controller exit identity differs')
    need(exit_check['status'] in ['ABSENT','OLD_IDENTITY_ABSENT_PID_REUSED'] and exit_check['processMutations']==0
         and utc(exit_check['checkedAt'])>=utc(terminal['finishedAt']),'controller absence was not independently checked')
    need(exit_check['observedCreateTime'] is None if exit_check['status']=='ABSENT' else exit_check['observedCreateTime']!=controller['createTime'],'PID reuse was falsely labeled exit')
    numbers=dict(settlingSeconds=elapsed,samples=300,passSamples=statuses['PASS'],unknownSamples=statuses['UNKNOWN'],failSamples=statuses['FAIL'],
                 maxGapSeconds=gap,apiExplicitEmptySamples=api_empty,unknownReadAndCoverageSamples=read_and_coverage,
                 unknownCoverageOnlySamples=coverage_only,noSuchProcessReadEvents=read_classes['NoSuchProcess'],
                 settlingMinimumAvailableBytes=min(row['availableBytes'] for row in samples),settlingMaximumAvailableBytes=max(row['availableBytes'] for row in samples),
                 settlingSwapMinimumBytes=min(row['swapUsedBytes'] for row in samples),settlingSwapMaximumBytes=max(row['swapUsedBytes'] for row in samples),
                 settlingSwapRangeBytes=max(row['swapUsedBytes'] for row in samples)-min(row['swapUsedBytes'] for row in samples),
                 admissionSamples=0,plannedKnownPairs=10,plannedKnownConditionRows=20,unattemptedKnownConditionRows=20,
                 completedConditionRows=0,rendererSessions=0,newModelRequests=0,freshHeldoutCases=0,binaryDependencyFiles=576,
                 defaultPassed=684,defaultNotExecuted=29,browserNotExecuted=38)
    return dict(schema='aijade.ch7.mac-formal-refusal-audit.v1',status='INDEPENDENT_REFUSAL_AUDIT_PASS',
                sourceCommit=Q,buildFreezeCommit=B,planCommit=P,planSha256=PLAN_SHA,numbers=numbers,scope=SCOPE,
                rawIdentities={path:sha(access.raw(path)) for path in sorted(RAW_FILES)},actualBuildSha256=BUILD_SHA,
                protectedSourceFiles=331,observerModuleSha256=OBSERVER_SHA,processPolicySha256=POLICY_SHA,
                blockerCodeOccurrences=dict(codes),unknownDetails=details,controllerExit=exit_check,
                interpretation='Complete retained settling refusal before admission; sampled empty daemon/API evidence does not establish full-machine quiescence, formal device qualification or any C1/C2 result.')


def verify(root,repo,content_only=False,overrides=None,compare_saved=True):
    access=Access(root,overrides)
    integrity=None if content_only else verify_manifest(access)
    value=audit_core(access,repo)
    if compare_saved and 'audit/independent-refusal-audit.json' in access.names():
        saved=access.json('audit/independent-refusal-audit.json')
        need(saved==value,'saved independent audit does not match a full raw replay')
    return dict(audit=value,packetIntegrity=integrity)


def controls(root,repo):
    base=Access(root)
    def rebound_manifest(access,schema=MANIFEST_SCHEMA):
        rows=[]
        for path in sorted(access.names()-{MANIFEST}):
            raw=access.stored(path);row=dict(path=path,sha256=sha(raw),sizeBytes=len(raw))
            if path.endswith('.gz'):
                logical=gzip.decompress(raw);row.update(logicalSha256=sha(logical),logicalSizeBytes=len(logical))
            rows.append(row)
        return json.dumps(dict(schema=schema,files=rows)).encode()
    baseline_overrides={} if MANIFEST in base.names() else {MANIFEST:rebound_manifest(base)}
    normal=verify(root,repo,overrides=baseline_overrides,compare_saved=False)
    source=decode(base.raw('qualification/settling/telemetry.jsonl').splitlines()[0])
    original=[decode(line) for line in base.raw('qualification/settling/telemetry.jsonl').splitlines()]
    unknown=next(i for i,row in enumerate(original) if row['processObservation']['status']=='UNKNOWN')
    results=[]
    def check(name,patches,manifest_schema=MANIFEST_SCHEMA):
        overrides=dict(patches)
        # Rebind all changed storage/logical hashes so rejection must be semantic.
        overrides[MANIFEST]=rebound_manifest(Access(root,overrides),manifest_schema)
        try:verify(root,repo,overrides=overrides,compare_saved=False)
        except (ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:results.append(dict(name=name,rejected=True,reason=str(error)))
        else:raise ValueError('coherent negative control was accepted: '+name)
    def changed_trace(samples):
        raw=b''.join((json.dumps(row,separators=(',',':'))+'\n').encode() for row in samples)
        result={'qualification/settling/telemetry.jsonl':raw}
        if 'qualification/settling/telemetry.jsonl.gz' in base.names():result['qualification/settling/telemetry.jsonl.gz']=None
        return result
    altered=list(original);row=copy.deepcopy(original[unknown]);row['processObservation'].update(status='PASS',blockers=[],ownedRssBytes=0);row['processObservation']['idleDaemon']['status']='PASS';altered[unknown]=row
    check('unknown-rewritten-as-pass',changed_trace(altered))
    altered=original[:10]+original[11:];patches=changed_trace(altered);settle=base.json('qualification/settling/receipt.json');settle['samples']=299;settle['coverage']['samples']=299;patches['qualification/settling/receipt.json']=json.dumps(settle).encode();check('missing-sample-coherent-count',patches)
    changed=base.json('qualification/receipt.json');changed.update(codeCommit='0'*40,implementationCommit='0'*40,repositoryCommit='0'*40);check('changed-source',{'qualification/receipt.json':json.dumps(changed).encode()})
    changed=base.json('qualification/receipt.json');changed['status']='ADMITTED_NOT_STARTED';check('false-admission-status',{'qualification/receipt.json':json.dumps(changed).encode()})
    check('hidden-admission-trace',{'qualification/admission/telemetry.jsonl':b'{}\n'})
    check('hidden-renderer-block',{'qualification/block-1/receipt.json':b'{"status":"COMPLETE"}\n'})
    changed=base.json('qualification/receipt.json');changed['unattemptedCaseIds'].pop();check('hidden-row-disposition',{'qualification/receipt.json':json.dumps(changed).encode()})
    altered=list(original);row=copy.deepcopy(original[0]);api=row['processObservation']['evidence']['api'];api['emptyBodyBase64']=base64.b64encode(b'{"models":[{}]}').decode();api['bytes']=len(b'{"models":[{}]}');api['bodySha256']=sha(b'{"models":[{}]}');row['processObservation']['idleDaemon']['api']=copy.deepcopy(api);altered[0]=row;check('false-empty-api-body',changed_trace(altered))
    check('first-unused-build-substitution',{'frozen-build.json':base.raw('engineering/build-attempt-01/frozen-build.json')})
    changed=base.json('audit/controller-exit.json');changed['status']='STILL_PRESENT';check('false-controller-cleanup',{'audit/controller-exit.json':json.dumps(changed).encode()})
    check('wrong-manifest-schema',{},manifest_schema='aijade.ch7.invalid-packet-manifest.v1')
    return dict(status='COHERENT_REFUSAL_CONTROLS_PASS',baselineManifestSchema=MANIFEST_SCHEMA,
                baselineManifestVerified=normal['packetIntegrity']['status'],controls=results,
                networkRequests=0,modelRequests=0,rendererSessions=0,measuredWindows=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--content-only',action='store_true');parser.add_argument('--controls',action='store_true')
    args=parser.parse_args()
    try:
        value=verify(args.root,args.repo,args.content_only)
        if args.controls:value['negativeControls']=controls(args.root,args.repo)
        print(json.dumps(value,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError,ET.ParseError) as error:
        print(json.dumps(dict(status='REFUSAL_PACKET_REJECTED',reason=str(error)),ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)
