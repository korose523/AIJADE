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
               '.sln','.slnx','.props','.targets','.csproj','.diff'}
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
    retained_jsonl_container=p.name.endswith('.jsonl.gz')
    need((p.suffix.lower() in TEXT_SUFFIXES or retained_jsonl_container) and not any(part.casefold() in FORBIDDEN_PARTS for part in p.parts),
         'SDK/binary/private/auth source prohibited')
    if retained_jsonl_container:
        # Existing, source-bound synthetic development input only; preserve its
        # exact compressed original bytes, never recompress or treat as SDK data.
        with p.open('rb') as stream:header=stream.read(10)
        need(header[:3]==b'\x1f\x8b\x08' and header[3]==0 and header[4:8]==b'\0\0\0\0',
             'retained JSONL container is not deterministic gzip')
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
    """E4 transport/structural closure only, never E3 first-sample semantics."""
    false=('backendQualified','scientificAcceptance','formalHardwareQualification','independentHumanReview',
           'authorApproval','seedConstructed','heldoutComparisonComplete','currentProductInheritsResearchQualification')
    need(all(summary['scope'].get(k) is False and root['scope'].get(k) is False for k in false),
         'negative engineering archive promoted scientific scope')
    need(summary['engineeringEnvelopeAccepted'] is False and root['engineeringEnvelopeAccepted'] is False,
         'negative attempt promoted to complete engineering acceptance')
    need(audit['schema'] in ('aijade.ch7.nested-partial-negative-record-audit.v2','aijade.ch7.e4-partial-cold-negative-audit.v1')
         and audit['status']=='REFUSED_NESTED_PARTIAL_RECORDS_INVENTORIED_NOT_ENGINEERING_ACCEPTED'
         and audit['completeEngineeringAuditAccepted'] is False,
         'E4 negative archive requires its explicit structural-only audit')
    if audit['schema']=='aijade.ch7.e4-partial-cold-negative-audit.v1':
        from e4_refusal_semantics import verify
        return verify(body,summary,audit,root)
    # The result-specific E3 cold predicate deliberately does not exist here.
    # Journal and retained-record structural counts are derived by the separately
    # archived v2 inspector, with missing/invalid journal populations left null.
    return dict(status='E4_STRUCTURAL_NEGATIVE_RECORD_ONLY_NO_KERNEL_OR_COMPLETE_ACCEPTANCE',
        actualKernelColdReplayRepeated=False,completeEngineeringAuditAccepted=False,scientificQualification=False)


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
    passport_raw=body('publication/engineering-02-passport.json');passport=decode(passport_raw)
    need(typed_equal(source['sourceFiles'],passport['sourceFiles'])
         and typed_equal(source['observerSources'],passport['observerSources']),
         'original passport and frozen source closure population differ')
    need(sha(passport_raw)==manifest['passportSha256']==summary['passportSha256']
         and body('run/engineering-02/engineering-passport.json')==passport_raw,
         'actual original/external passport body identity differs')
    need(type(passport['observerSources']) is dict and len(passport['observerSources'])==17
         and 'experiments/ch7/full_state_clone_cursor.py' in passport['observerSources']
         and passport['onlineReplaySourceSha256']==source['sourceFiles']['experiments/ch7/full_state_clone_cursor.py'],
         'E4 complete seventeen-source initializer closure differs')
    false=('backendQualified','scientificAcceptance','formalHardwareQualification','independentHumanReview',
           'authorApproval','seedConstructed','heldoutComparisonComplete','currentProductInheritsResearchQualification')
    need(all(summary['scope'].get(k) is False and root['scope'].get(k) is False for k in false),
         'engineering packet promoted scientific scope')
    need(sha(body('audit/independent-audit.json'))==manifest['independentAuditSha256']==summary['independentAuditSha256']
         ==root['independentAuditSha256']
         and sha(body('audit/root-disposition.json'))==manifest['rootDispositionSha256']==summary['rootDispositionSha256'],
         'independent audit/root disposition exact body anchors differ')
    terminal=decode(body('launch/engineering-02-launch.terminal.json'));parent_wait_known(terminal)
    launch=decode(body('launch/engineering-02-launch.json'))
    stability=decode(body('audit/writer-stability.json'))
    need(stability['writerStabilityAccepted'] is True and stability['allOriginalWritersTerminatedOrClosed'] is True
         and stability['unresolvedWriters']==[] and stability['sourceCommit']==manifest['sourceCommit']
         and stability['parentTerminalSha256']==sha(body('launch/engineering-02-launch.terminal.json'))
         ==root['parentTerminalSha256']
         and terminal['launchRecordSha256']==sha(body('launch/engineering-02-launch.json'))
         and terminal['logSha256']==sha(body('launch/engineering-02-launch.log'))
         and terminal['passportSha256']==launch['passportSha256']==sha(passport_raw),
         'source-bound original outer wait/writer closure/launch/log binding differs')
    ci=decode(body('publication/final-source-ci.json'))
    need(ci['headSha']==manifest['sourceCommit'] and ci['status']=='completed' and ci['conclusion']=='success',
         'actual successful source CI differs')
    if manifest['outcomeKind']=='complete-engineering-accepted':
        need(audit['status']=='ENGINEERING_REAL_NESTED_RAW_AUDIT_PASS_NOT_BACKEND_QUALIFIED'
             and summary['engineeringEnvelopeAccepted'] is True and root['engineeringEnvelopeAccepted'] is True
             and terminal['controllerExitCode']==0
             and all(name in logical for name in ['run/engineering-02/initialization.json',*[f'run/engineering-02/block-{n}/initialization.json' for n in range(1,5)]]),
             'complete E4 outcome missing its actual full audit/initializer population')
    directory=decode(body('metadata/run-directory-state.json'))
    prefix='run/engineering-02/'
    run_bodies={name[len(prefix):]:value for name,value in logical.items() if name.startswith(prefix)}
    need(typed_equal(directory['files'],run_bodies) and typed_equal(audit['inputFiles'],run_bodies),
         'complete retained original run body inventory differs from cold audit')
    need(sha(body('history/p4-refusal-summary.json'))=='7dbe9435d07f4357d8282200c3f540429b6bc7e4ed0b898166d328283d337b26',
         'immutable old P4 refusal summary differs')
    need(sha(body('history/e3-refusal-summary.json'))=='af8c9488554d254fefa86435871d8278389fae98640cf4176e696ce7195d51e9'
         and sha(body('history/e3-refusal-packet-manifest.json'))=='75f8d31201824cf437a7142e160a9aab43d49f0c7e9a507cd47fb89df5d3a56b',
         'immutable E3 refusal summary/manifest differs')
    negative=(verify_negative_semantics(body,summary,audit,root)
              if manifest['outcomeKind']=='partial-refusal' else None)
    return dict(status='COMPLETE_PHYSICAL_LOGICAL_PACKET_CLOSURE_VERIFIED_NOT_QUALIFIED',
        payloadFiles=len(rows),originalFiles=len(mapping),manifestSha256=file_sha(packet/'packet-manifest.json'),
        allPhysicalAndLogicalBodiesVerified=True,negativeRecordSemantics=negative,
        backendQualified=False,independentHumanReview=False)
