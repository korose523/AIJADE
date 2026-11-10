"""Compress the pinned worker's unmodified record stream before it reaches disk."""
import gzip
import io
from pathlib import Path
import runpy
import sys

worker = Path(__file__).resolve().parents[2] / 'reference-oracles/2026-11-10/worker.py'
with gzip.GzipFile(fileobj=sys.stdout.buffer, mode='wb', filename='', mtime=0, compresslevel=1) as compressed:
    with io.TextIOWrapper(compressed, encoding='utf-8', write_through=True) as stream:
        sys.stdout = stream
        runpy.run_path(str(worker), run_name='__main__')
