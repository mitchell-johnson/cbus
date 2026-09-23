"""Offline thermostat scheduling selection, composition and lock release.

Reads one resolved-state JSON document, evaluates the retained outer
selection predicates, composes missing levels without save providers, or
releases one caller-owned project lock, and reports the outcome. Loading
unit parameters, native persistence, VCL dispatch and device operation are
separate operations.
"""
from __future__ import annotations

import json
from pathlib import Path

from .thermostat_schedule_levels import ScheduleLevel
from .thermostat_scheduling import ScheduleGroup, ThermostatScheduling
from .thermostat_unit_load import RAW_FIELDS, ThermostatLoadGroup, ThermostatUnitLoader

SCOPE = ('Supplied resolved thermostat state only; no unit load, native '
         'persistence, VCL dispatch or device operation')
SCOPE_CREATE = ('Supplied resolved state with no save providers; no native '
                'persistence, VCL dispatch or device operation')
SCOPE_LOAD = ('Supplied raw scheduling bytes and resolved application/group collection; '
              'no inherited loader, native persistence, VCL dispatch or device operation')
MAX_STATE_BYTES = 1024 * 1024


def _level(raw, where):
    if type(raw) is not dict or set(raw) != {'identity', 'address', 'value', 'tag'}:
        raise ValueError(where + ' level must define exactly identity, address, value and tag')
    identity, address, value, tag = raw['identity'], raw['address'], raw['value'], raw['tag']
    if type(identity) is not str or not identity or len(identity) > 128 or '\0' in identity:
        raise ValueError(where + ' level identity must be nonempty bounded text without NUL')
    if type(address) is not int or not 0 <= address <= 255:
        raise ValueError(where + ' level address must be a byte integer')
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(where + ' level Value must be a byte integer')
    if type(tag) is not str or len(tag) > 128 or '\0' in tag:
        raise ValueError(where + ' level tag must be bounded text without NUL')
    identity.encode('utf-8', 'strict')
    tag.encode('utf-8', 'strict')
    return ScheduleLevel(identity, address, value, tag)


def _groups(raw):
    if type(raw) is not list or len(raw) > 256:
        raise ValueError('State groups must be a list of at most 256 records')
    groups = []
    for index, item in enumerate(raw):
        where = 'Group %d' % index
        if type(item) is not dict or set(item) != {'identity', 'address', 'levels'}:
            raise ValueError(where + ' must define exactly identity, address and levels')
        identity, address, levels = item['identity'], item['address'], item['levels']
        if type(identity) is not str or not identity or len(identity) > 128 or '\0' in identity:
            raise ValueError(where + ' identity must be nonempty bounded text without NUL')
        if type(address) is not int or not 0 <= address <= 255:
            raise ValueError(where + ' address must be a byte integer')
        if type(levels) is not list or len(levels) > 256:
            raise ValueError(where + ' levels must be a list of at most 256 records')
        identity.encode('utf-8', 'strict')
        groups.append(ScheduleGroup(identity, address, tuple(_level(entry, where) for entry in levels)))
    return groups


def _state(raw):
    if type(raw) is not dict or not {'groups', 'roles', 'enabled'} <= set(raw) <= {'groups', 'roles', 'enabled', 'save_lock', 'pending_save'}:
        raise ValueError('State must define groups, roles and enabled with optional save_lock and pending_save')
    if type(raw['enabled']) is not bool:
        raise ValueError('State enabled must be Boolean')
    save_lock = raw.get('save_lock', 0)
    if type(save_lock) is not int or not 0 <= save_lock <= 2:
        raise ValueError('State save_lock must be 0, 1 or 2')
    pending_save = raw.get('pending_save', False)
    if type(pending_save) is not bool:
        raise ValueError('State pending_save must be Boolean')
    roles = raw['roles']
    if type(roles) is not dict or set(roles) != {'on', 'off', 'override'}:
        raise ValueError('State roles must define exactly on, off and override')
    for name in ('on', 'off', 'override'):
        value = roles[name]
        if value is not None and (type(value) is not str or not value or len(value) > 128):
            raise ValueError('Role references must be null or bounded identity text')
    return _groups(raw['groups']), roles['on'], roles['off'], roles['override'], raw['enabled'], save_lock, pending_save


def _load(path):
    if not isinstance(path, Path):
        raise ValueError('State path is required')
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError('Cannot read state file: ' + str(error)) from error
    if len(data) > MAX_STATE_BYTES or not data:
        raise ValueError('State file must be nonempty and at most 1 MiB')
    try:
        raw = json.loads(data.decode('utf-8'))
    except (UnicodeError, ValueError) as error:
        raise ValueError('State file must be UTF-8 JSON: ' + str(error)) from error
    return _state(raw)


def _unit_load(path):
    if not isinstance(path, Path):
        raise ValueError('Unit-load path is required')
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError('Cannot read unit-load file: ' + str(error)) from error
    if len(data) > MAX_STATE_BYTES or not data:
        raise ValueError('Unit-load file must be nonempty and at most 1 MiB')
    try:
        raw = json.loads(data.decode('utf-8'))
    except (UnicodeError, ValueError) as error:
        raise ValueError('Unit-load file must be UTF-8 JSON: ' + str(error)) from error
    if type(raw) is not dict or set(raw) != {'raw', 'application_present', 'groups'}:
        raise ValueError('Unit-load document must define exactly raw, application_present and groups')
    if type(raw['raw']) is not dict or set(raw['raw']) != set(RAW_FIELDS):
        raise ValueError('Unit-load raw state must contain the six exact scheduling fields')
    if type(raw['groups']) is not list or len(raw['groups']) > 256:
        raise ValueError('Unit-load groups must be a list of at most 256 records')
    groups = []
    for index, group in enumerate(raw['groups']):
        if type(group) is not dict or set(group) != {'identity', 'address', 'tag'}:
            raise ValueError('Unit-load group %d must define identity, address and tag' % index)
        groups.append(ThermostatLoadGroup(**group))
    return raw['raw'], raw['application_present'], groups


def options(commands):
    parser = commands.add_parser('thermostat-scheduling',
                                 help='Evaluate retained outer scheduling selection over supplied state')
    actions = parser.add_subparsers(dest='action', required=True)
    load = actions.add_parser('load', help='Resolve retained scheduling state from supplied raw bytes')
    load.add_argument('state', type=Path, help='Raw scheduling/application/group JSON document')
    load.add_argument('--group-name', default='Group', help='Supplied standard group label used for created non-255 groups')
    load.add_argument('--unused-name', default='<Unused>', help='Supplied label used for a created group 255')
    for name in ('selected', 'required'):
        sub = actions.add_parser(name, help='Evaluate the ' + name + ' predicate')
        sub.add_argument('state', type=Path, help='Resolved-state JSON document')
    create = actions.add_parser('create-levels', help='Compose missing levels without save providers')
    create.add_argument('state', type=Path, help='Resolved-state JSON document')
    create.add_argument('--policy', choices=('button', 'direct'), default='button',
                        help='Button applies selection gating; direct composes unconditionally')
    release = actions.add_parser('end-save-lock', help='Release one caller-owned project lock without storage')
    release.add_argument('state', type=Path, help='Resolved-state JSON document')


def run(args):
    if args.area != 'thermostat-scheduling' or args.action not in ('load', 'selected', 'required', 'create-levels', 'end-save-lock'):
        raise ValueError('Unsupported thermostat scheduling command')
    if args.action == 'load':
        raw, application_present, groups = _unit_load(args.state)
        outcome = ThermostatUnitLoader().load(raw, application_present=application_present,
            groups=groups, group_name=args.group_name, unused_name=args.unused_name)
        return {**outcome.as_dict(), 'scheduling_state': outcome.scheduling_state(),
                'scope': SCOPE_LOAD}, 0
    groups, on, off, override, enabled, save_lock, pending_save = _load(args.state)
    model = ThermostatScheduling()
    state = model.load(groups, on=on, off=off, override=override, enabled=enabled,
                       save_lock=save_lock, pending_save=pending_save)
    if args.action in ('selected', 'required'):
        outcome = model.selected(state) if args.action == 'selected' else model.required(state)
        return {'predicate': args.action, 'value': outcome['value'],
                'semantic_events': outcome['semantic_events'], 'scope': SCOPE}, 0
    if args.action == 'end-save-lock':
        outcome = model.end_save_lock(state)
        return {**outcome.as_dict(), 'scope': SCOPE_CREATE}, 0
    if type(args.policy) is not str or args.policy not in ('button', 'direct'):
        raise ValueError('Policy must be button or direct')
    outcome = model.create_levels(state, policy=args.policy)
    return {**outcome.as_dict(), 'scope': SCOPE_CREATE}, 0
