"""Bounded offline snapshot-cost probe; no collector, API or new workload window."""
from pathlib import Path
import copy
import cProfile
import gc
import hashlib
import io
import json
import marshal
import math
import pstats
import statistics
import sys
import time
from datetime import datetime, timezone

B=Path('/Volumes/Untitled/AIJADE')
I=Path(__file__).parent
W=B/'.runtime/posix/nested-20261117/worktree'
R=B/'.runtime/posix/runs/ch7-nested-20261117/engineering-01'
OUT=I/'cursor-clone-probe-01'
LIFE_SHA='93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65'
source=W/'experiments/ch7/process_lifecycle.py'
assert hashlib.sha256(source.read_bytes()).hexdigest()==LIFE_SHA
sys.path.insert(0,str(source.parent))
import process_lifecycle as life

KEYS=('leases','discovered','scopes','launchRefusals','launchRefusalArtifacts',
      'runId','sourceCommit','policySha256','lastSequence','bytes','sha256')


def builtin_only(value):
    """Reject unsupported subtypes/code/sets/cycles before any local marshal load."""
    completed=set();active=set()
    def visit(item):
        kind=type(item)
        if kind in (type(None),bool,int,str):return
        if kind is float:
            if not math.isfinite(item):raise ValueError('nonfinite state')
            return
        if kind not in (dict,list,tuple):raise ValueError('unsupported state type')
        ident=id(item)
        if ident in active:raise ValueError('cyclic state')
        if ident in completed:return
        active.add(ident)
        if kind is dict:
            for key,value in item.items():visit(key);visit(value)
        else:
            for value in item:visit(value)
        active.remove(ident);completed.add(ident)
    visit(value)


def checked_marshal(value):
    builtin_only(value)
    return marshal.loads(marshal.dumps(value,4))


def same(a,b,seen=None):
    if type(a) is not type(b):return False
    if seen is None:seen=set()
    if type(a) in (dict,list,tuple):
        pair=(id(a),id(b))
        if pair in seen:return True
        seen.add(pair)
    if type(a) is dict:
        return set(a)==set(b) and all(same(a[k],b[k],seen) for k in a)
    if type(a) in (list,tuple):return len(a)==len(b) and all(same(x,y,seen) for x,y in zip(a,b))
    return a==b


def detached_mutable_graph(a,b):
    mapping={};reverse={};pairs=set();input_ids=set();output_ids=set()
    def visit(x,y):
        assert type(x) is type(y)
        kind=type(x)
        if kind not in (dict,list,tuple):return
        pair=(id(x),id(y))
        if pair in pairs:return
        pairs.add(pair)
        if kind in (dict,list):
            assert mapping.get(id(x),id(y))==id(y) and reverse.get(id(y),id(x))==id(x)
            mapping[id(x)]=id(y);reverse[id(y)]=id(x)
            input_ids.add(id(x));output_ids.add(id(y))
        if kind is dict:
            assert list(x)==list(y)
            for key in x:visit(x[key],y[key])
        else:
            for left,right in zip(x,y):visit(left,right)
    visit(a,b)
    assert input_ids.isdisjoint(output_ids)
    return len(input_ids)


def synthetic(base):
    events=[json.loads(line) for line in base.splitlines()]
    register=next(e for e in events if e['event']=='FINITE_REGISTER')
    root=events[0]['writer'];parts=[base];size=len(base)
    previous=events[-1]['sha256'];seq=events[-1]['seq'];origin=events[-1]['monotonicSeconds']+1
    checkpoints={};number=0;maximum=16252928
    while True:
        number+=1;lease=('%032x'%(0x700000+number));pid=300000+number
        identity=dict(pid=pid,createTimeMicros=root['createTimeMicros']+10000+number,parentPid=root['pid'])
        stamp=origin+number*.01
        data=copy.deepcopy(register['data'])
        data.update(leaseId=lease,identity=identity,parentIdentity=root,stageId='snapshot-probe',readyMonotonic=stamp-.001)
        definitions=[('FINITE_REGISTER',data,stamp),('RELEASE',dict(leaseId=lease),stamp+.001),
            ('WAIT',dict(leaseId=lease,identity=identity,exitCode=0,waitSource='Popen.wait',reapedMonotonic=stamp+.002),stamp+.003)]
        raw=[];next_previous=previous
        for name,data,mono in definitions:
            event=dict(schema=life.EVENT_SCHEMA,seq=seq+len(raw)+1,event=name,monotonicSeconds=mono,
                runId=events[0]['runId'],writer=root,sourceCommit=events[0]['sourceCommit'],
                policySha256=events[0]['policySha256'],data=data,previousSha256=next_previous)
            event['sha256']=life.digest(life.canonical(event));raw.append(life.canonical(event)+b'\n')
            next_previous=event['sha256']
        addition=b''.join(raw)
        if size+len(addition)>maximum:break
        parts.append(addition);size+=len(addition);seq+=3;previous=next_previous
        if 'synthetic14MiB' not in checkpoints and size>=14*1024**2:
            checkpoints['synthetic14MiB']=(size,seq)
    body=b''.join(parts);checkpoints['syntheticNear15_5MiB']=(len(body),seq)
    return body,checkpoints,number-1


def timed(function,state):
    wall=time.perf_counter();cpu=time.process_time();result=function(state)
    cpu=time.process_time()-cpu;wall=time.perf_counter()-wall
    return result,dict(wallSeconds=wall,cpuSeconds=cpu)


def main():
    assert not OUT.exists();OUT.mkdir()
    row=json.loads((R/'settling/telemetry.jsonl').read_text().splitlines()[0])
    view=row['processObservation']['lifecycle'];final=(R/'lifecycle-journal.jsonl').read_bytes();base=final[:view['journalBytes']]
    assert len(base)==6286107 and hashlib.sha256(base).hexdigest()==view['journalSha256']
    synthetic_raw,cutoffs,tasks=synthetic(base)
    (OUT/'synthetic-derived-not-observed.jsonl').write_bytes(synthetic_raw)
    cases=[('actualE3FirstPrefix',base),*[(label,synthetic_raw[:cutoff]) for label,(cutoff,_) in cutoffs.items()]]
    results=[]
    for label,raw in cases:
        before=time.perf_counter();state=life.replay_journal(raw);parse=time.perf_counter()-before
        state['launchRefusalArtifacts']=[]
        methods=[('deepcopyFullState',copy.deepcopy),('marshalFullStateUncheckedTimingOnly',lambda s:marshal.loads(marshal.dumps(s,4))),
                 ('marshalFullStateChecked',checked_marshal),
                 ('deepcopyGuardProjectionOnly',lambda s:copy.deepcopy({k:s[k] for k in KEYS}))]
        measurements={name:[] for name,_ in methods}
        for repeat in range(3):
            # Fixed alternating order, every observation retained; no best-run acceptance.
            order=methods if repeat%2==0 else list(reversed(methods))
            for name,function in order:
                gc.collect()
                clone,measurement=timed(function,state)
                expected=state if 'Projection' not in name else {k:state[k] for k in KEYS}
                assert same(expected,clone)
                detached=detached_mutable_graph(expected,clone)
                measurements[name].append(dict(repeat=repeat,mutableNodesChecked=detached,**measurement))
                del clone
        results.append(dict(label=label,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),events=len(state['events']),
            leases=len(state['leases']),coldParserWallSeconds=parse,
            measurements={name:dict(raw=values,medianWallSeconds=statistics.median(v['wallSeconds'] for v in values),
                maximumWallSeconds=max(v['wallSeconds'] for v in values)) for name,values in measurements.items()}))
        del state
    profiler=cProfile.Profile();profiler.enable();cursor=life.ViewCursor()
    cursor.validate_view(view,final);profiler.disable()
    output=io.StringIO();pstats.Stats(profiler,stream=output).sort_stats('cumulative').print_stats(30)
    (OUT/'actual-prefix-cold-view-profile.txt').write_text(output.getvalue())
    report=dict(schema='aijade.ch7.offline-cursor-clone-probe.v1',status='BOUNDED_OFFLINE_PRIMITIVE_PROBE_NOT_QUALIFICATION',
        at=datetime.now(timezone.utc).isoformat(),sourceCommit='1ab9056dfee6cc804f84677830989b1d2f8153a4',
        lifecycleSourceSha256=LIFE_SHA,originalPrefixSha256=hashlib.sha256(base).hexdigest(),
        originalPrefixBytes=len(base),syntheticAddedTaskChains=tasks,syntheticCheckpoints=cutoffs,
        repeatCountPerMethod=3,results=results,
        scope=dict(noNewObservedWindow=True,noObserverApiNativeOrModelCalls=True,rawE3Unmodified=True,
                   timingsOfflineCacheAndHostSpecific=True,fullGuardOrServiceAcceptanceMeasured=False,backendQualified=False))
    path=OUT/'result.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(path=str(path),summary=[dict(label=r['label'],parse=r['coldParserWallSeconds'],
        medians={k:v['medianWallSeconds'] for k,v in r['measurements'].items()}) for r in results]),indent=2))


if __name__=='__main__':main()
