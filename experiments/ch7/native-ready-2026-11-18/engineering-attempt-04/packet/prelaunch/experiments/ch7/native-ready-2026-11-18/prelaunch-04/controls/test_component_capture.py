"""Capture-flow controls with real disposable pipes, never a child/listener."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('native_component_control_subject',HERE/'component_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class FakeHandle:
    lease_id='f'*32
    returncode=0
    def __init__(self,stdout,stderr):
        streams=[]
        for payload in (stdout,stderr):
            r,w=os.pipe();os.write(w,payload);os.close(w);streams.append(os.fdopen(r,'rb'))
        self.stdout,self.stderr=streams
        self.process=self
    def poll(self):return 0
    def wait(self,timeout=None):return 0


class FakeRegistry:
    def __init__(self,stdout,stderr):self.payloads=(stdout,stderr);self.calls=0
    def launch(self,argv,**kwargs):
        self.calls+=1
        if argv!=probe.ARGV:raise AssertionError('global argv changed')
        return FakeHandle(*self.payloads)
    def _state(self):return {'bytes':123,'sha256':'f'*64,'lastSequence':5,'leases':{'f'*32:{'leaseId':'f'*32}}}


class ComponentControls(unittest.TestCase):
    def execute(self,stdout,stderr):
        registry=FakeRegistry(stdout,stderr)
        plan={'sourcePins':dict(adapter='a'*64,lifecycle='b'*64,CSource='c'*64,legacyShim='d'*64,caller='e'*64),
            'lsofExecutableSha256':'f'*64}
        with mock.patch.object(probe,'check_sources'):
            value=probe.capture(registry,'legacy',{'lifecycle':{'execShimSha256':'d'*64}},plan)
        self.assertEqual(registry.calls,1)
        return value

    def test_complete_global_records_keep_ipv6_and_duplicate_fd_entries(self):
        raw=b'p701\nf7\nPTCP\ntIPv4\nn127.0.0.1:11434\nTST=LISTEN\nf8\nPTCP\ntIPv6\nn[::1]:11434\nTST=LISTEN\n'
        value=self.execute(raw,b'')
        self.assertEqual(value['outcome']['state'],'OBSERVED')
        self.assertEqual(len(value['outcome']['records']),2)
        self.assertEqual(value['outcome']['records'][1]['family'],'IPv6')
        self.assertEqual(probe.parser._decode_capture(value['transcript']['stdout'],'STDOUT'),raw)

    def test_stderr_and_incomplete_fields_do_not_pass(self):
        value=self.execute(b'p701\nf7\nPTCP\n',b'visible warning\n')
        self.assertEqual(value['outcome']['state'],'UNKNOWN')
        self.assertIn('STDERR_NOT_EMPTY',value['outcome']['reasons'])
        self.assertIn('STDOUT_INCOMPLETE_RECORD',value['outcome']['reasons'])

    def test_declared_fixed_plan_source_and_limits_match_before_queries(self):
        plan=json.loads((HERE/'component-plan-02.json').read_bytes())
        self.assertEqual(plan['fixedOrder'],['legacy','native']*10)
        self.assertEqual(plan['priorChainsPerHalf']+plan['actualCallsPerHalf'],6318)
        self.assertEqual(plan['wholeListenerMaximumSeconds'],.5)
        self.assertEqual(plan['sourcePins']['caller'],hashlib.sha256((HERE/'component_probe.py').read_bytes()).hexdigest())
        self.assertFalse(plan['full15_5MiBUpperEnvelopeCovered'])


if __name__=='__main__':unittest.main(verbosity=2)
