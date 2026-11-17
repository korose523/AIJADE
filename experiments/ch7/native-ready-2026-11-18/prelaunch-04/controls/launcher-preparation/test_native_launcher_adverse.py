"""Native E6 parent boundary controls: fake files, no artifact execution."""
import copy
import json
import os
import unittest
from unittest import mock
import test_nested_launcher as inherited
import test_owned_launcher_adverse as owned

Fixture=inherited.Fixture
parent=inherited.parent
sha=inherited.sha


class NativeLauncherControls(unittest.TestCase):
    rebind_policy=inherited.ParentControls.rebind_policy
    rebind_source_fixture=inherited.ParentControls.rebind_source_fixture
    rebind_protocol=owned.OwnedLauncherAdverseControls.rebind_protocol

    def bind_leaf(self,f,key,change):
        value=copy.deepcopy(f.data[key]);change(value)
        self.rebind_policy(f,lambda policy:policy.update({key:copy.deepcopy(value)}))
        self.rebind_protocol(f,lambda protocol:protocol.update({key:copy.deepcopy(value)}))
        f.data[key]=copy.deepcopy(value);f.freeze()

    def test_61_missing_native_mode_in_passport_never_spawns(self):
        f=Fixture(self);f.data.pop('lifecycleExecMode');f.freeze()
        with self.assertRaisesRegex(ValueError,'three-way native exec mode'):f.run()
        f.popen.assert_not_called()

    def test_62_legacy_mode_coherently_rebound_in_all_three_is_not_native(self):
        f=Fixture(self);self.rebind_policy(f,lambda policy:policy.update(lifecycleExecMode='legacy-python-ready'))
        self.rebind_protocol(f,lambda protocol:protocol.update(lifecycleExecMode='legacy-python-ready'))
        f.data['lifecycleExecMode']='legacy-python-ready';f.freeze()
        with self.assertRaisesRegex(ValueError,'three-way native exec mode'):f.run()
        f.popen.assert_not_called()

    def test_63_closed_native_leaf_rejects_extra_witness_field(self):
        f=Fixture(self);self.bind_leaf(f,'nativeExec',lambda value:value.update(cachedPass=True))
        with self.assertRaisesRegex(ValueError,'closed three-way native'):f.run()
        f.popen.assert_not_called()

    def test_64_missing_native_binary_pin_cannot_fall_back(self):
        f=Fixture(self);self.bind_leaf(f,'nativeExec',lambda value:value.pop('binarySha256'))
        with self.assertRaisesRegex(ValueError,'closed three-way native'):f.run()
        f.popen.assert_not_called()

    def test_65_native_source_pin_must_name_actual_colocated_c_source(self):
        f=Fixture(self);self.bind_leaf(f,'nativeExec',lambda value:value.update(sourcePath=str(f.repo/'experiments/ch7/lifecycle_exec.py')))
        with self.assertRaisesRegex(ValueError,'native C source pin/path'):f.run()
        f.popen.assert_not_called()

    def test_66_native_adapter_pin_cannot_name_legacy_registry(self):
        f=Fixture(self);self.bind_leaf(f,'nativeExec',lambda value:value.update(adapterSourceSha256=f.data['sourceFiles']['experiments/ch7/process_lifecycle.py']))
        with self.assertRaisesRegex(ValueError,'native adapter source pin'):f.run()
        f.popen.assert_not_called()

    def test_67_native_binary_content_change_refuses_without_executing_it(self):
        f=Fixture(self);f.exec_shim.write_bytes(b'CHANGED NATIVE IMAGE')
        with self.assertRaisesRegex(ValueError,'native binary fixed SHA'):f.run()
        f.popen.assert_not_called()

    def test_68_native_binary_mode_must_be_exact0755(self):
        f=Fixture(self);f.exec_shim.chmod(0o644)
        with self.assertRaisesRegex(ValueError,'exact0755'):f.run()
        f.popen.assert_not_called()

    def test_69_native_binary_hardlink_is_refused(self):
        f=Fixture(self);os.link(f.exec_shim,f.root/'hardlinked-image')
        with self.assertRaisesRegex(ValueError,'owner/link'):f.run()
        f.popen.assert_not_called()

    def test_70_native_binary_symlink_is_refused(self):
        f=Fixture(self);link=f.root/'linked-image';link.symlink_to(f.exec_shim)
        self.bind_leaf(f,'nativeExec',lambda value:value.update(binaryPath=str(link)))
        with self.assertRaisesRegex(ValueError,'noncanonical|symlink'):f.run()
        f.popen.assert_not_called()

    def test_71_native_binary_owner_must_match_actual_current_user(self):
        f=Fixture(self);uid=os.getuid()
        with mock.patch.object(parent.os,'getuid',return_value=uid+1):
            with self.assertRaisesRegex(ValueError,'owner/link'):f.run()
        f.popen.assert_not_called()

    def test_72_same_bytes_changed_metadata_during_read_cannot_pass(self):
        f=Fixture(self);original=os.read;changed=False
        def mutate(fd,count):
            nonlocal changed
            raw=original(fd,count)
            if raw.startswith(b'FIXTURE_NATIVE_SHIM') and not changed:
                changed=True;info=f.exec_shim.stat();os.utime(f.exec_shim,ns=(info.st_atime_ns,info.st_mtime_ns+1000000))
            return raw
        with mock.patch.object(parent.os,'read',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'changed during complete read'):f.run()
        self.assertTrue(changed);f.popen.assert_not_called()

    def test_73_lifecycle_shim_pin_cannot_fall_back_to_python_source(self):
        f=Fixture(self)
        self.rebind_policy(f,lambda policy:policy['lifecycle'].update(execShimSha256=f.data['sourceFiles']['experiments/ch7/lifecycle_exec.py']))
        with self.assertRaisesRegex(ValueError,'legacy fallback forbidden'):f.run()
        f.popen.assert_not_called()

    def test_74_listener_leaf_is_closed(self):
        f=Fixture(self);self.bind_leaf(f,'listenerEvidence',lambda value:value.update(onlyTargetPid=701))
        with self.assertRaisesRegex(ValueError,'closed three-way listener'):f.run()
        f.popen.assert_not_called()

    def test_75_listener_pid_filter_cannot_replace_global_command(self):
        f=Fixture(self);self.bind_leaf(f,'listenerEvidence',lambda value:value['command'].extend(['-p','701']))
        with self.assertRaisesRegex(ValueError,'global listener argv'):f.run()
        f.popen.assert_not_called()

    def test_76_listener_timeout_or_acceptance_type_cannot_be_widened(self):
        f=Fixture(self);self.bind_leaf(f,'listenerEvidence',lambda value:value.update(maxSeconds=.6))
        with self.assertRaisesRegex(ValueError,'whole deadline/cap'):f.run()
        f.popen.assert_not_called()

    def test_77_listener_parser_pin_cannot_name_other_source(self):
        f=Fixture(self);self.bind_leaf(f,'listenerEvidence',lambda value:value.update(moduleSha256=f.data['sourceFiles']['experiments/ch7/lifecycle_exec_native.c']))
        with self.assertRaisesRegex(ValueError,'listener transcript source pin'):f.run()
        f.popen.assert_not_called()

    def test_78_actual_lsof_executable_hash_is_required(self):
        f=Fixture(self);f.lsof.write_bytes(b'CHANGED LSOF IMAGE')
        with self.assertRaisesRegex(ValueError,'lsof fixed executable SHA'):f.run()
        f.popen.assert_not_called()

    def test_79_all_three_new_modules_need_distinct_actual_git_proofs(self):
        f=Fixture(self);name='tests/shell/replacement-native-proof.py';path=f.repo/name;path.write_bytes(b'MOCK REPLACEMENT PROOF\n')
        f.data['sourceFiles'][name]=sha(path);f.frozen_blobs[name]=path.read_bytes()
        proof=next(item for item in f.data['preflightCommands'] if item['arguments']==['show','{SOURCE}:experiments/ch7/lifecycle_exec_native.c'])
        proof.update(arguments=['show','{SOURCE}:'+name],stdoutSha256=sha(path));f.freeze()
        with self.assertRaisesRegex(ValueError,'all three native/listener source modules'):f.run()
        f.popen.assert_not_called()

    def test_80_parent_record_preserves_negative_component_and_no_cold_claim(self):
        f=Fixture(self);result=f.run();record=json.loads(parent.RECORD.read_bytes())
        basis=record['developmentComponentBasis']
        self.assertEqual(len(parent.OBSERVERS),21)
        self.assertEqual((basis['nativeComplete'],basis['attemptsPerHalf']),(9,10))
        self.assertGreater(basis['firstNativeWholeSeconds'],.5)
        self.assertFalse(basis['additionalWarmup']);self.assertFalse(basis['listenerDeadlineExemption'])
        self.assertFalse(basis['coldArtifactFirstEverExecutionClaim'])
        self.assertEqual(result['developmentComponentBasis'],basis)
        self.assertTrue(all(result[key] is False for key in parent.FALSE_GATES))
        self.assertEqual(f.popen.call_count,1)

    def test_81_nonregular_native_path_is_refused_without_blocking_or_execution(self):
        f=Fixture(self);fifo=f.root/'not-an-executable';os.mkfifo(fifo,0o600)
        self.bind_leaf(f,'nativeExec',lambda value:value.update(binaryPath=str(fifo)))
        with self.assertRaisesRegex(ValueError,'must be regular'):f.run()
        f.popen.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
