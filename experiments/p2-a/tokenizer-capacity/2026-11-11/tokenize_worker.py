"""Tokenize one fixed model's complete prompt corpus in two independent engines."""
import argparse
from collections import Counter
import hashlib,json,os,resource,struct,subprocess,time
from pathlib import Path

from gguf_metadata import read_metadata
from independent_bpe import IndependentBpe


def sha(data):return hashlib.sha256(data).hexdigest()
def packed(ids):return struct.pack('<'+str(len(ids))+'i',*ids)
def file_state(path):
    s=path.stat();return {'inode':s.st_ino,'size':s.st_size,'mtimeNs':s.st_mtime_ns}


class Native:
    def __init__(self,executable,model,out):
        self.stderr=(out/'native.stderr.log').open('wb')
        self.archive=(out/'native-token-ids.bin').open('wb')
        self.child=subprocess.Popen([str(executable),str(model)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr)
        assert self.read(8)==b'P2TOK01\0'
        fields=struct.unpack('<5I',self.read(20));version=self.read(self.u32()).decode()
        self.info={'vocabSize':fields[0],'bosId':fields[1],'eosId':fields[2],'addBos':bool(fields[3]),'addEos':bool(fields[4]),'libraryVersion':version}
    def read(self,size):
        value=bytearray()
        while len(value)<size:
            block=self.child.stdout.read(size-len(value))
            if not block:raise ValueError('Native tokenizer ended before the complete record')
            value.extend(block)
        result=bytes(value);self.archive.write(result);return result
    def u32(self):return struct.unpack('<I',self.read(4))[0]
    def encode(self,text):
        raw=text.encode();assert len(raw)<=1048576
        self.child.stdin.write(struct.pack('<I',len(raw)));self.child.stdin.write(raw);self.child.stdin.flush()
        results=[]
        for _ in range(2):
            count=self.u32();assert count<=1048576
            ids=list(struct.unpack('<'+str(count)+'i',self.read(count*4)))
            decoded=self.read(self.u32()).decode('utf-8')
            results.append((ids,decoded))
        self.archive.flush();return results
    def close(self):
        self.child.stdin.close();code=self.child.wait(timeout=20)
        self.archive.close();self.stderr.close()
        assert code==0,code


def run(config,corpus,executable,out):
    os.environ['TOKENIZERS_PARALLELISM']='false'
    cfg=json.loads(config.read_text());model=Path(cfg['modelBlobPath'])
    assert file_state(model)==cfg['modelFileState']
    metadata=read_metadata(model)
    if 'ggufMetadataSha256' in cfg:assert metadata['metadataSha256']==cfg['ggufMetadataSha256']
    independent=IndependentBpe(metadata)
    out.mkdir(parents=True,exist_ok=False)
    native=None;started=time.monotonic();cpu=time.process_time()
    summary={'schema':'aijade.p2a.token-capacity.worker.v1','model':cfg['model'],'rows':0,'counts':{},'newCompletionCalls':0,
             'modelBlobSha256':cfg['modelBlobSha256'],'ggufMetadataSha256':metadata['metadataSha256'],
             'corpusSha256':sha(corpus.read_bytes()),'driverSha256':sha(Path(__file__).read_bytes()),
             'nativeExecutableSha256':sha(executable.read_bytes()),'tokenizersVersion':__import__('tokenizers').__version__,
             'nativeInfo':None,'modelFileStateBefore':file_state(model)}
    try:
        native=Native(executable,model,out);summary['nativeInfo']=native.info
        assert native.info['vocabSize']==len(independent.pieces)
        assert native.info['addBos']==independent.add_bos and native.info['addEos']==independent.add_eos
        assert native.info['bosId']==independent.bos and native.info['eosId']==independent.eos
        counts=Counter()
        with corpus.open(encoding='utf-8') as inputs,(out/'measurements.jsonl').open('w',encoding='utf-8') as output,(out/'independent-token-ids.bin').open('wb') as ids_output:
            for line in inputs:
                row=json.loads(line);measurements={};row_pass=True
                assert sha(row['rawPrompt'].encode())==row['rawSha256']
                assert sha(row['chatPrompt'].encode())==row['chatSha256']
                for prefix,text in [('raw',row['rawPrompt']),('chat',row['chatPrompt'])]:
                    received=native.encode(text)
                    for special,(actual_ids,actual_text) in zip([False,True],received):
                        reference_ids=independent.encode(text,special);reference_text=independent.decode(reference_ids)
                        expected=text
                        if special and independent.add_bos:expected=independent.pieces[independent.bos]+expected
                        if special and independent.add_eos:expected+=independent.pieces[independent.eos]
                        same=actual_ids==reference_ids
                        decoded_ok=actual_text==expected and reference_text==expected
                        name=prefix+('WithSpecial' if special else 'NoSpecial')
                        data=packed(reference_ids);ids_output.write(struct.pack('<I',len(reference_ids)));ids_output.write(data)
                        measurements[name]={'count':len(actual_ids),'independentCount':len(reference_ids),
                            'nativeTokenSha256':sha(packed(actual_ids)),'independentTokenSha256':sha(data),'idsAgree':same,
                            'decodedSha256':sha(actual_text.encode()),'independentDecodedSha256':sha(reference_text.encode()),
                            'expectedDecodedSha256':sha(expected.encode()),'roundtripAgree':decoded_ok}
                        if not same:
                            first=next((i for i,(a,b) in enumerate(zip(actual_ids,reference_ids)) if a!=b),min(len(actual_ids),len(reference_ids)))
                            measurements[name]['firstMismatch']={'index':first,'native':actual_ids[max(first-2,0):first+4],'independent':reference_ids[max(first-2,0):first+4]}
                        row_pass=row_pass and same and decoded_ok
                result={key:row[key] for key in ['id','taskId','promptKind','rawSha256','chatSha256','templateSha256','systemSha256']}
                result.update(model=cfg['model'],measurements=measurements,status='PASS' if row_pass else 'MISMATCH')
                output.write(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n');output.flush();ids_output.flush()
                summary['rows']+=1;counts[result['status']]+=1;summary['counts']=dict(counts)
                (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        native.close();native=None
        summary['modelFileStateAfter']=file_state(model);assert summary['modelFileStateAfter']==cfg['modelFileState']
        usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        summary.update(wallSeconds=time.monotonic()-started,pythonCpuSeconds=time.process_time()-cpu,childCpuSeconds=usage.ru_utime+usage.ru_stime,
                       status='PASS' if summary['counts']=={'PASS':summary['rows']} else 'MISMATCH')
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    finally:
        if native is not None:
            if native.child.poll() is None:native.child.kill();native.child.wait()
            native.archive.close();native.stderr.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--model-config',type=Path,required=True);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--native',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    run(a.model_config.resolve(),a.corpus.resolve(),a.native.resolve(),a.out.resolve())
