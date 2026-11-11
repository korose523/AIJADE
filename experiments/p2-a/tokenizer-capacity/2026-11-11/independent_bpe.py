"""Independent tokenizers BPE engine with the exact local GGUF vocabulary and rules."""
from tokenizers import AddedToken, Regex, Tokenizer, decoders, models, pre_tokenizers

PREFIX = r"(?:'[sS]|'[tT]|'[rR][eE]|'[vV][eE]|'[mM]|'[lL][lL]|'[dD])|[^\r\n\p{L}\p{N}]?\p{L}+|"
SUFFIX = r"| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"


class IndependentBpe:
    def __init__(self, metadata):
        self.data=metadata['values']
        pieces=self.data['tokenizer.ggml.tokens']
        if len(set(pieces))!=len(pieces):raise ValueError('Duplicate vocabulary pieces need explicit handling')
        pre=self.data.get('tokenizer.ggml.pre')
        if pre not in ['llama-bpe','qwen2']:raise ValueError('Unfrozen pre-tokenizer')
        regex=PREFIX+(r'\p{N}{1,3}' if pre=='llama-bpe' else r'\p{N}')+SUFFIX
        merges=[tuple(row.split(' ',1)) for row in self.data['tokenizer.ggml.merges']]
        if any(len(row)!=2 for row in merges):raise ValueError('Invalid merge pair')
        vocab={piece:i for i,piece in enumerate(pieces)}
        self.tokenizer=Tokenizer(models.BPE(vocab=vocab,merges=merges,ignore_merges=(pre=='llama-bpe')))
        self.tokenizer.pre_tokenizer=pre_tokenizers.Sequence([
            pre_tokenizers.Split(Regex(regex),behavior='isolated'),
            pre_tokenizers.ByteLevel(add_prefix_space=False,use_regex=False),
        ])
        self.tokenizer.decoder=decoders.ByteLevel()
        kinds=self.data['tokenizer.ggml.token_type']
        special=[AddedToken(piece,special=True,normalized=False,lstrip=False,rstrip=False,single_word=False)
                 for piece,kind in zip(pieces,kinds) if kind in [2,3,4]]
        self.tokenizer.add_special_tokens(special)
        if any(self.tokenizer.token_to_id(piece)!=i for i,piece in enumerate(pieces)):
            raise ValueError('Vocabulary IDs changed during independent construction')
        self.add_bos=self.data.get('tokenizer.ggml.add_bos_token',pre=='llama-bpe')
        self.add_eos=self.data.get('tokenizer.ggml.add_eos_token',False)
        self.bos=self.data.get('tokenizer.ggml.bos_token_id')
        self.eos=self.data.get('tokenizer.ggml.eos_token_id')
        self.pieces=pieces
        self.pre=pre

    def encode(self,text,add_special=False):
        result=self.tokenizer.encode(text,add_special_tokens=False).ids
        if add_special and self.add_bos:
            if self.bos is None:raise ValueError('Missing BOS ID')
            result.insert(0,self.bos)
        if add_special and self.add_eos:
            if self.eos is None:raise ValueError('Missing EOS ID')
            result.append(self.eos)
        return result

    def decode(self,ids):
        return self.tokenizer.decode(ids,skip_special_tokens=False)
