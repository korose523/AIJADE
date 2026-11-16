"""Portable fault controls for finite-run ownership, identity and terminal evidence."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/ch7'))
from finite_runtime import validate_build, cleanup_owned_databases, stop_owned_processes, dispositions, read_block_receipt
import run_finite_block
import run_finite_sequence

HEAD='1'*40
ONE='aijade_test_'+'a'*32
TWO='aijade_test_'+'b'*32


class RuntimeFaultControls(unittest.TestCase):
    def setUp(self):
        scratch=REPO/'.runtime/tmp';scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='finite-runtime-control-',dir=scratch)
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def leases(self,names):
        p=self.root/'leases.jsonl';p.write_text(''.join(json.dumps(dict(database=n))+'\n' for n in names));return p
    def build(self):
        # A nonexecutable byte fixture tests identity/refusal, never actual .NET validity.
        b=self.root/'Aijade.Tests.dll';b.write_bytes(b'nonexecutable identity fixture: 0.1.0+'+HEAD.encode())
        for ext in ['deps','runtimeconfig']:(self.root/('Aijade.Tests.'+ext+'.json')).write_text('{}')
        p=self.root/'freeze.json'
        v=dict(status='CLEAN_COMMITTED_BUILD_FROZEN_BEFORE_QUALIFICATION',commit=HEAD,assemblyInformationalVersion='0.1.0+'+HEAD,
               files={q.name:hashlib.sha256(q.read_bytes()).hexdigest() for q in self.root.iterdir() if q.is_file()})
        p.write_text(json.dumps(v));return b,p,v
    def test_explicit_binary_and_dependency_identity_rejects_stale_or_missing_files(self):
        b,p,v=self.build()
        # The manifest is deliberately beside the fixture only here; exclude its own file from the identity population.
        m=self.root/'metadata';m.mkdir();p.rename(m/'freeze.json');p=m/'freeze.json'
        validate_build(b,p,HEAD)
        b.write_bytes(b.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'bytes changed'):validate_build(b,p,HEAD)
        b.write_bytes(b.read_bytes()[:-7]);(self.root/'Aijade.Tests.deps.json').unlink()
        with self.assertRaisesRegex(ValueError,'dependency file missing'):validate_build(b,p,HEAD)
    def test_build_from_wrong_commit_is_refused(self):
        b,p,v=self.build();v['commit']='2'*40;p.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'wrong committed build'):validate_build(b,p,HEAD)
    def test_entire_lease_list_is_validated_before_any_drop(self):
        calls=[]
        def run(*a,**k):calls.append(a);raise AssertionError('must not run')
        rows=cleanup_owned_databases(self.leases([ONE,'production;DROP DATABASE aijade']),'/explicit/docker','aijade-next-db',run=run)
        self.assertEqual(calls,[]);self.assertIsNone(rows[0]['remaining']);self.assertIn('nothing dropped',rows[0]['error'])
    def test_failed_presence_is_unknown_and_other_owned_leases_are_still_cleaned(self):
        calls=[];alive={TWO}
        def run(command,**kwargs):
            calls.append(command);sql=command[-1]
            if ONE in sql:return SimpleNamespace(returncode=1,stdout='',stderr='controlled transport failure')
            if sql.startswith('DROP DATABASE'):alive.remove(TWO);out='DROP DATABASE'
            else:out='1' if TWO in alive else '0'
            return SimpleNamespace(returncode=0,stdout=out,stderr='')
        rows=cleanup_owned_databases(self.leases([ONE,TWO]),'/explicit/docker','isolated-db',run=run)
        self.assertIsNone(rows[0]['remaining']);self.assertTrue(rows[0]['error']);self.assertEqual(rows[1]['remaining'],0)
        self.assertTrue(all(c[:3]==['/explicit/docker','exec','isolated-db'] for c in calls))
    def test_duplicate_lease_is_dropped_once_and_absence_is_requeried(self):
        calls=[];alive=True
        def run(command,**kwargs):
            nonlocal alive
            calls.append(command[-1])
            if command[-1].startswith('DROP DATABASE'):alive=False;out='DROP DATABASE'
            else:out='1' if alive else '0'
            return SimpleNamespace(returncode=0,stdout=out,stderr='')
        rows=cleanup_owned_databases(self.leases([ONE,ONE]),'/explicit/docker','isolated-db',run=run)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['remaining'],0)
        self.assertEqual(sum(x.startswith('DROP DATABASE') for x in calls),1);self.assertEqual(len(calls),3)
    def test_exhausted_cleanup_budget_never_reports_absence(self):
        rows=cleanup_owned_databases(self.leases([ONE,TWO]),'/explicit/docker','isolated-db',budget_seconds=0)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['remaining'] is None and r['error'] for r in rows))
    def test_started_flow_without_capture_is_unknown_rather_than_unattempted(self):
        p=['known/C1','known/C2']
        self.assertEqual(dispositions(self.root,p,True)['unknownCaseIds'],p)
        self.assertEqual(dispositions(self.root,p,False)['unattemptedCaseIds'],p)
    def test_partial_journal_preserves_started_and_unknown_dispositions(self):
        (self.root/'journal.jsonl').write_text(json.dumps(dict(caseId='known/C1'))+'\n{broken')
        r=dispositions(self.root,['known/C1','known/C2'],True)
        self.assertEqual(r['inFlightCaseIds'],['known/C1']);self.assertEqual(r['unknownCaseIds'],['known/C2']);self.assertTrue(r['dispositionErrors'])
    def test_exit_zero_without_a_block_receipt_is_not_completion(self):
        r=subprocess.run([sys.executable,'-c','pass'],cwd=self.root,check=False)
        self.assertEqual(r.returncode,0)
        with self.assertRaisesRegex(ValueError,'terminal receipt'):read_block_receipt(self.root/'receipt.json')
    def test_owned_process_group_is_stopped_and_reaped(self):
        p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],cwd=self.root,start_new_session=True)
        try:
            r=stop_owned_processes([p]);self.assertIsNotNone(p.poll());self.assertIsNotNone(r[0]['exitCode']);self.assertEqual(r[0]['errors'],[])
        finally:
            if p.poll() is None:p.kill();p.wait()
    def test_precondition_error_writes_receipt_but_cannot_overwrite_existing_output(self):
        out=self.root/'new';args=SimpleNamespace(output=out)
        with patch.object(run_finite_block,'_main',side_effect=RuntimeError('controlled launch/precondition failure')):
            self.assertEqual(run_finite_block.main(args),1)
        value=json.loads((out/'receipt.json').read_text());self.assertEqual(value['status'],'STOPPED_PRECONDITION');self.assertFalse(value['measurementStarted'])
        original=(out/'receipt.json').read_bytes()
        with patch.object(run_finite_block,'_main',side_effect=RuntimeError('existing output refused')):run_finite_block.main(args)
        self.assertEqual((out/'receipt.json').read_bytes(),original)
    def test_sequence_error_after_start_preserves_real_completed_count(self):
        out=self.root/'new';args=SimpleNamespace(output=out)
        def fail(a):
            out.mkdir();(out/'receipt.json').write_text(json.dumps(dict(status='RUNNING',startedAt='recorded',completedConditionRows=3)))
            raise RuntimeError('controlled controller failure')
        before=signal.getsignal(signal.SIGTERM)
        with patch.object(run_finite_sequence,'_execute',side_effect=fail):self.assertEqual(run_finite_sequence.execute(args),1)
        value=json.loads((out/'receipt.json').read_text());self.assertEqual(value['completedConditionRows'],3);self.assertTrue(value['measurementStarted'])
        self.assertEqual(value['status'],'STOPPED_CONTROLLER_ERROR');self.assertEqual(signal.getsignal(signal.SIGTERM),before)
    def test_signal_during_idle_phase_retains_a_terminal_nonmeasurement_receipt(self):
        out=self.root/'interrupted';args=SimpleNamespace(output=out)
        def interrupted(a):
            out.mkdir();(out/'receipt.json').write_text(json.dumps(dict(status='FIXED_UNLOADED_SETTLING_RUNNING',requestedSeconds=600)))
            os.kill(os.getpid(),signal.SIGTERM)
        with patch.object(run_finite_sequence,'_execute',side_effect=interrupted):self.assertEqual(run_finite_sequence.execute(args),1)
        value=json.loads((out/'receipt.json').read_text());self.assertEqual(value['status'],'STOPPED_PRE_BLOCK');self.assertFalse(value['measurementStarted'])
        self.assertEqual(value['requestedSeconds'],600);self.assertIn('signal',value['reason'])


if __name__=='__main__':unittest.main()
