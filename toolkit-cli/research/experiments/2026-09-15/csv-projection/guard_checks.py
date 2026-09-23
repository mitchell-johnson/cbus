"""Host-only failure/admission checks. No vendor import, subprocess or emulation."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result

probe=module('guard_csv_probe',BASE/'NativeCachedCSVProbe.py')
launcher=module('guard_csv_launcher',BASE/'run.py')

class GuardChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='host-guards-',dir=BASE)
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_fifo_and_symlink_rejected_without_read(self):
        fifo=self.root/'input-fifo';os.mkfifo(fifo)
        regular=self.root/'regular';regular.write_bytes(b'abc')
        link=self.root/'link';link.symlink_to(regular)
        for reader in (probe.bounded,launcher.read):
            with self.subTest(reader=reader.__module__),patch.object(os,'read',side_effect=AssertionError('read must not begin')):
                with self.assertRaisesRegex(RuntimeError,'Regular input'):reader(fifo,10)
                with self.assertRaises(OSError):reader(link,10)
            self.assertEqual(reader(regular,3),b'abc')
            with self.assertRaisesRegex(RuntimeError,'bound'):reader(regular,2)
    def test_first_read_and_validation_error_survive_close(self):
        first=KeyboardInterrupt('first read');second=SystemExit('secondary close')
        for reader in (probe.bounded,launcher.read):
            with self.subTest(reader=reader.__module__),patch.object(os,'open',return_value=987),patch.object(os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFREG,st_size=0)),patch.object(os,'read',side_effect=first),patch.object(os,'close',side_effect=second):
                with self.assertRaises(KeyboardInterrupt) as caught:reader(self.root/'unused',10)
                self.assertIs(caught.exception,first)
            with patch.object(os,'open',return_value=987),patch.object(os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO,st_size=0)),patch.object(os,'close',side_effect=second):
                with self.assertRaisesRegex(RuntimeError,'Regular input'):reader(self.root/'unused',10)
    def test_close_without_primary_is_raised(self):
        second=SystemExit('close alone')
        for reader in (probe.bounded,launcher.read):
            with patch.object(os,'open',return_value=987),patch.object(os,'fstat',return_value=types.SimpleNamespace(st_mode=stat.S_IFREG,st_size=0)),patch.object(os,'read',return_value=b''),patch.object(os,'close',side_effect=second):
                with self.assertRaises(SystemExit) as caught:reader(self.root/'unused',10)
                self.assertIs(caught.exception,second)
    def test_capture_parent_escape_rejected_before_write(self):
        owned=self.root/'owned';owned.mkdir();outside=self.root/'outside';outside.mkdir()
        (outside/'launch-owned.json').write_text('{}')
        link=owned/'link';link.symlink_to(outside,target_is_directory=True)
        with patch.object(probe,'BASE',owned):
            with self.assertRaisesRegex(RuntimeError,'nonsymlink'):probe.admit_output(link/'capture')
            self.assertEqual(sorted(p.name for p in outside.iterdir()),['launch-owned.json'])
            normal=owned/'job';normal.mkdir();(normal/'launch-owned.json').write_text('{}')
            probe.admit_output(normal/'capture');probe.admit_output(owned/'prepare')
            self.assertFalse((normal/'capture').exists())
            self.assertFalse((owned/'prepare').exists())
    def test_probe_first_error_and_posthash_evidence(self):
        owned=self.root/'pilot';owned.mkdir()
        (self.root/'ownership.json').write_text(json.dumps({'task':'/root/project_store','owner_token':launcher.TOKEN,'root':str(self.root)}))
        paths={name:owned/name for name in ('exe','map','serializer','self.py')}
        for name,path in paths.items():path.write_text(name)
        (owned/'cases.json').write_bytes((BASE/'cases.json').read_bytes())
        first=KeyboardInterrupt('load support first');second=SystemExit('posthash second')
        counts={};original=probe.bounded
        def read(path,limit):
            counts[path]=counts.get(path,0)+1
            if path==paths['exe'] and counts[path]==2:raise second
            return original(path,limit)
        with patch.multiple(probe,BASE=owned,ORIGINAL=paths['exe'],MAP=paths['map'],SERIALIZER=paths['serializer'],__file__=str(paths['self.py']),EXE_SHA=probe.sha(b'exe'),MAP_SHA=probe.sha(b'map'),SERIALIZER_SHA=probe.sha(b'serializer')),patch.object(probe,'bounded',side_effect=read),patch.object(probe,'load_support',side_effect=first) as forbidden,patch.object(sys,'argv',['probe','prepare',str(owned/'output')]):
            with self.assertRaises(KeyboardInterrupt) as caught:probe.main()
            self.assertIs(caught.exception,first);forbidden.assert_called_once()
        report=json.loads((owned/'output/report.json').read_text())
        self.assertFalse(report['capture_complete']);self.assertFalse(report['original_execution'])
        self.assertEqual(report['error']['type'],'KeyboardInterrupt')
        self.assertEqual(report['postcheck_errors'][0]['type'],'SystemExit')
        self.assertIn(str(paths['map']),report['after'])
    def test_launcher_retains_partial_capture_on_first_error(self):
        owned=self.root/'pilot';owned.mkdir();repo=self.root/'repo'
        helper=owned/'helper.py'
        helper.write_text('''import json\nfrom pathlib import Path\nimport csv_guard_state as state\ndef _run(command,environment,out,report):\n    report.update(attempted=True,started=True,reaped=True)\n    capture=out/'capture';capture.mkdir()\n    (capture/'report.json').write_text(json.dumps({'capture_complete':False,'error':{'type':'DeclaredFailure'}}))\n    (out/'stdout.txt').write_bytes(b'partial stdout')\n    state.started=True\n    raise state.first\ndef _finish_report(out,report,first):\n    (out/'report.json').write_text(json.dumps(report))\n''')
        (owned/'NativeCachedCSVProbe.py').write_text('not executed')
        (owned/'cases.json').write_bytes((BASE/'cases.json').read_bytes())
        (owned/'PROPOSAL.md').write_text('fixture')
        (self.root/'ownership.json').write_text(json.dumps({'owner_token':launcher.TOKEN,'root':str(self.root),'volume_uuid':'24F890EF-A1B9-4B52-8E18-823080A2F0BB'}))
        for relative in ('research/NativeToolkitDatabaseCSVProbe.py','research/vendor/toolkit/app/CBusToolkit.exe','research/vendor/toolkit/app/CBusToolkit.map'):
            p=repo/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(relative)
        dependencies={}
        for name in ('capstone','unicorn','pefile'):
            p=owned/'deps'/name/'__init__.py';p.parent.mkdir(parents=True);p.write_text('not imported');dependencies[name]=p
            if name!='pefile':(p.parent/(name+'.dylib')).write_text(name)
        (owned/'admission.json').write_text(json.dumps({'format':'csv-projection-admission-v1','probe_sha256':launcher.sha((owned/'NativeCachedCSVProbe.py').read_bytes()),'cases_sha256':launcher.sha((owned/'cases.json').read_bytes()),'authorization':'root-reviewed-cached-csv-pilot12-v1'}))
        first=KeyboardInterrupt('process first');second=SystemExit('posthash second')
        state=types.SimpleNamespace(first=first,started=False);original=launcher.read
        def read(path,limit=64*1024*1024):
            if state.started and path==helper:raise second
            return original(path,limit)
        with patch.multiple(launcher,BASE=owned,REPO=repo,HELPER=helper,HELPER_SHA=launcher.sha(helper.read_bytes()),LIBRARIES={launcher.sha(b'capstone'),launcher.sha(b'unicorn')}),patch.dict(sys.modules,{'csv_guard_state':state}),patch.object(importlib.util,'find_spec',side_effect=lambda name:types.SimpleNamespace(origin=str(dependencies[name]))),patch.object(launcher,'read',side_effect=read),patch.object(sys,'argv',['launcher',str(owned/'output')]):
            with self.assertRaises(KeyboardInterrupt) as caught:launcher.main()
            self.assertIs(caught.exception,first)
        report=json.loads((owned/'output/report.json').read_text())
        self.assertFalse(report['passed']);self.assertTrue(report['reaped'])
        self.assertEqual(report['error']['type'],'KeyboardInterrupt')
        self.assertEqual(report['postcheck_errors'][0]['type'],'SystemExit')
        partial=report['partial_capture_artifacts']['capture/report.json']
        self.assertFalse(partial['capture_complete']);self.assertEqual(partial['error']['type'],'DeclaredFailure')
        self.assertEqual(partial['sha256'],launcher.sha((owned/'output/capture/report.json').read_bytes()))

if __name__=='__main__':unittest.main(verbosity=2)
