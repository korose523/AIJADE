"""Versioned decision binding controls; no renderer, model or admission."""
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
import finite_runtime as runtime

class CensusDecisionBinding(unittest.TestCase):
    def test_policy_cannot_choose_an_unknown_observer(self):
        with self.assertRaisesRegex(ValueError,'unrecognized'):runtime.mac_observer({'kind':'other'})
    def test_old_decision_keeps_exact_original_paths(self):
        p={'kind':'mac-observed-idle-daemon-v1'}
        self.assertEqual(runtime.mac_plan(p),'2026-11-16-ch7-mac-formal-backend.md')
        self.assertEqual(runtime.mac_build_path(p),'experiments/ch7/mac-formal-2026-11-16/frozen-build.json')
        self.assertEqual(runtime.mac_observer(p).__name__,'mac_process_guard')
    def test_new_decision_has_separate_frozen_build_and_plan(self):
        p={'kind':'mac-bulk-observed-idle-daemon-v2'}
        self.assertEqual(runtime.mac_plan(p),'2026-11-16-ch7-mac-bulk-census.md')
        self.assertEqual(runtime.mac_build_path(p),'experiments/ch7/mac-census-2026-11-16/frozen-build.json')
        self.assertNotEqual(runtime.mac_build_path(p),runtime.MAC_BUILD_FREEZE_PATH)
    def test_new_policy_dispatch_cannot_reuse_old_pass(self):
        old=types.SimpleNamespace(validate_observation=lambda p,o:{'status':'PASS','blockers':[],'ownedRssBytes':0})
        new=types.SimpleNamespace(validate_observation=lambda p,o:{'status':'UNKNOWN','blockers':['bulk-evidence-absent']})
        obs={'status':'PASS','blockers':[],'ownedProcesses':[],'processPolicySha256':'p','observerModuleSha256':'m'}
        with patch.dict(sys.modules,{'mac_process_guard':old,'mac_process_guard_v2':new}):
            with self.assertRaisesRegex(ValueError,'independently'):runtime.validate_mac_observation(obs,'p','m',{'kind':'mac-bulk-observed-idle-daemon-v2'})
    def test_new_evidence_namespace_is_allowed_without_executable_suffixes(self):
        self.assertIn('experiments/ch7/mac-census-2026-11-16/',runtime.MAC_DATA_PREFIXES)
        for s in ('.py','.c','.dylib','.sh','.exe'):self.assertNotIn(s,runtime.MAC_DATA_SUFFIXES)
    def test_whole_sequence_rejects_wrong_decision_plan(self):
        import finite_sequence_audit as a
        v={'buildFreezePath':runtime.MAC_CENSUS_BUILD_FREEZE_PATH}
        self.assertEqual(a.expected_plan_sha256(v),a.CENSUS_PLAN_SHA256)
        self.assertNotEqual(a.expected_plan_sha256(v),a.PLAN_SHA256)
        with self.assertRaisesRegex(ValueError,'unknown execution decision'):a.expected_plan_sha256({'buildFreezePath':'new/frozen-build.json'})
    def test_native_build_cannot_substitute_another_pinned_helper(self):
        native={'path':'/Volumes/Untitled/AIJADE/fixture','sha256':'a'*64,'sourceSha256':'b'*64}
        policy={'kind':'mac-bulk-observed-idle-daemon-v2','nativeHelper':native}
        runtime.validate_mac_build_policy(policy,{'nativeCensus':dict(native,compiler='fixture')})
        for key in native:
            changed=dict(native);changed[key]='substituted'
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'identity differ'):
                runtime.validate_mac_build_policy(policy,{'nativeCensus':changed})
    def test_retained_observer_bytes_equal_historical_actual_implementation(self):
        import hashlib,subprocess
        path='experiments/ch7/mac_process_guard.py'
        actual=(REPO/path).read_bytes()
        self.assertEqual(hashlib.sha256(actual).hexdigest(),'be8df86b47f382f663eab4f22553025a41661326695d112cfc30ffbe1c677d87')
if __name__=='__main__':unittest.main()
