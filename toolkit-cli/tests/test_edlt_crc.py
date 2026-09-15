import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit.edlt import EdltError, configuration_crc
from research.edlt_crc_original import _finish_report, probe

ROOT = Path(__file__).resolve().parents[1]


class CrcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads((ROOT / 'research/fixtures/edlt-crc-original-vectors.json').read_text())

    def test_all_65536_two_byte_inputs_match_original_literal_table(self):
        expected = base64.b64decode(self.vectors['two_byte_crc_be_base64'], validate=True)
        self.assertEqual(len(expected), 131072)
        actual = b''.join(configuration_crc(value.to_bytes(2, 'big')).to_bytes(2, 'big') for value in range(65536))
        self.assertEqual(actual, expected)

    def test_original_buffers_cover_all_configuration_region_boundaries(self):
        rows = self.vectors['long_cases']
        self.assertEqual(len(rows), 52)
        lengths = set()
        for row in rows:
            data = base64.b64decode(row['data_base64'], validate=True)
            lengths.add(len(data))
            with self.subTest(length=len(data), crc=row['crc']):
                self.assertEqual(configuration_crc(data), row['crc'])
        self.assertTrue({n + delta for n in (239, 3839, 4095, 1023, 9199, 9216)
                         for delta in (-1, 0, 1)} <= lengths)
        self.assertTrue({0, 1, 65535, 65536} <= lengths)

    def test_original_seed_polynomial_and_no_final_xor_literals(self):
        self.assertEqual(configuration_crc(b''), 0xFA50)
        self.assertEqual(configuration_crc(b'123456789'), 342)
        self.assertEqual(configuration_crc(bytes.fromhex('000102ff')), 59018)

    def test_previously_rejected_non_bytes_remain_rejected(self):
        for value in (None, True, 1, 'abc', bytearray(b'abc'), memoryview(b'abc'), [1, 2, 3]):
            with self.subTest(type=type(value).__name__), self.assertRaises(EdltError):
                configuration_crc(value)

    def test_bytes_subclass_iteration_and_exception_semantics_are_preserved(self):
        class Plain(bytes): pass
        class Redirected(bytes):
            def __iter__(self): return iter(b'123456789')
            def __bytes__(self): raise AssertionError('must not coerce subclass')
        class Empty(bytes):
            def __iter__(self): return iter(())
        marker = RuntimeError('original iterator exception')
        class Raises(bytes):
            def __iter__(self): raise marker
        self.assertEqual(configuration_crc(Plain(b'123456789')), 342)
        self.assertEqual(configuration_crc(Redirected(b'abc')), 342)
        self.assertEqual(configuration_crc(Empty(b'abc')), 0xFA50)
        with self.assertRaises(RuntimeError) as raised:
            configuration_crc(Raises(b'abc'))
        self.assertIs(raised.exception, marker)

    def test_wrong_original_dll_is_rejected_before_output_or_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / 'wrong.dll'; wrong.write_bytes(b'not original')
            out = Path(directory) / 'new'
            with patch('subprocess.run', side_effect=AssertionError('must not execute')):
                with self.assertRaisesRegex(ValueError, 'exact original CBusLogicModel.dll'):
                    probe(wrong, Path(directory) / 'absent', out)
            self.assertFalse(out.exists())

    def test_evidence_failures_do_not_replace_primary_interruption(self):
        class Unprintable(KeyboardInterrupt):
            def __str__(self): raise RuntimeError('format failed')
        first = Unprintable()
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / 'artifact').write_bytes(b'data')
            report = {'passed': True}
            with patch('research.edlt_crc_original.digest', side_effect=SystemExit(9)):
                try:
                    try: raise first
                    except BaseException as error:
                        _finish_report(out, report, error)
                        raise
                except KeyboardInterrupt as caught:
                    self.assertIs(caught, first)
            self.assertFalse(report['passed'])
            self.assertEqual(report['failure']['message'], '<exception message unavailable>')
            with patch('pathlib.Path.open', side_effect=OSError('report unavailable')):
                _finish_report(out, report, first)

    def test_success_report_failure_is_visible_and_cannot_claim_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            report = {'passed': True}
            failure = OSError('cannot publish report')
            with patch('research.edlt_crc_original.os.replace', side_effect=failure):
                with self.assertRaises(OSError) as caught:
                    _finish_report(Path(directory), report)
            self.assertIs(caught.exception, failure)
            self.assertFalse(report['passed'])
            self.assertFalse((Path(directory) / 'report.json').exists())

    def test_reporting_write_interruption_survives_close_failure(self):
        first = KeyboardInterrupt('write interrupted')
        handle = Mock()
        handle.write.side_effect = first
        handle.close.side_effect = SystemExit('close failed')
        report = {'passed': True}
        with tempfile.TemporaryDirectory() as directory:
            with patch('pathlib.Path.open', return_value=handle):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    _finish_report(Path(directory), report)
            self.assertIs(caught.exception, first)
            self.assertFalse(report['passed'])
            self.assertFalse((Path(directory) / 'report.json').exists())
            handle.close.assert_called_once_with()


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('CBUS_TOOLKIT_EXE')
                     and os.environ.get('CBUS_MONO_MACOS_ROOT'), 'requires pinned original files and owned macOS Mono')
class OriginalCrcTests(unittest.TestCase):
    def test_fresh_unchanged_original_all_vectors_and_actual_runtime(self):
        parent = os.environ.get('CBUS_CRC_REPORT_DIR')
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(parent or temporary).resolve() / 'original'
            result = probe(Path(os.environ['CBUS_TOOLKIT_EXE']).parent / 'CBusLogicModel.dll',
                           os.environ['CBUS_MONO_MACOS_ROOT'], destination)
            self.assertTrue(result['passed'])
            self.assertEqual(result['before'], result['after'])
            self.assertEqual((result['two_byte_cases'], result['long_cases']), (65536, 52))
            self.assertTrue(result['result_matches'])
            self.assertEqual(len(result['actual_runtime']), 3)


if __name__ == '__main__':
    unittest.main()
