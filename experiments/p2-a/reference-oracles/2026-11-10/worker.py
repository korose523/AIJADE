"""Run one pinned/public or artificial reference under the controller's OS restrictions."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import random
import resource
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_core import canonical, comparator_requirements, load_deserializer, source_json, typed


def emit(record):
    sys.stdout.write(canonical(record) + '\n')
    sys.stdout.flush()


def error(exc):
    return {'type': type(exc).__name__, 'message': str(exc)[:2000]}


def main():
    payload = json.load(sys.stdin)
    settings = payload.get('limits', {})
    limits = {}
    for key, resource_key, value in [('cpuSeconds', resource.RLIMIT_CPU, settings.get('cpuSeconds', 15)),
                                      ('dataBytes', resource.RLIMIT_DATA, 512*1024**2),
                                      ('fileBytes', resource.RLIMIT_FSIZE, 64*1024**2),
                                      ('openFiles', resource.RLIMIT_NOFILE, 64), ('coreBytes', resource.RLIMIT_CORE, 0)]:
        try:
            resource.setrlimit(resource_key, (value, value))
            limits[key] = {'requested': value, 'observed': list(resource.getrlimit(resource_key)), 'status': 'SETTING_ACCEPTED_NOT_INDEPENDENTLY_PROVEN'}
        except (OSError, ValueError) as exc:
            limits[key] = {'requested': value, 'status': 'UNAVAILABLE', 'error': type(exc).__name__}
    random.seed(0)
    problem = payload['problem']
    task_id, dataset = problem['task_id'], payload['dataset']
    upstream = Path(__file__).resolve().parent/'upstream'
    deserialize, function_sha = load_deserializer(upstream)
    comparators = comparator_requirements(dataset, problem, upstream)
    code = problem['prompt'] + problem['canonical_solution']
    begin = {'kind': 'begin', 'taskId': task_id, 'dataset': dataset,
             'problemSha256': hashlib.sha256(source_json(problem).encode()).hexdigest(),
             'codeSha256': hashlib.sha256(code.encode()).hexdigest(), 'deserializerFunctionSha256': function_sha,
             'comparatorRequirements': comparators, 'limits': limits, 'pythonVersion': sys.version,
             'hashSeed': os.environ.get('PYTHONHASHSEED'), 'namespacePerPartition': True,
             'argumentsDeepcopiedPerCall': True}
    emit(begin)
    counts = {}
    # Keep reference print calls separate from the structured raw-record channel.
    with open(os.devnull, 'w') as sink:
        for partition in ['base', 'plus']:
            serialized = copy.deepcopy(problem[partition + '_input'])
            restored = deserialize(task_id, copy.deepcopy(serialized)) if dataset == 'MBPP+' else copy.deepcopy(serialized)
            assert len(restored) == len(serialized)
            namespace = {}
            load_error = None
            try:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    exec(compile(code, '<public-canonical-reference>', 'exec'), namespace)
                fn = namespace[problem['entry_point']]
            except BaseException as exc:
                load_error = error(exc)
            pending = []
            for index, (raw_args, args) in enumerate(zip(serialized, restored)):
                args = copy.deepcopy(args)  # Exactly the pinned trusted_exec calling convention.
                typed_input, input_flags = typed(args)
                record = {'kind': 'case', 'taskId': task_id, 'dataset': dataset, 'partition': partition, 'index': index,
                          'serializedArgsJson': json.dumps(raw_args, ensure_ascii=False, separators=(',', ':')),
                          'input': typed_input, 'inputFlags': sorted(input_flags), 'outputFlags': []}
                if load_error:
                    record.update(status='REFERENCE_EXCEPTION', error=load_error)
                else:
                    try:
                        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                            output = fn(*args)
                        record.update(status='OK', _nativeOutput=output)
                    except BaseException as exc:
                        record.update(status='REFERENCE_EXCEPTION', error=error(exc))
                pending.append(record)
            # The upstream helper retains the return values in a list. Later calls may mutate an
            # aliased return object; serialize after the partition, not an early value snapshot.
            for record in pending:
                if record['status'] == 'OK':
                    output = record.pop('_nativeOutput')
                    encoded, flags = typed(output)
                    if type(output) is float:
                        flags.add('flat-float-output-needs-upstream-tolerance')
                    record.update(output=encoded, outputFlags=sorted(flags))
                emit(record)
            counts[partition] = len(restored)
        namespace = {}
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                exec(compile(code, '<public-canonical-reference>', 'exec'), namespace)
                if dataset == 'HumanEval+':
                    exec(compile(problem['test'], '<public-base-check>', 'exec'), namespace)
                    namespace['check'](namespace[problem['entry_point']])
                else:
                    assert 'assertion' in problem
                    exec(compile(problem['assertion'], '<public-base-assertions>', 'exec'), namespace)
            native = {'status': 'PASS'}
        except BaseException as exc:
            native = {'status': 'FAIL', 'error': error(exc)}
    emit({'kind': 'end', 'taskId': task_id, 'counts': counts, 'nativeAssertions': native})


if __name__ == '__main__':
    main()
