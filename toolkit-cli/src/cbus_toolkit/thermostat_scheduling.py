"""Retained thermostat scheduling selection and ordered role operations.

Inputs are resolved model state. Loading unit parameters, creating applications
or groups, native persistence, VCL dispatch and Delphi exception unwinding are
separate operations. The button policy and direct outer call are distinct.
Address 255 is the unused sentinel: it is shareable across groups and skipped
during selection/creation (present but never actionable). An all-255 role set
is therefore indistinguishable from an empty role set (both selected/required
False). Button policy with enabled=False is an intentional no-op that still
reports complete:true with only the enabled event. Save locks are 0-2 at rest:
`load` accepts 0-2 and every completed role operation preserves the entry lock.
Callbacks and failed partial states can retain depth 3 while an inner operation
holds its own lock. Such failed states cannot be resumed. Outer group address 0 is real and
actionable (only 255 is exempt); inner ScheduleLevel addresses remain unique
including 255.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from weakref import WeakKeyDictionary

from .thermostat_schedule_levels import ScheduleLevel, ScheduleLevelsEngine, ScheduleLevelsOutcome


ROLES = ('on', 'off', 'override')
ACTIONS = ('Enable', 'Disable', 'Overrd')
COUNTERS = ('level_save_attempts', 'level_save_completed', 'storage_attempts',
            'storage_completed', 'project_requests')


@dataclass(frozen=True)
class ScheduleGroup:
    identity: str
    address: int
    levels: tuple[ScheduleLevel, ...] = ()

    def as_dict(self):
        return {'identity': self.identity, 'address': self.address,
                'levels': [level.as_dict() for level in self.levels]}


@dataclass(frozen=True, eq=False)
class SchedulingState:
    groups: tuple[ScheduleGroup, ...]
    roles: tuple[str | None, str | None, str | None]
    enabled: bool
    save_lock: int = 0
    pending_save: bool = False
    level_save_attempts: int = 0
    level_save_completed: int = 0
    storage_attempts: int = 0
    storage_completed: int = 0
    project_requests: int = 0

    def as_dict(self):
        return {'groups': [group.as_dict() for group in self.groups],
                'roles': dict(zip(ROLES, self.roles)), 'enabled': self.enabled,
                'save_lock': self.save_lock, 'pending_save': self.pending_save,
                **{name: getattr(self, name) for name in COUNTERS}}


@dataclass(frozen=True)
class SchedulingOutcome:
    state: SchedulingState
    document: str

    def as_dict(self):
        return json.loads(self.document)


def _text(value, label):
    if type(value) is not str or not value or len(value) > 128 or '\0' in value:
        raise ValueError(label + ' must be nonempty bounded text without NUL')
    value.encode('utf-8', 'strict')


def _validate(state):
    if type(state) is not SchedulingState or type(state.groups) is not tuple or len(state.groups) > 256:
        raise ValueError('Scheduling state must contain at most 256 exact group records')
    if type(state.roles) is not tuple or len(state.roles) != 3 or type(state.enabled) is not bool:
        raise ValueError('Three ordered role references and a Boolean enable value are required')
    identities = set(); addresses = set()
    for group in state.groups:
        if type(group) is not ScheduleGroup or type(group.levels) is not tuple:
            raise ValueError('Groups must be exact ScheduleGroup records with tuple levels')
        _text(group.identity, 'Group identity')
        if type(group.address) is not int or not 0 <= group.address <= 255:
            raise ValueError('Group address must be a byte integer')
        if group.identity in identities:
            raise ValueError('Group identities must be unique')
        if group.address != 255 and group.address in addresses:
            raise ValueError('Group addresses must be unique except for unused address 255')
        identities.add(group.identity); addresses.add(group.address)
        ScheduleLevelsEngine().load(group.levels)
    for role in state.roles:
        if role is not None and (type(role) is not str or role not in identities):
            raise ValueError('Each role must be null or reference a supplied group identity')
    if type(state.save_lock) is not int or not 0 <= state.save_lock <= 3:
        raise ValueError('Retained save lock must be an integer from 0 through 3')
    if type(state.pending_save) is not bool:
        raise ValueError('Pending save must be Boolean')
    for name in COUNTERS:
        value = getattr(state, name)
        if type(value) is not int or value < 0:
            raise ValueError('Save counters must be nonnegative integers')


def _fingerprint(state):
    _validate(state)
    return repr(state)


def _detached(state):
    return replace(state, groups=tuple(replace(group, levels=tuple(replace(level) for level in group.levels))
                                       for group in state.groups))


def _selection(state, required):
    events = []
    if required:
        events.append({'event': 'enabled', 'value': state.enabled})
        if not state.enabled:
            return False, events
    groups = {group.identity: group for group in state.groups}
    for role, identity in zip(ROLES, state.roles):
        group = groups.get(identity)
        event = {'event': 'group', 'role': role, 'present': group is not None}
        events.append(event)
        if group is None:
            continue
        events.append(dict(event))
        events.append({'event': 'address', 'role': role, 'value': group.address})
        if group.address == 255:
            continue
        if not required:
            return True, events
        events.append(dict(event))
        addresses = {level.address for level in group.levels}
        for address in range(1, 32):
            found = address in addresses
            events.append({'event': 'find', 'role': role, 'address': address, 'create': False, 'found': found})
            if not found:
                return True, events
    return False, events


class ThermostatScheduling:
    """Compose the inner engine with shared group identities and project state.

    Save callbacks receive detached full-state snapshots. Group identity plus
    level identity identifies a level; level identity strings are group-local.
    Failed partial states cannot be resumed. No native writes occur here.
    """

    def __init__(self):
        self._issued = WeakKeyDictionary()
        self._active = False
        self.last_outcome = None
        self.last_error = None

    def _reset(self):
        if self._active:
            raise ValueError('A scheduling operation is already active')
        self.last_outcome = None
        self.last_error = None

    def _issue(self, state, resumable=True):
        self._issued[state] = (_fingerprint(state), resumable)
        return state

    def _require(self, state):
        if type(state) is not SchedulingState or state not in self._issued:
            raise ValueError('Use a state issued by this scheduling manager')
        fingerprint, resumable = self._issued[state]
        if _fingerprint(state) != fingerprint:
            raise ValueError('Issued scheduling state changed')
        if not resumable:
            raise ValueError('A failed partial scheduling state cannot be resumed')

    def load(self, groups, *, on=None, off=None, override=None, enabled=False,
             save_lock=0, pending_save=False):
        self._reset()
        if type(groups) not in (tuple, list) or len(groups) > 256:
            raise ValueError('Supply a list or tuple of at most 256 groups')
        if type(save_lock) is not int or not 0 <= save_lock <= 2:
            raise ValueError('Initial project save lock must be 0, 1 or 2')
        return self._issue(SchedulingState(tuple(groups), (on, off, override), enabled, save_lock, pending_save))

    def selected(self, state):
        self._reset(); self._require(state)
        value, events = _selection(state, False)
        return {'value': value, 'semantic_events': events}

    def required(self, state):
        self._reset(); self._require(state)
        value, events = _selection(state, True)
        return {'value': value, 'semantic_events': events}

    def _publish(self, state, fields, first):
        def encode(value):
            if type(value) in (SchedulingState, ScheduleLevelsOutcome):
                return value.as_dict()
            raise TypeError('Unexpected scheduling evidence value')
        document = {**fields, 'complete': first is None, 'state': state,
                    'native_persistence_verified': False, 'original_ui_executed': False,
                    'original_exception_unwind_executed': False,
                    'input_scope': 'supplied_resolved_thermostat_state'}
        try:
            state = self._issue(state, first is None)
            result = SchedulingOutcome(state, json.dumps(document, default=encode, ensure_ascii=True, separators=(',', ':')))
        except BaseException as error:
            if first is None:
                first = error
            try:
                if state in self._issued:
                    self._issued[state] = (self._issued[state][0], False)
            except BaseException:
                pass
            result = SchedulingOutcome(state, '{"complete":false,"evidence_export_failed":true}')
        self.last_outcome = result
        self.last_error = first
        if first is not None:
            raise first
        return result

    def create_levels(self, state, *, policy='button', level_save=None, storage_save=None):
        self._reset(); self._require(state)
        if type(policy) is not str or policy not in ('button', 'direct'):
            raise ValueError('Policy must be button or direct')
        if any(callback is not None and not callable(callback) for callback in (level_save, storage_save)):
            raise ValueError('Save providers must be callable or absent')
        self._active = True
        current = state
        events = []
        roles = []
        required = None
        first = None
        try:
            if policy == 'button':
                required, checks = _selection(current, True)
                events.extend(checks)
            if policy == 'direct' or required:
                events.extend([{'event': 'cursor', 'value': -11}, {'event': 'delay_started'}])
                for role, identity, action in zip(ROLES, current.roles, ACTIONS):
                    group = next((group for group in current.groups if group.identity == identity), None)
                    event = {'event': 'group', 'role': role, 'present': group is not None}
                    events.append(event)
                    if group is None:
                        continue
                    events.extend([dict(event), {'event': 'address', 'role': role, 'value': group.address}])
                    if group.address == 255:
                        continue
                    events.append(dict(event))
                    baseline = current
                    engine = ScheduleLevelsEngine()
                    inner = engine.load(group.levels, save_lock=current.save_lock, pending_save=current.pending_save)
                    call = {'role': role, 'group': identity, 'action': action, 'complete': False}
                    roles.append(call)

                    def merged(inner_state):
                        replacement = replace(group, levels=inner_state.levels)
                        return replace(baseline, groups=tuple(replacement if item.identity == identity else item for item in baseline.groups),
                                       save_lock=inner_state.save_lock, pending_save=inner_state.pending_save,
                                       **{name: getattr(baseline, name) + getattr(inner_state, name) for name in COUNTERS})

                    def notify(callback, inner_state, level=None):
                        if callback is None:
                            return
                        snapshot = _detached(merged(inner_state))
                        fingerprint = _fingerprint(snapshot)
                        if level is None:
                            callback(snapshot)
                        else:
                            snapshot_group = next(g for g in snapshot.groups if g.identity == identity)
                            snapshot_level = next(v for v in snapshot_group.levels if v.identity == level.identity)
                            callback(identity, snapshot_level, snapshot)
                        if _fingerprint(snapshot) != fingerprint:
                            raise ValueError('Save callback changed its scheduling snapshot')

                    try:
                        outcome = engine.create_levels(inner, action,
                            level_save=(lambda level, snapshot: notify(level_save, snapshot, level)) if level_save is not None else None,
                            storage_save=(lambda snapshot: notify(storage_save, snapshot)) if storage_save is not None else None)
                    finally:
                        outcome = engine.last_outcome
                        if outcome is not None:
                            current = merged(outcome.state)
                            call.update(complete=outcome.complete, state=current, inner=outcome)
                events.extend([{'event': 'delay_finished'}, {'event': 'cursor', 'value': 0}])
        except BaseException as error:
            first = error
        finally:
            self._active = False
        return self._publish(current, {'operation': 'create_remote_schedule_levels', 'policy': policy,
                                      'required': required, 'events': events, 'roles': roles}, first)

    def end_save_lock(self, state, *, storage_save=None):
        """Explicitly release one caller-owned project lock after role operations."""
        self._reset(); self._require(state)
        if not state.save_lock:
            raise ValueError('No outer project save lock remains')
        if storage_save is not None and not callable(storage_save):
            raise ValueError('Storage provider must be callable or absent')
        engine = ScheduleLevelsEngine()
        inner = engine.load((), save_lock=state.save_lock, pending_save=state.pending_save)
        def merged(value):
            return replace(state, save_lock=value.save_lock, pending_save=value.pending_save,
                           **{name: getattr(state, name) + getattr(value, name) for name in COUNTERS})
        def notify(value):
            snapshot = _detached(merged(value)); fingerprint = _fingerprint(snapshot)
            storage_save(snapshot)
            if _fingerprint(snapshot) != fingerprint:
                raise ValueError('Storage callback changed its scheduling snapshot')
        self._active = True
        first = None
        try:
            engine.end_save_lock(inner, storage_save=notify if storage_save is not None else None)
        except BaseException as error:
            first = error
        finally:
            self._active = False
        outcome = engine.last_outcome
        current = merged(outcome.state) if outcome is not None else state
        return self._publish(current, {'operation': 'end_save_lock', 'inner': outcome}, first)
