"""Bounded SESU rollout helper with an explicitly owned registry provider.

The retained direct-helper probe redirected both registry names before
invocation. A separate source-bound derivation now identifies the original
fields, but this module still never selects that updater location. Its Windows
adapter is restricted to a CLI-owned scratch subtree in HKCU Registry32.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import secrets
from typing import Callable, Protocol

from .toolkit_update_rollout import inspect_rollout_cohort


_INT32_TEXT = re.compile(r"[ \t]*[+-]?[0-9]{1,10}[ \t]*\Z", re.ASCII)


@dataclass(frozen=True)
class CohortRegistryRead:
    state: str  # key_absent, entry_absent, or present
    kind: str | None = None  # REG_SZ or REG_DWORD in the admitted profile
    value: str | int | None = None


class CohortRegistry(Protocol):
    def read(self) -> CohortRegistryRead: ...
    def write_decimal(self, value: str) -> None: ...


def _stored_int32(read: CohortRegistryRead) -> tuple[int | None, str]:
    if read.kind == "REG_DWORD" and type(read.value) is int:
        # A high-bit DWORD may ToString as -1 in .NET, entering the original
        # sentinel branch. That behavior is not covered by the 17-case probe.
        if not 0 <= read.value <= 0x7fffffff:
            return None, "unsupported"
        return read.value, "parsed"
    if read.kind != "REG_SZ" or type(read.value) is not str:
        return None, "unsupported"
    if len(read.value) > 64 or "\0" in read.value or not read.value.isascii():
        return None, "unsupported"
    if not _INT32_TEXT.fullmatch(read.value):
        return None, "malformed"
    number = int(read.value)
    if not -0x80000000 <= number <= 0x7fffffff:
        return None, "malformed"
    return number, "parsed"


@dataclass(frozen=True)
class RegistryRolloutDecision:
    catalogue_source_sha256: str
    selected_node_sha256: str
    canonical_node_sha256: str | None
    node_id: str
    visibility_in_percent: int | None
    status: str
    reason: str | None
    read_attempted: bool
    registry_read: CohortRegistryRead | None
    parse_status: str | None
    effective_cohort: int | None
    sample_attempted: bool
    cohort_generated: bool
    write_attempted: bool
    cohort_persisted: bool | None
    write_outcome_uncertain: bool
    registry_error_type: str | None

    @property
    def gate(self) -> bool | None:
        return {"passed": True, "failed": False, "unsupported": None}[self.status]

    def as_dict(self) -> dict:
        read = self.registry_read
        value = None if read is None else read.value
        state = None if read is None else read.state
        kind = None if read is None else read.kind
        if type(state) is not str or len(state) > 32 or not state.isascii():
            state = None
        if kind is not None and (type(kind) is not str or len(kind) > 32 or not kind.isascii()):
            kind = None
        if ((type(value) is str and (len(value) > 64 or not value.isascii()
                                     or "\0" in value))
                or type(value) not in (str, int, type(None))):
            value = None  # Unsupported provider values are never exported.
        return {
            "format": "cbus-toolkit-update-rollout-owned-registry-v1",
            "scope": "One original rollout-helper branch under a caller-selected CLI-owned HKCU Registry32 scratch key",
            "catalogue_source_sha256": self.catalogue_source_sha256,
            "selected_node_sha256": self.selected_node_sha256,
            "canonical_node_sha256": self.canonical_node_sha256,
            "node_id": self.node_id,
            "visibility_in_percent": self.visibility_in_percent,
            "status": self.status,
            "reason": self.reason,
            "registry_view": "HKCU Registry32 owned scratch subtree; not the original updater key",
            "registry_provider_identity_verified": False,
            "registry_backend_provenance": "caller-injected provider; the CLI selects its guarded Windows adapter",
            "registry_accessed": self.read_attempted,
            "registry_read": (None if read is None else {
                "state": state, "kind": kind, "value": value,
            }),
            "parse_status": self.parse_status,
            "effective_cohort": self.effective_cohort,
            "sample_attempted": self.sample_attempted,
            "cohort_generated": self.cohort_generated,
            "write_attempted": self.write_attempted,
            "cohort_persisted": self.cohort_persisted,
            "write_outcome_uncertain": self.write_outcome_uncertain,
            "cohort_persistence_basis": (
                "write may have committed before provider error; no retry"
                if self.write_outcome_uncertain else
                "provider write returned; no independent readback or durable flush"
                if self.cohort_persisted else "no write attempted"
            ),
            "durable_persistence_verified": False,
            "registry_error_type": self.registry_error_type,
            "rollout_gate_under_owned_registry": self.gate,
            "original_updater_registry_identity_verified": False,
            "metadata_signature_verified": False,
            "publisher_trust_evaluated": False,
            "certificate_chain_evaluated": False,
            "complete_revocation_status_evaluated": False,
            "full_machine_applicability_evaluated": False,
            "version_comparison_performed": False,
            "updates_available": None,
            "install_permitted": False,
            "network_request_initiated": False,
            "downloaded": False,
            "installed": False,
        }


def inspect_rollout_owned_registry(
    catalogue_response: bytes, *, node_id: str, registry: CohortRegistry,
    sample: Callable[[], int] | None = None,
) -> RegistryRolloutDecision:
    """Inspect one source-bound node, then read/sample/persist an owned cohort.

    A present malformed Int32 returns false like the captured helper. Provider
    and persistence failures are indeterminate and fail closed. The caller
    supplies the provider; no original updater registry location is inferred.
    """
    profile = inspect_rollout_cohort(
        catalogue_response, node_id=node_id, stored_cohort="0")
    read = None
    read_attempted = False
    parse_status = None
    cohort = None
    sample_attempted = generated = write_attempted = persisted = uncertain = False
    error_type = None

    def report(status: str, reason: str | None) -> RegistryRolloutDecision:
        return RegistryRolloutDecision(
            profile.catalogue_source_sha256, profile.selected_node_sha256,
            profile.canonical_node_sha256, node_id, profile.visibility_in_percent,
            status, reason, read_attempted, read, parse_status, cohort, sample_attempted,
            generated, write_attempted, persisted, uncertain, error_type,
        )

    if profile.status == "unsupported":
        return report("unsupported", profile.reason)
    read_attempted = True
    try:
        read = registry.read()
    except Exception as error:
        error_type = type(error).__name__
        return report("unsupported", "owned registry read failed")
    if type(read) is not CohortRegistryRead:
        read = None
        return report("unsupported", "registry provider returned an invalid typed read")
    if read.state == "key_absent" and read.kind is None and read.value is None:
        return report("failed", "original helper returns false when its key is absent")
    if read.state == "entry_absent" and read.kind is None and read.value is None:
        seed = True
    elif read.state == "present":
        if read.kind == "REG_SZ" and read.value == "-1":
            seed = True
            parse_status = "literal_minus_one_sentinel"
        else:
            seed = False
            cohort, parse_status = _stored_int32(read)
            if parse_status == "malformed":
                return report("failed", "stored value is not a parseable Int32")
            if parse_status == "unsupported":
                return report("unsupported", "stored registry type or text is outside the admitted profile")
    else:
        return report("unsupported", "registry provider returned an invalid typed read")
    if seed:
        sample_attempted = True
        try:
            sampled = (secrets.randbelow(100) if sample is None else sample())
        except Exception as error:
            error_type = type(error).__name__
            return report("unsupported", "cohort sampling failed")
        if type(sampled) is not int or not 0 <= sampled <= 99:
            return report("unsupported", "cohort sampler returned an invalid 0–99 integer")
        cohort = sampled
        generated = True
        write_attempted = True
        try:
            registry.write_decimal(str(cohort))
        except Exception as error:
            error_type = type(error).__name__
            persisted = None
            uncertain = True
            return report("unsupported", "sampled cohort could not be persisted")
        persisted = True
    passed = profile.visibility_in_percent > cohort
    return report("passed" if passed else "failed", None if passed else
                  "visibilityInPercent did not exceed the effective cohort")
