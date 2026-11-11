"""Model-free, read-only reconstruction of the complete bounded-input archive."""
from pathlib import Path
import hashlib,json,sys
from audit_bounded import audit,load,file_sha,logical_sha
HERE=Path(__file__).resolve().parent

def verify(root=HERE):
 receipt=load(root/'results/receipt.json')
 for rel,expected in receipt['artifactSha256'].items():
  path=root/rel
  assert path.is_file() and file_sha(path)==expected,('changed bounded-input payload',rel)
 index=load(root/'records/transcode-index.json')
 assert len(index)==len({r['source'] for r in index})==len({r['archive'] for r in index})
 for row in index:
  path=root/'records'/row['archive']
  assert path.stat().st_size==row['archiveBytes'] and file_sha(path)==row['archiveSha256']
  assert logical_sha(path)==row['logical']['sha256']
 rejected=root/'records/attempt-01';cap=root/'records/attempt-02';accepted=root/'records/attempt-04'
 assert load(rejected/'summary.json')['status']=='FAIL' and load(cap/'summary.json')['status']=='FAIL'
 assert load(cap/'legacy-export/process.json')['exitCode']==-6
 third=root/'records/attempt-03';third_summary=load(third/'summary.json');assert third_summary['status']=='FAIL'
 assert all(v['status']=='PASS' for k,v in third_summary['results'].items() if k.startswith('policy-probe/'))
 assert load(root/'records/development-heap768-qwen/process.json')['exitCode']==-6
 assert logical_sha(cap/'legacy-export/stderr.log')==hashlib.sha256(b'Out of memory.\n').hexdigest()
 assert load(accepted/'execution.json')['executionCodeCommit']==receipt['executionCodeCommit']
 correction=[]
 for model in ['qwen','llama']:
  first=load(rejected/'complete'/model/'data/summary.json');current=load(accepted/'complete'/model/'data/summary.json')
  assert first['status']==current['status']=='PASS' and first['rows']==current['rows']==8581
  assert first['losslessStreams']==current['losslessStreams'],'token IDs/bytes changed across resource/receipt correction'
  correction.append(model)
 for scenario in ['compact4k','compact8k']:
  assert file_sha(rejected/'selection'/scenario/'exposure.json')==file_sha(accepted/'selection'/scenario/'exposure.json')
 assert logical_sha(rejected/'selection/raw-prompts.jsonl')==logical_sha(accepted/'selection/raw-prompts.jsonl')
 actual=audit(accepted);recorded=load(root/'results/summary.json');assert actual==recorded,'changed complete aggregate'
 return dict(status='PASS',artifactFiles=len(receipt['artifactSha256']),losslessRecords=len(index),
  tasks=actual['tasks'],fullOracleCases=actual['fullOracleCases'],modelProfileRows=actual['modelProfileRows'],
  profileTokenViews=actual['profileTokenViews'],selectionQueryViews=actual['selectionQueryViews'],policyProbes=actual['policyProbes'],
  exactBoundaryPairs=actual['exactBoundaryPairs'],mockSteps=actual['mockSteps'],replayedPrefixSteps=actual['replayedPrefixSteps'],
  negativeEvidenceChecks=actual['negativeEvidenceChecks'],completeSelectionAndCapacityRecomputed=True,
  unchangedCompleteTokenStreamsAcrossCorrection=correction,failedAttemptsRetained=3,developmentHeapProbeRetained=True,
  executionCodeCommit=receipt['executionCodeCommit'],newModelCompletionCalls=0,
  scope='Recorded tokenizer/capacity and synthetic transport evidence; not model reliability, author acceptance or live device qualification.')

if __name__=='__main__':
 try:print(json.dumps(verify(),indent=2))
 except (AssertionError,KeyError,ValueError,OSError) as error:
  print('BOUNDED ARCHIVE REJECTED:',repr(error),file=sys.stderr);raise SystemExit(1)
