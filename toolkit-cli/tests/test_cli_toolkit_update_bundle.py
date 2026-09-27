"""Public CLI coverage for exact-file update diagnostic composition."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_toolkit_update_bundle import NODE, encode, reports, source_documents


class UpdateDiagnosticBundleCLITests(unittest.TestCase):
    def run_bundle(self, values, *, status=0, raw_override=None,
                   source_override=None, include_sources=True, omit_sources=()):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {}
            for name, value in values.items():
                path = root / (name + ".json")
                path.write_bytes((raw_override or {}).get(name, encode(value)))
                paths[name] = path
            command = [
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
                ]
            if include_sources:
                for name, value in source_documents().items():
                    if name in omit_sources:
                        continue
                    suffix = ".der" if name.endswith("certificate") else ".json"
                    path = root / (name + suffix)
                    path.write_bytes((source_override or {}).get(name, value))
                    command.extend(("--" + name.replace("_", "-"), str(path)))
            process = subprocess.run(
                command,
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

    def test_mismatched_canonical_digest_receipt_is_public_nonzero_evidence(self):
        for report, link in (("metadata", "catalogue_metadata"),
                             ("revocation", "metadata_revocation")):
            with self.subTest(report=report):
                values = reports()
                values[report]["stages"][0]["sha256_hex"] = "0" * 64
                result = self.run_bundle(values, status=1)
                self.assertFalse(result["diagnostics_complete"])
                self.assertFalse(result["links"][link]["canonical_digest_receipt_matches"])
                self.assertIn("digest receipts", result["links"][link]["reason"])
                self.assertFalse(result["install_permitted"])

    def test_report_only_public_bundle_retains_unverified_provenance(self):
        result = self.run_bundle(reports(), status=1, include_sources=False)
        self.assertFalse(result["diagnostics_complete"])
        self.assertEqual(result["links"]["catalogue_metadata"]["reason"],
                         "raw catalogue response was not supplied")

    def test_public_missing_certificate_preserves_independent_links(self):
        result = self.run_bundle(
            reports(), status=1, omit_sources=("metadata_certificate",)
        )
        self.assertTrue(result["links"]["catalogue_metadata"]["linked"])
        self.assertFalse(result["links"]["metadata_revocation"]["linked"])
        self.assertFalse(result["diagnostics_complete"])

    def test_public_malformed_certificate_is_input_error(self):
        result = self.run_bundle(
            reports(), status=1,
            source_override={"metadata_certificate": b"not a DER certificate"},
        )
        self.assertIn("DER SEQUENCE", result["error"])

    def test_substituted_catalogue_source_is_public_nonzero_evidence(self):
        source = source_documents()
        body = json.loads(source["catalogue_response"])
        body["data"][0]["nodeName"] = "Toolkit 1.20.0"
        result = self.run_bundle(
            reports(), status=1,
            source_override={"catalogue_response": encode(body)},
        )
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["catalogue_metadata"]["catalogue_source_matches"])

    def test_equal_boolean_and_integer_candidate_does_not_link(self):
        values = reports()
        values["catalogue"]["candidates"][0]["metadata_signature_present"] = 0
        result = self.run_bundle(values, status=1)
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["catalogue_metadata"]["catalogue_source_matches"])

    def test_equal_boolean_and_integer_context_fact_does_not_link(self):
        values = reports()
        source = source_documents()
        context = {
            "format": "cbus-toolkit-condition-context-v1",
            "culture": "invariant-ascii",
            "files": [{"path": "C:/test", "exists": True}],
        }
        source["context_input"] = encode(context)
        digest = hashlib.sha256(source["context_input"]).hexdigest()
        values["conditions"]["context_sha256"] = digest
        values["conditions"]["source"]["context_file_sha256"] = digest
        values["conditions"]["supplied_context"] = context
        values["conditions"]["supplied_context"]["files"][0]["exists"] = 1
        result = self.run_bundle(values, status=1, source_override=source)
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["metadata_conditions"]["condition_sources_match"])

    def test_changed_installed_version_does_not_link(self):
        values = reports()
        values["catalogue"]["installed_version"] = "1.19.0.2754"
        result = self.run_bundle(values, status=1)
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["catalogue_metadata"]["request_receipt_matches"])

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
