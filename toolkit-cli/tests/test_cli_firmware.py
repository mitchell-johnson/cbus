"""Read-only firmware diagnostics CLI with an independent pseudo-terminal peer."""
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

IDENTITY = (b"Manufacturer=Schneider Electric\r\nProduct=eDLT\r\nSerial Number=101136.1558\r\n"
            b"HW Version=3.0 (Tiva + NCC)\r\nFW Version=1.7.0\r\nCPU Speed=120 MHz\r\nUnit Address=4\r\n")
NCC = b"NCC current version: 1.2.3\r\nNCC embedded version: 1.3.0\r\n"


class FirmwareCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", "firmware", *map(str, args)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_identification_package_metadata_and_partial_or_unsupported_replies(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            transcript, archive = directory / "id.txt", directory / "eDLTFirmware_1.7.0.zip"
            transcript.write_bytes(IDENTITY)
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("edlt_main_hwv3_1_7_0.bin", b"explicit synthetic image")
                package.writestr("edlt_fontdata_1.0.0.bin", b"explicit synthetic font")
            result = self.cli("parse-id", transcript, "--package", archive)
            self.assertTrue(result["complete"])
            self.assertEqual(result["variant"], "TivaNCC")
            self.assertTrue(result["package"]["metadata_match"])
            self.assertEqual(result["package"]["version_relation"], "same")
            self.assertFalse(result["package"]["update_implemented"])
            self.assertFalse(result["package"]["image_contents_verified"])
            metadata = self.cli("inspect-package", archive)
            self.assertEqual(len(metadata["entries"]), 2)
            self.assertFalse(metadata["archive_extracted"])
            self.assertEqual(sorted(p.name for p in directory.iterdir()), [archive.name, transcript.name])
            transcript.write_bytes(IDENTITY.replace(b"Serial Number=101136.1558", b"Serial Number="))
            unusable = self.cli("parse-id", transcript, status=1)
            self.assertTrue(unusable["complete"])
            self.assertFalse(unusable["usable_identity"])
            transcript.write_bytes(NCC)
            self.assertTrue(self.cli("parse-ncc", transcript)["update_available"])
            transcript.write_bytes(b"COMMAND NOT VALID\r\n")
            unsupported = self.cli("parse-ncc", transcript, status=1)
            self.assertFalse(unsupported["complete"])
            self.assertFalse(unsupported["supported"])
            transcript.write_bytes(b"Manufacturer=Schneider Electric\r\n")
            partial = self.cli("parse-id", transcript, status=1)
            self.assertFalse(partial["complete"])
            self.assertEqual(partial["fields"]["Manufacturer"], "Schneider Electric")
            self.assertEqual(self.cli("classify-hardware", "2 (tiva)")["variant"], "TivaPCI")
            self.assertEqual(self.cli("classify-hardware", "3 (Unknown)", status=1)["variant"], "Unknown")

    def test_corrupt_package_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "eDLTFirmware_1.7.0.zip"
            package.write_bytes(b"PK\x03\x04truncated header")
            result = self.cli("inspect-package", package, status=1)
            self.assertIn("not a valid ZIP archive", result["error"])
            self.assertEqual(package.read_bytes(), b"PK\x03\x04truncated header")

    @unittest.skipUnless(hasattr(os, "openpty") and importlib.util.find_spec("serial"),
                         "Install serial extra on a POSIX host for serial CLI acceptance")
    def test_real_serial_cli_emits_only_id_or_nv_and_preserves_partial_timeout(self):
        for action, expected, reply, status in (
                ("identify", b"id\r", IDENTITY, 0), ("ncc-versions", b"nv\r", NCC, 0),
                ("ncc-versions", b"nv\r", b"COMMAND NOT VALID\r\n", 1),
                ("identify", b"id\r", b"Manufacturer=Schneider Electric\r\n", 1)):
            with self.subTest(action=action, reply=reply):
                master, slave = os.openpty()
                commands, errors = [], []
                def peer():
                    try:
                        data = b""
                        while not data.endswith(b"\r"):
                            if not select.select([master], [], [], 5)[0]:
                                raise TimeoutError("CLI did not send a diagnostic command")
                            data += os.read(master, 1024)
                        commands.append(data)
                        for index in range(0, len(reply), 3):
                            os.write(master, reply[index:index + 3])
                    except Exception as error:
                        errors.append(str(error))
                worker = threading.Thread(target=peer, daemon=True)
                worker.start()
                try:
                    result = self.cli(action, "--port", os.ttyname(slave), "--timeout", ".3", status=status)
                    worker.join(5)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors, [])
                    self.assertEqual(commands, [expected])
                    self.assertTrue(result["read_only"])
                    if action == "identify" and status:
                        self.assertEqual(result["fields"], {"Manufacturer": "Schneider Electric"})
                finally:
                    os.close(master)
                    os.close(slave)


if __name__ == "__main__":
    unittest.main()
