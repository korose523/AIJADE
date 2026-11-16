#!/usr/bin/env python3
"""Offline integrity audit of one terminal bulk-census refusal. Never a qualifier.

Only recorded data and immutable Git blobs are read. No observer, native helper,
renderer, model, database, admission, network or credential operation is invoked.
"""
from __future__ import annotations
import argparse,base64,collections,datetime,functools,gzip,hashlib,json,math,re,subprocess,sys,types
from pathlib import Path
import xml.etree.ElementTree as ET
sys.dont_write_bytecode=True
Q='d96152b98f61e3cb47db9ec3d95e00591830d024'
B='a20f090423548dedbf1337ec50786daa9e2d028a'
P='82cfaa2fd4ff7810cab09012829e5b8d7a2c82c9'
H='3e37a85b5bb39669782543fc7197d73eecf2dc1f'
HISTORY='2d52777bc6b34fd8c6410800f0c56268d8132301'
PLAN='experiments/plans/2026-11-16-ch7-mac-bulk-census.md'
PLAN_SHA='d8c5ed7cc58267571c5bdb1ee1cd1043eba9c6a3136f340677d69087575038b5'
BUILD_PATH='experiments/ch7/mac-census-2026-11-16/frozen-build.json'
POLICY_PATH='configs/research/ch7-mac-bulk-process-policy.json'
OLD_MANIFEST_SHA='51d95447adf50e028daddf64b48138000db22fafad45e5d2569687707cd77b6f'
FACTS_SHA='3ab7e3e0ba2251fef89492c0648dcc2a7e5ce021c618b85c7db99e47161adccd'
MANIFEST_SCHEMA='aijade.ch7.mac-bulk-packet-manifest.v1'
AUDIT_SCHEMA='aijade.ch7.mac-bulk-refusal-audit.v1'
AUDIT_STATUS='INDEPENDENT_TERMINAL_REFUSAL_AUDIT_PASS'
SHARED=('codeCommit','implementationCommit','repositoryCommit','buildFreezeCommit','buildFreezePath','inputPublicationCommit',
        'dataPublicationManifestPath','dataPublicationManifestSha256','addedDataPaths','executionPlanSha256','processPolicyPath',
        'processPolicySha256','observerModuleSha256','controllerProcess')

def need(ok,message):
    if not ok:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def unique(pairs):
    result={}
    for key,value in pairs:need(key not in result,'duplicate JSON key');result[key]=value
    return result
def decode(raw):return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def canonical(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
def safe(name):
    need(type(name) is str and name and not name.startswith('/') and '\\' not in name and ':' not in name,'unsafe packet path')
    need(all(x not in ('','.','..','.git','.svn') and not any(ord(c)<32 for c in x) for x in name.split('/')),'unsafe packet path')
    return name
def finite(value):return type(value) in (int,float) and math.isfinite(value)
def integer(value):return type(value) is int and value>=0
def key(row):
    need(type(row.get('pid')) is int and row['pid']>1 and finite(row.get('createTime')) and row['createTime']>0,'invalid owned identity')
    return row['pid'],row['createTime']
def close(a,b):return finite(a) and finite(b) and abs(a-b)<=0.00001
def utc(value):
    d=datetime.datetime.fromisoformat(value.replace('Z','+00:00'));need(d.tzinfo is not None,'missing UTC zone');return d.timestamp()

@functools.lru_cache(maxsize=1536)
def git(repo,commit,path):
    safe(path);need(re.fullmatch('[0-9a-f]{40}',commit) is not None,'full immutable commit required')
    return subprocess.check_output(['git','show',commit+':'+path],cwd=repo,stderr=subprocess.DEVNULL)

def body(root,name):
    name=safe(name);plain=root/name;compressed=root/(name+'.gz')
    need(plain.is_file()!=compressed.is_file(),'missing or ambiguous raw/compressed file: '+name)
    path=plain if plain.is_file() else compressed;need(not path.is_symlink(),'symlink input')
    return path.read_bytes() if path==plain else gzip.decompress(path.read_bytes())
def load(root,name):return decode(body(root,name))
def lines(root,name):
    raw=body(root,name);need(raw.endswith(b'\n') and raw.strip(),'incomplete JSONL: '+name)
    rows=raw.splitlines();need(all(row.strip() for row in rows),'blank JSONL row');return [decode(row) for row in rows]

def verify_manifest(root):
    value=decode((root/'packet-manifest.json').read_bytes())
    need(set(value)=={'schema','files'} and value['schema']==MANIFEST_SCHEMA,'wrong packet manifest schema')
    need(type(value['files']) is list and value['files'],'empty manifest');seen=set()
    for row in value['files']:
        need(type(row) is dict,'manifest row schema');name=safe(row['path']);need(name not in seen and name!='packet-manifest.json','duplicate/self manifest path');seen.add(name)
        need(set(row)==({'path','sha256','sizeBytes','logicalSha256','logicalSizeBytes'} if name.endswith('.gz') else {'path','sha256','sizeBytes'}),'manifest physical/logical fields')
        path=root/name;need(path.is_file() and not path.is_symlink() and not any(p.is_symlink() for p in path.parents),'missing/symlink manifest file')
        raw=path.read_bytes();need(integer(row['sizeBytes']) and len(raw)==row['sizeBytes'] and sha(raw)==row['sha256'],'manifest physical identity: '+name)
        if name.endswith('.gz'):
            need(raw[:2]==b'\x1f\x8b' and raw[4:8]==b'\0'*4,'gzip mtime must be zero')
            restored=gzip.decompress(raw);need(len(restored)==row['logicalSizeBytes'] and sha(restored)==row['logicalSha256'],'manifest logical identity: '+name)
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    need(actual==seen|{'packet-manifest.json'},'complete packet population differs')
    return len(seen)

def source_observer(root,repo):
    for name in ['experiments/ch7/mac_process_guard_v2.py','experiments/ch7/mac_process_guard.py','experiments/ch7/mac_bulk_census.c']:
        need(body(root,'source/'+name)==git(repo,Q,name),'Q source substitution: '+name)
    path=root/'source/experiments/ch7/mac_process_guard_v2.py'
    module=types.ModuleType('aijade_frozen_mac_bulk');module.__file__=str(path)
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module

def history(root,repo):
    frozen=decode(git(repo,Q,'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'))['files'];need(len(frozen)==331,'protected source count')
    for row in frozen:need(sha(git(repo,Q,row['path']))==row['sha256'],'protected source changed: '+row['path'])
    observed=load(root,'audit/post-run-protected-source.json')
    need(observed['schema']=='aijade.ch7.mac-bulk-actual-protected-source.v1' and observed['status']=='ALL_331_ACTUAL_PROTECTED_SOURCE_BYTES_UNCHANGED' and observed['sourceCommit']==Q
         and observed['fileCount']==331 and observed['readOnly'] is True and observed['files']=={row['path']:row['sha256'] for row in frozen},'actual protected-source byte receipt differs from Q/331 freeze')
    prefix='experiments/ch7/mac-formal-2026-11-16/packet'
    old_raw=git(repo,Q,prefix+'/packet-manifest.json');need(sha(old_raw)==OLD_MANIFEST_SHA,'old refusal manifest changed')
    old=decode(old_raw);need(len(old['files'])==85,'old refusal population')
    for row in old['files']:
        raw=git(repo,Q,prefix+'/'+row['path']);need(sha(raw)==row['sha256'] and len(raw)==row['sizeBytes'],'old refusal payload changed')
        if 'logicalSha256' in row:
            restored=gzip.decompress(raw);need(sha(restored)==row['logicalSha256'] and len(restored)==row['logicalSizeBytes'],'old refusal raw changed')
    prefixes=['experiments/ch7/mac-formal-2026-11-16','experiments/ch7/mac-formal-qualification-20261116.json',
              'experiments/ch7/relocated-runtime-2026-11-16','experiments/ch7/relocated-runtime-readiness-20261116.json']
    need(subprocess.check_output(['git','diff','--name-status',HISTORY,Q,'--',*prefixes],cwd=repo)==b'','historical refusal trees changed')
    facts=body(root,'metadata/facts-baseline.json');need(sha(facts)==FACTS_SHA and len(decode(facts))==12311,'old 12311-fact baseline changed')
    return dict(protectedSourceFiles=331,oldRefusalPayloadFiles=85,oldFactBaselineEntries=12311,oldFactBaselineSha256=FACTS_SHA,oldRefusalManifestSha256=OLD_MANIFEST_SHA)

def inputs(root,repo):
    original=decode(git(repo,Q,'experiments/ch7/live-manifest-known-input-v1.json'))
    selected=decode(git(repo,Q,'experiments/ch7/2026-11-12/selection.json'))
    pool=dict(schema='aijade.ch7.archived-candidate-bank.v1',programs=[selected['usable'],selected['unusable']],sources=selected['sources'],
              newModelJudgments=0,newHeldoutCases=0,interpretation='The same two programmes as the old development inputs, not the new candidate pool.')
    selection=body(root,'inputs/selection.json');need(selection==encoded(pool),'original known selection changed')
    for path,digest in selected['sources'].items():need(sha(git(repo,Q,path))==digest,'original candidate/test source changed')
    cases=[dict(input=c,replayAt='before_delivery' if c['operations']['repeatOutcome'] else 'none',
                revokeAt='after_delivery' if c['operations']['revokeBeforeReuse'] else 'none',failurePoint='authority_before' if c['operations']['failStateWrite'] else 'none') for c in original['cases']]
    expected=dict(schema='aijade.ch7.live-case-manifest.v2',purpose='qualification_only',protocolPlanSha256=sha(git(repo,Q,'experiments/plans/2026-11-12-ch7-confirmed-finite-heldout.md')),
                  constructionFreezeCommit=Q,selectionSha256=sha(selection),blockIndex=0,cases=cases)
    runtime=body(root,'inputs/runtime-manifest.json');need(runtime==encoded(expected),'original ten known cases or Q construction identity changed')
    rules=decode(git(repo,Q,'experiments/ch7/manifest-preparation-2026-11-12/comparison-manifest.json'))['cases']
    score=dict(schema='aijade.ch7.finite-scoring-manifest.v1',purpose='qualification_only',constructionFreezeCommit=Q,blockIndex=0,runtimeManifestSha256=sha(runtime),selectionSha256=sha(selection),
               conditions=[{'id':'C1','policy':'strong-local-v1'},{'id':'C2','policy':'cross-module-v1'}],windowRegistrySha256='edaadb5fb69a2e00ca202136273546a79aeece346dfd4caa6096579ccb7f0681',cases=rules,
               scheduledInvalidPromotionOpportunitiesPerCondition=sum(x['promotionOpportunity'] for x in rules),scheduledInvalidReuseOpportunitiesPerCondition=sum(x['reuseOpportunity'] for x in rules),round2SemanticActCorrectness='NOT_MEASURED')
    need(body(root,'inputs/scoring-manifest.json')==encoded(score),'known scoring rules changed')
    return [c['input']['caseId']+'/'+arm for c in cases for arm in c['input']['conditions']]

def publications(root,repo):
    plan=load(root,'publication/plan.json');implementation=load(root,'publication/implementation.json');binary=load(root,'publication/binary-freeze.json');launch=load(root,'publication/launch.json');terminal=load(root,'publication/terminal.json');pre=load(root,'publication/prelaunch.json')
    need(plan['publicCommit']==P and plan['researchIntroductionCommit']==H and plan['sha256']==PLAN_SHA,'plan publication identity')
    need(git(repo,P,PLAN)==git(repo,H,PLAN)==git(repo,Q,PLAN) and sha(git(repo,Q,PLAN))==PLAN_SHA,'prospective plan bytes changed')
    need(implementation['sourceCommit']==Q and binary['sourceCommit']==Q and binary['buildFreezeCommit']==B,'Q/B publication mismatch')
    for commit,record in [(Q,implementation),(B,binary)]:need(subprocess.check_output(['git','rev-parse',commit+'^{tree}'],cwd=repo).decode().strip()==record['tree'],'publication Git tree mismatch')
    for path,name in [(BUILD_PATH,'metadata/frozen-build.json'),('experiments/ch7/mac-census-2026-11-16/native-build.json','metadata/native-build.json'),('experiments/ch7/mac-census-2026-11-16/prepared-renderer-full-tree.json','metadata/prepared-renderer-verification.json')]:
        raw=body(root,name);need(raw==git(repo,B,path),'B metadata bytes changed: '+path)
        need(any(row['path']==path and row['sha256']==sha(raw) and row['bytes']==len(raw) for row in binary['files']),'B publication manifest missing exact metadata')
    need(launch['implementationCommit']==launch['repositoryCommit']==Q and launch['buildFreezeCommit']==B and launch['purpose']=='qualification_only' and launch['automaticRetries']==0,'single launch binding')
    need(pre['Q']==Q and pre['B']==B and pre['configSha256']==launch['configSha256'] and pre['freshCases']==0 and pre['seedConstructed'] is False,'prelaunch/config identity')
    need(utc(plan['checkedAt'])<=utc(implementation['checkedAt'])<=utc(binary['checkedAt'])<=utc(launch['startedAt'])<utc(terminal['finishedAt']),'publication/launch chronology')
    need(terminal['controllerExitCode']==1 and terminal['receiptStatus']=='STOPPED' and terminal['automaticRetries']==0 and terminal['scientificAcceptance'] is False,'terminal refusal altered')
    return launch,terminal

def build_and_engineering(root,repo):
    build=load(root,'metadata/frozen-build.json');native=load(root,'metadata/native-build.json')
    need(build['commit']==Q and build['assemblyInformationalVersion']=='0.1.0+'+Q and len(build['files'])==576 and build['protectedSourceFiles']==331,'frozen build identity')
    need(build['nativeCensus']==native and sha(body(root,'native/mac_bulk_census'))==native['sha256'] and sha(git(repo,Q,'experiments/ch7/mac_bulk_census.c'))==native['sourceSha256'],'native Q/B/body identity')
    post=load(root,'audit/post-run-binaries.json')
    need(post['sourceCommit']==Q and post['buildFreezeCommit']==B and post['buildManifestSha256']==sha(body(root,'metadata/frozen-build.json')) and post['files']==build['files']
         and post['actualFileCount']==576 and post['assemblyContainsQ'] is True and post['nativeHelperSha256']==native['sha256'],'actual post-run binary byte receipt mismatch')
    bound=load(root,'engineering/all-python-controls-source-bound.json')
    need(bound['commit']==Q and bound['exitCode']==0 and bound['unchanged'] is True and sha(body(root,'engineering/all-python-controls-source-bound.log'))==bound['logSha256'],'source-bound control log changed')
    for path,digest in bound['files'].items():need(sha(git(repo,Q,path))==digest,'128-controls source binding changed')
    need(re.search(rb'Ran 128 tests in [0-9.]+s\s+OK\s*$',body(root,'engineering/all-python-controls-source-bound.log')) is not None,'128 controls did not pass')
    ci=load(root,'engineering/source-ci-current.json');need(ci=={'conclusion':'success','headSha':Q,'status':'completed','url':'https://github.com/korose523/AIJADE/actions/runs/43865968775'},'actual Q CI success missing')
    def trx_counts(directory):
        result=collections.Counter();paths=sorted((root/directory).glob('*.trx.gz'));need(len(paths)==2,'two TRX required')
        raw_hashes=set()
        for p in paths:
            raw=body(root,p.relative_to(root).as_posix()[:-3]);raw_hashes.add(sha(raw));tree=ET.fromstring(raw)
            result.update(x.get('outcome') for x in tree.iter() if x.tag.rsplit('}',1)[-1]=='UnitTestResult')
        return dict(result),raw_hashes
    used,used_hashes=trx_counts('engineering/default-regression')
    need(used=={'Passed':684,'NotExecuted':67} and used_hashes=={row['sha256'] for row in build['trx']},'actual used build outcomes changed')
    unused,unused_hashes=trx_counts('engineering/build-attempt-01-external-artifact-root/default-regression')
    failure=load(root,'engineering/build-attempt-01-external-artifact-root/failure-receipt.json')
    need(unused=={'Passed':663,'Failed':21,'NotExecuted':67} and unused_hashes=={x['sha256'] for x in failure['trx']}
         and failure['status']=='FAILED_COMPLETE_DEFAULT_REGRESSION_NOT_USED_FOR_QUALIFICATION','unused first build failure hidden/changed')
    candidate=load(root,'engineering/source-candidate-not-used.json');need(candidate['candidate']=='65bc254ace14d65418fb139ba5f918a49be883f7' and candidate['dotnetBuilds']==candidate['admissionStarts']==0 and candidate['implementationCommit']==Q,'unused first source candidate relabeled')
    checks=load(root,'engineering/default-required-controls-final.json');bank=load(root,'engineering/candidate-bank-control.json')
    need(checks['commit']==Q and checks['defaultPassed']==684 and checks['defaultNotExecuted']==29 and checks['browserNotExecuted']==38 and checks['candidateRecords']==len(bank)==8
         and checks['placementTestRecords']==12 and checks['originalCandidateLabelsUnchanged'] is True and checks['candidateRawSha256']==sha(body(root,'engineering/candidate-bank-control.json')),'default/bank/placement engineering controls mismatch')
    need(all(row['actualExecution']['ok']==row['archivedExecutionOk'] for row in bank),'adverse original bank labels changed')
    return dict(binaryFiles=576,nativeSha256=native['sha256'],nativeSourceSha256=native['sourceSha256'],pythonControls=128,
                usedDefaultPassed=684,usedDefaultSkipped=29,browserSkipped=38,unusedFirstBuildPassed=663,unusedFirstBuildFailed=21,unusedFirstBuildSkipped=29,
                binaryReplayBoundary='CI binds stored actual post-run byte observation to published B; it does not reread the original Mac binaries or execute native code.')

def verify(root,repo,*,check_manifest=True,check_core=True):
    root=Path(root).resolve();repo=str(Path(repo).resolve())
    manifest_files=verify_manifest(root) if check_manifest else None
    module=source_observer(root,repo);prior=history(root,repo);planned=inputs(root,repo);launch,terminal=publications(root,repo);engineering=build_and_engineering(root,repo)
    qroot=root/'qualification';receipt=load(qroot,'receipt.json');policy_raw=body(qroot,'process-policy.json');policy=decode(policy_raw)
    need(policy_raw==git(repo,Q,POLICY_PATH),'policy bytes changed');module.validate_policy(policy)
    need(receipt['codeCommit']==receipt['implementationCommit']==receipt['repositoryCommit']==Q and receipt['buildFreezeCommit']==B and receipt['buildFreezePath']==BUILD_PATH
         and receipt['executionPlanSha256']==PLAN_SHA and receipt['processPolicyPath']==POLICY_PATH and receipt['processPolicySha256']==sha(policy_raw)
         and receipt['observerModuleSha256']==sha(git(repo,Q,'experiments/ch7/mac_process_guard_v2.py')),'sequence Q/B/plan/policy identity')
    need(receipt['inputPublicationCommit'] is None and receipt['dataPublicationManifestPath'] is None and receipt['dataPublicationManifestSha256'] is None and receipt['addedDataPaths']==[],'undeclared fresh input publication')
    need(receipt['status']=='STOPPED' and receipt['purpose']=='qualification_only' and receipt['plannedPairs']==10 and receipt['plannedConditionRows']==20 and receipt['plannedBlocks']==1
         and receipt['completedBlocks']==receipt['completedConditionRows']==receipt['modelRequests']==0 and receipt['blocks']==receipt['inFlightCaseIds']==receipt['unattemptedCaseIds']==[]
         and receipt['unknownCaseIds']==planned and len(planned)==20 and receipt['formalHardwareQualification'] is False and receipt['independentHumanReview'] is False,'terminal original unknown dispositions or scope altered')
    expected={'receipt.json','process-observations.jsonl.gz','block-1-controller.log.gz','sustained-timers.json','process-policy.json','owned-process-registry.json',
              'settling/receipt.json','settling/telemetry.jsonl.gz','admission/receipt.json','admission/telemetry.jsonl.gz'}
    need({p.relative_to(qroot).as_posix() for p in qroot.rglob('*') if p.is_file()}==expected and not(qroot/'block-1').exists(),'hidden/missing block or qualification output')
    need(body(qroot,'block-1-controller.log')==b'' and load(qroot,'sustained-timers.json')=={},'unexpected block output/resource timers')
    if (root/'publication/controller.log.gz').exists():need(decode(body(root,'publication/controller.log'))==receipt,'controller stdout differs from primary receipt')
    seen=set();api_count=0;native_count=0;all_owned=set();controller=key(receipt['controllerProcess']);direct={key(x) for x in receipt['blockControllers']}
    need(len(direct)==1,'one owned block controller required');authorized={controller}|direct
    def replay(sample,idle=False):
        nonlocal api_count,native_count
        obs=sample['processObservation'];sid=obs['sampleId'];need(sid not in seen,'duplicate sample identity');seen.add(sid)
        need(sample['processPolicySha256']==receipt['processPolicySha256'] and sample['observerModuleSha256']==receipt['observerModuleSha256'],'sample source/policy changed')
        need(sample['monotonicSeconds']<=obs['startedMonotonic']<=obs['finishedMonotonic']<=sample['observationCompletedMonotonic'],'sample capture clocks inconsistent')
        roots={key(x) for x in obs['ownedRoots']};need(roots<=authorized,'unleased owned root')
        for phase in ['before','after']:
            data=obs['evidence'][phase];nodes,collector=module.parse_native_evidence(policy,data['processGraph']['nativeCensus']);native_count+=1
            need(nodes==data['processGraph']['nodes'],'native derived graph changed')
            for row in data['ownedProcesses']:all_owned.add(key(row));authorized.add(key(row))
        decision=module.validate_observation(policy,obs)
        need(decision['status']==obs['status'] and decision['blockers']==obs['blockers'] and decision['ownedRssBytes']==obs['ownedRssBytes']==sample['rssBytes'],'claimed process/RSS decision differs from Q replay')
        api=obs['evidence']['api'];raw=base64.b64decode(api['emptyBodyBase64'],validate=True)
        need(decode(raw)=={'models':[]} and sha(raw)==api['bodySha256'] and len(raw)==api['bytes'] and api['modelCount']==0 and api['state']=='EMPTY','explicit API empty evidence changed');api_count+=1
        if idle:need(roots==set() and obs['ownedProcesses']==[] and decision['status']=='PASS' and sample['rssBytes']==0,'unloaded phase not all PASS/empty')
        return decision
    def phase(name,duration,count):
        record=load(qroot,name+'/receipt.json');samples=lines(qroot,name+'/telemetry.jsonl')
        need(all(record.get(k)==receipt[k] for k in SHARED),'phase identity differs')
        need(record['status']==('ADMITTED' if name=='admission' else 'FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION'),'original phase controller status changed')
        clock=record['phaseClock'];start=clock['startMonotonic'];end=clock['endMonotonic']
        need(clock['requestedSeconds']==duration and clock['intervalReset'] is False and duration<=end-start<=duration+3 and close(record['elapsedSeconds'],end-start)
             and len(samples)==record['samples']==count,'fixed phase duration/population changed')
        times=[]
        for index,sample in enumerate(samples):
            elapsed=sample['elapsedSeconds'];times.append(sample['monotonicSeconds'])
            need(sample['scheduledSeconds']==2*index and 2*index<=elapsed<2*index+3 and close(elapsed,sample['monotonicSeconds']-start),'fixed phase schedule/reset changed')
            need(sample['monotonicSeconds']<=sample['observationCompletedMonotonic']<=start+duration and close(sample['observationDurationSeconds'],sample['observationCompletedMonotonic']-sample['monotonicSeconds']),'fixed phase capture outside deadline')
            need(integer(sample['availableBytes']) and integer(sample['swapUsedBytes']),'unknown phase resources');replay(sample,True)
        gap=max(b-a for a,b in zip(times,times[1:]));need(0<gap<=3 and times[0]-start<=3 and duration-3<=times[-1]-start<duration,'phase resource coverage gap')
        need(record['coverage']['samples']==count and close(record['coverage']['maximumGapSeconds'],gap) and record['coverage']['coverageComplete'] is True,'claimed phase coverage changed')
        return record,samples,gap
    settle,settle_samples,settle_gap=phase('settling',600,300);admit,admit_samples,admit_gap=phase('admission',120,60)
    transition=admit['phaseClock']['startMonotonic']-settle['phaseClock']['endMonotonic'];after_admit=receipt['sequenceEpochMonotonic']-admit['phaseClock']['endMonotonic']
    need(transition>3 and 0<=after_admit<=3,'original failed transition changed/concealed')
    min_admit=min(x['availableBytes'] for x in admit_samples);swap_range=max(x['swapUsedBytes'] for x in admit_samples)-min(x['swapUsedBytes'] for x in admit_samples)
    need(min_admit>=4*1024**3 and swap_range<=64*1024**2 and admit['minimumAvailableBytes']==min_admit and admit['swapRangeBytes']==swap_range and admit['noResearchProcesses'] is True and admit['formalHardwareQualification'] is False and admit['windowReset'] is False,'controller admission aggregate/resources changed')
    sequence_auditor=git(repo,Q,'experiments/ch7/finite_sequence_audit.py')
    need(b"require(0 <= start - settling_end <= 3, 'settling/admission transition is not immediate')" in sequence_auditor,'Q whole-sequence transition rule missing')
    rows=lines(qroot,'process-observations.jsonl');samples=[x for x in rows if 'processObservation' in x];errors=[x for x in rows if 'observationError' in x]
    need(len(rows)==9 and len(samples)==receipt['processObservationCount']==8 and len(errors)==1 and rows[-1] is errors[0],'runtime sample/error population changed')
    decisions=[];times=[]
    for sample in samples:
        mono=sample['monotonicSeconds'];times.append(mono);need(close(mono-receipt['sequenceEpochMonotonic'],sample['sequenceElapsedSeconds']) and close(sample['elapsedSeconds'],sample['sequenceElapsedSeconds']),'mixed execution epoch')
        need(integer(sample['availableBytes']) and integer(sample['swapUsedBytes']) and sample['swapIncreaseBytes']==max(0,sample['swapUsedBytes']-receipt['initialSystemSwapUsedBytes']),'runtime resource/baseline changed')
        decisions.append(replay(sample))
    need([d['status'] for d in decisions]==['PASS']*7+['FAIL'],'terminal raw FAIL missing/reclassified')
    final=samples[-1]['processObservation'];need([x['code'] for x in final['blockers']]==['SNAPSHOT_READ_UNKNOWN','OWNED_ROOT_MISSING_OR_REUSED','OWNED_PROCESS_REPARENTED_OUTSIDE_CLOSURE','OWNED_PROCESS_REPARENTED_OUTSIDE_CLOSURE'],'original final failure cascade changed')
    need(final['evidence']['after']['errors']==[{'code':'OWNED_PROCESS_RSS_UNKNOWN','errorClass':'ValueError'}] and final['evidence']['after']['ownedProcesses']==[] and final['ownedRssBytes'] is None,'final unknown RSS converted to success/zero')
    before={x['pid']:x for x in final['evidence']['before']['processGraph']['nodes']};after={x['pid']:x for x in final['evidence']['after']['processGraph']['nodes']}
    for pid,created in {controller}|direct:need(pid in before and pid in after and before[pid]['createTime']==after[pid]['createTime']==created and before[pid]['parentPid']==after[pid]['parentPid'],'surviving controller graph does not support recorded cascade explanation')
    missing=[row for row in final['ownedRoots'] if row['pid'] not in after];need(len(missing)==1,'original missing root changed')
    sentinel=errors[0];need(sentinel['observationError']=='ValueError: process observation adverse or unknown' and sentinel['utc'] is None and sentinel['monotonicSeconds']==samples[-1]['monotonicSeconds'] and sentinel['sequenceElapsedSeconds']==samples[-1]['sequenceElapsedSeconds']
         and receipt['processObservationErrors']==[sentinel['observationError']] and receipt['lastControllerExitCode']==-15,'stop error/child exit altered')
    runtime_gap=max(b-a for a,b in zip(times,times[1:]));need(0<runtime_gap<=3 and 0<=times[0]-receipt['sequenceEpochMonotonic']<=3 and receipt['wallSeconds']-samples[-1]['sequenceElapsedSeconds']<=3,'runtime coverage/cleanup boundary missing')
    registry_raw=body(qroot,'owned-process-registry.json');registry=decode(registry_raw)
    need(sha(registry_raw)==receipt['ownedProcessRegistrySha256'] and registry['status']=='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' and registry['remainingIdentities']==[] and {key(x) for x in registry['controllers']}=={controller} and {key(x) for x in registry['explicitlyRegisteredIdentities']}==direct,'owned registry binding/cleanup changed')
    need({key(x) for x in registry['knownIdentities']}-{controller}=={key(x) for x in registry['retiredIdentities']} and all(x['status'] in ['ABSENT','PID_REUSED_OLD_IDENTITY_ABSENT'] for x in registry['retiredIdentities']),'owned identities not retired')
    exit_proof=load(root,'audit/controller-exit.json');need(exit_proof['receiptSha256']==sha(body(qroot,'receipt.json')) and utc(exit_proof['checkedAt'])>=utc(terminal['finishedAt']) and {key(x) for x in exit_proof['processes']}=={controller}|direct and exit_proof['allAttemptControllersAbsent'] is True and all(x['status'] in ['PID_ABSENT','PID_REUSED_OLD_IDENTITY_ABSENT'] for x in exit_proof['processes']),'independent controller-exit proof absent')
    all_proof=load(root,'audit/all-owned-exit.json');needed=all_owned|{key(x) for x in registry['knownIdentities']}
    need(all_proof['receiptSha256']==sha(body(qroot,'receipt.json')) and utc(all_proof['checkedAt'])>=utc(terminal['finishedAt']) and {key(x) for x in all_proof['processes']}==needed and all_proof['allRecordedOwnedIdentitiesAbsent'] is True and all(x['status'] in ['PID_ABSENT','PID_REUSED_OLD_IDENTITY_ABSENT'] for x in all_proof['processes']),'recorded owned identity absence incomplete')
    numbers=dict(settlingSeconds=settle['elapsedSeconds'],settlingSamples=300,settlingPassSamples=300,settlingUnknownSamples=0,settlingFailSamples=0,settlingMaximumGapSeconds=settle_gap,settlingMinimumAvailableBytes=min(x['availableBytes'] for x in settle_samples),settlingSwapRangeBytes=max(x['swapUsedBytes'] for x in settle_samples)-min(x['swapUsedBytes'] for x in settle_samples),
        admissionSeconds=admit['elapsedSeconds'],admissionSamples=60,admissionPassSamples=60,admissionUnknownSamples=0,admissionFailSamples=0,admissionMaximumGapSeconds=admit_gap,admissionMinimumAvailableBytes=min_admit,admissionSwapRangeBytes=swap_range,settlingToAdmissionGapSeconds=transition,settlingToAdmissionMaximumAllowedGapSeconds=3,admissionToSequenceGapSeconds=after_admit,
        runtimeSequenceSeconds=receipt['wallSeconds'],runtimeSamples=8,runtimeRawRows=9,runtimePassSamples=7,runtimeUnknownSamples=0,runtimeFailSamples=1,runtimeErrorSentinels=1,runtimeMaximumGapSeconds=runtime_gap,runtimeMinimumAvailableBytes=min(x['availableBytes'] for x in samples),runtimePeakKnownOwnedRssBytes=max(x['rssBytes'] for x in samples if x['rssBytes'] is not None),runtimeSwapGrowthBytes=max(x['swapIncreaseBytes'] for x in samples),apiExplicitEmptySamples=api_count,nativeResponseReplays=native_count,
        plannedKnownPairs=10,plannedConditionRows=20,completedBlocks=0,completedConditionRows=0,unknownConditionRows=20,unattemptedConditionRows=0,blockOutputDirectories=0,modelRequests=0,freshHeldoutCases=0)
    need(len(numbers)==41 and api_count==368 and native_count==736,'complete replay population mismatch')
    scope=dict(terminalRecordIntegrityAccepted=True,admissionControllerStatus='ADMITTED',settlingToAdmissionContinuous=False,wholeSequenceAdmissionAudit='REFUSED_SETTLING_ADMISSION_TRANSITION_NOT_IMMEDIATE',fullFiniteDriverQualified=False,formalHardwareQualification=False,heldoutComparisonComplete=False,table7_3='NOT_RUN',independentHumanReview=False,currentProductInheritsResearchQualification=False,freshHeldoutCases=0)
    result=dict(schema=AUDIT_SCHEMA,status=AUDIT_STATUS,sourceCommit=Q,buildFreezeCommit=B,planCommit=P,researchIntroductionCommit=H,planSha256=PLAN_SHA,numbers=numbers,scope=scope,
        history=prior,engineering=engineering,cleanup=dict(recordedOwnedIdentities=len(needed),allOldIdentitiesAbsent=True),
        limitations=['Integrity acceptance is not backend/scientific acceptance.','The phase controller ADMITTED but Q whole-sequence transition rule rejects the 3.631-second gap.',
        'Final FAIL and null owned RSS are preserved. Missing registered root empties closure and produces reparent labels for still-present controllers; this is not evidence those controllers really reparented.',
        'No block directory/case/flow/renderer output exists. Q order supports an inference that flow/renderer was not reached; the census category other does not identify Git or prove a complete OS execution history.',
        'All20 original unknown dispositions remain unknown; no fresh suite, seed, held-out input, outcome scoring or qualification acceptance is created.'])
    if check_core and (root/'audit/independent-refusal-audit.json').exists():
        stored=load(root,'audit/independent-refusal-audit.json');need(stored==result,'stored independent core audit differs from replay')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path);parser.add_argument('--repo',required=True,type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=verify(args.root,args.repo)
    raw=(json.dumps(result,indent=2)+'\n')
    if args.output:need(not args.output.resolve().is_relative_to(args.root.resolve()),'write audit output outside immutable packet');args.output.write_text(raw)
    else:print(raw,end='')
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError,ET.ParseError) as error:print('REFUSAL_PACKET_REJECTED: '+str(error),file=sys.stderr);raise SystemExit(2)
