"""Explicit build identity and bounded owned cleanup for the finite controller.

These helpers never decide a C1/C2 scientific outcome. Unknown cleanup is adverse.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import threading
from pathlib import PurePosixPath


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


BUILD_FREEZE_PATH='experiments/ch7/relocated-runtime-2026-11-16/frozen-build.json'
MAC_PLAN='2026-11-16-ch7-mac-formal-backend.md'
MAC_BUILD_FREEZE_PATH='experiments/ch7/mac-formal-2026-11-16/frozen-build.json'
MAC_CENSUS_PLAN='2026-11-16-ch7-mac-bulk-census.md'
MAC_CENSUS_BUILD_FREEZE_PATH='experiments/ch7/mac-census-2026-11-16/frozen-build.json'
MAC_LIFECYCLE_PLAN='2026-11-17-ch7-mac-lifecycle-continuity.md'
MAC_LIFECYCLE_BUILD_FREEZE_PATH='experiments/ch7/mac-lifecycle-2026-11-17/frozen-build.json'
MAC_LIFECYCLE_KIND='mac-lifecycle-observed-idle-daemon-v3'
MAC_PREFIX_DECISION='mac-prefix-v4'
MAC_PREFIX_PLAN='2026-11-17-ch7-mac-prefix-v4-qualification.md'
MAC_PREFIX_PLAN_SHA256='7aa91508eee3e728cadd8d25f8cdd122deb9a35d06a09901e8143d1e028d9d36'
MAC_PREFIX_BUILD_FREEZE_PATH='experiments/ch7/mac-prefix-v4-2026-11-17/frozen-build.json'
MAC_PREFIX_POLICY_PATH='configs/research/ch7-mac-prefix-v4-process-policy.json'
MAC_PREFIX_DATA_PREFIX='experiments/ch7/mac-prefix-v4-2026-11-17/'
MAC_PLANS=(MAC_PLAN,MAC_CENSUS_PLAN,MAC_LIFECYCLE_PLAN,MAC_PREFIX_PLAN)
MAC_LIFECYCLE_SOURCES=tuple('experiments/ch7/'+name for name in (
    'mac_process_guard_v3.py','process_lifecycle.py','lifecycle_exec.py','binary_authentication.py',
    'phase_continuity.py','lifecycle_audit.py','mac_process_guard.py',
    'mac_process_guard_v2.py','mac_bulk_census.c','finite_runtime.py',
    'run_finite_sequence.py','run_finite_block.py','finite_audit.py',
    'finite_sequence_audit.py','godot_local.py'))
PROJECT_ROOT=Path('/Volumes/Untitled/AIJADE')
MAC_DATA_PREFIXES=('experiments/ch7/mac-formal-2026-11-16/', 'experiments/ch7/mac-census-2026-11-16/', 'experiments/ch7/mac-lifecycle-2026-11-17/', 'experiments/ch7/finite-heldout/', MAC_PREFIX_DATA_PREFIX)
MAC_DATA_SUFFIXES={'.json','.jsonl','.md','.txt','.log','.csv','.tsv','.xml','.trx'}


def safe_relative(value):
    require(type(value) is str and value and '\\' not in value and ':' not in value, 'unsafe tracked relative path')
    parts=value.split('/')
    require(not value.startswith('/') and all(p not in ('','.','..') and not any(ord(c)<32 for c in p) for p in parts), 'unsafe tracked relative path')
    require(PurePosixPath(value).as_posix()==value, 'noncanonical tracked path')
    return value


def managed_check_output(command, **kwargs):
    # Historical policies have no lifecycle environment and retain their old path.
    if not os.environ.get('AIJADE_LIFECYCLE_JOURNAL'):
        return subprocess.check_output(command, **kwargs)
    from process_lifecycle import from_environment
    registry=from_environment()
    if 'stdout' in kwargs:raise ValueError('check_output stdout override')
    result=registry.run(command, stdout=subprocess.PIPE, check=True, **kwargs)
    return result.stdout


def managed_run(command, **kwargs):
    if not os.environ.get('AIJADE_LIFECYCLE_JOURNAL'):
        return subprocess.run(command, **kwargs)
    from process_lifecycle import from_environment
    return from_environment().run(command, **kwargs)


def git_bytes(repo,*arguments):
    return managed_check_output(['git',*arguments],cwd=repo)



def setup_lifecycle(args, stage):
    """Open source-bound instrumentation before v3 controller preflight commands."""
    execution_plan=getattr(getattr(args,'execution_plan',None),'name',None)
    if execution_plan not in (MAC_LIFECYCLE_PLAN,MAC_PREFIX_PLAN):return None
    import psutil
    from process_lifecycle import Registry, from_environment
    policy_raw=args.process_policy.read_bytes();policy=json.loads(policy_raw)
    require(policy.get('kind')==MAC_LIFECYCLE_KIND,'v3 execution/policy mismatch')
    require(mac_plan(policy)==execution_plan,'lifecycle execution decision/plan mismatch')
    guard=mac_observer(policy);guard.validate_policy(policy)
    source=os.environ.get('AIJADE_GIT_COMMIT','')
    require(re.fullmatch('[0-9a-f]{40}',source) is not None,'lifecycle Q identity missing')
    policy_sha=hashlib.sha256(policy_raw).hexdigest()
    if os.environ.get('AIJADE_LIFECYCLE_JOURNAL'):
        registry=from_environment()
        require(registry.source_commit==source and registry.policy_sha256==policy_sha,
                'inherited lifecycle source/policy mismatch')
    else:
        parent=args.output.resolve().parent;parent.mkdir(parents=True,exist_ok=True)
        journal=parent/(args.output.name+'-lifecycle.jsonl')
        require(not journal.exists(),'never reuse a prior lifecycle journal')
        registry=Registry(journal,[(os.getpid(),psutil.Process().create_time())],stage=stage,
            source_commit=source,policy_sha256=policy_sha,
            capture_lock_path=guard.coordination_lock_path(policy))
    registry.activate()
    return registry


def wait_post_cleanup_sample(monitor, cleanup_monotonic):
    """Wait once for the next existing scheduled tick; never collect a replacement."""
    deadline=cleanup_monotonic+3
    while True:
        monitor.check()
        candidates=[s for s in monitor.samples if s.get('monotonicSeconds',-1)>=cleanup_monotonic]
        if candidates:
            require(len(candidates)==1,'unexpected multiple post-cleanup ticks before finalization')
            return candidates[0]
        require(time.monotonic()<=deadline,'next scheduled post-cleanup sample missed its bound')
        time.sleep(.01)



def seal_refused_cleanup(registry, output):
    """Reap only failed-launch handles once; successful cleanup cannot accept them."""
    if not getattr(registry,'refused_process_records',[]):return None
    key='_root_refused_cleanup_receipt'
    receipt=getattr(registry,key,None)
    if receipt is None:
        receipt=dict(schema='aijade.ch7.refused-launch-process-cleanup.v1',
                     scopeId=registry.scope_id,status='UNKNOWN',rows=[],errors=[],
                     startedMonotonic=time.monotonic(),workloadAccepted=False,
                     plannedAttemptIds=[r['attemptId'] for r in registry.refused_process_records])
        # Store before touching a handle. Finalization cannot retry the batch.
        setattr(registry,key,receipt)
        try:
            receipt['rows']=registry.cleanup_refused(grace_seconds=5.0,wait_seconds=1.0)
            require([r.get('attemptId') for r in receipt['rows']]==receipt['plannedAttemptIds'],
                    'refused process cleanup population changed or incomplete')
            if all(r.get('cleanupKnown') is True and not r.get('errors') for r in receipt['rows']):
                receipt['status']='CLEANED_REFUSED_PROCESSES_NOT_ACCEPTED'
        except BaseException as error:receipt['errors'].append(type(error).__name__+': '+str(error))
        receipt['finishedMonotonic']=time.monotonic()
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    path=output/'launch-refused-process-cleanup.json'
    raw=(json.dumps(receipt,indent=2)+'\n').encode()
    if path.exists():require(path.read_bytes()==raw,'refused cleanup receipt changed')
    else:
        with path.open('xb') as stream:stream.write(raw)
    return receipt


def finish_monitored_cleanup(monitor, require_terminal_sample=False):
    errors=[]
    if require_terminal_sample:
        try:wait_post_cleanup_sample(monitor,time.monotonic())
        except BaseException as error:errors.append('post-cleanup: '+type(error).__name__+': '+str(error))
    try:monitor.stop()
    except BaseException as error:errors.append('monitor-stop: '+type(error).__name__+': '+str(error))
    require(not errors,'; '.join(errors))


def commit_id(repo,value):
    require(re.fullmatch(r'[0-9a-f]{40}',value or '') is not None,'full immutable commit required')
    require(git_bytes(repo,'rev-parse',value+'^{commit}').decode().strip()==value,'commit does not exist')
    return value


def changed_paths(repo,base,target):
    fields=git_bytes(repo,'diff','--name-status','--no-renames','-z',base,target).split(b'\0')
    require(fields[-1]==b'', 'malformed Git change closure')
    fields=fields[:-1];require(len(fields)%2==0,'malformed Git change closure')
    return [(fields[i].decode(),safe_relative(fields[i+1].decode())) for i in range(0,len(fields),2)]


def validate_repository_binding(repo,implementation,repository=None,data_manifest_path=None,require_head=False):
    """Q owns every executable blob; I may only add exactly declared input/evidence files."""
    repo=Path(repo).resolve();q=commit_id(repo,implementation);i=commit_id(repo,repository or implementation)
    require(managed_run(['git','merge-base','--is-ancestor',q,i],cwd=repo,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0,'Q is not an ancestor of repository I')
    if require_head:
        require(git_bytes(repo,'rev-parse','HEAD').decode().strip()==i,'HEAD differs from repository commit')
        require(not git_bytes(repo,'status','--porcelain'),'dirty execution checkout')
    changes=changed_paths(repo,q,i)
    result=dict(implementationCommit=q,repositoryCommit=i,inputPublicationCommit=i if i!=q else None,
                dataPublicationManifestPath=None,dataPublicationManifestSha256=None,addedDataPaths=[])
    if q==i:
        require(data_manifest_path is None,'data publication manifest is only valid at I')
        return result
    require(data_manifest_path is not None,'explicit tracked I data publication manifest required')
    path=safe_relative(str(data_manifest_path));raw=git_bytes(repo,'show',i+':'+path)
    manifest=json.loads(raw)
    require(manifest.get('schema')=='aijade.ch7.mac-data-publication.v1' and manifest.get('implementationCommit')==q,'wrong Q/I data publication manifest')
    added=manifest.get('addedPaths')
    require(type(added) is list and all(type(p) is str for p in added)
            and len(added)==len(set(added)) and path in added,'declared added path closure missing or duplicated')
    for item in added:
        safe_relative(item);require(item.startswith(MAC_DATA_PREFIXES),'non-data I path is prohibited')
        require(Path(item).suffix.lower() in MAC_DATA_SUFFIXES,'executable or unknown I file type is prohibited')
    q_names=git_bytes(repo,'ls-tree','-r','--name-only','-z',q).decode().split('\0')
    require(len({p.casefold() for p in added})==len(added) and not ({p.casefold() for p in added}&{p.casefold() for p in q_names if p}),'I path case collision')
    tree={}
    for row in git_bytes(repo,'ls-tree','-rz',i).split(b'\0'):
        if row:
            metadata,name=row.split(b'\t',1);mode,kind,_=metadata.decode().split();tree[name.decode()]=(mode,kind)
    require(all(tree.get(path)==('100644','blob') for path in added),'I data must be regular non-executable blobs; links and executable modes are prohibited')
    require(all(action=='A' for action,_ in changes),'I modified, removed or renamed a Q blob')
    require({p for _,p in changes}==set(added),'I changes differ from the declared additions')
    if require_head:
        require((repo/path).read_bytes()==raw,'I publication manifest working bytes differ')
    result.update(dataPublicationManifestPath=path,dataPublicationManifestSha256=hashlib.sha256(raw).hexdigest(),addedDataPaths=sorted(added))
    return result


def mac_observer(policy):
    import importlib
    kind=policy.get('kind')
    require(kind in (None,'mac-observed-idle-daemon-v1','mac-bulk-observed-idle-daemon-v2',MAC_LIFECYCLE_KIND),'unrecognized observer policy kind')
    if kind==MAC_LIFECYCLE_KIND:return importlib.import_module('mac_process_guard_v3')
    return importlib.import_module('mac_process_guard_v2' if kind=='mac-bulk-observed-idle-daemon-v2' else 'mac_process_guard')


def mac_plan(policy):
    if 'executionDecision' in policy:
        require(policy.get('executionDecision')==MAC_PREFIX_DECISION and policy.get('kind')==MAC_LIFECYCLE_KIND,
                'unknown or mixed execution decision')
        return MAC_PREFIX_PLAN
    if policy.get('kind')==MAC_LIFECYCLE_KIND:return MAC_LIFECYCLE_PLAN
    return MAC_CENSUS_PLAN if policy.get('kind')=='mac-bulk-observed-idle-daemon-v2' else MAC_PLAN


def mac_build_path(policy):
    if mac_plan(policy)==MAC_PREFIX_PLAN:return MAC_PREFIX_BUILD_FREEZE_PATH
    if mac_plan(policy)==MAC_LIFECYCLE_PLAN:return MAC_LIFECYCLE_BUILD_FREEZE_PATH
    return MAC_CENSUS_BUILD_FREEZE_PATH if mac_plan(policy)==MAC_CENSUS_PLAN else MAC_BUILD_FREEZE_PATH


def validate_mac_execution_identity(policy,value):
    """Bind the new decision without reinterpreting a legacy observation kind."""
    plan=mac_plan(policy)
    require(value.get('buildFreezePath')==mac_build_path(policy),'execution decision/build-freeze path mismatch')
    if plan==MAC_PREFIX_PLAN:
        require(value.get('processPolicyPath')==MAC_PREFIX_POLICY_PATH,'prefix decision requires its canonical policy path')
        require(value.get('executionPlanSha256')==MAC_PREFIX_PLAN_SHA256,'wrong prospective prefix execution plan')
        require(all(type(path) is str and path.startswith(MAC_PREFIX_DATA_PREFIX)
                    for path in value.get('addedDataPaths',[])),'prefix I additions escaped their new data prefix')
        manifest=value.get('dataPublicationManifestPath')
        require(manifest is None or (type(manifest) is str and manifest.startswith(MAC_PREFIX_DATA_PREFIX)),
                'prefix I manifest escaped its new data prefix')
    else:
        require(value.get('processPolicyPath')!=MAC_PREFIX_POLICY_PATH,'new policy path lacks its explicit execution decision')
    return plan


def validate_mac_build_policy(policy,build):
    if mac_plan(policy) in (MAC_CENSUS_PLAN,MAC_LIFECYCLE_PLAN,MAC_PREFIX_PLAN):
        native=build.get('nativeCensus');expected=policy.get('nativeHelper')
        require(type(native) is dict and type(expected) is dict and all(native.get(key)==expected.get(key) for key in ('path','sha256','sourceSha256')),'native build and process-policy identity differ')
    if mac_plan(policy) in (MAC_LIFECYCLE_PLAN,MAC_PREFIX_PLAN):
        sources=build.get('observerSources')
        repo=Path(__file__).resolve().parents[2]
        require(type(sources) is dict and set(sources)==set(MAC_LIFECYCLE_SOURCES)
                and all(sha(repo/name)==value for name,value in sources.items()),'v3 build observer source closure differs')


def load_mac_policy(repo,path,implementation):
    repo=Path(repo).resolve();original=Path(path);path=original.resolve()
    require(path.is_relative_to(repo) and path.is_file() and not original.is_symlink(),'explicit repository-local process policy required')
    relative=safe_relative(str(path.relative_to(repo)));raw=path.read_bytes()
    require(raw==git_bytes(repo,'show',implementation+':'+relative),'process policy differs from Q')
    policy=json.loads(raw);plan=mac_plan(policy)
    require((relative==MAC_PREFIX_POLICY_PATH)==(plan==MAC_PREFIX_PLAN),'prefix policy path/execution decision mismatch')
    if plan==MAC_PREFIX_PLAN:
        require(policy.get('onlineReplayMode')=='incremental-exact-prefix-v1'
                and policy.get('binaryAuthenticationMode')=='full-read-exact-bytes-v1',
                'prefix policy must retain its accepted replay/authentication modes')
        plan_relative='experiments/plans/'+MAC_PREFIX_PLAN
        plan_raw=git_bytes(repo,'show',implementation+':'+plan_relative)
        require(hashlib.sha256(plan_raw).hexdigest()==MAC_PREFIX_PLAN_SHA256
                and (repo/plan_relative).read_bytes()==plan_raw,'prefix plan differs from the published decision at Q')
    guard=mac_observer(policy);guard.validate_policy(policy)
    module=repo/'experiments/ch7'/('mac_process_guard_v3.py' if policy.get('kind')==MAC_LIFECYCLE_KIND else 'mac_process_guard_v2.py' if mac_plan(policy)==MAC_CENSUS_PLAN else 'mac_process_guard.py')
    require(module.read_bytes()==git_bytes(repo,'show',implementation+':'+str(module.relative_to(repo))),'observer module differs from Q')
    if mac_plan(policy) in (MAC_CENSUS_PLAN,MAC_LIFECYCLE_PLAN,MAC_PREFIX_PLAN):
        for name in ('mac_process_guard.py','mac_bulk_census.c'):
            source=repo/'experiments/ch7'/name
            require(source.read_bytes()==git_bytes(repo,'show',implementation+':'+str(source.relative_to(repo))),'observer dependency differs from Q')
        require(sha(repo/'experiments/ch7/mac_bulk_census.c')==policy['nativeHelper']['sourceSha256'],'native source differs from policy')
    dependencies={}
    if mac_plan(policy) in (MAC_LIFECYCLE_PLAN,MAC_PREFIX_PLAN):
        for relative_source in MAC_LIFECYCLE_SOURCES:
            source=repo/relative_source
            require(source.read_bytes()==git_bytes(repo,'show',implementation+':'+relative_source),'lifecycle dependency differs from Q')
            dependencies[relative_source]=sha(source)
    return policy,dict(processPolicyPath=relative,processPolicySha256=hashlib.sha256(raw).hexdigest(),observerModuleSha256=sha(module),**({'observerSources':dependencies} if dependencies else {}))


def validate_mac_observation(observation,policy_sha,module_sha,policy=None,lifecycle_journal=None,*,lifecycle_cursor=None):
    require(type(observation) is dict and observation.get('processPolicySha256')==policy_sha
            and observation.get('observerModuleSha256')==module_sha,'observer/policy identity missing')
    require(observation.get('status')=='PASS' and observation.get('blockers')==[],'process observation adverse or unknown')
    require(type(observation.get('ownedProcesses')) is list,'owned process observation missing')
    require(policy is not None,'observer evidence requires the frozen policy for independent validation')
    recalculated=(mac_observer(policy).validate_observation(policy,observation,lifecycle_journal=lifecycle_journal,lifecycle_cursor=lifecycle_cursor)
                  if policy.get('kind')==MAC_LIFECYCLE_KIND else mac_observer(policy).validate_observation(policy,observation))
    require(recalculated.get('status')=='PASS' and recalculated.get('blockers')==[], 'raw process/API evidence does not independently pass')
    return recalculated


def validate_mac_sample(item,policy_sha,module_sha,policy,lifecycle_journal=None,*,lifecycle_cursor=None):
    if policy.get('kind')==MAC_LIFECYCLE_KIND:
        began=item.get('monotonicSeconds');ended=item.get('observationCompletedMonotonic')
        require(type(began) in (int,float) and type(ended) in (int,float) and 0<=ended-began<=2.5,
                'complete v3 observation including postprocessing exceeded budget')
        raw=item.get('processObservation',{})
        require(began<=raw.get('startedMonotonic',-1)<=raw.get('finishedMonotonic',float('inf'))<=ended,
                'v3 raw evidence lies outside actual outer observation')
    require(item.get('processPolicySha256')==policy_sha and item.get('observerModuleSha256')==module_sha,'sample observer identity missing')
    recalculated=validate_mac_observation(item['processObservation'],policy_sha,module_sha,policy,lifecycle_journal=lifecycle_journal,lifecycle_cursor=lifecycle_cursor)
    require(type(item.get('rssBytes')) is int and item['rssBytes']==recalculated['ownedRssBytes'],'sample owned RSS differs from raw process evidence')
    return recalculated


def online_lifecycle_cursors(policy):
    """Independent journal states; live file authentication never caches a verdict."""
    if policy is None:
        return {}, {}
    inner,outer={},{}
    if policy.get('onlineReplayMode') is not None:
        require(policy.get('kind')==MAC_LIFECYCLE_KIND and
                policy['onlineReplayMode']=='incremental-exact-prefix-v1','unsupported online replay mode')
        from process_lifecycle import ViewCursor
        inner['lifecycle_cursor'],outer['lifecycle_cursor']=ViewCursor(),ViewCursor()
    if policy.get('binaryAuthenticationMode') is not None:
        require(policy.get('kind')==MAC_LIFECYCLE_KIND,'binary authentication policy kind')
        inner['binary_authenticator']=mac_observer(policy).new_binary_authenticator(policy)
    return inner,outer


def validate_coverage(samples,duration=None,minimum_samples=None,max_gap=3):
    require(type(samples) is list and samples,'missing observation coverage')
    clocks=[s['elapsedSeconds'] for s in samples]
    require(all(type(v) in (int,float) and v>=0 for v in clocks),'invalid observation clock')
    require(all(b>a and b-a<=max_gap for a,b in zip(clocks,clocks[1:])),'observation time reversal or gap')
    if minimum_samples is not None:require(len(samples)>=minimum_samples,'incomplete sample population')
    if duration is not None:
        require(clocks[0]<=max_gap and duration-clocks[-1]<=max_gap and clocks[-1]<=duration,'incomplete phase endpoints')
        require(all(s['elapsedSeconds']+s.get('observationDurationSeconds',0)<=duration for s in samples),'observation exceeded the fixed phase deadline')
    return dict(samples=len(samples),maximumGapSeconds=max([0]+[b-a for a,b in zip(clocks,clocks[1:])]),coverageComplete=True)


def fixed_phase(duration,sampler,writer,clock=time.monotonic,sleeper=time.sleep):
    """Nominal two-second monotonic deadlines; no reset, extension or favorable segment."""
    start=clock();end=start+duration;index=0;samples=[]
    while start+index*2<end:
        target=start+index*2;remaining=target-clock()
        if remaining>0:sleeper(remaining)
        now=clock()
        if now>=end:break
        item=sampler();item.update(elapsedSeconds=now-start,monotonicSeconds=now,scheduledSeconds=index*2,
                                   observationCompletedMonotonic=clock(),observationDurationSeconds=clock()-now)
        samples.append(item);writer(item);index+=1
    remaining=end-clock()
    if remaining>0:sleeper(remaining)
    return samples,dict(startMonotonic=start,endMonotonic=clock(),requestedSeconds=duration,intervalReset=False)


class MacMonitor:
    """A read-only observation thread covers blocking startup, child work and cleanup."""
    def __init__(self,path,sampler,validator,epoch,swap_baseline,timers_path=None,maximum_wall=4800,local_epoch=None,previous_sample_monotonic=None):
        self.path=Path(path);self.sampler=sampler;self.validator=validator;self.epoch=epoch
        self.swap_baseline=swap_baseline;self.timers_path=Path(timers_path) if timers_path else None
        self.maximum_wall=maximum_wall;self.stop_event=threading.Event();self.errors=[];self.samples=[]
        self.local_epoch=epoch if local_epoch is None else local_epoch
        self.previous_sample_monotonic=previous_sample_monotonic
        self.timers={};self.thread=threading.Thread(target=self._run,name='aijade-readonly-process-observer',daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        deadline=time.monotonic();previous=self.previous_sample_monotonic
        try:
            with self.path.open('x') as log:
                while not self.stop_event.is_set():
                    now=time.monotonic()
                    try:
                        item=self.sampler();item.update(monotonicSeconds=now,sequenceElapsedSeconds=now-self.epoch,
                            elapsedSeconds=now-self.local_epoch,observationCompletedMonotonic=time.monotonic())
                        item['swapIncreaseBytes']=max(0,item['swapUsedBytes']-self.swap_baseline)
                        self.samples.append(item);log.write(json.dumps(item)+'\n');log.flush()
                        require(previous is None or 0<now-previous<=3,'runtime process observation coverage gap')
                        self.validator(item)
                        require(now-self.epoch<=self.maximum_wall,'overall wall limit stop')
                        for name,crossed in [('rss',item['rssBytes']>2*1024**3),('available',item['availableBytes']<3*1024**3),('swap',item['swapIncreaseBytes']>1024**3)]:
                            if not crossed:self.timers.pop(name,None)
                            else:
                                self.timers.setdefault(name,now)
                                require(now-self.timers[name]<30,'runtime sustained '+name+' stop')
                        if self.timers_path:self.timers_path.write_text(json.dumps(self.timers)+'\n')
                    except BaseException as error:
                        self.errors.append(type(error).__name__+': '+str(error))
                        log.write(json.dumps(dict(utc=None,monotonicSeconds=now,sequenceElapsedSeconds=now-self.epoch,
                                                  observationError=self.errors[-1]))+'\n');log.flush()
                    previous=now;deadline+=2
                    if self.stop_event.wait(max(0,deadline-time.monotonic())):break
        except BaseException as error:self.errors.append(type(error).__name__+': '+str(error))

    def check(self):
        require(not self.errors,'runtime observation failed: '+ '; '.join(self.errors))

    def stop(self):
        self.stop_event.set();self.thread.join(timeout=3)
        require(not self.thread.is_alive(),'owned observer thread failed to stop')
        self.check()


class OwnedRegistry:
    """Remember proven descendants across reparenting; retire only known-absent identities."""
    def __init__(self,roots,lookup=None):
        self.active={tuple(value) for value in roots};self.controllers=set(self.active)
        self.known=set(self.active);self.retired=[];self.registered=[];self.lookup=lookup or self._lookup

    @staticmethod
    def _lookup(pid):
        import psutil
        try:return psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:return None
        except psutil.Error as error:raise ValueError('owned PID identity is unknown: '+type(error).__name__) from error

    def roots(self):
        for pid,created in list(self.active):
            actual=self.lookup(pid)
            if actual is None or actual!=created:
                self.active.remove((pid,created))
                self.retired.append(dict(pid=pid,createTime=created,status='ABSENT' if actual is None else 'PID_REUSED_OLD_IDENTITY_ABSENT',
                                         observedCreateTime=actual,checkedMonotonic=time.monotonic()))
        require(self.controllers<=self.active,'owned controller identity disappeared')
        return sorted(self.active)

    def remember(self,observation):
        for value in observation.get('ownedProcesses',[]):
            key=(value['pid'],value['createTime']);self.active.add(key);self.known.add(key)

    def register(self,pid,created):
        key=(pid,created)
        if key not in self.known:self.registered.append(dict(pid=pid,createTime=created,registeredMonotonic=time.monotonic()))
        self.active.add(key);self.known.add(key)

    def final(self):
        self.roots()
        remaining=sorted(self.active-self.controllers)
        return dict(status='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' if not remaining else 'OWNED_IDENTITIES_REMAIN',
                    controllers=[dict(pid=p,createTime=c) for p,c in sorted(self.controllers)],
                    knownIdentities=[dict(pid=p,createTime=c) for p,c in sorted(self.known)],
                    explicitlyRegisteredIdentities=self.registered,
                    retiredIdentities=self.retired,
                    remainingIdentities=[dict(pid=p,createTime=c) for p,c in remaining])


def validate_owned_registry(record,samples):
    require(record.get('status')=='ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT' and record.get('remainingIdentities')==[], 'owned identities remain or cleanup is unknown')
    key=lambda value:(value['pid'],value['createTime'])
    controllers={key(value) for value in record['controllers']}
    known={key(value) for value in record['knownIdentities']}
    registered={key(value) for value in record['explicitlyRegisteredIdentities']}
    observed={key(value) for sample in samples for value in sample['processObservation']['ownedProcesses']}
    require(len(controllers)==1 and known==controllers|registered|observed,'owned registry identity closure differs')
    retired=record['retiredIdentities'];retired_keys=[key(value) for value in retired]
    require(len(set(retired_keys))==len(retired_keys) and set(retired_keys)==known-controllers,'owned absence proof is incomplete or duplicated')
    for value in retired:
        require(value['status'] in ['ABSENT','PID_REUSED_OLD_IDENTITY_ABSENT'],'owned absence is unknown')
        require((value['observedCreateTime'] is None) if value['status']=='ABSENT' else (value['observedCreateTime']!=value['createTime']),'PID reuse is not proof of old-identity absence')
    return dict(knownOwnedIdentities=len(known),retiredNonControllerIdentities=len(retired),allOwnedChildrenAbsent=True)


def validate_build(assembly, manifest, commit, repo=None, freeze_commit=None,freeze_path=BUILD_FREEZE_PATH,strict_publication=False):
    assembly=Path(assembly).resolve();manifest=Path(manifest).resolve()
    require(assembly.name=='Aijade.Tests.dll' and assembly.is_file(), 'explicit test assembly missing')
    build=json.loads(manifest.read_text())
    require(build['status']=='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION' and build['commit']==commit, 'wrong committed build')
    require(build['assemblyInformationalVersion']=='0.1.0+'+commit, 'declared assembly revision')
    require(build['assemblyInformationalVersion'].encode() in assembly.read_bytes(), 'assembly revision bytes absent')
    files={str(p.relative_to(assembly.parent)):p for p in assembly.parent.rglob('*') if p.is_file()}
    require(assembly.with_suffix('.deps.json').name in files and assembly.with_suffix('.runtimeconfig.json').name in files, 'assembly runtime/dependency file missing')
    require(set(files)==set(build['files']), 'build file population changed')
    require(all(sha(p)==build['files'][name] for name,p in files.items()), 'build binary/dependency bytes changed')
    if repo is not None:
        require(re.fullmatch(r'[0-9a-f]{40}',freeze_commit or '') is not None, 'public build-freeze commit required')
        freeze_path=safe_relative(freeze_path)
        frozen=managed_check_output(['git','show',freeze_commit+':'+freeze_path],cwd=repo)
        require(frozen==manifest.read_bytes(), 'pre-qualification public build freeze differs')
        if strict_publication:
            require(freeze_path in (MAC_BUILD_FREEZE_PATH,MAC_CENSUS_BUILD_FREEZE_PATH,MAC_LIFECYCLE_BUILD_FREEZE_PATH,MAC_PREFIX_BUILD_FREEZE_PATH),'new Mac qualification requires its separate build-freeze path')
            if freeze_path in (MAC_CENSUS_BUILD_FREEZE_PATH,MAC_LIFECYCLE_BUILD_FREEZE_PATH,MAC_PREFIX_BUILD_FREEZE_PATH):
                native=build['nativeCensus'];helper=Path(native['path'])
                require(helper.is_absolute() and helper.resolve().is_relative_to(PROJECT_ROOT.resolve()) and '..' not in helper.parts and not helper.is_symlink() and helper.is_file() and sha(helper)==native['sha256'],'native helper changed or outside project')
                source='experiments/ch7/mac_bulk_census.c'
                require(sha(Path(repo)/source)==native['sourceSha256'] and hashlib.sha256(git_bytes(repo,'show',commit+':'+source)).hexdigest()==native['sourceSha256'],'native compiled source differs from Q')
            commit_id(repo,freeze_commit)
    return build


def cleanup_owned_databases(leases, docker, container, run=subprocess.run, budget_seconds=30):
    """Validate every lease before any destructive operation; never infer absence on an error."""
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',container) is not None, 'invalid explicit database container')
    try:
        values=[json.loads(line) for line in Path(leases).read_text().splitlines()] if Path(leases).is_file() else []
        names=[row['database'] for row in values]
        require(all(type(n) is str and re.fullmatch(r'aijade_test_[0-9a-f]{32}',n) for n in names), 'invalid owned lease; nothing dropped')
    except (OSError,ValueError,KeyError,TypeError) as error:
        return [dict(database=None,presentAfterProcessExit=None,remaining=None,error=type(error).__name__+': '+str(error))]
    command=[str(docker),'exec',container,'psql','-X','-U','aijade','-d','aijade','-v','ON_ERROR_STOP=1','-tAc']
    deadline=time.monotonic()+budget_seconds;records=[]
    def query(sql):
        remaining=deadline-time.monotonic()
        require(remaining>0, 'owned cleanup budget exhausted')
        result=run(command+[sql],capture_output=True,text=True,timeout=min(5,remaining),check=False)
        require(result.returncode==0, 'database cleanup command failed: '+result.stderr.strip()[:1000])
        return result.stdout.strip()
    for name in dict.fromkeys(names):
        row=dict(database=name,presentAfterProcessExit=None,remaining=None,error=None)
        try:
            count=query("SELECT count(*) FROM pg_database WHERE datname='"+name+"'")
            require(count in ['0','1'], 'unknown database presence response')
            row['presentAfterProcessExit']=int(count)
            if count=='1':
                query('DROP DATABASE '+name+' WITH (FORCE)')
            count=query("SELECT count(*) FROM pg_database WHERE datname='"+name+"'")
            require(count in ['0','1'], 'unknown final database presence response')
            row['remaining']=int(count)
        except (OSError,ValueError,subprocess.SubprocessError) as error:
            row['error']=type(error).__name__+': '+str(error)
        records.append(row)
    return records


def stop_owned_processes(roots, grace_seconds=5):
    records=[]
    for root in roots:
        row=dict(pid=root.pid,exitCode=root.poll(),errors=[])
        if row['exitCode'] is None:
            try:os.killpg(root.pid,signal.SIGTERM)
            except OSError as error:row['errors'].append(type(error).__name__+': '+str(error))
        records.append(row)
    deadline=time.monotonic()+grace_seconds
    while any(p.poll() is None for p in roots) and time.monotonic()<deadline:
        time.sleep(.05)
    for root,row in zip(roots,records):
        if root.poll() is None:
            try:os.killpg(root.pid,signal.SIGKILL)
            except OSError as error:row['errors'].append(type(error).__name__+': '+str(error))
        try:root.wait(timeout=1)
        except (subprocess.SubprocessError,ValueError) as error:row['errors'].append(type(error).__name__+': '+str(error))
        row['exitCode']=root.poll()
    return records


def dispositions(root, planned, flow_started=False):
    """Partial/missing capture cannot be silently promoted to an unattempted or zero-error record."""
    root=Path(root);completed=[];started=set();errors=[]
    try:
        rows=json.loads((root/'cases.json').read_text()) if (root/'cases.json').is_file() else []
        completed=[r['caseId']+'/'+r['condition'] for r in rows]
        require(len(completed)==len(set(completed)) and set(completed)<=set(planned), 'invalid completed population')
    except (OSError,ValueError,KeyError,TypeError) as error:
        errors.append(type(error).__name__+': '+str(error));completed=[]
    try:
        for line in (root/'journal.jsonl').read_text().splitlines() if (root/'journal.jsonl').is_file() else []:
            key=json.loads(line)['caseId']
            if '/' in key:
                require(key in planned, 'unexpected journal identity');started.add(key)
    except (OSError,ValueError,KeyError,TypeError) as error:
        errors.append(type(error).__name__+': '+str(error))
    unknown=[p for p in planned if p not in completed and p not in started] if flow_started and (errors or not (root/'journal.jsonl').is_file()) else []
    return dict(completedCaseIds=completed,inFlightCaseIds=[p for p in planned if p in started and p not in completed],unknownCaseIds=unknown,
                unattemptedCaseIds=[p for p in planned if p not in started and p not in completed and p not in unknown],dispositionErrors=errors)


def read_block_receipt(path):
    try:
        value=json.loads(Path(path).read_text())
        require(type(value) is dict and value.get('status')=='COMPLETE_FINITE_BLOCK_OBSERVATIONS', 'missing/noncomplete block receipt')
        return value
    except (OSError,ValueError,TypeError) as error:
        raise ValueError('block did not produce a complete terminal receipt: '+str(error)) from error
