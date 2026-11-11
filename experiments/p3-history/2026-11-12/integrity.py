"""Exact archive membership and byte binding; excludes only the root manifest."""
import hashlib
def digest(path):return hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
def verify_hashes(root,manifest):
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'manifest.json' and '__pycache__' not in p.parts}
    assert actual==set(manifest['files']),'archive-membership'
    for relative,row in manifest['files'].items():
        p=root/relative
        assert p.stat().st_size==row['bytes'] and digest(p)==row['sha256'],'archive-byte-hash: '+relative
