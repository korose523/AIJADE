#!/usr/bin/env python3
"""Frozen source projection without expected answers; no product execution."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
from pathlib import Path

CORPUS_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
ARMS=['static','history','record-after','record-before','record-between']
MONTHS={name:i for i,names in enumerate([
 ['january','jan'],['february','feb'],['march','mar'],['april','apr'],['may'],['june','jun'],
 ['july','jul'],['august','aug'],['september','sep','sept'],['october','oct'],['november','nov'],['december','dec']]) for name in names}
UTC=dt.timezone.utc
def sha(data):return hashlib.sha256(data).hexdigest()
def pack(c,source):return 'ep_p3-history-'+str(c)+'-'+sha(source.encode())
def timestamp(text,session):
    time=re.search(r'([0-9]{1,2}):([0-9]{2})\s*(am|pm).*?([0-9]{1,2})\s+([a-z]+),?\s*([0-9]{4})',text,re.I)
    date=re.search(r'([0-9]{1,2})\s+([a-z]+),?\s*([0-9]{4})',text,re.I)
    if time and time[5].lower() in MONTHS:
        h=int(time[1]);m=int(time[2]);ap=time[3].lower()
        if ap=='pm' and h!=12:h+=12
        if ap=='am' and h==12:h=0
        d=int(time[4]);month=MONTHS[time[5].lower()];y=int(time[6])
    elif date and date[2].lower() in MONTHS:
        h=12;m=0;d=int(date[1]);month=MONTHS[date[2].lower()];y=int(date[3])
    else:return int((dt.datetime(2023,1,1,tzinfo=UTC)+dt.timedelta(days=session)).timestamp()*1000)
    value=dt.datetime(y,month+1,1,tzinfo=UTC)+dt.timedelta(days=d-1,hours=h,minutes=m)
    return int(value.timestamp()*1000)
def project(raw):
    frame=[];missing=[];unlocated=[];empty=0
    for c,conversation in enumerate(raw):
        turns=[]
        for key,items in conversation['conversation'].items():
            match=re.fullmatch(r'session_([0-9]+)',key)
            if not match or not isinstance(items,list):continue
            base=timestamp(conversation['conversation'].get(key+'_date_time',''),int(match[1]))
            for i,t in enumerate(items):
                content=t.get('text','')
                if not content.strip():empty+=1;continue
                turns.append(dict(sourceId=t['dia_id'],id=pack(c,t['dia_id']),content=content,createdAt=base+i*60000))
        ids={t['sourceId'] for t in turns};assert len(ids)==len(turns)
        questions=[]
        for q,item in enumerate(conversation['qa']):
            evidence=[e for e in item.get('evidence',[]) if isinstance(e,str)] if isinstance(item.get('evidence',[]),list) else []
            category=item.get('category',0);gold=list(dict.fromkeys(evidence))
            row=dict(q=q,question=item.get('question',''),category=category,evidenceSourceIds=evidence,
                     goldIds=[pack(c,e) for e in gold],unlocatedGoldIds=[pack(c,e) for e in gold if e not in ids])
            assert row['question'].strip(),'Empty public question requires a prospective handling rule'
            questions.append(row)
            if category!=5 and not evidence:missing.append([c,q])
            if category!=5 and row['unlocatedGoldIds']:unlocated.append([c,q,row['unlocatedGoldIds']])
        frame.append(dict(c=c,sampleId=conversation['sample_id'],turns=turns,questions=questions))
    primary=sum(q['category']!=5 for c in frame for q in c['questions'])
    annotated=sum(q['category']!=5 and bool(q['goldIds']) for c in frame for q in c['questions'])
    return dict(schema='aijade.p3.history-input.v1',corpusSha256=CORPUS_SHA,arms=ARMS,conversations=frame,
      accounting=dict(dialogues=len(frame),questions=sum(len(c['questions']) for c in frame),answerable=primary,
       annotatedAnswerable=annotated,answerableWithoutEvidence=missing,answerableWithUnlocatedEvidence=unlocated,
       nonemptySourceTurns=sum(len(c['turns']) for c in frame),emptySourceTurnsSkipped=empty),
      scope='Public-question source projection without expected answers; same already-observed corpus, no new held-out construction.')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    data=a.corpus.read_bytes();assert sha(data)==CORPUS_SHA
    result=project(json.loads(data));assert result['accounting']['dialogues']==10 and result['accounting']['questions']==1986
    assert not a.out.exists();a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_bytes(gzip.compress((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode(),mtime=0))
    print(json.dumps(result['accounting'],indent=2))
