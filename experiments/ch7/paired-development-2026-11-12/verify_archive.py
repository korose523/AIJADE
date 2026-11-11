#!/usr/bin/env python3
"""Verify all archive bytes and independently reconstruct paired raw outcomes and scoring."""
from pathlib import Path
import gzip
import hashlib
import json
import sys
import io
import unittest
root=Path(__file__).resolve().parent
repo=next(p for p in root.parents if (p/'src/Aijade.Research').is_dir())
sys.path.insert(0,str(repo/'experiments/ch7'))
from audit_paired_development import verify
from audit_retrieval_led import load,raw
from audit_retrieval_suffix import require
from test_paired_rejections import run
def audit():
    listing=load(root,'manifest.json');known=set()
    for row in listing['files']:
        rel=row['path'];p=root/rel
        require(rel not in known and not Path(rel).is_absolute() and '..' not in Path(rel).parts,'unsafe manifest path')
        known.add(rel);data=p.read_bytes()
        require(not p.is_symlink() and len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],'manifest bytes/hash: '+rel)
    require(known=={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'manifest.json'},'unlisted archive file')
    for row in load(root,'logical-files.json'):
        data=gzip.decompress((root/row['path']).read_bytes())
        require(len(data)==row['uncompressedBytes'] and hashlib.sha256(data).hexdigest()==row['uncompressedSha256'],'logical raw file hash')
    first=raw(root,'engineering/full-tests.log').decode();repeat=raw(root,'engineering/full-tests-repeat.log').decode()
    require('通过:   654' in first and '失败:     1' in first,'original local regression failure missing')
    require('通过:   655' in repeat and '失败:     0' in repeat,'unchanged-default regression repeat absent')
    require(load(root,'engineering/regression-diagnostic.json')['rootCauseEstablished'] is False,'unestablished timeout cause relabeled')
    preservation=load(root,'engineering/primary-preservation-before-audit-fix.json')
    omitted={row['path']:row['sha256'] for row in load(root,'additional-local-files.json')}
    for rel,expected in preservation.items():
        if rel in omitted:require(omitted[rel]==expected,'local-only preserved hash changed')
        else:require(hashlib.sha256(raw(root/'attempts/development-01',rel)).hexdigest()==expected,'primary bytes changed after audit correction')
    from test_proposal_dto_conversion import DiagnosticProposalConversionTests
    tests=unittest.defaultTestLoader.loadTestsFromTestCase(DiagnosticProposalConversionTests)
    report=unittest.TextTestRunner(stream=io.StringIO()).run(tests)
    require(report.wasSuccessful() and report.testsRun==4,'diagnostic conversion controls')
    result=verify(root/'attempts/development-01',repo)
    negative=run(root/'attempts/development-01',repo)
    result.update(manifestFiles=len(known),rejectedCorruptions=negative['rejectedControls'],retainedLocalDefaultRegressionFailures=1,diagnosticConversionControls=4,primaryMeasurementRerun=False)
    return result
if __name__=='__main__':print(json.dumps(audit(),indent=2))
