"""Duplicate-serial resolution planner (issue #11 box 2, bead cbus-61h).

Spec-first offline scaffold only. Pure decision logic over
caller-supplied duplicate observations; no bus scans, no writes, no
endpoints, no credentials.

Honesty boundary: the plan states which location to keep and which
spare addresses to relocate the rest to. It performs no moves and
establishes no on-device behavior; physical displacement, occupied
destinations, and bridge-coupled moves remain open and every physical
slot starts ``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class Resolution:
    serial: str
    keep: int
    relocations: tuple[tuple[int, int], ...]
    escalated: tuple[int, ...]
    physical_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def _check_group(item: Any, pos: int) -> tuple[str, list[int]]:
    if not isinstance(item, dict):
        raise TypeError(f"group {pos} must be dict")
    try:
        serial, locations = item["serial"], item["locations"]
    except KeyError as exc:
        raise ValueError(f"group {pos} missing {exc}") from exc
    if not isinstance(serial, str) or not serial:
        raise ValueError(f"group {pos} serial must be a non-empty str")
    if (
        not isinstance(locations, (list, tuple))
        or not locations
        or any(
            isinstance(v, bool) or not isinstance(v, int) or v < 0
            for v in locations
        )
    ):
        raise ValueError(f"group {pos} locations must be non-empty int list")
    if len(set(locations)) != len(locations):
        raise ValueError(f"group {pos} locations contain repeats")
    return serial, list(locations)


def resolve_duplicates(
    groups: Any,
    spare_addresses: Any,
    extra: dict[str, Any] | None = None,
) -> tuple[Resolution, ...]:
    """Plan duplicate resolution deterministically.

    ``groups``: sequence of ``{"serial": str, "locations": [int]}``
    caller-observed facts. ``spare_addresses``: sequence of empty
    destination addresses (caller-verified empty; NOT checked here).
    Per multi-location group: keep the lowest location, relocate the
    rest (ascending) to spares in order; locations without a spare go
    to ``escalated``. Single-location groups resolve to keep with no
    relocations. Output sorted by serial. ``extra`` echoes by deep copy.
    """
    if isinstance(groups, (str, bytes)) or not hasattr(groups, "__iter__"):
        raise TypeError("groups must be a sequence of dicts")
    if isinstance(spare_addresses, (str, bytes)) or not hasattr(
        spare_addresses, "__iter__"
    ):
        raise TypeError("spare_addresses must be a sequence of ints")
    spares: list[int] = []
    for pos, addr in enumerate(spare_addresses):
        if isinstance(addr, bool) or not isinstance(addr, int) or addr < 0:
            raise ValueError(f"spare {pos} must be int >= 0")
        if addr in spares:
            raise ValueError(f"spare {pos} repeats address {addr}")
        spares.append(addr)
    echo = copy.deepcopy(dict(extra) if extra is not None else {})
    spare_iter = iter(spares)
    spare_left = len(spares)
    out: list[Resolution] = []
    parsed = sorted(
        (_check_group(g, pos) for pos, g in enumerate(groups)),
        key=lambda t: t[0],
    )
    for serial, locations in parsed:
        locs = sorted(locations)
        keep = locs[0]
        relocations: list[tuple[int, int]] = []
        escalated: list[int] = []
        for loc in locs[1:]:
            if spare_left > 0:
                relocations.append((loc, next(spare_iter)))
                spare_left -= 1
            else:
                escalated.append(loc)
        out.append(
            Resolution(
                serial=serial,
                keep=keep,
                relocations=tuple(relocations),
                escalated=tuple(escalated),
                echo=echo,
            )
        )
    return tuple(out)
