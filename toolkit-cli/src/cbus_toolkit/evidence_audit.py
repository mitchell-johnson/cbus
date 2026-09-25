"""Ledger evidence-path auditor (issue #11 boxes 14/16, bead cbus-sb2).

Spec-first offline scaffold only. Pure existence audit: every ledger
feature's ``evidence`` paths must resolve under a caller-supplied root.
No status flips, no acceptance claims, no file writes, no endpoints.

Honesty function: missing evidence paths are the cheapest false-
completion vector (a ledger entry citing a file that does not exist).
This module reports them structurally. Presence on disk is NOT
acceptance — content comparison against independent Toolkit behavior
remains open and every behavioral slot starts ``unassessed``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class EvidenceAudit:
    checked: int
    missing: tuple[str, ...]
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def audit_evidence(ledger: Any, root: Any) -> EvidenceAudit:
    """Audit that all ledger evidence paths exist under root.

    ``ledger``: dict with a ``features`` list of ``{"id": str,
    "evidence": [str]}`` entries (``evidence`` may be absent → no
    paths). ``root``: directory path (str or ``Path``). Returns counts
    plus ``"id:path"`` strings for missing files. Malformed ledger
    raises ``TypeError``/``ValueError``; a missing root raises
    ``ValueError`` (never creates directories).
    """
    if not isinstance(ledger, dict):
        raise TypeError("ledger must be dict")
    try:
        features = ledger["features"]
    except KeyError as exc:
        raise ValueError("ledger missing 'features'") from exc
    if not isinstance(features, list):
        raise ValueError("ledger 'features' must be a list")
    base = Path(root) if not isinstance(root, Path) else root
    if not base.is_dir():
        raise ValueError(f"root is not a directory: {root!r}")
    missing: list[str] = []
    checked = 0
    for pos, entry in enumerate(features):
        if not isinstance(entry, dict):
            raise TypeError(f"feature {pos} must be dict")
        fid = entry.get("id", None)
        if not isinstance(fid, str) or not fid:
            raise ValueError(f"feature {pos} id must be a non-empty str")
        evidence = entry.get("evidence", [])
        if not isinstance(evidence, list) or any(
            not isinstance(p, str) or not p for p in evidence
        ):
            raise ValueError(f"feature {fid!r} evidence must be str list")
        for path in evidence:
            checked += 1
            if not (base / path).exists():
                missing.append(f"{fid}:{path}")
    return EvidenceAudit(checked=checked, missing=tuple(sorted(missing)))
