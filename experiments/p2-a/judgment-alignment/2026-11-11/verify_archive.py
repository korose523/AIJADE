"""Verify the complete archived preparation and both stopped calibration attempts, without model files or inference."""
from pathlib import Path
import hashlib,json
from audit_judgment import audit_preparation,audit_cli,audit_calibration,load,logical_sha,streams

HERE=Path(__file__).resolve().parent
def file_sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024**2),b''):h.update(b)
 return h.hexdigest()
def audit():
 receipt=load(HERE/'results/receipt.json')
 assert receipt['schema']=='aijade.p2.whole-task-archive.v1' and receipt['primaryExperiment'] is False
 for name,expected in receipt['artifactSha256'].items():assert file_sha(HERE/name)==expected,('changed artifact',name)
 index=load(HERE/'records/transcode-index.json');assert len({r['archive'] for r in index})==len(index)
 for row in index:
  path=HERE/'records'/row['archive'];assert file_sha(path)==row['archiveSha256'] and path.stat().st_size==row['archiveBytes']
  assert logical_sha(path)==row['logical']['sha256']
 base=HERE/'records';prep,catalogs=audit_preparation(base/'preparation-01');cli=audit_cli(base/'cli-controls-01')
 calibrations=[audit_calibration(base/name,base/'preparation-01',catalogs) for name in ['calibration-01','calibration-02']]
 assert [c['attempt']['status'] for c in calibrations]==['STOPPED','STOPPED']
 assert [c['newVerifierCompletions'] for c in calibrations]==[0,0]
 assert calibrations[0]['attempt']['reason']=='RuntimeError: REQUEST_WALL_TIMEOUT'
 assert calibrations[0]['attempt']['inFlightObservations']==1 and len(calibrations[0]['attempt']['unattemptedSlots'])==31
 assert calibrations[1]['attempt']['reason']=='RuntimeError: UNLOADED_ADMISSION_FAILED/qwen'
 assert calibrations[1]['attempt']['inFlightObservations']==0 and len(calibrations[1]['attempt']['unattemptedSlots'])==32
 assert logical_sha(base/'calibration-01/order.json')==logical_sha(base/'calibration-02/order.json')
 chats=sum(sum(row['kind']=='http-request' for row in streams.records(path))
  for name in ['calibration-01','calibration-02'] for path in (base/name/'observations').glob('*/requests.jsonl*'))
 assert chats==1
 stage=load(base/'model-staging-01/receipt.json');assert stage['status']=='PASS' and stage['destinationFilesystem']=='apfs'
 assert stage['totalFiles']==len(stage['files'])==13 and sum(v['size'] for v in stage['files'])==stage['copiedBytes']==9603843626
 expected={}
 for path in sorted((base/'staged-manifests/manifests').rglob('*')):
  if not path.is_file():continue
  manifest=load(path);relative=str(path.relative_to(base/'staged-manifests'));expected[relative]=dict(sha256=file_sha(path),size=path.stat().st_size)
  for layer in [manifest['config'],*manifest['layers']]:expected['blobs/'+layer['digest'].replace(':','-')]=dict(sha256=layer['digest'].split(':')[1],size=layer['size'])
 assert len(expected)==13
 validation=load(base/'model-staging-01/before-service-validation.json');assert validation['status']=='PASS' and len(validation['files'])==13
 for row in stage['files']:
  assert expected[row['path']]==dict(sha256=row['sha256'],size=row['size']) and row['copiedSha256']==row['sha256']
  assert row['sourceStateBefore']==row['sourceStateAfter'] and row['sourceStateBefore']['size']==row['targetState']['size']==row['size']
  before=next(v for v in validation['files'] if v['path']==row['path']);assert before['sha256']==row['sha256'] and before['state']==row['targetState']
 order=load(base/'model-staging-01/order-equality-before-requests.json');assert order['status']=='PASS' and order['all32CellsIdentical']
 assert order['orderSha256']==logical_sha(base/'calibration-01/order.json')
 model_hashes=load(base/'preparation-01/selection/builtin-listed-v1-exposure.json')['modelManifestSha256ByName']
 assert expected['manifests/registry.ollama.ai/library/qwen2.5-coder/7b-instruct']['sha256']==model_hashes['qwen2.5-coder:7b-instruct']
 assert expected['manifests/registry.ollama.ai/library/llama3.1/8b']['sha256']==model_hashes['llama3.1:8b']
 actual=dict(schema='aijade.p2.whole-task.aggregate.v1',status='PASS',auditScope='Complete recorded evidence and preparation; neither real calibration attempt completed.',
  primaryExperiment=False,planCommit=receipt['planCommit'],storageAmendmentCommit=receipt['storageAmendmentCommit'],
  preparation=prep,cli=cli,calibrations=calibrations,staging=stage,negativeTokenControls=streams.negative_checks(),
  acceptedCompleteCalibration=False,newVerifierCompletions=0,newGenerationCalls=0,attemptedChatRequests=chats)
 assert actual==load(HERE/'results/summary.json'),'Independent reconstruction differs from published summary'
 return dict(status='PASS',payloadFiles=len(index),allArtifactFiles=len(receipt['artifactSha256']),tasks=466,
  selectionQueries=prep['selectionQueries'],selectionQueryViews=prep['selectionQueryViews'],mockSteps=cli['steps'],continuedSteps=cli['replayedSteps'],identityRejections=cli['identityRejections'],
  calibrationStatus=['STOPPED','STOPPED'],newVerifierCompletions=0,acceptedCompleteCalibration=False,primaryExperiment=False)
if __name__=='__main__':print(json.dumps(audit(),indent=2))
