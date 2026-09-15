"""Direct MMI CLI using literal standard PCI response blocks."""
import contextlib
import io
import json
import select
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_cli_pci_serials import peer

FIRST = b'D8FF00' + b'00'*4 + b'01' + b'00'*17 + b'28\r\n'
MIDDLE = b'D8FF58' + b'00'*22 + b'D1\r\n'
LAST = b'D6FFB0' + b'00'*19 + b'80FB\r\n'
ERROR = b'D6FFB0' + b'00'*19 + b'C0BB\r\n'


class PCIMMICLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        process = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'pci', *map(str, args)],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, status, process.stdout + process.stderr)
        return json.loads(process.stdout or process.stderr)

    def test_defaults_complete_ranges_and_single_request(self):
        with peer([b'g.', FIRST[:17], FIRST[17:], MIDDLE, LAST]) as (port, requests, errors):
            result = self.cli('--port', port, '--local-unit', 16, 'mmi')
        self.assertEqual(errors, [])
        self.assertEqual(requests, [b'\\05FF00FAFF00g\r'])
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['complete'])
        self.assertTrue(result['coverage_complete'])
        self.assertTrue(result['local_present'])
        self.assertTrue(result['connection_closed'])
        self.assertEqual(result['addresses'], [16,255])
        self.assertEqual(len(result['states']), 256)
        self.assertEqual((result['states'][16], result['states'][255]), (1,2))
        self.assertEqual(result['missing_ranges'], [])
        self.assertEqual(result['automatic_retries'], 0)
        self.assertFalse(result['serials_observed'])
        self.assertFalse(result['physical_addresses_changed'])
        self.assertEqual(result['timing']['overall_timeout_seconds'], 10.0)

    def test_missing_middle_cannot_report_unobserved_addresses_absent(self):
        with peer([b'g.', FIRST, LAST]) as (port, requests, errors):
            result = self.cli('--port', port, '--local-unit', 16, '--checksum', '--timeout', 1,
                'mmi', '--confirmation-timeout', '.2', '--response-timeout', '.5', status=1)
        self.assertEqual(errors, [])
        self.assertEqual(requests, [b'\\05FF00FAFF0003g\r'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['termination'], 'coverage_error')
        self.assertEqual(result['states'][88:], [None]*168)
        self.assertEqual(result['missing_ranges'], [{'start':88, 'end_exclusive':256}])
        self.assertEqual(result['addresses'], [16])
        self.assertEqual(result['timing']['overall_timeout_seconds'], 1.0)

    def test_complete_coverage_with_error_state_has_nonzero_exit(self):
        with peer([b'g.', FIRST, MIDDLE, ERROR]) as (port, requests, errors):
            result = self.cli('--port', port, '--local-unit', 16, 'mmi', status=1)
        self.assertEqual(errors, [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(result['status'], 'mmi_errors')
        self.assertTrue(result['complete'])
        self.assertEqual(result['error_addresses'], [255])

    def test_ack_only_and_invalid_input_preserve_evidence_and_do_not_retry(self):
        with peer([b'g.']) as (port, requests, errors):
            result = self.cli('--port', port, '--local-unit', 16, '--timeout', 1,
                'mmi', '--confirmation-timeout', '.2', '--response-timeout', '.05', status=1)
        self.assertEqual(errors, [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(result['states'], [None]*256)
        self.assertFalse(result['local_present'])
        self.assertEqual(result['termination'], 'response_timeout')
        self.assertTrue(result['connection_closed'])
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); listener.listen(1)
            port = listener.getsockname()[1]
            self.assertIn('--local-unit', self.cli('--port', port, 'mmi', status=1)['error'])
            self.assertIn('Overall timeout', self.cli('--port', port, '--local-unit', 16,
                '--timeout', 1, 'mmi', status=1)['error'])
            self.assertIn('max_frames', self.cli('--port', port, '--local-unit', 16,
                'mmi', '--max-frames', 0, status=1)['error'])
            self.assertFalse(select.select([listener],[],[],0)[0])

    def test_cancellation_emits_partial_collector_evidence_and_closes_without_more_io(self):
        from cbus_toolkit.cli import main
        from cbus_toolkit.pci_inventory import PCIMMICollector

        class Stream:
            def __init__(self):
                self.calls = []
                self.replies = [b'g.' + FIRST, KeyboardInterrupt('cancelled')]

            def settimeout(self, value):
                self.calls.append(('settimeout', value))

            def connect(self, endpoint):
                self.calls.append(('connect', endpoint))

            def sendall(self, data):
                self.calls.append(('sendall', data))

            def recv(self, count):
                self.calls.append(('recv', count))
                event = self.replies.pop(0)
                if isinstance(event, BaseException):
                    self.calls.append(('interrupted',))
                    raise event
                return event

            def close(self):
                self.calls.append(('close',))

        stream = Stream()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(PCIMMICollector, '_make_socket', return_value=stream), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(['pci', '--local-unit', '16', 'mmi'])
        self.assertEqual(status, 130)
        self.assertEqual(stdout.getvalue(), '')
        result = json.loads(stderr.getvalue())
        self.assertEqual(result['error'], 'Interrupted')
        evidence = result['pci_mmi_observation']
        self.assertEqual(evidence['termination'], 'interrupted')
        self.assertFalse(evidence['complete'])
        self.assertTrue(evidence['connection_closed'])
        self.assertEqual(evidence['states'][:88], [0]*16 + [1] + [0]*71)
        self.assertEqual(evidence['states'][88:], [None]*168)
        self.assertEqual(evidence['received_hex'], (b'g.' + FIRST).hex())
        self.assertEqual(evidence['automatic_retries'], 0)
        self.assertEqual([call for call in stream.calls if call[0] == 'connect'],
                         [('connect', ('127.0.0.1', 10001))])
        self.assertEqual([call for call in stream.calls if call[0] == 'sendall'],
                         [('sendall', b'\\05FF00FAFF00g\r')])
        self.assertEqual(sum(call[0] == 'recv' for call in stream.calls), 2)
        self.assertEqual(stream.calls[stream.calls.index(('interrupted',)) + 1:], [('close',)])


if __name__ == '__main__':
    unittest.main()
