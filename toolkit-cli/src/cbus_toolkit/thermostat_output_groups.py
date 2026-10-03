"""Ordinary thermostat output loading, ordered selections and typed Add outcomes.

This is a bounded projection of the recovered agent and group dialogs, not
Load Template or the quick-zone lifecycle. The caller supplies one shared
resolver, so earlier setback groups and later schedule groups retain causal
identity. Each selection names an object present after that complete load or
an earlier accepted Add; direct cancellation creates no object.
"""
from __future__ import annotations

from collections.abc import Mapping
import json

from .edlt_add_dialog import (AddDialogError, accept_group_dialog, default_group_name,
    standard_group_name, _message, _rewrite)
from .native import _tail
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


def normalize_output_operations(operations):
    """Bind an immutable ordered history without inventing editable-text events."""
    if operations is None:
        return None
    if type(operations) not in (list, tuple) or len(operations) > 256:
        _fail('Output operations must be an ordered list of at most 256 records')
    result = []
    for row in operations:
        if not isinstance(row, Mapping):
            _fail('Each output operation must be a record')
        op = row.get('op')
        if op == 'select-output-group':
            if set(row) != {'op', 'parameter', 'address'}:
                _fail('Output select operation requires exactly op, parameter and address')
            parameter, address = normalize_output_selections([
                {'parameter': row['parameter'], 'address': row['address']}])[0]
            value = {'op': op, 'parameter': parameter, 'address': address}
        elif op == 'add-output-group':
            if not {'op', 'parameter', 'outcome'} <= set(row) or set(row) - {
                    'op', 'parameter', 'outcome', 'address', 'name'}:
                _fail('Output Add requires op, parameter, outcome and optional address/name')
            parameter, outcome = row['parameter'], row['outcome']
            if type(parameter) is not str or parameter not in OUTPUT_FIELDS:
                _fail('Unknown thermostat output Add parameter: ' + str(parameter))
            if type(outcome) is not str or outcome not in ('accept', 'cancel'):
                _fail('Output Add outcome must be accept or cancel')
            if outcome == 'cancel' and set(row) != {'op', 'parameter', 'outcome'}:
                _fail('Direct-cancel output Add admits no address or name edits')
            value = {'op': op, 'parameter': parameter, 'outcome': outcome}
            if 'address' in row:
                if type(row['address']) is not int or not 0 <= row['address'] <= 254:
                    _fail('Output Add address must be an integer in 0..254')
                value['address'] = row['address']
            if 'name' in row:
                name = row['name']
                if type(name) is not str:
                    _fail('Output Add name must be text')
                try:
                    units = len(name.encode('utf-16-le')) // 2
                except UnicodeEncodeError as error:
                    raise ThermostatTemplateError('Output Add name contains unpaired UTF-16 surrogates') from error
                if units > 32:
                    _fail('Output Add name exceeds 32 UTF-16 code units before trimming')
                value['name'] = name
        else:
            _fail('Unknown thermostat output operation: ' + str(op))
        result.append(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')))
    return tuple(result)


def _safe_added_name(name):
    """Native command/XML admission after the source dialog has trimmed text."""
    try:
        _tail(name)
    except ValueError as error:
        raise ThermostatTemplateError('Output Add native name domain: ' + str(error)) from error
    if any(not (0x20 <= ord(c) <= 0xd7ff or 0xe000 <= ord(c) <= 0xfffd
                or 0x10000 <= ord(c) <= 0x10ffff) for c in name):
        _fail('Output Add name cannot be represented by the native command/XML domain')
    return name


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
        self.operations = None
        self.add_dialogs = []
        self.project_tag_name = None
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

    def _role(self, parameter):
        role = {pp_name(role): role for role in OUTPUTS + DAMPERS + RELAYS}[parameter]
        if not self.eligible(role):
            _fail('Output selector is hidden or disabled in the loaded model: ' + parameter)
        return role

    def _select(self, parameter, address, position):
        role = self._role(parameter)
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
        return {'position': position, 'parameter': parameter, 'address': address,
            'previous_identity': previous.identity if previous else None, 'identity': selected.identity,
            'changed': previous is None or previous.identity != selected.identity}

    def select(self, selections):
        for index, (parameter, address) in enumerate(selections, 1):
            self.history.append(self._select(parameter, address, index))

    def operate(self, operations, *, project_tag_name=None, validate_address):
        """Direct Delphi Add outcomes, interleaved with existing-object choices.

        The prepared controllers are active and their optional BeforeChange/
        CanChange callbacks are unassigned. Source immediate group storage is
        projected onto the owner's graph ledger after complete preflight.
        """
        self.operations = []
        self.project_tag_name = project_tag_name
        for position, encoded in enumerate(operations, 1):
            row = json.loads(encoded)
            parameter = row['parameter']
            if row['op'] == 'select-output-group':
                validate_address(parameter, row['address'])
                receipt = self._select(parameter, row['address'], position)
                self.history.append(receipt)
                self.operations.append(dict(receipt, op=row['op']))
                continue
            role = self._role(parameter)
            groups = {address: group.name for (app, address), group in self.resolver.live.items()
                      if app == self.application}
            free = [address for address in range(255) if address not in groups]
            noun = standard_group_name(self.application)
            if len(groups) >= 256 or not free:
                _fail(_message(2271, noun))
            first = free[0]
            seed = default_group_name(self.application) + ' ' + str(first)
            shown = _rewrite(seed, noun, first)
            previous = self.references[role]
            receipt = {'position': position, 'op': row['op'], 'parameter': parameter,
                'outcome': row['outcome'], 'application': self.application, 'kind': 'Group',
                'first_free_address': first, 'seeded_name': seed, 'shown_name': shown,
                'existing_group_count': len(groups), 'free_address_count': len(free),
                'operator_address': 'address' in row, 'operator_name': 'name' in row,
                'previous_identity': previous.identity if previous else None,
                'identity': previous.identity if previous else None, 'changed': False,
                'object_created': False, 'address': None, 'name': None,
                'address_selected_name': None, 'entered_name': None}
            if row['outcome'] == 'accept':
                if type(project_tag_name) is not str:
                    _fail('Accepted output Add requires an explicit scalar Project.TagName')
                try:
                    accepted = accept_group_dialog(parameter, self.application, groups, project_tag_name,
                        address=row.get('address'), name=row.get('name'))
                except AddDialogError as error:
                    raise ThermostatTemplateError(str(error)) from error
                name = _safe_added_name(accepted.name)
                validate_address(parameter, accepted.address)
                selected = self.resolver.create(self.application, accepted.address, name,
                    'output_add:' + str(position) + ':' + parameter, output_add=True)
                # A fresh identity cannot equal an existing fan peer. Use the
                # same selector gate and assignment as explicit selection.
                assignment = self._select(parameter, selected.address, position)
                address_name = shown if accepted.address == first else _rewrite(shown, noun, accepted.address)
                receipt.update(assignment, name=name, object_created=True,
                    address_selected_name=address_name, entered_name=row.get('name', address_name))
            self.add_dialogs.append(receipt)
            self.operations.append(receipt)

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
        result = {'profile': 'ordinary-agent-load-then-ordered-existing-group-selections',
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
        if self.operations is not None:
            result.update(profile='ordinary-agent-load-then-ordered-output-control-outcomes',
                operations=self.operations, add_dialogs=self.add_dialogs,
                project_tag_name=self.project_tag_name, original_add_storage_callbacks_reproduced=False)
        return result
