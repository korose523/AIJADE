"""Post-measurement structural corruption controls, without changing the scorer."""
from pathlib import Path
import argparse,collections,copy,gzip,hashlib,json,shutil,sys,tempfile
from urllib.parse import urlencode
parser=argparse.ArgumentParser(description=__doc__)
for key in ['root','frame','oracle','out']:parser.add_argument('--'+key,type=Path,required=True)
parser.add_argument('--scripts',type=Path,default=Path(__file__).resolve().parent)
args=parser.parse_args();E=args.scripts
sys.path.insert(0,str(E))
from audit import audit,audit_row,load,lines
from input_frame import ARMS,sha
root=args.root;frame=load(args.frame);results=[]
def reject(name,target):
 try:audit(target,args.frame,args.oracle)
 except AssertionError as err:results.append(dict(name=name,rejected=True,reason=str(err)));return
 raise AssertionError('Corruption accepted: '+name)
with tempfile.TemporaryDirectory(prefix='aijade-history-extra-') as td:
 p=Path(td);shutil.copy2(root/'prompt-constants.json',p/'prompt-constants.json')
 dirs=[f"c{c['c']:02d}-{arm}" for c in frame['conversations'] for arm in ARMS]
 for name in dirs[:-1]:(p/name).mkdir()
 reject('whole_trajectory_omitted',p)
 (p/dirs[-1]).mkdir()
 target=p/'c00-static'
 for name in ['input.json','base-store.json.gz','base-writes.jsonl.gz','journal.jsonl']:
  shutil.copy2(root/'c00-static'/name,target/name)
 raw=gzip.decompress((root/'c00-static/records.jsonl.gz').read_bytes());rows=raw.splitlines(keepends=True)
 (target/'records.jsonl.gz').write_bytes(gzip.compress(b''.join(rows[:-1]),mtime=0));reject('complete_question_row_omitted',p)
 (target/'records.jsonl.gz').write_bytes(gzip.compress(b''.join(rows+[rows[-1]]),mtime=0));reject('complete_question_row_duplicated',p)
oracle=load(args.oracle);matches={(x['c'],x['query']):x['ids'] for x in oracle['entries']};constants=load(root/'prompt-constants.json')
conv=frame['conversations'][0]
def coherent(name,mutate):
 row,_=lines(root/'c00-static/records.jsonl.gz')[0];journal=collections.defaultdict(list)
 for event,_ in lines(root/'c00-static/journal.jsonl'):journal[event['key']].append(event)
 mutate(row)
 row['searches']=[copy.deepcopy(call) for call in row['calls'] if call['method']=='GET' and call['path']=='/api/v1/memory/items']
 calls={call['call']:call for call in row['calls']}
 for event in journal['c00/static/q0000']:
  d=event['detail']
  if event['phase']=='http.begin':
   call=calls[d['call']];d['requestSha256']=None if call['requestBody'] is None else sha(call['requestBody'].encode())
  elif event['phase']=='http.end':d['responseSha256']=sha(calls[d['call']]['responseBody'].encode())
  elif event['phase']=='memory.response':
   call=calls[d['call']];d['responseSha256']=sha(call['responseBody'].encode())
   d['candidateIdsSha256']=sha(json.dumps(call['candidateIds'],separators=(',',':')).encode())
 h=sha(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode());journal['c00/static/q0000'][-1]['detail']['rowSha256']=h
 logical={t['id']:'source:'+t['sourceId'] for t in conv['turns']};store={'source:'+t['sourceId']:dict(content=t['content'],createdAt=t['createdAt']) for t in conv['turns']}
 try:audit_row(row,conv['questions'][0],conv,'static',store,logical,[],matches,constants,journal,h)
 except (AssertionError,KeyError) as err:results.append(dict(name=name,rejected=True,reason=str(err),provenanceCopiesAndHashesRebound=True));return
 raise AssertionError('Coherent corruption accepted: '+name)
def query_change(row):
 call=next(c for c in row['calls'] if c['path']=='/api/v1/memory/items');call['memoryQuery']=conv['questions'][1]['question']
 call['queryString']='?'+urlencode(dict(q=call['memoryQuery'],limit=6))
def candidate_change(row):
 call=next(c for c in row['calls'] if c.get('candidateIds'));call['candidateIds']=call['candidateIds'][1:];call['candidateCreatedAt']=call['candidateCreatedAt'][1:]
def response_change(row):
 call=next(c for c in row['calls'] if c['path']=='/api/v1/memory/items' and json.loads(c['responseBody'])['items'])
 body=json.loads(call['responseBody']);body['items'][0]['content']='coherently edited response';call['responseBody']=json.dumps(body,separators=(',',':'))
coherent('query_changed_with_matching_copies_and_hashes',query_change)
coherent('native_pool_changed_with_matching_copies_and_hashes',candidate_change)
coherent('response_changed_with_matching_copies_and_hashes',response_change)
coherent('selection_changed_with_matching_row_hash',lambda r:r['selected'][0].update(id='invented-selected-source'))
result=dict(status='STRUCTURAL_DISPOSABLE_CORRUPTIONS_REJECTED',controls=results,
 timing='Additional post-measurement audit controls; original runtime, audit/scorer sources and primary bytes unchanged.')
args.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
