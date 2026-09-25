"""Scene/macro action-sequence planner (issue #11 box 3, bead cbus-0up).

Spec-first offline scaffold only. Pure ordered action-list planner
with the documented retained SceneManager capacity bound (64 items;
see docs/implementation-status.md eDLT retained scenes). No device
writes, no triggers fired, no endpoints, no credentials.

Honesty boundary: shape and capacity conformance are structural.
Trigger timing, scene invocation effects, learning, and physical
button behavior require device acceptance and remain open; every
behavioral slot starts ``unassessed``. Partial-capacity outcomes
cannot be saved — over-capacity plans raise instead of truncating.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"

# Documented retained SceneManager capacity (ledger: edlt-retained-
# scene-editing). Profiles with other capacities stay open; callers may
# pass an explicit smaller capacity but never a larger one.
DOCUMENTED_CAPACITY = 64

ACTIONS = ("recall", "set_level", "ramp", "delay", "trigger")


@dataclass(frozen=True)
class SequenceStep:
    action: str
    target: str
    arg: int


@dataclass(frozen=True)
class SequencePlan:
    steps: tuple[SequenceStep, ...]
    capacity: int
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def _check_step(item: Any, pos: int) -> SequenceStep:
    if not isinstance(item, dict):
        raise TypeError(f"step {pos} must be dict")
    try:
        action, target = item["action"], item["target"]
    except KeyError as exc:
        raise ValueError(f"step {pos} missing {exc}") from exc
    if action not in ACTIONS:
        raise ValueError(f"step {pos} unknown action: {action!r}")
    if not isinstance(target, str) or not target:
        raise ValueError(f"step {pos} target must be a non-empty str")
    arg = item.get("arg", 0)
    if isinstance(arg, bool) or not isinstance(arg, int) or arg < 0:
        raise ValueError(f"step {pos} arg must be int >= 0")
    if action == "set_level" and not 0 <= arg <= 100:
        raise ValueError(f"step {pos} set_level arg 0-100: {arg!r}")
    return SequenceStep(action=action, target=target, arg=arg)


def plan_sequence(
    steps: Any,
    capacity: int = DOCUMENTED_CAPACITY,
    extra: dict[str, Any] | None = None,
) -> SequencePlan:
    """Plan an ordered scene/macro action sequence (no side effects).

    ``steps`` is a sequence of ``{"action", "target", "arg?"}`` dicts,
    kept in input order. ``capacity`` defaults to the documented 64;
    callers may pass a smaller bound, never larger (raises). More steps
    than capacity raises ``ValueError`` (partial outcomes unsavable).
    ``extra`` echoes by deep copy.
    """
    if isinstance(steps, (str, bytes)) or not hasattr(steps, "__iter__"):
        raise TypeError("steps must be a sequence of dicts")
    if (
        isinstance(capacity, bool)
        or not isinstance(capacity, int)
        or capacity < 1
    ):
        raise ValueError("capacity must be int >= 1")
    if capacity > DOCUMENTED_CAPACITY:
        raise ValueError(
            f"capacity {capacity} exceeds documented {DOCUMENTED_CAPACITY}"
        )
    planned = tuple(_check_step(s, pos) for pos, s in enumerate(steps))
    if len(planned) > capacity:
        raise ValueError(
            f"{len(planned)} steps exceed capacity {capacity}"
        )
    return SequencePlan(
        steps=planned,
        capacity=capacity,
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )
