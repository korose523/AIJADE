from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from collections import Counter
import hashlib, json, shutil, subprocess, xml.etree.ElementTree as ET

C=Path(__file__).resolve().parent;BASE=Path('/Volumes/Untitled/AIJADE');W=C/'worktree';P=C/'packet'
S='3dc0644da43054ad879cfeb1d2b3a57313f57ff8'
PLAN='0dd5b04e1fc77325c6f7e7aa97c21ac86c0d310c'
OLD='46efbfc88a25ee4ea9af536112f20e7d202bcff9'
PLAN_PATH='experiments/plans/2026-11-16-ch7-relocated-runtime-qualification.md'
BUILD_PATH='experiments/ch7/relocated-runtime-2026-11-16/frozen-build.json'
Q=BASE/'.runtime/posix/runs/ch7-relocation-20261116/qualification-01'
load=lambda p:json.loads(p.read_text())
sha=lambda b:hashlib.sha256(b).hexdigest()
assert not P.exists();P.mkdir()
def cp(source,relative):
    dest=P/relative;dest.parent.mkdir(parents=True,exist_ok=True);assert not dest.exists();shutil.copyfile(source,dest)
def write(relative,value):
    dest=P/relative;dest.parent.mkdir(parents=True,exist_ok=True);assert not dest.exists();dest.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

files={
 'publication':['prospective-plan-publication.json','execution-source-publication.json','binary-freeze-publication.json','execution-source-ci.json','execution-source-ci.log','single-qualification-launch.json','single-qualification-command-exit.json'],
 'runtime':['runtime-setup-first.json','runtime-setup.json','runtime-image-create.log','runtime-image-attach.log','colima-start-01.log','colima-start-02.log','colima-stop-first-path-fallback.log','colima-path-fallback-relocation.json','docker-version.log','docker-version-after-path-repair.log','postgres-version-and-extension.log','runtime-images.log','service-environment.json','filesystem-precondition.json','permission-precondition.json','real-owned-database-control.json','preflight-database-lease.jsonl','ollama-status-after-refusal.json','godot-project-writes-only.sb','godot-contained-version.json','sandbox-write-boundary.json','sandbox-write-boundary-device.json','native-cache-correction.json','renderer-preparation.json','renderer-prebuild.log','renderer-prebuild-native-cache.log'],
 'engineering':['runtime-controls-first.log','runtime-controls-with-signal.log','runtime-controls-recursive-build.log','launcher-controls.json','launcher-controls-native-root.json','prebuild-source-invariants.json','complete-default-regression.log','complete-default-env-corrected-regression.log','default-regression-failure-and-prospective-correction.json','default-regression-skips.json','build-regression-status.json','clean-current-committed-source.log','clean-default-env-corrected-source.log','build-regression-controller.log'],
 'provenance-scripts':['restore_runtime.py','repair_runtime_location.py','prepare_renderer.py','resume_renderer_prebuild.py','original-renderer-launcher.py','sandbox_write_probe.py','sandbox_write_probe_device.py','build_regression.py','prepare_default_regression_correction.py','build_regression_corrected.py','publish_binary_freeze.py','launch_single_qualification.py'],
}
for category,names in files.items():
    for name in names:cp(C/name,category+'/'+name)
cp(C/'frozen-build.json','frozen-build.json')
for source,relative in [('default-regression','engineering/failed-default-regression'),('default-env-corrected-regression','engineering/corrected-default-regression'),('qualification-inputs','qualification-inputs')]:
    for path in sorted((C/source).rglob('*')):
        if path.is_file():cp(path,relative+'/'+str(path.relative_to(C/source)))
for path in sorted(Q.rglob('*')):
    if path.is_file():cp(path,'qualification/'+str(path.relative_to(Q)))

# Raw Git commits, the necessary complete tree objects and bound source blobs.
G=P/'git-proof';G.mkdir();trees={};commits={};bindings=[]
def oid(kind,data):return hashlib.sha1(kind.encode()+b' '+str(len(data)).encode()+b'\0'+data).hexdigest()
process=subprocess.Popen(['git','cat-file','--batch'],cwd=W,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
def get(query):
    assert '\n' not in query;process.stdin.write(query.encode()+b'\n');process.stdin.flush()
    fields=process.stdout.readline().decode().strip().split();assert len(fields)==3 and fields[2].isdigit(),fields
    key,kind,n=fields;data=process.stdout.read(int(n));assert process.stdout.read(1)==b'\n' and oid(kind,data)==key
    return key,kind,data
def commit(key):
    if key in commits:return commits[key]
    actual,kind,data=get(key);assert actual==key and kind=='commit';(G/(key+'.commit')).write_bytes(data)
    root=data.splitlines()[0].decode().split()[1];commits[key]=root;return root
def tree(key):
    if key in trees:return trees[key]
    actual,kind,data=get(key);assert actual==key and kind=='tree';(G/(key+'.tree')).write_bytes(data)
    rows={};i=0
    while i<len(data):
        a=data.index(b' ',i);b=data.index(b'\0',a);name=data[a+1:b].decode();assert name not in rows
        rows[name]=(data[i:a].decode(),data[b+1:b+21].hex());i=b+21
    assert i==len(data);trees[key]=rows;return rows
def lookup(root,path):
    current=root;parts=PurePosixPath(path).parts
    for i,name in enumerate(parts):
        value=tree(current).get(name)
        if value is None:return None
        mode,key=value
        if i==len(parts)-1:return mode,key
        assert mode=='40000';current=key
def bind(key,path,prefix):
    root=commit(key);mode,expected=lookup(root,path);actual,kind,body=get(expected)
    assert actual==expected and kind=='blob' and mode in ['100644','100755']
    dest=P/prefix/path;dest.parent.mkdir(parents=True,exist_ok=True);assert not dest.exists();dest.write_bytes(body)
    bindings.append(dict(commit=key,path=path,archivePath=str(dest.relative_to(P)),mode=mode,gitBlobSha1=actual,sha256=sha(body),bytes=len(body)))
def differences(a,b,prefix=''):
    if a==b:return []
    left,right=tree(a),tree(b);result=[]
    for name in sorted(set(left)|set(right)):
        x,y=left.get(name),right.get(name);path=prefix+name
        if x==y:continue
        if x and y and x[0]==y[0]=='40000':result+=differences(x[1],y[1],path+'/')
        elif x is None and y[0]=='40000':result+=leaves(y[1],path+'/')
        elif y is None and x[0]=='40000':result+=leaves(x[1],path+'/')
        else:result.append(path)
    return result
def leaves(key,prefix):
    out=[]
    for name,(mode,value) in sorted(tree(key).items()):
        if mode=='40000':out+=leaves(value,prefix+name+'/')
        else:out.append(prefix+name)
    return out
E=load(C/'binary-freeze-publication.json')['buildFreezeCommit']
try:
    for key in [OLD,PLAN,'caf82e988dff283b51c2f2acd89a26998fa1cfcd',S,E]:commit(key)
    assert differences(commit(OLD),commit(PLAN))==[PLAN_PATH]
    assert differences(commit(S),commit(E))==[BUILD_PATH]
    previous=load(C.parent/'ch7-readiness-20261116/packet/source-membership.json')
    paths={r['path'] for r in previous['files']}
    paths.update([PLAN_PATH,'experiments/ch7/finite_runtime.py','experiments/ch7/godot_local.py',
                  'tests/shell/test_finite_runtime.py','tests/shell/verify_workspace_env.py',
                  'tools/with-workspace-env.sh','.github/workflows/ci.yml',
                  'experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'])
    for path in sorted(paths):bind(S,path,'frozen-source')
    bind(PLAN,PLAN_PATH,'plan-source');bind(E,BUILD_PATH,'build-freeze-source')
    protected_path='experiments/ch7/manifest-preparation-2026-11-12/source-freeze.json'
    assert lookup(commit(OLD),protected_path)==lookup(commit(S),protected_path)
    bank_path='experiments/ch7/finite-heldout/candidate-bank.json'
    for path in ['experiments/ch7/finite_inputs.py','experiments/ch7/finite_score.py','experiments/ch7/finite_validate.py',bank_path]:
        assert lookup(commit(OLD),path)==lookup(commit(S),path)
    proof=dict(sourceCommit=S,baseCommit=OLD,planCommit=PLAN,buildFreezeCommit=E,
               trees=len(trees),commits=commits,files=bindings,planOnlyChangedFiles=[PLAN_PATH],buildFreezeOnlyChangedFiles=[BUILD_PATH],
               protectedSourceFiles=331,interpretation='Git object membership and byte identity, not independent authorship, binary reproduction or scientific acceptance.')
    write('git-membership.json',proof)
finally:
    process.stdin.close();process.stdout.close();assert process.wait()==0

ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
def populations(directory):
    out={}
    for path in sorted((C/directory).glob('*.trx')):
        rows=ET.parse(path).findall('.//t:UnitTestResult',ns)
        name='browser' if all(r.attrib['testName'].startswith('Aijade.E2E.') for r in rows) else 'unit'
        assert name not in out;out[name]=dict(Counter(r.attrib['outcome'] for r in rows))
    return out
good=populations('default-env-corrected-regression');bad=populations('default-regression')
assert good=={'browser':{'NotExecuted':38},'unit':{'Passed':684,'NotExecuted':29}},good
assert bad['unit']=={'Passed':640,'NotExecuted':29,'Failed':44},bad
settling=load(Q/'settling/receipt.json');admission=load(Q/'admission/receipt.json');receipt=load(Q/'receipt.json')
assert receipt['status']=='NOT_ADMITTED_NO_MEASUREMENT' and receipt['completedConditionRows']==0
status=load(C/'ollama-status-after-refusal.json');assert status=={'models':[]}
numbers=dict(defaultPassed=684,defaultSkipped=29,defaultTotal=713,browserSkipped=38,
             firstDefaultFailed=44,firstDefaultRedisFailures=23,firstDefaultRootFailures=21,
             protectedSourceFiles=331,binaryDependencyFiles=len(load(C/'frozen-build.json')['files']),
             runtimeControls=13,pathControls=11,realOwnedDatabaseLifecycles=1,
             serviceSetupSeconds=load(C/'runtime-setup.json')['elapsedSeconds'],vmStarts=2,
             settlingSeconds=settling['elapsedSeconds'],settlingSamples=settling['samples'],
             admissionSeconds=admission['elapsedSeconds'],admissionSamples=admission['samples'],
             admissionMinimumAvailableBytes=admission['minimumAvailableBytes'],admissionSwapRangeBytes=admission['swapRangeBytes'],
             admissionProcessBlockedSamples=60,plannedKnownConditionRows=20,unattemptedKnownConditionRows=20,
             completedFiniteQualificationRows=0,freshHeldoutCases=0,newModelRequests=0)
write('readiness.json',dict(schema='aijade.ch7.relocated-runtime-readiness.v1',
      status='RUNTIME_AND_ENGINEERING_CONTROLS_READY_ADMISSION_REFUSED',recordedAt=datetime.now(timezone.utc).isoformat(),
      sourceCommit=S,planCommit=PLAN,buildFreezeCommit=E,numbers=numbers,
      fullFiniteDriverQualified=False,heldoutComparisonComplete=False,newCaseConstructionAllowed=False,
      caseGenerationSeed=None,table7_3='NOT_RUN',formalHardwareQualification=False,independentHumanReview=False,
      planPublishedAloneBeforeImplementation=True,binaryIdentitiesPublishedBeforeSettling=True,
      admissionReason='Frozen process-name condition failed; memory and swap conditions passed.',
      ollamaAfterRefusal='Read-only /api/ps returned an empty model list after the window; this is not evidence about activity throughout it. No retroactive admission waiver.',
      earlierRefusalsAndOrderDeviationPreserved=True,
      qualificationCorruptionControls='NOT_RUN_NO_COMPLETE_LIVE_BLOCK; no claim that the nineteen planned raw-block corruptions passed.',
      aiAssistance='All interpretation and development are AI-assisted; no independent human review or author-final approval inferred.'))
print(json.dumps(dict(status='UNSEALED_PACKET_PREPARED',sourceFiles=len([r for r in bindings if r['commit']==S]),gitTrees=len(trees),numbers=numbers)))
