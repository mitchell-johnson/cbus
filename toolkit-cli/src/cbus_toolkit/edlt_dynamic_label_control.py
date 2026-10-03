"""Explicit source-owned ComboImageTagDLT callbacks and binding modes.

An owner supplies actual property callbacks and ordered DataStore rows. No
CurrencyManager selection, rendering or asynchronous notification is inferred.
A detached review receipt cannot resume the control.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json

from .edlt import EdltError

_ISSUER = object()
_ARROWS = ('left', 'right', 'up', 'down')
_CHANGES = ('reset', 'item-added', 'item-deleted', 'item-moved', 'item-changed',
            'property-descriptor-added', 'property-descriptor-deleted', 'property-descriptor-changed')


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(',', ':')).encode('utf8')
    except (TypeError, ValueError, UnicodeError) as error:
        raise EdltError('Dynamic-label callbacks need Unicode JSON-compatible receipts') from error


def _text(value, *, input_text=False):
    if type(value) is not str:
        raise EdltError('Dynamic-label control text must be a string')
    try:
        units = len(value.encode('utf-16-le')) // 2
    except UnicodeError as error:
        raise EdltError('Dynamic-label text cannot contain an unpaired surrogate') from error
    if input_text and ('\0' in value or units > 64):
        raise EdltError('Dynamic-label input must be NUL-free and at most 64 UTF-16 units')
    return value


def _int(value, name='index'):
    if type(value) is not int or not -1 <= value <= 2**31 - 1:
        raise EdltError(f'Dynamic-label {name} must be -1 or a nonnegative signed integer')
    return value


def _flag(row, key, default):
    value = row.get(key, default)
    if type(value) is not bool:
        raise EdltError(f'Dynamic-label {key} must be boolean')
    return value


def normalize_events(events):
    """Normalize explicit callbacks; ``enter`` abbreviates Enter-key preview.

    It does not represent WinForms focus Enter/OnEnter, which is unestablished.
    """
    if not isinstance(events, (list, tuple)) or len(events) > 512:
        raise EdltError('Dynamic-label events require at most 512 ordered callbacks')
    result = []
    for row in events:
        if not isinstance(row, Mapping):
            raise EdltError('Dynamic-label events require records')
        kind = row.get('event')
        if kind == 'input' and set(row) == {'event', 'text'}:
            item = {'event': kind, 'text': _text(row['text'], input_text=True)}
        elif kind in ('enter', 'leave', 'close') and set(row) == {'event'}:
            item = {'event': kind}
        elif kind == 'key-preview' and set(row) == {'event', 'key'} and row['key'] in (*_ARROWS, 'enter', 'other'):
            item = dict(row)
        elif kind == 'selected-row' and set(row) <= {'event', 'index', 'identity', 'value', 'data_source_present', 'data_manager_present'} and 'index' in row:
            index = _int(row['index'])
            source = _flag(row, 'data_source_present', True)
            item = {'event': kind, 'index': index, 'data_source_present': source,
                    'data_manager_present': _flag(row, 'data_manager_present', True)}
            if source and index >= 0:
                if not {'identity', 'value'} <= set(row):
                    raise EdltError('Selected dynamic-label row needs exact ordinal, identity and value')
                item.update(identity=_text(row['identity']), value=_int(row['value'], 'choice value'))
            elif 'identity' in row or 'value' in row:
                raise EdltError('Unselected dynamic-label rows cannot supply an identity/value')
        elif kind == 'list-refresh' and set(row) <= {'event', 'change_type', 'new_index', 'old_index', 'selected_index', 'visible', 'list_updates_disabled', 'invoke_required'} and {'change_type', 'new_index', 'old_index', 'selected_index'} <= set(row):
            if row['change_type'] not in _CHANGES:
                raise EdltError('Unknown dynamic-label list change type')
            item = {'event': kind, 'change_type': row['change_type'],
                    **{key: _int(row[key], key) for key in ('new_index', 'old_index', 'selected_index')},
                    'visible': _flag(row, 'visible', True),
                    'list_updates_disabled': _flag(row, 'list_updates_disabled', False),
                    'invoke_required': _flag(row, 'invoke_required', False)}
        elif kind == 'set-editable' and set(row) == {'event', 'value'}:
            item = {'event': kind, 'value': _flag(row, 'value', False)}
        elif kind == 'binding-source-change' and set(row) == {'event', 'present', 'changed'}:
            item = {'event': kind, 'present': _flag(row, 'present', False), 'changed': _flag(row, 'changed', False)}
        elif kind == 'drop-down' and set(row) == {'event', 'open'}:
            item = {'event': kind, 'open': _flag(row, 'open', False)}
        else:
            raise EdltError('Unsupported dynamic-label control event')
        result.append(item)
    return result


def normalize_operation(operation):
    if (not isinstance(operation, Mapping) or set(operation) != {'op', 'target', 'events'}
            or operation.get('op') != 'dynamic-label-control'
            or operation.get('target') not in ('label', 'status')):
        raise EdltError('Invalid dynamic-label-control operation')
    return {'op': 'dynamic-label-control', 'target': operation['target'], 'events': normalize_events(operation['events'])}


def _rows(choices):
    if (not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or len(choices) > 4096):
        raise EdltError('Dynamic-label controls need complete observed ordered rows')
    result = []
    for row in choices:
        if (not isinstance(row, Mapping) or not {'identity', 'value', 'name', 'image_present'} <= set(row)
                or set(row) - {'identity', 'value', 'name', 'image_present', 'formatted_display'}):
            raise EdltError('Invalid dynamic-label observed row')
        item = {'identity': _text(row['identity']), 'value': _int(row['value'], 'choice value'),
                'name': None if row['name'] is None else _text(row['name']),
                'image_present': _flag(row, 'image_present', False)}
        if 'formatted_display' in row:
            item['formatted_display'] = None if row['formatted_display'] is None else _text(row['formatted_display'])
        result.append(item)
    if len({row['identity'] for row in result}) != len(result):
        raise EdltError('Observed dynamic-label row identities must be unique')
    return result


@dataclass(frozen=True)
class DynamicLabelControlState:
    text: str
    selected_value: int
    text_editable: bool
    binding_present: bool
    pending: bool = False
    suppress_next_selection: bool = False
    dropped_down: bool = False
    list_handler_attached: bool = False
    _owner: object = field(default=None, repr=False, compare=False)
    _issuer: object = field(default=None, repr=False, compare=False)
    _seal: str = field(default='', repr=False, compare=False)

    def as_dict(self):
        return {key: getattr(self, key) for key in ('text', 'selected_value', 'text_editable',
                'binding_present', 'pending', 'suppress_next_selection', 'dropped_down', 'list_handler_attached')}


def _issue(owner, **values):
    return DynamicLabelControlState(**values, _owner=owner, _issuer=_ISSUER,
        _seal=hashlib.sha256(_json({'owner_identity': id(owner), 'values': values})).hexdigest())


def check_state(state, *, owner):
    if (owner is None or type(state) is not DynamicLabelControlState or state._issuer is not _ISSUER
            or state._owner is not owner
            or hashlib.sha256(_json({'owner_identity': id(owner), 'values': state.as_dict()})).hexdigest() != state._seal):
        raise EdltError('Dynamic-label continuation needs its exact owner-issued immutable state')
    return state


@dataclass(frozen=True)
class DynamicLabelControlResult:
    state: DynamicLabelControlState
    _receipt_json: str

    def as_dict(self):
        return json.loads(self._receipt_json)


def run_dynamic_label_control(events, *, owner, choices,
        get_text: Callable[[], str], set_text: Callable[[str], object],
        get_index: Callable[[], int], set_index: Callable[[int], object],
        text_editable=False, binding_present=True, initial_state=None):
    """Run declared synchronous callbacks against one owning widget property.

    Source SelectedIndexChanged catches/logs exceptions; this qualified profile
    fails closed. Earlier writes are neither rolled back nor retried here.
    The ``enter`` event is the explicit PreviewKeyDown Enter-key shorthand.
    """
    rows = normalize_events(events)
    if owner is None or any(not callable(fn) for fn in (get_text, set_text, get_index, set_index)):
        raise EdltError('Dynamic-label controls need a non-null owner and property callbacks')
    _flag({'text_editable': text_editable}, 'text_editable', False)
    _flag({'binding_present': binding_present}, 'binding_present', False)
    _rows(choices)
    if initial_state is None:
        state = _issue(owner, text=_text(get_text()), selected_value=_int(get_index(), 'bound index'),
                       text_editable=text_editable, binding_present=binding_present, pending=False,
                       suppress_next_selection=False, dropped_down=False, list_handler_attached=False)
    else:
        state = check_state(initial_state, owner=owner)
    values = state.as_dict()
    initial, journal, projected, closed = state.as_dict(), [], [], False

    def record(index, event, action, **facts):
        journal.append({'event_index': index, 'event': event, 'action': action, **facts})

    def read(index, event, property_name):
        if property_name == 'Text':
            values['text'], values['pending'] = _text(get_text()), False
            value = values['text']
        else:
            value = values['selected_value'] = _int(get_index(), 'bound index')
        record(index, event, 'ReadValue', property=property_name, value=value)

    def write_read(index, event, property_name):
        value = values['text'] if property_name == 'Text' else values['selected_value']
        receipt = (set_text if property_name == 'Text' else set_index)(value)
        record(index, event, 'WriteValue', property=property_name, value=value, result=json.loads(_json(receipt)))
        read(index, event, property_name)

    def remove(index, event, prior_editable):
        for action in ('DetachSelectedIndexChanged', 'DetachPreviewKeyDown', 'DetachLeave'):
            record(index, event, action)
        if values['binding_present']:
            record(index, event, 'RemoveBinding', property='Text' if prior_editable else 'SelectedValue')

    def bind(index, event):
        if not values['binding_present']:
            return
        editable = values['text_editable']
        record(index, event, 'SetBindingMode', draw_mode=0 if editable else 1,
               value_member='Name' if editable else 'ValueAsInt',
               display_member='FormattedDisplay' if editable else 'DisplayValuePad3Name',
               drop_down_style=1 if editable else 2, data_source_update_mode=2)
        record(index, event, 'AddBinding', property='Text' if editable else 'SelectedValue')
        if editable:
            record(index, event, 'AttachPreviewKeyDown'); record(index, event, 'AttachLeave')
        record(index, event, 'AttachSelectedIndexChanged')

    for index, row in enumerate(rows):
        if closed:
            raise EdltError('Dynamic-label callbacks cannot follow explicit close')
        kind, start = row['event'], len(journal)
        if kind == 'input':
            if not values['text_editable'] or not values['binding_present']:
                raise EdltError('Dynamic-label text input requires an editable bound control')
            values['text'], values['pending'] = row['text'], True
        elif kind in ('enter', 'leave'):
            if values['binding_present'] and values['text_editable']:
                write_read(index, kind, 'Text')
        elif kind == 'key-preview':
            if values['binding_present'] and values['text_editable']:
                if row['key'] == 'enter':
                    write_read(index, kind, 'Text')
                elif row['key'] in _ARROWS:
                    values['suppress_next_selection'] = True
                elif values['dropped_down']:
                    values['dropped_down'] = False; record(index, kind, 'SetDroppedDown', value=False)
        elif kind == 'selected-row':
            if row['data_manager_present']:
                values['list_handler_attached'] = values['text_editable']
                record(index, kind, 'DetachListChanged')
                if values['text_editable']:
                    record(index, kind, 'AttachListChanged')
            if row['data_source_present'] and row['index'] >= 0:
                current = _rows(choices)
                if row['index'] >= len(current):
                    raise EdltError('Selected dynamic-label row is outside the observed collection')
                choice = current[row['index']]
                if (choice['identity'], choice['value']) != (row['identity'], row['value']):
                    raise EdltError('Selected dynamic-label row must match observed ordinal, identity and value')
                values['selected_value'] = choice['value']
                if values['text_editable']:
                    text = choice['formatted_display'] if 'formatted_display' in choice else choice['name']
                    if text is None or '\0' in text:
                        raise EdltError('Null/NUL selected text is outside the qualified host-text profile')
                    values['text'], values['pending'] = _text(text), True
            if values['suppress_next_selection']:
                values['suppress_next_selection'] = False; record(index, kind, 'SuppressSelectionWrite')
            elif row['data_source_present'] and row['index'] >= 0 and values['binding_present']:
                write_read(index, kind, 'Text' if values['text_editable'] else 'SelectedValue')
        elif kind == 'list-refresh':
            if values['text_editable'] and not row['list_updates_disabled']:
                if row['invoke_required']:
                    raise EdltError('Asynchronous dynamic-label dispatch is not established in this callback profile')
                earlier = (row['new_index'] < row['selected_index'] or (row['old_index'] < row['selected_index'] and row['old_index'] != -1))
                if (row['visible'] and row['change_type'] in ('item-added', 'item-changed', 'reset') and earlier and values['binding_present']):
                    read(index, kind, 'Text')
        elif kind == 'set-editable':
            if row['value'] != values['text_editable']:
                prior = values['text_editable']; values['text_editable'] = row['value']
                record(index, kind, 'SetVisible', value=True); remove(index, kind, prior); bind(index, kind)
                if values['binding_present']:
                    values['list_handler_attached'] = row['value']; record(index, kind, 'DetachListChanged')
                    if row['value']:
                        record(index, kind, 'AttachListChanged')
        elif kind == 'binding-source-change':
            if row['changed']:
                remove(index, kind, values['text_editable'])
                values['binding_present'] = row['present']; bind(index, kind)
        elif kind == 'drop-down':
            values['dropped_down'] = row['open']
        elif kind == 'close':
            if values['pending']:
                raise EdltError('Pending dynamic-label close has no established binding commit order')
            closed = True
        projected.append({**row, 'state': dict(values), 'actions': [entry['action'] for entry in journal[start:]]})
    final = _issue(owner, **values)
    receipt = {'format': 'cbus-edlt-dynamic-label-control-v1', 'initial_state': initial, 'state': final.as_dict(),
               'events': projected, 'binding_callbacks': journal, 'pending': final.pending, 'closed': closed,
               'input_limit_utf16_units': 64, 'automatic_binding_refresh_inferred': False,
               'implicit_close_inferred': False, 'host_gui_executed': False, 'physical_device_verified': False,
               'framework_async_dispatch_verified': False}
    return DynamicLabelControlResult(final, _json(receipt).decode('utf8'))


def drawing_descriptor(choices, *, index, text=''):
    """Logical OnDrawItem strings/icon branch, excluding pixels/font metrics."""
    rows = _rows(choices); index = _int(index)
    if len(rows) > 4:
        return {'drawn': False, 'reason': 'source-items-count-exceeds-four'}
    if index < 0:
        return {'drawn': True, 'text': _text(text), 'image_present': False}
    if index >= len(rows):
        raise EdltError('Original drawing Items index is outside the observed list')
    row = rows[index]
    ordinal = (row['value'] + 1 + 2**31) % 2**32 - 2**31
    prefix = str(ordinal) + ' - '
    return {'drawn': True, 'text': prefix if row['image_present'] else prefix + (row['name'] if row['name'] is not None else '<Default>'),
            'image_present': row['image_present'], 'pixel_rendering_verified': False}
