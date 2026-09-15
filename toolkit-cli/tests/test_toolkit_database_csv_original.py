import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch

from research.toolkit_database_csv_original import _finish_report, _run, probe


class OriginalCSVHarnessTests(unittest.TestCase):
    def test_wrong_executable_rejected_before_execution_or_output(self):
        with tempfile.TemporaryDirectory() as folder:
            wrong = Path(folder) / 'wrong.exe'; wrong.write_bytes(b'wrong')
            output = Path(folder) / 'new'
            with patch('subprocess.Popen', side_effect=AssertionError('No execution')):
                with self.assertRaisesRegex(ValueError, 'exact original'): probe(wrong, output)
            self.assertFalse(output.exists())

    def test_report_failure_keeps_first_interruption_and_withholds_success(self):
        class Broken(KeyboardInterrupt):
            def __str__(self): raise SystemExit('format failed')
        first = Broken()
        with tempfile.TemporaryDirectory() as folder:
            report = {'passed': True}
            with patch('research.toolkit_database_csv_original.digest', side_effect=SystemExit(3)):
                (Path(folder) / 'file').write_bytes(b'x')
                _finish_report(Path(folder), report, first)
            self.assertFalse(report['passed'])
            self.assertEqual(report['error']['message'], '<exception message unavailable>')
            report = {'passed': True}
            with patch('research.toolkit_database_csv_original.os.replace', side_effect=OSError('replace failed')):
                with self.assertRaises(OSError): _finish_report(Path(folder), report)
            self.assertFalse(report['passed']); self.assertFalse((Path(folder) / 'report.json').exists())

    def test_reporting_write_interruption_is_not_replaced_by_close(self):
        first = KeyboardInterrupt('write'); stream = Mock()
        stream.write.side_effect = first; stream.close.side_effect = SystemExit('close')
        with tempfile.TemporaryDirectory() as folder, patch('pathlib.Path.open', return_value=stream):
            with self.assertRaises(KeyboardInterrupt) as raised: _finish_report(Path(folder), {'passed': True})
        self.assertIs(raised.exception, first); stream.close.assert_called_once()

    def test_partial_process_output_survives_timeout_and_primary_interruption(self):
        for first in (subprocess.TimeoutExpired('original', 75), KeyboardInterrupt('original interrupted')):
            with self.subTest(type=type(first).__name__), tempfile.TemporaryDirectory() as folder:
                process = Mock(pid=17); process.poll.return_value = None
                process.communicate.side_effect = first; process.wait.return_value = -9
                if isinstance(first, KeyboardInterrupt): process.kill.side_effect = SystemExit('kill interrupted')
                def spawn(*args, **kwargs):
                    kwargs['stdout'].write(b'partial stdout'); kwargs['stderr'].write(b'partial stderr')
                    return process
                report = {}; out = Path(folder)
                with patch('research.toolkit_database_csv_original.subprocess.Popen', side_effect=spawn):
                    with self.assertRaises(type(first)) as raised: _run(['owned'], {}, out, report)
                self.assertIs(raised.exception, first)
                self.assertEqual((out / 'stdout.txt').read_bytes(), b'partial stdout')
                self.assertEqual((out / 'stderr.txt').read_bytes(), b'partial stderr')
                self.assertTrue(report['process']['started']); self.assertTrue(report['process']['reaped'])
                process.kill.assert_called_once(); process.wait.assert_called_once_with(timeout=5)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires exact original Toolkit executable')
class OriginalCSVTests(unittest.TestCase):
    def test_all_88_fresh_original_instruction_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            # Acceptance supplies a retained destination; ordinary developer runs
            # use a disposable isolated directory selected by TMPDIR.
            parent = Path(os.environ.get('CBUS_CSV_ORIGINAL_OUTPUT', folder)).resolve()
            result = probe(os.environ['CBUS_TOOLKIT_EXE'], parent / 'fresh-original')
            self.assertTrue(result['passed']); self.assertEqual(result['cases'], 88)


if __name__ == '__main__': unittest.main()
