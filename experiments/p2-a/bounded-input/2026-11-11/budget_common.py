"""Exact local templates and vocabulary-only tokenization shared by preparation and guard."""
from pathlib import Path
import hashlib,json,os,struct,subprocess,sys

os.environ['TOKENIZERS_PARALLELISM']='false'
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
TOKENIZER=ROOT/'experiments/p2-a/tokenizer-capacity/2026-11-11'
sys.path.insert(0,str(TOKENIZER))
from gguf_metadata import read_metadata
from independent_bpe import IndependentBpe
from prepare_inputs import expected_chat

def sha(data):return hashlib.sha256(data).hexdigest()
def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()
def load(path):return json.loads(Path(path).read_text())
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def state(path):
    s=Path(path).stat();return {'inode':s.st_ino,'size':s.st_size,'mtimeNs':s.st_mtime_ns}

class Renderer:
    def __init__(self,executable,template,system,model):
        self.model=model;self.system=Path(system).read_bytes().decode();self.id=0
        self.child=subprocess.Popen([str(executable),str(template),str(system)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr)
    def render(self,text):
        self.id+=1;identity=str(self.id)
        raw=json.dumps({'id':identity,'content':text},ensure_ascii=False,separators=(',',':')).encode()+b'\n'
        assert len(raw)<=8*1024**2,'bounded renderer transport'
        self.child.stdin.write(raw);self.child.stdin.flush()
        line=self.child.stdout.readline(8*1024**2+1)
        assert line.endswith(b'\n') and len(line)<=8*1024**2,'missing or oversized renderer response'
        value=json.loads(line);assert value['id']==identity
        result=value['prompt'];assert result==expected_chat(self.model,self.system,text),'template implementations differ'
        return result
    def close(self):
        if self.child.poll() is None:
            self.child.stdin.close()
            try:self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait()
        assert self.child.returncode==0,'renderer failed'

class Native:
    def __init__(self,executable,model):
        self.child=subprocess.Popen([str(executable),str(model)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr)
        try:
            assert self.read(8)==b'P2TOK02\0'
            fields=struct.unpack('<5I',self.read(20));version=self.read(self.u32()).decode()
            self.info={'vocabSize':fields[0],'bosId':fields[1],'eosId':fields[2],'addBos':bool(fields[3]),'addEos':bool(fields[4]),'libraryVersion':version}
        except BaseException:
            if self.child.poll() is None:self.child.kill();self.child.wait()
            raise
    def read(self,n):
        assert 0<=n<=8*1024**2,'bounded native frame'
        result=bytearray()
        while len(result)<n:
            part=self.child.stdout.read(n-len(result))
            if not part:raise ValueError('Native tokenizer ended before a complete response')
            result.extend(part)
        return bytes(result)
    def u32(self):return struct.unpack('<I',self.read(4))[0]
    def encode(self,text):
        raw=text.encode();assert len(raw)<=1048576,'prompt transport exceeds 1 MiB'
        self.child.stdin.write(struct.pack('<I',len(raw))+raw);self.child.stdin.flush();result=[]
        for _ in range(2):
            count=self.u32();assert count<=1048576
            raw_ids=self.read(count*4);decoded=self.read(self.u32())
            result.append((raw_ids,decoded,count))
        return result
    def close(self):
        if self.child.poll() is None:
            self.child.stdin.close()
            try:self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait()
        assert self.child.returncode==0,'native tokenizer failed'

class Runtime:
    def __init__(self,config,native=False):
        self.path=Path(config);self.cfg=load(config);cfg=self.cfg
        assert cfg['schema']=='aijade.p2a.token-counter.config.v1'
        for path,expected in cfg['sourceSha256'].items():assert file_sha(path)==expected,('changed tokenizer source',path)
        for key in ['native','library','renderer','template','system']:
            assert file_sha(cfg[key]['path'])==cfg[key]['sha256'],('changed runtime input',key)
        import tokenizers
        assert tokenizers.__version__==cfg['tokenizersVersion']=='0.22.1'
        extensions={p.name:file_sha(p) for p in Path(tokenizers.__file__).parent.glob('*.so')}
        assert extensions==cfg['tokenizersExtensionSha256'],'changed independent tokenizer extension'
        self.model=cfg['modelConfig'];self.model_path=Path(self.model['modelBlobPath'])
        assert state(self.model_path)==self.model['modelFileState'],'changed model file identity; rehash before a new plan'
        metadata=read_metadata(self.model_path)
        assert metadata['metadataSha256']==self.model['ggufMetadataSha256']
        self.independent=IndependentBpe(metadata)
        self.renderer=Renderer(cfg['renderer']['path'],cfg['template']['path'],cfg['system']['path'],self.model['id'])
        self.native=None
        if native:
            try:
                self.native=Native(cfg['native']['path'],self.model_path)
                expected={'vocabSize':len(self.independent.pieces),'bosId':self.independent.bos,'eosId':self.independent.eos,
                          'addBos':self.independent.add_bos,'addEos':self.independent.add_eos,'libraryVersion':'0.7.0-dev'}
                assert self.native.info==expected
            except BaseException:
                if self.native is not None:self.native.close()
                self.renderer.close();raise
    def predict(self,text):
        chat=self.renderer.render(text)
        return {'rawNoSpecial':len(self.independent.encode(text,False)),
                'chatWithSpecial':len(self.independent.encode(chat,True))},chat
    def count(self,text):
        assert self.native is not None
        chat=self.renderer.render(text);views={}
        for prefix,value in [('raw',text),('chat',chat)]:
            actual=self.native.encode(value)
            for special,(raw_ids,decoded,count) in zip([False,True],actual):
                ids=self.independent.encode(value,special);packed=struct.pack('<'+str(len(ids))+'i',*ids)
                expected=value
                if special and self.independent.add_bos:expected=self.independent.pieces[self.independent.bos]+expected
                if special and self.independent.add_eos:expected+=self.independent.pieces[self.independent.eos]
                assert raw_ids==packed and count==len(ids),'independent IDs differ'
                assert decoded==expected.encode() and self.independent.decode(ids)==expected,'byte reconstruction differs'
                views[prefix+('WithSpecial' if special else 'NoSpecial')]={'count':count,'tokenIdsSha256':sha(raw_ids),'decodedSha256':sha(decoded)}
        value=views['chatWithSpecial']
        return {'inputTokens':value['count'],'rawSha256':sha(text.encode()),'chatSha256':sha(chat.encode()),
                'tokenIdsSha256':value['tokenIdsSha256'],'crossEngineAgreement':True,'views':views}
    def close(self):
        try:
            if self.native is not None:self.native.close()
        finally:
            self.renderer.close()
            assert state(self.model_path)==self.model['modelFileState'],'model file changed during counter use'
