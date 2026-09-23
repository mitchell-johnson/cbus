"""Retained programmable-thermostat scheduling state after original AfterLoad.

The planner starts from supplied raw bytes and an already resolved application
collection. It reproduces the reviewed normalization and application/group
selection decisions without loading a unit, constructing native objects or
performing storage writes.
"""
from __future__ import annotations

from dataclasses import dataclass

from .thermostat_schedule_levels import ScheduleLevel, ScheduleLevelsEngine


RAW_FIELDS = ('RemoteScheduleOnGroup', 'RemoteScheduleOffGroup',
              'RemoteScheduleOverrideGroup', 'RemoteScheduleEnable',
              'EvapProgramEnabled', 'NonEvapProgramEnabled')
ROLES = ('on', 'off', 'override')


def _text(value, label, *, empty=False):
    if (type(value) is not str or (not empty and not value) or len(value) > 128
            or '\0' in value):
        raise ValueError(label + ' must be bounded text without NUL')
    value.encode('utf-8', 'strict')
    return value


@dataclass(frozen=True)
class ThermostatLoadGroup:
    identity: str
    address: int
    tag: str
    levels: tuple[ScheduleLevel, ...] = ()

    def __post_init__(self):
        _text(self.identity, 'Group identity')
        if type(self.address) is not int or not 0 <= self.address <= 255:
            raise ValueError('Group address must be a byte integer')
        _text(self.tag, 'Group tag', empty=True)
        if type(self.levels) is not tuple:
            raise ValueError('Group levels must be an exact tuple')
        ScheduleLevelsEngine().load(self.levels)

    def as_dict(self):
        return {'identity': self.identity, 'address': self.address, 'tag': self.tag}


@dataclass(frozen=True)
class ThermostatUnitLoadOutcome:
    evap: bool
    nonevap: bool
    remote: bool
    normalized_flags: tuple[int, int]
    roles: tuple[str | None, str | None, str | None]
    application_created: bool
    saved: tuple[str, ...]
    groups: tuple[ThermostatLoadGroup, ...]

    def __post_init__(self):
        if any(type(value) is not bool for value in (self.evap, self.nonevap, self.remote,
                                                      self.application_created)):
            raise ValueError('Load flags must be Boolean')
        if (type(self.normalized_flags) is not tuple or len(self.normalized_flags) != 2
                or any(type(value) is not int or value not in (0, 1)
                       for value in self.normalized_flags)):
            raise ValueError('Normalized flags must be exact zero/one integers')
        if type(self.roles) is not tuple or len(self.roles) != 3:
            raise ValueError('Load outcome requires three ordered role identities')
        identities = {group.identity for group in self.groups}
        if len(identities) != len(self.groups):
            raise ValueError('Load group identities must be unique')
        if any(role is not None and role not in identities for role in self.roles):
            raise ValueError('Load role must reference an outcome group')
        if type(self.saved) is not tuple or any(type(value) is not str for value in self.saved):
            raise ValueError('Saved object evidence must be a text tuple')

    def as_dict(self):
        return {'evap': self.evap, 'nonevap': self.nonevap, 'remote': self.remote,
                'normalized_flags': {'EvapProgramEnabled': self.normalized_flags[0],
                                     'NonEvapProgramEnabled': self.normalized_flags[1]},
                'roles': dict(zip(ROLES, self.roles)),
                'application_created': self.application_created,
                'saved': list(self.saved),
                'groups': [group.as_dict() for group in self.groups],
                'scope': 'supplied raw bytes and resolved application/group collection',
                'original_afterload_rules_replayed': True,
                'native_persistence_verified': False,
                'inherited_loader_executed': False,
                'physical_device_verified': False}

    def scheduling_state(self):
        """Return the exact JSON shape accepted by thermostat-scheduling."""
        return {'groups': [{'identity': group.identity, 'address': group.address,
                            'levels': [level.as_dict() for level in group.levels]}
                           for group in self.groups],
                'roles': dict(zip(ROLES, self.roles)), 'enabled': self.remote}


class ThermostatUnitLoader:
    """Apply the reviewed AfterLoad scheduling decisions to supplied state."""

    def load(self, raw, *, application_present, groups=(), group_name='Group',
             unused_name='<Unused>'):
        if type(raw) is not dict or set(raw) != set(RAW_FIELDS):
            raise ValueError('Raw state must contain the six exact scheduling fields')
        for name in RAW_FIELDS:
            value = raw[name]
            if type(value) is not int or not 0 <= value <= 255:
                raise ValueError(name + ' must be a byte integer')
        if type(application_present) is not bool:
            raise ValueError('application_present must be Boolean')
        if type(groups) not in (tuple, list) or len(groups) > 256:
            raise ValueError('groups must contain at most 256 records')
        retained = tuple(groups)
        if any(type(group) is not ThermostatLoadGroup for group in retained):
            raise ValueError('groups must contain exact ThermostatLoadGroup records')
        identities = {group.identity for group in retained}
        if len(identities) != len(retained):
            raise ValueError('Group identities must be unique')
        if not application_present and retained:
            raise ValueError('A missing application cannot have retained groups')
        group_name = _text(group_name, 'Standard group name')
        unused_name = _text(unused_name, 'Unused group name', empty=True)

        evap_raw = 0 if raw['EvapProgramEnabled'] > 1 else raw['EvapProgramEnabled']
        nonevap_raw = 1 if raw['NonEvapProgramEnabled'] > 1 else raw['NonEvapProgramEnabled']
        evap, nonevap = evap_raw > 0, nonevap_raw > 0
        remote = evap or nonevap
        current = list(retained)
        saved = []
        application_created = not application_present
        if application_created:
            saved.append('application')

        def create_identity():
            base = 'created-' + str(len(current));identity = base;suffix = 1
            while identity in identities:
                identity = base + '-' + str(suffix);suffix += 1
            identities.add(identity);return identity

        def resolve(address, create):
            found = next((group for group in current if group.address == address), None)
            if found is not None or not create or len(current) >= 256:
                return found
            identity = create_identity()
            group = ThermostatLoadGroup(identity, address,
                unused_name if address == 255 else group_name + ' ' + str(address))
            current.append(group);saved.append(identity);return group

        addresses = (raw['RemoteScheduleOnGroup'], raw['RemoteScheduleOffGroup'],
                     raw['RemoteScheduleOverrideGroup']) if remote else (255, 255, 255)
        roles = tuple((group.identity if group is not None else None)
                      for group in (resolve(address, remote) for address in addresses))
        return ThermostatUnitLoadOutcome(evap, nonevap, remote, (evap_raw, nonevap_raw),
                                         roles, application_created, tuple(saved), tuple(current))
