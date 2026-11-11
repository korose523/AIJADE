"""Copy only the two frozen cached manifests/layers locally, with full byte verification."""
import argparse,datetime,hashlib,json,os,plistlib,shutil,subprocess,time
from pathlib import Path

FIXED={
 'registry.ollama.ai/library/qwen2.5-coder/7b-instruct':'dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364',
 'registry.ollama.ai/library/llama3.1/8b':'3fc95d284915704cf140b825abf5150af0d32fde95f55c081c9602d49d4547c0'}
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def state(p):
 s=p.stat();return dict(inode=s.st_ino,size=s.st_size,mtimeNs=s.st_mtime_ns)
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as stream:
  for block in iter(lambda:stream.read(2*1024**2),b''):h.update(block)
 return h.hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def main(a):
 root=next(p for p in Path(__file__).resolve().parents if (p/'src/Aijade.Research').is_dir())
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip(),'Freeze staging code first'
 assert not a.destination.exists() and not a.out.exists(),'Use new staging and receipt directories'
 assert a.destination==Path('/Users/mac/.cache/aijade-p2-judgment-models-20261111')
 assert a.source==Path('/Volumes/Untitled/ollama_models_mac')
 files={};manifests={}
 for name,expected in FIXED.items():
  path=a.source/'manifests'/name;raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==expected
  manifest=json.loads(raw);manifests['manifests/'+name]=dict(sha256=expected,size=len(raw))
  for layer in [manifest['config'],*manifest['layers']]:
   algorithm,identity=layer['digest'].split(':');assert algorithm=='sha256' and len(identity)==64
   key='blobs/sha256-'+identity;value=dict(sha256=identity,size=layer['size'])
   assert key not in files or files[key]==value;files[key]=value
 files.update(manifests);required=sum(v['size'] for v in files.values());free=shutil.disk_usage(a.destination.parent).free
 assert free>=required+10*1024**3
 disk=plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist','/System/Volumes/Data']))
 assert disk.get('FilesystemType')=='apfs'
 a.out.mkdir(parents=True);a.destination.mkdir();start=time.monotonic();receipt=dict(schema='aijade.p2.local-model-staging.v1',status='RUNNING',startedAt=now(),
  executionCodeCommit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),driverSha256=digest(Path(__file__)),
  storageAmendmentCommit=subprocess.check_output(['git','log','--diff-filter=A','--format=%H','--','experiments/plans/2026-11-11-p2-calibration-local-storage.md'],cwd=root,text=True).strip(),
  source=str(a.source),destination=str(a.destination),destinationFilesystem='apfs',freeBytesBefore=free,requiredBytes=required,modelCompletionCalls=0,files=[])
 write(a.out/'receipt.json',receipt)
 try:
  for name,expected in files.items():
   source=a.source/name;target=a.destination/name;target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_name(target.name+'.copying')
   before=state(source);assert before['size']==expected['size'];h=hashlib.sha256();copied=0;began=time.monotonic()
   with source.open('rb') as src,temporary.open('xb') as dst:
    for block in iter(lambda:src.read(2*1024**2),b''):dst.write(block);h.update(block);copied+=len(block)
    dst.flush();os.fsync(dst.fileno())
   assert copied==expected['size'] and h.hexdigest()==expected['sha256'] and state(source)==before
   assert digest(temporary)==expected['sha256'];temporary.replace(target)
   receipt['files'].append(dict(path=name,**expected,sourceStateBefore=before,sourceStateAfter=state(source),copiedSha256=digest(target),
    targetState=state(target),wallSeconds=time.monotonic()-began));write(a.out/'receipt.json',receipt)
   print(name,copied,'bytes verified',flush=True)
  assert len(receipt['files'])==len(files)
  receipt.update(status='PASS',endedAt=now(),wallSeconds=time.monotonic()-start,totalFiles=len(files),copiedBytes=sum(r['size'] for r in receipt['files']))
 except Exception as error:
  receipt.update(status='FAIL',endedAt=now(),wallSeconds=time.monotonic()-start,error=type(error).__name__+': '+str(error));raise
 finally:write(a.out/'receipt.json',receipt)
 return 0
if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__)
 for key in ['source','destination','out']:p.add_argument('--'+key,type=Path,required=True)
 raise SystemExit(main(p.parse_args()))
