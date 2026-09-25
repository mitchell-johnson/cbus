"""Canonical and source-pinned Toolkit culture contracts for Measurement."""
import hashlib
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_measurement import MEASUREMENT_CULTURES, measurement_composite


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/edlt-measurement-culture-acceptance.json'


def converts(value, **kwargs):
    return measurement_composite(value, **kwargs)


class InvariantCultureTests(unittest.TestCase):
    def test_comma_and_grouping_inputs_reject(self):
        for value in ('1,5', '1.234,56', '1,000', '1 000', '1_0', '1,000.00'):
            with self.subTest(value=value), self.assertRaises(EdltError):
                converts(value)

    def test_non_decimal_text_rejects(self):
        for value in ('0x10', 'inf', '-inf', 'Infinity', 'nan', 'NaN', '', '   ', 'abc', '1.2.3', '--1', 'e10'):
            with self.subTest(value=value), self.assertRaises(EdltError):
                converts(value)

    def test_non_string_inputs_reject(self):
        for value in (True, False, None, b'1.5', 1.5, 29, object()):
            with self.subTest(value=value), self.assertRaises(EdltError):
                converts(value)

    def test_whitespace_trims_but_raw_field_width_is_twenty(self):
        conversion = converts(' 0.29 ')
        self.assertEqual((conversion['mantissa'], conversion['exponent']), (28, -2))
        self.assertEqual(conversion['input'], ' 0.29 ')
        with self.assertRaises(EdltError):
            converts('123456789012345678901')
        with self.assertRaises(EdltError):
            converts(' 1234567890123456789 ')
        self.assertEqual(converts('12345678901234567890')['exact'], False)

    def test_dot_and_exponent_forms_accept(self):
        self.assertEqual(converts('5.')['stored_value'], '5')
        self.assertEqual(converts('.5')['stored_value'], '0.5')
        self.assertEqual(converts('+.5')['stored_value'], '0.5')
        self.assertEqual(converts('1E5')['stored_value'], '100000')
        self.assertEqual(converts('00.5')['stored_value'], '0.5')

    def test_unicode_digits_reject(self):
        for value in ('١.٥', '１.５'):
            with self.subTest(value=value), self.assertRaises(EdltError):
                converts(value)

    def test_gain_zero_becomes_one_but_offset_zero_stays_zero(self):
        for value in ('0', '0.0', '-0.0'):
            with self.subTest(value=value):
                self.assertEqual(converts(value, gain=True)['stored_value'], '1')
        self.assertEqual(converts('0')['stored_value'], '0')
        self.assertEqual((converts('0')['mantissa'], converts('0')['exponent']), (0, 0))


class MagnitudeLimitTests(unittest.TestCase):
    def test_large_but_storable_exponents_reduce(self):
        conversion = converts('1e100')
        self.assertEqual((conversion['mantissa'], conversion['exponent']), (1, 100))
        self.assertEqual(conversion['stored_value'], '1' + '0' * 100)
        conversion = converts('-1e100')
        self.assertEqual((conversion['mantissa'], conversion['exponent']), (-1, 100))
        conversion = converts('1e127')
        self.assertEqual((conversion['mantissa'], conversion['exponent']), (1, 127))

    def test_unstorable_exponents_fail_closed_as_edlt_error(self):
        for value in ('1e128', '1e200', '1e300', '-1e300', '9e307', '-9e307'):
            with self.subTest(value=value):
                with self.assertRaises(EdltError):
                    converts(value)

    def test_source_pinned_tiny_values_collapse_to_zero(self):
        for value in ('1e-51', '1e-130', '1e-300'):
            with self.subTest(value=value):
                conversion = converts(value)
                self.assertEqual((conversion['mantissa'], conversion['exponent']), (0, 0))
                self.assertEqual(conversion['stored_value'], '0')


class ToolkitCultureTests(unittest.TestCase):
    def test_source_pinned_evidence_matches_probe(self):
        evidence = json.loads(EVIDENCE.read_text())
        source = ROOT / evidence['probe']['source']
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), evidence['probe']['source_sha256'])
        self.assertEqual(evidence['profile'], {
            'toolkit_version': '1.18.0.2754',
            'logic_model_sha256': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
            'edlt_sha256': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3',
        })
        self.assertEqual(tuple(evidence['cultures']), MEASUREMENT_CULTURES[1:])

    def test_culture_decimal_and_group_separators_match_original(self):
        cases = (
            ('invariant', '1.5', '1.5'), ('invariant', '1,5', '15'),
            ('en-NZ', '1,234.5', '1234.5'), ('en-NZ', '1,,2', '12'),
            ('en-NZ', '1,.2', '1.2'),
            ('de-DE', '1,5', '1.5'), ('de-DE', '1.5', '15'),
            ('de-DE', '1.2,3', '12.3'),
            ('fr-FR', '1\u202f234,5', '1234.5'),
        )
        for culture, value, stored in cases:
            with self.subTest(culture=culture, value=value):
                conversion = converts(value, culture=culture)
                self.assertEqual(conversion['stored_value'], stored)
                self.assertEqual(conversion['culture'], culture)

    def test_culture_specific_invalid_forms_reject(self):
        cases = (
            ('invariant', ',1'), ('invariant', '1.2,3'),
            ('de-DE', '.5'), ('de-DE', '1,,2'),
            ('fr-FR', '1.5'), ('fr-FR', '1 234,5'), ('fr-FR', '1\u00a0234,5'),
        )
        for culture, value in cases:
            with self.subTest(culture=culture, value=value), self.assertRaises(EdltError):
                converts(value, culture=culture)

    def test_final_editor_blank_and_zero_rules(self):
        for culture in MEASUREMENT_CULTURES[1:]:
            with self.subTest(culture=culture):
                self.assertEqual(converts('', culture=culture, gain=True)['stored_value'], '1')
                self.assertEqual(converts('', culture=culture)['stored_value'], '1')
                self.assertEqual(converts('0', culture=culture, gain=True)['stored_value'], '1')
                self.assertEqual(converts('0', culture=culture)['stored_value'], '0')
        with self.assertRaises(EdltError):
            converts('', culture='canonical')

    def test_original_signed_byte_serialization_wraps_large_exponents(self):
        cases = {
            '1e128': (1, 128, -128, True, '0'),
            '1e300': (1, 300, 44, True, '1' + '0' * 44),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                conversion = converts(value, culture='invariant')
                actual = (conversion['mantissa'], conversion['editor_exponent'], conversion['exponent'],
                          conversion['exponent_wrapped'], conversion['display_value'])
                self.assertEqual(actual, expected)
        with self.assertRaises(EdltError):
            converts('1e128')

    def test_nonfinite_and_transitional_values_fail_safely(self):
        for culture in MEASUREMENT_CULTURES[1:]:
            for value in ('NaN', 'Infinity', '-Infinity', '-', '.', ','):
                with self.subTest(culture=culture, value=value), self.assertRaises(EdltError):
                    converts(value, culture=culture)

    def test_unknown_culture_rejects(self):
        with self.assertRaisesRegex(EdltError, 'culture'):
            converts('1', culture='en-US')


if __name__ == '__main__':
    unittest.main()
