"""Artificial process/type/isolation and data-rejection checks, before corpus execution."""
import argparse
import copy
import json
from pathlib import Path

from analyze import validate_rows
from oracle_core import digest_file, js_value, read_problems
from run import execute, HERE


def problem(name, body, base=None, plus=None, test='def check(candidate):\n    assert candidate(2) == 4\n'):
    return {'task_id': name, 'prompt': '', 'canonical_solution': body, 'entry_point': 'solve',
            'base_input': base if base is not None else [[2]], 'plus_input': plus if plus is not None else [[3]],
            'test': test, 'atol': 0}


def main(args):
    assert not args.out.exists()
    args.out.mkdir(parents=True)
    checks = []

    def run_case(name, p, dataset='HumanEval+', **kwargs):
        receipt, data = execute({'dataset': dataset, 'problem': p, **kwargs.pop('payload', {})}, args.out/name, **kwargs)
        records = [json.loads(line) for line in data.splitlines()]
        return receipt, records

    def passed(name, condition):
        assert condition, name
        checks.append(name)

    p = problem('Artificial/success', 'def solve(x):\n    return x * 2\n')
    receipt, records = run_case('success', p)
    passed('ordinaryReferenceAndBaseCheck', receipt['status'] == 'COMPLETE' and records[-1]['nativeAssertions']['status'] == 'PASS')
    validated = validate_rows(records, 'HumanEval+', p)
    passed('rawInputAndCompleteCoverageValidation', validated['caseRows'] == 2)

    inf = problem('Artificial/infinity', 'def solve(x):\n    return x\n', base=[[float('inf')]], plus=[[-float('inf')]], test='def check(candidate):\n    assert candidate(float("inf")) == float("inf")\n')
    r, inf_rows = run_case('nonfinite-source-transport', inf)
    passed('nonfiniteSourcePreservedAsTypedRecords', r['status'] == 'COMPLETE' and all('nonfinite-float' in x['inputFlags'] and 'nonfinite-float' in x['outputFlags'] for x in inf_rows if x['kind'] == 'case'))
    validate_rows(inf_rows, 'HumanEval+', inf)

    order = problem('Artificial/dictionary-order', 'def solve(x):\n    return list(x.keys())\n', base=[[{'z':1,'a':2}]], plus=[[{'b':3,'a':4}]], test='def check(candidate):\n    assert candidate({"z":1,"a":2}) == ["z","a"]\n')
    r, order_rows = run_case('dictionary-input-order', order)
    order_values = [js_value(x['output']) for x in order_rows if x['kind'] == 'case']
    passed('dictionaryInputOrderRetained', r['status'] == 'COMPLETE' and order_values == [['z','a'],['b','a']])
    validate_rows(order_rows, 'HumanEval+', order)

    bad = copy.deepcopy(records); bad.pop(1)
    try:
        validate_rows(bad, 'HumanEval+', p)
    except AssertionError:
        checks.append('missingCaseRejected')
    else:
        raise AssertionError('Missing case accepted')
    bad = copy.deepcopy(records); bad.insert(1, bad[1])
    try:
        validate_rows(bad, 'HumanEval+', p)
    except AssertionError:
        checks.append('duplicateCaseRejected')
    else:
        raise AssertionError('Duplicate case accepted')
    bad = copy.deepcopy(records); bad[0]['problemSha256'] = '0'*64
    try:
        validate_rows(bad, 'HumanEval+', p)
    except AssertionError:
        checks.append('changedProblemHashRejected')
    else:
        raise AssertionError('Changed input accepted')
    fake = args.out/'wrong-corpus'; fake.mkdir();(fake/'HumanEvalPlus-v0.1.10.jsonl.gz').write_bytes(b'wrong')
    try:
        read_problems(fake)
    except AssertionError:
        checks.append('wrongCorpusDigestRejected')
    else:
        raise AssertionError('Wrong corpus accepted')

    p = problem('Artificial/assertion', 'def solve(x):\n    return x * 2\n', test='def check(candidate):\n    assert candidate(2) == 999\n')
    r, rows = run_case('native-assertion-failure', p)
    passed('nativeAssertionFailureSeparateFromReferenceCalls', r['status'] == 'COMPLETE' and rows[-1]['nativeAssertions']['status'] == 'FAIL' and all(x['status'] == 'OK' for x in rows if x['kind'] == 'case'))

    p = problem('Mbpp/2', 'def solve(a,b):\n    return type(a) is tuple and type(b) is tuple\n', base=[[[1],[2]]], plus=[[[],[]]])
    p['assertion'] = 'assert solve((1,), (2,)) is True'
    r, rows = run_case('mbpp-tuples', p, 'MBPP+')
    passed('officialTupleRestoration', r['status'] == 'COMPLETE' and all(js_value(x['output']) is True for x in rows if x['kind'] == 'case'))
    p = problem('Mbpp/124', 'def solve(a,b):\n    return [type(a).__name__,type(b).__name__]\n', base=[['1.0','2+3j']], plus=[['1.0','2+3j']])
    p['assertion'] = 'assert solve(1.0, 2+3j) == ["float", "complex"]'
    r, rows = run_case('mbpp-complex', p, 'MBPP+')
    passed('officialComplexRestoration', r['status'] == 'COMPLETE' and all(js_value(x['output']) == ['float','complex'] for x in rows if x['kind'] == 'case'))

    p = problem('Artificial/state', 'count=0\ndef solve(a):\n    global count\n    count+=1\n    a.append(7)\n    return [count,a]\n', base=[[[0]],[[0]]], plus=[[[0]]], test='def check(candidate):\n    assert candidate([0]) == [1,[0,7]]\n')
    r, rows = run_case('state-and-arguments', p)
    values=[js_value(x['output']) for x in rows if x['kind']=='case']
    passed('partitionNamespacesAndArgumentCopies', r['status']=='COMPLETE' and values==[[1,[0,7]],[2,[0,7]],[1,[0,7]]])

    p = problem('Artificial/alias', 'shared=[]\ndef solve(x):\n    shared.append(x)\n    return shared\n', base=[[1],[2]], plus=[[3]], test='def check(candidate):\n    assert candidate(9) == [9]\n')
    r, rows = run_case('aliased-return-values', p)
    values=[js_value(x['output']) for x in rows if x['kind']=='case']
    passed('upstreamEndOfPartitionReturnAliasing', r['status']=='COMPLETE' and values==[[1,2],[1,2],[3]])

    forbidden = args.out/'unrelated-private-fixture.txt'; forbidden.write_text('ARTIFICIAL_DO_NOT_READ')
    p=problem('Artificial/file','def solve(x):\n    return open('+repr(str(forbidden))+').read()\n')
    r,rows=run_case('unrelated-file-denied',p)
    passed('unrelatedFileContentDenied',r['status']=='COMPLETE' and all(x.get('error',{}).get('type')=='PermissionError' for x in rows if x['kind']=='case'))
    p=problem('Artificial/network','def solve(x):\n    import socket\n    socket.socket().connect(("127.0.0.1",9))\n    return True\n')
    r,rows=run_case('network-denied',p)
    passed('networkDenied',r['status']=='COMPLETE' and all(x.get('error',{}).get('type')=='PermissionError' for x in rows if x['kind']=='case'))
    target=args.out/'unrelated-write.txt'
    p=problem('Artificial/write','def solve(x):\n    return open('+repr(str(target))+',"w").write("not allowed")\n')
    r,rows=run_case('unrelated-write-denied',p)
    passed('unrelatedWriteDenied',r['status']=='COMPLETE' and not target.exists() and all(x.get('error',{}).get('type')=='PermissionError' for x in rows if x['kind']=='case'))
    p=problem('Artificial/loop','def solve(x):\n    while True: pass\n')
    r,rows=run_case('nontermination',p,payload={'limits':{'cpuSeconds':1}},wall_seconds=2)
    passed('nonterminationStoppedAndPartialRetained',r['status']=='INCOMPLETE' and r['exitCode']!=0 and rows and rows[0]['kind']=='begin')
    out={'status':'PASS','checks':checks,'count':len(checks),'sourceSha256':{n:digest_file(HERE/n) for n in ['run.py','worker.py','oracle_core.py']},
         'scope':'Artificial development checks only; no public benchmark program, model or held-out case executed.'}
    (args.out/'qualification.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--out',type=Path,required=True);main(parser.parse_args())
