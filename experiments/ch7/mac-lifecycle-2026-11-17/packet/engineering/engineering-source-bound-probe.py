"""One two-observation engineering probe. Not an admission or case trajectory."""
from pathlib import Path
from datetime import datetime,timezone
import sys,os,json,time,hashlib,subprocess,psutil
B=Path('/Volumes/Untitled/AIJADE');C=Path(__file__).parent;W=B/'.runtime/posix/research/ch7-lifecycle-20261117/worktree'
sys.path.insert(0,str(W/'experiments/ch7'))
from finite_runtime import load_mac_policy,validate_mac_sample
from process_lifecycle import Registry
import mac_process_guard_v3 as guard
from lifecycle_audit import verify_lifecycle
Q=json.loads((C/'implementation-publication.json').read_bytes())['sourceCommit']
publication=json.loads((C/'binary-freeze-publication.json').read_bytes())
assert publication['sourceCommit']==Q and publication['status']=='ACTUAL_Q_AND_NATIVE_BINARY_IDENTITIES_PUBLIC_BEFORE_ADMISSION'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=W,text=True).strip()==Q
assert not subprocess.check_output(['git','status','--porcelain'],cwd=W)
policy,ident=load_mac_policy(W,W/'configs/research/ch7-mac-lifecycle-process-policy.json',Q)
root=B/'.runtime/posix/runs/ch7-mac-lifecycle-20261117/engineering-live-01';root.parent.mkdir(parents=True,exist_ok=True);root.mkdir();journal=root/'lifecycle-journal.jsonl'
registry=Registry(journal,[(os.getpid(),psutil.Process().create_time())],stage='engineering-probe-not-qualification',
 source_commit=Q,policy_sha256=ident['processPolicySha256'],capture_lock_path=guard.coordination_lock_path(policy)).activate()
rows=[];errors=[];child=None
try:
 child_code="import subprocess,sys,time;p=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(4)']);p.wait();time.sleep(4)"
 child=registry.launch([sys.executable,'-B','-c',child_code],stage='engineering-finite-child')
 # A fixed readiness pause outside any admission schedule allows the opaque
 # descendant to exist in the first predetermined capture. No retry or selection.
 time.sleep(.25)
 for label in ['known-finite-child-running','known-finite-child-parent-wait-reaped']:
  if label.endswith('reaped'):assert child.wait(timeout=10)==0
  began=time.monotonic();observation=guard.observe(policy,owned_roots=registry.roots(),lifecycle=registry)
  observation.update(ident);available=psutil.virtual_memory().available;swap=psutil.swap_memory().used;ended=time.monotonic()
  row=dict(label=label,utc=datetime.now(timezone.utc).isoformat(),monotonicSeconds=began,
   observationCompletedMonotonic=ended,observationDurationSeconds=ended-began,
   processObservation=observation,rssBytes=observation.get('ownedRssBytes'),
   availableBytes=available,swapUsedBytes=swap,**ident)
  rows.append(row)
  with (root/'observations.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n');stream.flush()
  try:validate_mac_sample(row,ident['processPolicySha256'],ident['observerModuleSha256'],policy)
  except BaseException as error:errors.append(type(error).__name__+': '+str(error))
except BaseException as error:errors.append(type(error).__name__+': '+str(error))
finally:
 if child is not None:
  try:
   if child.poll() is None:child.kill()
   child.wait(timeout=2)
  except BaseException as error:errors.append('cleanup '+type(error).__name__+': '+str(error))
 try:final=registry.final()
 except BaseException as error:final={'status':'UNKNOWN','error':str(error)};errors.append('final '+str(error))
 if not registry.closed:registry.close()
 raw=journal.read_bytes()
 audit=None
 try:audit=verify_lifecycle(raw,rows,source_commit=Q,policy_sha256=ident['processPolicySha256'],policy=policy,
                           controller={'pid':os.getpid(),'createTime':psutil.Process().create_time()})
 except BaseException as error:errors.append('independent replay '+type(error).__name__+': '+str(error))
 if audit is not None and audit.get('discoveredOnlyConfirmedAbsentUnknownExit',0)<1:errors.append('opaque descendant was not witnessed and independently closed')
 receipt=dict(status='ENGINEERING_LIVE_PROBE_PASS_NO_QUALIFICATION' if not errors and len(rows)==2 and final.get('status')=='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' else 'ENGINEERING_LIVE_PROBE_REFUSED',
  checkedAt=datetime.now(timezone.utc).isoformat(),implementationCommit=Q,buildFreezeCommit=publication['buildFreezeCommit'],
  scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),observations=len(rows),observerStatuses=[r['processObservation']['status'] for r in rows],
  wholeCallDurations=[r['observationDurationSeconds'] for r in rows],lifecycleJournalBytes=len(raw),lifecycleJournalSha256=hashlib.sha256(raw).hexdigest(),
  registryFinal=final,independentAudit=audit,errors=errors,qualification=False,admissionStarted=False,caseTrajectories=0,modelRequests=0,freshHeldoutCases=0,automaticRetries=0)
 (root/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');(C/'engineering-live-01-receipt.json').write_text(json.dumps(dict(receipt,physicalOutput=str(root)),indent=2)+'\n');print(json.dumps({k:v for k,v in receipt.items() if k not in ('registryFinal','independentAudit')}),flush=True)
assert receipt['status']=='ENGINEERING_LIVE_PROBE_PASS_NO_QUALIFICATION'
