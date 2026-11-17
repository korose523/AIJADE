"""Nine copied-baseline adversarial controls; never change original evidence."""
from pathlib import Path
from datetime import datetime,timezone
import gzip
import hashlib
import json
import shutil

from packet_common import read,decode,encoded,new,sha,file_sha,need,typed_equal,verify_packet

B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-nested-20261117'
PRIMARY=C/'audit/engineering-01-packet';T=C/'archive-tools'
FIXTURES=T/'packet-controls-01-fixtures'


def table(root):
    return {p.relative_to(root).as_posix():dict(sha256=file_sha(p),bytes=p.stat().st_size)
            for p in sorted(root.rglob('*')) if p.is_file()}


def mapping(root):
    return {r.get('logicalPath',r['path']):r for r in read(root/'packet-manifest.json')['files']}


def body(root,name):
    row=mapping(root)[name];p=root/row['path']
    if row.get('compressedDeterministically'):
        with gzip.open(p,'rb') as stream:return stream.read()
    return p.read_bytes()


def put(root,name,raw):
    row=mapping(root)[name];p=root/row['path']
    if row.get('compressedDeterministically'):
        with p.open('wb') as stream:
            with gzip.GzipFile(filename='',fileobj=stream,mode='wb',compresslevel=6,mtime=0) as zipper:zipper.write(raw)
    else:p.write_bytes(raw)


def put_json(root,name,value):put(root,name,encoded(value))


def coherence(root):
    """Rebind hashes and copied-baseline metadata before testing semantics."""
    manifest=read(root/'packet-manifest.json');rows=manifest['files']
    def actual(row):
        p=root/row['path']
        if row.get('compressedDeterministically'):
            with gzip.open(p,'rb') as stream:raw=stream.read()
        else:raw=p.read_bytes()
        return dict(sha256=sha(raw),bytes=len(raw))
    run_prefix='run/engineering-01/'
    run={r.get('logicalPath',r['path'])[len(run_prefix):]:actual(r) for r in rows
         if r.get('logicalPath',r['path']).startswith(run_prefix)}
    directory=decode(body(root,'metadata/run-directory-state.json'));directory['files']=run
    directory['emptyFiles']=sorted(k for k,v in run.items() if v['bytes']==0)
    put_json(root,'metadata/run-directory-state.json',directory)
    audit=decode(body(root,'audit/independent-audit.json'));audit['inputFiles']=run
    if 'originalDirectoryState' in audit:audit['originalDirectoryState']=directory
    put_json(root,'audit/independent-audit.json',audit)
    disposition=decode(body(root,'audit/root-disposition.json'))
    disposition['independentAuditSha256']=sha(body(root,'audit/independent-audit.json'))
    put_json(root,'audit/root-disposition.json',disposition)
    summary=decode(body(root,'summary.json'))
    summary['independentAuditSha256']=sha(body(root,'audit/independent-audit.json'))
    summary['rootDispositionSha256']=sha(body(root,'audit/root-disposition.json'))
    put_json(root,'summary.json',summary)
    manifest['independentAuditSha256']=summary['independentAuditSha256'];manifest['rootDispositionSha256']=summary['rootDispositionSha256']
    source_map=decode(body(root,'metadata/source-map.json'))
    by_name={r.get('logicalPath',r['path']):r for r in rows}
    for item in source_map['originalSources']:
        v=actual(by_name[item['logicalPacketPath']]);item['originalSha256']=v['sha256'];item['originalSizeBytes']=v['bytes']
    put_json(root,'metadata/source-map.json',source_map)
    for row in rows:
        p=root/row['path'];row.update(sha256=file_sha(p),sizeBytes=p.stat().st_size)
        if 'logicalSha256' in row:
            v=actual(row);row.update(logicalSha256=v['sha256'],logicalSizeBytes=v['bytes'])
    (root/'packet-manifest.json').write_bytes(encoded(manifest))


def coherent_numbers(root,key,value):
    for name in ('summary.json','audit/independent-audit.json','audit/root-disposition.json'):
        record=decode(body(root,name));record['numbers'][key]=value;put_json(root,name,record)


def missing(root):
    row=mapping(root)['run/engineering-01/admission/telemetry.jsonl'];(root/row['path']).unlink()


def corrupt(root):
    p=root/mapping(root)['run/engineering-01/preflight-continuity.json']['path'];p.write_bytes(p.read_bytes()+b' ')


def number(root):coherent_numbers(root,'fullServiceSeconds',1.5);coherence(root)
def boolean(root):coherent_numbers(root,'modelRequests',False);coherence(root)


def promote(root):
    for name in ('summary.json','audit/independent-audit.json','audit/root-disposition.json'):
        value=decode(body(root,name));value['scope']['backendQualified']=True;put_json(root,name,value)
    coherence(root)


def truncated_prefix(root):
    name='run/engineering-01/settling/telemetry.jsonl';row=decode(body(root,name).strip());view=row['processObservation']['lifecycle']
    view['journalBytes']-=1;view['journalSha256']=sha(body(root,'run/engineering-01/lifecycle-journal.jsonl')[:view['journalBytes']])
    put(root,name,json.dumps(row,allow_nan=False).encode()+b'\n')
    coherent_numbers(root,'originalSampleJournalCutoffBytes',view['journalBytes']);coherence(root)


def changed_original_pass(root):
    name='run/engineering-01/settling/telemetry.jsonl';row=decode(body(root,name).strip())
    row['streamValidationStatus']='FAIL';row['processObservation']['status']='FAIL'
    put(root,name,json.dumps(row,allow_nan=False).encode()+b'\n')
    coherent_numbers(root,'settlingRawGuardColdPass',0);coherent_numbers(root,'settlingOriginalStreamValidationPass',0);coherence(root)


def source_omission(root):
    name='experiments/ch7/nested_event_index.py';physical='source/'+name
    (root/physical).unlink()
    proofs=decode(body(root,'metadata/frozen-source-proofs.json'))
    proofs['sourceFiles'].pop(name);proofs['sources']=[r for r in proofs['sources'] if r['path']!=name]
    put_json(root,'metadata/frozen-source-proofs.json',proofs)
    manifest=read(root/'packet-manifest.json');manifest['files']=[r for r in manifest['files'] if r['path']!=physical]
    (root/'packet-manifest.json').write_bytes(encoded(manifest));coherence(root)


def old_refusal(root):
    name='history/p4-refusal-summary.json';value=decode(body(root,name));value['status']='FALSELY_REPLACED_BY_LATER_PASS'
    put_json(root,name,value);coherence(root)


def main():
    need(not FIXTURES.exists(),'never overwrite actual copied-control history')
    primary=table(PRIMARY);baseline=verify_packet(PRIMARY);FIXTURES.mkdir()
    cases=[('missing-original-empty-admission',missing,'exact physical packet file population differs'),
        ('corrupt-physical-original',corrupt,'physical packet hash/size differs'),
        ('coherent-service-number-promotion',number,'coherently changed negative summary numbers'),
        ('coherent-bool-zero-substitution',boolean,'coherently changed negative summary numbers'),
        ('coherent-backend-gate-promotion',promote,'negative engineering archive promoted scientific scope'),
        ('coherent-truncated-original-prefix',truncated_prefix,'retained original sample cutoff hash/event count differs'),
        ('coherent-original-stream-pass-erasure',changed_original_pass,'original first-sample PASS was changed'),
        ('coherent-source-map-omission',source_omission,'original passport and frozen source closure population differ'),
        ('coherent-old-refusal-replacement',old_refusal,'immutable old P4 refusal summary differs')]
    records=[]
    for index,(name,mutation,predicate) in enumerate(cases,1):
        copy=FIXTURES/('%02d-'%index+name);shutil.copytree(PRIMARY,copy)
        positive=verify_packet(copy);before=table(copy)
        mutation(copy);after=table(copy)
        need(not typed_equal(before,after),'adversarial control is a no-op')
        try:
            verify_packet(copy)
            raise AssertionError('coherent adversarial packet unexpectedly accepted')
        except ValueError as error:
            need(predicate in str(error),'control refused for wrong predicate: '+str(error))
            records.append(dict(control=name,baselineAccepted=True,mutationNonNoOp=True,
                expectedPredicate=predicate,actualError=str(error),status='REJECTED_EXPECTED_PREDICATE',
                fixture=str(copy),mutatedManifestSha256=file_sha(copy/'packet-manifest.json')))
        print(json.dumps(dict(control=index,name=name,status=records[-1]['status'])),flush=True)
    need(table(PRIMARY)==primary,'immutable original packet changed during controls')
    result=dict(schema='aijade.ch7.e3-post-terminal-packet-controls.v1',status='NINE_ADVERSARIAL_POST_TERMINAL_CONTROLS_PASS',
        checkedAt=datetime.now(timezone.utc).isoformat(),controls=records,discovered=9,passed=9,failed=0,
        actualPrimaryPacket=str(PRIMARY),actualPrimaryManifestSha256=baseline['manifestSha256'],
        originalPrimaryUnchanged=True,independentColdNegativeAuditUnmodified=True,
        controlSourceSha256=file_sha(Path(__file__)),verifierSourceSha256=file_sha(T/'verify_e3_packet.py'),
        commonSourceSha256=file_sha(T/'packet_common.py'),
        scope='Copied post-terminal archive integrity/semantics controls; no new live observation or scientific qualification.',
        backendQualified=False,independentHumanReview=False)
    output=T/'packet-controls-01.json';new(output,encoded(result));print(json.dumps(dict(status=result['status'],path=str(output),sha256=file_sha(output)),indent=2))


if __name__=='__main__':main()
