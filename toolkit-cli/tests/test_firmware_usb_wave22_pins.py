"""Wave22 offline pins for USB DFU coordinator guards (P10).

Narrow scope: only ``cbus_toolkit.firmware_usb.run_usb_dfu``. Every call
injects a fake backend; no host USB is enumerated. Pins coordinator guards
with zero prior test refs (verified 2026-10-16 via ``grep -rnF`` over
``tests/`` for the exact literals below):

* result envelope ``cbus-usb-dfu-result-v1``
* ``endpoint_trace`` result key
* ``timeout_scope`` result key
* error-type literals ``USBOperationFailure`` / ``USBReleaseFailure``
* scope literals ``One explicitly claimed USB DFU operation; no automatic
  erase, reset or retry``, ``DFU operation deadline and
  per-inspection-transfer timeout; acquisition and release are not deadline
  bounded``, ``One DFU operation over a claimed USB Endpoint0 lease;
  hardware acceptance is not established``
"""

from __future__ import annotations

import unittest

from cbus_toolkit.dfu_transport import parse_descriptors
from cbus_toolkit.firmware_usb import run_usb_dfu
from tests.test_usb_dfu import ClaimedBackend
from tests.test_usb_inspection import CONFIG, DEVICE


def run(backend, operation='inspect', **options):
    defaults = dict(bus=1, address=7, expected_serial='ABC123',
                    descriptor=parse_descriptors(DEVICE, CONFIG),
                    release_policy='reset-first-alternate',
                    flash_size=262144, application_start=8192,
                    backend=backend)
    defaults.update(options)
    return run_usb_dfu(operation, **defaults)


class FirmwareUSBWave22PinsTests(unittest.TestCase):
    def test_wave22_result_envelope_and_offline_scope(self):
        backend = ClaimedBackend()
        result = run(backend)
        self.assertTrue(result['complete'])
        self.assertEqual(result['format'], 'cbus-usb-dfu-result-v1')
        self.assertEqual(result['scope'],
                         'One explicitly claimed USB DFU operation; '
                         'no automatic erase, reset or retry')
        self.assertEqual(result['timeout_scope'],
                         'DFU operation deadline and '
                         'per-inspection-transfer timeout; acquisition and '
                         'release are not deadline bounded')
        self.assertFalse(result['physical_device_verified'])
        self.assertTrue(result['operation_invoked'])
        self.assertIsNone(result['error'])
        self.assertEqual(result['errors'], [])
        self.assertFalse(result['preflight']['transport_acquired'])
        self.assertFalse(result['preflight']['device_verified'])

    def test_wave22_endpoint_trace_and_transfer_scope(self):
        backend = ClaimedBackend()
        result = run(backend)
        self.assertTrue(result['complete'])
        trace = result['endpoint_trace']
        self.assertIsInstance(trace, list)
        self.assertGreater(len(trace), 0)
        for row in trace:
            self.assertIsInstance(row, dict)
            for key in ('bmRequestType', 'bRequest', 'wValue', 'wIndex',
                        'wLength', 'timeout_ms', 'transferred'):
                self.assertIn(key, row)
        self.assertEqual(
            result['transfer']['scope'],
            'One DFU operation over a claimed USB Endpoint0 lease; '
            'hardware acceptance is not established')
        self.assertFalse(result['transfer']['physical_device_verified'])

    def test_wave22_interruption_pins_usb_operation_failure(self):
        def fault(backend, fixture, row, normal):
            if row.get('out_data') == '41424344':
                raise KeyboardInterrupt('stop')
            return normal

        backend = ClaimedBackend(fault=fault)
        with self.assertRaises(KeyboardInterrupt) as caught:
            run(backend, 'program', data=b'ABCD', address_offset=8192)
        interruption = caught.exception
        self.assertIs(interruption.args[0], 'stop')
        result = interruption.usb_dfu_evidence
        self.assertFalse(result['complete'])
        self.assertTrue(result['operation_invoked'])
        self.assertEqual(result['error'],
                         'DFU operation interrupted: KeyboardInterrupt')
        kinds = {(row['stage'], row['type']) for row in result['errors']}
        self.assertIn(('transfer', 'USBOperationFailure'), kinds)
        self.assertIn(('transfer', 'KeyboardInterrupt'), kinds)

    def test_wave22_release_failures_pin_usb_release_failure(self):
        backend = ClaimedBackend(release_error=OSError('release failed'),
                                 close_error=OSError('close failed'))
        result = run(backend, 'program', data=b'ABCD', address_offset=8192)
        self.assertFalse(result['complete'])
        self.assertTrue(result['transfer']['complete'])
        self.assertTrue(result['transfer']['peer_verified'])
        self.assertFalse(result['release']['complete'])
        self.assertEqual(result['error'], 'release failed')
        self.assertEqual(
            [(row['stage'], row['type'], row['error'])
             for row in result['errors']],
            [('release', 'USBReleaseFailure', 'release failed'),
             ('close', 'USBReleaseFailure', 'close failed')])


if __name__ == '__main__':
    unittest.main()
