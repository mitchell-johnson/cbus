"""One source-bound, caller-supplied SESU rollout comparison.

The original helper also reads and sometimes writes HKCU Registry32. This
module deliberately receives an already-stored cohort as data and does not
claim that it came from the current machine or that an update is applicable.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .toolkit_update_metadata import (
    MAX_NODE_BYTES,
    _canonical,
    _json,
    select_node,
    validate_node_id,
)


_COHORT = re.compile(r"[0-9]{1,2}\Z", re.ASCII)


def parse_supplied_stored_cohort(stored_cohort: str) -> int:
    """Admit the same narrow already-stored decimal string in both reports."""
    if (type(stored_cohort) is not str or not _COHORT.fullmatch(stored_cohort)
            or int(stored_cohort) > 99):
        raise ValueError("stored_cohort must be one or two ASCII decimal digits from 0 to 99")
    return int(stored_cohort)


@dataclass(frozen=True)
class RolloutCohortDecision:
    catalogue_source_sha256: str
    selected_node_sha256: str
    canonical_node_sha256: str | None
    node_id: str
    visibility_in_percent: int | None
    supplied_stored_cohort: int
    status: str
    reason: str | None

    @property
    def gate_under_supplied_cohort(self) -> bool | None:
        return {"passed": True, "failed": False, "unsupported": None}[self.status]

    def as_dict(self) -> dict:
        return {
            "format": "cbus-toolkit-update-rollout-cohort-v1",
            "scope": "One original strict-greater-than rollout gate with caller-supplied stored cohort",
            "catalogue_source_sha256": self.catalogue_source_sha256,
            "selected_node_sha256": self.selected_node_sha256,
            "canonical_node_sha256": self.canonical_node_sha256,
            "node_id": self.node_id,
            "visibility_in_percent": self.visibility_in_percent,
            "supplied_stored_cohort": self.supplied_stored_cohort,
            "cohort_provenance": "caller-supplied; not observed from this host",
            "status": self.status,
            "reason": self.reason,
            "rollout_gate_under_supplied_cohort": self.gate_under_supplied_cohort,
            "metadata_signature_verified": False,
            "publisher_trust_evaluated": False,
            "certificate_chain_evaluated": False,
            "complete_revocation_status_evaluated": False,
            "full_machine_applicability_evaluated": False,
            "version_comparison_performed": False,
            "updates_available": None,
            "install_permitted": False,
            "network_request_initiated": False,
            "registry_accessed": False,
            "cohort_generated": False,
            "cohort_persisted": False,
            "downloaded": False,
            "installed": False,
        }


def inspect_rollout_cohort(
    catalogue_response: bytes, *, node_id: str, stored_cohort: str,
) -> RolloutCohortDecision:
    """Evaluate only a supplied, persisted 0..99 cohort against one node.

    Missing registry keys/entries, random generation, writes, and host facts are
    separate original branches and are not modeled by this pure function.
    """
    validate_node_id(node_id)
    cohort = parse_supplied_stored_cohort(stored_cohort)
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
    visibility = None

    def report(status: str, reason: str | None) -> RolloutCohortDecision:
        return RolloutCohortDecision(
            source_sha, selected_sha, canonical_sha, node_id, visibility,
            cohort, status, reason,
        )

    try:
        canonical_sha = hashlib.sha256(_canonical(node)).hexdigest()
    except ValueError:
        return report("unsupported", "selected node is outside the bounded typed metadata profile")
    data = node.get("data")
    if type(data) is not dict:
        return report("unsupported", "selected node has no complete package data")
    condition = data.get("clientConditionData")
    if (type(condition) is not dict or type(condition.get("conditions")) is not dict
            or condition["conditions"]):
        return report("unsupported", "only an empty original condition dictionary is admitted")
    visibility = data.get("visibilityInPercent")
    if type(visibility) is not int or not 0 <= visibility < 100:
        visibility = None
        return report("unsupported", "only explicit visibilityInPercent from 0 to 99 is admitted")
    passed = visibility > cohort
    return report("passed" if passed else "failed", None if passed else
                  "visibilityInPercent does not exceed the supplied stored cohort")
