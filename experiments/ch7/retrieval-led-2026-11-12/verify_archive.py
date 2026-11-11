#!/usr/bin/env python3
"""Verify every archived byte, both attempts, controls and actual retrieval-led chronology."""
from pathlib import Path
import gzip
import hashlib
import json
import sys
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parent
repo=next(p for p in root.parents if (p/'src/Aijade.Research').is_dir())
sys.path.insert(0,str(repo/'experiments/ch7'))
from audit_retrieval_led import verify, verify_control, load, raw, lines, require
from test_retrieval_rejections import run

def audit():
    listing=json.loads((root/'manifest.json').read_text())
    known=set()
    for row in listing['files']:
        rel=row['path'];p=root/rel
        require(rel not in known and not Path(rel).is_absolute() and '..' not in Path(rel).parts,'unsafe manifest path')
        known.add(rel);data=p.read_bytes()
        require(not p.is_symlink() and len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],'manifest bytes/hash: '+rel)
    require(known=={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'manifest.json'},'unlisted archive file')
    for row in load(root,'logical-files.json'):
        data=gzip.decompress((root/row['path']).read_bytes())
        require(len(data)==row['uncompressedBytes'] and hashlib.sha256(data).hexdigest()==row['uncompressedSha256'],'logical file hash')
    failed=root/'attempts/development-01';r=load(failed,'receipt.json')
    require(r['status']=='STOPPED' and r['completedCases']==0 and r['modelRequests']==0 and r['inFlightCaseIds']==['H'] and len(r['unattemptedCaseIds'])==9,'failed attempt accounting')
    require('42601: cannot insert multiple commands into a prepared statement' in raw(failed,'flow.log').decode(),'failed initialization diagnosis')
    require(not (failed/'renderer-request.json').exists() and not (failed/'renderer-ready.json').exists() and not (failed/'client').exists(),'unexpected failed-attempt renderer')
    require(all(j['phase'] in ['batch.begin','database.disposed'] for j in lines(failed,'journal.jsonl')),'failed attempt reached candidate path')
    cleanup=load(failed,'database-cleanup.json');require(len(cleanup)==1 and cleanup[0]['remaining']==0,'failed attempt owned database not cleaned')
    x=ET.fromstring(raw(failed,'flow.xml'));require(any(a.attrib.get('failed')=='1' for a in x.iter('assembly')),'failed XML absent')
    result=verify(root/'attempts/development-02',repo)
    verify_control(load(root,'engineering/route-control-corrected.json'),load(root,'selection.json'))
    rejection=run(root/'attempts/development-02',repo)
    result.update(manifestFiles=len(known),retainedFailedAttempts=1,routingControlConditions=3,rejectedCorruptions=rejection['rejectedControls'])
    return result

if __name__=='__main__':print(json.dumps(audit(),indent=2))
