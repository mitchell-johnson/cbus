"""Ordinary thermostat output loading and ordered existing-group selections.

This is a bounded projection of the recovered agent and group dialogs, not
Load Template or the quick-zone lifecycle. The caller supplies one shared
resolver, so earlier setback groups and later schedule groups retain causal
identity. Every selection names an object present after that complete load.
"""
from __future__ import annotations

from collections.abc import Mapping

from .thermostat_post_load import (OUTPUTS, DAMPERS, RELAYS, INSTALLATION_NAMES,
    DAMPER_NAMES, _default_name, pp_name, virtual_plant_type)
from .thermostat_templates import ThermostatTemplateError
from .unitspec import _integer

OUTPUT_FIELDS = tuple(pp_name(role) for role in OUTPUTS + DAMPERS + RELAYS)
OUTPUT_READ_FIELDS = OUTPUT_FIELDS + ('ApplicationNumber', 'ZoneGroup', 'InstallationCode',
    'ControlledZones', 'InternalPlantType', 'InternalPlantZones')
COOLING_PLANTS = frozenset((2, 3, 5, 6, 7, 9, 10, 11))


def _fail(message):
    raise ThermostatTemplateError(message)


def normalize_output_selections(selections):
    if selections is None:
        return None
    if type(selections) not in (list, tuple):
        _fail('Output selections must be an ordered list of parameter/address records')
    if len(selections) > 256:
        _fail('Output selection history exceeds 256 operations')
    result = []
    for row in selections:
        if not isinstance(row, Mapping) or set(row) != {'parameter', 'address'}:
            _fail('Each output selection requires exactly parameter and address')
        parameter, address = row['parameter'], row['address']
        if type(parameter) is not str or parameter not in OUTPUT_FIELDS:
            _fail('Unknown thermostat output selection: ' + str(parameter))
        if type(address) not in (int, str):
            _fail('Output group address must be an integer byte')
        try:
            address = _integer(str(address))
        except ValueError as error:
            raise ThermostatTemplateError('Output group address must be an integer byte') from error
        if not 0 <= address <= 255:
            _fail('Output group address must be 0..255')
        result.append((parameter, address))
    return tuple(result)


class OutputGroupModel:
    """One retained ordinary model, with explicit post-load control history."""

    def __init__(self, values, family, unit_type, resolver):
        self.values, self.family, self.unit_type = values, family, unit_type
        self.resolver = resolver
        self.application = values['ApplicationNumber']
        if not (48 <= self.application <= 95 or self.application == 203):
            _fail('Output groups admit selected Lighting applications 48..95 or Enable Control 203')
        # These source getters precede inherited remote/output getters.
        # Other inherited special applications (115/116) have no dependency
        # on this prefix or the owned references and remain outside this lane.
        resolver.application(172, 'output_zone_application', False, creation_name='Air Conditioning')
        zone = resolver.group(172, values['ZoneGroup'], True, 'output_zone_group', enable_application=False)
        if values['InternalPlantType'] > 11:
            _fail('Ordinary output loading admits raw InternalPlantType 0..11')
        self.plant = virtual_plant_type(values)
        self.master = values['ControlledZones'] > 0
        code = values['InstallationCode']
        self.installation = code if code <= 9 else 1
        self.installation_name = INSTALLATION_NAMES.get(self.installation)
        self.prefix = '[CG' + format(zone.address, '02d') + ']'
        self.zone_identity = zone.identity
        self.references = {}
        self.loaded = {}
        self.history = []
        resolver.application(self.application, 'output_application', False,
            creation_name={56: 'Lighting', 95: 'DALI', 203: 'Enable Control'}.get(
                self.application, str(self.application)))

    def _lookup(self, address, role):
        return self.resolver.group(self.application, address, False, role, enable_application=False)

    def _unused(self, role):
        return self.resolver.group(self.application, 255, True, role, enable_application=False)

    def _default(self, existing, address, label, role):
        tag = self.prefix + ' ' + label
        if existing is not None:
            # Ordinary CreateAndRenameGroup does not seek a same-tag object
            # before renaming an already resolved source-address object.
            return self.resolver.rename(existing, tag, role)
        inventory = [group for (app, _), group in self.resolver.live.items() if app == self.application]
        if any(not group.name.isascii() for group in inventory):
            _fail('Missing output default lookup requires an ASCII group-name inventory')
        matches = [group for group in inventory if group.name.lower() == tag.lower()]
        if len(matches) > 1:
            _fail('Generated output group name is ambiguous without original manager order: ' + tag)
        self.resolver.getters.append({'getter': 'FindExistingGroup', 'role': role,
            'application': self.application, 'name': tag,
            'identity': matches[0].identity if matches else None})
        return matches[0] if matches else self.resolver.create(self.application, address, tag, role)

    def load(self):
        for role in OUTPUTS:
            address = self.values[pp_name(role)]
            if address == 255:
                group = self._unused(role)
            else:
                group = self._lookup(address, role)
                if group is None or group.name.startswith(self.prefix):
                    label = _default_name(role, self.plant, self.installation_name)
                    if label is not None:
                        group = self._default(group, address, label, role)
                    elif group is None:
                        group = self._unused(role)
            self.references[role] = group
        for role in DAMPERS:
            address = self.values[pp_name(role)]
            if self.family == 'basic':
                group = self._lookup(255, role)
            elif address == 255:
                group = self._unused(role)
            else:
                group = self._lookup(address, role)
                # Unlike output defaults, ordinary damper getters retain any
                # existing object, including one bearing this unit's prefix.
                if group is None:
                    group = self._default(None, address, DAMPER_NAMES[role], role)
            self.references[role] = group
        for role in RELAYS:
            self.references[role] = self.resolver.group(self.application, self.values[pp_name(role)],
                True, role, enable_application=False)
        self.loaded = dict(self.references)

    def eligible(self, role):
        if role in OUTPUTS[:7]:
            return self.plant in COOLING_PLANTS
        if role in OUTPUTS[7:]:
            return self.plant not in (0, 2, 5) and not (self.plant == 8 and role.startswith('HeatFan'))
        if role in DAMPERS:
            return (self.family == 'programmable' and self.plant != 0
                    and bool(self.values['InternalPlantZones'] & 30))
        return self.unit_type in ('PC_TSA5', 'PC_TSB5') and self.master

    def select(self, selections):
        by_parameter = {pp_name(role): role for role in OUTPUTS + DAMPERS + RELAYS}
        for index, (parameter, address) in enumerate(selections, 1):
            role = by_parameter[parameter]
            if not self.eligible(role):
                _fail('Output selector is hidden or disabled in the loaded model: ' + parameter)
            selected = self.resolver.live.get((self.application, address))
            if selected is None:
                _fail('Output selection requires an existing group after ordinary load: ' + str(address))
            if address != 255 and role.startswith(('CoolFan', 'HeatFan')):
                peers = [name for name in OUTPUTS if name.startswith(role[:7]) and name != role]
                if any(self.references[name] is not None and self.references[name].identity == selected.identity
                       for name in peers):
                    _fail('Fan selector excludes a group currently used by another speed: ' + parameter)
            previous = self.references[role]
            self.references[role] = selected
            self.history.append({'position': index, 'parameter': parameter, 'address': address,
                'previous_identity': previous.identity if previous else None, 'identity': selected.identity,
                'changed': previous is None or previous.identity != selected.identity})

    def validate(self):
        for roles, label in ((OUTPUTS[:7], 'cooling'), (OUTPUTS[7:], 'heating'), (DAMPERS, 'damper')):
            selected = [self.references[role] for role in roles
                        if self.references[role] is not None and self.references[role].address != 255]
            if len({group.identity for group in selected}) != len(selected):
                _fail('Original output validation rejects duplicate ' + label + ' group identities')

    @property
    def expected(self):
        return {pp_name(role): 255 if group is None or (role in DAMPERS and not self.master)
                else group.address for role, group in self.references.items()}

    def as_dict(self):
        def roles(rows):
            return {pp_name(role): None if group is None else {
                'address': group.address, 'identity': group.identity,
                'name': self.resolver.current(group).name} for role, group in rows.items()}
        return {'profile': 'ordinary-agent-load-then-ordered-existing-group-selections',
            'application': self.application, 'zone_group_identity': self.zone_identity,
            'prefix': self.prefix, 'virtual_plant_type': self.plant,
            'installation_code': self.installation, 'installation_name': self.installation_name,
            'loaded_master': self.master, 'loaded_references': roles(self.loaded),
            'resolved_references': roles(self.references), 'selections': self.history,
            'selectors_enabled': {pp_name(role): self.eligible(role) for role in OUTPUTS + DAMPERS + RELAYS},
            'expected': self.expected, 'validation': {'passed': True,
                'separate_cooling_heating_damper_uniqueness': True, 'cross_collection_sharing_allowed': True,
                'relay_uniqueness_required': False},
            'selection_creates_groups': False, 'complete_form_lifecycle_reproduced': False,
            'zone_history_or_template_callbacks_reproduced': False}
