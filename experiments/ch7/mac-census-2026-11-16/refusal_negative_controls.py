#!/usr/bin/env python3
"""Coherently rebind disposable copies of a valid refusal; never mutate its raw."""
from pathlib import Path
import argparse,base64,gzip,hashlib,json,shutil,sys,tempfile,types
sys.dont_write_bytecode=True
C=Path('/Volumes/Untitled/AIJADE/.research/runs/ch7-mac-census-20261116');BASE=Path('/Volumes/Untitled/AIJADE')
SCRIPT=Path(__file__).with_name('audit.py');m=types.ModuleType('mac_bulk_refusal');m.__file__=str(SCRIPT)
AUDITOR_BYTES=SCRIPT.read_bytes();CONTROL_BYTES=Path(__file__).read_bytes()
exec(compile(AUDITOR_BYTES,str(SCRIPT),'exec'),m.__dict__)

def write(root,name,value):
    raw=(json.dumps(value,indent=2)+'\n').encode();(root/name).write_bytes(raw)
def raw_lines(root,name):return m.lines(root,name)
def write_lines(root,name,rows):
    raw=b''.join((json.dumps(row)+'\n').encode() for row in rows)
    (root/(name+'.gz')).write_bytes(gzip.compress(raw,compresslevel=9,mtime=0))
def seal(root):
    files=[]
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.name=='packet-manifest.json':continue
        raw=path.read_bytes();row=dict(path=path.relative_to(root).as_posix(),sha256=m.sha(raw),sizeBytes=len(raw))
        if path.suffix=='.gz':
            logical=gzip.decompress(raw);row.update(logicalSha256=m.sha(logical),logicalSizeBytes=len(logical))
        files.append(row)
    write(root,'packet-manifest.json',dict(schema=m.MANIFEST_SCHEMA,files=files))
def receipt_rebind(root,value):
    write(root,'qualification/receipt.json',value);digest=m.sha((root/'qualification/receipt.json').read_bytes())
    for name in ['audit/controller-exit.json','audit/all-owned-exit.json']:
        proof=m.load(root,name);proof['receiptSha256']=digest;write(root,name,proof)
    (root/'publication/controller.log.gz').write_bytes(gzip.compress((json.dumps(value)+'\n').encode(),compresslevel=9,mtime=0))

def mutation(name,root):
    if name=='claimed-final-fail-to-pass':
        rows=raw_lines(root,'qualification/process-observations.jsonl');o=rows[-2]['processObservation'];o['status']='PASS';o['blockers']=[];o['ownedRssBytes']=0;rows[-2]['rssBytes']=0;write_lines(root,'qualification/process-observations.jsonl',rows)
    elif name=='unknown-to-unattempted':
        value=m.load(root,'qualification/receipt.json');value['unattemptedCaseIds']=value['unknownCaseIds'];value['unknownCaseIds']=[];receipt_rebind(root,value)
    elif name=='drop-runtime-failure-and-error':
        rows=raw_lines(root,'qualification/process-observations.jsonl');write_lines(root,'qualification/process-observations.jsonl',rows[:-2]);value=m.load(root,'qualification/receipt.json');value['processObservationCount']=7;value['processObservationErrors']=[];receipt_rebind(root,value)
    elif name=='drop-settling-sample':
        rows=raw_lines(root,'qualification/settling/telemetry.jsonl');write_lines(root,'qualification/settling/telemetry.jsonl',rows[:-1]);value=m.load(root,'qualification/settling/receipt.json');value['samples']=299;value['coverage']['samples']=299;write(root,'qualification/settling/receipt.json',value)
    elif name=='forge-continuous-phase-transition':
        settle=m.load(root,'qualification/settling/receipt.json');value=m.load(root,'qualification/admission/receipt.json');delta=settle['phaseClock']['endMonotonic']+2-value['phaseClock']['startMonotonic']
        value['phaseClock']['startMonotonic']+=delta;value['phaseClock']['endMonotonic']+=delta;write(root,'qualification/admission/receipt.json',value)
        rows=raw_lines(root,'qualification/admission/telemetry.jsonl')
        for row in rows:
            row['monotonicSeconds']+=delta;row['observationCompletedMonotonic']+=delta
            row['processObservation']['startedMonotonic']+=delta;row['processObservation']['finishedMonotonic']+=delta
        write_lines(root,'qualification/admission/telemetry.jsonl',rows)
    elif name=='substitute-q-observer':
        path=root/'source/experiments/ch7/mac_process_guard_v2.py';path.write_bytes(path.read_bytes()+b'\n# substitution\n')
    elif name=='substitute-b-native-metadata':
        value=m.load(root,'metadata/native-build.json');value['sha256']='f'*64;write(root,'metadata/native-build.json',value)
    elif name=='corrupt-final-native-raw':
        rows=raw_lines(root,'qualification/process-observations.jsonl');native=rows[-2]['processObservation']['evidence']['after']['processGraph']['nativeCensus'];raw=base64.b64decode(native['stdoutBase64']);value=json.loads(raw);value['recordCount']+=1;raw=json.dumps(value,separators=(',',':')).encode();native.update(stdoutBase64=base64.b64encode(raw).decode(),stdoutBytes=len(raw),stdoutSha256=m.sha(raw));write_lines(root,'qualification/process-observations.jsonl',rows)
    elif name=='hide-block-output':
        path=root/'qualification/block-1/cases.json';path.parent.mkdir();path.write_text('[]\n')
    elif name=='forge-api-empty-from-nonempty':
        rows=raw_lines(root,'qualification/admission/telemetry.jsonl');api=rows[0]['processObservation']['evidence']['api'];raw=b'{"models":[{}]}';api.update(emptyBodyBase64=base64.b64encode(raw).decode(),bodySha256=m.sha(raw),bytes=len(raw));write_lines(root,'qualification/admission/telemetry.jsonl',rows)
    elif name=='controller-still-present':
        value=m.load(root,'audit/controller-exit.json');value['processes'][0]['status']='ORIGINAL_IDENTITY_STILL_PRESENT';value['allAttemptControllersAbsent']=False;write(root,'audit/controller-exit.json',value)
    elif name=='hide-unused-first-build-failures':
        path=next((root/'engineering/build-attempt-01-external-artifact-root/default-regression').glob('*21_26_35*.trx.gz'));path.unlink()
    elif name=='alter-one-old-fact':
        value=m.load(root,'metadata/facts-baseline.json');first=next(iter(value));value[first]='changed';write(root,'metadata/facts-baseline.json',value)
    elif name=='unknown-runtime-rss-to-zero':
        rows=raw_lines(root,'qualification/process-observations.jsonl');rows[-2]['rssBytes']=0;rows[-2]['processObservation']['ownedRssBytes']=0;write_lines(root,'qualification/process-observations.jsonl',rows)
    elif name=='wrong-manifest-schema':return
    else:raise AssertionError(name)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=C/'staging/packet')
    parser.add_argument('--repo',type=Path,default=C/'worktree')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--temp-root',type=Path)
    args=parser.parse_args();baseline=args.root.resolve();repo=args.repo.resolve()
    output=(args.output or baseline.parent/'refusal-negative-controls.json').resolve()
    m.need(not output.is_relative_to(baseline),'control report must remain outside packet; avoid manifest self-cycle')
    temp=(args.temp_root or baseline.parent/'.runtime/refusal-audit-controls').resolve()
    m.need(not temp.is_relative_to(baseline),'disposable controls must remain outside packet')
    accepted=m.verify(baseline,repo)
    need=lambda ok:None if ok else (_ for _ in ()).throw(AssertionError('control accepted or no-op'))
    names=['claimed-final-fail-to-pass','unknown-to-unattempted','drop-runtime-failure-and-error','drop-settling-sample','forge-continuous-phase-transition',
           'substitute-q-observer','substitute-b-native-metadata','corrupt-final-native-raw','hide-block-output','forge-api-empty-from-nonempty',
           'controller-still-present','hide-unused-first-build-failures','alter-one-old-fact','unknown-runtime-rss-to-zero','wrong-manifest-schema']
    outcomes=[];temp.mkdir(parents=True,exist_ok=True)
    for name in names:
        with tempfile.TemporaryDirectory(prefix='mac-bulk-refusal-control-',dir=temp) as directory:
            root=Path(directory)/'packet';shutil.copytree(baseline,root);before=(root/'packet-manifest.json').read_bytes();mutation(name,root);seal(root)
            if name=='wrong-manifest-schema':
                manifest=json.loads((root/'packet-manifest.json').read_bytes());manifest['schema']='aijade.ch7.wrong.v1';write(root,'packet-manifest.json',manifest)
            need((root/'packet-manifest.json').read_bytes()!=before)
            if name!='wrong-manifest-schema':m.verify_manifest(root)
            try:m.verify(root,repo)
            except (ValueError,OSError,KeyError,TypeError) as error:
                outcomes.append(dict(name=name,coherentManifestRebound=True,semanticRejected=True,reason=type(error).__name__+': '+str(error)));print(name+': REJECTED',flush=True)
            else:raise AssertionError('Mutation accepted: '+name)
    result=dict(schema='aijade.ch7.mac-bulk-refusal-controls.v1',status='VALID_BASELINE_AND_ALL_15_COHERENT_NEGATIVE_CONTROLS_PASS',baselineManifestSha256=m.sha((baseline/'packet-manifest.json').read_bytes()),baselinePayloadFiles=m.verify_manifest(baseline),baselineAuditStatus=accepted['status'],baselineCoreSha256=m.sha((baseline/'audit/independent-refusal-audit.json').read_bytes()),
                auditorSha256=m.sha(AUDITOR_BYTES),controlsSourceSha256=m.sha(CONTROL_BYTES),controls=outcomes,total=len(outcomes),rejected=len(outcomes),acceptedMutations=0,noOpMutations=0,actualQualificationWindows=0,networkRequests=0)
    m.need(SCRIPT.read_bytes()==AUDITOR_BYTES and Path(__file__).read_bytes()==CONTROL_BYTES,'audit/control source changed during controls')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result['status'],'controls':len(outcomes),'output':str(output)}))

if __name__=='__main__':main()
