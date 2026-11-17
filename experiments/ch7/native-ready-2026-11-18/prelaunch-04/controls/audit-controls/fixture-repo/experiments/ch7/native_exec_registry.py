"""Explicit AIJADE native READY adapter; original lifecycle implementation remains intact.

Only native shim/provenance and detached phase evidence differ in launch. Canonical
journal state, prefix verification, refusals and ManagedProcess actual waits are
provided by the pinned original module. Legacy factories keep the original class.
"""
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import stat
import subprocess
import threading
import time
from types import MappingProxyType
import uuid
import process_lifecycle as life

MODE='native-ready-release-v1'
LIFECYCLE_SHA256='93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65'
LEGACY_SHIM_SHA256='ecd60bb498802a220d5e2217cabda8dd3fcd601a77ed5dacb2417a3ecc998bc3'
need=life.need
_number=life._number
_unique=life._unique
_open_owned=life._open_owned
canonical=life.canonical
digest=life.digest
identity=life.identity
identity_key=life.identity_key
capture_lock=life.capture_lock
READY_SECONDS=life.READY_SECONDS
ManagedProcess=life.ManagedProcess
BINDING_KEYS={'mode','adapterSourceSha256','sourcePath','sourceSha256','binaryPath','binarySha256'}


def _authenticated_file(path,expected,*,executable=False):
    path=life.project_path(path)
    need(life._hex(expected),'native source/binary full SHA required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink==1,'native provenance requires one regular inode')
        if executable:
            need(before.st_uid==os.getuid() and stat.S_IMODE(before.st_mode)==0o755,
                 'native shim exact owner/executable mode')
        hasher=hashlib.sha256()
        while block:=os.read(fd,1024*1024):hasher.update(block)
        after=os.fstat(fd);current=os.stat(path,follow_symlinks=False)
        def key(value):return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_mode)
        need(key(before)==key(after)==key(current) and hasher.hexdigest()==expected,
             'native provenance content or metadata changed')
        return dict(path=str(path),sha256=expected,device=before.st_dev,inode=before.st_ino,
            sizeBytes=before.st_size,mtimeNs=before.st_mtime_ns,mode=stat.S_IMODE(before.st_mode))
    finally:os.close(fd)


def _executed_shim(process,shim,argv,birth):
    import psutil
    item=psutil.Process(process.pid)
    before=round(item.create_time()*1000000)
    observed_executable=item.exe();observed_argv=item.cmdline();parent=item.ppid()
    after=round(psutil.Process(process.pid).create_time()*1000000)
    need(before==after==birth['createTimeMicros'] and parent==birth['parentPid']
         and Path(observed_executable)==shim and observed_argv==argv,
         'actual gated native shim image/argv/birth differs')
    return dict(pid=process.pid,createTimeMicros=before,parentPid=parent,
        executable=str(shim),argvSha256=digest(canonical(argv)))


class NativeExecRegistry(life.Registry):
    def __init__(self,*args,native_exec,**kwargs):
        need(type(native_exec) is dict and set(native_exec)==BINDING_KEYS and native_exec['mode']==MODE,
             'explicit native exec binding required')
        need(digest(Path(life.__file__).read_bytes())==LIFECYCLE_SHA256
             and digest(Path(life.__file__).with_name('lifecycle_exec.py').read_bytes())==LEGACY_SHIM_SHA256,
             'preserved lifecycle or legacy shim changed')
        self._native_binding=MappingProxyType(dict(native_exec))
        self._native_generation=None
        self._native_launch_records={}
        self._verify_native_binding()
        super().__init__(*args,**kwargs)

    def _verify_native_binding(self):
        value=self._native_binding
        need(Path(value['sourcePath'])==Path(__file__).with_name('lifecycle_exec_native.c'),
             'exact colocated native C source required')
        proof=dict(adapter=_authenticated_file(__file__,value['adapterSourceSha256']),
            source=_authenticated_file(value['sourcePath'],value['sourceSha256']),
            binary=_authenticated_file(value['binaryPath'],value['binarySha256'],executable=True))
        need(self._native_generation is None or proof==self._native_generation,
             'native shim generation changed since Registry binding')
        if self._native_generation is None:self._native_generation=copy.deepcopy(proof)
        return proof

    def native_launch_records(self):
        with self._mutex:return copy.deepcopy(self._native_launch_records)

    def launch(self,command,*,role='finite',stage=None,ready_timeout=None,**kwargs):
        attempt_id=uuid.uuid4().hex;started=time.monotonic()
        process=None;registered=False;released=False;launched=False;raw=bytearray();reads=[];owns_group=False
        ready_r=ready_w=gate_r=gate_w=-1;executable_sha=None;command_sha=None
        handle=None;active_error=None
        contexts=ExitStack()
        evidence=dict(schema='aijade.lifecycle.native-launch.v1',mode=MODE,leaseId=attempt_id,
            stageId=stage or self.stage,role=role,phaseClocks={'requestStartedMonotonic':started})
        clocks=evidence['phaseClocks']
        try:
            self._require_cache_usable()
            evidence['sourceProofBefore']=self._verify_native_binding()
            evidence.update(adapterSourceSha256=self._native_binding['adapterSourceSha256'],
                shimSourceSha256=self._native_binding['sourceSha256'],
                shimSha256=self._native_binding['binarySha256'])
            need(not self.closed,'cannot launch after local persistent scope closes')
            need(role in ('finite','controller') and type(command) in (list,tuple) and command
                 and all(type(x) is str and '\x00' not in x for x in command),'finite command schema')
            command_sha=digest(canonical(list(command)))
            need(not kwargs.get('shell') and not kwargs.get('preexec_fn') and not kwargs.get('pass_fds'), 'unsupported subprocess escape')
            need(type(kwargs.get('start_new_session',False)) is bool,'start_new_session must be explicit boolean')
            owns_group=kwargs.get('start_new_session',False)
            ready_budget=READY_SECONDS if ready_timeout is None else ready_timeout
            need(_number(ready_budget) and 0<ready_budget<=READY_SECONDS,'identity-ready deadline invalid')
            env=dict(os.environ if kwargs.get('env') is None else kwargs.pop('env'))
            env.update(self.environment());env['AIJADE_LIFECYCLE_STAGE']=stage or self.stage
            executable=shutil.which(command[0],path=env.get('PATH')) if not Path(command[0]).is_absolute() else command[0]
            need(executable is not None,'finite executable missing')
            # Preserve virtualenv argv0; hash its actual executable target.
            executable=Path(executable).absolute();executable_sha=digest(executable.resolve(strict=True).read_bytes())
            env['AIJADE_LIFECYCLE_PARENT_LEASE']=attempt_id
            shim=Path(self._native_binding['binaryPath'])
            clocks['captureRequestedMonotonic']=time.monotonic()
            coordination=contexts.enter_context(capture_lock(self.lock_path))
            clocks['captureAcquiredMonotonic']=time.monotonic()
            evidence['captureLock']=coordination
            ready_r,ready_w=os.pipe();gate_r,gate_w=os.pipe()
            native_argv=[str(shim),str(ready_w),str(gate_r),'--',str(executable),*command[1:]]
            clocks['popenStartedMonotonic']=time.monotonic()
            process=subprocess.Popen(native_argv,
                env=env,pass_fds=(ready_w,gate_r),**kwargs)
            clocks['popenReturnedMonotonic']=time.monotonic()
            os.close(ready_w);ready_w=-1;os.close(gate_r);gate_r=-1
            selected=selectors.DefaultSelector();selected.register(ready_r,selectors.EVENT_READ)
            deadline=time.monotonic()+ready_budget
            try:
                while b'\n' not in raw:
                    remaining=deadline-time.monotonic();need(remaining>0,'identity-ready timeout')
                    need(selected.select(remaining),'identity-ready timeout')
                    block=os.read(ready_r,4097-len(raw));need(block,'identity-ready EOF')
                    raw.extend(block);need(len(raw)<=4096,'identity-ready cap')
            finally:selected.close()
            clocks['readyReadCompletedMonotonic']=time.monotonic()
            ready=json.loads(bytes(raw),object_pairs_hook=_unique)
            need(set(ready)=={'pid','parentPid','readyMonotonic'} and type(ready['pid']) is int
                 and ready['pid']==process.pid and ready['parentPid']==self.writer['pid']
                 and _number(ready['readyMonotonic']),'identity-ready report mismatch')
            # The exact Popen child stays behind its gate for both kernel reads.
            need(clocks['popenStartedMonotonic']<=ready['readyMonotonic']<=clocks['readyReadCompletedMonotonic']+.002,
                 'native READY clock outside parent launch envelope')
            evidence['readyMonotonic']=ready['readyMonotonic']
            first=identity(process.pid);identity_key(first);reads.append(first)
            clocks['firstIdentityCompletedMonotonic']=time.monotonic()
            evidence['executedShimIdentity']=_executed_shim(process,shim,native_argv,first)
            second=identity(process.pid);identity_key(second);reads.append(second)
            clocks['secondIdentityCompletedMonotonic']=time.monotonic()
            need(first['parentPid']==self.writer['pid'] and second==first
                 and time.monotonic()<=deadline,'identity-ready kernel identity/deadline mismatch')
            evidence['sourceProofReady']=self._verify_native_binding()
            evidence.update(identity=dict(first),commandSha256=command_sha,executableSha256=executable_sha)
            clocks['registerStartedMonotonic']=time.monotonic()
            self._append('FINITE_REGISTER',dict(leaseId=attempt_id,role='finite',stageId=stage or self.stage,
                identity=first,parentIdentity=self.writer,commandSha256=command_sha,executableSha256=executable_sha,
                readyMonotonic=ready['readyMonotonic'],shimSha256=self._native_binding['binarySha256'],
                identityWitnessKind='PARENT_KERNEL_IDENTITY_WHILE_READY_GATE_HELD'))
            clocks['registerCompletedMonotonic']=time.monotonic()
            registered=True
            clocks['releaseStartedMonotonic']=time.monotonic()
            self._append('RELEASE',dict(leaseId=attempt_id));released=True
            clocks['releaseCompletedMonotonic']=time.monotonic()
            need(os.write(gate_w,b'1')==1,'native release byte incomplete')
            clocks['gateWrittenMonotonic']=time.monotonic()
            evidence['sourceProofAfter']=self._verify_native_binding()
            clocks['postProvenanceCompletedMonotonic']=time.monotonic()
            handle=ManagedProcess(self,process,attempt_id)
            self.handles.append(handle);launched=True
            return handle
        except BaseException as error:
            active_error=error
            evidence.update(errorClass=type(error).__name__,errorMessage=str(error))
            clocks['failureMonotonic']=time.monotonic()
            exit_code=None;cleanup_known=process is None
            if process is not None:
                self.refused_processes.append(process)
                self.refused_process_records.append(dict(handle=process,attemptId=attempt_id,ownsProcessGroup=owns_group))
                try:
                    if process.poll() is None:process.kill()
                    exit_code=process.wait(timeout=.5);cleanup_known=True
                except BaseException:cleanup_known=False
            data=dict(attemptId=attempt_id,stageId=stage if type(stage) is str and stage else self.stage,
                commandSha256=command_sha,executableSha256=executable_sha,
                spawnedPid=process.pid if process is not None else None,readyBytes=len(raw),readySha256=digest(bytes(raw)),
                ownsProcessGroup=owns_group,
                identityReads=reads,identityStatus='BOUND' if len(reads)==2 and reads[0]==reads[1] else 'UNKNOWN',
                registeredLeaseId=attempt_id if registered else None,errorClass=type(error).__name__,
                actualExitCode=exit_code,cleanupKnown=cleanup_known,waitSource='Popen.wait' if exit_code is not None else None,
                startedMonotonic=started,cleanupCompletedMonotonic=time.monotonic())
            self.launch_refusal_records.append(dict(data,writer=self.writer))
            try:
                if registered and released and exit_code is not None:
                    lease=self._lease(attempt_id)
                    if lease['waitSeq'] is None:
                        self._append('WAIT',dict(leaseId=attempt_id,identity=lease['identity'],exitCode=exit_code,
                            waitSource='Popen.wait',reapedMonotonic=data['cleanupCompletedMonotonic']))
                self._append('LAUNCH_REFUSED',data)
            except BaseException as journal_error:
                artifact=self.path.with_name('launch-refused-'+attempt_id+'.json')
                document=dict(schema='aijade.process-lifecycle-launch-refusal.v1',runId=self.run_id,writer=self.writer,
                    sourceCommit=self.source_commit,policySha256=self.policy_sha256,data=data,
                    journalAppendErrorClass=type(journal_error).__name__,qualificationAdverse=True)
                try:
                    fd=_open_owned(artifact,os.O_WRONLY|os.O_CREAT|os.O_EXCL)
                    try:os.write(fd,canonical(document)+b'\n');os.fsync(fd)
                    finally:os.close(fd)
                    error.lifecycleRefusalPath=str(artifact)
                except BaseException:pass
            try:error.lifecycleRefusal=data
            except BaseException:pass
            evidence['refusal']=copy.deepcopy(data)
            raise
        finally:
            if process is not None and not launched:
                for stream in (process.stdin,process.stdout,process.stderr):
                    if stream is not None:stream.close()
            for fd in (ready_r,ready_w,gate_r,gate_w):
                if fd>=0:os.close(fd)
            try:
                contexts.close()
            finally:
                clocks['returnedMonotonic']=time.monotonic()
                with self._mutex:self._native_launch_records[attempt_id]=copy.deepcopy(evidence)
                if handle is not None:handle.native_launch_evidence=copy.deepcopy(evidence)
                if active_error is not None:
                    try:active_error.nativeLaunchEvidence=copy.deepcopy(evidence)
                    except BaseException:pass


def evidence_for_handle(handle):
    """Detached phase record plus original canonical actual-wait evidence."""
    need(type(handle) is life.ManagedProcess and type(handle.registry) is NativeExecRegistry,
         'exact native Registry managed handle required')
    registry=handle.registry
    with registry._mutex:
        need(handle.lease_id in registry._native_launch_records,'native launch record missing')
        result=copy.deepcopy(registry._native_launch_records[handle.lease_id])
        state=registry._state();lease=state['leases'][handle.lease_id]
        result.update(waitSequence=lease['waitSeq'],exitCode=lease['exitCode'],
            actualReapedMonotonic=lease.get('reapedMonotonic'),
            waitEventMonotonic=state['events'][lease['waitSeq']-1]['monotonicSeconds'] if lease['waitSeq'] else None,
            waitSource='Popen.wait' if lease['waitSeq'] else None)
        return result


def _policy_binding(policy):
    need(type(policy) is dict,'native Registry policy required')
    mode=policy.get('lifecycleExecMode')
    if mode is None:
        need('nativeExec' not in policy,'native exec fields require explicit mode')
        return None
    need(mode==MODE and type(policy.get('nativeExec')) is dict,'unknown native exec selection')
    value=policy['nativeExec']
    need(set(value)==BINDING_KEYS and value.get('mode')==MODE
         and policy.get('lifecycle',{}).get('execShimSha256')==value.get('binarySha256'),
         'native exec policy/shim binding differs')
    return copy.deepcopy(value)


def registry_for_policy(policy,*args,**kwargs):
    binding=_policy_binding(policy)
    if binding is None:return life.Registry(*args,**kwargs)
    return NativeExecRegistry(*args,native_exec=binding,**kwargs)


def activate_from_environment(policy):
    """Called explicitly before the original lazy factory in a native child."""
    binding=_policy_binding(policy)
    if binding is None:return life.from_environment()
    path=os.environ.get('AIJADE_LIFECYCLE_JOURNAL')
    if not path:return None
    active=getattr(life,'_env_registry',None)
    if active is not None and active.writer['pid']==os.getpid():
        need(type(active) is NativeExecRegistry and dict(active._native_binding)==binding,
             'current process already activated a different Registry')
        active._verify_native_binding()
        return active
    current=identity()
    return NativeExecRegistry(path,[(current['pid'],current['createTimeMicros']/1000000)],
        stage=os.environ['AIJADE_LIFECYCLE_STAGE'],source_commit=os.environ['AIJADE_LIFECYCLE_SOURCE_COMMIT'],
        policy_sha256=os.environ['AIJADE_LIFECYCLE_POLICY_SHA256'],run_id=os.environ['AIJADE_LIFECYCLE_RUN_ID'],
        capture_lock_path=os.environ['AIJADE_LIFECYCLE_CAPTURE_LOCK'],
        parent_lease_id=os.environ['AIJADE_LIFECYCLE_PARENT_LEASE'],native_exec=binding).activate()
