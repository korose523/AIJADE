"""Lossless byte transport for original gzip files above GitHub's file limit.

The logical compressed SHA-256 and every chunk are verified before reading.
No record is re-serialized, recompressed, sampled or discarded.
"""
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
from pathlib import Path


CHUNK_BYTES = 60 * 1024 * 1024


class ChunkReader(io.RawIOBase):
    def __init__(self, paths):
        super().__init__()
        self.paths = iter(paths)
        self.current = None

    def readable(self):
        return True

    def readinto(self, buffer):
        view = memoryview(buffer)
        done = 0
        while done < len(view):
            if self.current is None:
                path = next(self.paths, None)
                if path is None:
                    break
                self.current = path.open('rb')
            count = self.current.readinto(view[done:])
            if count:
                done += count
            else:
                self.current.close()
                self.current = None
        return done

    def close(self):
        if self.current is not None:
            self.current.close()
            self.current = None
        super().close()


def verified_parts(path):
    path = Path(path)
    record = json.loads(Path(str(path) + '.parts.json').read_text())
    assert record['schema'] == 'aijade.lossless-gzip-transport.v1'
    assert record['logicalFile'] == path.name
    whole = hashlib.sha256()
    size = 0
    paths = []
    for part in record['parts']:
        assert Path(part['path']).name == part['path']
        target = path.parent / part['path']
        digest = hashlib.sha256()
        length = 0
        with target.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
                whole.update(block)
                length += len(block)
        assert length == part['bytes'] and digest.hexdigest() == part['sha256']
        size += length
        paths.append(target)
    assert paths and size == record['bytes'] and whole.hexdigest() == record['sha256']
    return paths


@contextmanager
def gzip_text(path):
    path = Path(path)
    if path.exists():
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            yield stream
    else:
        with io.BufferedReader(ChunkReader(verified_parts(path))) as raw:
            with gzip.GzipFile(fileobj=raw, mode='rb') as compressed:
                with io.TextIOWrapper(compressed, encoding='utf-8') as stream:
                    yield stream


def split_copy(source, logical_target):
    """Copy one unchanged compressed byte stream into independently hashed chunks."""
    source, logical_target = Path(source), Path(logical_target)
    logical_target.parent.mkdir(parents=True, exist_ok=True)
    record = {'schema': 'aijade.lossless-gzip-transport.v1', 'logicalFile': logical_target.name,
              'bytes': 0, 'sha256': None, 'parts': []}
    whole = hashlib.sha256()
    with source.open('rb') as stream:
        for index, block in enumerate(iter(lambda: stream.read(CHUNK_BYTES), b'')):
            target = logical_target.with_name(logical_target.name + '.part-{:03d}'.format(index))
            digest = hashlib.sha256(block).hexdigest()
            if target.exists():
                assert target.stat().st_size == len(block)
                assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
            else:
                target.write_bytes(block)
            record['parts'].append({'path': target.name, 'bytes': len(block), 'sha256': digest})
            record['bytes'] += len(block)
            whole.update(block)
    record['sha256'] = whole.hexdigest()
    Path(str(logical_target) + '.parts.json').write_text(json.dumps(record, indent=2) + '\n')
    verified_parts(logical_target)
    return record
