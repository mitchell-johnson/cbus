"""Exact-byte provenance and cross-report linkage for update diagnostics."""
import copy
import base64
import hashlib
import json
import unittest

from cbus_toolkit.toolkit_update_bundle import (
    UpdateBundleError,
    compose_update_diagnostic_bundle,
)
from cbus_toolkit.toolkit_update_conditions import STAGES as CONDITION_STAGES
from cbus_toolkit.toolkit_update_metadata import (
    STAGES as METADATA_STAGES,
    _canonical as canonical_metadata_node,
    select_node,
)
from cbus_toolkit.toolkit_update_revocation import STAGES as REVOCATION_STAGES
from cbus_toolkit.toolkit_updates import CATALOGUE_URL, _candidate, catalogue_request


NODE = "435e4274-3bcf-4f3e-a67a-3008278c539c"
CERTIFICATE = "A" * 40
CONDITION_MODEL = {"expression": "true", "conditions": {}}


def encode(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


CATALOGUE_NODE = {
    "nodeId": NODE,
    "nodeName": "Toolkit 1.19.0",
    "data": {"type": "PackageData", "clientConditionData": CONDITION_MODEL},
    "files": [],
    "signatures": {},
}
CATALOGUE_BODY = encode({
    "success": True,
    "statusCode": 200,
    "message": "OK",
    "data": [CATALOGUE_NODE],
})
SELECTED_NODE = select_node(CATALOGUE_BODY, node_id=NODE)
REVOCATION_DATA = encode({"id": CERTIFICATE})
CONDITION_INPUT = encode(CONDITION_MODEL)
CONTEXT_INPUT = encode({"format": "cbus-toolkit-condition-context-v1", "culture": "invariant", "files": []})


def source_documents():
    return {
        "catalogue_response": CATALOGUE_BODY,
        "revocation_input": REVOCATION_DATA,
        "conditions_input": CONDITION_INPUT,
        "context_input": CONTEXT_INPUT,
    }


def stage_rows(names, status="passed"):
    return [{"stage": name, "status": status} for name in names]


def reports(*, condition=True):
    body_digest = hashlib.sha256(CATALOGUE_BODY).hexdigest()
    node_digest = hashlib.sha256(SELECTED_NODE).hexdigest()
    revocation_digest = hashlib.sha256(REVOCATION_DATA).hexdigest()
    conditions_digest = hashlib.sha256(CONDITION_INPUT).hexdigest()
    context_digest = hashlib.sha256(CONTEXT_INPUT).hexdigest()
    metadata_stages = stage_rows(METADATA_STAGES)
    metadata_stages[0]["canonical_utf8"] = canonical_metadata_node(CATALOGUE_NODE).decode()
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
    for rows in (metadata_stages, revocation_stages):
        digest = hashlib.sha256(rows[0]["canonical_utf8"].encode()).digest()
        rows[0]["sha256_hex"] = digest.hex()
        rows[0]["sha256_base64"] = base64.b64encode(digest).decode()
    return {
        "catalogue": {
            "complete": True,
            "error": None,
            "installed_version": "1.18.0.2754",
            "endpoint": CATALOGUE_URL,
            "request_sha256": hashlib.sha256(catalogue_request("1.18.0.2754")).hexdigest(),
            "http": {
                "complete": True,
                "body_complete": True,
                "status": 200,
                "body_sha256": body_digest,
                "headers": [],
                "body_bytes_retained": len(CATALOGUE_BODY),
                "bytes_received": len(CATALOGUE_BODY),
                "request_attempted": True,
                "error": None,
                "cleanup": [],
                "end_to_end_deadline_bounded": False,
            },
            "body_success": True,
            "body_status": 200,
            "body_message": "OK",
            "candidates": [_candidate(CATALOGUE_NODE).as_dict()],
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
            "supplied_context": json.loads(CONTEXT_INPUT),
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


def compose(raw, *, sources=None):
    sources = source_documents() if sources is None else sources
    return compose_update_diagnostic_bundle(
        raw["catalogue"],
        raw["metadata"],
        raw["revocation"],
        raw["conditions"],
        node_id=NODE,
        catalogue_response_bytes=sources.get("catalogue_response"),
        revocation_input_bytes=sources.get("revocation_input"),
        conditions_input_bytes=sources.get("conditions_input"),
        context_input_bytes=sources.get("context_input"),
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
        self.assertEqual(
            result["source_sha256"],
            {name: hashlib.sha256(value).hexdigest() for name, value in source_documents().items()},
        )
        self.assertTrue(result["links"]["catalogue_metadata"]["canonical_digest_receipt_matches"])
        self.assertTrue(result["links"]["metadata_revocation"]["canonical_digest_receipt_matches"])
        self.assertEqual(result["format"], "cbus-toolkit-update-diagnostic-bundle-v3")
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

    def test_canonical_receipts_bind_both_digest_representations(self):
        for report, link in (("metadata", "catalogue_metadata"),
                             ("revocation", "metadata_revocation")):
            for field, value in (("sha256_hex", "0" * 64),
                                 ("sha256_base64", "unrelated-digest"),
                                 ("sha256_hex", None),
                                 ("sha256_base64", None),
                                 ("sha256_hex", True)):
                with self.subTest(report=report, field=field, value=value):
                    values = reports()
                    row = values[report]["stages"][0]
                    if value is None:
                        row.pop(field)
                    else:
                        row[field] = value
                    result = compose(encoded_reports(values)).as_dict()
                    self.assertFalse(result["diagnostics_complete"])
                    self.assertFalse(result["links"][link]["linked"])
                    self.assertFalse(result["links"][link]["canonical_digest_receipt_matches"])
                    self.assertIn("digest receipts", result["links"][link]["reason"])
                    self.assertFalse(result["install_permitted"])

    def test_canonical_digest_from_another_same_id_version_does_not_link(self):
        values = reports()
        other = copy.deepcopy(CATALOGUE_NODE)
        other["nodeName"] = "Toolkit other version"
        digest = hashlib.sha256(canonical_metadata_node(other)).digest()
        values["metadata"]["stages"][0].update(
            sha256_hex=digest.hex(), sha256_base64=base64.b64encode(digest).decode())
        result = compose(encoded_reports(values)).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertTrue(result["links"]["catalogue_metadata"]["canonical_node_matches_source"])
        self.assertFalse(result["links"]["catalogue_metadata"]["canonical_digest_receipt_matches"])

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

    def test_report_only_provenance_cannot_claim_linked_completion(self):
        result = compose(encoded_reports(), sources={}).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertEqual(
            {name: link["linked"] for name, link in result["links"].items()},
            {"catalogue_metadata": False, "metadata_conditions": False, "metadata_revocation": False},
        )
        self.assertTrue(all(value is None for value in result["source_sha256"].values()))

    def test_same_id_different_source_node_cannot_borrow_metadata_receipt(self):
        changed_node = copy.deepcopy(CATALOGUE_NODE)
        changed_node["nodeName"] = "Toolkit 1.20.0"
        changed_body = encode({"success": True, "statusCode": 200, "message": "OK", "data": [changed_node]})
        values = reports()
        digest = hashlib.sha256(changed_body).hexdigest()
        values["catalogue"]["http"]["body_sha256"] = digest
        values["catalogue"]["candidates"] = [_candidate(changed_node).as_dict()]
        values["metadata"]["source"]["file_sha256"] = digest
        source = source_documents()
        source["catalogue_response"] = changed_body
        result = compose(encoded_reports(values), sources=source).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertTrue(result["links"]["catalogue_metadata"]["catalogue_source_matches"])
        self.assertFalse(result["links"]["catalogue_metadata"]["selected_node_matches_source"])

    def test_catalogue_summary_and_canonical_stage_must_match_source(self):
        values = reports()
        values["catalogue"]["candidates"][0]["name"] = "Substituted summary"
        result = compose(encoded_reports(values)).as_dict()
        self.assertFalse(result["links"]["catalogue_metadata"]["catalogue_source_matches"])
        values = reports()
        canonical = json.loads(values["metadata"]["stages"][0]["canonical_utf8"])
        canonical["nodeName"] = "Substituted canonical node"
        values["metadata"]["stages"][0]["canonical_utf8"] = encode(canonical).decode()
        result = compose(encoded_reports(values)).as_dict()
        self.assertFalse(result["links"]["catalogue_metadata"]["canonical_node_matches_source"])

    def test_catalogue_candidate_boolean_cannot_be_replaced_by_equal_json_number(self):
        for field, value in (
            ("metadata_signature_present", 0),
            ("metadata_signature_verified", 0.0),
            ("applicability_verified", 0),
        ):
            values = reports()
            values["catalogue"]["candidates"][0][field] = value
            with self.subTest(field=field, value=value):
                result = compose(encoded_reports(values)).as_dict()
                self.assertFalse(result["diagnostics_complete"])
                self.assertFalse(result["links"]["catalogue_metadata"]["catalogue_source_matches"])

    def test_catalogue_status_and_message_receipts_must_match_source(self):
        for field, value in (("body_status", 503), ("body_message", "different")):
            values = reports()
            values["catalogue"][field] = value
            with self.subTest(field=field):
                result = compose(encoded_reports(values)).as_dict()
                self.assertFalse(result["links"]["catalogue_metadata"]["catalogue_source_matches"])
        values = reports()
        values["catalogue"]["http"]["status"] = 503
        result = compose(encoded_reports(values)).as_dict()
        self.assertFalse(result["links"]["catalogue_metadata"]["linked"])
        source = source_documents()
        body = json.loads(CATALOGUE_BODY)
        body["message"] = None
        source["catalogue_response"] = encode(body)
        values = reports()
        values["catalogue"]["body_message"] = None
        values["catalogue"]["http"]["body_sha256"] = hashlib.sha256(source["catalogue_response"]).hexdigest()
        values["catalogue"]["http"]["body_bytes_retained"] = len(source["catalogue_response"])
        values["catalogue"]["http"]["bytes_received"] = len(source["catalogue_response"])
        values["metadata"]["source"]["file_sha256"] = values["catalogue"]["http"]["body_sha256"]
        result = compose(encoded_reports(values), sources=source).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["catalogue_metadata"]["catalogue_source_matches"])

    def test_contradictory_catalogue_http_receipt_cannot_link(self):
        for field, value in (
            ("error", {"stage": "response_body", "type": "IncompleteRead", "message": "truncated"}),
            ("error", "missing"),
            ("request_attempted", False),
            ("body_bytes_retained", 1),
            ("bytes_received", 1),
            ("cleanup", [{"resource": "response", "attempted": True,
                          "succeeded": False, "error": {"type": "OSError"}}]),
        ):
            values = reports()
            if value == "missing":
                del values["catalogue"]["http"][field]
            else:
                values["catalogue"]["http"][field] = value
            with self.subTest(field=field, value=value):
                result = compose(encoded_reports(values)).as_dict()
                self.assertFalse(result["diagnostics_complete"])
                self.assertFalse(result["links"]["catalogue_metadata"]["linked"])
                self.assertEqual(
                    result["links"]["catalogue_metadata"]["reason"],
                    "catalogue HTTP body receipt is incomplete",
                )

    def test_catalogue_request_and_endpoint_receipt_bind_installed_version(self):
        for field, value in (
            ("installed_version", "1.19.0.2754"),
            ("installed_version", 1),
            ("request_sha256", "f" * 64),
            ("endpoint", "https://unrelated.invalid/collections/PackageData/list"),
        ):
            values = reports()
            values["catalogue"][field] = value
            with self.subTest(field=field, value=value):
                result = compose(encoded_reports(values)).as_dict()
                link = result["links"]["catalogue_metadata"]
                self.assertFalse(result["diagnostics_complete"])
                self.assertFalse(link["request_receipt_matches"])
                self.assertEqual(
                    link["reason"],
                    "catalogue request or endpoint receipt does not match the installed version",
                )
        for field in ("request_sha256", "endpoint"):
            values = reports()
            del values["catalogue"][field]
            with self.subTest(missing=field):
                result = compose(encoded_reports(values)).as_dict()
                self.assertFalse(result["diagnostics_complete"])
                self.assertFalse(result["links"]["catalogue_metadata"]["request_receipt_matches"])

    def test_alternate_declared_installed_version_with_its_request_receipt_is_allowed(self):
        values = reports()
        values["catalogue"]["installed_version"] = "1.17.0.0"
        values["catalogue"]["request_sha256"] = hashlib.sha256(
            catalogue_request("1.17.0.0")
        ).hexdigest()
        result = compose(encoded_reports(values)).as_dict()
        self.assertTrue(result["diagnostics_complete"])
        self.assertTrue(result["links"]["catalogue_metadata"]["request_receipt_matches"])
        self.assertFalse(result["version_comparison_performed"])

    def test_substituted_source_bytes_and_duplicate_source_keys_fail_closed(self):
        source = source_documents()
        source["catalogue_response"] = encode({**json.loads(CATALOGUE_BODY), "message": "different"})
        result = compose(encoded_reports(), sources=source).as_dict()
        self.assertFalse(result["links"]["catalogue_metadata"]["catalogue_source_matches"])
        source["catalogue_response"] = CATALOGUE_BODY.replace(b'"success":true', b'"success":true,"success":true', 1)
        with self.assertRaisesRegex(UpdateBundleError, "Duplicate JSON key"):
            compose(encoded_reports(), sources=source)

    def test_duplicate_selected_identity_in_raw_response_is_rejected(self):
        source = source_documents()
        response = json.loads(CATALOGUE_BODY)
        response["data"].append({**CATALOGUE_NODE, "nodeName": "Toolkit 1.20.0"})
        source["catalogue_response"] = encode(response)
        with self.assertRaisesRegex(UpdateBundleError, "ambiguous repeated node_id"):
            compose(encoded_reports(), sources=source)

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

    def test_revocation_response_selection_is_bound_to_exact_source(self):
        response = encode({"success": True, "statusCode": 200, "data": json.loads(REVOCATION_DATA)})
        values = reports()
        values["revocation"]["source"].update({
            "file_sha256": hashlib.sha256(response).hexdigest(),
            "selection": "normalized-data-from-raw-response",
            "selected_data_representation": "normalized UTF-8 JSON; not an original byte slice",
        })
        source = source_documents()
        source["revocation_input"] = response
        self.assertTrue(compose(encoded_reports(values), sources=source).complete)
        source["revocation_input"] = encode({"success": True, "statusCode": 200, "data": {"id": "B" * 40}})
        result = compose(encoded_reports(values), sources=source).as_dict()
        self.assertFalse(result["links"]["metadata_revocation"]["revocation_source_matches"])

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

    def test_condition_and_context_reports_are_bound_to_source_contents(self):
        values = reports()
        source = source_documents()
        different_context = encode({"format": "cbus-toolkit-condition-context-v1", "culture": "invariant", "files": ["other"]})
        digest = hashlib.sha256(different_context).hexdigest()
        values["conditions"]["context_sha256"] = digest
        values["conditions"]["source"]["context_file_sha256"] = digest
        source["context_input"] = different_context
        result = compose(encoded_reports(values), sources=source).as_dict()
        self.assertFalse(result["links"]["metadata_conditions"]["condition_sources_match"])
        source = source_documents()
        source["conditions_input"] = encode({"expression": "false", "conditions": {}})
        result = compose(encoded_reports(), sources=source).as_dict()
        self.assertFalse(result["links"]["metadata_conditions"]["condition_sources_match"])

    def test_context_boolean_cannot_be_replaced_by_equal_json_number(self):
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
        values["conditions"]["supplied_context"] = copy.deepcopy(context)
        self.assertTrue(compose(encoded_reports(values), sources=source).complete)
        values["conditions"]["supplied_context"]["files"][0]["exists"] = 1
        result = compose(encoded_reports(values), sources=source).as_dict()
        self.assertFalse(result["diagnostics_complete"])
        self.assertFalse(result["links"]["metadata_conditions"]["condition_sources_match"])

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
