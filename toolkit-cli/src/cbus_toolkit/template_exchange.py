"""Template exchange guard spec (issue #11 box 5, bead cbus-ws3).

Spec-first offline scaffold only. Pure import/export request planner
where profile compatibility is a caller-supplied fact, never an
embedded vendor claim. No file I/O, no bus calls, no endpoints, no
credentials, no vendor payloads invented or read.

Honesty boundary: this module validates request shape and identity
preservation only. Vendor template byte-compatibility, cross-type
conversion semantics, and on-device transfer effects require
per-profile acceptance and remain open; every behavioral slot starts
``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"
DIRECTIONS = ("import", "export")


@dataclass(frozen=True)
class ExchangePlan:
    direction: str
    profile: str
    steps: tuple[str, ...]
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IdentityCheck:
    ok: bool
    note: str
    behavioral_comparison: str = UNASSESSED


def _check_profile(profile: Any, supported: Any) -> str:
    if not isinstance(profile, str) or not profile:
        raise ValueError("profile must be a non-empty str")
    if not isinstance(supported, (set, frozenset, list, tuple)):
        raise TypeError("supported_profiles must be a collection")
    if profile not in set(supported):
        raise ValueError(f"unsupported profile: {profile!r}")
    return profile


def _check_identity(identity: Any, label: str) -> dict[str, Any]:
    if not isinstance(identity, dict):
        raise TypeError(f"{label} identity must be dict")
    for key in ("serial", "address"):
        if key not in identity:
            raise ValueError(f"{label} identity missing {key!r}")
    serial, address = identity["serial"], identity["address"]
    if not isinstance(serial, str) or not serial:
        raise ValueError(f"{label} serial must be a non-empty str")
    if isinstance(address, bool) or not isinstance(address, int) or address < 0:
        raise ValueError(f"{label} address must be int >= 0")
    return copy.deepcopy(identity)


def plan_exchange(
    direction: str,
    profile: str,
    supported_profiles: Any,
    identity: Any,
    attrs: Any,
    extra: dict[str, Any] | None = None,
) -> ExchangePlan:
    """Plan a template import/export request (no side effects).

    Steps: ``validate_identity`` → ``check_profile`` → direction step
    (``read_template`` for export, ``stage_template`` for import) →
    ``verify_identity_preserved``. ``attrs`` is caller-opaque (must be
    dict); it echoes by deep copy inside ``extra``-merged echo as
    ``{"attrs": attrs}`` only when provided via ``extra`` — attrs
    themselves are NOT stored (exchange payload stays with the caller).
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction: {direction!r}")
    prof = _check_profile(profile, supported_profiles)
    ident = _check_identity(identity, "source")
    if not isinstance(attrs, dict):
        raise TypeError("attrs must be dict")
    middle = "read_template" if direction == "export" else "stage_template"
    echo = copy.deepcopy(dict(extra) if extra is not None else {})
    echo["identity"] = ident
    return ExchangePlan(
        direction=direction,
        profile=prof,
        steps=(
            "validate_identity",
            "check_profile",
            middle,
            "verify_identity_preserved",
        ),
        echo=echo,
    )


def check_identity_preservation(
    source: Any, target: Any, remap_reason: Any = ""
) -> IdentityCheck:
    """Compare source/target identities for an exchange.

    Equal ``(serial, address)`` → ok/preserved. Differing without a
    non-empty ``remap_reason`` str → not ok with conflict note.
    Differing with reason → ok with remap note (caller owns the claim).
    """
    src = _check_identity(source, "source")
    tgt = _check_identity(target, "target")
    if (src["serial"], src["address"]) == (tgt["serial"], tgt["address"]):
        return IdentityCheck(ok=True, note="identity preserved")
    if not isinstance(remap_reason, str) or not remap_reason:
        return IdentityCheck(
            ok=False, note="identity differs without remap reason"
        )
    return IdentityCheck(ok=True, note=f"remapped: {remap_reason}")
