"""Source-owned Timer, Shutter and Room Courtesy properties.

Explicit getters may write. Read-only views never run macro/preset getters.
Assignment intents are source setter calls, not PP transport operations.
"""
from dataclasses import dataclass, replace
from .edlt import EdltError

FAMILY_TYPES = {'timer': 5, 'shutter': 3, 'room-courtesy': 15}
OFFSETS = {'timer': {'label': 17, 'status': 18},
           'shutter': {'label': 10, 'status': 11},
           'room-courtesy': {'label': 8, 'status': 9}}
MACRO_INPUTS = {
    8: (), 9: (), 10: (), 11: ('RampRate',), 12: ('RampRate',),
    14: ('RampRate',), 13: ('RampRate',), 15: ('RampRate',), 16: ('RampRate',),
    17: ('RampRate',), 18: ('RampRate',), 19: ('RampRate',), 20: ('RampRate',),
    21: ('Offset',), 22: ('Offset',), 23: ('RampRate', 'TargetLevel1'),
    24: ('RampRate', 'TargetLevel1'), 25: (), 26: ('SceneNumber',), 27: ('SceneNumber',),
    28: ('SceneNumber', 'RampRate'), 29: ('SceneNumber', 'RampRate'),
    30: ('SceneNumberCycleList', 'SceneNumber'), 31: ('SceneNumberCycleList', 'SceneNumber'),
    32: ('SceneNumber', 'Offset'), 33: ('SceneNumber', 'Offset'),
    34: ('TimerValue', 'ExpiryLevel'), 35: ('TimerValue', 'ExpiryLevel'), 255: (),
}
COMMON_PROPERTIES = frozenset(('StatusIconOnIndex', 'StatusIconOffIndex',
    'LeftButtonMacrofunction', 'RightButtonMacrofunction', 'DualButtonMacrofunction',
    'RampRateEditable', 'TargetLevel1Editable', 'TargetLevel2Editable', 'OffsetEditable',
    'RampRate', 'TargetLevel1', 'TargetLevel2', 'Offset'))
FAMILY_PROPERTIES = {
    'timer': COMMON_PROPERTIES | {'TargetLevel', 'ExpiryLevel', 'TimerValue'},
    'shutter': COMMON_PROPERTIES,
    'room-courtesy': COMMON_PROPERTIES | {'KeyMacrofunction', 'OffColour', 'OnColour', 'StatusIconIndex'},
}


def integer(value, what='Dual-key property'):
    if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
        raise EdltError(f'{what} requires an exact signed 32-bit integer')
    return value


def pp_byte(value):
    """PPAttribute.ValueAsInt's source clamp, not byte wrapping."""
    return min(255, max(0, integer(value)))


def checked_names(names):
    if type(names) is not tuple or len(names) != 64 or any(type(v) is not str for v in names):
        raise EdltError('Dual-key binding requires all 64 retained Names')
    try:
        for text in names:
            text.encode('utf8')
    except UnicodeError as error:
        raise EdltError('Dual-key Names require valid Unicode') from error
    return names


@dataclass(frozen=True)
class DualKeyPropertyState:
    family: str
    record: bytes
    restore_level: int
    editable: tuple[bool, bool, bool, bool] = (True, True, True, True)
    virtual_values: tuple[int, int, int, int] = (0, 0, 0, 0)

    def __post_init__(self):
        if (type(self.family) is not str or self.family not in FAMILY_TYPES
                or type(self.record) is not bytes or len(self.record) != 32
                or self.record[0] != FAMILY_TYPES[self.family]
                or type(self.restore_level) is not int or not 0 <= self.restore_level <= 255
                or type(self.editable) is not tuple or len(self.editable) != 4
                or any(type(v) is not bool for v in self.editable)
                or type(self.virtual_values) is not tuple or len(self.virtual_values) != 4):
            raise EdltError('Dual-key model requires a complete exact family record and typed source state')
        for v in self.virtual_values:
            integer(v)

    def used_static_text(self):
        used = []
        if self.record[1] & 15 == 5:
            index = self.record[OFFSETS[self.family]['status']]
            used.append(index if index < 64 else 0)
        if (self.record[1] >> 4) & 7 == 3:
            index = self.record[OFFSETS[self.family]['label']]
            used.append(index if index < 64 else 0)
        return tuple(sorted(set(used)))


@dataclass(frozen=True)
class DualKeyPropertyResult:
    state: DualKeyPropertyState
    writes: tuple[tuple[int, int], ...] = ()
    notifications: tuple[str, ...] = ()
    value: object = None

    def as_dict(self):
        return {'record_hex': self.state.record.hex(), 'restore_level': self.state.restore_level,
            'assignment_intents': [{'offset': i, 'value': v} for i, v in self.writes],
            'notification_intents': list(self.notifications), 'value': self.value,
            'implicit_framework_dispatch': False}


def _finish(state, writes=(), notifications=(), value=None, *, editable=None, virtual=None):
    raw = bytearray(state.record)
    normalized = tuple((i, pp_byte(v)) for i, v in writes)
    for i, val in normalized:
        raw[i] = val
    return DualKeyPropertyResult(replace(state, record=bytes(raw),
        editable=state.editable if editable is None else tuple(editable),
        virtual_values=state.virtual_values if virtual is None else tuple(virtual)),
        normalized, tuple(notifications), value)


def _check(state, property):
    if type(state) is not DualKeyPropertyState or type(property) is not str or property not in FAMILY_PROPERTIES[state.family]:
        raise EdltError('Property is not an actual member of this dual-key source family')


def input_value_is_editable(state, input_name):
    """Source ordered macro walk (each matching side overwrites the flag)."""
    if input_name not in ('RampRate', 'TargetLevel1', 'TargetLevel2', 'Offset'):
        raise EdltError('Unsupported source editability input')
    flag, count = False, 0
    for macro, inputs in MACRO_INPUTS.items():
        if macro == state.record[7]:
            flag = input_name in inputs
            count += 1
        if macro == state.record[8]:
            flag = input_name in inputs
            count += 1
        if flag or count >= 2:
            break
    return flag


def set_key_function_defaults(state):
    if state.family == 'shutter':
        return _finish(state, notifications=('InputValues',))
    flags, virtual = list(state.editable), list(state.virtual_values)
    writes = []
    for n, prop in enumerate(('RampRate', 'TargetLevel1', 'TargetLevel2', 'Offset')):
        active = input_value_is_editable(state, prop)
        if active != flags[n]:
            flags[n] = active
            if active:
                val = (1, 255, 255, 25)[n]
                if prop == 'RampRate' and state.family == 'timer':
                    writes.append((16, val))
                else:
                    virtual[n] = val
    return _finish(state, writes, ('InputValues',), editable=flags, virtual=virtual)


def read_dual_key_property(state, property, *, names=None):
    _check(state, property)
    if names is not None:
        checked_names(names)
    r, f = state.record, state.family
    if property == 'DualButtonMacrofunction':
        result = set_key_function_defaults(state)
        return replace(result, value=f'{r[7]}|{r[8]}')
    if f == 'shutter' and property in ('TargetLevel1', 'TargetLevel2'):
        offset = 8 if property == 'TargetLevel1' else 9
        value = min(248, max(6, r[offset]))
        return _finish(state, ((offset, value),) if value != r[offset] else (), value=value)
    simple = {'StatusIconOnIndex': r[2], 'StatusIconOffIndex': r[3],
        'LeftButtonMacrofunction': r[7], 'RightButtonMacrofunction': r[8],
        'RampRateEditable': state.editable[0], 'TargetLevel1Editable': state.editable[1],
        'TargetLevel2Editable': state.editable[2], 'OffsetEditable': state.editable[3],
        'RampRate': state.virtual_values[0], 'TargetLevel1': state.virtual_values[1],
        'TargetLevel2': state.virtual_values[2], 'Offset': state.virtual_values[3]}
    if f == 'shutter':
        simple.update(TargetLevel1Editable=r[7] > 0, TargetLevel2Editable=r[7] > 0)
    if f == 'timer':
        expiry = (r[15] << 8) + r[14]
        simple.update(RampRate=r[16], TargetLevel=r[9], TimerValue=(r[13] << 8) + r[12],
            ExpiryLevel=expiry - 65536 if expiry >= 32768 else expiry)
    if f == 'room-courtesy':
        simple.update(KeyMacrofunction=r[7], OffColour=r[10], OnColour=r[11], StatusIconIndex=r[2])
    return _finish(state, value=simple[property])


def write_dual_key_property(state, property, value):
    """Separate direct source property API; not a GUI parse/scheduling claim."""
    _check(state, property)
    if property == 'DualButtonMacrofunction':
        if value is None:
            return _finish(state)
        # Explicit canonical integer pair; host TryParse culture/null is open.
        if type(value) is not str or value.count('|') != 1:
            raise EdltError('Dual-key macro property requires a canonical integer pair')
        try:
            left, right = (integer(int(v)) for v in value.split('|'))
            if value != f'{left}|{right}':
                raise ValueError
        except (ValueError, TypeError, EdltError) as error:
            raise EdltError('Dual-key macro property requires a canonical signed integer pair') from error
        old = read_dual_key_property(state, property)
        if old.value == value:
            return old
        a = write_dual_key_property(old.state, 'LeftButtonMacrofunction', left)
        b = write_dual_key_property(a.state, 'RightButtonMacrofunction', right)
        c = set_key_function_defaults(b.state)
        return DualKeyPropertyResult(c.state, old.writes + a.writes + b.writes + c.writes,
            old.notifications + a.notifications + b.notifications + c.notifications)
    if property.endswith('Editable'):
        if type(value) is not bool or (state.family == 'shutter' and property.startswith('TargetLevel')):
            raise EdltError('This derived source property has no admitted setter')
        n = ('RampRateEditable', 'TargetLevel1Editable', 'TargetLevel2Editable', 'OffsetEditable').index(property)
        flags, virtual = list(state.editable), list(state.virtual_values)
        writes = []
        if flags[n] != value:
            flags[n] = value
            if value:
                v = (1, 255, 255, 25)[n]
                if n == 0 and state.family == 'timer':
                    writes = [(16, v)]
                else:
                    virtual[n] = v
        return _finish(state, writes, editable=flags, virtual=virtual)
    integer(value)
    if property in ('StatusIconOnIndex', 'StatusIconOffIndex'):
        return _finish(state, ((2 if property.endswith('OnIndex') else 3, value),))
    if state.family == 'room-courtesy' and property == 'StatusIconIndex':
        return _finish(state, ((3, value), (2, value)))
    if property in ('LeftButtonMacrofunction', 'RightButtonMacrofunction'):
        offset = 7 if property.startswith('Left') else 8
        writes = ((offset, value),) if state.record[offset] != value else ()
        return _finish(state, writes, ('InputValues',) if state.family == 'shutter' and offset == 7 else ())
    if state.family == 'timer':
        if property == 'ExpiryLevel':
            return _finish(state, ((15, (value >> 8) & 255), (14, value & 255)), ('ExpiryLevel',))
        if property == 'TimerValue':
            return _finish(state, ((13, value >> 8), (12, value & 255)))
        if property in ('TargetLevel', 'RampRate'):
            return _finish(state, ((9 if property == 'TargetLevel' else 16, value),),
                ('TargetLevel',) if property == 'TargetLevel' else ())
    if state.family == 'shutter' and property in ('TargetLevel1', 'TargetLevel2'):
        offset, val = (8 if property == 'TargetLevel1' else 9), min(248, max(6, value))
        return _finish(state, ((offset, val),) * (2 if value != val else 1))
    if state.family == 'room-courtesy' and property in ('KeyMacrofunction', 'OffColour', 'OnColour'):
        return _finish(state, (({'KeyMacrofunction': 7, 'OffColour': 10, 'OnColour': 11}[property], value),))
    if property in ('RampRate', 'TargetLevel1', 'TargetLevel2', 'Offset'):
        n = ('RampRate', 'TargetLevel1', 'TargetLevel2', 'Offset').index(property)
        virtual = list(state.virtual_values)
        virtual[n] = value
        return _finish(state, virtual=virtual)
    raise EdltError('Unsupported source property setter')


def force_dual_key_values(state):
    if type(state) is not DualKeyPropertyState:
        raise EdltError('Dual-key model state must be typed')
    if state.family == 'timer' and state.record[9] == 0:
        return write_dual_key_property(state, 'TargetLevel', 1)
    return _finish(state)


def dual_key_readonly_view(state, *, names=None):
    if type(state) is not DualKeyPropertyState:
        raise EdltError('Dual-key model state must be typed')
    if names is not None:
        checked_names(names)
    return {'family': state.family, 'record_hex': state.record.hex(),
        'restore_level': state.restore_level, 'raw_left_macro': state.record[7],
        'raw_right_macro': state.record[8], 'raw_status_type': state.record[1] & 15,
        'raw_label_type': (state.record[1] >> 4) & 7,
        'raw_label_index': state.record[OFFSETS[state.family]['label']],
        'raw_status_index': state.record[OFFSETS[state.family]['status']],
        'used_static_text': list(state.used_static_text()),
        'source_editable_flags': list(state.editable), 'source_virtual_values': list(state.virtual_values),
        'implicit_mutating_getters': False}
