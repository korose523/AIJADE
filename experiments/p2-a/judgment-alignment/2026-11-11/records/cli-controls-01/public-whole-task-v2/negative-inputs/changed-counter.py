"""Bounded JSONL exact-token counter; vocabulary-only, no networking or inference context."""
import argparse,json,sys
from pathlib import Path
from budget_common import Runtime,file_sha

def run(config):
    runtime=None
    try:
        runtime=Runtime(config,native=True)
        model=runtime.model
        ready={'schema':'aijade.p2a.token-counter.ready.v1','configSha256':file_sha(config),'scriptSha256':file_sha(__file__),
               'modelManifestSha256':model['manifestSha256'],'templateSha256':model['effectiveTemplateSha256'],'systemSha256':model['effectiveSystemSha256'],
               'nativeInfo':runtime.native.info,'nativeExecutableSha256':runtime.cfg['native']['sha256'],'librarySha256':runtime.cfg['library']['sha256'],
               'ggufMetadataSha256':model['ggufMetadataSha256'],'tokenizersExtensionSha256':runtime.cfg['tokenizersExtensionSha256'],
               'pythonVersion':sys.version,'pythonPrefix':sys.prefix,'pid':__import__('os').getpid()}
        print(json.dumps(ready,separators=(',',':')),flush=True)
        while True:
            line=sys.stdin.buffer.readline(8*1024**2+1)
            if not line:break
            assert line.endswith(b'\n') and len(line)<=8*1024**2,'bounded JSONL input exceeded'
            request=json.loads(line);assert set(request)=={'id','prompt'} and type(request['id']) is int and isinstance(request['prompt'],str)
            result=runtime.count(request['prompt'])
            print(json.dumps({'schema':'aijade.p2a.token-counter.count.v1','id':request['id'],**result},separators=(',',':')),flush=True)
    finally:
        if runtime is not None:runtime.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--config',type=Path,required=True);a=p.parse_args();run(a.config)

