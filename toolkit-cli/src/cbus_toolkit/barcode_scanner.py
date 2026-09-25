"""Barcode-scanner input spec (issue #11 box 11, bead cbus-9zz).

Spec-first offline scaffold only. Defines scanner-payload grammar and the
resulting project/unit selection-or-creation decision table as pure
functions with explicit caller-supplied inventory facts. No I/O, no
endpoints, no credentials, no vendor specifications invented or read.

Honesty boundary (per toolkit-surface.md P2): generic string handling is
NOT evidence of Toolkit scanner behavior. Every vendor-comparison slot
starts ``unassessed``; this module claims no Toolkit parity. Serial text
is opaque: it is not reformatted, not validated as a manufacturer
barcode, and not treated as proof of unit-type compatibility (see
docs/addressing.md). Vendor help topic 4590.htm is proprietary and
outside Git; no bytes from it are embedded here.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

PENDING = "pending"
UNASSESSED = "unassessed"

# Payload kinds. ``unknown`` covers anything that does not match the
# structural ``CBUS:<opaque>`` shape; callers must reject it.
KINDS = ("serial", "unknown")

# Decisions returned by decide_action. ``propose_create`` never creates
# anything: it only states what creation the caller *would* request.
DECISIONS = ("select_existing", "propose_create", "reject")


@dataclass(frozen=True)
class ParsedPayload:
    kind: str
    opaque: str
    vendor_comparison: str = UNASSESSED


@dataclass(frozen=True)
class ScannerDecision:
    decision: str
    reason: str
    echo: dict[str, Any] = field(default_factory=dict)
    vendor_comparison: str = UNASSESSED


def parse_payload(raw: Any) -> ParsedPayload:
    """Parse a raw scanner string into a structural payload.

    Rules (structural only, no vendor semantics):
    - input must be ``str``; anything else raises ``TypeError``.
    - surrounding ASCII whitespace is stripped; empty-after-strip raises
      ``ValueError``.
    - ``CBUS:<opaque>`` (case-sensitive prefix, non-empty opaque of
      at most 64 chars) -> ``serial`` with the opaque preserved
      verbatim (no case folding, no reformatting).
    - anything else -> ``unknown`` with the stripped text preserved.
    """
    if not isinstance(raw, str):
        raise TypeError(f"scanner payload must be str, got {type(raw).__name__}")
    text = raw.strip(" \t\r\n")
    if not text:
        raise ValueError("scanner payload is empty")
    if text.startswith("CBUS:"):
        opaque = text[5:]
        if opaque and len(opaque) <= 64:
            return ParsedPayload(kind="serial", opaque=opaque)
    return ParsedPayload(kind="unknown", opaque=text)


def decide_action(
    parsed: ParsedPayload,
    inventory_match: str,
    extra: dict[str, Any] | None = None,
) -> ScannerDecision:
    """Map a parsed payload + caller-supplied inventory fact to a decision.

    ``inventory_match`` is an explicit caller fact (no lookup here):
    ``"found"`` (project already has this unit), ``"absent"`` (no
    match), or ``"ambiguous"`` (multiple matches). Anything else raises
    ``ValueError``. Decision table:
    - unknown kind -> ``reject`` (any inventory fact).
    - serial + found -> ``select_existing``.
    - serial + absent -> ``propose_create`` (no side effects).
    - serial + ambiguous -> ``reject`` (caller must resolve duplicates).
    ``extra`` is echoed back by deep copy (value preservation, no alias).
    """
    if not isinstance(parsed, ParsedPayload):
        raise TypeError("parsed must be ParsedPayload")
    if inventory_match not in ("found", "absent", "ambiguous"):
        raise ValueError(f"unknown inventory_match: {inventory_match!r}")
    echo = copy.deepcopy(dict(extra) if extra is not None else {})
    if parsed.kind == "unknown":
        return ScannerDecision(
            decision="reject",
            reason="unrecognized scanner payload shape",
            echo=echo,
        )
    if parsed.kind == "serial":
        if inventory_match == "found":
            return ScannerDecision(
                decision="select_existing",
                reason="payload matches exactly one project unit",
                echo=echo,
            )
        if inventory_match == "absent":
            return ScannerDecision(
                decision="propose_create",
                reason="no project unit matches; creation proposed, not performed",
                echo=echo,
            )
        return ScannerDecision(
            decision="reject",
            reason="ambiguous inventory match; resolve duplicates first",
            echo=echo,
        )
    raise ValueError(f"unknown payload kind: {parsed.kind!r}")
