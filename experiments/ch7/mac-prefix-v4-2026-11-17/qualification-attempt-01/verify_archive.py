#!/usr/bin/env python3
"""Portable P4 refusal-record consistency; no current Mac SDK or live workload.

Checks every physical/logical body, fixed Git source/publication objects, original
phase clocks, lifecycle chain/WAIT evidence, parent provenance and summary. The
original Mac360 cold replay is retained and bound to its exact input hashes;
this tool does not claim another cold guard/SDK validation on Linux.
"""
from __future__ import annotations
import argparse,copy,gzip,hashlib,importlib.util,io,json,math,os
from pathlib import Path,PurePosixPath
import shutil,subprocess,sys,tempfile,traceback,unicodedata

Q='147564c9db812c1a9e5ae07992d9aa282399a310'
B='8acfa99d061f1c41197fac2a1c243b3b347bcfef'
P='42fc728ade94c60b0d24575b9510b69dd2048676'
PRE='5d020ccbf54c16965b4a1fe3467b3d8d726d23f8'
PLAN='experiments/plans/2026-11-17-ch7-mac-prefix-v4-qualification.md'
PLAN_SHA='7aa91508eee3e728cadd8d25f8cdd122deb9a35d06a09901e8143d1e028d9d36'
POLICY='configs/research/ch7-mac-prefix-v4-process-policy.json'
POLICY_SHA='caf8392394a09ec168df44347337ec0676f695f5d3cd9af576372678e03a925a'
PREFIX='experiments/ch7/mac-prefix-v4-2026-11-17/'
MANIFEST='d4266adabc2ece0f33f1b3d19b538588d104ce383635d62dd8731aaeb6238949'
AUDIT_SHA='4aed475c1cefc00c94c0e0d21bf9beeb6a2f9b4539e58910f10127e33fb88aea'
BASE=Path('/Volumes/Untitled/AIJADE')
CAP=256*1024**2
RUN='run/qualification-01/'
REQUIRED_RUN={'receipt.json','owned-process-registry.json','process-policy.json','process-observations.jsonl',
    'phase-events.jsonl','settling/receipt.json','settling/telemetry.jsonl','preflight-continuity.json',
    'lifecycle-journal.jsonl','sustained-timers.json','block-1-controller.log','admission/receipt.json','admission/telemetry.jsonl'}

def need(ok,message):
    if not ok:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
def unique(pairs):
    result={}
    for key,value in pairs:need(key not in result,'DUPLICATE_JSON_KEY');result[key]=value
    return result
def decode(raw):return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
def same(a,b):return type(a) is type(b) and (set(a)==set(b) and all(same(a[k],b[k]) for k in a) if type(a) is dict else len(a)==len(b) and all(same(x,y) for x,y in zip(a,b)) if type(a) is list else a==b)
def integer(x):need(type(x) is int and x>=0,'INTEGER_TYPE');return x
def real(x):need(type(x) in (int,float) and math.isfinite(x),'FINITE_CLOCK');return x
def close(a,b):return abs(real(a)-real(b))<=1e-7
def relative(name):
    need(type(name) is str and name and '\\' not in name and ':' not in name and not any(ord(c)<32 for c in name),'UNSAFE_PATH')
    item=PurePosixPath(name);need(not item.is_absolute() and str(item)==name and all(p not in ('','.','..') for p in name.split('/')),'UNSAFE_PATH')
    return name
def file_sha(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()

class Packet:
    def __init__(self,root,expected):
        self.root=root;self.raw=(root/'packet-manifest.json').read_bytes();need(sha(self.raw)==expected,'MANIFEST_IDENTITY')
        self.manifest=decode(self.raw);m=self.manifest
        need(m['schema']=='aijade.ch7.prefix-qualification-refusal-packet-manifest.v1' and m['sourceCommit']==Q
            and m['buildFreezeCommit']==B and m['planCommit']==P and m['planSha256']==PLAN_SHA
            and m['processPolicySha256']==POLICY_SHA and m['independentAuditSha256']==AUDIT_SHA,'FIXED_CONTEXT')
        self.rows={};self.logical={};folded=set();total=0
        for row in m['files']:
            need(type(row) is dict and set(row) in ({'path','sha256','sizeBytes'},{'path','sha256','sizeBytes','logicalSha256','logicalSizeBytes'}),'MANIFEST_ROW')
            name=relative(row['path']);key=unicodedata.normalize('NFC',name).casefold()
            need(name not in self.rows and key not in folded,'PATH_COLLISION');folded.add(key)
            path=root/name;need(path.is_file() and not path.is_symlink(),'NONREGULAR_BODY')
            need(integer(row['sizeBytes'])==path.stat().st_size and file_sha(path)==row['sha256'],'PHYSICAL_IDENTITY')
            logical=name[:-3] if name.endswith('.jsonl.gz') else name
            need(logical not in self.logical,'AMBIGUOUS_GZIP_OR_PLAIN');self.rows[name]=row;self.logical[logical]=name
            if name.endswith('.jsonl.gz'):
                with path.open('rb') as stream:header=stream.read(10)
                need(header[4:8]==b'\0'*4 and integer(row['logicalSizeBytes'])<=CAP,'DETERMINISTIC_GZIP_OR_CAP')
                digest=hashlib.sha256();count=0
                with gzip.open(path,'rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block);count+=len(block);need(count<=CAP,'LOGICAL_CAP')
                need(count==row['logicalSizeBytes'] and digest.hexdigest()==row['logicalSha256'],'LOGICAL_IDENTITY');total+=count
            else:need('logicalSha256' not in row,'PLAIN_LOGICAL_SCHEMA');total+=row['sizeBytes']
        need(total<=512*1024**2,'TOTAL_LOGICAL_CAP')
        actual=set();actual_dirs=set()
        for path in root.rglob('*'):
            need(not path.is_symlink(),'LINKED_PACKET')
            if path.is_file():actual.add(path.relative_to(root).as_posix())
            elif path.is_dir():actual_dirs.add(path.relative_to(root).as_posix())
            else:need(False,'SPECIAL_PACKET_BODY')
        expected_dirs={str(p) for name in self.rows for p in PurePosixPath(name).parents if str(p)!='.'}
        need(actual==set(self.rows)|{'packet-manifest.json'} and actual_dirs==expected_dirs,'PHYSICAL_CLOSURE')
    def body_sha(self,name):
        row=self.rows[self.logical[name]];return row.get('logicalSha256',row['sha256'])
    def body_size(self,name):
        row=self.rows[self.logical[name]];return row.get('logicalSizeBytes',row['sizeBytes'])
    def open(self,name):
        physical=self.logical[name];return gzip.open(self.root/physical,'rb') if physical.endswith('.jsonl.gz') else (self.root/physical).open('rb')
    def body(self,name):
        with self.open(name) as stream:raw=stream.read(CAP+1)
        need(len(raw)<=CAP,'BODY_CAP');return raw
    def json(self,name):return decode(self.body(name))
    def lines(self,name):
        with self.open(name) as stream:
            for line in stream:
                need(len(line)<=4*1024**2,'JSONL_RECORD_CAP')
                if line.strip():yield decode(line)

class Context:
    def __init__(self,repo,temp):self.repo=repo;self.temp=temp;self.modules={};self.phase_cache={};self.git_cache={}
    def git(self,commit,name):
        need(commit in (Q,B,P,PRE),'NONFROZEN_GIT_REQUEST');relative(name);key=(commit,name)
        if key not in self.git_cache:
            self.git_cache[key]=subprocess.check_output(['git','--no-replace-objects','-C',str(self.repo),'show',commit+':'+name],stderr=subprocess.PIPE,timeout=30,
                env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_NO_REPLACE_OBJECTS='1'))
        return self.git_cache[key]
    def independent(self,p):
        raw=p.body('source/experiments/ch7/lifecycle_audit.py');need(raw==self.git(Q,'experiments/ch7/lifecycle_audit.py'),'FROZEN_AUDITOR_SOURCE')
        key=sha(raw)
        if key not in self.modules:
            path=self.temp/('lifecycle-'+key+'.py');path.write_bytes(raw)
            spec=importlib.util.spec_from_file_location('p4_frozen_record_lifecycle',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);self.modules[key]=module
        return self.modules[key]

def verify(root,context,expected=MANIFEST):
    p=Packet(root,expected)
    mapping=p.json('metadata/source-map.json')['originalSources'];need(len(mapping)==74,'ORIGINAL_SOURCE_POPULATION')
    mapped={}
    for row in mapping:
        logical=relative(row['logicalPacketPath']);need(logical not in mapped and p.logical.get(logical)==row['packetPath'],'SOURCE_MAP_PATH')
        need(p.body_sha(logical)==row['originalSha256'],'SOURCE_MAP_LOGICAL_SHA')
        need(p.body_size(logical)==integer(row['originalSizeBytes']) and p.rows[row['packetPath']]['sha256']==row['physicalSha256']
             and p.rows[row['packetPath']]['sizeBytes']==row['physicalSizeBytes'] and row['originalBytesPreserved'] is True,'SOURCE_MAP_IDENTITY')
        mapped[logical]=row
    generated={'summary.json','README.md','metadata/source-map.json','metadata/run-directory-state.json',
               'metadata/frozen-source-proofs.json','metadata/archive-scope.json'}
    need(set(p.logical)==set(mapped)|generated and len(p.rows)==80,'EXACT80_PAYLOAD_SOURCE_CLOSURE')
    need({name[len(RUN):] for name in mapped if name.startswith(RUN)}==REQUIRED_RUN,'ORIGINAL_RUN_POPULATION')
    need(p.body_size(RUN+'block-1-controller.log')==0,'EMPTY_UNSPAWNED_CONTROLLER_LOG')
    source_proofs=p.json('metadata/frozen-source-proofs.json');need(source_proofs['sourceCommit']==Q and len(source_proofs['sources'])==16,'SOURCE16_CONTEXT')
    for row in source_proofs['sources']:
        name=relative(row['path']);raw=p.body('source/'+name)
        need(row['commit']==Q and raw==context.git(Q,name) and sha(raw)==row['sha256']
             and hashlib.sha1(('blob %d\0'%len(raw)).encode()+raw).hexdigest()==row['gitBlob'],'Q2_FROZEN_SOURCE_BYTES')
    need(p.body('publication/plan.md')==context.git(P,PLAN) and p.body_sha('publication/plan.md')==PLAN_SHA,'P4_PLAN_BYTES')
    need(p.body(RUN+'process-policy.json')==context.git(Q,POLICY) and p.body_sha(RUN+'process-policy.json')==POLICY_SHA,'POLICY_BYTES')
    need(p.body('publication/frozen-build.json')==context.git(B,PREFIX+'frozen-build.json'),'B4_BUILD_BYTES')
    pub=p.json('publication/prelaunch-publication.json');need(pub['metadataCommit']==PRE and pub['sourceCommit']==Q,'PRELAUNCH_CONTEXT')
    for row in pub['files']:
        name=row['path'];logical='inputs/'+Path(name).name if '/qualification-inputs/' in name else 'publication/'+Path(name).name
        need(p.body(logical)==context.git(PRE,name) and p.body_sha(logical)==row['sha256'],'PRELAUNCH_EXACT_BYTES')
    audit=p.json('audit/independent-p4-terminal-audit-01.json');need(p.body_sha('audit/independent-p4-terminal-audit-01.json')==AUDIT_SHA,'ORIGINAL_INDEPENDENT_AUDIT_IDENTITY')
    need(audit['scope']['terminalRecordIntegrityAccepted'] is True and audit['numbers']['idleColdPassSamples']==360,'ORIGINAL_COLD_REPLAY_SCOPE')
    receipt=p.json(RUN+'receipt.json');phases={name:p.json(RUN+name+'/receipt.json') for name in ('settling','admission')}
    pre=p.json(RUN+'preflight-continuity.json');events=list(p.lines(RUN+'phase-events.jsonl'))
    need(pre['status']=='PREFLIGHT_COMPLETE_ADMITTED' and integer(pre['samples'])==integer(pre['validatedSamples'])==360
         and pre['windowReset'] is False,'PREFLIGHT360_CONTEXT')
    need(receipt['status']=='STOPPED' and receipt['implementationCommit']==receipt['repositoryCommit']==Q and receipt['buildFreezeCommit']==B,'TERMINAL_CONTEXT')
    need(integer(receipt['completedBlocks'])==integer(receipt['completedConditionRows'])==integer(receipt['modelRequests'])==0
         and len(receipt['unattemptedCaseIds'])==20 and receipt['unknownCaseIds']==receipt['inFlightCaseIds']==receipt['blocks']==receipt['blockControllers']==[],'STOPPED20_UNATTEMPTED')
    need(len(events)==363 and all(integer(event['eventIndex'])==i for i,event in enumerate(events)),'EVENT363_POPULATION')
    written={(event['phase'],event['globalIndex']):event for event in events if event['event']=='sample-written'}
    need(len(written)==360 and all(real(a['monotonicSeconds'])<=real(b['monotonicSeconds']) for a,b in zip(events,events[1:])),'EVENT_CHRONOLOGY')
    origin=real(phases['settling']['phaseClock']['startMonotonic']);previous=None;global_rows=[];phase_facts={}
    for name,count,seconds,offset in (('settling',300,600,0),('admission',60,120,300)):
        r=phases[name];clock=r['phaseClock'];start=real(clock['startMonotonic']);end=real(clock['endMonotonic'])
        need(r['status']==('ADMITTED' if name=='admission' else 'FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION')
             and integer(r['samples'])==integer(r['validatedSamples'])==integer(r['expectedSamples'])==count,'PHASE_POPULATION')
        need(seconds<=end-start<=seconds+3 and close(r['elapsedSeconds'],end-start)
             and clock['requestedSeconds']==seconds and clock['intervalReset'] is False,'PHASE_DURATION')
        need(same(pre['phases'][name],{key:r[key] for key in pre['phases'][name]}),'PHASE_RECEIPT_PREFLIGHT_BINDING')
        cache_key=(p.body_sha(RUN+name+'/telemetry.jsonl'),p.body_sha(RUN+'phase-events.jsonl'),sha(encode(r)),Q,POLICY_SHA)
        if cache_key in context.phase_cache:facts=copy.deepcopy(context.phase_cache[cache_key])
        else:
            facts=[]
            for local,row in enumerate(p.lines(RUN+name+'/telemetry.jsonl')):
                need(row['phase']==name and integer(row['globalIndex'])==offset+local and row['streamValidationStatus']=='PASS','RAW_PHASE_IDENTITY')
                stamp=real(row['monotonicSeconds']);completed=real(row['observationCompletedMonotonic']);validating=real(row['validatorStartedMonotonic']);validated=real(row['validatorCompletedMonotonic']);writing=real(row['writerStartedMonotonic'])
                event=written[(name,offset+local)];finished=real(event['writerCompletedMonotonic'])
                need(close(row['globalScheduledMonotonic'],origin+(offset+local)*2) and close(row['scheduledSeconds'],local*2),'GLOBAL_FIXED_SCHEDULE')
                need(start<=stamp<=completed<=validating<=validated<=writing<=finished<=start+seconds and completed-stamp<=2.5 and finished-stamp<=2,'FULL_SAMPLE_CLOCK_BUDGET')
                need(event['sampleId']==row['sampleId'] and close(event['writerStartedMonotonic'],writing)
                     and close(event['validatorStartedMonotonic'],validating) and close(event['validatorCompletedMonotonic'],validated),'WRITER_EVENT_BINDING')
                observation=row['processObservation']
                need(observation['status']=='PASS' and observation['blockers']==[] and observation['ownedRoots']==observation['ownedProcesses']==[]
                     and type(row['rssBytes']) is int and row['rssBytes']==0 and row['processPolicySha256']==POLICY_SHA,'RECORDED_IDLE_PROCESS_SCOPE')
                need(integer(row['availableBytes'])>=6*1024**3 and type(row['swapUsedBytes']) is int,'RECORDED_RESOURCE_THRESHOLD')
                facts.append({'sampleId':row['sampleId'],'globalIndex':row['globalIndex'],'start':stamp,'finished':finished,
                    'availableBytes':row['availableBytes'],'swapUsedBytes':row['swapUsedBytes']})
            need(len(facts)==count,'PHASE_RAW_DENOMINATOR');context.phase_cache[cache_key]=copy.deepcopy(facts)
        for fact in facts:
            need(previous is None or 0<fact['start']-previous<=3,'GLOBAL_START_GAP');previous=fact['start'];global_rows.append(fact)
        need(len(facts)==count and max(f['swapUsedBytes'] for f in facts)-min(f['swapUsedBytes'] for f in facts)==0,'PHASE_SWAP_RANGE')
        phase_facts[name]={'samples':len(facts),'minimumAvailableBytes':min(f['availableBytes'] for f in facts),'firstStart':facts[0]['start'],'lastStart':facts[-1]['start']}
    need(0<=phases['admission']['phaseClock']['startMonotonic']-phases['settling']['phaseClock']['endMonotonic']<=3,'PHASE_BOUNDARY')
    parent=p.json('launch/qualification-single-launch.terminal.json');launch=p.json('launch/qualification-single-launch.json')
    need(type(parent['controllerExitCode']) is int and parent['controllerExitCode']==1 and parent['intervention'] is False
         and parent['watchdogSeconds']==5700 and parent['automaticRetries']==0 and parent['unresolved'] is False
         and parent['controllerLogMayStillGrow'] is False and parent['childIdentityUnresolved'] is False
         and parent['wholeProcessGroupCleanupClaimed'] is False,'PARENT_ADVERSE_NO_INTERVENTION')
    need(parent['configSha256']==p.body_sha('publication/qualification-fixed-launch.json') and parent['launchRecordSha256']==p.body_sha('launch/qualification-single-launch.json')
         and parent['logSha256']==p.body_sha('launch/qualification-single-launch.controller.log'),'PARENT_HASH_BINDING')
    evidence=parent['processEvidence'];need(len(evidence['terminalPolls'])==len(evidence['waitCalls'])==1,'PARENT_POLL_WAIT_POPULATION')
    poll=evidence['terminalPolls'][0];wait=evidence['waitCalls'][0]
    need(type(poll['exitCode']) is int and type(wait['exitCode']) is int and poll['exitCode']==wait['exitCode']==1
         and poll['provenance']=='TERMINAL_STATUS_FIRST_OBTAINED_BY_POPEN_POLL'
         and wait['provenance']=='CACHED_RETURN_AFTER_PRIOR_TERMINAL_STATUS'
         and wait['returncodeKnownBeforeCall'] is True and wait['reapedBeforeThisCall'] is True
         and poll['independentKernelWaitClaimed'] is False and wait['independentKernelWaitClaimed'] is False,'PARENT_WAIT_PROVENANCE')
    registry=p.json(RUN+'owned-process-registry.json');refusals=registry['launchRefusals']
    need(len(refusals)==1,'SINGLE_LAUNCH_REFUSAL');refusal=refusals[0]
    need(refusal['spawnedPid'] is None and refusal['registeredLeaseId'] is None and refusal['identityReads']==[] and refusal['readyBytes']==0
         and refusal['actualExitCode'] is None and refusal['cleanupKnown'] is True and refusal['stageId']=='block-1','REFUSED_BEFORE_POPEN_NO_PID')
    need(registry['remainingIdentities']==registry['unresolvedFiniteLeases']==registry['unleasedDiscoveredIdentities']==[]
         and registry['status']=='UNKNOWN_OR_ADVERSE_OWNED_LIFECYCLE' and registry['scopeClosed'] is True,'ADVERSE_REGISTRY_NOT_PHYSICAL_RESIDUAL_CLAIM')
    journal=p.body(RUN+'lifecycle-journal.jsonl');need(journal==p.body('adjacent/qualification-01-lifecycle.jsonl'),'ARCHIVED_ADJACENT_JOURNAL_BYTES')
    independent=context.independent(p);state=independent._replay(journal,Q,POLICY_SHA)
    finite=[lease for lease in state['leases'].values() if lease['role']=='finite']
    need(len(state['events'])==4432 and len(finite)==1476 and all(type(lease['exitCode']) is int and lease['exitCode']==0 and lease['waitSeq'] is not None and lease['absence'] is not None for lease in finite),'JOURNAL1476_WAIT_ZERO')
    need({lease['leaseId']:lease for lease in finite}=={lease['leaseId']:lease for lease in registry['knownFiniteLeases']},'FINAL_FINITE_PROJECTION')
    need(len(state['launchRefusals'])==1 and same(state['launchRefusals'][0],refusal),'JOURNAL_REFUSAL_PROJECTION')
    runtime=list(p.lines(RUN+'process-observations.jsonl'));actual=[row for row in runtime if 'processObservation' in row];errors=[row for row in runtime if 'observationError' in row]
    need(len(actual)==len(errors)==1,'RUNTIME_ONE_ADVERSE_ONE_ERROR');r=actual[0];obs=r['processObservation'];lock=obs['coordinationLock']
    need(obs['status']=='FAIL' and any(row['code']=='LAUNCH_REFUSED' for row in obs['blockers']) and r['rssBytes'] is None,'RUNTIME_ADVERSE_NOT_FILLED_RSS')
    need(lock['maxWaitSeconds']==1.25 and 0<=real(lock['waitSeconds'])<=1.25 and lock['state']=='HELD_AND_RELEASED'
         and real(lock['acquiredMonotonic'])<refusal['cleanupCompletedMonotonic']<real(lock['releasedMonotonic']),'LOCK_ACTUAL_BOUNDS')
    need(real(refusal['startedMonotonic'])<real(lock['acquiredMonotonic']) and refusal['cleanupCompletedMonotonic']-refusal['startedMonotonic']>=1.25,'LAUNCH_TIMEOUT_ACTUAL_BOUNDS')
    need(0<r['monotonicSeconds']-global_rows[-1]['start']<=3 and r['observationCompletedMonotonic']-r['monotonicSeconds']<=2.5,'RUNTIME_HANDOFF_CLOCK')
    for field,name in (('lifecycleJournalSha256','lifecycle-journal.jsonl'),('phaseEventsSha256','phase-events.jsonl'),('ownedProcessRegistrySha256','owned-process-registry.json'),('preflightContinuitySha256','preflight-continuity.json')):
        need(receipt[field]==p.body_sha(RUN+name),'RECEIPT_ARTIFACT_HASH')
    summary=p.json('summary.json');need(summary['status']=='REFUSED_RUNTIME_HANDOFF_LOCK_TIMEOUT_NO_BLOCK_SPAWN' and summary['sourceCommit']==Q and summary['buildFreezeCommit']==B and summary['planCommit']==P,'SUMMARY_REFUSAL_CONTEXT')
    for key,value in audit['numbers'].items():need(key in summary['numbers'] and same(summary['numbers'][key],value),'SUMMARY_NUMERIC_TYPED_MATCH')
    aliases=p.json('audit/p4-raw-receipt-review-preaudit-draft.json')['numbers']
    for key,value in aliases.items():need(key in summary['numbers'] and same(summary['numbers'][key],value),'SUMMARY_ALIAS_TYPED_MATCH')
    need(summary['independentAuditSha256']==AUDIT_SHA and summary['scope']['terminalRecordIntegrityAccepted'] is True
         and all(summary['scope'].get(key) is False for key in ('backendQualified','fullFiniteDriverQualified','formalHardwareQualification','independentHumanReview','authorApproval','heldoutComparisonComplete','currentProductInheritsResearchQualification','seedConstructed'))
         and summary['scope']['table7_3']=='NOT_RUN' and summary['caseGenerationSeed'] is None and summary['formalInputPublicationCommit'] is None,'NO_SCIENTIFIC_PROMOTION')
    for key,value in audit['scope'].items():need(key in summary['scope'] and same(summary['scope'][key],value),'SUMMARY_SCOPE_TYPED_MATCH')
    need(audit['wholeRuntimeContinuity']['status']=='REFUSED' and audit['wholeRuntimeContinuity']['error']=='raw v3 process evidence adverse'
         and audit['wholeLifecyclePredicate']['status']=='REFUSED' and audit['wholeLifecyclePredicate']['error']=='LAUNCH_REFUSED evidence verified; qualification remains adverse','ORIGINAL_FROZEN_REFUSALS_RETAINED')
    # Final immutable Mac cold-replay input binding, after semantic checks.
    originals={row['originalPath']:row for row in mapping}
    for proof in audit['inputFiles']:
        need(proof['path'] in originals and proof['sha256']==originals[proof['path']]['originalSha256']
             and proof['sizeBytes']==originals[proof['path']]['originalSizeBytes'],'ORIGINAL_MAC_COLD_INPUT_BINDING')
    need(sha((root/'packet-manifest.json').read_bytes())==expected,'PACKET_CHANGED_DURING_RECORD_CHECK')
    return {'status':'RECORDS_ONLY_P4_REFUSAL_CONSISTENCY_PASS_NOT_QUALIFIED','manifestSha256':expected,'payloadFiles':len(p.rows),
        'originalSourceFiles':len(mapping),'sourceCommit':Q,'buildFreezeCommit':B,'planCommit':P,
        'numbers':summary['numbers'],'scope':summary['scope'],'phaseRecordFacts':phase_facts,
        'actualLockHoldSeconds':lock['releasedMonotonic']-lock['acquiredMonotonic'],
        'actualRefusedLaunchElapsedSeconds':refusal['cleanupCompletedMonotonic']-refusal['startedMonotonic'],
        'originalMac360ColdReplayRetainedAndInputBound':True,'fresh360GuardColdReplayPerformedHere':False,
        'currentMacSdkAndNativeBinaryPhysicalCheck':'NOT_RECHECKED_RECORDS_ONLY','liveObserverApiModelRendererInvoked':False,
        'rawJournalIndependentlyReplayed':True,'qualified':False,'sourceHeadUsedAsOriginalImplementation':False}

def write_logical(root,name,value):
    plain=root/name;gz=root/(name+'.gz');raw=encode(value) if not isinstance(value,bytes) else value
    if gz.exists():
        with gz.open('wb') as out:
            with gzip.GzipFile(filename='',mode='wb',fileobj=out,mtime=0,compresslevel=6) as stream:stream.write(raw)
    else:plain.write_bytes(raw)

def rebind(root):
    # Coherently rebind all physical/logical metadata, including source-map and
    # receipt/parent hashes. Test mutations never touch the immutable originals.
    m=decode((root/'packet-manifest.json').read_bytes())
    def logical_raw(name):
        path=root/name
        if path.exists():return path.read_bytes()
        with gzip.open(root/(name+'.gz'),'rb') as stream:return stream.read()
    receipt=decode(logical_raw(RUN+'receipt.json'))
    for field,name in (('lifecycleJournalSha256','lifecycle-journal.jsonl'),('phaseEventsSha256','phase-events.jsonl'),('ownedProcessRegistrySha256','owned-process-registry.json'),('preflightContinuitySha256','preflight-continuity.json')):
        receipt[field]=sha(logical_raw(RUN+name))
    write_logical(root,RUN+'receipt.json',receipt)
    # The recorded controller printed the receipt before the archive-only keys.
    log_receipt={k:v for k,v in receipt.items() if k not in ('lifecycleJournalBytes','lifecycleJournalArchive')}
    write_logical(root,'launch/qualification-single-launch.controller.log',(json.dumps(log_receipt)+'\n').encode())
    parent=decode(logical_raw('launch/qualification-single-launch.terminal.json'))
    parent['logSha256']=sha(logical_raw('launch/qualification-single-launch.controller.log'))
    write_logical(root,'launch/qualification-single-launch.terminal.json',parent)
    mapping=decode(logical_raw('metadata/source-map.json'))
    for row in mapping['originalSources']:
        path=root/row['packetPath'];raw=logical_raw(row['logicalPacketPath'])
        row.update(originalSha256=sha(raw),originalSizeBytes=len(raw),physicalSha256=file_sha(path),physicalSizeBytes=path.stat().st_size)
    write_logical(root,'metadata/source-map.json',mapping)
    for row in m['files']:
        path=root/row['path'];row.update(sha256=file_sha(path),sizeBytes=path.stat().st_size)
        if row['path'].endswith('.jsonl.gz'):
            with gzip.open(path,'rb') as stream:raw=stream.read()
            row.update(logicalSha256=sha(raw),logicalSizeBytes=len(raw))
    (root/'packet-manifest.json').write_bytes(encode(m));return sha((root/'packet-manifest.json').read_bytes())

def controls(root,context,temp):
    baseline=verify(root,context);out=[]
    def require_effective(before,after):need(not same(before,after),'NO_OP_TYPED_TARGET_MUTATION')
    try:require_effective(baseline['numbers']['modelRequests'],copy.deepcopy(baseline['numbers']['modelRequests']))
    except ValueError:noop_canary=True
    else:raise ValueError('NO_OP_CANARY_ACCEPTED')
    names=('summary_completed','summary_bool_zero','parent_fake_success','parent_fake_independent_wait',
           'settling_shortened','admission_schedule_reset','refusal_fake_spawned_pid','summary_fake_qualification')
    for name in names:
        print('CONTROL_BASELINE',name,flush=True)
        with tempfile.TemporaryDirectory(prefix='p4-record-control-',dir=temp) as directory:
            mutant=Path(directory)/'packet';shutil.copytree(root,mutant);verify(mutant,context)
            p=Packet(mutant,MANIFEST);before=sha((mutant/'packet-manifest.json').read_bytes())
            summary=p.json('summary.json')
            if name=='summary_completed':
                old_target=summary['numbers']['completedConditionRows'];summary['numbers']['completedConditionRows']=1;new_target=summary['numbers']['completedConditionRows']
            elif name=='summary_bool_zero':
                old_target=summary['numbers']['modelRequests'];summary['numbers']['modelRequests']=False;new_target=summary['numbers']['modelRequests']
            elif name=='summary_fake_qualification':
                old_target=summary['scope']['backendQualified'];summary['scope']['backendQualified']=True;new_target=summary['scope']['backendQualified']
            elif name.startswith('parent_'):
                parent=p.json('launch/qualification-single-launch.terminal.json')
                if name=='parent_fake_success':
                    old_target=parent['controllerExitCode'];new_target=0
                    parent['controllerExitCode']=0
                    parent['processEvidence']['terminalPolls'][0]['exitCode']=0;parent['processEvidence']['waitCalls'][0]['exitCode']=0
                else:
                    old_target=parent['processEvidence']['waitCalls'][0]['independentKernelWaitClaimed'];new_target=True
                    parent['processEvidence']['waitCalls'][0]['independentKernelWaitClaimed']=True
                write_logical(mutant,'launch/qualification-single-launch.terminal.json',parent)
            elif name=='settling_shortened':
                r=p.json(RUN+'settling/receipt.json');old_target=r['phaseClock']['endMonotonic'];r['phaseClock']['endMonotonic']-=1;new_target=r['phaseClock']['endMonotonic'];r['elapsedSeconds']=r['phaseClock']['endMonotonic']-r['phaseClock']['startMonotonic'];write_logical(mutant,RUN+'settling/receipt.json',r)
            elif name=='admission_schedule_reset':
                r=p.json(RUN+'admission/receipt.json');data=[];old_target=[];new_target=[]
                for i,row in enumerate(p.lines(RUN+'admission/telemetry.jsonl')):
                    old_target.append(row['globalScheduledMonotonic'])
                    row['globalScheduledMonotonic']=r['phaseClock']['startMonotonic']+i*2
                    new_target.append(row['globalScheduledMonotonic'])
                    data.append(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()+b'\n')
                write_logical(mutant,RUN+'admission/telemetry.jsonl',b''.join(data))
            elif name=='refusal_fake_spawned_pid':
                r=p.json(RUN+'owned-process-registry.json');old_target=r['launchRefusals'][0]['spawnedPid'];r['launchRefusals'][0]['spawnedPid']=999999;new_target=r['launchRefusals'][0]['spawnedPid'];write_logical(mutant,RUN+'owned-process-registry.json',r)
            require_effective(old_target,new_target)
            write_logical(mutant,'summary.json',summary);rebound=rebind(mutant);need(rebound!=before,'NO_OP_MANIFEST_MUTATION')
            Packet(mutant,rebound)  # Prove complete physical/logical closure first.
            try:verify(mutant,context,rebound)
            except Exception as error:reason=type(error).__name__+': '+str(error)
            else:raise ValueError('SEMANTIC_CORRUPTION_ACCEPTED '+name)
            expected={'summary_completed':'SUMMARY_NUMERIC_TYPED_MATCH','summary_bool_zero':'SUMMARY_NUMERIC_TYPED_MATCH',
                'summary_fake_qualification':'NO_SCIENTIFIC_PROMOTION','parent_fake_success':'PARENT_ADVERSE_NO_INTERVENTION',
                'parent_fake_independent_wait':'PARENT_WAIT_PROVENANCE','settling_shortened':'PHASE_DURATION',
                'admission_schedule_reset':'GLOBAL_FIXED_SCHEDULE','refusal_fake_spawned_pid':'REFUSED_BEFORE_POPEN_NO_PID'}[name]
            need(expected in reason,'WRONG_REJECTION_PREDICATE '+name+' '+reason)
            out.append({'name':name,'baselineAccepted':True,'mutationWasEffective':True,'manifestAndSourceMapCoherentlyRebound':True,
                'physicalLogicalClosureAccepted':True,'typedTargetMutationEffective':True,'rejected':True,'reason':reason});print('CONTROL_REJECTED',name,reason,flush=True)
    need(sha((root/'packet-manifest.json').read_bytes())==MANIFEST,'ORIGINAL_PACKET_CHANGED')
    return {'schema':'aijade.ch7.p4-records-only-negative-controls.v1','status':'RECORDS_ONLY_BASELINE_AND_8_SEMANTIC_CORRUPTIONS_REJECTED',
        'baseline':baseline,'controls':8,'baselineAccepted':8,'rejected':8,'rows':out,'originalPacketUnchanged':True,
        'equalTypedTargetNoOpCanaryRejected':noop_canary,
        'nineteenLiveQualificationControlsExecuted':False,'currentSdkPhysicallyRechecked':False,'qualified':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path);parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--output',type=Path);parser.add_argument('--temp-root',type=Path);parser.add_argument('--controls',action='store_true');args=parser.parse_args()
    root=args.root or (Path(__file__).with_name('refusal-packet') if Path(__file__).with_name('refusal-packet').is_dir() else Path(__file__).with_name('packet'))
    output=args.output or Path.cwd()/'.runtime/p4-records-only-controls.json';root=root.absolute();output=output.absolute()
    need(not output.exists() and root not in output.parents,'NEW_OUTPUT_OUTSIDE_IMMUTABLE_PACKET_REQUIRED')
    temp=args.temp_root or (BASE/'.runtime/posix/tmp' if sys.platform=='darwin' else Path(os.environ.get('RUNNER_TEMP') or tempfile.gettempdir()))
    if sys.platform=='darwin':need(temp.absolute().is_relative_to(BASE) and output.is_relative_to(BASE),'MAC_OUTPUTS_MUST_REMAIN_IN_AIJADE')
    temp.mkdir(parents=True,exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='p4-record-source-',dir=temp) as directory:
            context=Context(args.repo.resolve(),Path(directory));result=controls(root,context,temp) if args.controls else verify(root,context)
        result['verificationToolSha256']=sha(Path(__file__).read_bytes());output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as stream:stream.write(encode(result))
        print(json.dumps({'status':result['status'],'output':str(output),'sha256':file_sha(output)},sort_keys=True),flush=True);return 0
    except Exception as error:
        failure={'status':'P4_RECORDS_ONLY_VERIFICATION_REFUSED','error':type(error).__name__+': '+str(error),'traceback':traceback.format_exc(),'qualified':False,'currentSdkRechecked':False}
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as stream:stream.write(encode(failure))
        traceback.print_exc();return 1

if __name__=='__main__':raise SystemExit(main())
