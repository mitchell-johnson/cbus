"""Commissioning recovery journal spec (issue #11 box 2, bead cbus-61h).

Spec-first offline scaffold only. Pure in-memory append-only journal
recording commissioning steps (move/address/verify/save) so an
interrupted workflow can resume or roll back deterministically. No
file I/O, no bus calls, no endpoints, no credentials.

Honesty boundary: journal integrity (sequence continuity, op allowlist,
roundtrip fidelity) is structural. It establishes no on-device recovery
behavior; physical persistence and coupled-bridge recovery remain open
and every physical slot starts ``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"

ALLOWED_OPS = ("move", "address", "verify", "save", "rollback_note")


@dataclass(frozen=True)
class JournalEntry:
    seq: int
    op: str
    target: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JournalCheck:
    ok: bool
    problems: tuple[str, ...]
    physical_comparison: str = UNASSESSED


def append_entry(
    entries: Any, op: str, target: str, detail: dict[str, Any] | None = None
) -> tuple[JournalEntry, ...]:
    """Append one entry, returning a new tuple (input never mutated).

    ``entries`` is a sequence of ``JournalEntry`` (empty allowed).
    ``op`` must be in ``ALLOWED_OPS``; ``target`` a non-empty str.
    ``seq`` auto-assigns as ``len(entries)``. ``detail`` deep-copied.
    """
    if isinstance(entries, (str, bytes)) or not hasattr(entries, "__iter__"):
        raise TypeError("entries must be a sequence of JournalEntry")
    items = tuple(entries)
    for pos, item in enumerate(items):
        if not isinstance(item, JournalEntry):
            raise TypeError(f"entry {pos} must be JournalEntry")
    if op not in ALLOWED_OPS:
        raise ValueError(f"unknown op: {op!r}")
    if not isinstance(target, str) or not target:
        raise ValueError("target must be a non-empty str")
    entry = JournalEntry(
        seq=len(items),
        op=op,
        target=target,
        detail=copy.deepcopy(dict(detail) if detail is not None else {}),
    )
    return items + (entry,)


def verify_journal(entries: Any) -> JournalCheck:
    """Check sequence continuity (0..n-1), op allowlist, target shape."""
    if isinstance(entries, (str, bytes)) or not hasattr(entries, "__iter__"):
        raise TypeError("entries must be a sequence of JournalEntry")
    items = tuple(entries)
    problems: list[str] = []
    for pos, item in enumerate(items):
        if not isinstance(item, JournalEntry):
            problems.append(f"entry {pos} not a JournalEntry")
            continue
        if item.seq != pos:
            problems.append(
                f"entry {pos} seq {item.seq} breaks continuity"
            )
        if item.op not in ALLOWED_OPS:
            problems.append(f"entry {pos} unknown op {item.op!r}")
        if not isinstance(item.target, str) or not item.target:
            problems.append(f"entry {pos} bad target")
    return JournalCheck(ok=not problems, problems=tuple(problems))


def serialize(entries: Any) -> list[dict[str, Any]]:
    """Render entries to plain JSON-ready dicts (deep copy)."""
    if isinstance(entries, (str, bytes)) or not hasattr(entries, "__iter__"):
        raise TypeError("entries must be a sequence of JournalEntry")
    out: list[dict[str, Any]] = []
    for pos, item in enumerate(entries):
        if not isinstance(item, JournalEntry):
            raise TypeError(f"entry {pos} must be JournalEntry")
        out.append(
            {
                "seq": item.seq,
                "op": item.op,
                "target": item.target,
                "detail": copy.deepcopy(item.detail),
            }
        )
    return out


def load(entries: Any) -> tuple[JournalEntry, ...]:
    """Rebuild entries from ``serialize`` output, verifying continuity."""
    if isinstance(entries, (str, bytes)) or not hasattr(entries, "__iter__"):
        raise TypeError("entries must be a sequence of dicts")
    rebuilt: list[JournalEntry] = []
    for pos, item in enumerate(entries):
        if not isinstance(item, dict):
            raise TypeError(f"entry {pos} must be dict")
        try:
            seq, op, target = item["seq"], item["op"], item["target"]
            detail = item.get("detail", {})
        except KeyError as exc:
            raise ValueError(f"entry {pos} missing key {exc}") from exc
        if seq != pos:
            raise ValueError(f"entry {pos} seq {seq} breaks continuity")
        if op not in ALLOWED_OPS:
            raise ValueError(f"entry {pos} unknown op {op!r}")
        if not isinstance(target, str) or not target:
            raise ValueError(f"entry {pos} bad target")
        if not isinstance(detail, dict):
            raise ValueError(f"entry {pos} detail must be dict")
        rebuilt.append(
            JournalEntry(
                seq=seq, op=op, target=target,
                detail=copy.deepcopy(detail),
            )
        )
    return tuple(rebuilt)
