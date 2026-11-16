"""Versioned bulk observer controls; fixtures are not qualification evidence."""
import base64
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'experiments/ch7'))
import mac_process_guard_v2 as guard
from test_mac_process_guard import policy as old_policy, listener, empty_api


def policy(helper=None):
    value = old_policy()
    value.update(schemaVersion=2, kind='mac-bulk-observed-idle-daemon-v2',
                 nativeHelper={'path': str(helper or guard.WORKSPACE / '.runtime/posix/tmp/offline-native-helper'),
                               'sha256': 'a' * 64, 'sourceSha256': guard._file_sha(guard.CENSUS_SOURCE)})
    return value


def row(pid, parent, category='other', seconds=None):
    return {'pid': pid, 'parentPid': parent, 'createTimeMicros': (seconds if seconds is not None else pid) * 1000000,
            'category': category, 'commandNameAtLimit': False}


def native(extra=(), collector_pid=500, parent=20, attempts=1):
    rows = sorted([row(1, 0), row(10, 1, 'ollama'), row(11, 10, 'ollama'), row(parent, 1),
                   row(collector_pid, parent), *extra], key=lambda x: x['pid'])
    abi, query = 648, len(rows) * 648
    history, cap = [], guard._capacity(query, abi)
    initial = cap
    for index in range(attempts):
        last = index == attempts - 1
        history.append({'capacityBytes': cap, 'returnedBytes': query if last else cap,
                        'result': 0 if last else -1, 'errno': 0 if last else 12})
        if not last: cap = guard._capacity(cap, abi)
    return {'schema': guard.CENSUS_SCHEMA, 'status': 'OK', 'recordCount': len(rows), 'returnedBytes': query,
            'abiRecordBytes': abi, 'sizeQueryBytes': query, 'initialCapacityBytes': initial,
            'capacityBytes': cap, 'readAttempts': attempts, 'enomemGrowths': attempts - 1,
            'maxCapacityBytes': guard.MAX_KERNEL_BYTES, 'maxReadAttempts': 3, 'maxOutputBytes': guard.MAX_CENSUS_BYTES,
            'startedMonotonicNs': 1000000000, 'finishedMonotonicNs': 1001000000,
            'clockKind': 'clock_gettime.CLOCK_MONOTONIC', 'nameField': 'kinfo_proc.p_comm',
            'commandNameMaxBytes': 16, 'categoryRule': 'ascii-casefold-kinfo-comm-v1',
            'atLimitCount': 0, 'recordsSortedByPid': True, 'notAtomicMachineHistory': True,
            'collector': {'pid': collector_pid, 'parentPid': parent, 'createTimeMicros': collector_pid * 1000000, 'rssBytes': 4000000},
            'readHistory': history, 'attemptCapacities': [x['capacityBytes'] for x in history],
            'readErrnos': [x['errno'] for x in history], 'records': rows}


def evidence(p, data):
    raw = (json.dumps(data, separators=(',', ':')) + '\n').encode()
    identity = {'device': 1, 'inode': 2, 'regular': True, 'singleLink': True, 'ownedByCurrentUser': True}
    return {'helperSha256Before': p['nativeHelper']['sha256'], 'helperSha256After': p['nativeHelper']['sha256'],
            'sourceSha256Before': p['nativeHelper']['sourceSha256'], 'sourceSha256After': p['nativeHelper']['sourceSha256'],
            'spawnedHelperPid': data['collector']['pid'], 'observerPid': data['collector']['parentPid'],
            'exitCode': 0, 'cleanupKnown': True, 'timedOut': False, 'oversized': False, 'stderrBytes': 0,
            'durationSeconds': 0.01, 'observerClockKind': 'python.time.monotonic',
            'stdoutBase64': base64.b64encode(raw).decode(), 'stdoutSha256': hashlib.sha256(raw).hexdigest(), 'stdoutBytes': len(raw),
            'captureLock': {'schema': 'aijade.mac.capture-lock.v1', 'state': 'HELD_AND_RELEASED',
                            'pathSha256': guard._sha_bytes(str(guard._lock_path(p['nativeHelper']['path'])).encode()),
                            'waitSeconds': 0.001, 'heldSeconds': 0.01, 'maxWaitSeconds': 0.5, 'maxHoldSeconds': 1.0,
                            'initialIdentity': identity, 'finalIdentity': dict(identity)}}


def graph(p, data):
    saved = evidence(p, data)
    rows, _ = guard.parse_native_evidence(p, saved)
    return {'schema': 'aijade.mac.bulk-process-graph.v2', 'nodes': rows, 'errors': [], 'nativeCensus': saved}


class BulkObserverControls(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='mac-bulk-observer-controls-')
        self.root = Path(self.scratch.name)
    def tearDown(self): self.scratch.cleanup()

    def observe(self, before=None, after=None, roots=(), rss=None, api=None, identities=None, listeners=None):
        p = policy()
        before = before or native()
        after = after or native(collector_pid=501)
        def identity(pid): return copy.deepcopy(p['daemon']['app' if pid == 10 else 'serve'])
        def actual_rss(node):
            if node['pid'] in (500, 501): raise AssertionError('exited exact collector must use its native self witness')
            return 1000
        with patch.object(guard, '_read_processes', side_effect=[graph(p, before), graph(p, after)]), \
             patch.object(guard, '_read_identity', side_effect=identities or identity), \
             patch.object(guard, '_read_rss', side_effect=rss or actual_rss), \
             patch.object(guard, '_read_api', return_value=api or empty_api()), \
             patch.object(guard, '_read_listeners', return_value=listeners or listener()):
            return guard.observe(p, roots)

    def test_old_source_bytes_and_versioned_policy_are_preserved(self):
        self.assertEqual(guard._file_sha(REPO / 'experiments/ch7/mac_process_guard.py'), 'be8df86b47f382f663eab4f22553025a41661326695d112cfc30ffbe1c677d87')
        with self.assertRaises(ValueError): guard.validate_policy(old_policy())
        guard.validate_policy(policy())

    def test_complete_batch_does_not_require_different_responses_to_have_same_population(self):
        observation = self.observe(before=native([row(30, 1)]), after=native([row(31, 1)], collector_pid=501))
        self.assertEqual(observation['status'], 'PASS')
        self.assertNotEqual(observation['evidence']['before']['processGraph']['nodes'], observation['evidence']['after']['processGraph']['nodes'])
        self.assertEqual(observation['ownedRssBytes'], 0)

    def test_only_exact_exited_collector_gets_native_self_rss(self):
        observation = self.observe(roots=[(20, 20.0)])
        self.assertEqual(observation['status'], 'PASS')
        self.assertEqual(observation['ownedRssBytes'], 4001000)
        self.assertEqual(observation['ownedProcesses'][-1]['rssSource'], 'native-collector-self')
        def denied(node): raise PermissionError('fixture unknown ordinary owned RSS')
        adverse = self.observe(roots=[(20, 20.0)], rss=denied)
        self.assertEqual(adverse['status'], 'UNKNOWN'); self.assertIsNone(adverse['ownedRssBytes'])

    def test_forbidden_processes_and_unknown_descendants_are_not_filtered(self):
        for extra in (row(40, 1, 'dotnet'), row(40, 1, 'godot'), row(40, 1, 'ollama'), row(40, 11)):
            with self.subTest(extra=extra): self.assertEqual(self.observe(before=native([extra]))['status'], 'FAIL')
        self.assertEqual(self.observe(before=native([row(40, 20, 'dotnet')]), after=native([row(40, 20, 'dotnet')], collector_pid=501), roots=[(20, 20.0)])['status'], 'PASS')

    def test_native_substitution_parse_errors_cannot_be_replayed_as_pass(self):
        observation = self.observe()
        mutations = [lambda x: x.update(nativeHelperSha256='f' * 64), lambda x: x.update(observerModuleSha256='f' * 64),
                     lambda x: x['evidence']['after']['processGraph']['nativeCensus'].update(helperSha256After='f' * 64),
                     lambda x: x['evidence']['after']['processGraph']['nativeCensus'].update(stdoutSha256='f' * 64),
                     lambda x: x['evidence']['after']['processGraph']['nativeCensus']['captureLock'].update(state='HELD'),
                     lambda x: x.update(ownedRssBytes=999)]
        for mutate in mutations:
            changed = copy.deepcopy(observation); mutate(changed)
            with self.subTest(mutation=mutate): self.assertNotEqual(guard.validate_observation(policy(), changed)['status'], 'PASS')

    def test_validation_never_executes_helper_or_requires_live_mac(self):
        observation = self.observe()
        with patch.object(guard, '_run_native', side_effect=AssertionError('not offline')), \
             patch.object(guard, '_read_identity', side_effect=AssertionError('not offline')), \
             patch.object(guard, '_read_api', side_effect=AssertionError('not offline')):
            self.assertEqual(guard.validate_observation(policy(), observation)['status'], 'PASS')

    def test_empty_truncated_misaligned_duplicate_unknown_and_invalid_rows_refuse(self):
        changes = [lambda d: d.update(records=[], recordCount=0, returnedBytes=0),
                   lambda d: d.update(returnedBytes=d['returnedBytes'] - 1),
                   lambda d: d['records'].append(copy.deepcopy(d['records'][0])),
                   lambda d: d['records'][0].update(pid=-1),
                   lambda d: d['records'][0].update(category='unknown'),
                   lambda d: d['records'][0].update(createTimeMicros=float('nan')),
                   lambda d: d.update(recordCount=True),
                   lambda d: d.update(abiRecordBytes=0),
                   lambda d: d.update(capacityBytes=guard.MAX_KERNEL_BYTES + 1)]
        p = policy()
        for mutate in changes:
            data = native(); mutate(data)
            with self.subTest(change=mutate):
                with self.assertRaises((ValueError, TypeError)): guard.parse_native_evidence(p, evidence(p, data))

    def test_only_bounded_enomem_growth_may_lead_to_complete_response(self):
        p = policy()
        for attempts in (1, 2, 3): guard.parse_native_evidence(p, evidence(p, native(attempts=attempts)))
        for mutate in [lambda d: d['readHistory'][0].update(errno=22),
                       lambda d: d.update(readAttempts=4), lambda d: d.update(enomemGrowths=0),
                       lambda d: d.update(readErrnos=[12, 12, False]),
                       lambda d: d['readHistory'][1].update(capacityBytes=d['readHistory'][0]['capacityBytes'])]:
            data = native(attempts=3); mutate(data)
            with self.assertRaises(ValueError): guard.parse_native_evidence(p, evidence(p, data))

    def test_native_and_python_clock_origins_are_not_compared(self):
        p = policy(); data = native()
        data['startedMonotonicNs'] += 9000000000000000
        data['finishedMonotonicNs'] += 9000000000000000
        guard.parse_native_evidence(p, evidence(p, data))
        data['finishedMonotonicNs'] += 600000000
        with self.assertRaises(ValueError): guard.parse_native_evidence(p, evidence(p, data))

    def test_short_name_limit_is_explicit_and_ancestry_errors_are_adverse(self):
        before = native()
        before['records'][-1]['commandNameAtLimit'] = True; before['atLimitCount'] = 1
        self.assertEqual(self.observe(before=before)['status'], 'PASS')
        wrong = native([row(40, 50), row(50, 40)])
        self.assertNotEqual(self.observe(before=wrong)['status'], 'PASS')
        reused = native(); reused['records'][1]['createTimeMicros'] += 1
        self.assertEqual(self.observe(before=reused)['status'], 'FAIL')

    def test_listener_api_loaded_model_and_identity_failures_remain_adverse(self):
        loaded = {'state': 'NONEMPTY', 'durationSeconds': 0.01, 'modelCount': 1}
        self.assertEqual(self.observe(api=loaded)['status'], 'FAIL')
        self.assertEqual(self.observe(api={'state': 'UNKNOWN', 'durationSeconds': 0.01})['status'], 'UNKNOWN')
        self.assertEqual(self.observe(listeners={'state': 'UNKNOWN'})['status'], 'UNKNOWN')
        p = policy()
        def changed(pid):
            item = copy.deepcopy(p['daemon']['app' if pid == 10 else 'serve']); item['sha256'] = 'f' * 64; return item
        self.assertEqual(self.observe(identities=changed)['status'], 'FAIL')

    def test_lock_unknown_timeout_replacement_and_truncation_are_adverse(self):
        p = policy(); saved = evidence(p, native())
        for modify in [lambda l: l.update(waitSeconds=0.6), lambda l: l.update(state='UNKNOWN'),
                       lambda l: l['finalIdentity'].update(inode=999)]:
            changed = copy.deepcopy(saved); modify(changed['captureLock'])
            with self.assertRaises(ValueError): guard.parse_native_evidence(p, changed)
        lock = self.root / 'fixed.lock'; lock.write_bytes(b'untouched sentinel')
        with patch.object(guard, '_lock_path', return_value=lock):
            with guard._capture_lock(p['nativeHelper']['path']) as metadata: self.assertEqual(metadata['state'], 'HELD')
        self.assertEqual(lock.read_bytes(), b'untouched sentinel')
        self.assertEqual(metadata['state'], 'HELD_AND_RELEASED')
        linked = self.root / 'linked.lock'; linked.symlink_to(lock)
        with patch.object(guard, '_lock_path', return_value=linked):
            with self.assertRaises(OSError):
                with guard._capture_lock(p['nativeHelper']['path']): pass

    def test_real_cross_process_lock_wait_has_fixed_deadline(self):
        lock = self.root / 'busy.lock'
        program = 'import fcntl,os,sys,time; f=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); time.sleep(0.8)'
        child = subprocess.Popen([sys.executable, '-B', '-c', program, str(lock)], stdout=subprocess.PIPE)
        try:
            self.assertEqual(child.stdout.readline().strip(), b'ready')
            with patch.object(guard, '_lock_path', return_value=lock):
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    with guard._capture_lock(policy()['nativeHelper']['path']): pass
                self.assertLess(time.monotonic() - started, 0.7)
        finally:
            child.wait(timeout=2); child.stdout.close()

    def fixture(self, behavior):
        path = self.root / ('disposable-fixture-' + str(len(list(self.root.iterdir()))))
        path.write_text('#!' + sys.executable + '\n' + behavior)
        path.chmod(0o755)
        return path

    def test_native_pipe_cap_timeout_and_cleanup_are_bounded(self):
        big = self.fixture('import os;os.write(1,b"x"*(4194304+10000))\n')
        result = guard._run_native(big)
        self.assertTrue(result['oversized']); self.assertTrue(result['cleanupKnown'])
        self.assertLessEqual(len(result['stdout']), guard.MAX_CENSUS_BYTES + 1)
        slow = self.fixture('import time;time.sleep(5)\n')
        result = guard._run_native(slow)
        self.assertTrue(result['timedOut']); self.assertTrue(result['cleanupKnown'])

    def test_two_concurrent_disposable_captures_serialize_and_do_not_capture_peer(self):
        template = native(parent=20)
        active, events = self.root / 'active.json', self.root / 'events.jsonl'
        # A native disposable fixture avoids measuring a cold Python startup
        # against the production native helper's unchanged 0.5-second deadline.
        compiler = shutil.which('cc')
        if compiler is None: self.skipTest('A native fixture compiler is unavailable')
        template.update(records='@ROWS@', recordCount=3, returnedBytes=1944)
        template['readHistory'][-1]['returnedBytes'] = 1944
        template['collector'].update(pid='@CHILD@', parentPid='@PARENT@', createTimeMicros=30000000)
        wire = json.dumps(template, separators=(',', ':')).replace('"@CHILD@"', '%d').replace('"@PARENT@"', '%d').replace('"@ROWS@"', '%s') + '\n'
        self.assertEqual(wire.count('%d'), 2); self.assertEqual(wire.count('%s'), 1)
        source = self.root / 'disposable-capture.c'; helper = self.root / 'disposable-native-capture'
        zero = json.dumps(row(0, 0, seconds=0), separators=(',', ':'))
        parent_format = json.dumps(row(999, 0, seconds=20), separators=(',', ':')).replace('999', '%d', 1)
        child_format = json.dumps(row(998, 997, seconds=30), separators=(',', ':')).replace('998', '%d', 1).replace('997', '%d', 1)
        source.write_text('''#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <time.h>
#include <unistd.h>
int main(void) {
  int pid=(int)getpid(), parent=(int)getppid(), peer=0;
  FILE *f=fopen(ACTIVE,"r"); if(f){(void)fscanf(f,"%d",&peer);fclose(f);}
  f=fopen(EVENTS,"a"); if(!f)return 2;
  fprintf(f,"{\\"pid\\":%d,\\"peer\\":",pid);
  if(peer)fprintf(f,"%d",peer);else fputs("null",f);fputs("}\\n",f);fclose(f);
  f=fopen(ACTIVE,"w");if(!f)return 3;fprintf(f,"%d",pid);fclose(f);
  struct timespec pause={0,60000000};nanosleep(&pause,0);
  char p[256], c[256], rows[1024];
  snprintf(p,sizeof(p),PARENT_ROW,parent);snprintf(c,sizeof(c),CHILD_ROW,pid,parent);
  if(parent<pid)snprintf(rows,sizeof(rows),"[%s,%s,%s]",ZERO_ROW,p,c);
  else snprintf(rows,sizeof(rows),"[%s,%s,%s]",ZERO_ROW,c,p);
  unlink(ACTIVE);printf(WIRE,pid,parent,rows);return 0;
}
'''.replace('int main(void)', '#define ACTIVE ' + json.dumps(str(active)) + '\n#define EVENTS ' + json.dumps(str(events)) +
              '\n#define PARENT_ROW ' + json.dumps(parent_format) + '\n#define CHILD_ROW ' + json.dumps(child_format) +
              '\n#define ZERO_ROW ' + json.dumps(zero) + '\n#define WIRE ' + json.dumps(wire) + '\nint main(void)'))
        compiled = subprocess.run([compiler, '-std=c11', str(source), '-o', str(helper)], capture_output=True, timeout=30)
        self.assertEqual(compiled.returncode, 0, compiled.stderr.decode(errors='replace'))
        p = policy(helper); p['nativeHelper']['sha256'] = guard._file_sha(helper)
        lock = self.root / 'concurrent.lock'
        results, errors = [], []
        barrier = threading.Barrier(2)
        def capture():
            try: barrier.wait(); results.append(guard._read_processes(p))
            except Exception as error: errors.append(type(error).__name__)
        with patch.object(guard, '_lock_path', return_value=lock):
            threads = [threading.Thread(target=capture) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=3)
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(not result['errors'] for result in results), results)
        self.assertTrue(all(json.loads(line)['peer'] is None for line in events.read_text().splitlines()))
        self.assertTrue(all(result['nativeCensus']['captureLock']['state'] == 'HELD_AND_RELEASED' for result in results))


if __name__ == '__main__': unittest.main()
