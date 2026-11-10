"""Separate streaming recomputation of preparation counts and readiness from raw records."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path


def stable(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def json_representable(value):
    kind = value['t']
    if kind in ['none', 'str', 'bool']:
        return True
    if kind == 'int':
        return abs(int(value['v']) if 'v' in value else int(value['hex'], 16)) <= 2**53-1
    if kind == 'float':
        return math.isfinite(float.fromhex(value['hex']))
    if kind in ['tuple', 'list']:
        return all(json_representable(x) for x in value['items'])
    if kind == 'dict':
        return all(k['t'] == 'str' and json_representable(v) for k, v in value['items'])
    return False


def comparable(value):
    if value['t'] in ['cycle', 'unsupported']:
        return False
    if value['t'] == 'dict':
        return all(comparable(k) and comparable(v) for k, v in value['items'])
    return all(comparable(v) for v in value.get('items', []))


def verify(folder, summary_path):
    summary = json.loads(Path(summary_path).read_text())
    actual = {}
    for pass_id in ['1', '2']:
        root = Path(folder)/('pass-'+pass_id)
        task_runs = {r['taskId']: r for r in map(json.loads, (root/'tasks.jsonl').read_text().splitlines())}
        tasks = {}
        with gzip.open(root/'rows.jsonl.gz', 'rt') as stream:
            for line in stream:
                row = json.loads(line); task_id = row['taskId']
                if row['kind'] == 'begin':
                    assert task_id not in tasks
                    tasks[task_id] = {'dataset': row['dataset'], 'states': Counter(), 'flags': Counter(), 'types': Counter(),
                                      'count': 0, 'json': True, 'comparable': True, 'native': 'NOT_REACHED',
                                      'requirements': row['comparatorRequirements'], 'hash': hashlib.sha256()}
                t = tasks[task_id]
                if row['kind'] == 'case':
                    t['count'] += 1;t['states'][row['status']] += 1
                    t['flags'].update(row['inputFlags']+row['outputFlags'])
                    t['hash'].update((stable(row)+'\n').encode())
                    if row['status'] == 'OK':
                        t['types'][row['output']['t']] += 1
                        t['json'] &= json_representable(row['input']) and json_representable(row['output'])
                        t['comparable'] &= comparable(row['output'])
                    else:
                        t['json'] = False
                if row['kind'] == 'end':
                    t['native'] = row['nativeAssertions']['status']
                    t['hash'].update(stable(row['nativeAssertions']).encode())
        for task_id,t in tasks.items():
            t['complete'] = task_runs[task_id]['status'] == 'COMPLETE'
            if t['native'] == 'NOT_REACHED':
                t['hash'].update(stable({'status': 'NOT_REACHED'}).encode())
            t['hash'] = t['hash'].hexdigest()
        actual[pass_id] = tasks
    ledger_by_id = {r['taskId']:r for r in summary['ledger']}
    ready = Counter()
    for task_id,row in ledger_by_id.items():
        a,b=actual['1'].get(task_id),actual['2'].get(task_id)
        assert a is not None and b is not None, 'Full attempt coverage is required by this validator'
        expected=row['passes']['1']['expectedCases']
        criteria={'bothPassesComplete':a['complete'] and b['complete'],
                  'noReferenceExceptions':not a['states']['REFERENCE_EXCEPTION'] and not b['states']['REFERENCE_EXCEPTION'],
                  'nativeBaseAssertionsPass':a['native']==b['native']=='PASS',
                  'repeatSemanticsEqual':a['complete'] and b['complete'] and a['comparable'] and b['comparable'] and a['hash']==b['hash'],
                  'jsonProjectionRepresentable':a['json'] and b['json'] and a['count']==b['count']==expected,
                  'noUnresolvedComparator':not a['requirements'] and not b['requirements'] and not a['flags']['flat-float-output-needs-upstream-tolerance'] and not b['flags']['flat-float-output-needs-upstream-tolerance']}
        assert row['criteria']==criteria,(task_id,row['criteria'],criteria)
        assert row['readyAmongStaticDirect']==(row['staticClass']=='direct' and all(criteria.values()))
        ready[row['dataset']]+=int(row['readyAmongStaticDirect'])
    for dataset,s in summary['datasets'].items():
        assert s['readyAmongStaticDirect']==ready[dataset]
        for pass_id,reported in s['perPass'].items():
            cases=Counter();flags=Counter();types=Counter()
            rows=[t for t in actual[pass_id].values() if t['dataset']==dataset]
            for t in rows:cases.update(t['states']);flags.update(t['flags']);types.update(t['types'])
            assert reported['attemptedTasks']==len(rows)
            assert reported['completeTasks']==sum(t['complete'] for t in rows)
            assert reported['cases']==sum(t['count'] for t in rows)
            assert reported['referenceExceptions']==cases['REFERENCE_EXCEPTION']
            assert reported['nativeAssertionsPass']==sum(t['native']=='PASS' for t in rows)
            assert reported['nativeAssertionsFail']==sum(t['native']=='FAIL' for t in rows)
            assert reported['flags']==dict(flags) and reported['rootOutputTypes']==dict(types)
    return {'status':'PASS','taskPasses':sum(map(len,actual.values())),'readyAmongStaticDirect':dict(ready),
            'caseRows':sum(t['count'] for tasks in actual.values() for t in tasks.values()),
            'method':'Separate streaming aggregation, JSON representability and readiness derivation; no canonical/model code executed.',
            'scope':'Computational consistency, not independent semantic review or scientific acceptance.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('folder',type=Path);parser.add_argument('--summary',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();result=verify(args.folder,args.summary);args.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
