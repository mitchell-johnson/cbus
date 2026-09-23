"""Original-backed cached unit projection for Toolkit database CSV rows.

This is the finite cached-object boundary captured from Toolkit 1.18.  It does
not parse a project or access native storage.  The admitted RELAY4 profile
replays the two Area getter loads, group lookup/reference changes and optional
missing-unused-group save before composing the accepted CSV serializer.
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


PROFILE = 'cbus-toolkit-database-cached-projection-v1'
_RELAY_FIRMWARE = frozenset(('0', '4.4', '9', '9.1', '10'))
_AREA_VALUES = frozenset(('12', '13', '255', 'invalid'))
_ROOT_FIELDS = frozenset(('format', 'unit', 'group_cache', 'area_observations', 'group_save'))
_UNIT_FIELDS = frozenset(('identity', 'address', 'part_name', 'tag_name', 'unit_type',
                          'catalog', 'serial', 'firmware', 'primary', 'secondary',
                          'group_identities'))
_GROUP_FIELDS = frozenset(('identity', 'address', 'tag', 'oid', 'references'))


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
        _identity(self.oid, 'Group OID token')
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

    def __post_init__(self):
        _identity(self.identity, 'Unit identity')
        if type(self.address) is not int or not 0 <= self.address <= 255:
            raise ValueError('Unit address must be a byte integer')
        for name in ('part_name', 'tag_name', 'unit_type', 'catalog', 'serial',
                     'firmware', 'primary', 'secondary'):
            _text(getattr(self, name), name)
        if (type(self.group_identities) is not tuple or len(self.group_identities) > 16
                or any(type(value) is not str or not value for value in self.group_identities)
                or len(set(self.group_identities)) != len(self.group_identities)):
            raise ValueError('Unit groups must be at most sixteen unique identities in an exact tuple')

    def as_dict(self):
        return {'identity': self.identity, 'address': self.address,
                **{name: getattr(self, name) for name in ('part_name', 'tag_name', 'unit_type',
                    'catalog', 'serial', 'firmware', 'primary', 'secondary')},
                'group_identities': list(self.group_identities)}


@dataclass(frozen=True)
class CSVAreaObservation:
    raw: str
    completed: bool = True

    def __post_init__(self):
        _text(self.raw, 'Area observation')
        if self.raw not in _AREA_VALUES:
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

    @property
    def rows(self):
        if self.report is not None:
            return self.report.rows
        return (''.join(COLUMN_LABELS[name] + ',' for name in self.columns),)

    def as_dict(self):
        return {'format': PROFILE, 'complete': self.complete,
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


def _class(unit):
    kind = unit.unit_type.upper()
    if kind == 'OWNED_UNKNOWN' and unit.unit_type == 'OWNED_UNKNOWN' and unit.firmware == '4.4':
        return 'TCBusUnitGeneric'
    if kind == 'RELAY4' and unit.firmware in _RELAY_FIRMWARE:
        return 'TRELAY4' if unit.firmware in ('0', '4.4', '9') else 'TCBusUnitGeneric'
    raise ValueError('Cached projection profile supports only the captured generic/RELAY4 type and firmware pairs')


def _validated_groups(unit, groups):
    if type(groups) is not tuple or not 1 <= len(groups) <= 256:
        raise ValueError('group_cache must be a nonempty exact tuple of at most 256 groups')
    if any(type(group) is not CachedCSVGroup for group in groups):
        raise ValueError('group_cache must contain exact CachedCSVGroup records')
    identities = [group.identity for group in groups]
    addresses = [group.address for group in groups]
    oids = [group.oid for group in groups]
    if len(set(identities)) != len(groups) or len(set(addresses)) != len(groups) or len(set(oids)) != len(groups):
        raise ValueError('Cached group identities, addresses and OID tokens must be unique')
    if any(identity not in set(identities) for identity in unit.group_identities):
        raise ValueError('Every unit group identity must resolve in the complete cache')
    if any(unit.identity in group.references for group in groups):
        raise ValueError('The captured v1 profile requires a cold nil Area reference')
    return tuple(replace(group, references=tuple(group.references)) for group in groups)


def project_cached_csv_unit(unit, *, group_cache, area_observations=(),
                            group_save=None, columns):
    """Replay one captured cached unit projection without external I/O.

    Provider failures are completed partial outcomes rather than exceptions.
    Validation failures occur before any modeled operation.
    """
    if type(unit) is not CachedCSVUnit:
        raise ValueError('unit must be an exact CachedCSVUnit')
    selected = validate_columns(columns)
    selected_class = _class(unit)
    current = list(_validated_groups(unit, group_cache))
    if type(area_observations) is not tuple or any(type(value) is not CSVAreaObservation
                                                   for value in area_observations):
        raise ValueError('area_observations must be an exact tuple of CSVAreaObservation records')
    if group_save is not None and type(group_save) is not CSVGroupSaveObservation:
        raise ValueError('group_save must be an exact CSVGroupSaveObservation or absent')
    if selected_class == 'TRELAY4' and len(area_observations) != 2:
        raise ValueError('The captured RELAY4 projection requires two ordered Area observations')
    if selected_class != 'TRELAY4' and area_observations and len(area_observations) != 2:
        raise ValueError('Captured generic observations are absent or an ignored pair')

    events = [_event('factory_selected', selected_class=selected_class)]
    raw_area = area_identity = None
    save_required = False

    def partial(reason):
        return CachedCSVProjection(selected_class, False, selected, unit, tuple(current),
            tuple(events), raw_area, area_identity, save_required, None, reason)

    if selected_class == 'TRELAY4':
        for index, observation in enumerate(area_observations, 1):
            events.append(_event('area_load', ordinal=index, completed=observation.completed,
                                 raw=observation.raw))
            if not observation.completed:
                return partial('area_load_failed')
            raw_area = observation.raw
            address = int(raw_area) if raw_area.isdecimal() else 255
            found = next((group for group in current if group.address == address), None)
            events.append(_event('group_lookup', address=address, found=found is not None))
            if found is None:
                if address != 255:
                    raise ValueError('The v1 profile only captured creation of missing group 255')
                if len(current) >= 256:
                    raise ValueError('Cached group collection has no capacity for the missing Area group')
                found = CachedCSVGroup('created-255', 255, '<Unused>', 'OID-created-255')
                current.append(found)
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
    interaction_count = 6 if selected_class == 'TRELAY4' else 8
    values = tuple(CSVGroupValue(cache[identity].tag, index < interaction_count)
                   for index, identity in enumerate(unit.group_identities))
    area = cache[area_identity].tag if area_identity is not None else None
    csv_unit = CSVUnitValues(unit.address, unit.part_name, unit.tag_name, unit.unit_type,
        unit.catalog, unit.serial, unit.firmware, unit.primary, unit.secondary, area, values)
    report = document_database_csv((csv_unit,), columns=selected)
    events.append(_event('row_projected', columns=len(selected), bytes=len(report.utf8_bytes)))
    return CachedCSVProjection(selected_class, True, selected, unit, tuple(current),
        tuple(events), raw_area, area_identity, save_required, report, None)


def parse_cached_projection(value, *, columns):
    """Validate and project the exact bounded cached-object JSON schema."""
    if type(value) is not dict or set(value) != _ROOT_FIELDS or value.get('format') != PROFILE:
        raise ValueError('Expected the cbus-toolkit-database-cached-projection-v1 object')
    raw_unit = value['unit']
    if type(raw_unit) is not dict or set(raw_unit) != _UNIT_FIELDS:
        raise ValueError('Cached unit must provide every documented field, without extras')
    group_identities = raw_unit['group_identities']
    if type(group_identities) is not list:
        raise ValueError('Cached unit group identities must be a JSON array')
    unit = CachedCSVUnit(**{name: raw_unit[name] for name in _UNIT_FIELDS - {'group_identities'}},
                         group_identities=tuple(group_identities))

    raw_groups = value['group_cache']
    if type(raw_groups) is not list or not 1 <= len(raw_groups) <= 256:
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
    return project_cached_csv_unit(unit, group_cache=tuple(groups),
        area_observations=tuple(observations), group_save=save, columns=columns)


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
        if len(pairs) > len(_GROUP_FIELDS) + 6 or len({key for key, _ in pairs}) != len(pairs):
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
