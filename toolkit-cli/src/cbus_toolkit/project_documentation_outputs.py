"""Additional source-pinned output documentor profiles; no editor admission.

These profiles describe the original report's populated channel objects only.
They do not expand din-output-settings or imply programming/write support.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
import re

from .din_output_settings import PROFILES
from .toolkit_database_csv_registry import registrations_for


@dataclass(frozen=True)
class OutputProfile:
    indices: tuple[int, ...]


# Exact TDinRailOutputCGateAgent registration and TCBusDimmerUnit ancestry.
# The basic loader maps both channel groups and association flags by channel
# index; its four logic group slots are GroupAddress[12..15].
DIRECT_CHANNELS = MappingProxyType({
    "ANODN4": 4, "DIMDS8": 8, "DIMPR1": 1, "DIMPR2": 2,
    "DIMPR4": 4, "RELDB1": 1, "RELDC4": 4,
})
DIRECT_PROFILES = MappingProxyType({
    kind: OutputProfile(tuple(range(count))) for kind, count in DIRECT_CHANNELS.items()
})
NCC_TYPES = frozenset({"DIMDH4", "RELDN4A", "RELDN8A", "RELDN16A",
                       "DIMDD4", "DIMDD4F", "DIMDD8", "DIMDD8F"})


def _registration(unit):
    firmware = getattr(unit, "firmware", "")
    # An absent/malformed stored identity cannot select an exact native class.
    if not isinstance(firmware, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", firmware):
        return None
    if any(len(part) > 10 or int(part) > 2147483647 for part in firmware.split(".")):
        return None
    rows = registrations_for(unit.unit_type, firmware)
    return rows[0] if rows else None


def output_profile(unit):
    """Return a report profile only when its channel PP projection is known."""
    kind = unit.unit_type.upper()
    if kind in PROFILES:
        return PROFILES[kind]
    row = _registration(unit)
    if kind in DIRECT_PROFILES and row is not None and row[3:5] == (
            "T" + kind, "TDinRailOutputCGateAgent"):
        return DIRECT_PROFILES[kind]
    from .project_documentation_special_outputs import special_output_profile
    return special_output_profile(unit)


def output_base_only(unit) -> bool:
    """Native TOutputDocumentor exits after base for a non-dimmer NCC unit.

    This is a DocumentHTML type check, not an absence of output programming or
    group usage. Earlier DIMDD firmware has a different native class and is not
    admitted here.
    """
    row = _registration(unit)
    return unit.unit_type.upper() in NCC_TYPES and row is not None and row[3:5] == (
        "TNCCOutputUnit", "TNCCOutputCGateAgent")
