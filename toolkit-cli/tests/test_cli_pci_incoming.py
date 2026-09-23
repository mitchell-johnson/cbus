"""Received-frame CLI: literal original input, no inferred identity or I/O."""
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from tests import test_cli_pci_routing as outgoing_tests

ROOT = Path(__file__).resolve().parents[1]


class IncomingRoutingCLITests(unittest.TestCase):
    execute = outgoing_tests.RoutingCLITests.execute

    def test_original_06_and_86_literals_retain_raw_route_and_cal(self):
        for header, raw in ((6, '061410021504810436\r'), (134, '8614100215048104B6\r')):
            status, result = self.execute(['--compact', 'pci-route', 'receive', raw.encode().hex()])
            self.assertEqual(status, 0)
            self.assertEqual(result['format'], 'cbus-received-cal-route-v1')
            self.assertEqual(result['header'], header)
            self.assertEqual(result['outer_source_byte'], 20)
            self.assertEqual(result['destination_byte'], 16)
            self.assertEqual(result['route_entries'], [21, 4])
            self.assertEqual(result['address_path'], [20, 21, 4])
            self.assertEqual(result['cal_hex'], '8104')
            self.assertEqual(result['wire_text'], raw)
            self.assertEqual(result['raw_hex'], raw.encode().hex().upper())
            self.assertTrue(result['checksum_valid'])
            for field in ('io_performed', 'device_origin_verified', 'logical_network_resolved', 'programming_mode_inferred'):
                self.assertFalse(result[field])
            for field in ('unit', 'source', 'network', 'requested', 'reply_correlated'):
                self.assertNotIn(field, result)

    def test_original_zero_route_marker_is_not_promoted_to_programming_or_identity(self):
        # Sealed original20-case pilot, dl-one; public CRC validation succeeded.
        raw = '86141001008104D0\r'
        status, result = self.execute(['pci-route', 'receive', raw.encode().hex()])
        self.assertEqual(status, 0)
        self.assertEqual(result['address_path'], [20, 0])
        self.assertEqual(result['route_count'], 1)
        self.assertFalse(result['programming_mode_inferred'])
        self.assertFalse(result['device_origin_verified'])

    def test_original_maximum_supported_single_cal_frame(self):
        fixture = json.loads((ROOT / 'research/fixtures/pci-incoming-original-vectors.json').read_text())
        case = next(row for row in fixture['cases'] if row['input']['id'] == 'max-one-cal-six-route')
        raw = case['input']['raw'] + '\r'
        self.assertEqual(len(raw), 87)
        status, result = self.execute(['pci-route', 'receive', raw.encode().hex()])
        self.assertEqual(status, 0)
        self.assertEqual(result['route_entries'], [21, 22, 23, 24, 25, 4])
        self.assertEqual(result['cal_hex'], 'BFFF' + bytes(range(30)).hex().upper())
        self.assertEqual(result['wire_text'], raw)

    def test_malformed_or_oversized_arguments_reject_before_dispatch(self):
        cases = [['pci-route', 'receive', value] for value in ('', '0', '00 00', 'g0', '00' * 88)]
        valid = ['pci-route', 'receive', '3836313431303032313530343831303442360D']
        cases += [valid + ['--checksum'], valid + ['--host', '127.0.0.1'], valid + ['--confirmation', 'g']]
        for arguments in cases:
            with self.subTest(arguments=arguments), patch.object(cli, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    cli.main(arguments)
                self.assertEqual(stopped.exception.code, 2)
                run.assert_not_called()

    def test_invalid_frames_do_not_fall_back_strip_controls_or_connect(self):
        raw = b'8614100215048104B6\r'
        cases = [b'\\461E12140421044Dg\r', b'8104\r', raw[:-1], raw + b'\n', raw + b'\r',
                 raw[:-3] + b'00\r', raw[:4] + b'\x11' + raw[4:], b' ' + raw,
                 raw[:-1] + b'g\r', b'8614100715048104B1\r']
        for bad in cases:
            with self.subTest(raw=bad):
                status, result = self.execute(['pci-route', 'receive', bad.hex()])
                self.assertEqual(status, 1)
                self.assertIn('error', result)
                self.assertNotIn('wire_text', result)


if __name__ == '__main__':
    unittest.main()
