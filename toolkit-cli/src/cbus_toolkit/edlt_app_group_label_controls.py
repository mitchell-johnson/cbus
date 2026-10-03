"""Source-owned label/status callbacks for six AppGroup widget panels.

Native metadata issues each binding at the ordinary widget plan's actual
position. Receipts describe that profile; they cannot issue choices or resume
a control. Explicit callbacks do not infer host notification scheduling.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
from weakref import WeakKeyDictionary

from .edlt import EdltError, _field
from .edlt_app_group_label_properties import (
    AppGroupLabelState, apply_app_group_label_type, profile,
    set_app_group_label_index,
)
from .edlt_dynamic_label_control import (
    normalize_events as dynamic_events, run_dynamic_label_control,
)
from .edlt_scene_name_control import (
    normalize_events as static_events, run_scene_name_control,
)
from .edlt_scene_names import (
    FIXED_SUGGESTION_NAMES, assign_name, load_names, save_names, scene_name,
)

_ISSUER = object()
_ISSUED = WeakKeyDictionary()


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf8')
    except (ValueError, TypeError, UnicodeError) as error:
        raise EdltError('AppGroup control bindings require bounded Unicode JSON facts') from error


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def normalize_controls(controls, *, family):
    """Panel-specific histories; enter denotes the Enter key, never focus Enter.

MultiLevel/Fan Off/Low/Medium/High use ComboBoxStaticText callbacks. Their
static targets therefore use selected-name/arrow-preview, not image ordinals.
Other targets use ComboImageTagDLT. No caller supplies binding modes or state.
"""
    selected = profile(family)
    if not isinstance(controls, (list, tuple)) or not 1 <= len(controls) <= 64:
        raise EdltError('AppGroup label_controls require 1..64 ordered control histories')
    targets = ('label', 'status', *(name for name, _ in selected.static_status_targets))
    result = []
    for row in controls:
        if (not isinstance(row, Mapping) or not {'target', 'events'} <= set(row)
                or set(row) - {'target', 'type', 'events'}
                or type(row['target']) is not str or row['target'] not in targets):
            raise EdltError('Invalid AppGroup label/status control history')
        target = row['target']
        static_target = bool(selected.static_status_targets) and target != 'label'
        events = static_events(row['events']) if static_target else dynamic_events(row['events'])
        if any(event['event'] in ('set-editable', 'binding-source-change') for event in events):
            raise EdltError('AppGroup mode/binding changes belong to its type control')
        item = {'target': target, 'events': events}
        if 'type' in row:
            allowed = (0, 10, 3) if target == 'label' else selected.status_choices
            if type(row['type']) is not int or row['type'] not in allowed:
                raise EdltError('AppGroup control type is outside its actual panel choices')
            item['type'] = row['type']
        result.append(item)
    return tuple(result)


@dataclass(frozen=True, eq=False)
class AppGroupLabelBinding:
    family: str
    operation_number: int
    application: int
    group: int
    source_sha256: str
    operation_sha256: str
    _rows_json: str = field(repr=False)
    _names_json: str = field(repr=False)
    _provider_json: str = field(repr=False)
    _owner: object = field(repr=False)
    _issuer: object = field(repr=False)

    def as_dict(self):
        return {'format': 'cbus-edlt-app-group-label-binding-v1',
                'family': self.family, 'operation': self.operation_number,
                'application': self.application, 'group': self.group,
                'source_sha256': self.source_sha256,
                'operation_sha256': self.operation_sha256,
                'retained_names_sha256': _digest(json.loads(self._names_json)),
                'dynamic_rows': json.loads(self._rows_json),
                'provider_provenance': json.loads(self._provider_json),
                'snapshot_owned': True, 'receipt_can_resume': False}


def _payload(binding):
    return {'family': binding.family, 'operation_number': binding.operation_number,
            'application': binding.application, 'group': binding.group,
            'source_sha256': binding.source_sha256,
            'operation_sha256': binding.operation_sha256,
            'rows': json.loads(binding._rows_json),
            'retained_names': json.loads(binding._names_json),
            'provider': json.loads(binding._provider_json)}


def issue_app_group_label_binding(owner, *, operation_number, application, group,
                                  source_values, operation, dynamic_rows,
                                  provider_provenance=None):
    if not isinstance(operation, Mapping):
        raise EdltError('AppGroup binding requires an exact operation')
    family = operation.get('op')
    selected = profile(family)
    valid_application = (application == selected.fixed_application
        if selected.fixed_application is not None
        else type(application) is int and (48 <= application <= 95
            or family in ('multilevel', 'room-courtesy') and (96 <= application <= 127 or application == 136)))
    if (owner is None or type(operation_number) is not int or operation_number < 1
            or type(application) is not int or not valid_application
            or type(group) is not int or not 0 <= group <= 255):
        raise EdltError('Invalid native AppGroup label binding identity')
    normalize_controls(operation.get('label_controls'), family=family)
    if type(dynamic_rows) is not tuple or len(dynamic_rows) > 4:
        raise EdltError('AppGroup needs observed ordered DynamicAll rows, not inferred images')
    if group == 255 and dynamic_rows:
        raise EdltError('AppGroup group255 has no selectable DynamicLabels in the source model')
    rows = []
    for index, row in enumerate(dynamic_rows):
        if (type(row) is not tuple or len(row) != 3 or row[0] != str(index)
                or type(row[1]) is not str or type(row[2]) is not bool):
            raise EdltError('AppGroup DynamicAll requires exact variant0..3 text/image facts')
        rows.append({'identity': f'label:{application}/{group}/{index}', 'value': index,
                     'name': row[1], 'image_present': row[2]})
    from .edlt_static_grid import current
    grid = current(source_values)
    names = tuple(grid.names) if grid is not None else load_names(source_values)
    binding = AppGroupLabelBinding(family, operation_number, application, group,
        _digest(source_values), _digest(operation), _json(rows).decode('utf8'), _json(names).decode('utf8'),
        _json(provider_provenance).decode('utf8'), owner, _ISSUER)
    # Authority stays outside the public immutable fields. Even a same-content
    # dataclasses.replace copy is unissued; mutating its owner/digest cannot
    # replace the independently retained original owner and payload.
    _ISSUED[binding] = (owner, _digest(_payload(binding)))
    return binding


def _check(binding, owner, values, operation, number):
    if (type(binding) is not AppGroupLabelBinding or binding._issuer is not _ISSUER
            or binding._owner is not owner or owner is None):
        raise EdltError('AppGroup label_controls need an owner-issued automatic snapshot binding')
    issued = _ISSUED.get(binding)
    if (issued is None or issued[0] is not owner
            or issued[1] != _digest(_payload(binding))
            or binding.operation_number != number
            or binding.family != operation.get('op')
            or binding.source_sha256 != _digest(values)
            or binding.operation_sha256 != _digest(operation)):
        raise EdltError('AppGroup label binding differs from its exact owner/source/history')
    return json.loads(binding._rows_json)


def project_app_group_label_controls(owner, binding, *, operation_number,
                                     operation, values, record, common):
    family = operation.get('op')
    selected = profile(family)
    controls = normalize_controls(operation['label_controls'], family=family)
    rows = _check(binding, owner, values, operation, operation_number)
    state = AppGroupLabelState(family, record)
    application = (selected.fixed_application if selected.fixed_application is not None
        else values['SecondaryApplication' if record[1] & 128 else 'PrimaryApplication'][0])
    if application != binding.application or record[6] != binding.group:
        raise EdltError('AppGroup label binding does not match the selected application/group')
    single_page = values.get('NavWidgetType') in ((0,), (255,))
    if (type(operation.get('page')) is not int or not 1 <= operation['page'] <= (1 if single_page else 4)
            or type(operation.get('position')) is not int
            or not 1 <= operation['position'] <= (5 if single_page else 4)):
        raise EdltError('AppGroup controls require an exact widget position')
    widget = 6 + (operation['page'] - 1) * 4 + operation['position'] - 1
    if any(values.get(_field(widget, offset)) != (record[offset],) for offset in range(32)):
        raise EdltError('AppGroup control record differs from its exact post-widget source')
    from .edlt_static_grid import current, adopt_retained_names
    grid = current(values)
    names = list(grid.names if grid is not None else load_names(values))
    if names != json.loads(binding._names_json):
        raise EdltError('AppGroup label binding differs from its complete retained name cache')
    projected = dict(values)
    images = tuple(row['image_present'] for row in rows)
    control_states, receipts, allocations = {}, [], []
    control_owners = {row['target']: object() for row in controls}
    static_choices = list(names) + list(FIXED_SUGGESTION_NAMES)

    def install(new_state):
        nonlocal state
        state = new_state
        for offset in range(32):
            projected[_field(widget, offset)] = (state.record[offset],)

    def get_text(target):
        return scene_name(tuple(names), state.index(target))

    def set_text(target, text):
        reference_view = dict(projected)
        # The source GetUsedStaticText consumes virtual, clamped index getters.
        for display, offset in (('label', selected.label_offset), ('status', selected.status_offset)):
            if state.display_type(display) == (3 if display == 'label' else 5):
                reference_view[_field(widget, offset)] = (state.index(display),)
        used = common.static_references(reference_view)
        assignment = assign_name(tuple(names), state.index(target), text,
                                 values=projected, used_indices=lambda: tuple(used))
        names[:] = assignment.names
        static_choices[:] = names + list(FIXED_SUGGESTION_NAMES)
        projected.update(assignment.changes)
        setter = set_app_group_label_index(state, target=target, index=assignment.index,
                                          image_flags=images)
        install(setter.state)
        allocations.append(assignment.as_dict())
        return {'static_assignment': assignment.as_dict(), 'index_setter': setter.as_dict()}

    for ordinal, control in enumerate(controls, 1):
        target = control['target']
        type_result = None
        if 'type' in control:
            type_result = apply_app_group_label_type(state, target=target,
                value=control['type'], image_flags=images)
            install(type_result.state)
        static_target = bool(selected.static_status_targets) and target != 'label'
        previous = control_states.get(target)
        if static_target:
            result = run_scene_name_control(control['events'],
                get_name=lambda: get_text(target), set_name=lambda text: set_text(target, text),
                known_names=static_choices, initial_state=previous)
            control_class = 'ComboBoxStaticText'
        else:
            editable = state.display_type(target) == (3 if target == 'label' else 5)
            events = control['events']
            if editable and any(row['event'] == 'selected-row' and row['index'] >= 0 for row in events):
                raise EdltError('Native static suggestion ordinals require an observed source culture/order profile')
            if previous is not None and previous.text_editable != editable:
                events = [{'event': 'set-editable', 'value': editable}, *events]

            def set_index(index):
                setter = set_app_group_label_index(state, target=target, index=index,
                                                   image_flags=images)
                install(setter.state)
                return setter.as_dict()

            result = run_dynamic_label_control(events, owner=control_owners[target],
                choices=rows if not editable else [], get_text=lambda: get_text(target),
                set_text=lambda text: set_text(target, text), get_index=lambda: state.index(target),
                set_index=set_index, text_editable=editable, initial_state=previous)
            control_class = 'ComboImageTagDLT'
        control_states[target] = result.state
        receipts.append({'history': ordinal, 'target': target, 'control_class': control_class,
                        'type_control': None if type_result is None else type_result.as_dict(),
                        'control': result.as_dict()})
    if any(control.pending for control in control_states.values()):
        raise EdltError('AppGroup label_controls have pending text; parent save needs an explicit binding commit/read')
    static_changes, setters = save_names(projected, tuple(names))
    projected.update(static_changes)
    changes = {name: value for name, value in projected.items() if value != values[name]}
    receipt = {'format': 'cbus-edlt-app-group-label-controls-v1',
        'family': family, 'binding': binding.as_dict(), 'histories': receipts,
        'state': state.as_dict(), 'static_names': names,
        'static_setter_indices': list(setters), 'allocations': allocations,
        'pending': False, 'automatic_framework_dispatch_inferred': False,
        'original_host_executed': False, 'physical_device_verified': False}
    # A later callback/refused pending close must leave the enclosing owning
    # cache intact. Install the retained table only after the complete branch
    # and its save projection have succeeded.
    adopt_retained_names(projected, tuple(names))
    return state.record, changes, receipt
