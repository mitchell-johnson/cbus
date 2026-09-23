"""Actual CLI/owned-peer boundaries for explicitly routed one-shot reads."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import build_parser, main
from cbus_toolkit import pci_routed_recall as core
from cbus_toolkit import pci_routed_recall_cli as helper
import test_pci_routed_recall as peers


class RoutedRecallCLITests(unittest.TestCase):
    def invoke(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:status = main(arguments)
            except SystemExit as exc:status = exc.code
        return status, output.getvalue(), error.getvalue()

    def arguments(self, port=10001, *, prefix=(), extra=()):
        return ['--compact', 'pci', '--host', '127.0.0.1', '--port', str(port), *prefix,
                'routed-recall', '4', '0x1e', '1', '--bridge', '20', '--bridge', '21',
                '--expected-source', '20', '--expected-destination', '16',
                '--expected-route', '21', '--expected-route', '4', *extra]

    def test_real_cli_both_orders_and_command_checksum_modes(self):
        for checksum, wire in ((False, b'\\46141215041A1E01g\r'), (True, b'\\46141215041A1E0142g\r')):
            joined = peers.ROUTED + b'g.' if checksum else b'g.' + peers.ROUTED
            peer = peers.Peer(wire, [joined[:7], joined[7:]])
            try:
                with patch.object(core.socket, 'getaddrinfo', side_effect=AssertionError('No resolver')):
                    code, stdout, stderr = self.invoke(self.arguments(peer.port, prefix=('--checksum',) if checksum else ()))
                self.assertEqual((code, stderr), (0, ''))
                result = json.loads(stdout)
                self.assertEqual(result['requested'], {'unit': 4, 'parameter': 30, 'count': 1, 'bridges': [20, 21], 'addressing': 'direct'})
                self.assertEqual(result['sent_hex'], wire.hex().upper())
                self.assertEqual(result['data_hex'], '00')
                self.assertEqual(result['response']['route_entries'], [21, 4])
                self.assertTrue(result['request_sent_once'])
                self.assertFalse(result['physical_delivery_verified'])
            finally:peer.finish()

    def test_parser_domain_and_missing_path_fail_before_socket(self):
        base = self.arguments()
        invalid = [base[:base.index('--expected-source')], self.arguments(extra=('--addressing', 'programming'))]
        for count in ('0', '31', '0x20', '-1', '1.0'):
            args = base[:];args[args.index('routed-recall') + 3] = count;invalid.append(args)
        with patch.object(core.socket, 'socket', side_effect=AssertionError('No socket')), \
             patch.object(core.socket, 'getaddrinfo', side_effect=AssertionError('No resolver')):
            for args in invalid:
                code, stdout, _ = self.invoke(args)
                self.assertEqual((code, stdout), (2, ''))

    def test_semantic_path_endpoint_and_resource_validation_precedes_io(self):
        variants = [self.arguments(prefix=('--local-unit', '4')),
                    self.arguments(extra=('--expected-route', '5')),
                    self.arguments(extra=('--max-events', '4097')),
                    self.arguments(extra=('--max-received-bytes', '1048577')),
                    self.arguments(extra=tuple(v for _ in range(5) for v in ('--bridge', '5')))]
        hostname = self.arguments();hostname[hostname.index('--host')+1]='localhost';variants.append(hostname)
        with patch.object(core.socket, 'socket', side_effect=AssertionError('No socket')), \
             patch.object(core.socket, 'getaddrinfo', side_effect=AssertionError('No resolver')):
            for args in variants:
                code, stdout, stderr = self.invoke(args)
                self.assertEqual((code, stdout), (1, ''))
                evidence = json.loads(stderr)['pci_routed_recall_evidence']
                self.assertFalse(evidence['connect_attempted'])
                self.assertFalse(evidence['send_attempted'])

    def test_actual_peer_rejection_is_structured_and_closes_once(self):
        wire = b'\\46141215041A1E01g\r'
        peer = peers.Peer(wire, [b'g#'])
        try:
            code, stdout, stderr = self.invoke(self.arguments(peer.port))
            self.assertEqual((code, stdout), (1, ''))
            result = json.loads(stderr)
            self.assertEqual(result['type'], 'PCIRejected')
            evidence = result['pci_routed_recall_evidence']
            self.assertTrue(evidence['send_completed'])
            self.assertTrue(evidence['close_completed'])
            self.assertFalse(evidence['complete'])
            self.assertFalse(evidence['resubmitted'])
        finally:peer.finish()

    def test_cli_interruption_retains_primary_and_secondary_close_evidence(self):
        first = KeyboardInterrupt('owned receive interruption')
        fixture = peers.SocketFixture(fault={'recv': first}, close_error=RuntimeError('owned close failure'))
        with patch.object(core.socket, 'socket', return_value=fixture):
            code, stdout, stderr = self.invoke(self.arguments())
        self.assertEqual((code, stdout), (130, ''))
        evidence = json.loads(stderr)['pci_routed_recall_evidence']
        self.assertEqual(evidence['error']['type'], 'KeyboardInterrupt')
        self.assertEqual(evidence['cleanup_errors'], [{'type': 'RuntimeError', 'message': 'owned close failure'}])
        self.assertEqual(len(fixture.sent), 1)
        self.assertEqual([call for call in fixture.calls if call[0] == 'close'], [('close',)])

    def test_result_export_failure_preserves_completed_exchange_and_detached_evidence(self):
        first = ValueError('owned result export failure')
        class Receipt:
            def as_dict(self):raise first
        class Client:
            def __init__(self, *args, **kwargs):
                self.last_error = None
                self.last_evidence = {'complete': True, 'send_completed': True, 'close_completed': True}
            def exchange(self, *args, **kwargs):return Receipt()
        args = build_parser().parse_args(self.arguments())
        with patch.object(helper, 'RoutedRecallClient', Client):
            try:helper.run(args)
            except ValueError as actual:self.assertIs(actual, first)
            else:self.fail('Missing result export error')
        result = helper.error_payload(first, args)['pci_routed_recall_evidence']
        self.assertTrue(result['completed_exchange']['complete'])
        self.assertTrue(result['result_export_failed'])
        result['completed_exchange']['complete'] = False
        self.assertTrue(helper.error_payload(first, args)['pci_routed_recall_evidence']['completed_exchange']['complete'])
        self.assertEqual(helper.error_payload(ValueError('unrelated'), args), {})
        with patch.object(helper.copy, 'deepcopy', side_effect=SystemExit('secondary')):
            self.assertTrue(helper.error_payload(first, args)['pci_routed_recall_evidence']['evidence_export_failed'])
        self.assertIs(args._pci_routed_recall_error, first)
