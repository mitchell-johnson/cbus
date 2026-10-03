"""Source-owned explicit dual-key panel and unlinked numeric-control callbacks.

These are synchronous named callbacks, not a WinForms event scheduler. Complete
causal PP and retained Names are owner-issued; detached receipts cannot resume.
Numeric input is explicit, so text parsing, modal level selection and linked
LevelControl propagation do not acquire invented behavior.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import re
from weakref import WeakKeyDictionary
from .edlt import EdltError, _field
from .edlt_dual_key_control_properties import (
    FAMILY_TYPES, FAMILY_PROPERTIES, DualKeyPropertyState, checked_names,
    integer, read_dual_key_property, write_dual_key_property,
    force_dual_key_values, dual_key_readonly_view,
)

_ISSUER = object()
_BINDINGS, _STATES, _RESULTS = WeakKeyDictionary(), WeakKeyDictionary(), WeakKeyDictionary()
_HEX = re.compile('[0-9a-f]{64}\\Z')
_LEVELS = {'timer': {'target': 'TargetLevel', 'expiry': 'ExpiryLevel'},
           'shutter': {'preset1': 'TargetLevel1', 'preset2': 'TargetLevel2'}, 'room-courtesy': {}}
_TARGETS = {'timer': {'ramp-rate': 'RampRate', 'icon-on': 'StatusIconOnIndex', 'icon-off': 'StatusIconOffIndex'},
           'shutter': {'macro': 'LeftButtonMacrofunction', 'icon-on': 'StatusIconOnIndex', 'icon-off': 'StatusIconOffIndex'},
           'room-courtesy': {'macro': 'KeyMacrofunction', 'on-colour': 'OnColour', 'off-colour': 'OffColour', 'icon-on': 'StatusIconIndex'}}
_LEVEL_EVENTS = frozenset(('level-read', 'level-value', 'level-set', 'level-no-changed',
    'level-validating', 'level-trackbar-changed', 'level-numeric-changed', 'level-mouse-down',
    'level-enabled', 'level-advanced'))


def _json(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                         allow_nan=False).encode('utf8')
    except (ValueError, TypeError, UnicodeError) as error:
        raise EdltError('Dual-key controls require bounded valid Unicode JSON') from error
    if len(raw) > 4 * 1024 * 1024:
        raise EdltError('Dual-key fact document exceeds its bounded profile')
    return raw


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _pin(value):
    if value is not None and (type(value) is not str or _HEX.fullmatch(value) is None):
        raise EdltError('Dual-key source pin must be an exact lowercase SHA256 or absent')
    return value


def _snapshot(values):
    if not isinstance(values, Mapping) or len(values) > 4096:
        raise EdltError('Dual-key binding requires a complete causal PP mapping')
    result = {}
    for name, raw in values.items():
        if type(name) is str and type(raw) is str:
            result[name] = raw
            continue
        if (type(name) is not str or not isinstance(raw, (list, tuple)) or len(raw) > 4096
                or any(type(v) is not int or not 0 <= v <= 65535 for v in raw)):
            raise EdltError('Dual-key causal PP fields require normalized strings or 16-bit numeric arrays')
        result[name] = tuple(raw)
    _json(result)
    return result


def _record(values, widget, family):
    try:
        rows = tuple(values[_field(widget, offset)] for offset in range(32))
        restore = values[f'Widget{widget}RestoreLevel']
        if any(type(row) is not tuple or len(row) != 1 for row in rows) or len(restore) != 1:
            raise ValueError
        return DualKeyPropertyState(family, bytes(row[0] for row in rows), restore[0])
    except (KeyError, ValueError, TypeError) as error:
        raise EdltError('Dual-key controls require their complete owned byte record and RestoreLevel') from error


def _install(values, widget, model):
    values.update({_field(widget, i): (v,) for i, v in enumerate(model.record)})
    values[f'Widget{widget}RestoreLevel'] = (model.restore_level,)


def choice_identity(family, target, value):
    if family not in FAMILY_TYPES or target not in _TARGETS[family] or target.startswith('icon-'):
        raise EdltError('This dual-key binding has no offered list identity')
    prefix = ('dual-key-ramp' if target == 'ramp-rate' else 'dual-key-colour'
              if target.endswith('colour') else f'dual-key-{family}-macro')
    return f'{prefix}:{value}'


def normalize_dual_key_controls(events, *, family):
    """Strict additive callback schema, before metadata/connection admission."""
    if type(family) is not str or family not in FAMILY_TYPES:
        raise EdltError('Unknown dual-key panel family')
    if not isinstance(events, (list, tuple)) or not 1 <= len(events) <= 512:
        raise EdltError('dual_key_controls require 1..512 explicit callbacks')
    result = []
    for row in events:
        if not isinstance(row, Mapping) or type(row.get('event')) is not str:
            raise EdltError('Dual-key callback requires an explicit event record')
        kind = row['event']
        if kind == 'binding-write':
            target, val = row.get('target'), row.get('value')
            if type(target) is not str or target not in _TARGETS[family]:
                raise EdltError('Dual-key family has no requested visible binding')
            integer(val)
            allowed = (range(256) if target.startswith('icon-') else range(16) if target == 'ramp-rate'
                       else range(9) if target.endswith('colour') else (0, 1) if family == 'shutter' else (255, 25))
            keys = {'event', 'target', 'value'} | (set() if target.startswith('icon-') else {'identity'})
            if set(row) != keys or val not in allowed:
                raise EdltError('Dual-key binding requires an actual offered value and exact fields')
            if 'identity' in row and row['identity'] != choice_identity(family, target, val):
                raise EdltError('Dual-key offered choice identity does not match its value')
        elif kind in _LEVEL_EVENTS:
            if type(row.get('target')) is not str or row['target'] not in _LEVELS[family]:
                raise EdltError('Dual-key family has no requested LevelControl')
            keys = {'event', 'target'}
            if kind in ('level-value', 'level-set', 'level-no-changed', 'level-trackbar-changed', 'level-numeric-changed'):
                keys.add('value')
                val = integer(row.get('value'), 'LevelControl value')
                if kind in ('level-trackbar-changed', 'level-numeric-changed') and not 0 <= val <= 255:
                    raise EdltError('Trackbar/NumericUpDown values must be within 0..255')
            if kind == 'level-mouse-down':
                keys.add('x')
                integer(row.get('x'), 'LevelControl mouse x')
            if kind == 'level-enabled':
                keys.add('enabled')
                if type(row.get('enabled')) is not bool:
                    raise EdltError('LevelControl enabled state requires a Boolean')
            if set(row) != keys:
                raise EdltError('LevelControl callback contains unsupported state or fields')
        elif kind in ('timer-set-value', 'timer-value-changed') and family == 'timer':
            if set(row) != {'event', 'seconds'}:
                raise EdltError('TimerSelector callback requires explicit seconds')
            seconds = integer(row.get('seconds'), 'TimerSelector seconds')
            if kind == 'timer-value-changed' and not 0 <= seconds <= 86399:
                raise EdltError('Explicit DateTime time-of-day seconds require 0..86399')
        elif kind in ('timer-read', 'timer-get', 'timer-write') and family == 'timer' and set(row) == {'event'}:
            pass
        elif kind in ('get-view', 'get-used-static-text', 'force-values') and set(row) == {'event'}:
            pass
        elif kind == 'get-property' and set(row) == {'event', 'property'}:
            if type(row['property']) is not str or row['property'] not in FAMILY_PROPERTIES[family]:
                raise EdltError('Dual-key family does not have that source property')
        elif kind == 'read-properties' and set(row) == {'event', 'properties'}:
            props = row['properties']
            if (not isinstance(props, (list, tuple)) or not 1 <= len(props) <= 32
                    or any(type(prop) is not str or prop not in FAMILY_PROPERTIES[family] for prop in props)
                    or len(set(props)) != len(props)):
                raise EdltError('Dual-key reads require exact family-specific property members')
        elif kind == 'property-changed' and family == 'shutter' and set(row) == {'event', 'property'}:
            if type(row['property']) is not str or len(row['property']) > 256:
                raise EdltError('Shutter PropertyChanged requires a bounded explicit property name')
        else:
            raise EdltError('Unsupported dual-key callback; no implicit GUI parse, modal, close or scheduling')
        result.append(dict(row))
    _json(result)
    return tuple(result)


@dataclass(frozen=True)
class LevelControlState:
    value: int = 0
    trackbar: int = 0
    numeric: int = 0
    enabled: bool = True

    def as_dict(self):
        return {'value': self.value, 'trackbar': self.trackbar, 'numeric': self.numeric,
                'enabled': self.enabled, 'percent': 100 * (self.value + 2) // 255,
                'group_bound': False, 'linked_controls': False}


@dataclass(frozen=True, eq=False)
class DualKeyControlState:
    model: DualKeyPropertyState
    levels: tuple[tuple[str, LevelControlState], ...]
    timer_seconds: int
    _issuer: object = field(repr=False)

    @property
    def pending(self):
        return False

    def as_dict(self):
        return {'levels': {target: control.as_dict() for target, control in self.levels},
            'timer_seconds': self.timer_seconds if self.model.family == 'timer' else None,
            'source_editable_flags': list(self.model.editable),
            'source_virtual_values': list(self.model.virtual_values),
            'pending': False, 'receipt_can_resume': False}


def _state_payload(state):
    return (state.model.family, state.model.record, state.model.restore_level,
        state.model.editable, state.model.virtual_values,
        tuple((target, c.value, c.trackbar, c.numeric, c.enabled) for target, c in state.levels),
        state.timer_seconds)


@dataclass(frozen=True, eq=False)
class DualKeyControlBinding:
    family: str
    widget: int
    operation_number: int
    source_sha256: str
    operation_sha256: str
    names_sha256: str
    project_sha256: str | None
    provider_sha256: str | None
    external_used_indices: tuple[int, ...]
    default_initialized: bool
    _names: tuple[str, ...] = field(repr=False)
    _initial_state: DualKeyControlState | None = field(repr=False)
    _owner: object = field(repr=False)
    _issuer: object = field(repr=False)

    def as_dict(self):
        return {'format': 'cbus-edlt-dual-key-control-binding-v1', 'family': self.family,
            'widget': self.widget, 'operation': self.operation_number,
            'source_sha256': self.source_sha256, 'operation_sha256': self.operation_sha256,
            'retained_names_sha256': self.names_sha256, 'project_sha256': self.project_sha256,
            'provider_sha256': self.provider_sha256, 'external_used_indices': list(self.external_used_indices),
            'model_initialization': 'source-default' if self.default_initialized else 'constructor',
            'snapshot_owned': True, 'receipt_can_resume': False}


def _binding_payload(binding):
    return (binding.family, binding.widget, binding.operation_number, binding.source_sha256,
        binding.operation_sha256, binding.names_sha256, binding.project_sha256,
        binding.provider_sha256, binding.external_used_indices, binding.default_initialized, binding._names,
        binding._initial_state, None if binding._initial_state is None else _state_payload(binding._initial_state))


def issue_dual_key_control_binding(*, owner, operation, values, family, widget, retained_names,
        external_used_indices, operation_number=1, project_sha256=None, provider_sha256=None, initial_state=None, default_initialized=False):
    if (owner is None or type(family) is not str or family not in FAMILY_TYPES
            or type(widget) is not int or not 1 <= widget <= 21
            or type(operation_number) is not int or operation_number < 1
            or not isinstance(operation, Mapping) or operation.get('op') != family
            or type(default_initialized) is not bool or (initial_state is not None and default_initialized)):
        raise EdltError('Invalid dual-key owner/record/operation association')
    normalize_dual_key_controls(operation.get('dual_key_controls'), family=family)
    snapshot, names = _snapshot(values), checked_names(retained_names)
    model = _record(snapshot, widget, family)
    if any(type(snapshot.get(f'StaticTextString{i}')) is not tuple
           or len(snapshot[f'StaticTextString{i}']) != 64
           or any(v > 255 for v in snapshot[f'StaticTextString{i}']) for i in range(64)):
        raise EdltError('Dual-key binding requires all 64 complete byte-backed static PP rows')
    if (type(external_used_indices) is not tuple
            or any(type(v) is not int or not 0 <= v <= 255 for v in external_used_indices)
            or external_used_indices != tuple(sorted(set(external_used_indices)))):
        raise EdltError('Dual-key binding requires an exact sorted external reference roster')
    project_sha256, provider_sha256 = _pin(project_sha256), _pin(provider_sha256)
    if initial_state is not None:
        prior = _STATES.get(initial_state) if type(initial_state) is DualKeyControlState else None
        if (prior is None or initial_state._issuer is not _ISSUER or prior[0] is not owner
                or prior[1] != _state_payload(initial_state)
                or prior[2:7] != (family, widget, _digest(snapshot), _digest(names), (project_sha256, provider_sha256))
                or operation_number <= prior[7] or initial_state.model.record != model.record):
            raise EdltError('Dual-key continuation requires its exact state and current record/Names')
    binding = DualKeyControlBinding(family, widget, operation_number, _digest(snapshot), _digest(operation),
        _digest(names), project_sha256, provider_sha256, external_used_indices, default_initialized, names, initial_state, owner, _ISSUER)
    _BINDINGS[binding] = (owner, _binding_payload(binding))
    return binding


@dataclass(frozen=True, eq=False)
class DualKeyControlResult:
    record: bytes
    restore_level: int
    retained_names: tuple[str, ...]
    changes: tuple[tuple[str, object], ...]
    state: DualKeyControlState
    _receipt_json: str = field(repr=False)
    _owner: object = field(repr=False)
    _issuer: object = field(repr=False)

    @property
    def pending(self):
        return self.state.pending

    def as_dict(self):
        return json.loads(self._receipt_json)


def _result_payload(result):
    return (result.record, result.restore_level, result.retained_names, result.changes,
            result.state, _state_payload(result.state), result._receipt_json)


def prepare_dual_key_projection(result, *, owner):
    original = _RESULTS.get(result) if type(result) is DualKeyControlResult else None
    if (owner is None or original is None or original[0] is not owner or result._issuer is not _ISSUER
            or original[1] != _result_payload(result)):
        raise EdltError('Dual-key projection requires the exact unchanged owner-issued result')
    return result.record, dict(result.changes), result.as_dict()


def project_dual_key_controls(binding, *, owner, operation, values, retained_names):
    prior = _BINDINGS.get(binding) if type(binding) is DualKeyControlBinding else None
    if (owner is None or prior is None or binding._issuer is not _ISSUER or binding._owner is not owner
            or prior[0] is not owner or prior[1] != _binding_payload(binding)):
        raise EdltError('Dual-key projection requires its exact unchanged owner-issued binding')
    snapshot, names = _snapshot(values), checked_names(retained_names)
    if (binding.source_sha256 != _digest(snapshot) or binding.operation_sha256 != _digest(operation)
            or binding.names_sha256 != _digest(names)):
        raise EdltError('Dual-key binding source, operation or full retained Names are stale')
    events = normalize_dual_key_controls(operation.get('dual_key_controls'), family=binding.family)
    model = _record(snapshot, binding.widget, binding.family)
    if binding.default_initialized and binding.family == 'timer':
        model = DualKeyPropertyState(model.family, model.record, model.restore_level, (False, False, False, False))
    if binding._initial_state is not None:
        model = binding._initial_state.model
    levels = dict(binding._initial_state.levels) if binding._initial_state is not None else {
        target: LevelControlState() for target in _LEVELS[binding.family]}
    timer_seconds = binding._initial_state.timer_seconds if binding._initial_state is not None else 0
    journal = []
    for ordinal, event in enumerate(events, 1):
        before, intents, notes, callbacks, observed = model.record, [], [], [], None

        def install(outcome):
            nonlocal model
            model = outcome.state
            intents.extend(outcome.writes)
            notes.extend(outcome.notifications)
            return outcome.value

        def read(prop):
            return install(read_dual_key_property(model, prop, names=names))

        def write(prop, val):
            install(write_dual_key_property(model, prop, val))

        def level_value(target, value, suppress=False):
            """Source Value setter before UpdateControls' NUD recursion."""
            control = levels[target]
            old = control.value
            if old != value:
                callbacks.append({'action': 'OnValueChanged', 'old': old, 'new': value,
                                  'event_delivery_suppressed': suppress})
                callbacks.append({'action': 'Binding.WriteValue', 'target': target, 'value': value})
                write(_LEVELS[binding.family][target], value)
            levels[target] = LevelControlState(value, control.trackbar, control.numeric, control.enabled)
            # UpdateControls always runs, including equal-value assignments.
            callbacks.append({'action': 'UpdateControls', 'target': target, 'value': value})
            if value < 0 or value > 255:
                level_value(target, min(255, max(0, value)), suppress)
            control = levels[target]
            levels[target] = LevelControlState(control.value, control.value, control.value, control.enabled)

        def level_set(target, value):
            if levels[target].value == value:
                callbacks.append({'action': 'SetValue.EqualValueReturn', 'target': target})
                return
            min_level = 6 if binding.family == 'shutter' else 1 if target == 'target' else 0
            max_level = 248 if binding.family == 'shutter' else 255
            level_value(target, min(max_level, max(min_level, value)))

        kind = event['event']
        if kind == 'binding-write':
            target = event['target']
            if target.startswith('icon-') and snapshot.get('UseBigIcon') != (1,):
                raise EdltError('Dual-key icon binding requires the owning UseBigIcon setting enabled')
            callbacks.append({'action': 'Binding.WriteValue', 'target': target, 'value': event['value']})
            write(_TARGETS[binding.family][target], event['value'])
        elif kind in _LEVEL_EVENTS:
            target = event['target']
            if kind == 'level-read':
                val = read(_LEVELS[binding.family][target])
                callbacks.append({'action': 'Binding.ReadValue', 'target': target, 'value': val})
                level_value(target, val)
            elif kind == 'level-validating':
                callbacks.append({'action': 'Binding.WriteValue', 'target': target, 'value': levels[target].value})
                write(_LEVELS[binding.family][target], levels[target].value)
            elif kind in ('level-value', 'level-no-changed'):
                level_value(target, event['value'], kind == 'level-no-changed')
            elif kind in ('level-set', 'level-trackbar-changed', 'level-numeric-changed'):
                level_set(target, event['value'])
            elif kind == 'level-mouse-down':
                # CIL sub wraps Int32 before the source double calculation;
                # Convert.ToInt32 then uses ties-to-even.
                x = ((event['x'] - 7 + (1 << 31)) & 0xffffffff) - (1 << 31)
                val = round(min(255.0, x / 132.0 * 255.0 if x >= 0 else 0.0))
                c = levels[target]
                levels[target] = LevelControlState(c.value, val, c.numeric, c.enabled)
                callbacks.append({'action': 'Trackbar.Value', 'target': target, 'value': val,
                                  'ValueChanged_dispatch_inferred': False})
            elif kind == 'level-enabled':
                c = levels[target]
                levels[target] = LevelControlState(c.value, c.trackbar, c.numeric, event['enabled'])
                callbacks.append({'action': 'OnEnabledChanged.BorderStyle', 'value': 1 if event['enabled'] else 0})
            else:
                callbacks.append({'action': 'AdvancedClick.EmptyHandler'})
            observed = levels[target].as_dict()
        elif kind.startswith('timer-'):
            if kind == 'timer-read':
                raw = read('TimerValue')
                timer_seconds = min(64800, max(0, raw))
                callbacks.append({'action': 'Binding.ReadValue', 'target': 'timer-value', 'value': raw})
                callbacks.append({'action': 'TimerSelector.TimerValue.set', 'display_seconds': timer_seconds})
            elif kind in ('timer-set-value', 'timer-value-changed'):
                timer_seconds = min(64800, max(0, event['seconds']))
                callbacks.append({'action': 'TimerSelector.TimerValue.set' if kind == 'timer-set-value' else 'TimerSelector.OnValueChanged',
                                  'display_seconds': timer_seconds, 'binding_dispatch_inferred': False})
            elif kind == 'timer-write':
                callbacks.append({'action': 'Binding.WriteValue', 'target': 'timer-value', 'value': timer_seconds})
                write('TimerValue', timer_seconds)
            observed = timer_seconds
        elif kind == 'get-property':
            observed = read(event['property'])
        elif kind == 'read-properties':
            observed = {prop: read(prop) for prop in event['properties']}
        elif kind == 'get-view':
            observed = dual_key_readonly_view(model, names=names)
        elif kind == 'get-used-static-text':
            observed = list(model.used_static_text())
        elif kind == 'force-values':
            install(force_dual_key_values(model))
        elif kind == 'property-changed':
            if event['property'] in ('LeftButtonMacrofunction', 'RightButtonMacrofunctin'):
                notes.append('TargetLevel1Editable')
        journal.append({'event_index': ordinal, 'event': event, 'record_before_hex': before.hex(),
            'record_after_hex': model.record.hex(),
            'assignment_intents': [{'offset': i, 'value': v} for i, v in intents],
            'notification_intents': notes, 'binding_callbacks': callbacks, 'observed': observed})
    projected = dict(snapshot)
    _install(projected, binding.widget, model)
    changes = tuple(sorted((k, v) for k, v in projected.items() if v != snapshot[k]))
    state = DualKeyControlState(model, tuple(sorted(levels.items())), timer_seconds, _ISSUER)
    _STATES[state] = (owner, _state_payload(state), binding.family, binding.widget,
                     _digest(projected), _digest(names), (binding.project_sha256, binding.provider_sha256), binding.operation_number)
    receipt = {'format': 'cbus-edlt-dual-key-controls-v1', 'binding': binding.as_dict(),
        'record_hex': model.record.hex(), 'restore_level': model.restore_level,
        'state': state.as_dict(), 'journal': journal, 'pending': False,
        'used_static_text': list(model.used_static_text()), 'retained_names_sha256': _digest(names),
        'automatic_framework_dispatch_inferred': False, 'original_host_executed': False,
        'physical_device_verified': False, 'receipt_can_resume': False}
    result = DualKeyControlResult(model.record, model.restore_level, names, changes, state,
                                 _json(receipt).decode('utf8'), owner, _ISSUER)
    _RESULTS[result] = (owner, _result_payload(result))
    return result
