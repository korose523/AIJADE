"""Fourteen copied-baseline adversarial controls; never change original evidence."""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import gzip
import hashlib
import json
import shutil

from packet_common import read,decode,encoded,new,sha,file_sha,need,typed_equal,verify_packet,logical_table,logical_body,codec_module

B=Path('/Volumes/Untitled/AIJADE');C=B/'.research/runs/ch7-owned-state-20261118'
PRIMARY=C/'audit/engineering-03-packet';T=C/'archive-tools'
FIXTURES=T/'packet-controls-01-fixtures'


def table(root):
    return {p.relative_to(root).as_posix():dict(sha256=file_sha(p),bytes=p.stat().st_size)
            for p in sorted(root.rglob('*')) if p.is_file()}


def mapping(root):return logical_table(root)


def body(root,name):return logical_body(root,mapping(root)[name])


def save_manifest(root,manifest):
    (root/'packet-manifest.json').write_bytes(encoded(manifest))


def put(root,name,raw):
    need(FIXTURES in root.parents,'only copied controls may be mutated')
    manifest=read(root/'packet-manifest.json');entry=next(v for v in manifest['logicalFiles'] if v['logicalPath']==name)
    if entry['kind']=='direct':
        (root/entry['packetPath']).write_bytes(raw)
    else:
        directory=(root/entry['envelopePath']).parent
        shutil.rmtree(directory)
        source=FIXTURES/(root.name+'-rewrite-input.bin');source.write_bytes(raw)
        result=codec_module().encode_file(source,directory,name)
        entry['envelopeSha256']=result['envelopeSha256']
    entry.update(logicalSha256=sha(raw),logicalSizeBytes=len(raw));save_manifest(root,manifest)


def put_json(root,name,value):put(root,name,encoded(value))


def coherence(root):
    """Rebind copied physical/logical envelopes and all metadata anchors."""
    manifest=read(root/'packet-manifest.json');entries={r['logicalPath']:r for r in manifest['logicalFiles']}
    prefix='run/engineering-03/'
    run={name[len(prefix):]:dict(sha256=r['logicalSha256'],bytes=r['logicalSizeBytes'])
         for name,r in entries.items() if name.startswith(prefix)}
    directory=decode(body(root,'metadata/run-directory-state.json'));directory['files']=run
    directory['emptyFiles']=sorted(k for k,v in run.items() if v['bytes']==0)
    put_json(root,'metadata/run-directory-state.json',directory)
    audit=decode(body(root,'audit/independent-audit.json'));audit['inputFiles']=run
    if 'originalDirectoryState' in audit:audit['originalDirectoryState']=directory
    put_json(root,'audit/independent-audit.json',audit)
    disposition=decode(body(root,'audit/root-disposition.json'));disposition['independentAuditSha256']=sha(body(root,'audit/independent-audit.json'))
    put_json(root,'audit/root-disposition.json',disposition)
    summary=decode(body(root,'summary.json'));summary['independentAuditSha256']=sha(body(root,'audit/independent-audit.json'))
    summary['rootDispositionSha256']=sha(body(root,'audit/root-disposition.json'));put_json(root,'summary.json',summary)
    source_map=decode(body(root,'metadata/source-map.json'));entries=mapping(root)
    for item in source_map['originalSources']:
        row=entries[item['logicalPacketPath']];item['originalSha256']=row['logicalSha256'];item['originalSizeBytes']=row['logicalSizeBytes']
        if row['kind']!='direct':item['transportEnvelopeSha256']=row['envelopeSha256']
    put_json(root,'metadata/source-map.json',source_map)
    manifest=read(root/'packet-manifest.json');manifest['independentAuditSha256']=summary['independentAuditSha256'];manifest['rootDispositionSha256']=summary['rootDispositionSha256']
    manifest['files']=[dict(path=p.relative_to(root).as_posix(),sha256=file_sha(p),sizeBytes=p.stat().st_size)
                       for p in sorted(root.rglob('*')) if p.is_file() and p.name!='packet-manifest.json']
    save_manifest(root,manifest)


def coherent_numbers(root,key,value):
    for name in ('summary.json','audit/independent-audit.json','audit/root-disposition.json'):
        record=decode(body(root,name));record['numbers'][key]=value;put_json(root,name,record)


def missing(root):
    row=mapping(root)['run/engineering-03/admission/telemetry.jsonl'];directory=(root/row['envelopePath']).parent;(directory/'member-000000.gz').unlink()


def corrupt(root):
    row=mapping(root)['run/engineering-03/preflight-continuity.json'];p=(root/row['envelopePath']).parent/'member-000000.gz';p.write_bytes(p.read_bytes()+b' ')


def number(root):coherent_numbers(root,'fullServiceSeconds',1.5);coherence(root)
def boolean(root):coherent_numbers(root,'modelRequests',False);coherence(root)


def promote(root):
    for name in ('summary.json','audit/independent-audit.json','audit/root-disposition.json'):
        value=decode(body(root,name));value['scope']['backendQualified']=True;put_json(root,name,value)
    coherence(root)


def truncated_prefix(root):
    name='run/engineering-03/settling/telemetry.jsonl';rows=[decode(v) for v in body(root,name).splitlines()]
    view=rows[-1]['processObservation']['lifecycle'];view['journalBytes']-=1
    view['journalSha256']=sha(body(root,'run/engineering-03/lifecycle-journal.jsonl')[:view['journalBytes']])
    put(root,name,b''.join(json.dumps(row,allow_nan=False).encode()+b'\n' for row in rows))
    coherent_numbers(root,'originalSampleJournalCutoffBytes',view['journalBytes']);coherence(root)


def changed_original_pass(root):
    name='run/engineering-03/settling/telemetry.jsonl';rows=[decode(v) for v in body(root,name).splitlines()]
    rows[0]['streamValidationStatus']='FAIL';rows[0]['processObservation']['status']='FAIL'
    put(root,name,b''.join(json.dumps(row,allow_nan=False).encode()+b'\n' for row in rows))
    coherent_numbers(root,'settlingRawGuardColdPass',172);coherent_numbers(root,'settlingOriginalStreamValidationPass',172);coherence(root)


def missing_initializer(root):
    row=mapping(root)['run/engineering-03/initialization.json'];((root/row['envelopePath']).parent/'member-000000.gz').unlink()


def omitted_first_compare(root):
    name='run/engineering-03/receipt.json';value=decode(body(root,name))
    value['outerCursor']['fullPrefixComparedBytes']-=value['initialization']['prefixBytes']
    put_json(root,name,value);coherence(root)


def replaced_e4(root):
    name='history/e4-refusal-summary.json';value=decode(body(root,name));value['status']='FALSELY_SUPERSEDED_BY_E4'
    put_json(root,name,value);coherence(root)


def source_omission(root):
    name='experiments/ch7/newowned_guard_cursor.py';physical='source/'+name
    (root/physical).unlink()
    proofs=decode(body(root,'metadata/frozen-source-proofs.json'))
    proofs['sourceFiles'].pop(name);proofs['sources']=[r for r in proofs['sources'] if r['path']!=name]
    put_json(root,'metadata/frozen-source-proofs.json',proofs)
    manifest=read(root/'packet-manifest.json');manifest['files']=[r for r in manifest['files'] if r['path']!=physical];manifest['logicalFiles']=[r for r in manifest['logicalFiles'] if r['logicalPath']!=physical]
    (root/'packet-manifest.json').write_bytes(encoded(manifest));coherence(root)


def old_refusal(root):
    name='history/p4-refusal-summary.json';value=decode(body(root,name));value['status']='FALSELY_REPLACED_BY_LATER_PASS'
    put_json(root,name,value);coherence(root)


def promote_unknown_to_pass(root):
    name='run/engineering-03/settling/telemetry.jsonl';rows=[decode(v) for v in body(root,name).splitlines()]
    row=rows[-1];row['streamValidationStatus']='PASS';row.pop('streamValidationError',None);row['rssBytes']=0
    row['processObservation'].update(status='PASS',blockers=[],ownedRssBytes=0)
    put(root,name,b''.join(json.dumps(v,allow_nan=False).encode()+b'\n' for v in rows))
    coherent_numbers(root,'settlingRawGuardColdPass',174);coherent_numbers(root,'settlingRawGuardColdUnknown',0)
    coherent_numbers(root,'settlingOriginalStreamValidationPass',174);coherent_numbers(root,'settlingOriginalStreamValidationRefused',0)
    coherence(root)


def impute_unknown_rss_zero(root):
    name='run/engineering-03/settling/telemetry.jsonl';rows=[decode(v) for v in body(root,name).splitlines()]
    rows[-1]['rssBytes']=0;rows[-1]['processObservation']['ownedRssBytes']=0
    put(root,name,b''.join(json.dumps(v,allow_nan=False).encode()+b'\n' for v in rows))
    coherent_numbers(root,'originalLastOwnedRssBytes',0);coherence(root)


def main(*,fixtures=None,output=None,packet=None):
    global FIXTURES,PRIMARY
    if fixtures is not None:FIXTURES=Path(fixtures).resolve()
    if packet is not None:PRIMARY=Path(packet).resolve()
    need(not FIXTURES.exists(),'never overwrite actual copied-control history')
    primary=table(PRIMARY);baseline=verify_packet(PRIMARY);FIXTURES.mkdir()
    cases=[('missing-original-empty-admission',missing,'exact physical packet file population differs'),
        ('corrupt-physical-original',corrupt,'physical packet hash/size differs'),
        ('coherent-service-number-promotion',number,'coherently changed E5 negative numbers'),
        ('coherent-bool-zero-substitution',boolean,'coherently changed E5 negative numbers'),
        ('coherent-backend-gate-promotion',promote,'engineering packet promoted scientific scope'),
        ('coherent-truncated-original-prefix',truncated_prefix,'retained E5 actual cutoff/init reference differs'),
        ('coherent-original-stream-pass-erasure',changed_original_pass,'retained original first173 E5 raw/stream PASS was modified'),
        ('coherent-source-map-omission',source_omission,'complete frozen source population differs'),
        ('coherent-old-refusal-replacement',old_refusal,'immutable old refusal history differs: history/p4-refusal-summary.json'),
        ('missing-original-initializer',missing_initializer,'exact physical packet file population differs'),
        ('coherent-first-bootstrap-compare-omission',omitted_first_compare,'retained E5 actual per-owner prefix/read/compare/tail/eval/canonical counter population differs'),
        ('coherent-e4-refusal-replacement',replaced_e4,'immutable old refusal history differs: history/e4-refusal-summary.json'),
        ('coherent-final-unknown-promotion-to-pass',promote_unknown_to_pass,'retained final E5 raw UNKNOWN/stream refusal/None RSS was modified'),
        ('coherent-unknown-rss-imputation-to-zero',impute_unknown_rss_zero,'retained final E5 raw UNKNOWN/stream refusal/None RSS was modified')]
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
    result=dict(schema='aijade.ch7.e5-post-terminal-packet-controls.v1',status='FOURTEEN_ADVERSARIAL_POST_TERMINAL_CONTROLS_PASS',
        checkedAt=datetime.now(timezone.utc).isoformat(),controls=records,discovered=14,passed=14,failed=0,
        actualPrimaryPacket=str(PRIMARY),actualPrimaryManifestSha256=baseline['manifestSha256'],
        originalPrimaryUnchanged=True,independentColdNegativeAuditUnmodified=True,
        controlSourceSha256=file_sha(Path(__file__)),verifierSourceSha256=file_sha(T/'verify_e5_packet.py'),
        commonSourceSha256=file_sha(T/'packet_common.py'),
        scope='Copied post-terminal archive integrity/semantics controls; no new live observation or scientific qualification.',
        backendQualified=False,independentHumanReview=False)
    output=T/'packet-controls-01.json' if output is None else Path(output).resolve()
    new(output,encoded(result));print(json.dumps(dict(status=result['status'],path=str(output),sha256=file_sha(output)),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet');parser.add_argument('--fixtures');parser.add_argument('--output')
    args=parser.parse_args();main(fixtures=args.fixtures,output=args.output,packet=args.packet)
