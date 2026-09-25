"""Label-transfer planner spec (issue #11 P-D, bead cbus-8w7).

Spec-first offline scaffold only. Pure slot-allocation planner mapping
source labels onto target slots: explicit slot requests honored
first-wins, the rest auto-allocated to the lowest free slots, overflow
and collisions escalated. No device writes, no bus calls, no endpoints,
no credentials, no vendor data invented or read.

Honesty boundary: allocation arithmetic is structural. On-device label
storage, encoding, language variants, and physical display effects
require device acceptance and remain open; every behavioral slot starts
``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class TransferPlan:
    assignments: tuple[tuple[str, int], ...]
    escalated: tuple[str, ...]
    capacity: int
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def plan_transfer(
    labels: Any,
    capacity: int,
    extra: dict[str, Any] | None = None,
) -> TransferPlan:
    """Plan label-to-slot assignment (no side effects).

    ``labels`` is a sequence of ``{"text": str}`` or ``{"text": str,
    "slot": int}`` dicts. Texts must be non-empty strs (opaque, never
    reformatted). Requested slots must be ints in ``0..capacity``;
    first request wins, later contests escalate. Unrequested labels
    fill the lowest free slots in input order; labels without a free
    slot escalate. ``capacity`` must be int >= 1. More labels than
    capacity escalates the excess (never silently drops: escalated
    lists every unassigned text in input order).
    """
    if isinstance(labels, (str, bytes)) or not hasattr(labels, "__iter__"):
        raise TypeError("labels must be a sequence of dicts")
    if isinstance(capacity, bool) or not isinstance(capacity, int):
        raise TypeError("capacity must be int")
    if capacity < 1:
        raise ValueError("capacity must be >= 1")
    texts: list[str] = []
    requested: dict[int, str] = {}
    contests: list[str] = []
    auto: list[str] = []
    for pos, item in enumerate(labels):
        if not isinstance(item, dict):
            raise TypeError(f"label {pos} must be dict")
        try:
            text = item["text"]
        except KeyError as exc:
            raise ValueError(f"label {pos} missing {exc}") from exc
        if not isinstance(text, str) or not text:
            raise ValueError(f"label {pos} text must be a non-empty str")
        slot = item.get("slot", None)
        if slot is None:
            auto.append(text)
            continue
        if isinstance(slot, bool) or not isinstance(slot, int):
            raise ValueError(f"label {pos} slot must be int")
        if not 0 <= slot < capacity:
            raise ValueError(f"label {pos} slot out of range")
        if slot in requested:
            contests.append(text)
        else:
            requested[slot] = text
        texts.append(text)
    used = set(requested)
    assignments: list[tuple[str, int]] = sorted(requested.items(),
                                               key=lambda kv: kv[0])
    assignments = [(text, slot) for slot, text in assignments]
    escalated: list[str] = list(contests)
    free = [s for s in range(capacity) if s not in used]
    for text in auto:
        if free:
            assignments.append((text, free.pop(0)))
        else:
            escalated.append(text)
    assignments.sort(key=lambda kv: kv[1])
    return TransferPlan(
        assignments=tuple(assignments),
        escalated=tuple(escalated),
        capacity=capacity,
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )
