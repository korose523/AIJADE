"""Local post-terminal packet primitives; no work is performed on import."""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import json
import os
import stat
import unicodedata

BASE=Path('/Volumes/Untitled/AIJADE')
TEXT_SUFFIXES={'.json','.jsonl','.log','.py','.c','.cs','.md','.txt','.trx','.xml','.yml','.yaml','.sb','.csv','.tsv','.toml','.sh',
               '.sln','.slnx','.props','.targets','.csproj'}
FORBIDDEN_PARTS={'auth','credentials','private-renderer-assets','private-assets','weights','models','bin','obj','node_modules'}


def need(value,message):
    if not value:
        raise ValueError(message)


def typed_equal(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return set(a)==set(b) and all(typed_equal(a[k],b[k]) for k in a)
    if type(a) is list:return len(a)==len(b) and all(typed_equal(x,y) for x,y in zip(a,b))
    return a==b


def unique(pairs):
    result={}
    for key,value in pairs:
        need(key not in result,'duplicate JSON key');result[key]=value
    return result


def decode(raw):
    return json.loads(raw,object_pairs_hook=unique,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def read(path):return decode(Path(path).read_bytes())
def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()


def path(value):
    p=Path(value)
    need(p.is_absolute() and p==p.resolve() and p.is_relative_to(BASE),'canonical AIJADE path required')
    need(not any(q.is_symlink() for q in (p,*p.parents)),'symlink in project path')
    return p


def relative(value):
    need(type(value) is str and value and '\\' not in value and not any(ord(c)<32 for c in value),'relative path type')
    p=PurePosixPath(value)
    need(not p.is_absolute() and '..' not in p.parts and '.' not in p.parts and p.as_posix()==value,'unsafe relative path')
    return value


def text_source(p):
    p=path(p)
    need(p.is_file() and stat.S_ISREG(p.stat().st_mode) and p.stat().st_nlink==1,'original source not regular/single-link')
    need(p.suffix.lower() in TEXT_SUFFIXES and not any(part.casefold() in FORBIDDEN_PARTS for part in p.parts),
         'SDK/binary/private/auth source prohibited')
    return p


def file_sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def new(p,raw):
    p=path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as stream:stream.write(raw)


def inventory(root,*,absent_allowed=False):
    root=path(root)
    if not root.exists():
        need(absent_allowed,'original run directory absent')
        return dict(exists=False,files={},directories=[],emptyFiles=[])
    need(root.is_dir(),'run root is not a directory')
    files={};directories=[];folded=set()
    for directory,dirs,names in os.walk(root,followlinks=False):
        dp=path(directory)
        need(all(not (dp/n).is_symlink() for n in dirs),'run directory symlink')
        directories.append(dict(path='' if dp==root else dp.relative_to(root).as_posix(),empty=not dirs and not names))
        for name in names:
            p=text_source(dp/name);rel=relative(p.relative_to(root).as_posix())
            key=unicodedata.normalize('NFC',rel).casefold();need(key not in folded,'case/normalization collision');folded.add(key)
            files[rel]=dict(sha256=file_sha(p),bytes=p.stat().st_size)
    return dict(exists=True,files=dict(sorted(files.items())),directories=sorted(directories,key=lambda r:r['path']),
                emptyFiles=sorted(name for name,row in files.items() if row['bytes']==0))


def parent_wait_known(terminal):
    need(terminal.get('schema')=='aijade.ch7.nested-load-parent-terminal.v1','actual parent terminal schema')
    waits=terminal.get('actualParentWaits')
    need(type(waits) is list and waits and terminal.get('actualParentWaitSource')=='Popen.wait'
         and type(terminal.get('controllerExitCode')) is int,'actual parent terminal wait unknown')
    terminal_waits=[r for r in waits if type(r.get('exitCode')) is int and r.get('timedOut') is False]
    need(terminal_waits and all(r.get('source')=='Popen.wait' for r in terminal_waits)
         and terminal_waits[-1]['exitCode']==terminal['controllerExitCode'],'actual terminal wait/exit mismatch')
    return terminal_waits[-1]


def verify_negative_semantics(body,summary,audit,root):
    """Recompute the actual E3 first-slot refusal fields from retained originals.

    This transport check is not a substitute for the separately archived actual
    independent raw/kernel cold audit. It prevents a coherent metadata-only
    promotion or number change from being accepted by hash closure alone.
    """
    false=('backendQualified','scientificAcceptance','formalHardwareQualification','independentHumanReview',
           'authorApproval','seedConstructed','heldoutComparisonComplete','currentProductInheritsResearchQualification')
    need(all(summary['scope'].get(k) is False and root['scope'].get(k) is False for k in false),
         'negative engineering archive promoted scientific scope')
    need(summary['engineeringEnvelopeAccepted'] is False and root['engineeringEnvelopeAccepted'] is False,
         'negative attempt promoted to complete engineering acceptance')
    need(audit['status']=='REFUSED_NESTED_PARTIAL_RECORDS_INVENTORIED_NOT_ENGINEERING_ACCEPTED', 'negative independent audit status differs')
    if audit.get('schema')!='aijade.ch7.nested-partial-cold-negative-audit.v1':
        return dict(status='STRUCTURAL_NEGATIVE_RECORD_ONLY_NO_KERNEL_ACCEPTANCE',scientificQualification=False)
    base='run/engineering-01/'
    rec=decode(body(base+'receipt.json'));pre=decode(body(base+'preflight-continuity.json'))
    settling=[decode(x) for x in body(base+'settling/telemetry.jsonl').splitlines()]
    admission=[decode(x) for x in body(base+'admission/telemetry.jsonl').splitlines()]
    phases=[decode(x) for x in body(base+'phase-events.jsonl').splitlines()]
    service_disk=[decode(x) for x in body(base+'preflight-service-events.jsonl').splitlines()]
    stages=[decode(x) for x in body(base+'stage-events.jsonl').splitlines()]
    terminal=decode(body('launch/engineering-01-launch.terminal.json'));parent_wait_known(terminal)
    passport=decode(body('publication/engineering-01-passport.json'))
    journal=body(base+'lifecycle-journal.jsonl');events=[];previous='0'*64
    for seq,line in enumerate(journal.splitlines(),1):
        e=decode(line);payload={k:v for k,v in e.items() if k!='sha256'}
        canonical=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
        need(type(e['seq']) is int and e['seq']==seq and e['previousSha256']==previous and sha(canonical)==e['sha256'],
             'retained original journal sequence/hash chain changed')
        need(e['sourceCommit']==summary['sourceCommit'] and e['policySha256']==passport['policySha256'], 'journal source/policy binding differs')
        events.append(e);previous=e['sha256']
    need(journal.endswith(b'\n') and sha(journal)==rec['lifecycleJournalSha256'] and len(journal)==rec['lifecycleJournalBytes'],
         'retained terminal journal body/prefix differs')
    finite={e['data']['leaseId']:e for e in events if e['event']=='FINITE_REGISTER'}
    waits={e['data']['leaseId']:e for e in events if e['event']=='WAIT'}
    need(set(finite)==set(waits) and all(waits[k]['data']['waitSource']=='Popen.wait'
        and type(waits[k]['data']['exitCode']) is int and waits[k]['data']['exitCode']==0
        and waits[k]['data']['identity']==v['data']['identity'] and waits[k]['writer']==v['data']['parentIdentity']
        for k,v in finite.items()), 'retained original finite actual wait population differs')
    need(len(settling)==1 and admission==[] and len(phases)==2 and len(service_disk)==1 and len(stages)==2,
         'actual first-slot refusal population differs')
    row=settling[0];obs=row['processObservation'];sv=rec['preflightServices'][0]
    need(row['streamValidationStatus']==obs['status']=='PASS' and obs['blockers']==[], 'original first-sample PASS was changed')
    need(pre['status']=='PREFLIGHT_REFUSED' and pre['validatedSamples']==0 and pre['runtimeHandoffAnchor'] is None
         and rec['status']=='ENGINEERING_REAL_NESTED_LOAD_REFUSED' and rec['nestedEpochMonotonic'] is None
         and rec['nestedBlocks']==rec['blockWaits']==[] and terminal['controllerExitCode']==1,
         'partial refusal or retained unknown/null fields were promoted')
    need(pre['phases']['settling']['elapsedSeconds'] is None and pre['phases']['settling']['phaseClock']['endMonotonic'] is None,
         'unfinished phase endpoint cannot be zero-filled')
    start=row['monotonicSeconds'];origin=pre['schedule']['originMonotonic'];full=sv['serviceCompletedMonotonic']-start
    need(full==sv['fullServiceSeconds']>2 and 0<=start-origin<=.5
         and row['observationCompletedMonotonic']-start<=2.5, 'original complete-service refusal trigger differs')
    original_files=decode(body('metadata/run-directory-state.json'))['files']
    data=dict(originalRunFiles=len(original_files),settlingRawSamples=len(settling),settlingRawGuardColdPass=1,
        settlingOriginalStreamValidationPass=1,settlingCompleteEngineeringServicePass=0,
        settlingControllerValidatedSamples=pre['phases']['settling']['validatedSamples'],
        settlingPlannedSlots=pre['phases']['settling']['expectedSamples'],
        settlingUnattemptedSlots=pre['phases']['settling']['expectedSamples']-len(settling),
        admissionPlannedSlots=pre['schedule']['admissionSeconds']//2,admissionRawSamples=len(admission),
        originalPhaseEventRecords=len(phases),originalPreflightServiceRecords=len(service_disk),nestedRuntimeSamples=0,
        nestedBlocksStarted=len(rec['nestedBlocks']),nestedBlocksCompleted=len(rec['nestedBlocks']),
        sourceProofGitTasks=len(rec['preflightCommands']),prefixPaddingGitTasks=len(rec['prefixPaddingCommands']),
        actualGitFiniteTasks=sum(e['data']['executableSha256']==passport['toolExecutableSha256']['git'] for e in finite.values()),
        nativeCaptures=sum(e['data']['stageId']=='observer-native-census' for e in finite.values()),
        listenerFiniteTasks=sum(e['data']['executableSha256']==passport['toolExecutableSha256']['lsof'] for e in finite.values()),
        finiteLeases=len(finite),finiteActualParentWaitZero=len(waits),journalEvents=len(events),finalJournalBytes=len(journal),
        originalSampleJournalCutoffBytes=obs['lifecycle']['journalBytes'],originalSampleJournalCutoffEvents=obs['lifecycle']['lastSequence'],
        fullServiceSeconds=full,startLatenessSeconds=start-origin,
        rawCaptureSeconds=row['observationCompletedMonotonic']-start,
        outerValidatorSeconds=row['validatorCompletedMonotonic']-row['validatorStartedMonotonic'],
        rawWriteSeconds=phases[1]['writerCompletedMonotonic']-row['writerStartedMonotonic'],
        beforeLockHeldSeconds=obs['coordinationLocks']['before']['releasedMonotonic']-obs['coordinationLocks']['before']['acquiredMonotonic'],
        afterLockHeldSeconds=obs['coordinationLocks']['after']['releasedMonotonic']-obs['coordinationLocks']['after']['acquiredMonotonic'],
        beforeLockRequestToAcquireSeconds=obs['coordinationLocks']['before']['acquiredMonotonic']-obs['coordinationLocks']['before']['requestStartedMonotonic'],
        afterLockRequestToAcquireSeconds=obs['coordinationLocks']['after']['acquiredMonotonic']-obs['coordinationLocks']['after']['requestStartedMonotonic'],
        actualPreparationSeconds=stages[1]['monotonicSeconds']-rec['preparationEpochMonotonic'],
        actualControllerExitCode=terminal['controllerExitCode'],modelRequests=rec['modelRequests'],rendererRequests=rec['rendererRequests'])
    need(typed_equal(data,audit['numbers']),'coherently changed negative summary numbers differ from retained original raw records')
    cutoff=obs['lifecycle']['journalBytes'];prefix=journal[:cutoff]
    need(prefix.endswith(b'\n') and sha(prefix)==obs['lifecycle']['journalSha256']
         and len(prefix.splitlines())==obs['lifecycle']['lastSequence'],
         'retained original sample cutoff hash/event count differs')
    return dict(status='ACTUAL_NEGATIVE_POPULATION_AND_TRIGGER_REDERIVED_NOT_QUALIFIED',numbers=len(data),
                actualKernelColdReplayRepeated=False,scientificQualification=False)


def verify_packet(packet):
    # Read-only verifier is relocatable (including a Linux CI checkout). The
    # archive creator and every local writer retain the strict BASE boundary.
    original=Path(packet).absolute()
    need(not any(p.is_symlink() for p in (original,*original.parents)), 'symlink in read-only packet path')
    packet=original.resolve();need(packet.is_dir(),'packet directory missing')
    manifest=read(packet/'packet-manifest.json')
    need(manifest.get('schema')=='aijade.ch7.real-nested-packet-manifest.v1','packet manifest schema')
    rows=manifest['files'];names=[relative(r['path']) for r in rows]
    need(len(names)==len(set(names)) and 'packet-manifest.json' not in names,'packet manifest population')
    actual={p.relative_to(packet).as_posix() for p in packet.rglob('*') if p.is_file()}
    need(actual==set(names)|{'packet-manifest.json'},'exact physical packet file population differs')
    need(not any(p.is_symlink() for p in packet.rglob('*')),'packet symlink')
    logical={}
    for row in rows:
        p=packet/row['path']
        need(type(row['sizeBytes']) is int and p.stat().st_size==row['sizeBytes'] and file_sha(p)==row['sha256'],
             'physical packet hash/size differs: '+row['path'])
        name=row.get('logicalPath',row['path'])
        relative(name);need(name not in logical,'logical path collision')
        if row.get('compressedDeterministically') is True:
            need(row['path']==name+'.gz' and name.endswith('.jsonl') and row['logicalSizeBytes']>0,'compressed mapping differs')
            with p.open('rb') as stream:header=stream.read(10)
            need(header[:3]==b'\x1f\x8b\x08' and header[3]==0 and header[4:8]==b'\0\0\0\0','gzip filename/flags/mtime not deterministic')
            h=hashlib.sha256();size=0
            with gzip.open(p,'rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):
                    size+=len(chunk);need(size<=row['logicalSizeBytes'],'gzip logical body exceeds declared bound');h.update(chunk)
            need(size==row['logicalSizeBytes'] and h.hexdigest()==row['logicalSha256'],'logical decompressed hash/size differs')
            logical[name]=dict(sha256=h.hexdigest(),bytes=size)
        else:
            need('logicalSha256' not in row or (row['logicalSha256']==row['sha256'] and row['logicalSizeBytes']==row['sizeBytes']),
                 'uncompressed logical metadata differs')
            logical[name]=dict(sha256=row['sha256'],bytes=row['sizeBytes'])
    mapping=read(packet/'metadata/source-map.json')['originalSources']
    need(len({r['logicalPacketPath'] for r in mapping})==len(mapping),'source-map duplicate')
    for row in mapping:
        need(row['logicalPacketPath'] in logical and typed_equal(logical[row['logicalPacketPath']],
            dict(sha256=row['originalSha256'],bytes=row['originalSizeBytes'])),'original/logical source mapping differs')
    summary=read(packet/'summary.json');audit=read(packet/'audit/independent-audit.json');root=read(packet/'audit/root-disposition.json')
    need(typed_equal(summary['numbers'],audit['numbers']) and typed_equal(root['numbers'],audit['numbers']),
         'complete summary numeric values/types were dropped or changed')
    source=read(packet/'metadata/frozen-source-proofs.json')
    proof=source['sources'];need(source['sourceCommit']==manifest['sourceCommit']==summary['sourceCommit'], 'source commit anchors differ')
    need(len(proof)==len(source['sourceFiles']) and {r['path'] for r in proof}==set(source['sourceFiles'])
         and {name[7:] for name in logical if name.startswith('source/')}==set(source['sourceFiles']), 'complete frozen source population differs')
    for row in proof:
        need(logical['source/'+row['path']]['sha256']==row['sha256']==source['sourceFiles'][row['path']], 'frozen source body/hash differs')
    by_logical={r.get('logicalPath',r['path']):r for r in rows}
    def body(name):
        r=by_logical[name];p=packet/r['path']
        if r.get('compressedDeterministically') is True:
            with gzip.open(p,'rb') as stream:return stream.read()
        return p.read_bytes()
    passport_raw=body('publication/engineering-01-passport.json');passport=decode(passport_raw)
    need(typed_equal(source['sourceFiles'],passport['sourceFiles'])
         and typed_equal(source['observerSources'],passport['observerSources']),
         'original passport and frozen source closure population differ')
    need(sha(passport_raw)==manifest['passportSha256']==summary['passportSha256']
         and body('run/engineering-01/engineering-passport.json')==passport_raw,
         'actual original/external passport body identity differs')
    directory=decode(body('metadata/run-directory-state.json'))
    prefix='run/engineering-01/'
    run_bodies={name[len(prefix):]:value for name,value in logical.items() if name.startswith(prefix)}
    need(typed_equal(directory['files'],run_bodies) and typed_equal(audit['inputFiles'],run_bodies),
         'complete retained original run body inventory differs from cold audit')
    need(sha(body('history/p4-refusal-summary.json'))=='7dbe9435d07f4357d8282200c3f540429b6bc7e4ed0b898166d328283d337b26',
         'immutable old P4 refusal summary differs')
    negative=(verify_negative_semantics(body,summary,audit,root)
              if manifest['outcomeKind']=='partial-refusal' else None)
    return dict(status='COMPLETE_PHYSICAL_LOGICAL_PACKET_CLOSURE_VERIFIED_NOT_QUALIFIED',
        payloadFiles=len(rows),originalFiles=len(mapping),manifestSha256=file_sha(packet/'packet-manifest.json'),
        allPhysicalAndLogicalBodiesVerified=True,negativeRecordSemantics=negative,
        backendQualified=False,independentHumanReview=False)
