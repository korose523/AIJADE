#!/usr/bin/env python3
"""Verify complete archived history trajectories without a model or database service."""
import gzip,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
P=Path(__file__).resolve().parent
R=P.parents[2]
sys.path.insert(0,str(P))
from audit import audit,load
from analyze import summarize
from integrity import verify_hashes
def sha(p):return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
def main():
    manifest=load(P/'manifest.json');verify_hashes(P,manifest)
    frozen=load(P/'engineering/frozen-build.json')
    for relative,digest in frozen['sources'].items():assert sha(R/relative)==digest,relative
    assert sha(R/'experiments/plans/2026-11-12-p3-history-question-recording.md')==frozen['planSha256']
    for item in load(P/'logical-files.json'):
        with gzip.open(P/item['path'],'rb') as stream:
            h=hashlib.sha256();n=0
            while chunk:=stream.read(1024*1024):h.update(chunk);n+=len(chunk)
        assert n==item['logicalBytes'] and h.hexdigest()==item['logicalSha256'],item['path']
    rows,receipt=audit(P/'attempt-01',P/'input-frame.json.gz',P/'eligibility-oracle.json.gz')
    assert receipt==load(P/'analysis/audit.json'),'raw-audit-changed'
    expected=[json.loads(x) for x in gzip.decompress((P/'analysis/metrics.jsonl.gz').read_bytes()).splitlines()]
    assert rows==expected,'full-derived-row-reconstruction'
    summary=summarize(rows);assert summary==load(P/'analysis/summary.json'),'analysis-changed'
    with tempfile.TemporaryDirectory(prefix='aijade-history-ci-') as tmp:
        out=Path(tmp)/'rejections.json'
        subprocess.run([sys.executable,str(P/'test_rejections_v2.py'),'--root',str(P/'attempt-01'),'--frame',str(P/'input-frame.json.gz'),
          '--oracle',str(P/'eligibility-oracle.json.gz'),'--out',str(out)],check=True,capture_output=True,text=True)
        assert load(out)==load(P/'analysis/rejections.json'),'corruption-controls-changed'
        agg=Path(tmp)/'aggregation.json'
        subprocess.run([sys.executable,str(P/'check_aggregation.py'),'--metrics',str(P/'analysis/metrics.jsonl.gz'),
          '--summary',str(P/'analysis/summary.json'),'--out',str(agg)],check=True,capture_output=True,text=True)
        assert load(agg)==load(P/'analysis/aggregation-check.json'),'aggregation-check-changed'
        extra=Path(tmp)/'extra.json'
        subprocess.run([sys.executable,str(P/'extra_controls.py'),'--root',str(P/'attempt-01'),'--frame',str(P/'input-frame.json.gz'),
          '--oracle',str(P/'eligibility-oracle.json.gz'),'--out',str(extra)],check=True,capture_output=True,text=True)
        assert load(extra)==load(P/'engineering/extra-rejections.json'),'structural-controls-changed'
    return dict(status='FULL_CONTROLLED_HISTORY_ARCHIVE_VERIFIED',rows=len(rows),trajectories=50,
      files=len(manifest['files'])+1,bytes=sum(x['bytes'] for x in manifest['files'].values()),
      executionCommit=frozen['commit'],newModelCalls=0,formalHardwareQualification=False,independentHumanReview=False,
      scope='Complete configured script and offline raw reconstruction; no answer-quality, natural-dialogue or complete Web/QQ qualification.')
if __name__=='__main__':print(json.dumps(main(),indent=2))
