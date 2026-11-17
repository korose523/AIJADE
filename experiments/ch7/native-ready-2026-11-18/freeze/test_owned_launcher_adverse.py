"""E5 parent-launcher adverse controls, all child/identity/signal calls mocked."""
import json
from pathlib import Path
import unittest

import test_nested_launcher as inherited
Fixture=inherited.Fixture
parent=inherited.parent
sha=inherited.sha

OWNED='experiments/ch7/newowned_guard_cursor.py'
CLONE='experiments/ch7/full_state_clone_cursor.py'


class OwnedLauncherAdverseControls(unittest.TestCase):
    rebind_policy=inherited.ParentControls.rebind_policy
    rebind_source_fixture=inherited.ParentControls.rebind_source_fixture

    def rebind_protocol(self,f,change):
        value=json.loads(f.protocol_path.read_bytes());change(value)
        f.protocol_path.write_text(json.dumps(value));f.data['protocolSha256']=sha(f.protocol_path)
        self.rebind_source_fixture(f,str(f.protocol_path.relative_to(f.repo)))

    def test_47_eighteenth_owned_observer_cannot_be_omitted(self):
        f=Fixture(self);self.assertEqual(len(parent.OBSERVERS),21)
        f.data['observerSources'].pop(OWNED);f.freeze()
        with self.assertRaisesRegex(ValueError,'closure'):f.run()
        f.popen.assert_not_called()

    def test_48_legacy_clone_remains_a_required_observer_dependency(self):
        f=Fixture(self);f.data['observerSources'].pop(CLONE);f.freeze()
        with self.assertRaisesRegex(ValueError,'closure'):f.run()
        f.popen.assert_not_called()

    def test_49_equal_population_wrong_eighteenth_observer_is_refused(self):
        f=Fixture(self);value=f.data['observerSources'].pop(OWNED)
        f.data['observerSources']['tests/shell/source-00.py']=value;f.freeze()
        self.assertEqual(len(f.data['observerSources']),21)
        with self.assertRaisesRegex(ValueError,'closure'):f.run()
        f.popen.assert_not_called()

    def test_50_passport_mode_must_match_owned_policy_and_protocol(self):
        f=Fixture(self);f.data['onlineReplayMode']='full-state-c-clone-exact-prefix-v1';f.freeze()
        with self.assertRaisesRegex(ValueError,'owned-state initialization mode'):f.run()
        f.popen.assert_not_called()

    def test_51_rebound_protocol_cursor_pin_must_match_actual_owned_source(self):
        f=Fixture(self);self.rebind_protocol(f,lambda p:p.update(onlineReplaySourceSha256='f'*64))
        with self.assertRaisesRegex(ValueError,'owned-state source pin'):f.run()
        f.popen.assert_not_called()

    def test_52_passport_cursor_pin_must_match_policy_protocol_and_source(self):
        f=Fixture(self);f.data['onlineReplaySourceSha256']='f'*64;f.freeze()
        with self.assertRaisesRegex(ValueError,'owned-state source pin'):f.run()
        f.popen.assert_not_called()

    def test_53_legacy_clone_source_pin_cannot_replace_owned_source(self):
        f=Fixture(self)
        self.rebind_policy(f,lambda p:p.update(onlineReplaySourceSha256=f.data['sourceFiles'][CLONE]))
        with self.assertRaisesRegex(ValueError,'owned-state source pin'):f.run()
        f.popen.assert_not_called()

    def test_54_coherent_old_mode_and_initialization_cannot_be_e5(self):
        f=Fixture(self)
        change=lambda p:p.update(onlineReplayMode='full-state-c-clone-exact-prefix-v1',
            onlineReplayInitializationMode='paired-source-verified-journal-prefix-v1')
        self.rebind_policy(f,change);self.rebind_protocol(f,change);change(f.data);f.freeze()
        with self.assertRaisesRegex(ValueError,'owned-state initialization mode'):f.run()
        f.popen.assert_not_called()

    def test_55_canonical_but_different_output_cannot_replace_fixed_attempt(self):
        f=Fixture(self);f.data['output']=str(f.root/'another-attempt-output');f.freeze()
        with self.assertRaisesRegex(ValueError,'owned-state engineering output'):f.run()
        f.popen.assert_not_called()

    def test_56_repeated_source_proof_cannot_keep_thirty_command_population(self):
        f=Fixture(self);proofs=[x for x in f.data['preflightCommands'] if x['arguments'][0]=='show']
        proofs[-1].update(arguments=list(proofs[0]['arguments']),stdoutSha256=proofs[0]['stdoutSha256']);f.freeze()
        self.assertEqual(len(f.data['preflightCommands']),30)
        with self.assertRaisesRegex(ValueError,'distinct actual source proof'):f.run()
        f.popen.assert_not_called()

    def test_57_source_proof_digest_must_bind_actual_source_bytes(self):
        f=Fixture(self);next(x for x in f.data['preflightCommands'] if x['arguments'][0]=='show')['stdoutSha256']='f'*64;f.freeze()
        with self.assertRaisesRegex(ValueError,'actual source proof'):f.run()
        f.popen.assert_not_called()

    def test_58_actual_owned_source_must_appear_in_twenty_eight_proofs(self):
        f=Fixture(self);name='tests/shell/extra-proof.py';path=f.repo/name;path.write_bytes(b'ACTUAL EXTRA MOCK SOURCE\n')
        f.data['sourceFiles'][name]=sha(path);f.frozen_blobs[name]=path.read_bytes()
        proof=next(x for x in f.data['preflightCommands'] if x['arguments']==['show','{SOURCE}:'+OWNED])
        proof.update(arguments=['show','{SOURCE}:'+name],stdoutSha256=sha(path));f.freeze()
        with self.assertRaisesRegex(ValueError,'owned-state source must be proved'):f.run()
        f.popen.assert_not_called()

    def test_59_passport_initialization_field_cannot_be_omitted(self):
        f=Fixture(self);f.data.pop('onlineReplayInitializationMode');f.freeze()
        with self.assertRaisesRegex(ValueError,'owned-state initialization mode'):f.run()
        f.popen.assert_not_called()

    def test_60_rebound_protocol_old_initialization_cannot_dispatch(self):
        f=Fixture(self)
        self.rebind_protocol(f,lambda p:p.update(onlineReplayInitializationMode='paired-source-verified-journal-prefix-v1'))
        with self.assertRaisesRegex(ValueError,'owned-state initialization mode'):f.run()
        f.popen.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
