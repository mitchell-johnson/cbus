"""Actual CLI and owned loopback boundaries for raw routed IDENTIFY."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import build_parser, main
from cbus_toolkit import pci_routed_identify as core
from cbus_toolkit import pci_routed_identify_cli as helper
import test_pci_routed_recall as peers


class RoutedIdentifyCLITests(unittest.TestCase):
    def invoke(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                status = main(arguments)
            except SystemExit as exc:
                status = exc.code
        return status, output.getvalue(), error.getvalue()

    def arguments(self, port=10001, *, prefix=(), extra=(), routed=True):
        path = (['--bridge', '20', '--bridge', '21', '--expected-source', '20',
                 '--expected-route', '21', '--expected-route', '4'] if routed
                else ['--expected-source', '4'])
        return ['--compact', 'pci', '--host', '127.0.0.1', '--port', str(port), *prefix,
                'routed-identify', '4', '0x01', '--expected-destination', '16', *path, *extra]

    def test_owned_peer_both_orders_checksum_modes_and_raw_payload(self):
        for checksum, wire in ((False, b'\\46141215042101g\r'), (True, b'\\4614121504210159g\r')):
            frame = b'8614100215048201A513\r'
            joined = frame + b'g.' if checksum else b'g.' + frame
            peer = peers.Peer(wire, [joined[:7], joined[7:]])
            try:
                with patch.object(core.socket, 'getaddrinfo', side_effect=AssertionError('No resolver')):
                    code, stdout, stderr = self.invoke(self.arguments(peer.port,
                        prefix=('--checksum',) if checksum else (), extra=('--expected-count', '1')))
                self.assertEqual((code, stderr), (0, ''))
                result = json.loads(stdout)
                self.assertEqual(result['requested'], {'unit': 4, 'attribute': 1, 'expected_count': 1,
                    'bridges': [20, 21], 'addressing': 'direct'})
                self.assertEqual(result['sent_hex'], wire.hex().upper())
                self.assertEqual((result['actual_count'], result['data_hex']), (1, 'A5'))
                self.assertFalse(result['original_typed_getter_used'])
                self.assertFalse(result['original_short_matcher_used'])
                self.assertFalse(result['physical_delivery_verified'])
            finally:
                peer.finish()

    def test_zero_byte_reply_with_unspecified_or_exact_zero_count(self):
        for extra in ((), ('--expected-count', '0')):
            peer = peers.Peer(b'\\4604002101g\r', [b'g.860410008101E4\r'])
            try:
                code, stdout, stderr = self.invoke(self.arguments(peer.port, routed=False, extra=extra))
                self.assertEqual((code, stderr), (0, ''))
                result = json.loads(stdout)
                self.assertEqual((result['actual_count'], result['data_hex']), (0, ''))
                self.assertEqual(result['expected_count'], 0 if extra else None)
            finally:
                peer.finish()

    def test_invalid_count_or_missing_path_fails_in_parser(self):
        invalid = [self.arguments()[:self.arguments().index('--expected-source')],
                   self.arguments(extra=('--addressing', 'programming'))]
        invalid += [self.arguments(extra=('--expected-count', count)) for count in ('31', '-1', '1.0', '0x20')]
        with patch.object(core.socket, 'socket', side_effect=AssertionError('No socket')):
            for args in invalid:
                code, stdout, _ = self.invoke(args)
                self.assertEqual((code, stdout), (2, ''))

    def test_semantic_validation_has_no_socket_or_resolver(self):
        variants = [self.arguments(prefix=('--local-unit', '4')),
                    self.arguments(extra=('--expected-route', '5')),
                    self.arguments(extra=('--max-events', '4097')),
                    self.arguments(extra=('--max-received-bytes', '1048577')),
                    self.arguments(extra=tuple(v for _ in range(5) for v in ('--bridge', '5')))]
        host = self.arguments(); host[host.index('--host') + 1] = 'localhost'; variants.append(host)
        with patch.object(core.socket, 'socket', side_effect=AssertionError('No socket')), \
             patch.object(core.socket, 'getaddrinfo', side_effect=AssertionError('No resolver')):
            for args in variants:
                code, stdout, stderr = self.invoke(args)
                self.assertEqual((code, stdout), (1, ''))
                evidence = json.loads(stderr)['pci_routed_identify_evidence']
                self.assertFalse(evidence['connect_attempted'])
                self.assertFalse(evidence['send_attempted'])

    def test_actual_peer_rejection_unsupported_cal_and_wrong_count(self):
        for payload, extra, error_type in ((b'g#', (), 'PCIRejected'),
                (b'g.860410003B002B\r', (), 'ProtocolError'),
                (b'g.860410008201A53E\r', ('--expected-count', '0'), 'ProtocolError')):
            peer = peers.Peer(b'\\4604002101g\r', [payload])
            try:
                code, stdout, stderr = self.invoke(self.arguments(peer.port, routed=False, extra=extra))
                self.assertEqual((code, stdout), (1, ''))
                result = json.loads(stderr)
                self.assertEqual(result['type'], error_type)
                evidence = result['pci_routed_identify_evidence']
                self.assertTrue(evidence['send_completed'])
                self.assertTrue(evidence['close_completed'])
                self.assertFalse(evidence['complete'])
                self.assertFalse(evidence['resubmitted'])
            finally:
                peer.finish()

    def test_interruption_retains_receive_error_and_single_close_failure(self):
        first = KeyboardInterrupt('owned receive interruption')
        fixture = peers.SocketFixture(fault={'recv': first}, close_error=RuntimeError('owned close failure'))
        with patch.object(core.socket, 'socket', return_value=fixture):
            code, stdout, stderr = self.invoke(self.arguments())
        self.assertEqual((code, stdout), (130, ''))
        evidence = json.loads(stderr)['pci_routed_identify_evidence']
        self.assertEqual(evidence['error']['type'], 'KeyboardInterrupt')
        self.assertEqual(evidence['cleanup_errors'], [{'type': 'RuntimeError', 'message': 'owned close failure'}])
        self.assertEqual(len(fixture.sent), 1)
        self.assertEqual([call for call in fixture.calls if call[0] == 'close'], [('close',)])

    def test_export_failure_keeps_completed_exchange_and_detached_evidence(self):
        first = ValueError('owned result export failure')
        class Receipt:
            def as_dict(self):
                raise first
        class Client:
            def __init__(self, *args, **kwargs):
                self.last_error = None
                self.last_evidence = {'complete': True, 'send_completed': True, 'close_completed': True}
            def exchange(self, *args, **kwargs):
                return Receipt()
        args = build_parser().parse_args(self.arguments())
        with patch.object(helper, 'RoutedIdentifyClient', Client), self.assertRaises(ValueError) as caught:
            helper.run(args)
        self.assertIs(caught.exception, first)
        result = helper.error_payload(first, args)['pci_routed_identify_evidence']
        self.assertTrue(result['completed_exchange']['complete'])
        self.assertTrue(result['result_export_failed'])
        result['completed_exchange']['complete'] = False
        self.assertTrue(helper.error_payload(first, args)['pci_routed_identify_evidence']['completed_exchange']['complete'])
        self.assertEqual(helper.error_payload(ValueError('unrelated'), args), {})
        with patch.object(helper.copy, 'deepcopy', side_effect=SystemExit('secondary')):
            self.assertTrue(helper.error_payload(first, args)['pci_routed_identify_evidence']['evidence_export_failed'])
        self.assertIs(args._pci_routed_identify_error, first)
