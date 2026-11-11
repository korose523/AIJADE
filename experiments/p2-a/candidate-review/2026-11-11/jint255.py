"""Test recovered Mbpp/255 cases with the already archived public-task Jint executor."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import resource
import shutil
import sys

sys.dont_write_bytecode = True
from recover255 import (CHUNK, FILE_LIMIT, JAVASCRIPT, PLAN, ROOT, TASK, canonical, digest_bytes,
                        digest_file, git, iter_rows, open_case, read_jsonl, run_bounded, write_json)

sys.path.insert(0, str(JAVASCRIPT))
from prepare import project

OLD_CACHE = Path('/Users/mac/.cache/aijade-p2a-js-20261111')
DOTNET = Path('/usr/local/share/dotnet/dotnet')
DLL = OLD_CACHE / 'dotnet-final/bin/JintReplay/release/JintReplay.dll'
PORT = OLD_CACHE / 'ports-06/Mbpp-255.js'
MODE = {'bigint': False, 'tuples': False, 'entries': False, 'decimalDigits': False}
CONTRACT = ('Arguments are provided in this order (l, n). Numeric values use finite JavaScript Number values. '
            'Lists and tuples are arrays.')


def allocation_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_LIMIT, FILE_LIMIT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def measure_literal(stream_path, row):
    counts = Counter()
    with open_case(stream_path, row) as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            counts.update(block)
    tokens = [project(value, MODE).encode('ascii') for value in row['alphabet']]
    # Outer brackets, row separators, tuple brackets, element separators, values.
    tuples, arity = row['tupleCount'], row['tupleArity']
    size = 2 + max(0, tuples - 1) + tuples * (2 + max(0, arity - 1))
    size += sum(count * len(tokens[token]) for token, count in counts.items())
    assert sum(counts.values()) == tuples * arity
    return size, tokens


def expected_literal(stream_path, row, tokens):
    literal = bytearray(b'[')
    for index, values in enumerate(iter_rows(stream_path, row)):
        if index:
            literal.extend(b',')
        literal.extend(b'[')
        literal.extend(b','.join(tokens[value] for value in values))
        literal.extend(b']')
    literal.extend(b']')
    return literal.decode('ascii')


def replay(reference, out):
    assert git('status', '--porcelain') == ''
    release = json.loads((JAVASCRIPT / 'results/release/execution.json').read_text())
    old_summary = json.loads((JAVASCRIPT / 'results/release/summary.json').read_text())
    task = next(row for row in old_summary['tasks'] if row['taskId'] == TASK)
    assert digest_file(DOTNET) == release['executableSha256']
    assert digest_file(DLL) == release['jintReplaySha256']
    assert digest_file(DLL.parent / 'Aijade.Research.dll') == release['researchAssemblySha256']
    assert digest_file(DLL.parent / 'Jint.dll') == release['jintAssemblySha256']
    assert digest_file(PORT) == task['port']['sha256']
    runtime = JAVASCRIPT / 'results/release/source/python-semantics.js'
    assert digest_file(runtime) == release['artifactSha256']['source/python-semantics.js']
    rows = list(read_jsonl(reference / 'cases.jsonl'))
    assert len(rows) == 112
    out.mkdir(parents=True, exist_ok=False)
    summary = {
        'schema': 'aijade.p2a.mbpp255-jint.v1', 'taskId': TASK, 'planCommit': PLAN,
        'executionCodeCommit': git('rev-parse', 'HEAD'), 'originalExecutionCodeCommit': release['executionCodeCommit'],
        'newModelCalls': 0, 'startedAt': datetime.now(timezone.utc).isoformat(),
        'executableSha256': digest_file(DOTNET), 'jintReplaySha256': digest_file(DLL),
        'researchAssemblySha256': release['researchAssemblySha256'], 'jintAssemblySha256': release['jintAssemblySha256'],
        'referenceCatalogSha256': digest_file(reference / 'cases.jsonl'),
        'referenceValuesSha256': digest_file(reference / 'values.gz'),
        'portSha256': digest_file(PORT), 'runtimeSha256': digest_file(runtime),
        'driverSha256': digest_file(__file__),
        'limits': {'sandboxMilliseconds': 2000, 'sandboxAllocationBytes': 512 * CHUNK,
                   'processCpuSeconds': 15, 'processWallSeconds': 30, 'sampledRssBytes': 2 * 1024**3,
                   'expectedLiteralBytes': FILE_LIMIT},
        'caseOutcomes': {}, 'cases': [],
    }
    source = out / 'source'
    source.mkdir()
    shutil.copyfile(PORT, source / PORT.name)
    for row in rows:
        size, tokens = measure_literal(reference / 'values.gz', row)
        case = {'taskId': TASK, 'case': row['case'], 'tupleCount': row['tupleCount'],
                'tupleArity': row['tupleArity'], 'expectedLiteralBytes': size,
                'referenceValueStreamSha256': row['valueStreamSha256']}
        if size > FILE_LIMIT:
            case.update(outcome='TRANSPORT_LIMIT', reason='Expected JS literal exceeds the declared 64 MiB ceiling.')
        else:
            folder = out / ('%s-%03d' % tuple(row['case']))
            folder.mkdir()
            expected = expected_literal(reference / 'values.gz', row, tokens)
            assert len(expected.encode()) == size
            arguments = project(row['typedArguments'], MODE)
            fixture = {'taskId': TASK, 'statement': 'Enumerate combinations with replacement in input-position order.',
                       'contract': CONTRACT, 'cases': [
                           {'args': arguments, 'expected': expected, 'publicFloatTolerance': False}]}
            fixture_path = folder / 'input.json'
            write_json(fixture_path, fixture)
            case.update({'projectedInputSha256': digest_bytes(arguments.encode()),
                         'projectedExpectedSha256': digest_bytes(expected.encode()),
                         'fixtureSha256': digest_file(fixture_path)})
            process = run_bounded([str(DOTNET), str(DLL), str(fixture_path), str(runtime), str(source / PORT.name)],
                                  folder, {'PATH': '/usr/bin:/bin:/usr/local/bin', 'TZ': 'UTC', 'LC_ALL': 'C'},
                                  wall=30, stdout_name='stdout.json', limits=allocation_limits)
            case['process'] = process
            if process['exitCode'] == 0 and not process['stop']:
                observed = json.loads((folder / 'stdout.json').read_text())
                assert observed['taskId'] == TASK and observed['total'] == 1
                case['observed'] = observed
                if observed['passed'] == 1:
                    assert not observed['error'] and not observed['failures']
                    case['outcome'] = 'PASS'
                elif observed['error']:
                    case['outcome'] = 'SANDBOX_LIMIT'
                elif observed['failures']:
                    case['outcome'] = 'ERROR' if observed['failures'][0].get('error') else 'MISMATCH'
                else:
                    raise AssertionError(observed)
            else:
                case['outcome'] = process['stop'] or 'PROCESS_FAILURE'
            fixture_path.unlink()
        summary['cases'].append(case)
        summary['caseOutcomes'] = dict(Counter(item['outcome'] for item in summary['cases']))
        write_json(out / 'summary.json', summary)
        print(row['case'], case['outcome'], 'literal', size, flush=True)
    summary['completeAgreement'] = summary['caseOutcomes'] == {'PASS': len(rows)}
    summary['candidateDecision'] = 'AUTHOR_REVIEW' if summary['completeAgreement'] else 'EXCLUDE_BOUNDED_JINT_COVERAGE'
    write_json(out / 'summary.json', summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    replay(args.reference.resolve(), args.out.resolve())
