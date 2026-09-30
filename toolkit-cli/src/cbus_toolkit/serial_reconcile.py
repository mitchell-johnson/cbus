"""Reconcile one verified selected-serial move with the project database.

Admitted physical evidence is a complete ``serial-address apply`` journal, or
a separate direct read-only verification handoff bound to an immutable apply
journal and marker. Its independently reparsed after-inventory must equal the
plan's exact expected identity map.
The database unit carrying that serial is then moved from the journal's source
address to its destination with its OID, metadata, programming and OID
references preserved. No PCI, CNI or C-Bus network I/O is performed.

Progress is kept in a separate reconciliation record beside the journal. It is
created exclusively and advanced through ``physical_done`` -> ``db_pending`` ->
``db_done``. A rerun after ``db_done`` is a read-only no-op; a rerun after
``db_pending`` re-reads the database. A loaded C-Gate project must be reopened
to prove the saved image; repeating its database-only move requires explicit
authorization after saved-original readback. No physical request is replayed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID, uuid4

from .pci_selected_serial import (
    ATTEMPT_FORMAT, ATTEMPT_SCOPES, VERIFICATION_FORMAT, MAX_JOURNAL_BYTES, SelectedSerialCoordinator, SelectedSerialPlan, _Journal,
    _canonical_fingerprint, _hex, _inventory_proof, _json, _keys, _options_proof, _raw_serials, _unique_pairs,
    recovery_binding,
)
from .commissioning_route import resolve_network_route
from .pci_serial_address import decode_serial_address_receipt
from .project import ProjectDocument, _address, _all_elements, _elements, _field, _is_entity, _name, _oid
from .serials import parse_native_serial


RECORD_FORMAT = "cbus-serial-reconcile-record-v1"
CGATE_RECORD_FORMAT = "cbus-serial-reconcile-record-v2"
RESULT_FORMAT = "cbus-serial-reconcile-result-v1"
PHASES = ("physical_done", "db_pending", "db_done")
MAX_RECORD_BYTES = MAX_JOURNAL_BYTES
_RECORD_KEYS = ("format", "phase", "journal", "move", "database", "unit", "before_sha256", "expected_sha256",
                "backup", "database_changed", "history", "last_error", "rollback_errors", "bus_io_performed")
# Fields whose exact values every completed selected-serial apply journal carries.
_FIXED = {"operation": "apply", "state": "after_observed", "outcome": "observed_expected_change",
          "attempt_recorded": True, "attempt_durability_verified": True, "transport_invoked": True,
          "send_attempted": True, "after_collection_complete": True, "expected_identity_change": True,
          "unexpected_changes": [], "errors": [], "atomic_observation": False,
          "firmware_persistence_verified": False, "physical_compatibility_verified": False,
          "exclusive_ownership_required": True, "automatic_retries": 0, "automatic_rollback": False,
          "database_updated": False, "deadline_scope": "transaction_after_validation_and_lock"}


class ReconcileError(RuntimeError):
    """Reconciliation refused or stopped; ``details`` names the durable state."""

    def __init__(self, message, **details):
        self.details = {"serial_reconcile": details} if details else {}
        super().__init__(message)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_bounded(path, limit):
    """Read one regular file without following a final symbolic link."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError(f"{path} is not a regular file")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{path} exceeds its size bound")
    return raw


def _parse(raw, name):
    try:
        text = raw.decode("utf-8")
        return json.loads(text, object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON value")))
    except (UnicodeDecodeError, ValueError) as error:
        raise ReconcileError(f"{name} is not strict UTF-8 JSON: {error}") from error


@dataclass(frozen=True)
class VerifiedMove:
    """A journal-proven physical move; every field was rederived from raw evidence."""
    journal_path: str
    journal_sha256: str
    attempt_id: str
    attempt_identity: str
    serial: str
    source: int
    destination: int
    endpoint: dict
    local_unit: int
    receipt_matches_request: bool
    route: tuple[int, ...] = ()
    project_sha256: str | None = None
    source_network: int | None = None
    target_network: int | None = None

    def as_dict(self):
        return {"path": self.journal_path, "sha256": self.journal_sha256, "attempt_id": self.attempt_id,
                "attempt_identity": self.attempt_identity, "outcome": "observed_expected_change",
                "receipt_matches_request": self.receipt_matches_request}

    def move(self):
        value = {"serial": self.serial, "source": self.source, "destination": self.destination,
                 "endpoint": dict(self.endpoint), "local_unit": self.local_unit}
        if self.route:
            value.update(route=list(self.route), project_sha256=self.project_sha256,
                         source_network=self.source_network, target_network=self.target_network)
        return value


def _routed_binding(value, plan):
    """Validate handoff evidence without following its recorded project path."""
    binding = value.get("route_binding")
    if not plan.get("route"):
        if binding is not None:
            raise ValueError("a direct journal cannot carry a route binding")
        return None
    _keys(binding, ("project_path", "project_sha256", "source_network", "target_network", "route",
                    "route_rederived", "physical_bridge_acceptance_verified", "topology_fresh_at_handoff"),
          "Routed journal binding")
    if not isinstance(binding["project_path"], str) or not Path(binding["project_path"]).is_absolute():
        raise ValueError("route binding project path is not absolute")
    for key in ("source_network", "target_network"):
        if type(binding[key]) is not int or not 0 <= binding[key] <= 255:
            raise ValueError("route binding network must be an integer in 0..255")
    if (binding["source_network"] == binding["target_network"] or
            binding["project_sha256"] != plan["project_sha256"] or
            _json(binding["route"]) != _json(plan["route"]) or
            binding["route_rederived"] is not True or binding["topology_fresh_at_handoff"] is not True or
            binding["physical_bridge_acceptance_verified"] is not False):
        raise ValueError("route binding differs from the completed routed handoff")
    return binding


def _receipt_proof(exchange, plan):
    """Reparse the whole retained receipt; a missing match is not movement proof."""
    raw = _hex(exchange.get("received_hex"), 4096)
    receipt = decode_serial_address_receipt(raw, serial=plan["serial"], destination=plan["destination"],
                                            local_unit=plan["local_unit"], bridges=plan.get("route", ()))
    expected = {"format": "cbus-pci-serial-address-exchange-v1", "send_completed": True,
                "bytes_received": len(raw), "retained_bytes": len(raw), "sent_byte_count": None,
                "receipt": receipt.as_dict(), "correlation_status": receipt.status,
                "retained_receipt_matches_request": receipt.matched,
                "termination": "response_window_elapsed", "automatic_retries": 0,
                "movement_verified": False, "persistence_verified": False,
                "requires_independent_verification": True, "inventory_performed": False,
                "database_updated": False, "request_has_source_address": False}
    if any(_json(exchange.get(key)) != _json(wanted) for key, wanted in expected.items()):
        raise ValueError("exchange receipt or summary differs from its raw evidence")
    if type(exchange.get("max_bytes")) is not int or not max(1, len(raw)) <= exchange["max_bytes"] <= 4096:
        raise ValueError("exchange byte bound is inconsistent")
    return receipt.matched


def verify_journal(path):
    """Admit only a complete, internally consistent ``observed_expected_change`` journal.

    Outcome fields in a journal are not authenticated, so this reparses every
    captured byte: the fresh before inventory must equal the plan's, the local
    PCI checks must hold, the exchange must be the plan's single clean request,
    and the after inventory must reparse to exactly the expected map. The
    attempt marker must still exist and embed the same plan; deleting it is the
    operator's replay authorization, which makes this journal stale.
    """
    path = Path(path)
    try:
        raw = _read_bounded(path, MAX_JOURNAL_BYTES)
    except (OSError, ValueError) as error:
        raise ReconcileError(f"Cannot read selected-serial journal: {error}") from error
    value = _parse(raw, "Selected-serial journal")
    if not isinstance(value, dict):
        raise ReconcileError("Selected-serial journal must be a JSON object")
    if value.get("format") == VERIFICATION_FORMAT:
        return _verified_handoff(path, raw, value)
    if value.get("format") == ATTEMPT_FORMAT:
        raise ReconcileError("An attempt marker records only an uncertain attempt; reconcile a completed apply journal")
    if value.get("format") == "cbus-selected-serial-apply-v2":
        from .rust_serial_reconcile import verify_rust_journal
        return verify_rust_journal(path, raw, value)
    if value.get("format") != "cbus-selected-serial-result-v1":
        raise ReconcileError("Unsupported selected-serial journal format")
    try:
        plan = SelectedSerialPlan.from_dict(value.get("plan")).as_dict()
    except (ValueError, TypeError, KeyError) as error:
        raise ReconcileError(f"Journal plan is invalid or tampered: {error}") from error
    validator = SelectedSerialCoordinator(**plan["endpoint"], local_unit=plan["local_unit"],
                                          expected_local_serial=plan["expected_local_serial"], **plan["settings"])
    expected = validator._base("apply")
    if "route_binding" not in value:
        expected.pop("route_binding")  # Journals written before routed execution.
    try:
        _keys(value, expected, "Recovery journal")
    except ValueError as error:
        raise ReconcileError(f"Journal fields are unsupported or incomplete (pre-marker journals are unbound): {error}") from error
    if value["operation"] != "apply":
        raise ReconcileError("Reconciliation requires an apply journal")
    if value["state"] != "after_observed":
        raise ReconcileError(f"Journal is in progress or interrupted (state {value['state']!r}); verify it read-only first")
    if value["outcome"] != "observed_expected_change":
        raise ReconcileError(f"Journal outcome {value['outcome']!r} is not observed_expected_change")
    for key, expected in _FIXED.items():
        if _json(value[key]) != _json(expected):
            raise ReconcileError(f"Journal field {key} is inconsistent with a completed expected change")
    if _json(value["plan"]) != _json(plan):
        raise ReconcileError("Journal plan is not in canonical validated form")
    checksum, local, endpoint = plan["settings"]["command_checksum"], plan["local_unit"], plan["endpoint"]
    try:
        binding = _routed_binding(value, plan)
        route = tuple(plan.get("route", ()))
        before = _inventory_proof(value["before"], endpoint, local, checksum, route)
        if before != _inventory_proof(plan["before"], endpoint, local, checksum, route):
            raise ValueError("fresh before inventory differs from the plan")
        address, serials = _raw_serials(value["local_identity"], local, checksum)
        if address != local or serials != [plan["expected_local_serial"]]:
            raise ValueError("local PCI identity differs from the plan")
        _options_proof(value["local_options"], local, checksum)
        exchange = value["exchange"]
        if not isinstance(exchange, dict) or not isinstance(exchange.get("receipt"), dict):
            raise ValueError("exchange evidence is missing")
        if (exchange.get("request_hex") != plan["request_hex"] or exchange.get("send_attempted") is not True or
                exchange.get("errors") != [] or exchange.get("capture_complete") is not True or
                exchange.get("connection_closed") is not True or exchange["receipt"].get("errors") != [] or
                exchange["receipt"].get("pending_hex")):
            raise ValueError("exchange is not the plan's single clean request")
        if value["receipt_matches_request"] is not _receipt_proof(exchange, plan):
            raise ValueError("receipt summary differs from its exchange")
        after = _inventory_proof(value["after"], endpoint, local, checksum, route)
        if after != plan["expected_after"]:
            raise ValueError("after inventory does not reparse to the expected identity map")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReconcileError(f"Journal evidence is tampered or inconsistent: {error}") from error
    recorded = value["journal"]
    if not isinstance(recorded, dict) or set(recorded) != {"path"} or not isinstance(recorded["path"], str):
        raise ReconcileError("Journal location record is malformed")
    marker = value["attempt_identity"]
    fingerprint = _canonical_fingerprint(plan)
    if not isinstance(marker, str) or Path(marker).name != f".cbus-selected-serial-attempt-sha256-{fingerprint}.json":
        raise ReconcileError("Journal attempt identity does not name its plan's marker")
    try:
        marker_raw = _read_bounded(marker, MAX_JOURNAL_BYTES)
    except FileNotFoundError as error:
        raise ReconcileError("Attempt marker is missing; its deletion authorizes a replay, so this journal is stale") from error
    except (OSError, ValueError) as error:
        raise ReconcileError(f"Cannot read the attempt marker: {error}") from error
    record = _parse(marker_raw, "Attempt marker")
    try:
        _keys(record, ("format", "operation", "attempt_id", "scope", "journal", "plan",
                       "send_may_have_occurred", "read_only_recovery_only"), "Attempt marker")
        if record["format"] != ATTEMPT_FORMAT or record["attempt_id"] != "sha256:" + fingerprint:
            raise ValueError("marker ID differs from the journal plan")
        if (record["operation"] != "apply" or record["send_may_have_occurred"] is not True or
                record["read_only_recovery_only"] is not True or record["scope"] not in ATTEMPT_SCOPES):
            raise ValueError("marker envelope does not describe a read-only recovery-only apply attempt")
        if _json(SelectedSerialPlan.from_dict(record["plan"]).as_dict()) != _json(plan):
            raise ValueError("marker embeds a different plan")
        # The marker stores the resolved journal path; the journal its absolute path.
        written = Path(recorded["path"])
        if record["journal"] not in (recorded["path"], str(written.parent.resolve() / written.name)):
            raise ValueError("marker names a different journal")
        scope = (ATTEMPT_SCOPES[0] if Path(marker).parent.resolve() == Path(record["journal"]).parent.resolve()
                 else ATTEMPT_SCOPES[1])
        if record["scope"] != scope:
            raise ValueError("marker scope does not match its journal directory")
    except (ValueError, TypeError) as error:
        raise ReconcileError(f"Attempt marker does not bind this journal (stale or tampered): {error}") from error
    return VerifiedMove(str(path.absolute()), hashlib.sha256(raw).hexdigest(), record["attempt_id"], marker,
                        plan["serial"], plan["source"], plan["destination"], dict(endpoint), local,
                        value["receipt_matches_request"], route, plan.get("project_sha256"),
                        binding["source_network"] if binding else None,
                        binding["target_network"] if binding else None)


def _verified_handoff(path, raw, value):
    """Reparse a fresh observation without inventing a successful apply receipt."""
    try:
        _keys(value, ("format", "original", "verification", "address_command_replayed",
                      "original_journal_modified"), "Verification handoff")
        if value["address_command_replayed"] is not False or value["original_journal_modified"] is not False:
            raise ValueError("handoff is not immutable read-only recovery")
        original = value["original"]
        if not isinstance(original, dict) or _json(recovery_binding(original["path"]), MAX_JOURNAL_BYTES) != _json(original, MAX_JOURNAL_BYTES):
            raise ValueError("original journal or marker differs from the fresh verification binding")
        plan = SelectedSerialPlan.from_dict(original["plan"]).as_dict()
        validator = SelectedSerialCoordinator(**plan["endpoint"], local_unit=plan["local_unit"],
            expected_local_serial=plan["expected_local_serial"], **plan["settings"])
        observed = value["verification"]
        expected = validator._base("verify", SelectedSerialPlan.from_dict(plan))
        _keys(observed, expected, "Fresh verification")
        binding = _routed_binding(observed, plan)
        expected.update(after=observed["after"], route_binding=observed["route_binding"], state="after_observed")
        validator._classify(expected, plan)
        if expected["outcome"] != "observed_expected_change" or _json(expected, MAX_JOURNAL_BYTES) != _json(observed, MAX_JOURNAL_BYTES):
            raise ValueError("fresh verification differs from the exact expected read-only inventory")
        route = tuple(plan.get("route", ()))
        if _inventory_proof(observed["after"], plan["endpoint"], plan["local_unit"], plan["settings"]["command_checksum"], route) != plan["expected_after"]:
            raise ValueError("fresh raw inventory differs from the expected identity map")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReconcileError(f"Verification handoff is stale, tampered or incomplete: {error}") from error
    return VerifiedMove(str(path.absolute()), hashlib.sha256(raw).hexdigest(), original["attempt_id"],
        original["attempt_identity"], plan["serial"], plan["source"], plan["destination"],
        dict(plan["endpoint"]), plan["local_unit"], False, route, plan.get("project_sha256"),
        binding["source_network"] if binding else None, binding["target_network"] if binding else None)


@dataclass(frozen=True)
class DatabaseUnit:
    network: int
    address: int
    unit_type: str
    firmware: str
    serial_text: str
    oid: str | None

    def as_dict(self):
        return {"network": self.network, "address": self.address, "unit_type": self.unit_type,
                "firmware": self.firmware, "serial_text": self.serial_text, "oid": self.oid}


def _units(document):
    """Every entity Unit of every Network, with raw serial text retained."""
    result = []
    for network in _elements(document.project, "Network"):
        if not _is_entity(network):
            continue
        number = _address(_field(network, "Address"))
        for unit in _elements(network, "Unit"):
            if _is_entity(unit):
                result.append(DatabaseUnit(number, _address(_field(unit, "Address")), _field(unit, "UnitType"),
                                           _field(unit, "FirmwareVersion"), _field(unit, "SerialNumber"), _oid(unit)))
    return result


def _canonical_serial(text):
    try:
        number = parse_native_serial(text)
    except ValueError:
        return None
    return number.canonical if number.known else None


def locate(document, move, *, network=None, unit_type=None, firmware=None):
    """Find the one database unit carrying the moved serial and classify its address."""
    units = _units(document)
    matches = [u for u in units if _canonical_serial(u.serial_text) == move.serial]
    if network is not None:
        matches = [u for u in matches if u.network == network]
    if not matches:
        raise ReconcileError(f"Serial {move.serial} is not recorded in the database"
                             + ("" if network is None else f" network {network}"))
    if len(matches) > 1:
        raise ReconcileError(f"Serial {move.serial} is ambiguous in the database",
                             candidates=[u.as_dict() for u in matches])
    unit = matches[0]
    try:
        UUID(unit.oid or "")
    except ValueError as error:
        raise ReconcileError("Matched database unit has no valid OID") from error
    if unit_type is not None and unit.unit_type != unit_type:
        raise ReconcileError(f"Matched database unit type {unit.unit_type!r} differs from {unit_type!r}")
    if firmware is not None and unit.firmware != firmware:
        raise ReconcileError(f"Matched database firmware {unit.firmware!r} differs from {firmware!r}")
    if unit.unit_type.upper().startswith(("BRIDGE", "WGATE")):
        raise ReconcileError("Bridge/wireless gateway readdress requires coupled topology changes")
    occupant = [u for u in units if u.network == unit.network and u.address == move.destination and u.oid != unit.oid]
    if occupant:
        raise ReconcileError(f"Destination {move.destination} is occupied in database network {unit.network}",
                             occupant=occupant[0].as_dict())
    if unit.address == move.source:
        position = "source"
    elif unit.address == move.destination:
        position = "destination"
    else:
        raise ReconcileError(f"Database records serial {move.serial} at {unit.address}, neither the journal source "
                             f"{move.source} nor destination {move.destination}; the journal or database is stale",
                             unit=unit.as_dict())
    return unit, position


class ProjectFileDatabase:
    """A legacy XML or CBZ project file, edited in memory and saved atomically."""

    def __init__(self, path):
        self.path = Path(path).absolute()
        self._routed_move = None

    def identity(self):
        return {"kind": "project_file", "path": str(self.path)}

    def snapshot(self):
        raw = _read_bounded(self.path, 128 * 1024 * 1024)
        return ProjectDocument.from_snapshot(raw, source=self.path), raw

    def _route(self, document):
        """Re-derive both sides of the edit from the same bound topology."""
        move = self._routed_move
        if move is None:
            return
        try:
            route = resolve_network_route(document, source_network=move.source_network,
                                          target_network=move.target_network)
        except ValueError as error:
            raise ReconcileError(f"Routed project topology is invalid: {error}") from error
        if route != move.route:
            raise ReconcileError("Routed project topology differs from the journal route")

    def _original(self, raw):
        if self._routed_move is not None and hashlib.sha256(raw).hexdigest() != self._routed_move.project_sha256:
            raise ReconcileError("Project changed or does not match the routed journal project_sha256")

    def bind_move(self, move, record, *, unit_type=None, firmware=None):
        """Pin a routed preimage, or recover its exact authorized candidate.

        The handoff's private project path is never followed. The caller's
        database must supply those original bytes, or its durable backup must
        do so after our atomic save necessarily changed the project hash.
        A record is not authority to accept an arbitrary expected digest: we
        reconstruct the candidate from the SHA-bound original on every run.
        """
        self._routed_move = move if move.route else None
        if not move.route:
            return
        current, current_raw = self.snapshot()
        original_raw = current_raw
        if record is not None and record.value["backup"] is not None:
            backup = record.value["backup"]
            if not isinstance(backup, str) or not Path(backup).is_absolute():
                raise ReconcileError("Routed reconciliation backup path is malformed")
            try:
                original_raw = _read_bounded(backup, 128 * 1024 * 1024)
            except (OSError, ValueError) as error:
                raise ReconcileError(f"Cannot read routed reconciliation backup: {error}") from error
        self._original(original_raw)
        original = ProjectDocument.from_snapshot(original_raw, source=self.path)
        self._route(original)
        unit, position = locate(original, move, network=move.target_network,
                                unit_type=unit_type, firmware=firmware)
        before = self.digest(original)
        evidence = self.candidate(original, unit, move.destination) if position == "source" else None
        expected = self.digest(original)
        if record is not None:
            wanted_unit = unit.as_dict() | {
                "source_path": evidence["source_path"] if evidence else None,
                "destination_path": evidence["destination_path"] if evidence else None}
            wanted = {"journal": move.as_dict(), "move": move.move(), "unit": wanted_unit,
                      "before_sha256": before if evidence else None,
                      "expected_sha256": expected if evidence else None, "bus_io_performed": False}
            if any(_json(record.value[key]) != _json(value) for key, value in wanted.items()):
                raise ReconcileError("Routed reconciliation record differs from the original bound project move")
            if record.value["phase"] == "db_done":
                # A completed record remains read-only, even if someone edits
                # the project later. current() reports that mismatch.
                return
        if hashlib.sha256(current_raw).hexdigest() != move.project_sha256:
            if (record is None or record.value["phase"] != "db_pending" or
                    record.value["backup"] is None or self.digest(current) != expected):
                raise ReconcileError("Project changed while routed reconciliation was pending; resolve manually")
            self._route(current)

    @staticmethod
    def digest(document):
        """Content digest: the XML payload plus every other archive member."""
        state = hashlib.sha256(document.to_xml_bytes())
        for info, data in sorted(document._members or (), key=lambda item: item[0].filename):
            if info.filename != document.xml_member:
                state.update(b"\0" + info.filename.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
        return state.hexdigest()

    @staticmethod
    def _paths(unit, address):
        return f"/network/{unit.network}/unit/{address}"

    def candidate(self, document, unit, destination):
        """Apply the one move in memory and return evidence of what was preserved."""
        source = self._paths(unit, unit.address)
        self._route(document)
        if self._routed_move is None:
            for node in _all_elements(document.project):
                if _name(node) == "InterfaceType" and "".join(
                        c.data for c in node.childNodes if c.nodeType == c.TEXT_NODE).strip().lower() == "bridge":
                    raise ReconcileError("Projects with bridge connections require coupled topology handling")
        text = document.raw_xml()
        if re.search(rf"/{unit.network}/p/{unit.address}(?![0-9])", text):
            raise ReconcileError("Project contains a textual unit-path reference requiring explicit reconciliation")
        parameters = document.parameters(source)
        stored = parameters.get("UnitAddress")
        try:
            if stored is None or int(stored, 0) != unit.address:
                raise ValueError
        except ValueError as error:
            raise ReconcileError("Stored PP UnitAddress is missing or differs from the database address") from error
        encoded = hex(destination) if stored.lower().startswith("0x") else str(destination)
        references = document._references({unit.oid})
        document.update(source, {"Address": str(destination)})
        target = self._paths(unit, destination)
        document.set_parameter(target, "UnitAddress", encoded)
        if _oid(document.resolve(target)) != unit.oid or document._references({unit.oid}) != references:
            raise ReconcileError("Moving the unit changed its OID or OID references")
        self._route(document)
        return {"source_path": source, "destination_path": target, "unit_address_before": stored,
                "unit_address_after": encoded, "oid_references": references}

    def plan(self, unit, destination):
        document, raw = self.snapshot()
        self._original(raw)
        before = self.digest(document)
        evidence = self.candidate(document, unit, destination)
        return {"before_sha256": before, "expected_sha256": self.digest(document), **evidence}

    def current(self):
        document, _ = self.snapshot()
        return self.digest(document)

    @staticmethod
    def _sync_parent(path):
        """Make a backup/create or project/replace directory entry durable."""
        descriptor = os.open(Path(path).parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def backup(self, raw):
        suffix = self.path.suffix
        target = self.path.with_name(f"{self.path.stem}.pre-reconcile-{uuid4().hex[:12]}{suffix}")
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if self._routed_move is not None:
            self._sync_parent(target)
        if _read_bounded(target, len(raw)) != raw:
            raise ReconcileError("Project backup readback differs from the original")
        return str(target)

    def apply(self, unit, destination, plan, record):
        """Backup, move, atomic save, then verify a fresh reload against the original."""
        document, raw = self.snapshot()
        self._original(raw)
        if self.digest(document) != plan["before_sha256"]:
            raise ReconcileError("Project changed after planning")
        record.advance("db_pending", backup=self.backup(raw))
        evidence = self.candidate(document, unit, destination)
        if self.digest(document) != plan["expected_sha256"]:
            raise ReconcileError("Candidate project differs from its plan")
        record.mark_attempted()
        if self._routed_move is not None:
            # Journal/backup fsyncs may take time; check the raw source again
            # after the durable intent and immediately before replacement.
            self._original(_read_bounded(self.path, 128 * 1024 * 1024))
        document.save(self.path)
        if self._routed_move is not None:
            self._sync_parent(self.path)
        self.verify_reload(raw, unit, destination, evidence, plan)

    def verify_reload(self, original_raw, unit, destination, evidence, plan):
        reloaded, _ = self.snapshot()
        if self.digest(reloaded) != plan["expected_sha256"]:
            raise ReconcileError("Reloaded project differs from the planned move")
        self._route(reloaded)
        node = reloaded.resolve(evidence["destination_path"])
        if _oid(node) != unit.oid or reloaded._references({unit.oid}) != evidence["oid_references"]:
            raise ReconcileError("Reloaded project lost the unit OID or its references")
        # Undo the two planned field edits on the reload: everything else,
        # including metadata, programming and member files, must be identical.
        reloaded.update(evidence["destination_path"], {"Address": str(unit.address)})
        reloaded.set_parameter(evidence["source_path"], "UnitAddress", evidence["unit_address_before"])
        original = ProjectDocument.from_snapshot(original_raw)
        if reloaded.document.toxml() != original.document.toxml():
            raise ReconcileError("Reloaded project changed data outside the unit address")


def _project_digest(document):
    """Native entity ordering is immaterial; opaque nested data keeps its order."""
    from .classic_replacement import _canonical, _shape
    from xml.dom import Node
    def shape(node):
        if node.nodeType != Node.ELEMENT_NODE or node.tagName not in ("Installation", "Project", "Network"):
            return _canonical(node.toxml()) if node.nodeType == Node.ELEMENT_NODE and node.tagName == "Unit" else _shape(node)
        attrs = tuple(sorted((node.attributes.item(i).name, node.attributes.item(i).value)
                             for i in range(node.attributes.length)))
        children = [shape(c) for c in node.childNodes if not (c.nodeType == Node.TEXT_NODE and not c.data.strip())]
        return node.tagName, attrs, tuple(sorted(children, key=repr))
    return hashlib.sha256(repr(shape(document.document.documentElement)).encode()).hexdigest()


class CGateDatabase:
    """One exclusively owned closed project, with durable whole-project readback."""

    def __init__(self, client, project, *, endpoint=None, exclusive_project=False, route_project=None):
        from .addressing import DatabaseAddressing
        from .native import _project
        self.client, self.project, self.endpoint = client, _project(project), endpoint
        self.addressing = DatabaseAddressing(client)
        self.exclusive_project = exclusive_project
        self.route_project = Path(route_project).absolute() if route_project is not None else None
        self._routed_move = None
        self._route_original_digest = None

    def identity(self):
        return {"kind": "cgate", "endpoint": self.endpoint, "project": self.project}

    def snapshot(self):
        from .programming import xml_text
        self.addressing.projects.operation("use", self.project)
        text = xml_text(self.addressing.database.get("//" + self.project, xml=True))
        document = ProjectDocument.from_bytes(text.encode("utf-8"))
        if _field(document.project, "Address") != self.project:
            raise ReconcileError("C-Gate snapshot does not contain the selected project")
        self._route(document)
        return document, None

    def _route(self, document):
        move = self._routed_move
        if move is None:
            return
        # Reconciliation can outlive several backup/save/reopen operations.
        # Keep the caller's original route snapshot immutable throughout them.
        if (self.route_project is None or
                hashlib.sha256(_read_bounded(self.route_project, 128 * 1024 * 1024)).hexdigest() != move.project_sha256):
            raise ReconcileError("Route project changed during C-Gate reconciliation")
        try:
            route = resolve_network_route(document, source_network=move.source_network,
                                          target_network=move.target_network)
        except ValueError as error:
            raise ReconcileError(f"Routed C-Gate project topology is invalid: {error}") from error
        if route != move.route:
            raise ReconcileError("Routed C-Gate project topology differs from the journal route")

    def bind_move(self, move, record, *, unit_type=None, firmware=None):
        """Bind a loaded routed project to explicitly supplied original bytes.

        The path recorded by a physical journal is evidence, never an instruction
        to read that path. A caller supplies the original exported project again;
        the same raw digest and the complete semantic project must agree. After a
        move, the durable record reconstructs the only accepted candidate.
        """
        self._routed_move = move if move.route else None
        if not move.route:
            if self.route_project is not None:
                raise ReconcileError("--route-project requires a routed journal")
            return
        if self.route_project is None:
            raise ReconcileError("Routed C-Gate reconciliation requires --route-project with the original bound snapshot")
        self._owned()
        raw = _read_bounded(self.route_project, 128 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != move.project_sha256:
            raise ReconcileError("Route project changed or does not match the journal project_sha256")
        original = ProjectDocument.from_snapshot(raw, source=self.route_project)
        if _field(original.project, "Address") != self.project:
            raise ReconcileError("Route project does not name the selected C-Gate project")
        self._route(original)
        unit, position = locate(original, move, network=move.target_network,
                                unit_type=unit_type, firmware=firmware)
        if position != "source":
            raise ReconcileError("Original route project must contain the moved serial at its source")
        self._route_original_digest = _project_digest(original)
        allowed = {self._route_original_digest}
        if record is not None:
            state = record.value.get("cgate")
            if not isinstance(state, dict) or state.get("before_project_sha256") != self._route_original_digest:
                raise ReconcileError("C-Gate record original differs from the bound route project")
            source = f"/network/{unit.network}/unit/{unit.address}"
            original.update(source, {"Address": str(move.destination)})
            original.set_parameter(f"/network/{unit.network}/unit/{move.destination}",
                                   "UnitAddress", state.get("unit_address_after"))
            self._route(original)
            allowed.add(_project_digest(original))
        current, _ = self.snapshot()
        if _project_digest(current) not in allowed:
            raise ReconcileError("Loaded C-Gate project differs from the bound whole original/candidate")

    def _closed(self, document, *, project=None):
        from .addressing import NetworkAddressing
        guard = NetworkAddressing(self.client)
        networks = [_address(_field(n, "Address")) for n in _elements(document.project, "Network") if _is_entity(n)]
        if not networks or len(networks) != len(set(networks)):
            raise ReconcileError("Project must contain unique networks")
        self._route(document)
        for network in networks:
            guard._closed(guard._runtime(f"//{project or self.project}/{network}"))

    def _owned(self):
        if self.exclusive_project is not True:
            raise ReconcileError("C-Gate apply/recovery requires --exclusive-project for all editing and reloading")

    def _guard_project(self, *digests):
        """Check a fresh whole model and runtime immediately before mutation.

        Every durable intent can yield to another cooperating editor. Intent is
        not a lease or permission to overwrite that editor's newer state.
        """
        self._owned()
        document, _ = self.snapshot()
        self._closed(document)
        if _project_digest(document) not in digests:
            raise ReconcileError("Whole project changed outside the bound move; refusing to close or save it")
        return document

    def _path(self, unit, address):
        return f"//{self.project}/{unit.network}/p/{address}"

    def plan(self, unit, destination):
        from .classic_replacement import _digest
        document, _ = self.snapshot()
        self._closed(document)
        plan = (self._routed_plan(document, unit, destination) if self._routed_move is not None else
                self.addressing.plan(self._path(unit, unit.address), destination))
        if plan.oid != unit.oid:
            raise ReconcileError("C-Gate unit OID differs from the project inventory")
        self._address_plan = plan
        self._before_project = document.raw_xml()
        self._before_project_sha256 = _project_digest(document)
        source = f"/network/{unit.network}/unit/{unit.address}"
        document.update(source, {"Address": str(destination)})
        document.set_parameter(f"/network/{unit.network}/unit/{destination}", "UnitAddress", dict(plan.parameters)["UnitAddress"])
        self._route(document)
        self._expected_project_sha256 = _project_digest(document)
        return {"before_sha256": plan.source_hash, "expected_sha256": _digest(plan.candidate_xml),
                "source_path": plan.source, "destination_path": plan.destination,
                "unit_address_before": dict(plan.source_parameters)["UnitAddress"],
                "unit_address_after": dict(plan.parameters)["UnitAddress"],
                "before_project_sha256": self._before_project_sha256,
                "expected_project_sha256": self._expected_project_sha256}

    def _routed_plan(self, project, unit, destination):
        """Stage a native two-field edit only after the separate route admission.

        General database readdressing remains direct-only. This path repeats its
        XML, PP and validation controls, with exact whole-project/topology proof
        replacing the generic bridge refusal for a known ordinary unit.
        """
        from .addressing import AddressPlan, _pp_node
        from .classic_replacement import _canonical, _digest, _document, _field as native_field, _set
        if _project_digest(project) != self._route_original_digest:
            raise ReconcileError("Routed database plan requires the bound whole original project")
        move = self._routed_move
        actual, position = locate(project, move, network=move.target_network,
                                  unit_type=unit.unit_type, firmware=unit.firmware)
        if position != "source" or actual != unit:
            raise ReconcileError("Routed source identity differs from the bound unit")
        source, target = self._path(unit, unit.address), self._path(unit, destination)
        if source in project.raw_xml():
            raise ReconcileError("Project contains a textual unit-path reference requiring explicit reconciliation")
        if re.search(rf"/{unit.network}/p/{unit.address}(?![0-9])", project.raw_xml()):
            raise ReconcileError("Project contains a textual unit-path reference requiring explicit reconciliation")
        source_xml = self.addressing._xml(source)
        document = _document(source_xml)
        if (_canonical(source_xml) != _canonical(project.resolve(f"/network/{unit.network}/unit/{unit.address}").toxml()) or
                native_field(document, "OID") != unit.oid or native_field(document, "Address") != str(unit.address)):
            raise ReconcileError("Fresh C-Gate unit differs from the bound project identity")
        if self.addressing._optional_xml(target) is not None:
            raise ReconcileError("Destination unit address is occupied")
        self.addressing._validate(source)
        stored = _pp_node(document, "UnitAddress").getAttribute("Value")
        if int(stored, 0) != unit.address:
            raise ReconcileError("Stored PP UnitAddress differs from the source address")
        network = f"//{self.project}/{unit.network}"
        with self.addressing.programmer.load(network, "/db" + source) as session:
            before = session.values()
            if "UnitAddress" not in before or int(before["UnitAddress"], 0) != unit.address:
                raise ReconcileError("Loaded PP UnitAddress differs from the source address")
            session.set("UnitAddress", str(destination))
            after = session.values()
            if (int(after.get("UnitAddress", "-1"), 0) != destination or
                    {k: v for k, v in before.items() if k != "UnitAddress"} !=
                    {k: v for k, v in after.items() if k != "UnitAddress"}):
                raise ReconcileError("Native UnitAddress staging changed other PP values")
        _set(document, "Address", str(destination))
        _pp_node(document, "UnitAddress").setAttribute("Value", after["UnitAddress"])
        return AddressPlan(source, target, unit.oid, source_xml, _digest(source_xml),
                           tuple(sorted(before.items())), tuple(sorted(after.items())), document.toxml())

    def evidence(self, plan):
        return {"format": "cbus-serial-reconcile-cgate-save-v1", "stage": "planned",
                "before_xml": self._before_project, "before_project_sha256": self._before_project_sha256,
                "expected_project_sha256": self._expected_project_sha256,
                "unit_address_after": plan["unit_address_after"], "backup_confirmed": False,
                "backup_readback_sha256": None, "saved_readback_verified": False}

    def bind_record(self, move, record):
        """Rederive both digests and the two-field candidate from the bound original."""
        if record.value.get("format") != CGATE_RECORD_FORMAT or "cgate" not in record.value:
            raise ReconcileError("Legacy C-Gate records lack durable saved-state evidence; resolve manually")
        state = record.value["cgate"]
        try:
            _keys(state, ("format", "stage", "before_xml", "before_project_sha256", "expected_project_sha256",
                          "unit_address_after", "backup_confirmed", "backup_readback_sha256",
                          "saved_readback_verified"), "C-Gate save evidence")
            if (state["format"] != "cbus-serial-reconcile-cgate-save-v1" or
                    type(state["backup_confirmed"]) is not bool or type(state["saved_readback_verified"]) is not bool or
                    state["stage"] not in ("planned", "baseline_save_intent", "baseline_save_complete", "backup_intent",
                        "backup_complete", "database_write_intent", "database_write_complete", "target_save_intent",
                        "target_save_complete", "close_intent", "close_complete", "load_intent", "load_complete", "readback_complete")):
                raise ValueError("unsupported saved-state evidence")
            if record.value["backup"] is not None and not re.fullmatch(r"B[0-9A-F]{7}", record.value["backup"]):
                raise ValueError("backup identity is malformed")
            if state["backup_confirmed"] and record.value["backup"] is None:
                raise ValueError("confirmed backup identity is missing")
            if state["backup_readback_sha256"] != (state["before_project_sha256"] if state["backup_confirmed"] else None):
                raise ValueError("backup readback does not bind the original project")
            if record.value["phase"] == "db_done" and (state["saved_readback_verified"] is not True or state["stage"] != "readback_complete"):
                raise ValueError("completion lacks saved readback")
            before = ProjectDocument.from_bytes(state["before_xml"].encode())
            self._route(before)
            if self._routed_move is not None and _project_digest(before) != self._route_original_digest:
                raise ValueError("original differs from the bound route project")
            if _field(before.project, "Address") != self.project or record.value["move"] != move.move():
                raise ValueError("project or physical move differs")
            unit, position = locate(before, move, network=record.value["unit"]["network"],
                                    unit_type=record.value["unit"]["unit_type"], firmware=record.value["unit"]["firmware"])
            paths = {"source_path": self._path(unit, move.source), "destination_path": self._path(unit, move.destination)}
            if position != "source" or record.value["unit"] != unit.as_dict() | paths:
                raise ValueError("original source identity/OID differs")
            from .classic_replacement import _digest
            source = f"/network/{unit.network}/unit/{unit.address}"
            if _digest(before.resolve(source).toxml()) != record.value["before_sha256"]:
                raise ValueError("original unit digest differs")
            if _project_digest(before) != state["before_project_sha256"] or int(state["unit_address_after"], 0) != move.destination:
                raise ValueError("original digest or candidate UnitAddress differs")
            before.update(source, {"Address": str(move.destination)})
            destination = f"/network/{unit.network}/unit/{move.destination}"
            before.set_parameter(destination, "UnitAddress", state["unit_address_after"])
            self._route(before)
            if (_project_digest(before) != state["expected_project_sha256"] or
                    _digest(before.resolve(destination).toxml()) != record.value["expected_sha256"]):
                raise ValueError("candidate differs from the exact two-field move")
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ReconcileError(f"C-Gate record binding is invalid: {error}") from error

    def _stage(self, record, stage, **fields):
        record.value["cgate"].update(stage=stage, **fields)
        record.value["history"].append({"event": stage, "at": _now()})
        record._write()

    def _backup_readback(self, record):
        """Read the copied original; normalize only its repository project name."""
        from .programming import xml_text
        backup = record.value["backup"]
        self.addressing.projects.operation("load", backup)
        self.addressing.projects.operation("use", backup)
        try:
            text = xml_text(self.addressing.database.get("//" + backup, xml=True))
            document = ProjectDocument.from_bytes(text.encode())
            if _field(document.project, "Address") not in (backup, self.project):
                raise ReconcileError("Backup readback names a different project")
            document.update("/", {"Address": self.project})
            self._closed(document, project=backup)
            digest = _project_digest(document)
            if digest != record.value["cgate"]["before_project_sha256"]:
                raise ReconcileError("Backup differs from the bound whole original project")
            return digest
        finally:
            self.addressing.projects.operation("use", self.project)

    def _reopen(self, record):
        """Discard only our bound loaded state and read the saved image; never SAVE."""
        self._owned()
        # LOAD is a no-op when already loaded, and recovers a lost CLOSE reply.
        self.addressing.projects.operation("load", self.project)
        document, _ = self.snapshot()
        self._closed(document)
        state = record.value["cgate"]
        if _project_digest(document) not in (state["before_project_sha256"], state["expected_project_sha256"]):
            raise ReconcileError("Loaded project changed outside the bound move; refusing to close or save it")
        self._stage(record, "close_intent")
        self._guard_project(state["before_project_sha256"], state["expected_project_sha256"])
        self.addressing.projects.operation("close", self.project)
        self._stage(record, "close_complete")
        self._stage(record, "load_intent")
        self.addressing.projects.operation("load", self.project)
        self._stage(record, "load_complete")
        reloaded, _ = self.snapshot()
        self._closed(reloaded)
        digest = _project_digest(reloaded)
        if digest not in (state["before_project_sha256"], state["expected_project_sha256"]):
            raise ReconcileError("Saved project conflicts with the bound original/candidate; resolve manually")
        expected = digest == state["expected_project_sha256"]
        self._stage(record, "readback_complete", saved_readback_verified=expected)
        return expected

    def recover(self, record, *, apply, retry_database=False):
        if not apply:
            raise ReconcileError("Pending C-Gate reconciliation needs --apply --exclusive-project to reopen and classify saved state")
        if self._reopen(record):
            if not record.value["cgate"]["backup_confirmed"]:
                raise ReconcileError("Saved candidate has no confirmed original backup")
            self._backup_readback(record)
            record.advance("db_done", database_changed=True, last_error=None)
            return True
        if not retry_database:
            raise ReconcileError("Saved project remains the original; database move is unconfirmed. "
                                 "Use --retry-database --apply to authorize one database-only retry; no address command is replayed",
                                 record=str(record.path), phase="db_pending", saved_candidate_verified=False)
        return False

    def current(self, unit, plan):
        """Classify the unit by the digests of its native XML at both paths."""
        from .classic_replacement import _digest, _document, _field
        self.addressing.projects.operation("use", self.project)
        for key, path in (("expected_sha256", plan["destination_path"]), ("before_sha256", plan["source_path"])):
            text = self.addressing._optional_xml(path)
            if text is not None and _field(_document(text), "OID") == unit.oid and _digest(text) == plan[key]:
                return plan[key]
        return None

    def apply(self, unit, destination, plan, record):
        self._owned()
        before, _ = self.snapshot()
        self._closed(before)
        state = record.value["cgate"]
        if _project_digest(before) != state["before_project_sha256"]:
            raise ReconcileError("Whole project changed before database mutation")
        backup = record.value["backup"] or "B" + uuid4().hex[:7].upper()
        record.advance("db_pending", backup=backup)
        address_plan = getattr(self, "_address_plan", None) or self.addressing.plan(plan["source_path"], destination)
        try:
            if not state["backup_confirmed"]:
                # A fresh backup name never overwrites an uncertain previous copy.
                if state["stage"] == "readback_complete":
                    backup = "B" + uuid4().hex[:7].upper()
                    record.advance("db_pending", backup=backup)
                self._stage(record, "baseline_save_intent")
                self._guard_project(state["before_project_sha256"])
                self.addressing.projects.operation("save", self.project)
                self._stage(record, "baseline_save_complete")
                self._stage(record, "backup_intent")
                self._guard_project(state["before_project_sha256"])
                self.addressing.projects.operation("copy", self.project, backup)
                digest = self._backup_readback(record)
                self._stage(record, "backup_complete", backup_confirmed=True, backup_readback_sha256=digest)
            else:
                self._backup_readback(record)
            current, _ = self.snapshot()
            self._closed(current)
            if _project_digest(current) != state["before_project_sha256"]:
                raise ReconcileError("Whole project changed while creating the backup")
            record.mark_attempted()
            self._stage(record, "database_write_intent", saved_readback_verified=False)
            # Durable intent may take time. Re-read the complete model and the
            # route snapshot immediately before the sole database mutation.
            self._guard_project(state["before_project_sha256"])
            self.client.command_document("DBSETXML " + address_plan.source, address_plan.candidate_xml)
            self._stage(record, "database_write_complete")
            self.addressing._verify(address_plan)
            candidate, _ = self.snapshot()
            self._closed(candidate)
            if _project_digest(candidate) != state["expected_project_sha256"]:
                raise ReconcileError("Database mutation changed data outside the two planned fields")
            self._stage(record, "target_save_intent")
            self._guard_project(state["expected_project_sha256"])
            self.addressing.projects.operation("save", self.project)
            self._stage(record, "target_save_complete")
            if not self._reopen(record):
                raise ReconcileError("PROJECT SAVE did not persist the exact candidate")
        except BaseException as error:
            record.fail(error)
            # Never restore, SAVE again, or replay an uncertain mutation.
            raise


class ReconcileRecord:
    """Exclusive-create reconciliation record with checked atomic updates."""

    def __init__(self, path, value=None, raw=None):
        self.path = Path(path).absolute()
        self.value = value
        self.writer = _Journal(self.path)
        self.writer.expected = raw

    @classmethod
    def load(cls, path):
        try:
            raw = _read_bounded(path, MAX_RECORD_BYTES)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise ReconcileError(f"Cannot read reconciliation record: {error}") from error
        value = _parse(raw, "Reconciliation record")
        if (not isinstance(value, dict) or
                (value.get("format"), set(value)) not in ((RECORD_FORMAT, set(_RECORD_KEYS)),
                    (CGATE_RECORD_FORMAT, set(_RECORD_KEYS) | {"cgate"})) or
                value["phase"] not in PHASES or not isinstance(value["history"], list)):
            raise ReconcileError("Unsupported or malformed reconciliation record")
        return cls(path, value, raw)

    def _write(self):
        self.writer.write(self.value)

    def create(self, value):
        try:
            self.value = value
            self._write()
        except FileExistsError as error:
            raise ReconcileError("A reconciliation record was created concurrently; rerun to resume",
                                 record=str(self.path)) from error

    def advance(self, phase, **fields):
        self.value.update(fields)
        self.value["phase"] = phase
        self.value["history"].append({"phase": phase, "at": _now()})
        self._write()

    def mark_attempted(self):
        self.value["database_changed"] = None  # Unknown until verification.
        self.value["history"].append({"event": "database_write_attempted", "at": _now()})
        self._write()

    def fail(self, error, rollback_errors=()):
        self.value["last_error"] = {"type": type(error).__name__, "message": str(error)}
        self.value["rollback_errors"] = list(rollback_errors)
        self.value["history"].append({"event": "database_write_failed", "at": _now()})
        try:
            self._write()
        except BaseException as secondary:  # Keep the original failure visible.
            self.value["last_error"]["record_update_error"] = str(secondary)


def default_record_path(journal):
    journal = Path(journal).absolute()
    return journal.with_name(journal.name + ".reconcile.json")


def reconcile(journal, database, *, apply=False, record_path=None, network=None, unit_type=None, firmware=None,
              retry_database=False):
    """Plan (default) or apply one database reconciliation for a verified move."""
    move = verify_journal(journal)
    if retry_database and (not apply or not isinstance(database, CGateDatabase)):
        raise ReconcileError("--retry-database requires --apply and a pending C-Gate record")
    if apply and isinstance(database, CGateDatabase):
        database._owned()
    if move.route:
        if network is not None and (type(network) is not int or network != move.target_network):
            raise ReconcileError("Requested network differs from the routed journal target network")
        network = move.target_network
    record_path = Path(record_path).absolute() if record_path is not None else default_record_path(journal)
    record = ReconcileRecord.load(record_path)
    identity = database.identity()
    if record is not None:
        value = record.value
        if value["journal"]["sha256"] != move.journal_sha256 or value["journal"]["attempt_id"] != move.attempt_id:
            raise ReconcileError("Journal changed after reconciliation started (stale or tampered)", record=str(record.path))
        if value["database"] != identity:
            raise ReconcileError("Reconciliation record belongs to a different database", record=str(record.path),
                                 recorded=value["database"])
    if isinstance(database, (ProjectFileDatabase, CGateDatabase)):
        database.bind_move(move, record, unit_type=unit_type, firmware=firmware)
    if isinstance(database, CGateDatabase) and record is not None:
        database.bind_record(move, record)
    if retry_database and (record is None or record.value["phase"] != "db_pending"):
        raise ReconcileError("--retry-database requires an existing pending C-Gate record")
    result = {"format": RESULT_FORMAT, "mode": "apply" if apply else "dry_run", "journal": move.as_dict(),
              "move": move.move(), "database": identity, "record": None, "database_changed": False,
              "bus_io_performed": False, "hardware_programmed": False}

    def finish(outcome, *, changed=False, extra=None):
        result.update(outcome=outcome, database_changed=changed, **(extra or {}))
        if record is not None:
            result["record"] = {"path": str(record.path), "phase": record.value["phase"],
                                "backup": record.value["backup"]}
        return result

    if record is not None and record.value["phase"] == "db_done":
        unit = DatabaseUnit(**{k: record.value["unit"][k] for k in ("network", "address", "unit_type",
                                                                     "firmware", "serial_text", "oid")})
        matches = None
        if record.value["expected_sha256"] is not None:
            matches = _current(database, unit, record.value) == record.value["expected_sha256"]
        if isinstance(database, CGateDatabase) and matches is not True:
            raise ReconcileError("Completed C-Gate project differs from its saved candidate; resolve manually",
                                 record=str(record.path), phase="db_done")
        return finish("already_reconciled", extra={"current_database_matches_record": matches})
    if isinstance(database, CGateDatabase) and record is not None and record.value["phase"] == "db_pending":
        if database.recover(record, apply=apply, retry_database=retry_database):
            return finish("resumed_complete", changed=True)
    document, _ = database.snapshot()
    unit, position = locate(document, move, network=network, unit_type=unit_type, firmware=firmware)
    if record is not None and record.value["unit"]["oid"] != unit.oid:
        raise ReconcileError("Database unit OID differs from the reconciliation record", record=str(record.path))
    result["unit"] = unit.as_dict()
    if position == "destination":
        # Already moved: an interrupted earlier run (db_pending) or a database
        # that recorded the destination beforehand. Nothing is written to it.
        if record is not None and record.value["phase"] == "db_pending":
            plan = record.value
            if _current(database, unit, plan) != plan["expected_sha256"]:
                raise ReconcileError("Database unit is at the destination but differs from the planned move; "
                                     "resolve manually", record=str(record.path), phase="db_pending")
            if apply:
                if move.route:
                    # A previous rename may have succeeded before its parent
                    # directory fsync failed; make that publication durable
                    # before declaring recovery complete. Never repeat save.
                    database._sync_parent(database.path)
                record.advance("db_done", database_changed=True, last_error=None)
            return finish("resumed_complete" if apply else "resume_pending", changed=True)
        if not apply:
            return finish("database_already_matches")
        if isinstance(database, CGateDatabase):
            raise ReconcileError("C-Gate destination has no bound original reconciliation record; "
                                 "saved two-field move cannot be established")
        record = record or ReconcileRecord(record_path)
        if record.value is None:
            record.create(_record(move, identity, unit, None, "physical_done"))
        record.advance("db_done", database_changed=False)
        return finish("database_already_matches")
    plan = database.plan(unit, move.destination)
    result["plan"] = dict(plan)
    if record is not None and record.value["phase"] == "db_pending":
        if record.value["before_sha256"] != plan["before_sha256"]:
            raise ReconcileError("Database unit changed while reconciliation was pending; resolve manually",
                                 record=str(record.path), phase="db_pending")
        if isinstance(database, CGateDatabase):
            if (record.value["expected_sha256"] != plan["expected_sha256"] or
                    record.value["cgate"]["expected_project_sha256"] != plan["expected_project_sha256"]):
                raise ReconcileError("Fresh database-only retry differs from the bound two-field candidate")
        else:
            record.value["expected_sha256"] = plan["expected_sha256"]
    if not apply:
        return finish("planned")
    if record is None:
        record = ReconcileRecord(record_path)
        record.create(_record(move, identity, unit, plan, "physical_done",
                              cgate=database.evidence(plan) if isinstance(database, CGateDatabase) else None))
    elif record.value["phase"] == "physical_done":
        # No database write was marked; bind the record to the fresh plan.
        if isinstance(database, CGateDatabase) and (
                record.value["cgate"]["before_project_sha256"] != plan["before_project_sha256"] or
                record.value["cgate"]["expected_project_sha256"] != plan["expected_project_sha256"]):
            raise ReconcileError("Whole project changed after reconciliation planning")
        record.value.update(before_sha256=plan["before_sha256"], expected_sha256=plan["expected_sha256"])
        record.value["unit"].update(source_path=plan["source_path"], destination_path=plan["destination_path"])
    try:
        database.apply(unit, move.destination, plan, record)
    except ReconcileError as error:
        if record.value["phase"] == "db_pending" and record.value["last_error"] is None:
            record.fail(error)
        raise
    except Exception as error:
        record.fail(error)
        raise ReconcileError(f"Database move stopped: {error}; reconciliation remains {record.value['phase']}",
                             record=str(record.path), phase=record.value["phase"],
                             backup=record.value["backup"]) from error
    record.advance("db_done", database_changed=True, last_error=None)
    return finish("reconciled", changed=True)


def _current(database, unit, plan):
    if isinstance(database, CGateDatabase):
        if "cgate" in plan:
            document, _ = database.snapshot()
            database._closed(document)
            digest = _project_digest(document)
            return (plan["expected_sha256"] if digest == plan["cgate"]["expected_project_sha256"] else
                    plan["before_sha256"] if digest == plan["cgate"]["before_project_sha256"] else None)
        return database.current(unit, {"source_path": plan["unit"]["source_path"],
                                       "destination_path": plan["unit"]["destination_path"],
                                       "before_sha256": plan["before_sha256"],
                                       "expected_sha256": plan["expected_sha256"]})
    return database.current()


def _record(move, identity, unit, plan, phase, *, cgate=None):
    unit_record = unit.as_dict()
    unit_record["source_path"] = plan["source_path"] if plan else None
    unit_record["destination_path"] = plan["destination_path"] if plan else None
    value = {"format": CGATE_RECORD_FORMAT if cgate is not None else RECORD_FORMAT, "phase": phase, "journal": move.as_dict(), "move": move.move(),
            "database": identity, "unit": unit_record,
            "before_sha256": plan["before_sha256"] if plan else None,
            "expected_sha256": plan["expected_sha256"] if plan else None,
            "backup": None, "database_changed": False, "history": [{"phase": phase, "at": _now()}],
            "last_error": None, "rollback_errors": [], "bus_io_performed": False}
    if cgate is not None:
        value["cgate"] = cgate
    return value


def _endpoint(text):
    match = re.fullmatch(r"\[([0-9A-Fa-f:.]+)\]:([0-9]{1,5})|([^:\[\]]+):([0-9]{1,5})", text or "")
    if not match:
        raise ValueError("Use --cgate HOST:PORT")
    host, port = (match[1], match[2]) if match[1] else (match[3], match[4])
    if not 1 <= int(port) <= 65535:
        raise ValueError("C-Gate port must be in 1..65535")
    return host, int(port)


def run_cli(args):
    """``cbus-toolkit serial-address reconcile``; returns (result, exit status)."""
    options = dict(apply=args.apply, record_path=args.record, network=args.network,
                   unit_type=args.unit_type, firmware=args.firmware, retry_database=args.retry_database)
    if args.project is not None:
        if args.cgate is not None or args.project_name is not None or getattr(args, "route_project", None) is not None:
            raise ValueError("Use either --project or --cgate with --project-name")
        return reconcile(args.journal, ProjectFileDatabase(args.project), **options), 0
    if args.cgate is None or args.project_name is None:
        raise ValueError("Use --project FILE, or --cgate HOST:PORT with --project-name")
    if args.retry_database and not args.apply:
        raise ReconcileError("--retry-database requires --apply")
    # Validate the physical evidence and explicit topology before connecting.
    move = verify_journal(args.journal)
    route_project = getattr(args, "route_project", None)
    if move.route:
        if route_project is None:
            raise ReconcileError("Routed C-Gate reconciliation requires --route-project with the original bound snapshot")
        raw = _read_bounded(route_project, 128 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != move.project_sha256:
            raise ReconcileError("Route project does not match the routed journal project_sha256")
        document = ProjectDocument.from_snapshot(raw, source=route_project)
        if (_field(document.project, "Address") != args.project_name or
                resolve_network_route(document, source_network=move.source_network,
                                      target_network=move.target_network) != move.route):
            raise ReconcileError("Route project identity or topology differs from the routed journal")
        if args.network is not None and args.network != move.target_network:
            raise ReconcileError("Requested network differs from the routed journal target network")
    elif route_project is not None:
        raise ReconcileError("--route-project requires a routed journal")
    if (args.apply or move.route) and not args.exclusive_project:
        raise ReconcileError("C-Gate apply/recovery requires --exclusive-project")
    from .cgate import CGateClient
    host, port = _endpoint(args.cgate)
    with CGateClient(host, port, timeout=args.timeout, max_line_bytes=16 * 1024 * 1024 + 4096) as client:
        database = CGateDatabase(client, args.project_name, endpoint=f"{host}:{port}",
                                 exclusive_project=args.exclusive_project, route_project=route_project)
        return reconcile(args.journal, database, **options), 0
