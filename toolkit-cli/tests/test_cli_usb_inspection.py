"""USB CLI routing through real PyUSB and an independent descriptor backend."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

import usb.core

from cbus_toolkit.cli import main
from tests.test_usb_inspection import FakeBackend, USBFixture


class USBInspectionCLITests(unittest.TestCase):
    def cli(self, backend, *args, status=0):
        out, err = io.StringIO(), io.StringIO()
        with patch('usb.backend.libusb1.get_backend', return_value=backend), redirect_stdout(out), redirect_stderr(err):
            code = main(['firmware', *map(str, args)])
        self.assertEqual(code, status, out.getvalue() + err.getvalue())
        self.assertNotIn('FORBIDDEN', backend.events)
        return json.loads(out.getvalue() or err.getvalue())

    def test_listing_opens_nothing_and_preserves_enumeration_limit(self):
        backend = FakeBackend([USBFixture(), USBFixture(address=8)])
        result = self.cli(backend, 'usb-list')
        self.assertTrue(result['complete'])
        self.assertEqual([row['address'] for row in result['devices']], [7, 8])
        self.assertEqual(backend.open_count, 0)
        self.assertEqual(backend.requests, [])
        partial = self.cli(backend, 'usb-list', '--max-devices', 1, status=1)
        self.assertFalse(partial['complete'])
        self.assertEqual(len(partial['devices']), 1)
        self.assertEqual(backend.open_count, 0)

    def test_explicit_selection_reads_only_standard_in_and_matches_serial(self):
        backend = FakeBackend([USBFixture(address=6), USBFixture(), USBFixture(address=8)])
        result = self.cli(backend, 'usb-inspect', '--bus', 1, '--address', 7,
                          '--expected-serial', 'ABC123', '--timeout', .025)
        self.assertTrue(result['complete'])
        self.assertTrue(result['expected_serial_matches'])
        self.assertTrue(result['dfu_profile_supported'])
        self.assertFalse(result['exclusive_ownership'])
        self.assertEqual(result['strings']['serial'], 'ABC123')
        self.assertEqual(result['active_configuration'], 1)
        self.assertEqual((backend.open_count, backend.close_count), (1, 1))
        self.assertEqual(len(backend.requests), 13)
        self.assertEqual([(r['bmRequestType'], r['bus'], r['address'], r['timeout_ms'])
                          for r in backend.requests], [(0x80, 1, 7, 25)] * 13)
        self.assertEqual([r['bRequest'] for r in backend.requests], [6, 8] + [6] * 10 + [8])

    def test_missing_ambiguous_and_invalid_selectors_cannot_open_a_device(self):
        for backend, args in ((FakeBackend([]), ('--bus', 1, '--address', 7)),
                              (FakeBackend([USBFixture(), USBFixture()]), ('--bus', 1, '--address', 7)),
                              (FakeBackend(), ('--bus', 1, '--address', 0)),
                              (FakeBackend(), ('--bus', 256, '--address', 7))):
            result = self.cli(backend, 'usb-inspect', *args, status=1)
            self.assertIn('error', result)
            self.assertEqual((backend.open_count, backend.close_count), (0, 0))
            self.assertEqual(backend.requests, [])

    def test_partial_transfer_serial_mismatch_and_close_error_remain_failed_results(self):
        def short(_backend, _fixture, row, response):
            return response[:-1] if row['bRequest'] == 6 and row['wValue'] == 0x303 and row['wLength'] > 2 else response
        for backend, extra in ((FakeBackend(fault=short), ()),
                               (FakeBackend(), ('--expected-serial', 'wrong')),
                               (FakeBackend(close_error=usb.core.USBError('close failed')), ())):
            result = self.cli(backend, 'usb-inspect', '--bus', 1, '--address', 7, *extra, status=1)
            self.assertFalse(result['complete'])
            self.assertIsNotNone(result['error'])
            self.assertTrue(result['trace'])
            self.assertIsNotNone(result['device_descriptor'])
            self.assertEqual((backend.open_count, backend.close_count), (1, 1))
        self.assertEqual(result['strings']['serial'], 'ABC123')
        self.assertIsNotNone(result['close_error'])
        self.assertFalse(result['resources_closed'])

    def test_unconfigured_device_is_successful_inspection_with_no_readiness_claim(self):
        backend = FakeBackend([USBFixture(active_configuration=0)])
        result = self.cli(backend, 'usb-inspect', '--bus', 1, '--address', 7)
        self.assertTrue(result['complete'])
        self.assertFalse(result['dfu_profile_supported'])
        self.assertFalse(result['active_alternate_setting_verified'])
        self.assertFalse(result['exclusive_ownership'])
        self.assertEqual(result['active_configuration'], 0)
        self.assertIn('unconfigured', result['unsupported_reason'])


if __name__ == '__main__':
    unittest.main()
