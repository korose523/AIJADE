#!/usr/bin/env python3
"""Compile the original local-SDK census helper; never start an observation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

BASE = Path('/Volumes/Untitled/AIJADE')
SOURCE = Path(__file__).with_name('mac_bulk_census.c')


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode: raise RuntimeError('Native compile/read command failed: ' + result.stderr[-4000:])
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    args = parser.parse_args()
    for path in (args.out, args.metadata):
        path.absolute().relative_to(BASE)
        if path.exists(): raise ValueError('Refuse to overwrite prior native engineering artifact: ' + str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.resolve() != path.parent.absolute(): raise ValueError('Native output parent must not contain symlinks')
    if platform.system() != 'Darwin': raise RuntimeError('The helper must compile against the installed Mac SDK')
    clang = command(['/usr/bin/xcrun', '--sdk', 'macosx', '--find', 'clang'])
    sdk = command(['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-path'])
    version = command([clang, '--version'])
    sdk_version = command(['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-version'])
    before = sha(SOURCE)
    argv = [clang, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-isysroot', sdk, str(SOURCE), '-o', str(args.out)]
    command(argv)
    if sha(SOURCE) != before: raise ValueError('C source changed during compilation')
    args.out.chmod(0o755)
    data = {'status': 'NATIVE_HELPER_COMPILED_ENGINEERING_ONLY_NO_OBSERVATION',
            'path': str(args.out.absolute()), 'sha256': sha(args.out), 'sourceSha256': before,
            'sourcePath': str(SOURCE.absolute()), 'compilerPath': clang, 'compilerVersion': version,
            'sdkPath': sdk, 'sdkVersion': sdk_version, 'targetMachine': platform.machine(),
            'command': argv, 'compiledAt': datetime.now(timezone.utc).isoformat(),
            'helperExecuted': False, 'qualification': False}
    with args.metadata.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
