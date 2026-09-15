"""C-Gate-backed native project operations.

The vendor server owns SQLite migrations and business rules. This module
never edits its database files directly and never opens networks implicitly.
"""
from __future__ import annotations

import re


def _command(client, command):
    response = client.command(command)
    if getattr(response, "code", 200) >= 400:
        raise RuntimeError("Native operation did not complete: " + response.final)
    return response


def _token(value, label="argument"):
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} is required")
    value = str(value)
    if not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{label} must be one nonempty C-Gate token")
    return value


def _tail(value):
    if value is None:
        raise ValueError("C-Gate value cannot be None")
    value = str(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("C-Gate values cannot contain control characters")
    return value


def _project(value):
    value = _token(value, "project name")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,8}", value):
        raise ValueError("Project names must contain 1..8 letters, digits or underscores")
    return value


def _address(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError("Entity address must be an integer in 0..255")
    return str(value)


class NativeProjects:
    def __init__(self, client):
        self.client = client

    def list(self):
        return _command(self.client, "PROJECT LIST")

    def directory(self):
        return _command(self.client, "PROJECT DIR")

    def operation(self, action, name, other=None):
        action = action.lower()
        if action in ("new", "use", "load", "save", "close", "delete", "repair"):
            if other is not None:
                raise ValueError(f"PROJECT {action.upper()} takes one project name")
            command = f"PROJECT {action.upper()} {_project(name)}"
        elif action in ("copy", "rename"):
            command = f"PROJECT {action.upper()} {_project(name)} {_project(other)}"
        elif action in ("archive", "restore"):
            command = f"PROJECT {action.upper()} {_project(name)} {_token(other, 'server file path')}"
        else:
            raise ValueError(f"Unknown native project operation: {action}")
        response = _command(self.client, command)
        if getattr(response, "code", 200) != 200:
            raise RuntimeError("Native project operation did not complete: " + response.final)
        return response


class NativeDatabase:
    def __init__(self, client):
        self.client = client

    def get(self, path, *, xml=False):
        return _command(self.client, f"{'DBGETXML' if xml else 'DBGET'} {_token(path, 'database path')}")

    def create_network(self, project, address, name, interface_type, interface_address):
        """Create all required network fields, then load its closed runtime model."""
        if interface_type.lower() not in ("serial", "cni", "bridge"):
            raise ValueError("Interface type must be Serial, Cni or Bridge")
        project = _project(project)
        command = (f"DBCREATENET {_address(address)} {_token(name, 'network name')} "
                   f"{interface_type} {_token(interface_address, 'interface address')}")
        NativeProjects(self.client).operation("use", project)
        created = _command(self.client, command)
        _command(self.client, "NET LOAD DB")
        return created

    def create_unit(self, network, address, name, unit_type, firmware, *, catalog_number=None):
        """Create a native database unit and initialize its full-sized PP memory.

        Loading the new database unit lets C-Gate allocate memory from its
        specification. PP NEW incorrectly fixes memory at 2048 bytes, which
        prevents initializing devices such as eDLT and architectural dimmers.
        No physical unit is read or written by this workflow.
        """
        from .programming import Programmer
        network = _token(network, "network address")
        match = re.fullmatch(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})", network)
        if match is None or int(match[2]) > 255:
            raise ValueError("Use a fully qualified network address such as //TEST/254")
        address_text = _address(address)
        unit_type = _tail(unit_type)
        if not unit_type.strip():
            raise ValueError("Unit type cannot be blank")
        firmware = _token(firmware, "firmware")
        if catalog_number is not None:
            catalog_number = _tail(catalog_number)
        path = network + "/p/" + address_text
        created = self.add(network, "unit", address, name)
        try:
            for field, value in (("UnitType", unit_type), ("UnitName", unit_type), ("FirmwareVersion", firmware)):
                self.set(path + "/" + field, value)
            if catalog_number is not None:
                self.set(path + "/CatalogNumber", catalog_number)
            with Programmer(self.client).load(network, "/db" + path) as session:
                session.reset_defaults()
                values = session.values()
                if "UnitAddress" in values:
                    session.set("UnitAddress", address_text)
                if "Project" in values:
                    session.set("Project", match[1])
                saved = session.save_to_source()
            return {"unit": path, "unit_type": unit_type, "firmware": firmware,
                    "catalog_number": catalog_number, "parameter_count": len(values),
                    "created": created, "saved": saved}
        except (ValueError, OSError, RuntimeError) as error:
            try:
                self.delete(path)
            except (ValueError, OSError, RuntimeError) as cleanup:
                raise RuntimeError(f"Unit initialization failed: {error}; unable to remove new database unit {path}: {cleanup}") from error
            raise

    def add(self, parent, kind, address, name):
        if kind.lower() not in ("network", "application", "group", "unit", "level", "netvar"):
            raise ValueError("Expected network, application, group, unit, level or netvar")
        name = _tail(name)
        if not name.strip():
            raise ValueError("Tag name cannot be blank")
        element = "NetVar" if kind.lower() == "netvar" else kind.title()
        response = _command(self.client, f"DBADDSAFE {_token(parent)} {element} {_address(address)} {name}")
        if kind.lower() == "level":
            self._initialize_level(response, address)
        return response

    def _initialize_level(self, response, value):
        # Native DBADDSAFE sets Level/Address but leaves Level/Value NULL,
        # violating the C-Gate 3 SQLite constraint at PROJECT SAVE. DBCOPYSAFE
        # likewise keeps the old Value when assigning a different Address.
        matches = [re.fullmatch(r"301[- ]OID=([0-9a-fA-F-]{36})", line) for line in response.lines]
        identifiers = [match[1] for match in matches if match]
        if len(identifiers) != 1:
            raise RuntimeError("New level did not return one OID; unable to initialize its value")
        oid = identifiers[0]
        # !OID addressing also works for NetVar levels, whose numeric Level
        # paths trigger a native Group-only cast exception.
        path = "!" + oid
        identity = self.get(path + "/OID")
        if identity.code != 342 or identity.final.rsplit("=", 1)[-1] != oid:
            raise RuntimeError(f"New level {oid} could not be uniquely resolved at {path}")
        try:
            self.set(path + "/Value", value)
        except (ValueError, OSError, RuntimeError) as error:
            try:
                self.delete(path)
            except (ValueError, OSError, RuntimeError) as cleanup:
                raise RuntimeError(f"Level initialization failed: {error}; unable to remove new level {oid}: {cleanup}") from error
            raise

    def set(self, parameter_path, value):
        return _command(self.client, f"DBSETSAFE {_token(parameter_path)} {_tail(value)}")

    def copy(self, source, parent, address, name):
        from .programming import xml_text
        from xml.etree import ElementTree as ET
        name = _tail(name)
        if not name.strip():
            raise ValueError("Tag name cannot be blank")
        source, parent, address_text = _token(source), _token(parent), _address(address)
        document = xml_text(self.get(source, xml=True))
        if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
            raise ValueError("Unsupported source XML declarations")
        try:
            kind = ET.fromstring(document).tag.rsplit("}", 1)[-1]
        except ET.ParseError as error:
            raise RuntimeError("Unable to determine native copy source type") from error
        response = _command(self.client, f"DBCOPYSAFE {source} {parent} {address_text} {name}")
        if kind == "Level":
            self._initialize_level(response, address)
        return response

    def delete(self, path):
        return _command(self.client, f"DBDELETE {_token(path)}")

    def validate(self, path):
        return _command(self.client, f"DBVALIDATE {_token(path)}")

    def rename_network(self, path, address):
        """Rename only the database layer; runtime NET RENAME is separate."""
        path = _token(path, "network path")
        match = re.fullmatch(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})", path)
        if not match or int(match[2]) > 255:
            raise ValueError("Use a fully qualified network path such as //PROJECT/254")
        destination = _address(address)
        if int(match[2]) == address:
            raise ValueError("New network address must differ from its current address")
        NativeProjects(self.client).operation("use", match[1])
        return _command(self.client, f"DBRENAMENETSAFE {int(match[2])} {destination}")
