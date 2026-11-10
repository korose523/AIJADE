"""AI-assisted checks derived from the statements of the 52 formerly blocked tasks."""
import argparse
import ast
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import gzip
import hashlib
import json
import math
import operator
from pathlib import Path

from prepare import REFERENCE, canonical, digest_file, groups, read_problems, write_json


class OutsideDomain(ValueError):
    pass


class Unresolved(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise OutsideDomain(reason)


def integer(value, low=None):
    require(type(value) is int or type(value) is float and value.is_integer(), 'integer required by the task')
    n=int(value)
    require(low is None or n>=low, f'ordinal or count below {low}')
    return n


def numeric(value):
    require(type(value) is int or type(value) is float and math.isfinite(value), 'finite numeric value required')
    return value


def numbers(values, nonempty=False):
    require(isinstance(values,(list,tuple)) and (values or not nonempty), 'numeric sequence has invalid length')
    return [numeric(v) for v in values]


def shape(value):
    kind=value['t']
    if kind=='int':
        return int(value['hex'],16) if 'hex' in value else int(value['v'])
    if kind=='float':
        return float.fromhex(value['hex'])
    if kind=='none':
        return None
    if kind in ['str','bool']:
        return value['v']
    if kind=='list':
        return [shape(x) for x in value['items']]
    if kind=='tuple':
        return tuple(shape(x) for x in value['items'])
    if kind=='dict':
        return {shape(k):shape(v) for k,v in value['items']}
    raise Unresolved('unsupported value in semantic check')


def same(a,b,real=False):
    if type(a) is bool or type(b) is bool:
        return type(a) is type(b) and a==b
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
        return len(a)==len(b) and all(same(x,y,real) for x,y in zip(a,b))
    if isinstance(a,dict) and isinstance(b,dict):
        return a.keys()==b.keys() and all(same(a[k],b[k],real) for k in a)
    if real and type(a) in [int,float] and type(b) in [int,float] and (type(a) is float or type(b) is float):
        return abs(a-b)<=1e-6+1e-7*abs(b)
    return a==b


def recurrence(n, initial):
    n=integer(n,0)
    values=list(initial)
    width=len(initial)
    while len(values)<=n:
        values.append(sum(values[-width:]))
    return values[n]


def fib_pair(n):
    if not n:
        return 0,1
    a,b=fib_pair(n//2)
    c,d=a*(2*b-a),a*a+b*b
    return (d,c+d) if n%2 else (c,d)


def prime64(n):
    if n<2:
        return False
    bases=(2,3,5,7,11,13,17,19,23,29,31,37)
    for p in bases:
        if n%p==0:
            return n==p
    if n>=2**64:
        raise Unresolved('outside the checked deterministic primality range')
    d,s=n-1,0
    while d%2==0:
        d//=2
        s+=1
    for p in bases:
        x=pow(p,d,n)
        if x in (1,n-1):
            continue
        for _ in range(s-1):
            x=x*x%n
            if x==n-1:
                break
        else:
            return False
    return True


@lru_cache(maxsize=None)
def prime_fib(rank):
    n=integer(rank,1)
    index=3
    while True:
        value=fib_pair(index)[0]
        if prime64(value):
            n-=1
            if n==0:
                return value
        index+=1


def geometric(args, scale=1):
    dims=numbers(args)
    require(all(x>=0 for x in dims), 'a geometric length is negative')
    return scale*math.prod(dims)


def sum_numbers(xs):
    return math.fsum(xs) if any(type(x) is float for x in xs) else sum(xs)


def flattened(xs):
    for x in xs:
        if type(x) is list:
            yield from flattened(x)
        else:
            yield numeric(x)


def divisors_sum(a,b):
    n=math.gcd(integer(a),integer(b))
    require(n>0,'common divisors of two zeros have no finite sum')
    return sum(d if d*d==n else d+n//d for d in range(1,math.isqrt(n)+1) if n%d==0)


def algebra(ops, xs):
    require(len(ops)>0 and len(xs)==len(ops)+1,'operator and operand counts are inconsistent')
    ints=[integer(x,0) for x in xs]
    allowed={'+','-','*','//','**'}
    require(all(op in allowed for op in ops),'operator outside the published arithmetic grammar')
    expression=''.join(str(a)+op for a,op in zip(ints,ops))+str(ints[-1])
    operations={ast.Add:operator.add, ast.Sub:operator.sub, ast.Mult:operator.mul, ast.FloorDiv:operator.floordiv, ast.Pow:operator.pow}
    def value(node):
        if isinstance(node,ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node,ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](value(node.left),value(node.right))
        raise Unresolved('arithmetic grammar boundary')
    return value(ast.parse(expression,mode='eval').body)


def kth(a,b,k):
    x,y=numbers(a),numbers(b)
    require(x==sorted(x) and y==sorted(y),'the statement specifies two sorted arrays')
    rank=integer(k,1)
    require(rank<=len(x)+len(y),'rank exceeds the combined length')
    return sorted(x+y)[rank-1]


def triangular_index(n):
    target=10**(integer(n,1)-1)
    k=(math.isqrt(8*target+1)-1)//2
    return k if k*(k+1)//2>=target else k+1


def tuple_string(value):
    try:
        parsed=ast.literal_eval(value)
    except (ValueError,SyntaxError) as exc:
        raise OutsideDomain('not a literal tuple of integers') from exc
    require(type(parsed) is tuple and all(type(x) is int for x in parsed),'not a literal tuple of integers')
    return parsed


def nearest(text):
    value=Decimal(text.strip())
    require(value.is_finite(),'nonfinite decimal text')
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


@lru_cache(maxsize=None)
def bell(n):
    if not n:
        return 1
    return sum(math.comb(n-1,k)*bell(k) for k in range(n))


def pairs(xs,target):
    xs=numbers(xs);target=numeric(target)
    seen=Counter()
    count=0
    for x in xs:
        if type(x) is float or type(target) is float:
            count+=sum(n for y,n in seen.items() if x+y==target)
        else:
            count+=seen[target-x] if not any(type(y) is float for y in seen) else sum(n for y,n in seen.items() if x+y==target)
        seen[x]+=1
    return count


def nsw_prime(args, reference):
    integer(args[0],1)
    if type(reference) is int and (reference<2 or any(reference>p and reference%p==0 for p in [2,3,5,7,11,13,17,19,23,29,31])):
        return 'STATEMENT_CONFLICT','The released result is composite or below 2 although the statement asks for a prime.'
    raise Unresolved('The release computes a sequence value. Its rank among the primes is unspecified by the examples.')


def combinations(xs,n):
    from itertools import combinations_with_replacement
    return list(combinations_with_replacement(xs,integer(n,0)))


def coordinates(xs):
    from itertools import product
    return [list(x) for x in product(*(range(integer(v)-1,integer(v)+2) for v in xs))]


# Each entry records the statement interpretation and a separate check of the released value.
RULES={
 'HumanEval/8': ('Sum and product of integer values, including empty identities.',lambda a:(sum(map(integer,a[0])),math.prod(map(integer,a[0])))),
 'HumanEval/15': ('Decimal sequence 0 through n with one space between terms.',lambda a:' '.join(map(str,range(integer(a[0],0)+1)))),
 'HumanEval/35': ('Greatest member of a nonempty numeric sequence.',lambda a:max(numbers(a[0],True))),
 'HumanEval/39': ('Positive Fibonacci-prime rank, checked by fast doubling and independent small-prime witnesses.',lambda a:prime_fib(a[0])),
 'HumanEval/41': ('Every car in one group meets each car in the other group once.',lambda a:integer(a[0],0)**2),
 'HumanEval/46': ('Four-term recurrence with initial values 0, 0, 2, 0.',lambda a:recurrence(a[0],(0,0,2,0))),
 'HumanEval/55': ('Fibonacci value with F(0)=0 and F(1)=1, checked by fast doubling.',lambda a:fib_pair(integer(a[0],0))[0]),
 'HumanEval/63': ('Three-term recurrence with initial values 0, 0, 1.',lambda a:recurrence(a[0],(0,0,1))),
 'HumanEval/83': ('Inclusion-exclusion for n-digit integers starting or ending in 1.',lambda a:1 if integer(a[0],1)==1 else 18*10**(int(a[0])-2)),
 'HumanEval/99': ('Nearest integer to exact decimal text, with half ties away from zero.',lambda a:nearest(a[0])),
 'HumanEval/106': ('One-based positions alternate triangular sums and factorials.',lambda a:[math.factorial(i) if i%2==0 else i*(i+1)//2 for i in range(1,integer(a[0],0)+1)]),
 'HumanEval/139': ('Product of factorials from 1 through positive n.',lambda a:math.prod(math.factorial(i) for i in range(1,integer(a[0],1)+1))),
 'HumanEval/142': ('Zero-based index test gives the square rule precedence over cubing.',lambda a:sum(integer(x)**(2 if i%3==0 else 3 if i%4==0 else 1) for i,x in enumerate(a[0]))),
 'HumanEval/160': ('Allowed arithmetic and precedence on the stated nonnegative integer operands.',lambda a:algebra(*a)),
 'Mbpp/14': ('Triangular prism volume from nonnegative length, base and height.',lambda a:geometric(a,.5)),
 'Mbpp/17': ('Square perimeter equals four times its nonnegative side.',lambda a:4*geometric(a)),
 'Mbpp/62': ('Minimum member of the nonempty numeric list.',lambda a:min(numbers(a[0],True))),
 'Mbpp/65': ('Sum after recursively flattening numeric lists.',lambda a:sum_numbers(list(flattened(a[0])))),
 'Mbpp/80': ('Nonnegative ordinal tetrahedral number from a binomial coefficient.',lambda a:math.comb(integer(a[0],0)+2,3)),
 'Mbpp/93': ('Real scalar exponentiation over the released finite inputs.',lambda a:operator.pow(*numbers(a))),
 'Mbpp/126': ('Exact sum of the divisors of the greatest common divisor.',lambda a:divisors_sum(*a)),
 'Mbpp/133': ('Sum of strictly negative elements.',lambda a:sum_numbers([x for x in numbers(a[0]) if x<0])),
 'Mbpp/145': ('Maximum absolute difference equals max minus min.',lambda a:max(numbers(a[0],True))-min(a[0])),
 'Mbpp/171': ('Regular pentagon perimeter equals five times the nonnegative side.',lambda a:5*geometric(a)),
 'Mbpp/227': ('Minimum of the three supplied numeric values.',lambda a:min(numbers(a))),
 'Mbpp/234': ('Cube volume from a nonnegative side.',lambda a:geometric(a)**3),
 'Mbpp/255': ('Combinations with repetition of input positions, in input order.',lambda a:combinations(*a)),
 'Mbpp/260': ('Check the published prime requirement against released sequence values.',None),
 'Mbpp/264': ('Proposed explicit convention uses 10.5 per year for the first two years and 4 thereafter.',lambda a:10.5*min(geometric(a),2)+4*max(a[0]-2,0)),
 'Mbpp/266': ('Lateral surface covers four square faces of a cube.',lambda a:4*geometric(a)**2),
 'Mbpp/267': ('Exact sum of squares of the first n positive odd integers.',lambda a:(lambda n:n*(4*n*n-1)//3)(integer(a[0],0))),
 'Mbpp/268': ('Centered hexagram number at positive ordinal n.',lambda a:(lambda n:6*n*(n-1)+1)(integer(a[0],1))),
 'Mbpp/271': ('Exact sum of fifth powers of the first n positive even integers.',lambda a:(lambda n:8*n*n*(n+1)**2*(2*n*n+2*n-1)//3)(integer(a[0],0))),
 'Mbpp/274': ('Even-index binomial sum for the specified positive exponent.',lambda a:2**(integer(a[0],1)-1)),
 'Mbpp/287': ('Exact sum of squares of the first n positive even integers.',lambda a:(lambda n:2*n*(n+1)*(2*n+1)//3)(integer(a[0],0))),
 'Mbpp/391': ('Three lists form a list of nested mappings. The proposed contract specifies truncation to the shortest list.',lambda a:[{x:{y:z}} for x,y,z in zip(*a)]),
 'Mbpp/409': ('Minimum product across the given pairs.',lambda a:min(math.prod(numbers(p)) for p in a[0])),
 'Mbpp/441': ('Cube surface covers six square faces.',lambda a:6*geometric(a)**2),
 'Mbpp/447': ('Cube every numeric element in list order.',lambda a:[x**3 for x in numbers(a[0])]),
 'Mbpp/458': ('Area from the two nonnegative rectangle dimensions.',lambda a:geometric(a)),
 'Mbpp/573': ('Multiply each distinct numeric value once.',lambda a:math.prod(set(numbers(a[0],True)))),
 'Mbpp/577': ('Last decimal digit of a nonnegative integer factorial.',lambda a:(lambda n:0 if n>=5 else math.factorial(n)%10)(integer(a[0],0))),
 'Mbpp/592': ('Vandermonde identity for products of adjacent binomial coefficients.',lambda a:(lambda n:math.comb(2*n,n-1))(integer(a[0],1))),
 'Mbpp/597': ('One-based rank in the union by concatenation of two sorted arrays.',lambda a:kth(*a)),
 'Mbpp/608': ('Bell number from the independent binomial recurrence.',lambda a:bell(integer(a[0],0))),
 'Mbpp/623': ('Apply the supplied exponent to every element in order.',lambda a:[x**numeric(a[1]) for x in numbers(a[0])]),
 'Mbpp/630': ('Cartesian product of each coordinate and its neighbors, including the center shown in the release example.',lambda a:coordinates(a[0])),
 'Mbpp/739': ('Smallest triangular index reaching the exact n-digit threshold.',lambda a:triangular_index(a[0])),
 'Mbpp/752': ('Exact Jacobsthal closed form with zero-based ordinal.',lambda a:(lambda n:(2**n-(-1)**n)//3)(integer(a[0],0))),
 'Mbpp/767': ('Count unordered pairs of distinct indices whose values sum to the target.',lambda a:pairs(*a)),
 'Mbpp/785': ('Parse a literal tuple of integers and keep the element order.',lambda a:tuple_string(a[0])),
 'Mbpp/796': ('Sum the numeric values in the dictionary.',lambda a:sum_numbers(numbers(list(a[0].values())))),
}
REAL={'Mbpp/14','Mbpp/17','Mbpp/65','Mbpp/93','Mbpp/133','Mbpp/145','Mbpp/171','Mbpp/234','Mbpp/264','Mbpp/266','Mbpp/409','Mbpp/441','Mbpp/447','Mbpp/458','Mbpp/573','Mbpp/623','Mbpp/796'}


def preview(value):
    if type(value) is int and value.bit_length()>640:
        return f'integer with {value.bit_length()} bits'
    if isinstance(value,(list,tuple,dict)) and len(value)>25:
        return f'{type(value).__name__} with {len(value)} elements'
    return repr(value)[:200]


def audit(pack,recovery,out):
    out.mkdir(parents=True,exist_ok=False)
    scope={r['taskId']:r for r in json.loads((pack/'manifest.json').read_text())['tasks'] if not r['priorReady']}
    assert set(scope)==set(RULES)
    sources={p['task_id']:p for _,p in read_problems(REFERENCE/'inputs')}
    recovered=json.loads((recovery/'summary.json').read_text())['tasks']
    summaries=[]
    with gzip.open(out/'semantic-cases.jsonl.gz','wt',encoding='utf-8') as stream:
        for task_id, lines in groups(REFERENCE/'runs/attempt-02/pass-1/rows.jsonl.gz'):
            if task_id not in scope:
                continue
            item=scope[task_id]
            if item['referenceSource']=='accepted_recovery_pass_1':
                [(tid,lines)]=list(groups(recovery/recovered[task_id]['passes'][0]['path']))
                assert tid==task_id
            rule, check=RULES[task_id]
            counts=Counter(); examples=[]; seen=set()
            for line in lines:
                row=json.loads(line)
                key=(row['partition'],row['index'])
                assert key not in seen
                seen.add(key)
                result={'taskId':task_id,'case':list(key),'typedRowSha256':hashlib.sha256(line).hexdigest()}
                try:
                    args=shape(row['input']); ref=shape(row['output'])
                    if check is None:
                        status,detail=nsw_prime(args,ref)
                        result.update(status=status,detail=detail)
                    else:
                        expected=check(args)
                        if same(ref,expected,task_id in REAL):
                            result['status']='AGREES'
                        else:
                            result.update(status='STATEMENT_CONFLICT',inputPreview=preview(args),referencePreview=preview(ref),
                                          statementResultPreview=preview(expected))
                except OutsideDomain as error:
                    result.update(status='OUTSIDE_DOMAIN',detail=str(error),inputPreview=preview(args))
                except (Unresolved,ValueError,TypeError,KeyError,ArithmeticError) as error:
                    result.update(status='UNRESOLVED',detail=str(error)[:200])
                counts[result['status']]+=1
                if result['status']!='AGREES' and len(examples)<6:
                    examples.append(result)
                stream.write(canonical(result)+'\n')
            for partition in ['base','plus']:
                for i in range(len(sources[task_id][partition+'_input'])):
                    if (partition,i) not in seen:
                        counts['MISSING_REFERENCE']+=1
                        stream.write(canonical({'taskId':task_id,'case':[partition,i],'status':'MISSING_REFERENCE'})+'\n')
            assert sum(counts.values())==item['planned']
            summaries.append({'taskId':task_id,'statementSha256':item['originalStatementSha256'],'rule':rule,
                              'counts':dict(counts),'examples':examples})
    totals=Counter()
    for task in summaries:
        totals.update(task['counts'])
    result={'review':'AI-assisted statement interpretation and independent numeric or structural checks',
            'tasks':summaries,'counts':dict(totals),'caseLedgerSha256':digest_file(out/'semantic-cases.jsonl.gz')}
    write_json(out/'semantic-summary.json',result)
    print(len(summaries),dict(totals),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--pack',type=Path,required=True)
    parser.add_argument('--recovery',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    audit(args.pack,args.recovery,args.out)
