"""Pure fabricated-byte/clock/canonical-state fixtures; no child or OS query."""
import base64
import copy
import json
import unittest
import listener_evidence as le
import frozen_e918_oracle

PARSER_PIN, CALLER_PIN = 'a' * 64, 'b' * 64
RAW = (b'p330\nf17\nPTCP\ntIPv4\nn127.0.0.1:11434\nTST=LISTEN\n'
       b'f18\nPTCP\ntIPv6\nn[::1]:11434\nTST=LISTEN\n'
       b'p991\nf17\nPTCP\ntIPv4\nn*:11434\nTST=LISTEN\n')


def fixture(raw=RAW):
    pins = dict(adapterSourceSha256='c' * 64, shimSourceSha256='d' * 64,
        shimSha256='e' * 64, executableSha256='f' * 64,
        parserSourceSha256=PARSER_PIN, callerSourceSha256=CALLER_PIN)
    policy = dict(lifecycleExecMode=le.NATIVE_MODE,
        listenerEvidence=dict(mode=le.MODE, moduleSha256=PARSER_PIN, command=list(le.ARGV),
            executableSha256=pins['executableSha256'], maxSeconds=.5, maxBytes=65536),
        nativeExec=dict(mode=le.NATIVE_MODE, adapterSourceSha256=pins['adapterSourceSha256'],
            sourcePath='/fixture/ch7/lifecycle_exec_native.c', sourceSha256=pins['shimSourceSha256'],
            binaryPath='/fixture/bin/native', binarySha256=pins['shimSha256']),
        lifecycle=dict(execShimSha256=pins['shimSha256'], coordinationLockPath='/fixture/capture.lock'))
    parent = dict(pid=100, createTimeMicros=100000, parentPid=10)
    identity = dict(pid=201, createTimeMicros=200000, parentPid=100)
    lease_id = '1' * 32
    clock_values = [.01, .02, .03, .04, .05, .06, .07, .08, .09, .11, .12, .14, .15, .16, .17]
    proof = {}
    for index, (name, path, sha) in enumerate((
        ('adapter', '/fixture/ch7/native_exec_registry.py', pins['adapterSourceSha256']),
        ('source', policy['nativeExec']['sourcePath'], pins['shimSourceSha256']),
        ('binary', policy['nativeExec']['binaryPath'], pins['shimSha256']))):
        proof[name] = dict(path=path, sha256=sha, device=1, inode=index + 1,
            sizeBytes=100, mtimeNs=1000, mode=0o755 if name == 'binary' else 0o600)
    native = dict(schema=le.NATIVE_SCHEMA, mode=le.NATIVE_MODE, leaseId=lease_id,
        stageId='fixture-listener', role='finite', identity=identity,
        commandSha256=le.sha256(le.canonical(le.ARGV)), executableSha256=pins['executableSha256'],
        shimSha256=pins['shimSha256'], adapterSourceSha256=pins['adapterSourceSha256'],
        shimSourceSha256=pins['shimSourceSha256'], phaseClocks=dict(zip(le.PHASE_FIELDS, clock_values)),
        readyMonotonic=.055, actualReapedMonotonic=.24, waitEventMonotonic=.25,
        waitSequence=3, exitCode=0, waitSource='Popen.wait',
        captureLock=dict(pathSha256=le.sha256(b'/fixture/capture.lock'), waitSeconds=0.0, nested=True),
        sourceProofBefore=copy.deepcopy(proof), sourceProofReady=copy.deepcopy(proof),
        sourceProofAfter=copy.deepcopy(proof),
        executedShimIdentity=dict(identity, executable=policy['nativeExec']['binaryPath'], argvSha256='3' * 64))
    reg_data = dict(leaseId=lease_id, role='finite', stageId=native['stageId'], identity=copy.deepcopy(identity),
        parentIdentity=parent, commandSha256=native['commandSha256'], executableSha256=native['executableSha256'],
        readyMonotonic=native['readyMonotonic'], shimSha256=native['shimSha256'])
    state = dict(leases={lease_id: dict(reg_data, registerSeq=1, registerMonotonic=.10,
        releaseSeq=2, releaseMonotonic=.13, waitSeq=3, exitCode=0, reapedMonotonic=.24)}, events=[
        dict(seq=1, event='FINITE_REGISTER', monotonicSeconds=.10, writer=parent, data=copy.deepcopy(reg_data)),
        dict(seq=2, event='RELEASE', monotonicSeconds=.13, writer=parent, data=dict(leaseId=lease_id)),
        dict(seq=3, event='WAIT', monotonicSeconds=.25, writer=parent, data=dict(leaseId=lease_id,
            identity=copy.deepcopy(identity), exitCode=0, waitSource='Popen.wait', reapedMonotonic=.24))])
    transcript = dict(schema=le.SCHEMA, mode=le.MODE, argv=list(le.ARGV),
        stdout=le.encode_capture(raw), stderr=le.encode_capture(b''), returnCode=0, exception=None,
        startedMonotonic=0.0, runCompletedMonotonic=.30, parseCompletedMonotonic=.40,
        sourcePins=pins, nativeLaunch=native)
    outer = dict(startedMonotonic=0.0, finishedMonotonic=.5)
    return transcript, state, policy, outer


class ListenerEvidenceTests(unittest.TestCase):
    def verify(self, values):
        transcript, state, policy, outer = values
        return le.verify_transcript(transcript, state, policy,
            parser_source_sha256=PARSER_PIN, caller_source_sha256=CALLER_PIN, outer_clock=outer)

    def unknown(self, values, code):
        result = self.verify(values)
        self.assertEqual(result['state'], 'UNKNOWN', result)
        self.assertIn(code, result['reasons'], result)
        self.assertEqual(result['records'], [])

    def test_01_exact_half_second_observed_global_records(self):
        result = self.verify(fixture())
        self.assertEqual(result['state'], 'OBSERVED', result)
        self.assertEqual([v['pid'] for v in result['records']], [330, 330, 991])
        self.assertEqual([v['family'] for v in result['records']], ['IPv4', 'IPv6', 'IPv4'])

    def test_02_half_second_plus_epsilon_refused(self):
        values = fixture(); values[3]['finishedMonotonic'] = .5000000000000001
        self.unknown(values, 'WHOLE_CALL_DEADLINE_EXCEEDED')

    def test_03_internal_deadline_independent_reason(self):
        values = fixture(); values[0]['parseCompletedMonotonic'] = .51; values[3]['finishedMonotonic'] = .52
        self.unknown(values, 'INTERNAL_CALL_DEADLINE_EXCEEDED')

    def test_04_stderr_with_exit_zero(self):
        values = fixture(); values[0]['stderr'] = le.encode_capture(b'lsof warning\n')
        self.unknown(values, 'STDERR_NOT_EMPTY')

    def test_05_nonzero_exit(self):
        values = fixture(); values[0]['returnCode'] = 1
        self.unknown(values, 'RETURN_CODE_NONZERO')

    def test_06_missing_exit(self):
        values = fixture(); values[0]['returnCode'] = None
        self.unknown(values, 'RETURN_CODE_MISSING_OR_INVALID')

    def test_07_bool_exit_is_not_zero(self):
        values = fixture(); values[0]['returnCode'] = False
        self.unknown(values, 'RETURN_CODE_MISSING_OR_INVALID')

    def test_08_float_exit_is_not_zero(self):
        values = fixture(); values[0]['returnCode'] = 0.0
        self.unknown(values, 'RETURN_CODE_MISSING_OR_INVALID')

    def test_09_exception_named(self):
        values = fixture(); values[0]['exception'] = {'class': 'TimeoutExpired', 'message': 'fixture only'}
        self.unknown(values, 'CAPTURE_EXCEPTION_TimeoutExpired')

    def test_10_duplicates_not_deduplicated(self):
        record = b'p330\nf17\nPTCP\ntIPv4\nn127.0.0.1:11434\nTST=LISTEN\n'
        result = self.verify(fixture(record + record))
        self.assertEqual(result['state'], 'OBSERVED', result)
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(result['records'][0], result['records'][1])

    def test_11_empty_success_original_positive_semantics(self):
        result = self.verify(fixture(b''))
        self.assertEqual(result['state'], 'OBSERVED', result)
        self.assertEqual(result['records'], [])

    def test_12_raw_encoded_tamper(self):
        values = fixture(); values[0]['stdout']['dataBase64'] = base64.b64encode(RAW + b'\n').decode()
        self.unknown(values, 'STDOUT_BYTES_HASH')

    def test_13_base64_noncanonical(self):
        values = fixture(); values[0]['stdout']['dataBase64'] += '\n'
        self.unknown(values, 'STDOUT_BASE64')

    def test_14_bool_byte_count(self):
        values = fixture(); values[0]['stdout']['capturedBytes'] = True
        self.unknown(values, 'STDOUT_SCHEMA')

    def test_15_acceptance_cap_exact(self):
        raw = RAW + b'\n' * (le.MAX_STDOUT - len(RAW))
        self.assertEqual(self.verify(fixture(raw))['state'], 'OBSERVED')

    def test_16_acceptance_cap_plus_one(self):
        self.unknown(fixture(RAW + b'\n' * (le.MAX_STDOUT + 1 - len(RAW))), 'STDOUT_ACCEPTANCE_CAP')

    def test_17_truncated_prefix_unknown_no_full_hash(self):
        values = fixture(); values[0]['stdout'] = le.encode_capture(RAW, truncated=True, total_bytes=None)
        self.assertIsNone(values[0]['stdout']['totalSha256'])
        self.unknown(values, 'STDOUT_TRUNCATED')

    def test_18_truncated_prefix_cannot_claim_full_hash(self):
        values = fixture(); values[0]['stdout'] = le.encode_capture(RAW, truncated=True, total_bytes=999)
        values[0]['stdout']['totalSha256'] = le.sha256(RAW)
        self.unknown(values, 'STDOUT_TRUNCATION_SCHEMA')

    def test_19_ascii_decode_unknown(self):
        self.unknown(fixture(RAW + b'\xff'), 'STDOUT_ASCII_DECODE')

    def test_20_malformed_orphan_fd(self):
        self.unknown(fixture(b'f1\n'), 'STDOUT_FD_SCHEMA')

    def test_21_ambiguous_duplicate_field(self):
        self.unknown(fixture(RAW.replace(b'PTCP\n', b'PTCP\nPTCP\n', 1)), 'STDOUT_DUPLICATE_FIELD')

    def test_22_missing_record_field(self):
        self.unknown(fixture(RAW.replace(b'TST=LISTEN\n', b'', 1)), 'STDOUT_INCOMPLETE_RECORD')

    def test_23_wrong_global_argv(self):
        values = fixture(); values[0]['argv'].append('-p330')
        self.unknown(values, 'TRANSCRIPT_ARGV')

    def test_24_wrong_lease(self):
        values = fixture(); values[0]['nativeLaunch']['leaseId'] = '9' * 32
        self.unknown(values, 'CANONICAL_LEASE_MISSING')

    def test_25_coherently_resigned_command_still_original_lease(self):
        values = fixture(); values[0]['nativeLaunch']['commandSha256'] = le.sha256(le.canonical(le.ARGV + ['-p330']))
        self.unknown(values, 'NATIVE_COMMAND_BINDING')

    def test_26_coherently_resigned_birth_still_original_lease(self):
        values = fixture(); values[0]['nativeLaunch']['identity']['createTimeMicros'] += 1
        self.unknown(values, 'CANONICAL_IDENTITY_BINDING')

    def test_27_future_wait_after_capture(self):
        values = fixture(); values[0]['nativeLaunch']['waitEventMonotonic'] = .31
        self.unknown(values, 'NATIVE_WAIT_CLOCK')

    def test_28_missing_unrecorded_wait(self):
        values = fixture(); values[1]['events'].pop()
        self.unknown(values, 'CANONICAL_EVENT_MISSING')

    def test_29_unrecorded_exit_unknown(self):
        values = fixture(); values[1]['leases']['1' * 32]['exitCode'] = None
        self.unknown(values, 'CANONICAL_WAIT_BINDING')

    def test_30_source_pin_tamper(self):
        values = fixture(); values[0]['sourcePins']['callerSourceSha256'] = '0' * 64
        self.unknown(values, 'TRANSCRIPT_SOURCE_BINDING')

    def test_31_native_source_changed_between_ready_and_after(self):
        values = fixture(); values[0]['nativeLaunch']['sourceProofAfter']['source']['inode'] += 1
        self.unknown(values, 'NATIVE_PROVENANCE_GENERATION_CHANGED')

    def test_32_actual_shim_birth_mismatch(self):
        values = fixture(); values[0]['nativeLaunch']['executedShimIdentity']['pid'] += 1
        self.unknown(values, 'NATIVE_EXECUTED_SHIM_BINDING')

    def test_33_return_reap_partial_order_short_process_valid(self):
        values = fixture(); values[0]['nativeLaunch']['actualReapedMonotonic'] = .155
        values[1]['leases']['1' * 32]['reapedMonotonic'] = .155
        values[1]['events'][-1]['data']['reapedMonotonic'] = .155
        self.assertEqual(self.verify(values)['state'], 'OBSERVED')

    def test_34_reap_before_gate_refused(self):
        values = fixture(); values[0]['nativeLaunch']['actualReapedMonotonic'] = .149
        self.unknown(values, 'NATIVE_WAIT_CLOCK')

    def test_35_bool_native_identity_refused(self):
        values = fixture(); values[0]['nativeLaunch']['identity']['pid'] = True
        self.unknown(values, 'NATIVE_LEASE_SCHEMA')

    def test_36_float_native_wait_sequence_refused(self):
        values = fixture(); values[0]['nativeLaunch']['waitSequence'] = 3.0
        self.unknown(values, 'NATIVE_ACTUAL_ZERO_WAIT')

    def test_37_nan_outer_clock(self):
        values = fixture(); values[3]['finishedMonotonic'] = float('nan')
        self.unknown(values, 'OUTER_READ_CLOCK_SCHEMA')

    def test_38_no_extra_schema_fields(self):
        values = fixture(); values[0]['cachedPass'] = True
        self.unknown(values, 'TRANSCRIPT_SCHEMA')

    def test_39_return_decision_detached_and_no_pass_cache(self):
        values = fixture(); before = le.canonical(values)
        result = self.verify(values); result['records'][0]['pid'] = -7
        result['provenance']['identity']['pid'] = -7
        self.assertEqual(le.canonical(values), before)
        self.assertEqual(self.verify(values)['records'][0]['pid'], 330)
        values[0]['stderr'] = le.encode_capture(b'adverse second call')
        self.unknown(values, 'STDERR_NOT_EMPTY')

    def test_40_both_or_reasons_retained(self):
        values = fixture(); values[0]['returnCode'] = 2
        values[0]['stderr'] = le.encode_capture(b'err'); values[3]['finishedMonotonic'] = .6
        result = self.verify(values)
        self.assertTrue({'RETURN_CODE_NONZERO', 'STDERR_NOT_EMPTY', 'WHOLE_CALL_DEADLINE_EXCEEDED'} <= set(result['reasons']))

    def test_41_policy_cannot_relax_deadline(self):
        values = fixture(); values[2]['listenerEvidence']['maxSeconds'] = .6
        self.unknown(values, 'POLICY_BOUNDS')

    def test_42_policy_cannot_relax_bytes(self):
        values = fixture(); values[2]['listenerEvidence']['maxBytes'] = 131072
        self.unknown(values, 'POLICY_BOUNDS')

    def test_43_native_c_source_mismatch(self):
        values = fixture(); values[0]['nativeLaunch']['shimSourceSha256'] = '0' * 64
        self.unknown(values, 'NATIVE_SHIMSOURCESHA256_BINDING')

    def test_44_old_coarse_listener_shape_refused(self):
        values = fixture(); values = (dict(state='OBSERVED', records=[]),) + values[1:]
        self.unknown(values, 'TRANSCRIPT_SCHEMA')

    def test_45_no_native_flag_refused(self):
        values = fixture(); values[2].pop('lifecycleExecMode')
        self.unknown(values, 'POLICY_NATIVE_MODE')

    def test_46_nul_raw_refused(self):
        self.unknown(fixture(RAW + b'\x00'), 'STDOUT_NUL')

    def test_47_canonical_duplicate_wait_refused(self):
        values = fixture(); values[1]['events'].append(copy.deepcopy(values[1]['events'][-1]))
        self.unknown(values, 'CANONICAL_EVENT_MULTIPLICITY')

    def test_48_parent_identity_mismatch(self):
        values = fixture(); values[0]['nativeLaunch']['identity']['parentPid'] = 999
        self.unknown(values, 'CANONICAL_IDENTITY_BINDING')

    def test_49_outer_clock_must_enclose_internal(self):
        values = fixture(); values[3]['startedMonotonic'] = .001
        self.unknown(values, 'OUTER_READ_CLOCK_SCHEMA')

    def test_50_pure_derive_reparses_adverse_new_tail(self):
        values = fixture()
        self.assertEqual(le.derive_outcome(values[0], values[3])['state'], 'OBSERVED')
        values[0]['stdout'] = le.encode_capture(RAW + b'Xmalformed\n')
        self.assertIn('STDOUT_UNKNOWN_FIELD', le.derive_outcome(values[0], values[3])['reasons'])

    def test_51_frozen_original_function_positive_projection(self):
        class FakeTime:
            @staticmethod
            def monotonic():
                return 0.0
        class Result:
            returncode, stderr = 0, b''
        class FakeLifecycle:
            def __init__(self, raw):
                self.raw = raw
            def run(inner, argv, **kwargs):
                self.assertEqual(argv, le.ARGV)
                self.assertEqual(kwargs, dict(capture_output=True, timeout=.5, check=False))
                result = Result(); result.stdout = inner.raw
                return result
        frozen_e918_oracle.time = FakeTime
        frozen_e918_oracle.MAX_API_BYTES = 65536
        cases = [b'', RAW, RAW + RAW, RAW.replace(b'127.0.0.1', b'*'),
            RAW.replace(b'[::1]', b'[fe80::1234%lo0]'), RAW.replace(b'\n', b'\r\n'),
            RAW + b'\n', RAW.replace(b'TST=LISTEN\n', b'TQR=0\nTST=LISTEN\n')]
        for raw in cases:
            with self.subTest(raw=raw):
                old = frozen_e918_oracle._read_listeners(FakeLifecycle(raw))
                self.assertEqual(old['state'], 'OBSERVED')
                self.assertEqual(le.parse_global_stdout(raw), old['records'])

    def test_52_nonnested_capture_exact_metadata(self):
        values = fixture(); ident = dict(device=1, inode=5, regular=True, singleLink=True, ownedByCurrentUser=True)
        values[0]['nativeLaunch']['captureLock'] = dict(schema='aijade.lifecycle.capture-lock.v1',
            pathSha256=le.sha256(b'/fixture/capture.lock'), maxWaitSeconds=1.25, state='HELD_AND_RELEASED',
            waitSeconds=.001, acquiredMonotonic=.025, releasedMonotonic=.165, nested=False,
            initialIdentity=ident, finalIdentity=copy.deepcopy(ident))
        self.assertEqual(self.verify(values)['state'], 'OBSERVED')

    def test_53_capture_path_replaced_refused(self):
        values = fixture(); values[0]['nativeLaunch']['captureLock']['pathSha256'] = '0' * 64
        self.unknown(values, 'NATIVE_CAPTURE_LOCK_PATH_BINDING')

    def test_54_native_provenance_binary_hash_refused(self):
        values = fixture(); values[0]['nativeLaunch']['sourceProofBefore']['binary']['sha256'] = '0' * 64
        self.unknown(values, 'NATIVE_PROVENANCE_SCHEMA')

    def test_55_unknown_extra_native_key_refused(self):
        values = fixture(); values[0]['nativeLaunch']['cacheHit'] = True
        self.unknown(values, 'NATIVE_SCHEMA')

    def test_56_canonical_bool_registration_sequence_refused(self):
        values = fixture(); values[1]['leases']['1' * 32]['registerSeq'] = True
        self.unknown(values, 'CANONICAL_EVENT_ORDER')

    def test_57_infinite_internal_clock_refused(self):
        values = fixture(); values[0]['parseCompletedMonotonic'] = float('inf')
        self.unknown(values, 'TRANSCRIPT_CLOCK_SCHEMA')

    def test_58_float_identity_refused(self):
        values = fixture(); values[0]['nativeLaunch']['identity']['pid'] = 201.0
        self.unknown(values, 'NATIVE_LEASE_SCHEMA')

    def test_59_exception_schema_refused(self):
        values = fixture(); values[0]['exception'] = {'class': '', 'message': 'fixture'}
        self.unknown(values, 'EXCEPTION_SCHEMA')

    def test_60_forensic_cap_builder_refuses_oversize(self):
        with self.assertRaisesRegex(ValueError, 'CAPTURE_INPUT_SCHEMA'):
            le.encode_capture(b'x' * (le.MAX_FORENSIC + 1))

    def test_61_canonical_wait_writer_mismatch(self):
        values = fixture(); values[1]['events'][-1]['writer'] = dict(pid=999, createTimeMicros=1, parentPid=1)
        self.unknown(values, 'CANONICAL_EVENT_SOURCE_SCHEMA')

    def test_62_wait_zero_cannot_use_poll(self):
        values = fixture(); values[0]['nativeLaunch']['waitSource'] = 'Popen.poll'
        self.unknown(values, 'NATIVE_ACTUAL_ZERO_WAIT')

    def test_63_float_capture_count_refused(self):
        values = fixture(); values[0]['stdout']['capturedBytes'] = float(len(RAW))
        self.unknown(values, 'STDOUT_SCHEMA')

    def test_64_coherently_resigned_malformed_raw_refused(self):
        values = fixture(); values[0]['stdout'] = le.encode_capture(RAW.replace(b'p330', b'pTRUE'))
        self.unknown(values, 'STDOUT_PID_SCHEMA')

    def test_65_no_pid_target_filter(self):
        values = fixture(); values[0]['argv'][2] = '-iTCP:11434 -p330'
        self.unknown(values, 'TRANSCRIPT_ARGV')


if __name__ == '__main__':
    unittest.main(verbosity=2)
