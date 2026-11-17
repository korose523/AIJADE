"""Pure, fail-closed listener transcript v2 parsing and canonical lease binding.

No capture, process, clock, file, network or cache operation is performed here.
An OBSERVED result means this transcript passed the declared checks. It does not
prove that macOS exposed every system listener to the capture process.
"""
import base64
import copy
import hashlib
import json
import math

SCHEMA = 'aijade.listener.transcript.v2'
MODE = 'complete-managed-lsof-transcript-v1'
NATIVE_SCHEMA = 'aijade.lifecycle.native-launch.v1'
NATIVE_MODE = 'native-ready-release-v1'
ARGV = ['/usr/sbin/lsof', '-nP', '-iTCP:11434', '-sTCP:LISTEN', '-FpfPtTn']
DEADLINE = .5
MAX_STDOUT = 65536
MAX_FORENSIC = 2 * 1024 * 1024
PIN_FIELDS = ('adapterSourceSha256', 'shimSourceSha256', 'shimSha256',
              'executableSha256', 'parserSourceSha256', 'callerSourceSha256')
PHASE_FIELDS = ('requestStartedMonotonic', 'captureRequestedMonotonic',
    'captureAcquiredMonotonic', 'popenStartedMonotonic', 'popenReturnedMonotonic',
    'readyReadCompletedMonotonic', 'firstIdentityCompletedMonotonic',
    'secondIdentityCompletedMonotonic', 'registerStartedMonotonic',
    'registerCompletedMonotonic', 'releaseStartedMonotonic',
    'releaseCompletedMonotonic', 'gateWrittenMonotonic',
    'postProvenanceCompletedMonotonic', 'returnedMonotonic')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _need(condition, code):
    if not condition:
        raise ValueError(code)


def _hex(value, size=64):
    return type(value) is str and len(value) == size and all(c in '0123456789abcdef' for c in value)


def _clock(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _identity(value):
    return (type(value) is dict and set(value) == {'pid', 'createTimeMicros', 'parentPid'}
        and all(type(value[k]) is int for k in value)
        and value['pid'] > 1 and value['createTimeMicros'] > 0 and value['parentPid'] > 0)


def encode_capture(raw, *, truncated=False, total_bytes=None):
    """Encode bytes actually retained, never invent a full hash for a prefix.

    If truncated, total_bytes is either the actually known byte count or None;
    totalSha256 remains None because this function was only given a prefix.
    """
    _need(type(raw) is bytes and len(raw) <= MAX_FORENSIC, 'CAPTURE_INPUT_SCHEMA')
    _need(type(truncated) is bool, 'CAPTURE_INPUT_SCHEMA')
    if truncated:
        _need(total_bytes is None or (type(total_bytes) is int and total_bytes >= len(raw)), 'CAPTURE_INPUT_SCHEMA')
        total_sha = None
    else:
        _need(total_bytes is None or (type(total_bytes) is int and total_bytes == len(raw)), 'CAPTURE_INPUT_SCHEMA')
        total_bytes, total_sha = len(raw), sha256(raw)
    return dict(encoding='base64', dataBase64=base64.b64encode(raw).decode('ascii'),
        capturedBytes=len(raw), capturedSha256=sha256(raw), totalBytes=total_bytes,
        totalSha256=total_sha, truncated=truncated)


def _decode_capture(value, label):
    fields = {'encoding', 'dataBase64', 'capturedBytes', 'capturedSha256', 'totalBytes', 'totalSha256', 'truncated'}
    _need(type(value) is dict and set(value) == fields and value['encoding'] == 'base64', label + '_SCHEMA')
    _need(type(value['capturedBytes']) is int and 0 <= value['capturedBytes'] <= MAX_FORENSIC
        and type(value['dataBase64']) is str and len(value['dataBase64']) <= 4 * ((MAX_FORENSIC + 2) // 3)
        and type(value['truncated']) is bool and _hex(value['capturedSha256']), label + '_SCHEMA')
    try:
        raw = base64.b64decode(value['dataBase64'], validate=True)
    except (ValueError, TypeError):
        raise ValueError(label + '_BASE64') from None
    _need(base64.b64encode(raw).decode('ascii') == value['dataBase64'], label + '_BASE64')
    _need(len(raw) == value['capturedBytes'] and sha256(raw) == value['capturedSha256'], label + '_BYTES_HASH')
    if value['truncated']:
        _need(value['totalSha256'] is None and (value['totalBytes'] is None or
            (type(value['totalBytes']) is int and value['totalBytes'] >= len(raw))), label + '_TRUNCATION_SCHEMA')
    else:
        _need(type(value['totalBytes']) is int and value['totalBytes'] == len(raw)
            and value['totalSha256'] == value['capturedSha256'], label + '_COMPLETE_HASH')
    return raw


def parse_global_stdout(raw):
    """Frozen e918 positive record projection, with v2 malformed-field refusal.

    The exact original f-delimited record order/multiplicity and values survive;
    FD labels remain in raw stdout, as the original projection omitted them.
    No filtering, endpoint normalization, deduplication or alternate command.
    """
    _need(type(raw) is bytes and len(raw) <= MAX_STDOUT, 'STDOUT_ACCEPTANCE_CAP')
    try:
        text = raw.decode('ascii')
    except UnicodeDecodeError:
        raise ValueError('STDOUT_ASCII_DECODE') from None
    _need('\x00' not in text, 'STDOUT_NUL')
    records, process_pid, current = [], None, None
    def flush():
        if current is not None:
            _need(set(current) == {'pid', 'protocol', 'family', 'endpoint', 'socketState'}, 'STDOUT_INCOMPLETE_RECORD')
            _need(current['protocol'] == 'TCP' and current['family'] in ('IPv4', 'IPv6')
                  and current['socketState'] == 'LISTEN' and bool(current['endpoint']), 'STDOUT_SOCKET_SCHEMA')
            records.append(dict(current))
    for line in text.splitlines():
        if not line:
            continue
        code, value = line[0], line[1:]
        if code == 'p':
            flush(); current = None
            _need(value.isascii() and value.isdecimal() and int(value) > 1, 'STDOUT_PID_SCHEMA')
            process_pid = int(value)
        elif code == 'f':
            flush()
            _need(process_pid is not None and bool(value), 'STDOUT_FD_SCHEMA')
            current = {'pid': process_pid}
        elif code in ('P', 't', 'n'):
            _need(current is not None and bool(value), 'STDOUT_FIELD_WITHOUT_FD')
            key = {'P': 'protocol', 't': 'family', 'n': 'endpoint'}[code]
            _need(key not in current, 'STDOUT_DUPLICATE_FIELD')
            current[key] = value
        elif code == 'T' and value.startswith('ST='):
            _need(current is not None and 'socketState' not in current, 'STDOUT_DUPLICATE_OR_ORPHAN_STATE')
            current['socketState'] = value[3:]
        else:
            # Only T queue/status subfields are allowed as ignored lsof detail.
            # The frozen parser also ignored unknown tags; v2 refuses them.
            _need(code == 'T' and current is not None and '=' in value, 'STDOUT_UNKNOWN_FIELD')
    flush()
    return records


def _policy(policy, parser_pin, caller_pin):
    _need(type(policy) is dict and policy.get('lifecycleExecMode') == NATIVE_MODE, 'POLICY_NATIVE_MODE')
    listener, native = policy.get('listenerEvidence'), policy.get('nativeExec')
    fields = {'mode', 'moduleSha256', 'command', 'executableSha256', 'maxSeconds', 'maxBytes'}
    _need(type(listener) is dict and set(listener) == fields and listener['mode'] == MODE, 'POLICY_SCHEMA')
    _need(listener['command'] == ARGV and type(listener['command']) is list
        and all(type(v) is str for v in listener['command']), 'POLICY_ARGV')
    _need(type(listener['maxSeconds']) is float and listener['maxSeconds'] == DEADLINE
        and type(listener['maxBytes']) is int and listener['maxBytes'] == MAX_STDOUT, 'POLICY_BOUNDS')
    _need(type(native) is dict and set(native) == {'mode', 'adapterSourceSha256', 'sourcePath',
        'sourceSha256', 'binaryPath', 'binarySha256'} and native['mode'] == NATIVE_MODE, 'POLICY_NATIVE_SCHEMA')
    _need(all(_hex(native[k]) for k in ('adapterSourceSha256', 'sourceSha256', 'binarySha256'))
        and all(type(native[k]) is str and native[k].startswith('/') and '\x00' not in native[k]
                for k in ('sourcePath', 'binaryPath'))
        and native['sourcePath'].endswith('/lifecycle_exec_native.c'), 'POLICY_NATIVE_SOURCE_PIN_SCHEMA')
    _need(type(policy.get('lifecycle')) is dict and policy['lifecycle'].get('execShimSha256') == native['binarySha256'], 'POLICY_NATIVE_SHIM_BINDING')
    _need(type(policy['lifecycle'].get('coordinationLockPath')) is str
        and policy['lifecycle']['coordinationLockPath'].startswith('/')
        and '\x00' not in policy['lifecycle']['coordinationLockPath'], 'POLICY_CAPTURE_LOCK_PATH')
    _need(_hex(parser_pin) and _hex(caller_pin) and listener['moduleSha256'] == parser_pin
        and _hex(listener['executableSha256']), 'SOURCE_CALLER_BINDING')
    return dict(adapterSourceSha256=native['adapterSourceSha256'], shimSourceSha256=native['sourceSha256'],
        shimSha256=native['binarySha256'], executableSha256=listener['executableSha256'],
        parserSourceSha256=parser_pin, callerSourceSha256=caller_pin)


def _bind_native(native, state, policy, pins, started, run_completed):
    fields = {'schema', 'mode', 'leaseId', 'stageId', 'role', 'identity', 'commandSha256',
        'executableSha256', 'shimSha256', 'adapterSourceSha256', 'shimSourceSha256', 'phaseClocks',
        'readyMonotonic', 'actualReapedMonotonic', 'waitEventMonotonic', 'waitSequence', 'exitCode', 'waitSource',
        'captureLock', 'sourceProofBefore', 'sourceProofReady', 'sourceProofAfter', 'executedShimIdentity'}
    _need(type(native) is dict and set(native) == fields and native['schema'] == NATIVE_SCHEMA
        and native['mode'] == NATIVE_MODE, 'NATIVE_SCHEMA')
    _need(_hex(native['leaseId'], 32) and type(native['stageId']) is str and native['stageId']
        and native['role'] == 'finite' and _identity(native['identity']), 'NATIVE_LEASE_SCHEMA')
    for key in ('adapterSourceSha256', 'shimSourceSha256', 'shimSha256', 'executableSha256'):
        _need(_hex(native[key]) and native[key] == pins[key], 'NATIVE_' + key.upper() + '_BINDING')
    _need(native['commandSha256'] == sha256(canonical(ARGV)), 'NATIVE_COMMAND_BINDING')
    _need(type(state) is dict and type(state.get('leases')) is dict and type(state.get('events')) is list,
          'CANONICAL_STATE_SCHEMA')
    lease = state['leases'].get(native['leaseId'])
    _need(type(lease) is dict and lease.get('leaseId') == native['leaseId'], 'CANONICAL_LEASE_MISSING')
    for key in ('stageId', 'role', 'identity', 'commandSha256', 'executableSha256', 'shimSha256', 'readyMonotonic'):
        _need(type(lease.get(key)) is type(native[key]) and lease.get(key) == native[key], 'CANONICAL_' + key.upper() + '_BINDING')
    _need(_identity(lease.get('identity')) and _identity(lease.get('parentIdentity'))
        and native['identity']['parentPid'] == lease['parentIdentity']['pid'], 'CANONICAL_PARENT_BINDING')
    clocks = native['phaseClocks']
    _need(type(clocks) is dict and set(clocks) == set(PHASE_FIELDS)
        and all(_clock(clocks[k]) for k in PHASE_FIELDS), 'NATIVE_CLOCK_SCHEMA')
    values = [started] + [clocks[k] for k in PHASE_FIELDS]
    _need(all(a <= b for a, b in zip(values, values[1:])), 'NATIVE_CLOCK_ORDER')
    _need(_clock(native['readyMonotonic']) and clocks['popenStartedMonotonic'] <= native['readyMonotonic']
        <= clocks['readyReadCompletedMonotonic'], 'NATIVE_READY_CLOCK')
    _need(clocks['returnedMonotonic'] <= run_completed, 'NATIVE_RETURN_CLOCK')
    _need(type(native['waitSequence']) is int and native['waitSequence'] > 0
        and type(native['exitCode']) is int and native['exitCode'] == 0
        and native['waitSource'] == 'Popen.wait', 'NATIVE_ACTUAL_ZERO_WAIT')
    _need(_clock(native['actualReapedMonotonic']) and _clock(native['waitEventMonotonic'])
        and clocks['gateWrittenMonotonic'] <= native['actualReapedMonotonic']
        <= native['waitEventMonotonic'] <= run_completed, 'NATIVE_WAIT_CLOCK')
    _need(type(lease.get('exitCode')) is int and lease['exitCode'] == native['exitCode']
        and type(lease.get('waitSeq')) is int and lease['waitSeq'] == native['waitSequence']
        and _clock(lease.get('reapedMonotonic')) and lease.get('reapedMonotonic') == native['actualReapedMonotonic'], 'CANONICAL_WAIT_BINDING')
    selected = {}
    for event in state['events']:
        _need(type(event) is dict, 'CANONICAL_EVENT_SCHEMA')
        data = event.get('data')
        if type(data) is dict and data.get('leaseId') == native['leaseId'] and event.get('event') in ('FINITE_REGISTER', 'RELEASE', 'WAIT'):
            name = event['event']
            _need(name not in selected, 'CANONICAL_EVENT_MULTIPLICITY')
            selected[name] = event
    _need(set(selected) == {'FINITE_REGISTER', 'RELEASE', 'WAIT'}, 'CANONICAL_EVENT_MISSING')
    reg, release, wait = (selected[k] for k in ('FINITE_REGISTER', 'RELEASE', 'WAIT'))
    _need(all(type(e.get('seq')) is int and _clock(e.get('monotonicSeconds'))
        and _identity(e.get('writer')) and e.get('writer') == lease['parentIdentity']
        for e in (reg, release, wait)), 'CANONICAL_EVENT_SOURCE_SCHEMA')
    _need(type(lease.get('registerSeq')) is int and type(lease.get('releaseSeq')) is int
        and reg['seq'] == lease.get('registerSeq') and release['seq'] == lease.get('releaseSeq')
        and reg['seq'] < release['seq'] < wait['seq'] == native['waitSequence'], 'CANONICAL_EVENT_ORDER')
    _need(clocks['registerStartedMonotonic'] <= reg['monotonicSeconds'] <= clocks['registerCompletedMonotonic']
        and clocks['releaseStartedMonotonic'] <= release['monotonicSeconds'] <= clocks['releaseCompletedMonotonic']
        and wait['monotonicSeconds'] == native['waitEventMonotonic'], 'CANONICAL_EVENT_CLOCK_BINDING')
    _need(_clock(lease.get('registerMonotonic')) and lease['registerMonotonic'] == reg['monotonicSeconds']
        and _clock(lease.get('releaseMonotonic')) and lease['releaseMonotonic'] == release['monotonicSeconds'], 'CANONICAL_LEASE_CLOCK_BINDING')
    _need(_identity(reg['data'].get('identity')) and reg['data'].get('identity') == native['identity']
        and reg['data'].get('commandSha256') == native['commandSha256']
        and reg['data'].get('executableSha256') == native['executableSha256']
        and reg['data'].get('shimSha256') == native['shimSha256']
        and _clock(reg['data'].get('readyMonotonic')) and reg['data'].get('readyMonotonic') == native['readyMonotonic']
        and reg['data'].get('parentIdentity') == lease['parentIdentity'], 'CANONICAL_REGISTER_DATA_BINDING')
    _need(_identity(wait['data'].get('identity')) and wait['data'].get('identity') == native['identity']
        and type(wait['data'].get('exitCode')) is int
        and wait['data']['exitCode'] == 0 and wait['data'].get('waitSource') == 'Popen.wait'
        and wait['data'].get('reapedMonotonic') == native['actualReapedMonotonic'], 'CANONICAL_WAIT_DATA_BINDING')
    native_policy = policy['nativeExec']
    expected = {'adapter': (pins['adapterSourceSha256'], None),
                'source': (pins['shimSourceSha256'], native_policy['sourcePath']),
                'binary': (pins['shimSha256'], native_policy['binaryPath'])}
    for key in ('sourceProofBefore', 'sourceProofReady', 'sourceProofAfter'):
        proof = native[key]
        _need(type(proof) is dict and set(proof) == set(expected), 'NATIVE_PROVENANCE_SCHEMA')
        for name, (sha, path) in expected.items():
            item = proof[name]
            _need(type(item) is dict and set(item) == {'path', 'sha256', 'device', 'inode', 'sizeBytes', 'mtimeNs', 'mode'}
                and type(item['path']) is str and item['path'].startswith('/') and '\x00' not in item['path']
                and item['sha256'] == sha and all(type(item[k]) is int and item[k] >= 0
                    for k in ('device', 'inode', 'sizeBytes', 'mtimeNs', 'mode'))
                and item['inode'] > 0 and item['sizeBytes'] > 0, 'NATIVE_PROVENANCE_SCHEMA')
            _need((path is None and item['path'].endswith('/native_exec_registry.py')) or item['path'] == path,
                  'NATIVE_PROVENANCE_PATH_BINDING')
            if name == 'binary':
                _need(item['mode'] == 0o755, 'NATIVE_BINARY_MODE')
    _need(native['sourceProofBefore'] == native['sourceProofReady'] == native['sourceProofAfter'], 'NATIVE_PROVENANCE_GENERATION_CHANGED')
    adapter_path = native['sourceProofBefore']['adapter']['path']
    _need(adapter_path.rsplit('/', 1)[0] + '/lifecycle_exec_native.c' == native_policy['sourcePath'], 'NATIVE_COLOCATED_SOURCE_BINDING')
    executed = native['executedShimIdentity']
    _need(type(executed) is dict and set(executed) == {'pid', 'createTimeMicros', 'parentPid', 'executable', 'argvSha256'}
        and _identity({k: executed[k] for k in ('pid', 'createTimeMicros', 'parentPid')})
        and all(executed[k] == native['identity'][k] for k in ('pid', 'createTimeMicros', 'parentPid'))
        and executed['executable'] == native_policy['binaryPath'] and _hex(executed['argvSha256']), 'NATIVE_EXECUTED_SHIM_BINDING')
    lock = native['captureLock']
    _need(type(lock) is dict and type(lock.get('nested')) is bool and _hex(lock.get('pathSha256')),
          'NATIVE_CAPTURE_LOCK_SCHEMA')
    _need(lock['pathSha256'] == sha256(policy['lifecycle']['coordinationLockPath'].encode()), 'NATIVE_CAPTURE_LOCK_PATH_BINDING')
    if lock['nested']:
        _need(set(lock) == {'pathSha256', 'waitSeconds', 'nested'} and type(lock['waitSeconds']) is float
            and lock['waitSeconds'] == 0.0, 'NATIVE_NESTED_CAPTURE_LOCK_SCHEMA')
    else:
        _need(set(lock) == {'schema', 'pathSha256', 'maxWaitSeconds', 'state', 'waitSeconds', 'acquiredMonotonic',
            'nested', 'initialIdentity', 'finalIdentity', 'releasedMonotonic'}
            and lock.get('schema') == 'aijade.lifecycle.capture-lock.v1' and lock.get('state') == 'HELD_AND_RELEASED'
            and type(lock.get('maxWaitSeconds')) is float and lock['maxWaitSeconds'] == 1.25
            and _clock(lock.get('waitSeconds')) and lock['waitSeconds'] <= 1.25
            and _clock(lock.get('acquiredMonotonic')) and _clock(lock.get('releasedMonotonic'))
            and clocks['captureRequestedMonotonic'] <= lock['acquiredMonotonic'] <= clocks['captureAcquiredMonotonic']
            and clocks['postProvenanceCompletedMonotonic'] <= lock['releasedMonotonic'] <= clocks['returnedMonotonic']
            and lock.get('initialIdentity') == lock.get('finalIdentity'), 'NATIVE_CAPTURE_LOCK_BINDING')
        lock_ident = lock['initialIdentity']
        _need(type(lock_ident) is dict and set(lock_ident) == {'device', 'inode', 'regular', 'singleLink', 'ownedByCurrentUser'}
            and type(lock_ident['device']) is int and type(lock_ident['inode']) is int
            and lock_ident['device'] >= 0 and lock_ident['inode'] > 0
            and all(lock_ident[k] is True for k in ('regular', 'singleLink', 'ownedByCurrentUser')),
            'NATIVE_CAPTURE_LOCK_IDENTITY')
    return dict(managedLeaseId=native['leaseId'], identity=copy.deepcopy(native['identity']),
        waitSequence=native['waitSequence'], actualReapedMonotonic=native['actualReapedMonotonic'])


def derive_outcome(transcript, outer_clock):
    """Reparse captured bytes and complete whole-call clocks on every call."""
    reasons, records, raw = [], [], {}
    fields = {'schema', 'mode', 'argv', 'stdout', 'stderr', 'returnCode', 'exception',
        'startedMonotonic', 'runCompletedMonotonic', 'parseCompletedMonotonic', 'sourcePins', 'nativeLaunch'}
    try:
        _need(type(transcript) is dict and set(transcript) == fields and transcript['schema'] == SCHEMA
            and transcript['mode'] == MODE, 'TRANSCRIPT_SCHEMA')
        _need(type(transcript['argv']) is list and transcript['argv'] == ARGV
            and all(type(v) is str for v in transcript['argv']), 'TRANSCRIPT_ARGV')
        _need(type(transcript['sourcePins']) is dict and set(transcript['sourcePins']) == set(PIN_FIELDS)
            and all(_hex(transcript['sourcePins'][k]) for k in PIN_FIELDS), 'TRANSCRIPT_SOURCE_SCHEMA')
        clocks = [transcript[k] for k in ('startedMonotonic', 'runCompletedMonotonic', 'parseCompletedMonotonic')]
        _need(all(_clock(v) for v in clocks) and clocks[0] <= clocks[1] <= clocks[2], 'TRANSCRIPT_CLOCK_SCHEMA')
        _need(type(outer_clock) is dict and set(outer_clock) == {'startedMonotonic', 'finishedMonotonic'}
            and all(_clock(v) for v in outer_clock.values())
            and outer_clock['startedMonotonic'] <= clocks[0] <= clocks[2] <= outer_clock['finishedMonotonic'], 'OUTER_READ_CLOCK_SCHEMA')
    except (ValueError, KeyError, TypeError) as error:
        return dict(state='UNKNOWN', code='LISTENER_EVIDENCE_UNKNOWN', reasons=[str(error)], records=[])
    if clocks[2] - clocks[0] > DEADLINE:
        reasons.append('INTERNAL_CALL_DEADLINE_EXCEEDED')
    if outer_clock['finishedMonotonic'] - outer_clock['startedMonotonic'] > DEADLINE:
        reasons.append('WHOLE_CALL_DEADLINE_EXCEEDED')
    if type(transcript['returnCode']) is not int:
        reasons.append('RETURN_CODE_MISSING_OR_INVALID')
    elif transcript['returnCode'] != 0:
        reasons.append('RETURN_CODE_NONZERO')
    exception = transcript['exception']
    if exception is not None:
        if type(exception) is not dict or set(exception) != {'class', 'message'} or not all(type(v) is str for v in exception.values()) or not exception.get('class'):
            reasons.append('EXCEPTION_SCHEMA')
        else:
            reasons.append('CAPTURE_EXCEPTION_' + exception['class'])
    for label in ('stdout', 'stderr'):
        try:
            raw[label] = _decode_capture(transcript[label], label.upper())
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            reasons.append(str(error) if type(error) is ValueError else label.upper() + '_SCHEMA')
            raw[label] = None
        if type(transcript[label]) is dict and transcript[label].get('truncated') is True:
            reasons.append(label.upper() + '_TRUNCATED')
    if raw.get('stdout') is not None:
        if len(raw['stdout']) > MAX_STDOUT:
            reasons.append('STDOUT_ACCEPTANCE_CAP')
        elif not transcript['stdout']['truncated']:
            try:
                records = parse_global_stdout(raw['stdout'])
            except ValueError as error:
                reasons.append(str(error))
    if raw.get('stderr'):
        reasons.append('STDERR_NOT_EMPTY')
    if reasons:
        return dict(state='UNKNOWN', code='LISTENER_EVIDENCE_UNKNOWN', reasons=reasons, records=[])
    return dict(state='OBSERVED', records=copy.deepcopy(records))


def verify_transcript(transcript, canonical_state, policy, *, parser_source_sha256, caller_source_sha256, outer_clock):
    """Re-derive detached semantic result from raw evidence and validated state.

    canonical_state MUST be the source-validated full lifecycle state for the
    current observation cutoff. This function does not validate a journal or
    trust a transcript's claimed PASS. Caller pins come from frozen source.
    """
    reasons, bound = [], None
    def attempt(operation):
        try:
            return operation()
        except (ValueError, KeyError, TypeError, OverflowError, RecursionError) as error:
            code = str(error) if type(error) is ValueError else 'TRANSCRIPT_SCHEMA_' + type(error).__name__.upper()
            if code not in reasons:
                reasons.append(code)
            return None
    pins = attempt(lambda: _policy(policy, parser_source_sha256, caller_source_sha256))
    if pins is None:
        return dict(state='UNKNOWN', code='LISTENER_EVIDENCE_UNKNOWN', reasons=reasons, records=[])
    outcome = derive_outcome(transcript, outer_clock)
    reasons.extend(outcome.get('reasons', []))
    # Structurally invalid transcripts cannot safely name internal clocks.
    if type(transcript) is not dict or not all(k in transcript for k in ('sourcePins', 'nativeLaunch',
        'startedMonotonic', 'runCompletedMonotonic')):
        return outcome
    try:
        _need(type(transcript['sourcePins']) is dict and set(transcript['sourcePins']) == set(PIN_FIELDS)
            and all(transcript['sourcePins'][k] == pins[k] and _hex(transcript['sourcePins'][k]) for k in PIN_FIELDS), 'TRANSCRIPT_SOURCE_BINDING')
    except (ValueError, KeyError, TypeError) as error:
        reasons.append(str(error))
    bound = attempt(lambda: _bind_native(transcript['nativeLaunch'], canonical_state, policy, pins,
        transcript['startedMonotonic'], transcript['runCompletedMonotonic']))
    if not reasons:
        return dict(state='OBSERVED', records=copy.deepcopy(outcome['records']), provenance=bound)
    return dict(state='UNKNOWN', code='LISTENER_EVIDENCE_UNKNOWN', reasons=reasons, records=[])
