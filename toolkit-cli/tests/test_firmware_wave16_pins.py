"""Wave16 offline pins for eDLT download payload/authenticity guards (P10.01 #64).

Narrow scope: only cbus_toolkit.firmware_payload. No hardware, no transport.
Pins guards with zero prior test refs (verified 2026-10-15):
  - receipt source provenance (dfuprog/dll hashes, dispatcher addrs)
  - plan receipt format/scope and unwritten flags
  - oversize-input refusal before interpretation
  - external CHECK descriptor ambiguity without device claim
"""
import json
import unittest
from unittest import mock

from cbus_toolkit import firmware_payload
from cbus_toolkit.firmware_payload import (
    describe_external_check_addresses,
    plan_download_payload,
    resolve_download_payload,
)


class FirmwareWave16PinsTests(unittest.TestCase):
    def test_wave16_receipt_provenance_and_no_authenticity_claim(self):
        result = resolve_download_payload(b'ABCD', address=8192)
        self.assertTrue(result.supported)
        receipt = result.as_dict()
        self.assertEqual(receipt['format'], 'cbus-edlt-download-payload-v1')
        source = receipt['source']
        self.assertEqual(source['dfuprog_sha256'], firmware_payload.DFUPROG_SHA256)
        self.assertEqual(source['dfu_dll_sha256'], firmware_payload.DFU_DLL_SHA256)
        self.assertEqual(source['dispatcher'], '0x401B50')
        self.assertEqual(source['prefixed_wrapper'], '0x402400')
        self.assertEqual(source['image_reader'], '0x1000E940')
        self.assertEqual(source['prefixed_download'], '0x10010280')
        for key in ('physical_execution_supported', 'authenticity_verified',
                    'device_verified', 'firmware_written'):
            self.assertFalse(receipt[key], key)
        self.assertIn('Offline payload interpretation', receipt['scope'])
        self.assertNotIn('ABCD', json.dumps(receipt))

    def test_wave16_download_plan_stays_offline_and_unwritten(self):
        result = resolve_download_payload(b'ABCD', address=8192)
        plan = plan_download_payload(result, flash_size=65536, application_start=8192)
        self.assertEqual(plan['format'], 'cbus-edlt-download-payload-plan-v1')
        self.assertFalse(plan['physical_execution_supported'])
        self.assertFalse(plan['firmware_written'])
        self.assertIn('TI-prefixed native packet', plan['scope'])
        embedded = plan['payload']
        self.assertEqual(embedded['format'], 'cbus-edlt-download-payload-v1')
        self.assertFalse(embedded['authenticity_verified'])
        self.assertFalse(embedded['device_verified'])

    def test_wave16_oversize_inputs_refused_before_interpretation(self):
        with mock.patch.object(firmware_payload, 'MAX_IMAGE_SIZE', 4):
            with self.assertRaises(ValueError):
                resolve_download_payload(b'ABCDE', address=0)
        with self.assertRaises(ValueError):
            describe_external_check_addresses(address=0, length=67108864 + 1)

    def test_wave16_external_check_descriptor_without_device_claim(self):
        nonzero = describe_external_check_addresses(address=0x20000, length=2048)
        self.assertEqual(nonzero['format'], 'cbus-edlt-external-check-address-v1')
        self.assertNotEqual(nonzero['blank_check_header_hex'],
                            nonzero['erase_verify_check_header_hex'])
        self.assertTrue(nonzero['ambiguous'])
        self.assertEqual(nonzero['source']['dfu_dll_sha256'],
                         firmware_payload.DFU_DLL_SHA256)
        self.assertEqual(nonzero['source']['blank_check'], '0x1000F8C0')
        self.assertEqual(nonzero['source']['erase'], '0x1000F9C0')
        self.assertFalse(nonzero['physical_execution_supported'])
        self.assertFalse(nonzero['device_verified'])
        self.assertIn('Original host-side encodings only', nonzero['scope'])


if __name__ == '__main__':
    unittest.main()
