"""DLT variant guard spec (issue #11 P-E, bead cbus-kxo).

Spec-first offline scaffold only. Pure model/firmware variant lookup
where the variant table is a caller-supplied fact, never embedded
vendor data. Firmware matches exactly (no semver range invention).
No devices, no USB, no firmware writes, no endpoints, no credentials.

Honesty boundary: table membership is structural. Variant behavior,
physical reset/factory effects, updater payload compatibility, and
bootloader/recovery acceptance remain open; every behavioral slot
starts ``unassessed``. Live-hardware legs are additionally guarded
and out of scope here.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class VariantCheck:
    supported: bool
    note: str
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def _table_pairs(table: Any) -> dict[tuple[str, str], Any]:
    if isinstance(table, dict):
        items = list(table.items())
    elif isinstance(table, (set, frozenset, list, tuple)) and not isinstance(
        table, (str, bytes)
    ):
        items = [(p, {}) for p in table]
    else:
        raise TypeError("table must be a mapping or pair collection")
    out: dict[tuple[str, str], Any] = {}
    for pos, item in enumerate(items):
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 2
            or not isinstance(item[0], (list, tuple))
            or len(item[0]) != 2
        ):
            raise ValueError(f"table entry {pos} must be ((model, fw), info)")
        (model, fw), _info = item
        if not isinstance(model, str) or not model:
            raise ValueError(f"table entry {pos} model must be non-empty str")
        if not isinstance(fw, str) or not fw:
            raise ValueError(f"table entry {pos} firmware must be non-empty str")
        out[(model, fw)] = item[1]
    return out


def supported_variants(table: Any) -> tuple[tuple[str, str], ...]:
    """Return sorted (model, firmware) pairs from a caller table."""
    return tuple(sorted(_table_pairs(table)))


def check_variant(model: Any, firmware: Any, table: Any) -> VariantCheck:
    """Check exact (model, firmware) membership in a caller table."""
    if not isinstance(model, str) or not model:
        raise ValueError("model must be a non-empty str")
    if not isinstance(firmware, str) or not firmware:
        raise ValueError("firmware must be a non-empty str")
    pairs = _table_pairs(table)
    if (model, firmware) in pairs:
        return VariantCheck(
            supported=True,
            note=f"{model} @ {firmware} listed",
            echo=copy.deepcopy(
                pairs[(model, firmware)]
                if isinstance(pairs[(model, firmware)], dict)
                else {"info": pairs[(model, firmware)]}
            ),
        )
    return VariantCheck(
        supported=False, note=f"{model} @ {firmware} not listed")
