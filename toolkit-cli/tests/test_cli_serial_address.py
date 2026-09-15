"""Offline CLI acceptance using original literal PCI requests and receipts."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import main


class SerialAddressCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", "serial-address", *map(str, args)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_native_command_and_srchk_are_json_bytes_only(self):
        for options, wire in (([], b'\\05FF000F0018B106160615g\r'),
                              (["--checksum", "--confirmation", "z"], b'\\05FF000F0018B106160615EDz\r')):
            with self.subTest(options=options):
                result = self.cli("encode", "0101136.01558", "0x06", *options)
                self.assertEqual(result["format"], "cbus-pci-serial-address-command-v1")
                self.assertEqual(result["serial"], "101136.1558")
                self.assertEqual(result["destination"], 6)
                self.assertEqual(result["wire_text"].encode("ascii"), wire)
                self.assertEqual(bytes.fromhex(result["wire_hex"]), wire)
                self.assertFalse(result["io_performed"])
                self.assertFalse(result["movement_verified"])
                self.assertFalse(result["persistence_verified"])

    def test_full_capture_correlation_and_uncertainty_exit_status(self):
        frame = b'86061000870018B106160000F8\r\n'
        captures = ((b'g.' + frame, "matched", 0), (frame, "unverified", 1),
                    (b'g.' + frame + b'86', "incomplete", 1),
                    (b'g.' + frame + b'00\r\n', "invalid", 1),
                    (b'g.' + frame * 2, "ambiguous", 1), (b'g!', "rejected", 1),
                    (b'g.86091000870018B106160000F5\r\n', "unverified", 1),
                    (b'g.86061000870018B10616FACE30\r\n', "matched", 0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.bin"
            for data, expected, status in captures:
                with self.subTest(status=expected, data=data):
                    path.write_bytes(data)
                    result = self.cli("receipt", path, "--serial", "101136.1558",
                                      "--destination", "6", "--local-unit", "16", status=status)
                    self.assertEqual(result["format"], "cbus-pci-serial-address-receipt-v1")
                    self.assertEqual(result["status"], expected)
                    self.assertEqual(result["raw_hex"], data.hex())
                    self.assertEqual(result["receipt_matches_request"], expected == "matched")
                    self.assertFalse(result["movement_verified"])
                    self.assertFalse(result["persistence_verified"])
                    self.assertFalse(result["io_performed"])
                    self.assertTrue(result["requires_independent_verification"])
                    self.assertEqual(path.read_bytes(), data)
                    if data.endswith(b'FACE30\r\n'):
                        self.assertEqual(result["replies"][0]["opaque_tail_hex"], "face")

    def test_invalid_inputs_and_capture_bound(self):
        for serial, destination in (("0.0", "6"), ("1048576.1", "6"), ("101136.1558", "255")):
            with self.subTest(serial=serial, destination=destination):
                self.assertIn("error", self.cli("encode", serial, destination, status=1))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.bin"
            path.write_bytes(b'\r' * 4097)
            result = self.cli("receipt", path, "--serial", "101136.1558", "--destination", "6",
                              "--local-unit", "16", status=1)
            self.assertIn("4096", result["error"])

    def test_commands_do_not_open_network_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.bin"
            path.write_bytes(b'g.86061000870018B106160000F8\r\n')
            with patch("socket.socket", side_effect=AssertionError("Unexpected socket")), \
                    patch("socket.create_connection", side_effect=AssertionError("Unexpected connection")):
                for args in (("encode", "101136.1558", "6"),
                             ("receipt", str(path), "--serial", "101136.1558", "--destination", "6", "--local-unit", "16")):
                    output = StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(main(["serial-address", *args]), 0)
                    self.assertFalse(json.loads(output.getvalue())["io_performed"])


if __name__ == "__main__":
    unittest.main()
