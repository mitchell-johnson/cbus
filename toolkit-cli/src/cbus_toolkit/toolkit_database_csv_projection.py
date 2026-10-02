"""Original-backed cached unit projection for Toolkit database CSV rows.

This is the finite cached-object boundary captured from Toolkit 1.18.  It does
not parse a project or access native storage.  The admitted RELAY4 and KEYE
profiles replay the two Area getter loads and group lookup/reference changes;
the RELAY4 profile also models the captured optional missing-unused-group save.
The KEYGL5 profile consumes sixteen already-resolved functional widget groups.
The marshalling-box remap profiles (RELDN8, RELDN8SP and RELMB8) retain both
their sixteen initial DIN associations and the eight or nine marshalling-box
reload associations. The latter replace the group manager list and are the
CSV-visible groups.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json

from .toolkit_database_csv import (
    COLUMN_LABELS,
    CSVGroupValue,
    CSVUnitValues,
    DatabaseCSV,
    _text,
    document_database_csv,
    validate_columns,
)
from .toolkit_database_csv_registry import refusal_reason, registrations_for
from .toolkit_database_csv_last_profiles import (
    LAST_CLASSES, last_profile, temperature_group_count,
)


PROFILE = 'cbus-toolkit-database-cached-projection-v1'
IDENTITY_PROFILE = 'cbus-toolkit-database-cached-projection-v2'
WIRELESS_PROFILE = 'cbus-toolkit-database-cached-projection-v3'
SOURCE_PROFILE = 'cbus-toolkit-database-cached-projection-v4'
# These are exact-class factory agents and literal VMT loader bindings, not
# parent-class guesses. The committed completion vector pins every range.
_SOURCE_INPUT_AGENTS = {
    'TBCNC4CGateAgent': (4, False),
    'TCBusPirSensorInputCGateAgent': (4, False),
    'TCBusMultisensorCGateAgent': (8, False),
    'TCBusST7MultisensorCGateAgent': (8, True),
    'TCBusST7LightLevelSensorCGateAgent': (8, True),
    'TCBusSurfaceMountMultisensorCGateAgent': (8, True),
    'TCBusSurfaceMountPIRSensorCGateAgent': (8, True),
    'TCBusSurfaceMountLightLevelSensorCGateAgent': (8, True),
    'TCBusCouplerProInputCGateAgent': (8, True),
    'TCBusCouplerVieoInputCGateAgent': (8, True),
    'TCBusDynamicLabelInputCGateAgent': (8, True),
}
_SOURCE_OUTPUT_AGENTS = {
    'TDIMDNUXCGateAgent': 'GroupAddress',
    'TBusPoweredDinRailOutputCGateAgent': 'GroupAddress',
    'TCBusFanControllerCGateAgent': 'GroupAddress',
    'TDIMARXCGateAgent': 'ChannelOutputGroup',
    'TDIMPR12CGateAgent': 'GroupAddress',
    'TDIMDD4CGateAgent': 'channel_fields',
    'TDIMDD8CGateAgent': 'channel_fields',
    'TCBus1RelayCGateAgent': 'relay_logic',
}
_SOURCE_CHANNELS = {
    'TDIMDU4': 4, 'TDIMPR3A': 3, 'TDIMPR6A': 6, 'TDIMPR12A': 12,
    'TRELSM8': 8, 'TRELDF1': 1,
    'TDIMAR3': 3, 'TDIMAR6': 6, 'TDIMAR12': 12, 'TDIMPR12': 12,
    'TDIMDD4': 4, 'TDIMDD4F': 4, 'TDIMDD8': 8, 'TDIMDD8F': 8,
    'TRELAY1': 1, 'TRELAY2': 2, 'TDIMMER4': 4, 'TAN_OUT4': 4,
}

_SOURCE_GENERIC_CLASSES = {
    'TCBusBurden': 'TCBusNonUnitCGateAgent',
    'TCBusCable': 'TCBusNonUnitCGateAgent',
    'TNCCInputUnit': 'TNCCInputCGateAgent',
    'TNCCOutputUnit': 'TNCCOutputCGateAgent',
    'TPCI2': 'TCBusPCI2CGateAgent',
    'TPCI3': 'TCBusPCICGateAgent',
    'TPCI4': 'TCBusPCICGateAgent',
    'TPCI4DALI': 'TCBusPCICGateAgent',
    'TPCI4NoBurden': 'TCBusPCICGateAgent',
    'TPCI4PC_CTA': 'TCBusPC_CTACGateAgent',
    'TPCI4_PC_CTB': 'TCBusPCICGateAgent',
    'TPCI4_PC_CTBL': 'TCBusPCICGateAgent',
    'TPCIMIND2': 'TCBusPCICGateAgent',
    'TPC_PACA': 'TCBusPC_PACACGateAgent',
    'TPC_WHAM': 'TCBusPC_WHAMCGateAgent',
    'TPowerSupply': 'TPowerSupplyCGateAgent',
    'TSYSDAL2': 'TSYSDAL2CGateAgent',
}
FAMILY_AGENTS = ('TCBusKeyInputCGateAgent', 'TCBusNeoInputCGateAgent',
                 'TCBusNeoProInputCGateAgent', 'TCBusWirelessInputUnitCGateAgent',
                 'TCBusWirelessInputUnit8RemotesCGateAgent',
                 'TCBusWirelessDecoratorInputUnitCGateAgent',
                 *_SOURCE_INPUT_AGENTS, *_SOURCE_OUTPUT_AGENTS,
                 *dict.fromkeys(_SOURCE_GENERIC_CLASSES.values()),
                 *dict.fromkeys(row['agent'] for row in LAST_CLASSES.values()))


def family_profile(unit_type, firmware):
    """Select one literal factory range, never guess across overlapping rows."""
    rows = registrations_for(unit_type, firmware)
    candidates = [row for row in rows if row[4] in FAMILY_AGENTS
                  and not (row[4] == 'TCBus1RelayCGateAgent' and unit_type.upper() == 'RELAY4')
                  and (row[4] not in _SOURCE_GENERIC_CLASSES.values()
                       or _SOURCE_GENERIC_CLASSES.get(row[3]) == row[4])]
    if not candidates:
        return None
    # registrations_for deliberately returns all rows on an invalid version.
    from .toolkit_database_csv_registry import _firmware
    if _firmware(firmware) is None or len(rows) != 1:
        raise ValueError('CSV family firmware must select exactly one static registration')
    row, = candidates
    last = last_profile(row[3], row[4])
    if last is not None:
        return last
    if _SOURCE_GENERIC_CLASSES.get(row[3]) == row[4]:
        return {'class': row[3], 'agent': row[4], 'wireless': False,
                'blocks': 0, 'has_area': False, 'secondary_blocks': False,
                'source_model': True, 'generic': True, 'group_parameter': None}
    if row[4] in _SOURCE_INPUT_AGENTS:
        blocks, secondary = _SOURCE_INPUT_AGENTS[row[4]]
        return {'class': row[3], 'agent': row[4], 'wireless': False,
                'blocks': blocks, 'has_area': True, 'secondary_blocks': secondary,
                'source_model': True, 'group_parameter': 'GroupAddress'}
    if row[4] in _SOURCE_OUTPUT_AGENTS:
        return {'class': row[3], 'agent': row[4], 'wireless': False,
                'blocks': 6 if row[4] == 'TCBus1RelayCGateAgent' else _SOURCE_CHANNELS[row[3]], 'has_area': True,
                'secondary_blocks': False, 'source_model': True,
                'group_parameter': _SOURCE_OUTPUT_AGENTS[row[4]]}
    wireless = row[4].startswith('TCBusWireless')
    return {'class': row[3], 'agent': row[4], 'wireless': wireless,
            'blocks': 16 if wireless else 4 if row[4] == FAMILY_AGENTS[0] else 8,
            'has_area': not wireless,
            'secondary_blocks': wireless or row[4] == 'TCBusNeoProInputCGateAgent'}
_RELAY_FIRMWARE = frozenset(('0', '4.4', '9', '9.1', '10'))
_KEYE_TYPES = frozenset((
    'KEYE1', 'KEYE2', 'KEYE3', 'KEYE4',
    'KEYEIR1', 'KEYEIR2', 'KEYEIR3', 'KEYEIR4',
))
# Exact NeoPro Saturn registrations; eight input blocks are CSV-visible even
# when the physical key count is two, four or six. See the NeoPro source vector.
_NEOPRO_TYPES = {'KEYB2': 'TKEYB2', 'KEYB4': 'TKEYB4', 'KEYB6': 'TKEYB6'}
# DIN-output agent classes and their GetMaxChannels value. The shared agent
# reloads one group per channel from GroupAddress[0:max], so later stored slots
# are unavailable in the report. The 2026-09-30 factory registry pins each row.
_DIN_CHANNELS = {'TDIMDN4': 4, 'TDIMDN4F': 4, 'TDIMDN8': 8, 'TDIMDN8F': 8,
                 'TRELDN4': 4, 'TRELDN8B': 8, 'TRELDN12': 12,
                 'TANODN4': 4, 'TDIMDS8': 8, 'TDIMPR1': 1, 'TDIMPR2': 2,
                 'TDIMPR4': 4, 'TRELDC4': 4, 'TRELDB1': 1,
                 'TANOMB8': 9, 'TDSIMB8': 9}
_DIN_TYPES = {'DIMDN4': 'TDIMDN4', 'DIMDN4F': 'TDIMDN4F',
              'DIMDN8': 'TDIMDN8', 'DIMDN8F': 'TDIMDN8F',
              'RELDN4': 'TRELDN4', 'RELDN8B': 'TRELDN8B',
              'RELDN12': 'TRELDN12', 'ANODN4': 'TANODN4', 'DIMDS8': 'TDIMDS8',
              'DIMPR1': 'TDIMPR1', 'DIMPR2': 'TDIMPR2', 'DIMPR4': 'TDIMPR4',
              'RELDC4': 'TRELDC4', 'RELDB1': 'TRELDB1',
              'ANOMB8': 'TANOMB8', 'DSIMB8': 'TDSIMB8'}
# TMarshallingBoxCGateAgent.LoadGroups remaps TRELDN8 (and subclasses) and
# TRELMB8 after the DIN load: stored indices 1-4 then 7-11, bounded by the
# class channel count.
_REMAP_TYPES = {'RELDN8': ('TRELDN8', 8), 'RELDN8SP': ('TRELDN8SP', 9),
                'RELMB8': ('TRELMB8', 9)}
_RELDN8SP_RELOAD_INDICES = (1, 2, 3, 4, 7, 8, 9, 10, 11)
_SENSOR_TYPES = {'SENPIROA': ('2.4.00', 'TST7SENPIROA'),
                 'SENPIRIA': ('2.4.00', 'TST7SENPIRSS'),
                 'SENPIRIB': ('2.2.00', 'TST7SENPIRSS')}


def remap_indices(unit_type):
    """Stored GroupAddress indices reloaded by the marshalling-box agent."""
    return _RELDN8SP_RELOAD_INDICES[:_REMAP_TYPES[unit_type.upper()][1]]


def admitted_profiles():
    """Every admitted (unit type, firmware, selected class) point, in order."""
    rows = [('RELAY4', firmware, 'TRELAY4') for firmware in ('0', '4.4', '9')]
    rows += [(kind, '2.5.00', 'TKEYEx') for kind in sorted(_KEYE_TYPES)]
    rows += [(kind, '2.5.00', klass) for kind, klass in _NEOPRO_TYPES.items()]
    rows += [(kind, '2.7.00', klass) for kind, klass in _DIN_TYPES.items()]
    rows += [(kind, '2.7.00', klass) for kind, (klass, _) in _REMAP_TYPES.items()]
    rows += [(kind, firmware, klass) for kind, (firmware, klass) in _SENSOR_TYPES.items()]
    rows.append(('KEYGL5', '5.5.00', 'TCBusEDLTUnit'))
    from .toolkit_database_csv_registry import REGISTRATIONS
    for kind, low, high, klass, agent, _ in REGISTRATIONS:
        if agent not in FAMILY_AGENTS:
            continue
        for point in (low, high):
            try:
                profile = family_profile(kind, point)
            except ValueError:
                continue
            if profile is not None and profile['class'] == klass:
                rows.append((kind.upper(), point, klass))
    return tuple(dict.fromkeys(rows))
_AREA_VALUES = frozenset(('12', '13', '255', 'invalid'))
_ROOT_FIELDS = frozenset(('format', 'unit', 'group_cache', 'area_observations', 'group_save'))
_UNIT_FIELDS = frozenset(('identity', 'address', 'part_name', 'tag_name', 'unit_type',
                          'catalog', 'serial', 'firmware', 'primary', 'secondary',
                          'group_identities'))
_GROUP_FIELDS = frozenset(('identity', 'address', 'tag', 'oid', 'references'))
_CONTEXT_FIELDS = frozenset(('primary_identity', 'secondary_identity',
                            'secondary_mask', 'applications'))
_APPLICATION_FIELDS = frozenset(('identity', 'address', 'tag', 'group_identities'))


def _identity(value, label):
    _text(value, label)
    if not value:
        raise ValueError(label + ' must be nonempty')
    return value


@dataclass(frozen=True)
class CachedCSVGroup:
    identity: str
    address: int
    tag: str
    oid: str
    references: tuple[str, ...] = ()

    def __post_init__(self):
        _identity(self.identity, 'Group identity')
        if type(self.address) is not int or not 0 <= self.address <= 255:
            raise ValueError('Group address must be a byte integer')
        _text(self.tag, 'Group tag')
        _text(self.oid, 'Group OID token')
        if (type(self.references) is not tuple
                or any(type(value) is not str or not value for value in self.references)
                or len(set(self.references)) != len(self.references)):
            raise ValueError('Group references must be unique nonempty strings in an exact tuple')

    def as_dict(self):
        return {'identity': self.identity, 'address': self.address, 'tag': self.tag,
                'oid': self.oid, 'references': list(self.references)}


@dataclass(frozen=True)
class CachedCSVUnit:
    identity: str
    address: int
    part_name: str
    tag_name: str
    unit_type: str
    catalog: str
    serial: str
    firmware: str
    primary: str
    secondary: str
    group_identities: tuple[str, ...]
    loader_associations: tuple[str, ...] = ()

    def __post_init__(self):
        _identity(self.identity, 'Unit identity')
        if type(self.address) is not int or not 0 <= self.address <= 255:
            raise ValueError('Unit address must be a byte integer')
        for name in ('part_name', 'tag_name', 'unit_type', 'catalog', 'serial',
                     'firmware', 'primary', 'secondary'):
            _text(getattr(self, name), name)
        if (type(self.group_identities) is not tuple or len(self.group_identities) > 32
                or any(type(value) is not str or not value for value in self.group_identities)):
            raise ValueError('Unit groups must be at most thirty-two nonempty identities in an exact tuple')
        if type(self.loader_associations) is not tuple or any(
                type(value) is not str or not value for value in self.loader_associations):
            raise ValueError('Loader associations must be nonempty identities in an exact tuple')
        kind = self.unit_type.upper()
        if len(self.group_identities) > 16:
            family = family_profile(kind, self.firmware)
            if family is None or not family['wireless']:
                raise ValueError('Non-wireless unit groups must contain at most sixteen identities')
        if kind in _REMAP_TYPES:
            indices = remap_indices(kind)
            if (len(self.group_identities) != len(indices)
                    or len(self.loader_associations) != 16 + len(indices)
                    or self.group_identities != self.loader_associations[16:]
                    or self.group_identities != tuple(
                        self.loader_associations[index] for index in indices)):
                raise ValueError(f'{kind} requires sixteen DIN loads followed by its exact '
                                 f'{len(indices)}-group marshalling-box replacement')
        elif self.loader_associations:
            raise ValueError('Loader association history is supported only for marshalling-box remap profiles')

    def as_dict(self):
        result = {'identity': self.identity, 'address': self.address,
                **{name: getattr(self, name) for name in ('part_name', 'tag_name', 'unit_type',
                    'catalog', 'serial', 'firmware', 'primary', 'secondary')},
                'group_identities': list(self.group_identities)}
        if self.loader_associations:
            result['loader_associations'] = list(self.loader_associations)
        return result


@dataclass(frozen=True)
class CSVAreaObservation:
    raw: str
    completed: bool = True

    def __post_init__(self):
        _text(self.raw, 'Area observation')
        if (self.raw not in _AREA_VALUES and not (self.raw.isascii()
                and self.raw.isdecimal() and str(int(self.raw)) == self.raw
                and 0 <= int(self.raw) <= 255)):
            raise ValueError('Area observation is outside the captured v1 domain')
        if type(self.completed) is not bool:
            raise ValueError('Area observation completion must be Boolean')


@dataclass(frozen=True)
class CSVGroupSaveObservation:
    completed: bool

    def __post_init__(self):
        if type(self.completed) is not bool:
            raise ValueError('Group-save completion must be Boolean')


@dataclass(frozen=True)
class CSVWirelessLoader:
    installed_keys: int
    installed_channels: int
    channel_relay_mask: int
    block_secondary: tuple[bool, ...]
    output_secondary: tuple[bool, ...]

    def __post_init__(self):
        for name in ('installed_keys', 'installed_channels'):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 16:
                raise ValueError('Wireless installed counts must be integers from zero through sixteen')
        if (type(self.channel_relay_mask) is not int
                or not 0 <= self.channel_relay_mask <= 65535):
            raise ValueError('Wireless ChannelRelayMask must be a sixteen-bit integer')
        for values, count in ((self.block_secondary, 16),
                              (self.output_secondary, self.installed_channels)):
            if type(values) is not tuple or len(values) != count or any(type(v) is not bool for v in values):
                raise ValueError('Wireless secondary arrays must match sixteen blocks and installed channels')

    @property
    def secondary_mask(self):
        return sum(int(value) << index for index, value in enumerate(
            self.block_secondary + self.output_secondary))

    def as_dict(self):
        return {'installed_keys': self.installed_keys, 'installed_channels': self.installed_channels,
                'channel_relay_mask': self.channel_relay_mask,
                'block_secondary': list(self.block_secondary), 'output_secondary': list(self.output_secondary)}


@dataclass(frozen=True)
class CachedCSVApplication:
    identity: str
    address: int
    tag: str
    group_identities: tuple[str, ...]

    def __post_init__(self):
        _identity(self.identity, 'Application identity')
        if type(self.address) is not int or not 0 <= self.address <= 255:
            raise ValueError('Application address must be a byte integer')
        _text(self.tag, 'Application tag')
        if (type(self.group_identities) is not tuple or len(self.group_identities) > 256
                or any(type(value) is not str or not value for value in self.group_identities)
                or len(set(self.group_identities)) != len(self.group_identities)):
            raise ValueError('Application groups must be unique identities in an exact bounded tuple')

    def as_dict(self):
        return {'identity': self.identity, 'address': self.address, 'tag': self.tag,
                'group_identities': list(self.group_identities)}


@dataclass(frozen=True)
class CachedCSVApplicationContext:
    primary_identity: str
    secondary_identity: str | None
    secondary_mask: int
    applications: tuple[CachedCSVApplication, ...]

    def __post_init__(self):
        _identity(self.primary_identity, 'Primary Application identity')
        if self.secondary_identity is not None:
            _identity(self.secondary_identity, 'Secondary Application identity')
        if type(self.secondary_mask) is not int or not 0 <= self.secondary_mask <= 0xffffffff:
            raise ValueError('Secondary application mask must be a bounded integer')
        if (type(self.applications) is not tuple or not 1 <= len(self.applications) <= 2
                or any(type(value) is not CachedCSVApplication for value in self.applications)):
            raise ValueError('Application context requires one or two exact Application records')

    def as_dict(self):
        return {'primary_identity': self.primary_identity,
                'secondary_identity': self.secondary_identity,
                'secondary_mask': self.secondary_mask,
                'applications': [value.as_dict() for value in self.applications]}


@dataclass(frozen=True)
class CSVProjectionEvent:
    event: str
    fields: tuple[tuple[str, object], ...] = ()

    def as_dict(self):
        return {'event': self.event, **dict(self.fields)}


def _event(name, **fields):
    return CSVProjectionEvent(name, tuple(fields.items()))


@dataclass(frozen=True)
class CachedCSVProjection:
    selected_class: str
    complete: bool
    columns: tuple[str, ...]
    unit: CachedCSVUnit
    groups: tuple[CachedCSVGroup, ...]
    events: tuple[CSVProjectionEvent, ...]
    raw_area: str | None
    area_identity: str | None
    group_save_required: bool
    report: DatabaseCSV | None
    stop_reason: str | None
    csv_unit: CSVUnitValues | None = None
    application_context: CachedCSVApplicationContext | None = None
    wireless_loader: CSVWirelessLoader | None = None

    @property
    def rows(self):
        if self.report is not None:
            return self.report.rows
        return (''.join(COLUMN_LABELS[name] + ',' for name in self.columns),)

    def as_dict(self):
        result = {'format': SOURCE_PROFILE if (family_profile(self.unit.unit_type, self.unit.firmware) or {}).get('source_model') else
                  WIRELESS_PROFILE if self.wireless_loader is not None else
                  IDENTITY_PROFILE if self.application_context is not None else PROFILE,
                'complete': self.complete,
                'selected_class': self.selected_class, 'columns': list(self.columns),
                'unit': self.unit.as_dict(), 'groups': [group.as_dict() for group in self.groups],
                'events': [event.as_dict() for event in self.events],
                'raw_area': self.raw_area, 'area_identity': self.area_identity,
                'group_save_required': self.group_save_required,
                'stop_reason': self.stop_reason, 'rows': list(self.rows),
                'report': self.report.as_dict() if self.report is not None else None,
                'input_scope': 'explicit retained cached unit/group records and captured provider outcomes',
                'original_cached_projection_replayed': True,
                'native_database_loaded': False, 'native_mutation_performed': False,
                'original_instructions_executed': False, 'physical_device_accessed': False}
        if self.application_context is not None:
            result['application_context'] = self.application_context.as_dict()
        if self.wireless_loader is not None:
            result['wireless_loader'] = self.wireless_loader.as_dict()
        return result


def _class(unit):
    kind = unit.unit_type.upper()
    if kind == 'OWNED_UNKNOWN' and unit.unit_type == 'OWNED_UNKNOWN' and unit.firmware == '4.4':
        return 'TCBusUnitGeneric'
    if kind == 'RELAY4' and unit.firmware in _RELAY_FIRMWARE:
        return 'TRELAY4' if unit.firmware in ('0', '4.4', '9') else 'TCBusUnitGeneric'
    if kind in _KEYE_TYPES and unit.firmware == '2.5.00':
        if len(unit.group_identities) != 9:
            raise ValueError('Cached KEYE profile requires exactly nine stored groups')
        return 'TKEYEx'
    if kind in _NEOPRO_TYPES and unit.firmware == '2.5.00':
        if len(unit.group_identities) != 8:
            raise ValueError('Cached NeoPro profile requires exactly eight stored groups')
        return _NEOPRO_TYPES[kind]
    profile = family_profile(kind, unit.firmware)
    if profile is not None:
        count = len(unit.group_identities)
        dynamic = profile.get('dynamic_blocks')
        if (dynamic == 'temperature_mode' and count not in (0, 1, 3)
                or dynamic == 'wireless_channels' and not 0 <= count <= 16
                or not dynamic and not profile['wireless'] and count != profile['blocks']
                or profile['wireless'] and not 16 <= count <= 32):
            raise ValueError('Cached family group count disagrees with the selected static loader')
        return profile['class']
    if kind in _DIN_TYPES and unit.firmware == '2.7.00':
        if len(unit.group_identities) != 16:
            raise ValueError('Cached DIN profile requires exactly sixteen stored groups')
        return _DIN_TYPES[kind]
    if kind in _REMAP_TYPES and unit.firmware == '2.7.00':
        return _REMAP_TYPES[kind][0]
    if kind in _SENSOR_TYPES and unit.firmware == _SENSOR_TYPES[kind][0]:
        if len(unit.group_identities) != 8:
            raise ValueError('Cached sensor profile requires exactly eight stored groups')
        return _SENSOR_TYPES[kind][1]
    if kind == 'KEYGL5' and unit.firmware == '5.5.00' and unit.catalog == '5055EDL':
        return 'TCBusEDLTUnit'
    raise ValueError('Cached projection supports the captured profiles and source-backed Key, Neo, NeoPro and wireless factory ranges; ' + refusal_reason(unit.unit_type, unit.firmware))


def _validated_groups(unit, groups, *, allow_empty=False):
    if type(groups) is not tuple or not int(not allow_empty) <= len(groups) <= 256:
        raise ValueError('group_cache must be a nonempty exact tuple of at most 256 groups')
    if any(type(group) is not CachedCSVGroup for group in groups):
        raise ValueError('group_cache must contain exact CachedCSVGroup records')
    identities = [group.identity for group in groups]
    oids = [group.oid for group in groups if group.oid]
    if len(set(identities)) != len(groups) or len(set(oids)) != len(oids):
        raise ValueError('Cached group identities and nonempty OID tokens must be unique')
    if any(identity not in set(identities) for identity in
           (*unit.group_identities, *unit.loader_associations)):
        raise ValueError('Every unit group identity must resolve in the complete cache')
    if any(unit.identity in group.references for group in groups):
        raise ValueError('The captured v1 profile requires a cold nil Area reference')
    return tuple(replace(group, references=tuple(group.references)) for group in groups)


def _validated_application_context(unit, groups, context, *, source_model=False):
    if type(context) is not CachedCSVApplicationContext:
        raise ValueError('NeoPro cached projection requires explicit primary Application identity context')
    if context.secondary_mask >> len(unit.group_identities):
        raise ValueError('Secondary Application mask has bits beyond the stored associations')
    applications = {app.identity: app for app in context.applications}
    if (len(applications) != len(context.applications)
            or len({app.address for app in context.applications}) != len(applications)):
        raise ValueError('Application identities and addresses must be unique')
    selected = {context.primary_identity}
    if context.secondary_identity is not None:
        selected.add(context.secondary_identity)
    if selected != set(applications):
        raise ValueError('Application cache must resolve exactly the declared primary and secondary identities')
    primary = applications[context.primary_identity]
    secondary = (None if context.secondary_identity is None else
                 applications[context.secondary_identity])
    if source_model and secondary is None:
        raise ValueError('Source cached projection requires the resolved secondary Application identity; base formatting defaults it to255')
    if secondary is not None and secondary.address == 255 and not source_model:
        raise ValueError('Secondary Application address 255 must be represented as an unused null identity')
    if unit.primary != primary.tag or unit.secondary != ('' if secondary is None else secondary.tag):
        raise ValueError('Unit application tags disagree with the authoritative Application identities')
    if secondary is None and context.secondary_mask:
        raise ValueError('Secondary group blocks require a configured secondary Application identity')
    cache = {group.identity: group for group in groups}
    group_tokens = set(cache) | {group.oid for group in groups if group.oid}
    if (unit.identity in group_tokens or set(applications) &
            (group_tokens | {unit.identity})):
        raise ValueError('Application identities must not collide with Unit or Group identities')
    membership = {}
    for app in context.applications:
        if any(identity not in cache for identity in app.group_identities):
            raise ValueError('Application membership refers to a missing cached Group identity')
        addresses = [cache[identity].address for identity in app.group_identities]
        if len(set(addresses)) != len(addresses):
            raise ValueError('Application membership contains ambiguous Group addresses')
        for identity in app.group_identities:
            if identity in membership:
                raise ValueError('Cached Group identity belongs to more than one Application')
            membership[identity] = app.identity
    if set(membership) != set(cache):
        raise ValueError('Every cached Group must have exactly one authoritative Application membership')
    for index, identity in enumerate(unit.group_identities):
        expected = (context.secondary_identity if context.secondary_mask & (1 << index)
                    else context.primary_identity)
        if membership[identity] != expected:
            raise ValueError('Stored NeoPro block order disagrees with its secondary Application mask')
    return context


def project_cached_csv_unit(unit, *, group_cache, area_observations=(),
                            group_save=None, columns, application_context=None, wireless_loader=None):
    """Replay one captured cached unit projection without external I/O.

    Provider failures are completed partial outcomes rather than exceptions.
    Validation failures occur before any modeled operation.
    """
    if type(unit) is not CachedCSVUnit:
        raise ValueError('unit must be an exact CachedCSVUnit')
    selected = validate_columns(columns)
    selected_class = _class(unit)
    family = family_profile(unit.unit_type, unit.firmware)
    current = list(_validated_groups(unit, group_cache, allow_empty=bool(
        (family or {}).get('generic') or (family or {}).get('dynamic_blocks'))))
    if family is not None:
        application_context = _validated_application_context(unit, current, application_context,
            source_model=family.get('source_model', False))
        if family.get('dynamic_blocks') == 'temperature_mode':
            primary = next(app for app in application_context.applications
                           if app.identity == application_context.primary_identity)
            if len(unit.group_identities) != temperature_group_count(primary.address):
                raise ValueError('Temperature CSV associations disagree with primary Application mode')
        if family['wireless']:
            if (type(wireless_loader) is not CSVWirelessLoader
                    or len(unit.group_identities) != 16 + wireless_loader.installed_channels
                    or application_context.secondary_mask != wireless_loader.secondary_mask):
                raise ValueError('Wireless projection requires matching consumed loader metadata and Application routing')
        elif wireless_loader is not None:
            raise ValueError('Wireless loader metadata is only supported for wireless profiles')
        elif not family['secondary_blocks'] and application_context.secondary_mask:
            raise ValueError('The selected primary-only loader cannot consume secondary block routing')
    elif application_context is not None:
        raise ValueError('Application identity context is supported only for the exact NeoPro profile')
    elif wireless_loader is not None:
        raise ValueError('Wireless loader metadata is only supported for wireless profiles')
    if type(area_observations) is not tuple or any(type(value) is not CSVAreaObservation
                                                   for value in area_observations):
        raise ValueError('area_observations must be an exact tuple of CSVAreaObservation records')
    if group_save is not None and type(group_save) is not CSVGroupSaveObservation:
        raise ValueError('group_save must be an exact CSVGroupSaveObservation or absent')
    has_area = (selected_class in _DIN_CHANNELS or selected_class in _NEOPRO_TYPES.values() or selected_class in (
        'TRELAY4', 'TKEYEx', 'TRELDN8', 'TRELDN8SP', 'TRELMB8',
        'TST7SENPIROA', 'TST7SENPIRSS'))
    if family is not None:
        has_area = family['has_area']
    if has_area and len(area_observations) != 2:
        raise ValueError('The captured input/output projection requires two ordered Area observations')
    if not has_area and area_observations and len(area_observations) != 2:
        raise ValueError('Captured generic observations are absent or an ignored pair')
    if wireless_loader is not None and area_observations:
        raise ValueError('Wireless loader has no Area provider observations')
    if (family or {}).get('generic') and not has_area and area_observations:
        raise ValueError('Source generic loader has no Area provider observations')

    if not (family or {}).get('source_model') and any(
            observation.raw not in _AREA_VALUES for observation in area_observations):
        raise ValueError('Area observation is outside the captured v1 domain')

    events = [_event('factory_selected', selected_class=selected_class)]
    raw_area = area_identity = None
    save_required = False

    def partial(reason):
        return CachedCSVProjection(selected_class, False, selected, unit, tuple(current),
            tuple(events), raw_area, area_identity, save_required, None, reason,
            application_context=application_context)

    if has_area:
        for index, observation in enumerate(area_observations, 1):
            events.append(_event('area_load', ordinal=index, completed=observation.completed,
                                 raw=observation.raw))
            if not observation.completed:
                return partial('area_load_failed')
            raw_area = observation.raw
            address = int(raw_area) if raw_area.isdecimal() else 255
            primary_groups = (None if application_context is None else set(next(
                app.group_identities for app in application_context.applications
                if app.identity == application_context.primary_identity)))
            found = next((group for group in current if group.address == address
                          and (primary_groups is None or group.identity in primary_groups)), None)
            events.append(_event('group_lookup', address=address, found=found is not None))
            if found is None:
                if address != 255:
                    raise ValueError('The v1 profile only captured creation of missing group 255')
                if len(current) >= 256:
                    raise ValueError('Cached group collection has no capacity for the missing Area group')
                found = CachedCSVGroup('created-255', 255, '<Unused>', 'OID-created-255')
                if application_context is not None:
                    retained = ({unit.identity}
                                | {app.identity for app in application_context.applications}
                                | {group.identity for group in current}
                                | {group.oid for group in current if group.oid})
                    if {found.identity, found.oid} & retained:
                        raise ValueError('Modeled created Area identity collides with the retained cache')
                current.append(found)
                if application_context is not None:
                    application_context = replace(application_context, applications=tuple(
                        replace(app, group_identities=(*app.group_identities, found.identity))
                        if app.identity == application_context.primary_identity else app
                        for app in application_context.applications))
                save_required = True
                events.append(_event('group_created', identity=found.identity,
                                     address=255, tag='<Unused>'))
                if group_save is None:
                    raise ValueError('Missing group 255 requires an explicit group-save observation')
                events.append(_event('group_save', completed=group_save.completed,
                                     identity=found.identity))
                if not group_save.completed:
                    return partial('group_save_failed')
            old = area_identity
            area_identity = found.identity
            for position, group in enumerate(current):
                references = tuple(value for value in group.references if value != unit.identity)
                if group.identity == area_identity:
                    references += (unit.identity,)
                current[position] = replace(group, references=references)
            events.append(_event('area_reference', previous=old, current=area_identity,
                                 oid=found.oid, changed=True, update_count=0))
    else:
        if group_save is not None:
            raise ValueError('Generic cached projection cannot consume a group-save observation')

    if group_save is not None and not save_required:
        raise ValueError('Group-save observation was supplied but the projection did not require a save')

    cache = {group.identity: group for group in current}
    if wireless_loader is not None:
        events.append(_event('wireless_groups_replaced', block_count=16,
                             channel_count=wireless_loader.installed_channels,
                             installed_keys=wireless_loader.installed_keys,
                             channel_relay_mask=wireless_loader.channel_relay_mask))
    if unit.loader_associations:
        events.append(_event('marshalling_box_groups_replaced', initial_count=16,
                             replacement_count=len(unit.group_identities)))
    interaction_count = {'TRELAY4': 6, 'TRELDN8': 8, 'TRELDN8SP': 9, 'TRELMB8': 9,
                         'TCBusEDLTUnit': 16, **_DIN_CHANNELS}.get(selected_class, 8)
    if family is not None:
        interaction_count = (len(unit.group_identities) if family.get('dynamic_blocks') else
                             16 if family['wireless'] else family['blocks'])
    values = tuple(CSVGroupValue(cache[identity].tag, index < interaction_count)
                   for index, identity in enumerate(unit.group_identities[:16]))
    area = cache[area_identity].tag if area_identity is not None else None
    csv_unit = CSVUnitValues(unit.address, unit.part_name, unit.tag_name, unit.unit_type,
        unit.catalog, unit.serial, unit.firmware, unit.primary, unit.secondary, area, values)
    report = document_database_csv((csv_unit,), columns=selected)
    events.append(_event('row_projected', columns=len(selected), bytes=len(report.utf8_bytes)))
    return CachedCSVProjection(selected_class, True, selected, unit, tuple(current),
        tuple(events), raw_area, area_identity, save_required, report, None, csv_unit,
        application_context, wireless_loader)


def parse_cached_projection(value, *, columns):
    """Validate and project the exact bounded cached-object JSON schema."""
    if type(value) is not dict or value.get('format') not in (PROFILE, IDENTITY_PROFILE, WIRELESS_PROFILE, SOURCE_PROFILE):
        raise ValueError('Expected the cbus-toolkit-database-cached-projection-v1 object')
    with_identity = value['format'] in (IDENTITY_PROFILE, WIRELESS_PROFILE, SOURCE_PROFILE)
    with_wireless = value['format'] == WIRELESS_PROFILE
    expected_root = _ROOT_FIELDS | ({'application_context'} if with_identity else set())
    if with_wireless:
        expected_root |= {'wireless_loader'}
    if set(value) != expected_root:
        raise ValueError('Cached projection must provide every documented root field, without extras')
    raw_unit = value['unit']
    if type(raw_unit) is not dict or not _UNIT_FIELDS <= set(raw_unit):
        raise ValueError('Cached unit must provide every documented field, without extras')
    expected_unit_fields = (_UNIT_FIELDS | {'loader_associations'}
                            if type(raw_unit['unit_type']) is str
                            and raw_unit['unit_type'].upper() in _REMAP_TYPES
                            else _UNIT_FIELDS)
    if set(raw_unit) != expected_unit_fields:
        raise ValueError('Cached unit must provide every documented field, without extras')
    neopro = type(raw_unit['unit_type']) is str and raw_unit['unit_type'].upper() in _NEOPRO_TYPES
    family = family_profile(raw_unit['unit_type'], raw_unit['firmware'])
    if neopro and not with_identity:
        # This public schema has tags but no primary Application identity.
        # The v2 contract or native adapter must bind primary membership.
        raise ValueError('NeoPro cached v1 JSON cannot establish primary Application identity; '
                         'use cached v2 or an explicit native XML snapshot')
    if family is not None and not with_identity:
        raise ValueError('CSV family cached JSON requires explicit Application identity context')
    if bool(family and family.get('source_model')) != (value['format'] == SOURCE_PROFILE):
        raise ValueError('Source-backed completion profiles require cached v4')
    if with_wireless != bool(family and family['wireless']):
        raise ValueError('Wireless profiles require cached v3 loader metadata')
    if with_identity and family is None:
        raise ValueError('Cached v2 Application identity context supports only NeoPro')
    group_identities = raw_unit['group_identities']
    if type(group_identities) is not list:
        raise ValueError('Cached unit group identities must be a JSON array')
    raw_loader = raw_unit.get('loader_associations', [])
    if type(raw_loader) is not list:
        raise ValueError('Cached loader associations must be a JSON array')
    unit = CachedCSVUnit(**{name: raw_unit[name] for name in _UNIT_FIELDS - {'group_identities'}},
                         group_identities=tuple(group_identities),
                         loader_associations=tuple(raw_loader))

    raw_groups = value['group_cache']
    if (type(raw_groups) is not list or not int(not bool(
            (family or {}).get('generic') or (family or {}).get('dynamic_blocks')))
            <= len(raw_groups) <= 256):
        raise ValueError('Cached groups must be a nonempty JSON array of at most 256 entries')
    groups = []
    for raw_group in raw_groups:
        if type(raw_group) is not dict or set(raw_group) != _GROUP_FIELDS:
            raise ValueError('Cached group must provide every documented field, without extras')
        references = raw_group['references']
        if type(references) is not list:
            raise ValueError('Cached group references must be a JSON array')
        groups.append(CachedCSVGroup(**{name: raw_group[name]
            for name in _GROUP_FIELDS - {'references'}}, references=tuple(references)))

    context = None
    if with_identity:
        raw_context = value['application_context']
        if type(raw_context) is not dict or set(raw_context) != _CONTEXT_FIELDS:
            raise ValueError('Application context must provide every documented field, without extras')
        raw_apps = raw_context['applications']
        if type(raw_apps) is not list or not 1 <= len(raw_apps) <= 2:
            raise ValueError('Application cache must contain one or two JSON records')
        applications = []
        for raw_app in raw_apps:
            if type(raw_app) is not dict or set(raw_app) != _APPLICATION_FIELDS:
                raise ValueError('Cached Application must provide every documented field, without extras')
            if type(raw_app['group_identities']) is not list:
                raise ValueError('Application Group identities must be a JSON array')
            applications.append(CachedCSVApplication(**{name: raw_app[name]
                for name in _APPLICATION_FIELDS - {'group_identities'}},
                group_identities=tuple(raw_app['group_identities'])))
        context = CachedCSVApplicationContext(**{name: raw_context[name]
            for name in _CONTEXT_FIELDS - {'applications'}}, applications=tuple(applications))

    raw_observations = value['area_observations']
    if type(raw_observations) is not list or len(raw_observations) > 2:
        raise ValueError('Area observations must be a JSON array of at most two entries')
    observations = []
    for raw_observation in raw_observations:
        if type(raw_observation) is not dict or set(raw_observation) != {'raw', 'completed'}:
            raise ValueError('Each Area observation requires raw and completed')
        observations.append(CSVAreaObservation(**raw_observation))

    raw_save = value['group_save']
    if raw_save is None:
        save = None
    elif type(raw_save) is dict and set(raw_save) == {'completed'}:
        save = CSVGroupSaveObservation(**raw_save)
    else:
        raise ValueError('group_save must be null or an object containing completed')
    wireless = None
    if with_wireless:
        raw = value['wireless_loader']
        if type(raw) is not dict or set(raw) != {'installed_keys', 'installed_channels',
                'channel_relay_mask', 'block_secondary', 'output_secondary'}:
            raise ValueError('Wireless loader must provide every documented field without extras')
        if type(raw['block_secondary']) is not list or type(raw['output_secondary']) is not list:
            raise ValueError('Wireless secondary arrays must be JSON arrays')
        wireless = CSVWirelessLoader(raw['installed_keys'], raw['installed_channels'],
            raw['channel_relay_mask'], tuple(raw['block_secondary']), tuple(raw['output_secondary']))
    return project_cached_csv_unit(unit, group_cache=tuple(groups),
        area_observations=tuple(observations), group_save=save, columns=columns,
        application_context=context, wireless_loader=wireless)


def loads_cached_projection(raw, *, columns):
    """Decode strict bounded UTF-8 JSON and run the cached projection."""
    from .toolkit_database_csv import MAX_CAPTURE_BYTES
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CAPTURE_BYTES:
        raise ValueError('Cached projection input must be nonempty bytes within the 8 MiB bound')
    text = raw.decode('utf-8')
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > 5:
                raise ValueError('Cached projection nesting exceeds its schema')
        elif char in ']}':
            depth -= 1

    def unique(pairs):
        if (len(pairs) > max(len(_UNIT_FIELDS) + 1, len(_GROUP_FIELDS) + 6)
                or len({key for key, _ in pairs}) != len(pairs)):
            raise ValueError('Cached projection contains duplicate or excessive object keys')
        return dict(pairs)

    def integer(raw_value):
        if len(raw_value.lstrip('-')) > 10:
            raise ValueError('Cached projection integer exceeds its bounded domain')
        return int(raw_value)

    def no_float(_):
        raise ValueError('Cached projection numbers must be integers')

    value = json.loads(text, object_pairs_hook=unique, parse_int=integer,
                       parse_float=no_float, parse_constant=no_float)
    return parse_cached_projection(value, columns=columns)
