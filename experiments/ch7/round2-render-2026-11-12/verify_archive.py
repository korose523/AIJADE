#!/usr/bin/env python3
"""Verify archived bytes, independent raw reconstruction and disposable controls."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
P=Path(__file__).resolve().parent
R=P.parents[2]
sys.path.insert(0,str(R/'experiments/ch7'))
from audit_round2_render import verify
from test_round2_render_rejections import run as reject

def sha(data):return hashlib.sha256(data).hexdigest()

def main():
    m=json.loads((P/'manifest.json').read_text())
    expected={r['path'] for r in m['files']}|{'manifest.json'}
    actual={str(p.relative_to(P)) for p in P.rglob('*') if p.is_file()}
    assert actual==expected,'Incomplete/extra archive file list'
    for row in m['files']:
        p=P/row['path'];data=p.read_bytes()
        assert len(data)==row['bytes'] and sha(data)==row['sha256'],row['path']
    for row in json.loads((P/'logical-files.json').read_text()):
        data=gzip.decompress((P/row['path']).read_bytes())
        assert len(data)==row['uncompressedBytes'] and sha(data)==row['uncompressedSha256']
    for rel,h in m['instrumentSourceHashes'].items():
        assert sha((R/rel).read_bytes())==h,rel
    frozen=json.loads((P/'engineering/frozen-build.json').read_text())
    ident=json.loads((P/'attempts/development-01/input-identities.json').read_text())
    assert frozen['commit']==ident['codeCommit']==ident['assemblyInfo']['embeddedGitRevision']
    assert frozen['binaries']==ident['binaries']
    assert frozen['assemblyInfoText']==ident['assemblyInfo']['text']
    result=verify(P/'attempts/development-01',R)
    assert result==json.loads((P/'full-raw-audit.json').read_text()),'Changed complete raw reconstruction'
    controls=reject(P/'attempts/development-01',R)
    assert controls==json.loads((P/'rejections.json').read_text()),'Changed corruption checks'
    summary=json.loads((P/'data-summary.json').read_text())
    assert summary['conditionCounts']==result['conditionCounts'] and summary['byCase']==result['byCase']
    assert summary['baseIntegrityCounts']==result['baseIntegrityCounts']
    assert summary['heldOutComparisonComplete'] is False and summary['formalHardwareQualification'] is False
    return dict(status='MECHANICAL_SECOND_ROUND_OBSERVATION_AUDIT_PASS',packetFiles=len(expected),
                knownConditionTrajectories=20,cleanBuildEmbeddedSource=frozen['commit'],
                conditionCounts=result['conditionCounts'],rejectedCorruptions=controls['rejectedCorruptions'],
                heldOutCases=0,modelRequests=0,formalHardwareQualification=False,
                scope=result['semanticScope'])

if __name__=='__main__':print(json.dumps(main(),indent=2))
