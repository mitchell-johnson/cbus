import decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt_percentage import byte_to_percentage, percentage_to_byte
from research.edlt_percentage_original import probe

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / 'research/fixtures/edlt-percentage-vectors.json'


def vectors():
    return json.loads(VECTORS.read_text())


class PercentageTests(unittest.TestCase):
    def test_original_windows_and_mono_supported_rows(self):
        supported = excluded = 0
        for row in vectors()['original_rows']:
            fields = row.split('\t')
            with self.subTest(row=row):
                if fields[0] == 'roundtrip':
                    self.assertEqual(byte_to_percentage(int(fields[1])), fields[2])
                    self.assertEqual(percentage_to_byte(fields[2]), int(fields[3]))
                elif fields[0] == 'get':
                    self.assertEqual(percentage_to_byte(fields[1]), int(fields[2]))
                elif fields[2:4] == ['0', '100'] and 0 <= int(fields[1]) <= 255:
                    self.assertEqual(byte_to_percentage(int(fields[1])), fields[4])
                else:
                    excluded += 1
                    continue
                supported += 1
        self.assertEqual((supported, excluded), (270, 20))

    def test_all_independent_original_coefficient_boundary_getters(self):
        rows = vectors()['supplement_rows']
        self.assertEqual(len(rows), 6214)
        for row in rows:
            fields = row.split('\t')
            with self.subTest(input=fields[1]):
                self.assertEqual(percentage_to_byte(fields[1]), int(fields[2]))

    def test_original_roundtrip_losses_remain_visible(self):
        expected = [3, 4, 5, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50,
                    73, 75, 77, 79, 205, 207, 209, 216, 218, 220, 225, 227, 229, 236, 238,
                    240, 245, 247, 249]
        differences = []
        for raw in range(256):
            actual = percentage_to_byte(byte_to_percentage(raw))
            if actual != raw:
                self.assertEqual(actual, raw - 1)
                differences.append(raw)
        self.assertEqual(differences, expected)
        # Original Decimal multiplication rounds before the final truncation.
        self.assertEqual(percentage_to_byte('7.84313725490196078431372549'), 20)
        self.assertEqual(percentage_to_byte('0.3921568627450980392156862745'), 1)

    def test_grammar_accepts_bounded_leading_and_value_preserving_trailing_zeros(self):
        for text in ('0', '000', '000.0000000000000000000000000000'):
            self.assertEqual(percentage_to_byte(text), 0)
        for text in ('50', '050.0000000000000000000000000000'):
            self.assertEqual(percentage_to_byte(text), 127)
        for text in ('100', '100.0000000000000000000000000000'):
            self.assertEqual(percentage_to_byte(text), 255)
        self.assertEqual(percentage_to_byte('007.9228162514264337593543950335'), 20)
        self.assertEqual(percentage_to_byte('79.228162514264337593543950335'), 202)
        self.assertEqual(byte_to_percentage(0), '0')
        self.assertEqual(byte_to_percentage(255), '100')

    def test_unrepresentable_decimal_is_rejected_without_input_rounding(self):
        for text in ('7.9228162514264337593543950336', '79.228162514264337593543950336',
                     '99.9999999999999999999999999999', '100.0000000000000000000000000001'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'exactly representable'):
                percentage_to_byte(text)

    def test_rejects_noncanonical_input_types_and_outside_fixed_point_domain(self):
        class Integer(int): pass
        class Text(str): pass
        for value in (True, False, Integer(1), 1.0, '1', None, -1, 256, 10**1000):
            with self.subTest(value=repr(value)[:50]), self.assertRaises(ValueError):
                byte_to_percentage(value)
        for value in (Text('50'), 50, 50.0, decimal.Decimal('50'), True, b'50', None,
                      '', ' 50', '50 ', '50\n', '+1', '-0', '1e1', '.5', '5.',
                      '1,5', '１', '١', 'NaN', 'Infinity', '0000', '0.' + '0' * 29,
                      '101', '999', '0' * 100_000):
            with self.subTest(value=repr(value)[:50]), self.assertRaises(ValueError):
                percentage_to_byte(value)

    def test_python_decimal_context_locale_and_io_do_not_affect_results(self):
        def forbidden(*args, **kwargs): raise AssertionError('unexpected I/O or locale query')
        with decimal.localcontext() as context:
            context.prec = 1
            context.rounding = decimal.ROUND_UP
            context.traps[decimal.Inexact] = True
            with patch('locale.localeconv', side_effect=forbidden), patch('builtins.open', side_effect=forbidden), \
                    patch('socket.create_connection', side_effect=forbidden), patch('os.getenv', side_effect=forbidden):
                self.assertEqual(byte_to_percentage(3), '1.1764705882352941176470588235')
                self.assertEqual(percentage_to_byte('1.1764705882352941176470588235'), 2)
                self.assertEqual(percentage_to_byte('7.84313725490196078431372549'), 20)

    def test_portable_module_needs_only_standard_library(self):
        import cbus_toolkit.edlt_percentage as module
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / 'cbus_toolkit'; package.mkdir()
            (package / '__init__.py').write_text('')
            (package / 'edlt_percentage.py').write_bytes(Path(module.__file__).read_bytes())
            script = ('import sys;sys.path.insert(0,sys.argv[1]);'
                      'from cbus_toolkit.edlt_percentage import byte_to_percentage,percentage_to_byte;'
                      'assert percentage_to_byte(byte_to_percentage(3))==2;'
                      'assert not any(n.startswith("research") for n in sys.modules)')
            result = subprocess.run([sys.executable, '-I', '-S', '-c', script, directory],
                                    capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_original_probe_rejects_wrong_dll_before_output_or_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / 'eDLT.dll'; wrong.write_bytes(b'not original')
            output = Path(directory) / 'never-created'
            with patch('subprocess.run', side_effect=AssertionError('must not execute')):
                with self.assertRaisesRegex(ValueError, 'exact original eDLT.dll'):
                    probe(wrong, Path(directory) / 'absent-mono', output)
            self.assertFalse(output.exists())


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_MONO_MACOS_ROOT'),
                     'requires exact original Toolkit files and owned Mono runtime')
class OriginalPercentageTests(unittest.TestCase):
    def test_fresh_original_il_all_vectors_and_written_instruction_audit(self):
        parent = os.environ.get('CBUS_PERCENTAGE_REPORT_DIR')
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            result = probe(Path(os.environ['CBUS_TOOLKIT_EXE']).parent / 'eDLT.dll',
                           os.environ['CBUS_MONO_MACOS_ROOT'], Path(parent or directory) / 'original')
            self.assertTrue(result['passed'])
            self.assertEqual(result['before'], result['after'])
            self.assertEqual(result['rows'], vectors()['original_rows'] + vectors()['supplement_rows'])
            self.assertEqual(len(result['rows']), 6504)
            self.assertEqual(len(result['commands']), 6)
            self.assertEqual(result['runtime_evidence'][0].split('\t')[-2:], ['pointer_bits', '64'])
            if parent:
                (Path(parent) / 'original-report.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
