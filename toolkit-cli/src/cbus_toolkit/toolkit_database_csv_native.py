"""Read-only native C-Gate XML adapter for the captured CSV projection profile."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from uuid import UUID
from xml.dom import Node

from .addressing import _container
from .toolkit_database_csv import (DatabaseCSV, MAX_CAPTURE_BYTES, MAX_UNITS,
                                   document_database_csv, validate_columns)
from .toolkit_database_csv_projection import (
    CSVAreaObservation,
    CachedCSVGroup,
    CachedCSVProjection,
    CachedCSVUnit,
    project_cached_csv_unit,
)


PROFILE = 'cbus-toolkit-database-native-xml-projection-v1'


def native_xml_reply_text(reply):
    """Extract all XML payload lines from a native DBGETXML response."""
    lines = getattr(reply, 'lines', None)
    if not isinstance(lines, (tuple, list)) or any(type(line) is not str for line in lines):
        raise ValueError('Native response does not expose bounded text lines')
    payload = []
    started = False
    for line in lines:
        match = re.fullmatch(r'(?:\[[^]\r\n]+\]\s*)?([0-9]{3})[- ](.*)', line)
        if match is not None:
            code = int(match[1])
            if code == 347:
                started = True
                payload.append(match[2])
            elif code == 344 and started:
                break
            elif started:
                raise ValueError('Native XML response contains an unexpected status line')
        elif started:
            payload.append(line)
    if not payload:
        raise ValueError('Native response does not contain an XML snippet')
    return '\n'.join(payload)


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


def _optional_oid(parent):
    rows = _children(parent, 'OID')
    if not rows:
        return ''
    if len(rows) != 1:
        raise ValueError('Expected at most one native OID field')
    return _oid(_field(parent, 'OID'))


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
    project_name, _network_address, _unit_address = _path(unit_path)
    project = _snapshot_project(text, project_name)
    return _project_native_xml_unit(project, unit_path, columns=columns,
                                   xml_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())


def _snapshot_project(text, project_name):
    document = _container(text, 'Installation')
    root = document.documentElement
    projects = _children(root, 'Project')
    if len(projects) != 1 or _field(projects[0], 'Address') != project_name:
        raise ValueError('Native XML must contain exactly the selected project')
    return projects[0]


def _project_native_xml_unit(project, unit_path, *, columns, xml_sha256):
    project_name, network_address, unit_address = _path(unit_path)
    network = _one_by_address(project, 'Network', network_address)
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
        secondary_node = (None if secondary_address == 255 else
                          _one_by_address(network, 'Application', secondary_address))
        secondary = '' if secondary_node is None else _field(secondary_node, 'TagName')
        if group_values != (*range(1, 9), *(255 for _ in range(8))):
            raise ValueError('Captured native RELAY4 profile requires groups 1 through 8 followed by eight unused slots')
        group_addresses = group_values
        group_applications = (primary,) * len(group_addresses)
        area_address = area_values[0]
    elif unit_type in ('KEYE1', 'KEYE2', 'KEYE3') and firmware == '2.5.00':
        app_values = _tokens(_parameter(unit, 'Application'), 'Application', count=2)
        group_values = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress', count=9)
        area_values = _tokens(_parameter(unit, 'AreaGroupAddress'), 'AreaGroupAddress', count=1)
        secondary_blocks = _tokens(
            _parameter(unit, 'SecondApplicationBlocks'), 'SecondApplicationBlocks', count=1)
        primary_address, secondary_address = app_values
        secondary_mask = secondary_blocks[0]
        if secondary_address == 255 and secondary_mask:
            raise ValueError('KEYE secondary group blocks require a configured secondary application')
        if area_values != (255,):
            raise ValueError('Captured native KEYE profile requires Area group 255')
        primary = _one_by_address(network, 'Application', primary_address)
        secondary_node = (None if secondary_address == 255 else
                          _one_by_address(network, 'Application', secondary_address))
        secondary = '' if secondary_node is None else _field(secondary_node, 'TagName')
        group_addresses = group_values
        group_applications = tuple(
            secondary_node if index < 8 and secondary_mask & (1 << index) else primary
            for index in range(len(group_addresses)))
        area_address = 255
    elif unit_type in ('DIMDN8', 'RELDN12') and firmware == '2.7.00':
        app_values = _tokens(_parameter(unit, 'Application'), 'Application', count=2)
        group_values = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress', count=16)
        area_values = _tokens(_parameter(unit, 'AreaGroupAddress'), 'AreaGroupAddress', count=1)
        primary_address, secondary_address = app_values
        if secondary_address != 255:
            raise ValueError('Captured native DIN profile requires an unused secondary application')
        if area_values != (255,):
            raise ValueError('Captured native DIN profile requires Area group 255')
        primary = _one_by_address(network, 'Application', primary_address)
        secondary = ''
        group_addresses = group_values
        group_applications = (primary,) * len(group_addresses)
        area_address = 255
    elif unit_type == 'SENPIROA' and firmware == '2.4.00':
        app_values = _tokens(_parameter(unit, 'Application'), 'Application', count=2)
        group_values = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress', count=8)
        area_values = _tokens(_parameter(unit, 'AreaGroupAddress'), 'AreaGroupAddress', count=1)
        secondary_blocks = _tokens(
            _parameter(unit, 'SecondApplicationBlocks'), 'SecondApplicationBlocks', count=1)
        primary_address, secondary_address = app_values
        if secondary_address != 255 or secondary_blocks != (0,):
            raise ValueError('Captured native SENPIROA profile requires an unused secondary application')
        if area_values != (255,):
            raise ValueError('Captured native SENPIROA profile requires Area group 255')
        primary = _one_by_address(network, 'Application', primary_address)
        secondary = ''
        group_addresses = group_values
        group_applications = (primary,) * len(group_addresses)
        area_address = 255
    elif unit_type == 'OWNED_UNKNOWN' and firmware == '4.4':
        if _children(unit, 'PP'):
            raise ValueError('Captured native generic profile requires no stored PP records')
        if len(applications) != 1:
            raise ValueError('Captured native generic profile requires exactly one application')
        primary, secondary = applications[0], ''
        _byte(_field(primary, 'Address'), 'Application address')
        group_addresses = tuple(range(1, 9))
        group_applications = (primary,) * len(group_addresses)
        area_address = None
    else:
        raise ValueError('Native XML projection supports only captured RELAY4 4.4, KEYE1/2/3 2.5.00, DIMDN8/RELDN12 2.7.00, SENPIROA 2.4.00 and OWNED_UNKNOWN 4.4 profiles')

    groups = []
    application_groups = {}
    for application in dict.fromkeys(group_applications):
        application_address = _byte(_field(application, 'Address'), 'Application address')
        by_address = {}
        for node in _children(application, 'Group'):
            address = _byte(_field(node, 'Address'), 'Group address')
            if address in by_address:
                raise ValueError('Native application contains duplicate group addresses')
            oid = _optional_oid(node)
            identity = oid or f'//{project_name}/{network_address}/{application_address}/{address}'
            group = CachedCSVGroup(identity, address, _field(node, 'TagName'), oid)
            groups.append(group)
            by_address[address] = group
        application_groups[application] = by_address
    missing = [(application, address) for application, address
               in zip(group_applications, group_addresses)
               if address not in application_groups[application]]
    if missing:
        raise ValueError('Native unit group reference is absent from its selected application cache')
    primary_groups = application_groups[primary]
    if area_address is not None and area_address not in primary_groups:
        raise ValueError('Native Area group is absent; original report creation requires an unperformed database mutation')
    if area_address is not None and area_address not in (12, 13, 255):
        raise ValueError('Captured native RELAY4 profile supports existing Area12, Area13 or Area255')
    identities = tuple(application_groups[application][address].identity
                       for application, address in zip(group_applications, group_addresses))
    unit_oid = _optional_oid(unit)
    cached_unit = CachedCSVUnit(unit_oid or unit_path, unit_address,
        _field(unit, 'UnitName'), _field(unit, 'TagName'), unit_type,
        _field(unit, 'CatalogNumber'), _field(unit, 'SerialNumber'), firmware,
        _field(primary, 'TagName'), secondary, identities)
    observations = () if area_address is None else (
        CSVAreaObservation(str(area_address)), CSVAreaObservation(str(area_address)))
    cached = project_cached_csv_unit(cached_unit, group_cache=tuple(groups),
                                     area_observations=observations, columns=columns)
    return NativeXMLCSVProjection(unit_path, xml_sha256, cached)


def loads_native_xml_projection(raw, unit_path, *, columns):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CAPTURE_BYTES:
        raise ValueError('Native XML snapshot must be nonempty bytes within the 8 MiB bound')
    return project_native_xml_unit(raw.decode('utf-8'), unit_path, columns=columns)


def _network_path(value):
    if type(value) is not str:
        raise ValueError('Native XML network path must be text')
    match = re.fullmatch(r'//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})', value)
    if match is None or int(match[2]) > 255:
        raise ValueError('Use //PROJECT/network with a byte network address')
    return match[1], int(match[2])


def _selection_project(*, unit_paths=None, network_path=None):
    """Validate a selection without XML or I/O and return its one project name."""
    if (unit_paths is None) == (network_path is None):
        raise ValueError('Select exactly one ordered unit selection or one network')
    if network_path is not None:
        return _network_path(network_path)[0]
    if type(unit_paths) is not tuple or not 1 <= len(unit_paths) <= MAX_UNITS:
        raise ValueError('Unit selection must be a nonempty exact tuple of at most 4096 paths')
    projects = {_path(path)[0] for path in unit_paths}
    if len(set(unit_paths)) != len(unit_paths):
        raise ValueError('Unit selection contains duplicate paths')
    if len(projects) != 1:
        raise ValueError('Unit selection must belong to one project snapshot')
    return next(iter(projects))


@dataclass(frozen=True)
class NativeXMLCSVSelection:
    unit_paths: tuple[str, ...]
    network_path: str | None
    xml_sha256: str
    projections: tuple[NativeXMLCSVProjection, ...]
    report: DatabaseCSV

    @property
    def complete(self):
        return True

    @property
    def stop_reason(self):
        return None

    def as_dict(self):
        return {
            'format': 'cbus-toolkit-database-native-xml-selection-v1',
            'complete': True, 'unit_paths': list(self.unit_paths),
            'network_path': self.network_path,
            'unit_order': ('snapshot_document' if self.network_path is not None
                           else 'explicit_selection'),
            'xml_sha256': self.xml_sha256,
            'projections': [item.as_dict() for item in self.projections],
            'report': self.report.as_dict(),
            'input_scope': 'one explicit native DBGETXML Installation snapshot',
            'native_database_loaded': True, 'native_database_mutated': False,
            'network_io_performed': False, 'physical_device_accessed': False,
            'original_instructions_executed': False,
            'original_manager_enumeration_verified': False,
            'missing_area_group_creation_supported': False,
        }


def project_native_xml_selection(text, *, unit_paths=None, network_path=None, columns):
    """Project an ordered unit selection or all units in one snapshot network.

    Network selection preserves XML document order. This composes the admitted
    per-unit profiles; it does not infer Toolkit's manager enumeration order.
    Every selected unit must project successfully before a report is returned.
    """
    project_name = _selection_project(unit_paths=unit_paths, network_path=network_path)
    selected = validate_columns(columns)
    project = _snapshot_project(text, project_name)
    xml_sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if network_path is not None:
        network_address = _network_path(network_path)[1]
        network = _one_by_address(project, 'Network', network_address)
        units = _children(network, 'Unit')
        if len(units) > MAX_UNITS:
            raise ValueError('Network unit selection exceeds 4096 units')
        addresses = tuple(_byte(_field(unit, 'Address'), 'Unit address') for unit in units)
        if len(set(addresses)) != len(addresses):
            raise ValueError('Native network contains duplicate unit addresses')
        unit_paths = tuple(f'{network_path}/p/{address}' for address in addresses)

    projections = []
    identities = set()
    for path in unit_paths:
        try:
            projection = _project_native_xml_unit(project, path, columns=selected,
                                                  xml_sha256=xml_sha256)
            if not projection.complete or projection.cached.csv_unit is None:
                raise ValueError('Native XML projection stopped: ' + str(projection.stop_reason))
            identity = projection.cached.unit.identity
            if identity in identities:
                raise ValueError('Selected units contain duplicate object identities')
            identities.add(identity)
            projections.append(projection)
        except ValueError as error:
            raise ValueError(path + ': ' + str(error)) from error
    report = document_database_csv(tuple(item.cached.csv_unit for item in projections),
                                    columns=selected)
    return NativeXMLCSVSelection(unit_paths, network_path, xml_sha256, tuple(projections), report)


def loads_native_xml_selection(raw, *, unit_paths=None, network_path=None, columns):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CAPTURE_BYTES:
        raise ValueError('Native XML snapshot must be nonempty bytes within the 8 MiB bound')
    return project_native_xml_selection(raw.decode('utf-8'), unit_paths=unit_paths,
                                        network_path=network_path, columns=columns)
