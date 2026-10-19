"""One-shot WRITE with explicit ACK and route expectations.

The caller supplies literal outgoing and incoming route bytes plus the expected
ACK tag.  This module never resolves a logical network, retries a mutation, or
turns an ACK into a claim about nonvolatile device state.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
import os
import socket
import stat
import tempfile
import threading
import time
from pathlib import Path

from .pci import AcknowledgeCAL, PCIRejected, ProtocolError, WriteCAL
from .pci_routing import RoutedCALCommand, ReceivedCALRoute, inspect_received_cal_route
from .pci_routed_recall import RoutedReplyPath, _Stream, _path, _integer, _copy, _error


@dataclass(frozen=True)
class RoutedWriteEvent:
    kind: str
    raw: bytes
    matched: bool
    status: str | None = None
    frame: ReceivedCALRoute | None = None

    def as_dict(self):
        value = {"kind": self.kind, "raw_hex": self.raw.hex().upper(), "matched": self.matched}
        if self.status is not None:
            value["status"] = self.status
        if self.frame is not None:
            value["frame"] = self.frame.as_dict()
        return value


@dataclass(frozen=True)
class RoutedWriteResult:
    command: RoutedCALCommand
    expected: RoutedReplyPath
    expected_ack_tag: int
    sent: bytes
    confirmation: bytes
    acknowledgement: ReceivedCALRoute
    events: tuple[RoutedWriteEvent, ...]
    received_chunks: tuple[bytes, ...]

    def as_dict(self):
        return {
            "format": "cbus-routed-write-result-v1",
            "complete": True,
            "sent_hex": self.sent.hex().upper(),
            "confirmation": self.confirmation.decode("ascii"),
            "acknowledgement": self.acknowledgement.as_dict(),
            "expected": self.expected.as_dict(),
            "expected_ack_tag": self.expected_ack_tag,
            "events": [value.as_dict() for value in self.events],
            "received_chunks_hex": [value.hex().upper() for value in self.received_chunks],
            "matches_declared_wire_expectation": True,
            "confirmation_received": True,
            "acknowledgement_received": True,
            "request_sent_once": True,
            "resubmitted": False,
            "completion_boundary": "all bytes in the final received chunk processed",
            "raw_zero_address_ambiguous": self.command.unit == 0,
            "logical_network_resolved": False,
            "device_origin_verified": False,
            "causal_freshness_verified": False,
            "physical_delivery_verified": False,
            "parameter_commit_verified": False,
            "nonvolatile_persistence_verified": False,
            "original_cached_object_correlation_verified": False,
        }


def acknowledgement_matches(frame, expected, parameter, expected_ack_tag):
    """Return whether one inspected frame is the declared routed WRITE ACK.

    The complete received path (outer source, destination and route entries),
    the ACK parameter and the declared tag must all match. This is a byte-level
    correlation; it never resolves a cached logical network.
    """
    return (
        _path(frame) == expected
        and type(frame.cal) is AcknowledgeCAL
        and frame.cal.parameter == parameter
        and frame.cal.tag == expected_ack_tag
    )


class RoutedWriteClient:
    """Send one direct routed WRITE and require one exact ACK plus PCI confirm.

    A successful result proves only the caller-declared wire correlation.  The
    operation is deliberately one-shot because any failure after send can have
    an uncertain device side effect.
    """

    def __init__(self, host, port=10001, *, timeout=5.0, command_checksum=False,
                 max_events=256, max_received_bytes=32768):
        if type(host) is not str or not 1 <= len(host) <= 45 or "%" in host:
            raise ValueError("host must be a numeric IPv4 or IPv6 address without a zone")
        address = ipaddress.ip_address(host)
        self.host = str(address)
        self.family = socket.AF_INET if address.version == 4 else socket.AF_INET6
        self.port = _integer(port, "port", 1, 65535)
        if type(timeout) not in (int, float):
            raise ValueError("timeout must be finite and positive")
        try:
            timeout = float(timeout)
        except OverflowError as error:
            raise ValueError("timeout must be finite and positive") from error
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if type(command_checksum) is not bool:
            raise ValueError("command_checksum must be a Boolean")
        self.timeout, self.command_checksum = timeout, command_checksum
        self.max_events = _integer(max_events, "max_events", 1, 4096)
        self.max_received_bytes = _integer(max_received_bytes, "max_received_bytes", 1, 1048576)
        self._used = False
        self._lock = threading.Lock()
        self.last_error = None
        self.last_evidence = None

    def _remember(self, error, evidence):
        try:
            value = _copy(evidence)
        except BaseException as export_error:
            if error is None:
                error = export_error
            value = {
                "format": "cbus-routed-write-evidence-v1",
                "complete": False,
                "evidence_export_failed": True,
                "error_type": None if error is None else type(error).__name__,
            }
        self.last_error, self.last_evidence = error, value
        if error is not None:
            try:
                error.pci_routed_write_evidence = _copy(value)
            except BaseException:
                pass
        return error

    @staticmethod
    def _preflight(command, expected, expected_ack_tag):
        if type(command) is not RoutedCALCommand or type(command.cal) is not WriteCAL:
            raise ValueError("Only an exact RoutedCALCommand containing WriteCAL is supported")
        if type(command.addressing) is not str or command.addressing != "direct":
            raise ValueError("Routed WRITE requires explicit direct addressing")
        _integer(command.cal.parameter, "parameter", 0, 255)
        if not isinstance(command.cal.data, bytes) or len(command.cal.data) > 30:
            raise ValueError("WRITE data must be bytes with at most 30 values")
        expected_ack_tag = _integer(expected_ack_tag, "expected_ack_tag", 0, 255)
        canonical = RoutedCALCommand(
            command.unit,
            WriteCAL(command.cal.parameter, command.cal.data),
            bridges=command.bridges,
            addressing="direct",
        )
        if type(expected) is not RoutedReplyPath:
            raise ValueError("expected must be an exact RoutedReplyPath")
        path = RoutedReplyPath(expected.outer_source_byte, expected.destination_byte, expected.route_entries)
        terminal = path.route_entries[-1] if path.route_entries else path.outer_source_byte
        if terminal != canonical.unit:
            raise ValueError("Final declared ACK path byte must equal the requested unit")
        return canonical, path, expected_ack_tag

    def exchange(self, command, *, expected, expected_ack_tag):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A routed WRITE exchange is already active")
        self.last_error = self.last_evidence = None
        evidence = {
            "format": "cbus-routed-write-evidence-v1",
            "complete": False,
            "stage": "preflight",
            "connect_attempted": False,
            "send_attempted": False,
            "send_completed": False,
            "close_attempted": False,
            "close_completed": False,
            "resubmitted": False,
            "confirmation_received": False,
            "acknowledgement_received": False,
            "events": [],
            "received_chunks_hex": [],
            "cleanup_errors": [],
            "logical_network_resolved": False,
            "device_origin_verified": False,
            "parameter_commit_verified": False,
            "nonvolatile_persistence_verified": False,
            "original_cached_object_correlation_verified": False,
        }
        first = traceback = sock = result = None
        stream = _Stream()
        events = []
        chunks = []
        try:
            if self._used:
                raise RuntimeError("A routed WRITE client permits only one exchange")
            command, expected, expected_ack_tag = self._preflight(command, expected, expected_ack_tag)
            settings = RoutedWriteClient(
                self.host,
                self.port,
                timeout=self.timeout,
                command_checksum=self.command_checksum,
                max_events=self.max_events,
                max_received_bytes=self.max_received_bytes,
            )
            code = b"g"
            sent = command.encode(confirmation=code, checksum=settings.command_checksum)
            evidence.update(
                expected=expected.as_dict(),
                expected_ack_tag=expected_ack_tag,
                sent_hex=sent.hex().upper(),
                confirmation=code.decode("ascii"),
                raw_zero_address_ambiguous=command.unit == 0,
            )
            self._used = True
            deadline = time.monotonic() + settings.timeout

            def remaining():
                value = deadline - time.monotonic()
                if value <= 0:
                    raise TimeoutError("Routed WRITE I/O deadline expired; write outcome is uncertain")
                return value

            evidence["stage"] = "connect"
            evidence["connect_attempted"] = True
            sock = socket.socket(settings.family, socket.SOCK_STREAM)
            sock.settimeout(remaining())
            endpoint = ((settings.host, settings.port) if settings.family == socket.AF_INET
                        else (settings.host, settings.port, 0, 0))
            sock.connect(endpoint)
            evidence["stage"] = "send"
            sock.settimeout(remaining())
            evidence["send_attempted"] = True
            sock.sendall(sent)
            evidence["send_completed"] = True
            confirmed = False
            acknowledgement = None
            received = 0
            evidence["stage"] = "receive"
            while not (confirmed and acknowledgement is not None):
                if received >= settings.max_received_bytes:
                    raise ProtocolError("Routed WRITE received-byte limit reached; write outcome is uncertain")
                sock.settimeout(remaining())
                chunk = sock.recv(min(4096, settings.max_received_bytes - received))
                if type(chunk) is not bytes or len(chunk) > settings.max_received_bytes - received:
                    raise ProtocolError("Socket returned bytes outside the requested receive bound")
                chunks.append(chunk)
                received += len(chunk)
                evidence["received_chunks_hex"].append(chunk.hex().upper())
                remaining()
                if not chunk:
                    raise ConnectionError(
                        "PCI disconnected before the routed WRITE outcome was confirmed; write outcome is uncertain"
                    )
                for kind, raw in stream.feed(chunk):
                    if len(events) >= settings.max_events:
                        raise ProtocolError("Routed WRITE event limit reached; write outcome is uncertain")
                    if kind == "confirmation":
                        matched = raw[:1] == code
                        event = RoutedWriteEvent(kind, raw, matched, chr(raw[1]))
                        events.append(event)
                        evidence["events"].append(event.as_dict())
                        if matched:
                            if confirmed:
                                raise ProtocolError("Multiple matching confirmations in the received prefix")
                            if raw[1:] != b".":
                                raise PCIRejected("PCI did not positively confirm the routed WRITE")
                            confirmed = True
                            evidence["confirmation_received"] = True
                    else:
                        frame = inspect_received_cal_route(raw)
                        matched = acknowledgement_matches(
                            frame, expected, command.cal.parameter, expected_ack_tag
                        )
                        event = RoutedWriteEvent("frame", raw, matched, frame=frame)
                        events.append(event)
                        evidence["events"].append(event.as_dict())
                        if matched:
                            if acknowledgement is not None:
                                raise ProtocolError("Multiple matching acknowledgements in the received prefix")
                            acknowledgement = frame
                            evidence["acknowledgement_received"] = True
                if confirmed and acknowledgement is not None and stream.buffer:
                    raise ProtocolError("Incomplete trailing bytes in the final received chunk")
            result = RoutedWriteResult(
                command,
                expected,
                expected_ack_tag,
                sent,
                code,
                acknowledgement,
                tuple(events),
                tuple(chunks),
            )
        except BaseException as error:
            first, traceback = error, error.__traceback__
        finally:
            if sock is not None:
                evidence["close_attempted"] = True
                try:
                    sock.close()
                    evidence["close_completed"] = True
                except BaseException as error:
                    if first is None:
                        first, traceback = error, error.__traceback__
                        evidence["stage"] = "close"
                    else:
                        evidence["cleanup_errors"].append(_error(error))
            try:
                evidence["pending_fragment_hex"] = bytes(stream.buffer).hex().upper()
                if first is None:
                    evidence["complete"] = True
                    evidence["stage"] = "complete"
                else:
                    evidence["error"] = _error(first)
                    evidence["write_outcome_uncertain"] = bool(evidence["send_attempted"])
                remembered = self._remember(first, evidence)
                if first is None and remembered is not None:
                    first, traceback = remembered, remembered.__traceback__
            except BaseException as evidence_error:
                if first is None:
                    first, traceback = evidence_error, evidence_error.__traceback__
                self.last_error = first
                self.last_evidence = {
                    "format": "cbus-routed-write-evidence-v1",
                    "complete": False,
                    "evidence_export_failed": True,
                    "error_type": type(first).__name__,
                }
            finally:
                self._lock.release()
        if first is not None:
            raise BaseException.with_traceback(first, traceback)
        return result


# --- Exclusive journal, generation binding and read-only recovery. ---
#
# A routed WRITE mutates far-side state, so a typed or journaled attempt
# records its exact generation before any send. The journal is exclusively
# created (O_EXCL, 0o600) and fsynced, then atomically replaced with fsync;
# every replacement first proves the file still holds this writer's previous
# bytes. The envelope always records ``send_may_have_occurred=true`` and
# ``read_only_recovery_only=true`` from creation, because a crash at any
# later instant can leave the record as the only evidence. Nothing here
# authorizes a replay: a second send with the same journal is refused and
# recovery only reads.

ROUTED_WRITE_JOURNAL_FORMAT = "cbus-routed-write-journal-v1"
ROUTED_WRITE_JOURNAL_OPERATION = "routed-write"
ROUTED_WRITE_GENERATION_FORMAT = "cbus-routed-write-generation-v1"
MAX_ROUTED_WRITE_JOURNAL_BYTES = 65536

_JOURNAL_REQUIRED_KEYS = frozenset({
    "format", "operation", "attempt_id", "generation", "route_plan",
    "send_may_have_occurred", "read_only_recovery_only", "complete", "stage",
    "resubmitted",
})
_JOURNAL_ALLOWED_KEYS = _JOURNAL_REQUIRED_KEYS | frozenset({"evidence"})
_GENERATION_REQUIRED_KEYS = frozenset({
    "format", "unit", "parameter", "data_hex", "bridges", "expected",
    "expected_ack_tag", "project_sha256",
})
_GENERATION_ALLOWED_KEYS = _GENERATION_REQUIRED_KEYS | frozenset({"route_plan"})


class RoutedWriteJournalError(ValueError):
    """The journal is missing, malformed, or refuses the requested write."""


class RoutedWriteUncertain(RuntimeError):
    """An attempt was recorded or is otherwise uncertain; do not replay."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate journal key: {key!r}")
        result[key] = value
    return result


def _journal_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _journal_canonical(value) -> bytes:
    return _journal_json(value).encode("utf-8")


def _resolve_journal_path(path: Path) -> Path:
    if not isinstance(path, Path):
        raise TypeError("journal path must be a pathlib.Path")
    if path.name in ("", ".", ".."):
        raise ValueError("journal path must name a file")
    try:
        directory = path.parent.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"journal parent cannot be resolved: {error}") from error
    if not directory.is_dir():
        raise ValueError(f"journal parent is not a directory: {directory}")
    return directory / path.name


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_journal_bytes(path: Path) -> bytes:
    resolved = _resolve_journal_path(path)
    descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    handle = None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RoutedWriteJournalError("recovery journal is not a regular file")
        handle = os.fdopen(descriptor, "rb")
        raw = handle.read(MAX_ROUTED_WRITE_JOURNAL_BYTES + 1)
        if len(raw) > MAX_ROUTED_WRITE_JOURNAL_BYTES:
            raise RoutedWriteJournalError("recovery journal exceeds its size bound")
    except BaseException:
        try:
            if handle is None:
                os.close(descriptor)
            else:
                handle.close()
        except BaseException:
            pass
        raise
    else:
        handle.close()
        return raw


def _parse_journal(raw: bytes) -> dict:
    if type(raw) is not bytes:
        raise TypeError("journal payload must be bytes")
    if len(raw) > MAX_ROUTED_WRITE_JOURNAL_BYTES:
        raise RoutedWriteJournalError("recovery journal exceeds its size bound")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, ValueError) as error:
        raise RoutedWriteJournalError(f"recovery journal is not canonical JSON: {error}") from error
    if type(value) is not dict:
        raise RoutedWriteJournalError("recovery journal must be a JSON object")
    return value


def _check_generation(generation) -> dict:
    if type(generation) is not dict:
        raise RoutedWriteJournalError("generation must be a JSON object")
    if set(generation) - _GENERATION_ALLOWED_KEYS or not _GENERATION_REQUIRED_KEYS <= set(generation):
        raise RoutedWriteJournalError("generation fields are unsupported or incomplete")
    if generation["format"] != ROUTED_WRITE_GENERATION_FORMAT:
        raise RoutedWriteJournalError("unsupported generation format")
    if type(generation["unit"]) is not int or not 0 <= generation["unit"] <= 255:
        raise RoutedWriteJournalError("generation unit must be an integer in 0..255")
    if type(generation["parameter"]) is not int or not 0 <= generation["parameter"] <= 255:
        raise RoutedWriteJournalError("generation parameter must be an integer in 0..255")
    if type(generation["data_hex"]) is not str or len(generation["data_hex"]) > 60 or len(generation["data_hex"]) % 2:
        raise RoutedWriteJournalError("generation data_hex must be 0..30 hexadecimal bytes")
    try:
        bytes.fromhex(generation["data_hex"])
    except ValueError as error:
        raise RoutedWriteJournalError(f"generation data_hex is not hex: {error}") from error
    if generation["data_hex"] != generation["data_hex"].upper():
        raise RoutedWriteJournalError("generation data_hex must be uppercase")
    bridges = generation["bridges"]
    if type(bridges) is not list or len(bridges) > 6 or any(type(v) is not int or not 0 <= v <= 255 for v in bridges):
        raise RoutedWriteJournalError("generation bridges must be a list of at most six bytes")
    expected = generation["expected"]
    if type(expected) is not dict or set(expected) != {"outer_source_byte", "destination_byte", "route_entries"}:
        raise RoutedWriteJournalError("generation expected path fields are invalid")
    for key in ("outer_source_byte", "destination_byte"):
        if type(expected[key]) is not int or not 0 <= expected[key] <= 255:
            raise RoutedWriteJournalError("generation expected bytes must be in 0..255")
    route_entries = expected["route_entries"]
    if type(route_entries) is not list or len(route_entries) > 6 or any(
            type(v) is not int or not 0 <= v <= 255 for v in route_entries):
        raise RoutedWriteJournalError("generation route entries must be a list of at most six bytes")
    terminal = route_entries[-1] if route_entries else expected["outer_source_byte"]
    if terminal != generation["unit"]:
        raise RoutedWriteJournalError("generation terminal path byte must equal the requested unit")
    if type(generation["expected_ack_tag"]) is not int or not 0 <= generation["expected_ack_tag"] <= 255:
        raise RoutedWriteJournalError("generation expected_ack_tag must be an integer in 0..255")
    digest = generation["project_sha256"]
    if digest is not None and (type(digest) is not str or len(digest) != 64
                               or any(c not in "0123456789abcdef" for c in digest)):
        raise RoutedWriteJournalError("generation project_sha256 must be 64 lowercase hex or null")
    route_plan = generation.get("route_plan")
    if route_plan is not None and type(route_plan) is not dict:
        raise RoutedWriteJournalError("generation route_plan must be an object or null")
    return generation


def routed_write_generation(command, expected, expected_ack_tag, *,
                            project_sha256=None, route_plan=None) -> dict:
    """Bind one exact WRITE attempt to its wire identity and topology generation.

    The returned dict is the journal's generation: unit, parameter, uppercase
    data, outgoing bridges, independent expected ACK path and tag, plus the
    bound project digest and optional route plan. No I/O occurs.
    """
    if type(command) is not RoutedCALCommand or type(command.cal) is not WriteCAL:
        raise ValueError("Only an exact RoutedCALCommand containing WriteCAL is supported")
    if type(command.addressing) is not str or command.addressing != "direct":
        raise ValueError("Routed WRITE generation requires explicit direct addressing")
    if type(expected) is not RoutedReplyPath:
        raise ValueError("expected must be an exact RoutedReplyPath")
    expected_ack_tag = _integer(expected_ack_tag, "expected_ack_tag", 0, 255)
    if project_sha256 is not None and (
            type(project_sha256) is not str or len(project_sha256) != 64
            or any(c not in "0123456789abcdef" for c in project_sha256)):
        raise ValueError("project_sha256 must be 64 lowercase hexadecimal characters or None")
    if route_plan is not None and type(route_plan) is not dict:
        raise ValueError("route_plan must be a route-plan dict or None")
    if route_plan is not None:
        if project_sha256 is None:
            raise ValueError("A bound route plan requires its project_sha256")
        if route_plan.get("format") != "cbus-commissioning-route-plan-v1":
            raise ValueError("route_plan must be a commissioning-route plan dict")
        if route_plan.get("project_sha256") != project_sha256:
            raise ValueError("route_plan digest does not match the bound project_sha256")
        if list(route_plan.get("bridges", [])) != list(command.bridges):
            raise ValueError("route_plan bridges do not match the WRITE command")
        plan_expected = route_plan.get("expected_ack_path", route_plan.get("expected_reply_path"))
        if plan_expected != expected.as_dict():
            raise ValueError("route_plan expected path does not match the WRITE expectation")
    canonical_expected = RoutedReplyPath(
        expected.outer_source_byte, expected.destination_byte, expected.route_entries)
    terminal = (canonical_expected.route_entries[-1] if canonical_expected.route_entries
                else canonical_expected.outer_source_byte)
    if terminal != command.unit:
        raise ValueError("Final declared ACK path byte must equal the requested unit")
    generation = {
        "format": ROUTED_WRITE_GENERATION_FORMAT,
        "unit": command.unit,
        "parameter": command.cal.parameter,
        "data_hex": bytes(command.cal.data).hex().upper(),
        "bridges": list(command.bridges),
        "expected": canonical_expected.as_dict(),
        "expected_ack_tag": expected_ack_tag,
        "project_sha256": project_sha256,
        "route_plan": None if route_plan is None else json.loads(json.dumps(route_plan)),
    }
    _check_generation(generation)
    return generation


def routed_write_attempt_id(generation) -> str:
    """Return the stable ``sha256:`` handle for one validated generation."""
    _check_generation(generation)
    return "sha256:" + hashlib.sha256(_journal_canonical(generation)).hexdigest()


def _check_journal_document(value) -> dict:
    if type(value) is not dict:
        raise RoutedWriteJournalError("recovery journal must be a JSON object")
    if set(value) - _JOURNAL_ALLOWED_KEYS or not _JOURNAL_REQUIRED_KEYS <= set(value):
        raise RoutedWriteJournalError("journal fields are unsupported or incomplete")
    if value["format"] != ROUTED_WRITE_JOURNAL_FORMAT:
        raise RoutedWriteJournalError("unsupported recovery journal format")
    if value["operation"] != ROUTED_WRITE_JOURNAL_OPERATION:
        raise RoutedWriteJournalError("unsupported recovery journal operation")
    _check_generation(value["generation"])
    route_plan = value["route_plan"]
    if route_plan is not None and type(route_plan) is not dict:
        raise RoutedWriteJournalError("journal route_plan must be an object or null")
    if route_plan != value["generation"].get("route_plan"):
        raise RoutedWriteJournalError("journal route_plan does not match its generation")
    if value["attempt_id"] != routed_write_attempt_id(value["generation"]):
        raise RoutedWriteJournalError("journal attempt_id does not match its generation")
    if value["send_may_have_occurred"] is not True or value["read_only_recovery_only"] is not True:
        raise RoutedWriteJournalError("journal envelope must record a possible send with read-only recovery")
    if type(value["complete"]) is not bool or type(value["stage"]) is not str or not value["stage"]:
        raise RoutedWriteJournalError("journal completion fields are invalid")
    if value["resubmitted"] is not False:
        raise RoutedWriteJournalError("journal must never record a resubmission")
    if "evidence" in value and type(value["evidence"]) is not dict:
        raise RoutedWriteJournalError("journal evidence must be an object")
    return value


def create_routed_write_journal(journal_path: Path, generation) -> bytes:
    """Exclusively create one journal bound to ``generation`` before any send.

    Refuses with ``FileExistsError`` when the path already exists, without
    opening an endpoint: the existing record authorizes only read-only
    recovery. Returns the exact bytes written for later handoff comparison.
    """
    _check_generation(generation)
    resolved = _resolve_journal_path(journal_path)
    attempt_id = routed_write_attempt_id(generation)
    document = {
        "format": ROUTED_WRITE_JOURNAL_FORMAT,
        "operation": ROUTED_WRITE_JOURNAL_OPERATION,
        "attempt_id": attempt_id,
        "generation": json.loads(_journal_json(generation)),
        "route_plan": generation.get("route_plan"),
        "send_may_have_occurred": True,
        "read_only_recovery_only": True,
        "complete": False,
        "stage": "planned",
        "resubmitted": False,
    }
    _check_journal_document(document)
    raw = (_journal_json(document) + "\n").encode("utf-8")
    if len(raw) > MAX_ROUTED_WRITE_JOURNAL_BYTES:
        raise RoutedWriteJournalError("journal generation exceeds its size bound")
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise RoutedWriteUncertain(
            f"journal already exists at {resolved}; read-only recovery only") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(resolved)
        except BaseException:
            pass
        raise
    try:
        _sync_directory(resolved.parent)
    except BaseException:
        # The record may already be visible; the caller must treat the
        # outcome as uncertain and recover read-only.
        raise
    current = _read_journal_bytes(resolved)
    if current != raw:
        raise RoutedWriteJournalError("journal changed during creation")
    return raw


def update_routed_write_journal(journal_path: Path, expected_raw: bytes, document) -> bytes:
    """Atomically replace one journal after proving the previous bytes.

    ``expected_raw`` must be the exact bytes this writer last wrote or read.
    Any difference refuses without touching the file. Returns the new bytes.
    """
    if type(expected_raw) is not bytes:
        raise TypeError("expected journal bytes must be bytes")
    _check_journal_document(document)
    resolved = _resolve_journal_path(journal_path)
    current = _read_journal_bytes(resolved)
    if current != expected_raw:
        raise RoutedWriteJournalError("journal changed outside this exclusive writer")
    raw = (_journal_json(document) + "\n").encode("utf-8")
    if len(raw) > MAX_ROUTED_WRITE_JOURNAL_BYTES:
        raise RoutedWriteJournalError("journal update exceeds its size bound")
    descriptor, temporary_path = tempfile.mkstemp(prefix="." + resolved.name + ".", dir=str(resolved.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, str(resolved))
        _sync_directory(resolved.parent)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except BaseException:
            pass
        raise
    current = _read_journal_bytes(resolved)
    if current != raw:
        raise RoutedWriteJournalError("journal changed during replacement")
    return raw


def load_routed_write_recovery(journal_path: Path) -> dict:
    """Load one journal read-only; never opens an endpoint or authorizes replay.

    Returns a deep copy of the validated journal document. Any oversize,
    non-regular, tampered or generation-unbound record refuses. Historical
    outcome fields are not trusted as fresh device state; callers must obtain
    a new observation for verification.
    """
    raw = _read_journal_bytes(journal_path)
    value = _parse_journal(raw)
    _check_journal_document(value)
    return json.loads(_journal_json(value))
