"""Check literal examples in the released task statements against overlapping reference cases."""
import argparse
import ast
from collections import Counter
import doctest
import hashlib
import json
from pathlib import Path

from prepare import REFERENCE, canonical, groups, read_problems, source_statement, typed_flags, write_json
from semantic_audit import same, shape
from oracle_core import typed


def literal_call(node, entry):
    if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id!=entry or node.keywords:
        raise ValueError('example is not a direct literal call')
    return [ast.literal_eval(x) for x in node.args]


def examples(doc, entry):
    accepted=[]
    skipped=0
    try:
        doctests=doctest.DocTestParser().get_examples(doc)
    except ValueError:
        doctests=[]
        skipped+=1
    for example in doctests:
        try:
            args=literal_call(ast.parse(example.source.strip(),mode='eval').body,entry)
            want=ast.literal_eval(example.want.strip())
            accepted.append((args,want,'doctest',example.lineno+1))
        except (SyntaxError,ValueError):
            skipped+=1
    for index,line in enumerate(doc.splitlines(),1):
        if not line.strip().startswith('assert '):
            continue
        try:
            assertion=ast.parse(line.strip()).body[0].test
            if not isinstance(assertion,ast.Compare) or len(assertion.ops)!=1 or not isinstance(assertion.ops[0],ast.Eq):
                raise ValueError('nonliteral comparison')
            args=literal_call(assertion.left,entry)
            want=ast.literal_eval(assertion.comparators[0])
            accepted.append((args,want,'assertion',index))
        except (SyntaxError,ValueError):
            skipped+=1
    return accepted,skipped


def digest_args(value):
    return hashlib.sha256(canonical(typed(list(value))[0]).encode()).hexdigest()


def audit(pack,out):
    inventory={r['taskId']:r for r in json.loads((pack/'manifest.json').read_text())['tasks']}
    problem={p['task_id']:p for _,p in read_problems(REFERENCE/'inputs')}
    records=[]
    for tid, lines in groups(REFERENCE/'runs/attempt-02/pass-1/rows.jsonl.gz'):
        if tid not in inventory:
            continue
        p=problem[tid]
        fn,text,original=source_statement(p)
        assert text==inventory[tid]['statement'] and text and not any(s.strip().startswith(('assert ','>>>')) for s in text.splitlines())
        extracted,unsupported=examples(original,p['entry_point'])
        by_input={}
        for args,want,kind,position in extracted:
            key=digest_args(args)
            by_input.setdefault(key,[]).append({'kind':kind,'line':position,'expected':want,'matches':[]})
        if by_input:
            for line in lines:
                row=json.loads(line)
                if row['status']!='OK':
                    continue
                args=shape(row['input'])
                key=digest_args(args)
                if key not in by_input:
                    continue
                actual=shape(row['output'])
                for ex in by_input[key]:
                    ex['matches'].append({'case':[row['partition'],row['index']],
                                          'agrees':same(actual,ex['expected'],type(ex['expected']) is float)})
        projected=[]
        for key,entries in by_input.items():
            for entry in entries:
                projected.append({'inputSha256':key,'kind':entry['kind'],'line':entry['line'],'matches':entry['matches']})
        positional=len(fn.args.args)+len(fn.args.posonlyargs)
        required=positional-len(fn.args.defaults)
        arity_mismatches=[{'case':[part,i],'arity':len(a)} for part in ['base','plus'] for i,a in enumerate(p[part+'_input'])
                         if len(a)<required or not fn.args.vararg and len(a)>positional]
        records.append({'taskId':tid,'statementSha256':inventory[tid]['originalStatementSha256'],
                        'arityMismatches':arity_mismatches,'literalExamples':len(extracted),
                        'unsupportedExamples':unsupported,'matches':projected})
    counts=Counter()
    for r in records:
        counts['literalExamples']+=r['literalExamples']
        counts['unsupportedExamples']+=r['unsupportedExamples']
        counts['arityMismatches']+=len(r['arityMismatches'])
        for ex in r['matches']:
            counts['matchedExamples' if ex['matches'] else 'unmatchedExamples']+=1
            counts['exampleCaseAgreements']+=sum(m['agrees'] for m in ex['matches'])
            counts['exampleCaseConflicts']+=sum(not m['agrees'] for m in ex['matches'])
    write_json(out,{'scope':'Literal statement examples and released positional arity',
                    'taskCount':len(records),'counts':dict(counts),'tasks':records})
    print(dict(counts),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--pack',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    audit(args.pack,args.out)
