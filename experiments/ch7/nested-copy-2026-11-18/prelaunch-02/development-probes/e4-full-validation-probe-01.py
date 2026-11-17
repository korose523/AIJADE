"""Offline source-bound cursor/guard fixture replay, not a live observation.

Synthetic extra finite chains are inserted before recorded native frames and
normally reaped there. Both old/new validators see identical populations and
every repeat retains its measurements. No collector, daemon, API or model runs.
"""
from pathlib import Path
import copy
import gc
import hashlib
import json
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone

B=Path('/Volumes/Untitled/AIJADE');I=Path(__file__).parent;W=B/'.runtime/posix/nested-20261117/worktree'
sys.path.insert(0,str(W/'experiments/ch7'))
import process_lifecycle as life
import full_state_clone_cursor as clone
import mac_process_guard_v3 as guard
import finite_runtime as runtime
from cursor_clone_probe_support import typed_equal,assert_mutable_detached

R=B/'.runtime/posix/runs/ch7-nested-20261117/engineering-01'
OUT=I/'e4-full-validation-probe-01'


def hashed(events):
    previous=life.ZERO;parts=[]
    for index,event in enumerate(events,1):
        event=copy.deepcopy(event);event['seq']=index;event['previousSha256']=previous
        event['sha256']=life.digest(life.canonical({k:v for k,v in event.items() if k!='sha256'}))
        previous=event['sha256'];parts.append(life.canonical(event)+b'\n')
    return b''.join(parts)


def derived_input(base,observation,target):
    events=[json.loads(line) for line in base.splitlines()]
    cut=next(i for i,e in enumerate(events) if e['event']=='FINITE_REGISTER' and e['data']['stageId']=='observer-native-census')
    preparation=events[:cut];tail=events[cut:]
    if target==0:return events
    template=next(e for e in events if e['event']=='FINITE_REGISTER')
    owner=events[0]['writer'];before=observation['evidence']['before']['graphStartedMonotonic']
    lower=preparation[-1]['monotonicSeconds'];gap=before-lower
    assert gap>0
    additions=[];approximate=len(base);count=0
    while approximate<target:
        count+=1;lease='%032x'%(0x800000+count);pid=300000+count
        ident=dict(pid=pid,createTimeMicros=owner['createTimeMicros']+10000+count,parentPid=owner['pid'])
        clock=lower+gap*(count*3)/(5000*3+4)
        assert clock+gap/(5000*3+4)<before
        data=copy.deepcopy(template['data']);data.update(leaseId=lease,identity=ident,parentIdentity=owner,
            stageId='snapshot-probe',readyMonotonic=clock-gap/(5000*3+4))
        specs=[('FINITE_REGISTER',data,clock),('RELEASE',dict(leaseId=lease),clock+gap/(5000*3+4)/3),
            ('WAIT',dict(leaseId=lease,identity=ident,exitCode=0,waitSource='Popen.wait',reapedMonotonic=clock+gap/(5000*3+4)*.6),
             clock+gap/(5000*3+4)*.7)]
        for name,data,mono in specs:
            event=dict(schema=life.EVENT_SCHEMA,seq=1,event=name,monotonicSeconds=mono,
                runId=events[0]['runId'],writer=owner,sourceCommit=events[0]['sourceCommit'],
                policySha256=events[0]['policySha256'],data=data,previousSha256='0'*64,sha256='0'*64)
            additions.append(event);approximate+=len(life.canonical(event))+1
    return preparation+additions+tail


def make_case(events,policy,original,directory):
    policy=copy.deepcopy(policy);praw=(json.dumps(policy,sort_keys=True,allow_nan=False)+'\n').encode();psha=life.digest(praw)
    events=copy.deepcopy(events)
    for event in events:event['policySha256']=psha
    raw=hashed(events);state=life.replay_journal(raw)
    observation=copy.deepcopy(original)
    observation.update(observerModuleSha256=guard._file_sha(Path(guard.__file__)),policyCanonicalSha256=guard.canonical_sha256(policy),
                       lifecyclePolicySha256=psha)
    view=observation['lifecycle'];refs={tuple(v) for v in view['referencedIdentities']}
    journal=directory/'journal.jsonl';journal.write_bytes(raw);journal.chmod(0o600)
    view.update(journalPath=str(journal),journalBytes=len(raw),journalSha256=life.digest(raw),lastSequence=len(events),
        leases=copy.deepcopy([v for v in state['leases'].values() if v['absence'] is None or life.identity_key(v['identity']) in refs]))
    view['controllers']=[v['leaseId'] for v in view['leases'] if v['identity']==view['controllerIdentity']]
    return policy,observation,raw,state


def moment(function):
    a=time.perf_counter();cpu=time.process_time();result=function()
    return result,dict(wallSeconds=time.perf_counter()-a,cpuSeconds=time.process_time()-cpu)


def main():
    assert not OUT.exists();OUT.mkdir()
    original=json.loads((R/'settling/telemetry.jsonl').read_text().splitlines()[0])['processObservation']
    final=(R/'lifecycle-journal.jsonl').read_bytes();base=final[:original['lifecycle']['journalBytes']]
    old_policy=json.loads((R/'process-policy.json').read_bytes())
    results=[]
    with tempfile.TemporaryDirectory(dir=B/'.runtime/posix/tmp',prefix='e4-full-clone-probe-') as scratch:
        scratch=Path(scratch)
        for label,target in [('E3DerivedSamePopulation',0),('Synthetic14MiB',14*1024**2),('Synthetic15_4MiB',int(15.4*1024**2))]:
            events=derived_input(base,original,target)
            cases={}
            for mode in ('legacy','candidate'):
                directory=scratch/(label+'-'+mode);directory.mkdir()
                policy=copy.deepcopy(old_policy)
                if mode=='candidate':policy.update(onlineReplayMode=clone.MODE,onlineReplaySourceSha256=guard._file_sha(Path(clone.__file__)),
                                                   onlineReplayInitializationMode=clone.INITIALIZATION_MODE)
                p,o,raw,state=make_case(events,policy,original,directory)
                if mode=='legacy':
                    def prepare():
                        inner,outer=life.ViewCursor(),life.ViewCursor()
                        inner.validate_view(o['lifecycle']);outer.validate_view(o['lifecycle'])
                        return inner,outer
                    pair,init=moment(prepare);record=None
                else:
                    registry=object.__new__(life.Registry);registry.sample=lambda:copy.deepcopy(o['lifecycle'])
                    options,init=moment(lambda:runtime.online_lifecycle_cursors(p,lifecycle=registry,preparation_path=directory/'initialization.json'))
                    inner_options,outer_options=options;pair=(inner_options['lifecycle_cursor'],outer_options['lifecycle_cursor'])
                    record=runtime.lifecycle_cursor_initialization(inner_options)
                    o.update(onlineReplayMode=clone.MODE,onlineReplaySourceSha256=p['onlineReplaySourceSha256'],
                        onlineReplayInitializationMode=clone.INITIALIZATION_MODE,onlineReplayPreparation=pair[0].preparation_reference())
                    assert_mutable_detached(pair[0]._state,pair[1]._state)
                observations=[]
                for repeat in range(3):
                    gc.collect()
                    def validate_pair():
                        a=guard.validate_observation(p,o,lifecycle_cursor=pair[0])
                        b=guard.validate_observation(p,o,lifecycle_cursor=pair[1])
                        assert a['status']==b['status']=='PASS' and a['blockers']==b['blockers']==[]
                        return a,b
                    decisions,timing=moment(validate_pair)
                    assert typed_equal(decisions[0],decisions[1])
                    observations.append(dict(repeat=repeat,**timing))
                cases[mode]=dict(bytes=len(raw),events=len(events),leases=len(state['leases']),initialization=init,
                    rawTimings=observations,medianPairValidationSeconds=statistics.median(r['wallSeconds'] for r in observations),
                    maximumPairValidationSeconds=max(r['wallSeconds'] for r in observations),
                    innerStatistics=pair[0].statistics(),outerStatistics=pair[1].statistics(),
                    initializationRecord=record)
                del pair,state
            results.append(dict(label=label,methods=cases))
    report=dict(schema='aijade.ch7.offline-full-validation-clone-probe.v1',status='OFFLINE_GUARD_VALIDATION_PROBE_NOT_RUNTIME_QUALIFICATION',
        at=datetime.now(timezone.utc).isoformat(),sourceFiles={n:guard._file_sha(W/'experiments/ch7'/n) for n in
            ('full_state_clone_cursor.py','mac_process_guard_v3.py','finite_runtime.py','process_lifecycle.py')},
        originalE3PrefixSha256=life.digest(base),results=results,
        scope=dict(derivedFixtures=True,nativeOrApiOrModelCalls=0,newObservedWindows=0,rawE3Unmodified=True,
            noNewTailPerRepeatedTiming=True,actualOriginalPhysicalFileReadsPerCall=True,
            actualSamplingAndFullServiceNotMeasured=True,backendQualified=False))
    path=OUT/'result.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(path=str(path),summary=[dict(label=r['label'],methods={m:dict(init=v['initialization']['wallSeconds'],
        pairMedian=v['medianPairValidationSeconds'],pairMaximum=v['maximumPairValidationSeconds'],bytes=v['bytes'])
        for m,v in r['methods'].items()}) for r in results]),indent=2))


if __name__=='__main__':main()
