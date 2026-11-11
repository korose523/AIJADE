from pathlib import Path
import hashlib,json,os,signal,socket,subprocess,time,urllib.request

CACHE=Path(__file__).resolve().parent;MODELS=Path('/Volumes/Untitled/ollama_models_mac')
base='http://127.0.0.1:11454'
try:
 with socket.create_connection(('127.0.0.1',11454),timeout=1):raise RuntimeError('Private port already owned; refuse to reuse or stop it')
except ConnectionRefusedError:pass

def call(path,data=None):
 body=json.dumps(data).encode() if data is not None else None
 request=urllib.request.Request(base+path,data=body,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
 return h.hexdigest()

out=CACHE/'model-snapshot';out.mkdir(exist_ok=False)
env=os.environ.copy();env.update(OLLAMA_HOST='127.0.0.1:11454',OLLAMA_MODELS=str(MODELS),OLLAMA_NO_CLOUD='1',OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_KEEP_ALIVE='0')
with (out/'service.log').open('wb') as log:
 server=subprocess.Popen(['/Applications/Ollama.app/Contents/Resources/ollama','serve'],stdout=log,stderr=log,env=env,start_new_session=True)
 try:
  version=None;start=time.monotonic()
  while time.monotonic()-start<30:
   if server.poll() is not None:raise RuntimeError('Owned metadata service exited')
   try:version=call('/api/version');break
   except (OSError,ValueError):time.sleep(.2)
  assert version is not None
  before=call('/api/ps');assert not before.get('models')
  inventory=[]
  for short,name,tag in [('qwen','qwen2.5-coder','7b-instruct'),('llama','llama3.1','8b')]:
   manifest_path=MODELS/'manifests/registry.ollama.ai/library'/name/tag
   raw=manifest_path.read_bytes();manifest=json.loads(raw)
   folder=out/short;folder.mkdir();(folder/'manifest.json').write_bytes(raw)
   show=call('/api/show',{'model':name+':'+tag,'verbose':False});(folder/'show.json').write_text(json.dumps(show,ensure_ascii=False,indent=2)+'\n')
   config=MODELS/'blobs'/manifest['config']['digest'].replace(':','-')
   assert sha(config)==manifest['config']['digest'].split(':')[1]
   (folder/'config.json').write_bytes(config.read_bytes())
   item={'id':short,'model':name+':'+tag,'manifestSha256':hashlib.sha256(raw).hexdigest(),'configSha256':sha(config),'layers':[],'effectiveTemplateSha256':hashlib.sha256(show['template'].encode()).hexdigest(),'effectiveSystemSha256':hashlib.sha256(show.get('system','').encode()).hexdigest()}
   for layer in manifest['layers']:
    blob=MODELS/'blobs'/layer['digest'].replace(':','-');kind=layer['mediaType'].split('.')[-1]
    if kind=='model':
     stat_before=blob.stat();actual=sha(blob);stat_after=blob.stat()
     assert actual==layer['digest'].split(':')[1]
     assert (stat_before.st_ino,stat_before.st_size,stat_before.st_mtime_ns)==(stat_after.st_ino,stat_after.st_size,stat_after.st_mtime_ns)
     item.update(modelBlobSha256=actual,modelBlobPath=str(blob),modelFileState={'inode':stat_after.st_ino,'size':stat_after.st_size,'mtimeNs':stat_after.st_mtime_ns})
    elif kind in ['template','system','params','license']:
     actual=sha(blob);assert actual==layer['digest'].split(':')[1]
     (folder/('layer-'+kind+'.txt')).write_bytes(blob.read_bytes())
    else:actual=sha(blob);assert actual==layer['digest'].split(':')[1]
    item['layers'].append({**layer,'sha256Verified':actual})
   assert (folder/'layer-template.txt').read_text()==show['template']
   assert not (folder/'layer-system.txt').exists() or (folder/'layer-system.txt').read_text()==show.get('system','')
   (folder/'template.txt').write_text(show['template']);(folder/'system.txt').write_text(show.get('system',''))
   inventory.append(item);print(short,'manifest, full GGUF and effective template verified',flush=True)
  after=call('/api/ps');assert not after.get('models')
  report={'version':version,'privatePort':11454,'loadedBefore':before,'loadedAfter':after,'models':inventory,'newCompletionCalls':0,'requests':['GET /api/version','GET /api/ps','POST /api/show x2','GET /api/ps']}
  (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 finally:
  if server.poll() is None:
   os.killpg(server.pid,signal.SIGTERM)
   try:server.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(server.pid,signal.SIGKILL);server.wait()
  (out/'termination.json').write_text(json.dumps({'ownedPid':server.pid,'exitCode':server.returncode,'stopped':server.poll() is not None},indent=2)+'\n')
