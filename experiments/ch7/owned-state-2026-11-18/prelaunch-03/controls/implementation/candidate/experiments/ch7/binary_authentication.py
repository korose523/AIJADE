"""Exact full-file authentication with an immutable, expected-SHA-bound baseline.

Every call opens and reads the actual file to EOF. An approved baseline saves
repeated SHA work, never the file read or exact byte comparison. Stable changed
content returns its actual SHA for the caller's existing mismatch decision.
Unstable reads retain the cold guard's metadata refusal. This is not a process
verdict cache or isolation from a caller able to rewrite Python module memory.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import threading
from types import MappingProxyType
from typing import Mapping


_CHUNK_BYTES = 1024 * 1024


def _path(value):
    name = os.fspath(value)
    if not isinstance(name, str) or not name or any(c in name for c in ('\x00', '\n', '\r')):
        raise ValueError('invalid binary authentication path')
    item = Path(name)
    if not item.is_absolute() or '..' in item.parts or os.path.normpath(name) != name:
        raise ValueError('binary authentication path must be canonical and absolute')
    return name


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _identity(item):
    # Same before/after/current stability fields as the existing guard._file_sha.
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns


@dataclass(frozen=True, slots=True)
class _Approved:
    chunks: tuple[bytes, ...]
    size: int
    sha256: str


def _compare(block, approved, index, offset):
    """Compare arbitrary short-read boundaries without joining/copying baseline."""
    position = 0
    view = memoryview(block)
    while position < len(block):
        if index >= len(approved.chunks):
            return False, index, offset
        reference = approved.chunks[index]
        length = min(len(block) - position, len(reference) - offset)
        if view[position:position + length] != memoryview(reference)[offset:offset + length]:
            return False, index, offset
        position += length
        offset += length
        if offset == len(reference):
            index += 1
            offset = 0
    return True, index, offset


def _seed(approved, length):
    """The prefix already compared equal is the actual stream's exact prefix."""
    result = hashlib.sha256()
    remaining = length
    for block in approved.chunks:
        if remaining <= 0:
            break
        size = min(len(block), remaining)
        result.update(memoryview(block)[:size])
        remaining -= size
    if remaining:
        raise ValueError('invalid authenticated prefix')
    return result


class BinaryAuthenticator:
    """One immutable path/expected-SHA context; no PASS result is memoized.

    Persistent RAM is bounded by max_total_bytes and per-file max_file_bytes.
    One read chunk and temporary chunk references add bounded overhead. A file
    that cannot fit is still fully hashed in one physical pass, without cache.
    Statistics are diagnostic integer copies and never enter acceptance.
    """

    def __init__(self, expected: Mapping, max_total_bytes=192 * 1024 ** 2,
                 max_file_bytes=128 * 1024 ** 2):
        if not isinstance(expected, Mapping):
            raise TypeError('expected must be a path-to-SHA mapping')
        for limit in (max_total_bytes, max_file_bytes):
            if type(limit) is not int or limit < 0:
                raise ValueError('cache limits must be nonnegative integers')
        bindings = {}
        for name, value in expected.items():
            name = _path(name)
            if name in bindings or not _sha(value):
                raise ValueError('invalid or duplicate expected binary SHA')
            bindings[name] = value
        self.__expected = MappingProxyType(bindings)
        self.__approved = {}
        self.__max_total = max_total_bytes
        self.__max_file = max_file_bytes
        self.__mutex = threading.RLock()
        self.__stats = dict(calls=0, openedFiles=0, fullFileReads=0, physicalReadBytes=0,
                            sha256Computations=0, sha256Bytes=0, equalBytesAuthenticated=0,
                            cacheMatchReads=0, cacheMismatchReads=0, capFallbackReads=0,
                            unapprovedDigestReads=0, approvedFiles=0, approvedBytes=0,
                            failures=0)

    def statistics(self):
        with self.__mutex:
            return dict(self.__stats)

    def bindings(self):
        """Detached context proof for the caller's exact policy binding check."""
        with self.__mutex:
            return dict(self.__expected)

    def sha256(self, path):
        with self.__mutex:
            self.__stats['calls'] += 1
            try:
                return self.__read(_path(path))
            except BaseException:
                self.__stats['failures'] += 1
                raise

    def __read(self, path):
        if path not in self.__expected:
            raise ValueError('unbound binary authentication path')
        expected = self.__expected[path]
        approved = self.__approved.get(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        self.__stats['openedFiles'] += 1
        chunks, pending, stored, index, offset, count = [], bytearray(), 0, 0, 0, 0
        mismatch = False
        hasher = None if approved is not None else hashlib.sha256()
        if hasher is not None:
            self.__stats['sha256Computations'] += 1
        try:
            stream = os.fdopen(descriptor, 'rb')
        except BaseException:
            # fdopen may reject a directory before our regular-file check.
            # It may already have closed the descriptor during initialization.
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        with stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('not a regular executable')
            remaining_cap = self.__max_total - self.__stats['approvedBytes']
            cache_limit = min(self.__max_file, remaining_cap)
            candidate = (approved is None and self.__max_total > 0 and self.__max_file > 0
                         and before.st_size <= cache_limit)
            fallback = approved is None and not candidate
            while True:
                block = stream.read(_CHUNK_BYTES)
                if not block:
                    break
                self.__stats['physicalReadBytes'] += len(block)
                if approved is not None and not mismatch:
                    equal, next_index, next_offset = _compare(block, approved, index, offset)
                    if equal:
                        index, offset = next_index, next_offset
                        self.__stats['equalBytesAuthenticated'] += len(block)
                    else:
                        mismatch = True
                        hasher = _seed(approved, count)
                        self.__stats['sha256Computations'] += 1
                        self.__stats['sha256Bytes'] += count
                if hasher is not None:
                    hasher.update(block)
                    self.__stats['sha256Bytes'] += len(block)
                count += len(block)
                if candidate:
                    if stored + len(block) <= cache_limit:
                        # Coalesce even arbitrarily short reads: the approved
                        # tuple has at most ceil(size / CHUNK) entries. Its RAM
                        # bound cannot be defeated by one-byte read boundaries.
                        if pending:
                            take = min(_CHUNK_BYTES - len(pending), len(block))
                            pending.extend(memoryview(block)[:take])
                            if len(pending) == _CHUNK_BYTES:
                                chunks.append(bytes(pending))
                                pending.clear()
                            pending.extend(memoryview(block)[take:])
                        elif len(block) == _CHUNK_BYTES:
                            chunks.append(block)
                        else:
                            pending.extend(block)
                        stored += len(block)
                    else:
                        chunks.clear()
                        pending.clear()
                        stored = 0
                        candidate = False
                        fallback = True
            after = os.fstat(stream.fileno())
        current = os.stat(path, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(current):
            raise ValueError('executable changed during observation')
        self.__stats['fullFileReads'] += 1
        if fallback:
            self.__stats['capFallbackReads'] += 1
        if approved is not None:
            if not mismatch and count == approved.size:
                self.__stats['cacheMatchReads'] += 1
                return approved.sha256
            if not mismatch:
                # EOF before the immutable approved baseline is a stable truncation.
                hasher = _seed(approved, count)
                self.__stats['sha256Computations'] += 1
                self.__stats['sha256Bytes'] += count
            self.__stats['cacheMismatchReads'] += 1
            return hasher.hexdigest()
        actual = hasher.hexdigest()
        if actual != expected:
            self.__stats['unapprovedDigestReads'] += 1
        elif candidate:
            if pending:
                chunks.append(bytes(pending))
            self.__approved[path] = _Approved(tuple(chunks), count, actual)
            self.__stats['approvedFiles'] += 1
            self.__stats['approvedBytes'] += count
        return actual
