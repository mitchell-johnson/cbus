"""Guarded Toolkit-style database serial metadata population from native cache."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from uuid import UUID, uuid4
from xml.dom import Node

from .addressing import _container, _network_canonical, _network_path
from .classic_replacement import _canonical, _document, _field, _set
from .native import NativeDatabase, NativeProjects, _project
from .programming import xml_text
from .serials import NativeSerials, SerialInventory, _selection, parse_native_serial


class SerialPopulationError(RuntimeError):
    def __init__(self, message, *, backup_project=None, rollback_errors=()):
        self.details = {"backup_project": backup_project, "rollback_errors": list(rollback_errors)}
        super().__init__(message)


# Concrete Toolkit class compatibility is deliberately bounded. These types
# are enabled only after source verification of the inherited equality branch.
_SUPPORTED_TYPES = frozenset(("KEYE1", "KEYGL5", "PC_CNIED"))


def _fingerprint(inventory):
    if not isinstance(inventory, SerialInventory):
        raise ValueError("Expected a native SerialInventory")
    if inventory.requested is not None or not inventory.complete or not inventory.records:
        raise ValueError("Serial population requires a complete, nonempty whole-network inventory")
    if inventory.mode not in ("cached", "refresh") or inventory.mode == "refresh" and not inventory.refresh_completed:
        raise ValueError("Inventory has no successful cached or refreshed observation")
    addresses, serials, rows = set(), set(), []
    for record in inventory.records:
        if record.status != "ok" or record.state != "ok" or record.errors:
            raise ValueError("Inventory contains an unresolved identity")
        if record.presence != ("cached" if inventory.mode == "cached" else "single"):
            raise ValueError("Inventory has no unique physical identity at an address")
        number = parse_native_serial(record.serial)
        if not number.known or number.canonical in serials or record.address in addresses:
            raise ValueError("Inventory contains unknown or duplicate serials/addresses")
        if record.identity is None or not record.firmware:
            raise ValueError("Inventory identity is incomplete")
        addresses.add(record.address); serials.add(number.canonical)
        rows.append((record.address, record.unit_type, record.firmware, record.serial, record.state))
    return tuple(sorted(rows))


def _network_digest(text):
    return hashlib.sha256(repr(_network_canonical(text)).encode()).hexdigest()


def _units(document):
    units = {}
    for node in document.documentElement.childNodes:
        if node.nodeType != Node.ELEMENT_NODE or node.tagName != "Unit": continue
        unit = _document(node.toxml())
        address = _field(unit, "Address")
        if not address.isdecimal() or not 0 <= int(address) <= 255 or int(address) in units:
            raise ValueError("Database has an invalid or duplicate unit address")
        units[int(address)] = (node, unit)
    return units


@dataclass(frozen=True)
class SerialChange:
    address: int
    oid: str
    unit_type: str
    firmware: str
    old_serial: str
    new_serial: str
    source_xml: str
    candidate_xml: str

    def as_dict(self):
        return {"address": self.address, "oid": self.oid, "unit_type": self.unit_type,
                "firmware": self.firmware, "old_serial": self.old_serial, "new_serial": self.new_serial}


@dataclass(frozen=True)
class SerialPopulationPlan:
    network: str
    inventory: SerialInventory
    units: tuple[int, ...]
    source_xml: str
    source_hash: str
    candidate_xml: str
    changes: tuple[SerialChange, ...]

    def as_dict(self):
        return {"format": "cbus-database-serial-population-plan-v1", "network": self.network,
                "units": list(self.units), "source_hash": self.source_hash,
                "changes": [change.as_dict() for change in self.changes],
                "inventory_mode": self.inventory.mode, "observed_at": self.inventory.observed_at,
                "identity_guard": "same address, exact unit type and firmware; complete unique serial inventory",
                "updated": False, "hardware_programmed": False, "metadata_only": True}


class DatabaseSerials:
    def __init__(self, client):
        self.client = client
        self.database, self.projects = NativeDatabase(client), NativeProjects(client)
        self.scanner = NativeSerials(client)

    def _xml(self, path):
        return xml_text(self.database.get(path, xml=True))

    def _check_runtime(self, inventory):
        expected = _fingerprint(inventory)
        if _fingerprint(self.scanner.cached(inventory.network)) != expected:
            raise ValueError("Native serial inventory is stale")

    def plan(self, inventory, *, units=None):
        _fingerprint(inventory)
        network, project = _network_path(inventory.network)
        selection = _selection(units)
        self._check_runtime(inventory)
        self.projects.operation("use", project)
        source = self._xml(network)
        document = _container(source, "Network")
        database_units = _units(document)
        selected = selection if selection is not None else tuple(sorted(database_units))
        if not selected: raise ValueError("Database unit selection is empty")
        physical = {r.address: r for r in inventory.records}
        changes = []
        for address in selected:
            if address not in database_units or address not in physical:
                raise ValueError("Selected address must exist in both database and physical inventory")
            node, unit = database_units[address]
            record = physical[address]
            unit_type, firmware = _field(unit, "UnitType"), _field(unit, "FirmwareVersion")
            if unit_type not in _SUPPORTED_TYPES:
                raise ValueError("Toolkit compatibility is not yet verified for unit type " + unit_type)
            if unit_type != record.unit_type or firmware != record.firmware:
                raise ValueError("Database and physical unit type/firmware differ at address " + str(address))
            oid = _field(unit, "OID")
            try: UUID(oid)
            except (ValueError, AttributeError) as error: raise ValueError("Database unit has no valid OID") from error
            old_serial = _field(unit, "SerialNumber")
            if old_serial == record.serial: continue
            source_xml = unit.toxml()
            _set(unit, "SerialNumber", record.serial)
            candidate = unit.toxml()
            if _canonical(source_xml, exclude=("SerialNumber",)) != _canonical(candidate, exclude=("SerialNumber",)):
                raise ValueError("Serial edit changed non-serial unit data")
            changes.append(SerialChange(address, oid, unit_type, firmware, old_serial, record.serial, source_xml, candidate))
            document.documentElement.replaceChild(document.importNode(unit.documentElement, True), node)
        # A new serial may not collide with an unselected database unit.
        seen = {}
        for address, (_, unit) in _units(document).items():
            text = _field(unit, "SerialNumber")
            if not text: continue
            try: number = parse_native_serial(text)
            except ValueError: continue  # Existing unselected malformed metadata remains untouched.
            if not number.known: continue
            if number.canonical in seen:
                raise ValueError("Result would contain duplicate database serials")
            seen[number.canonical] = address
        return SerialPopulationPlan(network, inventory, selected, source, _network_digest(source), document.toxml(), tuple(changes))

    def _verify(self, plan, *, original=False):
        expected = plan.source_xml if original else plan.candidate_xml
        if _network_canonical(self._xml(plan.network)) != _network_canonical(expected):
            raise RuntimeError("Database verification found changes outside the expected serial metadata")

    def _restore(self, plan, attempted):
        errors = []
        for change in reversed(attempted):
            path = plan.network + "/p/" + str(change.address)
            try:
                current = _document(self._xml(path))
                if _field(current, "OID") != change.oid:
                    raise RuntimeError("Unit OID changed; rollback cannot overwrite a different unit")
                reply = self.client.command_document("DBSETXML " + path, change.source_xml)
                if reply.code != 301 or reply.lines != ("301 OID=" + change.oid,):
                    raise RuntimeError("Native serial rollback did not confirm the original OID")
                if _canonical(self._xml(path)) != _canonical(change.source_xml):
                    raise RuntimeError("Restored unit failed XML verification")
            except Exception as error:
                errors.append(path + ": " + str(error))
                if getattr(self.client, "connected", None) is False: break
        return errors

    def apply(self, plan, *, backup_project=None):
        if not isinstance(plan, SerialPopulationPlan): raise ValueError("Expected a SerialPopulationPlan")
        network, project = _network_path(plan.network)
        current = self.plan(plan.inventory, units=plan.units)
        if current != plan: raise ValueError("Serial population plan is stale or has been modified")
        if not plan.changes:
            return {**plan.as_dict(), "updated": False, "backup_project": None, "project_saved": False}
        backup = _project(backup_project) if backup_project is not None else "B" + uuid4().hex[:7].upper()
        if backup.upper() == project.upper(): raise ValueError("Backup must be a separate project")
        try:
            self.projects.operation("save", project)
            self.projects.operation("copy", project, backup)
        except Exception as error:
            raise SerialPopulationError("Project backup failed; serial metadata was not changed", backup_project=backup) from error
        attempted = []
        try:
            self._check_runtime(plan.inventory)
            self._verify(plan, original=True)
            for change in plan.changes:
                # Check every identity immediately before its scalar metadata write.
                self._check_runtime(plan.inventory)
                path = network + "/p/" + str(change.address)
                if _canonical(self._xml(path)) != _canonical(change.source_xml):
                    raise ValueError("Database unit changed after planning")
                attempted.append(change)  # A lost reply can follow a successful write.
                reply = self.database.set(path + "/SerialNumber", change.new_serial)
                if reply.code != 200: raise RuntimeError("Native serial metadata update was not accepted")
                if _canonical(self._xml(path)) != _canonical(change.candidate_xml):
                    raise RuntimeError("Serial metadata update changed other unit data")
            self._verify(plan)
            self._check_runtime(plan.inventory)
            self.projects.operation("save", project)
            self._verify(plan)
        except Exception as error:
            rollback_errors = []
            if attempted:
                if getattr(self.client, "connected", None) is False:
                    rollback_errors.append("Native connection closed; automatic rollback was not attempted")
                else:
                    rollback_errors.extend(self._restore(plan, attempted))
                    if getattr(self.client, "connected", None) is not False:
                        try:
                            self.projects.operation("save", project)
                            self._verify(plan, original=True)
                        except Exception as rollback: rollback_errors.append("Project restoration: " + str(rollback))
            raise SerialPopulationError("Database serial update failed", backup_project=backup,
                                        rollback_errors=rollback_errors) from error
        return {**plan.as_dict(), "updated": True, "backup_project": backup, "project_saved": True}

    def populate(self, inventory, *, units=None, backup_project=None):
        return self.apply(self.plan(inventory, units=units), backup_project=backup_project)
