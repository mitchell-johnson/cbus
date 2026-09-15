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

from research.pci_routed_identify_original import Failures, plan_tsv, run_original, run_process, semantic_digest, digest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'research/fixtures/pci-routed-identify-original-vectors.json'


class OriginalIdentifyHarnessTests(unittest.TestCase):
    def test_exact_source_and_all_json_tsv_associations(self):
        fixture=json.loads(FIXTURE.read_text())
        self.assertEqual([len(b['cases']) for b in fixture['batches']],[480,422])
        self.assertEqual(hashlib.sha256((ROOT/'research/NativeRoutedIdentifyProbe.java').read_bytes()).hexdigest(),fixture['source_sha256'])
        plans=[row['input'] for batch in fixture['batches'] for row in batch['cases']]
        for batch in fixture['batches']:
            self.assertEqual(hashlib.sha256(plan_tsv([row['input'] for row in batch['cases']])).hexdigest(),batch['tsv_sha256'])
        self.assertEqual(len({p['id'] for p in plans}),902)
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

    def test_final_clock_failure_cannot_replace_first_interruption(self):
        first=KeyboardInterrupt('first'); second=SystemExit('clock'); failures=Failures()
        class Process:
            pid=1
            calls=0
            def wait(self,timeout):
                self.calls+=1
                if self.calls==1:raise first
                return -9
            def kill(self):pass
        with tempfile.TemporaryDirectory() as directory, patch('research.pci_routed_identify_original.time.monotonic',side_effect=[1,second]):
            result=run_process('owned',['fixture'],destination=Path(directory),environment={},failures=failures,popen=lambda *a,**k:Process())
        self.assertIs(failures.first,first)
        self.assertEqual([r['stage'] for r in failures.records],['owned','owned.finish_clock'])
        self.assertNotIn('duration_seconds',result)
        try:failures.raise_first()
        except BaseException as caught:self.assertIs(caught,first)

    def test_launch_failure_never_becomes_started_or_retried(self):
        error=OSError('launch denied');errors=Failures()
        def launch(*args,**kwargs):raise error
        with tempfile.TemporaryDirectory() as directory:
            value=run_process('owned',['fixture-only'],destination=Path(directory),environment={},failures=errors,popen=launch)
        self.assertIs(errors.first,error);self.assertTrue(value['launch_attempted'])
        self.assertFalse(value['started']);self.assertFalse(value['completed']);self.assertFalse(value['resubmitted'])

    def test_runtime_hash_rejects_fifo_and_preserves_read_error_before_close(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo=Path(directory)/'runtime';os.mkfifo(fifo)
            with self.assertRaises(ValueError):digest(fifo)
            source=Path(directory)/'regular';source.write_bytes(b'abc')
            self.assertEqual(digest(source),hashlib.sha256(b'abc').hexdigest())
            first=KeyboardInterrupt('read');second=SystemExit('close')
            real_close=os.close
            def close(fd):real_close(fd);raise second
            with patch('os.read',side_effect=first),patch('os.close',side_effect=close):
                try:digest(source)
                except BaseException as error:self.assertIs(error,first)
            link=Path(directory)/'link';link.symlink_to(source)
            with self.assertRaises(OSError):digest(link)

    def test_unsupported_host_rejects_before_file_or_process_access(self):
        with patch('sys.platform','unsupported'),patch('pathlib.Path.resolve',side_effect=AssertionError('No file access')):
            with self.assertRaises(ValueError):run_original(ROOT,java='no',javac='no',jar='no',destination='no')


@unittest.skipUnless(sys.platform=='darwin' and all(os.environ.get(name) for name in
    ('CBUS_CGATE_JAVA','CBUS_CGATE_JAVAC','CBUS_LOCAL_CGATE_VENDOR')),
    'Explicit owned macOS JDK/compiler and original C-Gate files required')
class OriginalIdentifyTests(unittest.TestCase):
    def test_fresh_original_full902_with_supported_interpreter_prepins(self):
        parent=Path(os.environ.get('CBUS_PCI_ROUTED_IDENTIFY_REPORT_DIR',str(ROOT/'research/runtime/pci-routed-identify-original'))).resolve()
        parent.mkdir(parents=True,exist_ok=True)
        report=run_original(ROOT,java=os.environ['CBUS_CGATE_JAVA'],javac=os.environ['CBUS_CGATE_JAVAC'],
            jar=Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])/'cgate.jar',destination=parent/uuid.uuid4().hex)
        self.assertTrue(report['passed']);self.assertEqual(report['cases'],902)
        self.assertTrue(report['inputs_unchanged']);self.assertTrue(report['compiled_unchanged'])
        self.assertEqual(report['python_version'],sys.version)
        self.assertIn(str(Path(sys.executable).resolve()),report['inputs_before'])
        self.assertEqual([r['exit_code'] for r in report['processes']],[0,0,0])
        self.assertTrue(all(not r['resubmitted'] for r in report['processes']))


if __name__=='__main__':unittest.main()
