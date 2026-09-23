"""Original KEYGL5 Time/Date display settings and standby slice placement.

The unit-wide format fields configure displays; they do not set a clock or
select its time source. Database plans retain opaque bytes and expose exact
neighbor clearing when a standby widget changes to two slices.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render

DISPLAY_TYPES = MappingProxyType({'time': 0, 'date': 1, 'time-date': 2})
DATE_FORMATS = MappingProxyType(dict(enumerate((
    'dddd dd Mmm', 'ddd dd Mmm', 'ddd dd/mm', 'ddd mm/dd',
    'dd/mm', 'mm/dd', 'dd Mmm', 'Mmm dd'))))
TIME_FORMATS = MappingProxyType({'12-hour': 3, '24-hour': 1,
                               '12-hour-lowercase': 0, '12-hour-uppercase': 2})
_STANDBY_TYPES = frozenset((0, 10, 11, 12, 13, 255))
_FUNCTION_TYPES = frozenset((0, *range(2, 11), *range(12, 17), 255))


def _record(values, widget):
    return bytes(values[_field(widget, offset)][0] for offset in range(32))


@dataclass(frozen=True)
class TimeDateWidgetPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    slices: int
    display: str
    date_format: int
    time_format: str
    leading_zero: bool
    record_before: bytes
    record: bytes
    adjacent_widget: int | None
    adjacent_before: bytes | None
    adjacent_after: bytes | None
    restore_reset_widgets: tuple[int, ...]
    expected: Mapping
    changes: Mapping
    options: Mapping

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        globals_changed = {name: list(self.changes[name]) for name in
                           ('DateFormat', 'TimeFormat', 'TimeDateLeadingZero') if name in self.changes}
        return {'format': 'cbus-edlt-time-date-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00', 'page': self.page,
                'position': self.position, 'widget': self.widget, 'page_mode': self.page_mode,
                'slices': self.slices, 'display': self.display, 'date_format': self.date_format,
                'date_format_label': DATE_FORMATS[self.date_format], 'time_format': self.time_format,
                'leading_zero': self.leading_zero, 'global_format_changes': globals_changed,
                'global_formats_apply_to_whole_unit': True,
                'record_before_hex': self.record_before.hex(), 'record_hex': self.record.hex(),
                'adjacent_widget': self.adjacent_widget,
                'adjacent_before_hex': None if self.adjacent_before is None else self.adjacent_before.hex(),
                'adjacent_after_hex': None if self.adjacent_after is None else self.adjacent_after.hex(),
                'restore_reset_widgets': list(self.restore_reset_widgets),
                'changes': {name: list(value) if isinstance(value, tuple) else value
                            for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False, 'clock_set': False}


class EdltTimeDateWidget:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        for name, shape in {'DateFormat': ('int', 0, 4), 'TimeFormat': ('int', 5, 2),
                            'TimeDateLeadingZero': ('bit', 4, 1)}.items():
            try:
                layout = self.codec.layout(name)
            except (ValueError, KeyError) as error:
                raise EdltError('Unsupported time/date layout: ' + name) from error
            if (layout.address, layout.array_size, layout.array_skip) != (0x119, 1, 0) or (
                    layout.parameter.type, layout.bit_address, layout.bit_size) != shape:
                raise EdltError('Unsupported time/date layout: ' + name)

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, page, position, slices=None, display=None, page_mode=None,
             date_format=None, time_format=None, leading_zero=None):
        options = dict(page=page, position=position, slices=slices, display=display, page_mode=page_mode,
                       date_format=date_format, time_format=time_format, leading_zero=leading_zero)
        if slices is not None:
            _int(slices, 'Time/Date slices', 1, 2)
        if display is not None and (not isinstance(display, str) or display not in DISPLAY_TYPES):
            raise EdltError('display must be time/date/time-date')
        if date_format is not None:
            _int(date_format, 'Date format', 0, 7)
        if time_format is not None and (not isinstance(time_format, str) or time_format not in TIME_FORMATS):
            raise EdltError('Unsupported time format')
        if leading_zero is not None and type(leading_zero) is not bool:
            raise EdltError('leading_zero must be boolean')
        original = self.snapshot(current)
        self.common.static_references(original)
        for index in range(1, 22):
            kind = original[_field(index)][0]
            allowed = _STANDBY_TYPES if index < 6 else _FUNCTION_TYPES
            if kind not in allowed or (index == 5 and kind == 11):
                raise EdltError(f'Existing widget{index} type is outside the original UI placements')
        nav = original['NavWidgetType'][0]
        if nav not in (0, 1, 255):
            raise EdltError('Unsupported navigation widget mode')
        if page_mode is None:
            page_mode = 'multiple' if nav == 1 else 'single'
        if page_mode not in ('single', 'multiple'):
            raise EdltError('page_mode must be single or multiple')
        _int(page, 'Page', 0, 1 if page_mode == 'single' else 4)
        _int(position, 'Position', 1, 5 if page == 0 or page_mode == 'single' else 4)
        widget = position if page == 0 else 6 + (page - 1) * 4 + position - 1
        if page == 0 and position > 1 and original[_field(widget - 1)] == (11,):
            raise EdltError('This standby slot is covered by the previous two-slice widget; shrink it first')
        before = _record(original, widget)
        if slices is None:
            slices = 2 if before[0] == 11 else 1
        if slices == 2 and (page != 0 or position == 5):
            raise EdltError('Two-slice Time/Date is available only at standby positions1..4')
        kind = 9 + slices
        updates = dict(original)
        adjacent = None
        adjacent_before = adjacent_after = None
        if kind == 11 and before[0] != 11:
            adjacent = widget + 1
            adjacent_before = _record(original, adjacent)
            updates[_field(adjacent)] = (0,)
            adjacent_after = _record(updates, adjacent)
        record = bytearray(before)
        record[0] = kind
        if display is not None:
            record[1] = DISPLAY_TYPES[display]
        if record[1] not in DISPLAY_TYPES.values():
            raise EdltError('Invalid existing Time/Date display byte; supply an explicit display')
        display = next(name for name, value in DISPLAY_TYPES.items() if value == record[1])
        if widget >= 6 and before[0] != kind:
            updates[f'Widget{widget}RestoreLevel'] = (0,)
        for name, value in (('DateFormat', date_format),
                            ('TimeFormat', TIME_FORMATS[time_format] if time_format is not None else None),
                            ('TimeDateLeadingZero', int(leading_zero) if leading_zero is not None else None)):
            if value is not None:
                updates[name] = (value,)
        date_format = _int(updates['DateFormat'][0], 'Existing date format', 0, 7)
        time_code = _int(updates['TimeFormat'][0], 'Existing time format', 0, 3)
        time_format = next(name for name, value in TIME_FORMATS.items() if value == time_code)
        leading_zero = bool(_int(updates['TimeDateLeadingZero'][0], 'Existing leading zero', 0, 1))
        updates = self.common._place_record(updates, widget, record)
        updates['NavWidgetType'] = (1 if page_mode == 'multiple' else 0,)
        for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
            if original[name] == (255,):
                updates[name] = (value,)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        self.common.static_references(updates)
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        resets = tuple(index for index in range(6, 22) if updates[_field(index)] != original[_field(index)])
        return TimeDateWidgetPlan(page, position, widget, page_mode, slices, display, date_format,
                                  time_format, leading_zero, before, bytes(record), adjacent,
                                  adjacent_before, adjacent_after, resets, original, changes, options)

    def apply(self, session, plan):
        if not isinstance(plan, TimeDateWidgetPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a Time/Date plan returned by EdltTimeDateWidget.plan')
        for value, name, low, high in ((plan.widget, 'Plan widget', 1, 21), (plan.page, 'Plan page', 0, 4),
                                      (plan.position, 'Plan position', 1, 5), (plan.slices, 'Plan slices', 1, 2),
                                      (plan.date_format, 'Plan date format', 0, 7)):
            _int(value, name, low, high)
        if type(plan.leading_zero) is not bool:
            raise EdltError('Plan leading_zero must be boolean')
        if (not isinstance(plan.record, bytes) or len(plan.record) != 32 or
                not isinstance(plan.record_before, bytes) or len(plan.record_before) != 32):
            raise EdltError('Plan records must contain32 bytes')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid Time/Date plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated Time/Date settings')
        expected = {**plan.expected, **plan.changes}
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the Time/Date plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the Time/Date plan')
        except Exception as error:
            rollback_errors = []
            for name in reversed(attempted):
                if not getattr(session.programmer.client, 'connected', True):
                    rollback_errors.append('Connection lost; rollback stopped without recovery I/O; PP state is uncertain')
                    break
                try:
                    session.set(name, _render(plan.expected[name]))
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            if getattr(session.programmer.client, 'connected', True):
                try:
                    if self.snapshot(session.values()) != dict(plan.expected):
                        rollback_errors.append('Original PP values could not be verified')
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
