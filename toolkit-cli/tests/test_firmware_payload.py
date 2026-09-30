"""Synthetic payloads, literal original wire vectors and bounded offline plans."""
import hashlib
import json
import struct
import unittest
import zlib

from cbus_toolkit.firmware_payload import (
    describe_external_check_addresses, plan_download_payload, resolve_download_payload,
)


def suffix(body, *, vendor=0x166A, product=0x0501, version=0x0100, device=0x0100,
           signature=b'UFD', extra=b''):
    content = body + extra + struct.pack('<HHHH3sB', device, product, vendor, version, signature, 16 + len(extra))
    return content + struct.pack('<I', zlib.crc32(content) ^ 0xFFFFFFFF)


def prefixed(payload=b'\xde\xad\xbe\xef', *, address=8192, reserved=0, **kwargs):
    return suffix(struct.pack('<BBHI', 1, reserved, address // 1024, len(payload)) + payload, **kwargs)


class FirmwarePayloadTests(unittest.TestCase):
    def test_literal_original_suffix_writer_vector_normalizes_to_payload(self):
        data = bytes.fromhex('0100080004000000deadbeef000101056a16000155464410187ff0d3')
        self.assertEqual(prefixed(), data)
        result = resolve_download_payload(data, address=16384)
        self.assertTrue(result.supported)
        self.assertEqual(result.payload, b'\xde\xad\xbe\xef')
        self.assertEqual((result.requested_address, result.effective_address), (16384, 8192))
        self.assertEqual((result.payload_offset, result.suffix_bytes), (8, 16))
        plan = plan_download_payload(result, flash_size=65536, application_start=8192)
        self.assertEqual(plan['transfer']['program_header_hex'], '0100080004000000')
        self.assertEqual(plan['transfer']['data_chunk_lengths'], [4])
        self.assertFalse(plan['physical_execution_supported'])

    def test_raw_bytes_remain_unchanged_at_requested_address(self):
        data = struct.pack('<II', 0x20004000, 0x4101) + b'A' * 1025
        result = resolve_download_payload(data, address=16384)
        self.assertTrue(result.supported)
        self.assertIs(result.payload, data)
        self.assertEqual(result.effective_address, 16384)
        self.assertEqual(result.native_download_path, 'raw binary at -a')
        plan = plan_download_payload(result, flash_size=32768, application_start=16384)
        self.assertEqual(plan['transfer']['data_chunk_lengths'], [1024, 9])

    def test_suffix_only_uses_exact_binary_payload_and_command_line_address(self):
        body = struct.pack('<II', 0x20004000, 0x4101) + b'firmware'
        result = resolve_download_payload(suffix(body), address=16384)
        self.assertTrue(result.supported)
        self.assertEqual(result.payload, body)
        self.assertEqual(result.effective_address, 16384)
        self.assertFalse(result.container.has_ti_prefix)
        self.assertEqual(result.native_download_path, 'dfu-suffix-stripped binary at -a')
        plan = plan_download_payload(result, flash_size=16384 + len(body), application_start=16384)
        self.assertEqual(plan['transfer']['length'], len(body))

    def test_prefixed_external_request_retains_native_internal_opcode_and_is_refused(self):
        result = resolve_download_payload(prefixed(address=0), address=0, external=True)
        self.assertTrue(result.requested_external)
        self.assertFalse(result.effective_external)
        self.assertFalse(result.supported)
        self.assertIn('internal flash', result.issues[0])
        with self.assertRaisesRegex(ValueError, 'Unsupported firmware payload'):
            plan_download_payload(result, flash_size=65536, application_start=0)

    def test_external_raw_and_suffix_at_zero_only(self):
        for data in (b'ABCD', suffix(b'ABCD')):
            with self.subTest(data_bytes=len(data)):
                result = resolve_download_payload(data, address=0, external=True)
                self.assertTrue(result.supported)
                self.assertTrue(result.effective_external)
                plan = plan_download_payload(result, flash_size=65536, application_start=0)
                self.assertEqual(plan['transfer']['program_header_hex'], '0800000004000000')
                nonzero = resolve_download_payload(data, address=65536, external=True)
                self.assertFalse(nonzero.supported)
                self.assertIn('Nonzero external', nonzero.issues[0])

    def test_identity_checks_are_exact_and_device_bcd_is_not_a_version_gate(self):
        for kwargs in ({'vendor': 1}, {'product': 2}, {'vendor': 65535}, {'product': 65535}):
            result = resolve_download_payload(prefixed(**kwargs), address=8192)
            self.assertFalse(result.supported)
            self.assertIn('ID mismatch', result.issues[0])
        for device in (0, 0x1234, 65535):
            self.assertTrue(resolve_download_payload(prefixed(device=device), address=8192).supported)
        self.assertTrue(resolve_download_payload(prefixed(vendor=1, product=2), address=8192,
                                                 vendor_id=1, product_id=2).supported)

    def test_damaged_recognizable_containers_report_native_raw_fallback_but_refuse(self):
        crc = prefixed()[:-4] + b'\0' * 4
        for data in (crc, prefixed(signature=b'FOO'), suffix(b'ABCD')[:-4] + b'\0' * 4):
            with self.subTest(data_bytes=len(data)):
                result = resolve_download_payload(data, address=8192)
                self.assertFalse(result.supported)
                self.assertEqual(result.native_download_path, 'raw binary at -a')
                self.assertEqual(result.payload, data)
                self.assertIn('fallback is refused', result.issues[0])

    def test_native_valid_but_unsupported_format_is_not_silently_reinterpreted(self):
        for data, issue in ((prefixed(reserved=1), 'reserved'),
                            (prefixed(version=0x0110), 'DFU1.0'),
                            (prefixed(extra=b'12345678'), 'sixteen-byte'),
                            (prefixed(payload=b''), 'Empty'),
                            (suffix(b''), 'Empty')):
            with self.subTest(issue=issue):
                result = resolve_download_payload(data, address=8192)
                self.assertFalse(result.supported)
                self.assertTrue(any(issue in text for text in result.issues))

    def test_effective_prefix_address_controls_application_and_capacity_bounds(self):
        result = resolve_download_payload(prefixed(address=8192), address=16384)
        with self.assertRaisesRegex(ValueError, 'address must be an integer'):
            plan_download_payload(result, flash_size=65536, application_start=16384)
        with self.assertRaisesRegex(ValueError, 'range exceeds'):
            plan_download_payload(result, flash_size=8195, application_start=8192)
        self.assertTrue(resolve_download_payload(prefixed(), address=3).supported)
        self.assertFalse(resolve_download_payload(b'ABCD', address=3).supported)
        self.assertFalse(resolve_download_payload(b'ABCD', address=65536 * 1024).supported)

    def test_transfer_sequence_wrap_remains_refused(self):
        result = resolve_download_payload(b'A' * 400000, address=8192)
        with self.assertRaisesRegex(ValueError, 'wrap'):
            plan_download_payload(result, flash_size=1024 * 1024, application_start=8192, transfer_size=11)

    def test_receipts_and_default_repr_never_expose_payload(self):
        body = b'PRIVATE-BYTES-ONLY-IN-MEMORY'
        result = resolve_download_payload(suffix(body), address=8192)
        receipt = result.as_dict()
        rendered = json.dumps(receipt)
        self.assertNotIn(body.decode(), rendered)
        self.assertNotIn(body.hex(), rendered)
        self.assertNotIn(body.decode(), repr(result))
        self.assertEqual(receipt['payload_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(receipt['input_sha256'], hashlib.sha256(suffix(body)).hexdigest())
        for key in ('physical_execution_supported', 'authenticity_verified', 'device_verified', 'firmware_written'):
            self.assertFalse(receipt[key])

    def test_malformed_argument_types_fail_before_interpretation(self):
        for data in ('text', bytearray(b'x'), None):
            with self.assertRaises(ValueError):
                resolve_download_payload(data, address=0)
        for kwargs in ({'address': True}, {'address': -1}, {'address': 1 << 32},
                       {'address': 0, 'external': 1}, {'address': 0, 'vendor_id': None},
                       {'address': 0, 'product_id': True}):
            with self.assertRaises(ValueError):
                resolve_download_payload(b'ABCD', **kwargs)
        with self.assertRaises(ValueError):
            plan_download_payload({}, flash_size=65536, application_start=0)
        self.assertFalse(resolve_download_payload(b'', address=0).supported)

    def test_external_check_source_vectors_preserve_address_ambiguity(self):
        # Original native_dfu_probe.run uses address 0x20000 in both wrappers.
        # Their lengths differ in that capture; use each literal length here.
        blank = describe_external_check_addresses(address=0x20000, length=2048)
        erase = describe_external_check_addresses(address=0x20000, length=0x20000)
        self.assertEqual(blank['blank_check_header_hex'], '0a00020000080000')
        self.assertEqual(erase['erase_verify_check_header_hex'], '0a00800000000200')
        self.assertTrue(blank['ambiguous'])
        self.assertFalse(blank['physical_execution_supported'])
        zero = describe_external_check_addresses(address=0, length=65536)
        self.assertEqual(zero['blank_check_header_hex'], zero['erase_verify_check_header_hex'])
        self.assertFalse(zero['ambiguous'])
        for kwargs in ({'address': 1, 'length': 1}, {'address': True, 'length': 1},
                       {'address': 0, 'length': 0}, {'address': 65536 * 1024, 'length': 1}):
            with self.assertRaises(ValueError):
                describe_external_check_addresses(**kwargs)


if __name__ == '__main__':
    unittest.main()
