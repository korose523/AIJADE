#!/usr/bin/env python3
"""Prepare only missing native query-entity vectors under the pre-pushed coverage amendment."""
import argparse
import array
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import urllib.request

from external_policies import Replay

DIGEST='0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f'
AMENDMENT='2b1bf563c945618aa1ef8a85efbf642e265fd374'


def request(path, body=None):
    raw=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request('http://127.0.0.1:11434'+path,raw,{'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=600) as response:
        text=response.read().decode();return response.status,text,json.loads(text)


def main(args):
    from mem0 import Memory
    from mem0.utils.entity_extraction import extract_entities
    args.out.mkdir(parents=True,exist_ok=False)
    original=Replay(args.source)
    corpus=json.loads(args.corpus.read_text())
    mapping=[];wanted=set()
    normalizer=Memory.__new__(Memory)
    for c,conv in enumerate(corpus):
        for q,item in enumerate(conv['questions']):
            selected=[];seen=set()
            for kind,text in extract_entities(item['question'])[:8]:
                key=normalizer._normalize_entity_text(text)
                if key and key not in seen:
                    seen.add(key);selected.append({'type':kind,'text':text.strip()});wanted.add(text.strip())
            mapping.append({'c':c,'q':q,'entities':selected})
    missing=sorted(wanted-original.vectors.keys())
    _,_,tags=request('/api/tags');_,_,version=request('/api/version')
    model=next(x for x in tags['models'] if x['name'].split(':')[0]=='nomic-embed-text')
    assert model['digest']==DIGEST
    (args.out/'coverage.json').write_text(json.dumps({'amendment':AMENDMENT,'sourceSha256':original.source_sha,
        'questions':len(mapping),'uniqueEntityInputs':len(wanted),'reusedOriginalInputs':len(wanted)-len(missing),
        'missingInputsFixedBeforeEmbedding':missing,'queryEntityMap':mapping,'model':model,'runtime':version},ensure_ascii=False,indent=2)+'\n')
    vectors={};calls=0
    with gzip.open(args.out/'entity-requests.jsonl.gz','xt',encoding='utf-8') as journal:
        for i in range(0,len(missing),64):
            batch=missing[i:i+64];payload={'model':'nomic-embed-text','input':batch}
            status,raw,response=request('/api/embed',payload)
            journal.write(json.dumps({'time':dt.datetime.now(dt.timezone.utc).isoformat(),'status':status,'input':payload,'response':raw},ensure_ascii=False)+'\n');journal.flush()
            assert status==200 and len(response['embeddings'])==len(batch)
            for text,embedding in zip(batch,response['embeddings']):
                vector=array.array('f',embedding)
                assert len(vector)==768 and all(math.isfinite(v) for v in vector)
                vectors[text]=list(vector)
            calls+=1;print('entity batch',calls,'inputs',len(vectors),flush=True)
    assert set(vectors)==set(missing)
    result={'schema':'aijade.p3.policy.entity-supplement.v1','amendment':AMENDMENT,'modelDigest':DIGEST,
            'originalSourceSha256':original.source_sha,'newEmbeddingHttpRequests':calls,'newEmbeddingInputs':len(vectors),
            'newChatModelCalls':0,'vectors':vectors,'scope':'Only auxiliary native query entities; original turn/question vectors unchanged.'}
    with gzip.open(args.out/'supplement.json.gz','xt',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,allow_nan=False)
    print(json.dumps({k:v for k,v in result.items() if k!='vectors'}))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--corpus',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    main(p.parse_args())
