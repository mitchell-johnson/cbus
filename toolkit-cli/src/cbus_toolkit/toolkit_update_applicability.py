"""Offline, explicitly scoped SESU 3.0.7 applicability preflight.

The original collection coordinator admits a node only after separate
metadata validation. This module evaluates a narrower, supplied-context
date/file/media branch; it never treats that branch as publisher trust or
current machine applicability.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from urllib.parse import urlsplit

from .toolkit_update_metadata import (
    MAX_NODE_BYTES,
    _canonical,
    _json,
    select_node,
    validate_context,
    validate_node_id,
)


PLATFORMS = ("windows_x86_32", "windows_x86_64")


@dataclass(frozen=True)
class UpdateApplicabilityPreflight:
    catalogue_source_sha256: str
    selected_node_sha256: str
    canonical_node_sha256: str | None
    node_id: str
    platform: str
    at_utc: str
    status: str
    reason: str | None
    selected_file_id: str | None
    date_window_passed: bool | None
    media_passed: bool | None
    selected_uri_present: bool | None
    empty_conditions: bool | None
    rollout_bypassed_visibility_100: bool | None

    @property
    def applicable_under_supplied_context(self) -> bool | None:
        return {"passed": True, "failed": False, "unsupported": None}[self.status]

    def as_dict(self) -> dict:
        return {
            "format": "cbus-toolkit-update-applicability-preflight-v1",
            "scope": "Offline empty-condition/100-percent branch under an explicit UTC/platform context",
            "catalogue_source_sha256": self.catalogue_source_sha256,
            "selected_node_sha256": self.selected_node_sha256,
            "canonical_node_sha256": self.canonical_node_sha256,
            "node_id": self.node_id,
            "platform": self.platform,
            "at_utc": self.at_utc,
            "status": self.status,
            "reason": self.reason,
            "selected_file_id": self.selected_file_id,
            "checks": {
                "date_window_passed": self.date_window_passed,
                "supported_media_passed": self.media_passed,
                "selected_uri_present": self.selected_uri_present,
                "empty_conditions": self.empty_conditions,
                "rollout_bypassed_visibility_100": self.rollout_bypassed_visibility_100,
            },
            "applicability_under_supplied_context": self.applicable_under_supplied_context,
            "metadata_signature_verified": False,
            "publisher_trust_evaluated": False,
            "certificate_chain_evaluated": False,
            "complete_revocation_status_evaluated": False,
            "package_applicability_evaluated": False,
            "version_comparison_performed": False,
            "updates_available": None,
            "install_permitted": False,
            "downloaded": False,
            "installed": False,
            "network_request_initiated": False,
            "registry_accessed": False,
            "certificate_store_accessed": False,
        }


def _https_uri_in_profile(value: str) -> bool:
    """Admit only an unambiguous URI subset; never fetch or print it."""
    if (not value or len(value) > 16384
            or any(ord(char) <= 32 or ord(char) >= 127 or char == "\\" for char in value)):
        return False
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment):
            return False
        _ = parsed.port  # Invalid port syntax raises ValueError.
        return True
    except ValueError:
        return False


def inspect_update_applicability(
    catalogue_response: bytes, *, node_id: str, platform: str, at_utc: str,
) -> UpdateApplicabilityPreflight:
    """Evaluate one original date/file/media path without host or trust reads.

    A result of ``passed`` is a fact under caller-supplied UTC/platform inputs,
    not proof that the original Windows client would offer this update now.
    """
    validate_node_id(node_id)
    if type(platform) is not str or platform not in PLATFORMS:
        raise ValueError("platform must be windows_x86_32 or windows_x86_64")
    at_ticks, normalized_at = validate_context(at_utc)
    response = _json(catalogue_response, limit=MAX_NODE_BYTES)
    if (type(response) is not dict or response.get("success") is not True
            or type(response.get("statusCode")) is not int
            or response["statusCode"] != 200):
        raise ValueError("catalogue response must report exact success and statusCode 200")
    selected = select_node(catalogue_response, node_id=node_id)
    node = _json(selected)
    source_sha = hashlib.sha256(catalogue_response).hexdigest()
    selected_sha = hashlib.sha256(selected).hexdigest()
    canonical_sha = None
    chosen = None
    date_pass = media_pass = uri_pass = None
    empty_conditions = rollout_bypassed = None

    def report(status: str, reason: str | None) -> UpdateApplicabilityPreflight:
        return UpdateApplicabilityPreflight(
            source_sha, selected_sha, canonical_sha, node_id, platform,
            normalized_at, status, reason, chosen, date_pass, media_pass,
            uri_pass, empty_conditions, rollout_bypassed,
        )

    try:
        canonical_sha = hashlib.sha256(_canonical(node)).hexdigest()
    except ValueError:
        return report("unsupported", "selected node is outside the bounded typed metadata profile")

    data, files, urls = node.get("data"), node.get("files"), node.get("urls")
    if type(data) is not dict or type(files) is not list or type(urls) is not dict:
        return report("unsupported", "node lacks complete package data, files or URL map")
    condition = data.get("clientConditionData")
    if (type(condition) is not dict or type(condition.get("conditions")) is not dict
            or condition["conditions"]):
        return report("unsupported", "only an empty original condition dictionary is admitted")
    empty_conditions = True
    if type(data.get("visibilityInPercent")) is not int or data["visibilityInPercent"] != 100:
        return report("unsupported", "only visibilityInPercent=100 bypasses stateful rollout here")
    rollout_bypassed = True
    try:
        start, _ = validate_context(data["startDate"])
        expiry, _ = validate_context(data["expireDate"])
    except (KeyError, ValueError, TypeError):
        return report("unsupported", "explicit UTC startDate and expireDate are required")
    date_pass = start <= at_ticks <= expiry

    if any(type(item) is not dict for item in files):
        return report("unsupported", "all file descriptors must be complete objects")
    ids = [item.get("id") for item in files]
    if any(type(item) is not str or not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("file IDs must be unique nonempty strings")
    for item in files:
        metadata = item.get("metadata")
        if type(metadata) is not dict:
            return report("unsupported", "all file metadata must be complete objects")
        architecture = metadata.get("architecture")
        if architecture is None:
            continue
        if type(architecture) is not str:
            return report("unsupported", "architecture must be text")
        if platform not in architecture or item["id"] not in urls:
            continue
        chosen = item["id"]
        media = metadata.get("mediatype")
        if media == "singleFileExecutable":
            media_pass = True
        elif media is None:
            media_pass = False  # Original selector defaults to MediaType.Unknown (6).
        else:
            return report("unsupported", "selected media type is outside the captured finite profile")
        selected_url = urls[chosen]
        if type(selected_url) is not dict:
            return report("unsupported", "selected URL-map entry must be an object")
        address = selected_url.get("url")
        if address is None or address == "":
            uri_pass = False
        elif type(address) is str and _https_uri_in_profile(address):
            uri_pass = True
        else:
            return report("unsupported", "selected URL is outside the unambiguous HTTPS profile")
        break  # Original selector never falls back after a matching URL key.
    if chosen is None:
        media_pass = False
        uri_pass = False
    accepted = date_pass and media_pass and uri_pass
    return report("passed" if accepted else "failed", None if accepted else
                  "one or more date, selected-file, media or URI gates did not pass")
