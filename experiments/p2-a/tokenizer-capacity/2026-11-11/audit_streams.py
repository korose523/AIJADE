"""Independently join recorded inputs, complete token streams and per-view ledgers."""
from pathlib import Path
from itertools import zip_longest
import gzip,hashlib,json,lzma,struct

VIEWS=['rawNoSpecial','rawWithSpecial','chatNoSpecial','chatWithSpecial']

def opened(path,binary=True):
    path=Path(path)
    if not path.exists() and path.suffix=='.gz' and path.with_suffix('.xz').exists():path=path.with_suffix('.xz')
    if not path.exists():
        for extension in ['.xz','.gz']:
            if Path(str(path)+extension).exists():path=Path(str(path)+extension);break
    mode='rb' if binary else 'rt'
    if path.suffix=='.xz':return lzma.open(path,mode)
    if path.suffix=='.gz':return gzip.open(path,mode)
    return path.open(mode)

def records(path):
    with opened(path,False) as stream:
        for line in stream:yield json.loads(line)

def sha(value):return hashlib.sha256(value).hexdigest()

class Reader:
    def __init__(self,path):self.file=opened(path);self.hash=hashlib.sha256();self.size=0
    def read(self,n):
        assert 0<=n<=8*1024**2,('unbounded frame',n)
        data=self.file.read(n);assert len(data)==n,('incomplete frame',self.size,n,len(data))
        self.hash.update(data);self.size+=len(data);return data
    def u32(self):return struct.unpack('<I',self.read(4))[0]
    def end(self):assert self.file.read(1)==b'';self.file.close();return self.size,self.hash.hexdigest()

def header(native,info,protocol):
    assert native.read(8)==protocol
    values=struct.unpack('<5I',native.read(20))
    assert list(values)==[info[k] for k in ['vocabSize','bosId','eosId','addBos','addEos']]
    assert native.read(native.u32()).decode()==info['libraryVersion']

def validate_ids(native_ids,independent_ids,item):
    assert native_ids==independent_ids,'independent token sequence differs'
    assert len(native_ids)%4==0
    assert len(native_ids)//4==item['count']==item['independentCount']
    assert sha(native_ids)==item['nativeTokenSha256']==item['independentTokenSha256']
    assert item['idsAgree'] is True

def check_population(source,measurements,expected_rows,template,system):
    assert len(source)==len(measurements)==expected_rows,'missing planned row'
    assert len({r['id'] for r in source})==expected_rows,'duplicate source row'
    assert len({r['id'] for r in measurements})==expected_rows,'duplicate measurement row'
    assert {r['id'] for r in source}=={r['id'] for r in measurements},'population mismatch'
    for row in source+measurements:
        assert row['templateSha256']==template,'changed model template'
        assert row['systemSha256']==system,'changed model system'

def audit(data,corpus,expected_rows,model,protocol=b'P2TOK02\0'):
    summary=json.loads((data/'summary.json').read_text());assert summary['status']=='PASS'
    cfg=json.loads((Path(corpus).parent/'model-config.json').read_text())
    inputs=list(records(corpus));measurements=list(records(data/'measurements.jsonl'))
    check_population(inputs,measurements,expected_rows,cfg['effectiveTemplateSha256'],cfg['effectiveSystemSha256'])
    native=Reader(data/'native-token-ids.bin.gz');independent=Reader(data/'independent-token-ids.bin.gz')
    # Transcoded xz filenames replace the terminal gzip suffix, without altering bytes.
    header(native,summary['nativeInfo'],protocol)
    ids_seen=set();views=0;maximum=0
    for source,record in zip_longest(inputs,measurements):
        assert source is not None and record is not None,'missing source or measurement row'
        assert source['id']==record['id'] and source['id'] not in ids_seen
        ids_seen.add(source['id']);assert record['status']=='PASS'
        for field in ['taskId','promptKind','rawSha256','chatSha256','templateSha256','systemSha256']:assert source[field]==record[field],field
        assert sha(source['rawPrompt'].encode())==source['rawSha256']
        assert sha(source['chatPrompt'].encode())==source['chatSha256']
        for name in VIEWS:
            item=record['measurements'][name]
            actual=native.read(native.u32()*4);other=independent.read(independent.u32()*4)
            validate_ids(actual,other,item)
            decoded=native.read(native.u32());expected=source['rawPrompt' if name.startswith('raw') else 'chatPrompt']
            if name.endswith('WithSpecial') and summary['nativeInfo']['addBos']:
                assert model=='llama';expected='<|begin_of_text|>'+expected
            assert not summary['nativeInfo']['addEos']
            assert decoded==expected.encode(),'native byte-piece roundtrip'
            assert sha(decoded)==item['decodedSha256']==item['independentDecodedSha256']==item['expectedDecodedSha256']
            assert item['roundtripAgree'] is True
            maximum=max(maximum,len(actual)//4);views+=1
    assert len(ids_seen)==expected_rows==summary['rows']
    logical=summary['losslessStreams']
    assert native.end()==(logical['nativeLogicalBytes'],logical['nativeLogicalSha256'])
    assert independent.end()==(logical['independentLogicalBytes'],logical['independentLogicalSha256'])
    return {'rows':len(ids_seen),'views':views,'maximumTokens':maximum,'tokenIdAgreement':True,'rawByteRoundtrip':True,'logicalStreamHashes':True}

def negative_checks():
    raw=struct.pack('<2i',1,2)
    item={'count':2,'independentCount':2,'nativeTokenSha256':sha(raw),'independentTokenSha256':sha(raw),'idsAgree':True}
    validate_ids(raw,raw,item)
    rejected=[]
    for name,a,b,value in [('changed-token',struct.pack('<2i',1,3),raw,item),('changed-count',raw,raw,{**item,'count':3}),('changed-hash',raw,raw,{**item,'nativeTokenSha256':'0'*64})]:
        try:validate_ids(a,b,value)
        except AssertionError:rejected.append(name)
        else:raise AssertionError('negative control was accepted: '+name)
    base={'id':'x','templateSha256':'T','systemSha256':'S'}
    check_population([base],[base],1,'T','S')
    for name,source,rows in [('missing-row',[],[base]),('changed-template',[{**base,'templateSha256':'bad'}],[base]),('changed-system',[base],[{**base,'systemSha256':'bad'}])]:
        try:check_population(source,rows,1,'T','S')
        except AssertionError:rejected.append(name)
        else:raise AssertionError('negative control was accepted: '+name)
    return rejected

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(__doc__);p.add_argument('--stage',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    result={model:audit(a.stage/'complete'/model/'data',a.inputs/model/'complete.jsonl',2110,model) for model in ['qwen','llama']}
    result['negativeChecks']=negative_checks();a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
