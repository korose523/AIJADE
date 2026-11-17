"""Pinned-source ordering controls, real thread/flock, no spawned processes."""
import ast
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

REPO=Path(os.environ.get('AIJADE_LOCK_ORDER_REPO',str(Path(__file__).resolve().parents[2])))
sys.path.insert(0,str(REPO/'experiments/ch7'))
import process_lifecycle as life
SCRATCH=Path(os.environ.get('AIJADE_LOCK_ORDER_SCRATCH',str(REPO/'.runtime/registry-capture-controls')))
SCRATCH.mkdir(parents=True,exist_ok=True)


class ControlledNoSpawn(RuntimeError):pass


class RegistryCaptureOrderControls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.posix=self.root/'.runtime/posix';(self.posix/'locks').mkdir(parents=True)
        for key,value in [('BASE',self.root),('POSIX',self.posix)]:
            p=mock.patch.object(life,key,value);p.start();self.addCleanup(p.stop)
        self.registry=object.__new__(life.Registry)
        r=self.registry
        r.path=self.posix/'journal.jsonl';r.path.touch(mode=0o600)
        r.lock_path=self.posix/'locks/shared.lock'
        r.stage='fixture';r.writer=dict(pid=20,createTimeMicros=20000000,parentPid=1)
        r.source_commit='2'*40;r.policy_sha256='3'*64;r.run_id='1'*32
        r._mutex=threading.RLock();r.handles=[];r.scope_id='5'*32;r.closed=False
        r._cached_raw=b'';r._cached_state=None;r._cached_inode=None;r._policy=None
        r._cached_hasher=hashlib.sha256();r._cache_poison_reason=None;r._roots=[]
        r.refused_processes=[];r.refused_process_records=[];r.launch_refusal_records=[]
        r.parent_lease_id=None
        r._append('CONTROLLER_REGISTER',dict(leaseId='4'*32,role='controller',stageId='fixture',identity=r.writer,
            parentIdentity=None,commandSha256='a'*64,executableSha256='b'*64,readyMonotonic=0.))
        r._append('SCOPE_OPEN',dict(scopeId=r.scope_id,controllerIdentity=r.writer,parentLeaseId=None,stageId='fixture'))
        self.command=self.root/'synthetic-never-executed';self.command.write_bytes(b'fixture only; Popen is intercepted')

    def test_actual_source_has_no_mutex_before_capture_in_launch_or_run(self):
        source=Path(life.__file__).read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),'93e12314fd66c4cde97323afcda7c6f7ba3e08a9a9fe078aba6b22845ea12c65')
        tree=ast.parse(source);registry=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Registry')
        methods={n.name:n for n in registry.body if isinstance(n,ast.FunctionDef)}
        for name in ('launch','run'):
            self.assertEqual(methods[name].decorator_list,[])
            self.assertFalse(any(isinstance(n,ast.With) and any(isinstance(i.context_expr,ast.Attribute) and i.context_expr.attr=='_mutex' for i in n.items) for n in ast.walk(methods[name])))
        for name in ('_append','_state','sample','remember','close'):
            self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='capture_lock' for n in ast.walk(methods[name])))

    def test_actual_launch_reaches_shared_capture_without_holding_private_mutex(self):
        observed=[];original=life.capture_lock
        @contextmanager
        def capture(path,*args,**kwargs):
            observed.append(('request',self.registry._mutex._is_owned()))
            with original(path,*args,**kwargs) as value:
                observed.append(('acquired',self.registry._mutex._is_owned()))
                yield value
        def no_spawn(*args,**kwargs):
            self.assertFalse(self.registry._mutex._is_owned())
            raise ControlledNoSpawn('control stops before OS spawn')
        with mock.patch.object(life,'capture_lock',capture),mock.patch.object(life.subprocess,'Popen',side_effect=no_spawn):
            with self.assertRaises(ControlledNoSpawn):self.registry.launch([str(self.command)])
        self.assertEqual(observed,[('request',False),('acquired',False)])
        self.assertEqual(len(self.registry._state()['launchRefusals']),1)

    def test_two_actual_launches_same_registry_serialize_without_inverse_mutex(self):
        original=life.capture_lock
        second_requested=threading.Event();release=threading.Event()
        seen=[];errors=[];threads=[];record_lock=threading.Lock()
        @contextmanager
        def capture(path,*args,**kwargs):
            name=threading.current_thread().name
            with record_lock:seen.append((name,'request',self.registry._mutex._is_owned()))
            if name=='second':second_requested.set()
            with original(path,*args,**kwargs) as value:
                with record_lock:seen.append((name,'acquired',self.registry._mutex._is_owned()))
                yield value
        def no_spawn(*args,**kwargs):
            if threading.current_thread().name=='first':
                if not second_requested.wait(.5):raise AssertionError('second thread did not request capture')
                if not release.wait(.5):raise AssertionError('bounded release was not supplied')
            raise ControlledNoSpawn('control stops before OS spawn')
        def launch():
            try:self.registry.launch([str(self.command)])
            except ControlledNoSpawn:pass
            except BaseException as error:errors.append(error)
        with mock.patch.object(life,'capture_lock',capture),mock.patch.object(life.subprocess,'Popen',side_effect=no_spawn):
            try:
                first=threading.Thread(target=launch,name='first');threads.append(first);first.start()
                deadline=time.monotonic()+.5
                while not any(row[:2]==('first','acquired') for row in seen):
                    self.assertLess(time.monotonic(),deadline);time.sleep(.001)
                second=threading.Thread(target=launch,name='second');threads.append(second);second.start()
                self.assertTrue(second_requested.wait(.5))
                self.assertFalse(any(row[:2]==('second','acquired') for row in seen))
            finally:
                release.set()
                for thread in threads:thread.join(3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors,[])
        self.assertTrue(all(held is False for _,_,held in seen))
        self.assertEqual(len(self.registry._state()['launchRefusals']),2)

    def test_actual_append_completes_while_other_thread_holds_capture(self):
        errors=[];done=threading.Event()
        def append():
            try:self.registry._append('SCOPE_CLOSE',dict(scopeId=self.registry.scope_id))
            except BaseException as error:errors.append(error)
            finally:done.set()
        with life.capture_lock(self.registry.lock_path):
            thread=threading.Thread(target=append,name='journal-only-append');thread.start()
            completed_while_capture=done.wait(.5)
        thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertTrue(completed_while_capture,'actual append unexpectedly requested shared capture')


if __name__=='__main__':unittest.main()
