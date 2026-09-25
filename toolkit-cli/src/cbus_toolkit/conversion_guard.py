"""Unit-conversion guard spec (issue #11 box 5, bead cbus-ws3).

Spec-first offline scaffold only. Pure conversion-request planner
where the supported profile-pair table is a caller-supplied fact,
never an embedded vendor claim. No file I/O, no bus calls, no
endpoints, no credentials, no vendor data invented or read.

Honesty boundary: pair membership and request shape are structural.
Cross-type parameter semantics, non-ASCII exchange behavior, and
on-device transfer effects require per-profile acceptance and remain
open; every behavioral slot starts ``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class ConversionPlan:
    source: str
    target: str
    steps: tuple[str, ...]
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def _pair_table(table: Any) -> set[tuple[str, str]]:
    if isinstance(table, dict):
        items = list(table.keys())
    elif isinstance(table, (set, frozenset, list, tuple)) and not isinstance(
        table, (str, bytes)
    ):
        items = list(table)
    else:
        raise TypeError("table must be a mapping or collection of pairs")
    pairs: set[tuple[str, str]] = set()
    for pos, item in enumerate(items):
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or not isinstance(item[1], str)
            or not item[1]
        ):
            raise ValueError(f"table pair {pos} must be (str, str) non-empty")
        pairs.add((item[0], item[1]))
    return pairs


def supported_pairs(table: Any) -> tuple[tuple[str, str], ...]:
    """Return the sorted supported profile pairs from a caller table."""
    return tuple(sorted(_pair_table(table)))


def plan_conversion(
    source: str,
    target: str,
    table: Any,
    params: Any,
    extra: dict[str, Any] | None = None,
) -> ConversionPlan:
    """Plan a unit conversion request (no side effects).

    Raises ``ValueError`` for empty profiles, identical source/target,
    unsupported pairs, and non-dict params. Same-profile requests are
    rejected as conversions (use copy flows instead).
    """
    if not isinstance(source, str) or not source:
        raise ValueError("source must be a non-empty str")
    if not isinstance(target, str) or not target:
        raise ValueError("target must be a non-empty str")
    if source == target:
        raise ValueError("source and target must differ for conversion")
    pairs = _pair_table(table)
    if (source, target) not in pairs:
        raise ValueError(f"unsupported conversion: {source!r} -> {target!r}")
    if not isinstance(params, dict):
        raise TypeError("params must be dict")
    echo = copy.deepcopy(dict(extra) if extra is not None else {})
    echo["params"] = copy.deepcopy(params)
    return ConversionPlan(
        source=source,
        target=target,
        steps=(
            "validate_profiles",
            "check_pair_supported",
            "map_params",
            "verify_no_transfer",
        ),
        echo=echo,
    )
