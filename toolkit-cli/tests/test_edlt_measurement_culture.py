"""Invariant-culture input contract and magnitude limits for Measurement composites.

Issue #12 Phase 2: decimal Gain/Offset parsing, culture behavior, formatting.
The CLI parses invariant decimals only (dot separator, no locale grouping):
comma, hexadecimal, infinity, and underscore inputs are rejected, never
silently reinterpreted. Huge magnitudes follow the original lossy reduction
and fail closed with EdltError when the stored exponent leaves the
signed-byte range; a raw ``decimal`` error must never escape.
"""
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_measurement import measurement_composite


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

    def test_tiny_underflow_collapses_to_zero_current_code_only(self):
        # CURRENT-CODE-ONLY pin (no native citation yet): magnitudes far below
        # the fixed 50-decimal display collapse to stored zero and report the
        # established first-pass `exact` definition. TODO: confirm against
        # Toolkit 1.18 whether the original editor clamps, rounds, or rejects
        # these inputs; see issue #12 decimal Measurement behavior.
        for value in ('1e-130', '1e-300'):
            with self.subTest(value=value):
                conversion = converts(value)
                self.assertEqual((conversion['mantissa'], conversion['exponent']), (0, 0))
                self.assertEqual(conversion['stored_value'], '0')


if __name__ == '__main__':
    unittest.main()
