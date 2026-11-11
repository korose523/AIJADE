"""Recover every pinned Mbpp/255 reference as a lossless ordered tuple stream."""
import argparse
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
P2A = HERE.parents[1]
ROOT = HERE.parents[3]
REFERENCE = P2A / 'reference-oracles/2026-11-10'
JAVASCRIPT = P2A / 'javascript-port/2026-11-11'
PLAN = 'cc1ff398a424b02648bb66559813db74fa58527b'
PRIOR = 'fc01b9dbf2b38ea724b8006169f059007145c192'
TASK = 'Mbpp/255'
CHUNK = 1024**2
FILE_LIMIT = 64 * CHUNK

sys.path.insert(0, str(REFERENCE))
from oracle_core import DATASETS, canonical, digest_bytes, digest_file, load_deserializer, source_json, typed
from run import ENVIRONMENT, PYTHON, profile


def source_task(task_id):
    name, digest, *_ = DATASETS['MBPP+']
    source = REFERENCE / 'inputs' / name
    assert digest_file(source) == digest
    with gzip.open(source, 'rt', encoding='utf-8') as stream:
        return next(row for row in map(json.loads, stream) if row['task_id'] == task_id)


def case_inputs(problem):
    restore, _ = load_deserializer(REFERENCE / 'upstream')
    for partition in ('base', 'plus'):
        raw = problem[partition + '_input']
        native = restore(problem['task_id'], copy.deepcopy(raw))
        assert len(raw) == len(native)
        for index, (serialized, args) in enumerate(zip(raw, native)):
            yield [partition, index], serialized, args


def value_alphabet(pool):
    values = []
    signatures = {}
    tokens = {}
    position_tokens = []
    for item in pool:
        value, flags = typed(item)
        assert not flags - {'astral-string'} and type(item) in (str, int, float, bool)
        key = canonical(value)
        if key not in signatures:
            signatures[key] = len(values)
            values.append(value)
        token = signatures[key]
        tokens[id(item)] = token
        position_tokens.append(token)
    return values, tokens, position_tokens


def successor_rows(position_tokens, arity):
    """Enumerate ordered multisets of positions with an iterative successor."""
    if arity == 0:
        yield b''
        return
    if not position_tokens:
        return
    last = len(position_tokens) - 1
    indices = [0] * arity
    while True:
        yield bytes(position_tokens[index] for index in indices)
        pivot = arity - 1
        while pivot >= 0 and indices[pivot] == last:
            pivot -= 1
        if pivot < 0:
            return
        indices[pivot:] = [indices[pivot] + 1] * (arity - pivot)


def run_reference(mode, catalog_path):
    for key, limit in [(resource.RLIMIT_CPU, 120), (resource.RLIMIT_FSIZE, FILE_LIMIT), (resource.RLIMIT_CORE, 0)]:
        resource.setrlimit(key, (limit, limit))
    problem = json.load(sys.stdin)
    assert problem['task_id'] == TASK
    code = problem['prompt'] + problem['canonical_solution']
    scope = {}
    if mode == 'native':
        exec(compile(code, '<pinned-mbpp-255>', 'exec'), scope)
        exec(compile(problem['assertion'], '<pinned-mbpp-255-assertions>', 'exec'), scope)
    output = sys.stdout.buffer
    with catalog_path.open('w', encoding='utf-8') as catalog:
        for identity, raw, args in case_inputs(problem):
            pool, arity = args
            assert type(pool) is list and type(arity) is int and arity >= 0
            alphabet, object_tokens, position_tokens = value_alphabet(pool)
            offset = output.tell()
            count = 0
            digest = hashlib.sha256()
            if mode == 'native':
                rows = scope[problem['entry_point']](*args)
                assert type(rows) is list
                encoded = (bytes(map(object_tokens.__getitem__, map(id, row))) for row in rows)
            else:
                encoded = successor_rows(position_tokens, arity)
            with gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0, compresslevel=1) as zipped:
                block = bytearray()
                for row in encoded:
                    assert len(row) == arity
                    count += 1
                    block.extend(row)
                    if len(block) >= CHUNK:
                        zipped.write(block)
                        digest.update(block)
                        block.clear()
                zipped.write(block)
                digest.update(block)
            output.flush()
            if mode == 'native':
                del rows, encoded
            count_expected = math.comb(len(pool) + arity - 1, arity) if pool else int(arity == 0)
            assert count == count_expected
            record = {
                'taskId': TASK, 'case': identity,
                'rawInputSha256': digest_bytes(source_json(raw).encode()),
                'typedArguments': typed(args)[0], 'alphabet': alphabet,
                'shape': ['list', 'tuple'], 'tupleCount': count, 'tupleArity': arity,
                'offset': offset, 'compressedBytes': output.tell() - offset,
                'valueStreamSha256': digest.hexdigest(),
            }
            catalog.write(canonical(record) + '\n')
            catalog.flush()
    print(canonical({'mode': mode, 'nativeAssertions': 'PASS' if mode == 'native' else None}), file=sys.stderr)


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT, text=True).strip()


def run_bounded(command, folder, env, input_path=None, wall=180, rss_limit=2 * 1024**3,
                stdout_name='values.gz', limits=None):
    started = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat()
    stdout = folder / stdout_name
    stderr = folder / 'stderr.log'
    stop = None
    peak = 0
    with stdout.open('wb') as out, stderr.open('wb') as err:
        input_stream = input_path.open('rb') if input_path else None
        try:
            child = subprocess.Popen(command, stdin=input_stream or subprocess.DEVNULL, stdout=out, stderr=err,
                                     env=env, cwd=folder, start_new_session=True, preexec_fn=limits)
            while child.poll() is None:
                if time.monotonic() - started > wall:
                    stop = 'WALL_LIMIT'
                sample = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(child.pid)], capture_output=True, text=True)
                if sample.stdout.strip().isdigit():
                    peak = max(peak, int(sample.stdout) * 1024)
                    if peak > rss_limit:
                        stop = 'SAMPLED_RSS_LIMIT'
                if stop:
                    try:
                        # A process can exit between the last poll and the kill.
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    break
                time.sleep(0.10)
            exit_code = child.wait()
        finally:
            if input_stream:
                input_stream.close()
    return {
        'startedAt': timestamp, 'wallSeconds': round(time.monotonic() - started, 3),
        'exitCode': exit_code, 'stop': stop, 'sampledPeakRssBytes': peak,
        'stdoutSha256': digest_file(stdout), 'stderrSha256': digest_file(stderr),
        'stderr': stderr.read_text(encoding='utf-8', errors='replace'),
    }


def read_jsonl(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        yield from map(json.loads, stream)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def open_case(member_file, row):
    with member_file.open('rb') as stream:
        stream.seek(row['offset'])
        data = stream.read(row['compressedBytes'])
    assert len(data) == row['compressedBytes']
    return gzip.GzipFile(fileobj=io.BytesIO(data), mode='rb')


def iter_rows(member_file, row):
    width = row['tupleArity']
    with open_case(member_file, row) as stream:
        for _ in range(row['tupleCount']):
            tokens = stream.read(width)
            assert len(tokens) == width
            yield tokens
        assert stream.read(1) == b''


def validate_archive(directory):
    problem = source_task(TASK)
    rows = list(read_jsonl(directory / 'cases.jsonl'))
    inputs = list(case_inputs(problem))
    assert len(rows) == len(inputs) == 112
    output_file = directory / 'values.gz'
    expected_offset = 0
    for row, (identity, raw, args) in zip(rows, inputs):
        pool, arity = args
        alphabet, _, _ = value_alphabet(pool)
        assert row['taskId'] == TASK and row['case'] == identity
        assert row['rawInputSha256'] == digest_bytes(source_json(raw).encode())
        assert row['typedArguments'] == typed(args)[0] and row['alphabet'] == alphabet
        assert row['offset'] == expected_offset and row['shape'] == ['list', 'tuple']
        assert row['tupleArity'] == arity
        assert row['tupleCount'] == (math.comb(len(pool) + arity - 1, arity) if pool else int(arity == 0))
        digest = hashlib.sha256()
        width = size = 0
        with output_file.open('rb') as stream:
            stream.seek(row['offset'])
            raw_member = stream.read(row['compressedBytes'])
        row['compressedSha256'] = digest_bytes(raw_member)
        with open_case(output_file, row) as stream:
            for block in iter(lambda: stream.read(CHUNK), b''):
                digest.update(block)
                size += len(block)
                width = max(width, max(block) + 1)
        assert size == arity * row['tupleCount'] and width <= len(alphabet)
        assert digest.hexdigest() == row['valueStreamSha256']
        expected_offset += row['compressedBytes']
    assert expected_offset == output_file.stat().st_size
    old = json.loads((JAVASCRIPT / 'results/recovery/summary.json').read_text())['tasks'][TASK]['passes'][0]
    path = JAVASCRIPT / 'results/recovery' / old['path']
    assert digest_file(path) == old['streamSha256']
    # The earlier RSS stop left a truncated gzip trailer after the base prefix.
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        assert json.loads(stream.readline())['kind'] == 'begin'
        for row in rows[:3]:
            archived = json.loads(stream.readline())
            items = [{'t': 'tuple', 'items': [row['alphabet'][i] for i in tokens]}
                     for tokens in iter_rows(output_file, row)]
            assert archived['partition'] == 'base' and archived['index'] == row['case'][1]
            assert archived['input'] == row['typedArguments']
            assert archived['output'] == {'t': 'list', 'items': items}
    return rows


def recover(out):
    assert git('status', '--porcelain') == ''
    subprocess.run(['git', 'merge-base', '--is-ancestor', PLAN, 'HEAD'], cwd=ROOT, check=True)
    assert list(successor_rows([], 0)) == [b'']
    assert list(successor_rows([], 2)) == []
    assert list(successor_rows([0, 0, 1], 2)) == [b'\x00\x00', b'\x00\x00', b'\x00\x01',
                                                 b'\x00\x00', b'\x00\x01', b'\x01\x01']
    out.mkdir(parents=True, exist_ok=False)
    payload = out / 'input.json'
    problem = source_task(TASK)
    payload.write_text(source_json(problem), encoding='utf-8')
    result = {'schema': 'aijade.p2a.mbpp255-reference.v1', 'planCommit': PLAN, 'priorArchiveCommit': PRIOR,
              'executionCodeCommit': git('rev-parse', 'HEAD'), 'newModelCalls': 0,
              'limits': {'cpuSeconds': 120, 'wallSeconds': 180, 'sampledRssBytes': 2 * 1024**3,
                         'compressedFileBytes': FILE_LIMIT},
              'pythonSha256': digest_file(PYTHON), 'pythonVersion': subprocess.check_output(
                  [str(PYTHON), '--version'], text=True).strip(),
              'inputSha256': digest_file(payload), 'sourceSha256': digest_file(__file__),
              'releaseSha256': DATASETS['MBPP+'][1],
              'nativeCodeSha256': digest_bytes((problem['prompt'] + problem['canonical_solution']).encode()),
              'deserializerFunctionSha256': load_deserializer(REFERENCE / 'upstream')[1],
              'passes': {}, 'status': 'INCOMPLETE'}
    for mode in ('native', 'successor'):
        folder = out / mode
        folder.mkdir()
        catalog = folder / 'cases.jsonl'
        rule = (profile(folder / 'values.gz', folder / 'stderr.log') +
                f'(allow file-read* (literal {json.dumps(str(Path(__file__).resolve()))}))\n'
                f'(allow file-write* (literal {json.dumps(str(catalog.resolve()))}))\n')
        policy = folder / 'isolation.sb'
        policy.write_text(rule, encoding='utf-8')
        command = ['/usr/bin/sandbox-exec', '-f', str(policy), str(PYTHON), '-S', '-P',
                   str(HERE / Path(__file__).name), 'worker', mode, str(catalog)]
        receipt = run_bounded(command, folder, ENVIRONMENT, payload)
        receipt['profileSha256'] = digest_file(policy)
        result['passes'][mode] = receipt
        write_json(out / 'summary.json', result)
        print(mode, receipt['exitCode'], receipt['stop'], receipt['sampledPeakRssBytes'], flush=True)
        assert receipt['exitCode'] == 0 and not receipt['stop'], receipt
        rows = validate_archive(folder)
        receipt.update({'caseRows': len(rows), 'catalogSha256': digest_file(catalog),
                        'compressedBytes': (folder / 'values.gz').stat().st_size})
        write_json(out / 'summary.json', result)
    first, second = (result['passes'][mode] for mode in ('native', 'successor'))
    assert first['stdoutSha256'] == second['stdoutSha256'] and first['catalogSha256'] == second['catalogSha256']
    assert json.loads(first['stderr'])['nativeAssertions'] == 'PASS'
    reference_rows = validate_archive(out / 'native')
    result.update({'status': 'PASS', 'caseRows': len(reference_rows), 'baseCases': 3,
                   'recoveredPlusCases': 109, 'missingPlusCases': 0, 'previousBaseRowsMatch': 3,
                   'totalTuples': sum(row['tupleCount'] for row in reference_rows),
                   'totalTupleElements': sum(row['tupleCount'] * row['tupleArity'] for row in reference_rows),
                   'largestCase': max(reference_rows, key=lambda row: row['tupleCount']),
                   'repeatedStreamsByteIdentical': True})
    write_json(out / 'summary.json', result)
    print('Recovered', result['caseRows'], 'rows', result['totalTuples'], 'tuples', flush=True)


def main():
    parser = argparse.ArgumentParser(__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('recover').add_argument('directory', type=Path)
    worker = commands.add_parser('worker')
    worker.add_argument('mode', choices=['native', 'successor'])
    worker.add_argument('catalog', type=Path)
    decode = commands.add_parser('decode')
    decode.add_argument('directory', type=Path)
    decode.add_argument('partition', choices=['base', 'plus'])
    decode.add_argument('index', type=int)
    decode.add_argument('--preview', type=int)
    args = parser.parse_args()
    if args.command == 'recover':
        recover(args.directory.resolve())
    elif args.command == 'worker':
        run_reference(args.mode, args.catalog)
    else:
        rows = list(read_jsonl(args.directory / 'cases.jsonl'))
        row = next(row for row in rows if row['case'] == [args.partition, args.index])
        print(canonical({'case': row['case'], 'tupleCount': row['tupleCount'],
                         'tupleArity': row['tupleArity'], 'shape': row['shape']}))
        from itertools import islice
        tokens = iter_rows(args.directory / 'values.gz', row)
        for token_row in islice(tokens, args.preview):
            print(canonical({'t': 'tuple', 'items': [row['alphabet'][i] for i in token_row]}))


if __name__ == '__main__':
    main()
