"""Adversarial exact-source joins between update reports and local package bytes."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.toolkit_update_bundle import compose_update_diagnostic_bundle
from cbus_toolkit.toolkit_update_metadata import _canonical, select_node
from cbus_toolkit.toolkit_update_package_bundle import compose_update_package_bundle
from cbus_toolkit.toolkit_update_package_file import inspect_update_package_file
from cbus_toolkit.toolkit_updates import _candidate
from tests.test_toolkit_update_bundle import (
    CATALOGUE_NODE,
    NODE,
    encode,
    reports,
    source_documents,
)


FILE_ID = "synthetic-installer"
PACKAGE = b"owned offline package bytes\x00\xff"


def case(root: Path, *, version="1.19.0", package=PACKAGE,
         metadata_status="passed", omit_metadata_source=False, incomplete_http=False):
    node = copy.deepcopy(CATALOGUE_NODE)
    node["nodeName"] = "Toolkit " + version
    node["files"] = [{
        "id": FILE_ID,
        "name": "synthetic.exe",
        "size": len(package),
        "url": "https://invalid.example/synthetic.exe",
        "security": {"sha1": hashlib.sha1(package).hexdigest()},
        "metadata": {"architecture": "windows_x86_64", "mediatype": "singleFileExecutable"},
    }]
    source = encode({"success": True, "statusCode": 200, "message": "OK", "data": [node]})
    sources = source_documents()
    sources["catalogue_response"] = source
    selected = select_node(source, node_id=NODE)
    canonical = _canonical(node)
    values = reports()
    values["catalogue"]["http"]["body_sha256"] = hashlib.sha256(source).hexdigest()
    values["catalogue"]["http"]["bytes_received"] = len(source)
    values["catalogue"]["http"]["body_bytes_retained"] = len(source)
    if incomplete_http:
        values["catalogue"]["http"]["body_complete"] = False
    values["catalogue"]["candidates"] = [_candidate(node).as_dict()]
    metadata = values["metadata"]
    metadata["input_node_sha256"] = hashlib.sha256(selected).hexdigest()
    metadata["source"]["file_sha256"] = hashlib.sha256(source).hexdigest()
    metadata["source"]["selected_node_sha256"] = hashlib.sha256(selected).hexdigest()
    if omit_metadata_source:
        metadata.pop("source")
    canonical_row = metadata["stages"][0]
    canonical_row["canonical_utf8"] = canonical.decode("utf-8")
    digest = hashlib.sha256(canonical).digest()
    canonical_row["sha256_hex"] = digest.hex()
    canonical_row["sha256_base64"] = base64.b64encode(digest).decode("ascii")
    metadata["stages"][3]["status"] = metadata_status
    raw = {name: encode(value) for name, value in values.items()}
    path = root / "package.exe"
    path.write_bytes(package)
    diagnostic = compose_update_diagnostic_bundle(
        raw["catalogue"], raw["metadata"], raw["revocation"], raw["conditions"],
        node_id=NODE,
        catalogue_response_bytes=source,
        revocation_input_bytes=sources["revocation_input"],
        conditions_input_bytes=sources["conditions_input"],
        context_input_bytes=sources["context_input"],
    ).as_dict()
    receipt = inspect_update_package_file(
        source, node_id=NODE, file_id=FILE_ID, package_path=path,
    ).as_dict()
    return {"raw": raw, "sources": sources, "diagnostic": diagnostic,
            "receipt": receipt, "path": path, "node": node}


def join(value, *, raw=None, sources=None, diagnostic=None, receipt=None, path=None):
    raw = value["raw"] if raw is None else raw
    sources = value["sources"] if sources is None else sources
    diagnostic = value["diagnostic"] if diagnostic is None else diagnostic
    receipt = value["receipt"] if receipt is None else receipt
    return compose_update_package_bundle(
        raw["catalogue"], raw["metadata"], raw["revocation"], raw["conditions"],
        encode(diagnostic), encode(receipt),
        catalogue_response_bytes=sources["catalogue_response"],
        revocation_input_bytes=sources["revocation_input"],
        conditions_input_bytes=sources["conditions_input"],
        context_input_bytes=sources["context_input"],
        node_id=NODE, file_id=FILE_ID, package_path=value["path"] if path is None else path,
    ).as_dict()


class UpdatePackageBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_matching_reports_source_descriptor_and_bytes_link_without_trust(self):
        value = case(self.root)
        result = join(value)
        self.assertTrue(result["links"]["source_package"]["linked"])
        self.assertTrue(result["links"]["diagnostic_package"]["linked"])
        self.assertTrue(result["diagnostics_complete"])
        self.assertTrue(result["joined_diagnostics_complete"])
        self.assertEqual(result["catalogue_source_sha256"],
                         hashlib.sha256(value["sources"]["catalogue_response"]).hexdigest())
        self.assertEqual(result["observed_package_sha256"], hashlib.sha256(PACKAGE).hexdigest())
        self.assertNotIn("package_path", result)
        self.assertNotIn("url", json.dumps(result))
        for key in ("metadata_signature_verified", "publisher_trust_evaluated",
                    "certificate_chain_evaluated", "complete_revocation_status_evaluated",
                    "package_applicability_evaluated", "version_comparison_performed",
                    "downloaded", "installed", "install_permitted",
                    "updater_network_request_initiated"):
            self.assertFalse(result[key], key)
        self.assertIsNone(result["updates_available"])

    def test_negative_metadata_stage_preserves_independent_package_link(self):
        value = case(self.root, metadata_status="failed")
        result = join(value)
        self.assertFalse(result["diagnostics_complete"])
        self.assertTrue(result["links"]["source_package"]["linked"])
        self.assertTrue(result["links"]["diagnostic_package"]["linked"])
        self.assertFalse(result["joined_diagnostics_complete"])

    def test_missing_metadata_receipt_or_incomplete_http_keeps_only_source_package_link(self):
        for option in ({"omit_metadata_source": True}, {"incomplete_http": True}):
            with self.subTest(option=option):
                value = case(self.root, **option)
                result = join(value)
                self.assertTrue(result["links"]["source_package"]["linked"])
                self.assertFalse(result["links"]["diagnostic_package"]["linked"])
                self.assertFalse(result["links"]["diagnostic_package"]["catalogue_metadata_provenance_linked"])
                self.assertFalse(result["joined_diagnostics_complete"])

    def test_other_version_canonical_metadata_does_not_borrow_package_link(self):
        value = case(self.root)
        other_dir = self.root / "other"
        other_dir.mkdir()
        other = case(other_dir, version="1.20.0")
        changed_raw = dict(value["raw"])
        metadata = json.loads(changed_raw["metadata"])
        other_metadata = json.loads(other["raw"]["metadata"])
        metadata["stages"][0] = other_metadata["stages"][0]
        changed_raw["metadata"] = encode(metadata)
        diagnostic = compose_update_diagnostic_bundle(
            changed_raw["catalogue"], changed_raw["metadata"],
            changed_raw["revocation"], changed_raw["conditions"],
            node_id=NODE,
            catalogue_response_bytes=value["sources"]["catalogue_response"],
            revocation_input_bytes=value["sources"]["revocation_input"],
            conditions_input_bytes=value["sources"]["conditions_input"],
            context_input_bytes=value["sources"]["context_input"],
        ).as_dict()
        result = join(value, raw=changed_raw, diagnostic=diagnostic)
        self.assertTrue(result["links"]["source_package"]["linked"])
        self.assertFalse(result["links"]["diagnostic_package"]["linked"])
        self.assertFalse(result["links"]["diagnostic_package"]["canonical_node_matches"])

    def test_same_id_other_version_bundle_cannot_replace_selected_report(self):
        first = case(self.root)
        other_dir = self.root / "other"
        other_dir.mkdir()
        other = case(other_dir, version="1.20.0")
        result = join(first, diagnostic=other["diagnostic"])
        self.assertFalse(result["links"]["diagnostic_package"]["linked"])
        self.assertFalse(result["links"]["diagnostic_package"]["diagnostic_report_reproduced"])
        self.assertTrue(result["links"]["source_package"]["linked"])
        self.assertFalse(result["joined_diagnostics_complete"])

    def test_same_id_other_version_package_receipt_cannot_replace_selected_file(self):
        first = case(self.root)
        other_dir = self.root / "other"
        other_dir.mkdir()
        other = case(other_dir, version="1.20.0", package=b"another synthetic package")
        result = join(first, receipt=other["receipt"])
        self.assertFalse(result["links"]["diagnostic_package"]["linked"])
        self.assertFalse(result["links"]["source_package"]["package_receipt_reproduced"])

    def test_substituted_raw_catalogue_rejects_cross_source_join(self):
        first = case(self.root)
        other_dir = self.root / "other"
        other_dir.mkdir()
        other = case(other_dir, version="1.20.0")
        sources = dict(first["sources"])
        sources["catalogue_response"] = other["sources"]["catalogue_response"]
        result = join(first, sources=sources)
        self.assertFalse(result["links"]["diagnostic_package"]["linked"])
        self.assertFalse(result["links"]["diagnostic_package"]["catalogue_metadata_provenance_linked"])

    def test_changed_local_file_recomputes_observed_digest_and_fails(self):
        value = case(self.root)
        value["path"].write_bytes(b"X" * len(PACKAGE))
        result = join(value)
        self.assertFalse(result["links"]["source_package"]["linked"])
        self.assertFalse(result["links"]["source_package"]["package_receipt_reproduced"])
        self.assertFalse(result["links"]["source_package"]["bytes_match_catalogue_descriptor"])

    def test_supplied_descriptor_identity_and_observed_fields_are_rechecked(self):
        value = case(self.root)
        changes = {
            "catalogue_source_sha256": "0" * 64,
            "selected_node_sha256": "0" * 64,
            "canonical_node_sha256": "0" * 64,
            "node_id": "same-id-other-source",
            "file_id": "other-file",
            "declared_size": len(PACKAGE) + 1,
            "declared_sha1": "0" * 40,
            "observed_size": len(PACKAGE) + 1,
            "observed_sha1": "0" * 40,
            "observed_sha256": "0" * 64,
        }
        for field, replacement in changes.items():
            with self.subTest(field=field):
                forged = dict(value["receipt"])
                forged[field] = replacement
                result = join(value, receipt=forged)
                self.assertFalse(result["links"]["source_package"]["linked"])
                self.assertFalse(result["links"]["source_package"]["package_receipt_reproduced"])

    def test_duplicate_file_id_fails_closed(self):
        value = case(self.root)
        source = json.loads(value["sources"]["catalogue_response"])
        source["data"][0]["files"].append(copy.deepcopy(source["data"][0]["files"][0]))
        sources = dict(value["sources"])
        sources["catalogue_response"] = encode(source)
        with self.assertRaises(ValueError):
            join(value, sources=sources)

    def test_forged_trust_claim_or_json_type_change_does_not_reproduce(self):
        value = case(self.root)
        for field, replacement in (("install_permitted", True),
                                   ("diagnostics_complete", 1)):
            changed = copy.deepcopy(value["diagnostic"])
            changed[field] = replacement
            with self.subTest(field=field):
                result = join(value, diagnostic=changed)
                self.assertFalse(result["links"]["diagnostic_package"]["linked"])
                self.assertFalse(result["links"]["diagnostic_package"]["diagnostic_report_reproduced"])
                self.assertFalse(result["install_permitted"])

    def test_duplicate_json_key_in_supplied_receipt_is_rejected(self):
        value = case(self.root)
        duplicate = encode(value["receipt"]).replace(
            b'"file_id":"synthetic-installer"',
            b'"file_id":"synthetic-installer","file_id":"synthetic-installer"',
        )
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            compose_update_package_bundle(
                value["raw"]["catalogue"], value["raw"]["metadata"],
                value["raw"]["revocation"], value["raw"]["conditions"],
                encode(value["diagnostic"]), duplicate,
                catalogue_response_bytes=value["sources"]["catalogue_response"],
                revocation_input_bytes=value["sources"]["revocation_input"],
                conditions_input_bytes=value["sources"]["conditions_input"],
                context_input_bytes=value["sources"]["context_input"],
                node_id=NODE, file_id=FILE_ID, package_path=value["path"],
            )
