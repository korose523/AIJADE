"""Prepare separate exact-arithmetic repairs for statement conflicts observed on the release."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from prepare import HERE, REFERENCE, canonical, digest_file, filename, groups, js, write_json
from semantic_audit import RULES, integer, shape

AMENDMENT='03a329ecdbd5262904eb7b77e863da9819b5c400'
SPECIFICATIONS={
    'HumanEval/99':'Round a finite decimal string to the nearest integer, taking the written decimal value exactly and rounding half ties away from zero.',
    'Mbpp/267':'For a nonnegative integer n, return the exact sum of the squares of the first n positive odd integers.',
    'Mbpp/287':'For a nonnegative integer n, return the exact sum of the squares of the first n positive even integers.',
    'Mbpp/739':'For a positive integer n, return the smallest k such that the triangular number k(k+1)/2 has at least n digits.',
}


def bigint(value):
    return '('+hex(value)+'n)'


def prepare_variants(semantic, out, ports):
    out.mkdir(parents=True,exist_ok=False)
    (out/'cases').mkdir()
    ports.mkdir(parents=True,exist_ok=False)
    keys={tid:{} for tid in SPECIFICATIONS}
    with gzip.open(semantic/'semantic-cases.jsonl.gz','rt') as stream:
        for line in stream:
            row=json.loads(line)
            if row['taskId'] in keys:
                keys[row['taskId']][tuple(row['case'])]=row['status']
    inventory=[]
    versions=[]
    for tid,rows in groups(REFERENCE/'runs/attempt-02/pass-1/rows.jsonl.gz'):
        if tid not in SPECIFICATIONS:
            continue
        checks=[]
        cases=[]
        excluded=[]
        released_conflicts=0
        for line in rows:
            row=json.loads(line)
            key=(row['partition'],row['index'])
            status=keys[tid][key]
            if status=='OUTSIDE_DOMAIN':
                excluded.append(list(key))
                continue
            assert status in ['AGREES','STATEMENT_CONFLICT']
            a=shape(row['input'])
            exact=RULES[tid][1](a)
            if tid=='Mbpp/739':
                threshold=10**(integer(a[0],1)-1)
                assert (exact-1)*exact//2<threshold<=exact*(exact+1)//2
            if tid in ['Mbpp/267','Mbpp/287'] and int(a[0])<=1000:
                start=1 if tid=='Mbpp/267' else 2
                assert exact==sum((start+2*i)**2 for i in range(int(a[0])))
            args='['+(js(a[0]) if tid=='HumanEval/99' else bigint(integer(a[0])))+']'
            expected=bigint(exact)
            cases.append({'args':args,'expected':expected,'publicFloatTolerance':False})
            checks.append({'case':list(key),'inputSha256':hashlib.sha256(args.encode()).hexdigest(),
                           'expectedSha256':hashlib.sha256(expected.encode()).hexdigest(),'floatTolerance':False,
                           'releaseStatus':status})
            released_conflicts+=int(status=='STATEMENT_CONFLICT')
        ident=tid+'-exact'
        stem=filename(ident)
        statement=SPECIFICATIONS[tid]
        contract='Return an exact JavaScript BigInt. '+('The argument is a string.' if tid=='HumanEval/99' else 'The argument is a BigInt.')
        task=out/'cases'/(stem+'.json')
        task.write_text(canonical({'taskId':ident,'statement':statement,'contract':contract,'cases':cases})+'\n')
        code=ports/(stem+'.js')
        shutil.copyfile(HERE/'exact-variants'/(filename(tid)+'.js'),code)
        versions.append({'taskId':ident,'releaseTaskId':tid,'status':'EMITTED','method':'exact_arithmetic_variant','sha256':digest_file(code)})
        inventory.append({'taskId':ident,'releaseTaskId':tid,'statement':statement,'contract':contract,'planned':len(cases),
                          'projected':len(cases),'referenceRows':len(cases),'projectionCollisions':[], 'caseKeys':checks,
                          'comparisons':{'exact':len(cases)},'excludedSourceCases':excluded,'releaseConflicts':released_conflicts,
                          'taskFileSha256':digest_file(task)})
    assert len(inventory)==4
    write_json(out/'manifest.json',{'population':'exact_arithmetic_variants_4','amendmentCommit':AMENDMENT,'tasks':inventory,
                                   'semanticCaseSha256':digest_file(semantic/'semantic-cases.jsonl.gz')})
    write_json(ports/'ports.json',versions)
    print([(r['taskId'],r['planned'],r['releaseConflicts']) for r in inventory],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--semantic',type=Path,required=True)
    parser.add_argument('--pack',type=Path,required=True)
    parser.add_argument('--ports',type=Path,required=True)
    args=parser.parse_args()
    prepare_variants(args.semantic,args.pack,args.ports)
