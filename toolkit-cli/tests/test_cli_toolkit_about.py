from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cbus_toolkit import cli, toolkit_about_cli as boundary
from tests.test_toolkit_about import executable


class AboutCLITests(unittest.TestCase):
    def execute(self,options):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err),patch('socket.create_connection',side_effect=AssertionError('Unexpected network')):
            code=cli.main(['toolkit-about',*options])
        return code,json.loads(out.getvalue()or err.getvalue())

    def test_explicit_and_current_year_sources_and_native_resource_labels(self):
        source=executable();before=hashlib.sha256(source.read_bytes()).hexdigest()
        with patch.object(boundary,'datetime')as clock:
            code,value=self.execute([str(source),'--year','2026']);clock.now.assert_not_called()
        self.assertEqual(code,0);self.assertFalse(value['clock_read'])
        self.assertEqual(value['captions']['version'],'Version 1.18.0 (build 2754) ')
        self.assertEqual(value['provenance']['year'],'explicit CLI override')
        with patch.object(boundary,'datetime')as clock:
            clock.now.return_value=SimpleNamespace(year=2042)
            code,value=self.execute([str(source)]);clock.now.assert_called_once_with()
        self.assertEqual(code,0);self.assertTrue(value['clock_read']);self.assertEqual(value['year'],2042)
        self.assertIn('2042',value['captions']['copyright'])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)

    def test_captured_context_is_unverified_and_input_bytes_unchanged(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'context.json';data=json.dumps({'version':'3.3.2','build':'2039','max_memory_mb':512,
                'used_memory_mb':42,'java_version':'Java \U0001f4a1'}).encode();path.write_bytes(data)
            code,value=self.execute([str(executable()),'--year','2026','--context',str(path)])
            self.assertEqual(code,0);self.assertEqual(value['captions']['maximum_memory'],'C-Gate Max Memory: 512 MB')
            self.assertEqual(value['captions']['java'],'Java Version: Java \U0001f4a1')
            self.assertEqual(value['context_source'],'caller-supplied');self.assertFalse(value['context_verified_live'])
            self.assertEqual(path.read_bytes(),data)

    def test_invalid_year_and_context_reject_before_exe_read(self):
        for year in ('0','10000','True','20_26','0x07EA','\u0662\u0660\u0662\u0666','9'*10000):
            with self.subTest(year=year[:8]),patch.object(boundary,'_read')as read,redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit)as stopped:cli.main(['toolkit-about','missing','--year',year])
                self.assertEqual(stopped.exception.code,2);read.assert_not_called()
        cases=(b'null',b'{}',b'{"version":"one","version":"two"}',b'{"version":NaN}',
            b'{"used_memory_mb":'+b'9'*10000+b'}',b'['*64+b'0'+b']'*64,
            b'{"version":"x","build":"x","max_memory_mb":1,"used_memory_mb":1,"java_version":"\\ud800"}')
        for raw in cases:
            with self.subTest(raw=raw[:20]),patch.object(boundary,'_read',return_value=raw)as read:
                code,value=self.execute(['missing','--year','2026','--context','context'])
                self.assertEqual(code,1);self.assertEqual(read.call_count,1)

    def test_file_bounds_nonregular_race_and_first_interruption(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'input';path.write_bytes(b'not PE')
            link=Path(folder)/'link';link.symlink_to(path)
            for item in (Path(folder),link):
                with self.assertRaises(ValueError):boundary._read(item,16384)
            if hasattr(os,'mkfifo'):
                fifo=Path(folder)/'fifo';os.mkfifo(fifo)
                with self.assertRaises(ValueError):boundary._read(fifo,16384)
                real_open=os.open
                def swap(item,flags):
                    path.unlink();os.mkfifo(path);return real_open(item,flags)
                with patch.object(boundary.os,'open',side_effect=swap),self.assertRaises(ValueError):boundary._read(path,16384)
                path.unlink();path.write_bytes(b'one')
            first=KeyboardInterrupt('read interrupted');second=SystemExit('cleanup interrupted');close=os.close
            def cleanup(descriptor):close(descriptor);raise second
            with patch.object(boundary.os,'read',side_effect=first),patch.object(boundary.os,'close',side_effect=cleanup):
                with self.assertRaises(KeyboardInterrupt)as stopped:boundary._read(path,16384)
                self.assertIs(stopped.exception,first)
            with patch.object(boundary,'_read',side_effect=first):
                code,value=self.execute(['missing','--year','2026']);self.assertEqual(code,130)
