"""Exact-byte provenance and cross-report linkage for update diagnostics."""
import copy
import hashlib
import json
import unittest

from cbus_toolkit.toolkit_update_bundle import (
    UpdateBundleError,
    compose_update_diagnostic_bundle,
)
from cbus_toolkit.toolkit_update_conditions import STAGES as CONDITION_STAGES
from cbus_toolkit.toolkit_update_metadata import STAGES as METADATA_STAGES
from cbus_toolkit.toolkit_update_revocation import STAGES as REVOCATION_STAGES


NODE = "435e4274-3bcf-4f3e-a67a-3008278c539c"
CERTIFICATE = "A" * 40
CATALOGUE_BODY = b'{"data":[{"nodeId":"' + NODE.encode() + b'"}]}'
SELECTED_NODE = b'{"nodeId":"selected"}'
REVOCATION_DATA = b'{"id":"' + CERTIFICATE.encode() + b'"}'
CONDITION_MODEL = {"expression": "true", "conditions": {}}
CONDITION_INPUT = b'{"expression":"true","conditions":{}}'
CONTEXT_INPUT = b'{"format":"cbus-toolkit-condition-context-v1"}'


def encode(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def stage_rows(names, status="passed"):
    return [{"stage": name, "status": status} for name in names]


def reports(*, condition=True):
    body_digest = hashlib.sha256(CATALOGUE_BODY).hexdigest()
    node_digest = hashlib.sha256(SELECTED_NODE).hexdigest()
    revocation_digest = hashlib.sha256(REVOCATION_DATA).hexdigest()
    conditions_digest = hashlib.sha256(CONDITION_INPUT).hexdigest()
    context_digest = hashlib.sha256(CONTEXT_INPUT).hexdigest()
    canonical_node = {
        "nodeId": NODE,
        "data": {"clientConditionData": CONDITION_MODEL},
    }
    metadata_stages = stage_rows(METADATA_STAGES)
    metadata_stages[0]["canonical_utf8"] = json.dumps(
        canonical_node, separators=(",", ":"), sort_keys=True
    )
    revocation_stages = stage_rows(REVOCATION_STAGES)
    revocation_stages[0]["canonical_utf8"] = json.dumps(
        {
            "id": CERTIFICATE,
            "revokedCertificates": [],
            "revokedSignatures": [],
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "catalogue": {
            "complete": True,
            "error": None,
            "installed_version": "1.18.0.2754",
            "http": {
                "complete": True,
                "body_complete": True,
                "body_sha256": body_digest,
            },
            "candidates": [
                {"node_id": NODE, "name": "Toolkit 1.19.0", "version": None}
            ],
            "metadata_signature_verified": False,
            "applicability_verified": False,
            "updates_available": None,
        },
        "metadata": {
            "input_node_sha256": node_digest,
            "certificate_thumbprint_sha1": CERTIFICATE,
            "publisher_trust": {"status": "not_evaluated"},
            "revocation": {"status": "not_evaluated"},
            "applicability": {"status": "not_evaluated"},
            "stages": metadata_stages,
            "source": {
                "file_sha256": body_digest,
                "selection": "unique-node-from-raw-catalogue-response",
                "selected_node_id": NODE,
                "selected_node_representation": (
                    "normalized UTF-8 JSON; not an original byte slice"
                ),
                "selected_node_sha256": node_digest,
            },
        },
        "revocation": {
            "input_revocation_sha256": revocation_digest,
            "publisher_trust": {"status": "not_evaluated"},
            "certificate_chain": {"status": "not_evaluated"},
            "complete_revocation_status": {"status": "not_evaluated"},
            "applicability": {"status": "not_evaluated"},
            "stages": revocation_stages,
            "claimed_lists": {
                "id": CERTIFICATE,
                "revoked_certificates": [],
                "revoked_signatures": [],
                "request_subject_association_verified": False,
            },
            "source": {
                "file_sha256": revocation_digest,
                "selection": "complete-data-file",
                "selected_data_representation": "original-input-bytes",
                "selected_data_sha256": revocation_digest,
            },
        },
        "conditions": {
            "conditions_sha256": conditions_digest,
            "context_sha256": context_digest,
            "raw_typed_data": CONDITION_MODEL,
            "stages": stage_rows(CONDITION_STAGES),
            "condition_result_under_supplied_context": condition,
            "package_applicability_evaluated": False,
            "publisher_trust_evaluated": False,
            "updates_available": None,
            "source": {
                "conditions_file_sha256": conditions_digest,
                "context_file_sha256": context_digest,
                "representation": (
                    "Exact supplied file bytes; normalized model reported separately"
                ),
            },
        },
    }


def encoded_reports(values=None):
    values = reports() if values is None else values
    return {name: encode(value) for name, value in values.items()}


def compose(raw):
    return compose_update_diagnostic_bundle(
        raw["catalogue"],
        raw["metadata"],
        raw["revocation"],
        raw["conditions"],
        node_id=NODE,
    )


class UpdateDiagnosticBundleTests(unittest.TestCase):
    def test_valid_exact_reports_link_all_three_relationships(self):
        raw = encoded_reports()
        result = compose(raw).as_dict()
        self.assertTrue(result["diagnostics_complete"])
        self.assertEqual(
            {name: link["linked"] for name, link in result["links"].items()},
            {
                "catalogue_metadata": True,
                "metadata_conditions": True,
                "metadata_revocation": True,
            },
        )
        self.assertEqual(
            result["input_sha256"],
            {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
        )
        self.assertIsNone(result["updates_available"])
        for field in (
            "publisher_trust_evaluated",
            "certificate_chain_evaluated",
            "complete_revocation_status_evaluated",
            "package_applicability_evaluated",
            "version_comparison_performed",
            "downloaded",
            "installed",
            "install_permitted",
            "network_accessed",
            "registry_accessed",
            "certificate_store_accessed",
        ):
            self.assertFalse(result[field])

    def test_false_condition_is_a_complete_calculation_not_applicability(self):
        values = reports(condition=False)
        result = compose(encoded_reports(values)).as_dict()
        self.assertTrue(result["diagnostics_complete"])
        self.assertIs(result["condition_result_under_supplied_context"], False)
        self.assertFalse(result["package_applicability_evaluated"])

    def test_substituted_report_bytes_are_parsed_instead_of_a_separate_object(self):
        values = reports()
        raw = encoded_reports(values)
        substituted = copy.deepcopy(values["metadata"])
        substituted["source"]["file_sha256"] = "b" * 64
        raw["metadata"] = encode(substituted)
        result = compose(raw).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["catalogue_metadata"]["linked"])
        self.assertEqual(
            result["input_sha256"]["metadata"],
            hashlib.sha256(raw["metadata"]).hexdigest(),
        )

    def test_duplicate_json_keys_are_rejected_before_schema_validation(self):
        raw = encoded_reports()
        raw["catalogue"] = raw["catalogue"].replace(
            b'{"applicability_verified":false,',
            b'{"applicability_verified":false,"applicability_verified":false,',
            1,
        )
        with self.assertRaisesRegex(UpdateBundleError, "Duplicate JSON key"):
            compose(raw)

    def test_same_identity_with_different_versions_is_ambiguous(self):
        values = reports()
        values["catalogue"]["candidates"].append(
            {"node_id": NODE, "name": "Toolkit 1.20.0", "version": "1.20.0"}
        )
        with self.assertRaisesRegex(UpdateBundleError, "ambiguous repeated node_id"):
            compose(encoded_reports(values))

    def test_mismatched_catalogue_source_keeps_linked_completion_false(self):
        values = reports()
        values["metadata"]["source"]["file_sha256"] = "b" * 64
        result = compose(encoded_reports(values)).as_dict()
        link = result["links"]["catalogue_metadata"]
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(link["linked"])
        self.assertIn("does not match", link["reason"])

    def test_missing_metadata_receipt_keeps_linked_completion_false(self):
        values = reports()
        del values["metadata"]["source"]
        result = compose(encoded_reports(values)).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertEqual(
            result["links"]["catalogue_metadata"]["reason"],
            "metadata source receipt is absent or incomplete",
        )

    def test_unrelated_revocation_subject_keeps_linked_completion_false(self):
        values = reports()
        values["revocation"]["claimed_lists"]["id"] = "B" * 40
        canonical = json.loads(values["revocation"]["stages"][0]["canonical_utf8"])
        canonical["id"] = "B" * 40
        values["revocation"]["stages"][0]["canonical_utf8"] = json.dumps(
            canonical, separators=(",", ":"), sort_keys=True
        )
        result = compose(encoded_reports(values)).as_dict()
        link = result["links"]["metadata_revocation"]
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(link["linked"])
        self.assertFalse(link["subject_identifier_matches"])
        self.assertTrue(link["claimed_lists_match_canonical"])

    def test_revocation_claims_cannot_differ_from_evaluated_canonical_input(self):
        values = reports()
        values["revocation"]["claimed_lists"]["id"] = "B" * 40
        result = compose(encoded_reports(values)).as_dict()
        link = result["links"]["metadata_revocation"]
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(link["linked"])
        self.assertFalse(link["claimed_lists_match_canonical"])

    def test_unrelated_condition_model_keeps_linked_completion_false(self):
        values = reports()
        values["conditions"]["raw_typed_data"] = {
            "expression": "false",
            "conditions": {},
        }
        result = compose(encoded_reports(values)).as_dict()
        link = result["links"]["metadata_conditions"]
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(link["linked"])
        self.assertFalse(link["condition_model_matches"])

    def test_missing_condition_receipt_keeps_linked_completion_false(self):
        values = reports()
        del values["conditions"]["source"]
        result = compose(encoded_reports(values)).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["metadata_conditions"]["linked"])

    def test_failed_stage_is_retained_as_incomplete(self):
        values = reports()
        for row in values["metadata"]["stages"]:
            row["status"] = "failed"
        result = compose(encoded_reports(values)).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertEqual(result["stage_status"]["metadata"], ["failed"] * 6)

    def test_forged_trust_or_availability_claim_is_rejected(self):
        for report, field, value in (
            ("catalogue", "updates_available", True),
            ("conditions", "publisher_trust_evaluated", True),
        ):
            values = reports()
            values[report][field] = value
            with self.subTest(report=report, field=field), self.assertRaises(
                UpdateBundleError
            ):
                compose(encoded_reports(values))


if __name__ == "__main__":
    unittest.main()
