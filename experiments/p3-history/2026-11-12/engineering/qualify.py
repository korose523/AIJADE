from pathlib import Path
import collections,copy,gzip,json,subprocess,sys
C=Path(__file__).resolve().parent;W=Path('/Users/mac/.cache/aijade-ch7-qualification-20261112/worktree');E=W/'experiments/p3-history/2026-11-12'
sys.path.insert(0,str(E))
from input_frame import project,ARMS
from audit import audit_row,lines,sha
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=W,text=True).strip();root=C/('qualification-'+commit[:7])
raw=[dict(sample_id='synthetic-history',conversation=dict(session_1_date_time='12:00 pm on 1 January, 2023',
 session_1=[dict(dia_id='D1:'+str(i),speaker='synthetic',text='quartz' if i==0 else 'quartz '+'quartz 🐟 '*800 if i==7 else 'quartz source-'+str(i)) for i in range(8)]),
 qa=[dict(question=q,answer='not sent to the runtime',evidence=['D1:1'],category=1) for q in ['quartz impossiblephase','quartz','quartz']])]
frame=project(raw);fp=C/('qualification-frame-'+commit[:7]+'.json.gz');assert not fp.exists();fp.write_bytes(gzip.compress(json.dumps(frame,ensure_ascii=False).encode(),mtime=0))
op=C/('qualification-oracle-'+commit[:7]+'.json.gz')
subprocess.run([sys.executable,str(E/'eligibility.py'),'--frame',str(fp),'--out',str(op),'--docker','/Users/mac/.local/bin/docker'],check=True,cwd=W)
oracle=json.loads(gzip.decompress(op.read_bytes()));matches={(x['c'],x['query']):x['ids'] for x in oracle['entries']}
first=lines(root/'static/records.jsonl.gz')[0][0];system=json.loads(first['completionBody'])['messages'][0]['content'];parts=system.split('\n\n')
constants=dict(persona=parts[0],expressionInstruction=parts[-2],replyInstruction=parts[-1],memoryHeader='Things you remember about the user (use only when relevant):\n',truncationMarker='\n[Truncated by the product character budget.]')
conv=frame['conversations'][0];results=[]
for arm in ARMS:
 journal=collections.defaultdict(list)
 for e,_ in lines(root/arm/'journal.jsonl'):journal[e['key']].append(e)
 logical={t['id']:'source:'+t['sourceId'] for t in conv['turns']};store={'source:'+t['sourceId']:dict(content=t['content'],createdAt=t['createdAt']) for t in conv['turns']};prior=[]
 for (row,h),expected in zip(lines(root/arm/'records.jsonl.gz'),conv['questions']):
  results.append(audit_row(row,expected,conv,arm,store,logical,prior,matches,constants,journal,h))
result=dict(status='SYNTHETIC_RAW_RECONSTRUCTION_PASS',commit=commit,rows=len(results),arms=ARMS,
 promptStates=collections.Counter(x['promptState'] for x in results),unicodeSurrogateBudgetExercised=True)
(C/('qualification-audit-'+commit[:7]+'.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
