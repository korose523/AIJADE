"""Publication transport must preserve the original gzip bytes and reject corruption."""
import gzip
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import transport
import analyze


class TransportChecks(unittest.TestCase):
    def test_chunked_read_matches_original_bytes_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root/'original.gz'
            encoded = gzip.compress(b'{"row":1}\n{"row":2}\n', mtime=0)
            original.write_bytes(encoded)
            logical = root/'public.jsonl.gz'
            with patch.object(transport, 'CHUNK_BYTES', 7):
                record = transport.split_copy(original, logical)
            self.assertFalse(logical.exists())
            self.assertEqual(record['sha256'], hashlib.sha256(encoded).hexdigest())
            self.assertEqual(analyze.sha(logical), record['sha256'])
            restored = b''.join(p.read_bytes() for p in transport.verified_parts(logical))
            self.assertEqual(restored, encoded)
            with transport.gzip_text(logical) as stream:
                self.assertEqual(list(stream), ['{"row":1}\n', '{"row":2}\n'])
            self.assertEqual(original.read_bytes(), encoded)

    def test_corrupt_chunk_rejects_before_exposing_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root/'original.gz'
            original.write_bytes(gzip.compress(b'{"row":1}\n', mtime=0))
            logical = root/'public.jsonl.gz'
            with patch.object(transport, 'CHUNK_BYTES', 7):
                record = transport.split_copy(original, logical)
            first = root/record['parts'][0]['path']
            first.write_bytes(b'x' + first.read_bytes()[1:])
            with self.assertRaises(AssertionError):
                with transport.gzip_text(logical) as stream:
                    next(stream)


if __name__ == '__main__':
    unittest.main()
