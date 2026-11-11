#!/usr/bin/env python3
"""Reconstruct all measured rows from frozen inputs, native eligibility and raw HTTP.

This auditor does not trust selected IDs, observer labels, denominators or summaries.
No model is invoked. Native cutoff ties permit any valid member of the tied group.
"""
import argparse,datetime as dt,gzip,json,hashlib,collections
from pathlib import Path
from urllib.parse import parse_qs
from input_frame import ARMS,sha
from eligibility import terms

ANCHOR=1794441600000 # 2026-11-12T00:00:00Z
def load(p):return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
def lines(p):
    data=gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes()
    return [(json.loads(x),sha(x)) for x in data.splitlines() if x]
def check(ok,label):
    if not ok:raise AssertionError(label)
def millis(s):return int(dt.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)
def ulen(s):return len(s.encode('utf-16-le'))//2
def limit(s,n,marker):
    if ulen(s)<=n:return s
    if n<=ulen(marker):return ''
    raw=s.encode('utf-16-le')[:2*(n-ulen(marker))]
    if raw and 0xD800<=int.from_bytes(raw[-2:],'little')<=0xDBFF:raw=raw[:-2]
    return raw.decode('utf-16-le')+marker
def history_budget(history,window,n,marker):
    chosen=[]
    for row in list(history)[-window:][::-1]:
        content=row['content']
        if ulen(content)>n:
            if not chosen:
                excerpt=limit(content,n,marker)
                if excerpt:chosen.append(dict(role=row['role'],content=excerpt))
            break
        chosen.append(dict(role=row['role'],content=content));n-=ulen(content)
    return chosen[::-1]
def normalize_message(m):
    return {**{k:m.get(k) for k in ['id','seq','role','content','meta']},'createdAt':millis(m['createdAt'])}
def state(items):
    text='\n'.join(k+'\t'+str(v['createdAt'])+'\t'+sha(v['content'].encode()) for k,v in sorted(items.items()))
    return dict(count=len(items),canonicalSha256=sha(text.encode()),unmappedIds=[],vectorItems=0,owners=['test-user'])
def prompt_observe(system,selected,header,marker):
    base=dict(identifiable=True,truncated=False,fullItemIds=[],systemSha256=sha(system.encode()))
    if header not in system:return dict(base,state='absent')
    if system.count(header)>1 or not selected:return dict(base,state='unexplained-block',identifiable=False)
    texts=[s['content'] for s in selected]
    if len(texts)!=len(set(texts)) or any(header in s or marker in s for s in texts):
        return dict(base,state='ambiguous-source',identifiable=False)
    expected=header+'\n'.join('- '+s for s in texts);actual=system[system.index(header):]
    if actual.startswith(expected) and (len(actual)==len(expected) or actual[len(expected)]=='\n'):
        return dict(base,state='complete',fullItemIds=[s['id'] for s in selected])
    cut=actual.find(marker)
    if cut<0 or cut>=len(expected) or not expected.startswith(actual[:cut]):return dict(base,state='unexplained-block',identifiable=False)
    end=len(header);ids=[]
    for i,s in enumerate(selected):
        end+=(1 if i else 0)+2+len(s['content'])
        if end<=cut:ids.append(s['id'])
    return dict(base,state='truncated',truncated=True,fullItemIds=ids)
def audit_row(row,expected,conv,arm,store,logical,prior,matches,constants,journal,rowhash):
    c=conv['c'];q=expected['q'];key=f'c{c:02d}/{arm}/q{q:04d}'
    check((row['c'],row['arm'],row['q'],row['sampleId'])==(c,arm,q,conv['sampleId']),'scheduled-key')
    for k in ['question','category','evidenceSourceIds','goldIds','unlocatedGoldIds']:check(row[k]==expected[k],'input-'+k)
    check(row['storeBefore']==state(store),'store-before')
    calls=row['calls'];check([x['call'] for x in calls]==list(range(1,len(calls)+1)),'call-sequence')
    check(all(200<=x['status']<300 and x['beginTicks']<=x['nativeResponseTicks']<=x['endTicks'] for x in calls),'http-success-chronology')
    check(row['gatewayAttempts']==0 and not row['moduleFailures'],'gateway-or-module-failure')
    check(row['completed'] and row['completionCaptures']==1,'turn-incomplete')
    seen=journal[key];phases=[x['phase'] for x in seen]
    check(phases.count('question.begin')==1 and phases.count('question.complete')==1,'journal-question-closure')
    check(seen[-1]['detail']['rowSha256']==rowhash,'journal-row-hash')
    for call in calls:
        begin=[x for x in seen if x['phase']=='http.begin' and x['detail']['call']==call['call']]
        end=[x for x in seen if x['phase']=='http.end' and x['detail']['call']==call['call']]
        check(len(begin)==len(end)==1,'journal-http-closure')
        check(begin[0]['detail']['path']==call['path'] and begin[0]['detail']['requestSha256']==(None if call['requestBody'] is None else sha(call['requestBody'].encode())),'journal-http-input')
        check(end[0]['detail']['responseSha256']==sha(call['responseBody'].encode()) and end[0]['detail']['status']==call['status'],'journal-http-output')
    getters=[x for x in calls if x['method']=='GET' and x['path'].endswith('/messages')]
    expected_history=[] if arm=='static' else prior
    if arm=='static':check(not getters,'static-has-history-fetch')
    else:
        check(len(getters)==1 and parse_qs(getters[0]['queryString'].lstrip('?'))=={'after':['0']},'history-fetch')
        check([normalize_message(m) for m in json.loads(getters[0]['responseBody'])['messages']]==[normalize_message(m) for m in prior],'history-api-continuity')
    check([normalize_message(m) for m in row['historySupplied']]==[normalize_message(m) for m in expected_history],'supplied-history')
    writes=[x for x in calls if x['path']=='/api/v1/v9/perception']
    check(len(writes)==len(row['questionWrites'])==(1 if arm.startswith('record-') else 0),'question-write-count')
    current=None
    if writes:
        call=writes[0];body=json.loads(call['requestBody']);delta=row['questionWrites'][0]
        check(body['content']==expected['question'] and body['timestamp']==ANCHOR+60000*q and body['session_id']==f'p3-history-{c}' and body['source']=='chat','question-perception')
        current='ep_'+body['event_id'];check(current not in logical,'duplicate-question-pack')
        check(delta['packId']==current and delta['logicalId']==f'question:{q:04d}' and delta['q']==q and delta['accepted'] and delta['call']==call['call'],'question-write-delta')
        check(delta['stored']==dict(id=current,content=expected['question'],createdAt=ANCHOR+60000*q,owner='test-user',hasVector=False),'question-stored-content')
        logical[current]=f'question:{q:04d}'
        record_begin=next(x['monotonicTicks'] for x in seen if x['phase']=='question.record.begin')
        record_end=next(x['monotonicTicks'] for x in seen if x['phase']=='question.record.end')
        turn_begin=next(x['monotonicTicks'] for x in seen if x['phase']=='turn.begin')
        turn_end=next(x['monotonicTicks'] for x in seen if x['phase']=='turn.end')
        if arm=='record-before':check(record_end<turn_begin,'before-schedule')
        elif arm=='record-after':check(record_begin>turn_end,'after-schedule')
        else:check(turn_begin<record_begin<record_end<turn_end and phases.count('record.callback.begin')==phases.count('record.callback.end')==1,'between-schedule')
    searches=[x for x in calls if x['method']=='GET' and x['path']=='/api/v1/memory/items']
    check(searches==row['searches'] and searches,'search-call-copy')
    union=set();responses={};filtered={};ties=0
    for i,s in enumerate(searches):
        query=s['memoryQuery'];parsed=parse_qs(s['queryString'].lstrip('?'))
        check(parsed=={'q':[query],'limit':['6']} and s['limit']==6 and s['sessionFilter'] is None,'native-query-options')
        active=dict(store)
        if current and (arm=='record-before' or (arm=='record-between' and i>0)):
            active[f'question:{q:04d}']=dict(content=expected['question'],createdAt=ANCHOR+60000*q)
        eligible=set(matches[(c,query.strip())])&set(active)
        candidate=s['candidateIds'];check(len(candidate)==len(set(candidate)),'duplicate-candidate')
        check(set(logical[x] for x in candidate)==eligible,'native-candidate-eligibility')
        times=[active[logical[x]]['createdAt'] for x in candidate]
        check(times==sorted(times,reverse=True) and times==s['candidateCreatedAt'] and s['storeCountAtResponse']==len(active),'candidate-order-state')
        union.update(candidate)
        body=json.loads(s['responseBody']);items=body['items'];ids=[x['id'] for x in items]
        check(len(ids)==len(set(ids))==min(6,len(eligible)) and set(ids)<=set(candidate),'response-cutoff')
        expected_times=sorted(times,reverse=True)[:6]
        check([millis(x['createdAt']) for x in items]==expected_times,'response-time-order')
        if len(times)>6 and times[5]==times[6]:ties+=1
        for item in items:
            original=active[logical[item['id']]]
            check(item['content']==original['content'] and item['sessionId']==f'p3-history-{c}' and item['source']=='chat','response-content-origin')
            responses.setdefault(item['id'],item)
            if item['content'].strip().lower()!=expected['question'].strip().lower():filtered.setdefault(item['id'],item)
        if i==0:
            wanted=[expected['question']]+([] if filtered else terms(expected['question']))
            check([x['memoryQuery'] for x in searches]==wanted,'whole-query-fallback-schedule')
            if arm=='record-between':check(s['nativeStateObservedTicks']<record_begin<record_end<s['endTicks'],'between-native-response-boundary')
    selected=sorted(filtered.values(),key=lambda m:-millis(m['createdAt']))[:5]
    check(row['selected']==selected,'selected-newest-five')
    if current:store[f'question:{q:04d}']=dict(content=expected['question'],createdAt=ANCHOR+60000*q)
    check(row['storeAfter']==state(store),'store-after')
    completions=[x for x in calls if x['path'].endswith('/openai/v1/chat/completions')]
    check(len(completions)==1 and completions[0]['requestBody']==row['completionBody'],'completion-raw')
    request=json.loads(row['completionBody']);memory=constants['memoryHeader']+'\n'.join('- '+x['content'] for x in selected) if selected else ''
    bounded=limit(memory,4000,constants['truncationMarker'])
    system='\n\n'.join(x for x in [constants['persona'],bounded,constants['expressionInstruction'],constants['replyInstruction']] if x)
    used=history_budget(expected_history,24,24000,constants['truncationMarker'])
    check(request['messages']==[dict(role='system',content=system)]+used+[dict(role='user',content=expected['question'])],'assembled-prompt-history-budget')
    observed=prompt_observe(system,selected,constants['memoryHeader'],constants['truncationMarker'])
    check(row['promptObservation']==observed,'prompt-observation')
    appends=[x for x in calls if x['method']=='POST' and x['path'].endswith('/messages')]
    check(len(appends)==2,'chat-append-count')
    for call,role,text in zip(appends,['user','assistant'],[expected['question'],'ok']):
        body=json.loads(call['requestBody']);saved=json.loads(call['responseBody'])
        check(body['role']==saved['role']==role and body['content']==saved['content']==text,'chat-append-content')
        check(saved['seq']==len(prior)+1,'chat-sequence');prior.append(saved)
    gold=set(expected['goldIds']);unlocated=set(expected['unlocatedGoldIds']);g=len(gold)
    prompt_low=set(observed['fullItemIds']) if observed['identifiable'] else set()
    prompt_high=prompt_low if observed['identifiable'] else {x['id'] for x in selected}
    stages={'candidate':union,'response':set(responses),'echoFiltered':set(filtered),'selected':{x['id'] for x in selected},'prompt':prompt_low}
    metrics={}
    for name,ids in stages.items():
        lo=len(gold&ids);hi=len(gold&(prompt_high if name=='prompt' else ids))+len(unlocated)
        metrics[name]=[lo/g,hi/g] if g else [0,1]
    return dict(c=c,arm=arm,q=q,category=expected['category'],gold=len(gold),unlocated=len(unlocated),metrics=metrics,
      cutoffTies=ties,promptState=observed['state'],selectedItems=len(selected),promptFullItems=len(prompt_low),
      questionItemsSelected=sum(logical[x['id']].startswith('question:') for x in selected),
      suppliedHistory=len(expected_history),usedHistory=len(used),historyCharacters=sum(ulen(x['content']) for x in used),
      sourceExactTextInHistory=sum(any(t['content'] in h['content'] for h in used) for t in conv['turns'] if t['id'] in gold),
      fallbackQueries=len(searches)-1,searches=len(searches),promptUtf16=ulen(system))

def audit(root,framepath,oraclepath):
    frame=load(framepath);oracle=load(oraclepath);check(oracle['frameSha256']==sha(framepath.read_bytes()),'oracle-frame-hash')
    matches={(x['c'],x['query']):x['ids'] for x in oracle['entries']};constants=load(root/'prompt-constants.json')
    check(constants['historyWindow']==24 and constants['promptBudget']['moduleCharacters']==4000 and constants['promptBudget']['historyCharacters']==24000,'budget-constants')
    expected_dirs={f"c{c['c']:02d}-{arm}" for c in frame['conversations'] for arm in ARMS}
    check({p.name for p in root.glob('c*-*') if p.is_dir()}==expected_dirs,'trajectory-coverage')
    metrics=[];parity={};dbs=[]
    for conv in frame['conversations']:
        c=conv['c']
        for arm in ARMS:
            folder=root/f'c{c:02d}-{arm}';input=load(folder/'input.json');dbs.append(input['database'])
            check(input['c']==c and input['arm']==arm and input['position']==(ARMS.index(arm)-c)%5,'trajectory-order')
            base=load(folder/'base-store.json.gz');source={t['id']:t for t in conv['turns']}
            check(len(base)==len(source) and len({x['id'] for x in base})==len(base),'base-store-count')
            for item in base:
                t=source[item['id']];check(item==dict(id=t['id'],content=t['content'],createdAt=t['createdAt'],owner='test-user',hasVector=False),'base-store-projection')
            writes=lines(folder/'base-writes.jsonl.gz');check(len(writes)==len(source),'base-write-count')
            check([x['packId'] for x,_ in writes]==[t['id'] for t in conv['turns']],'base-write-order')
            for row,_ in writes:
                t=source[row['packId']];check(200<=row['status']<300 and row['sourceId']==t['sourceId'] and row['request']['content']==t['content'] and row['request']['timestamp']==t['createdAt'] and 'ep_'+row['request']['event_id']==t['id'],'base-api-ingestion')
            logical={t['id']:'source:'+t['sourceId'] for t in conv['turns']}
            store={'source:'+t['sourceId']:dict(content=t['content'],createdAt=t['createdAt']) for t in conv['turns']};prior=[]
            check(input['baseCanonicalSha256']==state(store)['canonicalSha256'],'input-base-hash')
            journal=collections.defaultdict(list);events=lines(folder/'journal.jsonl')
            check([e['sequence'] for e,_ in events]==list(range(1,len(events)+1)),'journal-sequence')
            check([e['monotonicTicks'] for e,_ in events]==sorted(e['monotonicTicks'] for e,_ in events),'journal-monotonic')
            for e,_ in events:journal[e['key']].append(e)
            records=lines(folder/'records.jsonl.gz');check(len(records)==len(conv['questions']),'question-coverage')
            for (row,rowhash),expected in zip(records,conv['questions']):
                metrics.append(audit_row(row,expected,conv,arm,store,logical,prior,matches,constants,journal,rowhash))
                if arm.startswith('record-'):parity.setdefault((c,expected['q']),[]).append(row['storeAfter']['canonicalSha256'])
            final=load(folder/'final-store.json.gz');check(len(final)==len(store),'final-store-count')
            for item in final:
                check(logical[item['id']] in store and item['content']==store[logical[item['id']]]['content'] and item['createdAt']==store[logical[item['id']]]['createdAt'] and item['owner']=='test-user' and not item['hasVector'],'final-store-content')
            receipt=load(folder/'receipt.json');check(receipt['counts']['rows']==len(records) and receipt['finalStore']==state(store),'trajectory-receipt')
    check(all(len(v)==3 and len(set(v))==1 for v in parity.values()),'record-arm-state-parity')
    check(len(dbs)==len(set(dbs))==50,'isolated-databases')
    execution=load(root/'execution.json');check(execution['rows']==len(metrics)==9930 and execution['trajectories']==50 and execution['gatewayAttempts']==0,'batch-execution')
    cleanup=load(root/'database-cleanup.json');check({x['database'] for x in cleanup}==set(dbs) and all(x['absent'] for x in cleanup),'database-cleanup')
    admission=load(root/'admission.json');check(admission['admitted'] and not admission['windowReset'] and admission['elapsedSeconds']>=120,'admission')
    controller=load(root/'controller-receipt.json');check(controller['status']=='COMPLETE' and controller['exitCode']==0 and controller['ownedProcessExited'] and controller['binariesUnchanged'],'controller-closure')
    freeze=load(root/'input-identities.json');check(execution['codeCommit']==controller['codeCommit']==freeze['commit'] and '0.1.0+'+freeze['commit'] in freeze['assemblyInfoText'],'embedded-revision')
    return metrics,dict(status='FULL_RAW_RECONSTRUCTION_PASS',rows=len(metrics),trajectories=50,matchedPostTurnStates=len(parity),
      frameSha256=sha(framepath.read_bytes()),oracleSha256=sha(oraclepath.read_bytes()),codeCommit=freeze['commit'],
      scope='Engineering reconstruction of controlled scripts; no independent human coding, model answer or formal hardware qualification.')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['root','frame','oracle','out']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();metrics,receipt=audit(a.root,a.frame,a.oracle);a.out.mkdir(parents=True,exist_ok=False)
    (a.out/'metrics.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(x,separators=(',',':')) for x in metrics)+'\n').encode(),mtime=0))
    (a.out/'audit.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
