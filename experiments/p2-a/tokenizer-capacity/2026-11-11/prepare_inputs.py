"""Export hash-matched C# prompts and render exact local model templates without inference."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from gguf_metadata import read_metadata

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
PRIOR=ROOT/'experiments/p2-a/executable-bank/2026-11-11'


def digest(raw):return hashlib.sha256(raw).hexdigest()
def load(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def expected_chat(model,system,prompt):
    if model=='qwen':return (f'<|im_start|>system\n{system}<|im_end|>\n' if system else '')+f'<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n'
    if model=='llama':
        if system:raise ValueError('Unexpected Llama system message for the frozen model')
        return f'<|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n'
    raise ValueError('Unfrozen model')


def prepare(bank,snapshot,dotnet,dll,renderer,out):
    out.mkdir(exist_ok=False,parents=True)
    lock=load(PRIOR/'input-lock.json');assert digest(bank.read_bytes())==lock['manifestSha256']
    prior={row['taskId']:row for row in load(PRIOR/'results/replay/summary.json')['tasks']}
    raw=out/'raw-prompts.jsonl'
    with raw.open('wb') as f:
        subprocess.run([str(dotnet),str(dll),'p2-bank-prompts','--bank',str(bank)],stdout=f,check=True,cwd=out)
    entries=[];seen=set()
    with raw.open(encoding='utf-8') as f:
        for line in f:
            row=json.loads(line);tid=row['taskId'];assert tid in prior and tid not in seen;seen.add(tid)
            assert row['manifestSha256']==lock['manifestSha256']
            assert set(row['prompts'])=={'generation','verifierA','verifierB','verifierAWithStub','verifierBWithStub'}
            for kind,text in row['prompts'].items():
                original=prior[tid]['promptSizes'][kind];encoded=text.encode()
                assert digest(encoded)==original['sha256'] and len(encoded)==original['utf8Bytes']
                entries.append({'id':tid+':'+kind,'taskId':tid,'promptKind':kind,'rawPrompt':text,'rawSha256':digest(encoded)})
    assert seen==set(prior) and len(entries)==2110
    controls=[{'id':'control:'+row['id'],'taskId':row['id'],'promptKind':'control','rawPrompt':row['text'],'rawSha256':digest(row['text'].encode())} for row in load(HERE/'controls.json')]
    model_snapshot=load(snapshot/'summary.json');assert model_snapshot['newCompletionCalls']==0
    counts={}
    for model in model_snapshot['models']:
        key=model['id'];folder=out/key;folder.mkdir()
        metadata=read_metadata(model['modelBlobPath']);model['ggufMetadataSha256']=metadata['metadataSha256'];model['metadataBytes']=metadata['metadataBytes']
        write(folder/'model-config.json',model)
        template=(snapshot/key/'template.txt').read_text();system=(snapshot/key/'system.txt').read_text()
        assert digest(template.encode())==model['effectiveTemplateSha256'] and digest(system.encode())==model['effectiveSystemSha256']
        for name,population in [('controls',controls),('complete',entries)]:
            input_file=folder/(name+'-render-input.jsonl');rendered=folder/(name+'-rendered.jsonl')
            with input_file.open('w',encoding='utf-8') as f:
                for row in population:f.write(json.dumps({'id':row['id'],'content':row['rawPrompt']},ensure_ascii=False)+'\n')
            with input_file.open('rb') as src,rendered.open('wb') as dst:
                subprocess.run([str(renderer),str(snapshot/key/'template.txt'),str(snapshot/key/'system.txt')],stdin=src,stdout=dst,check=True)
            with rendered.open(encoding='utf-8') as src,(folder/(name+'.jsonl')).open('w',encoding='utf-8') as dst:
                number=0
                for original,line in zip(population,src,strict=True):
                    value=json.loads(line);assert value['id']==original['id']
                    assert value['prompt']==expected_chat(key,system,original['rawPrompt']),(key,name,original['id'],repr(value['prompt'][:180]))
                    record={**original,'chatPrompt':value['prompt'],'chatSha256':digest(value['prompt'].encode()),'templateSha256':model['effectiveTemplateSha256'],'systemSha256':model['effectiveSystemSha256']}
                    dst.write(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n');number+=1
                counts[key+'/'+name]=number
            input_file.unlink();rendered.unlink()
    summary={'schema':'aijade.p2a.token-capacity.inputs.v1','bankManifestSha256':lock['manifestSha256'],'tasks':len(seen),'rawPrompts':len(entries),
             'modelRows':counts,'rawPromptsSha256':digest(raw.read_bytes()),'sourceCodeCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             'sourceDirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),'newCompletionCalls':0}
    write(out/'summary.json',summary);print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    for key in ['bank','snapshot','dotnet','dll','renderer','out']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();prepare(a.bank.resolve(),a.snapshot.resolve(),a.dotnet.resolve(),a.dll.resolve(),a.renderer.resolve(),a.out.resolve())
