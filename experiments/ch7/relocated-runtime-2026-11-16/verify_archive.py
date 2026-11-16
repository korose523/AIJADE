#!/usr/bin/env python3
"""Offline reconstruction of the relocated-runtime preflight and refused admission."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

SOURCE='3dc0644da43054ad879cfeb1d2b3a57313f57ff8'
BASE='46efbfc88a25ee4ea9af536112f20e7d202bcff9'
PLAN='0dd5b04e1fc77325c6f7e7aa97c21ac86c0d310c'
IMPLEMENTATION='caf82e988dff283b51c2f2acd89a26998fa1cfcd'
BUILD='c3164ecc4c13826b53466e386a94e38439ab6581'
PLAN_PATH='experiments/plans/2026-11-16-ch7-relocated-runtime-qualification.md'
BUILD_PATH='experiments/ch7/relocated-runtime-2026-11-16/frozen-build.json'
SHA=lambda b:hashlib.sha256(b).hexdigest()
def require(value,message):
    if not value:raise ValueError(message)
def oid(kind,data):return hashlib.sha1(kind.encode()+b' '+str(len(data)).encode()+b'\0'+data).hexdigest()
def verify(root,overrides=None):
    overrides=overrides or {}
    def read(path):
        p=PurePosixPath(path);require(not p.is_absolute() and '..' not in p.parts,'unsafe packet path')
        return overrides[path] if path in overrides else (root/path).read_bytes()
    def load(path):return json.loads(read(path))
    manifest=load('manifest.json');seen=set()
    for row in manifest['files']:
        require(row['path'] not in seen,'duplicate packet file');seen.add(row['path'])
        data=read(row['path']);require(len(data)==row['bytes'] and SHA(data)==row['sha256'],'packet file bytes/hash')
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'manifest.json'}
    require(actual==seen,'complete packet population')
    proof=load('git-membership.json');require(proof['sourceCommit']==SOURCE and proof['baseCommit']==BASE and proof['planCommit']==PLAN and proof['buildFreezeCommit']==BUILD,'Git proof anchors')
    commits={};bodies={};trees={}
    for key in [BASE,PLAN,IMPLEMENTATION,SOURCE,BUILD]:
        data=read('git-proof/'+key+'.commit');require(oid('commit',data)==key,'raw Git commit')
        commits[key]=data.splitlines()[0].decode().split()[1];bodies[key]=data
    for child,parent in [(PLAN,BASE),(IMPLEMENTATION,PLAN),(SOURCE,IMPLEMENTATION),(BUILD,SOURCE)]:
        require([l.decode() for l in bodies[child].splitlines() if l.startswith(b'parent ')]==['parent '+parent],'separate plan/implementation/build ancestry')
    def tree(key):
        if key in trees:return trees[key]
        data=read('git-proof/'+key+'.tree');require(oid('tree',data)==key,'raw Git tree')
        rows={};i=0
        while i<len(data):
            a=data.index(b' ',i);b=data.index(b'\0',a);name=data[a+1:b].decode();require(name not in rows,'duplicate tree name')
            rows[name]=(data[i:a].decode(),data[b+1:b+21].hex());i=b+21
        require(i==len(data),'malformed tree');trees[key]=rows;return rows
    def lookup(commit,path):
        current=commits[commit];parts=PurePosixPath(path).parts
        for i,name in enumerate(parts):
            result=tree(current).get(name)
            if result is None:return None
            mode,key=result
            if i==len(parts)-1:return mode,key
            require(mode=='40000','parent not directory');current=key
    def diff(a,b,prefix=''):
        if a==b:return []
        left,right=tree(a),tree(b);out=[]
        for name in sorted(set(left)|set(right)):
            x,y=left.get(name),right.get(name)
            if x==y:continue
            path=prefix+name
            if x and y and x[0]==y[0]=='40000':out+=diff(x[1],y[1],path+'/')
            elif x is None and y[0]=='40000':out+=leaves(y[1],path+'/')
            elif y is None and x[0]=='40000':out+=leaves(x[1],path+'/')
            else:out.append(path)
        return out
    def leaves(key,prefix):
        out=[]
        for name,(mode,value) in sorted(tree(key).items()):
            if mode=='40000':out+=leaves(value,prefix+name+'/')
            else:out.append(prefix+name)
        return out
    require(diff(commits[BASE],commits[PLAN])==[PLAN_PATH],'plan was not published alone')
    require(diff(commits[SOURCE],commits[BUILD])==[BUILD_PATH],'build evidence changed execution source')
    bound={}
    for row in proof['files']:
        pair=(row['commit'],row['path']);require(pair not in bound,'duplicate source binding')
        data=read(row['archivePath']);require(lookup(*pair)==(row['mode'],row['gitBlobSha1']),'bound Git membership')
        require(oid('blob',data)==row['gitBlobSha1'] and len(data)==row['bytes'] and SHA(data)==row['sha256'],'bound source bytes')
        bound[pair]=row
    source=lambda path:read(bound[(SOURCE,path)]['archivePath'])
    protected_path='experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'
    require(lookup(BASE,protected_path)==lookup(SOURCE,protected_path),'earlier source freeze changed')
    protected=json.loads(source(protected_path))['files'];require(len(protected)==331,'protected count')
    for row in protected:
        body=source(row['path']);require(SHA(body)==row['sha256'] and oid('blob',body)==row['gitBlobSha1'],'protected source changed')
    for path in ['experiments/ch7/finite_inputs.py','experiments/ch7/finite_score.py','experiments/ch7/finite_validate.py','experiments/ch7/finite-heldout/candidate-bank.json']:
        require(lookup(BASE,path)==lookup(SOURCE,path),'construction/scoring/bank drift')
    require(read('frozen-build.json')==read(bound[(BUILD,BUILD_PATH)]['archivePath']),'public binary freeze coherently rebound')
    build=load('frozen-build.json');require(build['commit']==SOURCE and build['assemblyInformationalVersion']=='0.1.0+'+SOURCE,'build revision')
    require('AssemblyInformationalVersionAttribute("0.1.0+'+SOURCE+'")' in build['assemblyInfo'],'generated build metadata')
    require(len(build['files'])==576 and all(re.fullmatch('[0-9a-f]{64}',v) for v in build['files'].values()),'binary hash population')
    require({'Aijade.Tests.dll','Aijade.Tests.deps.json','Aijade.Tests.runtimeconfig.json'}<=set(build['files']),'required build dependencies')
    require(all(x['exitCode']==0 for x in build['steps']),'build/regression unsuccessful')
    ci=load('publication/execution-source-ci.json');require(ci['headSha']==SOURCE and ci['status']=='completed' and ci['conclusion']=='success','source CI')
    plan=load('publication/prospective-plan-publication.json');binary=load('publication/binary-freeze-publication.json')
    require(plan['status']=='PLAN_ALONE_PUBLIC_BEFORE_IMPLEMENTATION_AND_SERVICE_SETUP' and plan['commit']==PLAN and plan['changedFiles']==[PLAN_PATH],'prospective publication')
    require(plan['sha256']==SHA(source(PLAN_PATH)),'plan SHA')
    require(binary['sourceCommit']==SOURCE and binary['buildFreezeCommit']==BUILD and binary['frozenBuildSha256']==SHA(read('frozen-build.json')) and binary['qualificationWindowStarted'] is False,'binary publication')
    setup=load('runtime/runtime-setup.json')
    require(setup['status']=='PROJECT_LOCAL_RUNTIME_READY' and setup['elapsedSeconds']<=1800 and setup['vmStartInvocations']==2 and setup['vmCpu']==2 and setup['vmMemoryGiB']==2,'service preparation limits')
    require(datetime.fromisoformat(plan['checkedAt'])<datetime.fromisoformat(setup['startedAt']),'setup preceded public plan')
    require(load('runtime/runtime-setup-first.json')['status']!='PROJECT_LOCAL_RUNTIME_READY','first setup failure lost')
    sql=load('runtime/real-owned-database-control.json');require(sql['status']=='PASS_REAL_OWNED_CREATE_DROP_AND_ABSENCE_REQUERY','real database lifecycle absent')
    require(sql['created']['exitCode']==0 and sql['cleanup'][0]['presentAfterProcessExit']==1 and sql['cleanup'][0]['remaining']==0 and sql['cleanup'][0]['error'] is None and sql['independentAfterQuery']['stdout']=='0\n1\n','database cleanup unknown')
    require(all(r['exitCode']==0 for r in sql['commands']) and len(sql['commands'])==3,'real SQL command population')
    path_controls=load('engineering/launcher-controls-native-root.json');require(path_controls['status']=='PASS' and len(path_controls['checks'])==path_controls['total']==11,'path controls')
    control_log=read('engineering/runtime-controls-recursive-build.log').decode();require('Ran 13 tests' in control_log and control_log.rstrip().endswith('OK') and len(re.findall(r'^test_',control_log,re.M))==13,'runtime fault controls')
    sandbox=load('runtime/sandbox-write-boundary-device.json');require(sandbox['exitCode']==0 and json.loads(sandbox['stdout'])=={'insideWrite':True,'outsideErrno':1,'outsideDenied':True},'actual write boundary')
    require(load('runtime/godot-contained-version.json')['exitCode']==0,'contained Godot SDK check')
    require(load('runtime/renderer-preparation.json')['status']=='PREBUILT_NO_RUNTIME_REBUILD','renderer preparation')
    ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    def outcomes(directory):
        groups={}
        for row in manifest['files']:
            if row['path'].startswith(directory+'/') and row['path'].endswith('.trx'):
                results=ET.fromstring(read(row['path'])).findall('.//t:UnitTestResult',ns)
                key='browser' if all(r.attrib['testName'].startswith('Aijade.E2E.') for r in results) else 'unit'
                require(key not in groups,'duplicate TRX population');groups[key]=Counter(r.attrib['outcome'] for r in results)
        return groups
    bad=outcomes('engineering/failed-default-regression');good=outcomes('engineering/corrected-default-regression')
    require(bad=={'browser':{'NotExecuted':38},'unit':{'Passed':640,'NotExecuted':29,'Failed':44}},'first regression hidden/changed')
    require(good=={'browser':{'NotExecuted':38},'unit':{'Passed':684,'NotExecuted':29}},'complete corrected regression')
    correction=load('engineering/default-regression-failure-and-prospective-correction.json')
    require(correction['failureCategories']=={'assembly_location_root_discovery':21,'global_redis_changed_inline_fixture':23} and len(correction['failures'])==44 and correction['prospectiveCorrection']['sourceFilesChanged']==0,'failure/correction population')
    require(datetime.fromisoformat(correction['recordedAt'])<datetime.fromisoformat(build['checkedAt']),'correction not recorded before build freeze')
    runtime=load('qualification-inputs/runtime-manifest.json');score=load('qualification-inputs/scoring-manifest.json')
    require(runtime['purpose']=='qualification_only' and runtime['constructionFreezeCommit']==SOURCE and len(runtime['cases'])==10,'known qualification input scope')
    old=json.loads(source('experiments/ch7/live-manifest-known-input-v1.json'))
    require([c['input'] for c in runtime['cases']]==old['cases'],'new cases substituted')
    require(score['runtimeManifestSha256']==SHA(read('qualification-inputs/runtime-manifest.json')) and runtime['selectionSha256']==SHA(read('qualification-inputs/selection.json')),'known input hashes')
    settle=load('qualification/settling/receipt.json');s=[json.loads(l) for l in read('qualification/settling/telemetry.jsonl').splitlines()]
    require(settle['status']=='FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION' and settle['elapsedSeconds']==s[-1]['elapsedSeconds']>=600 and settle['samples']==len(s) and settle['intervalReset'] is False and settle['measurementStarted'] is False,'fixed settling population/time')
    require(datetime.fromisoformat(binary['checkedAt'])<datetime.fromisoformat(s[0]['utc']),'binary freeze followed settling')
    require(all(datetime.fromisoformat(j['completedAt'].replace('Z','+00:00'))<datetime.fromisoformat(s[0]['utc']) for j in ci['jobs']),'source CI completed after settling')
    admission=load('qualification/admission/receipt.json');a=[json.loads(l) for l in read('qualification/admission/telemetry.jsonl').splitlines()]
    require(admission['elapsedSeconds']==a[-1]['elapsedSeconds']>=120 and len(a)==admission['samples']==60,'complete fixed admission')
    for rows in [s,a]:
        require(all(y['elapsedSeconds']>x['elapsedSeconds'] and datetime.fromisoformat(y['utc'])>datetime.fromisoformat(x['utc']) for x,y in zip(rows,rows[1:])),'sample time order')
        require(all(not any((p['name'] or '').lower()=='dotnet' or 'godot' in (p['name'] or '').lower() for p in row['researchProcesses']) for row in rows),'unreported compiler/renderer during unloaded phases')
    require(datetime.fromisoformat(s[-1]['utc'])<=datetime.fromisoformat(a[0]['utc']),'admission preceded settling')
    available=min(r['availableBytes'] for r in a);swap=max(r['swapUsedBytes'] for r in a)-min(r['swapUsedBytes'] for r in a)
    process_samples=sum(bool(r['researchProcesses']) for r in a)
    require(admission['minimumAvailableBytes']==available>=4*1024**3 and admission['swapRangeBytes']==swap==0,'memory/swap result changed')
    require(process_samples==60 and admission['noResearchProcesses'] is False and admission['windowReset'] is False,'process-name refusal hidden')
    require(all({(p['pid'],p['name']) for p in r['researchProcesses']}=={(669,'Ollama'),(701,'ollama')} for r in a),'process population changed')
    require(admission['status']=='NOT_ADMITTED_NO_MEASUREMENT' and admission['executionPlanSha256']==SHA(source(PLAN_PATH)),'refusal/plan relabelled')
    receipt=load('qualification/receipt.json');planned=[c['input']['caseId']+'/'+arm for c in runtime['cases'] for arm in c['input']['conditions']]
    require(receipt['status']=='NOT_ADMITTED_NO_MEASUREMENT' and receipt['completedBlocks']==receipt['completedConditionRows']==0 and receipt['blocks']==[] and receipt['unattemptedCaseIds']==planned and len(planned)==20 and receipt['inFlightCaseIds']==receipt['unknownCaseIds']==[],'missing/unattempted qualification rows')
    require(not any(path.startswith('qualification/block-') for path in seen),'refused admission contains a live block')
    require(load('runtime/ollama-status-after-refusal.json')=={'models':[]},'post-window diagnostic changed')
    numbers=dict(defaultPassed=684,defaultSkipped=29,defaultTotal=713,browserSkipped=38,
                 firstDefaultFailed=44,firstDefaultRedisFailures=23,firstDefaultRootFailures=21,
                 protectedSourceFiles=331,binaryDependencyFiles=len(build['files']),runtimeControls=13,pathControls=11,
                 realOwnedDatabaseLifecycles=1,serviceSetupSeconds=setup['elapsedSeconds'],vmStarts=2,
                 settlingSeconds=settle['elapsedSeconds'],settlingSamples=len(s),admissionSeconds=admission['elapsedSeconds'],
                 admissionSamples=len(a),admissionMinimumAvailableBytes=available,admissionSwapRangeBytes=swap,
                 admissionProcessBlockedSamples=process_samples,plannedKnownConditionRows=20,unattemptedKnownConditionRows=len(planned),
                 completedFiniteQualificationRows=0,freshHeldoutCases=0,newModelRequests=0)
    readiness=load('readiness.json');require(readiness['numbers']==numbers and all(type(readiness['numbers'][k]) is type(v) for k,v in numbers.items()),'independent numerical reconstruction')
    require(readiness['status']=='RUNTIME_AND_ENGINEERING_CONTROLS_READY_ADMISSION_REFUSED' and readiness['sourceCommit']==SOURCE and readiness['buildFreezeCommit']==BUILD and readiness['planCommit']==PLAN,'readiness identity/scope')
    for key in ['fullFiniteDriverQualified','heldoutComparisonComplete','newCaseConstructionAllowed','formalHardwareQualification','independentHumanReview']:
        require(readiness[key] is False,'unearned acceptance: '+key)
    require(readiness['caseGenerationSeed'] is None and readiness['table7_3']=='NOT_RUN','invented construction/heldout result')
    require(readiness['qualificationCorruptionControls'].startswith('NOT_RUN_'),'unrun full-block controls claimed passed')
    require(len(trees)==proof['trees'] and {path for path in seen if path.startswith('git-proof/') and path.endswith('.tree')}=={'git-proof/'+key+'.tree' for key in trees},'unverified or missing Git tree objects')
    return dict(status='RELOCATED_RUNTIME_ARCHIVE_VERIFIED_ADMISSION_REFUSED',sourceFiles=sum(r['commit']==SOURCE for r in proof['files']),gitTrees=len(trees),files=len(seen),numbers=numbers,fullFiniteDriverQualified=False,newCaseConstructionAllowed=False,
                interpretation='Engineering and conditional admission reconstruction only. Raw binary bytes are retained privately; the public packet binds their pre-window hashes and generated metadata, not an independent SDK rebuild or scientific acceptance.')

def controls(root):
    original=(root/'manifest.json').read_bytes();listing=json.loads(original);results=[]
    cases=['invented-full-qualification','invented-fresh-seed','changed-default-outcome','changed-protected-source',
           'hidden-process-condition','refusal-labelled-admitted','hidden-unattempted-row','false-available-memory',
           'missing-admission-sample','unknown-owned-cleanup','false-write-boundary','rebound-binary-hashes','claimed-unrun-full-block-controls']
    for name in cases:
        overrides={};obj=None
        if name in ['invented-full-qualification','invented-fresh-seed','claimed-unrun-full-block-controls']:
            rel='readiness.json';obj=json.loads((root/rel).read_text())
            if name=='invented-full-qualification':obj['fullFiniteDriverQualified']=True
            elif name=='invented-fresh-seed':obj['caseGenerationSeed']='f'*64
            else:obj['qualificationCorruptionControls']='PASS_19'
        elif name=='changed-default-outcome':
            rel=next(r['path'] for r in listing['files'] if r['path'].startswith('engineering/corrected-default-regression/') and r['path'].endswith('.trx') and b'Aijade.Tests.' in (root/r['path']).read_bytes())
            overrides[rel]=(root/rel).read_bytes().replace(b'outcome="Passed"',b'outcome="Failed"',1)
        elif name=='changed-protected-source':
            proof=json.loads((root/'git-membership.json').read_text());rel=next(r['archivePath'] for r in proof['files'] if r['commit']==SOURCE and r['path']=='src/Aijade.Server/AijadeServer.cs');overrides[rel]=(root/rel).read_bytes()+b'\n// altered\n'
        elif name in ['hidden-process-condition','refusal-labelled-admitted','false-available-memory']:
            rel='qualification/admission/receipt.json';obj=json.loads((root/rel).read_text())
            if name=='hidden-process-condition':obj['noResearchProcesses']=True
            elif name=='refusal-labelled-admitted':obj['status']='ADMITTED'
            else:obj['minimumAvailableBytes']+=1
        elif name=='hidden-unattempted-row':rel='qualification/receipt.json';obj=json.loads((root/rel).read_text());obj['unattemptedCaseIds'].pop()
        elif name=='missing-admission-sample':rel='qualification/admission/telemetry.jsonl';overrides[rel]=b'\n'.join((root/rel).read_bytes().splitlines()[1:])+b'\n'
        elif name=='unknown-owned-cleanup':rel='runtime/real-owned-database-control.json';obj=json.loads((root/rel).read_text());obj['cleanup'][0]['remaining']=None
        elif name=='false-write-boundary':rel='runtime/sandbox-write-boundary-device.json';obj=json.loads((root/rel).read_text());obj['stdout']='{"insideWrite":true,"outsideErrno":null,"outsideDenied":false}\n'
        else:rel='frozen-build.json';obj=json.loads((root/rel).read_text());obj['files']['Aijade.Tests.dll']='a'*64
        if obj is not None:overrides[rel]=(json.dumps(obj,indent=2)+'\n').encode()
        require(overrides[rel]!=(root/rel).read_bytes(),'no-op corruption')
        changed=json.loads(original)
        for row in changed['files']:
            if row['path'] in overrides:row.update(bytes=len(overrides[row['path']]),sha256=SHA(overrides[row['path']]))
        overrides['manifest.json']=(json.dumps(changed,indent=2)+'\n').encode()
        try:verify(root,overrides)
        except (ValueError,KeyError,TypeError,IndexError) as error:results.append(dict(control=name,rejected=True,reason=type(error).__name__+': '+str(error)))
        else:raise AssertionError('coherently rebound corruption accepted: '+name)
    require((root/'manifest.json').read_bytes()==original,'primary manifest changed')
    return dict(status='PASS',rejectedCorruptions=len(results),primaryUnchanged=True,controls=results,
                scope='Refused-admission archive controls only. The nineteen planned complete live-block controls were not executed.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);p.add_argument('--controls',action='store_true');a=p.parse_args()
    result=verify(a.root)
    if a.controls:result['corruptionControls']=controls(a.root)
    print(json.dumps(result,indent=2))
