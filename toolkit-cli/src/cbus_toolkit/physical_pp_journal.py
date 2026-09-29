"""Durable attempt journal for one physical PP save through cmqttd.

The journal is exclusively created and fsynced before the first ``PP SAVE`` or
``PP SAVE_TO_SOURCE`` is issued.  It uses the same envelope semantics as the
selected-serial attempt marker (``cbus_transport::apply``): from creation it
records ``send_may_have_occurred=true`` and ``read_only_recovery_only=true``,
because a crash at any later instant can leave the record as the only
evidence.  Neither the journal nor any later observation ever authorizes a
replay.  Each phase update is an atomic, fsynced replacement that first proves
the file still holds this writer's previous bytes.

The immutable ``plan`` binds the unit identity, method, planned byte ranges
(logical PP address, length and SHA-256 of the loaded and staged bytes) and
the captured cmqttd PCI generation.  ``attempt_id`` is SHA-256 over the
canonical plan, so a reader can detect an edited plan.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Callable, Mapping

from .pci_selected_serial import _Journal, _unique_pairs


JOURNAL_FORMAT = "cbus-physical-pp-journal-v1"
OPERATION = "physical-pp-save"
MAX_PP_JOURNAL_BYTES = 4 * 1024 * 1024
MAX_SCANNED_ENTRIES = 4096
PHASES = (
    "planned",
    "save-sent",
    "save-confirmed",
    "save-uncertain",
    "readback-verified",
    "readback-mismatch",
    "readback-unavailable",
    "complete",
)
# Per-range store state.  ``possible`` means the SAVE command was sent and the
# range may have been written; ``confirmed`` means cmqttd reported the range's
# tagged STORE acknowledgements and its exact per-range readback.
STORE_STATES = ("not-planned", "planned", "possible", "confirmed", "uncertain", "not-attempted")
NVM_STATES = ("not-required", "planned", "possible", "confirmed", "uncertain", "not-reached")
_DOCUMENT_KEYS = frozenset({
    "format", "operation", "attempt_id", "plan", "send_may_have_occurred",
    "read_only_recovery_only", "phase", "history", "ranges", "nvm_commit",
    "save_reply", "fresh_readback", "recoveries", "complete", "resolved", "resolution",
})
_PLAN_KEYS = frozenset({
    "operation_id", "unit", "schema_sha256", "method", "native_save_operation",
    "requires_nvm_commit", "pci_generation", "edits", "ranges",
})
_UNIT_KEYS = frozenset({"source", "destination", "lock_address", "project", "network", "unit"})
_RANGE_KEYS = frozenset({
    "index", "parameter", "program_method", "protection", "type", "logical_address",
    "length", "old_sha256", "new_sha256", "changed", "write_planned",
})
_PROGRESS_KEYS = frozenset({"index", "store_state"})


class PhysicalPPJournalError(ValueError):
    """The journal is missing, malformed, or refuses the requested save."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def attempt_id(plan: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical(plan)).hexdigest()


def byte_digest(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def _is_hex_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PhysicalPPJournalError("Physical PP journal is malformed: " + message)


def validate(document: Any) -> dict[str, Any]:
    """Strictly validate one journal document and return it."""
    _require(type(document) is dict, "expected one JSON object")
    _require(set(document) == _DOCUMENT_KEYS, "unsupported or missing fields")
    _require(document["format"] == JOURNAL_FORMAT, "unsupported format")
    _require(document["operation"] == OPERATION, "unsupported operation")
    # The same conservative envelope as the Rust/Python attempt marker.
    _require(document["send_may_have_occurred"] is True, "send_may_have_occurred must be true")
    _require(document["read_only_recovery_only"] is True, "read_only_recovery_only must be true")
    plan = document["plan"]
    _require(type(plan) is dict and set(plan) == _PLAN_KEYS, "plan fields")
    _require(document["attempt_id"] == attempt_id(plan), "attempt_id does not match its plan")
    unit = plan["unit"]
    _require(type(unit) is dict and set(unit) == _UNIT_KEYS, "unit identity fields")
    for name in ("source", "destination", "lock_address", "project"):
        _require(isinstance(unit[name], str) and unit[name], f"unit {name}")
    for name in ("network", "unit"):
        _require(type(unit[name]) is int, f"unit {name}")
    _require(_is_hex_digest(plan["schema_sha256"]), "schema_sha256")
    _require(isinstance(plan["method"], str), "method")
    _require(type(plan["requires_nvm_commit"]) is bool, "requires_nvm_commit")
    _require(plan["pci_generation"] is None or type(plan["pci_generation"]) is int,
             "pci_generation")
    ranges = plan["ranges"]
    _require(type(ranges) is list and ranges, "planned ranges")
    for index, row in enumerate(ranges):
        _require(type(row) is dict and set(row) == _RANGE_KEYS, "planned range fields")
        _require(row["index"] == index, "planned range order")
        _require(type(row["logical_address"]) is int and 0 <= row["logical_address"] < 65536,
                 "range address")
        _require(type(row["length"]) is int and 1 <= row["length"] <= 65536, "range length")
        _require(_is_hex_digest(row["old_sha256"]) and _is_hex_digest(row["new_sha256"]),
                 "range digests")
        _require(type(row["changed"]) is bool and type(row["write_planned"]) is bool,
                 "range flags")
    _require(document["phase"] in PHASES, "phase")
    _require(type(document["history"]) is list and document["history"], "history")
    progress = document["ranges"]
    _require(type(progress) is list and len(progress) == len(ranges), "range progress")
    for index, row in enumerate(progress):
        _require(type(row) is dict and set(row) == _PROGRESS_KEYS and row["index"] == index,
                 "range progress fields")
        _require(row["store_state"] in STORE_STATES, "range store state")
    _require(document["nvm_commit"] in NVM_STATES, "nvm_commit")
    _require(type(document["recoveries"]) is list, "recoveries")
    _require(type(document["complete"]) is bool and type(document["resolved"]) is bool,
             "complete/resolved")
    return document


def _parse(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError("Nonfinite JSON value")),
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise PhysicalPPJournalError("Physical PP journal is not strict UTF-8 JSON") from error
    return validate(value)


class PhysicalPPJournal:
    """Exclusive, fsynced writer for one physical PP save attempt."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path).absolute()
        self._writer = _Journal(self.path)
        self.document: dict[str, Any] | None = None

    @property
    def last_update(self) -> dict[str, Any]:
        return dict(self._writer.last_update)

    @property
    def failed(self) -> bool:
        return self._writer.failed

    def _write(self, document: dict[str, Any]) -> None:
        validate(document)
        raw = canonical(document)
        if len(raw) + 1 > MAX_PP_JOURNAL_BYTES:
            raise PhysicalPPJournalError("Physical PP journal exceeds its size bound")
        self._writer.write(document)
        self.document = document

    @classmethod
    def create(cls, path: str | os.PathLike[str], plan: dict[str, Any]) -> "PhysicalPPJournal":
        """Exclusively create and fsync the journal (file and directory)."""
        journal = cls(path)
        write_planned = [row["write_planned"] for row in plan["ranges"]]
        document = {
            "format": JOURNAL_FORMAT,
            "operation": OPERATION,
            "attempt_id": attempt_id(plan),
            "plan": plan,
            "send_may_have_occurred": True,
            "read_only_recovery_only": True,
            "phase": "planned",
            "history": [{"phase": "planned", "at": now()}],
            "ranges": [
                {"index": index, "store_state": "planned" if planned else "not-planned"}
                for index, planned in enumerate(write_planned)
            ],
            "nvm_commit": (
                "planned" if plan["requires_nvm_commit"] and any(write_planned)
                else "not-required"
            ),
            "save_reply": None,
            "fresh_readback": None,
            "recoveries": [],
            "complete": False,
            "resolved": False,
            "resolution": None,
        }
        try:
            journal._write(document)
        except FileExistsError as error:
            raise PhysicalPPJournalError(
                f"Physical PP journal already exists at {journal.path}; no PP SAVE was sent"
            ) from error
        return journal

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "PhysicalPPJournal":
        """Read one bounded regular journal for recovery and later updates."""
        journal = cls(path)
        try:
            raw = journal._writer._read_current()
        except FileNotFoundError as error:
            raise PhysicalPPJournalError(f"Physical PP journal {journal.path} does not exist") from error
        except (OSError, ValueError) as error:
            raise PhysicalPPJournalError(f"Physical PP journal {journal.path} is unreadable: {error}") from error
        if len(raw) > MAX_PP_JOURNAL_BYTES:
            raise PhysicalPPJournalError("Physical PP journal exceeds its size bound")
        journal.document = _parse(raw)
        # Later replacements must prove the file still holds these bytes.
        journal._writer.expected = raw
        return journal

    def advance(self, phase: str | None = None,
                mutate: Callable[[dict[str, Any]], None] | None = None) -> None:
        """Atomically replace the journal with the next phase/progress state."""
        if self.document is None:
            raise PhysicalPPJournalError("Physical PP journal is not open")
        document = json.loads(canonical(self.document))
        if mutate is not None:
            mutate(document)
        if phase is not None:
            if phase not in PHASES:
                raise PhysicalPPJournalError(f"Unknown physical PP journal phase {phase!r}")
            document["phase"] = phase
            document["history"].append({"phase": phase, "at": now()})
        self._write(document)


def _unresolved(document: Mapping[str, Any]) -> bool:
    return not (document.get("complete") is True or document.get("resolved") is True)


def refuse_unresolved(path: str | os.PathLike[str], destination: str) -> None:
    """Refuse a save before any I/O while an attempt needs recovery.

    The selected path must not exist.  Every other ``*.json`` physical PP
    journal in the same directory that names the same destination unit must
    be complete or resolved by ``physical-pp recover``.
    """
    target = Path(path).absolute()
    if target.name in ("", ".", ".."):
        raise PhysicalPPJournalError("Physical PP journal path must name a file")
    directory = target.parent
    if not directory.is_dir():
        raise PhysicalPPJournalError(f"Physical PP journal directory {directory} does not exist")
    try:
        os.lstat(target)
    except FileNotFoundError:
        pass
    else:
        try:
            existing = PhysicalPPJournal.open(target).document or {}
        except PhysicalPPJournalError as error:
            raise PhysicalPPJournalError(
                f"Physical PP journal path {target} already exists and is not a valid journal; "
                "no PP I/O was attempted"
            ) from error
        if _unresolved(existing):
            raise PhysicalPPJournalError(
                f"Physical PP journal {target} records an incomplete save (phase "
                f"{existing.get('phase')!r}); run 'physical-pp recover --journal {target}' "
                "before another save. No PP I/O was attempted"
            )
        raise PhysicalPPJournalError(
            f"Physical PP journal {target} already holds a finished attempt; choose a new "
            "journal path. No PP I/O was attempted"
        )
    scanned = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.name.endswith(".json") or entry.name.startswith("."):
                continue
            scanned += 1
            if scanned > MAX_SCANNED_ENTRIES:
                raise PhysicalPPJournalError(
                    "Physical PP journal directory holds too many JSON files to scan"
                )
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PP_JOURNAL_BYTES:
                continue
            try:
                document = PhysicalPPJournal.open(entry.path).document or {}
            except PhysicalPPJournalError:
                continue
            if document["plan"]["unit"]["destination"] == destination and _unresolved(document):
                raise PhysicalPPJournalError(
                    f"Physical PP journal {entry.path} records an incomplete save for "
                    f"{destination} (phase {document.get('phase')!r}); run "
                    f"'physical-pp recover --journal {entry.path}' first. No PP I/O was attempted"
                )
