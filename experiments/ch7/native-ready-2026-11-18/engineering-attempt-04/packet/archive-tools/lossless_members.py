"""Generic source-neutral lossless transport; no research outcome on import.

Every physical gzip file contains exactly one fixed-header member. A logical
file can span bounded members without ever rewriting JSON or other input bytes.
Future research manifests must pin the envelope SHA and separately audit meaning.
"""
from pathlib import Path
import gzip
import hashlib
import json
import os
import stat
import zlib

BASE=Path('/Volumes/Untitled/AIJADE')
SCHEMA='aijade.lossless-gzip-member-envelope.v1'
MEMBER_CODEC='gzip-single-member-level6-mtime0-v1'
BLOCK_BYTES=1024*1024
DEFAULT_MEMBER_BYTES=16*1024*1024
DEFAULT_ENCODED_CAP=32*1024*1024
MAX_LOGICAL_BYTES=2*1024**3
MAX_ENCODED_CAP=95*1024**2  # below GitHub's decimal 100,000,000-byte file ceiling
HEADER=b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff'


def need(ok,message):
    if not ok:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def _hex(value):return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _integer(value,low,high,label):
    need(type(value) is int and low<=value<=high,label+' integer/range')
    return value


def _canonical_path(value,writing=False):
    p=Path(value)
    need(p.is_absolute() and p==p.resolve(),'absolute canonical transport path required')
    need(not any(q.is_symlink() for q in (p,*p.parents)),'transport symlink path')
    if writing:need(p.is_relative_to(BASE),'transport writes must remain inside AIJADE')
    return p


def _identity(item):return (item.st_dev,item.st_ino,item.st_size,item.st_mtime_ns,item.st_mode,item.st_nlink,item.st_uid)


def _open_source(path):
    path=_canonical_path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    item=os.fstat(fd)
    if not stat.S_ISREG(item.st_mode) or item.st_nlink!=1:
        os.close(fd);raise ValueError('regular single-link source required')
    return path,os.fdopen(fd,'rb'),_identity(item)


def _same_source(path,stream,before):
    need(_identity(os.fstat(stream.fileno()))==before==_identity(os.stat(path,follow_symlinks=False)),
         'source changed during lossless transport')


def _digest_file(path):
    digest=hashlib.sha256();size=0
    path,stream,before=_open_source(path)
    with stream:
        for chunk in iter(lambda:stream.read(BLOCK_BYTES),b''):digest.update(chunk);size+=len(chunk)
        _same_source(path,stream,before)
    return size,digest.hexdigest()


def _logical_name(value):
    need(type(value) is str and value and '\\' not in value and ':' not in value and
         not any(ord(c)<32 for c in value) and not value.startswith('/') and
         all(p not in ('','.','..') for p in value.split('/')),'canonical logical name required')
    return value


def _decode_json(raw):
    def unique(pairs):
        value={}
        for key,item in pairs:
            need(key not in value,'duplicate envelope key');value[key]=item
        return value
    return json.loads(raw,object_pairs_hook=unique,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite envelope value')))


def encode_file(source,directory,logical_name,*,member_bytes=DEFAULT_MEMBER_BYTES,
                encoded_cap_bytes=DEFAULT_ENCODED_CAP,logical_cap_bytes=MAX_LOGICAL_BYTES):
    """Create a new envelope; partial failures remain explicitly unsealed."""
    _integer(member_bytes,1,DEFAULT_MEMBER_BYTES,'member decoded ceiling')
    _integer(encoded_cap_bytes,1,MAX_ENCODED_CAP,'member encoded ceiling')
    _integer(logical_cap_bytes,0,MAX_LOGICAL_BYTES,'logical ceiling')
    _logical_name(logical_name)
    directory=_canonical_path(directory,writing=True)
    need(not directory.exists() and directory.parent.is_dir(),'exclusive envelope directory required')
    source,stream,before=_open_source(source)
    logical_size=before[2]
    need(logical_size<=logical_cap_bytes,'source exceeds declared logical ceiling')
    members=[];logical_hash=hashlib.sha256();offset=0
    directory.mkdir(mode=0o700)
    with stream:
        for ordinal in range(max(1,(logical_size+member_bytes-1)//member_bytes)):
            amount=min(member_bytes,logical_size-offset);name='member-%06d.gz'%ordinal
            path=directory/name;decoded_hash=hashlib.sha256();count=0
            with path.open('xb') as output:
                os.fchmod(output.fileno(),0o600)
                with gzip.GzipFile(filename='',fileobj=output,mode='wb',compresslevel=6,mtime=0) as zipper:
                    while count<amount:
                        raw=stream.read(min(BLOCK_BYTES,amount-count))
                        need(raw,'source truncated during transport')
                        count+=len(raw);decoded_hash.update(raw);logical_hash.update(raw);zipper.write(raw)
            encoded_size,encoded_sha=_digest_file(path)
            need(encoded_size<=encoded_cap_bytes,'encoded member exceeds its bounded physical ceiling')
            with path.open('rb') as stream_check:
                need(stream_check.read(10)==HEADER,'encoder did not emit fixed no-filename gzip header')
            members.append(dict(ordinal=ordinal,path=name,logicalOffsetBytes=offset,
                decodedSizeBytes=count,decodedSha256=decoded_hash.hexdigest(),
                encodedSizeBytes=encoded_size,encodedSha256=encoded_sha))
            offset+=count
        need(offset==logical_size and stream.read(1)==b'','complete logical source size changed')
        _same_source(source,stream,before)
    envelope=dict(schema=SCHEMA,memberCodec=MEMBER_CODEC,logicalName=logical_name,
        logicalSizeBytes=logical_size,logicalSha256=logical_hash.hexdigest(),
        memberDecodedLimitBytes=member_bytes,memberEncodedLimitBytes=encoded_cap_bytes,members=members)
    raw=(json.dumps(envelope,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    with (directory/'envelope.json').open('xb') as output:output.write(raw)
    return dict(status='LOSSLESS_TRANSPORT_ENCODED_NO_RESEARCH_ACCEPTANCE',envelopeSha256=sha(raw),
        logicalSizeBytes=logical_size,logicalSha256=logical_hash.hexdigest(),members=len(members),
        sourceIdentityBeforeAndAfter=list(before),zlibVersion=zlib.ZLIB_VERSION,zlibRuntimeVersion=zlib.ZLIB_RUNTIME_VERSION,
        originalBytesRewritten=False,researchSemanticsChecked=False)


def verify_single_member(path,*,encoded_size_bytes,encoded_sha256,decoded_size_bytes,
                         decoded_sha256,decoded_cap_bytes=MAX_LOGICAL_BYTES,_sink=None):
    """Decode one exact gzip member; concatenation and every trailing byte refuse."""
    _integer(encoded_size_bytes,20,MAX_ENCODED_CAP,'encoded member size')
    _integer(decoded_cap_bytes,0,MAX_LOGICAL_BYTES,'decoded member cap')
    _integer(decoded_size_bytes,0,decoded_cap_bytes,'declared decoded size')
    need(_hex(encoded_sha256) and _hex(decoded_sha256),'fixed member SHA256 identities required')
    path,stream,before=_open_source(path)
    need(before[2]==encoded_size_bytes,'physical encoded size differs')
    compressed=hashlib.sha256();decoded=hashlib.sha256();encoded_count=decoded_count=0
    decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
    with stream:
        need(stream.read(10)==HEADER,'fixed gzip header/flags/mtime/filename differs')
        stream.seek(0)
        for chunk in iter(lambda:stream.read(BLOCK_BYTES),b''):
            need(not decoder.eof,'extra gzip member or trailing encoded bytes')
            encoded_count+=len(chunk);compressed.update(chunk)
            pending=chunk
            while pending:
                limit=min(BLOCK_BYTES,min(decoded_cap_bytes,decoded_size_bytes)-decoded_count+1)
                try:raw=decoder.decompress(pending,limit)
                except zlib.error as error:raise ValueError('invalid gzip stream/CRC/trailer') from error
                decoded_count+=len(raw)
                need(decoded_count<=decoded_size_bytes and decoded_count<=decoded_cap_bytes,'decoded body exceeds declared bound')
                need(not decoder.unused_data,'extra gzip member or trailing encoded bytes')
                remaining=decoder.unconsumed_tail
                need(raw or len(remaining)<len(pending) or decoder.eof,'stalled gzip decoder')
                decoded.update(raw)
                if _sink is not None:_sink(raw)
                pending=remaining
        need(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
             'incomplete gzip EOF or extra encoded member')
        need(encoded_count==encoded_size_bytes and compressed.hexdigest()==encoded_sha256,'encoded member SHA/size differs')
        need(decoded_count==decoded_size_bytes and decoded.hexdigest()==decoded_sha256,'decoded original SHA/size differs')
        _same_source(path,stream,before)
    return dict(status='EXACT_SINGLE_MEMBER_TRANSPORT_VERIFIED_NO_SEMANTIC_ACCEPTANCE',
        encodedSizeBytes=encoded_count,encodedSha256=compressed.hexdigest(),decodedSizeBytes=decoded_count,
        decodedSha256=decoded.hexdigest(),completeEof=True,extraMembers=False)


def verify_envelope(directory,*,expected_envelope_sha256,logical_cap_bytes=MAX_LOGICAL_BYTES,output=None):
    """Verify exact member population and logical concatenation; optional atomic output."""
    directory=_canonical_path(directory)
    need(directory.is_dir() and _hex(expected_envelope_sha256),'fixed envelope directory/SHA required')
    _integer(logical_cap_bytes,0,MAX_LOGICAL_BYTES,'logical decoded cap')
    envelope_path,envelope_stream,envelope_before=_open_source(directory/'envelope.json')
    with envelope_stream:
        need(envelope_before[2]<=1024*1024,'envelope metadata exceeds fixed cap')
        raw=envelope_stream.read(1024*1024+1)
        _same_source(envelope_path,envelope_stream,envelope_before)
    need(len(raw)<=1024*1024 and sha(raw)==expected_envelope_sha256,'pinned envelope bytes differ')
    value=_decode_json(raw)
    need(type(value) is dict and set(value)=={'schema','memberCodec','logicalName','logicalSizeBytes','logicalSha256',
        'memberDecodedLimitBytes','memberEncodedLimitBytes','members'} and value['schema']==SCHEMA and
        value['memberCodec']==MEMBER_CODEC,'exact generic transport envelope schema')
    size=_integer(value['logicalSizeBytes'],0,logical_cap_bytes,'logical size')
    _logical_name(value['logicalName'])
    member_cap=_integer(value['memberDecodedLimitBytes'],1,DEFAULT_MEMBER_BYTES,'member decoded cap')
    encoded_cap=_integer(value['memberEncodedLimitBytes'],1,MAX_ENCODED_CAP,'member encoded cap')
    need(_hex(value['logicalSha256']),'logical original hash required')
    rows=value['members'];expected_count=max(1,(size+member_cap-1)//member_cap)
    need(type(rows) is list and len(rows)==expected_count,'exact decoded member population')
    expected={'envelope.json'}|{'member-%06d.gz'%n for n in range(expected_count)}
    entries=list(directory.iterdir())
    need({p.name for p in entries}==expected and all(p.is_file() and not p.is_symlink() for p in entries),
         'missing/extra/symlink member or directory')
    target=partial=writer=None
    if output is not None:
        target=_canonical_path(output,writing=True)
        need(not target.is_relative_to(directory) and not target.exists(),'exclusive decoded output outside envelope required')
        partial=target.with_name(target.name+'.transport-partial')
        fd=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        writer=os.fdopen(fd,'wb')
    logical_hash=hashlib.sha256();offset=0;encoded_total=0
    try:
        for ordinal,row in enumerate(rows):
            need(type(row) is dict and set(row)=={'ordinal','path','logicalOffsetBytes','decodedSizeBytes','decodedSha256',
                'encodedSizeBytes','encodedSha256'},'exact member descriptor schema')
            _integer(row['ordinal'],ordinal,ordinal,'contiguous ordinal')
            _integer(row['logicalOffsetBytes'],offset,offset,'contiguous byte offset')
            need(row['path']=='member-%06d.gz'%ordinal,'fixed member name/order')
            amount=min(member_cap,size-offset)
            _integer(row['decodedSizeBytes'],amount,amount,'complete member decoded size')
            _integer(row['encodedSizeBytes'],20,encoded_cap,'physical member size/cap')
            def sink(data):
                logical_hash.update(data)
                if writer is not None:writer.write(data)
            verify_single_member(directory/row['path'],encoded_size_bytes=row['encodedSizeBytes'],
                encoded_sha256=row['encodedSha256'],decoded_size_bytes=amount,decoded_sha256=row['decodedSha256'],
                decoded_cap_bytes=member_cap,_sink=sink)
            offset+=amount;encoded_total+=row['encodedSizeBytes']
        need(offset==size and logical_hash.hexdigest()==value['logicalSha256'],'complete original logical body SHA/size differs')
        if writer is not None:
            writer.flush();os.fsync(writer.fileno());writer.close();writer=None
            os.link(partial,target)  # atomic no-overwrite publication, even if another writer races
            partial.unlink()
    finally:
        if writer is not None:writer.close()  # rejected partial is retained, never promoted
    return dict(status='LOSSLESS_ENVELOPE_BYTES_VERIFIED_NO_RESEARCH_ACCEPTANCE',
        envelopeSha256=expected_envelope_sha256,logicalSizeBytes=offset,logicalSha256=logical_hash.hexdigest(),
        memberCount=len(rows),encodedTotalBytes=encoded_total,allMembersCompleteSingleGzip=True,
        logicalOutputWritten=target is not None,originalBytesRewritten=False,researchSemanticsChecked=False)
