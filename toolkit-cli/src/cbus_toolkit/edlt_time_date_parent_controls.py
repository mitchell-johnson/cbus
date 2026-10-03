"""Source-owned Time/Date callback bases for one ordered parent transaction.

Ordinary scalar conversion retains its established validation. Callback-only
retained models preserve raw display/global values until an explicit binding
write, with exact adjacent-slot ownership supplied by the control projection.
"""
from dataclasses import dataclass, replace
from types import MappingProxyType

from .edlt import EdltError, _field, _int
from .edlt_time_date import _record, _STANDBY_TYPES, _FUNCTION_TYPES


@dataclass(frozen=True)
class TimeDateControlPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    record_before: bytes
    record: bytes
    adjacent_widget: int | None
    adjacent_before: bytes | None
    adjacent_after: bytes | None
    restore_reset_widgets: tuple
    expected: object
    changes: object
    options: object

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        projected = {**self.expected, **self.changes}
        return {'format': 'cbus-edlt-time-date-control-base-v1',
                'page': self.page, 'position': self.position, 'widget': self.widget,
                'page_mode': self.page_mode, 'slices': 2 if self.record[0] == 11 else 1,
                'display_type_raw': self.record[1],
                'global_formats': {name: projected[name][0] for name in
                    ('DateFormat', 'TimeFormat', 'TimeDateLeadingZero')},
                'record_before_hex': self.record_before.hex(), 'record_hex': self.record.hex(),
                'adjacent_widget': self.adjacent_widget,
                'adjacent_before_hex': None if self.adjacent_before is None else self.adjacent_before.hex(),
                'adjacent_after_hex': None if self.adjacent_after is None else self.adjacent_after.hex(),
                'restore_reset_widgets': list(self.restore_reset_widgets),
                'raw_model_fields_preserved': True, 'saved': False,
                'physical_device_verified': False, 'clock_set': False}


def _wrap(plan):
    return TimeDateControlPlan(plan.page, plan.position, plan.widget, plan.page_mode,
        plan.record_before, plan.record, plan.adjacent_widget, plan.adjacent_before,
        plan.adjacent_after, plan.restore_reset_widgets, plan.expected, plan.changes, plan.options)


def plan_control_base(editor, values, *, options):
    original = editor.snapshot(values)
    editor.common.static_references(original)
    for index in range(1, 22):
        kind = original[_field(index)][0]
        allowed = _STANDBY_TYPES if index < 6 else _FUNCTION_TYPES
        if kind not in allowed or (index == 5 and kind == 11):
            raise EdltError(f'Existing widget{index} type is outside the original UI placements')
    nav = original['NavWidgetType'][0]
    if nav not in (0, 1, 255):
        raise EdltError('Unsupported navigation widget mode')
    requested_mode = options.get('page_mode')
    mode = ('multiple' if nav == 1 else 'single') if requested_mode is None else requested_mode
    if mode not in ('single', 'multiple'):
        raise EdltError('page_mode must be single or multiple')
    page, position = options['page'], options['position']
    _int(page, 'Page', 0, 1 if mode == 'single' else 4)
    _int(position, 'Position', 1, 5 if page == 0 or mode == 'single' else 4)
    slot = position if page == 0 else 6 + (page - 1) * 4 + position - 1
    if page == 0 and position > 1 and original[_field(slot - 1)] == (11,):
        raise EdltError('This standby slot is covered by the previous two-slice widget; shrink it first')
    before = _record(original, slot)
    scalar = any(name not in ('page', 'position', 'page_mode') and value is not None
                 for name, value in options.items())
    if scalar or before[0] not in (10, 11):
        ordinary = editor.plan(values, **options)
        return _wrap(ordinary), {'mode': 'ordinary configuration/defaults before callbacks',
                                'converted': before[0] != ordinary.record[0],
                                'implicit_framework_dispatch': False}
    updates = editor.common._place_record(original, slot, before, normalize_mra=False)
    updates['NavWidgetType'] = (1 if mode == 'multiple' else 0,)
    for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
        if original[name] == (255,):
            updates[name] = (value,)
    updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
    updates.update(editor.crcs(updates))
    plan = TimeDateControlPlan(page, position, slot, mode, before, before,
        None, None, None, (), original,
        {name: value for name, value in updates.items() if value != original[name]}, options)
    return plan, {'mode': 'retained callbacks without ordinary mutation getters',
                  'converted': False, 'implicit_framework_dispatch': False}


def project_owned_controls(owner, binding, operation, values, plan):
    from .edlt_time_date_controls import project_time_date_controls, prepare_time_date_projection
    if binding.widget != plan.widget or operation['op'] != 'time-date':
        raise EdltError('Time/Date binding differs from the owning operation family/widget')
    result = project_time_date_controls(binding, owner=owner, operation=operation, values=values)
    record, changes, receipt = prepare_time_date_projection(result, owner=owner)
    adjacent = result.adjacent_widget
    # A scalar growth earlier in this operation still owns its cleared slot,
    # even if a later explicit callback shrinks the selected record again.
    return replace(plan, record=record, changes={**plan.changes, **changes},
        adjacent_widget=plan.adjacent_widget if adjacent is None else adjacent,
        adjacent_before=plan.adjacent_before if adjacent is None else result.adjacent_before,
        adjacent_after=plan.adjacent_after if adjacent is None else result.adjacent_after,
        restore_reset_widgets=tuple(sorted(set(plan.restore_reset_widgets)
                                          | set(result.restore_reset_widgets)))), receipt
