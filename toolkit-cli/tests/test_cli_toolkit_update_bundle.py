"""Public CLI coverage for exact-file update diagnostic composition."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_toolkit_update_bundle import NODE, encode, reports


class UpdateDiagnosticBundleCLITests(unittest.TestCase):
    def run_bundle(self, values, *, status=0, raw_override=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {}
            for name, value in values.items():
                path = root / (name + ".json")
                path.write_bytes((raw_override or {}).get(name, encode(value)))
                paths[name] = path
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cbus_toolkit",
                    "update-diagnostic-bundle",
                    "--catalogue",
                    str(paths["catalogue"]),
                    "--metadata",
                    str(paths["metadata"]),
                    "--revocation",
                    str(paths["revocation"]),
                    "--conditions",
                    str(paths["conditions"]),
                    "--node-id",
                    NODE,
                ],
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(process.returncode, status, process.stdout + process.stderr)
            return json.loads(process.stdout or process.stderr)

    def test_complete_public_bundle(self):
        result = self.run_bundle(reports())
        self.assertTrue(result["diagnostics_complete"])
        self.assertIsNone(result["updates_available"])
        self.assertFalse(result["install_permitted"])

    def test_unrelated_revocation_is_public_nonzero_evidence(self):
        values = reports()
        values["revocation"]["claimed_lists"]["id"] = "B" * 40
        canonical = json.loads(values["revocation"]["stages"][0]["canonical_utf8"])
        canonical["id"] = "B" * 40
        values["revocation"]["stages"][0]["canonical_utf8"] = json.dumps(
            canonical, separators=(",", ":"), sort_keys=True
        )
        result = self.run_bundle(values, status=1)
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["metadata_revocation"]["linked"])

    def test_duplicate_key_fails_closed_at_public_boundary(self):
        values = reports()
        duplicate = encode(values["catalogue"]).replace(
            b'{"applicability_verified":false,',
            b'{"applicability_verified":false,"applicability_verified":false,',
            1,
        )
        result = self.run_bundle(
            values, status=1, raw_override={"catalogue": duplicate}
        )
        self.assertIn("Duplicate JSON key", result["error"])


if __name__ == "__main__":
    unittest.main()
