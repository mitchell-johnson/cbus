"""Time/Date model properties from the retained managed source.

These explicit model calls are separate from offered GUI choices. Assignment
intents do not assert PPAttribute notification delivery: its original serialized
Value token and initialization mode are outside the normalized PP profile.
"""
from dataclasses import dataclass, replace
from .edlt import EdltError, _field

PROPERTIES = frozenset(('DisplayType', 'WidgetType', 'DateFormat', 'TimeFormat', 'TimeDateLeadingZero'))
GLOBAL_PROPERTIES = ('DateFormat', 'TimeFormat', 'TimeDateLeadingZero')


def integer(value):
    if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
        raise EdltError('Time/Date property requires an exact signed 32-bit integer')
    return value


def pp_byte(value):
    return min(255, max(0, integer(value)))


@dataclass(frozen=True)
class TimeDatePropertyState:
    widget: int
    record: bytes
    adjacent_record: bytes | None
    restore_level: int | None
    adjacent_restore_level: int | None
    date_format: int
    time_format: int
    leading_zero: int

    def __post_init__(self):
        if (type(self.widget) is not int or not 1 <= self.widget <= 21
                or type(self.record) is not bytes or len(self.record) != 32
                or self.record[0] not in (10, 11)
                or (self.adjacent_record is not None and (type(self.adjacent_record) is not bytes
                    or len(self.adjacent_record) != 32 or self.widget == 21))):
            raise EdltError('Time/Date properties require their exact selected and actual adjacent records')
        for value in (self.restore_level, self.adjacent_restore_level):
            if value is not None and (type(value) is not int or not 0 <= value <= 255):
                raise EdltError('Available Time/Date Restore fields must be exact bytes')
        if self.adjacent_record is None and self.adjacent_restore_level is not None:
            raise EdltError('Adjacent Restore cannot exist without its owned record')
        for value in (self.date_format, self.time_format, self.leading_zero):
            if type(value) is not int or not 0 <= value <= 255:
                raise EdltError('Time/Date raw global fields must be exact bytes')


@dataclass(frozen=True)
class TimeDatePropertyResult:
    state: TimeDatePropertyState
    writes: tuple[tuple[str, int], ...] = ()
    notification_intents: tuple[str, ...] = ()
    source_calls: tuple[str, ...] = ()
    value: object = None
    owns_adjacent: bool = False
    restore_reset_widgets: tuple[int, ...] = ()


def read_time_date_property(state, property):
    if type(state) is not TimeDatePropertyState or type(property) is not str or property not in PROPERTIES:
        raise EdltError('Unknown Time/Date source property')
    value = {'DisplayType': state.record[1], 'WidgetType': state.record[0],
        'DateFormat': state.date_format, 'TimeFormat': state.time_format,
        'TimeDateLeadingZero': state.leading_zero}[property]
    return TimeDatePropertyResult(state, value=value)


def set_time_date_default(state):
    """TimeAndDateData.SetToDefault delegates only to inherited Restore0."""
    if type(state) is not TimeDatePropertyState:
        raise EdltError('Time/Date default requires an exact model state')
    writes = () if state.restore_level is None else ((f'Widget{state.widget}RestoreLevel', 0),)
    return TimeDatePropertyResult(replace(state, restore_level=None if state.restore_level is None else 0),
        writes, source_calls=('TimeAndDateData.SetToDefault', 'WidgetBaseData.SetToDefault'),
        restore_reset_widgets=() if state.restore_level is None else (state.widget,))


def write_time_date_property(state, property, value):
    """Bounded direct model API; WidgetType admits only the Time/Date family."""
    read_time_date_property(state, property)
    requested, value = integer(value), pp_byte(value)
    if property == 'DisplayType':
        record = bytearray(state.record)
        record[1] = value
        return TimeDatePropertyResult(replace(state, record=bytes(record)),
            ((_field(state.widget, 1), value),), source_calls=('DisplayType.set', 'PPAttribute.ValueAsInt.set'))
    if property in GLOBAL_PROPERTIES:
        old = read_time_date_property(state, property).value
        if old == requested:
            return TimeDatePropertyResult(state, source_calls=(property + '.set.EqualValueReturn',))
        member = {'DateFormat': 'date_format', 'TimeFormat': 'time_format',
                  'TimeDateLeadingZero': 'leading_zero'}[property]
        return TimeDatePropertyResult(replace(state, **{member: value}), ((property, value),),
            source_calls=(property + '.set', 'PPAttribute.ValueAsInt.set'))
    if requested not in (10, 11):
        raise EdltError('This source profile cannot construct another WidgetData family')
    if state.record[0] == requested:
        return TimeDatePropertyResult(state, source_calls=('WidgetType.set.EqualValueReturn',))
    writes, calls, reset = [], [], []
    adjacent = state.adjacent_record
    adjacent_restore = state.adjacent_restore_level
    if requested == 11:
        if adjacent is None:
            raise EdltError('Two-slice source setter requires an actual next widget; off-unit access refuses')
        calls.append('WidgetBaseData.SuppressNotifications.true')
        if adjacent[0] != 0:
            raw = bytearray(adjacent)
            raw[0] = 0
            adjacent = bytes(raw)
            writes.append((_field(state.widget + 1), 0))
            calls.extend(('Next.WidgetType.set', 'Next.CreateData.BlankData', 'Next.WidgetBaseData.SetToDefault'))
            if adjacent_restore is not None:
                adjacent_restore = 0
                writes.append((f'Widget{state.widget + 1}RestoreLevel', 0))
                reset.append(state.widget + 1)
            calls.append('Next.NotifyPropertyChanged.WidgetType')
        else:
            calls.append('Next.WidgetType.set.EqualValueReturn')
        calls.append('WidgetBaseData.SuppressNotifications.false')
    raw = bytearray(state.record)
    raw[0] = requested
    writes.append((_field(state.widget), requested))
    calls.extend(('WidgetType.set', 'CreateData.TimeAndDateData', 'WidgetBaseData.SuppressNotifications.true',
                  'TimeAndDateData.SetToDefault', 'WidgetBaseData.SetToDefault'))
    restore = state.restore_level
    if restore is not None:
        restore = 0
        writes.append((f'Widget{state.widget}RestoreLevel', 0))
        reset.append(state.widget)
    calls.extend(('WidgetBaseData.SuppressNotifications.false', 'NotifyPropertyChanged.WidgetType'))
    return TimeDatePropertyResult(replace(state, record=bytes(raw), adjacent_record=adjacent,
        restore_level=restore, adjacent_restore_level=adjacent_restore), tuple(writes),
        ('Next.WidgetType', 'WidgetType') if requested == 11 and state.adjacent_record[0] != 0
        else ('WidgetType',), tuple(calls), owns_adjacent=requested == 11,
        restore_reset_widgets=tuple(reset))


def time_date_readonly_view(state):
    """Reads stored bytes only; no constructors, coercion or mutating getters."""
    if type(state) is not TimeDatePropertyState:
        raise EdltError('Time/Date view requires its exact model state')
    return {'widget': state.widget, 'widget_type': state.record[0], 'display_type': state.record[1],
        'record_hex': state.record.hex(), 'restore_level': state.restore_level,
        'adjacent_widget': None if state.adjacent_record is None else state.widget + 1,
        'adjacent_record_hex': None if state.adjacent_record is None else state.adjacent_record.hex(),
        'adjacent_restore_level': state.adjacent_restore_level,
        'date_format': state.date_format, 'time_format': state.time_format,
        'leading_zero': state.leading_zero, 'used_static_text': [], 'implicit_framework_dispatch': False}
