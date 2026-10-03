"""Final record projection for optional thermostat remote Level prompts.

The settings transaction owns persistence. This module reproduces the required
predicate, accepted role/address order and final records, not original storage
callbacks or their intermediate generic-name saves.
"""
from dataclasses import dataclass
from typing import Mapping

from .thermostat_schedule_levels import level_to_zones
from .thermostat_templates import ThermostatTemplateError


@dataclass(frozen=True)
class RemoteLevelCreation:
    application: int
    group: int
    group_identity: str
    address: int
    value: int
    initial_name: str
    name: str
    role: str
    phase: str

    @property
    def kind(self):
        return 'Level'

    @property
    def key(self):
        return self.application, self.group, self.address

    def as_dict(self):
        return {'kind': self.kind, 'application': self.application, 'group': self.group,
                'group_identity': self.group_identity, 'address': self.address, 'value': self.value,
                'initial_name': self.initial_name, 'name': self.name, 'role': self.role, 'phase': self.phase}


def normalize_level_prompts(value, family):
    if value is None:
        value = {}
    if (not isinstance(value, Mapping) or any(type(key) is not str or key not in ('setback', 'schedule')
                                             for key in value)):
        raise ThermostatTemplateError('Level prompts must map setback/schedule to accept or decline')
    result = {}
    for phase in ('setback', 'schedule'):
        response = value.get(phase, 'decline')
        if type(response) is not str or response not in ('accept', 'decline'):
            raise ThermostatTemplateError('Level prompt response must be accept or decline: ' + phase)
        result[phase] = response
    if family == 'basic' and result['schedule'] == 'accept':
        raise ThermostatTemplateError('Basic thermostat has no schedule Level prompt to accept')
    return tuple(result.items())


def project_remote_levels(references, *, family, setback_source, schedule_enabled, prompts):
    """Use Address alone for reuse; all existing records remain untouched."""
    choices = dict(prompts)
    creations, receipts = [], {}
    phases = (
        ('setback', setback_source > 0, 'Setbk', (('setback_on', 'Enable'), ('setback_off', 'Disable'))),
        ('schedule', family == 'programmable' and schedule_enabled, 'Sched',
         (('schedule_on', 'Enable'), ('schedule_off', 'Disable'), ('schedule_override', 'Overrd'))),
    )
    for phase, enabled, prefix, roles in phases:
        records = []
        for role, action in roles:
            group = references.get(role)
            if group is None:
                records.append({'role': role, 'application': None, 'group': None, 'group_identity': None,
                                'unused': True, 'missing_addresses': [], 'created_addresses': []})
                continue
            addresses = {level.address for level in group.levels}
            missing = [address for address in range(1, 32) if address not in addresses] if group.address != 255 else []
            records.append({'role': role, 'application': group.application, 'group': group.address,
                            'group_identity': group.identity, 'unused': group.address == 255,
                            'missing_addresses': missing, 'created_addresses': []})
        required = bool(enabled and any(record['missing_addresses'] for record in records))
        execute = required and choices[phase] == 'accept'
        count = 0
        if execute:
            for record, (role, action) in zip(records, roles):
                for address in record['missing_addresses']:
                    creations.append(RemoteLevelCreation(record['application'], record['group'],
                        record['group_identity'], address, address, 'Level ' + str(address),
                        prefix + ' ' + action + ' ' + level_to_zones(address), role, phase))
                    record['created_addresses'].append(address)
                    count += 1
        receipts[phase] = {'requested': choices[phase], 'required': required, 'offered': required,
                           'response_used': choices[phase] if required else None, 'executed': bool(execute),
                           'created_count': count, 'roles': records}
    return tuple(creations), receipts
