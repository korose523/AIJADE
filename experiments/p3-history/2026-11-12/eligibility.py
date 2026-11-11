#!/usr/bin/env python3
"""Independent PostgreSQL ILIKE oracle over frozen source and all possible question texts.

Only temporary tables in the existing development DB; no product records changed.
Result is an eligibility map, not measured retrieval or a gold-conditioned scorer.
"""
import argparse,csv,gzip,io,json,subprocess,unicodedata
from pathlib import Path
from input_frame import sha

def terms(text):
    words=[];word=''
    for ch in text+' ':
        if unicodedata.category(ch)[0] in ['L','N']:word+=ch
        else:
            if len(word)>=3 and word.lower() not in words:words.append(word.lower())
            word=''
    return sorted(words,key=lambda w:-len(w.encode('utf-16-le'))//2)[:3]
def copy(table,rows):
    stream=io.StringIO();writer=csv.writer(stream,lineterminator='\n');writer.writerows(rows)
    return 'COPY '+table+" FROM STDIN WITH (FORMAT csv);\n"+stream.getvalue()+"\\.\n"
def main(a):
    assert not a.out.exists()
    frame=json.loads(gzip.decompress(a.frame.read_bytes()));texts=[];queries=[];keys=[]
    for conv in frame['conversations']:
        c=conv['c'];texts += [(c,'source:'+t['sourceId'],t['content']) for t in conv['turns']]
        texts += [(c,'question:'+f"{q['q']:04d}",q['question']) for q in conv['questions']]
        unique=list(dict.fromkeys(s.strip() for q in conv['questions'] for s in [q['question']]+terms(q['question'])))
        for q in unique:keys.append([c,q]);queries.append((len(keys)-1,c,q))
    sql="BEGIN; CREATE TEMP TABLE texts(c int,id text,content text); CREATE TEMP TABLE queries(n int,c int,q text);\n"
    sql+=copy('texts',texts)+copy('queries',queries)
    sql+="SELECT json_build_object('n',q.n,'ids',COALESCE(json_agg(t.id ORDER BY t.id) FILTER (WHERE t.id IS NOT NULL),'[]'::json)) FROM queries q LEFT JOIN texts t ON t.c=q.c AND t.content ILIKE '%' || q.q || '%' GROUP BY q.n ORDER BY q.n;\nROLLBACK;\n"
    proc=subprocess.run([str(a.docker),'exec','-i','aijade-next-db','psql','-qAt','-U','aijade','-d','aijade','-v','ON_ERROR_STOP=1'],input=sql,capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    matches=[json.loads(s) for s in proc.stdout.splitlines()];assert len(matches)==len(keys)
    result=dict(schema='aijade.p3.native-ilike-oracle.v1',frameSha256=sha(a.frame.read_bytes()),
      sqlSha256=sha(sql.encode()),texts=len(texts),queries=len(keys),entries=[dict(c=keys[x['n']][0],query=keys[x['n']][1],ids=x['ids']) for x in matches],
      semantics='PostgreSQL native ILIKE over temporary tables on the same local server; all future questions are projected, then per-turn eligibility is independently filtered by audited write chronology.')
    a.out.write_bytes(gzip.compress((json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n').encode(),mtime=0))
    print(json.dumps({k:v for k,v in result.items() if k!='entries'}))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['frame','out','docker']:p.add_argument('--'+key,type=Path,required=True)
    main(p.parse_args())
