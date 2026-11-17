"""Conditional source-template serialization bound; never a live witness."""
import ast
import hashlib
import json
from pathlib import Path
import sys

B=Path('/Volumes/Untitled/AIJADE')
R=B/'.runtime/posix/nested-20261117/worktree'
P=R/'experiments/ch7/process_lifecycle.py'
source=P.read_bytes()
assert hashlib.sha256(source).hexdigest()=='93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65'
tree=ast.parse(source)
append=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_append')
event=next(n for n in ast.walk(append) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
           and n.func.id=='dict' and any(k.arg=='schema' for k in n.keywords))
common_keys={k.arg for k in event.keywords}|{'sha256'}
data_keys={}
for node in ast.walk(tree):
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='_append' and len(node.args)==2:
        if isinstance(node.args[0],ast.Constant) and node.args[0].value in ('FINITE_REGISTER','RELEASE','WAIT'):
            d=node.args[1]
            if isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id=='dict':
                data_keys.setdefault(node.args[0].value,set()).add(tuple(sorted(k.arg for k in d.keywords)))
sys.path.insert(0,str(R/'experiments/ch7'))
import process_lifecycle as life

ident=dict(pid=999999,createTimeMicros=9999999999999999,parentPid=999999)
mono=1.2345678901234567e-100
actual_clock_chars=len(json.dumps(mono))
assert 0<mono<=1e9 and actual_clock_chars<=24
base=dict(schema=life.EVENT_SCHEMA,seq=20000,monotonicSeconds=mono,runId='c'*32,writer=ident,
          sourceCommit='a'*40,policySha256='b'*64,previousSha256='d'*64,sha256='e'*64)
records=[('FINITE_REGISTER',dict(leaseId='f'*32,role='finite',stageId='observer-native-census',identity=ident,
    parentIdentity=ident,commandSha256='a'*64,executableSha256='b'*64,readyMonotonic=mono,
    shimSha256='c'*64,identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD'),2),
    ('RELEASE',dict(leaseId='f'*32),1),
    ('WAIT',dict(leaseId='f'*32,identity=ident,exitCode=0,waitSource='Popen.wait',reapedMonotonic=mono),2)]
rows=[]
for kind,data,float_count in records:
    assert set(base)|{'event','data'}==common_keys
    assert tuple(sorted(data)) in data_keys[kind]
    raw=life.canonical(dict(base,event=kind,data=data))+b'\n'
    rows.append(dict(event=kind,actualTemplateBytes=len(raw),floatFields=float_count,
        conservative24CharacterFloatBytes=len(raw)+float_count*(24-actual_clock_chars),
        exactDataKeys=sorted(data)))
result=dict(schema='aijade.ch7.conditional-event-serialization-bound.v1',
    status='SOURCE_TEMPLATE_CONDITIONAL_BOUND_NOT_UNIVERSAL',sourcePath=str(P),sourceSha256=hashlib.sha256(source).hexdigest(),
    templateVerifiedAgainstActualAppendAst=True,serializer='Actual unchanged process_lifecycle.canonical',
    numericContextLimits=dict(maximumManagedPid=999999,maximumManagedParentPid=999999,
        maximumBirthMicros=9999999999999999,maximumEventSequence=20000,maximumMonotonicSeconds=1e9,
        maximumClockJsonTokenCharacters=24,maximumFiniteStageAsciiBytes=22),
    originalTemplateClockJsonCharacters=actual_clock_chars,records=rows,
    conservativeChainBytes=sum(r['conservative24CharacterFloatBytes'] for r in rows),
    actualAcceptanceChainMaximumBytes=2560,maximumFiniteTasks=6318,
    nonfiniteAcceptanceMaximumBytes=65536,cleanupReserveBytes=524288,journalHardCeiling=16*1024**2,
    completeAcceptanceBudgetBytes=6318*2560+65536+524288,
    scope='Numeric context and every actual finite chain must be checked after the one frozen run. Not a universal event-schema size bound, WCET, live observation or backend acceptance.',
    liveRun=False)
assert result['conservativeChainBytes']<=2560 and result['completeAcceptanceBudgetBytes']<result['journalHardCeiling']
out=B/'.research/runs/ch7-nested-20261117/audit/static-chain-bound-02.json'
with out.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps(result,indent=2))
