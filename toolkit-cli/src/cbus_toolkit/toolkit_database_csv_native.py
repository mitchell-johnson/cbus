"""Read-only native C-Gate XML adapter for the captured CSV projection profile."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from uuid import UUID
from xml.dom import Node

from .addressing import _container
from .toolkit_database_csv_projection import (
    CSVAreaObservation,
    CachedCSVGroup,
    CachedCSVProjection,
    CachedCSVUnit,
    project_cached_csv_unit,
)


PROFILE = 'cbus-toolkit-database-native-xml-projection-v1'


def _children(parent, name):
    return [node for node in parent.childNodes
            if node.nodeType == Node.ELEMENT_NODE and node.tagName == name]


def _field(parent, name):
    rows = _children(parent, name)
    if len(rows) != 1 or any(node.nodeType not in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)
                             for node in rows[0].childNodes):
        raise ValueError('Expected exactly one native scalar field: ' + name)
    return ''.join(node.data for node in rows[0].childNodes)


def _byte(value, label):
    if type(value) is not str or re.fullmatch(r'0|[1-9][0-9]{0,2}', value) is None:
        raise ValueError(label + ' must be a canonical decimal byte')
    number = int(value)
    if number > 255:
        raise ValueError(label + ' must be a canonical decimal byte')
    return number


def _oid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError('Expected a canonical native object ID') from None
    return value


def _path(value):
    if type(value) is not str:
        raise ValueError('Native XML unit path must be text')
    match = re.fullmatch(r'//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})/p/(0|[1-9][0-9]{0,2})', value)
    if match is None or int(match[2]) > 255 or int(match[3]) > 255:
        raise ValueError('Use //PROJECT/network/p/unit with byte network and unit addresses')
    return match[1], int(match[2]), int(match[3])


def _tokens(value, label, *, count=None):
    if type(value) is not str or not value:
        raise ValueError('Stored ' + label + ' must be a nonempty byte sequence')
    values = []
    for token in value.split(' '):
        if re.fullmatch(r'(?:0[xX][0-9A-Fa-f]{1,2}|[0-9]{1,3})', token) is None:
            raise ValueError('Stored ' + label + ' contains a malformed byte')
        number = int(token, 16) if token.lower().startswith('0x') else int(token)
        if number > 255:
            raise ValueError('Stored ' + label + ' contains a value outside byte range')
        values.append(number)
    if count is not None and len(values) != count:
        raise ValueError('Stored ' + label + ' has an unexpected element count')
    return tuple(values)


def _parameter(unit, name):
    rows = [node for node in _children(unit, 'PP') if node.getAttribute('Name') == name]
    if len(rows) != 1 or not rows[0].hasAttribute('Value'):
        raise ValueError('Expected exactly one stored native parameter: ' + name)
    return rows[0].getAttribute('Value')


def _one_by_address(parent, kind, address):
    rows = [node for node in _children(parent, kind)
            if _byte(_field(node, 'Address'), kind + ' address') == address]
    if len(rows) != 1:
        raise ValueError('Expected exactly one native ' + kind + ' at address ' + str(address))
    return rows[0]


@dataclass(frozen=True)
class NativeXMLCSVProjection:
    unit_path: str
    xml_sha256: str
    cached: CachedCSVProjection

    @property
    def complete(self):
        return self.cached.complete

    @property
    def report(self):
        return self.cached.report

    @property
    def stop_reason(self):
        return self.cached.stop_reason

    def as_dict(self):
        return {'format': PROFILE, 'complete': self.complete, 'unit_path': self.unit_path,
                'xml_sha256': self.xml_sha256, 'cached_projection': self.cached.as_dict(),
                'input_scope': 'one explicit native DBGETXML Installation snapshot',
                'native_database_loaded': True, 'native_database_mutated': False,
                'network_io_performed': False, 'physical_device_accessed': False,
                'original_instructions_executed': False,
                'missing_area_group_creation_supported': False}


def project_native_xml_unit(text, unit_path, *, columns):
    """Project one unit from the exact captured native XML profile."""
    project_name, network_address, unit_address = _path(unit_path)
    document = _container(text, 'Installation')
    root = document.documentElement
    projects = _children(root, 'Project')
    if len(projects) != 1 or _field(projects[0], 'Address') != project_name:
        raise ValueError('Native XML must contain exactly the selected project')
    network = _one_by_address(projects[0], 'Network', network_address)
    unit = _one_by_address(network, 'Unit', unit_address)
    unit_type = _field(unit, 'UnitType')
    firmware = _field(unit, 'FirmwareVersion')
    applications = _children(network, 'Application')
    if not applications:
        raise ValueError('Native network has no application cache')

    if unit_type.upper() == 'RELAY4' and firmware == '4.4':
        app_values = _tokens(_parameter(unit, 'Application'), 'Application', count=2)
        group_values = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress', count=16)
        area_values = _tokens(_parameter(unit, 'AreaGroupAddress'), 'AreaGroupAddress', count=1)
        primary_address, secondary_address = app_values
        primary = _one_by_address(network, 'Application', primary_address)
        secondary = '' if secondary_address == 255 else _field(
            _one_by_address(network, 'Application', secondary_address), 'TagName')
        group_addresses = tuple(value for value in group_values if value != 255)
        if group_addresses != tuple(range(1, 9)):
            raise ValueError('Captured native RELAY4 profile requires group addresses 1 through 8')
        area_address = area_values[0]
    elif unit_type == 'OWNED_UNKNOWN' and firmware == '4.4':
        if _children(unit, 'PP'):
            raise ValueError('Captured native generic profile requires no stored PP records')
        if len(applications) != 1:
            raise ValueError('Captured native generic profile requires exactly one application')
        primary, secondary = applications[0], ''
        _byte(_field(primary, 'Address'), 'Application address')
        group_addresses = tuple(range(1, 9))
        area_address = None
    else:
        raise ValueError('Native XML projection supports only captured RELAY4 4.4 and OWNED_UNKNOWN 4.4 profiles')

    groups = []
    seen_addresses = set()
    for node in _children(primary, 'Group'):
        address = _byte(_field(node, 'Address'), 'Group address')
        if address in seen_addresses:
            raise ValueError('Native primary application contains duplicate group addresses')
        seen_addresses.add(address)
        groups.append(CachedCSVGroup(_oid(_field(node, 'OID')), address,
                                     _field(node, 'TagName'), _field(node, 'OID')))
    by_address = {group.address: group for group in groups}
    if any(address not in by_address for address in group_addresses):
        raise ValueError('Native unit group reference is absent from the primary application cache')
    if area_address is not None and area_address not in by_address:
        raise ValueError('Native Area group is absent; original report creation requires an unperformed database mutation')
    if area_address is not None and area_address not in (12, 255):
        raise ValueError('Captured native RELAY4 profile supports existing Area12 or Area255')
    identities = tuple(by_address[address].identity for address in group_addresses)
    cached_unit = CachedCSVUnit(_oid(_field(unit, 'OID')), unit_address,
        _field(unit, 'UnitName'), _field(unit, 'TagName'), unit_type,
        _field(unit, 'CatalogNumber'), _field(unit, 'SerialNumber'), firmware,
        _field(primary, 'TagName'), secondary, identities)
    observations = () if area_address is None else (
        CSVAreaObservation(str(area_address)), CSVAreaObservation(str(area_address)))
    cached = project_cached_csv_unit(cached_unit, group_cache=tuple(groups),
                                     area_observations=observations, columns=columns)
    return NativeXMLCSVProjection(unit_path, hashlib.sha256(text.encode('utf-8')).hexdigest(), cached)


def loads_native_xml_projection(raw, unit_path, *, columns):
    if type(raw) is not bytes or not 1 <= len(raw) <= 8 * 1024 * 1024:
        raise ValueError('Native XML snapshot must be nonempty bytes within the 8 MiB bound')
    return project_native_xml_unit(raw.decode('utf-8'), unit_path, columns=columns)
