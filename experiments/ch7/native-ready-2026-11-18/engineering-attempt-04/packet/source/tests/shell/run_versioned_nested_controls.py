"""Run unchanged E4/E5 tests with their actual historical source subjects.

Current native/owned tests run in separate CI invocations against current code.
This runner never imports an E5 cursor into a current native process.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from versioned_nested_scope import (materialize_e5_source,verify_materialized_e5,
    checked_file,E5_CRITICAL,E4_AUDIT_REL,E4_AUDIT_SHA,E4_TEST_SHA,E4_INITIALIZATION_TEST_SHA,E4_CURSOR_SHA)

REPO=Path(os.environ.get('AIJADE_VERSIONED_CONTROL_REPO',str(Path(__file__).resolve().parents[2]))).resolve()


def main():
    scratch=REPO/'.runtime/scoped-control-tmp';scratch.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(scratch);os.environ['TMPDIR']=str(scratch)
    sys.path[:0]=[str(REPO/'tests/shell'),str(REPO/'experiments/ch7')]
    checked_file(REPO/'tests/shell/test_nested_load_audit.py',E4_TEST_SHA)
    checked_file(REPO/'tests/shell/test_nested_initialization_audit.py',E4_INITIALIZATION_TEST_SHA)
    old=Path(os.environ.get('AIJADE_E4_AUDIT_SOURCE',str(REPO/E4_AUDIT_REL))).resolve()
    checked_file(old,E4_AUDIT_SHA)
    cursor=REPO/'experiments/ch7/full_state_clone_cursor.py';checked_file(cursor,E4_CURSOR_SHA)
    # Initialization controls use their own spec loader and bypass sys.modules;
    # bind that independent entry explicitly as well as the direct-import test.
    os.environ.update(AIJADE_E4_AUDIT_SOURCE=str(old),AIJADE_E4_CURSOR_SOURCE=str(cursor),
                      AIJADE_E4_SOURCE_REPO=str(REPO))
    spec=importlib.util.spec_from_file_location('audit_nested_load',old)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.modules['audit_nested_load']=module
    suite=unittest.TestSuite()
    paths=sorted((REPO/'tests/shell').glob('test_nested_*.py'))
    selected=[p for p in paths if p.name!='test_nested_owned_initialization_audit.py']
    if not selected:raise ValueError('no current baseline nested controls found')
    for path in selected:suite.addTests(unittest.defaultTestLoader.discover(str(REPO/'tests/shell'),pattern=path.name))
    print('E4 unchanged test bytes285181 use exact original11d5 module; current native controls run separately.',flush=True)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():return 1
    root=materialize_e5_source(REPO)
    checked_file(REPO/'tests/shell/test_nested_owned_initialization_audit.py',E5_CRITICAL['tests/shell/test_nested_owned_initialization_audit.py'])
    env=dict(os.environ,AIJADE_E5_SOURCE_REPO=str(root),
        AIJADE_E5_CURSOR_SOURCE=str(root/'experiments/ch7/newowned_guard_cursor.py'),
        AIJADE_E5_AUDIT_SOURCE=str(root/'experiments/ch7/audit_nested_load.py'))
    print('E5 original8d75 tests run in a new process with all48 original sources: audit88a3, owner1d50, guarde918; one unchanged earlier fixture66b5.',flush=True)
    completed=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(root/'tests/shell'),
        '-p','test_nested_owned_initialization_audit.py','-v'],cwd=REPO,env=env,check=False)
    verify_materialized_e5(root)
    return completed.returncode


if __name__=='__main__':raise SystemExit(main())
