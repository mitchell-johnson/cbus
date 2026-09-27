"""Link exact update diagnostics to one already-local package-file receipt.

Both supplied producer reports are reproduced from their original inputs.
This is an offline provenance check, not publisher trust or install approval.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os

from .toolkit_update_bundle import _parse, _same_json, compose_update_diagnostic_bundle
from .toolkit_update_package_file import MAX_PACKAGE_BYTES, inspect_update_package_file


@dataclass(frozen=True)
class UpdatePackageBundle:
    _document: str

    @property
    def complete(self) -> bool:
        return self.as_dict()["joined_diagnostics_complete"]

    def as_dict(self) -> dict:
        return json.loads(self._document)


def compose_update_package_bundle(
    catalogue_bytes: bytes,
    metadata_bytes: bytes,
    revocation_bytes: bytes,
    conditions_bytes: bytes,
    diagnostic_bundle_bytes: bytes,
    package_receipt_bytes: bytes,
    *,
    catalogue_response_bytes: bytes,
    revocation_input_bytes: bytes,
    conditions_input_bytes: bytes,
    context_input_bytes: bytes,
    node_id: str,
    file_id: str,
    package_path: str | os.PathLike[str],
    max_package_bytes: int = MAX_PACKAGE_BYTES,
) -> UpdatePackageBundle:
    """Reproduce both reports and bind their selected source to local file bytes.

    The two JSON reports are never accepted as proof by themselves. A failed
    diagnostic stage does not erase the independent catalogue-to-file link.
    """
    diagnostics = compose_update_diagnostic_bundle(
        catalogue_bytes,
        metadata_bytes,
        revocation_bytes,
        conditions_bytes,
        node_id=node_id,
        catalogue_response_bytes=catalogue_response_bytes,
        revocation_input_bytes=revocation_input_bytes,
        conditions_input_bytes=conditions_input_bytes,
        context_input_bytes=context_input_bytes,
    ).as_dict()
    package = inspect_update_package_file(
        catalogue_response_bytes,
        node_id=node_id,
        file_id=file_id,
        package_path=package_path,
        max_package_bytes=max_package_bytes,
    ).as_dict()
    supplied_diagnostics = _parse(diagnostic_bundle_bytes, "diagnostic bundle")
    supplied_package = _parse(package_receipt_bytes, "package-file receipt")
    metadata = _parse(metadata_bytes, "metadata")

    diagnostic_report_matches = _same_json(supplied_diagnostics, diagnostics)
    package_report_matches = _same_json(supplied_package, package)
    source_digest = hashlib.sha256(catalogue_response_bytes).hexdigest()
    source_matches = (
        diagnostics["source_sha256"]["catalogue_response"]
        == package["catalogue_source_sha256"]
        == source_digest
    )
    catalogue_link = diagnostics["links"]["catalogue_metadata"]
    catalogue_metadata_linked = catalogue_link["linked"] is True
    node_matches = (
        diagnostics["selected_node_id"] == package["node_id"] == node_id
        and diagnostics["selected_node_sha256"] == package["selected_node_sha256"]
    )
    canonical_matches = False
    stages = metadata.get("stages")
    if type(stages) is list and stages and type(stages[0]) is dict:
        row = stages[0]
        canonical = row.get("canonical_utf8")
        if type(canonical) is str:
            try:
                digest = hashlib.sha256(canonical.encode("utf-8")).digest()
                canonical_matches = (
                    digest.hex() == package["canonical_node_sha256"]
                    and row.get("sha256_hex") == digest.hex()
                    and row.get("sha256_base64")
                    == base64.b64encode(digest).decode("ascii")
                )
            except UnicodeError:
                pass

    # inspect_update_package_file reselects the unique file descriptor from the
    # bounded catalogue source, then hashes the exact safe-open file. A
    # type-exact reproduction rechecks its descriptor and observed byte fields.
    bytes_match = package["bytes_match_catalogue_descriptor"]
    source_package_linked = package_report_matches and bytes_match
    source_package_reason = (
        None if source_package_linked else
        "package-file receipt does not reproduce from the selected source and local file"
        if not package_report_matches else
        "local package bytes do not match the untrusted catalogue descriptor"
    )
    diagnostic_package_linked = all((
        source_package_linked,
        diagnostic_report_matches,
        source_matches,
        catalogue_metadata_linked,
        node_matches,
        canonical_matches,
    ))
    diagnostic_package_reason = (
        None if diagnostic_package_linked else
        source_package_reason
        if not source_package_linked else
        "diagnostic bundle does not reproduce from exact reports and sources"
        if not diagnostic_report_matches else
        "catalogue source digest differs between diagnostic and package receipts"
        if not source_matches else
        "diagnostic catalogue-to-metadata provenance is not linked"
        if not catalogue_metadata_linked else
        "selected node identity or normalized digest differs between receipts"
        if not node_matches else
        "metadata canonical node digest differs from the selected package source"
        if not canonical_matches else None
    )
    document = {
        "format": "cbus-toolkit-update-package-bundle-v1",
        "scope": "Offline exact-source link for one supplied package path; no update trust or install decision",
        "selected_node_id": node_id,
        "selected_file_id": file_id,
        "catalogue_source_sha256": source_digest,
        "selected_node_sha256": package["selected_node_sha256"],
        "canonical_node_sha256": package["canonical_node_sha256"],
        "diagnostic_bundle_report_sha256": hashlib.sha256(diagnostic_bundle_bytes).hexdigest(),
        "package_file_receipt_sha256": hashlib.sha256(package_receipt_bytes).hexdigest(),
        "declared_package_size": package["declared_size"],
        "declared_package_sha1": package["declared_sha1"],
        "observed_package_size": package["observed_size"],
        "observed_package_sha256": package["observed_sha256"],
        "links": {
            "source_package": {
                "linked": source_package_linked,
                "reason": source_package_reason,
                "package_receipt_reproduced": package_report_matches,
                "file_descriptor_reselected": True,
                "bytes_match_catalogue_descriptor": bytes_match,
            },
            "diagnostic_package": {
                "linked": diagnostic_package_linked,
                "reason": diagnostic_package_reason,
                "diagnostic_report_reproduced": diagnostic_report_matches,
                "catalogue_source_matches": source_matches,
                "catalogue_metadata_provenance_linked": catalogue_metadata_linked,
                "selected_node_matches": node_matches,
                "canonical_node_matches": canonical_matches,
            },
        },
        "diagnostics_complete": diagnostics["diagnostics_complete"],
        "joined_diagnostics_complete": diagnostic_package_linked and diagnostics["diagnostics_complete"],
        "metadata_signature_verified": False,
        "publisher_trust_evaluated": False,
        "certificate_chain_evaluated": False,
        "complete_revocation_status_evaluated": False,
        "package_applicability_evaluated": False,
        "version_comparison_performed": False,
        "updates_available": None,
        "downloaded": False,
        "installed": False,
        "install_permitted": False,
        "updater_network_request_initiated": False,
        "registry_accessed": False,
        "certificate_store_accessed": False,
    }
    return UpdatePackageBundle(json.dumps(document, ensure_ascii=True, separators=(",", ":")))
