"""Direct serial CLI against an independent literal TCP peer."""
from contextlib import contextmanager
import json
import select
import socket
import subprocess
import sys
import threading
import unittest


SERIAL_A = b'86FF10008D0438FFFFFFFF18B10616A200051A\r\n'
SERIAL_B = b'86FF10008D0438FFFFFFFF18B10617A2000519\r\n'


@contextmanager
def peer(parts):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(5)
    requests, errors = [], []
    def worker():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                request = b''
                while not request.endswith(b'\r'):
                    chunk = connection.recv(1024)
                    if not chunk:
                        raise AssertionError('Client closed before its request')
                    request += chunk
                requests.append(request)
                for part in parts:
                    connection.sendall(part)
                # Stay open until the collector closes its completed stream.
                if connection.recv(1024):
                    raise AssertionError('Collector sent an extra request')
        except Exception as error:
            errors.append(str(error))
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], requests, errors
    finally:
        thread.join(6)
        listener.close()
        if thread.is_alive():
            raise AssertionError('Literal peer did not terminate')


class PCISerialCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'pci', *map(str, args)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_native_window_single_identity_and_closed_one_shot_connection(self):
        with peer([b'g.', SERIAL_A]) as (port, requests, errors):
            result = self.cli('--port', port, '--local-unit', 16, 'serials', 255)
        self.assertEqual(errors, [])
        self.assertEqual(requests, [b'\\46FF002104g\r'])
        self.assertEqual((result['status'], result['serials']), ('single', ['101136.1558']))
        self.assertTrue(result['complete'])
        self.assertTrue(result['timing']['vendor_quiet_period'])
        self.assertGreaterEqual(result['timing']['elapsed_seconds'], 1.9)
        self.assertTrue(result['connection_closed'])
        self.assertEqual(result['automatic_retries'], 0)
        self.assertFalse(result['physical_addresses_changed'])

    def test_split_duplicate_responses_are_reported_and_checksum_request_is_exact(self):
        with peer([b'g', b'.' + SERIAL_A[:13], SERIAL_A[13:], SERIAL_B[:7], SERIAL_B[7:]]) as (port, requests, errors):
            result = self.cli('--port', port, '--local-unit', 16, '--checksum', '--timeout', 1,
                              'serials', 255, '--quiet-period', '.05', '--confirmation-timeout', '.2', status=1)
        self.assertEqual(errors, [])
        self.assertEqual(requests, [b'\\46FF00210496g\r'])
        self.assertEqual(result['status'], 'duplicate_address')
        self.assertTrue(result['complete'])
        self.assertEqual(result['serials'], ['101136.1558', '101136.1559'])
        self.assertEqual([row['raw_hex'] for row in result['replies']], [SERIAL_A.rstrip().hex(), SERIAL_B.rstrip().hex()])
        self.assertFalse(result['timing']['vendor_quiet_period'])

    def test_missing_confirmation_returns_partial_evidence_without_retry(self):
        with peer([]) as (port, requests, errors):
            result = self.cli('--port', port, '--local-unit', 16, '--timeout', 1,
                              'serials', 255, '--quiet-period', '.05', '--confirmation-timeout', '.1', status=1)
        self.assertEqual(errors, [])
        self.assertEqual(requests, [b'\\46FF002104g\r'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['termination'], 'confirmation_timeout')
        self.assertEqual(result['serials'], [])

    def test_missing_local_address_and_invalid_bounds_reject_before_connecting(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            error = self.cli('--port', port, 'serials', 255, status=1)
            self.assertIn('--local-unit', error['error'])
            error = self.cli('--port', port, '--local-unit', 16, 'serials', 255, '--max-frames', 0, status=1)
            self.assertIn('max_frames', error['error'])
            self.assertFalse(select.select([listener], [], [], 0)[0])


if __name__ == '__main__':
    unittest.main()
