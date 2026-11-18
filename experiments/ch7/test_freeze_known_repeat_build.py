"""Build-freeze controls using synthetic Git and binary bytes only."""

import errno
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from finite_construction_binding import decode
from finite_runtime import validate_build
from freeze_known_repeat_build import prepare_build_publication
from known_repeat_acceptance import BUILD, DECISION, DECISION_SCHEMA, PREFIX, SOURCE
from launch_known_repeats import PLAN_SCHEMA, digest, encode


class BuildPublicationControls(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='offline-building-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Offline Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.reply = self.root / 'fixture-reply.txt'
        self.reply.write_text('OFFLINE_SYNTHETIC reply bytes')
        self.qualification = self.root / 'fixture-plan.txt'
        self.qualification.write_text('OFFLINE_SYNTHETIC qualification plan bytes')
        self.plan = PREFIX + 'fixture-execution-plan.json'
        self.write(SOURCE, b'# OFFLINE_SYNTHETIC marker only\n')
        self.write(self.plan, encode({
            'schema': PLAN_SCHEMA, 'purpose': 'qualification_only', 'repeats': 2,
            'conditionSlotsPerRepeat': 20, 'databasePort': 15432,
            'toolsSha256': {name: 'a' * 64 for name in ('python', 'docker', 'dotnet')},
            'watchdog': dict(blockWallSeconds=60, rendererTimeoutSeconds=30, sustainedResourceSeconds=10,
                             parentAllowanceSeconds=30, shutdownGraceSeconds=10,
                             maxOwnedRssBytes=None, minAvailableBytes=None, maxSwapIncreaseBytes=None),
        }))
        self.decision = dict(schema=DECISION_SCHEMA, status='SUPERVISOR_REPLY_CONFIRMED',
                             executionPlanPath=self.plan, executionPlanSha256=digest((self.repo / self.plan).read_bytes()),
                             qualificationPlanSha256=digest(self.qualification.read_bytes()),
                             replySha256=digest(self.reply.read_bytes()))
        self.q = self.commit_q()
        self.assembly = self.root / 'prebuilt/Aijade.Tests.dll'
        self.assembly.parent.mkdir()
        self.assembly.write_bytes(b'OFFLINE_SYNTHETIC Aijade.Tests.dll 0.1.0+' + self.q.encode())
        self.assembly.with_suffix('.deps.json').write_text('{}')
        self.assembly.with_suffix('.runtimeconfig.json').write_text('{}')
        (self.assembly.parent / 'lib').mkdir()
        (self.assembly.parent / 'lib/Reference.dll').write_bytes(b'OFFLINE_SYNTHETIC dependency')

    def write(self, relative, data):
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True).strip()

    def commit_q(self):
        self.write(DECISION, encode(self.decision))
        self.git('add', '.')
        self.git('commit', '-qm', 'OFFLINE_SYNTHETIC implementation')
        return self.git('rev-parse', 'HEAD')

    def prepare(self):
        return prepare_build_publication(self.repo, self.q, self.assembly, self.reply, self.qualification)

    def test_exact_build_bytes_are_frozen_and_canonical(self):
        published = self.prepare()
        self.assertEqual(published, self.repo / BUILD)
        self.assertEqual(set(decode(published.read_bytes())['files']),
                         {'Aijade.Tests.dll', 'Aijade.Tests.deps.json', 'Aijade.Tests.runtimeconfig.json', 'lib/Reference.dll'})
        self.git('add', BUILD)
        self.git('commit', '-qm', 'OFFLINE_SYNTHETIC build freeze')
        b = self.git('rev-parse', 'HEAD')
        validate_build(self.assembly, published, self.q, self.repo, b, BUILD)
        with self.assertRaisesRegex(ValueError, 'clean approved Q'):
            self.prepare()
        (self.assembly.parent / 'lib/Reference.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'binary/dependency bytes changed'):
            validate_build(self.assembly, published, self.q, self.repo, b, BUILD)

    def test_pending_decision_cannot_publish(self):
        self.decision['status'] = 'PENDING_REPLY'
        self.q = self.commit_q()
        with self.assertRaisesRegex(ValueError, 'reply has not been confirmed'):
            self.prepare()
        self.assertFalse((self.repo / BUILD).exists())

    def test_unmatched_original_reply_cannot_publish(self):
        self.reply.write_text('OFFLINE_SYNTHETIC replaced reply')
        with self.assertRaisesRegex(ValueError, 'private original differs'):
            self.prepare()
        self.assertFalse((self.repo / BUILD).exists())

    def test_wrong_revision_or_link_cannot_freeze(self):
        original = self.assembly.read_bytes()
        self.assembly.write_bytes(b'OFFLINE_SYNTHETIC unrelated build')
        with self.assertRaisesRegex(ValueError, 'approved revision'):
            self.prepare()
        self.assembly.write_bytes(original)
        (self.assembly.parent / 'future.dll').symlink_to(self.reply)
        with self.assertRaisesRegex(ValueError, 'linked or special'):
            self.prepare()
        self.assertFalse((self.repo / BUILD).exists())

    def test_unsupported_exclusive_publication_leaves_no_canonical_B(self):
        with patch('freeze_known_repeat_build.os.link', side_effect=OSError(errno.ENOTSUP, 'no hardlinks')):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertFalse((self.repo / BUILD).exists())
        self.assertTrue((self.repo / BUILD).with_suffix('.json.pending').is_file())

    def test_dirty_source_cannot_publish(self):
        self.write('new.txt', b'OFFLINE_SYNTHETIC diff')
        with self.assertRaisesRegex(ValueError, 'clean approved Q'):
            self.prepare()
        self.assertFalse((self.repo / BUILD).exists())


if __name__ == '__main__':
    unittest.main()
