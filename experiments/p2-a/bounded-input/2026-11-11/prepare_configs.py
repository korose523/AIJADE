"""Bind existing local tokenizer installations; do not install, load inference, or change models."""
import argparse,sys
from pathlib import Path
from budget_common import HERE,TOKENIZER,file_sha,load,write

def prepare(snapshot,old_inputs,environment,native,renderer,python,out):
    out.mkdir(parents=True,exist_ok=False)
    env=load(environment)
    assert file_sha(native)==env['files']['nativeHelper']['sha256']
    assert file_sha(renderer)==env['files']['chatRenderer']['sha256']
    sources=[HERE/'budget_common.py',HERE/'token_counter.py',TOKENIZER/'gguf_metadata.py',TOKENIZER/'independent_bpe.py',TOKENIZER/'prepare_inputs.py']
    import tokenizers
    assert tokenizers.__version__=='0.22.1'
    extensions={p.name:file_sha(p) for p in Path(tokenizers.__file__).parent.glob('*.so')}
    prior_extension=env['files']['tokenizersExtension']
    assert extensions=={Path(prior_extension['path']).name:prior_extension['sha256']}
    for model in ['qwen','llama']:
        info=load(old_inputs/model/'model-config.json')
        write(out/(model+'-model-config.json'),info)
        config={'schema':'aijade.p2a.token-counter.config.v1','modelConfig':info,
                'native':{'path':str(native),'sha256':file_sha(native)},
                'library':{'path':env['files']['libllama']['path'],'sha256':env['files']['libllama']['sha256']},
                'renderer':{'path':str(renderer),'sha256':file_sha(renderer)},
                'template':{'path':str(snapshot/model/'template.txt'),'sha256':info['effectiveTemplateSha256']},
                'system':{'path':str(snapshot/model/'system.txt'),'sha256':info['effectiveSystemSha256']},
                'tokenizersVersion':'0.22.1','tokenizersExtensionSha256':extensions,
                'sourceSha256':{str(path):file_sha(path) for path in sources}}
        write(out/(model+'-counter.json'),config)
    write(out/'setup.json',{'pythonExecutable':str(python),'pythonSha256':file_sha(python),'counterScript':str(HERE/'token_counter.py'),
                            'counterScriptSha256':file_sha(HERE/'token_counter.py'),'snapshot':str(snapshot),'newCompletionCalls':0})

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    for name in ['snapshot','old-inputs','environment','native','renderer','python','out']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();prepare(a.snapshot.resolve(),a.old_inputs.resolve(),a.environment.resolve(),a.native.resolve(),a.renderer.resolve(),a.python.absolute(),a.out.resolve())
