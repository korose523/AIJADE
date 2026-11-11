"""Input-only, outcome-blind greedy visibility selection; full cases stay in the execution bank."""
import argparse,collections,hashlib,json,subprocess,sys
from pathlib import Path
from budget_common import Runtime,HERE,ROOT,sha,file_sha,load,write

SCENARIOS=[{'id':'compact4k','contextTokens':4096,'generationReplyTokens':2048,'verificationReplyTokens':256,'maxVisibleCases':3,'maxInputTokens':512},
           {'id':'compact8k','contextTokens':8192,'generationReplyTokens':4096,'verificationReplyTokens':256,'maxVisibleCases':3,'maxInputTokens':512}]

class Prompts:
    def __init__(self,dotnet,dll,bank):
        self.child=subprocess.Popen([str(dotnet),str(dll),'p2-bank-prompt-server','--bank',str(bank)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr)
        self.empty={};self.manifest=file_sha(bank)
    def call(self,kind,task,indices):
        self.child.stdin.write(json.dumps({'command':kind,'taskId':task,'indices':indices},separators=(',',':')).encode()+b'\n');self.child.stdin.flush()
        line=self.child.stdout.readline(8*1024**2+1);assert line.endswith(b'\n') and len(line)<=8*1024**2
        value=json.loads(line);assert value['taskId']==task and value['manifestSha256']==self.manifest
        return value
    def empty_prompts(self,task,indices):
        key=(task,tuple(indices))
        if key not in self.empty:self.empty[key]=self.call('empty',task,indices)['prompts']
        return self.empty[key]
    def close(self):
        self.child.stdin.close()
        try:self.child.wait(timeout=15)
        except subprocess.TimeoutExpired:self.child.kill();self.child.wait()
        assert self.child.returncode==0

class Queries:
    def __init__(self,runtimes):self.runtimes=runtimes;self.data={}
    def get(self,text):
        identity=sha(text.encode())
        if identity not in self.data:
            model_counts={};chats={}
            for model,runtime in self.runtimes.items():
                counts,chat=runtime.predict(text);model_counts[model]=counts;chats[model]=sha(chat.encode())
            self.data[identity]={'id':'query:'+identity,'taskId':'selection-query','promptKind':'selectionQuery','rawPrompt':text,
                                 'rawSha256':identity,'predictedCounts':model_counts,'predictedChatSha256':chats}
        return self.data[identity]

def input_identity(task):
    assert [row['index'] for row in task['cases']]==list(range(task['caseCount']))
    assert all(sha(row['args'].encode())==row['sha256'] for row in task['cases'])
    return sha((sha(task['instruction'].encode())+'\n'+'\n'.join(row['sha256'] for row in task['cases'])+'\n').encode())

def select(inputs,runtimes,prompts,queries,scenario):
    tasks=[];decisions=[]
    def budgets(task,indices):
        result={}
        for kind,text in prompts.empty_prompts(task,indices).items():
            query=queries.get(text)
            for model in runtimes:
                tokens=query['predictedCounts'][model]['chatWithSpecial']
                result[model+'/'+kind]={'queryId':query['id'],'inputTokens':tokens,'totalWithAllowance':tokens+scenario['generationReplyTokens']+scenario['verificationReplyTokens'],
                                          'fits':tokens+scenario['generationReplyTokens']+scenario['verificationReplyTokens']<=scenario['contextTokens']}
        return result
    for task in inputs:
        selected=[];rows=[]
        initial=budgets(task['taskId'],selected)
        for case in task['cases']:
            index=case['index']
            if len(selected)==scenario['maxVisibleCases']:
                rows.append({'index':index,'reason':'MAX_VISIBLE_REACHED'});continue
            query=queries.get(case['args']);counts={model:query['predictedCounts'][model]['rawNoSpecial'] for model in runtimes}
            if max(counts.values())>scenario['maxInputTokens']:
                rows.append({'index':index,'reason':'INPUT_TOKEN_LIMIT','queryId':query['id'],'inputTokens':counts});continue
            proposed=selected+[index];budget=budgets(task['taskId'],proposed);accepted=all(value['fits'] for value in budget.values())
            rows.append({'index':index,'reason':'SELECTED' if accepted else 'PROMPT_BUDGET','queryId':query['id'],'inputTokens':counts,'tentativeBudgets':budget})
            if accepted:selected=proposed
        final=budgets(task['taskId'],selected)
        tasks.append({'taskId':task['taskId'],'caseCount':task['caseCount'],'inputSha256':task['inputSha256'],'selectedCaseIndices':selected})
        decisions.append({'taskId':task['taskId'],'initialBudgets':initial,'decisions':rows,'finalBudgets':final,'selectedCaseIndices':selected,
                          'zeroVisible':not selected,'planningEnvelopeFits':all(row['fits'] for row in final.values())})
    return tasks,decisions

def prepare(bank,configs,dotnet,dll,out):
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(),'Freeze source before complete selection'
    out.mkdir(parents=True,exist_ok=False);manifest=file_sha(bank);runtimes={};server=None
    try:
        for model in ['qwen','llama']:runtimes[model]=Runtime(configs/(model+'-counter.json'))
        with (out/'input-only.jsonl').open('wb') as dst:
            subprocess.run([str(dotnet),str(dll),'p2-bank-inputs','--bank',str(bank)],stdout=dst,check=True,cwd=out)
        inputs=[]
        with (out/'input-only.jsonl').open() as src:
            for line in src:
                row=json.loads(line);assert set(row)=={'manifestSha256','task'} and row['manifestSha256']==manifest
                task=row['task'];assert set(task)=={'taskId','instruction','caseCount','inputSha256','cases'}
                assert all(set(c)=={'index','args','sha256'} for c in task['cases']);assert input_identity(task)==task['inputSha256'];inputs.append(task)
        assert len(inputs)==len({row['taskId'] for row in inputs})==422 and sum(task['caseCount'] for task in inputs)==115185
        server=Prompts(dotnet,dll,bank);queries=Queries(runtimes);selection={};profiles={}
        for scenario in SCENARIOS:
            tasks,decisions=select(inputs,runtimes,server,queries,scenario)
            profile={'schema':'aijade.p2a.prompt-exposure.v1','bankManifestSha256':manifest,'scenario':scenario,
                     'modelManifestSha256ByName':{runtime.model['model']:runtime.model['manifestSha256'] for runtime in runtimes.values()},'tasks':tasks}
            folder=out/scenario['id'];folder.mkdir();write(folder/'exposure.json',profile);write(folder/'selection.json',{'scenario':scenario,'tasks':decisions})
            profiles[scenario['id']]=profile;selection[scenario['id']]=decisions
            print(scenario['id'],'selected',sum(len(row['selectedCaseIndices']) for row in tasks),'zero-visible',sum(not row['selectedCaseIndices'] for row in tasks),flush=True)
        # Reference ports enter only after every input-only selection is complete.
        forms=[];task_by_id={row['taskId']:row for row in inputs}
        for scenario in SCENARIOS:
            for task in profiles[scenario['id']]['tasks']:
                value=server.call('all',task['taskId'],task['selectedCaseIndices'])
                assert value['fullOracleCases']==task['caseCount'] and value['inputSha256']==task['inputSha256'] and value['expectedOutputNoninterference'] is True
                assert value['selectedCaseIndices']==task['selectedCaseIndices']
                assert set(value['prompts'])=={'generation','verifierA','verifierB','verifierAWithStub','verifierBWithStub'}
                for kind,text in value['prompts'].items():
                    forms.append({'id':scenario['id']+':'+task['taskId']+':'+kind,'taskId':task['taskId'],'scenarioId':scenario['id'],'promptKind':kind,
                                  'rawPrompt':text,'rawSha256':sha(text.encode()),'selectedCaseIndices':task['selectedCaseIndices'],'fullOracleCases':task['caseCount']})
        assert len(forms)==len({row['id'] for row in forms})==4220
        with (out/'raw-prompts.jsonl').open('w') as dst:
            for row in forms:dst.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
        with (out/'selection-queries.jsonl').open('w') as dst:
            for identity in sorted(queries.data):dst.write(json.dumps(queries.data[identity],ensure_ascii=False,separators=(',',':'))+'\n')
        for model,runtime in runtimes.items():
            folder=out/model;folder.mkdir();write(folder/'model-config.json',runtime.model)
            with (folder/'complete.jsonl').open('w') as dst:
                for row in forms+list(queries.data.values()):
                    chat=runtime.renderer.render(row['rawPrompt'])
                    record={key:row[key] for key in ['id','taskId','promptKind','rawPrompt','rawSha256']}
                    record.update(chatPrompt=chat,chatSha256=sha(chat.encode()),templateSha256=runtime.model['effectiveTemplateSha256'],systemSha256=runtime.model['effectiveSystemSha256'])
                    dst.write(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
        summary={'schema':'aijade.p2a.bounded-input.selection.v1','sourceCodeCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                 'bankManifestSha256':manifest,'tasks':422,'cases':115185,'scenarios':2,'profilePromptForms':4220,'modelProfileRows':8440,'profileTokenViews':33760,
                 'selectionQueries':len(queries.data),'completeRowsPerModel':4220+len(queries.data),'inputOnlySha256':file_sha(out/'input-only.jsonl'),
                 'rawPromptsSha256':file_sha(out/'raw-prompts.jsonl'),'selectionQueriesSha256':file_sha(out/'selection-queries.jsonl'),
                 'newCompletionCalls':0,'authorReview':'PENDING','selectionUsedReferenceOrExpectedOutputs':False,
                 'scenarioProfiles':{key:file_sha(out/key/'exposure.json') for key in profiles},
                 'dllSha256':file_sha(dll),'configSha256':{model:file_sha(configs/(model+'-counter.json')) for model in runtimes}}
        write(out/'summary.json',summary)
    finally:
        if server is not None:server.close()
        for runtime in runtimes.values():runtime.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    for name in ['bank','configs','dotnet','dll','out']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();prepare(a.bank.resolve(),a.configs.resolve(),a.dotnet.resolve(),a.dll.resolve(),a.out.resolve())
