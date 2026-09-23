"""Native Windows acceptance for Toolkit's default CSV text conversion."""
import hashlib
import os
import unittest

from cbus_toolkit.toolkit_database_csv import DatabaseCSV
from cbus_toolkit.toolkit_database_csv_cli import _encode_output
from cbus_toolkit.windows_csv_encoding import WindowsToolkitCSVEncoder


class WindowsCSVEncodingTests(unittest.TestCase):
    def test_windows_is_required(self):
        if os.name != 'nt':
            with self.assertRaisesRegex(RuntimeError, 'requires Windows'):
                WindowsToolkitCSVEncoder()
        else:
            self.assertGreater(WindowsToolkitCSVEncoder().code_page, 0)

    @unittest.skipUnless(os.name == 'nt' and
                         os.environ.get('CBUS_WINDOWS_CSV_ENCODING'),
                         'Set CBUS_WINDOWS_CSV_ENCODING on an owned Windows host')
    def test_native_acp_conversion_preserves_delphi_utf16_unit_behavior(self):
        encoder = WindowsToolkitCSVEncoder()
        text = 'ASCII\r\nEuro €\r\nEmoji 💡\r\n'
        encoded = encoder.encode(text)
        self.assertEqual(
            encoder.encode('ASCII\r\nEuro €\r\n'),
            'ASCII\r\nEuro €\r\n'.encode('mbcs', errors='replace'))
        if encoder.code_page == 1252:
            # Delphi passes an explicit two-unit UTF-16 length. CP1252 replaces
            # each half of the non-BMP surrogate pair independently.
            self.assertEqual(
                encoded, b'ASCII\r\nEuro \x80\r\nEmoji ??\r\n')
        self.assertFalse(encoded.startswith((b'\xef\xbb\xbf', b'\xff\xfe')))
        self.assertEqual(encoder.encode(''), b'')
        for value in (None, 1, 'bad\0value', '\ud800'):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                encoder.encode(value)

    @unittest.skipUnless(os.name == 'nt' and
                         os.environ.get('CBUS_WINDOWS_CSV_ENCODING'),
                         'Set CBUS_WINDOWS_CSV_ENCODING on an owned Windows host')
    def test_production_output_boundary_emits_native_bytes_and_evidence(self):
        report = DatabaseCSV(
            ('tag_name',), ('Tag Name,', '"灯, ""💡""",'), 1)
        payload, evidence = _encode_output(report, True)
        if evidence['windows_code_page'] == 1252:
            self.assertEqual(payload, b'Tag Name,\r\n"?, ""??""",\r\n\r\n')
        self.assertEqual(evidence['mode'], 'toolkit_native')
        self.assertEqual(evidence['encoding'], 'windows-acp')
        self.assertEqual(evidence['wide_char_to_multi_byte_flags'], 0)
        self.assertTrue(evidence['original_encoding_equivalent'])
        self.assertFalse(evidence['bom'])
        self.assertEqual(evidence['bytes'], len(payload))
        self.assertEqual(evidence['sha256'], hashlib.sha256(payload).hexdigest())


if __name__ == '__main__':
    unittest.main()
