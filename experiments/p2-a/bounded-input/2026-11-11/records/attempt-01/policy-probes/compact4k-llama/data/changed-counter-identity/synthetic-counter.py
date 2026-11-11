import hashlib,json,sys
from pathlib import Path
config=Path(sys.argv[sys.argv.index('--config')+1]);data=json.loads(config.read_text());model=data['modelConfig']
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
print(json.dumps({'schema':'aijade.p2a.token-counter.ready.v1','configSha256':sha(config),'scriptSha256':sha(__file__),
    'modelManifestSha256':model['manifestSha256'],'templateSha256':'0'*64 if 'identity'=='identity' else model['effectiveTemplateSha256'],
    'systemSha256':model['effectiveSystemSha256']}),flush=True)
line=sys.stdin.readline()
if line:
    request=json.loads(line)
    print(json.dumps({'schema':'aijade.p2a.token-counter.count.v1','id':request['id'],'inputTokens':'malformed'}),flush=True)