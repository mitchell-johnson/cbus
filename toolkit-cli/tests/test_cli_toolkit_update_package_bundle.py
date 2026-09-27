"""Public CLI tests for exact update diagnostic and package-source linkage."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_toolkit_update_bundle import NODE, encode
from tests.test_toolkit_update_package_bundle import FILE_ID, case


class UpdatePackageBundleCLITests(unittest.TestCase):
    def run_join(self, value, root: Path, *, expected_status: int,
                 receipt=None, bundle=None):
        files = {}
        content = {
            **value["raw"],
            **value["sources"],
            "diagnostic_bundle": encode(value["diagnostic"] if bundle is None else bundle),
            "package_receipt": encode(value["receipt"] if receipt is None else receipt),
        }
        for name, raw in content.items():
            path = root / (name + ".json")
            path.write_bytes(raw)
            files[name] = path
        command = [sys.executable, "-m", "cbus_toolkit", "update-package-bundle"]
        for name in (
            "catalogue", "metadata", "revocation", "conditions",
            "diagnostic_bundle", "package_receipt", "catalogue_response",
            "revocation_input", "conditions_input", "context_input",
        ):
            command.extend(("--" + name.replace("_", "-"), str(files[name])))
        command.extend((
            "--node-id", NODE, "--file-id", FILE_ID,
            "--package-path", str(value["path"]),
        ))
        process = subprocess.run(command, text=True, capture_output=True, timeout=30)
        self.assertEqual(process.returncode, expected_status,
                         process.stdout + process.stderr)
        return json.loads(process.stdout or process.stderr)

    def test_public_exact_source_join_and_false_trust_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = self.run_join(case(root), root, expected_status=0)
        self.assertTrue(result["joined_diagnostics_complete"])
        self.assertTrue(result["links"]["source_package"]["linked"])
        self.assertTrue(result["links"]["diagnostic_package"]["linked"])
        self.assertFalse(result["publisher_trust_evaluated"])
        self.assertFalse(result["install_permitted"])

    def test_public_failed_stage_keeps_exact_package_link_but_exits_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = self.run_join(case(root, metadata_status="unsupported"),
                                   root, expected_status=1)
        self.assertTrue(result["links"]["source_package"]["linked"])
        self.assertTrue(result["links"]["diagnostic_package"]["linked"])
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["joined_diagnostics_complete"])

    def test_public_substituted_receipt_is_negative_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = case(root)
            changed = dict(value["receipt"])
            changed["observed_sha256"] = "0" * 64
            result = self.run_join(value, root, expected_status=1, receipt=changed)
        self.assertFalse(result["links"]["source_package"]["linked"])
        self.assertFalse(result["links"]["source_package"]["package_receipt_reproduced"])


if __name__ == "__main__":
    unittest.main()
