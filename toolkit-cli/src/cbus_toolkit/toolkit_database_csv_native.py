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
    _DIN_TYPES,
    _KEYE_TYPES,
    _NEOPRO_TYPES,
    family_profile,
    CSVWirelessLoader,
    _REMAP_TYPES,
    _SENSOR_TYPES,
    CSVAreaObservation,
    CachedCSVApplication,
    CachedCSVApplicationContext,
    CachedCSVGroup,
    CachedCSVProjection,
    CachedCSVUnit,
    project_cached_csv_unit,
    remap_indices,
)
from .toolkit_database_csv_registry import refusal_reason


PROFILE = 'cbus-toolkit-database-native-xml-projection-v1'


def native_xml_reply_text(reply, *, completion_codes=(344,)):
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
            elif code in completion_codes and started:
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
    if count == 0 and value == '':
        return ()
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


def _source_applications(unit, *, default_primary=56):
    """Bounded base FormatCgApplication input, before object resolution."""
    raw = _parameter(unit, 'Application')
    if raw == '':
        return default_primary, 255
    values = raw.split(' ')
    if len(values) not in (1, 2):
        raise ValueError('Source Application requires zero, one or two decimal byte addresses')
    addresses = tuple(_byte(value, 'Source Application') for value in values)
    return addresses if len(addresses) == 2 else (addresses[0], 255)


def _source_array(unit, parameter, count):
    stored = _tokens(_parameter(unit, parameter), parameter)
    if len(stored) > 32:
        raise ValueError('Source loader stored group array exceeds thirty-two slots')
    return (stored + (255,) * count)[:count]


def _last_group_addresses(unit, family, primary, secondary_node):
    """Exact final group-manager order, including consumed pre-report lookups."""
    parameter = family['group_parameter']
    if parameter is None:
        return (), 0
    if type(parameter) is tuple:
        return tuple(_tokens(_parameter(unit, name), name, count=1)[0]
                     for name in parameter), 0
    if parameter == 'temperature_mode':
        address = _byte(_field(primary, 'Address'), 'Primary Application')
        names = (('TemperatureGroup',) if address == 25 else
                 ('GroupAddress',) if address == 172 else () if address == 228 else
                 ('GroupAddress', 'EconomyGroup', 'ControlledGroup'))
        # In non-lighting modes the loader also resolves three unused primary
        # groups, although those references are omitted from the manager.
        if address in (25, 172, 228):
            _one_by_address(primary, 'Group', 255)
        return tuple(_tokens(_parameter(unit, name), name, count=1)[0]
                     for name in names), 0
    if parameter == 'iope':
        inputs = _source_array(unit, 'InputGroupAddress', 8)
        mask, = _tokens(_parameter(unit, 'SecondApplicationBlocks'),
                        'SecondApplicationBlocks', count=1)
        # LoadInputBlocks resolves secondary per-block references first. The
        # final report-manager reload deliberately uses primary for all eight.
        for index, address in enumerate(inputs):
            _one_by_address(secondary_node if mask & (1 << index) else primary,
                            'Group', address)
        outputs = _source_array(unit, 'OutputGroupAddress', family['output_channels'])
        return inputs + outputs, 0
    if parameter == 'wireless_channels':
        keys, = _tokens(_parameter(unit, 'InstalledKeys'), 'InstalledKeys', count=1)
        count, = _tokens(_parameter(unit, 'InstalledChannels'), 'InstalledChannels', count=1)
        raw_mask = _parameter(unit, 'ChannelRelayMask')
        if not re.fullmatch(r'[0-9]+|0[xX][0-9a-fA-F]+', raw_mask):
            raise ValueError('Stored ChannelRelayMask must be a bounded nonnegative integer')
        mask = int(raw_mask, 16 if raw_mask.lower().startswith('0x') else 10)
        routes = _tokens(_parameter(unit, 'OutputGroupSecondary'),
                         'OutputGroupSecondary', count=count)
        if not 0 <= keys <= 16 or not 0 <= count <= 16 or mask >= 1 << count:
            raise ValueError('Wireless fan installed counts or relay mask exceed the loader bounds')
        if any(route not in (0, 1) for route in routes):
            raise ValueError('Stored wireless secondary arrays must contain only zero or one')
        groups = _tokens(_parameter(unit, 'OutputGroup'), 'OutputGroup', count=count)
        return groups, sum(route << index for index, route in enumerate(routes))
    return _source_array(unit, parameter, family['blocks']), 0


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
    if type(text) is not str:
        raise ValueError('Native XML snapshot must be UTF-8 text within the 8 MiB bound')
    try:
        size = len(text.encode('utf-8'))
    except UnicodeEncodeError:
        raise ValueError('Native XML snapshot must be UTF-8 text within the 8 MiB bound') from None
    if not 1 <= size <= MAX_CAPTURE_BYTES:
        raise ValueError('Native XML snapshot must be UTF-8 text within the 8 MiB bound')
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
    family = family_profile(unit_type, firmware)
    wireless_loader = None
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
    elif unit_type in _KEYE_TYPES and firmware == '2.5.00':
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
    elif family is not None and family.get('last_source_model'):
        app_values = _source_applications(unit, default_primary=family['application_default'])
        primary = _one_by_address(network, 'Application', app_values[0])
        secondary_node = _one_by_address(network, 'Application', app_values[1])
        secondary = _field(secondary_node, 'TagName')
        group_addresses, secondary_mask = _last_group_addresses(
            unit, family, primary, secondary_node)
        group_applications = tuple(secondary_node if secondary_mask & (1 << index)
                                   else primary for index in range(len(group_addresses)))
        area_address = (_tokens(_parameter(unit, 'AreaGroupAddress'),
                                'AreaGroupAddress', count=1)[0] if family['has_area'] else None)
    elif family is not None and family.get('generic'):
        app_values = _source_applications(unit)
        primary = _one_by_address(network, 'Application', app_values[0])
        secondary_node = _one_by_address(network, 'Application', app_values[1])
        secondary = _field(secondary_node, 'TagName')
        group_addresses = group_applications = ()
        area_address = None
        secondary_mask = 0
    elif family is not None and family.get('source_model'):
        app_values = _source_applications(unit)
        primary = _one_by_address(network, 'Application', app_values[0])
        secondary_node = _one_by_address(network, 'Application', app_values[1])
        secondary = _field(secondary_node, 'TagName')
        count = family['blocks']
        parameter = family['group_parameter']
        if parameter == 'relay_logic':
            # The loader visits every physical channel's six logic masks, then
            # replaces the report manager with the six initialized logic groups.
            for logic in range(6):
                mask = _tokens(_parameter(unit, f'LogicGA{logic}Associations'),
                               f'LogicGA{logic}Associations')
                if len(mask) > 32:
                    raise ValueError('Relay logic association array exceeds thirty-two slots')
            stored = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress')
            if len(stored) > 32:
                raise ValueError('Relay stored group array exceeds thirty-two slots')
            group_values = (stored + (255,) * count)[:count]
        elif parameter == 'channel_fields':
            group_values = tuple(_tokens(_parameter(unit, f'Ch{index}GroupAddress'),
                f'Ch{index}GroupAddress', count=1)[0] for index in range(count))
        else:
            stored = _tokens(_parameter(unit, parameter), parameter)
            if len(stored) > 32:
                raise ValueError('Source loader stored group array exceeds thirty-two slots')
            # Native array access defaults absent trailing positions to255.
            # The complete cache must still establish every defaulted group.
            group_values = (stored + (255,) * count)[:count]
        secondary_mask = (_tokens(_parameter(unit, 'SecondApplicationBlocks'),
            'SecondApplicationBlocks', count=1)[0] if family['secondary_blocks'] else 0)
        if secondary_mask >> count or secondary_node is None and secondary_mask:
            raise ValueError('Source input secondary mask cannot resolve its declared Application')
        group_addresses = group_values
        group_applications = tuple(secondary_node if secondary_mask & (1 << index)
                                   else primary for index in range(count))
        area_address, = _tokens(_parameter(unit, 'AreaGroupAddress'), 'AreaGroupAddress', count=1)
    elif family is not None:
        app_values = _tokens(_parameter(unit, 'Application'), 'Application', count=2)
        if family['wireless']:
            # Init builds sixteen block references; the loader replaces the
            # report manager with those blocks, then every installed channel.
            # Channel tail failures remain fatal even beyond CSV column 16.
            installed_keys, = _tokens(_parameter(unit, 'InstalledKeys'), 'InstalledKeys', count=1)
            installed_channels, = _tokens(_parameter(unit, 'InstalledChannels'), 'InstalledChannels', count=1)
            relay_mask = _parameter(unit, 'ChannelRelayMask')
            if not re.fullmatch(r'[0-9]+|0[xX][0-9a-fA-F]+', relay_mask):
                raise ValueError('Stored ChannelRelayMask must be a bounded nonnegative integer')
            relay_mask = int(relay_mask, 16 if relay_mask.lower().startswith('0x') else 10)
            block_secondary = _tokens(_parameter(unit, 'BlockGroupSecondary'), 'BlockGroupSecondary', count=16)
            output_secondary = _tokens(_parameter(unit, 'OutputGroupSecondary'),
                                       'OutputGroupSecondary', count=installed_channels)
            if any(value not in (0, 1) for value in (*block_secondary, *output_secondary)):
                raise ValueError('Stored wireless secondary arrays must contain only zero or one')
            wireless_loader = CSVWirelessLoader(installed_keys, installed_channels, relay_mask,
                tuple(bool(value) for value in block_secondary), tuple(bool(value) for value in output_secondary))
            group_values = (_tokens(_parameter(unit, 'BlockGroup'), 'BlockGroup', count=16)
                            + _tokens(_parameter(unit, 'OutputGroup'), 'OutputGroup', count=installed_channels))
            secondary_mask = wireless_loader.secondary_mask
            area_address = None
        else:
            group_values = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress', count=family['blocks'])
            area_address, = _tokens(_parameter(unit, 'AreaGroupAddress'), 'AreaGroupAddress', count=1)
            secondary_mask = (_tokens(_parameter(unit, 'SecondApplicationBlocks'),
                                       'SecondApplicationBlocks', count=1)[0]
                              if family['secondary_blocks'] else 0)
        primary_address, secondary_address = app_values
        if secondary_address == 255 and secondary_mask:
            raise ValueError('CSV family secondary groups require a configured secondary application')
        primary = _one_by_address(network, 'Application', primary_address)
        secondary_node = (None if secondary_address == 255 else
                          _one_by_address(network, 'Application', secondary_address))
        secondary = '' if secondary_node is None else _field(secondary_node, 'TagName')
        group_addresses = group_values
        group_applications = tuple(
            secondary_node if secondary_mask & (1 << index) else primary
            for index in range(len(group_values)))
    elif unit_type in _DIN_TYPES and firmware == '2.7.00':
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
    elif unit_type in _REMAP_TYPES and firmware == '2.7.00':
        app_values = _tokens(_parameter(unit, 'Application'), 'Application', count=2)
        group_values = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress', count=16)
        area_values = _tokens(_parameter(unit, 'AreaGroupAddress'),
                              'AreaGroupAddress', count=1)
        primary_address, secondary_address = app_values
        if secondary_address != 255 or area_values != (255,):
            raise ValueError(f'Captured native {unit_type} profile requires unused secondary application and Area255')
        primary = _one_by_address(network, 'Application', primary_address)
        secondary = ''
        # LoadGroups first runs the DIN loader. The marshalling-box pass then
        # clears the unit group manager and appends the selected indices.
        group_addresses = group_values + tuple(
            group_values[index] for index in remap_indices(unit_type))
        group_applications = (primary,) * len(group_addresses)
        area_address = 255
    elif unit_type in _SENSOR_TYPES and firmware == _SENSOR_TYPES[unit_type][0]:
        app_values = _tokens(_parameter(unit, 'Application'), 'Application', count=2)
        group_values = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress', count=8)
        area_values = _tokens(_parameter(unit, 'AreaGroupAddress'), 'AreaGroupAddress', count=1)
        secondary_blocks = _tokens(
            _parameter(unit, 'SecondApplicationBlocks'), 'SecondApplicationBlocks', count=1)
        primary_address, secondary_address = app_values
        secondary_mask = secondary_blocks[0]
        if unit_type == 'SENPIROA' and (secondary_address != 255 or secondary_mask):
            raise ValueError('Captured native SENPIROA profile requires an unused secondary application')
        if unit_type != 'SENPIROA' and secondary_address == 255 and secondary_mask:
            raise ValueError(unit_type + ' secondary group blocks require a configured secondary application')
        if area_values != (255,):
            raise ValueError('Captured native sensor profile requires Area group 255')
        primary = _one_by_address(network, 'Application', primary_address)
        secondary_node = (None if secondary_address == 255 else
                          _one_by_address(network, 'Application', secondary_address))
        secondary = '' if secondary_node is None else _field(secondary_node, 'TagName')
        group_addresses = group_values
        group_applications = tuple(
            secondary_node if secondary_mask & (1 << index) else primary
            for index in range(len(group_addresses)))
        area_address = 255
    elif (unit_type == 'KEYGL5' and firmware == '5.5.00'
          and _field(unit, 'CatalogNumber') == '5055EDL'):
        # The original eDLT agent loads Widget6..Widget21 in this order. Its
        # group getter uses ByteValue6 for types 2/3/4/5/14/15/16, and 255
        # otherwise. Type 14 resolves in Enable (203); other types select
        # Primary/SecondaryApplication through ByteValue1 bit 7.
        app_values = _tokens(_parameter(unit, 'Application'), 'Application', count=2)
        primary_values = _tokens(_parameter(unit, 'PrimaryApplication'),
                                 'PrimaryApplication', count=1)
        secondary_values = _tokens(_parameter(unit, 'SecondaryApplication'),
                                   'SecondaryApplication', count=1)
        primary_address, secondary_address = app_values
        if (primary_values != (primary_address,) or
                secondary_values != (secondary_address,)):
            raise ValueError('KEYGL5 stored application fields disagree')
        if primary_address == 255:
            raise ValueError('KEYGL5 requires a resolved primary application')
        primary = _one_by_address(network, 'Application', primary_address)
        secondary_node = (None if secondary_address == 255 else
                          _one_by_address(network, 'Application', secondary_address))
        secondary = '' if secondary_node is None else _field(secondary_node, 'TagName')
        enable_node = None
        group_addresses = []
        group_applications = []
        for slot in range(6, 22):
            prefix = f'Widget{slot}'
            kind, = _tokens(_parameter(unit, prefix + 'WidgetType'),
                            prefix + 'WidgetType', count=1)
            control, = _tokens(_parameter(unit, prefix + 'WidgetByteValue1'),
                               prefix + 'WidgetByteValue1', count=1)
            stored_group, = _tokens(_parameter(unit, prefix + 'WidgetByteValue6'),
                                    prefix + 'WidgetByteValue6', count=1)
            if kind == 14:
                if enable_node is None:
                    enable_node = _one_by_address(network, 'Application', 203)
                application = enable_node
            elif control & 128:
                if secondary_node is None:
                    raise ValueError('KEYGL5 secondary widget requires a configured secondary application')
                application = secondary_node
            else:
                application = primary
            group_applications.append(application)
            group_addresses.append(stored_group if kind in (2, 3, 4, 5, 14, 15, 16)
                                   else 255)
        group_addresses = tuple(group_addresses)
        group_applications = tuple(group_applications)
        area_address = None
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
        raise ValueError('Native XML projection supports source-backed Key, Neo, NeoPro and wireless factory ranges plus captured RELAY4 4.4, KEYE1-4/KEYEIR1-4, '
                         'DIN-output and marshalling-box 2.7.00, SENPIROA/SENPIRIA 2.4.00, SENPIRIB 2.2.00, '
                         'KEYGL5 5.5.00/5055EDL and OWNED_UNKNOWN 4.4 profiles; '
                         + refusal_reason(unit_type, firmware))

    groups = []
    application_groups = {}
    # Retain both configured Application caches and their authoritative
    # membership. NeoPro Area lookup must not depend on cache traversal order.
    cache_applications = ((primary, *((secondary_node,) if secondary_node is not None else ()),
                           *group_applications)
                          if family is not None else group_applications)
    for application in dict.fromkeys(cache_applications):
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
    if (area_address is not None and area_address not in (12, 13, 255)
            and not (family or {}).get('source_model')):
        raise ValueError('Captured native RELAY4 profile supports existing Area12, Area13 or Area255')
    identities = tuple(application_groups[application][address].identity
                       for application, address in zip(group_applications, group_addresses))
    unit_oid = _optional_oid(unit)
    cached_unit = CachedCSVUnit(unit_oid or unit_path, unit_address,
        _field(unit, 'UnitName'), _field(unit, 'TagName'), unit_type,
        _field(unit, 'CatalogNumber'), _field(unit, 'SerialNumber'), firmware,
        _field(primary, 'TagName'), secondary,
        identities[16:] if unit_type in _REMAP_TYPES else identities,
        loader_associations=identities if unit_type in _REMAP_TYPES else ())
    observations = () if area_address is None else (
        CSVAreaObservation(str(area_address)), CSVAreaObservation(str(area_address)))
    context = None
    if family is not None:
        def application_identity(node):
            address = _byte(_field(node, 'Address'), 'Application address')
            return _optional_oid(node) or f'//{project_name}/{network_address}/{address}'

        context = CachedCSVApplicationContext(application_identity(primary),
            None if secondary_node is None else application_identity(secondary_node),
            secondary_mask, tuple(CachedCSVApplication(application_identity(node),
                _byte(_field(node, 'Address'), 'Application address'), _field(node, 'TagName'),
                tuple(group.identity for group in by_address.values()))
                for node, by_address in application_groups.items()))
    cached = project_cached_csv_unit(cached_unit, group_cache=tuple(groups),
        area_observations=observations, columns=columns, application_context=context,
        wireless_loader=wireless_loader)
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


def _project_path(value):
    if type(value) is not str or re.fullmatch(r'//[A-Za-z0-9_]{1,8}', value) is None:
        raise ValueError('Use //PROJECT with a one-to-eight character project identifier')
    return value[2:]


def _selection_project(*, unit_paths=None, network_path=None, project_path=None):
    """Validate a selection without XML or I/O and return its one project name."""
    if sum(value is not None for value in (unit_paths, network_path, project_path)) != 1:
        raise ValueError('Select exactly one ordered unit selection, network or project')
    if project_path is not None:
        return _project_path(project_path)
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
    project_path: str | None = None

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
            'project_path': self.project_path,
            'unit_order': ('project_network_document_unit_address_ascending'
                           if self.project_path is not None else
                           'network_unit_address_ascending' if self.network_path is not None
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


def project_native_xml_selection(text, *, unit_paths=None, network_path=None,
                                 project_path=None, columns):
    """Project an ordered selection, one network or every project network.

    Network selections follow numeric unit address. The original network
    constructor sets the report unit manager to custom address-ascending sort,
    and AsCSV enumerates that manager by index. Project selection retains
    network document order because Toolkit's report action selects one network.
    This source-backed ordering does not establish full native runtime parity.
    Every selected unit must project successfully before a report is returned.
    """
    project_name = _selection_project(unit_paths=unit_paths, network_path=network_path,
                                      project_path=project_path)
    selected = validate_columns(columns)
    project = _snapshot_project(text, project_name)
    xml_sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if network_path is not None or project_path is not None:
        networks = (_children(project, 'Network') if project_path is not None else
                    [_one_by_address(project, 'Network', _network_path(network_path)[1])])
        if len(networks) > 256:
            raise ValueError('Project network selection exceeds 256 networks')
        seen_networks = set()
        selected_paths = []
        for network in networks:
            address = _byte(_field(network, 'Address'), 'Network address')
            if address in seen_networks:
                raise ValueError('Native project contains duplicate network addresses')
            seen_networks.add(address)
            units = _children(network, 'Unit')
            if len(selected_paths) + len(units) > MAX_UNITS:
                raise ValueError('Native unit selection exceeds 4096 units')
            addresses = tuple(_byte(_field(unit, 'Address'), 'Unit address') for unit in units)
            if len(set(addresses)) != len(addresses):
                raise ValueError('Native network contains duplicate unit addresses')
            selected_paths.extend(f'//{project_name}/{address}/p/{unit}'
                                  for unit in sorted(addresses))
        unit_paths = tuple(selected_paths)

    projections = []
    identities = set()
    for path in unit_paths:
        try:
            projection = _project_native_xml_unit(project, path, columns=selected,
                                                  xml_sha256=xml_sha256)
            if not projection.complete or projection.report is None:
                raise ValueError('Native XML projection stopped: ' + str(projection.stop_reason))
            identity = projection.cached.unit.identity
            if identity in identities:
                raise ValueError('Selected units contain duplicate object identities')
            identities.add(identity)
            projections.append(projection)
        except ValueError as error:
            raise ValueError(path + ': ' + str(error)) from error
    # Preserve the literal caught per-Unit error row as well as normal rows.
    # All projections complete before one bounded report is returned.
    header = document_database_csv((), columns=selected).rows[0]
    report = DatabaseCSV(selected, (header, *(item.report.rows[1]
        for item in projections)), len(projections))
    return NativeXMLCSVSelection(unit_paths, network_path, xml_sha256, tuple(projections),
                                 report, project_path)


def loads_native_xml_selection(raw, *, unit_paths=None, network_path=None,
                               project_path=None, columns):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CAPTURE_BYTES:
        raise ValueError('Native XML snapshot must be nonempty bytes within the 8 MiB bound')
    return project_native_xml_selection(raw.decode('utf-8'), unit_paths=unit_paths,
                                        network_path=network_path, project_path=project_path,
                                        columns=columns)
