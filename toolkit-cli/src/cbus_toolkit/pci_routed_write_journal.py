"""Exclusive attempt journal for one direct routed WRITE.

The journal is exclusively created (``O_EXCL``) and fsynced, file and
directory, before the one-shot WRITE leaves the host.  From creation it
records ``send_may_have_occurred=true`` and ``read_only_recovery_only=true``:
a crash at any later instant can leave the record as the only evidence, and
nothing in it ever authorizes a replay.  Later phase updates are atomic,
fsynced replacements that first prove the file still holds this writer's
previous bytes (the shared selected-serial ``_Journal`` writer).

The immutable ``plan`` binds the endpoint, the exact WRITE, the declared ACK
path, the project SHA-256 and route plan when a project resolved the route,
a ``topology_sha256`` over the route facts, the PCI generation observed when
the attempt was planned (``null`` when the caller has no generation source),
and the read-only RECALL recovery contract with its pre-write baseline.
``attempt_id`` is SHA-256 over the canonical plan.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from .pci_selected_serial import _Journal, _unique_pairs


JOURNAL_FORMAT = "cbus-pci-routed-write-journal-v1"
OPERATION = "pci-routed-write"
MAX_ROUTED_WRITE_JOURNAL_BYTES = 1024 * 1024
MAX_SCANNED_ENTRIES = 4096
# ``planned``: created and fsynced; the send may have happened after it.
# ``not-sent``: the client proved no WRITE byte was handed to the socket.
# ``acknowledged``: exact confirmation and ACK on an unchanged generation.
# ``uncertain``: a send was attempted and its outcome is not established.
PHASES = ("planned", "not-sent", "acknowledged", "uncertain")
GENERATION_SOURCES = ("caller-probe", "unavailable")
_DOCUMENT_KEYS = frozenset({
    "format", "operation", "attempt_id", "plan", "send_may_have_occurred",
    "read_only_recovery_only", "phase", "history", "send", "recoveries",
    "complete", "resolved", "resolution",
})
_PLAN_KEYS = frozenset({
    "endpoint", "command_checksum", "unit", "parameter", "data_hex", "expected_ack_tag",
    "bridges", "expected", "mode", "project_sha256", "route_plan", "topology_sha256",
    "pci_generation", "pci_generation_source", "recovery_read",
})
_PATH_KEYS = frozenset({"outer_source_byte", "destination_byte", "route_entries"})
_READ_KEYS = frozenset({"parameter", "count", "expected_hex", "baseline_hex"})
_HEX = re.compile(r"(?:[0-9A-F]{2})*")
_SHA = re.compile(r"[0-9a-f]{64}")


class RoutedWriteJournalError(ValueError):
    """The journal is missing, malformed, or refuses the requested WRITE."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def attempt_id(plan: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical(plan)).hexdigest()


def topology_sha256(*, mode: str, bridges, expected: Mapping[str, Any],
                    project_sha256: str | None, route_plan: Mapping[str, Any] | None) -> str:
    """Digest of every route fact the WRITE and its recovery depend on."""
    return hashlib.sha256(canonical({
        "mode": mode,
        "bridges": list(bridges),
        "expected": dict(expected),
        "project_sha256": project_sha256,
        "route_plan": None if route_plan is None else dict(route_plan),
    })).hexdigest()


def _byte(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 255


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RoutedWriteJournalError("Routed WRITE journal is malformed: " + message)


def validate(document: Any) -> dict[str, Any]:
    """Strictly validate one journal document and return it."""
    _require(type(document) is dict, "expected one JSON object")
    _require(set(document) == _DOCUMENT_KEYS, "unsupported or missing fields")
    _require(document["format"] == JOURNAL_FORMAT, "unsupported format")
    _require(document["operation"] == OPERATION, "unsupported operation")
    _require(document["send_may_have_occurred"] is True, "send_may_have_occurred must be true")
    _require(document["read_only_recovery_only"] is True, "read_only_recovery_only must be true")
    plan = document["plan"]
    _require(type(plan) is dict and set(plan) == _PLAN_KEYS, "plan fields")
    _require(document["attempt_id"] == attempt_id(plan), "attempt_id does not match its plan")
    endpoint = plan["endpoint"]
    _require(type(endpoint) is dict and set(endpoint) == {"host", "port"}
             and type(endpoint["host"]) is str and endpoint["host"]
             and type(endpoint["port"]) is int and 1 <= endpoint["port"] <= 65535, "endpoint")
    _require(type(plan["command_checksum"]) is bool, "command_checksum")
    for name in ("unit", "parameter", "expected_ack_tag"):
        _require(_byte(plan[name]), name)
    data = plan["data_hex"]
    _require(type(data) is str and _HEX.fullmatch(data) is not None and 4 <= len(data) <= 60,
             "data_hex")
    _require(int(data[:2], 16) == plan["expected_ack_tag"], "first WRITE byte must be the ACK tag")
    bridges = plan["bridges"]
    _require(type(bridges) is list and len(bridges) <= 6 and all(map(_byte, bridges)), "bridges")
    expected = plan["expected"]
    _require(type(expected) is dict and set(expected) == _PATH_KEYS
             and _byte(expected["outer_source_byte"]) and _byte(expected["destination_byte"])
             and type(expected["route_entries"]) is list and len(expected["route_entries"]) <= 6
             and all(map(_byte, expected["route_entries"])), "expected path")
    terminal = (expected["route_entries"][-1] if expected["route_entries"]
                else expected["outer_source_byte"])
    _require(terminal == plan["unit"], "expected path must end at the unit")
    _require(plan["mode"] in ("typed", "raw"), "mode")
    if plan["mode"] == "typed":
        _require(type(plan["project_sha256"]) is str and _SHA.fullmatch(plan["project_sha256"]) is not None,
                 "project_sha256")
        _require(type(plan["route_plan"]) is dict
                 and plan["route_plan"].get("project_sha256") == plan["project_sha256"]
                 and plan["route_plan"].get("bridges") == bridges
                 and plan["route_plan"].get("expected_ack_path") == expected, "route_plan")
    else:
        _require(plan["project_sha256"] is None and plan["route_plan"] is None,
                 "raw mode carries no project")
    _require(plan["topology_sha256"] == topology_sha256(
        mode=plan["mode"], bridges=bridges, expected=expected,
        project_sha256=plan["project_sha256"], route_plan=plan["route_plan"]), "topology_sha256")
    _require(plan["pci_generation"] is None or type(plan["pci_generation"]) is int, "pci_generation")
    _require(plan["pci_generation_source"] in GENERATION_SOURCES, "pci_generation_source")
    _require((plan["pci_generation_source"] == "unavailable") == (plan["pci_generation"] is None),
             "pci_generation source/value")
    read = plan["recovery_read"]
    _require(type(read) is dict and set(read) == _READ_KEYS, "recovery_read fields")
    _require(read["parameter"] == plan["parameter"] and read["count"] == len(data) // 2 - 1,
             "recovery_read range")
    _require(read["expected_hex"] == data[2:], "recovery_read expected bytes")
    _require(type(read["baseline_hex"]) is str and _HEX.fullmatch(read["baseline_hex"]) is not None
             and len(read["baseline_hex"]) == 2 * read["count"], "recovery_read baseline")
    _require(document["phase"] in PHASES, "phase")
    _require(type(document["history"]) is list and document["history"], "history")
    _require(document["send"] is None or type(document["send"]) is dict, "send")
    _require(type(document["recoveries"]) is list, "recoveries")
    _require(type(document["complete"]) is bool and type(document["resolved"]) is bool,
             "complete/resolved")
    _require(document["resolution"] is None or type(document["resolution"]) is dict, "resolution")
    return document


def _parse(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError("Nonfinite JSON value")),
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise RoutedWriteJournalError("Routed WRITE journal is not strict UTF-8 JSON") from error
    return validate(value)


class RoutedWriteJournal:
    """Exclusive, fsynced writer for one routed WRITE attempt."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path).absolute()
        self._writer = _Journal(self.path)
        self.document: dict[str, Any] | None = None
        self.raw: bytes | None = None

    @property
    def last_update(self) -> dict[str, Any]:
        return dict(self._writer.last_update)

    def _write(self, document: dict[str, Any]) -> None:
        validate(document)
        if len(canonical(document)) + 1 > MAX_ROUTED_WRITE_JOURNAL_BYTES:
            raise RoutedWriteJournalError("Routed WRITE journal exceeds its size bound")
        self._writer.write(document)
        self.document = document
        self.raw = self._writer.expected

    @classmethod
    def create(cls, path: str | os.PathLike[str], plan: dict[str, Any]) -> "RoutedWriteJournal":
        journal = cls(path)
        document = {
            "format": JOURNAL_FORMAT,
            "operation": OPERATION,
            "attempt_id": attempt_id(plan),
            "plan": plan,
            "send_may_have_occurred": True,
            "read_only_recovery_only": True,
            "phase": "planned",
            "history": [{"phase": "planned", "at": now()}],
            "send": None,
            "recoveries": [],
            "complete": False,
            "resolved": False,
            "resolution": None,
        }
        try:
            journal._write(document)
        except FileExistsError as error:
            raise RoutedWriteJournalError(
                f"Routed WRITE journal already exists at {journal.path}; no WRITE was sent"
            ) from error
        return journal

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "RoutedWriteJournal":
        journal = cls(path)
        try:
            raw = journal._writer._read_current()
        except FileNotFoundError as error:
            raise RoutedWriteJournalError(f"Routed WRITE journal {journal.path} does not exist") from error
        except (OSError, ValueError) as error:
            raise RoutedWriteJournalError(
                f"Routed WRITE journal {journal.path} is unreadable: {error}") from error
        if len(raw) > MAX_ROUTED_WRITE_JOURNAL_BYTES:
            raise RoutedWriteJournalError("Routed WRITE journal exceeds its size bound")
        journal.document = _parse(raw)
        journal.raw = raw
        journal._writer.expected = raw
        return journal

    def advance(self, phase: str | None = None,
                mutate: Callable[[dict[str, Any]], None] | None = None) -> None:
        if self.document is None:
            raise RoutedWriteJournalError("Routed WRITE journal is not open")
        document = json.loads(canonical(self.document))
        if mutate is not None:
            mutate(document)
        if phase is not None:
            if phase not in PHASES:
                raise RoutedWriteJournalError(f"Unknown routed WRITE journal phase {phase!r}")
            document["phase"] = phase
            document["history"].append({"phase": phase, "at": now()})
        self._write(document)


def target_key(plan: Mapping[str, Any]) -> tuple:
    """Endpoint, outgoing route and unit that one attempt may have changed."""
    return (plan["endpoint"]["host"], plan["endpoint"]["port"], tuple(plan["bridges"]), plan["unit"])


def _unresolved(document: Mapping[str, Any]) -> bool:
    return not (document.get("complete") is True or document.get("resolved") is True)


def refuse_unresolved(path: str | os.PathLike[str], key: tuple) -> None:
    """Refuse a WRITE before any I/O while a same-target attempt needs recovery.

    The selected path must not exist.  Every other valid routed WRITE journal
    in the same directory naming the same endpoint, route and unit must be
    complete or resolved by ``routed-write --recover``.
    """
    target = Path(path).absolute()
    if target.name in ("", ".", ".."):
        raise RoutedWriteJournalError("Routed WRITE journal path must name a file")
    directory = target.parent
    if not directory.is_dir():
        raise RoutedWriteJournalError(f"Routed WRITE journal directory {directory} does not exist")
    try:
        os.lstat(target)
    except FileNotFoundError:
        pass
    else:
        raise RoutedWriteJournalError(
            f"Routed WRITE journal path {target} already exists; choose a new path or run "
            f"'routed-write --recover --journal {target}'. No PCI I/O was attempted"
        )
    scanned = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.name.endswith(".json") or entry.name.startswith("."):
                continue
            scanned += 1
            if scanned > MAX_SCANNED_ENTRIES:
                raise RoutedWriteJournalError(
                    "Routed WRITE journal directory holds too many JSON files to scan")
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ROUTED_WRITE_JOURNAL_BYTES:
                continue
            try:
                document = RoutedWriteJournal.open(entry.path).document or {}
            except RoutedWriteJournalError:
                continue
            if target_key(document["plan"]) == key and _unresolved(document):
                raise RoutedWriteJournalError(
                    f"Routed WRITE journal {entry.path} records an unresolved attempt for this "
                    f"endpoint, route and unit (phase {document['phase']!r}); run "
                    f"'routed-write --recover --journal {entry.path}' first. No PCI I/O was attempted"
                )
