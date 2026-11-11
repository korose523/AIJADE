#!/usr/bin/env python3
"""Independent complete-capture/source mapping audit and declared question-case inference. No model calls."""
import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from export_inputs import DATA_SHA, PLAN

POLICIES = ['6-newest', '6-server', '60-newest', '60-server']
HEADER = 'Things you remember about the user (use only when relevant):\n'
MARKER = '\n[Truncated by the product character budget.]'
SEED = 20261111
B = 10000


def load(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def lines(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return [json.loads(row) for row in f]


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def utf16(text):
    return len(text.encode('utf-16-le')) // 2


def observe(system, planned, store):
    start = system.find(HEADER)
    if start < 0:
        return 'absent', []
    texts = [store[i]['Content'] for i in planned]
    if system.find(HEADER, start + len(HEADER)) >= 0 or not planned:
        return 'unexplained-block', None
    if len(set(planned)) != len(planned) or len(set(texts)) != len(texts) or any(HEADER in t or MARKER in t for t in texts):
        return 'ambiguous-source', None
    expected = HEADER + '\n'.join('- ' + t for t in texts)
    actual = system[start:]
    if actual.startswith(expected) and (len(actual) == len(expected) or actual[len(expected)] == '\n'):
        return 'complete', list(planned)
    cut = actual.find(MARKER)
    if cut < 0 or cut >= len(expected) or not expected.startswith(actual[:cut]):
        return 'unexplained-block', None
    full, end = [], len(HEADER)
    for i, text in zip(planned, texts):
        end += (0 if not full and i == planned[0] else 1) + 2 + len(text)
        if end <= cut:
            full.append(i)
    return 'truncated', full


def summarize(product, inputs, output):
    receipt = json.loads((product/'product-receipt.json').read_text())
    assert receipt['captures'] == 2000 and receipt['writes'] == 246738 and receipt['questions'] == 500
    assert receipt['newModelCalls'] == receipt['gatewayAttempts'] == 0
    assert receipt['corpusSha256'] == DATA_SHA and receipt['planCommit'] == PLAN
    eligibility = lines(inputs/'eligibility.jsonl.gz')
    assert len(eligibility) == 500
    output.mkdir(parents=True, exist_ok=True)
    rows, source_rows = [], []
    writes_total = native_tie_cases = 0
    for index, source in enumerate(eligibility):
        assert index == source['rawIndex']
        prefix = f'question-{index:03d}'
        store_rows = load(product/(prefix+'-store.json.gz'))
        store = {r['Id']: r for r in store_rows}
        expected = {'ep_longmem-'+str(index)+'-'+sha(t['id']): t for t in source['turns'] if not t['blank']}
        assert len(store) == len(store_rows) == len(expected)
        assert store.keys() == expected.keys()
        gold = {i for i, turn in expected.items() if turn['hasAnswer']}
        assert len(gold) == len(source['markedIds'])
        for i, item in store.items():
            turn = expected[i]
            assert sha(item['Content']) == turn['contentSha256']
            assert utf16(item['Content']) == turn['utf16Length']
            assert not item['HasVector'] and item['Owner'] == 'test-user'
            assert abs(dt.datetime.fromisoformat(item['CreatedAt'].replace('Z', '+00:00')).replace(tzinfo=dt.timezone.utc).timestamp()*1000-turn['timestamp']) < 0.01
        writes = lines(product/(prefix+'-writes.jsonl.gz'))
        assert len(writes) == len(expected)
        assert len({w['packId'] for w in writes}) == len(expected)
        for write in writes:
            assert 200 <= write['status'] < 300
            assert sha(write['request']['content']) == expected[write['packId']]['contentSha256']
            assert write['sourceId'] == expected[write['packId']]['id']
            assert write['request']['event_id'] == write['packId'][3:]
            assert write['request']['timestamp'] == expected[write['packId']]['timestamp']
        writes_total += len(writes)
        captured = load(product/(prefix+'-captures.json.gz'))
        raw = lines(product/(prefix+'-raw-boundaries.jsonl.gz'))
        assert len(captured) == len(raw) == 4
        assert {r['policy'] for r in captured} == set(POLICIES)
        for position, (row, boundary) in enumerate(zip(captured, raw)):
            assert row['rawIndex'] == index and row['questionId'] == source['questionId']
            assert row['position'] == position and row['policy'] == POLICIES[(index+position) % 4]
            assert row['answerable'] == source['answerable'] and row['legacyMarked'] == source['legacyMarked']
            assert row['completed'] and row['completionCaptures'] == 1
            assert boundary['CompletionBody'] == row['completionBody'] and boundary['SystemMessage'] == row['rawSystem']
            body = json.loads(row['completionBody'])
            assert sha(row['completionBody']) == row['completionBodySha256']
            assert sha(row['rawSystem']) == row['systemSha256']
            messages = body['messages']
            assert [m['content'] for m in messages if m['role'] == 'user'] == [source['question']]
            assert not [m for m in messages if m['role'] == 'assistant']
            assert [m['content'] for m in messages if m['role'] == 'system'] == [row['rawSystem']]
            pool, returned = set(), []
            for search, witness in zip(row['searches'], row['poolQueries']):
                assert search['Status'] == 200 and search['Query'] == witness['query']
                assert search['Limit'] == int(row['policy'].split('-')[0])
                ranked = witness['nativePoolIds']; found = search['Ids']
                assert len(found) == min(search['Limit'], len(ranked)) and len(found) == len(set(found))
                assert set(found) <= set(ranked) <= store.keys()
                times = [store[i]['CreatedAt'] for i in found]
                assert times == sorted(times, reverse=True)
                if found:
                    cutoff = store[ranked[len(found)-1]]['CreatedAt']
                    assert {i for i in ranked if store[i]['CreatedAt'] > cutoff} <= set(found)
                    assert all(store[i]['CreatedAt'] >= cutoff for i in found)
                    native_tie_cases += len([i for i in ranked if store[i]['CreatedAt'] == cutoff]) > 1
                response = json.loads(search['RawBody'])['items']
                assert [r['id'] for r in response] == found
                assert all(r['content'] == store[r['id']]['Content'] for r in response)
                pool.update(ranked)
                returned.extend(i for i in found if i not in returned)
            kept = [i for i in returned if store[i]['Content'].strip().lower() != source['question'].strip().lower()]
            planned = (sorted(kept, key=lambda i: store[i]['CreatedAt'], reverse=True) if row['policy'].endswith('newest') else kept)[:5]
            assert planned == row['plannedIds'] and kept == row['keptIds'] and returned == row['responseIds'] and pool == set(row['poolIds'])
            state, observed = observe(row['rawSystem'], planned, store)
            assert state == row['state'] and state != 'unexplained-block'
            assert observed == row['observedIds']
            assert (MARKER in row['rawSystem']) == row['rawTruncationMarker']
            assert set(row['goldIds']) == gold and row['evidence'] == len(gold)
            for name, ids in [('stored', store), ('pool', pool), ('response', returned), ('kept', kept), ('planned', planned)]:
                assert row[name] == len(set(ids) & gold)
            low = len(set(observed) & gold) if observed is not None else 0
            high = low if observed is not None else len(set(planned) & gold)
            assert row['promptLower'] == low and row['promptUpper'] == high
            assert row['prompt'] == (low if observed is not None else None)
            row['recall'] = {k: row[k]/len(gold) if gold else None for k in ['stored', 'pool', 'response', 'kept', 'planned', 'promptLower', 'promptUpper']}
            rows.append(row)
        source_rows.append(dict(rawIndex=index, questionId=source['questionId'], writes=len(writes), captures=4, markedTurns=len(gold),
                                answerable=source['answerable'], maxTurnUtf16=max((t['utf16Length'] for t in source['turns']), default=0)))
    assert writes_total == 246738 and len(rows) == 2000
    groups = {p: sorted([r for r in rows if r['policy'] == p and r['answerable']], key=lambda r:r['rawIndex']) for p in POLICIES}
    assert all(len(g)==470 for g in groups.values())
    assert all(all(r['evidence'] > 0 for r in g) for g in groups.values())
    rng = np.random.Generator(np.random.PCG64(SEED))
    sample = rng.integers(0, 470, size=(B,470), dtype=np.int32)
    signs = rng.integers(0,2,size=(B,470),dtype=np.int8)*2-1
    np.savez_compressed(output/'resampling.npz', indices=sample, signs=signs)
    def estimate(v):
        v=np.asarray(v, dtype=np.float64)
        return dict(mean=float(v.mean()), ci95=[float(q) for q in np.quantile(v[sample].mean(axis=1), [.025,.975], method='linear')])
    policies = {}
    for p,g in groups.items():
        low=np.array([r['recall']['promptLower'] for r in g]);high=np.array([r['recall']['promptUpper'] for r in g])
        pool=np.array([r['recall']['pool'] for r in g])
        policies[p]=dict(questions=470, stages={s:estimate([r['recall'][s] for r in g]) for s in ['stored','pool','response','kept','planned']},
                         promptLower=estimate(low), promptUpper=estimate(high), candidateToPromptLossLower=estimate(pool-high), candidateToPromptLossUpper=estimate(pool-low),
                         unknown=sum(not r['attributable'] for r in g), truncated=sum(r['rawTruncationMarker'] for r in g),
                         consecutiveLosses={f'{a}-{b}':estimate([r['recall'][a]-r['recall'][b] for r in g]) for a,b in [('stored','pool'),('pool','response'),('response','kept'),('kept','planned')]},
                         assemblyLossLower=estimate(np.array([r['recall']['planned'] for r in g])-high),
                         assemblyLossUpper=estimate(np.array([r['recall']['planned'] for r in g])-low))
    contrasts=[]
    for name, coeff in [('server-order-at-6',{'6-server':1,'6-newest':-1}),('widen-server-response',{'60-server':1,'6-server':-1}),
                        ('limit-by-order-interaction',{'60-server':1,'60-newest':-1,'6-server':-1,'6-newest':1})]:
        lower=sum(w*np.array([r['recall']['promptLower' if w>0 else 'promptUpper'] for r in groups[p]]) for p,w in coeff.items())
        upper=sum(w*np.array([r['recall']['promptUpper' if w>0 else 'promptLower'] for r in groups[p]]) for p,w in coeff.items())
        identified=bool(np.array_equal(lower,upper))
        c=dict(key=name, coefficients=coeff, lower=estimate(lower), upper=estimate(upper), pointIdentified=identified, signFlipP=None, holmP=None)
        if identified:
            obs=abs(lower.mean());extreme=int((np.abs((signs*lower).mean(axis=1))>=obs-1e-12).sum());c['signFlipP']=(extreme+1)/(B+1)
        contrasts.append(c)
    cumulative=0
    for i,c in enumerate(sorted(contrasts,key=lambda c:c['signFlipP'] if c['signFlipP'] is not None else 1)):
        if c['signFlipP'] is not None:
            cumulative=max(cumulative,min(1,(3-i)*c['signFlipP']));c['holmP']=cumulative
    sensitivities={}
    for frame,predicate in [('legacy-marked-v1',lambda r:r['legacyMarked']),('all-questions-v1',lambda r:True)]:
        sensitivities[frame]={p:dict(questions=len(g:=[r for r in rows if r['policy']==p and predicate(r)]),
                                      nonnullDenominators=sum(r['evidence']>0 for r in g), nullDenominators=sum(r['evidence']==0 for r in g),
                                      promptLowerMean=float(np.mean([r['recall']['promptLower'] for r in g if r['evidence']])),
                                      promptUpperMean=float(np.mean([r['recall']['promptUpper'] for r in g if r['evidence']]))) for p in POLICIES}
    summary=dict(schema='aijade.p3.longmemeval.product.analysis.v2', status='complete-audited',planCommit=PLAN, primaryFrame='answerable-v2',
                 rawQuestions=500, primaryQuestions=470, captures=2000,writes=writes_total,policies=policies,contrasts=contrasts,sensitivities=sensitivities,
                 states=collections.Counter(r['state'] for r in rows),nativeTiedCutoffSearches=native_tie_cases,
                 resampling=dict(unit='question case conditional on compiled history',algorithm='NumPy PCG64; bootstrap indices then sign assignments; linear percentile',seed=SEED,draws=B,numpy=np.__version__),
                 limitations='Source sessions overlap between histories. No independent-user population, dense/external second-corpus result, model answer or semantic answer-loss claim.')
    (output/'product-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    with gzip.open(output/'case-recall-ledger.jsonl.gz','xt',encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps({k:r[k] for k in ['rawIndex','questionId','policy','answerable','legacyMarked','evidence','recall','state','attributable','rawTruncationMarker']},ensure_ascii=False)+'\n')
    (output/'complete-source-audit.json').write_text(json.dumps(source_rows,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['status','rawQuestions','primaryQuestions','captures','writes','states']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--product',type=Path,required=True);parser.add_argument('--inputs',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();summarize(args.product,args.inputs,args.out)
