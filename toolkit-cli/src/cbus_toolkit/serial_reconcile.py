"""Reconcile one verified selected-serial move with the project database.

The only admitted physical evidence is a complete ``serial-address apply``
journal whose independently reparsed after-inventory equals the plan's exact
expected identity map and whose attempt marker still binds the same plan.
The database unit carrying that serial is then moved from the journal's source
address to its destination with its OID, metadata, programming and OID
references preserved. No PCI, CNI or C-Bus network I/O is performed.

Progress is kept in a separate reconciliation record beside the journal. It is
created exclusively and advanced through ``physical_done`` -> ``db_pending`` ->
``db_done``. A rerun after ``db_done`` is a read-only no-op; a rerun after
``db_pending`` re-reads the database and either completes the record, repeats
an unstarted move or reports a conflict. Nothing is retried automatically.
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
    ATTEMPT_FORMAT, MAX_JOURNAL_BYTES, SelectedSerialCoordinator, SelectedSerialPlan, _Journal,
    _canonical_fingerprint, _hex, _inventory_proof, _json, _keys, _options_proof, _raw_serials, _unique_pairs,
)
from .commissioning_route import resolve_network_route
from .pci_serial_address import decode_serial_address_receipt
from .project import ProjectDocument, _address, _all_elements, _elements, _field, _is_entity, _name, _oid
from .serials import parse_native_serial


RECORD_FORMAT = "cbus-serial-reconcile-record-v1"
RESULT_FORMAT = "cbus-serial-reconcile-result-v1"
PHASES = ("physical_done", "db_pending", "db_done")
MAX_RECORD_BYTES = 1024 * 1024
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
        if _json(SelectedSerialPlan.from_dict(record["plan"]).as_dict()) != _json(plan):
            raise ValueError("marker embeds a different plan")
        # The marker stores the resolved journal path; the journal its absolute path.
        written = Path(recorded["path"])
        if record["journal"] not in (recorded["path"], str(written.parent.resolve() / written.name)):
            raise ValueError("marker names a different journal")
    except (ValueError, TypeError) as error:
        raise ReconcileError(f"Attempt marker does not bind this journal (stale or tampered): {error}") from error
    return VerifiedMove(str(path.absolute()), hashlib.sha256(raw).hexdigest(), record["attempt_id"], marker,
                        plan["serial"], plan["source"], plan["destination"], dict(endpoint), local,
                        value["receipt_matches_request"], route, plan.get("project_sha256"),
                        binding["source_network"] if binding else None,
                        binding["target_network"] if binding else None)


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


class CGateDatabase:
    """A loaded C-Gate project, moved through verified ``DatabaseAddressing``."""

    def __init__(self, client, project, *, endpoint=None):
        from .addressing import DatabaseAddressing
        from .native import _project
        self.client, self.project, self.endpoint = client, _project(project), endpoint
        self.addressing = DatabaseAddressing(client)

    def identity(self):
        return {"kind": "cgate", "endpoint": self.endpoint, "project": self.project}

    def snapshot(self):
        from .programming import xml_text
        self.addressing.projects.operation("use", self.project)
        text = xml_text(self.addressing.database.get("//" + self.project, xml=True))
        return ProjectDocument.from_bytes(text.encode("utf-8")), None

    def _path(self, unit, address):
        return f"//{self.project}/{unit.network}/p/{address}"

    def plan(self, unit, destination):
        from .classic_replacement import _digest
        plan = self.addressing.plan(self._path(unit, unit.address), destination)
        if plan.oid != unit.oid:
            raise ReconcileError("C-Gate unit OID differs from the project inventory")
        self._address_plan = plan
        return {"before_sha256": plan.source_hash, "expected_sha256": _digest(plan.candidate_xml),
                "source_path": plan.source, "destination_path": plan.destination,
                "unit_address_before": dict(plan.source_parameters)["UnitAddress"],
                "unit_address_after": dict(plan.parameters)["UnitAddress"]}

    def current(self, unit, plan):
        """Classify the unit by the digests of its native XML at both paths."""
        from .classic_replacement import _digest, _document, _field
        for key, path in (("expected_sha256", plan["destination_path"]), ("before_sha256", plan["source_path"])):
            text = self.addressing._optional_xml(path)
            if text is not None and _field(_document(text), "OID") == unit.oid and _digest(text) == plan[key]:
                return plan[key]
        return None

    def apply(self, unit, destination, plan, record):
        from .addressing import AddressingError
        backup = "B" + uuid4().hex[:7].upper()
        record.advance("db_pending", backup=backup)
        address_plan = getattr(self, "_address_plan", None) or self.addressing.plan(plan["source_path"], destination)
        record.mark_attempted()
        try:
            self.addressing.apply(address_plan, backup_project=backup)
        except AddressingError as error:
            record.fail(error, error.details.get("rollback_errors", []))
            raise ReconcileError("C-Gate database move failed; reconciliation remains db_pending",
                                 record=str(record.path), phase=record.value["phase"],
                                 backup_project=backup, rollback_errors=error.details.get("rollback_errors", [])) from error
        if self.current(unit, plan) != plan["expected_sha256"]:
            raise ReconcileError("Saved C-Gate unit differs from the planned move")
        if self.addressing._optional_xml(plan["source_path"]) is not None:
            raise ReconcileError("Old database unit address remains occupied")


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
        if (not isinstance(value, dict) or set(value) != set(_RECORD_KEYS) or value["format"] != RECORD_FORMAT or
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


def reconcile(journal, database, *, apply=False, record_path=None, network=None, unit_type=None, firmware=None):
    """Plan (default) or apply one database reconciliation for a verified move."""
    move = verify_journal(journal)
    if move.route:
        if not isinstance(database, ProjectFileDatabase):
            raise ReconcileError("Routed reconciliation requires an offline XML/CBZ project; "
                                 "routed C-Gate database reconciliation is unsupported")
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
    if isinstance(database, ProjectFileDatabase):
        database.bind_move(move, record, unit_type=unit_type, firmware=firmware)
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
        return finish("already_reconciled", extra={"current_database_matches_record": matches})
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
        record.value["expected_sha256"] = plan["expected_sha256"]
    if not apply:
        return finish("planned")
    if record is None:
        record = ReconcileRecord(record_path)
        record.create(_record(move, identity, unit, plan, "physical_done"))
    elif record.value["phase"] == "physical_done":
        # No database write was marked; bind the record to the fresh plan.
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
        return database.current(unit, {"source_path": plan["unit"]["source_path"],
                                       "destination_path": plan["unit"]["destination_path"],
                                       "before_sha256": plan["before_sha256"],
                                       "expected_sha256": plan["expected_sha256"]})
    return database.current()


def _record(move, identity, unit, plan, phase):
    unit_record = unit.as_dict()
    unit_record["source_path"] = plan["source_path"] if plan else None
    unit_record["destination_path"] = plan["destination_path"] if plan else None
    return {"format": RECORD_FORMAT, "phase": phase, "journal": move.as_dict(), "move": move.move(),
            "database": identity, "unit": unit_record,
            "before_sha256": plan["before_sha256"] if plan else None,
            "expected_sha256": plan["expected_sha256"] if plan else None,
            "backup": None, "database_changed": False, "history": [{"phase": phase, "at": _now()}],
            "last_error": None, "rollback_errors": [], "bus_io_performed": False}


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
                   unit_type=args.unit_type, firmware=args.firmware)
    if args.project is not None:
        if args.cgate is not None or args.project_name is not None:
            raise ValueError("Use either --project or --cgate with --project-name")
        return reconcile(args.journal, ProjectFileDatabase(args.project), **options), 0
    if args.cgate is None or args.project_name is None:
        raise ValueError("Use --project FILE, or --cgate HOST:PORT with --project-name")
    # Validate the physical evidence before opening any connection.
    if verify_journal(args.journal).route:
        raise ReconcileError("Routed C-Gate database reconciliation is unsupported; use the bound offline XML/CBZ project")
    from .cgate import CGateClient
    host, port = _endpoint(args.cgate)
    with CGateClient(host, port, timeout=args.timeout, max_line_bytes=16 * 1024 * 1024 + 4096) as client:
        database = CGateDatabase(client, args.project_name, endpoint=f"{host}:{port}")
        return reconcile(args.journal, database, **options), 0
