"""Public command acceptance for the bounded local SESU package receipt."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli, toolkit_update_package_file_cli as boundary
from tests.test_toolkit_update_package_file import FILE_ID, NODE_ID, PACKAGE, body, encode


class UpdatePackageFileCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalogue = Path(self.tmp.name) / "catalogue.json"
        self.catalogue.write_bytes(encode(body()))
        self.package = Path(self.tmp.name) / "local-package.exe"
        self.package.write_bytes(PACKAGE)

    def invoke(self, *, status=0, extra=()):
        stdout, stderr = io.StringIO(), io.StringIO()
        command = [
            "update-package-file", "--catalogue-response", str(self.catalogue),
            "--node-id", NODE_ID, "--file-id", FILE_ID,
            "--package-path", str(self.package), *extra,
        ]
        with redirect_stdout(stdout), redirect_stderr(stderr), \
             patch("socket.socket", side_effect=AssertionError("No network")):
            result = cli.main(command)
        self.assertEqual(result, status, stdout.getvalue() + stderr.getvalue())
        if status in (0, 1):
            return json.loads(stdout.getvalue() or stderr.getvalue())
        raise AssertionError("Unexpected expected status")

    def test_match_emits_exact_receipt_without_trust_or_install_claim(self):
        result = self.invoke()
        self.assertTrue(result["bytes_match_catalogue_descriptor"])
        self.assertEqual(result["observed_sha256"], hashlib.sha256(PACKAGE).hexdigest())
        self.assertEqual(result["catalogue_source_sha256"],
                         hashlib.sha256(self.catalogue.read_bytes()).hexdigest())
        for field in ("metadata_signature_verified", "publisher_trust_evaluated",
                      "package_applicability_evaluated", "install_permitted",
                      "downloaded", "installed"):
            self.assertFalse(result[field])
        self.assertNotIn("package_path", result)

    def test_mismatch_emits_negative_receipt_and_nonzero_status(self):
        self.package.write_bytes(b"!" * len(PACKAGE))
        result = self.invoke(status=1)
        self.assertFalse(result["bytes_match_catalogue_descriptor"])
        self.assertEqual(result["observed_size"], len(PACKAGE))

    def test_invalid_catalogue_and_unsafe_package_fail_with_json_error(self):
        self.catalogue.write_bytes(b'{"success":true,"success":true}')
        self.assertEqual(self.invoke(status=1)["type"], "ValueError")
        self.catalogue.write_bytes(encode(body()))
        link = Path(self.tmp.name) / "link.exe"
        link.symlink_to(self.package)
        self.package = link
        self.assertEqual(self.invoke(status=1)["type"], "ValueError")

    def test_bound_is_checked_before_catalogue_file_io(self):
        with patch.object(boundary, "_read", side_effect=AssertionError("No file I/O")):
            self.assertEqual(self.invoke(status=1, extra=("--max-package-bytes", "0"))["type"],
                             "ValueError")

    def test_undersized_bound_rejects_declared_file_before_package_read(self):
        result = self.invoke(status=1, extra=("--max-package-bytes", str(len(PACKAGE) - 1)))
        self.assertIn("declared package size", result["error"])


if __name__ == "__main__":
    unittest.main()
