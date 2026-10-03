"""Owner-issued native Lighting label/status callback projection.

Only an authoritative snapshot producer issues binding rows. The detached
receipt is diagnostic and cannot import image facts or continue controls.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json

from .edlt import EdltError, _field
from .edlt_dynamic_label_control import normalize_events, run_dynamic_label_control
from .edlt_label_type_control import (LightingLabelState, apply_lighting_label_type,
                                     set_lighting_label_index)
from .edlt_scene_names import assign_name, load_names, scene_name

_ISSUER = object()


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf8')
    except (ValueError, TypeError, UnicodeError) as error:
        raise EdltError('Lighting control bindings require bounded Unicode JSON facts') from error


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def normalize_controls(controls):
    if not isinstance(controls, (list, tuple)) or not 1 <= len(controls) <= 64:
        raise EdltError('Lighting label_controls require 1..64 ordered label/status histories')
    result = []
    for row in controls:
        if (not isinstance(row, Mapping) or not {'target', 'events'} <= set(row)
                or set(row) - {'target', 'type', 'events'} or row['target'] not in ('label', 'status')):
            raise EdltError('Invalid Lighting label/status control history')
        item = {'target': row['target'], 'events': normalize_events(row['events'])}
        if 'type' in row:
            allowed = (0, 3, 10) if row['target'] == 'label' else (0, 1, 2, 3, 5, 10)
            if type(row['type']) is not int or row['type'] not in allowed:
                raise EdltError('Lighting control type is outside source choices')
            item['type'] = row['type']
        result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class LightingLabelBinding:
    operation_number: int
    application: int
    group: int
    source_sha256: str
    operation_sha256: str
    _rows_json: str = field(repr=False)
    _owner: object = field(repr=False, compare=False)
    _issuer: object = field(repr=False, compare=False)
    _seal: str = field(repr=False)

    def as_dict(self):
        return {'format': 'cbus-edlt-lighting-label-binding-v1',
                'operation': self.operation_number, 'application': self.application,
                'group': self.group, 'source_sha256': self.source_sha256,
                'operation_sha256': self.operation_sha256,
                'dynamic_rows': json.loads(self._rows_json),
                'snapshot_owned': True, 'receipt_can_resume': False}


def issue_lighting_label_binding(owner, *, operation_number, application, group,
                                 source_values, operation, dynamic_rows):
    if (owner is None or type(operation_number) is not int or operation_number < 1
            or type(application) is not int or not 48 <= application <= 95
            or type(group) is not int or not 0 <= group <= 255
            or not isinstance(operation, Mapping) or operation.get('op') != 'lighting'):
        raise EdltError('Invalid native Lighting label binding identity')
    normalize_controls(operation.get('label_controls'))
    if not isinstance(dynamic_rows, tuple) or len(dynamic_rows) > 4:
        raise EdltError('Lighting needs observed ordered DynamicAll rows, not inferred images')
    if group == 255 and dynamic_rows:
        raise EdltError('Lighting group255 has no selectable DynamicLabels in the source model')
    rows = []
    for index, row in enumerate(dynamic_rows):
        if (type(row) is not tuple or len(row) != 3 or row[0] != str(index)
                or type(row[1]) is not str or type(row[2]) is not bool):
            raise EdltError('Lighting DynamicAll must have exact variant0..3 value/text/image facts')
        rows.append({'identity': f'label:{application}/{group}/{index}', 'value': index,
                     'name': row[1], 'image_present': row[2]})
    payload = {'operation_number': operation_number, 'application': application, 'group': group,
               'source_sha256': _digest(source_values), 'operation_sha256': _digest(operation),
               'rows': rows}
    return LightingLabelBinding(operation_number, application, group, payload['source_sha256'],
        payload['operation_sha256'], _json(rows).decode('utf8'), owner, _ISSUER,
        _digest({'owner_identity': id(owner), 'values': payload}))


def _check(binding, owner, values, operation, number):
    if type(binding) is not LightingLabelBinding or binding._issuer is not _ISSUER or binding._owner is not owner:
        raise EdltError('Lighting label_controls need an owner-issued automatic snapshot binding')
    payload = {'operation_number': binding.operation_number, 'application': binding.application,
               'group': binding.group, 'source_sha256': binding.source_sha256,
               'operation_sha256': binding.operation_sha256, 'rows': json.loads(binding._rows_json)}
    if (_digest({'owner_identity': id(owner), 'values': payload}) != binding._seal
            or binding.operation_number != number
            or binding.source_sha256 != _digest(values) or binding.operation_sha256 != _digest(operation)):
        raise EdltError('Lighting label binding differs from its exact owner/source/history')
    return payload['rows']


def project_lighting_label_controls(owner, binding, *, operation_number,
                                    operation, values, record, common):
    controls = normalize_controls(operation['label_controls'])
    rows = _check(binding, owner, values, operation, operation_number)
    if type(record) is not bytes or len(record) != 32 or record[0] != 2:
        raise EdltError('Lighting label controls require an exact LightingData record')
    application = values['SecondaryApplication' if record[1] & 128 else 'PrimaryApplication'][0]
    if application == 255 and not record[1] & 128:
        application = 56
    if application != binding.application or record[6] != binding.group:
        raise EdltError('Lighting label binding does not match the selected application/group')
    from .edlt_static_grid import current as current_grid, adopt_retained_names
    grid = current_grid(values)
    names = list(grid.names if grid is not None else load_names(values))
    projected = dict(values)
    images = tuple(row['image_present'] for row in rows)
    state = LightingLabelState(record[1], record[13], record[14])
    control_states, receipts, allocations = {}, [], []
    control_owners = {'label': object(), 'status': object()}
    widget = 6 + (operation['page'] - 1) * 4 + operation['position'] - 1

    def install(new_state):
        nonlocal state
        state = new_state
        for offset, value in ((1, state.byte_value), (13, state.raw_label_index), (14, state.raw_status_index)):
            projected[_field(widget, offset)] = (value,)

    for ordinal, control in enumerate(controls, 1):
        target = control['target']
        type_result = None
        if 'type' in control:
            type_result = apply_lighting_label_type(state, target=target, value=control['type'], image_flags=images)
            install(type_result.state)
        editable = state.display_type(target) == (3 if target == 'label' else 5)
        previous = control_states.get(target)
        events = control['events']
        if any(row['event'] == 'selected-row' and row['index'] >= 0 for row in events) and editable:
            raise EdltError('Native static suggestion ordinals require an observed source culture/order profile')
        # Widget mode is owner-derived, never supplied as caller metadata.
        if any(row['event'] in ('set-editable', 'binding-source-change') for row in events):
            raise EdltError('Lighting mode/binding changes are owned by its type control, not caller event facts')
        if previous is not None and previous.text_editable != editable:
            events = [{'event': 'set-editable', 'value': editable}, *events]

        def get_text():
            return scene_name(tuple(names), state.index(target))

        def set_text(text):
            reference_view = dict(projected)
            for display, offset in (('label', 13), ('status', 14)):
                if state.display_type(display) == (3 if display == 'label' else 5):
                    reference_view[_field(widget, offset)] = (state.index(display),)
            used = common.static_references(reference_view)
            assignment = assign_name(tuple(names), state.index(target), text,
                                     values=projected, used_indices=lambda: tuple(used))
            names[:] = assignment.names
            projected.update(assignment.changes)
            allocation = set_lighting_label_index(state, target=target, index=assignment.index, image_flags=images)
            install(allocation.state)
            allocations.append(assignment.as_dict())
            adopt_retained_names(projected, tuple(names))
            return {'static_assignment': assignment.as_dict(), 'index_setter': allocation.as_dict()}

        def set_index(index):
            result = set_lighting_label_index(state, target=target, index=index, image_flags=images)
            install(result.state)
            return result.as_dict()

        result = run_dynamic_label_control(events, owner=control_owners[target],
            choices=rows if not editable else [], get_text=get_text, set_text=set_text,
            get_index=lambda: state.index(target), set_index=set_index,
            text_editable=editable, initial_state=previous)
        control_states[target] = result.state
        receipts.append({'history': ordinal, 'target': target,
                         'type_control': None if type_result is None else type_result.as_dict(),
                         'control': result.as_dict()})
    if any(state.pending for state in control_states.values()):
        raise EdltError('Lighting label_controls have pending text; parent save needs an explicit binding commit/read')
    from .edlt_scene_names import save_names
    static_changes, setters = save_names(projected, tuple(names))
    projected.update(static_changes)
    final = bytearray(record)
    final[1], final[13], final[14] = state.byte_value, state.raw_label_index, state.raw_status_index
    changes = {name: value for name, value in projected.items() if value != values[name]}
    return bytes(final), changes, {'format': 'cbus-edlt-lighting-label-controls-v1',
        'binding': binding.as_dict(), 'histories': receipts, 'state': state.as_dict(),
        'static_names': names, 'static_setter_indices': list(setters), 'allocations': allocations,
        'pending': False, 'automatic_framework_dispatch_inferred': False,
        'original_host_executed': False, 'physical_device_verified': False}
