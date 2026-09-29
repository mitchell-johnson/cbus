"""Public command acceptance for the catalogue-bound package download."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import unittest

from cbus_toolkit import cli
from tests.test_toolkit_update_download import (
    FILE_ID, HOST, NODE_ID, OwnedTLSFixture, PACKAGE, catalogue_report, response_body,
)


class UpdateDownloadCLITests(OwnedTLSFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        body = response_body(port=self.server.port)
        self.paths = {}
        for name, data in (("report.json", catalogue_report(body)), ("response.json", body),
                           ("ca.pem", self.server.ca)):
            path = self.root / name
            path.write_bytes(data)
            self.paths[name] = path

    def invoke(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = cli.main([
                "update-download", "--catalogue-report", str(self.paths["report.json"]),
                "--catalogue-response", str(self.paths["response.json"]), "--package", NODE_ID,
                "--file-id", FILE_ID, "--output", str(self.output), "--timeout", "5", *extra])
        return status, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_cli_downloads_with_explicit_ca_and_reports_provenance(self):
        status, result = self.invoke("--ca-file", str(self.paths["ca.pem"]))
        self.assertEqual(status, 0, result)
        self.assertEqual(result["outcome"], "downloaded")
        self.assertEqual((self.output / "Owned-Setup.exe").read_bytes(), PACKAGE)
        self.assertEqual(result["provenance"]["url"].split("/")[2], f"{HOST}:{self.server.port}")
        self.assertFalse(result["installed"])

    def test_cli_failure_and_refusal_statuses(self):
        status, result = self.invoke()  # System trust does not include the owned CA.
        self.assertEqual(status, 1)
        self.assertEqual(result["failure"]["stage"], "tls")
        self.assertTrue(os.path.exists(self.output / result["failure_artifacts"]["record"]))
        (self.output / "Owned-Setup.exe").write_bytes(b"keep")
        status, result = self.invoke("--ca-file", str(self.paths["ca.pem"]))
        self.assertEqual(status, 1)
        self.assertIn("never overwritten", result["error"])

