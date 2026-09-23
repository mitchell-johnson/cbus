from dataclasses import FrozenInstanceError
from fractions import Fraction
import importlib.util
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.toolkit_numeric import (
    ToolkitNumericConversionError, UnsupportedToolkitNumericInput,
    parse_toolkit_integer,
)

ROOT = Path(__file__).resolve().parents[1]


def vectors():
    return json.loads((ROOT/'research/fixtures/toolkit-numeric-original-vectors.json').read_text())


class ToolkitNumericTests(unittest.TestCase):
    def test_original_values_and_intermediate_extended_bytes(self):
        for row in vectors()['rows']:
            original = row.get('original', row)
            options = {'decimal_separator': original['decimal_separator'], 'thousands_separator': original['thousands_separator']}
            with self.subTest(text=original['input'], **options):
                if row['status'] == 'conversion-error':
                    with self.assertRaises(ToolkitNumericConversionError):
                        parse_toolkit_integer(original['input'], **options)
                elif row['status'] == 'unsupported-int64-overflow':
                    with self.assertRaises(UnsupportedToolkitNumericInput):
                        parse_toolkit_integer(original['input'], **options)
                else:
                    actual = parse_toolkit_integer(original['input'], **options)
                    self.assertEqual(actual.value, original['converted_integers'][0])
                    self.assertEqual(actual.extended80_hex, original['extended80_hex'][0])
                    self.assertEqual([actual.normalized_text] if actual.normalized_text else [], original['original_float_inputs'])

    def test_source_power_tables_match_exact_nearest_even_generation(self):
        # Independently compare the compact arithmetic primitive to original
        # literal tables, including the separate 10**32 scaling stage.
        from cbus_toolkit.toolkit_numeric import _round_extended, _extended_bytes
        for row in vectors()['power_constants']:
            self.assertEqual(_extended_bytes(_round_extended(Fraction(10**row['power'])), False).hex(), row['hex'])

    def test_nonstandard_filter_and_prefix_sign_are_not_python_number_parsing(self):
        for text, value in [('6A4',64),('0x40',40),('1e3',13),('NaN',0),('(64)',64),('--64',64),('-+ (64',-64),('64-2',642),('\t-64',64)]:
            self.assertEqual(parse_toolkit_integer(text).value,value)
        self.assertTrue(parse_toolkit_integer('1.234,56').separators_swapped)
        self.assertFalse(parse_toolkit_integer('1,234.56').separators_swapped)
        self.assertEqual(parse_toolkit_integer('1.234,56').normalized_text,'1234.56')

    def test_int32_wrap_and_int64_limits_are_separate(self):
        for text, integer, value in [('2147483648',2147483648,-2147483648),('4294967296',4294967296,0),('9223372036854775807',9223372036854775807,-1),('-9223372036854775808',-9223372036854775808,0)]:
            result=parse_toolkit_integer(text)
            self.assertEqual((result.truncated_integer,result.value,result.int32_wrapped),(integer,value,True))
        for text in ('9223372036854775808','-9223372036854775809','9'*64):
            with self.assertRaisesRegex(UnsupportedToolkitNumericInput,'signed 64-bit'):
                parse_toolkit_integer(text)

    def test_truncation_after_rounding_and_negative_zero(self):
        self.assertEqual(parse_toolkit_integer('1234.9999999999999999').value,1234)
        self.assertEqual(parse_toolkit_integer('.99999999999999999999').value,1)
        self.assertEqual(parse_toolkit_integer('-64.9').value,-64)
        self.assertEqual(parse_toolkit_integer('-0').extended80_hex,'00000000000000000080')
        self.assertEqual(parse_toolkit_integer('-NaN').extended80_hex,'00000000000000000000')
        self.assertEqual(parse_toolkit_integer('0'*64).value,0)

    def test_strict_bounded_input_and_locale_do_not_consult_host_locale(self):
        for value in (None,True,64,b'64'):
            with self.assertRaises(TypeError):parse_toolkit_integer(value)
        for value in ('0'*65,'6\0'+'4','６４','é64'):
            with self.assertRaises(UnsupportedToolkitNumericInput):parse_toolkit_integer(value)
        for pair in (('.', '.'),(',', ','),(' ','.'),('',','),(True,','),(['.'],',')):
            with self.assertRaises(UnsupportedToolkitNumericInput):
                parse_toolkit_integer('64',decimal_separator=pair[0],thousands_separator=pair[1])
        self.assertEqual(parse_toolkit_integer('64,9',decimal_separator=',',thousands_separator='.').value,64)
        with self.assertRaises(ToolkitNumericConversionError):parse_toolkit_integer('.2.3')

    def test_result_is_immutable_and_export_is_detached(self):
        result=parse_toolkit_integer('64')
        with self.assertRaises(FrozenInstanceError):result.value=123
        exported=result.as_dict();exported['value']=123
        self.assertEqual(result.value,64)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires exact original Toolkit executable')
class OriginalToolkitNumericTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=ROOT/'research/toolkit_numeric_original.py'
        spec=importlib.util.spec_from_file_location('toolkit_numeric_original',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        cls.probe=module.NumericOriginalProbe(os.environ['CBUS_TOOLKIT_EXE'])

    def test_original_direct_conversion_matrix_and_power_constants(self):
        frozen=vectors()
        self.assertEqual(self.probe.powers(),frozen['power_constants'])
        for row in frozen['rows']:
            expected=row.get('original',row)
            with self.subTest(text=expected['input'],decimal=expected['decimal_separator']):
                if row['status']=='conversion-error':
                    with self.assertRaisesRegex(ValueError,'Original StrToFloat reached'):
                        self.probe.run(expected['input'],decimal=expected['decimal_separator'],thousands=expected['thousands_separator'])
                else:
                    self.assertEqual(self.probe.run(expected['input'],decimal=expected['decimal_separator'],thousands=expected['thousands_separator']),expected)

    def test_original_validator_retains_all_66_historical_results(self):
        frozen=json.loads((ROOT/'research/fixtures/toolkit-numeric-validation-vectors.json').read_text())
        self.assertEqual(len(frozen['cases']),66)
        for expected in frozen['cases']:
            with self.subTest(text=expected['input'],decimal=expected['decimal_separator']):
                actual=self.probe.validate(expected['input'],decimal=expected['decimal_separator'],thousands=expected['thousands_separator'])
                for key in ('converted_integers','original_float_inputs','error_message_ids','gui_stub_trace'):
                    self.assertEqual(actual[key],expected[key])
                self.assertEqual(bool(actual['return_value']&255),expected['accepted'])
