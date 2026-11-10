"""Project accepted typed references and build a separate JavaScript statement inventory."""
import argparse
import ast
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from compile_ports import Compiler, Unsupported, js

HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parents[1]/'reference-oracles/2026-11-10'
sys.path.insert(0, str(REFERENCE))
from oracle_core import canonical, digest_file, read_problems

CLARIFICATIONS = {
    'Mbpp/255': 'Treat the positions in the input list as distinct and enumerate combinations in nondecreasing position order.',
    'Mbpp/264': 'For the first two years use 10.5 dog years per human year. For additional years use four dog years per human year.',
    'Mbpp/391': 'Return one nested mapping for each position up to the shortest list. The first list supplies the outer key, the second the inner key, and the third the value.',
    'Mbpp/597': 'Use one-based rank.',
    'Mbpp/630': 'In each dimension take the input coordinate minus one, the coordinate, and the coordinate plus one. Return their Cartesian product in that order, including the center.',
    'Mbpp/767': 'Count unordered pairs of distinct positions, including different pairs with the same values.',
}


def filename(task_id):
    return task_id.replace('/', '-')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2)+'\n')


def source_statement(problem):
    tree = ast.parse(problem['prompt']+problem['canonical_solution'])
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name==problem['entry_point'])
    doc = ast.get_docstring(fn) or ast.get_docstring(tree) or ''
    lines = []
    in_example = False
    for line in doc.splitlines():
        s=line.strip()
        if re.match(r'(?i)^(?:notes?|constraints?|assumptions?)\s*:', s):
            in_example=False
        if s.startswith('>>>') or re.match(r'(?i)^(?:examples?|for example)\s*:', s):
            in_example=True
        if s.startswith('assert ') or in_example:
            continue
        lines.append(line)
    description=re.sub(r'(?i)\b(?:python|jsthon) function\b','JavaScript function','\n'.join(lines).strip())
    if problem['task_id'] in CLARIFICATIONS:
        description+='\n'+CLARIFICATIONS[problem['task_id']]
    return fn, description, doc


def typed_flags(value):
    kind = value['t']
    if kind == 'int' and 'hex' in value:
        yield 'unsafe-int'
    if kind == 'dict':
        for key, item in value['items']:
            if key['t'] != 'str':
                yield 'nonstring-key'
            elif re.fullmatch(r'0|[1-9][0-9]{0,9}', key['v']) and int(key['v']) < 2**32-1:
                yield 'index-key'
            yield from typed_flags(key)
            yield from typed_flags(item)
    elif kind in ['list', 'tuple']:
        for item in value['items']:
            yield from typed_flags(item)


def project(value, contract):
    kind=value['t']
    if kind=='int':
        if contract['bigint']:
            return '('+value.get('v',value.get('hex',''))+'n)'
        if 'hex' in value:
            raise ValueError('unsafe Number projection')
        return value['v']
    if kind=='float':
        n=float.fromhex(value['hex'])
        if not math.isfinite(n):
            raise ValueError('nonfinite Number')
        if abs(n)<2**53 and n.is_integer() and not (n==0 and math.copysign(1,n)<0):
            return str(int(n))
        return js(n)
    if kind=='none':
        return 'null'
    if kind in ['bool','str']:
        return js(value['v'])
    if kind in ['list','tuple']:
        items='['+','.join(project(x,contract) for x in value['items'])+']'
        return '{$tuple:'+items+'}' if kind=='tuple' and contract['tuples'] else items
    if kind=='dict':
        pairs=value['items']
        if contract['entries']:
            return '{$entries:['+','.join('['+project(k,contract)+','+project(v,contract)+']' for k,v in pairs)+']}'
        if any(k['t']!='str' for k,_ in pairs):
            raise ValueError('unprojectable dictionary key')
        return '{'+','.join('['+js(k['v'])+']:'+project(v,contract) for k,v in pairs)+'}'
    raise ValueError('unprojectable '+kind)


def float_case(value):
    return value['t']=='float' or (value['t'] in ['list','tuple'] and bool(value['items'])
                                  and all(x['t']=='float' for x in value['items']))


def groups(path):
    task_id=None
    rows=[]
    with gzip.open(path,'rb') as stream:
        for line in stream:
            # The canonical writer sorts fields, so kind identifies boundaries without loading large value trees.
            marker = re.search(rb'"kind":"(begin|case|end)"',line)
            if marker is None:
                raise ValueError('invalid record boundary')
            if marker[1]==b'begin':
                if task_id is not None:
                    yield task_id, rows
                task_id=json.loads(line)['taskId']
                rows=[]
            elif marker[1]==b'case':
                rows.append(line)
        if task_id is not None:
            yield task_id,rows


def mode_for(problem, rows, prior):
    typenames=set()
    for node in ast.walk(ast.parse(problem['prompt']+problem['canonical_solution'])):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id=='isinstance':
            typenames.update(n.id for n in ast.walk(node.args[1]) if isinstance(n,ast.Name))
        if isinstance(node,ast.Compare) and isinstance(node.left,ast.Call) and isinstance(node.left.func,ast.Name) and node.left.func.id=='type':
            typenames.update(n.id for arg in node.comparators for n in ast.walk(arg) if isinstance(n,ast.Name))
    flags=set(prior['passes']['1']['flags']) | set(prior['passes']['2']['flags'])
    index_keys=False
    # Only input key ordering needs a separate projection for ordinary string keys.
    for line in rows:
        if b'"t":"dict"' in line and 'index-key' in set(typed_flags(json.loads(line)['input'])):
            index_keys=True
            break
    decimal_digits=problem['task_id']=='HumanEval/83'
    return {'bigint': not decimal_digits and ('integer-outside-js-exact-range' in flags or 'int' in typenames or 'type' in typenames
                      or problem['task_id'] in ['Mbpp/222', 'HumanEval/151', 'Mbpp/390', 'Mbpp/421']),
            'tuples': 'tuple' in typenames or problem['task_id']=='Mbpp/222',
            'entries': 'nonstring-dict-key' in flags or index_keys,'decimalDigits':decimal_digits}


def contract_text(fn, mode, has_tolerance):
    names=', '.join(a.arg for a in fn.args.args)
    lines=[f'Arguments are provided in this order ({names}).',
           'Integer values use JavaScript BigInt throughout, including integer leaves of arrays and records. Real values use Number.' if mode['bigint']
           else 'Numeric values use finite JavaScript Number values.']
    lines.append('Tuples are records with a `$tuple` array. Lists are arrays.' if mode['tuples'] else 'Lists and tuples are arrays.')
    if mode['entries']:
        lines.append('Dictionaries are records with a `$entries` array of ordered key/value pairs.')
    if mode['decimalDigits']:
        lines.append('Return the exact count as a decimal digit string without leading zeros.')
    if has_tolerance:
        lines.append('Finite scalar and flat real-array outputs are checked with absolute tolerance 1e-6 and relative tolerance 1e-7 on the designated cases.')
    return ' '.join(lines)


def prepare(out, recovery):
    out.mkdir(parents=True, exist_ok=False)
    (out/'cases').mkdir()
    prior=json.loads((REFERENCE/'summary.json').read_text())
    direct={r['taskId']:r for r in prior['ledger'] if r['staticClass']=='direct'}
    assert len(direct)==425 and sum(not r['readyAmongStaticDirect'] for r in direct.values())==52
    receipt=json.loads((REFERENCE/'receipt.json').read_text())
    old_path='runs/attempt-02/pass-1/rows.jsonl.gz'
    assert digest_file(REFERENCE/old_path)==receipt['artifactSha256'][old_path]
    recovered=json.loads((recovery/'summary.json').read_text())['tasks']
    problems={p['task_id']:(dataset,p) for dataset,p in read_problems(REFERENCE/'inputs')}
    inventory=[]
    for tid, rows in groups(REFERENCE/old_path):
        if tid not in direct:
            continue
        dataset,p=problems[tid]
        before=direct[tid]
        accepted_recovery=recovered.get(tid,{}).get('accepted',False)
        ref_source='accepted_reference_pass_1'
        if accepted_recovery:
            item=recovered[tid]['passes'][0]
            path=recovery/item['path']
            assert digest_file(path)==item['streamSha256']
            [(actual_id, all_rows)]=list(groups(path))
            assert actual_id==tid and all_rows[:len(rows)]==rows
            rows=all_rows
            ref_source='accepted_recovery_pass_1'
        mode=mode_for(p,rows,before)
        fn,statement,original=source_statement(p)
        task_path=out/'cases'/(filename(tid)+'.json')
        keys=[]
        observed=set()
        excluded=[]
        comparisons=Counter()
        seen={}
        collisions=[]
        case_rows=[]
        for line in rows:
            row=json.loads(line)
            key=[row['partition'],row['index']]
            assert tuple(key) not in observed
            observed.add(tuple(key))
            try:
                if row['status']!='OK':
                    raise ValueError(row['status'])
                if before['passes']['1']['comparatorRequirements']:
                    raise ValueError('special comparator')
                assert row['input']['t'] in ['list','tuple']
                arg='['+','.join(project(x,mode) for x in row['input']['items'])+']'
                if mode['decimalDigits']:
                    n=int(row['input']['items'][0]['v'])
                    value=row['output']
                    assert n>=1 and value['t']=='int'
                    exact=int(value['hex'],16) if 'hex' in value else int(value['v'])
                    assert exact==(1 if n==1 else 18*10**(n-2))
                    expected=js('1' if n==1 else '18'+'0'*(n-2))
                else:
                    expected=project(row['output'],mode)
                tolerance=float_case(row['output'])
            except ValueError as error:
                excluded.append({'case':key,'reason':str(error)})
                continue
            input_sha=hashlib.sha256(arg.encode()).hexdigest()
            output_sha=hashlib.sha256(expected.encode()).hexdigest()
            if input_sha in seen and seen[input_sha][0]!=output_sha:
                collisions.append({'case':key,'earlierCase':seen[input_sha][1],'inputSha256':input_sha})
            seen.setdefault(input_sha,(output_sha,key))
            keys.append({'case':key,'inputSha256':input_sha,'expectedSha256':output_sha,'floatTolerance':tolerance})
            case_rows.append({'args':arg,'expected':expected,'publicFloatTolerance':tolerance})
            comparisons['float' if tolerance else 'exact']+=1
        total=sum(len(p[part+'_input']) for part in ['base','plus'])
        missing=[[part,i] for part in ['base','plus'] for i in range(len(p[part+'_input'])) if (part,i) not in observed]
        assert len(missing)+len(excluded)+len(keys)==total
        contract=contract_text(fn,mode,bool(comparisons['float']))
        task_path.write_text(canonical({'taskId':tid,'statement':statement,'contract':contract,'cases':case_rows})+'\n')
        inventory.append({'taskId':tid,'dataset':dataset,'priorReady':before['readyAmongStaticDirect'],
            'priorBlockedBy':[key for key,val in before['criteria'].items() if not val],
            'originalStatementSha256':hashlib.sha256(original.encode()).hexdigest(),
            'statement':statement,'contract':contract,'mode':mode,'referenceSource':ref_source,
            'planned':total,'referenceRows':len(rows),'projected':len(keys),'unprojectable':excluded,'missingCases':missing,
            'caseKeys':keys,'comparisons':dict(comparisons),'projectionCollisions':collisions,
            'taskFileSha256':digest_file(task_path)})
    assert set(r['taskId'] for r in inventory)==set(direct)
    write_json(out/'manifest.json',{'population':'static_direct_425','tasks':inventory,'outsideDirect':sorted(set(problems)-set(direct)),
                                  'referenceSummarySha256':digest_file(REFERENCE/'summary.json')})
    print('Prepared',len(inventory),'tasks and',sum(r['projected'] for r in inventory),'projected cases',flush=True)


def make_ports(pack, out):
    out.mkdir(parents=True,exist_ok=False)
    rows=json.loads((pack/'manifest.json').read_text())['tasks']
    problems={p['task_id']:p for _,p in read_problems(REFERENCE/'inputs')}
    provenance=[]
    for row in rows:
        tid=row['taskId']; problem=problems[tid]
        origin=problem['prompt']+problem['canonical_solution']
        override=HERE/'overrides'/(filename(tid)+'.js')
        identity={'taskId':tid,'pythonSourceSha256':hashlib.sha256(origin.encode()).hexdigest()}
        try:
            if override.exists():
                code=override.read_text()
                method='individual_javaScript_port'
            else:
                code=Compiler().program(origin,problem['entry_point'])
                code+='const solve = $p.wrap($entry, '+js(row['mode'])+');\n'
                method='source_derived_javaScript_port'
        except (Unsupported,KeyError) as error:
            provenance.append({**identity,'status':'UNSUPPORTED','reason':str(error)})
            continue
        dest=out/(filename(tid)+'.js')
        dest.write_text(code)
        provenance.append({**identity,'status':'EMITTED','method':method,'sha256':digest_file(dest)})
    write_json(out/'ports.json',provenance)
    print('Emitted',sum(r['status']=='EMITTED' for r in provenance),'ports of',len(rows),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--pack',type=Path,required=True)
    parser.add_argument('--recovery',type=Path)
    parser.add_argument('--ports',type=Path,required=True)
    args=parser.parse_args()
    if args.recovery:
        prepare(args.pack,args.recovery)
    make_ports(args.pack,args.ports)
