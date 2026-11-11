#!/usr/bin/env python3
"""Public-archive completeness and point-estimate checks, stdlib only.

This does not repeat retrieval or certify independence, answer quality, hardware qualification or journal eligibility.
Full bootstrap/sign-flip reconstruction is provided separately by audit_kernel.py/analyze_product.py.
"""
import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

PLAN='a7961cf8cde1de659c2272a664d4c936a50484c4'
SOURCE='9d17f8235508afa1cfba9e6da758f1738adfe8ea'
CORPUS='d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442'
POLICIES=['6-newest','6-server','60-newest','60-server']


def read(path):
    if str(path).endswith('.gz'):
        with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)
    return json.loads(path.read_text())


def lines(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return [json.loads(line) for line in f]


def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1024**2),b''):h.update(part)
    return h.hexdigest()


def verify(root,expected_manifest=None):
    manifest_path=root/'manifest.json'
    if expected_manifest:assert file_sha(manifest_path)==expected_manifest
    manifest=read(manifest_path)
    assert manifest['planCommit']==PLAN and manifest['measurementCodeCommit']==SOURCE
    paths=set()
    for row in manifest['files']:
        relative=Path(row['path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        assert row['path'] not in paths;paths.add(row['path'])
        p=root/relative;assert p.is_file() and p.stat().st_size==row['bytes'] and file_sha(p)==row['sha256'],row['path']
        assert row['bytes']<95*1024**2
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='manifest.json'}
    assert actual==paths,dict(missing=sorted(paths-actual),unlisted=sorted(actual-paths))
    for run in read(root/'development-checks.json')['runs']:
        path=root/'qualification/development'/run['file']
        assert file_sha(path)==run['sha256']
        trx=ET.parse(path)
        counters=trx.find('.//{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}Counters').attrib
        assert counters==run['counters']
    source=read(root/'inputs/input-receipt.json')
    assert source['corpusSha256']==CORPUS and source['planCommit']==PLAN
    q=lines(root/'inputs/eligibility.jsonl.gz');assert len(q)==500
    assert len({r['questionId'] for r in q})==500 and [r['rawIndex'] for r in q]==list(range(500))
    count=collections.Counter()
    for row in q:
        abstention='_abs' in row['questionId'];assert row['answerable']==(not abstention)
        gold=[t['id'] for t in row['turns'] if t['hasAnswer']]
        assert gold==row['markedIds'] and row['legacyMarked']==bool(gold)
        assert gold or abstention
        count['rawQuestions']+=1;count['primaryQuestions']+=not abstention;count['abstentionQuestions']+=abstention
        count['markedQuestions']+=bool(gold);count['abstentionWithMarks']+=abstention and bool(gold)
        count['markedTurns']+=len(gold);count['primaryMarkedTurns']+=len(gold) if not abstention else 0
        count['turnOccurrences']+=len(row['turns']);count['blankTurns']+=sum(t['blank'] for t in row['turns'])
        count['blankMarkedTurns']+=sum(t['blank'] and t['hasAnswer'] for t in row['turns'])
        count['plannedProductWrites']+=sum(not t['blank'] for t in row['turns'])
    for key,value in count.items():assert value==source['counts'][key],(key,value)
    assert count['primaryQuestions']==470 and count['markedQuestions']==479 and count['plannedProductWrites']==246738
    collisions=collections.Counter()
    for case in q:
        by_hash=collections.defaultdict(list)
        for turn in case['turns']:by_hash[turn['contentSha256']].append(turn)
        marked=sum(sum(t['hasAnswer'] for t in group) for group in by_hash.values()
                   if any(t['hasAnswer'] for t in group) and any(not t['hasAnswer'] for t in group))
        collisions['allMarkedTurnsWithUnmarkedExactCopy']+=marked
        collisions['allQuestionsWithCollision']+=bool(marked)
        if case['answerable']:
            collisions['primaryMarkedTurnsWithUnmarkedExactCopy']+=marked
            collisions['primaryQuestionsWithCollision']+=bool(marked)
    collision_record=read(root/'inputs/gold-content-collision.json')
    assert collision_record['inputOnly'] and not collision_record['outcomeRecordsUsed']
    assert dict(collisions)==collision_record['counts']
    answers=lines(root/'inputs/expected-answers.jsonl.gz')
    assert [r['questionId'] for r in answers]==[r['questionId'] for r in q]
    sessions=read(root/'inputs/session-dependence.json.gz');assert len(sessions)==19195
    by_session={r['id']:r for r in sessions};assert len(by_session)==len(sessions)
    assert all(s['contentVariants']==len({o['contentSha256'] for o in s['occurrences']})==1 for s in sessions)
    for row in q:
        for s in row['sessions']:
            assert any((o['rawIndex'],o['sessionPosition'],o['contentSha256'])==(row['rawIndex'],s['position'],s['contentSha256']) for o in by_session[s['id']]['occurrences'])
    overlap=read(root/'inputs/session-overlap-diagnostic.json')
    for eligible,target,expected_shared in [(set(range(500)),overlap,3932),({r['rawIndex'] for r in q if r['answerable']},overlap['primaryAnswerableFrame'],3556)]:
        parents={i:i for i in eligible}
        def find(i):
            while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
            return i
        shared=0
        for session in sessions:
            ids={o['rawIndex'] for o in session['occurrences']} & eligible
            shared+=len(ids)>1
            ids=list(ids)
            for i in ids[1:]:parents[find(i)]=find(ids[0])
        assert shared==expected_shared
        assert sorted(collections.Counter(find(i) for i in eligible).values(),reverse=True)==target['componentSizes']
    acceptance=read(root/'results/acceptance.json')
    assert acceptance['kernel']=='PASS' and acceptance['product']=='PASS'
    final_input=read(root/'execution/input-source-final-state.json')
    assert final_input['status']=='PASS' and final_input['corpusSha256']==CORPUS and final_input['unchangedDuringFinalRead']
    history=read(root/'execution/historical-files-final-check.json')
    assert history['status']=='PASS' and history['files']==read(root/'historical-input-hashes.json')
    for phase in ['build','input','qualification','kernel','product-text','kernel-independent-audit',
                  'product-independent-analysis','delivery-figure','figure-text-audit','figure-collision-audit']:
        receipt=read(root/'execution'/phase/'receipt.json')
        assert receipt['status']=='PASS' and receipt['exitCode']==0 and receipt['sourceUnchanged']
        assert receipt['codeCommit']==SOURCE and receipt['planCommit']==PLAN
        assert receipt['maxOwnedFamilyRssBytes']<=3*1024**3
        assert receipt['elapsedSeconds']<=43200 and receipt['observedCpuSeconds']<=28800
        for log in receipt['logs']:
            p=root/'execution'/phase/log['path'];assert p.stat().st_size==log['bytes'] and file_sha(p)==log['sha256']
    kernel_receipt=read(root/'results/kernel/kernel-receipt.json')
    assert kernel_receipt['markedCases']==479 and kernel_receipt['primaryCases']==470 and kernel_receipt['rawQuestions']==500
    journal=root/'results/kernel/kernel-cases.jsonl.gz'
    h=hashlib.sha256();marked_cases=[]
    with gzip.open(journal,'rb') as f:
        for line in f:h.update(line);marked_cases.append(json.loads(line))
    assert h.hexdigest()==kernel_receipt['journalSha256']
    assert len(marked_cases)==479 and sum(r['answerable'] for r in marked_cases)==470
    assert {r['questionId'] for r in marked_cases}=={r['questionId'] for r in q if r['legacyMarked']}
    legacy=read(root/'results/kernel/legacy-comparison.json')
    assert legacy['status']=='PASS' and legacy['numericalMetrics']==280 and legacy['differences']==[]
    assert legacy['legacyQuestions']==479 and legacy['tolerance']==1e-9
    assert read(root/'audit/kernel/kernel-audit.json')['status']=='PASS'
    assert read(root/'audit/independent-qualification.json')['status']=='PASS'
    qualification=read(root/'audit/qualification-reaudit.json')
    assert qualification['status']=='PASS' and qualification['actualRequests']==8 and qualification['writes']==140
    assert qualification['newServiceCalls']==qualification['newModelCalls']==0
    for row in qualification['inputFiles']:
        p=root/'qualification'/row['path']
        assert p.stat().st_size==row['bytes'] and file_sha(p)==row['sha256']
    visual=read(root/'figures/visual-review.json')
    assert visual['status']=='PASS' and not visual['independentHumanReview']
    product_receipt=read(root/'results/product/product-receipt.json')
    assert product_receipt['questions']==500 and product_receipt['captures']==2000 and product_receipt['writes']==246738
    assert product_receipt['newModelCalls']==product_receipt['gatewayAttempts']==0
    assert product_receipt['codeCommit']==SOURCE and product_receipt['planCommit']==PLAN
    summary=read(root/'results/product-summary.json');assert summary['status']=='complete-audited'
    assert summary['primaryFrame']=='answerable-v2' and summary['planCommit']==PLAN
    assert (summary['rawQuestions'],summary['primaryQuestions'],summary['captures'],summary['writes'])==(500,470,2000,246738)
    rows=[];writes=0
    for index,case in enumerate(q):
        prefix=f'question-{index:03d}'
        store=read(root/'results/product'/(prefix+'-store.json.gz'))
        expected={'ep_longmem-'+str(index)+'-'+hashlib.sha256(t['id'].encode()).hexdigest():t for t in case['turns'] if not t['blank']}
        assert len(store)==len(expected) and {r['Id'] for r in store}==set(expected)
        for item in store:
            turn=expected[item['Id']]
            assert hashlib.sha256(item['Content'].encode()).hexdigest()==turn['contentSha256'] and len(item['Content'].encode('utf-16-le'))//2==turn['utf16Length']
            assert not item['HasVector'] and item['Owner']=='test-user'
        history_writes=lines(root/'results/product'/(prefix+'-writes.jsonl.gz'));writes+=len(history_writes)
        assert len(history_writes)==len(store) and len({r['packId'] for r in history_writes})==len(store)
        for write in history_writes:
            assert 200<=write['status']<300 and hashlib.sha256(write['request']['content'].encode()).hexdigest()==expected[write['packId']]['contentSha256']
        captures=read(root/'results/product'/(prefix+'-captures.json.gz'))
        boundaries=lines(root/'results/product'/(prefix+'-raw-boundaries.jsonl.gz'))
        assert len(captures)==len(boundaries)==4 and {r['policy'] for r in captures}==set(POLICIES)
        assert len({r['storeSha256'] for r in captures})==1
        gold={i for i,t in expected.items() if t['hasAnswer']}
        for position,(r,b) in enumerate(zip(captures,boundaries)):
            assert (r['rawIndex'],r['questionId'],r['answerable'],r['legacyMarked'],r['policy'],r['position'])==(index,case['questionId'],case['answerable'],bool(gold),POLICIES[(index+position)%4],position)
            assert r['completed'] and r['completionCaptures']==b['CompletionCaptures']==1
            assert r['completionBody']==b['CompletionBody'] and r['rawSystem']==b['SystemMessage']
            assert hashlib.sha256(r['completionBody'].encode()).hexdigest()==r['completionBodySha256']
            assert hashlib.sha256(r['rawSystem'].encode()).hexdigest()==r['systemSha256']
            body=json.loads(r['completionBody']);assert [m['content'] for m in body['messages'] if m['role']=='user']==[case['question']]
            assert not [m for m in body['messages'] if m['role']=='assistant']
            assert set(r['goldIds'])==gold and r['evidence']==len(gold)
            for key,ids in [('stored',expected),('pool',r['poolIds']),('response',r['responseIds']),('kept',r['keptIds']),('planned',r['plannedIds'])]:
                assert set(ids)<=set(expected) and r[key]==len(set(ids)&gold)
            assert r['attributable']==(r['observedIds'] is not None)
            if r['observedIds'] is not None:assert set(r['observedIds'])<=set(r['plannedIds']) and r['prompt']==len(set(r['observedIds'])&gold)
            else:assert r['prompt'] is None
            assert 0<=r['promptLower']<=r['promptUpper']<=r['planned']<=r['kept']<=r['response']<=r['pool']<=r['stored']<=r['evidence']
            rows.append(r)
    assert writes==246738 and len(rows)==2000
    numerical=0
    def eq(x,y):
        nonlocal numerical
        assert math.isclose(x,y,abs_tol=1e-9,rel_tol=0),(x,y);numerical+=1
    for policy in POLICIES:
        group=sorted([r for r in rows if r['answerable'] and r['policy']==policy],key=lambda r:r['rawIndex']);assert len(group)==470
        target=summary['policies'][policy]
        for stage in ['stored','pool','response','kept','planned']:eq(target['stages'][stage]['mean'],statistics.fmean(r[stage]/r['evidence'] for r in group))
        for bound in ['Lower','Upper']:eq(target['prompt'+bound]['mean'],statistics.fmean(r['prompt'+bound]/r['evidence'] for r in group))
        eq(target['candidateToPromptLossLower']['mean'],statistics.fmean((r['pool']-r['promptUpper'])/r['evidence'] for r in group))
        eq(target['candidateToPromptLossUpper']['mean'],statistics.fmean((r['pool']-r['promptLower'])/r['evidence'] for r in group))
        assert target['unknown']==sum(not r['attributable'] for r in group)
    return dict(status='PASS',manifestFiles=len(paths),rawQuestions=500,primaryQuestions=470,markedQuestions=479,
                productWrites=writes,requestCaptures=len(rows),pointEstimatesRecomputed=numerical,
                scope='Archive identity, complete population/source/request records and point estimates; no model answer, dependence-robust population result, Mac qualification or CAS partition certification.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);parser.add_argument('--expected-manifest-sha256')
    args=parser.parse_args();print(json.dumps(verify(args.root,args.expected_manifest_sha256),indent=2))
