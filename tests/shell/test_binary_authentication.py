"""Portable disposable-file controls; no observer, SDK or live service is used."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('binary_authentication_tested', REPO / 'experiments/ch7/binary_authentication.py')
auth_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = auth_module
SPEC.loader.exec_module(auth_module)
BinaryAuthenticator = auth_module.BinaryAuthenticator


def digest(value):
    return hashlib.sha256(value).hexdigest()


class Reader:
    def __init__(self, stream, *, short=None, fail_after=None, on_read=None):
        self.stream, self.short, self.fail_after, self.on_read = stream, short, fail_after, on_read
        self.reads, self.bytes, self.eof = 0, 0, False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def fileno(self):
        return self.stream.fileno()

    def read(self, size):
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise OSError('controlled read failure')
        result = self.stream.read(min(size, self.short) if self.short else size)
        self.reads += 1
        self.bytes += len(result)
        if not result:
            self.eof = True
        if self.on_read:
            self.on_read(self.reads)
        return result


class BinaryAuthenticationTests(unittest.TestCase):
    def setUp(self):
        # The local checkout is under BASE/APFS. CI uses its own checkout, never
        # a hardcoded /Volumes path or the system /tmp directory.
        self.temp_parent = REPO / '.runtime/test-tmp'
        self.temp_parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='binary-auth-', dir=self.temp_parent)
        self.root = Path(self.temp.name)
        self.file = self.root / 'binary'
        self.content = b'A' * (auth_module._CHUNK_BYTES + 31) + b'end'
        self.file.write_bytes(self.content)

    def tearDown(self):
        self.temp.cleanup()

    def auth(self, **kwargs):
        return BinaryAuthenticator({str(self.file): digest(self.content)}, **kwargs)

    def tracked(self, *, short=None, fail_after=None, on_read=None):
        real = os.fdopen
        readers = []

        def opened(fd, *args, **kwargs):
            reader = Reader(real(fd, *args, **kwargs), short=short, fail_after=fail_after, on_read=on_read)
            readers.append(reader)
            return reader
        return mock.patch.object(auth_module.os, 'fdopen', side_effect=opened), readers

    def assert_single_full_read(self, readers, data):
        self.assertEqual(len(readers), 1)
        self.assertEqual(readers[0].bytes, len(data))
        self.assertTrue(readers[0].eof)

    def test_initial_sha_then_hit_still_opens_and_reads_all_bytes(self):
        auth = self.auth()
        self.assertEqual(auth.sha256(self.file), digest(self.content))
        patch, readers = self.tracked()
        with patch:
            self.assertEqual(auth.sha256(self.file), digest(self.content))
        self.assert_single_full_read(readers, self.content)
        self.assertEqual(auth.statistics()['sha256Computations'], 1)
        self.assertEqual(auth.statistics()['cacheMatchReads'], 1)
        self.assertEqual(auth.statistics()['physicalReadBytes'], len(self.content) * 2)

    def test_same_length_changed_bytes_and_restored_mtime_return_actual_sha(self):
        auth = self.auth(); auth.sha256(self.file)
        original = self.file.stat()
        changed = self.content[:17] + b'Z' + self.content[18:]
        self.file.write_bytes(changed)
        os.utime(self.file, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(self.file.stat().st_size, original.st_size)
        self.assertEqual(self.file.stat().st_mtime_ns, original.st_mtime_ns)
        patch, readers = self.tracked()
        with patch:
            self.assertEqual(auth.sha256(self.file), digest(changed))
        self.assert_single_full_read(readers, changed)
        self.assertEqual(auth.statistics()['cacheMismatchReads'], 1)

    def test_late_chunk_change_seeds_exact_prefix_without_rereading_file(self):
        auth = self.auth(); auth.sha256(self.file)
        changed = self.content[:-1] + b'!'
        self.file.write_bytes(changed)
        patch, readers = self.tracked()
        with patch:
            self.assertEqual(auth.sha256(self.file), digest(changed))
        self.assert_single_full_read(readers, changed)

    def test_stable_truncation_returns_actual_digest_including_empty(self):
        auth = self.auth(); auth.sha256(self.file)
        for changed in (self.content[:19], b''):
            with self.subTest(size=len(changed)):
                self.file.write_bytes(changed)
                patch, readers = self.tracked()
                with patch:
                    self.assertEqual(auth.sha256(self.file), digest(changed))
                self.assert_single_full_read(readers, changed)

    def test_stable_growth_returns_actual_digest_and_never_approves_it(self):
        auth = self.auth(); auth.sha256(self.file)
        changed = self.content + b'growth' * 100
        self.file.write_bytes(changed)
        for _ in range(2):
            patch, readers = self.tracked()
            with patch:
                self.assertEqual(auth.sha256(self.file), digest(changed))
            self.assert_single_full_read(readers, changed)
        self.assertEqual(auth.statistics()['approvedBytes'], len(self.content))
        self.assertEqual(auth.statistics()['cacheMismatchReads'], 2)
        self.file.write_bytes(self.content)
        before = auth.statistics()['sha256Computations']
        self.assertEqual(auth.sha256(self.file), digest(self.content))
        self.assertEqual(auth.statistics()['sha256Computations'], before)

    def test_inode_replacement_with_identical_bytes_reads_then_matches(self):
        auth = self.auth(); auth.sha256(self.file)
        old_inode = self.file.stat().st_ino
        replacement = self.root / 'replacement'; replacement.write_bytes(self.content); replacement.replace(self.file)
        self.assertNotEqual(self.file.stat().st_ino, old_inode)
        patch, readers = self.tracked()
        with patch:
            self.assertEqual(auth.sha256(self.file), digest(self.content))
        self.assert_single_full_read(readers, self.content)

    def test_inode_replacement_with_changed_bytes_returns_actual(self):
        auth = self.auth(); auth.sha256(self.file)
        changed = b'coherent new stable file'
        replacement = self.root / 'replacement'; replacement.write_bytes(changed); replacement.replace(self.file)
        self.assertEqual(auth.sha256(self.file), digest(changed))
        self.assertEqual(auth.statistics()['approvedBytes'], len(self.content))

    def test_expected_mapping_is_copied_and_new_context_has_new_expected(self):
        binding = {str(self.file): digest(self.content)}
        auth = BinaryAuthenticator(binding)
        changed = b'new content'; self.file.write_bytes(changed)
        binding[str(self.file)] = digest(changed)
        self.assertEqual(auth.sha256(self.file), digest(changed))
        self.assertEqual(auth.statistics()['approvedFiles'], 0)
        new = BinaryAuthenticator(binding)
        self.assertEqual(new.sha256(self.file), digest(changed))
        self.assertEqual(new.statistics()['approvedFiles'], 1)

    def test_cross_path_is_not_authorized_by_matching_content(self):
        auth = self.auth(); auth.sha256(self.file)
        second = self.root / 'second'; second.write_bytes(self.content)
        with mock.patch.object(auth_module.os, 'open') as opened:
            with self.assertRaisesRegex(ValueError, 'unbound'):
                auth.sha256(second)
            opened.assert_not_called()

    def test_two_bound_paths_have_independent_baselines(self):
        second = self.root / 'second'; second.write_bytes(self.content)
        auth = BinaryAuthenticator({str(self.file): digest(self.content), str(second): digest(self.content)})
        auth.sha256(self.file); auth.sha256(second)
        second.write_bytes(b'changed second')
        self.assertEqual(auth.sha256(second), digest(b'changed second'))
        self.assertEqual(auth.sha256(self.file), digest(self.content))

    def test_unapproved_first_digest_is_never_a_future_cache_hit(self):
        auth = BinaryAuthenticator({str(self.file): '0' * 64})
        for _ in range(2):
            self.assertEqual(auth.sha256(self.file), digest(self.content))
        self.assertEqual(auth.statistics()['approvedFiles'], 0)
        self.assertEqual(auth.statistics()['sha256Computations'], 2)

    def test_stats_are_typed_detached_and_expose_no_baseline_bytes(self):
        auth = self.auth(); result = auth.sha256(self.file)
        self.assertIsInstance(result, str)
        report = auth.statistics()
        self.assertTrue(all(type(value) is int for value in report.values()))
        report['approvedBytes'] = -1
        self.assertEqual(auth.statistics()['approvedBytes'], len(self.content))
        self.assertEqual(auth.sha256(self.file), digest(self.content))

    def test_bindings_are_detached_and_cannot_change_expected_context(self):
        auth = self.auth()
        mapping = auth.bindings()
        self.assertEqual(mapping, {str(self.file): digest(self.content)})
        mapping[str(self.file)] = '0' * 64
        mapping[str(self.root / 'unbound')] = digest(self.content)
        self.assertEqual(auth.bindings(), {str(self.file): digest(self.content)})
        self.assertEqual(auth.sha256(self.file), digest(self.content))

    def test_per_file_cap_falls_back_without_caching_or_skipping_reads(self):
        auth = self.auth(max_file_bytes=31)
        for _ in range(2):
            patch, readers = self.tracked()
            with patch:
                self.assertEqual(auth.sha256(self.file), digest(self.content))
            self.assert_single_full_read(readers, self.content)
        self.assertEqual(auth.statistics()['approvedBytes'], 0)
        self.assertEqual(auth.statistics()['capFallbackReads'], 2)

    def test_total_cap_does_not_evict_or_allow_unbounded_new_baseline(self):
        second = self.root / 'second'; second.write_bytes(self.content)
        auth = BinaryAuthenticator({str(self.file): digest(self.content), str(second): digest(self.content)},
                                   max_total_bytes=len(self.content))
        auth.sha256(self.file); auth.sha256(second); auth.sha256(second)
        self.assertEqual(auth.statistics()['approvedFiles'], 1)
        self.assertEqual(auth.statistics()['approvedBytes'], len(self.content))
        self.assertEqual(auth.statistics()['capFallbackReads'], 2)

    def test_zero_caps_still_hash_full_actual_file(self):
        for kwargs in ({'max_total_bytes': 0}, {'max_file_bytes': 0}):
            with self.subTest(kwargs=kwargs):
                auth = self.auth(**kwargs)
                self.assertEqual(auth.sha256(self.file), digest(self.content))
                self.assertEqual(auth.statistics()['approvedFiles'], 0)

    def test_arbitrary_short_read_boundaries_compare_exactly(self):
        auth = self.auth()
        patch, _ = self.tracked(short=7919)
        with patch:
            auth.sha256(self.file)
        patch, readers = self.tracked(short=1741)
        with patch:
            self.assertEqual(auth.sha256(self.file), digest(self.content))
        self.assert_single_full_read(readers, self.content)
        self.assertEqual(auth.statistics()['sha256Computations'], 1)

    def test_short_reads_then_cross_boundary_mismatch_match_cold_sha(self):
        auth = self.auth()
        patch, _ = self.tracked(short=4091)
        with patch:
            auth.sha256(self.file)
        changed = self.content[:8180] + b'Z' + self.content[8181:]
        self.file.write_bytes(changed)
        patch, readers = self.tracked(short=5003)
        with patch:
            self.assertEqual(auth.sha256(self.file), digest(changed))
        self.assert_single_full_read(readers, changed)

    def test_one_byte_reads_cannot_inflate_baseline_chunk_population(self):
        content = b'A' * 2049
        self.file.write_bytes(content)
        auth = BinaryAuthenticator({str(self.file): digest(content)})
        patch, readers = self.tracked(short=1)
        with patch:
            self.assertEqual(auth.sha256(self.file), digest(content))
        self.assert_single_full_read(readers, content)
        baseline = auth._BinaryAuthenticator__approved[str(self.file)]
        self.assertIs(type(baseline.chunks), tuple)
        self.assertEqual(len(baseline.chunks), 1)
        self.assertTrue(all(type(chunk) is bytes for chunk in baseline.chunks))
        self.assertTrue(memoryview(baseline.chunks[0]).readonly)
        with self.assertRaises((AttributeError, TypeError)):
            baseline.size = -1
        self.assertEqual(auth.sha256(self.file), digest(content))

    def test_initial_read_failure_propagates_without_partial_approval(self):
        auth = self.auth()
        patch, _ = self.tracked(fail_after=1)
        with patch, self.assertRaisesRegex(OSError, 'controlled'):
            auth.sha256(self.file)
        self.assertEqual(auth.statistics()['approvedFiles'], 0)
        self.assertEqual(auth.statistics()['fullFileReads'], 0)
        self.assertEqual(auth.sha256(self.file), digest(self.content))

    def test_hit_read_failure_never_reuses_last_pass(self):
        auth = self.auth(); auth.sha256(self.file)
        patch, _ = self.tracked(fail_after=1)
        with patch, self.assertRaisesRegex(OSError, 'controlled'):
            auth.sha256(self.file)
        self.assertEqual(auth.statistics()['cacheMatchReads'], 0)
        self.assertEqual(auth.statistics()['failures'], 1)

    def test_unstable_metadata_during_read_refuses_like_original_guard(self):
        auth = self.auth(); auth.sha256(self.file)
        before = self.file.stat()

        def changed(number):
            if number == 1:
                os.utime(self.file, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000))
        patch, _ = self.tracked(on_read=changed)
        with patch, self.assertRaisesRegex(ValueError, 'changed during'):
            auth.sha256(self.file)
        self.assertEqual(auth.statistics()['cacheMatchReads'], 0)

    def test_growth_beyond_lied_about_stat_size_drops_candidate_at_cap(self):
        auth = self.auth(max_file_bytes=32)
        fstat, pathstat = os.fstat, os.stat

        def small(item):
            return SimpleNamespace(st_dev=item.st_dev, st_ino=item.st_ino, st_size=1,
                                   st_mtime_ns=item.st_mtime_ns, st_mode=item.st_mode)
        with mock.patch.object(auth_module.os, 'fstat', side_effect=lambda fd: small(fstat(fd))), \
                mock.patch.object(auth_module.os, 'stat', side_effect=lambda *a, **k: small(pathstat(*a, **k))):
            self.assertEqual(auth.sha256(self.file), digest(self.content))
        self.assertEqual(auth.statistics()['approvedBytes'], 0)
        self.assertEqual(auth.statistics()['capFallbackReads'], 1)

    def test_symlink_leaf_is_refused(self):
        link = self.root / 'link'; link.symlink_to(self.file)
        auth = BinaryAuthenticator({str(link): digest(self.content)})
        with self.assertRaises(OSError):
            auth.sha256(link)

    def test_nonregular_directory_is_refused(self):
        auth = BinaryAuthenticator({str(self.root): digest(b'')})
        # Both fdopen's IsADirectoryError and the explicit regular-file check
        # are refusals under the original guard's exception semantics.
        with self.assertRaises((ValueError, OSError)):
            auth.sha256(self.root)

    def test_invalid_paths_sha_and_limit_types_refuse(self):
        for name in ['relative', str(self.root / '..' / 'binary'), str(self.file) + '\n']:
            with self.subTest(path=name), self.assertRaises(ValueError):
                BinaryAuthenticator({name: digest(self.content)})
        for value in ['X' * 64, '0', None]:
            with self.subTest(sha=value), self.assertRaises(ValueError):
                BinaryAuthenticator({str(self.file): value})
        for value in [True, 1.5, -1]:
            with self.subTest(limit=value), self.assertRaises(ValueError):
                self.auth(max_total_bytes=value)


if __name__ == '__main__':
    unittest.main()
