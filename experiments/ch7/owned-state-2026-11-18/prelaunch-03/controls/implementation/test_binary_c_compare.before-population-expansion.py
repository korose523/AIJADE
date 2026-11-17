"""Exact C-comparison controls; project-local files, never executable inputs."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib.util
import os
import random
import sys
import tempfile
import tracemalloc
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('binary_c_compare_subject', REPO/'experiments/ch7/binary_authentication.py')
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_binary_authentication import Reader


def digest(value):
    return hashlib.sha256(value).hexdigest()


def legacy_compare(block, approved, index, offset):
    # Original Q8231 comparison body, kept as an independent differential oracle.
    position = 0
    view = memoryview(block)
    while position < len(block):
        if index >= len(approved.chunks):
            return False, index, offset
        reference = approved.chunks[index]
        length = min(len(block)-position, len(reference)-offset)
        if view[position:position+length] != memoryview(reference)[offset:offset+length]:
            return False, index, offset
        position += length
        offset += length
        if offset == len(reference):
            index += 1
            offset = 0
    return True, index, offset


class CComparisonControls(unittest.TestCase):
    def setUp(self):
        scratch = REPO/'.runtime/binary-c-compare-controls'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'synthetic-payload'

    def tracked(self, *, short=None, on_read=None, fail_after=None):
        real = os.fdopen
        readers = []
        def opened(fd, *args, **kwargs):
            item = Reader(real(fd,*args,**kwargs),short=short,on_read=on_read,fail_after=fail_after)
            readers.append(item)
            return item
        return mock.patch.object(subject.os,'fdopen',side_effect=opened),readers

    def test_every_mismatch_position_and_boundary_matches_original_compare(self):
        population = 0
        for chunk_size in (1,2,3,7,17,31):
            original = bytes((i*29+11)%256 for i in range(chunk_size*3+5))
            approved = SimpleNamespace(chunks=tuple(original[i:i+chunk_size] for i in range(0,len(original),chunk_size)))
            for prefix in range(len(original)+1):
                index,offset = divmod(prefix,chunk_size)
                if index == len(approved.chunks): offset = 0
                tail = original[prefix:]
                blocks = [tail,tail+b'extension',tail[:-1],b'']
                blocks.extend(tail[:i]+bytes([tail[i]^1])+tail[i+1:] for i in range(len(tail)))
                for block in blocks:
                    self.assertEqual(subject._compare(block,approved,index,offset),legacy_compare(block,approved,index,offset))
                    population += 1
        self.assertGreater(population,10000)

    def test_deterministic_random_chunk_and_short_read_schedules_match(self):
        rng = random.Random(20261118)
        for _ in range(500):
            original = rng.randbytes(rng.randrange(1,1025))
            sizes = []
            remaining = len(original)
            while remaining:
                size = rng.randrange(1,min(remaining,73)+1)
                sizes.append(size);remaining -= size
            chunks=[];position=0
            for size in sizes:chunks.append(original[position:position+size]);position += size
            approved=SimpleNamespace(chunks=tuple(chunks))
            changed=bytearray(original)
            if rng.randrange(2):changed[rng.randrange(len(changed))] ^= 1
            if rng.randrange(3)==0:changed.extend(rng.randbytes(rng.randrange(1,20)))
            index=offset=position=0
            while position<len(changed):
                block=bytes(changed[position:position+rng.randrange(1,130)])
                result=subject._compare(block,approved,index,offset)
                self.assertEqual(result,legacy_compare(block,approved,index,offset))
                if not result[0]:break
                _,index,offset=result;position += len(block)

    def test_actual_every_mismatch_position_reads_to_eof_and_returns_cold_digest(self):
        content=bytes((i*11+7)%256 for i in range(131))
        self.path.write_bytes(content)
        with mock.patch.object(subject,'_CHUNK_BYTES',31):
            auth=subject.BinaryAuthenticator({str(self.path):digest(content)})
            self.assertEqual(auth.sha256(self.path),digest(content))
            for position in range(len(content)):
                changed=content[:position]+bytes([content[position]^1])+content[position+1:]
                self.path.write_bytes(changed)
                patch,readers=self.tracked(short=17)
                before=auth.statistics()
                with patch:self.assertEqual(auth.sha256(self.path),digest(changed))
                after=auth.statistics()
                self.assertEqual(len(readers),1)
                self.assertEqual(readers[0].bytes,len(changed));self.assertTrue(readers[0].eof)
                self.assertEqual(after['physicalReadBytes']-before['physicalReadBytes'],len(changed))
                self.assertEqual(after['sha256Bytes']-before['sha256Bytes'],len(changed))
                self.assertEqual(after['approvedBytes'],len(content))
            self.path.write_bytes(content)
            hashes=auth.statistics()['sha256Computations']
            self.assertEqual(auth.sha256(self.path),digest(content))
            self.assertEqual(auth.statistics()['sha256Computations'],hashes)

    def test_short_reads_crossing_real_megabyte_boundaries_preserve_exact_counts(self):
        content=bytes(range(256))*(subject._CHUNK_BYTES//128)+b'end'
        self.path.write_bytes(content)
        auth=subject.BinaryAuthenticator({str(self.path):digest(content)})
        patch,_=self.tracked(short=7919)
        with patch:self.assertEqual(auth.sha256(self.path),digest(content))
        patch,readers=self.tracked(short=5003)
        with patch:self.assertEqual(auth.sha256(self.path),digest(content))
        self.assertTrue(readers[0].eof);self.assertEqual(readers[0].bytes,len(content))
        for position in (subject._CHUNK_BYTES-1,subject._CHUNK_BYTES,subject._CHUNK_BYTES+1,len(content)-1):
            changed=content[:position]+bytes([content[position]^1])+content[position+1:]
            self.path.write_bytes(changed)
            patch,readers=self.tracked(short=5003)
            with patch:self.assertEqual(auth.sha256(self.path),digest(changed))
            self.assertTrue(readers[0].eof);self.assertEqual(readers[0].bytes,len(content))

    def test_truncation_extension_empty_and_restoration_do_not_poison_approved_bytes(self):
        content=bytes(range(199));self.path.write_bytes(content)
        with mock.patch.object(subject,'_CHUNK_BYTES',31):
            auth=subject.BinaryAuthenticator({str(self.path):digest(content)})
            auth.sha256(self.path)
            for changed in (content[:31],content[:32],b'',content+b'extension',content):
                self.path.write_bytes(changed)
                patch,readers=self.tracked(short=17)
                with patch:self.assertEqual(auth.sha256(self.path),digest(changed))
                self.assertTrue(readers[0].eof);self.assertEqual(readers[0].bytes,len(changed))
                self.assertEqual(auth.statistics()['approvedBytes'],len(content))
            self.assertEqual(auth.statistics()['cacheMismatchReads'],4)
            self.assertEqual(auth.statistics()['cacheMatchReads'],1)

    def test_actual_inode_replacement_at_eof_is_refused_before_any_cache_hit(self):
        content=b'original fixture'*100;self.path.write_bytes(content)
        auth=subject.BinaryAuthenticator({str(self.path):digest(content)});auth.sha256(self.path)
        replaced=False
        def change(number):
            nonlocal replaced
            if number==2:
                replacement=self.root/'replacement';replacement.write_bytes(content);replacement.replace(self.path);replaced=True
        patch,readers=self.tracked(on_read=change)
        with patch,self.assertRaisesRegex(ValueError,'changed during'):auth.sha256(self.path)
        self.assertTrue(replaced);self.assertTrue(readers[0].eof)
        self.assertEqual(auth.statistics()['cacheMatchReads'],0)

    def test_leaf_symlink_swap_during_read_and_future_open_are_refused(self):
        content=b'original fixture'*100;self.path.write_bytes(content)
        target=self.root/'target';target.write_bytes(content)
        auth=subject.BinaryAuthenticator({str(self.path):digest(content)});auth.sha256(self.path)
        def change(number):
            if number==1:self.path.unlink();self.path.symlink_to(target)
        patch,_=self.tracked(on_read=change)
        with patch,self.assertRaisesRegex(ValueError,'changed during'):auth.sha256(self.path)
        with self.assertRaises(OSError):auth.sha256(self.path)
        self.assertEqual(auth.statistics()['cacheMatchReads'],0)

    def test_read_failure_after_mismatch_cannot_promote_changed_content(self):
        content=b'A'*300;self.path.write_bytes(content)
        with mock.patch.object(subject,'_CHUNK_BYTES',31):
            auth=subject.BinaryAuthenticator({str(self.path):digest(content)});auth.sha256(self.path)
            changed=b'B'+content[1:];self.path.write_bytes(changed)
            patch,_=self.tracked(fail_after=2)
            with patch,self.assertRaisesRegex(OSError,'controlled'):auth.sha256(self.path)
            self.assertEqual(auth.statistics()['fullFileReads'],1)
            self.assertEqual(auth.statistics()['cacheMismatchReads'],0)
            self.assertEqual(auth.statistics()['approvedBytes'],len(content))
            self.assertEqual(auth.sha256(self.path),digest(changed))
            self.path.write_bytes(content)
            self.assertEqual(auth.sha256(self.path),digest(content))

    def test_partial_reference_allocation_is_bounded_by_one_extra_chunk(self):
        chunk=subject._CHUNK_BYTES
        reference=b'a'*chunk
        approved=SimpleNamespace(chunks=(reference,reference,reference))
        # The block crosses a boundary: partial C slices must not be retained
        # between loop iterations. Existing reference/read payloads predate trace.
        block=b'a'*chunk
        tracemalloc.start()
        try:
            self.assertEqual(subject._compare(block,approved,0,1),(True,1,1))
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLessEqual(peak,chunk+4096)


if __name__=='__main__':unittest.main()
