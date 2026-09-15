"""Offline DFU CLI records, malformed containers and explicit range guards."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib


class DFUCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        process = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'firmware', *map(str, args)],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, status, process.stdout + process.stderr)
        return json.loads(process.stdout or process.stderr)

    def test_status_and_command_decoding_preserves_device_errors_and_ambiguity(self):
        status = self.cli('dfu-status', '00 05 00 01 02 00')
        self.assertEqual(status['poll_timeout_ms'], 65541)
        self.assertEqual(status['state_name'], 'dfuIDLE')
        self.assertTrue(status['read_only'])
        error = self.cli('dfu-status', '030000000a00', status=1)
        self.assertEqual(error['status_name'], 'errWRITE')
        self.assertEqual(error['native_error'], -12)
        command = self.cli('dfu-command', '0100080000050000')
        self.assertEqual((command['operation'], command['address'], command['length']), ('program', 8192, 1280))
        ambiguous = self.cli('dfu-command', '0a00010000000100', status=1)
        self.assertFalse(ambiguous['supported'])
        self.assertIsNone(ambiguous['address'])
        self.assertIn('conflicting', ambiguous['limitation'])
        for action, value in (('dfu-status', '00'), ('dfu-command', 'zz'), ('dfu-command', '00'),
                              ('dfu-command', 'ab' * 129)):
            self.assertIn('error', self.cli(action, value, status=1))

    def test_container_validation_is_offline_and_checks_expected_identity(self):
        payload = b'Synthetic opaque payload; not firmware'
        prefix = struct.pack('<BBHI', 1, 0, 8, len(payload))
        suffix = struct.pack('<HHHH3sB', 0x0100, 0x0501, 0x166a, 0x0100, b'UFD', 16)
        contents = prefix + payload + suffix
        contents += struct.pack('<I', zlib.crc32(contents) ^ 0xffffffff)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.dfu'
            path.write_bytes(contents)
            result = self.cli('dfu-inspect', path, '--vendor-id', '0x166a', '--product-id', '0x0501')
            self.assertTrue(result['valid'])
            self.assertTrue(result['supported'])
            self.assertEqual((result['address'], result['payload_length']), (8192, len(payload)))
            self.assertFalse(result['device_verified'])
            self.assertFalse(result['firmware_written'])
            mismatch = self.cli('dfu-inspect', path, '--product-id', '0x0502', status=1)
            self.assertIn('Product ID mismatch', mismatch['issues'])
            self.assertEqual(path.read_bytes(), contents)
            path.write_bytes(contents[:-1] + bytes([contents[-1] ^ 1]))
            self.assertIn('DFU checksum mismatch', self.cli('dfu-inspect', path, status=1)['issues'])
            path.write_bytes(b'not a DFU image')
            self.assertFalse(self.cli('dfu-inspect', path, status=1)['valid'])
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_plan_uses_explicit_capacity_and_rejects_unverified_external_address(self):
        result = self.cli('dfu-plan', '--length', 1280, '--address', '0x2000',
                          '--flash-size', '0x40000', '--application-start', '0x2000')
        self.assertEqual(result['data_chunk_lengths'], [1024, 256])
        self.assertEqual(result['program_header_hex'], '0100080000050000')
        self.assertEqual(result['read_header_hex'], '0200080000050000')
        self.assertEqual(result['terminal_dnload_length'], 0)
        external = self.cli('dfu-plan', '--length', 64, '--address', 0,
                            '--flash-size', 65536, '--application-start', 0, '--external')
        self.assertTrue(external['external'])
        self.assertEqual(external['program_header_hex'], '0800000040000000')
        for address, length, extra in ((1024, 64, ['--external']), (1023, 64, []), (64512, 2048, [])):
            error = self.cli('dfu-plan', '--length', length, '--address', address,
                             '--flash-size', 65536, '--application-start', 0, *extra, status=1)
            self.assertIn('error', error)

    def test_descriptor_files_are_validated_without_transport_access(self):
        device = bytes.fromhex('12010002000000406a160105341201020301')
        configuration = bytes.fromhex('09021b0001010080320904000000fe010200092107e80300040001')
        with tempfile.TemporaryDirectory() as folder:
            dev, config = Path(folder) / 'device.bin', Path(folder) / 'configuration.bin'
            dev.write_bytes(device)
            config.write_bytes(configuration)
            result = self.cli('dfu-descriptors', dev, config)
            self.assertEqual((result['vendor_id'], result['product_id'], result['interface']), (0x166a, 0x0501, 0))
            self.assertEqual(result['transfer_size'], 1024)
            self.assertTrue(result['read_only'])
            self.assertFalse(result['physical_device_verified'])
            self.assertEqual(dev.read_bytes(), device)
            self.assertEqual(config.read_bytes(), configuration)
            for data in (configuration[:9] + b'\0' + configuration[10:],
                         configuration[:23] + b'\0\0' + configuration[25:],
                         configuration[:18]):
                config.write_bytes(data)
                self.assertIn('error', self.cli('dfu-descriptors', dev, config, status=1))
            config.write_bytes(configuration)
            dev.write_bytes(device + b'\0')
            self.assertIn('eighteen bytes', self.cli('dfu-descriptors', dev, config, status=1)['error'])


if __name__ == '__main__':
    unittest.main()
