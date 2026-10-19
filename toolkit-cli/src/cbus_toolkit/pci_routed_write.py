"""One-shot WRITE with explicit ACK and route expectations.

The caller supplies literal outgoing and incoming route bytes plus the expected
ACK tag.  This module never resolves a logical network, retries a mutation, or
turns an ACK into a claim about nonvolatile device state.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import math
import socket
import threading
import time

from .pci import AcknowledgeCAL, PCIRejected, ProtocolError, RecallCAL, WriteCAL
from .pci_routing import RoutedCALCommand, ReceivedCALRoute, inspect_received_cal_route
from .pci_routed_recall import (
    RoutedRecallClient, RoutedReplyPath, _Stream, _path, _integer, _copy, _error,
)
from . import pci_routed_write_journal as journal_module


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

    def exchange(self, command, *, expected, expected_ack_tag, before_send=None):
        """Run the one-shot exchange.

        ``before_send``, when given, is called after connect and immediately
        before the WRITE bytes are handed to the socket. If it raises, nothing
        is sent and the error propagates with ``send_attempted=false``.
        """
        if before_send is not None and not callable(before_send):
            raise ValueError("before_send must be callable")
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
            if before_send is not None:
                evidence["stage"] = "handoff_check"
                evidence["handoff_check_passed"] = False
                before_send()
                evidence["handoff_check_passed"] = True
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


class RoutedWriteRefused(RuntimeError):
    """A journaled WRITE was refused before any WRITE byte reached the socket."""


class RoutedWriteUncertain(RuntimeError):
    """A journaled WRITE was sent and its outcome is not established."""


def recovery_contract(command, expected_ack_tag):
    """Return the read-only RECALL range that can observe this WRITE.

    Owned model, matching the original ACK matcher (the ACK tag is the first
    WRITE byte after the parameter) and the Rust simulator fixture: the first
    data byte is the tag and the remaining bytes are the parameter values a
    RECALL of ``parameter`` returns. This is not a device programming method.
    """
    data = command.cal.data
    if len(data) < 2:
        raise ValueError(
            "A journaled routed WRITE needs the tag byte plus 1..29 parameter bytes "
            "so recovery can RECALL them"
        )
    if data[0] != expected_ack_tag:
        raise ValueError("A journaled routed WRITE's first data byte must equal the expected ACK tag")
    return command.cal.parameter, len(data) - 1, bytes(data[1:])


def _probe(generation_probe):
    if generation_probe is None:
        return None
    value = generation_probe()
    if type(value) is not int:
        raise ValueError("PCI generation probe must return an integer")
    return value


def _recall(factory, *, host, port, timeout, command_checksum, max_events, max_received_bytes,
            unit, parameter, count, bridges, expected):
    client = factory(host, port, timeout=timeout, command_checksum=command_checksum,
                     max_events=max_events, max_received_bytes=max_received_bytes)
    command = RoutedCALCommand(unit, RecallCAL(parameter, count), bridges=tuple(bridges),
                               addressing="direct")
    try:
        result = client.exchange(command, expected=expected)
    except Exception as error:
        return None, client.last_evidence, error
    return result, client.last_evidence, None


def journal_summary(attempt):
    """Compact JSON view of one journal's current state."""
    document = None if attempt is None else attempt.document
    if document is None:
        return {"path": None if attempt is None else str(attempt.path), "created": False}
    return {
        "path": str(attempt.path),
        "created": True,
        "attempt_id": document["attempt_id"],
        "phase": document["phase"],
        "complete": document["complete"],
        "resolved": document["resolved"],
        "recovery_required": not (document["complete"] or document["resolved"]),
        "topology_sha256": document["plan"]["topology_sha256"],
        "project_sha256": document["plan"]["project_sha256"],
        "pci_generation": document["plan"]["pci_generation"],
        "pci_generation_source": document["plan"]["pci_generation_source"],
        "baseline_hex": document["plan"]["recovery_read"]["baseline_hex"],
    }


def journaled_write(command, *, expected, expected_ack_tag, journal, host, port=10001,
                    timeout=5.0, command_checksum=False, max_events=256,
                    max_received_bytes=32768, project_sha256=None, route_plan=None,
                    handoff_check=None, generation_probe=None,
                    write_client_factory=None, recall_client_factory=None, observer=None):
    """Baseline RECALL, exclusive fsynced journal, then one routed WRITE.

    Order: refuse an existing path or an unresolved same-target journal; read
    the PCI generation; perform one read-only baseline RECALL of the recovery
    range; rerun ``handoff_check`` and the generation probe; exclusively create
    and fsync the journal; connect; immediately before the send rerun both
    checks again (any change refuses with nothing sent); send once; re-probe
    the generation. A changed generation after send, or any post-send fault,
    is ``uncertain`` and leaves the journal unresolved for ``recover_write``.
    Nothing is retried.
    """
    write_client_factory = write_client_factory or RoutedWriteClient
    recall_client_factory = recall_client_factory or RoutedRecallClient
    if observer is None:
        observer = {}
    canonical_command, expected, expected_ack_tag = RoutedWriteClient._preflight(
        command, expected, expected_ack_tag)
    parameter, count, written = recovery_contract(canonical_command, expected_ack_tag)
    if (route_plan is None) != (project_sha256 is None):
        raise ValueError("project_sha256 and route_plan must be supplied together")
    if handoff_check is not None and not callable(handoff_check):
        raise ValueError("handoff_check must be callable")
    if generation_probe is not None and not callable(generation_probe):
        raise ValueError("generation_probe must be callable")
    settings = write_client_factory(host, port, timeout=timeout, command_checksum=command_checksum,
                                    max_events=max_events, max_received_bytes=max_received_bytes)
    observer["write_client"] = settings
    journal_module.refuse_unresolved(journal, journal_module.target_key({
        "endpoint": {"host": settings.host, "port": settings.port},
        "bridges": list(canonical_command.bridges),
        "unit": canonical_command.unit,
    }))
    generation = _probe(generation_probe)
    baseline, baseline_evidence, baseline_error = _recall(
        recall_client_factory, host=settings.host, port=settings.port, timeout=settings.timeout,
        command_checksum=settings.command_checksum, max_events=settings.max_events,
        max_received_bytes=settings.max_received_bytes, unit=canonical_command.unit,
        parameter=parameter, count=count, bridges=canonical_command.bridges, expected=expected)
    observer["baseline_evidence"] = baseline_evidence
    if baseline_error is not None:
        raise RoutedWriteRefused(
            f"Baseline RECALL failed ({type(baseline_error).__name__}: {baseline_error}); "
            "no journal was created and no WRITE was sent") from baseline_error
    if handoff_check is not None:
        handoff_check()
    if _probe(generation_probe) != generation:
        raise RoutedWriteRefused(
            "PCI generation changed during the baseline RECALL; no journal was created and no WRITE was sent")
    expected_dict = expected.as_dict()
    mode = "raw" if route_plan is None else "typed"
    plan = {
        "endpoint": {"host": settings.host, "port": settings.port},
        "command_checksum": settings.command_checksum,
        "unit": canonical_command.unit,
        "parameter": parameter,
        "data_hex": canonical_command.cal.data.hex().upper(),
        "expected_ack_tag": expected_ack_tag,
        "bridges": list(canonical_command.bridges),
        "expected": expected_dict,
        "mode": mode,
        "project_sha256": project_sha256,
        "route_plan": None if route_plan is None else _copy(route_plan),
        "topology_sha256": journal_module.topology_sha256(
            mode=mode, bridges=canonical_command.bridges, expected=expected_dict,
            project_sha256=project_sha256, route_plan=route_plan),
        "pci_generation": generation,
        "pci_generation_source": "unavailable" if generation_probe is None else "caller-probe",
        "recovery_read": {
            "parameter": parameter,
            "count": count,
            "expected_hex": written.hex().upper(),
            "baseline_hex": baseline.data.hex().upper(),
        },
    }
    attempt = journal_module.RoutedWriteJournal.create(journal, plan)
    observer["journal"] = attempt

    def before_send():
        if handoff_check is not None:
            try:
                handoff_check()
            except Exception as error:
                raise RoutedWriteRefused(
                    f"Topology changed at handoff ({error}); no WRITE was sent") from error
        if _probe(generation_probe) != generation:
            raise RoutedWriteRefused("PCI generation changed at handoff; no WRITE was sent")

    client = write_client_factory(settings.host, settings.port, timeout=settings.timeout,
                                  command_checksum=settings.command_checksum,
                                  max_events=settings.max_events,
                                  max_received_bytes=settings.max_received_bytes)
    observer["write_client"] = client
    try:
        receipt = client.exchange(canonical_command, expected=expected,
                                  expected_ack_tag=expected_ack_tag, before_send=before_send)
    except BaseException as error:
        evidence = client.last_evidence if type(client.last_evidence) is dict else {}
        # Only an explicit false proves no WRITE byte reached the socket.
        sent = evidence.get("send_attempted") is not False
        record = {"send_attempted": sent, "error": _error(error),
                  "handoff_check_passed": evidence.get("handoff_check_passed")}
        try:
            if sent:
                attempt.advance("uncertain", lambda doc: doc.update(send=record))
            else:
                def not_sent(doc):
                    doc.update(send=record, complete=True, resolved=True,
                               resolution={"by": "writer", "outcome": "not-sent",
                                           "at": journal_module.now()})
                attempt.advance("not-sent", not_sent)
        except BaseException as journal_error:
            observer["journal_update_error"] = _error(journal_error)
        raise
    observer["receipt"] = receipt
    record = {"send_attempted": True, "confirmation_received": True,
              "acknowledgement_received": True, "sent_hex": receipt.sent.hex().upper(),
              "generation_changed_after_send": False}
    try:
        changed = _probe(generation_probe) != generation
    except Exception as error:
        record["generation_probe_error"] = _error(error)
        changed = True
    if changed:
        record["generation_changed_after_send"] = True
        try:
            attempt.advance("uncertain", lambda doc: doc.update(send=record))
        except BaseException as journal_error:
            observer["journal_update_error"] = _error(journal_error)
        raise RoutedWriteUncertain(
            "PCI generation changed after the routed WRITE was sent; the acknowledgement is "
            "not accepted and the outcome is uncertain. Run recovery; nothing was retried")

    def finished(doc):
        doc.update(send=record, complete=True, resolved=True,
                   resolution={"by": "writer", "outcome": "acknowledged", "at": journal_module.now()})

    try:
        attempt.advance("acknowledged", finished)
    except BaseException as journal_error:
        observer["journal_update_error"] = _error(journal_error)
        raise RoutedWriteUncertain(
            "The routed WRITE was acknowledged but its journal could not be finalized; "
            "run recovery before another WRITE. Nothing was retried") from journal_error
    return receipt, attempt


def recover_write(journal, *, host, port, timeout=5.0, max_events=256, max_received_bytes=32768,
                  route_check=None, generation_probe=None, recall_client_factory=None):
    """Classify a journaled attempt by one fresh read-only routed RECALL.

    This never constructs a WRITE client or sends a WRITE. The journal is
    marked resolved only for ``expected`` or ``unchanged``; ``mixed`` and
    ``unreadable`` leave it unresolved so a later same-target WRITE stays
    refused. A matching readback does not establish which writer caused it,
    persistence or a physical effect.
    """
    recall_client_factory = recall_client_factory or RoutedRecallClient
    attempt = journal_module.RoutedWriteJournal.open(journal)
    document = attempt.document
    plan = document["plan"]
    requested = RoutedRecallClient(host, port)
    if (requested.host, requested.port) != (plan["endpoint"]["host"], plan["endpoint"]["port"]):
        raise ValueError("Recovery endpoint differs from the journaled endpoint; no PCI I/O was attempted")
    if route_check is not None:
        route_check(plan)
    read = plan["recovery_read"]
    report = {
        "format": "cbus-pci-routed-write-recovery-v1",
        "journal": str(attempt.path),
        "journal_sha256": hashlib.sha256(attempt.raw).hexdigest(),
        "attempt_id": document["attempt_id"],
        "journal_phase": document["phase"],
        "journal_resolved_before": document["resolved"],
        "mode": plan["mode"],
        "project_sha256": plan["project_sha256"],
        "topology_sha256": plan["topology_sha256"],
        "topology_rechecked": route_check is not None,
        "recorded_pci_generation": plan["pci_generation"],
        "fresh_pci_generation": None,
        "pci_generation_changed": None,
        "read": {"parameter": read["parameter"], "count": read["count"]},
        "expected_hex": read["expected_hex"],
        "baseline_hex": read["baseline_hex"],
        "fresh_hex": None,
        "classification": "unreadable",
        "conclusive": False,
        "read_only": True,
        "writes_attempted": False,
        "write_resubmitted": False,
        "automatic_retries": 0,
        "attempt_replay_authorized": False,
        "indistinguishable_from_unchanged": read["expected_hex"] == read["baseline_hex"],
        "writer_identity_verified": False,
        "physical_delivery_verified": False,
        "nonvolatile_persistence_verified": False,
        "original_cached_object_correlation_verified": False,
    }
    errors = []
    try:
        fresh_generation = _probe(generation_probe)
        report["fresh_pci_generation"] = fresh_generation
        if generation_probe is not None:
            report["pci_generation_changed"] = fresh_generation != plan["pci_generation"]
    except Exception as error:
        errors.append({"phase": "generation", **_error(error)})
    expected = RoutedReplyPath(plan["expected"]["outer_source_byte"],
                               plan["expected"]["destination_byte"],
                               tuple(plan["expected"]["route_entries"]))
    result, evidence, error = _recall(
        recall_client_factory, host=plan["endpoint"]["host"], port=plan["endpoint"]["port"],
        timeout=timeout, command_checksum=plan["command_checksum"], max_events=max_events,
        max_received_bytes=max_received_bytes, unit=plan["unit"], parameter=read["parameter"],
        count=read["count"], bridges=plan["bridges"], expected=expected)
    report["recall_evidence"] = evidence
    if error is not None:
        errors.append({"phase": "recall", **_error(error)})
    else:
        fresh = result.data.hex().upper()
        report["fresh_hex"] = fresh
        if fresh == read["expected_hex"]:
            report["classification"] = "expected"
        elif fresh == read["baseline_hex"]:
            report["classification"] = "unchanged"
        else:
            report["classification"] = "mixed"
        report["conclusive"] = True
    report["errors"] = errors
    resolves = report["classification"] in ("expected", "unchanged")
    record = {
        "at": journal_module.now(),
        "classification": report["classification"],
        "fresh_hex": report["fresh_hex"],
        "fresh_pci_generation": report["fresh_pci_generation"],
        "errors": errors,
    }

    def mutate(updated):
        updated["recoveries"].append(record)
        if resolves and not updated["resolved"]:
            updated["resolved"] = True
            updated["resolution"] = {"by": "recover", "outcome": report["classification"],
                                     "at": record["at"]}

    try:
        attempt.advance(None, mutate)
        report["journal_updated"] = True
    except BaseException as journal_error:
        report["journal_updated"] = False
        report["journal_update_error"] = _error(journal_error)
    report["resolved"] = attempt.document["resolved"]
    report["resolution"] = attempt.document["resolution"]
    return report
