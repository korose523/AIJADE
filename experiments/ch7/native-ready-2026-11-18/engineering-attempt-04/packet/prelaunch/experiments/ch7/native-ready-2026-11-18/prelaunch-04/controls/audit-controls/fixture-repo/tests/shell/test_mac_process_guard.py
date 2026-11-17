"""Offline adverse controls for sampled process/API evidence; no live daemon."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'experiments/ch7'))
import mac_process_guard as guard


def policy():
    return {'schemaVersion': 1, 'kind': guard.KIND,
            'daemon': {'app': {'pid': 10, 'createTime': 10.0, 'parentPid': 1,
                               'executable': '/Applications/Ollama.app/Contents/MacOS/Ollama',
                               'sha256': 'a' * 64, 'argvSha256': 'b' * 64, 'commandForm': 'gui'},
                       'serve': {'pid': 11, 'createTime': 11.0, 'parentPid': 10,
                                 'executable': '/Applications/Ollama.app/Contents/Resources/ollama',
                                 'sha256': 'c' * 64, 'argvSha256': 'd' * 64, 'commandForm': 'serve'}},
            'listener': {'address': '127.0.0.1', 'port': 11434, 'pid': 11},
            'api': {'url': guard.API_URL, 'timeoutSeconds': 0.5, 'maxBytes': 65536}}


def node(pid, parent, created=None, category='other'):
    return {'pid': pid, 'parentPid': parent, 'createTime': float(created if created is not None else pid), 'category': category}


def graph(extra=()):
    nodes = [node(1, 0, 1), node(10, 1, category='ollama'), node(11, 10, category='ollama'), *extra]
    pids = sorted(x['pid'] for x in nodes)
    return {'enumeratedPids': pids, 'endPids': pids, 'nodes': nodes, 'errors': []}


def empty_api():
    raw = b'{"models":[]}'
    return {'state': 'EMPTY', 'httpStatus': 200, 'modelCount': 0, 'bytes': len(raw),
            'bodySha256': hashlib.sha256(raw).hexdigest(), 'emptyBodyBase64': base64.b64encode(raw).decode(),
            'durationSeconds': 0.001}


def listener():
    return {'state': 'OBSERVED', 'records': [{'pid': 11, 'protocol': 'TCP', 'family': 'IPv4',
                                             'endpoint': '127.0.0.1:11434', 'socketState': 'LISTEN'}]}


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = b''
        self.timeouts = []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def settimeout(self, timeout): self.timeouts.append(timeout)
    def sendall(self, raw): self.sent += raw
    def recv(self, cap):
        if not self.chunks: return b''
        raw = self.chunks.pop(0)
        self.assert_cap = cap
        return raw


def http_bytes(body, status=200):
    return ('HTTP/1.1 %d Fixture\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n' % (status, len(body))).encode() + body


class MacProcessGuardControls(unittest.TestCase):
    def observe(self, extra=(), roots=(), api=None, graph_value=None, identities=None, listeners=None, rss=None):
        p = policy()
        value = graph_value if graph_value is not None else graph(extra)
        def read_identity(pid):
            return copy.deepcopy(next(x for x in p['daemon'].values() if x['pid'] == pid))
        with patch.object(guard, '_read_processes', side_effect=lambda: copy.deepcopy(value)), \
             patch.object(guard, '_read_identity', side_effect=identities or read_identity), \
             patch.object(guard, '_read_listeners', side_effect=lambda: copy.deepcopy(listeners or listener())), \
             patch.object(guard, '_read_api', return_value=copy.deepcopy(api if api is not None else empty_api())), \
             patch.object(guard, '_read_rss', side_effect=rss or (lambda item: item['pid'] * 100)):
            return guard.observe(p, owned_roots=roots)

    def assert_adverse(self, observation):
        self.assertIn(observation['status'], ('FAIL', 'UNKNOWN'))
        self.assertIsNone(observation['ownedRssBytes'])
        self.assertNotEqual(guard.validate_observation(policy(), observation)['status'], 'PASS')

    def test_fixed_gui_serve_empty_api_is_accepted_and_replayed_from_evidence(self):
        observation = self.observe()
        self.assertEqual(observation['status'], 'PASS')
        self.assertEqual(observation['ownedRssBytes'], 0)
        self.assertEqual(guard.validate_observation(policy(), observation)['status'], 'PASS')
        self.assertEqual(observation['ownedProcesses'], [])
        self.assertEqual(observation['idleDaemon']['api']['modelCount'], 0)
        self.assertNotIn('executable', observation['evidence']['before']['daemon']['app'])
        self.assertNotIn('argv', json.dumps(observation).replace('argvSha256', ''))

    def test_loaded_model_runner_and_unknown_daemon_descendants_are_refused(self):
        loaded = {'state': 'NONEMPTY', 'httpStatus': 200, 'modelCount': 1, 'durationSeconds': 0.01}
        self.assertEqual(self.observe(api=loaded)['status'], 'FAIL')
        for child in [node(12, 11, category='ollama'), node(12, 10), node(12, 11), node(12, 1, category='ollama')]:
            with self.subTest(child=child): self.assertEqual(self.observe([child])['status'], 'FAIL')

    def test_identity_hash_parent_command_and_creation_changes_are_refused(self):
        for field, changed in [('sha256', 'e' * 64), ('argvSha256', 'f' * 64), ('createTime', 9.0),
                               ('parentPid', 99), ('commandForm', 'runner'), ('executable', '/elsewhere/ollama')]:
            p = policy()
            def identities(pid):
                result = copy.deepcopy(p['daemon']['app' if pid == 10 else 'serve'])
                if pid == 11: result[field] = changed
                return result
            with self.subTest(field=field): self.assertEqual(self.observe(identities=identities)['status'], 'FAIL')

    def test_after_api_snapshot_detects_new_descendant(self):
        p = policy()
        def identity(pid): return copy.deepcopy(p['daemon']['app' if pid == 10 else 'serve'])
        with patch.object(guard, '_read_processes', side_effect=[graph(), graph([node(12, 11)])]), \
             patch.object(guard, '_read_identity', side_effect=identity), patch.object(guard, '_read_listeners', return_value=listener()), \
             patch.object(guard, '_read_api', return_value=empty_api()):
            self.assertEqual(guard.observe(p)['status'], 'FAIL')

    def test_listener_wildcard_unknown_owner_extra_socket_and_read_failure_are_adverse(self):
        for field, value in [('endpoint', '*:11434'), ('endpoint', '[::1]:11434'), ('pid', 55), ('family', 'IPv6')]:
            value_list = listener(); value_list['records'][0][field] = value
            with self.subTest(field=field, value=value): self.assertEqual(self.observe(listeners=value_list)['status'], 'FAIL')
        duplicate = listener(); duplicate['records'] *= 2
        self.assertEqual(self.observe(listeners=duplicate)['status'], 'FAIL')
        self.assert_adverse(self.observe(listeners={'state': 'UNKNOWN', 'code': 'AccessDenied'}))

    def test_foreign_dotnet_and_godot_are_refused_but_complete_owned_tree_is_allowed(self):
        extras = [node(20, 1), node(21, 20, category='dotnet'), node(22, 21, category='godot')]
        self.assertEqual(self.observe(extras)['status'], 'FAIL')
        observation = self.observe(extras, roots=[(20, 20.0)])
        self.assertEqual(observation['status'], 'PASS')
        self.assertEqual([x['pid'] for x in observation['ownedProcesses']], [20, 21, 22])
        self.assertEqual(observation['ownedRssBytes'], 6300)
        replay = guard.validate_observation(policy(), observation)
        self.assertEqual(replay['ownedRssBytes'], 6300)
        self.assertEqual(replay['ownedProcesses'], observation['ownedProcesses'])

    def test_owned_model_runner_is_still_forbidden(self):
        observation = self.observe([node(20, 1), node(21, 20, category='ollama')], roots=[(20, 20.0)])
        self.assertEqual(observation['status'], 'FAIL')

    def test_still_live_owned_descendant_cannot_escape_rss_by_reparenting(self):
        before = graph([node(20, 1), node(21, 20)])
        after = graph([node(20, 1), node(21, 1)])
        p = policy()
        def identity(pid): return copy.deepcopy(p['daemon']['app' if pid == 10 else 'serve'])
        with patch.object(guard, '_read_processes', side_effect=[before, after]), \
             patch.object(guard, '_read_identity', side_effect=identity), patch.object(guard, '_read_listeners', return_value=listener()), \
             patch.object(guard, '_read_api', return_value=empty_api()), patch.object(guard, '_read_rss', return_value=100):
            observation = guard.observe(p, [(20, 20.0)])
        self.assertEqual(observation['status'], 'FAIL')
        self.assertTrue(any(x['code'] == 'OWNED_PROCESS_REPARENTED_OUTSIDE_CLOSURE' for x in observation['blockers']))
        self.assertIsNone(observation['ownedRssBytes'])

    def test_observer_source_read_failure_is_unknown_rather_than_an_uncaught_exception(self):
        with patch.object(guard, '_file_sha', side_effect=PermissionError('fixture')):
            observation = guard.observe(policy())
        self.assertEqual(observation['status'], 'UNKNOWN')
        self.assertIsNone(observation['ownedRssBytes'])

    def test_owned_pid_reuse_missing_rss_and_incomplete_census_are_unknown_not_zero(self):
        self.assert_adverse(self.observe([node(20, 1)], roots=[(20, 19.0)]))
        def denied(node): raise PermissionError('fixture, no process touched')
        self.assert_adverse(self.observe([node(20, 1)], roots=[(20, 20.0)], rss=denied))
        value = graph(); value['enumeratedPids'] += [999]; value['endPids'] += [999]
        self.assert_adverse(self.observe(graph_value=value))
        value = graph(); value['endPids'] = [1, 10]
        self.assert_adverse(self.observe(graph_value=value))
        value = graph(); value['errors'] = [{'code': 'PROCESS_READ_UNKNOWN', 'pid': 999}]
        self.assert_adverse(self.observe(graph_value=value))

    def test_owned_daemon_and_pid_one_cannot_whitelist_the_machine(self):
        self.assertEqual(self.observe(roots=[(10, 10.0)])['status'], 'FAIL')
        self.assert_adverse(self.observe(roots=[(1, 1.0)]))

    def test_offline_replay_rejects_derived_status_identity_body_and_rss_corruption(self):
        original = self.observe([node(20, 1)], roots=[(20, 20.0)])
        mutations = [lambda x: x.update(observerModuleSha256='0' * 64),
                     lambda x: x.update(policyCanonicalSha256='0' * 64),
                     lambda x: x.update(ownedProcesses=[]),
                     lambda x: x.update(ownedRssBytes=0),
                     lambda x: x['evidence']['api'].update(bodySha256='0' * 64),
                     lambda x: x['evidence']['api'].update(modelCount=False),
                     lambda x: x['evidence']['before']['listener']['records'][0].update(pid=11.0),
                     lambda x: x['evidence']['api'].update(emptyBodyBase64=base64.b64encode(b'{"models":[{}]}').decode()),
                     lambda x: x['evidence']['after']['ownedProcesses'][0].update(rssBytes=None),
                     lambda x: x['evidence']['after']['processGraph'].update(endPids=[]),
                     lambda x: x.update(finishedMonotonic=float('nan'))]
        for mutate in mutations:
            observation = copy.deepcopy(original); mutate(observation); observation['status'] = 'PASS'
            with self.subTest(mutation=mutate): self.assertNotEqual(guard.validate_observation(policy(), observation)['status'], 'PASS')

    def test_policy_endpoint_command_form_hash_and_numeric_limits_are_strict(self):
        for mutate in [lambda p: p['api'].update(url='https://example.invalid/api/ps'),
                       lambda p: p['api'].update(timeoutSeconds=0.6),
                       lambda p: p['api'].update(maxBytes=65537),
                       lambda p: p['api'].update(timeoutSeconds=float('nan')),
                       lambda p: p['daemon']['serve'].update(commandForm='runner'),
                       lambda p: p['daemon']['serve'].update(parentPid=1),
                       lambda p: p['daemon']['app'].update(argvSha256=''),
                       lambda p: p['listener'].update(address='0.0.0.0')]:
            p = policy(); mutate(p)
            with self.subTest(mutation=mutate):
                with self.assertRaises(ValueError): guard.validate_policy(p)

    def test_raw_api_only_empty_explicit_list_is_idle_without_proxy_or_redirect(self):
        bodies = [(b'{"models":[]}', 'EMPTY'), (b'{"models":[{}]}', 'NONEMPTY'),
                  (b'{}', 'UNKNOWN'), (b'{"models":null}', 'UNKNOWN'),
                  (b'{"models":false}', 'UNKNOWN'), (b'{"models":[],"models":[]}', 'UNKNOWN'),
                  (b'{"models":[],"private":"not recorded"}', 'UNKNOWN'), (b'broken', 'UNKNOWN')]
        for body, expected in bodies:
            fake = FakeSocket([http_bytes(body)])
            with self.subTest(body=body), patch.object(guard.socket, 'create_connection', return_value=fake) as connect, \
                 patch.dict(os.environ, {'HTTP_PROXY': 'http://unused.invalid:9999'}):
                result = guard._read_api(policy()['api'])
                self.assertEqual(result['state'], expected)
                self.assertEqual(connect.call_args.args[0], ('127.0.0.1', 11434))
                self.assertTrue(fake.sent.startswith(b'GET /api/ps HTTP/1.1\r\n'))
                self.assertNotIn(b'Authorization:', fake.sent)
                self.assertTrue(all(0 < x <= 0.5 for x in fake.timeouts))
                if expected != 'EMPTY': self.assertNotIn('emptyBodyBase64', result)
        fake = FakeSocket([http_bytes(b'', 302)])
        with patch.object(guard.socket, 'create_connection', return_value=fake) as connect:
            self.assertEqual(guard._read_api(policy()['api'])['state'], 'UNKNOWN')
            self.assertEqual(connect.call_count, 1)

    def test_raw_api_cap_truncation_and_absolute_deadline_are_unknown(self):
        valid_but_incomplete = http_bytes(b'{"models":[]}').replace(b'Content-Length: 13', b'Content-Length: 15')
        for wire in [http_bytes(b'x' * 65537), http_bytes(b'{"models":[]}')[:-3], valid_but_incomplete]:
            with patch.object(guard.socket, 'create_connection', return_value=FakeSocket([wire])):
                self.assertEqual(guard._read_api(policy()['api'])['state'], 'UNKNOWN')
        ticks = iter(x * 0.2 for x in range(20))
        with patch.object(guard.time, 'monotonic', side_effect=lambda: next(ticks)), \
             patch.object(guard.socket, 'create_connection', return_value=FakeSocket([b'H'] * 20)):
            self.assertEqual(guard._read_api(policy()['api'])['state'], 'UNKNOWN')

    def test_lsof_machine_fields_are_strict_and_stderr_is_not_ignored(self):
        raw = b'p11\nf4\ntIPv4\nPTCP\nn127.0.0.1:11434\nTST=LISTEN\n'
        with patch.object(guard.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=raw, stderr=b'')) as execute:
            self.assertEqual(guard._read_listeners(), listener())
            self.assertEqual(execute.call_args.args[0][1:4], ['-nP', '-iTCP:11434', '-sTCP:LISTEN'])
            self.assertLessEqual(execute.call_args.kwargs['timeout'], 0.5)
        with patch.object(guard.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=raw, stderr=b'incomplete permission')):
            self.assertEqual(guard._read_listeners()['state'], 'UNKNOWN')

    def test_real_identity_bytes_complete_command_hash_and_pid_reuse(self):
        with tempfile.TemporaryDirectory(prefix='mac-guard-offline-') as directory:
            app, serve = Path(directory) / 'Ollama', Path(directory) / 'ollama'
            app.write_bytes(b'nonexecutable GUI identity fixture')
            serve.write_bytes(b'nonexecutable server identity fixture')
            def process(pid):
                path = app if pid == 10 else serve
                return SimpleNamespace(create_time=lambda: float(pid), exe=lambda: str(path),
                                       cmdline=lambda: [str(path)] + ([] if pid == 10 else ['serve']), ppid=lambda: 1 if pid == 10 else 10)
            fake = SimpleNamespace(Process=process)
            with patch.dict(sys.modules, {'psutil': fake}):
                p = guard.build_policy(10, 11)
                old = p['daemon']['serve']['sha256']
                serve.write_bytes(b'changed server fixture')
                self.assertNotEqual(guard._read_identity(11)['sha256'], old)
                self.assertNotIn('argv', p['daemon']['serve'])
                self.assertEqual(p['daemon']['serve']['commandForm'], 'serve')
                self.assertEqual(p['daemon']['serve']['argvSha256'], guard.canonical_sha256([str(serve), 'serve']))
            self.assertEqual(guard._command_form(str(serve), [str(serve), 'runner']), 'unknown')

    def test_process_enumeration_read_errors_are_preserved(self):
        class Denied(Exception): pass
        def process(pid):
            if pid == 22: raise Denied()
            return SimpleNamespace(create_time=lambda: 1.0, name=lambda: 'ordinary', ppid=lambda: 0)
        with patch.dict(sys.modules, {'psutil': SimpleNamespace(pids=lambda: [1, 22], Process=process)}):
            result = guard._read_processes()
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['errors'][0]['pid'], 22)
        self.assertEqual(result['enumeratedPids'], [1, 22])


if __name__ == '__main__':
    unittest.main()
