"""Bind retained update diagnostics to their exact report files.

This is a provenance composer, not an updater.  It parses the four exact
report byte streams itself, verifies every currently provable cross-report
receipt, and leaves trust, availability, download and installation decisions
explicitly unevaluated.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from .toolkit_update_conditions import STAGES as CONDITION_STAGES
from .toolkit_update_metadata import MAX_NODE_BYTES, STAGES as METADATA_STAGES, _json
from .toolkit_update_revocation import STAGES as REVOCATION_STAGES


MAX_REPORT_BYTES = MAX_NODE_BYTES
_HEX40 = re.compile(r"[0-9A-Fa-f]{40}\Z", re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class UpdateBundleError(ValueError):
    """The supplied reports cannot be safely interpreted as bounded evidence."""


def _parse(raw: bytes, name: str) -> dict:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_REPORT_BYTES:
        raise UpdateBundleError(
            f"{name} report must be nonempty bytes within {MAX_REPORT_BYTES} bytes"
        )
    try:
        value = _json(raw, limit=MAX_REPORT_BYTES, depth_limit=32)
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise UpdateBundleError(f"{name} report is not bounded unique-key JSON: {error}") from error
    if type(value) is not dict:
        raise UpdateBundleError(f"{name} report must be a JSON object")
    return value


def _object(value, name: str) -> dict:
    if type(value) is not dict:
        raise UpdateBundleError(name + " must be a JSON object")
    return value


def _boolean(value, name: str) -> bool:
    if type(value) is not bool:
        raise UpdateBundleError(name + " must be a Boolean")
    return value


def _sha256(value, name: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise UpdateBundleError(name + " must be a lowercase SHA-256 digest")
    return value


def _thumbprint(value, name: str) -> str:
    if type(value) is not str or _HEX40.fullmatch(value) is None:
        raise UpdateBundleError(name + " must be a 40-digit hexadecimal thumbprint")
    return value.upper()


def _stages(report: dict, expected: tuple[str, ...], name: str):
    rows = report.get("stages")
    if type(rows) is not list or len(rows) != len(expected):
        raise UpdateBundleError(name + " must contain every bounded stage exactly once")
    statuses = []
    by_name = {}
    for index, (row, stage) in enumerate(zip(rows, expected, strict=True)):
        if type(row) is not dict or row.get("stage") != stage:
            raise UpdateBundleError(
                f"{name} stage {index} must be {stage!r} in retained order"
            )
        status = row.get("status")
        if status not in ("passed", "failed", "unsupported", "not_run"):
            raise UpdateBundleError(name + " contains an unknown stage status")
        statuses.append(status)
        by_name[stage] = row
    return tuple(statuses), by_name


def _unevaluated(report: dict, field: str, name: str):
    value = _object(report.get(field), name + "." + field)
    if value.get("status") != "not_evaluated":
        raise UpdateBundleError(name + "." + field + " must remain not_evaluated")


def _link(linked: bool, reason: str, **details):
    return {"linked": linked, "reason": None if linked else reason, **details}


def _canonical_object(stage_rows: dict):
    row = stage_rows["canonicalization"]
    raw = row.get("canonical_utf8")
    if row.get("status") != "passed" or type(raw) is not str:
        return None
    try:
        value = _json(raw.encode("utf-8"), limit=MAX_REPORT_BYTES, depth_limit=32)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return None
    return value if type(value) is dict else None


@dataclass(frozen=True)
class UpdateDiagnosticBundle:
    _document: str

    @property
    def complete(self):
        return self.as_dict()["diagnostics_complete"]

    def as_dict(self):
        return json.loads(self._document)


def compose_update_diagnostic_bundle(
    catalogue_bytes: bytes,
    metadata_bytes: bytes,
    revocation_bytes: bytes,
    conditions_bytes: bytes,
    *,
    node_id: str,
) -> UpdateDiagnosticBundle:
    """Compose one report from the four exact files supplied by the caller.

    Parsed objects are intentionally not accepted.  This prevents a caller
    from supplying one object for validation and unrelated bytes for hashing.
    """
    if (
        type(node_id) is not str
        or not node_id
        or len(node_id) > 256
        or any(0xD800 <= ord(character) <= 0xDFFF for character in node_id)
    ):
        raise UpdateBundleError("node_id must be bounded nonempty Unicode text")

    raw = {
        "catalogue": catalogue_bytes,
        "metadata": metadata_bytes,
        "revocation": revocation_bytes,
        "conditions": conditions_bytes,
    }
    reports = {name: _parse(value, name) for name, value in raw.items()}
    catalogue = reports["catalogue"]
    metadata = reports["metadata"]
    revocation = reports["revocation"]
    conditions = reports["conditions"]

    catalogue_complete = _boolean(catalogue.get("complete"), "catalogue.complete")
    candidates = catalogue.get("candidates")
    if type(candidates) is not list or len(candidates) > 256:
        raise UpdateBundleError("catalogue.candidates must be an array of at most 256 objects")
    identities = []
    for index, candidate in enumerate(candidates):
        if type(candidate) is not dict:
            raise UpdateBundleError(f"catalogue candidate {index} must be an object")
        identity = candidate.get("node_id")
        if type(identity) is not str or not identity or len(identity) > 256:
            raise UpdateBundleError(f"catalogue candidate {index} has an invalid node_id")
        identities.append(identity)
    if len(set(identities)) != len(identities):
        raise UpdateBundleError(
            "catalogue contains an ambiguous repeated node_id, including same-ID version variants"
        )
    selected = [candidate for candidate in candidates if candidate["node_id"] == node_id]
    if len(selected) != 1:
        raise UpdateBundleError("node_id must select exactly one catalogue candidate")

    if catalogue.get("metadata_signature_verified") is not False:
        raise UpdateBundleError("catalogue must not claim a verified metadata signature")
    if catalogue.get("applicability_verified") is not False:
        raise UpdateBundleError("catalogue must not claim verified applicability")
    if catalogue.get("updates_available") is not None:
        raise UpdateBundleError("catalogue must not claim update availability")

    http = catalogue.get("http")
    catalogue_body_sha256 = None
    http_complete = False
    if http is not None:
        http = _object(http, "catalogue.http")
        catalogue_body_sha256 = _sha256(
            http.get("body_sha256"), "catalogue.http.body_sha256"
        )
        http_complete = _boolean(http.get("complete"), "catalogue.http.complete") and _boolean(
            http.get("body_complete"), "catalogue.http.body_complete"
        )
    catalogue_receipt_complete = (
        catalogue_complete
        and catalogue.get("error") is None
        and http_complete
        and catalogue_body_sha256 is not None
    )

    metadata_status, metadata_rows = _stages(
        metadata, METADATA_STAGES, "metadata report"
    )
    _unevaluated(metadata, "publisher_trust", "metadata")
    _unevaluated(metadata, "revocation", "metadata")
    _unevaluated(metadata, "applicability", "metadata")
    metadata_input_sha256 = _sha256(
        metadata.get("input_node_sha256"), "metadata.input_node_sha256"
    )
    metadata_thumbprint = _thumbprint(
        metadata.get("certificate_thumbprint_sha1"),
        "metadata.certificate_thumbprint_sha1",
    )
    canonical_node = _canonical_object(metadata_rows)
    metadata_source = metadata.get("source")
    metadata_source_receipt = False
    metadata_source_sha256 = None
    selected_node_sha256 = None
    selected_node_id = None
    if type(metadata_source) is dict:
        try:
            metadata_source_sha256 = _sha256(
                metadata_source.get("file_sha256"), "metadata.source.file_sha256"
            )
            selected_node_sha256 = _sha256(
                metadata_source.get("selected_node_sha256"),
                "metadata.source.selected_node_sha256",
            )
            selected_node_id = metadata_source.get("selected_node_id")
            metadata_source_receipt = (
                metadata_source.get("selection")
                == "unique-node-from-raw-catalogue-response"
                and metadata_source.get("selected_node_representation")
                == "normalized UTF-8 JSON; not an original byte slice"
                and selected_node_id == node_id
                and selected_node_sha256 == metadata_input_sha256
            )
        except UpdateBundleError:
            metadata_source_receipt = False
    canonical_identity_matches = (
        canonical_node is not None and canonical_node.get("nodeId") == node_id
    )
    catalogue_metadata_linked = (
        catalogue_receipt_complete
        and metadata_source_receipt
        and metadata_source_sha256 == catalogue_body_sha256
        and canonical_identity_matches
    )
    catalogue_metadata_reason = (
        "catalogue HTTP body receipt is incomplete"
        if not catalogue_receipt_complete
        else "metadata source receipt is absent or incomplete"
        if not metadata_source_receipt
        else "metadata source hash does not match the catalogue response body"
        if metadata_source_sha256 != catalogue_body_sha256
        else "metadata canonical node identity does not match the selected candidate"
    )

    condition_status, _ = _stages(
        conditions, CONDITION_STAGES, "conditions report"
    )
    if conditions.get("package_applicability_evaluated") is not False:
        raise UpdateBundleError("conditions must not claim package applicability")
    if conditions.get("publisher_trust_evaluated") is not False:
        raise UpdateBundleError("conditions must not claim publisher trust")
    if conditions.get("updates_available") is not None:
        raise UpdateBundleError("conditions must not claim update availability")
    condition_result = conditions.get("condition_result_under_supplied_context")
    if condition_result is not None and type(condition_result) is not bool:
        raise UpdateBundleError("condition result must be Boolean or null")
    condition_source = conditions.get("source")
    condition_receipts_match = False
    if type(condition_source) is dict:
        try:
            condition_receipts_match = (
                _sha256(
                    conditions.get("conditions_sha256"),
                    "conditions.conditions_sha256",
                )
                == _sha256(
                    condition_source.get("conditions_file_sha256"),
                    "conditions.source.conditions_file_sha256",
                )
                and _sha256(
                    conditions.get("context_sha256"), "conditions.context_sha256"
                )
                == _sha256(
                    condition_source.get("context_file_sha256"),
                    "conditions.source.context_file_sha256",
                )
            )
        except UpdateBundleError:
            condition_receipts_match = False
    metadata_conditions = None
    if canonical_node is not None and type(canonical_node.get("data")) is dict:
        metadata_conditions = canonical_node["data"].get("clientConditionData")
    condition_model_matches = (
        metadata_conditions is not None
        and conditions.get("raw_typed_data") == metadata_conditions
    )
    metadata_conditions_linked = condition_receipts_match and condition_model_matches
    metadata_conditions_reason = (
        "condition input/context receipts are absent or inconsistent"
        if not condition_receipts_match
        else "condition report does not describe the selected metadata condition model"
    )

    revocation_status, revocation_rows = _stages(
        revocation, REVOCATION_STAGES, "revocation report"
    )
    for field in (
        "publisher_trust",
        "certificate_chain",
        "complete_revocation_status",
        "applicability",
    ):
        _unevaluated(revocation, field, "revocation")
    revocation_input_sha256 = _sha256(
        revocation.get("input_revocation_sha256"),
        "revocation.input_revocation_sha256",
    )
    revocation_source = revocation.get("source")
    revocation_receipt = False
    revocation_source_sha256 = None
    if type(revocation_source) is dict:
        try:
            revocation_source_sha256 = _sha256(
                revocation_source.get("file_sha256"),
                "revocation.source.file_sha256",
            )
            selected_data_sha256 = _sha256(
                revocation_source.get("selected_data_sha256"),
                "revocation.source.selected_data_sha256",
            )
            selection = revocation_source.get("selection")
            representation = revocation_source.get("selected_data_representation")
            revocation_receipt = selected_data_sha256 == revocation_input_sha256 and (
                (
                    selection == "complete-data-file"
                    and representation == "original-input-bytes"
                    and revocation_source_sha256 == selected_data_sha256
                )
                or (
                    selection == "normalized-data-from-raw-response"
                    and representation
                    == "normalized UTF-8 JSON; not an original byte slice"
                )
            )
        except UpdateBundleError:
            revocation_receipt = False
    claimed_lists = revocation.get("claimed_lists")
    revocation_subject = None
    subject_matches = False
    claimed_lists_match_canonical = False
    canonical_revocation = _canonical_object(revocation_rows)
    if type(claimed_lists) is dict:
        try:
            revocation_subject = _thumbprint(
                claimed_lists.get("id"), "revocation.claimed_lists.id"
            )
            subject_matches = revocation_subject == metadata_thumbprint
            claimed_lists_match_canonical = (
                canonical_revocation is not None
                and canonical_revocation.get("id") == claimed_lists.get("id")
                and canonical_revocation.get("revokedCertificates")
                == claimed_lists.get("revoked_certificates")
                and canonical_revocation.get("revokedSignatures")
                == claimed_lists.get("revoked_signatures")
            )
        except UpdateBundleError:
            subject_matches = False
    metadata_revocation_linked = (
        revocation_receipt and claimed_lists_match_canonical and subject_matches
    )
    metadata_revocation_reason = (
        "revocation source receipt is absent or inconsistent"
        if not revocation_receipt
        else "revocation claimed lists do not match the evaluated canonical input"
        if not claimed_lists_match_canonical
        else "revocation subject does not match the metadata certificate"
    )

    links = {
        "catalogue_metadata": _link(
            catalogue_metadata_linked,
            catalogue_metadata_reason,
            catalogue_body_sha256=catalogue_body_sha256,
            metadata_source_sha256=metadata_source_sha256,
            canonical_node_id_matches=canonical_identity_matches,
        ),
        "metadata_conditions": _link(
            metadata_conditions_linked,
            metadata_conditions_reason,
            source_receipts_match=condition_receipts_match,
            condition_model_matches=condition_model_matches,
        ),
        "metadata_revocation": _link(
            metadata_revocation_linked,
            metadata_revocation_reason,
            metadata_certificate_thumbprint_sha1=metadata_thumbprint,
            revocation_subject_id=revocation_subject,
            claimed_lists_match_canonical=claimed_lists_match_canonical,
            subject_identifier_matches=subject_matches,
            complete_revocation_status_evaluated=False,
        ),
    }
    stage_status = {
        "metadata": list(metadata_status),
        "revocation": list(revocation_status),
        "conditions": list(condition_status),
    }
    diagnostics_complete = (
        all(link["linked"] for link in links.values())
        and all(status == "passed" for rows in stage_status.values() for status in rows)
        and type(condition_result) is bool
    )
    document = {
        "format": "cbus-toolkit-update-diagnostic-bundle-v2",
        "scope": "Exact-file-linked catalogue and offline diagnostic evidence for one selected node",
        "selected_node_id": node_id,
        "selected_node_sha256": selected_node_sha256,
        "installed_version": catalogue.get("installed_version"),
        "catalogue_complete": catalogue_complete,
        "links": links,
        "stage_status": stage_status,
        "condition_result_under_supplied_context": condition_result,
        "diagnostics_complete": diagnostics_complete,
        "publisher_trust_evaluated": False,
        "certificate_chain_evaluated": False,
        "complete_revocation_status_evaluated": False,
        "package_applicability_evaluated": False,
        "version_comparison_performed": False,
        "updates_available": None,
        "latest_version": None,
        "downloaded": False,
        "installed": False,
        "install_permitted": False,
        "network_accessed": False,
        "registry_accessed": False,
        "certificate_store_accessed": False,
        "input_sha256": {
            name: hashlib.sha256(value).hexdigest() for name, value in raw.items()
        },
    }
    return UpdateDiagnosticBundle(
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    )
