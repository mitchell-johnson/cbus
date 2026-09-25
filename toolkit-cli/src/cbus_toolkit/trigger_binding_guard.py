"""Trigger-binding guard spec (issue #11 scenes/triggers, bead cbus-0up).

Spec-first offline scaffold only. Pure trigger→action binding table
validator over caller-supplied group sets; no events fired, no bus
calls, no endpoints, no credentials, no vendor data invented or read.

Honesty boundary: table shape and group membership are structural.
Trigger firing effects, learning, and persistent scene triggers
require device acceptance and remain open; every behavioral slot
starts ``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class BindingPlan:
    bindings: tuple[tuple[int, str, int], ...]
    conflicts: tuple[str, ...]
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def validate_bindings(
    entries: Any,
    valid_groups: Any,
    extra: dict[str, Any] | None = None,
) -> BindingPlan:
    """Validate (trigger_group, action, target_group) bindings.

    ``valid_groups``: caller-supplied collection of legal group ints.
    Actions are opaque non-empty strs (no app semantics embedded).
    Duplicate trigger groups conflict first-wins. Bad shapes, unknown
    groups, and empty actions raise ``TypeError``/``ValueError``.
    ``extra`` echoes by deep copy.
    """
    if isinstance(entries, (str, bytes)) or not hasattr(entries, "__iter__"):
        raise TypeError("entries must be a sequence of tuples")
    if isinstance(valid_groups, (str, bytes)) or not hasattr(
        valid_groups, "__iter__"
    ):
        raise TypeError("valid_groups must be a collection of ints")
    allowed: set[int] = set()
    for pos, g in enumerate(valid_groups):
        if isinstance(g, bool) or not isinstance(g, int):
            raise ValueError(f"valid_groups[{pos}] must be int")
        allowed.add(g)
    seen: dict[int, tuple[str, int]] = {}
    conflicts: list[str] = []
    for pos, item in enumerate(entries):
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise ValueError(f"entry {pos} must be (trigger, action, target)")
        trig, action, target = item
        for label, val in (("trigger", trig), ("target", target)):
            if isinstance(val, bool) or not isinstance(val, int):
                raise ValueError(f"entry {pos} {label} must be int")
            if val not in allowed:
                raise ValueError(f"entry {pos} {label} not in valid groups")
        if not isinstance(action, str) or not action:
            raise ValueError(f"entry {pos} action must be a non-empty str")
        if trig in seen:
            conflicts.append(f"duplicate trigger group {trig} at entry {pos}")
            continue
        seen[trig] = (action, target)
    bindings = tuple(
        (trig, action, target)
        for trig, (action, target) in sorted(seen.items())
    )
    return BindingPlan(
        bindings=bindings,
        conflicts=tuple(conflicts),
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )
