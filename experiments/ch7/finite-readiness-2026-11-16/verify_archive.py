#!/usr/bin/env python3
"""Offline verification of instrument readiness and two refused windows. Never a live-comparison certificate."""
from collections import Counter
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET
from datetime import datetime

SOURCE='1ca27162beb53e0757f76199da420b66ad1d2161'
REGRESSION='2489bf6e61e289068f89a73d4a4a5ae252e93f59'
SHA=lambda b:hashlib.sha256(b).hexdigest()


def require(ok,why):
    if not ok:raise ValueError(why)
def oid(kind,data):return hashlib.sha1(kind.encode()+b' '+str(len(data)).encode()+b'\0'+data).hexdigest()


def verify(root,overrides=None):
    overrides=overrides or {}
    def read(rel):
        p=PurePosixPath(rel);require(not p.is_absolute() and '..' not in p.parts,'unsafe archive path')
        return overrides[rel] if rel in overrides else (root/rel).read_bytes()
    def load(rel):return json.loads(read(rel))
    listing=load('manifest.json');seen=set()
    for row in listing['files']:
        require(row['path'] not in seen,'duplicate archive file');seen.add(row['path'])
        value=read(row['path']);require(len(value)==row['bytes'] and SHA(value)==row['sha256'],'archive bytes/hash')
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'manifest.json'}
    require(actual==seen,'archive file population')
    proof=load('source-membership.json');require(proof['sourceCommit']==SOURCE,'wrong source commit')
    commit=read('git-source-proof/commit.raw');require(oid('commit',commit)==SOURCE,'Git commit bytes')
    tree=commit.splitlines()[0].decode().split()[1];require(tree==proof['rootTree'],'Git root tree')
    parent='971a99f68ceafb448bee9a572297304c9f85f8ab'
    require(('parent '+parent).encode() in commit.splitlines(),'source parent')
    parent_bytes=read('git-source-proof/'+parent+'.commit.raw')
    regression_bytes=read('git-source-proof/'+REGRESSION+'.commit.raw')
    require(oid('commit',parent_bytes)==parent and ('parent '+REGRESSION).encode() in parent_bytes.splitlines() and oid('commit',regression_bytes)==REGRESSION,'regression ancestry')
    cache={}
    def entries(key):
        if key in cache:return cache[key]
        data=read('git-source-proof/'+key+'.tree');require(oid('tree',data)==key,'Git tree bytes')
        result={};i=0
        while i<len(data):
            a=data.index(b' ',i);b=data.index(b'\0',a);name=data[a+1:b].decode();require(name not in result,'duplicate tree entry')
            result[name]=(data[i:a].decode(),data[b+1:b+21].hex());i=b+21
        require(i==len(data),'malformed tree');cache[key]=result;return result
    bound={}
    for f in proof['files']:
        parts=PurePosixPath(f['path']).parts;require(not PurePosixPath(f['path']).is_absolute() and '..' not in parts,'unsafe source path')
        current=tree
        for component in parts[:-1]:
            mode,current=entries(current)[component];require(mode=='40000','source parent not tree')
        mode,digest=entries(current)[parts[-1]];body=read('frozen-source/'+f['path'])
        require(mode==f['mode'] and digest==f['gitBlobSha1']==oid('blob',body),'source Git membership')
        require(SHA(body)==f['sha256'] and len(body)==f['bytes'],'source SHA-256/length')
        require(f['path'] not in bound,'duplicate bound source');bound[f['path']]=f
    parent_tree=parent_bytes.splitlines()[0].decode().split()[1]
    def lookup(root_key,path):
        current=root_key;parts=PurePosixPath(path).parts
        for i,component in enumerate(parts):
            found=entries(current).get(component)
            if found is None:return None
            mode,value=found
            if i==len(parts)-1:return value
            require(mode=='40000','order-audit parent tree');current=value
    audit=proof['prospectiveOrderAudit'];require(audit['parentCommit']==parent,'order-audit parent')
    plan_path='experiments/plans/2026-11-12-ch7-finite-qualification-settling.md';driver_path='experiments/ch7/run_finite_sequence.py'
    require(audit['settlingPlanPath']==plan_path and audit['controllerPath']==driver_path,'order-audit paths')
    require(lookup(parent_tree,plan_path) is None and lookup(tree,plan_path) is not None and lookup(parent_tree,driver_path)!=lookup(tree,driver_path),'settling plan/implementation commit order')
    require(audit['planPresentInParent'] is False and audit['planPresentInSource'] is True and audit['controllerChangedInSameCommit'] is True,'order-audit disclosure changed')
    require(len(cache)==proof['treeObjects'],'unused/missing tree count')
    old_root=read('git-source-proof/regression-root.tree');old_tree=regression_bytes.splitlines()[0].decode().split()[1]
    require(oid('tree',old_root)==old_tree,'regression tree bytes')
    old_entries={};i=0
    while i<len(old_root):
        a=old_root.index(b' ',i);b=old_root.index(b'\0',a);old_entries[old_root[a+1:b].decode()]=(old_root[i:a].decode(),old_root[b+1:b+21].hex());i=b+21
    for key in ['src','tests','tools','Directory.Build.props','Directory.Packages.props','global.json']:
        require(entries(tree)[key]==old_entries[key],'build/test source changed since the completed default regression')
    protected=load('source-bindings/experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json')['files']
    require(len(protected)==331 and proof['oldProtectedSourceFiles']==331,'protected source count')
    for f in protected:require(bound[f['path']]['sha256']==f['sha256'] and bound[f['path']]['gitBlobSha1']==f['gitBlobSha1'],'historical protected source changed')
    ci=load('source-ci.json');require(ci['head']==SOURCE and ci['status']=='completed' and ci['conclusion']=='success','source CI identity')
    readiness=load('readiness.json')
    require(readiness['status']=='INSTRUMENT_CONTROLS_PASS_FULL_QUALIFICATION_NOT_RUN','readiness scope')
    require(readiness['sourceCommit']==SOURCE and readiness['defaultRegressionCommit']==REGRESSION,'regression/source identity')
    for key in ['fullFiniteDriverQualified','heldoutComparisonComplete','newCaseConstructionAllowed','formalHardwareQualification','independentHumanReview']:
        require(readiness[key] is False,'unearned gate: '+key)
    require(readiness['table7_3']=='NOT_RUN' and readiness['caseGenerationSeed'] is None,'invented held-out outcome')
    deviation=load('prospective-order-deviation.json')
    require(readiness['implementationOrderDeviation'] is True and deviation['sameCommitAsImplementation'] is True and deviation['commit']==SOURCE and deviation['primaryDataChanged'] is False,'implementation-order deviation hidden')
    ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    trx=ET.fromstring(read('engineering/default-2489bf6.trx'));counter=trx.find('.//t:Counters',ns).attrib
    individual=Counter(r.attrib['outcome'] for r in trx.findall('.//t:UnitTestResult',ns))
    require(individual=={'Passed':687,'NotExecuted':26},'complete individual test outcomes')
    require(int(counter['total'])==713 and int(counter['passed'])==687 and int(counter['failed'])==0,'native test summary')
    require(readiness['trxCounterScope']['rawAggregateNotExecuted']==int(counter['notExecuted'])==0 and readiness['trxCounterScope']['individualNotExecuted']==26,'TRX representation discrepancy hidden')
    build=load('engineering/build-checks-2489bf6.json');require(build['commit']==REGRESSION and all(s['exitCode']==0 for s in build['steps']),'default regression not complete')
    bank=load('frozen-source/experiments/ch7/finite-heldout/candidate-bank.json')
    for p,digest in bank['sources'].items():require(SHA(read('frozen-source/'+p))==digest,'original candidate/test source')
    base='frozen-source/experiments/rq-c/redo/rq-c-s42-ollama-t30-r5/'
    candidates=[json.loads(l) for l in read(base+'candidates.jsonl').splitlines()]
    trials=[json.loads(l) for l in read(base+'trials.jsonl').splitlines()]
    eligible=[];excluded={'arr-sum','parse-query-string','str-to-camel','math-round-to','parse-csv-line'}
    for i,(c,t) in enumerate(zip(candidates,trials),1):
        if t['condition']=='sv1-ef0' and not t['reused'] and t['round']==t['attempt']==0 and t['taskId'] not in excluded:
            require(c['skillId']==t['skillId'] and c['execOk']==t['execOk'],'candidate/trial join')
            eligible.append(dict(taskId=t['taskId'],line=i,candidate=c,trial=t,code=c['code'],codeSha256=SHA(c['code'].encode())))
    selected=[]
    for label in [True,False]:
        tasks=sorted({p['taskId'] for p in eligible if p['trial']['execOk'] is label})[:4]
        require(len(tasks)==4,'candidate stratum')
        selected.extend(next(p for p in eligible if p['taskId']==task and p['trial']['execOk'] is label) for task in tasks)
    require(selected==bank['programs'] and set(bank['excludedTasks'])==excluded,'prospective selection drift')
    replays=load('engineering/candidate-replay-2489bf6.json');require(len(replays)==8,'candidate replay population')
    for p,r in zip(selected,replays):
        require((p['taskId'],p['codeSha256'],p['trial']['execOk'])==(r['taskId'],r['codeSha256'],r['archivedExecutionOk']),'replay binding')
        require(type(r['actualExecution']['ok']) is bool and r['actualExecution']['ok'] is r['archivedExecutionOk'],'original-label disagreement')
    known=load('frozen-source/experiments/ch7/live-manifest-known-input-v1.json')
    configs=[('replay',p) for p in ['before_delivery','after_delivery','after_first_reuse','after_duplicate_reuse']]+[
        ('revoke',p) for p in ['before_delivery','after_delivery','after_memory_probe','after_authority_probe']]+[
        ('failure',p) for p in ['authority_before','authority_after','outcome_before','outbox_before']]
    control_rows=0
    for operation,placement in configs:
        rows=load('engineering/placement-controls-2489bf6/'+operation+'-'+placement+'.json')
        require([r['condition'] for r in rows]==['C1','C2'],'placement-control condition population')
        for r in rows:
            control_rows+=1;finite=r['runtimeInput'];old=finite['input'];op=old['operations'];final=r['final'];phases=r['controlPhases']
            require(old in known['cases'] and r['batch']=='qualification_only' and r['dataOrigin']=='known_scenario_qualification','new-case claim in reused-evidence control')
            require(r['gatewayAttempts']==0 and len(r['importPosts'])==20 and all(p['status']==201 for p in r['importPosts']),'actual import/provider control')
            require(r['policyVersion']==('strong-local-v1' if r['condition']=='C1' else 'cross-module-v1'),'policy version')
            seq=lambda name:phases.index(name)
            if operation=='failure':
                w=r['databaseErrorWitness'];require(r['databaseErrorCode']=='P0001' and w['point']==placement and w['specs']==w['reports']==1,'in-transaction failure witness')
                table,timing={'authority_before':('research_skill_authority','BEFORE'),'authority_after':('research_skill_authority','AFTER'),
                    'outcome_before':('research_outcomes','BEFORE'),'outbox_before':('research_outbox','BEFORE')}[placement]
                require(w['table']==table and w['timing']==timing and w['operation']=='INSERT','failure table/timing')
                require(w['authority']==(0 if placement=='authority_before' else 1) and w['outcomes']==(1 if placement=='outbox_before' else 0) and w['outbox']==0,'failure visibility counts')
                expected=1 if r['condition']=='C1' else 0
                require(final['specs']==final['reports']==expected and final['authority']==[] and final['outcomes']==[] and final['outboxCount']==0,'actual rollback boundary')
            elif operation=='replay':
                require(finite['replayAt']==placement and op['repeatOutcome'] is True,'replay operation')
                require(r['duplicateCommit']['duplicate'] is True and r['round2']['executed'] is True and r['duplicateReuse']['executed'] is False,'actual duplicate outcome')
                lo,hi={'before_delivery':('commit.end','delivery.begin'),'after_delivery':('delivery.end','round2.begin'),
                    'after_first_reuse':('round2.first.end','round2.duplicate.end'),'after_duplicate_reuse':('round2.duplicate.end','round2.end')}[placement]
                require(seq(lo)<seq('replay.begin')<seq('replay.end')<seq(hi),'actual replay phase')
                require(final['specs']==final['reports']==final['reuseCount']==1,'replay durable/reuse counts')
            else:
                require(finite['revokeAt']==placement and op['revokeBeforeReuse'] is True,'revocation operation')
                require(seq('revoke.end')<seq('round2.begin') and r['round2']['retrieved'] is True and r['round2']['executed'] is False and r['round2']['reason']=='authority_revoked','stale memory/current authority')
                require(final['specs']==final['reports']==1 and final['authority'][0]['state']=='revoked' and final['reuseCount']==0,'revocation durable/reuse state')
                if placement in ['after_memory_probe','after_authority_probe']:
                    name=placement[6:];require(seq(name+'.end')<seq('revoke.begin'),'probe timing')
                    require(any(t['operation']==name for t in r['operationTrace']),'actual probe capture absent')
    observations=[]
    for i in [1,2]:
        prefix='qualification-0'+str(i)+'/'
        receipt=load(prefix+'admission/receipt.json');population=load(prefix+'receipt.json')
        samples=[json.loads(l) for l in read(prefix+'admission/telemetry.jsonl').splitlines()]
        require(len(samples)==receipt['samples'] and samples[-1]['elapsedSeconds']==receipt['elapsedSeconds']>=120,'complete fixed admission window')
        require(all(b['elapsedSeconds']>a['elapsedSeconds'] for a,b in zip(samples,samples[1:])),'admission clock order')
        available=min(s['availableBytes'] for s in samples);swap=max(s['swapUsedBytes'] for s in samples)-min(s['swapUsedBytes'] for s in samples)
        require(receipt['minimumAvailableBytes']==available and receipt['swapRangeBytes']==swap,'admission extrema')
        admitted=available>=4*1024**3 and swap<=64*1024**2 and all(not s['researchProcesses'] for s in samples)
        require(not admitted and receipt['status']==population['status']=='NOT_ADMITTED_NO_MEASUREMENT','refused admission relabelled')
        require(population['completedBlocks']==population['completedConditionRows']==0 and population['blocks']==[] and population['inFlightCaseIds']==[],'invented live completion')
        runtime=load(('qualification-inputs/' if i==1 else 'qualification-inputs-02/')+'runtime-manifest.json')
        expected=[c['input']['caseId']+'/'+a for c in runtime['cases'] for a in c['input']['conditions']]
        require(len(expected)==20 and population['unattemptedCaseIds']==expected,'lost unattempted rows')
        require(population['modelRequests']==0 and population['formalHardwareQualification'] is False and population['independentHumanReview'] is False,'scope inflation')
        observations.append(receipt)
    settling=load('qualification-02/settling/receipt.json');samples=[json.loads(l) for l in read('qualification-02/settling/telemetry.jsonl').splitlines()]
    require(settling['elapsedSeconds']==samples[-1]['elapsedSeconds']>=600 and settling['samples']==len(samples),'fixed settling span')
    require(settling['intervalReset'] is False and settling['measurementStarted'] is False,'settling reclassified')
    require(datetime.fromisoformat(ci['createdAt'].replace('Z','+00:00'))<datetime.fromisoformat(samples[0]['utc']),'source was not externally observed before settling')
    numbers=dict(defaultPassed=687,defaultSkipped=26,defaultTotal=713,protectedSourceFiles=331,candidatePrograms=8,
        originallyPassingPrograms=4,originallyFailingPrograms=4,entryBlockedPrograms=sum(r['actualExecution'].get('error') is not None for r in replays),
        placementConfigurations=len(configs),placementConditionRecords=control_rows,admissionWindows=2,
        completedFiniteQualificationRows=0,freshHeldoutCases=0,newModelRequests=0,settlingSeconds=settling['elapsedSeconds'],settlingSamples=len(samples))
    for name,r in zip(['first','second'],observations):
        numbers.update({name+'AdmissionSeconds':r['elapsedSeconds'],name+'AdmissionSamples':r['samples'],name+'MinimumAvailableBytes':r['minimumAvailableBytes'],name+'SwapRangeBytes':r['swapRangeBytes']})
    require(set(numbers)==set(readiness['numbers']) and all(type(readiness['numbers'][k]) is type(v) for k,v in numbers.items()) and numbers==readiness['numbers'],'readiness numerical reconstruction')
    require([r['swapRangeBytes'] for r in observations]==[167772160,100663296],'original resource outcomes changed')
    return dict(status='READINESS_ARCHIVE_VERIFIED_LIVE_QUALIFICATION_NOT_RUN',boundSourceFiles=len(bound),gitTreesVerified=len(cache),
        placementConfigurations=len(configs),placementConditionRecords=control_rows,admissionWindows=2,numbers=numbers,
        fullFiniteDriverQualified=False,newCaseConstructionAllowed=False,heldoutComparisonComplete=False,
        interpretation='Known-evidence instrument checks and refused resource windows only; not a new live renderer batch or scientific held-out result.')


def controls(root):
    original=(root/'manifest.json').read_bytes();listing=json.loads(original);results=[]
    cases=['invented-full-qualification','invented-case-seed','changed-trx-count','changed-source-body',
           'refusal-marked-admitted','invented-completed-row','changed-candidate-label','changed-failure-witness']
    cases.append('hidden-order-deviation')
    for name in cases:
        overrides={}
        if name in ['invented-full-qualification','invented-case-seed','changed-trx-count','hidden-order-deviation']:
            rel='readiness.json';obj=json.loads((root/rel).read_text())
            if name=='invented-full-qualification':obj['fullFiniteDriverQualified']=True
            elif name=='invented-case-seed':obj['caseGenerationSeed']='a'*64
            elif name=='changed-trx-count':obj['numbers']['defaultSkipped']+=1
            else:obj['implementationOrderDeviation']=False
        elif name=='changed-source-body':
            rel='frozen-source/tests/Aijade.Tests/ResearchFiniteManifestTests.cs';overrides[rel]=(root/rel).read_bytes()+b'\n// changed\n';obj=None
        elif name=='refusal-marked-admitted':rel='qualification-02/admission/receipt.json';obj=json.loads((root/rel).read_text());obj['status']='ADMITTED'
        elif name=='invented-completed-row':rel='qualification-02/receipt.json';obj=json.loads((root/rel).read_text());obj['completedConditionRows']=1
        elif name=='changed-candidate-label':rel='engineering/candidate-replay-2489bf6.json';obj=json.loads((root/rel).read_text());obj[0]['archivedExecutionOk']=False
        else:rel='engineering/placement-controls-2489bf6/failure-authority_after.json';obj=json.loads((root/rel).read_text());obj[0]['databaseErrorWitness']['authority']=0
        if obj is not None:overrides[rel]=(json.dumps(obj,indent=2)+'\n').encode()
        require(overrides[rel]!=(root/rel).read_bytes(),'no-op rejection fixture')
        mutated=copy.deepcopy(listing)
        for row in mutated['files']:
            if row['path'] in overrides:row.update(bytes=len(overrides[row['path']]),sha256=SHA(overrides[row['path']]))
        overrides['manifest.json']=(json.dumps(mutated,indent=2)+'\n').encode()
        try:verify(root,overrides)
        except (ValueError,KeyError,TypeError) as error:results.append(dict(control=name,rejected=True,reason=type(error).__name__+': '+str(error)))
        else:raise AssertionError('coherently rebound corruption accepted: '+name)
    require((root/'manifest.json').read_bytes()==original,'control modified primary bytes')
    return dict(status='PASS',rejectedCorruptions=len(results),controls=results,primaryUnchanged=True,scope='Disposable byte overlays with rebound per-file manifest hashes; no primary data mutation or new observations.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);p.add_argument('--controls',action='store_true');a=p.parse_args()
    result=verify(a.root)
    if a.controls:result['corruptionControls']=controls(a.root)
    print(json.dumps(result,indent=2))
