#!/usr/bin/env python3
"""Records-only replay of the refused B5 engineering attempt, never live work.

The old packet and both old audit scripts remain byte-identical. A pinned,
counted AST adapter removes only the original Mac host-file rechecks. It does
not fake file_sha, SDK files, process observations or successful qualification.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import contextmanager, redirect_stdout
import copy
from datetime import datetime
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import subprocess
import sys
import tempfile
import traceback
import unicodedata


SOURCE = 'b5af85f7a1b5f1da3ceeda0a9c1a64393a0e3efb'
FREEZE = 'bb2c25b808c1c3f604e081b5fa4da4d4f76af84d'
PASSPORT = '5755e4942768002eed52762a432c947bc6279ac945fcc8d7f9d0bb579da939e2'
MANIFEST = 'cda30ac1543b9514199906859579216ddd317d9997b2c28c4786a23a7fbf9e53'
ORIGINAL_AUDIT = '3844c1ed2473b56aef75196a44e79f4ce5726444540d5d144af4d1c249cd5063'
HELPER = '049b347a3a6265cb6f9a096c6c5db633934b4863bf78d4d9a81c777e36aeec64'
PREFIX = 'experiments/ch7/mac-prefix-2026-11-17/engineering-freeze/'
BASE = Path('/Volumes/Untitled/AIJADE')
CAP = 16 * 1024 ** 2


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def typed(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(typed(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(typed(a, b) for a, b in zip(left, right))
    return left == right


def relative(value):
    require(type(value) is str and value and '\\' not in value and '\x00' not in value, 'invalid packet path')
    item = PurePosixPath(value)
    require(not item.is_absolute() and '..' not in item.parts and str(item) == value, 'unsafe packet path')
    return value


def bounded_gzip(raw):
    require(raw[4:8] == b'\0' * 4, 'compressed original must retain deterministic mtime0')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        result = stream.read(CAP + 1)
        require(len(result) <= CAP and not stream.read(1), 'logical file exceeds cap')
    return result


def packet_bytes(root, manifest_sha=MANIFEST):
    require(not root.is_symlink(), 'linked packet root')
    original_manifest = (root / 'packet-manifest.json').read_bytes()
    require(sha(original_manifest) == manifest_sha, 'packet manifest identity')
    manifest = decode(original_manifest)
    require(manifest['schema'] == 'aijade.ch7.prefix-engineering-attempt-packet-manifest.v1'
            and manifest['sourceCommit'] == SOURCE and manifest['engineeringFreezeCommit'] == FREEZE
            and manifest['passportSha256'] == PASSPORT, 'packet immutable source/freeze context')
    require(type(manifest['files']) is list and len(manifest['files']) == 27, 'exact packet payload population')
    bodies, physical, nfc, folded = {}, {}, set(), set()
    for row in manifest['files']:
        require(type(row) is dict and set(row) in ({'path', 'sha256', 'sizeBytes'},
            {'path', 'sha256', 'sizeBytes', 'logicalSha256', 'logicalSizeBytes'}), 'manifest row schema')
        name = relative(row['path'])
        normalized = unicodedata.normalize('NFC', name)
        require(normalized not in nfc and normalized.casefold() not in folded, 'duplicate/colliding path')
        nfc.add(normalized); folded.add(normalized.casefold())
        require(type(row['sizeBytes']) is int and 0 <= row['sizeBytes'] <= CAP, 'physical size type/cap')
        path = root / name
        require(path.is_file() and not path.is_symlink(), 'nonregular/linked packet file')
        raw = path.read_bytes()
        require(len(raw) == row['sizeBytes'] and sha(raw) == row['sha256'], 'physical identity: ' + name)
        physical[name] = raw
        logical = name[:-3] if name.endswith('.gz') else name
        require(logical not in bodies, 'ambiguous plain/gzip original')
        if name.endswith('.gz'):
            require(logical.endswith('.jsonl') and type(row['logicalSizeBytes']) is int, 'logical identity/schema')
            data = bounded_gzip(raw)
            require(len(data) == row['logicalSizeBytes'] and sha(data) == row['logicalSha256'], 'logical identity: ' + name)
        else:
            require('logicalSha256' not in row, 'plain file must retain original bytes')
            data = raw
        bodies[logical] = data
    files, dirs = set(), set()
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'linked packet entry')
        if path.is_file(): files.add(path.relative_to(root).as_posix())
        elif path.is_dir(): dirs.add(path.relative_to(root).as_posix())
        else: raise ValueError('special packet entry')
    expected_dirs = set()
    for name in physical:
        expected_dirs.update(str(p) for p in PurePosixPath(name).parents if str(p) != '.')
    require(files == set(physical) | {'packet-manifest.json'} and dirs == expected_dirs, 'packet file/directory closure')
    require(sum(map(len, bodies.values())) <= 64 * 1024 ** 2, 'packet logical population cap')
    directory = decode(bodies['metadata/directory-state.json'])
    run = {k[len('run/engineering-01/'):]: v for k, v in bodies.items() if k.startswith('run/engineering-01/')}
    require(len(run) == 11 and set(directory['files']) == set(run), 'complete actual11 run population')
    require({x['path'] for x in directory['directories']} == {'', 'admission', 'settling', 'tail'}
            and directory['blockDirectories'] == [], 'original directory/block population')
    require(set(directory['emptyFiles']) == {k for k, v in run.items() if not v}
            == {'admission/telemetry.jsonl', 'tail/events.jsonl', 'tail/telemetry.jsonl'}, 'prepared empty logs')
    for name, data in run.items():
        require(typed(directory['files'][name], {'sha256': sha(data), 'sizeBytes': len(data)}), 'original run directory identity')
    mapping = decode(bodies['metadata/source-map.json'])['originalSources']
    require(type(mapping) is list and len(mapping) == 23, 'original source-map population')
    seen = set()
    for row in mapping:
        name = relative(row['packetPath'])
        logical = name[:-3] if name.endswith('.gz') else name
        require(name in physical and name not in seen, 'source map duplicate/unknown path')
        seen.add(name)
        data = bodies[logical]
        require(row['sha256'] == row['logicalSha256'] == sha(data)
                and type(row['sizeBytes']) is int and type(row['logicalSizeBytes']) is int
                and row['sizeBytes'] == row['logicalSizeBytes'] == len(data), 'source map exact byte binding')
    return manifest, bodies, physical


def git_blob(repo, expression):
    commit, separator, name = expression.partition(':')
    require(separator and commit in (SOURCE, FREEZE), 'Git operation is not a frozen blob read')
    relative(name)
    result = subprocess.run(['git', '--no-replace-objects', '-C', str(repo), 'show', expression],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_NO_REPLACE_OBJECTS='1'))
    require(len(result.stdout) <= CAP, 'frozen Git blob cap')
    return result.stdout


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def adapted_run(raw):
    """The complete pinned function is retained except counted host rechecks."""
    require(sha(raw) == ORIGINAL_AUDIT, 'original refusal audit source identity')
    tree = ast.parse(raw)
    function = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'run')
    require(sum(isinstance(x, ast.Name) and x.id == 'native_before' for x in ast.walk(function)) == 5,
            'unexpected original native variable population')
    matched = Counter()

    class Adapter(ast.NodeTransformer):
        def visit_Expr(self, node):
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'require':
                message = call.args[1].value if len(call.args) == 2 and isinstance(call.args[1], ast.Constant) else None
                if message == 'actual controller interpreter':
                    expected = "require(receipt['controllerSysExecutable'] == passport['pythonPath'] and h.file_sha(Path(passport['pythonPath'])) == passport['pythonSha256'], 'actual controller interpreter')"
                    require(ast.dump(node) == ast.dump(ast.parse(expected).body[0]), 'interpreter adaptation node drift')
                    matched['interpreter'] += 1
                    return ast.parse("require(receipt['controllerSysExecutable'] == passport['pythonPath'], 'recorded controller interpreter identity')").body[0]
                if message == 'actual frozen launcher/wrapper':
                    expected = "require(h.file_sha(BASE / '.runtime/run-local.sh') == passport['runtimeWrapperSha256'] and h.file_sha(C4 / 'launch_equal_load.py') == passport['launcherSha256'], 'actual frozen launcher/wrapper')"
                    require(ast.dump(node) == ast.dump(ast.parse(expected).body[0]), 'host tool adaptation node drift')
                    matched['hostTools'] += 1
                    return None
                if message == 'original inputs/source/native changed during replay':
                    require(isinstance(call.args[0], ast.BoolOp) and len(call.args[0].values) == 3, 'final closure node shape')
                    removed = ast.parse('native_before == h.file_sha(native_path)', mode='eval').body
                    require(ast.dump(call.args[0].values[1]) == ast.dump(removed), 'final native recheck node drift')
                    call.args[0].values.pop(1)
                    call.args[1] = ast.Constant('materialized inputs/frozen source bytes changed during records-only replay')
                    matched['finalNative'] += 1
            return self.generic_visit(node)

        def visit_Assign(self, node):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'native_before':
                require(ast.dump(node.value) == ast.dump(ast.parse('h.file_sha(native_path)', mode='eval').body), 'native assignment node drift')
                node.value = ast.parse("policy['nativeHelper']['sha256']", mode='eval').body
                matched['nativeAssignment'] += 1
            return self.generic_visit(node)

        def visit_Name(self, node):
            if node.id == 'native_before': node.id = 'recorded_native_sha'
            return node

        def visit_keyword(self, node):
            if node.arg == 'nativeBinarySha256':
                require(isinstance(node.value, ast.Name) and node.value.id == 'native_before', 'native report field drift')
                node.arg = 'recordedNativeBinarySha256'; matched['nativeReportField'] += 1
            return self.generic_visit(node)

    changed = Adapter().visit(function)
    expected = Counter(interpreter=1, hostTools=1, finalNative=1, nativeAssignment=1, nativeReportField=1)
    require(matched == expected, 'physical adaptation whitelist counts differ')
    module = ast.fix_missing_locations(ast.Module(body=[changed], type_ignores=[]))
    return compile(module, '<pinned-records-only-adapter>', 'exec'), dict(matched)


@contextmanager
def frozen_runtime(cache, repo):
    names = {p.stem for p in (cache / 'experiments/ch7').glob('*.py')}
    previous_modules = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    previous_path = list(sys.path)
    original_popen, original_connection = subprocess.Popen, socket.create_connection

    def only_git(argv, *args, **kwargs):
        require(type(argv) is list and len(argv) == 6 and argv[:5]
                == ['git', '--no-replace-objects', '-C', str(repo), 'show'], 'runtime process execution forbidden')
        require(argv[5].split(':', 1)[0] in (SOURCE, FREEZE), 'nonfrozen Git read forbidden')
        return original_popen(argv, *args, **kwargs)

    def no_connection(*args, **kwargs):
        raise ValueError('network/API connection forbidden in records-only replay')

    subprocess.Popen, socket.create_connection = only_git, no_connection
    sys.path.insert(0, str(cache / 'experiments/ch7'))
    try:
        yield
    finally:
        subprocess.Popen, socket.create_connection = original_popen, original_connection
        for name in names: sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


def verify_packet(root, repo, temp_parent, *, expected_manifest=MANIFEST):
    manifest, bodies, physical = packet_bytes(root, expected_manifest)
    core = decode(bodies['audit/independent-equal-load-refusal-audit-01.json'])
    summary = decode(bodies['summary.json'])
    receipt = decode(bodies['audit/independent-equal-load-refusal-audit-01.receipt.json'])
    require(len(core['numbers']) == len(summary['numbers']) == 47 and typed(core['numbers'], summary['numbers']), 'summary/core47 typed equality')
    require(summary['independentTerminalAuditSha256'] == sha(bodies['audit/independent-equal-load-refusal-audit-01.json']), 'summary/core hash binding')
    require(core['sourceCommit'] == summary['sourceCommit'] == SOURCE
            and core['engineeringFreezeCommit'] == summary['engineeringFreezeCommit'] == FREEZE
            and core['passportSha256'] == summary['passportSha256'] == PASSPORT, 'core/summary frozen context')
    require(typed(core['scope'], summary['scope']) and core['scope']['terminalRecordIntegrityAccepted'] is True
            and core['scope']['table7_3'] == 'NOT_RUN'
            and all(v is False for k, v in core['scope'].items() if k not in ('terminalRecordIntegrityAccepted', 'table7_3')),
            'integrity acceptance is not engineering/scientific qualification')
    require(all(v is False for v in summary['externalApprovalGates'].values()), 'external approval gate changed')
    require(receipt['terminalRecordIntegrityAccepted'] is True and receipt['engineeringAccepted'] is False
            and type(receipt['fullRawColdReplayed']) is int and receipt['fullRawColdReplayed'] == 10, 'historical Mac audit scope')
    for name, row in receipt['files'].items():
        require(row['sha256'] == sha(bodies['audit/' + relative(name)]), 'historical audit receipt internal binding')
    passport = decode(bodies['publication/engineering-01-passport.json'])
    require(sha(bodies['publication/engineering-01-passport.json']) == PASSPORT and len(passport['sourceFiles']) == 28,
            'exact B5 passport/source28')
    with tempfile.TemporaryDirectory(prefix='engineering01-records-', dir=temp_parent) as temporary:
        temporary = Path(temporary); cache = temporary / 'source'; c4 = temporary / 'records'; run = c4 / 'run'
        for name, expected in passport['sourceFiles'].items():
            raw = git_blob(repo, SOURCE + ':' + relative(name))
            require(sha(raw) == expected, 'B5 Git source mismatch: ' + name)
            path = cache / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        helper_raw = git_blob(repo, FREEZE + ':' + PREFIX + 'audit_equal_load.py')
        require(sha(helper_raw) == HELPER, 'exact pre-window helper')
        helper_path = temporary / 'audit_equal_load.py'; helper_path.write_bytes(helper_raw)
        for name, raw in bodies.items():
            if name.startswith('run/engineering-01/'):
                target = run / name[len('run/engineering-01/'):]
            elif name.startswith(('launch/', 'publication/')):
                target = c4 / Path(name).name
            elif name.startswith('audit/'):
                target = c4 / 'analysis' / Path(name).name
            else: continue
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        original_path = c4 / 'analysis/audit_equal_load_refusal_01.py'
        code, changes = adapted_run(original_path.read_bytes())
        helper = load_module('_old_equal_load_helper', helper_path)

        def frozen_git(ignored_repo, *args):
            require(len(args) == 2 and args[0] == 'show', 'only original Git show predicates are allowed')
            return git_blob(repo, args[1])

        helper.git = frozen_git
        namespace = dict(__file__=str(original_path), SOURCE=SOURCE, FREEZE=FREEZE, PASSPORT_SHA=PASSPORT,
            ACCEPTANCE_TOOL_SHA=HELPER, FREEZE_PREFIX=PREFIX, BASE=BASE, C4=c4,
            load_helpers=lambda: helper, require=require, Counter=Counter, datetime=datetime,
            hashlib=hashlib, json=json, Path=Path, sys=sys, traceback=traceback)
        exec(code, namespace)
        args = argparse.Namespace(root=run, repo=cache, output=temporary / 'computed.json',
            passport=c4 / 'engineering-01-passport.json', publication=c4 / 'engineering-freeze-publication.json',
            launch=c4 / 'engineering-launch.json', parent_terminal=c4 / 'engineering-launch.terminal.json',
            snapshot=c4 / 'analysis/equal-load-refusal-01-inputs.json')
        progress = io.StringIO()
        with frozen_runtime(cache, repo), redirect_stdout(progress):
            require(namespace['run'](args) == 0, 'frozen records predicates refused')
        computed = decode(args.output.read_bytes())
        require(typed(computed['numbers'], core['numbers']), 'computed/core47 values or types differ')
        require(typed(computed['scope'], core['scope']), 'computed/core qualification scope differs')
        require(computed['frozenRuntimeIdlePredicate']['error'] == core['frozenRuntimeIdlePredicate']['error'],
                'frozen runtime-domain refusal error differs; traceback paths are not compared')
        require(computed['numbers']['rawSamples'] == 10 and computed['numbers']['phaseValidatedSamples'] == 9
                and computed['numbers']['lastFullServiceSeconds'] > 2
                and computed['numbers']['controllerActualParentWaitExitCode'] == 1
                and computed['numbers']['finiteActualParentWaitZero'] == 70, 'terminal refusal facts differ')
        computed['status'] = 'RECORDS_ONLY_FROZEN_B5_REFUSAL_REPLAY_PASS'
        computed['livePhysicalRechecks'] = {name: 'NOT_RECHECKED_RECORDS_ONLY' for name in (
            'nativeBinary', 'controllerInterpreter', 'runtimeWrapper', 'launcherHostPath')}
        computed['frozenPredicateProgressOutput'] = progress.getvalue()
        computed['physicalCheckAdapterWhitelist'] = changes
    require(sha((root / 'packet-manifest.json').read_bytes()) == expected_manifest, 'packet manifest changed during replay')
    for name, raw in physical.items(): require((root / name).read_bytes() == raw, 'packet bytes changed during replay')
    return dict(schema='aijade.ch7.prefix-engineering-records-only-archive-verification.v1',
        status='RECORDS_ONLY_ARCHIVE_REPLAY_PASS_ENGINEERING_REFUSED', manifestSha256=expected_manifest,
        sourceCommit=SOURCE, engineeringFreezeCommit=FREEZE, passportSha256=PASSPORT,
        frozenSourcePopulation=28, frozenSourceGitObjectsVerified=True, coldRawReplayed=10,
        historicalOriginalMacAudit=dict(status=core['status'], sha256=sha(bodies['audit/independent-equal-load-refusal-audit-01.json']),
            recordedNativeBinarySha256=core['nativeBinarySha256'],
            physicalVerification='HISTORICALLY_RECORDED_BY_ORIGINAL_MAC_AUDIT_NOT_REEXECUTED'),
        recordsOnlyReplay=computed, numbers=computed['numbers'], scope=computed['scope'],
        currentLiveNativeBytesRechecked=False, currentLiveInterpreterBytesRechecked=False,
        currentLiveWrapperOrLauncherBytesRechecked=False, runtimeProcessesOrApiInvoked=False,
        currentE03CodeUsed=False, originalPacketUnchanged=True, qualified=False)


def rebind_packet(root):
    core_path = root / 'audit/independent-equal-load-refusal-audit-01.json'
    summary_path = root / 'summary.json'
    summary = decode(summary_path.read_bytes()); summary['independentTerminalAuditSha256'] = sha(core_path.read_bytes())
    summary_path.write_bytes(encode(summary))
    receipt_path = root / 'audit/independent-equal-load-refusal-audit-01.receipt.json'
    receipt = decode(receipt_path.read_bytes())
    for name, row in receipt['files'].items():
        raw = (root / 'audit' / name).read_bytes(); row['sha256'] = sha(raw)
        if 'sizeBytes' in row: row['sizeBytes'] = len(raw)
    receipt_path.write_bytes(encode(receipt))
    source_path = root / 'metadata/source-map.json'; sources = decode(source_path.read_bytes())
    for row in sources['originalSources']:
        raw = (root / row['packetPath']).read_bytes()
        logical = bounded_gzip(raw) if row['packetPath'].endswith('.gz') else raw
        row.update(sha256=sha(logical), logicalSha256=sha(logical), sizeBytes=len(logical), logicalSizeBytes=len(logical))
    source_path.write_bytes(encode(sources))
    manifest_path = root / 'packet-manifest.json'; manifest = decode(manifest_path.read_bytes())
    for row in manifest['files']:
        raw = (root / row['path']).read_bytes(); row.update(sha256=sha(raw), sizeBytes=len(raw))
        if 'logicalSha256' in row:
            logical = bounded_gzip(raw); row.update(logicalSha256=sha(logical), logicalSizeBytes=len(logical))
    manifest_path.write_bytes(encode(manifest))
    return sha(manifest_path.read_bytes())


def controls(root, repo, temp_parent):
    baseline = verify_packet(root, repo, temp_parent)
    rows = []
    for name in ('summary_population', 'coherent_planned_denominator', 'coherent_bool_zero'):
        print('CONTROL_BASELINE', name, flush=True)
        with tempfile.TemporaryDirectory(prefix='engineering01-control-', dir=temp_parent) as temporary:
            mutant = Path(temporary) / 'packet'; shutil.copytree(root, mutant)
            verify_packet(mutant, repo, temp_parent)
            before = sha((mutant / 'packet-manifest.json').read_bytes())
            summary_path = mutant / 'summary.json'; summary = decode(summary_path.read_bytes())
            core_path = mutant / 'audit/independent-equal-load-refusal-audit-01.json'; core = decode(core_path.read_bytes())
            if name == 'summary_population': summary['numbers']['rawSamples'] = 9
            elif name == 'coherent_planned_denominator':
                summary['numbers']['plannedSettlingSamples'] = core['numbers']['plannedSettlingSamples'] = 301
            else: summary['numbers']['modelRequests'] = core['numbers']['modelRequests'] = False
            summary_path.write_bytes(encode(summary)); core_path.write_bytes(encode(core))
            rebound = rebind_packet(mutant)
            require(rebound != before, 'NoOp mutation refused by control driver')
            packet_bytes(mutant, rebound)  # First prove complete coherent byte closure.
            try:
                verify_packet(mutant, repo, temp_parent, expected_manifest=rebound)
            except Exception as error:
                reason = type(error).__name__ + ': ' + str(error)
            else: raise ValueError('coherent corruption was accepted: ' + name)
            rows.append(dict(name=name, baselineAccepted=True, mutationWasEffective=True,
                manifestCoherentlyRebound=True, reboundManifestSha256=rebound, rejected=True, reason=reason))
            print('CONTROL_REJECTED', name, reason, flush=True)
    return dict(schema='aijade.ch7.prefix-engineering-archive-negative-controls.v1',
        status='RECORDS_ONLY_BASELINE_AND_3_COHERENT_CORRUPTIONS_REJECTED', baseline=baseline,
        controls=3, baselineAccepted=3, rejected=3, rows=rows, originalPacketUnchanged=True,
        originalManifestSha256=MANIFEST, qualified=False, noLiveRuntimeOrApiInvoked=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).with_name('packet'))
    parser.add_argument('--repo', type=Path, required=True, help='Existing Git object repository containing B5 and F; never current code for replay')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--temp-root', type=Path)
    parser.add_argument('--controls', action='store_true')
    args = parser.parse_args()
    root, repo, output = args.root.absolute(), args.repo.resolve(), args.output.absolute()
    require(not output.exists() and root not in output.parents, 'output must be new and outside the immutable packet')
    temp_parent = args.temp_root or (BASE / '.runtime/posix/tmp' if sys.platform == 'darwin'
        else Path(os.environ.get('RUNNER_TEMP') or os.environ.get('TMPDIR') or tempfile.gettempdir()))
    if sys.platform == 'darwin':
        require(temp_parent.absolute().is_relative_to(BASE) and output.is_relative_to(BASE), 'Mac output/temp must remain in AIJADE')
    temp_parent.mkdir(parents=True, exist_ok=True)
    try:
        result = controls(root, repo, temp_parent) if args.controls else verify_packet(root, repo, temp_parent)
        result['verificationToolSha256'] = sha(Path(__file__).read_bytes())
        output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(encode(result))
        print(json.dumps(dict(status=result['status'], output=str(output), sha256=sha(output.read_bytes())), sort_keys=True), flush=True)
        return 0
    except Exception as error:
        failure = dict(status='RECORDS_ONLY_ARCHIVE_VERIFICATION_REFUSED', error=type(error).__name__ + ': ' + str(error),
            traceback=traceback.format_exc(), qualified=False, currentLiveBytesRechecked=False)
        output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(encode(failure))
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
