"""Bounded synthetic byte-transport controls; no actual E5 packet or outcome."""
from pathlib import Path
import argparse
import copy
import gzip
import hashlib
import json
import os
import shutil
import time
import lossless_members as codec

C=Path(__file__).resolve().parent
B=Path('/Volumes/Untitled/AIJADE')


def main():
    p=argparse.ArgumentParser();p.add_argument('--generation',required=True);a=p.parse_args()
    if not a.generation.isascii() or not a.generation.replace('-','').isalnum():raise ValueError('safe exclusive generation required')
    report_dir=C/a.generation
    runtime=B/'.runtime/posix/archive-codec-controls'/a.generation
    if report_dir.exists() or runtime.exists():raise FileExistsError('retain all prior fixtures and reports')
    report_dir.mkdir();runtime.mkdir(parents=True,mode=0o700)
    start=time.monotonic();results=[]
    def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    def write(path,raw):
        with path.open('xb') as stream:os.fchmod(stream.fileno(),0o600);stream.write(raw)
    tiny=runtime/'original-opaque.bin'
    original=(b'{ "x":1.00, "x":2, "escaped":"\\u4e2d" }\r\n\t\x00\xff'+bytes(range(64)))*3
    write(tiny,original)
    tiny_receipt=codec.encode_file(tiny,runtime/'tiny-original','synthetic/opaque.jsonl',member_bytes=64)
    tiny_env=runtime/'tiny-original'
    descriptor=json.loads((tiny_env/'envelope.json').read_bytes())

    def control(name,action,refuse=False,reason=None):
        try:
            try:value=action()
            except (ValueError,OSError) as error:
                if not refuse or (reason and reason not in str(error)):raise
                record=dict(name=name,status='PASS',expected='REFUSED',actualType=type(error).__name__,reason=str(error))
            else:
                if refuse:raise AssertionError('adverse fixture accepted')
                record=dict(name=name,status='PASS',result=value)
        except Exception as error:record=dict(name=name,status='FAIL',errorType=type(error).__name__,error=str(error))
        results.append(record);print(record['status'],name,flush=True)
        (report_dir/'progress.json').write_bytes(encoded(results))

    def mutate(name,change,output=None):
        folder=runtime/name;shutil.copytree(tiny_env,folder)
        envelope=json.loads((folder/'envelope.json').read_bytes());change(folder,envelope)
        raw=encoded(envelope);(folder/'envelope.json').write_bytes(raw)
        return codec.verify_envelope(folder,expected_envelope_sha256=codec.sha(raw),output=output)

    def change_bytes(folder,envelope,operation):
        row=envelope['members'][0];path=folder/row['path'];raw=operation(path.read_bytes());path.write_bytes(raw)
        row.update(encodedSizeBytes=len(raw),encodedSha256=codec.sha(raw))

    def exact_roundtrip():
        output=runtime/'tiny-decoded.bin'
        result=codec.verify_envelope(tiny_env,expected_envelope_sha256=tiny_receipt['envelopeSha256'],output=output)
        if output.read_bytes()!=original:raise AssertionError('opaque original bytes were normalized or changed')
        if output.with_name(output.name+'.transport-partial').exists():raise AssertionError('verified output partial remained')
        return result
    control('tiny_opaque_bytes_roundtrip_no_json_rewrite',exact_roundtrip)

    def empty():
        path=runtime/'empty.bin';write(path,b'');receipt=codec.encode_file(path,runtime/'empty-envelope','empty.bin')
        result=codec.verify_envelope(runtime/'empty-envelope',expected_envelope_sha256=receipt['envelopeSha256'])
        if result['logicalSizeBytes']!=0 or result['memberCount']!=1:raise AssertionError('empty stream contract differs')
        return result
    control('empty_logical_file_has_one_complete_member',empty)
    control('immutable_envelope_pin_refuses_substitution',lambda:codec.verify_envelope(tiny_env,expected_envelope_sha256='0'*64),True,'pinned envelope')
    control('truncated_member_refused',lambda:mutate('bad-truncated',lambda f,e:change_bytes(f,e,lambda x:x[:-4])),True,'incomplete gzip EOF')
    control('corrupt_crc_refused',lambda:mutate('bad-crc',lambda f,e:change_bytes(f,e,lambda x:x[:-8]+bytes([x[-8]^1])+x[-7:])),True,'CRC')
    control('extra_empty_gzip_member_refused',lambda:mutate('bad-extra-empty',lambda f,e:change_bytes(f,e,lambda x:x+gzip.compress(b'',mtime=0))),True,'extra gzip member')
    control('arbitrary_trailing_bytes_refused',lambda:mutate('bad-trailing',lambda f,e:change_bytes(f,e,lambda x:x+b'\0')),True,'trailing encoded')
    control('nonzero_header_time_refused',lambda:mutate('bad-mtime',lambda f,e:change_bytes(f,e,lambda x:x[:4]+b'\1'+x[5:])),True,'header')
    control('optional_filename_flags_refused',lambda:mutate('bad-flags',lambda f,e:change_bytes(f,e,lambda x:x[:3]+b'\x08'+x[4:])),True,'header')
    control('encoded_sha_mismatch_refused',lambda:mutate('bad-encoded-sha',lambda f,e:e['members'][0].update(encodedSha256='0'*64)),True,'encoded member SHA')
    control('decoded_original_sha_mismatch_refused',lambda:mutate('bad-decoded-sha',lambda f,e:e['members'][0].update(decodedSha256='0'*64)),True,'decoded original SHA')
    control('whole_logical_sha_mismatch_refused',lambda:mutate('bad-logical-sha',lambda f,e:e.update(logicalSha256='0'*64)),True,'logical body SHA')
    control('ordinal_reorder_refused',lambda:mutate('bad-ordinal',lambda f,e:e['members'].reverse()),True,'ordinal')
    control('offset_gap_refused',lambda:mutate('bad-offset',lambda f,e:e['members'][1].update(logicalOffsetBytes=999)),True,'offset')
    control('boolean_size_refused',lambda:mutate('bad-bool',lambda f,e:e['members'][0].update(decodedSizeBytes=True)),True,'integer')
    control('equal_float_size_refused',lambda:mutate('bad-float',lambda f,e:e['members'][0].update(decodedSizeBytes=float(e['members'][0]['decodedSizeBytes']))),True,'integer')
    control('missing_member_refused',lambda:mutate('bad-missing',lambda f,e:(f/e['members'][-1]['path']).unlink()),True,'missing/extra')
    control('extra_member_file_refused',lambda:mutate('bad-extra',lambda f,e:(f/'unlisted.gz').write_bytes(b'fixture')),True,'missing/extra')
    control('logical_name_traversal_refused',lambda:mutate('bad-name',lambda f,e:e.update(logicalName='../outside')),True,'logical name')
    control('caller_logical_cap_refused',lambda:codec.verify_envelope(tiny_env,expected_envelope_sha256=tiny_receipt['envelopeSha256'],logical_cap_bytes=1),True,'logical size')
    control('encoded_cap_above_github_ceiling_refused',lambda:mutate('bad-encoded-cap',lambda f,e:e.update(memberEncodedLimitBytes=100000000)),True,'encoded cap')

    def duplicate_keys():
        folder=runtime/'bad-duplicate-key';shutil.copytree(tiny_env,folder)
        raw=(folder/'envelope.json').read_bytes().replace(b'{',b'{"schema":"duplicate",',1)
        (folder/'envelope.json').write_bytes(raw)
        return codec.verify_envelope(folder,expected_envelope_sha256=codec.sha(raw))
    control('duplicate_json_envelope_key_refused',duplicate_keys,True,'duplicate')

    def member_bomb():
        path=runtime/'declared-small-member.gz'
        with path.open('xb') as stream:
            with gzip.GzipFile(filename='',fileobj=stream,mode='wb',mtime=0,compresslevel=6) as zipper:zipper.write(b'x'*(2*1024*1024))
        n,h=codec._digest_file(path)
        return codec.verify_single_member(path,encoded_size_bytes=n,encoded_sha256=h,
            decoded_size_bytes=1024,decoded_sha256=codec.sha(b'x'*1024),decoded_cap_bytes=1024)
    control('gzip_expansion_stops_at_declared_decoded_cap',member_bomb,True,'decoded body exceeds')

    def rejected_output_not_promoted():
        output=runtime/'invalid-output.bin'
        try:mutate('bad-output',lambda f,e:e.update(logicalSha256='0'*64),output=output)
        except ValueError:
            if output.exists() or not output.with_name(output.name+'.transport-partial').exists():raise AssertionError('rejected partial was promoted or lost')
            return dict(rejectedFinalOutputAbsent=True,partialRetained=True)
        raise AssertionError('invalid logical output accepted')
    control('rejected_decoded_output_is_never_promoted',rejected_output_not_promoted)

    def existing_output():
        path=runtime/'protected-existing.bin';write(path,b'protected')
        try:codec.verify_envelope(tiny_env,expected_envelope_sha256=tiny_receipt['envelopeSha256'],output=path)
        finally:
            if path.read_bytes()!=b'protected':raise AssertionError('existing output overwritten')
    control('existing_output_never_overwritten',existing_output,True,'exclusive decoded output')

    def deterministic_large():
        path=runtime/'synthetic-opaque-128MiB.bin'
        block=(b'uncanonical: { "n": 1.00 }\r\n\t\x00\xff'+bytes(range(251)))*4000
        block=(block*((1024*1024+len(block)-1)//len(block)))[:1024*1024]
        digest=hashlib.sha256()
        with path.open('xb') as stream:
            os.fchmod(stream.fileno(),0o600)
            for _ in range(128):stream.write(block);digest.update(block)
        first=codec.encode_file(path,runtime/'large-A','synthetic/opaque-128MiB.bin')
        second=codec.encode_file(path,runtime/'large-B','synthetic/opaque-128MiB.bin')
        left=runtime/'large-A';right=runtime/'large-B'
        if first['envelopeSha256']!=second['envelopeSha256']:raise AssertionError('nondeterministic envelope')
        for part in left.iterdir():
            if part.read_bytes()!=(right/part.name).read_bytes():raise AssertionError('nondeterministic fixed gzip member')
        report=codec.verify_envelope(left,expected_envelope_sha256=first['envelopeSha256'])
        if report['logicalSizeBytes']!=128*1024**2 or report['logicalSha256']!=digest.hexdigest():raise AssertionError('full 128MiB byte identity differs')
        if any(p.stat().st_size>codec.DEFAULT_ENCODED_CAP for p in left.glob('*.gz')):raise AssertionError('physical GitHub object ceiling exceeded')
        return dict(rawBytes=128*1024**2,rawSha256=digest.hexdigest(),members=report['memberCount'],
            encodedTotalBytes=report['encodedTotalBytes'],envelopeSha256=first['envelopeSha256'],
            twoEncodesByteIdentical=True,decodedFullSizeAndShaVerified=True,secondDecodedRawNotWritten=True,
            maximumDecodeOutputChunkBytes=codec.BLOCK_BYTES,zlibVersion=first['zlibVersion'],zlibRuntimeVersion=first['zlibRuntimeVersion'])
    control('deterministic_128MiB_streamed_multimember_envelope',deterministic_large)

    def e4_existing_transport_only():
        packet=B/'.research/runs/ch7-nested-copy-20261118/audit/engineering-02-packet'
        manifest=(packet/'packet-manifest.json').read_bytes()
        if codec.sha(manifest)!='819cde4e8f7b8197f74181ec2ac6ec5d2ef82aeda6a6d56e1c949617de917e59':raise AssertionError('fixed original E4 packet differs')
        row=next(r for r in json.loads(manifest)['files'] if r.get('logicalPath')=='run/engineering-02/settling/telemetry.jsonl')
        result=codec.verify_single_member(packet/row['path'],encoded_size_bytes=row['sizeBytes'],encoded_sha256=row['sha256'],
            decoded_size_bytes=row['logicalSizeBytes'],decoded_sha256=row['logicalSha256'],decoded_cap_bytes=128*1024**2)
        if result['decodedSizeBytes']!=66926629:raise AssertionError('actual old transport logical size differs')
        return dict(**result,actualE4BytesOnly=True,newColdGuardAudit=False,newEngineeringAcceptance=False)
    control('immutable_existing_e4_transport_lossless_not_semantic_acceptance',e4_existing_transport_only)
    result=dict(schema='aijade.lossless-transport-controls.v1',status='PASS' if all(r['status']=='PASS' for r in results) else 'FAIL',
        passed=sum(r['status']=='PASS' for r in results),total=len(results),controls=results,
        elapsedSeconds=time.monotonic()-start,codecSourceSha256=codec.sha(Path(codec.__file__).read_bytes()),
        controlSourceSha256=codec.sha(Path(__file__).read_bytes()),projectRuntimeDirectory=str(runtime),
        allNewFilesInsideAIJADE=True,actualE4PacketChanged=False,actualE5PacketCreated=False,
        scientificOutcomeInvented=False,gitNetworkNativeApiModelCalls=0,semanticAcceptance=False)
    (report_dir/'result.json').write_bytes(encoded(result))
    print(json.dumps({k:result[k] for k in ('status','passed','total','elapsedSeconds')}))
    raise SystemExit(0 if result['status']=='PASS' else 1)


if __name__=='__main__':main()
