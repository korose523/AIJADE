"""Authenticate a frozen test oracle without executing an OS observation.

The historical module is never imported.  Only its full bytes and the exact
original function bytes are compared with the adjacent mock-only oracle.
"""
import ast
import hashlib
import json
from pathlib import Path

SOURCE_SHA256 = 'e918de7431e3f27af2e03017a2f504bf00d85a6a08bf05d7ba5fcd3e14291035'
ORACLE_SHA256 = 'd1f7424d4b39ede392f29bc9976ec0795ae7f76a80db73f113879cc0e445bd64'
FUNCTION_SHA256 = '2481f0b29f4353e3df94786d712901274ee84f3ed74f844bf2b1afb53ce974b0'


def verify_frozen_oracle(repo):
    repo = Path(repo)
    binding = json.loads((repo/'tests/fixtures/native-e6/binding.json').read_bytes())
    expected = dict(sourcePath='tests/fixtures/native-e6/e5_guard_source.py',
                    sourceSha256=SOURCE_SHA256,
                    oraclePath='tests/shell/frozen_e918_oracle.py',
                    oracleSha256=ORACLE_SHA256,
                    function='_read_listeners', functionSha256=FUNCTION_SHA256)
    for key, value in expected.items():
        if type(binding.get(key)) is not str or binding[key] != value:
            raise AssertionError('frozen listener oracle binding differs: '+key)
    source = (repo/expected['sourcePath']).read_bytes()
    oracle = (repo/expected['oraclePath']).read_bytes()
    for name, raw, sha in [('source', source, SOURCE_SHA256), ('oracle', oracle, ORACLE_SHA256)]:
        if hashlib.sha256(raw).hexdigest() != sha:
            raise AssertionError('frozen listener '+name+' full SHA256 differs')
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == expected['function']]
    if len(functions) != 1:
        raise AssertionError('historical listener function population differs')
    node = functions[0]
    body = b''.join(source.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
    if hashlib.sha256(body).hexdigest() != FUNCTION_SHA256:
        raise AssertionError('historical listener function bytes differ')
    # The adjacent oracle has only its provenance comment and the exact original
    # function.  Fake lifecycle/time objects are supplied by its tests.
    if oracle.split(b'\n', 1)[1] != body:
        raise AssertionError('mock listener oracle differs from original function bytes')
    return dict(sourceSha256=SOURCE_SHA256, oracleSha256=ORACLE_SHA256,
                functionSha256=FUNCTION_SHA256)
