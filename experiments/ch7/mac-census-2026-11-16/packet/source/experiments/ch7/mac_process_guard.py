#!/usr/bin/env python3
"""Sampled Mac process/idle-daemon evidence, never a model or renderer client.

Public API: build_policy(app_pid, serve_pid), observe(policy, owned_roots=()),
validate_observation(policy, observation). No service is stopped or reconfigured.
Policy argv hashes bind the complete command without publishing its arguments.
The returned PID/parent/time/category graph omits unrelated process names.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import socket
import stat
import subprocess
import time
import uuid

SCHEMA = 1
KIND = 'mac-observed-idle-daemon-v1'
API_URL = 'http://127.0.0.1:11434/api/ps'
MAX_API_BYTES = 65536
MAX_API_SECONDS = 0.5


def canonical_sha256(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _pid(value):
    return type(value) is int and value > 1


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _file_sha(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('not a regular executable')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        after = os.fstat(stream.fileno())
    current = os.stat(path, follow_symlinks=False)
    fields = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if fields(before) != fields(after) or fields(after) != fields(current):
        raise ValueError('executable changed during observation')
    return digest.hexdigest()


def validate_policy(policy):
    """Raise ValueError for an unsafe or incomplete predeclared policy."""
    if not isinstance(policy, dict) or type(policy.get('schemaVersion')) is not int or policy['schemaVersion'] != SCHEMA or policy.get('kind') != KIND:
        raise ValueError('policy schema/kind')
    daemon = policy.get('daemon')
    if not isinstance(daemon, dict) or set(daemon) != {'app', 'serve'}:
        raise ValueError('policy must bind exactly app and serve')
    for role in ('app', 'serve'):
        item = daemon[role]
        if not isinstance(item, dict) or not _pid(item.get('pid')) or not _finite(item.get('createTime')) or item['createTime'] <= 0:
            raise ValueError('invalid daemon PID/creation time')
        if type(item.get('parentPid')) is not int or item['parentPid'] < 1:
            raise ValueError('invalid parent identity')
        path = item.get('executable')
        if not isinstance(path, str) or not Path(path).is_absolute() or any(c in path for c in ('\x00', '\n', '\r')) or '..' in Path(path).parts:
            raise ValueError('invalid executable path')
        if not _hex(item.get('sha256')) or not _hex(item.get('argvSha256')):
            raise ValueError('missing executable or complete-command hash')
        if item.get('commandForm') != ('gui' if role == 'app' else 'serve'):
            raise ValueError('unsupported command form')
    if daemon['app']['pid'] == daemon['serve']['pid'] or daemon['serve']['parentPid'] != daemon['app']['pid'] or daemon['serve']['createTime'] < daemon['app']['createTime']:
        raise ValueError('daemon parent identity')
    listener = policy.get('listener')
    if not isinstance(listener, dict) or type(listener.get('port')) is not int or type(listener.get('pid')) is not int or listener != {'address': '127.0.0.1', 'port': 11434, 'pid': daemon['serve']['pid']}:
        raise ValueError('only the declared serve IPv4 loopback listener is allowed')
    api = policy.get('api')
    if not isinstance(api, dict) or api.get('url') != API_URL or not _finite(api.get('timeoutSeconds')) or not 0 < api['timeoutSeconds'] <= MAX_API_SECONDS:
        raise ValueError('unsafe API endpoint/deadline')
    if type(api.get('maxBytes')) is not int or not 1 <= api['maxBytes'] <= MAX_API_BYTES:
        raise ValueError('unsafe API response cap')
    canonical_sha256(policy)


def _command_form(executable, argv):
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
        return 'unknown'
    if Path(argv[0]).name.lower() != Path(executable).name.lower():
        return 'unknown'
    if len(argv) == 1 and Path(executable).name == 'Ollama':
        return 'gui'
    if len(argv) == 2 and argv[1] == 'serve' and Path(executable).name.lower() == 'ollama':
        return 'serve'
    return 'unknown'


def _read_identity(pid):
    import psutil
    process = psutil.Process(pid)
    created = process.create_time()
    executable, argv, parent = process.exe(), process.cmdline(), process.ppid()
    binary = _file_sha(executable)
    if psutil.Process(pid).create_time() != created:
        raise ValueError('PID reused during identity observation')
    return {'pid': pid, 'createTime': created, 'parentPid': parent, 'executable': executable,
            'sha256': binary, 'argvSha256': canonical_sha256(argv), 'commandForm': _command_form(executable, argv)}


def build_policy(app_pid, serve_pid):
    """Read fixed PIDs only; no API/model calls or process mutations."""
    policy = {'schemaVersion': SCHEMA, 'kind': KIND,
              'daemon': {'app': _read_identity(app_pid), 'serve': _read_identity(serve_pid)},
              'listener': {'address': '127.0.0.1', 'port': 11434, 'pid': serve_pid},
              'api': {'url': API_URL, 'timeoutSeconds': MAX_API_SECONDS, 'maxBytes': MAX_API_BYTES}}
    validate_policy(policy)
    return policy


def _category(name):
    name = name.lower()
    if name == 'dotnet': return 'dotnet'
    if 'godot' in name: return 'godot'
    if name == 'runner' or 'llama' in name: return 'ollama'
    return 'other'


def _read_processes():
    import psutil
    result = {'enumeratedPids': None, 'endPids': None, 'nodes': [], 'errors': []}
    try:
        result['enumeratedPids'] = sorted(psutil.pids())
        for pid in result['enumeratedPids']:
            try:
                process = psutil.Process(pid)
                created = process.create_time()
                name, parent = process.name(), process.ppid()
                if psutil.Process(pid).create_time() != created:
                    raise ValueError('PID identity changed')
                result['nodes'].append({'pid': pid, 'parentPid': parent, 'createTime': created, 'category': _category(name)})
            except Exception as error:
                result['errors'].append({'code': 'PROCESS_READ_UNKNOWN', 'pid': pid, 'errorClass': type(error).__name__})
        result['endPids'] = sorted(psutil.pids())
    except Exception as error:
        result['errors'].append({'code': 'PROCESS_ENUMERATION_UNKNOWN', 'errorClass': type(error).__name__})
    return result


def _owned_ids(nodes, roots):
    by_pid = {x['pid']: x for x in nodes}
    members = set()
    for root in roots:
        pid, created = root['pid'], root['createTime']
        if pid not in by_pid or by_pid[pid]['createTime'] != created:
            raise ValueError('owned root missing/reused')
        members.add(pid)
    while True:
        added = {x['pid'] for x in nodes if x['parentPid'] in members and x['pid'] not in members}
        if not added: return members
        members.update(added)


def _read_rss(node):
    import psutil
    process = psutil.Process(node['pid'])
    if process.create_time() != node['createTime']:
        raise ValueError('owned PID reused')
    rss = process.memory_info().rss
    if psutil.Process(node['pid']).create_time() != node['createTime']:
        raise ValueError('owned PID reused during RSS read')
    return rss


def _read_listeners():
    """macOS system connection enumeration may require root; lsof is bounded."""
    try:
        result = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:11434', '-sTCP:LISTEN', '-FpfPtTn'],
                                capture_output=True, timeout=0.5, check=False)
        if result.returncode != 0 or result.stderr or len(result.stdout) > MAX_API_BYTES:
            return {'state': 'UNKNOWN', 'code': 'LISTENER_ENUMERATION_UNKNOWN'}
        records, process_pid, current = [], None, None
        def flush():
            if current is not None: records.append(dict(current))
        for line in result.stdout.decode('ascii').splitlines():
            if not line: continue
            code, value = line[0], line[1:]
            if code == 'p':
                flush(); current = None; process_pid = int(value)
            elif code == 'f':
                flush(); current = {'pid': process_pid}
            elif current is not None and code in ('P', 't', 'n'):
                current[{'P': 'protocol', 't': 'family', 'n': 'endpoint'}[code]] = value
            elif current is not None and code == 'T' and value.startswith('ST='):
                current['socketState'] = value[3:]
        flush()
        return {'state': 'OBSERVED', 'records': records}
    except Exception as error:
        return {'state': 'UNKNOWN', 'code': 'LISTENER_READ_UNKNOWN', 'errorClass': type(error).__name__}


def _json_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate API JSON key')
        result[key] = value
    return result


class _MemorySocket:
    def __init__(self, raw): self.raw = raw
    def makefile(self, *args, **kwargs): return io.BytesIO(self.raw)


def _read_api(config):
    """Direct IPv4 socket, no proxy/redirect, one absolute wall-time deadline."""
    started, raw = time.monotonic(), bytearray()
    timeout, cap = config['timeoutSeconds'], config['maxBytes']
    deadline = started + timeout
    answer = {'state': 'UNKNOWN', 'code': 'API_READ_UNKNOWN'}
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0: raise TimeoutError('total API deadline')
        return value
    try:
        with socket.create_connection(('127.0.0.1', 11434), timeout=remaining()) as connection:
            connection.settimeout(remaining())
            connection.sendall(b'GET /api/ps HTTP/1.1\r\nHost: 127.0.0.1:11434\r\nAccept: application/json\r\nConnection: close\r\n\r\n')
            header_end, content_length = -1, None
            while True:
                connection.settimeout(remaining())
                block = connection.recv(min(8192, cap + 12288 - len(raw) + 1))
                if not block: break
                raw.extend(block)
                if len(raw) > cap + 12288: raise ValueError('response cap')
                if header_end < 0:
                    header_end = raw.find(b'\r\n\r\n')
                    if header_end < 0 and len(raw) > 8192: raise ValueError('header cap')
                    if header_end >= 0:
                        if header_end > 8192: raise ValueError('header cap')
                        headers = http.client.parse_headers(io.BytesIO(bytes(raw).split(b'\r\n', 1)[1][:header_end]))
                        length = headers.get('Content-Length')
                        if length is not None:
                            if headers.get('Transfer-Encoding') is not None: raise ValueError('ambiguous HTTP framing')
                            content_length = int(length)
                            if not 0 <= content_length <= cap: raise ValueError('body cap')
                if header_end >= 0 and content_length is not None and len(raw) >= header_end + 4 + content_length:
                    if len(raw) != header_end + 4 + content_length: raise ValueError('trailing HTTP data')
                    break
        if header_end < 0 or (content_length is not None and len(raw) != header_end + 4 + content_length):
            raise ValueError('incomplete HTTP response framing')
        response = http.client.HTTPResponse(_MemorySocket(bytes(raw)))
        response.begin()
        if response.status != 200:
            answer = {'state': 'UNKNOWN', 'code': 'API_HTTP_STATUS', 'httpStatus': response.status}
        else:
            body = response.read(cap + 1)
            if len(body) > cap: raise ValueError('decoded body cap')
            parsed = json.loads(body, object_pairs_hook=_json_unique)
            answer = {'state': 'UNKNOWN', 'code': 'API_SCHEMA_UNKNOWN', 'httpStatus': 200,
                      'bytes': len(body), 'bodySha256': _sha_bytes(body)}
            if isinstance(parsed, dict) and set(parsed) == {'models'} and isinstance(parsed['models'], list):
                answer.update({'state': 'EMPTY' if not parsed['models'] else 'NONEMPTY', 'modelCount': len(parsed['models'])})
                answer.pop('code', None)
                if not parsed['models']:
                    answer['emptyBodyBase64'] = base64.b64encode(body).decode('ascii')
        remaining()
    except Exception as error:
        answer = {'state': 'UNKNOWN', 'code': 'API_READ_UNKNOWN', 'errorClass': type(error).__name__}
    answer['durationSeconds'] = time.monotonic() - started
    return answer


def _normalize_roots(roots):
    result = []
    for root in roots:
        if isinstance(root, dict): pid, created = root['pid'], root['createTime']
        else: pid, created = root
        if not _pid(pid) or not _finite(created) or created <= 0 or any(x['pid'] == pid for x in result):
            raise ValueError('invalid or duplicate owned root')
        result.append({'pid': pid, 'createTime': created})
    return sorted(result, key=lambda x: x['pid'])


def _snapshot(policy, roots):
    graph = _read_processes()
    result = {'processGraph': graph, 'daemon': {}, 'ownedProcesses': [], 'errors': []}
    for role in ('app', 'serve'):
        try:
            identity = _read_identity(policy['daemon'][role]['pid'])
            identity['executablePathSha256'] = _sha_bytes(identity.pop('executable').encode())
            result['daemon'][role] = identity
        except Exception as error:
            result['errors'].append({'code': 'DAEMON_IDENTITY_READ_UNKNOWN', 'role': role, 'errorClass': type(error).__name__})
    try:
        members = _owned_ids(graph['nodes'], roots)
        for node in graph['nodes']:
            if node['pid'] in members:
                result['ownedProcesses'].append({key: node[key] for key in ('pid', 'createTime', 'parentPid')} | {'rssBytes': _read_rss(node)})
        result['ownedProcesses'].sort(key=lambda x: x['pid'])
    except Exception as error:
        result['errors'].append({'code': 'OWNED_PROCESS_RSS_UNKNOWN', 'errorClass': type(error).__name__})
    result['listener'] = _read_listeners()
    return result


def _decision(blockers, owned=None):
    status = 'FAIL' if any(x['severity'] == 'FAIL' for x in blockers) else 'UNKNOWN' if blockers else 'PASS'
    rows = owned if owned is not None else []
    return {'status': status, 'blockers': blockers, 'ownedProcesses': rows,
            'ownedRssBytes': sum(x['rssBytes'] for x in rows) if status == 'PASS' and owned is not None else None}


def validate_observation(policy, observation):
    """Recompute from recorded facts, not claimed PASS or derived RSS totals."""
    blockers = []
    def add(code, severity='UNKNOWN', **fields): blockers.append({'code': code, 'severity': severity, **fields})
    try:
        validate_policy(policy)
        if not isinstance(observation, dict) or observation.get('schemaVersion') != SCHEMA:
            raise ValueError('observation schema')
        if observation.get('policyCanonicalSha256') != canonical_sha256(policy):
            add('POLICY_HASH_MISMATCH', 'FAIL')
        if observation.get('observerModuleSha256') != _file_sha(Path(__file__)):
            add('OBSERVER_IDENTITY_MISMATCH', 'FAIL')
        if not isinstance(observation.get('sampleId'), str) or len(observation['sampleId']) != 32 or any(c not in '0123456789abcdef' for c in observation['sampleId']):
            add('SAMPLE_ID_MISSING')
        start, end = observation.get('startedMonotonic'), observation.get('finishedMonotonic')
        if not _finite(start) or not _finite(end) or start < 0 or end < start or end - start > 3:
            add('SAMPLE_CLOCK_UNKNOWN')
        roots = _normalize_roots(observation['ownedRoots'])
        expected_pids = {x['pid'] for x in policy['daemon'].values()}
        if expected_pids.intersection(x['pid'] for x in roots): add('DAEMON_CANNOT_BE_OWNED', 'FAIL')
        evidence = observation['evidence']
        owned_after = []
        owned_before = []
        for phase in ('before', 'after'):
            sample = evidence[phase]
            if not isinstance(sample.get('daemon'), dict) or set(sample['daemon']) != {'app', 'serve'}:
                raise ValueError('daemon evidence coverage')
            if not isinstance(sample.get('errors'), list): raise ValueError('missing snapshot error coverage')
            if sample.get('errors'): add('SNAPSHOT_READ_UNKNOWN', phase=phase)
            graph = sample['processGraph']
            if not isinstance(graph.get('errors'), list): raise ValueError('missing process error coverage')
            if graph.get('errors'): add('PROCESS_READ_UNKNOWN', phase=phase)
            initial, final, nodes = graph.get('enumeratedPids'), graph.get('endPids'), graph.get('nodes')
            if not isinstance(initial, list) or not isinstance(final, list) or not isinstance(nodes, list):
                raise ValueError('missing process census')
            if any(type(pid) is not int or pid < 0 for pid in initial + final) or len(initial) != len(set(initial)) or len(final) != len(set(final)):
                raise ValueError('invalid process census')
            by_pid = {}
            for node in nodes:
                pid = node['pid']
                if type(pid) is not int or pid < 0 or pid in by_pid or type(node.get('parentPid')) is not int or node['parentPid'] < 0 or not _finite(node.get('createTime')) or node['createTime'] < 0 or node.get('category') not in ('other', 'dotnet', 'godot', 'ollama'):
                    raise ValueError('invalid process evidence')
                by_pid[pid] = node
            if set(initial) != set(final) or set(initial) != set(by_pid): add('PROCESS_COVERAGE_INCOMPLETE', phase=phase)
            for node in nodes:
                parent = by_pid.get(node['parentPid'])
                if parent and parent['createTime'] > node['createTime']: add('PROCESS_PARENT_IDENTITY_UNKNOWN', phase=phase, pid=node['pid'])
                if node['parentPid'] > 0 and parent is None: add('PROCESS_PARENT_COVERAGE_UNKNOWN', phase=phase, pid=node['pid'])
                seen, ancestor = {node['pid']}, node['parentPid']
                while ancestor > 0 and ancestor in by_pid:
                    if ancestor in seen:
                        add('PROCESS_ANCESTRY_CYCLE', phase=phase, pid=node['pid']); break
                    seen.add(ancestor); ancestor = by_pid[ancestor]['parentPid']
            try: members = _owned_ids(nodes, roots)
            except ValueError:
                members = set(); add('OWNED_ROOT_MISSING_OR_REUSED', phase=phase)
            for role, expected in policy['daemon'].items():
                actual = sample['daemon'].get(role)
                if not isinstance(actual, dict):
                    add('DAEMON_IDENTITY_UNKNOWN', phase=phase, role=role); continue
                if type(actual.get('pid')) is not int or type(actual.get('parentPid')) is not int or not _finite(actual.get('createTime')):
                    raise ValueError('daemon evidence types')
                wanted = {key: expected[key] for key in ('pid', 'createTime', 'parentPid', 'sha256', 'argvSha256', 'commandForm')}
                wanted['executablePathSha256'] = _sha_bytes(expected['executable'].encode())
                if actual != wanted: add('DAEMON_IDENTITY_MISMATCH', 'FAIL', phase=phase, role=role)
                node = by_pid.get(expected['pid'])
                if not node: add('DAEMON_CENSUS_MISSING', phase=phase, role=role)
                elif any(node[key] != expected[key] for key in ('createTime', 'parentPid')) or node['category'] != 'ollama':
                    add('DAEMON_CENSUS_MISMATCH', 'FAIL', phase=phase, role=role)
            descendants = set(expected_pids)
            while True:
                new = {x['pid'] for x in nodes if x['parentPid'] in descendants and x['pid'] not in descendants}
                if not new: break
                descendants.update(new)
            for pid in sorted(descendants - expected_pids):
                add('UNEXPECTED_DAEMON_DESCENDANT', 'FAIL', phase=phase, pid=pid)
            for node in nodes:
                if node['category'] == 'ollama' and node['pid'] not in expected_pids:
                    add('UNKNOWN_OLLAMA_OR_RUNNER', 'FAIL', phase=phase, pid=node['pid'])
                if node['category'] in ('dotnet', 'godot') and node['pid'] not in members:
                    add('FOREIGN_RESEARCH_PROCESS', 'FAIL', phase=phase, pid=node['pid'])
            rows = sample['ownedProcesses']
            if not isinstance(rows, list) or {x['pid'] for x in rows} != members or len(rows) != len(members):
                add('OWNED_RSS_COVERAGE_INCOMPLETE', phase=phase)
            else:
                for row in rows:
                    if type(row.get('rssBytes')) is not int or row['rssBytes'] < 0 or any(row[key] != by_pid[row['pid']][key] for key in ('createTime', 'parentPid')):
                        add('OWNED_RSS_IDENTITY_UNKNOWN', phase=phase)
            if phase == 'before': owned_before = rows
            else:
                owned_after = rows
                for previous in owned_before:
                    still_present = by_pid.get(previous['pid'])
                    if still_present and still_present['createTime'] == previous['createTime'] and previous['pid'] not in members:
                        add('OWNED_PROCESS_REPARENTED_OUTSIDE_CLOSURE', 'FAIL', phase=phase, pid=previous['pid'])
            listener = sample['listener']
            if not isinstance(listener, dict): raise ValueError('listener evidence type')
            if listener.get('state') != 'OBSERVED': add('LISTENER_OBSERVATION_UNKNOWN', phase=phase)
            elif not isinstance(listener.get('records'), list) or len(listener['records']) != 1 or not isinstance(listener['records'][0], dict) or type(listener['records'][0].get('pid')) is not int or listener['records'] != [{'pid': policy['listener']['pid'], 'protocol': 'TCP', 'family': 'IPv4', 'endpoint': '127.0.0.1:11434', 'socketState': 'LISTEN'}]:
                add('LISTENER_IDENTITY_MISMATCH', 'FAIL', phase=phase)
        api = evidence['api']
        duration = api.get('durationSeconds')
        if not _finite(duration) or duration < 0 or duration > policy['api']['timeoutSeconds']:
            add('API_DEADLINE_UNKNOWN')
        if api.get('state') == 'NONEMPTY': add('MODEL_LOADED', 'FAIL')
        elif api.get('state') != 'EMPTY': add('API_IDLE_UNKNOWN')
        else:
            try:
                if not isinstance(api.get('emptyBodyBase64'), str) or len(api['emptyBodyBase64']) > ((policy['api']['maxBytes'] + 2) // 3) * 4:
                    raise ValueError('empty API evidence cap')
                raw = base64.b64decode(api['emptyBodyBase64'], validate=True)
                parsed = json.loads(raw, object_pairs_hook=_json_unique)
                if parsed != {'models': []} or set(parsed) != {'models'} or type(api.get('httpStatus')) is not int or api['httpStatus'] != 200 or type(api.get('modelCount')) is not int or api['modelCount'] != 0 or type(api.get('bytes')) is not int or api['bytes'] != len(raw) or len(raw) > policy['api']['maxBytes'] or api.get('bodySha256') != _sha_bytes(raw):
                    raise ValueError('empty API evidence changed')
            except Exception:
                add('API_EMPTY_EVIDENCE_INVALID', 'FAIL')
        if observation.get('ownedProcesses') != owned_after:
            add('DERIVED_OWNED_PROCESS_LIST_MISMATCH', 'FAIL')
        decision = _decision(blockers, owned_after if all(type(x.get('rssBytes')) is int and x['rssBytes'] >= 0 for x in owned_after) else [])
        if 'status' in observation and observation['status'] != decision['status']:
            add('CLAIMED_STATUS_MISMATCH', 'FAIL')
        if 'ownedRssBytes' in observation and observation['ownedRssBytes'] != decision['ownedRssBytes']:
            add('DERIVED_RSS_SUM_MISMATCH', 'FAIL')
        return _decision(blockers, decision['ownedProcesses'])
    except Exception:
        add('OBSERVATION_SCHEMA_OR_POLICY_UNKNOWN')
        return _decision(blockers)


def observe(policy, owned_roots=()):
    """Fresh before/API/after sample. UNKNOWN is never converted to idle/zero."""
    started = time.monotonic()
    result = {'schemaVersion': SCHEMA, 'sampleId': uuid.uuid4().hex, 'startedMonotonic': started,
              'observerModuleSha256': None, 'ownedProcesses': []}
    try:
        result['observerModuleSha256'] = _file_sha(Path(__file__))
        validate_policy(policy)
        roots = _normalize_roots(owned_roots)
        result.update({'policyCanonicalSha256': canonical_sha256(policy), 'ownedRoots': roots})
        before = _snapshot(policy, roots)
        api = _read_api(policy['api'])
        after = _snapshot(policy, roots)
        result.update({'evidence': {'before': before, 'api': api, 'after': after},
                       'ownedProcesses': after['ownedProcesses'], 'finishedMonotonic': time.monotonic()})
        decision = validate_observation(policy, result)
    except Exception as error:
        result['finishedMonotonic'] = time.monotonic()
        decision = _decision([{'code': 'OBSERVER_READ_UNKNOWN', 'severity': 'UNKNOWN', 'errorClass': type(error).__name__}])
    result.update({key: decision[key] for key in ('status', 'blockers', 'ownedRssBytes')})
    result['idleDaemon'] = {'status': decision['status'], 'api': result.get('evidence', {}).get('api', {'state': 'UNKNOWN'})}
    return result
