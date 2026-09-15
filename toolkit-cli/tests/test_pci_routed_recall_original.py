"""Bounded original matcher fixture and its failure-preserving local process helper."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from research.pci_routed_recall_original import Failures, plan_tsv, run_original, run_process, semantic_digest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'research/fixtures/pci-routed-recall-original-vectors.json'


class OriginalRecallHarnessTests(unittest.TestCase):
    def test_exact_source_and_all_json_tsv_associations(self):
        fixture=json.loads(FIXTURE.read_text())
        self.assertEqual(len(fixture['cases']),428)
        self.assertEqual(hashlib.sha256((ROOT/'research/NativeRoutedRecallProbe.java').read_bytes()).hexdigest(),fixture['source_sha256'])
        plans=[row['input'] for row in fixture['cases']]
        self.assertEqual(hashlib.sha256(plan_tsv(plans)).hexdigest(),fixture['tsv_sha256'])
        self.assertEqual(len({p['id'] for p in plans}),428)
        changed=[dict(p) for p in plans];changed[0]['root']=1
        self.assertNotEqual(plan_tsv(changed),plan_tsv(plans))

    def test_semantic_hash_only_removes_declared_clock_nondeterminism(self):
        first={'aW.N':100,'aW.ai':46,'nested':{'aW.F':['reply'],'utc_milliseconds_before':99,'utc_milliseconds_after':101}}
        other={'aW.N':200,'aW.ai':46,'nested':{'aW.F':['reply'],'utc_milliseconds_before':199,'utc_milliseconds_after':201}}
        self.assertEqual(semantic_digest(first),semantic_digest(other))
        for key,value in (('aW.N',0),('aW.ai',35),('extra',None)):
            modified={**other,key:value};self.assertNotEqual(semantic_digest(first),semantic_digest(modified))
        other['nested']['aW.F']=['different'];self.assertNotEqual(semantic_digest(first),semantic_digest(other))

    def test_partial_output_first_interrupt_and_reap_without_replay(self):
        class Refusal(KeyboardInterrupt):
            def with_traceback(self,_):raise SystemExit('secondary traceback')
        for original in (Refusal('first'),subprocess.TimeoutExpired('owned',1)):
            errors=Failures();calls=[]
            class Process:
                pid=12345
                def wait(self,timeout):
                    calls.append('wait')
                    if calls.count('wait')==1:raise original
                    return -9
                def kill(self):calls.append('kill');raise SystemExit('secondary kill')
            def launch(command,**kwargs):
                calls.append('launch');kwargs['stdout'].write(b'partial before failure\n');return Process()
            with tempfile.TemporaryDirectory() as directory:
                dest=Path(directory)
                value=run_process('owned',['fixture-only'],destination=dest,environment={},failures=errors,popen=launch)
                self.assertEqual((dest/'owned.stdout').read_bytes(),b'partial before failure\n')
                self.assertTrue(value['started']);self.assertTrue(value['completed']);self.assertFalse(value['resubmitted'])
            caught=None
            try:errors.raise_first()
            except BaseException as error:caught=error
            self.assertIs(caught,original)
            self.assertEqual(calls,['launch','wait','kill','wait'])

    def test_launch_failure_never_becomes_started_or_retried(self):
        error=OSError('launch denied');errors=Failures()
        def launch(*args,**kwargs):raise error
        with tempfile.TemporaryDirectory() as directory:
            value=run_process('owned',['fixture-only'],destination=Path(directory),environment={},failures=errors,popen=launch)
        self.assertIs(errors.first,error);self.assertTrue(value['launch_attempted'])
        self.assertFalse(value['started']);self.assertFalse(value['completed']);self.assertFalse(value['resubmitted'])

    def test_unsupported_host_rejects_before_file_or_process_access(self):
        with patch('sys.platform','unsupported'),patch('pathlib.Path.resolve',side_effect=AssertionError('No file access')):
            with self.assertRaises(ValueError):run_original(ROOT,java='no',javac='no',jar='no',destination='no')


@unittest.skipUnless(sys.platform=='darwin' and all(os.environ.get(name) for name in
    ('CBUS_CGATE_JAVA','CBUS_CGATE_JAVAC','CBUS_LOCAL_CGATE_VENDOR')),
    'Explicit owned macOS JDK/compiler and original C-Gate files required')
class OriginalRecallTests(unittest.TestCase):
    def test_fresh_original_full428_with_supported_interpreter_prepins(self):
        parent=Path(os.environ.get('CBUS_PCI_ROUTED_RECALL_REPORT_DIR',str(ROOT/'research/runtime/pci-routed-recall-original'))).resolve()
        parent.mkdir(parents=True,exist_ok=True)
        report=run_original(ROOT,java=os.environ['CBUS_CGATE_JAVA'],javac=os.environ['CBUS_CGATE_JAVAC'],
            jar=Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])/'cgate.jar',destination=parent/uuid.uuid4().hex)
        self.assertTrue(report['passed']);self.assertEqual(report['cases'],428)
        self.assertTrue(report['inputs_unchanged']);self.assertTrue(report['compiled_unchanged'])
        self.assertEqual(report['python_version'],sys.version)
        self.assertIn(str(Path(sys.executable).resolve()),report['inputs_before'])
        self.assertEqual([r['exit_code'] for r in report['processes']],[0,0])
        self.assertTrue(all(not r['resubmitted'] for r in report['processes']))


if __name__=='__main__':unittest.main()
