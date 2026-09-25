"""Form save-order + preservation spec (issue #11 P-C, bead cbus-26c).

Spec-first offline scaffold only. Pure save-ordering planner over a
caller-supplied field-dependency graph (deterministic Kahn's algorithm,
cycle → ValueError) plus an unrelated-field preservation checker.
No forms, no devices, no endpoints, no credentials, no vendor data.

Honesty boundary: ordering and preservation are structural. Binding
semantics, event ordering effects, and on-device save behavior require
device acceptance and remain open; every behavioral slot starts
``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class SaveOrder:
    order: tuple[str, ...]
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreservationCheck:
    ok: bool
    violations: tuple[str, ...]
    behavioral_comparison: str = UNASSESSED


def plan_save_order(
    fields: Any,
    dependencies: Any,
    extra: dict[str, Any] | None = None,
) -> SaveOrder:
    """Order fields so dependencies save first (deterministic).

    ``fields``: non-empty sequence of non-empty strs (duplicates
    rejected). ``dependencies``: mapping field → sequence of fields it
    depends on (must name known fields; self-dependency and cycles
    raise ``ValueError``). Ties broken alphabetically for determinism.
    """
    if isinstance(fields, (str, bytes)) or not hasattr(fields, "__iter__"):
        raise TypeError("fields must be a sequence of strs")
    names = list(fields)
    if not names or any(not isinstance(n, str) or not n for n in names):
        raise ValueError("fields must be non-empty strs")
    if len(set(names)) != len(names):
        raise ValueError("fields contain duplicates")
    if not isinstance(dependencies, dict):
        raise TypeError("dependencies must be dict")
    deps: dict[str, set[str]] = {n: set() for n in names}
    for key, val in dependencies.items():
        if key not in deps:
            raise ValueError(f"dependency on unknown field: {key!r}")
        if isinstance(val, (str, bytes)) or not hasattr(val, "__iter__"):
            raise TypeError(f"dependencies[{key!r}] must be a sequence")
        for d in val:
            if d not in deps:
                raise ValueError(f"dependency on unknown field: {d!r}")
            if d == key:
                raise ValueError(f"field depends on itself: {key!r}")
            deps[key].add(d)
    order: list[str] = []
    done: set[str] = set()
    remaining = dict(deps)
    while remaining:
        ready = sorted(n for n, ds in remaining.items() if ds <= done)
        if not ready:
            cycle = sorted(remaining)
            raise ValueError(f"dependency cycle: {cycle}")
        for n in ready:
            order.append(n)
            done.add(n)
            del remaining[n]
    return SaveOrder(
        order=tuple(order),
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )


def check_preservation(before: Any, after: Any, touched: Any) -> PreservationCheck:
    """Verify untouched fields are byte-identical after a save.

    ``before``/``after``: dicts; ``touched``: collection of field names
    the save was allowed to change. New keys in ``after`` count as
    violations unless listed in ``touched``. Removed keys always
    violate. Returns ok + violation strings (never raises for content).
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise TypeError("before/after must be dicts")
    if isinstance(touched, (str, bytes)) or not hasattr(touched, "__iter__"):
        raise TypeError("touched must be a collection of strs")
    allowed = set(touched)
    violations: list[str] = []
    for key, val in before.items():
        if key in allowed:
            continue
        if key not in after:
            violations.append(f"removed: {key!r}")
        elif after[key] != val:
            violations.append(f"changed: {key!r}")
    for key in after:
        if key not in before and key not in allowed:
            violations.append(f"added: {key!r}")
    return PreservationCheck(ok=not violations, violations=tuple(violations))
