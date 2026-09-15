"""Database unit readdressing and conservative, read-only serial reconciliation.

Only C-Gate's database is changed. Physical readdressing, occupied-address
displacement and bridge/gateway topology changes are separate workflows.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from uuid import UUID, uuid4
from xml.dom import Node, minidom
from xml.parsers import expat

from .cgate import CGateError
# These helpers preserve native Unit XML, including opaque metadata. Keeping
# one canonicalization definition also keeps rollback checks consistent.
from .classic_replacement import _canonical, _document, _field, _set, _digest, _path, _shape
from .native import NativeDatabase, NativeProjects, _address, _project
from .programming import Programmer, xml_text


class AddressingError(RuntimeError):
    def __init__(self, message, *, backup_project=None, rollback_errors=()):
        self.details = {"backup_project": backup_project, "rollback_errors": list(rollback_errors)}
        super().__init__(message)


def _network_path(value):
    match = re.fullmatch(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})", str(value))
    if not match or int(match[2]) > 255:
        raise ValueError("Use a fully qualified network path such as //PROJECT/254")
    return f"//{match[1]}/{int(match[2])}", match[1]


def _container(text, root):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 16 * 1024 * 1024:
        raise ValueError("Native XML exceeds 16 MiB or is not text")
    parser = expat.ParserCreate()
    def reject(*_): raise ValueError("DTD/entity declarations are unsupported")
    parser.StartDoctypeDeclHandler = reject
    parser.Parse(text, True)
    document = minidom.parseString(text)
    if document.documentElement.tagName != root:
        raise ValueError("Expected native " + root + " XML")
    return document


def _unit_documents(network_xml):
    root = _container(network_xml, "Network").documentElement
    return [_document(node.toxml()) for node in root.childNodes
            if node.nodeType == Node.ELEMENT_NODE and node.tagName == "Unit"]


def _pp_node(document, name):
    nodes = [n for n in document.documentElement.childNodes
             if n.nodeType == Node.ELEMENT_NODE and n.tagName == "PP" and n.getAttribute("Name") == name]
    if len(nodes) != 1:
        raise ValueError("Expected exactly one stored PP parameter " + name)
    if not nodes[0].hasAttribute("Value"):
        raise ValueError("Stored PP parameter has no Value: " + name)
    return nodes[0]


@dataclass(frozen=True)
class UnitIdentity:
    address: int
    unit_type: str
    serial: str = ""

    def __post_init__(self):
        _address(self.address)
        for name, value in (("unit_type", self.unit_type), ("serial", self.serial)):
            if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError(name + " must be text without control characters")
        if not self.unit_type or self.unit_type != self.unit_type.strip():
            raise ValueError("Unit type must be nonempty and have no surrounding whitespace")
        if self.serial != self.serial.strip():
            raise ValueError("Serial must have no surrounding whitespace")

    def as_dict(self):
        return {"address": self.address, "unit_type": self.unit_type, "serial": self.serial}


def match_serials(database_units, network_units, *, native_serials=False):
    """Report exact serial matches; never infer compatibility or move any unit.

    By default serials are opaque strings, preserving the original comparator.
    native_serials=True compares bounded native decimal-dot components and
    excludes both zero and all-ones placeholders. Duplicate serials, different
    types and occupied destinations are reported explicitly.
    """
    database, network = tuple(database_units), tuple(network_units)
    if type(native_serials) is not bool: raise ValueError("native_serials must be a boolean")
    for label, units in (("database", database), ("network", network)):
        if any(not isinstance(u, UnitIdentity) for u in units):
            raise ValueError("Inventories must contain UnitIdentity values")
        if len({u.address for u in units}) != len(units):
            raise ValueError("Duplicate " + label + " unit addresses")
    if native_serials:
        # Lazy import avoids coupling the original opaque comparator to native
        # parsing at module import time. The default behavior stays unchanged.
        from .serials import parse_native_serial
        invalid = {"database": [], "network": []}
        def normalized(units, label):
            result = []
            for unit in units:
                serial = ""
                if unit.serial:
                    try:
                        value = parse_native_serial(unit.serial)
                        serial = value.canonical if value.known else ""
                    except ValueError as error:
                        invalid[label].append({**unit.as_dict(), "error": str(error)})
                result.append(UnitIdentity(unit.address, unit.unit_type, serial))
            return result
        report = match_serials(normalized(database, "database"), normalized(network, "network"))
        originals = {"database": {u.address: u.as_dict() for u in database},
                     "network": {u.address: u.as_dict() for u in network}}
        for row in report["matches"]:
            for label in ("database", "network"):
                row[label] = [originals[label][u["address"]] for u in row[label]]
        for label in ("database", "network"):
            report["unidentified_" + label] = [originals[label][u["address"]] for u in report["unidentified_" + label]]
            report["invalid_" + label + "_serials"] = invalid[label]
        report["serial_comparison"] = "native decimal-dot components; zero/all-ones placeholders excluded; original text retained"
        report["native_serials"] = True
        return report
    def usable(serial): return serial not in ("", "00000000.0000")
    serials = sorted({u.serial for u in database + network if usable(u.serial)})
    rows = []
    for serial in serials:
        db = [u for u in database if u.serial == serial]
        net = [u for u in network if u.serial == serial]
        row = {"serial": serial, "database": [u.as_dict() for u in db], "network": [u.as_dict() for u in net]}
        if len(db) > 1 or len(net) > 1: status = "ambiguous_serial"
        elif not db: status = "network_only"
        elif not net: status = "database_only"
        elif db[0].unit_type != net[0].unit_type: status = "type_mismatch"
        elif db[0].address == net[0].address: status = "aligned"
        else:
            status = "different_address"
            row["database_to_network"] = {"from": db[0].address, "to": net[0].address,
                "destination_occupied": any(u.address == net[0].address for u in database)}
            row["network_to_database"] = {"from": net[0].address, "to": db[0].address,
                "destination_occupied": any(u.address == db[0].address for u in network)}
        row["status"] = status
        rows.append(row)
    return {"format": "cbus-serial-match-report-v1", "matches": rows,
            "unidentified_database": [u.as_dict() for u in database if not usable(u.serial)],
            "unidentified_network": [u.as_dict() for u in network if not usable(u.serial)],
            "applied": False, "hardware_programmed": False,
            "serial_comparison": "exact opaque strings; blank and native placeholder excluded"}


@dataclass(frozen=True)
class AddressPlan:
    source: str
    destination: str
    oid: str
    source_xml: str
    source_hash: str
    source_parameters: tuple[tuple[str, str], ...]
    parameters: tuple[tuple[str, str], ...]
    candidate_xml: str

    def as_dict(self):
        return {"format": "cbus-database-unit-readdress-plan-v1", "source": self.source,
                "destination": self.destination, "oid": self.oid, "source_hash": self.source_hash,
                "changes": {"Address": int(self.destination.rsplit("/", 1)[1]),
                            "PP.UnitAddress": dict(self.parameters)["UnitAddress"]},
                "metadata_retained": True, "oid_retained": True,
                "readdressed": False, "hardware_programmed": False}


class DatabaseAddressing:
    def __init__(self, client):
        self.client = client
        self.database, self.projects, self.programmer = NativeDatabase(client), NativeProjects(client), Programmer(client)

    def _xml(self, path):
        result = xml_text(self.database.get(path, xml=True))
        _document(result)
        return result

    def _optional_xml(self, path):
        try: return self._xml(path)
        except CGateError as error:
            if error.response.code == 401: return None
            raise

    def inventory(self, network):
        network, project = _network_path(network)
        self.projects.operation("use", project)
        documents = _unit_documents(xml_text(self.database.get(network, xml=True)))
        result = tuple(UnitIdentity(int(_field(d, "Address")), _field(d, "UnitType"), _field(d, "SerialNumber")) for d in documents)
        if len({u.address for u in result}) != len(result):
            raise ValueError("Database has duplicate unit addresses")
        return tuple(sorted(result, key=lambda u: u.address))

    def _snapshot(self, path):
        with self.programmer.load(path.rsplit("/p/", 1)[0], "/db" + path) as session:
            return tuple(sorted(session.values().items()))

    def _validate(self, path):
        reply = self.database.validate(path)
        if reply.code != 233 or any(not re.fullmatch(r"233[- ][^:]+: Valid", line) for line in reply.lines):
            raise ValueError("Native database validation failed: " + " | ".join(reply.lines))

    def _topology(self, project, source, unit_type):
        if unit_type == "BRIDGE" or unit_type.startswith("WGATE"):
            raise ValueError("Bridge/wireless gateway readdress requires coupled topology changes")
        project_xml = xml_text(self.database.get("//" + project, xml=True))
        document = _container(project_xml, "Installation")
        for node in document.getElementsByTagName("InterfaceType"):
            if "".join(c.data for c in node.childNodes if c.nodeType == Node.TEXT_NODE).lower() == "bridge":
                raise ValueError("Projects with bridge connections require coupled topology handling")
        # OID references remain valid. An opaque textual path reference cannot
        # be rewritten without knowing its schema, so leave the project intact.
        if source in project_xml:
            raise ValueError("Project contains a textual unit-path reference requiring explicit reconciliation")

    def plan(self, source, new_address):
        source, project, network_address, address = _path(source)
        new_address = int(_address(new_address))
        if new_address == address: raise ValueError("New unit address must differ from its current address")
        network = f"//{project}/{network_address}"
        destination = network + "/p/" + str(new_address)
        self.projects.operation("use", project)
        if any(u.address == new_address for u in self.inventory(network)):
            raise ValueError("Destination unit address is occupied")
        source_xml = self._xml(source)
        document = _document(source_xml)
        if _field(document, "Address") != str(address):
            raise ValueError("Source XML Address differs from its database path")
        oid = _field(document, "OID")
        try: UUID(oid)
        except ValueError as error: raise ValueError("Source unit has no valid OID") from error
        self._topology(project, source, _field(document, "UnitType"))
        self._validate(source)
        _pp_node(document, "UnitAddress")
        with self.programmer.load(network, "/db" + source) as session:
            before = session.values()
            if "UnitAddress" not in before or int(before["UnitAddress"], 0) != address:
                raise ValueError("Existing PP UnitAddress does not match the database address")
            session.set("UnitAddress", str(new_address))
            after = session.values()
            if int(after["UnitAddress"], 0) != new_address or {k: v for k, v in before.items() if k != "UnitAddress"} != {k: v for k, v in after.items() if k != "UnitAddress"}:
                raise ValueError("Native UnitAddress edit changed other programming parameters")
        _set(document, "Address", str(new_address))
        _pp_node(document, "UnitAddress").setAttribute("Value", after["UnitAddress"])
        return AddressPlan(source, destination, oid, source_xml, _digest(source_xml), tuple(sorted(before.items())),
                           tuple(sorted(after.items())), document.toxml())

    def _verify(self, plan):
        actual = self._xml(plan.destination)
        if _canonical(actual) != _canonical(plan.candidate_xml):
            raise RuntimeError("Native readdress changed metadata or stored programming")
        if self._optional_xml(plan.source) is not None:
            raise RuntimeError("Old database unit address remains occupied after readdress")
        if self._snapshot(plan.destination) != plan.parameters:
            raise RuntimeError("Native readdress programming verification failed")
        self._validate(plan.destination)

    def _restore(self, plan):
        source, destination = self._optional_xml(plan.source), self._optional_xml(plan.destination)
        source_oid = _field(_document(source), "OID") if source else None
        destination_oid = _field(_document(destination), "OID") if destination else None
        if source_oid not in (None, plan.oid):
            raise RuntimeError("Original unit address is now occupied by another OID; rollback cannot overwrite it")
        owned = [path for path, oid in ((plan.source, source_oid), (plan.destination, destination_oid)) if oid == plan.oid]
        if len(owned) != 1:
            raise RuntimeError("Cannot uniquely locate the original unit OID for rollback")
        self.client.command_document("DBSETXML " + owned[0], plan.source_xml)
        if _canonical(self._xml(plan.source)) != _canonical(plan.source_xml) or self._snapshot(plan.source) != plan.source_parameters:
            raise RuntimeError("Restored unit failed XML/programming verification")
        if destination_oid == plan.oid and self._optional_xml(plan.destination) is not None:
            raise RuntimeError("Moved unit remains at destination after rollback")

    def apply(self, plan, *, backup_project=None):
        if not isinstance(plan, AddressPlan): raise ValueError("Expected an AddressPlan")
        _source, project, _network, _unit = _path(plan.source)
        destination, destination_project, destination_network, destination_unit = _path(plan.destination)
        if destination_project != project or destination_network != _network:
            raise ValueError("Unit readdress must remain in the same network")
        current = self.plan(plan.source, destination_unit)
        if current != plan:
            raise ValueError("Readdress plan is stale or has been modified")
        backup = _project(backup_project) if backup_project is not None else "B" + uuid4().hex[:7].upper()
        if backup.upper() == project.upper(): raise ValueError("Backup must be a separate project")
        try:
            self.projects.operation("save", project)
            self.projects.operation("copy", project, backup)
        except Exception as error:
            raise AddressingError("Project backup failed; unit was not readdressed", backup_project=backup) from error
        attempted = False
        try:
            # Recheck after the backup operation, before the one XML mutation.
            if _canonical(self._xml(plan.source)) != _canonical(plan.source_xml) or self._snapshot(plan.source) != plan.source_parameters:
                raise ValueError("Source changed while creating backup")
            if self._optional_xml(destination) is not None:
                raise ValueError("Destination became occupied while creating backup")
            attempted = True  # A lost response can follow a successful write.
            self.client.command_document("DBSETXML " + plan.source, plan.candidate_xml)
            self._verify(plan)
            self.projects.operation("save", project)
            self._verify(plan)
        except Exception as error:
            rollback_errors = []
            if attempted:
                try:
                    self._restore(plan)
                    self.projects.operation("save", project)
                except Exception as rollback_error: rollback_errors.append(str(rollback_error))
            raise AddressingError("Database unit readdress failed", backup_project=backup, rollback_errors=rollback_errors) from error
        return {**plan.as_dict(), "readdressed": True, "project_saved": True,
                "backup_project": backup, "metadata_verified": True, "parameters_verified": True}

    def readdress(self, source, new_address, *, backup_project=None):
        return self.apply(self.plan(source, new_address), backup_project=backup_project)


def _network_canonical(text):
    root = _container(text, "Network").documentElement
    attributes = tuple(sorted((root.attributes.item(i).name, root.attributes.item(i).value)
                              for i in range(root.attributes.length)))
    children = []
    for child in root.childNodes:
        if child.nodeType == Node.TEXT_NODE and not child.data.strip(): continue
        # Native PP and scalar unit fields have unordered storage. Unknown
        # nested metadata keeps its order through the common Unit canonicalizer.
        children.append(("unit", _canonical(child.toxml())) if child.nodeType == Node.ELEMENT_NODE and child.tagName == "Unit" else _shape(child))
    return root.tagName, attributes, tuple(sorted(children, key=repr))


_RUNTIME_FIELDS = ("Name", "Type", "InterfaceAddress", "NetworkType", "InterfaceState", "TargetInterfaceState",
                   "SyncState", "State", "Options", "AutoSync", "AutoUnravel", "AutoUpdate", "DefaultApplication",
                   "EventLevel", "FastResponse", "QuickDetect", "ResponseDelay", "Retries", "ShortSync", "SyncTime", "TxEnable")


@dataclass(frozen=True)
class NetworkAddressPlan:
    source: str
    destination: str
    oid: str
    source_xml: str
    source_hash: str
    candidate_xml: str
    runtime: tuple[tuple[str, str], ...]
    unit_parameters: tuple[tuple[int, tuple[tuple[str, str], ...]], ...]

    def as_dict(self):
        return {"format": "cbus-closed-network-readdress-plan-v1", "source": self.source,
                "destination": self.destination, "oid": self.oid, "source_hash": self.source_hash,
                "unit_count": len(self.unit_parameters), "changes": {
                    "Address": int(self.destination.rsplit("/", 1)[1]),
                    "NetworkNumber": int(self.destination.rsplit("/", 1)[1]),
                    "runtime.Name": self.destination.rsplit("/", 1)[1]},
                "programming_policy": "preserve every unit PP value, including NetworkAddress",
                "closed_network_only": True, "readdressed": False, "hardware_programmed": False}


class NetworkAddressing:
    """Pair database/runtime renames for closed, independent wired networks.

    The exact Toolkit non-bridge path uses both rename commands and changes
    NetworkNumber; it does not edit unit PP NetworkAddress. This operation
    verifies all unit PP values and retains that behavior.
    """
    def __init__(self, client):
        self.client = client
        self.database, self.projects = NativeDatabase(client), NativeProjects(client)
        self.units = DatabaseAddressing(client)

    def _xml(self, path):
        result = xml_text(self.database.get(path, xml=True))
        _container(result, "Network")
        return result

    def _optional_xml(self, path):
        try: return self._xml(path)
        except CGateError as error:
            if error.response.code == 401: return None
            raise

    def _runtime(self, path):
        response = self.client.command("GET " + path + " *")
        values = {}
        for line in response.lines:
            match = re.fullmatch(r"300[- ]([^:]+): ([^=]+)=(.*)", line)
            if not match or match[1].upper() != path.upper() or match[2] in values:
                raise ValueError("Unexpected or duplicate native network runtime property")
            values[match[2]] = match[3]
        if any(name not in values for name in _RUNTIME_FIELDS):
            raise ValueError("Native network runtime is missing required configuration/state fields")
        return tuple((name, values[name]) for name in _RUNTIME_FIELDS)

    def _optional_runtime(self, path):
        try: return self._runtime(path)
        except CGateError as error:
            if error.response.code == 401: return None
            raise

    @staticmethod
    def _closed(runtime):
        values = dict(runtime)
        if values["InterfaceState"] != "closed" or values["TargetInterfaceState"] != "closed" or values["SyncState"] != "idle":
            raise ValueError("Network readdress requires a closed interface, closed target state and idle synchronization")

    def _snapshots(self, network, network_xml):
        documents = _unit_documents(network_xml)
        addresses = [int(_field(document, "Address")) for document in documents]
        if len(set(addresses)) != len(addresses): raise ValueError("Network has duplicate database unit addresses")
        return tuple((address, self.units._snapshot(network + "/p/" + _address(address))) for address in sorted(addresses))

    def _topology(self, project, source):
        text = xml_text(self.database.get("//" + project, xml=True))
        document = _container(text, "Installation")
        for node in document.getElementsByTagName("InterfaceType"):
            value = "".join(c.data for c in node.childNodes if c.nodeType == Node.TEXT_NODE)
            if value.lower() == "bridge":
                raise ValueError("Bridge connections require coupled topology changes")
        for node in document.getElementsByTagName("UnitType"):
            value = "".join(c.data for c in node.childNodes if c.nodeType == Node.TEXT_NODE)
            if value == "BRIDGE" or value.startswith("WGATE"):
                raise ValueError("Bridge/wireless gateway units require coupled topology changes")
        if re.search(re.escape(source) + r"(?:/|[^0-9]|$)", text):
            raise ValueError("Project contains a textual network-path reference requiring explicit reconciliation")

    def plan(self, source, new_address):
        source, project = _network_path(source)
        new_address = int(_address(new_address))
        old_address = int(source.rsplit("/", 1)[1])
        if new_address == old_address: raise ValueError("New network address must differ from its current address")
        destination = "//" + project + "/" + str(new_address)
        self.projects.operation("use", project)
        if self._optional_xml(destination) is not None or self._optional_runtime(destination) is not None:
            raise ValueError("Destination network address is occupied in the database or runtime")
        original = self._xml(source)
        document = _container(original, "Network")
        if _field(document, "Address") != str(old_address) or _field(document, "NetworkNumber") != str(old_address):
            raise ValueError("Database network Address/NetworkNumber differs from its path")
        oid = _field(document, "OID")
        try: UUID(oid)
        except ValueError as error: raise ValueError("Network has no valid OID") from error
        self._topology(project, source)
        self.units._validate(source)
        runtime = self._runtime(source)
        self._closed(runtime)
        properties = dict(runtime)
        if properties["Name"] != str(old_address): raise ValueError("Runtime network name differs from its path")
        interfaces = document.getElementsByTagName("Interface")
        if len(interfaces) != 1: raise ValueError("Expected one native network interface")
        interface = minidom.parseString(interfaces[0].toxml())
        if _field(interface, "InterfaceType").lower() not in ("cni", "serial") or properties["NetworkType"] != "Wired":
            raise ValueError("Only independent wired CNI/serial networks are supported")
        if properties["Type"].lower() != _field(interface, "InterfaceType").lower() or properties["InterfaceAddress"] != _field(interface, "InterfaceAddress"):
            raise ValueError("Runtime and database interface definitions differ")
        parameters = self._snapshots(source, original)
        _set(document, "Address", str(new_address))
        _set(document, "NetworkNumber", str(new_address))
        digest = hashlib.sha256(repr(_network_canonical(original)).encode("utf-8")).hexdigest()
        return NetworkAddressPlan(source, destination, oid, original, digest, document.toxml(), runtime, parameters)

    @staticmethod
    def _expected_runtime(plan, destination=True):
        address = (plan.destination if destination else plan.source).rsplit("/", 1)[1]
        return tuple((name, address if name == "Name" else value) for name, value in plan.runtime)

    def _verify(self, plan):
        if _network_canonical(self._xml(plan.destination)) != _network_canonical(plan.candidate_xml):
            raise RuntimeError("Network readdress changed database metadata or stored PP values")
        if self._optional_xml(plan.source) is not None or self._optional_runtime(plan.source) is not None:
            raise RuntimeError("Old network address remains in the database or runtime")
        runtime = self._runtime(plan.destination)
        self._closed(runtime)
        if runtime != self._expected_runtime(plan): raise RuntimeError("Renamed runtime configuration differs from plan")
        if self._snapshots(plan.destination, plan.candidate_xml) != plan.unit_parameters:
            raise RuntimeError("Network readdress changed unit programming values")
        self.units._validate(plan.destination)

    def _restore(self, plan):
        errors = []
        try:
            source, destination = self._optional_runtime(plan.source), self._optional_runtime(plan.destination)
            if source is None and destination == self._expected_runtime(plan):
                self._closed(destination)
                self.client.command("NET RENAME " + plan.destination + " " + plan.source.rsplit("/", 1)[1])
            elif source != plan.runtime or destination is not None:
                raise RuntimeError("Cannot uniquely identify the closed original runtime for rollback")
        except Exception as error: errors.append("Runtime rollback: " + str(error))
        try:
            source, destination = self._optional_xml(plan.source), self._optional_xml(plan.destination)
            source_oid = _field(_container(source, "Network"), "OID") if source else None
            destination_oid = _field(_container(destination, "Network"), "OID") if destination else None
            if source_oid not in (None, plan.oid): raise RuntimeError("Original network address is occupied by another OID")
            owned = [path for path, oid in ((plan.source, source_oid), (plan.destination, destination_oid)) if oid == plan.oid]
            if len(owned) != 1: raise RuntimeError("Cannot uniquely locate the original database network OID")
            if owned[0] == plan.destination:
                self.database.rename_network(plan.destination, int(plan.source.rsplit("/", 1)[1]))
            if _network_canonical(self._xml(plan.source)) != _network_canonical(plan.source_xml):
                self.client.command_document("DBSETXML " + plan.source, plan.source_xml)
            if _network_canonical(self._xml(plan.source)) != _network_canonical(plan.source_xml):
                raise RuntimeError("Restored network database metadata differs from original")
        except Exception as error: errors.append("Database rollback: " + str(error))
        try:
            if self._runtime(plan.source) != plan.runtime or self._optional_runtime(plan.destination) is not None:
                raise RuntimeError("Restored runtime differs from original")
            if self._optional_xml(plan.destination) is not None or self._snapshots(plan.source, plan.source_xml) != plan.unit_parameters:
                raise RuntimeError("Restored network programming differs from original")
            self.projects.operation("save", _network_path(plan.source)[1])
        except Exception as error: errors.append("Rollback verification/save: " + str(error))
        return errors

    def apply(self, plan, *, backup_project=None):
        if not isinstance(plan, NetworkAddressPlan): raise ValueError("Expected a NetworkAddressPlan")
        source, project = _network_path(plan.source)
        destination, destination_project = _network_path(plan.destination)
        if project != destination_project: raise ValueError("Network must remain in the same project")
        new_address = int(destination.rsplit("/", 1)[1])
        if self.plan(source, new_address) != plan:
            raise ValueError("Network readdress plan is stale or has been modified")
        backup = _project(backup_project) if backup_project is not None else "B" + uuid4().hex[:7].upper()
        if backup.upper() == project.upper(): raise ValueError("Backup must be a separate project")
        try:
            self.projects.operation("save", project)
            self.projects.operation("copy", project, backup)
        except Exception as error:
            raise AddressingError("Project backup failed; network was not readdressed", backup_project=backup) from error
        attempted = False
        try:
            if self.plan(source, new_address) != plan:
                raise ValueError("Network changed while creating backup")
            attempted = True
            self.database.rename_network(source, new_address)
            self.client.command("NET RENAME " + source + " " + str(new_address))
            self._verify(plan)
            self.projects.operation("save", project)
            self._verify(plan)
        except Exception as error:
            rollback_errors = self._restore(plan) if attempted else []
            raise AddressingError("Network readdress failed", backup_project=backup, rollback_errors=rollback_errors) from error
        return {**plan.as_dict(), "readdressed": True, "project_saved": True, "backup_project": backup,
                "database_runtime_consistent": True, "metadata_verified": True, "parameters_verified": True,
                "runtime_configuration_verified": True}

    def readdress(self, source, new_address, *, backup_project=None):
        return self.apply(self.plan(source, new_address), backup_project=backup_project)
