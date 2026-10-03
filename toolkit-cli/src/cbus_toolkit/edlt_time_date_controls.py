"""Owner-issued Time/Date property and explicitly requested binding callbacks.

No host CurrencyManager scheduling, parsing, painting or PP notification delivery
is inferred. A source setup ReadValue and an empty selected-index handler are
explicit events. Detached JSON receipts cannot issue or resume a capability.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import re
from weakref import WeakKeyDictionary
from .edlt import EdltError, _field
from .edlt_time_date_control_properties import (
    PROPERTIES, GLOBAL_PROPERTIES, TimeDatePropertyState, integer,
    read_time_date_property, write_time_date_property, time_date_readonly_view,
)

_ISSUER = object()
_BINDINGS, _STATES, _RESULTS = WeakKeyDictionary(), WeakKeyDictionary(), WeakKeyDictionary()
_HEX = re.compile('[0-9a-f]{64}\\Z')
_TARGETS = {'display': 'DisplayType', 'widget-type': 'WidgetType', 'date-format': 'DateFormat',
            'time-format': 'TimeFormat', 'leading-zero': 'TimeDateLeadingZero'}
_DISPLAY = ((1, 'Date'), (0, 'Time'), (2, 'Time & Date'))
_DATE = tuple(enumerate(('dddd dd Mmm (eg Tuesday 29 May)', 'ddd dd Mmm (eg Tue 29 May)',
    'ddd dd/mm (eg Tue 29/5)', 'ddd mm/dd (eg Tue 5/29)', 'dd/mm (eg 29/5)',
    'mm/dd (eg 5/29)', 'dd Mmm (eg 29 May)', 'Mmm dd (eg May 29)')))
_TIME = ((3, '12 hour'), (1, '24 hour'), (0, '12 hour (am/pm)'), (2, '12 hour (AM/PM)'))
_STANDBY = ((0, 'Blank'), (13, 'HVAC Temperature Display'), (12, 'Measurement'),
            (10, 'Time & Date'), (11, 'Time & Date (2 Slice)'))
_FUNCTION = ((0, 'Blank'), (14, 'Enable'), (4, 'Fan Control'), (13, 'HVAC Temperature Display'),
    (2, 'Lighting'), (12, 'Measurement'), (7, 'MRA Zone Control'), (8, 'MRA Source Select'),
    (9, 'MRA Source Control'), (16, 'Multi-Level'), (6, 'Scene'), (3, 'Shutter Relay'),
    (5, 'Timer'), (10, 'Time & Date'), (15, 'Room Courtesy Panel'))


def _json(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                         allow_nan=False).encode('utf8')
    except (ValueError, TypeError, UnicodeError) as error:
        raise EdltError('Time/Date controls require bounded valid Unicode JSON') from error
    if len(raw) > 4 * 1024 * 1024:
        raise EdltError('Time/Date fact document exceeds its bounded profile')
    return raw


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _pin(value):
    if value is not None and (type(value) is not str or _HEX.fullmatch(value) is None):
        raise EdltError('Time/Date source pin must be an exact lowercase SHA256 or absent')
    return value


def _snapshot(values):
    if not isinstance(values, Mapping) or len(values) > 4096:
        raise EdltError('Time/Date binding requires a complete causal PP mapping')
    result = {}
    for name, raw in values.items():
        if type(name) is not str:
            raise EdltError('Time/Date PP field names must be exact strings')
        if type(raw) is str:
            result[name] = raw
        elif (isinstance(raw, (list, tuple)) and len(raw) <= 4096
              and all(type(v) is int and 0 <= v <= 65535 for v in raw)):
            result[name] = tuple(raw)
        else:
            raise EdltError('Time/Date causal PP requires normalized strings or 16-bit numeric arrays')
    _json(result)
    return result


def _byte(values, name, *, optional=False):
    if optional and name not in values:
        return None
    row = values.get(name)
    if type(row) is not tuple or len(row) != 1 or type(row[0]) is not int or not 0 <= row[0] <= 255:
        raise EdltError('Time/Date requires its complete exact byte field: ' + name)
    return row[0]


def _record(values, widget):
    return bytes(_byte(values, _field(widget, i)) for i in range(32))


def _restore(values, widget):
    name = f'Widget{widget}RestoreLevel'
    if widget < 6:
        if name in values:
            raise EdltError('KEYGL5 standby records have no persistent RestoreLevel field')
        return None
    return _byte(values, name)


def _model(values, widget):
    return TimeDatePropertyState(widget, _record(values, widget),
        _record(values, widget + 1) if widget < 21 else None,
        _restore(values, widget),
        _restore(values, widget + 1) if widget < 21 else None,
        *(_byte(values, name) for name in GLOBAL_PROPERTIES))


def choice_identity(target, value):
    if target not in ('display', 'widget-type', 'date-format', 'time-format') or type(value) is not int:
        raise EdltError('This Time/Date binding has no offered list identity')
    return f'time-date-{target}:{value}'


def time_date_choices(widget):
    if type(widget) is not int or not 1 <= widget <= 21:
        raise EdltError('Time/Date choices require an actual widget position')
    pairs = {'display': _DISPLAY, 'date-format': _DATE, 'time-format': _TIME,
             'widget-type': _STANDBY[:-1] if widget == 5 else _STANDBY if widget < 6 else _FUNCTION}
    return {target: [{'identity': choice_identity(target, value), 'value': value,
        'name': name, 'formatted_display': name} for value, name in rows] for target, rows in pairs.items()}


def normalize_time_date_controls(events):
    if not isinstance(events, (list, tuple)) or not 1 <= len(events) <= 512:
        raise EdltError('time_date_controls require 1..512 explicit callbacks')
    result = []
    for row in events:
        if not isinstance(row, Mapping) or type(row.get('event')) is not str:
            raise EdltError('Time/Date callback requires an explicit event record')
        kind = row['event']
        if kind in ('get-view', 'setup-widget-selection', 'widget-type-selected-index-changed'):
            if set(row) != {'event'}:
                raise EdltError('Time/Date event contains unsupported state or fields')
        elif kind == 'get-property':
            if set(row) != {'event', 'property'} or type(row['property']) is not str or row['property'] not in PROPERTIES:
                raise EdltError('Unknown Time/Date source property')
        elif kind == 'read-properties':
            props = row.get('properties')
            if (set(row) != {'event', 'properties'} or not isinstance(props, (list, tuple))
                    or not 1 <= len(props) <= 5 or any(type(p) is not str or p not in PROPERTIES for p in props)
                    or len(set(props)) != len(props)):
                raise EdltError('Time/Date reads require exact distinct source properties')
        elif kind == 'binding-read':
            if set(row) != {'event', 'target'} or type(row['target']) is not str or row['target'] not in _TARGETS:
                raise EdltError('Unknown Time/Date declared binding')
        elif kind == 'binding-write':
            target = row.get('target')
            if type(target) is not str or target not in _TARGETS:
                raise EdltError('Unknown Time/Date declared binding')
            value = integer(row.get('value'))
            if target == 'leading-zero':
                if set(row) != {'event', 'target', 'value'} or value not in (0, 1):
                    raise EdltError('Leading-zero Checked binding requires an explicit numeric0/1 profile')
            else:
                if (set(row) != {'event', 'target', 'value', 'choice_index', 'identity'}
                        or type(row['choice_index']) is not int or row['identity'] != choice_identity(target, value)):
                    raise EdltError('Time/Date binding requires exact ordinal, identity and value')
                candidates = (_DISPLAY if target == 'display' else _DATE if target == 'date-format'
                              else _TIME if target == 'time-format' else _STANDBY if value == 11 else _FUNCTION)
                if target == 'widget-type':
                    valid = value in (10, 11) and row['choice_index'] in ((3, 13) if value == 10 else (4,))
                else:
                    valid = 0 <= row['choice_index'] < len(candidates) and candidates[row['choice_index']][0] == value
                if not valid:
                    raise EdltError('Time/Date binding must match an actual offered ordinal and value')
        else:
            raise EdltError('Unsupported Time/Date callback; no inferred GUI scheduling or parsing')
        result.append(dict(row))
    _json(result)
    return tuple(result)


def _placement(snapshot, operation, widget):
    page, position = operation.get('page'), operation.get('position')
    nav = _byte(snapshot, 'NavWidgetType')
    requested_mode = operation.get('page_mode')
    mode = ('multiple' if nav == 1 else 'single') if requested_mode is None else requested_mode
    if (nav not in (0, 1, 255) or mode not in ('single', 'multiple') or type(page) is not int
            or type(position) is not int or not 0 <= page <= (4 if mode == 'multiple' else 1)
            or not 1 <= position <= (5 if page == 0 or mode == 'single' else 4)):
        raise EdltError('Time/Date callback position is outside the source UI profile')
    actual = position if page == 0 else 6 + (page - 1) * 4 + position - 1
    if actual != widget:
        raise EdltError('Time/Date operation is not associated with the issued widget')
    if page == 0 and position > 1 and _byte(snapshot, _field(widget - 1)) == 11:
        raise EdltError('This standby slot is covered by the previous two-slice widget; shrink it first')
    if _byte(snapshot, _field(widget)) == 11 and widget > 4:
        raise EdltError('Retained two-slice Time/Date is outside the source UI placements')
    return mode


@dataclass(frozen=True, eq=False)
class TimeDateControlState:
    model: TimeDatePropertyState
    binding_values: tuple[tuple[str, int], ...]
    _issuer: object = field(repr=False)

    @property
    def pending(self):
        return False

    def as_dict(self):
        return {'binding_values': dict(self.binding_values), 'pending': False, 'receipt_can_resume': False}


def _state_payload(state):
    if (type(state) is not TimeDateControlState or type(state.model) is not TimeDatePropertyState
            or type(state.binding_values) is not tuple
            or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or row[0] not in _TARGETS
                   or type(row[1]) is not int or not 0 <= row[1] <= 255 for row in state.binding_values)):
        raise EdltError('Time/Date control state has unsupported typed contents')
    model = state.model
    model.__post_init__()
    return (model.widget, model.record, model.adjacent_record, model.restore_level,
        model.adjacent_restore_level, model.date_format, model.time_format,
        model.leading_zero, state.binding_values)


@dataclass(frozen=True, eq=False)
class TimeDateControlBinding:
    widget: int
    operation_number: int
    source_sha256: str
    operation_sha256: str
    project_sha256: str | None
    provider_sha256: str | None
    _initial_state: TimeDateControlState | None = field(repr=False)
    _owner: object = field(repr=False)
    _issuer: object = field(repr=False)

    def as_dict(self):
        return {'format': 'cbus-edlt-time-date-control-binding-v1', 'widget': self.widget,
            'operation': self.operation_number, 'source_sha256': self.source_sha256,
            'operation_sha256': self.operation_sha256, 'project_sha256': self.project_sha256,
            'provider_sha256': self.provider_sha256, 'snapshot_owned': True, 'receipt_can_resume': False}


def _binding_payload(binding):
    return (binding.widget, binding.operation_number, binding.source_sha256, binding.operation_sha256,
        binding.project_sha256, binding.provider_sha256, binding._initial_state,
        None if binding._initial_state is None else _state_payload(binding._initial_state))


def issue_time_date_control_binding(*, owner, operation, values, widget, operation_number=1,
        project_sha256=None, provider_sha256=None, initial_state=None):
    if (owner is None or type(widget) is not int or not 1 <= widget <= 21
            or type(operation_number) is not int or operation_number < 1
            or not isinstance(operation, Mapping) or operation.get('op') != 'time-date'):
        raise EdltError('Invalid Time/Date owner/record/operation association')
    normalize_time_date_controls(operation.get('time_date_controls'))
    snapshot = _snapshot(values)
    model = _model(snapshot, widget)
    _placement(snapshot, operation, widget)
    project_sha256, provider_sha256 = _pin(project_sha256), _pin(provider_sha256)
    if initial_state is not None:
        prior = _STATES.get(initial_state) if type(initial_state) is TimeDateControlState else None
        if (prior is None or initial_state._issuer is not _ISSUER or prior[0] is not owner
                or prior[1] != _state_payload(initial_state) or initial_state.model != model
                or prior[2:5] != (_digest(snapshot), widget, (project_sha256, provider_sha256))
                or operation_number <= prior[5]):
            raise EdltError('Time/Date continuation requires its exact state and current causal PP')
    binding = TimeDateControlBinding(widget, operation_number, _digest(snapshot), _digest(operation),
        project_sha256, provider_sha256, initial_state, owner, _ISSUER)
    _BINDINGS[binding] = (owner, _binding_payload(binding))
    return binding


@dataclass(frozen=True, eq=False)
class TimeDateControlResult:
    record: bytes
    restore_level: int | None
    adjacent_widget: int | None
    adjacent_before: bytes | None
    adjacent_after: bytes | None
    adjacent_restore_level: int | None
    restore_reset_widgets: tuple[int, ...]
    changes: tuple[tuple[str, object], ...]
    state: TimeDateControlState
    _receipt_json: str = field(repr=False)
    _owner: object = field(repr=False)
    _issuer: object = field(repr=False)

    @property
    def pending(self):
        return False

    def as_dict(self):
        return json.loads(self._receipt_json)


def _result_payload(result):
    return (result.record, result.restore_level, result.adjacent_widget, result.adjacent_before,
        result.adjacent_after, result.adjacent_restore_level, result.restore_reset_widgets, result.changes,
        result.state, _state_payload(result.state), result._receipt_json)


def prepare_time_date_projection(result, *, owner):
    original = _RESULTS.get(result) if type(result) is TimeDateControlResult else None
    if (owner is None or original is None or original[0] is not owner or result._owner is not owner
            or result._issuer is not _ISSUER or original[1] != _result_payload(result)):
        raise EdltError('Time/Date projection requires the exact unchanged owner-issued result')
    return result.record, dict(result.changes), result.as_dict()


def project_time_date_controls(binding, *, owner, operation, values):
    original = _BINDINGS.get(binding) if type(binding) is TimeDateControlBinding else None
    if (owner is None or original is None or original[0] is not owner or binding._owner is not owner
            or binding._issuer is not _ISSUER or original[1] != _binding_payload(binding)):
        raise EdltError('Time/Date projection requires its exact unchanged owner-issued binding')
    snapshot = _snapshot(values)
    if binding.source_sha256 != _digest(snapshot) or binding.operation_sha256 != _digest(operation):
        raise EdltError('Time/Date binding source or operation is stale')
    _placement(snapshot, operation, binding.widget)
    events, model = normalize_time_date_controls(operation['time_date_controls']), _model(snapshot, binding.widget)
    observed_bindings = dict(binding._initial_state.binding_values) if binding._initial_state is not None else {}
    journal, adjacent_owned, resets = [], False, set()
    choices = time_date_choices(binding.widget)
    for ordinal, event in enumerate(events, 1):
        before = model
        callbacks, observed, outcome = [], None, None
        kind = event['event']
        if kind == 'get-view':
            observed = {**time_date_readonly_view(model), 'choices': choices,
                        'binding_values': dict(observed_bindings)}
        elif kind == 'get-property':
            outcome = read_time_date_property(model, event['property'])
            observed = outcome.value
        elif kind == 'read-properties':
            observed = {p: read_time_date_property(model, p).value for p in event['properties']}
        elif kind == 'binding-read' or kind == 'setup-widget-selection':
            target = event['target'] if kind == 'binding-read' else 'widget-type'
            observed = read_time_date_property(model, _TARGETS[target]).value
            observed_bindings[target] = observed
            if kind == 'setup-widget-selection':
                callbacks.extend({'action': action} for action in ('DataBindings.SaveFirst', 'DataBindings.Clear',
                    'WidgetType.DataSource.Assign', 'DataBindings.AddSameBinding'))
            callbacks.append({'action': 'Binding.ReadValue', 'target': target, 'value': observed,
                              'host_selected_ordinal_inferred': False})
        elif kind == 'widget-type-selected-index-changed':
            callbacks.append({'action': 'WidgetType.SelectedIndexChanged.EmptyHandler'})
        else:
            target, value = event['target'], event['value']
            if target != 'leading-zero':
                rows, index = choices[target], event['choice_index']
                if (not 0 <= index < len(rows) or rows[index]['identity'] != event['identity']
                        or rows[index]['value'] != value or (target == 'widget-type' and value not in (10, 11))):
                    raise EdltError('Time/Date choice must match the current source ordinal, identity and value')
            if target == 'widget-type' and value == 11 and binding.widget > 4:
                raise EdltError('Two-slice Time/Date is available only at standby positions1..4')
            callbacks.append({'action': 'Binding.WriteValue', 'target': target, 'value': value})
            outcome = write_time_date_property(model, _TARGETS[target], value)
            observed_bindings[target] = value
        if outcome is not None:
            model = outcome.state
            adjacent_owned |= outcome.owns_adjacent
            resets.update(outcome.restore_reset_widgets)
        journal.append({'event_index': ordinal, 'event': event,
            'record_before_hex': before.record.hex(), 'record_after_hex': model.record.hex(),
            'adjacent_before_hex': None if before.adjacent_record is None else before.adjacent_record.hex(),
            'adjacent_after_hex': None if model.adjacent_record is None else model.adjacent_record.hex(),
            'assignment_intents': [] if outcome is None else [{'field': p, 'value': v} for p, v in outcome.writes],
            'source_calls': [] if outcome is None else list(outcome.source_calls),
            'notification_intents': [] if outcome is None else list(outcome.notification_intents),
            'pp_notification_delivery_established': False, 'binding_callbacks': callbacks, 'observed': observed})
    projected = dict(snapshot)
    projected.update({_field(binding.widget, i): (v,) for i, v in enumerate(model.record)})
    if model.restore_level is not None:
        projected[f'Widget{binding.widget}RestoreLevel'] = (model.restore_level,)
    if adjacent_owned:
        projected.update({_field(binding.widget + 1, i): (v,) for i, v in enumerate(model.adjacent_record)})
        if model.adjacent_restore_level is not None:
            projected[f'Widget{binding.widget + 1}RestoreLevel'] = (model.adjacent_restore_level,)
    projected.update({name: (value,) for name, value in zip(GLOBAL_PROPERTIES,
        (model.date_format, model.time_format, model.leading_zero))})
    changes = tuple((name, value) for name, value in projected.items() if value != snapshot[name])
    state = TimeDateControlState(model, tuple(sorted(observed_bindings.items())), _ISSUER)
    _STATES[state] = (owner, _state_payload(state), _digest(projected), binding.widget,
                      (binding.project_sha256, binding.provider_sha256), binding.operation_number)
    adjacent_before = _record(snapshot, binding.widget + 1) if adjacent_owned else None
    receipt = {'format': 'cbus-edlt-time-date-control-result-v1', 'binding': binding.as_dict(),
        'record_before_hex': _record(snapshot, binding.widget).hex(), 'record_hex': model.record.hex(),
        'adjacent_widget': binding.widget + 1 if adjacent_owned else None,
        'adjacent_before_hex': None if adjacent_before is None else adjacent_before.hex(),
        'adjacent_after_hex': None if not adjacent_owned else model.adjacent_record.hex(),
        'restore_reset_widgets': sorted(resets), 'global_format_changes': {
            n: list(v) for n, v in changes if n in GLOBAL_PROPERTIES},
        'state': state.as_dict(), 'journal': journal, 'pending': False,
        'global_formats_apply_to_whole_unit': True, 'implicit_framework_dispatch': False,
        'pp_notification_delivery_established': False, 'saved': False,
        'physical_device_verified': False, 'clock_set': False}
    result = TimeDateControlResult(model.record, model.restore_level,
        binding.widget + 1 if adjacent_owned else None, adjacent_before,
        model.adjacent_record if adjacent_owned else None, model.adjacent_restore_level if adjacent_owned else None,
        tuple(sorted(resets)), changes, state, _json(receipt).decode('utf8'), owner, _ISSUER)
    _RESULTS[result] = (owner, _result_payload(result))
    return result
