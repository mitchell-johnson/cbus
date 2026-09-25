"""Relay/dimmer channel planning spec (issue #11 box 3, bead cbus-0up).

Spec-first offline scaffold only. Pure channel-table validators with
explicit caller-supplied facts; no bus I/O, no endpoints, no
credentials, no vendor specifications invented or read.

Honesty boundaries:
- Logic-engine code editing (programmable controller logic) is an
  external application boundary, not Toolkit parity
  (``LOGIC_ENGINE_BOUNDARY = "external"``). This module plans relay
  states and dimmer levels/ramps only.
- Profile-specific channel counts, timings, and on-device effects
  require per-profile device acceptance and remain open; every
  physical-comparison slot starts ``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"

# Logic-engine programming stays in external applications (e.g. PICED);
# it is a documented boundary, never claimed here.
LOGIC_ENGINE_BOUNDARY = "external"

CHANNEL_MODES = ("relay", "dimmer", "unused")
MAX_RAMP_SECONDS = 600


@dataclass(frozen=True)
class ChannelPlan:
    table: tuple[tuple[int, str, int, int], ...]
    conflicts: tuple[str, ...]
    physical_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def _check_index(value: Any, pos: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"entry {pos} index must be int")
    if value < 0:
        raise ValueError(f"entry {pos} index must be >= 0: {value!r}")
    return value


def _check_mode(value: Any, pos: int) -> str:
    if value not in CHANNEL_MODES:
        raise ValueError(f"entry {pos} unknown mode: {value!r}")
    return value


def _check_level(mode: str, value: Any, pos: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"entry {pos} level must be int")
    if mode == "relay":
        if value not in (0, 100):
            raise ValueError(
                f"entry {pos} relay level must be 0 or 100: {value!r}"
            )
    elif not 0 <= value <= 100:
        raise ValueError(f"entry {pos} dimmer level 0-100: {value!r}")
    return value


def _check_ramp(mode: str, value: Any, pos: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"entry {pos} ramp must be int seconds")
    if not 0 <= value <= MAX_RAMP_SECONDS:
        raise ValueError(f"entry {pos} ramp 0-{MAX_RAMP_SECONDS}: {value!r}")
    if mode == "relay" and value != 0:
        raise ValueError(f"entry {pos} relay ramp must be 0: {value!r}")
    return value


def validate_bank(
    entries: Any, extra: dict[str, Any] | None = None
) -> ChannelPlan:
    """Validate a relay/dimmer channel table.

    ``entries`` is a sequence of ``(index, mode, level, ramp_seconds)``
    tuples. Returns the normalized table sorted by index plus conflict
    strings for duplicate indexes (first wins) and ``unused`` channels
    carrying nonzero level/ramp (kept, flagged). Bad shapes, unknown
    modes, out-of-range levels/ramps, and relay-with-ramp raise
    ``TypeError``/``ValueError``. ``extra`` echoes by deep copy.
    """
    if isinstance(entries, (str, bytes)) or not hasattr(entries, "__iter__"):
        raise TypeError("entries must be a sequence of channel tuples")
    seen: dict[int, tuple[int, str, int, int]] = {}
    conflicts: list[str] = []
    for pos, item in enumerate(entries):
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            raise ValueError(f"entry {pos} must be (index, mode, level, ramp)")
        idx = _check_index(item[0], pos)
        mode = _check_mode(item[1], pos)
        level = _check_level(mode, item[2], pos)
        ramp = _check_ramp(mode, item[3], pos)
        if idx in seen:
            conflicts.append(f"duplicate channel {idx} at entry {pos}")
            continue
        if mode == "unused" and (level != 0 or ramp != 0):
            conflicts.append(f"unused channel {idx} carries settings")
        seen[idx] = (idx, mode, level, ramp)
    return ChannelPlan(
        table=tuple(sorted(seen.values())),
        conflicts=tuple(conflicts),
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )
