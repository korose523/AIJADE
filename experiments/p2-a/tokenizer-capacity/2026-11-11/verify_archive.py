"""Read-only, model-free verification of the complete tokenizer-capacity archive."""
from pathlib import Path
from collections import Counter
import hashlib,json,sys
from audit_streams import opened,records,audit,negative_checks
from analyze_capacity import analyze
from prepare_inputs import expected_chat

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]

def load(path):return json.loads(path.read_text())
def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()
def logical_sha(path):
    h=hashlib.sha256()
    with opened(path) as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()

def verify(root=HERE):
    receipt=load(root/'results/receipt.json')
    for rel,expected in receipt['artifactSha256'].items():
        path=root/rel
        assert path.is_file() and file_sha(path)==expected,('changed archive payload',rel)
    records_root=root/'records';complete=records_root/'complete-03';inputs=records_root/'inputs-02'
    execution=load(complete/'execution.json');full=load(complete/'summary.json')
    assert full['status']=='PASS' and full['executionCodeCommit']==receipt['executionCodeCommit']
    assert execution['newCompletionCalls']==full['newCompletionCalls']==0
    assert execution['exportInputs']['rawPromptsSha256']==logical_sha(inputs/'raw-prompts.jsonl')
    assert execution['exportInputs']['bankManifestSha256']==receipt['bankManifestSha256']
    previous=load(ROOT/'experiments/p2-a/executable-bank/2026-11-11/results/replay/summary.json')
    prior={row['taskId']:row['promptSizes'] for row in previous['tasks']}
    canonical={};raw_count=0
    for row in records(inputs/'raw-prompts.jsonl'):
        assert row['taskId'] in prior
        assert row['manifestSha256']==receipt['bankManifestSha256']
        for kind,prompt in row['prompts'].items():
            raw=prompt.encode();old=prior[row['taskId']][kind]
            assert len(raw)==old['utf8Bytes'] and hashlib.sha256(raw).hexdigest()==old['sha256']
            identity=row['taskId']+':'+kind;assert identity not in canonical
            canonical[identity]=prompt;raw_count+=1
    assert raw_count==len(canonical)==2110
    report={};controls={};unchanged_views=0
    for model in ['qwen','llama']:
        config=load(inputs/model/'model-config.json');snapshot=records_root/'model-snapshot'/model
        template=(snapshot/'template.txt').read_text();system=(snapshot/'system.txt').read_text()
        assert hashlib.sha256(template.encode()).hexdigest()==config['effectiveTemplateSha256']
        assert hashlib.sha256(system.encode()).hexdigest()==config['effectiveSystemSha256']
        for kind,n in [('controls',15),('complete',2110)]:
            assert logical_sha(inputs/model/(kind+'.jsonl'))==execution['modelCorpusSha256'][model][kind]
            seen=set()
            for row in records(inputs/model/(kind+'.jsonl')):
                assert row['chatPrompt']==expected_chat(model,system,row['rawPrompt'])
                if kind=='complete':assert canonical[row['id']]==row['rawPrompt']
                assert row['id'] not in seen;seen.add(row['id'])
            assert len(seen)==n
            result=audit(complete/kind/model/'data',inputs/model/(kind+'.jsonl'),n,model)
            (controls if kind=='controls' else report)[model]=result
            process=load(complete/kind/model/'process.json')
            assert process['exitCode']==0 and process['stop'] is None
            assert process['sampledFamilyPeakRssBytes']<=process['limits']['sampledFamilyRssBytes']
            assert process['sampledFamilyCpuSeconds']<=process['limits']['cpuSeconds']
            assert process['wallSeconds']<=process['limits']['wallSeconds']
        old=list(records(records_root/'complete-02/complete'/model/'data/measurements.jsonl'))
        current=list(records(complete/'complete'/model/'data/measurements.jsonl'))
        assert len(old)==len(current)==2110
        for a,b in zip(old,current):
            assert a['id']==b['id']
            for view in a['measurements']:
                assert a['measurements'][view]['idsAgree'] is True
                assert a['measurements'][view]['nativeTokenSha256']==b['measurements'][view]['nativeTokenSha256']
                unchanged_views+=1
    assert unchanged_views==16880
    # Compare every scenario and task set, not just headline counts.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='aijade-token-audit-') as tmp:
        actual=analyze(complete,inputs,Path(tmp)/'summary.json')
    recorded=load(root/'results/summary.json')
    for key,value in actual.items():assert recorded[key]==value,('changed aggregate',key)
    assert load(records_root/'complete-01/summary.json')['status']=='FAIL'
    rejected=load(records_root/'complete-02/summary.json');assert rejected['status']=='FAIL'
    assert rejected['results']['complete/llama']['summary']['counts']=={'MISMATCH':1332,'PASS':778}
    assert report['qwen']['rows']==report['llama']['rows']==2110
    return {'status':'PASS','full':report,'controls':controls,'unchangedTokenViewsFromRejectedDecoderPass':unchanged_views,
            'rawPromptJoins':raw_count,'negativeChecks':negative_checks(),'completePopulationAndCapacityLedgerRecomputed':True,'newCompletionCalls':0,
            'scope':'Recorded-byte/ID and context arithmetic audit; no model inference, device qualification, task eligibility or scientific approval.'}

if __name__=='__main__':
    try:print(json.dumps(verify(),indent=2))
    except (AssertionError,KeyError,ValueError,OSError) as error:
        print('ARCHIVE REJECTED:',repr(error),file=sys.stderr);raise SystemExit(1)
