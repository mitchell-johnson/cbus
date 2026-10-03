"""Source-owned MRA panel callbacks; no host or service I/O.

The owner supplies a causal postordinary record, the complete retained Names,
and references belonging to the rest of the unit. Detached receipts cannot
resume controls. Binding.WriteValue is explicit; update-mode declarations do
not synthesize property changes, visibility callbacks or modal picker actions.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import re
from weakref import WeakKeyDictionary

from .edlt import EdltError, _field
from .edlt_mra_control_properties import (
    FAMILY_TYPES, OFFSETS, MRAPropertyState, checked_names, read_mra_property,
    write_mra_property, mra_readonly_view,
)
from .edlt_scene_name_control import (
    SceneNameControlState, normalize_events as static_events,
    run_scene_name_control,
)
from .edlt_scene_names import FIXED_SUGGESTION_NAMES, assign_name, save_names

_ISSUER = object()
_BINDINGS = WeakKeyDictionary()
_STATES = WeakKeyDictionary()
_RESULTS = WeakKeyDictionary()
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_TEXT_EVENTS = frozenset(('input', 'enter', 'leave', 'arrow-preview',
                         'selected-name', 'list-refresh', 'close'))
_PROPERTIES = frozenset((
    'StatusDisplayType', 'StatusDisplayValueEditable', 'Zone', 'Multiplexer',
    'BigIconOnIndex', 'BigIconOffIndex', 'FunctionVariant',
    'LabelValueIndex', 'LabelValueText', 'StatusValueIndex', 'StatusValueText',
    'LeftButtonMacrofunction', 'RightButtonMacrofunction', 'RampRate', 'Offset',
    'RampRateEditable', 'OffsetEditable', 'AbsoluteSource1', 'AbsoluteSource2',
    'AbsoluteSource1Editable', 'AbsoluteSource2Editable', 'AnyAbsoluteSourceEditable',
))
_ZONE_PROPERTIES = frozenset(('LeftButtonMacrofunction', 'RightButtonMacrofunction',
    'RampRate', 'Offset', 'RampRateEditable', 'OffsetEditable'))
_SELECT_PROPERTIES = frozenset(('AbsoluteSource1', 'AbsoluteSource2',
    'AbsoluteSource1Editable', 'AbsoluteSource2Editable', 'AnyAbsoluteSourceEditable'))
_FAMILY_PROPERTIES = {
    family: _PROPERTIES - (_SELECT_PROPERTIES if family != 'source-select' else frozenset())
        - (_ZONE_PROPERTIES if family != 'zone-control' else frozenset())
        - ({'StatusValueIndex', 'StatusValueText'} if family == 'source-control' else frozenset())
    for family in FAMILY_TYPES
}
_TARGET_PROPERTIES = {'variant': 'FunctionVariant', 'status-type': 'StatusDisplayType',
    'macro': 'DualButtonMacrofunction', 'ramp-rate': 'RampRate',
    'source1': 'AbsoluteSource1', 'source2': 'AbsoluteSource2',
    'icon-on': 'BigIconOnIndex', 'icon-off': 'BigIconOffIndex'}
_BASE_TARGETS = frozenset(('variant', 'icon-on'))
_FAMILY_TARGETS = {
    'zone-control': _BASE_TARGETS | {'status-type', 'macro', 'ramp-rate', 'icon-off'},
    'source-select': _BASE_TARGETS | {'source1', 'source2'},
    'source-control': _BASE_TARGETS,
}


def _json(value):
    try:
        result = json.dumps(value, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False, allow_nan=False).encode('utf8')
    except (ValueError, TypeError, UnicodeError) as error:
        raise EdltError('MRA controls require bounded valid Unicode JSON facts') from error
    if len(result) > 4 * 1024 * 1024:
        raise EdltError('MRA control fact document exceeds the bounded profile')
    return result


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _pin(value, what):
    if value is not None and (type(value) is not str or _HEX.fullmatch(value) is None):
        raise EdltError(f'MRA {what} must be an exact lowercase SHA256 or absent')
    return value


def _snapshot(values):
    if not isinstance(values, Mapping) or len(values) > 4096:
        raise EdltError('MRA binding requires the complete causal PP mapping')
    result = {}
    for name, raw in values.items():
        if type(name) is str and type(raw) is str:
            result[name] = raw
            continue
        if (type(name) is not str or not isinstance(raw, (list, tuple))
                or len(raw) > 4096
                or any(type(v) is not int or not 0 <= v <= 65535 for v in raw)):
            raise EdltError('MRA causal PP fields require normalized strings or 16-bit numeric arrays')
        result[name] = tuple(raw)
    _json(result)
    return result


def _record(values, widget, family):
    try:
        rows = tuple(values[_field(widget, offset)] for offset in range(32))
        restore = values[f'Widget{widget}RestoreLevel']
        if any(len(row) != 1 for row in rows) or len(restore) != 1:
            raise ValueError
        return MRAPropertyState(family, bytes(row[0] for row in rows), restore[0])
    except (KeyError, ValueError, TypeError) as error:
        raise EdltError('MRA controls require one complete owned 32-byte record and RestoreLevel') from error


def _install(values, widget, state):
    values.update({_field(widget, offset): (value,)
                   for offset, value in enumerate(state.record)})
    values[f'Widget{widget}RestoreLevel'] = (state.restore_level,)


def choice_identity(family, target, value):
    if target == 'variant':
        return f'mra-{family}-variant:{value}'
    prefixes = {'status-type': 'mra-status', 'macro': 'mra-zone-macro',
                'ramp-rate': 'mra-ramp', 'source1': 'mra-source', 'source2': 'mra-source'}
    try:
        return f'{prefixes[target]}:{value}'
    except KeyError as error:
        raise EdltError('This MRA Index binding is not an offered list-choice identity') from error


def _choice(family, target, value):
    if target == 'macro':
        return type(value) is str and value in ('15|16', '21|22')
    if type(value) is not int:
        return False
    if target == 'variant':
        return value in range(4 if family == 'zone-control' else 3)
    if target == 'status-type':
        return value in (0, 3, 1, 2, 5)
    if target == 'ramp-rate':
        return value in range(16)
    if target in ('source1', 'source2'):
        return value in range(7)
    return target in ('icon-on', 'icon-off') and value in range(256)


def normalize_mra_controls(events, *, family):
    """Validate additive explicit callbacks before a connection/model read.

    enter is the Enter key, not focus Enter. Icon Index writes specify only a
    source binding value; they do not assert which modal image was selected.
    """
    if type(family) is not str or family not in FAMILY_TYPES:
        raise EdltError('Unknown derived MRA family')
    if not isinstance(events, (list, tuple)) or not 1 <= len(events) <= 512:
        raise EdltError('mra_controls require 1..512 explicit ordered callbacks')
    result = []
    for row in events:
        if not isinstance(row, Mapping):
            raise EdltError('MRA events require explicit records')
        kind = row.get('event')
        if type(kind) is not str:
            raise EdltError('MRA callback event name must be a string')
        if kind == 'binding-write':
            target = row.get('target')
            if type(target) is not str or target not in _FAMILY_TARGETS[family] or not _choice(family, target, row.get('value')):
                raise EdltError('MRA binding write is outside the actual panel choices')
            keys = {'event', 'target', 'value'} if target.startswith('icon-') else {
                'event', 'target', 'value', 'identity'}
            if set(row) != keys:
                raise EdltError('MRA binding write requires its exact offered choice identity')
            if 'identity' in row and row['identity'] != choice_identity(family, target, row['value']):
                raise EdltError('MRA binding choice identity does not match its actual value')
            result.append(dict(row))
        elif kind in _TEXT_EVENTS:
            target = row.get('target')
            if type(target) is not str or target not in OFFSETS[family]:
                raise EdltError('MRA family has no requested static Text binding')
            normalized = static_events([{key: value for key, value in row.items() if key != 'target'}])[0]
            result.append({'target': target, **normalized})
        elif kind == 'get-zone-macro' and set(row) == {'event'} and family == 'zone-control':
            result.append(dict(row))
        elif kind in ('get-view', 'get-used-static-text') and set(row) == {'event'}:
            result.append(dict(row))
        elif kind == 'get-property' and set(row) == {'event', 'property'} and type(row['property']) is str and row['property'] in _FAMILY_PROPERTIES[family]:
            result.append(dict(row))
        elif kind == 'read-properties' and set(row) == {'event', 'properties'}:
            props = row['properties']
            if (not isinstance(props, (list, tuple)) or not 1 <= len(props) <= 32
                    or any(type(prop) is not str or prop not in _FAMILY_PROPERTIES[family] for prop in props)
                    or len(set(props)) != len(props)):
                raise EdltError('MRA reads require exact nonmutating property names')
            result.append({'event': kind, 'properties': list(props)})
        else:
            raise EdltError('Unsupported MRA callback; raw properties/defaults belong to the separate model API')
    _json(result)
    return tuple(result)


@dataclass(frozen=True, eq=False)
class MRAControlState:
    controls: tuple[tuple[str, SceneNameControlState], ...]
    closed_targets: tuple[str, ...]
    _issuer: object = field(repr=False)

    @property
    def pending(self):
        return any(control.pending for _, control in self.controls)

    def as_dict(self):
        return {'controls': {target: control.as_dict() for target, control in self.controls},
                'closed_targets': list(self.closed_targets),
                'pending': self.pending, 'receipt_can_resume': False}


@dataclass(frozen=True, eq=False)
class MRAControlBinding:
    family: str
    widget: int
    operation_number: int
    source_sha256: str
    operation_sha256: str
    names_sha256: str
    project_sha256: str | None
    provider_sha256: str | None
    external_used_indices: tuple[int, ...]
    _names: tuple[str, ...] = field(repr=False)
    _initial_state: MRAControlState | None = field(repr=False)
    _owner: object = field(repr=False)
    _issuer: object = field(repr=False)

    def as_dict(self):
        return {'format': 'cbus-edlt-mra-control-binding-v1', 'family': self.family,
                'widget': self.widget, 'operation': self.operation_number,
                'source_sha256': self.source_sha256, 'operation_sha256': self.operation_sha256,
                'retained_names_sha256': self.names_sha256,
                'project_sha256': self.project_sha256, 'provider_sha256': self.provider_sha256,
                'external_used_indices': list(self.external_used_indices),
                'snapshot_owned': True, 'receipt_can_resume': False}


def _binding_payload(binding):
    return (binding.family, binding.widget, binding.operation_number,
            binding.source_sha256, binding.operation_sha256, binding.names_sha256,
            binding.project_sha256, binding.provider_sha256,
            binding.external_used_indices, binding._names, binding._initial_state,
            None if binding._initial_state is None else _state_payload(binding._initial_state))


def _state_payload(state):
    return (tuple((target, control.text, control.pending, control.suppress_next_selection)
                  for target, control in state.controls), state.closed_targets)


def issue_mra_control_binding(*, owner, operation, values, family, widget,
        retained_names, external_used_indices, operation_number=1,
        project_sha256=None, provider_sha256=None, initial_state=None):
    """Trusted owner issuance; no serialized receipt or raw state authority."""
    if (owner is None or type(family) is not str or family not in FAMILY_TYPES or type(widget) is not int
            or not 1 <= widget <= 21 or type(operation_number) is not int or operation_number < 1
            or not isinstance(operation, Mapping) or operation.get('op') != family):
        raise EdltError('Invalid MRA control owner/record/operation identity')
    normalize_mra_controls(operation.get('mra_controls'), family=family)
    snapshot = _snapshot(values)
    _record(snapshot, widget, family)
    names = checked_names(retained_names)
    _json(names)
    # All static PP rows are required even where a retained long Name differs.
    if any(type(snapshot.get(f'StaticTextString{i}')) is not tuple
           or len(snapshot[f'StaticTextString{i}']) != 64
           or any(value > 255 for value in snapshot[f'StaticTextString{i}']) for i in range(64)):
        raise EdltError('MRA binding requires all 64 complete static PP rows')
    if (type(external_used_indices) is not tuple
            or any(type(index) is not int or not 0 <= index <= 255 for index in external_used_indices)
            or external_used_indices != tuple(sorted(set(external_used_indices)))):
        raise EdltError('MRA binding requires the exact sorted external source-reference roster')
    project_sha256, provider_sha256 = _pin(project_sha256, 'project'), _pin(provider_sha256, 'provider')
    if initial_state is not None:
        original = _STATES.get(initial_state) if type(initial_state) is MRAControlState else None
        if (original is None or initial_state._issuer is not _ISSUER
                or original[0] is not owner or original[1] != _state_payload(initial_state)
                or original[2:7] != (family, widget, _digest(snapshot), _digest(names),
                                      (project_sha256, provider_sha256))
                or operation_number <= original[7]):
            raise EdltError('MRA continuation requires the exact issued state and current record/Names')
    binding = MRAControlBinding(family, widget, operation_number, _digest(snapshot),
        _digest(operation), _digest(names), project_sha256, provider_sha256,
        external_used_indices, names, initial_state, owner, _ISSUER)
    _BINDINGS[binding] = (owner, _binding_payload(binding))
    return binding


@dataclass(frozen=True, eq=False)
class MRAControlResult:
    record: bytes
    restore_level: int
    retained_names: tuple[str, ...]
    changes: tuple[tuple[str, tuple[int, ...]], ...]
    state: MRAControlState
    _receipt_json: str = field(repr=False)
    _owner: object = field(repr=False)
    _issuer: object = field(repr=False)

    @property
    def pending(self):
        return self.state.pending

    def as_dict(self):
        return json.loads(self._receipt_json)


def _result_payload(result):
    return (result.record, result.restore_level, result.retained_names,
            result.changes, result.state, _state_payload(result.state), result._receipt_json)


def prepare_mra_projection(result, *, owner):
    """Parent admission before Names adoption, PP writes or save composition."""
    original = _RESULTS.get(result) if type(result) is MRAControlResult else None
    if (owner is None or original is None or result._issuer is not _ISSUER
            or original[0] is not owner or original[1] != _result_payload(result)):
        raise EdltError('MRA projection requires its exact unchanged owner-issued result')
    if result.pending:
        raise EdltError('MRA controls have pending text; parent save requires explicit commit/read')
    return result.record, dict(result.changes), result.as_dict()


def project_mra_controls(binding, *, owner, operation, values, retained_names):
    original = _BINDINGS.get(binding) if type(binding) is MRAControlBinding else None
    if (owner is None or original is None or binding._issuer is not _ISSUER
            or binding._owner is not owner or original[0] is not owner
            or original[1] != _binding_payload(binding)):
        raise EdltError('MRA projection requires its exact unchanged owner-issued binding')
    snapshot = _snapshot(values)
    names = list(checked_names(retained_names))
    if (binding.source_sha256 != _digest(snapshot) or binding.operation_sha256 != _digest(operation)
            or binding.names_sha256 != _digest(names)):
        raise EdltError('MRA binding source, operation or full retained Names are stale')
    events = normalize_mra_controls(operation.get('mra_controls'), family=binding.family)
    state = _record(snapshot, binding.widget, binding.family)
    projected = dict(snapshot)
    controls = dict(binding._initial_state.controls) if binding._initial_state is not None else {}
    closed_targets = set(binding._initial_state.closed_targets) if binding._initial_state is not None else set()
    suggestions = [*names, *FIXED_SUGGESTION_NAMES]
    journal, allocations = [], []

    def install(outcome):
        nonlocal state
        state = outcome.state
        _install(projected, binding.widget, state)

    def set_text(target, text):
        assignment = assign_name(tuple(names), state.index(target), text, values=projected,
            used_indices=lambda: tuple(sorted(set(binding.external_used_indices) | set(state.used_static_text()))))
        # Keep old references during allocation, then assign the resulting index.
        names[:] = assignment.names
        suggestions[:] = [*names, *FIXED_SUGGESTION_NAMES]
        projected.update(assignment.changes)
        if not assignment.ignored_null:
            install(write_mra_property(state, 'LabelValueIndex' if target == 'label' else 'StatusValueIndex', assignment.index))
        receipt = assignment.as_dict()
        receipt['allocation_policy'] = 'MRA Text property; old raw reference retained until assignment'
        allocations.append(receipt)
        return receipt

    for ordinal, event in enumerate(events, 1):
        kind = event['event']
        before = state.record
        assignments, notes, observed, callback = (), (), None, None
        if kind == 'binding-write':
            outcome = write_mra_property(state, _TARGET_PROPERTIES[event['target']], event['value'])
            install(outcome)
            assignments, notes = outcome.writes, outcome.notifications
        elif kind in _TEXT_EVENTS:
            target = event['target']
            if target in closed_targets:
                raise EdltError('MRA callbacks cannot follow that control\'s explicit close')
            # Source handlers observe retained display state. No visibility or
            # PropertyChanged dispatch is synthesized after other property writes.
            callback = run_scene_name_control(
                [{key: value for key, value in event.items() if key != 'target'}],
                get_name=lambda: read_mra_property(state,
                    'LabelValueText' if target == 'label' else 'StatusValueText', names=tuple(names)).value,
                set_name=lambda text: set_text(target, text), known_names=suggestions,
                initial_state=controls.get(target))
            controls[target] = callback.state
            if kind == 'close':
                closed_targets.add(target)
            # Ordered setter intents can be equal-value assignments. Capture
            # the target assignment once for every actual WriteValue callback.
            writes = [row for row in callback.as_dict()['binding_callbacks'] if row['action'] == 'WriteValue']
            if writes:
                assignments = ((OFFSETS[binding.family][target], state.index(target)),)
        elif kind == 'get-zone-macro':
            outcome = read_mra_property(state, 'DualButtonMacrofunction', names=tuple(names))
            install(outcome)
            assignments, notes, observed = outcome.writes, outcome.notifications, outcome.value
        elif kind == 'get-view':
            observed = mra_readonly_view(state, names=tuple(names))
        elif kind == 'get-used-static-text':
            observed = list(state.used_static_text())
        elif kind == 'get-property':
            observed = read_mra_property(state, event['property'], names=tuple(names)).value
        else:
            observed = {prop: read_mra_property(state, prop, names=tuple(names)).value
                        for prop in event['properties']}
        journal.append({'event_index': ordinal, 'event': event,
            'record_before_hex': before.hex(), 'record_after_hex': state.record.hex(),
            'assignment_intents': [{'offset': i, 'value': value} for i, value in assignments],
            'notification_intents': list(notes), 'observed': observed,
            'control': None if callback is None else callback.as_dict()})
    static_changes, setters = save_names(projected, tuple(names))
    projected.update(static_changes)
    changes = tuple(sorted((key, raw) for key, raw in projected.items() if raw != snapshot[key]))
    control_state = MRAControlState(tuple(sorted(controls.items())), tuple(sorted(closed_targets)), _ISSUER)
    _STATES[control_state] = (owner, _state_payload(control_state), binding.family, binding.widget,
        _digest(projected), _digest(names), (binding.project_sha256, binding.provider_sha256),
        binding.operation_number)
    receipt = {'format': 'cbus-edlt-mra-controls-v1', 'binding': binding.as_dict(),
        'record_hex': state.record.hex(), 'restore_level': state.restore_level,
        'state': control_state.as_dict(), 'journal': journal, 'allocations': allocations,
        'retained_names_sha256': _digest(names), 'static_setter_indices': list(setters),
        'used_static_text': list(state.used_static_text()), 'pending': control_state.pending,
        'automatic_framework_dispatch_inferred': False, 'original_host_executed': False,
        'physical_device_verified': False, 'receipt_can_resume': False}
    result = MRAControlResult(state.record, state.restore_level, tuple(names), changes,
        control_state, _json(receipt).decode('utf8'), owner, _ISSUER)
    _RESULTS[result] = (owner, _result_payload(result))
    return result
