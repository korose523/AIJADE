#!/usr/bin/env python3
"""Verify the unchanged research packet against its pinned product version, not a later product build.

This does not qualify current product code for research. The historical verifier and packet stay unmodified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = 'f90f04110f46fb17a2a43a777ed5d4e68a361902'
PACKET = 'experiments/ch7/manifest-preparation-2026-11-12'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(directory, *args):
    return subprocess.check_output(['git', *args], cwd=directory).decode().strip()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def verify(snapshot):
    snapshot = snapshot.resolve(strict=True)
    require(snapshot != ROOT, 'A separate pinned checkout is required')
    require(git(snapshot, 'rev-parse', 'HEAD') == SNAPSHOT, 'Wrong historical snapshot')
    require(not git(snapshot, 'status', '--porcelain', '--untracked-files=no'), 'Dirty historical snapshot')
    require(git(ROOT, 'remote', 'get-url', 'origin') == git(snapshot, 'remote', 'get-url', 'origin'), 'Snapshot repository mismatch')
    entries = subprocess.check_output(['git', 'ls-tree', '-rz', 'HEAD', '--', PACKET], cwd=snapshot).split(b'\0')
    paths = set()
    for entry in filter(None, entries):
        metadata, encoded = entry.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        relative = encoded.decode()
        require(mode == '100644' and kind == 'blob', 'Unexpected historical packet entry')
        current = ROOT / relative
        historical = snapshot / relative
        require(current.is_file() and not current.is_symlink(), 'Missing current packet: ' + relative)
        require(historical.is_file() and not historical.is_symlink(), 'Missing historical packet: ' + relative)
        require(blob(current.read_bytes()) == blob(historical.read_bytes()) == oid, 'Historical packet changed: ' + relative)
        paths.add(relative)
    require(paths, 'Empty historical packet')
    actual = {str(p.relative_to(ROOT)) for p in (ROOT / PACKET).rglob('*') if p.is_file()}
    require(actual == paths, 'Unlisted file in the historical packet')

    freeze = json.loads((snapshot / PACKET / 'source-freeze.json').read_text())
    changed = []
    for item in freeze['files']:
        current = ROOT / item['path']
        if not current.is_file() or current.is_symlink() or hashlib.sha256(current.read_bytes()).hexdigest() != item['sha256']:
            changed.append(item['path'])
    # Run the ORIGINAL whole-packet verifier on the ORIGINAL source tree. Do not patch a freeze to fit newer code.
    run = subprocess.run([sys.executable, '-B', str(snapshot / PACKET / 'verify_archive.py')],
                         cwd=snapshot, capture_output=True, text=True, timeout=120)
    require(run.returncode == 0, 'Pinned historical verifier failed:\n' + run.stdout + run.stderr)
    return {'status': 'HISTORICAL_MANIFEST_VERIFIED', 'snapshot': SNAPSHOT,
            'unchangedCurrentPacketFiles': len(paths), 'historicalSourceFiles': len(freeze['files']),
            'currentProductSourceChanges': changed, 'historicalVerifier': json.loads(run.stdout),
            'currentProductResearchQualified': False, 'newExperimentRun': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.snapshot), indent=2))
