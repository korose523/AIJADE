"""One positive + sixteen coherently manifested E6 transport/semantic controls.

Only retained packet bytes are copied/modified.  No listener, model, native
artifact, frozen guard or historical cold oracle is executed.
"""
from pathlib import Path
import base64
import copy
import hashlib
import json
import shutil
import sys
import os
from packet_common import read,decode,encoded,sha,file_sha,need,logical_body,verify_packet,codec_module

HERE=Path(__file__).resolve().parent
PRIMARY=HERE.parent/'e6-refusal-packet-02'
OUT=Path(os.environ.get('AIJADE_E6_PACKET_CONTROL_SCRATCH','/Volumes/Untitled/AIJADE/.runtime/posix/native-e6-controls-20261118/controls-02'))
RUN='run/engineering-04/'


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class Mutation:
    def __init__(self,packet):
        self.packet=packet;self.manifest=read(packet/'packet-manifest.json')
        self.table={v['logicalPath']:v for v in self.manifest['logicalFiles']}
        self.edits={};self.removed=set();self.cache={}
    def raw(self,name):
        if name in self.edits:return self.edits[name]
        if name not in self.cache:self.cache[name]=logical_body(self.packet,self.table[name])
        return self.cache[name]
    def value(self,name):return decode(self.raw(name))
    def put(self,name,value):self.edits[name]=encoded(value)
    def last_raw(self,action):
        name=RUN+'settling/telemetry.jsonl';lines=self.raw(name).splitlines(keepends=True)
        last=decode(lines[-1]);action(last);lines[-1]=canonical(last)+b'\n';self.edits[name]=b''.join(lines)
    def receipt(self,action):
        value=self.value(RUN+'receipt.json');action(value);self.put(RUN+'receipt.json',value)
    def numbers(self,key,value):
        for name in ['summary.json','audit/independent-audit.json','audit/root-disposition.json']:
            v=self.value(name);v['numbers'][key]=value;self.put(name,v)
    def export_last(self,action):
        name='audit/retained/e6-full-cold-decisions-01.jsonl';lines=self.raw(name).splitlines(keepends=True)
        last=decode(lines[-1]);action(last);lines[-1]=canonical(last)+b'\n';self.edits[name]=b''.join(lines)
    def finish(self):
        # Keep aliases of one actual selected original source byte-identical.
        mapping=self.value('metadata/source-map.json');groups={}
        for r in mapping['originalSources']:groups.setdefault(r['originalPath'],[]).append(r['logicalPacketPath'])
        def aliases():
            for names in groups.values():
                changed=[n for n in names if n in self.edits]
                if changed:
                    raw=self.edits[changed[0]]
                    for name in names:self.edits[name]=raw
        aliases()
        run_changes={name[len(RUN):]:dict(sha256=sha(raw),bytes=len(raw))
                     for name,raw in self.edits.items() if name.startswith(RUN)}
        audit=self.value('audit/independent-audit.json')
        directory=self.value('metadata/run-directory-state.json')
        for name,value in run_changes.items():
            audit['inputFiles'][name]=value;directory['files'][name]=value
        if 'originalDirectoryState' in audit:
            for name,value in run_changes.items():audit['originalDirectoryState']['files'][name]=value
        export='audit/retained/e6-full-cold-decisions-01.jsonl'
        if export in self.edits:audit['actualAll168FullColdDecisionsSha256']=sha(self.edits[export])
        self.put('audit/independent-audit.json',audit);self.put('metadata/run-directory-state.json',directory)
        root=self.value('audit/root-disposition.json');root['independentAuditSha256']=sha(self.edits['audit/independent-audit.json'])
        self.put('audit/root-disposition.json',root)
        summary=self.value('summary.json');summary['independentAuditSha256']=sha(self.edits['audit/independent-audit.json'])
        summary['rootDispositionSha256']=sha(self.edits['audit/root-disposition.json']);self.put('summary.json',summary)
        aliases()
        for row in mapping['originalSources']:
            name=row['logicalPacketPath']
            if name in self.edits:row.update(originalSha256=sha(self.edits[name]),originalSizeBytes=len(self.edits[name]))
        self.put('metadata/source-map.json',mapping)
        for name in self.removed:
            entry=self.table[name]
            if entry['kind']=='direct':(self.packet/entry['packetPath']).unlink()
            else:shutil.rmtree((self.packet/entry['envelopePath']).parent)
            self.manifest['logicalFiles'].remove(entry)
        codec=codec_module();scratch=self.packet.parent/'mutation-inputs';scratch.mkdir()
        for index,(name,raw) in enumerate(self.edits.items()):
            entry=self.table[name]
            if entry['kind']=='direct':(self.packet/entry['packetPath']).write_bytes(raw)
            else:
                folder=(self.packet/entry['envelopePath']).parent;shutil.rmtree(folder)
                source=scratch/('%04d.json'%index);source.write_bytes(raw)
                result=codec.encode_file(source,folder,name)
                entry['envelopeSha256']=result['envelopeSha256']
            entry.update(logicalSha256=sha(raw),logicalSizeBytes=len(raw))
        self.manifest['independentAuditSha256']=sha(self.edits['audit/independent-audit.json'])
        self.manifest['rootDispositionSha256']=sha(self.edits['audit/root-disposition.json'])
        self.manifest['files']=[dict(path=p.relative_to(self.packet).as_posix(),sha256=file_sha(p),sizeBytes=p.stat().st_size)
            for p in sorted(self.packet.rglob('*')) if p.is_file() and p.name!='packet-manifest.json']
        # A history file named packet-manifest.json is part of the population.
        self.manifest['files']=[dict(path=p.relative_to(self.packet).as_posix(),sha256=file_sha(p),sizeBytes=p.stat().st_size)
            for p in sorted(self.packet.rglob('*')) if p.is_file() and p!=self.packet/'packet-manifest.json']
        (self.packet/'packet-manifest.json').write_bytes(encoded(self.manifest))


def unknown_pass(m):
    def change(row):
        row['processObservation'].update(status='PASS',blockers=[],ownedRssBytes=0)
        row.update(rssBytes=0,streamValidationStatus='PASS');row.pop('streamValidationError',None)
    m.last_raw(change)
    m.export_last(lambda row:row['actualFullTypedDecision'].update(status='PASS',blockers=[],ownedRssBytes=0))
    for key,value in [('settlingRawGuardColdPass',168),('settlingRawGuardColdUnknown',0),
                      ('settlingOriginalStreamValidationPass',168),('settlingOriginalStreamValidationRefused',0),
                      ('originalLastOwnedRssBytes',0)]:m.numbers(key,value)


def rss_zero(m):
    def change(row):row.update(rssBytes=0);row['processObservation']['ownedRssBytes']=0
    m.last_raw(change);m.numbers('originalLastOwnedRssBytes',0)


def outer168(m):
    def change(r):
        r['outerCursor']['calls']=168;r['outerCursor']['guardEvaluations']=168
    m.receipt(change);m.numbers('outerActualGuardEvaluations',168)


def wait_nonzero(m):
    raw=m.raw(RUN+'lifecycle-journal.jsonl');rows=[decode(line) for line in raw.splitlines()]
    index=max(i for i,r in enumerate(rows) if r['event']=='WAIT');rows[index]['data']['exitCode']=1;previous='0'*64
    for row in rows:
        row['previousSha256']=previous;row['sha256']=sha(canonical({k:v for k,v in row.items() if k!='sha256'}));previous=row['sha256']
    mutated=b''.join(canonical(r)+b'\n' for r in rows);m.edits[RUN+'lifecycle-journal.jsonl']=mutated
    m.receipt(lambda r:r.update(lifecycleJournalSha256=sha(mutated),lifecycleJournalBytes=len(mutated)))


def service_erasure(m):
    m.receipt(lambda r:r['preflightServices'][-1].update(fullServiceSeconds=1.999))
    m.numbers('fullServiceSeconds',1.999);m.numbers('settlingCompleteServiceClockWithinTwoSeconds',168)


def listener_clock(m):
    def change(row):
        f=row['processObservation']['evidence']['after'];f['listenerReadClock']['finishedMonotonic']=f['listenerReadClock']['startedMonotonic']+.499
    m.last_raw(change)


def native_byte(m):
    def change(row):
        capture=row['processObservation']['evidence']['after']['listener']['transcript']['stdout']
        raw=base64.b64decode(capture['dataBase64']).replace(b'127.0.0.1',b'127.0.0.2')
        capture.update(dataBase64=base64.b64encode(raw).decode(),capturedSha256=sha(raw),totalSha256=sha(raw))
    m.last_raw(change)


def native_audit_pass(m):
    value=m.value('audit/independent-audit.json');value['nativeLifecycleAudit'].update(observedTranscripts=336,unknownTranscripts=0)
    m.put('audit/independent-audit.json',value)


def frozen_audit_pass(m):
    name='audit/retained/e6-frozen-full-audit-01.attempt.json';value=m.value(name)
    value.update(actualExitCode=0,outputReceiptExists=True,completeEngineeringAccepted=True);m.put(name,value)


def null_zero(m):
    name=RUN+'preflight-continuity.json';v=m.value(name)
    v['runtimeHandoffAnchor']=0;v['phases']['settling']['elapsedSeconds']=0
    v['phases']['settling']['phaseClock']['endMonotonic']=0;m.put(name,v)
    m.receipt(lambda r:r.update(nestedEpochMonotonic=0))


def inner168(m):m.receipt(lambda r:r['innerCursor'].update(calls=168,privateStateValidations=168))


def drop_export(m):
    name='audit/retained/e6-full-cold-decisions-01.jsonl';m.edits[name]=b''.join(m.raw(name).splitlines(keepends=True)[:-1])


def drop_source(m):
    name='metadata/frozen-source-proofs.json';v=m.value(name);removed=v['sources'].pop()['path'];v['sourceFiles'].pop(removed)
    m.removed.add('source/'+removed);m.put(name,v)


CASES=[
    ('01-positive-original',None,None),
    ('02-final-unknown-promoted-pass',unknown_pass,'final E6 raw UNKNOWN'),
    ('03-none-rss-zero-filled',rss_zero,'final E6 raw UNKNOWN'),
    ('04-fictional-outer-evaluation168',outer168,'per-owner prefix'),
    ('05-coherent-wait-count-change',lambda m:m.numbers('finiteActualParentWaitZero',3201),'negative numbers'),
    ('06-canonical-nonzero-wait',wait_nonzero,'finite actual owner wait'),
    ('07-erase-complete-service-failure',service_erasure,'full-service refusal distribution'),
    ('08-clamp-native-outer-clock',listener_clock,'Native raw-byte/deadline/provenance'),
    ('09-native-captured-byte-change',native_byte,'complete typed336-transcript'),
    ('10-promote-native-independent-object',native_audit_pass,'complete typed336-transcript'),
    ('11-erase-original-complete-audit-refusal',frozen_audit_pass,'complete auditor refusal'),
    ('12-four-pending-null-values-zero-filled',null_zero,'refusal/counts/nulls'),
    ('13-bootstrap-inner-call-erased',inner168,'per-owner prefix'),
    ('14-omit-one-full-cold-export',drop_export,'all168 complete cold decisions'),
    ('15-omit-one-frozen-source',drop_source,'complete frozen source population'),
    ('16-forge-export-original-prefix-bytes',lambda m:m.export_last(lambda r:r.update(originalPrefixBytes=r['originalPrefixBytes']+1)),'exported originalPrefixBytes differs'),
    ('17-forge-export-original-prefix-hash',lambda m:m.export_last(lambda r:r.update(originalPrefixSha256='0'*64)),'exported originalPrefixSha256 differs')]


def main():
    need(not OUT.exists(),'fresh fixture namespace required')
    before=file_sha(PRIMARY/'packet-manifest.json');OUT.mkdir(parents=True);results=[]
    for name,action,wanted in CASES:
        fixture=OUT/name/'packet';fixture.parent.mkdir()
        shutil.copytree(PRIMARY,fixture)
        if action:
            mutation=Mutation(fixture);action(mutation);mutation.finish()
        transport=verify_packet(fixture,transport_only=True)
        need(transport['allPhysicalAndLogicalBodiesVerified'] is True,'coherent physical/logical transport did not pass')
        try:
            verify_packet(fixture)
            need(action is None,'semantic mutation unexpectedly accepted: '+name)
            result=dict(name=name,status='ORIGINAL_ACCEPTED',transportCoherent=True)
        except Exception as error:
            need(action is not None and wanted in str(error),'unexpected control rejection: '+name+': '+str(error))
            result=dict(name=name,status='COHERENT_SEMANTIC_MUTATION_REJECTED',transportCoherent=True,
                        errorClass=type(error).__name__,error=str(error))
        results.append(result);print(json.dumps(result),flush=True)
        (OUT/'progress.json').write_bytes(encoded(dict(completed=len(results),results=results)))
    need(before==file_sha(PRIMARY/'packet-manifest.json'),'primary packet manifest changed')
    report=dict(status='SEVENTEEN_E6_PORTABLE_PACKET_CONTROLS_PASS_NOT_NEW_KERNEL_OR_COLD_EXECUTION',
        passed=17,failed=0,positive=1,coherentlyManifestedAdverse=16,primaryManifestSha256=before,
        primaryPacketUnmodified=True,controls=results,newKernelRequests=0,newColdExecutions=0,
        historicalCodec27ControlsRerun=False)
    target=HERE/'e6-packet-controls-17.json';need(not target.exists(),'never overwrite control result')
    target.write_bytes(encoded(report));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
