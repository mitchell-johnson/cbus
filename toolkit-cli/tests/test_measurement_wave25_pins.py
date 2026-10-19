"""Wave25 offline pins for KEYGL5 Measurement composite guards (P6).

Pins previously unasserted fields/messages in edlt_measurement.py:
blank_defaulted, gain_zero_normalized, 20-character limit, finite guard.
Zero prior refs verified via grep for each pinned string.
Pure offline: no broker, hardware, or PP fixtures.
"""
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_measurement import measurement_composite


class MeasurementWave25PinTests(unittest.TestCase):
    def test_blank_whitespace_defaults_with_flag(self):
        conversion = measurement_composite('   ', culture='en-NZ')
        self.assertTrue(conversion['blank_defaulted'])
        self.assertEqual(conversion['stored_value'], '1')
        self.assertEqual((conversion['mantissa'], conversion['exponent']), (1, 0))

    def test_gain_zero_normalizes_with_flag(self):
        with_gain = measurement_composite('0', gain=True)
        self.assertTrue(with_gain['gain_zero_normalized'])
        self.assertEqual((with_gain['mantissa'], with_gain['exponent']), (1, 0))
        without_gain = measurement_composite('0')
        self.assertFalse(without_gain['gain_zero_normalized'])
        self.assertEqual((without_gain['mantissa'], without_gain['exponent']), (0, 0))

    def test_overlong_composite_rejected(self):
        with self.assertRaisesRegex(EdltError, '20-character'):
            measurement_composite('1' * 21)

    def test_overflow_composite_rejected_as_nonfinite(self):
        with self.assertRaisesRegex(EdltError, 'finite'):
            measurement_composite('1e999')


if __name__ == '__main__':
    unittest.main()
