"""Wireless learn/join + gateway-mapping spec (issue #11 box 9, bead cbus-9zz).

Spec-first offline scaffold only. Pure planners/validators with explicit
caller-supplied facts; no radio I/O, no endpoints, no credentials, no
vendor specifications invented or read (vendor topics 693.htm/13994.htm
are proprietary and outside Git).

Honesty boundary (per toolkit-surface.md P2): this module claims no
Toolkit parity and no on-device behavior. Every physical-comparison slot
starts ``unassessed``. Join-mode outcomes, timing, and gateway transfer
effects require relevant-device acceptance and remain open.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"

JOIN_MODES = ("new_house", "join_existing")
PHASES = ("enter_learn", "join_devices", "assign_mapping", "exit_learn")


@dataclass(frozen=True)
class JoinPlan:
    mode: str
    steps: tuple[str, ...]
    physical_comparison: str = UNASSESSED


@dataclass(frozen=True)
class MappingResult:
    table: tuple[tuple[int, int], ...]
    conflicts: tuple[str, ...]
    physical_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def plan_join(mode: str, device_count: int) -> JoinPlan:
    """Return the ordered learn/join phase plan for a session.

    - ``mode`` must be ``new_house`` or ``join_existing``.
    - ``device_count`` must be a non-bool int >= 1 (number of wireless
      units to join; caller fact, not a scan result).
    Steps are the fixed ``PHASES`` order; ``join_devices`` repeats once
    per device in the returned step list as ``join_devices[i]``.
    """
    if mode not in JOIN_MODES:
        raise ValueError(f"unknown join mode: {mode!r}")
    if isinstance(device_count, bool) or not isinstance(device_count, int):
        raise TypeError("device_count must be int")
    if device_count < 1:
        raise ValueError("device_count must be >= 1")
    steps = ["enter_learn"]
    steps.extend(f"join_devices[{i}]" for i in range(device_count))
    steps.extend(["assign_mapping", "exit_learn"])
    return JoinPlan(mode=mode, steps=tuple(steps))


def _check_byte(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int")
    if not 0 <= value <= 255:
        raise ValueError(f"{name} out of range 0-255: {value!r}")
    return value


def validate_gateway_mapping(
    entries: Any, extra: dict[str, Any] | None = None
) -> MappingResult:
    """Validate a wireless-zone to wired-group mapping table.

    ``entries`` is a sequence of ``(zone, group)`` int pairs (0-255).
    Returns the normalized sorted table plus conflict strings for
    duplicate zones or duplicate groups (first occurrence wins in the
    table). Non-sequence input, bad shapes, or out-of-range values
    raise ``TypeError``/``ValueError``. ``extra`` echoes by deep copy.
    """
    if isinstance(entries, (str, bytes)) or not hasattr(entries, "__iter__"):
        raise TypeError("entries must be a sequence of (zone, group) pairs")
    seen_zone: dict[int, int] = {}
    seen_group: dict[int, int] = {}
    conflicts: list[str] = []
    for idx, item in enumerate(entries):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"entry {idx} must be a (zone, group) pair")
        zone = _check_byte(f"entry {idx} zone", item[0])
        group = _check_byte(f"entry {idx} group", item[1])
        if zone in seen_zone:
            conflicts.append(f"duplicate zone {zone} at entry {idx}")
            continue
        if group in seen_group:
            conflicts.append(f"duplicate group {group} at entry {idx}")
            continue
        seen_zone[zone] = group
        seen_group[group] = zone
    table = tuple(sorted(seen_zone.items()))
    return MappingResult(
        table=table,
        conflicts=tuple(conflicts),
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )
