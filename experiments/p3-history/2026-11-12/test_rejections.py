#!/usr/bin/env python3
"""Disposable corruption checks; primary records are read only."""
import argparse,collections,copy,gzip,json,tempfile
from pathlib import Path
from audit import audit_row,check,load,lines,prompt_observe
from input_frame import ARMS,sha
from integrity import verify_hashes

def main(a):
    frame=load(a.frame);oracle=load(a.oracle);matches={(x['c'],x['query']):x['ids'] for x in oracle['entries']};constants=load(a.root/'prompt-constants.json')
    primary_hashes={str(p):sha(p.read_bytes()) for p in a.root.glob('c00-*/*') if p.is_file()};results=[]
    conv=frame['conversations'][0]
    def context(arm,q=0):
        folder=a.root/f'c00-{arm}';rows=lines(folder/'records.jsonl.gz');journal=collections.defaultdict(list)
        for e,_ in lines(folder/'journal.jsonl'):journal[e['key']].append(e)
        logical={t['id']:'source:'+t['sourceId'] for t in conv['turns']};store={'source:'+t['sourceId']:dict(content=t['content'],createdAt=t['createdAt']) for t in conv['turns']};prior=[]
        for i in range(q):audit_row(rows[i][0],conv['questions'][i],conv,arm,store,logical,prior,matches,constants,journal,rows[i][1])
        row,h=rows[q];return copy.deepcopy([row,conv['questions'][q],conv,arm,store,logical,prior,matches,constants,journal,h])
    def reject(name,fn):
        try:fn()
        except (AssertionError,KeyError,ValueError,StopIteration) as e:results.append(dict(name=name,rejected=True,reason=str(e)[:180]));return
        raise AssertionError('Corruption was accepted: '+name)
    def row_case(name,arm,mutator,q=0):
        ctx=context(arm,q);mutator(ctx);reject(name,lambda:audit_row(*ctx))
    row_case('omitted_first_turn','static',lambda x:x[0].update(q=1))
    row_case('duplicate_question_index','history',lambda x:x[0].update(q=0),1)
    row_case('omitted_question_write','record-before',lambda x:x[0].update(questionWrites=[]))
    row_case('duplicate_question_write','record-after',lambda x:x[0]['questionWrites'].append(copy.deepcopy(x[0]['questionWrites'][0])))
    def swap(x):
        key='c00/record-before/q0000';entries=x[9][key]
        end=next(e for e in entries if e['phase']=='question.record.end');turn=next(e for e in entries if e['phase']=='turn.begin')
        end['monotonicTicks']=turn['monotonicTicks']+1
    row_case('swapped_record_timing','record-before',swap)
    row_case('edited_supplied_history','history',lambda x:x[0]['historySupplied'][0].update(content='edited'),1)
    row_case('changed_query','static',lambda x:x[0]['searches'][0].update(memoryQuery='different query'))
    row_case('edited_native_candidate_pool','static',lambda x:x[0]['searches'][0].update(candidateIds=[]))
    row_case('changed_raw_response','static',lambda x:x[0]['searches'][0].update(responseBody='{"items":[]}'))
    row_case('changed_client_selection','static',lambda x:x[0]['selected'].append(dict(id='invented')))
    row_case('hidden_prompt_uncertainty','static',lambda x:x[0]['promptObservation'].update(identifiable=not x[0]['promptObservation']['identifiable']))
    def history_prompt(x):
        request=json.loads(x[0]['completionBody']);request['messages'][1]['content']='edited history';x[0]['completionBody']=json.dumps(request)
    row_case('edited_completion_history','history',history_prompt,1)
    header=constants['memoryHeader'];marker=constants['truncationMarker']
    ambiguous=prompt_observe(header+'- duplicated\n- duplicated',[dict(id='a',content='duplicated'),dict(id='b',content='duplicated')],header,marker)
    check(not ambiguous['identifiable'] and ambiguous['state']=='ambiguous-source','synthetic-ambiguity-control')
    results.append(dict(name='duplicate_text_remains_source_ambiguous',rejected=True,reason='observer retains ambiguity'))
    with tempfile.TemporaryDirectory(prefix='aijade-history-corruption-') as temporary:
        root=Path(temporary);(root/'source.py').write_text('source\n');(root/'raw.json').write_text('{}\n')
        manifest=dict(files={str(p.relative_to(root)):dict(bytes=p.stat().st_size,sha256=sha(p.read_bytes())) for p in root.iterdir()})
        verify_hashes(root,manifest)
        (root/'source.py').write_text('edited\n');reject('edited_source_hash',lambda:verify_hashes(root,manifest));(root/'source.py').write_text('source\n')
        (root/'extra.json').write_text('{}');reject('unlisted_archive_member',lambda:verify_hashes(root,manifest));(root/'extra.json').unlink()
        (root/'raw.json').write_text('{"differentCorpus":true}');reject('changed_corpus_bytes',lambda:verify_hashes(root,manifest));(root/'raw.json').write_text('{}\n')
        (root/'raw.json').unlink();reject('omitted_archive_file',lambda:verify_hashes(root,manifest))
    check(primary_hashes=={str(p):sha(p.read_bytes()) for p in a.root.glob('c00-*/*') if p.is_file()},'primary-bytes-changed')
    result=dict(status='DISPOSABLE_CORRUPTIONS_REJECTED',controls=results,primaryBytesUnchanged=True,
      scope='Checks engineering rejection behavior. Some mutations are rejected by an earlier provenance gate; no implication of independent scientific review.')
    a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(status=result['status'],controls=len(results))))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['root','frame','oracle','out']:p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
