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
               '.sln','.slnx','.props','.targets','.csproj','.diff','.index'}
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
    """E5 transport/structural closure only, never E3 first-sample semantics."""
    false=('backendQualified','scientificAcceptance','formalHardwareQualification','independentHumanReview',
           'authorApproval','seedConstructed','heldoutComparisonComplete','currentProductInheritsResearchQualification')
    need(all(summary['scope'].get(k) is False for k in false) and all(root['scope'].get(k) is False for k in false if k!='currentProductInheritsResearchQualification'),
         'negative engineering archive promoted scientific scope')
    need(summary['engineeringEnvelopeAccepted'] is False and root_engineering_accepted(root) is False,
         'negative attempt promoted to complete engineering acceptance')
    need(audit['schema'] in ('aijade.ch7.nested-partial-negative-record-audit.v2','aijade.ch7.e5-partial-cold-negative-audit.v1')
         and audit['status']=='REFUSED_NESTED_PARTIAL_RECORDS_INVENTORIED_NOT_ENGINEERING_ACCEPTED'
         and audit['completeEngineeringAuditAccepted'] is False,
         'E5 negative archive requires its explicit structural-only audit')
    if audit['schema']=='aijade.ch7.e5-partial-cold-negative-audit.v1':
        from e5_refusal_semantics import verify
        return verify(body,summary,audit,root)
    # The result-specific E3 cold predicate deliberately does not exist here.
    # Journal and retained-record structural counts are derived by the separately
    # archived v2 inspector, with missing/invalid journal populations left null.
    return dict(status='E4_STRUCTURAL_NEGATIVE_RECORD_ONLY_NO_KERNEL_OR_COMPLETE_ACCEPTANCE',
        actualKernelColdReplayRepeated=False,completeEngineeringAuditAccepted=False,scientificQualification=False)



CODEC_SHA='5aef0e38d39a67273f6f9999b4dc52cc6b09250e8dbbd9fd09cdbaabcbaa3a72'
MAX_BODY_BYTES=128*1024**2
ROOT_SCHEMA='aijade.ch7.e5-root-disposition.v1'


def root_engineering_accepted(root):
    need(root.get('schema')==ROOT_SCHEMA and type(root.get('engineeringAccepted')) is bool,
         'actual E5 root disposition schema/acceptance type')
    need(root['scope'].get('fullEngineeringEnvelopeAccepted') is root['engineeringAccepted'],
         'root engineering acceptance fields disagree')
    return root['engineeringAccepted']


def codec_module():
    import lossless_members as codec
    expected=Path(__file__).with_name('lossless_members.py').resolve()
    need(Path(codec.__file__).resolve()==expected and file_sha(expected)==CODEC_SHA,
         'fixed colocated bounded lossless codec required')
    return codec


def logical_table(packet):
    return {r['logicalPath']:r for r in read(Path(packet)/'packet-manifest.json')['logicalFiles']}


def logical_body(packet, entry):
    packet=Path(packet)
    size=entry['logicalSizeBytes']
    need(type(size) is int and 0<=size<=MAX_BODY_BYTES,'bounded semantic logical body size')
    if entry['kind']=='direct':
        raw=(packet/entry['packetPath']).read_bytes()
    else:
        need(entry['kind']=='bounded-gzip-members-v1','logical body transport kind')
        codec=codec_module();directory=(packet/entry['envelopePath']).parent
        envelope=read(directory/'envelope.json');pieces=[];amount=[0]
        def sink(part):
            amount[0]+=len(part);need(amount[0]<=size,'logical body exceeds declared complete bound');pieces.append(part)
        for member in envelope['members']:
            codec.verify_single_member(directory/member['path'],encoded_size_bytes=member['encodedSizeBytes'],
                encoded_sha256=member['encodedSha256'],decoded_size_bytes=member['decodedSizeBytes'],
                decoded_sha256=member['decodedSha256'],decoded_cap_bytes=16*1024**2,_sink=sink)
        raw=b''.join(pieces)
    need(len(raw)==size and sha(raw)==entry['logicalSha256'],'logical body complete SHA/size differs')
    return raw


def verify_packet(packet):
    """Portable Python3.9+ transport/semantic check; no live/kernel/source execution."""
    original=Path(packet).absolute()
    need(not any(p.is_symlink() for p in (original,*original.parents)),'symlink in read-only packet path')
    packet=original.resolve();need(packet.is_dir(),'packet directory missing')
    manifest=read(packet/'packet-manifest.json')
    need(manifest.get('schema')=='aijade.ch7.real-nested-packet-manifest.v2'
         and manifest.get('transportCodecSha256')==CODEC_SHA,'packet v2 manifest/codec identity')
    rows=manifest['files'];names=[relative(r['path']) for r in rows]
    need(len(names)==len(set(names)) and 'packet-manifest.json' not in names,'packet manifest physical population')
    need(len({unicodedata.normalize('NFC',n).casefold() for n in names})==len(names),'physical case/normalization collision')
    actual={p.relative_to(packet).as_posix() for p in packet.rglob('*') if p.is_file()}
    need(actual==set(names)|{'packet-manifest.json'},'exact physical packet file population differs')
    need(not any(p.is_symlink() for p in packet.rglob('*')),'packet symlink')
    for row in rows:
        p=packet/row['path']
        need(type(row['sizeBytes']) is int and row['sizeBytes']>=0 and p.stat().st_size==row['sizeBytes']
             and file_sha(p)==row['sha256'],'physical packet hash/size differs: '+row['path'])
    logical={};entries={};referenced=set();codec=codec_module()
    for row in manifest['logicalFiles']:
        name=relative(row['logicalPath']);need(name not in logical,'logical path collision')
        need(type(row['logicalSizeBytes']) is int and 0<=row['logicalSizeBytes']<=2*1024**3,'logical size/cap')
        if row['kind']=='direct':
            physical=relative(row['packetPath']);need(physical==name and physical in names,'direct logical/physical path differs')
            need(file_sha(packet/physical)==row['logicalSha256'] and (packet/physical).stat().st_size==row['logicalSizeBytes'],
                 'direct logical hash/size differs');referenced.add(physical)
        else:
            need(row['kind']=='bounded-gzip-members-v1','undeclared logical codec')
            envelope_path=relative(row['envelopePath']);need(envelope_path=='transport/'+name+'/envelope.json',
                 'fixed original logical envelope path differs')
            directory=(packet/envelope_path).parent
            result=codec.verify_envelope(directory,expected_envelope_sha256=row['envelopeSha256'])
            envelope=read(packet/envelope_path)
            need(envelope['logicalName']==name and result['logicalSizeBytes']==row['logicalSizeBytes']
                 and result['logicalSha256']==row['logicalSha256'],'complete logical original envelope differs')
            referenced.add(envelope_path)
            referenced.update((Path(envelope_path).parent/v['path']).as_posix() for v in envelope['members'])
        logical[name]=dict(sha256=row['logicalSha256'],bytes=row['logicalSizeBytes']);entries[name]=row
    need(referenced==set(names),'unreferenced or multiply-scoped physical payload')
    def body(name):return logical_body(packet,entries[name])
    mapping=decode(body('metadata/source-map.json'))['originalSources']
    need(len({v['logicalPacketPath'] for v in mapping})==len(mapping),'source-map duplicate')
    for row in mapping:
        need(row['logicalPacketPath'] in logical and typed_equal(logical[row['logicalPacketPath']],
             dict(sha256=row['originalSha256'],bytes=row['originalSizeBytes'])),'original/logical source mapping differs')
    summary=decode(body('summary.json'));audit=decode(body('audit/independent-audit.json'));root=decode(body('audit/root-disposition.json'))
    need(typed_equal(summary['numbers'],audit['numbers']) and typed_equal(root['numbers'],audit['numbers']),
         'complete summary numeric values/types were dropped or changed')
    source=decode(body('metadata/frozen-source-proofs.json'));proof=source['sources']
    need(source['sourceCommit']==manifest['sourceCommit']==summary['sourceCommit']==root['sourceCommit'],'source commit anchors differ')
    need(len(proof)==len(source['sourceFiles'])==48 and {r['path'] for r in proof}==set(source['sourceFiles'])
         and {name[7:] for name in logical if name.startswith('source/')}==set(source['sourceFiles']),
         'complete frozen source population differs')
    for row in proof:
        raw=body('source/'+row['path'])
        need(sha(raw)==row['sha256']==source['sourceFiles'][row['path']]
             and hashlib.sha1(('blob %d\0'%len(raw)).encode()+raw).hexdigest()==row['gitBlob']
             and row['commit']==manifest['sourceCommit'] and row['gitMode'] in ('100644','100755'),
             'fixed original Git source body/hash/object differs')
    passport_raw=body('publication/engineering-03-passport.json');passport=decode(passport_raw)
    need(typed_equal(source['sourceFiles'],passport['sourceFiles']) and typed_equal(source['observerSources'],passport['observerSources']),
         'original passport and frozen source closure population differ')
    need(sha(passport_raw)==manifest['passportSha256']==summary['passportSha256']==root['passportSha256']
         and body('run/engineering-03/engineering-passport.json')==passport_raw,'actual original/external passport body identity differs')
    need(len(passport['observerSources'])==18 and passport['onlineReplayMode']=='owned-guard-state-exact-prefix-v1'
         and passport['onlineReplayInitializationMode']=='paired-source-verified-owned-state-v1'
         and passport['onlineReplaySourceSha256']==source['sourceFiles']['experiments/ch7/newowned_guard_cursor.py'],
         'actual eighteen-source owned observer closure differs')
    false=('backendQualified','scientificAcceptance','formalHardwareQualification','independentHumanReview',
           'authorApproval','seedConstructed','heldoutComparisonComplete','currentProductInheritsResearchQualification')
    need(all(summary['scope'].get(k) is False for k in false)
         and all(root['scope'].get(k) is False for k in false if k!='currentProductInheritsResearchQualification'),
         'engineering packet promoted scientific scope')
    need(root_engineering_accepted(root) is False and summary['engineeringEnvelopeAccepted'] is False,
         'original negative attempt promoted to acceptance')
    need(sha(body('audit/independent-audit.json'))==manifest['independentAuditSha256']==summary['independentAuditSha256']==root['independentAuditSha256']
         and sha(body('audit/root-disposition.json'))==manifest['rootDispositionSha256']==summary['rootDispositionSha256'],
         'independent audit/root disposition body anchors differ')
    terminal_raw=body('launch/engineering-03-launch.terminal.json');terminal=decode(terminal_raw);parent_wait_known(terminal)
    launch=decode(body('launch/engineering-03-launch.json'));stability_raw=body('audit/writer-stability.json');stability=decode(stability_raw)
    need(stability['writerStabilityAccepted'] is True and stability['allOriginalWritersTerminatedOrClosed'] is True
         and stability['unresolvedWriters']==[] and stability['sourceCommit']==manifest['sourceCommit']
         and stability['parentTerminalSha256']==audit['parentTerminalSha256']==sha(terminal_raw)
         and sha(stability_raw)==root['writerStabilityProofSha256']
         and sha(body('audit/root-writer-closure.json'))==root['rootAdditionalWriterClosureSha256']
         and terminal['launchRecordSha256']==sha(body('launch/engineering-03-launch.json'))
         and terminal['logSha256']==sha(body('launch/engineering-03-launch.log'))
         and terminal['passportSha256']==launch['passportSha256']==sha(passport_raw),
         'actual outer wait/writer closure/launch/log body binding differs')
    correction_raw=body('audit/listener-cause-precision-correction.json');correction=decode(correction_raw)
    need(sha(correction_raw)==root['causePrecisionCorrectionSha256']==summary['causePrecisionCorrectionSha256']
         and sha(body('history/ACTUAL-E5-RESULT-STATE.json'))==correction['earlierRecordSha256']
         and summary['causeClassification']=='UNRESOLVED_OR' and correction['originalRawFieldsChanged'] is False,
         'provisional cause/correction identity or unresolved classification differs')
    ci=decode(body('publication/final-source-ci.json'))
    need(ci['headSha']==manifest['sourceCommit'] and ci['status']=='completed' and ci['conclusion']=='success','actual successful source CI differs')
    directory=decode(body('metadata/run-directory-state.json'));prefix='run/engineering-03/'
    run_bodies={name[len(prefix):]:value for name,value in logical.items() if name.startswith(prefix)}
    need(typed_equal(directory['files'],run_bodies) and typed_equal(audit['inputFiles'],run_bodies),
         'complete retained original run body inventory differs from cold audit')
    old=[('history/p4-refusal-summary.json','7dbe9435d07f4357d8282200c3f540429b6bc7e4ed0b898166d328283d337b26'),
         ('history/e3-refusal-summary.json','af8c9488554d254fefa86435871d8278389fae98640cf4176e696ce7195d51e9'),
         ('history/e3-refusal-packet-manifest.json','75f8d31201824cf437a7142e160a9aab43d49f0c7e9a507cd47fb89df5d3a56b'),
         ('history/e4-refusal-summary.json','8d4f66480ec234c097a033165e48649a1c4128ce30f97a497ec256bb068187d1'),
         ('history/e4-refusal-packet-manifest.json','819cde4e8f7b8197f74181ec2ac6ec5d2ef82aeda6a6d56e1c949617de917e59')]
    for name,digest in old:need(sha(body(name))==digest,'immutable old refusal history differs: '+name)
    negative=verify_negative_semantics(body,summary,audit,root)
    return dict(status='COMPLETE_PHYSICAL_LOGICAL_PACKET_CLOSURE_VERIFIED_NOT_QUALIFIED',payloadFiles=len(rows),
        logicalFiles=len(logical),originalFiles=len(mapping),manifestSha256=file_sha(packet/'packet-manifest.json'),
        allPhysicalAndLogicalBodiesVerified=True,negativeRecordSemantics=negative,causeClassification='UNRESOLVED_OR',
        transportCodecSha256=CODEC_SHA,portableRuntime='Python3.9+; no AST or kernel replay',backendQualified=False,independentHumanReview=False)
