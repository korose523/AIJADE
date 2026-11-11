"""Read bounded GGUF metadata for the exact locally licensed vocabulary; never load tensors."""
from pathlib import Path
import hashlib
import struct

FORMATS={0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}


def read_metadata(path):
    def number(kind):
        fmt=FORMATS[kind];size=struct.calcsize(fmt);data=stream.read(size)
        if len(data)!=size:raise ValueError('Truncated GGUF scalar')
        return struct.unpack('<'+fmt,data)[0]
    def string():
        size=number(10)
        if size>16*1024**2:raise ValueError('GGUF string limit')
        data=stream.read(size)
        if len(data)!=size:raise ValueError('Truncated GGUF string')
        return data.decode('utf-8')
    def value(kind):
        if kind==8:return string()
        if kind==9:
            item_kind=number(4);count=number(10)
            if count>1_000_000:raise ValueError('GGUF array limit')
            return [value(item_kind) for _ in range(count)]
        if kind not in FORMATS:raise ValueError('Unsupported GGUF metadata kind')
        return number(kind)
    path=Path(path)
    with path.open('rb') as stream:
        if stream.read(4)!=b'GGUF':raise ValueError('Not a GGUF model')
        version=number(4)
        if version not in [2,3]:raise ValueError('Unsupported GGUF version')
        tensors=number(10);count=number(10)
        if count>100_000:raise ValueError('GGUF metadata count limit')
        metadata={}
        for _ in range(count):
            key=string()
            if key in metadata:raise ValueError('Duplicate GGUF metadata key')
            metadata[key]=value(number(4))
        end=stream.tell();stream.seek(0);identity=hashlib.sha256(stream.read(end)).hexdigest()
    return {'version':version,'tensors':tensors,'metadataBytes':end,'metadataSha256':identity,'values':metadata}
