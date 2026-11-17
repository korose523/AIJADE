"""Synthetic non-sampler event-complexity control, not an OS observation."""
import sys,time,json,tempfile,statistics,hashlib
from pathlib import Path
REPO=Path('/Volumes/Untitled/AIJADE/.runtime/posix/research/ch7-lifecycle-20261117/worktree');C=Path('/Volumes/Untitled/AIJADE/.research/runs/ch7-lifecycle-20261117')
sys.path[:0]=[str(REPO/'experiments/ch7'),str(REPO/'tests/shell')]
import process_lifecycle as life
import mac_process_guard_v3 as guard
from test_mac_lifecycle_guard import fixture,journal_events,raw_events
p,o,_=fixture();events=journal_events();writer=events[0]['writer'];counter=0
for i in range(1440):
 lease=f'{i+100:032x}';ident=dict(pid=1000000+i,createTimeMicros=(1000000+i)*1000000,parentPid=20)
 for name,data in [('FINITE_REGISTER',dict(leaseId=lease,role='finite',stageId='synthetic-complexity',identity=ident,parentIdentity=writer,commandSha256='c'*64,executableSha256='d'*64,readyMonotonic=2+counter*.01)),('RELEASE',dict(leaseId=lease)),('WAIT',dict(leaseId=lease,identity=ident,exitCode=0,waitSource='Popen.wait',reapedMonotonic=2+(counter+2)*.01))]:
  counter+=1;event=dict(schema=life.EVENT_SCHEMA,seq=len(events)+1,event=name,monotonicSeconds=2+counter*.01,runId='1'*32,writer=writer,sourceCommit='2'*40,policySha256='3'*64,data=data,previousSha256=events[-1]['sha256']);event['sha256']=life.digest(life.canonical(event));events.append(event)
raw=raw_events(events);state=life.replay_journal(raw);view=o['lifecycle'];view.update(journalBytes=len(raw),journalSha256=life.digest(raw),lastSequence=len(events),leases=[v for v in state['leases'].values() if v['absence'] is None or life.identity_key(v['identity']) in {tuple(x) for x in view['referencedIdentities']}])
(C/'lifecycle-synthetic-4322events.jsonl').write_bytes(raw)
measurements={}
for label,func in [('validate_view',lambda:life.validate_view(view,raw)),('guard_raw_replay',lambda:guard.validate_observation(p,o,lifecycle_journal=raw)),('three_guard_replays',lambda:[guard.validate_observation(p,o,lifecycle_journal=raw) for _ in range(3)])]:
 times=[]
 for n in range(5):
  start=time.monotonic();result=func();times.append(time.monotonic()-start)
  if label!='validate_view':
   values=result if isinstance(result,list) else [result]
   assert all(v['status']=='PASS' for v in values),result
 measurements[label]=dict(samples=5,seconds=times,maximumSeconds=max(times),medianSeconds=statistics.median(times))
print('SYNTHETIC reader controls complete',flush=True)
with tempfile.TemporaryDirectory(prefix='lifecycle-cache-stress-',dir=life.POSIX/'tmp') as folder:
 ident=life.identity();registry=life.Registry(Path(folder)/'journal.jsonl',[(ident['pid'],ident['createTimeMicros']/1000000)],source_commit='a'*40,policy_sha256='b'*64,capture_lock_path=Path(folder)/'capture.lock')
 append_times=[];start=time.monotonic()
 for i in range(1440):
  lid=f'{i+100:032x}';child=dict(pid=2000000+i,createTimeMicros=(2000000+i)*1000000,parentPid=ident['pid'])
  for kind,data in [('FINITE_REGISTER',dict(leaseId=lid,role='finite',stageId='synthetic-only',identity=child,parentIdentity=ident,commandSha256='c'*64,executableSha256='d'*64,readyMonotonic=time.monotonic())),('RELEASE',dict(leaseId=lid)),('WAIT',dict(leaseId=lid,identity=child,exitCode=0,waitSource='Popen.wait',reapedMonotonic=time.monotonic()))]:
   tick=time.monotonic();registry._append(kind,data);append_times.append(time.monotonic()-tick)
  if i and i%360==0:print('SYNTHETIC append leases',i,flush=True)
 elapsed=time.monotonic()-start;registry.sample();registry.close()
 measurements['incremental_append']=dict(events=4320,totalSeconds=elapsed,maximumEventSeconds=max(append_times),medianEventSeconds=statistics.median(append_times),finalJournalBytes=registry.path.stat().st_size,syntheticNoProcessesLaunched=True)
report=dict(schema='aijade.lifecycle.non-sampler-complexity-control.v1',status='SYNTHETIC_4322_EVENT_REPLAY_AND_INCREMENTAL_CACHE_PASS',eventPopulation=len(events),finiteTaskFixtures=1440,rawJournalBytes=len(raw),rawJournalSha256=life.digest(raw),measurements=measurements,actualObserversRun=0,nativeHelpersRun=0,modelCalls=0,qualification=False,scope='Synthetic chronology/complexity only. Actual total live v3 observation still has an independent strict2.5s budget including lockwait/capture/postprocessing; these timings do not establish admission or remaining budget on the host.')
(C/'lifecycle-complexity-controls.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
