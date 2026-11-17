"""Create exactly one private, immutable-source P4 refusal packet; no publish.

Original text bytes are copied, nonempty JSONL is losslessly gzip(mtime=0), empty
files remain empty. Private assets/weights and executable binary bodies are never
selected. Summary is a reviewable factual draft, not scientific acceptance.
"""
from datetime import datetime,timezone
import gzip,hashlib,json,os
from pathlib import Path
import shutil,stat,subprocess

BASE=Path('/Volumes/Untitled/AIJADE')
C=BASE/'.research/runs/ch7-prefix-qualification-20261117'
W=BASE/'.runtime/posix/research/ch7-prefix-20261117/worktree'
RUN=BASE/'.runtime/posix/runs/ch7-prefix-v4-20261117/qualification-01'
PACKET=C/'refusal-packet'
Q='147564c9db812c1a9e5ae07992d9aa282399a310'
B='8acfa99d061f1c41197fac2a1c243b3b347bcfef'
P='42fc728ade94c60b0d24575b9510b69dd2048676'
PLAN='experiments/plans/2026-11-17-ch7-mac-prefix-v4-qualification.md'
PLAN_SHA='7aa91508eee3e728cadd8d25f8cdd122deb9a35d06a09901e8143d1e028d9d36'
POLICY_SHA='caf8392394a09ec168df44347337ec0676f695f5d3cd9af576372678e03a925a'

def need(ok,message):
    if not ok:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
def read(path):return json.loads(path.read_bytes())
def file_sha(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()
def git(commit,path):return subprocess.check_output(['git','--no-replace-objects','-C',str(W),'show',commit+':'+path],stderr=subprocess.DEVNULL)
def strict_equal(a,b):return encode(a)==encode(b)
def write_new(path,raw):
    need(path.is_relative_to(BASE),'write outside BASE');path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write(raw)

def main():
    need(not PACKET.exists() and not(C/'refusal-packet-preparation.json').exists(),'never overwrite an archive')
    audit_path=C/'analysis/independent-p4-terminal-audit-01.json';audit=read(audit_path)
    need(audit['scope']['terminalRecordIntegrityAccepted'] is True and audit['numbers']['idleColdPassSamples']==360
         and audit['numbers']['finiteActualParentWaitZero']==1476,'complete actual independent audit required')
    need(audit['implementationCommit']==Q and audit['buildFreezeCommit']==B and audit['planCommit']==P,'actual Q2/B4/P4 audit binding')
    receipt=read(RUN/'receipt.json');settle=read(RUN/'settling/receipt.json');admit=read(RUN/'admission/receipt.json')
    terminal=read(C/'qualification-single-launch.terminal.json')
    review_path=C/'papers/p4-raw-receipt-review.json';review=read(review_path)
    aliases={
        'plannedPairs':receipt['plannedPairs'],'plannedConditionRows':receipt['plannedConditionRows'],
        'settlingSamples':settle['samples'],'settlingValidatedSamples':settle['validatedSamples'],'settlingSeconds':settle['elapsedSeconds'],
        'admissionSamples':admit['samples'],'admissionValidatedSamples':admit['validatedSamples'],'admissionSeconds':admit['elapsedSeconds'],
        'preflightSamples':settle['samples']+admit['samples'],'preflightValidatedSamples':settle['validatedSamples']+admit['validatedSamples'],
        'runtimeSamples':audit['numbers']['runtimeRawObservationRecords'],'completedBlocks':receipt['completedBlocks'],
        'completedConditionRows':receipt['completedConditionRows'],'unattemptedConditionRows':len(receipt['unattemptedCaseIds']),
        'unknownConditionRows':len(receipt['unknownCaseIds']),'inFlightConditionRows':len(receipt['inFlightCaseIds']),
        'modelRequests':receipt['modelRequests'],'parentControllerExitCode':terminal['controllerExitCode']}
    need(strict_equal(aliases,review['numbers']),'paper aliases differ from actual raw receipts; do not force-map')
    numbers=dict(audit['numbers'])
    for key,value in aliases.items():
        need(key not in numbers or strict_equal(numbers[key],value),'alias clashes with independently audited field')
        numbers[key]=value
    scope={**audit['scope'],'backendQualified':False,'runtimeHandoffAccepted':False,'qualificationComplete':False,
           'knownQualificationCasesExecuted':False,'parentIntervention':False,'table7_3':'NOT_RUN'}
    summary={'schema':'aijade.ch7.prefix-qualification-summary.v1',
        'status':'REFUSED_RUNTIME_HANDOFF_LOCK_TIMEOUT_NO_BLOCK_SPAWN','sourceCommit':Q,'buildFreezeCommit':B,'planCommit':P,
        'planSha256':PLAN_SHA,'processPolicySha256':POLICY_SHA,'numbers':numbers,'scope':scope,
        'independentAuditSha256':file_sha(audit_path),'rawReceiptAliasReviewSha256':file_sha(review_path),
        'numberProvenance':{'independentAuditKeys':sorted(audit['numbers']),'rawReceiptAliases':sorted(aliases),
            'overlapRequiresExactValueAndScalarType':True,'aliasSource':'Actual original receipts, crosschecked against the manuscript raw-receipt draft; no draft disagreement forced.'},
        'caseGenerationSeed':None,'formalInputPublicationCommit':None,
        'interpretation':'Both fixed idle phases passed their raw clocks and process evidence. The first runtime handoff refused the block launch before Popen; known finite WAIT0 and recorded remaining-identity0 do not erase this adverse launch evidence. No current PID disappearance is used.',
        'reviewStatus':'ROOT_REVIEW_REQUIRED_BEFORE_PUBLICATION','independentHumanReview':False,'authorApproval':False}
    sources=[];names=set()
    def select(path,relative,kind):
        path=Path(path)
        need(path.is_absolute() and path.resolve()==path and path.is_relative_to(BASE) and path.is_file() and not path.is_symlink(),'unsafe/missing source '+str(path))
        need(relative not in names and not relative.startswith('/') and all(p not in ('','.','..') for p in relative.split('/')),'unsafe/duplicate packet destination')
        need(path.suffix in {'.json','.jsonl','.log','.py','.c','.md','.txt','.sb','.trx','.yml'},'binary/private asset source prohibited')
        need(not any(p.casefold() in ('auth','credentials','private-renderer-assets') for p in path.parts),'private source prohibited')
        names.add(relative);sources.append((path,relative,kind))
    run_files=sorted(p for p in RUN.rglob('*') if p.is_file())
    need(len(run_files)==13,'actual original RUN file population changed')
    for path in run_files:select(path,'run/qualification-01/'+path.relative_to(RUN).as_posix(),'ACTUAL_ORIGINAL_RUN')
    adjacent=[]
    for path in sorted(RUN.parent.glob(RUN.name+'*')):
        if path==RUN:continue
        need(path.is_file() and not path.is_symlink(),'unexpected adjacent runtime directory/special body')
        select(path,'adjacent/'+path.name,'ACTUAL_ADJACENT_RUNTIME_ORIGINAL');adjacent.append(path)
    mandatory={
        'qualification-single-launch.json':'launch/qualification-single-launch.json',
        'qualification-single-launch.terminal.json':'launch/qualification-single-launch.terminal.json',
        'qualification-single-launch.controller.log':'launch/qualification-single-launch.controller.log',
        'qualification-fixed-launch.json':'publication/qualification-fixed-launch.json',
        'qualification-prelaunch.json':'publication/qualification-prelaunch.json',
        'qualification-prelaunch-integrity.json':'publication/qualification-prelaunch-integrity.json',
        'launch-readiness.json':'publication/launch-readiness.json',
        'implementation-publication.json':'publication/source-publication.json',
        'binary-freeze-publication.json':'publication/build-publication.json',
        'prelaunch-metadata-publication.json':'publication/prelaunch-publication.json',
        'build-metadata-publication-attempt.json':'publication/build-publication-attempt.json',
        'prelaunch-metadata-publication-attempt.json':'publication/prelaunch-publication-attempt.json',
        'frozen-build.json':'publication/frozen-build.json',
        'build-prerequisites.json':'publication/build-prerequisites.json',
        'prepared-renderer-verification.json':'publication/prepared-renderer-full-tree.json',
        'policy-static-validation.json':'engineering/policy-static-validation.json',
        'all-python-controls-source-bound.json':'engineering/all-python-controls-source-bound.json',
        'all-python-controls-source-bound.log':'engineering/all-python-controls-source-bound.log',
        'build-regression-status.json':'engineering/build-regression-status.json',
        'default-regression.log':'engineering/default-regression.log',
        'candidate-bank-control.json':'engineering/candidate-bank-control.json',
        'source-ci-current.json':'engineering/source-ci.json',
        'godot-project-writes-only.sb':'publication/godot-project-writes-only.sb',
        'source-ci-refused-358d114.json':'engineering/unused-q1/source-ci.json',
        'source-ci-refused-358d114.log':'engineering/unused-q1/source-ci.log',
        'unused-358d114-retention.json':'engineering/unused-q1/binary-retention-metadata-only.json'}
    for source,target in mandatory.items():select(C/source,target,'ORIGINAL_PRE_RUN_PUBLICATION_OR_ENGINEERING')
    need(read(C/'source-ci-current.json')['headSha']==Q and read(C/'source-ci-current.json')['conclusion']=='success','actual Q2 successful CI identity')
    need(read(C/'all-python-controls-source-bound.json')['commit']==Q and read(C/'build-regression-status.json')['commit']==Q,'actual Q2 engineering receipts')
    need((C/'frozen-build.json').read_bytes()==git(B,'experiments/ch7/mac-prefix-v4-2026-11-17/frozen-build.json'),'public B4 exact metadata')
    select(C/'native/native-build.json','publication/native-build.json','ORIGINAL_NATIVE_BUILD_METADATA_NO_BINARY')
    for path in sorted((C/'default-regression').glob('*.trx')):select(path,'engineering/default-regression/'+path.name,'ACTUAL_Q2_DEFAULT_TEST_TRX')
    need(len(list((C/'default-regression').glob('*.trx')))==2,'actual two default TRX population')
    for path in sorted((C/'qualification-inputs').iterdir()):select(path,'inputs/'+path.name,'UNCHANGED_KNOWN_ONLY_PREPARED_INPUT')
    need({p.name for p in (C/'qualification-inputs').iterdir()}=={'selection.json','runtime-manifest.json','scoring-manifest.json'},'exact known-only input population')
    audit_names=('independent_p4_terminal_audit.py','run-independent-p4-audit.py','independent-p4-terminal-audit-01.json',
        'independent-p4-terminal-audit-01.log','independent-p4-terminal-audit-01.receipt.json','independent-p4-cold-checkpoint-01.json')
    for name in audit_names:select(C/'analysis'/name,'audit/'+name,'POSTHOC_INDEPENDENT_AUDIT_OR_ACTUAL_SOURCE')
    select(review_path,'audit/p4-raw-receipt-review-preaudit-draft.json','PREADUIT_MANUSCRIPT_ALIAS_DRAFT_CROSSCHECKED_NOT_HUMAN_APPROVAL')
    for path in sorted((C/'analysis').glob('independent-p4-terminal-audit-01.failure.json')):
        select(path,'audit/'+path.name,'PRESERVED_POSTHOC_AUDIT_TOOL_FAILURE')
    for path in sorted((C/'analysis').glob('archive-preparation-refused-01*')):
        select(path,'audit/'+path.name,'PRESERVED_LOCAL_ARCHIVE_TOOL_PRESELECTION_REFUSAL_NOT_EXPERIMENT')
    select(Path(__file__).resolve(),'audit/archive_p4_refusal.py','ARCHIVE_CREATOR_SOURCE_NOT_MEASUREMENT_CODE')
    select(W/PLAN,'publication/plan.md','EXACT_ORIGINAL_PUBLIC_P4_PLAN')
    plan_pub=BASE/'.research/runs/ch7-prefix-20261117/p4-plan-publication.json'
    select(plan_pub,'publication/plan-publication.json','ORIGINAL_PLAN_PUBLICATION_RECEIPT')
    source_proofs=[]
    for name,expected in audit['sourceHashes'].items():
        path=W/name;raw=path.read_bytes();need(sha(raw)==expected and raw==git(Q,name),'exact Q2 source changed')
        select(path,'source/'+name,'EXACT_FROZEN_Q2_SOURCE_NOT_CURRENT_SDK');source_proofs.append({'path':name,'commit':Q,'sha256':expected,'gitBlob':hashlib.sha1(('blob %d\0'%len(raw)).encode()+raw).hexdigest()})
    PACKET.mkdir()
    mapping=[]
    for index,(path,name,kind) in enumerate(sources,1):
        before=path.stat();original_sha=file_sha(path);logical_size=before.st_size
        compressed=path.suffix=='.jsonl' and logical_size>0;target_name=name+'.gz' if compressed else name;target=PACKET/target_name
        target.parent.mkdir(parents=True,exist_ok=True)
        if compressed:
            with path.open('rb') as stream,target.open('xb') as output:
                with gzip.GzipFile(filename='',fileobj=output,mode='wb',compresslevel=6,mtime=0) as zipper:
                    shutil.copyfileobj(stream,zipper,1024*1024)
        else:
            with path.open('rb') as stream,target.open('xb') as output:shutil.copyfileobj(stream,output,1024*1024)
        digest=hashlib.sha256();read_size=0
        opener=gzip.open if compressed else open
        with opener(target,'rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block);read_size+=len(block)
        after=path.stat()
        need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
             and read_size==logical_size and digest.hexdigest()==original_sha,'original/roundtrip changed '+str(path))
        mapping.append({'originalPath':str(path),'packetPath':target_name,'logicalPacketPath':name,'kind':kind,
            'originalSha256':original_sha,'originalSizeBytes':logical_size,'physicalSha256':file_sha(target),'physicalSizeBytes':target.stat().st_size,
            'compressedDeterministically':compressed,'originalBytesPreserved':True})
        if index%15==0:print(json.dumps({'archived':index,'expectedSources':len(sources)}),flush=True)
    write_new(PACKET/'summary.json',encode(summary))
    dirs=[{'path':p.relative_to(RUN).as_posix() if p!=RUN else '', 'empty':not any(p.iterdir())} for p in [RUN,*sorted(p for p in RUN.rglob('*') if p.is_dir())]]
    state={'schema':'aijade.ch7.original-run-directory-state.v1','originalRoot':str(RUN),'files':{p.relative_to(RUN).as_posix():{'sha256':file_sha(p),'sizeBytes':p.stat().st_size} for p in run_files},
        'directories':dirs,'emptyFiles':[p.relative_to(RUN).as_posix() for p in run_files if p.stat().st_size==0],
        'blockDirectories':[p.name for p in RUN.glob('block-*') if p.is_dir()],'adjacentOriginals':[str(p) for p in adjacent]}
    write_new(PACKET/'metadata/run-directory-state.json',encode(state))
    write_new(PACKET/'metadata/source-map.json',encode({'schema':'aijade.ch7.refusal-source-map.v1','originalSources':mapping,
        'mappingPolicy':'Exact original relative text bytes; nonempty JSONL losslessly gzip with mtime0, original paths retained; generated metadata separately identified.'}))
    write_new(PACKET/'metadata/frozen-source-proofs.json',encode({'schema':'aijade.ch7.frozen-source-proofs.v1','sourceCommit':Q,'sources':source_proofs,'privateBinaryBodiesIncluded':False}))
    write_new(PACKET/'metadata/archive-scope.json',encode({'schema':'aijade.ch7.p4-refusal-archive-scope.v1',
        'actualMeasurementFilesComplete':True,'independentAuditFull360ColdReplay':True,'phaseAcceptedIsNotKnownQualification':True,
        'externalSdkBinaryPhysicalRecheck':'NOT_RECHECKED_RECORDS_ONLY','privatePmxWeightsAndFullBinariesIncluded':False,
        'newWindowOrCasesOrSeedCreated':False,'liveObserverModelRendererOrNetworkInvokedByArchiver':False,
        'summaryRequiresRootReviewBeforePublication':True,'unchangedOriginalsRequired':True}))
    write_new(PACKET/'README.md',('P4 original terminal refusal record. Both idle phases passed; runtime block launch refused before Popen.\n'
        'The original360 raw observations were independently cold-replayed; whole-runtime qualification remains refused.\n'
        'Nonempty JSONL uses deterministic gzip mtime0; empty files are original empty files.\n'
        'No private assets, model weights or full binary bodies are included. Current SDK bytes are not rechecked here.\n'
        'Summary is a factual draft for root review before publication. No human/author/hardware/heldout approval is implied.\n').encode())
    rows_out=[]
    for path in sorted(PACKET.rglob('*')):
        need(not path.is_symlink(),'packet symlink')
        if not path.is_file():continue
        name=path.relative_to(PACKET).as_posix();row={'path':name,'sha256':file_sha(path),'sizeBytes':path.stat().st_size}
        if name.endswith('.jsonl.gz'):
            digest=hashlib.sha256();size=0
            with gzip.open(path,'rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block);size+=len(block)
            row.update(logicalSha256=digest.hexdigest(),logicalSizeBytes=size)
        rows_out.append(row)
    manifest={'schema':'aijade.ch7.prefix-qualification-refusal-packet-manifest.v1','sourceCommit':Q,'buildFreezeCommit':B,
        'planCommit':P,'planSha256':PLAN_SHA,'processPolicySha256':POLICY_SHA,'independentAuditSha256':file_sha(audit_path),
        'files':rows_out}
    write_new(PACKET/'packet-manifest.json',encode(manifest))
    for row in mapping:need(file_sha(Path(row['originalPath']))==row['originalSha256'],'original source changed after archive')
    result={'schema':'aijade.ch7.p4-refusal-packet-preparation.v1','status':'FULL_ORIGINAL_BYTES_ARCHIVED_PENDING_ROOT_SUMMARY_REVIEW_NO_PUBLICATION',
        'packetRoot':str(PACKET),'manifestSha256':file_sha(PACKET/'packet-manifest.json'),'payloadFiles':len(rows_out),
        'sourceOriginalFiles':len(sources),'originalRunFiles':len(run_files),'adjacentOriginalFiles':len(adjacent),
        'summarySha256':file_sha(PACKET/'summary.json'),'independentAuditSha256':file_sha(audit_path),
        'allPhysicalAndLogicalBodiesVerified':True,'allOriginalSourceBytesUnchangedAfterFullReadback':True,
        'binaryBodiesOrPrivateAssetsIncluded':False,'networkRequests':0,'gitCommits':0,'svnRequests':0,
        'sourceCommit':Q,'buildFreezeCommit':B,'planCommit':P,'at':datetime.now(timezone.utc).isoformat()}
    write_new(C/'refusal-packet-preparation.json',encode(result));print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
