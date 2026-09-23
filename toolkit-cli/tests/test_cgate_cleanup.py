"""A secondary socket-close failure must not hide the original operation."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit import cli


class CGateCleanupTests(unittest.TestCase):
    def client(self, cleanup):
        client = CGateClient('owned.invalid')
        sock = Mock(); sock.close.side_effect = cleanup
        client._socket = sock; client._buffer.extend(b'partial')
        return client, sock

    def assert_closed(self, client, sock, error, cleanup):
        self.assertFalse(client.connected); self.assertFalse(client._buffer)
        self.assertEqual(error.cgate_cleanup_errors, (cleanup,)); sock.close.assert_called_once_with()
        with self.assertRaisesRegex(RuntimeError, 'not connected'): client.command('NOOP')
        client.close(); sock.close.assert_called_once_with()

    def test_context_retains_original_failure_and_cleanup_interruption(self):
        for original in (RuntimeError('first operation'), KeyboardInterrupt('first cancellation'), SystemExit(9)):
            for cleanup in (OSError('close failed'), KeyboardInterrupt('second cancellation'), SystemExit(11)):
                client, sock = self.client(cleanup)
                with self.subTest(original=type(original).__name__, cleanup=type(cleanup).__name__):
                    with self.assertRaises(type(original)) as caught:
                        with client: raise original
                    self.assertIs(caught.exception, original)
                    self.assert_closed(client, sock, original, cleanup)
                    del original.cgate_cleanup_errors

    def test_context_success_still_reports_close_failure(self):
        for cleanup in (OSError('close failed'), KeyboardInterrupt('close cancelled'), SystemExit(7)):
            client, sock = self.client(cleanup)
            with self.subTest(cleanup=type(cleanup).__name__), self.assertRaises(type(cleanup)) as caught:
                with client: pass
            self.assertIs(caught.exception, cleanup); self.assertFalse(client.connected)
            sock.close.assert_called_once_with()

    def test_connect_preserves_primary_runtime_and_interruption(self):
        for original in (RuntimeError('bad greeting'), KeyboardInterrupt('first'), SystemExit(4)):
            cleanup = KeyboardInterrupt('second'); client, sock = self.client(cleanup); client._socket = None
            with patch('cbus_toolkit.cgate.socket.create_connection', return_value=sock), \
                    patch.object(client, '_readline', side_effect=original), self.assertRaises(type(original)) as caught:
                client.connect()
            self.assertIs(caught.exception, original); self.assert_closed(client, sock, original, cleanup)

    def test_connect_oserror_keeps_sanitized_primary_message_and_close_details(self):
        cleanup = SystemExit(5); client, sock = self.client(cleanup); client._socket = None
        with patch('cbus_toolkit.cgate.socket.create_connection', return_value=sock), \
                patch.object(client, '_readline', side_effect=OSError('private low-level detail')), \
                self.assertRaisesRegex(RuntimeError, '^Unable to establish C-Gate connection$') as caught:
            client.connect()
        self.assert_closed(client, sock, caught.exception, cleanup)

    def test_command_preserves_first_failure_after_one_send_and_invalidates_stream(self):
        for original in (RuntimeError('malformed reply'), KeyboardInterrupt('cancel read'), SystemExit(3)):
            cleanup = KeyboardInterrupt('cancel close'); client, sock = self.client(cleanup)
            with patch.object(client, '_readline', side_effect=original), self.assertRaises(type(original)) as caught:
                client.command('LABEL CLEAREDLT //OWNED/254/p/5')
            self.assertIs(caught.exception, original); self.assert_closed(client, sock, original, cleanup)
            sock.sendall.assert_called_once_with(b'[1] LABEL CLEAREDLT //OWNED/254/p/5\r\n')

    def test_command_transport_errors_remain_uncertain_without_replay(self):
        for original, message in ((OSError('low-level'), 'transport failed'), (TimeoutError('timeout'), 'timed out')):
            cleanup = SystemExit(2); client, sock = self.client(cleanup)
            with patch.object(client, '_readline', side_effect=original), self.assertRaisesRegex(RuntimeError, message) as caught:
                client.command('NOOP')
            self.assertIn('outcome may be unknown', str(caught.exception))
            self.assert_closed(client, sock, caught.exception, cleanup); sock.sendall.assert_called_once()

    def test_event_failure_preserves_primary_and_does_not_send(self):
        for original in (RuntimeError('bad event'), OSError('event transport'), KeyboardInterrupt('first'), SystemExit(8)):
            cleanup = KeyboardInterrupt('second'); client, sock = self.client(cleanup)
            with patch.object(client, '_readline', side_effect=original), \
                    self.assertRaises(RuntimeError if isinstance(original, OSError) else type(original)) as caught:
                client.read_event()
            if not isinstance(original, OSError): self.assertIs(caught.exception, original)
            else: self.assertEqual(str(caught.exception), 'C-Gate event transport failed; connection closed')
            self.assert_closed(client, sock, caught.exception, cleanup); sock.sendall.assert_not_called()

    def test_cli_reports_original_status_and_bounded_cleanup_details(self):
        for original, status in ((RuntimeError('original reply failure'), 1), (KeyboardInterrupt('first'), 130)):
            cleanup = KeyboardInterrupt('secondary close'); client, sock = self.client(cleanup)
            output, error = io.StringIO(), io.StringIO()
            with patch('cbus_toolkit.cgate.CGateClient', return_value=client), \
                    patch.object(client, '_readline', side_effect=original), redirect_stdout(output), redirect_stderr(error):
                actual = cli.main(['cgate', 'exec', 'NOOP'])
            self.assertEqual(actual, status); self.assertEqual(output.getvalue(), '')
            result = json.loads(error.getvalue())
            self.assertEqual(result['error'], 'Interrupted' if status == 130 else str(original))
            self.assertEqual(result['cgate_cleanup_errors'], [{'type': 'KeyboardInterrupt', 'error': 'secondary close'}])
            self.assertFalse(result['cgate_cleanup_errors_truncated']); sock.sendall.assert_called_once()
        error = RuntimeError('primary'); error.cgate_cleanup_errors = [RuntimeError('x' * 2048)] * 20
        result = cli._cgate_cleanup_payload(error)
        self.assertEqual(len(result['cgate_cleanup_errors']), 16)
        self.assertTrue(all(len(row['error']) == 1024 for row in result['cgate_cleanup_errors']))
        self.assertTrue(result['cgate_cleanup_errors_truncated'])


if __name__ == '__main__': unittest.main()
