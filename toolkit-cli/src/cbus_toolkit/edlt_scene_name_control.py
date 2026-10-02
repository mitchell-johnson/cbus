"""Explicit ComboBoxStaticText callbacks, without a WinForms host.

The owning SceneManager supplies the SceneName property callbacks. This module
does not allocate labels, interpret whitespace, sort suggestions or save PP.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json

from .edlt import EdltError


_ARROWS = ('left', 'right', 'up', 'down')
_LIST_CHANGES = (
    'reset', 'item-added', 'item-deleted', 'item-moved', 'item-changed',
    'property-descriptor-added', 'property-descriptor-deleted',
    'property-descriptor-changed',
)


def _text(value, *, input_text=False, selected_text=False):
    if type(value) is not str:
        raise EdltError('SceneName control text must be a string')
    try:
        units = len(value.encode('utf-16-le')) // 2
    except UnicodeEncodeError as error:
        raise EdltError('SceneName control text cannot contain an unpaired surrogate') from error
    if (input_text or selected_text) and '\0' in value:
        raise EdltError('Embedded NUL input/selection is outside the qualified SceneName host-text profile')
    if input_text and units > 64:
        raise EdltError('SceneName input permits at most 64 UTF-16 units')
    return value


def _flag(row, name, default):
    value = row.get(name, default)
    if type(value) is not bool:
        raise EdltError(f'SceneName {name} must be an explicit boolean')
    return value


def _index(value):
    if type(value) is not int or not -1 <= value <= 2**31 - 1:
        raise EdltError('SceneName callback indices must be -1 or a nonnegative signed integer')
    return value


def normalize_events(events):
    """Validate callback facts without reading a model or accepting cache state."""
    if not isinstance(events, (list, tuple)) or len(events) > 512:
        raise EdltError('SceneName events require an ordered array of at most 512 callbacks')
    result = []
    for row in events:
        if not isinstance(row, Mapping):
            raise EdltError('SceneName events require explicit records')
        kind = row.get('event')
        if kind == 'input' and set(row) == {'event', 'text'}:
            item = {'event': kind, 'text': _text(row['text'], input_text=True)}
        elif kind in ('enter', 'leave') and set(row) <= {'event', 'binding_present'}:
            item = {'event': kind, 'binding_present': _flag(row, 'binding_present', True)}
        elif kind == 'arrow-preview' and set(row) == {'event', 'key'} and row['key'] in _ARROWS:
            item = dict(row)
        elif kind == 'selected-name' and set(row) <= {
                'event', 'name', 'selected_index', 'data_source_present',
                'data_manager_present', 'binding_present'} and 'selected_index' in row:
            index = _index(row['selected_index'])
            source = _flag(row, 'data_source_present', True)
            if source and index >= 0 and 'name' not in row:
                raise EdltError('A selected SceneName requires an explicit known name')
            item = {'event': kind, 'selected_index': index,
                    'data_source_present': source,
                    'data_manager_present': _flag(row, 'data_manager_present', True),
                    'binding_present': _flag(row, 'binding_present', True)}
            if 'name' in row:
                item['name'] = _text(row['name'], selected_text=True)
        elif kind == 'list-refresh' and set(row) <= {
                'event', 'change_type', 'new_index', 'old_index', 'selected_index',
                'visible', 'list_updates_disabled', 'invoke_required', 'binding_present'} and {
                'change_type', 'new_index', 'old_index', 'selected_index'} <= set(row):
            if row['change_type'] not in _LIST_CHANGES:
                raise EdltError('Unknown SceneName list change type')
            item = {'event': kind, 'change_type': row['change_type'],
                    **{name: _index(row[name]) for name in ('new_index', 'old_index', 'selected_index')},
                    'visible': _flag(row, 'visible', True),
                    'list_updates_disabled': _flag(row, 'list_updates_disabled', False),
                    'invoke_required': _flag(row, 'invoke_required', False),
                    'binding_present': _flag(row, 'binding_present', True)}
        elif kind == 'close' and set(row) == {'event'}:
            item = {'event': kind}
        else:
            raise EdltError('Unsupported SceneName control event')
        result.append(item)
    return result


def normalize_operation(operation):
    if (not isinstance(operation, Mapping)
            or set(operation) != {'op', 'scene', 'events'}
            or operation.get('op') != 'scene-name-control'):
        raise EdltError('Invalid scene-name-control operation')
    scene = operation['scene']
    if type(scene) is not int or not 1 <= scene <= 8:
        raise EdltError('SceneName control requires scene 1..8')
    return {'op': 'scene-name-control', 'scene': scene,
            'events': normalize_events(operation['events'])}


@dataclass(frozen=True)
class SceneNameControlState:
    """Internal model-owned continuation; operations JSON cannot resume it."""

    text: str
    pending: bool = False
    suppress_next_selection: bool = False

    def as_dict(self):
        return {'text': self.text, 'pending': self.pending,
                'suppress_next_selection': self.suppress_next_selection}


@dataclass(frozen=True)
class SceneNameControlResult:
    state: SceneNameControlState
    _receipt_json: str

    def as_dict(self):
        """Return a detached review receipt, never an accepted resume input."""
        return json.loads(self._receipt_json)


def run_scene_name_control(
        events, *, get_name: Callable[[], str], set_name: Callable[[str], object],
        known_names: Sequence[str], initial_text: str | None = None,
        initial_state: SceneNameControlState | None = None):
    """Project explicit synchronous callbacks against an owning SceneName model.

    End of the event array does not imply close. A pending result can only be
    continued through its typed internal state; the save owner must reject it.
    List indices are supplied callback facts, not inferred culture sort order.
    """
    rows = normalize_events(events)
    if not callable(get_name) or not callable(set_name):
        raise EdltError('SceneName requires callable property bindings')
    if (not isinstance(known_names, Sequence) or isinstance(known_names, (str, bytes))
            or len(known_names) > 4096):
        raise EdltError('SceneName requires a bounded known-name collection')
    def current_names():
        # The property setter can update the owning loaded model's name list.
        # Re-read that list at selection time without deriving its culture order.
        if len(known_names) > 4096:
            raise EdltError('SceneName requires a bounded known-name collection')
        return tuple(_text(name) for name in known_names)

    current_names()
    if initial_state is not None:
        if type(initial_state) is not SceneNameControlState or initial_text is not None:
            raise EdltError('SceneName continuation requires its internal typed state only')
        _text(initial_state.text)
        if type(initial_state.pending) is not bool or type(initial_state.suppress_next_selection) is not bool:
            raise EdltError('Invalid internal SceneName control state')
    if initial_text is not None:
        _text(initial_text)

    bound = _text(get_name())
    if initial_text is not None and initial_text != bound:
        raise EdltError('Initial SceneName text must match the binding; pending text requires typed continuation')
    state = initial_state or SceneNameControlState(bound if initial_text is None else initial_text)
    text, pending, suppressed = state.text, state.pending, state.suppress_next_selection
    initial = state.as_dict()
    journal, projected = [], []
    closed = False

    def read(index, cause):
        nonlocal text, bound, pending
        bound = _text(get_name())
        text, pending = bound, False
        journal.append({'event_index': index, 'event': cause,
                        'action': 'ReadValue', 'text': bound})

    def write_read(index, cause):
        # No retry or following read is attempted if the setter fails.
        allocation = set_name(text)
        try:
            detached = json.loads(json.dumps(allocation, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise EdltError('SceneName setter must return a JSON-compatible receipt') from error
        journal.append({'event_index': index, 'event': cause,
                        'action': 'WriteValue', 'text': text, 'result': detached})
        read(index, cause)

    for index, row in enumerate(rows):
        if closed:
            raise EdltError('SceneName events cannot follow an explicit close')
        kind = row['event']
        actions_start = len(journal)
        info = {}
        if kind == 'input':
            text, pending = row['text'], True
        elif kind in ('enter', 'leave'):
            if row['binding_present']:
                write_read(index, kind)
        elif kind == 'arrow-preview':
            suppressed = True
        elif kind == 'selected-name':
            if 'name' in row:
                if row['name'] not in current_names():
                    raise EdltError('Selected SceneName is not an ordinal member of the known names')
                text, pending = row['name'], True
            info['list_change_handler_rebound'] = row['data_manager_present']
            if suppressed:
                suppressed = False
                info['selection_write_suppressed'] = True
            elif row['data_source_present'] and row['selected_index'] >= 0 and row['binding_present']:
                write_read(index, kind)
        elif kind == 'list-refresh':
            if not row['list_updates_disabled']:
                if row['invoke_required']:
                    raise EdltError('Asynchronous SceneName list dispatch is not source-qualified in this callback profile')
                earlier = (row['new_index'] < row['selected_index']
                           or (row['old_index'] < row['selected_index'] and row['old_index'] != -1))
                if (row['visible'] and row['change_type'] in ('item-added', 'item-changed', 'reset')
                        and earlier and row['binding_present']):
                    read(index, kind)
        elif kind == 'close':
            if pending:
                raise EdltError('Pending SceneName close ordering is not source-established; commit or read the binding first')
            closed = True
        projected.append({**row, **info, 'text': text, 'bound_name': bound,
                          'pending': pending, 'suppress_next_selection': suppressed,
                          'binding_actions': [entry['action'] for entry in journal[actions_start:]]})

    final = SceneNameControlState(text, pending, suppressed)
    receipt = {'format': 'cbus-edlt-scene-name-control-v1',
               'initial_state': initial, 'state': final.as_dict(),
               'bound_name': bound, 'events': projected, 'binding_callbacks': journal,
               'closed': closed, 'pending': pending,
               'input_limit_utf16_units': 64, 'implicit_close_inferred': False,
               'selection_identity': 'explicit-ordinal-known-name',
               'suggestion_order_inferred': False, 'host_gui_executed': False,
               'framework_async_dispatch_verified': False}
    return SceneNameControlResult(final, json.dumps(receipt, ensure_ascii=False, allow_nan=False))
