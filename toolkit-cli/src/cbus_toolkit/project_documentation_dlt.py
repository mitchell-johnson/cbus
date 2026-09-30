"""Bounded classic DLT documentor body from explicit offline PP snapshots.

TDLTDocumentor delegates to NeoPro before appending its dynamic-update label
mode. The complete inherited projection has the shared Neo restrictions; this
module never edits labels, programming data or a connected device.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .project_documentation_neo import NeoProfile, document_neo

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

DLT_TYPES = ("KEYBL5", "KEYML5", "KEYDL4")
DLT_FIRMWARE = "3.0.00"
DLT_PROFILE = NeoProfile(physical_key_count=8, is_pro=True, infrared_virtual_keys=False)


def dlt_profile(unit: Unit) -> NeoProfile:
    """Admission for the source-pinned complete PP model, not label editing."""
    if unit.unit_type.upper() not in DLT_TYPES or unit.firmware != DLT_FIRMWARE:
        raise ValueError("unrecovered DLT class/firmware (requires KEYBL5, KEYML5 or KEYDL4 3.0.00)")
    return DLT_PROFILE


def dlt_label_mode(unit: Unit) -> str:
    """The native load is BlockDynamicUpdates = not EnableDynamicLabels."""
    values = unit.array("EnableDynamicLabels")
    if values is None or len(values) != 1 or values[0] not in (0, 1):
        raise ValueError("EnableDynamicLabels (requires one explicit bit value)")
    return "Labels: Dynamic" if values[0] else "Labels: Static"


def document_dlt(out: _Writer, network: Network, unit: Unit) -> str:
    """Render NeoPro tables and the exact DLT suffix, preserving partial status."""
    from .project_documentation import document_base
    try:
        profile = dlt_profile(unit)
    except ValueError as exc:
        document_base(out, network, unit)
        out.mark(network, unit, f"DLT controls: {exc}")
        return "partial"
    status = document_neo(out, network, unit, profile=profile)
    try:
        mode = dlt_label_mode(unit)
    except ValueError as exc:
        out.mark(network, unit, f"DLT labels: {exc}")
        return "partial"
    # TStringList.Add appends this after the inherited body without an HTML br.
    out.add(mode)
    return status
