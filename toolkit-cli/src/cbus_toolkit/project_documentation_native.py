"""Read-only adapter for an explicitly selected saved native DBGETXML snapshot.

This is an XML projection, not a C-Gate repository/database reader.  It uses
the plain Installation/Project/Network/Application/Group/Level/Unit shape
already exercised by ``toolkit_database_csv_native`` and
``edlt_parent_metadata``.  The native framing receipt also demonstrates the
nested Interface shape; saved snapshots may instead carry the two direct
Network interface fields.  Mixing these representations is ambiguous.

NetVar and typed group/level variants are refused: the existing native eDLT
adapter reads NetVar, but its equivalence to the original Delphi documentor's
group collection has not been established.  Missing programming stays
missing.  This module does not initialize unit specifications or infer their
defaults, fetch any endpoint, or assess original generated-page parity.
"""
from __future__ import annotations

import hashlib
import re
from xml.dom import Node, minidom
from xml.parsers import expat

from .addressing import _container
from .project import ProjectError, _named_address
from .project_documentation import Application, Group, Level, Network, ProjectModel, Unit


FORMAT = "native-cgate-xml-snapshot"
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
_ENTITY_NAMES = frozenset({"Project", "Network", "Application", "Group", "NetVar", "Level", "Unit", "PP"})
_UNIT_FIELDS = ("Burden", "ClockGenEnable", "CatalogNumber", "SwitchablePowerSupplyEnabled")


def _elements(parent: Node) -> list[minidom.Element]:
    return [node for node in parent.childNodes if node.nodeType == Node.ELEMENT_NODE]


def _children(parent: Node, name: str) -> list[minidom.Element]:
    matches = []
    for node in _elements(parent):
        if (node.localName or node.tagName) == name:
            if node.namespaceURI or node.tagName != name:
                raise ProjectError(f"Native {name} fields must be unnamespaced")
            matches.append(node)
    return matches


def _scalar(parent: Node, name: str, *, required: bool = False) -> str:
    nodes = _children(parent, name)
    if len(nodes) > 1 or (required and not nodes):
        raise ProjectError(f"Expected {'exactly' if required else 'at most'} one native {name} field")
    if not nodes:
        return ""
    if any(node.nodeType not in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)
           for node in nodes[0].childNodes):
        raise ProjectError(f"Native {name} must be a scalar field")
    return "".join(node.data for node in nodes[0].childNodes)


def _byte(value: str, label: str) -> int:
    if re.fullmatch(r"0|[1-9][0-9]{0,2}", value) is None or int(value) > 255:
        raise ProjectError(f"Native {label} must be a canonical decimal byte")
    return int(value)


def _address(node: Node) -> int:
    return _byte(_scalar(node, "Address", required=True), f"{node.nodeName} Address")


def native_network_address(value: str) -> int | str:
    """Retain one exact native catalogue identity, without numeric aliases.

    Canonical byte spellings retain the established numeric report JSON.
    Other stored path components (including 0254, 256 and 0xff) are strings:
    they are independent database identities, not physical network numbers.
    """
    value = _named_address(value)
    if re.fullmatch(r"0|[1-9][0-9]{0,2}", value) and int(value) <= 255:
        return int(value)
    return value


def native_network_number(value: str) -> int:
    """Read the explicit byte property; never infer it from the Address.

    The captured native materialization contains the hexadecimal 0xff
    sentinel as well as decimal numbers. Other raw property values remain
    outside this snapshot report profile.
    """
    if re.fullmatch(r"0[xX][0-9a-fA-F]{1,2}", value):
        return int(value[2:], 16)
    return _byte(value, "NetworkNumber")


def native_network_report_address(value: str) -> int:
    """Project the source Address cache, independently of database identity.

    TCGateAddressAttribute uses exact NA -> 0, then SysUtils.StrToInt and an
    exception fallback of 255. The pinned System.@ValLong grammar accepts
    leading ASCII spaces, an optional sign and decimal/$/x/0x forms. Hex
    values use the original unsigned accumulator then signed i32 result.
    This projection supplies report headings/anchors, never selection or
    physical NetworkNumber lookup.
    """
    value = _named_address(value)
    if value == "NA":
        return 0
    match = re.fullmatch(r"([+-]?)(?:(?:\$|0[xX]|[xX])([0-9a-fA-F]+)|([0-9]+))", value.lstrip(" "))
    if match is None:
        return 255
    sign, hexadecimal, decimal = match.groups()
    if hexadecimal is not None:
        hexadecimal = hexadecimal.lstrip("0") or "0"
        if len(hexadecimal) > 8:
            return 255
        number = int(hexadecimal, 16)
        if sign == "-":
            number = (-number) & 0xffffffff
        return number if number < 0x80000000 else number - 0x100000000
    decimal = decimal.lstrip("0") or "0"
    if len(decimal) > 10:
        return 255
    number = int(decimal)
    if sign == "-":
        number = -number
    return number if -(2**31) <= number < 2**31 else 255


def _unique(items, label):
    addresses = [item.identity if label == "network" else item.address for item in items]
    if len(addresses) != len(set(addresses)):
        raise ProjectError(f"Ambiguous native snapshot: duplicate {label} address")
    # Original LoadAndSort puts the address-255 sentinel first for these
    # three managers. Unit and level addresses retain plain numeric order.
    sentinel_first = label in ("network", "application", "group")
    def key(item):
        address = item.identity if label == "network" else item.address
        return (address != 255, isinstance(address, str), address) if sentinel_first else (False, address)
    return sorted(items, key=key)


def _shape(node: minidom.Element, children: set[str]) -> None:
    """Reject typed/hidden entity collections rather than dropping their rows."""
    if node.namespaceURI:
        raise ProjectError("Native documentor entities must be unnamespaced")
    for index in range(node.attributes.length):
        attribute = node.attributes.item(index)
        if attribute.localName == "type":
            raise ProjectError("Typed native XML entities are not supported by the documentor")
    for child in _elements(node):
        name = child.localName or child.tagName
        if name in children:
            if child.namespaceURI:
                raise ProjectError(f"Native {name} entities must be unnamespaced")
            continue
        # Config contains scalar Application text, which is metadata, not an
        # application entity. Only inspect immediate children here.
        if name in _ENTITY_NAMES or re.match(r"(?:Group|Level|NetVar)(?:[A-Z]|s$)", name):
            raise ProjectError(f"Unsupported native documentor entity: {name}")
        if any(desc.localName in _ENTITY_NAMES or desc.tagName == "Address"
               for desc in child.getElementsByTagName("*")):
            if name not in ("Config", "Languages", "TagsDLT", "Interface", "InstallationDetail"):
                raise ProjectError(f"Unsupported nested native documentor collection: {name}")


def _parameters(unit: minidom.Element) -> dict[str, str]:
    values = {}
    for pp in _children(unit, "PP"):
        if set(pp.attributes.keys()) != {"Name", "Value"} or pp.childNodes:
            raise ProjectError("Native PP records require only Name and Value attributes")
        name = pp.getAttribute("Name")
        if not name or name != name.strip() or name in values:
            raise ProjectError("Native PP names must be nonempty, trimmed and unique")
        values[name] = pp.getAttribute("Value")
    return values


def _interface(network: minidom.Element) -> tuple[str, str]:
    nested = _children(network, "Interface")
    direct = _children(network, "InterfaceType") + _children(network, "InterfaceAddress")
    if len(nested) > 1 or (nested and direct):
        raise ProjectError("Ambiguous native network interface representation")
    parent = nested[0] if nested else network
    if nested:
        _shape(parent, set())
    return _scalar(parent, "InterfaceType"), _scalar(parent, "InterfaceAddress")


def build_native_model(snapshot: bytes) -> ProjectModel:
    """Build a documentation model from one explicit, standalone XML snapshot.

    Callers must select this adapter explicitly. Installation XML alone is
    not enough to distinguish native snapshots from legacy projects. Native
    project Address is validated, but a missing TagName is never replaced by
    that address. Stored PP strings and field presence are preserved exactly.
    """
    if type(snapshot) is not bytes or not 1 <= len(snapshot) <= MAX_SNAPSHOT_BYTES:
        raise ProjectError("Native XML snapshot must be bytes within the 16 MiB limit")
    if snapshot.startswith(b"SQLite format 3\x00"):
        raise ProjectError("Use a saved DBGETXML snapshot; SQL/SQLite databases are unsupported")
    try:
        text = snapshot.decode("utf-8-sig")
        document = _container(text, "Installation")
    except (UnicodeError, ValueError, expat.ExpatError) as error:
        raise ProjectError(f"Invalid native XML snapshot: {error}") from error
    root = document.documentElement
    _shape(root, {"Project"})
    projects = _children(root, "Project")
    if len(projects) != 1:
        raise ProjectError("Native XML must contain exactly one Project")
    project = projects[0]
    _shape(project, {"Network"})
    if re.fullmatch(r"[A-Za-z0-9_]{1,8}", _scalar(project, "Address", required=True)) is None:
        raise ProjectError("Native Project Address must contain 1..8 letters, digits or underscores")
    networks = []
    for network_node in _children(project, "Network"):
        _shape(network_node, {"Application", "Unit"})
        raw_address = _scalar(network_node, "Address", required=True)
        network_address = native_network_address(raw_address)
        report_address = native_network_report_address(raw_address)
        number = None
        if _children(network_node, "NetworkNumber"):
            number = native_network_number(_scalar(network_node, "NetworkNumber"))
        applications = []
        for application_node in _children(network_node, "Application"):
            _shape(application_node, {"Group"})
            groups = []
            for group_node in _children(application_node, "Group"):
                _shape(group_node, {"Level"})
                levels = []
                for level_node in _children(group_node, "Level"):
                    _shape(level_node, set())
                    if not level_node.hasAttribute("Value"):
                        raise ProjectError("Native Level must have a stored Value attribute")
                    levels.append(Level(_address(level_node), _scalar(level_node, "TagName"),
                                        value=_byte(level_node.getAttribute("Value"), "Level Value")))
                groups.append(Group(_address(group_node), _scalar(group_node, "TagName"),
                                    _scalar(group_node, "Description"), _unique(levels, "level")))
            applications.append(Application(
                _address(application_node), _scalar(application_node, "TagName"),
                _scalar(application_node, "Description"), _unique(groups, "group")))
        units = []
        for unit_node in _children(network_node, "Unit"):
            _shape(unit_node, {"PP"})
            unit_type = _scalar(unit_node, "UnitType", required=True)
            firmware = _scalar(unit_node, "FirmwareVersion", required=True)
            if not unit_type or unit_type != unit_type.strip() or not firmware or firmware != firmware.strip():
                raise ProjectError("Native UnitType and FirmwareVersion must be nonempty trimmed text")
            units.append(Unit(
                _address(unit_node), _scalar(unit_node, "TagName"), unit_type,
                _scalar(unit_node, "UnitName"), _scalar(unit_node, "SerialNumber"), firmware,
                _scalar(unit_node, "Description"), _parameters(unit_node),
                {name: _scalar(unit_node, name) for name in _UNIT_FIELDS if _children(unit_node, name)}))
        interface_type, interface_address = _interface(network_node)
        networks.append(Network(report_address, _scalar(network_node, "TagName"),
                                interface_type, interface_address, _unique(applications, "application"),
                                _unique(units, "unit"), number, network_address))
    if not networks:
        raise ProjectError("Native snapshot contains no networks")
    return ProjectModel(_scalar(project, "TagName"), _unique(networks, "network"),
                        digest=hashlib.sha256(snapshot).hexdigest(), size=len(snapshot), format=FORMAT)
