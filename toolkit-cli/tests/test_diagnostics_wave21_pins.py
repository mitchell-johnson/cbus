"""Wave-21 offline pins for eDLT diagnostics guards with zero prior test refs.

Covers only guards in cbus_toolkit/firmware_diagnostics.py that no existing
test references (verified 2026-10-16 via ``grep -rn`` over ``tests/`` for
the exact literals below): bounded package filenames, non-bytes parser
chunks, short serial writes, explicit port requirement, and snapshot
digest/bound validation. Offline: synthetic bytes and fake serial factory
only, no hardware/serial/PTY/network/archives.
"""
import unittest

from cbus_toolkit.firmware_diagnostics import (
    DiagnosticError,
    DiagnosticParser,
    PackageSnapshot,
    SerialDiagnostics,
    open_package_snapshot,
    package_version,
)


class DiagnosticsWave21Pins(unittest.TestCase):
    def test_package_version_rejects_unbounded_filenames(self):
        for bad in (None, 123, b'eDLTFirmware_1.7.0.zip', 'a\0b.zip', 'x' * 4097):
            with self.subTest(bad=repr(bad)[:40]):
                with self.assertRaisesRegex(ValueError, 'bounded package filename'):
                    package_version(bad)

    def test_diagnostic_parser_rejects_non_bytes_chunks(self):
        parser = DiagnosticParser('id')
        for bad in ('id\r\n', None, 123, bytearray(b'id\r\n')):
            with self.subTest(bad=repr(bad)[:40]):
                with self.assertRaisesRegex(ValueError, 'chunks must be bytes'):
                    parser.feed(bad)
        self.assertEqual(parser.fields, {})

    def test_serial_short_write_and_port_guard_without_retry(self):
        for bad in ('', '   ', 'a\x01b'):
            with self.subTest(port=repr(bad)):
                with self.assertRaisesRegex(ValueError, 'explicit serial port'):
                    SerialDiagnostics(bad, serial_factory=lambda **kwargs: None)
        calls = []

        class ShortPeer:
            def __init__(self, **kwargs):
                self.options = kwargs
                self.closed = False
                self.reads = 0

            def write(self, data):
                self.request = data
                return 0

            def read(self, size):  # pragma: no cover - must never be reached
                self.reads += 1
                raise AssertionError('no read after short write')

            def close(self):
                self.closed = True

        def factory(**kwargs):
            peer = ShortPeer(**kwargs)
            calls.append(peer)
            return peer

        with self.assertRaisesRegex(DiagnosticError, 'Short diagnostic command write'):
            SerialDiagnostics('fixture', serial_factory=factory).identify()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].request, b'id\r')
        self.assertEqual(calls[0].reads, 0)
        self.assertTrue(calls[0].closed)

    def test_snapshot_rejects_bad_digest_and_bound_before_io(self):
        snapshot = PackageSnapshot('eDLTFirmware_1.7.0.zip', b'synthetic')
        for bad in ('XYZ', '0' * 63, 'G' * 64, '0' * 63 + 'g', 123):
            with self.subTest(digest=repr(bad)[:20]):
                with self.assertRaisesRegex(ValueError, 'lowercase SHA-256'):
                    open_package_snapshot(snapshot, expected_sha256=bad)
        for bad in (0, -1, True, '8', 512 * 1024 * 1024 + 1):
            with self.subTest(bound=repr(bad)[:20]):
                with self.assertRaisesRegex(ValueError, 'snapshot bound is invalid'):
                    open_package_snapshot(snapshot, max_bytes=bad)
        self.assertEqual(open_package_snapshot(snapshot), snapshot)


if __name__ == '__main__':
    unittest.main()
