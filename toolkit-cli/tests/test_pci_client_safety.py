"""Interrupted or expired PCI exchanges must never leave a reusable stream."""
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit.pci import PCIClient, ProtocolError


class PCIClientSafetyTests(unittest.TestCase):
    def client(self, *, local_unit=None, close_error=None):
        client = PCIClient('fixture.invalid', timeout=1, local_unit=local_unit)
        sock = Mock()
        sock.close.side_effect = close_error
        client.socket = sock
        return client, sock

    def assert_invalidated(self, client, sock):
        self.assertIsNone(client.socket)
        self.assertFalse(client.stream.buffer)
        sock.close.assert_called_once_with()
        sent = sock.sendall.call_count
        with self.assertRaisesRegex(RuntimeError, 'not connected'):
            client.write(5, 0, b'\x41\0\0', ack_tag=0x41)
        self.assertEqual(sock.sendall.call_count, sent)
        client.close()
        sock.close.assert_called_once_with()

    def test_interrupted_send_or_receive_invalidates_without_replay(self):
        for error_type in (KeyboardInterrupt, SystemExit):
            for stage in ('sendall', 'recv'):
                for cleanup in (None, OSError('close failed'), KeyboardInterrupt('close interrupted')):
                    with self.subTest(error=error_type, stage=stage, cleanup=cleanup):
                        original = error_type('request interrupted')
                        client, sock = self.client(close_error=cleanup)
                        client.stream.buffer.extend(b'8605')
                        getattr(sock, stage).side_effect = original
                        with self.assertRaises(error_type) as caught:
                            client.write(5, 0, b'\x41\0\0', ack_tag=0x41)
                        self.assertIs(caught.exception, original)
                        self.assert_invalidated(client, sock)
                        sock.sendall.assert_called_once()
                        if cleanup is not None:
                            self.assertEqual(original.pci_cleanup_errors, (cleanup,))

    def test_interrupted_discovery_never_sends_the_requested_write(self):
        client, sock = self.client()
        sock.recv.side_effect = KeyboardInterrupt('discovery interrupted')
        with self.assertRaises(KeyboardInterrupt):
            client.write(None, 0, b'\x41\0\0', ack_tag=0x41)
        self.assert_invalidated(client, sock)
        sock.sendall.assert_called_once_with(b'@1A2001\r')

    def test_cleanup_failure_keeps_original_protocol_failure(self):
        cleanup = OSError('close failed')
        client, sock = self.client(close_error=cleanup)
        sock.recv.return_value = b'g#'
        with self.assertRaises(ProtocolError) as caught:
            client.write(5, 0, b'\x41\0\0', ack_tag=0x41)
        self.assertEqual(caught.exception.pci_cleanup_errors, (cleanup,))
        self.assert_invalidated(client, sock)

    def test_context_cleanup_preserves_original_failure(self):
        original = KeyboardInterrupt('original interruption')
        cleanup = OSError('close failed')
        client, sock = self.client(close_error=cleanup)
        with patch.object(client, 'connect', return_value=client):
            with self.assertRaises(KeyboardInterrupt) as caught:
                with client:
                    raise original
        self.assertIs(caught.exception, original)
        self.assertEqual(original.pci_cleanup_errors, (cleanup,))
        self.assert_invalidated(client, sock)

    def test_close_failure_still_invalidates_connection(self):
        cleanup = OSError('close failed')
        client, sock = self.client(close_error=cleanup)
        client.stream.buffer.extend(b'8605')
        with self.assertRaises(OSError) as caught:
            client.close()
        self.assertIs(caught.exception, cleanup)
        self.assert_invalidated(client, sock)

    def test_connect_initialization_interruption_invalidates_new_socket(self):
        original = KeyboardInterrupt('initialization interrupted')
        cleanup = OSError('close failed')
        client, sock = self.client(close_error=cleanup)
        client.socket = None
        with patch('cbus_toolkit.pci.socket.create_connection', return_value=sock), \
                patch('cbus_toolkit.pci.FrameStream', side_effect=original):
            with self.assertRaises(KeyboardInterrupt) as caught:
                client.connect()
        self.assertIs(caught.exception, original)
        self.assertEqual(original.pci_cleanup_errors, (cleanup,))
        self.assert_invalidated(client, sock)

    def test_fragmented_unsolicited_traffic_does_not_fail_a_confirmed_write(self):
        client, sock = self.client()
        sock.recv.side_effect = [
            b'g.8605100100320041F1\r\n86061001003200',
            b'41F0\r\nh.8605100100320041F1\r\n',
        ]
        for _ in range(2):
            self.assertEqual(client.write(5, 0, b'\x41\0\0', ack_tag=0x41).tag, 0x41)
        self.assertIs(client.socket, sock)
        self.assertEqual(sock.sendall.call_count, 2)
        self.assertEqual([frame.source for frame in client.unsolicited], [6])

    def test_fragmented_unsolicited_traffic_can_follow_discovery(self):
        client, sock = self.client()
        sock.recv.side_effect = [
            b'8220104E\r\n86061001003200',
            b'41F0\r\ng.3200418D\r\n',
        ]
        self.assertEqual(client.write(None, 0, b'\x41\0\0', ack_tag=0x41).tag, 0x41)
        self.assertIs(client.socket, sock)
        self.assertEqual(sock.sendall.call_count, 2)
        self.assertEqual([frame.source for frame in client.unsolicited], [6])

    def test_expired_deadline_before_send_never_transmits(self):
        for unit in (None, 5):
            with self.subTest(unit=unit):
                client, sock = self.client()
                with patch('cbus_toolkit.pci.time.monotonic', side_effect=(0.0, 1.1)):
                    with self.assertRaises(TimeoutError):
                        client.write(unit, 0, b'\x41\0\0', ack_tag=0x41)
                sock.sendall.assert_not_called()
                self.assert_invalidated(client, sock)

    def test_discovery_expiry_never_sends_requested_write(self):
        client, sock = self.client()
        clock = [0.0]

        def discover(_size):
            clock[0] = 1.1
            return b'8220104E\r\n'

        sock.recv.side_effect = discover
        with patch('cbus_toolkit.pci.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                client.write(None, 0, b'\x41\0\0', ack_tag=0x41)
        self.assert_invalidated(client, sock)
        sock.sendall.assert_called_once_with(b'@1A2001\r')

    def test_complete_reply_after_deadline_is_not_success(self):
        client, sock = self.client()
        clock = [0.0]

        def reply(_size):
            clock[0] = 1.1
            return b'g.8605100100320041F1\r\n'

        sock.recv.side_effect = reply
        with patch('cbus_toolkit.pci.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                client.write(5, 0, b'\x41\0\0', ack_tag=0x41)
        self.assert_invalidated(client, sock)
        sock.sendall.assert_called_once()


if __name__ == '__main__':
    unittest.main()
