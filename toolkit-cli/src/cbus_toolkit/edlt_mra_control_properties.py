"""Source-owned properties for three derived MRA model classes.

No host/WinForms callbacks, source defaults or mutation getters run implicitly.
Source setter assignment intents are distinct from PPSET transport writes.
"""
from dataclasses import dataclass
from typing import Callable

from .edlt import EdltError

FAMILY_TYPES = {'zone-control': 7, 'source-select': 8, 'source-control': 9}
OFFSETS = {'zone-control': {'label': 11, 'status': 12},
           'source-select': {'label': 9, 'status': 10},
           'source-control': {'label': 7}}
# Exact full MacroFunctionTypes/MicroFunctions declaration dependency. Missing
# raw function IDs contribute nothing; no DualButtonMacrofunction getter read.
RAMP_FUNCTIONS = frozenset((11, 12, 14, 13, 15, 16, 17, 18, 19, 20, 23, 24, 28, 29))
OFFSET_FUNCTIONS = frozenset((21, 22, 32, 33))


def byte(value, what='MRA property'):
    if type(value) is not int or not 0 <= value <= 255:
        raise EdltError(f'{what} requires an exact byte')
    return value


def checked_names(names):
    if type(names) is not tuple or len(names) != 64 or any(type(v) is not str for v in names):
        raise EdltError('MRA properties require all 64 retained names')
    try:
        for text in names:
            text.encode('utf-8')
    except UnicodeError as error:
        raise EdltError('MRA retained names require valid Unicode') from error
    return names


@dataclass(frozen=True)
class MRAPropertyState:
    family: str
    record: bytes
    restore_level: int

    def __post_init__(self):
        if (type(self.family) is not str or self.family not in FAMILY_TYPES or type(self.record) is not bytes
                or len(self.record) != 32 or self.record[0] != FAMILY_TYPES[self.family]):
            raise EdltError('MRA state requires its exact derived-family complete record')
        byte(self.restore_level, 'MRA RestoreLevel')

    def index(self, target):
        try:
            return self.record[OFFSETS[self.family][target]]
        except KeyError as error:
            raise EdltError('MRA family has no requested static-text target') from error

    def used_static_text(self):
        if self.family == 'zone-control':
            used = [self.record[11]]
            if self.record[1] & 7 == 5:
                used.append(self.record[12])
        elif self.family == 'source-select':
            used = [self.record[9], self.record[10]]
        else:
            used = [self.record[7]]
        return tuple(sorted(set(used)))


@dataclass(frozen=True)
class MRAPropertyResult:
    state: MRAPropertyState
    writes: tuple[tuple[int, int], ...] = ()
    notifications: tuple[str, ...] = ()
    value: object = None

    def as_dict(self):
        return {'record_hex': self.state.record.hex(), 'restore_level': self.state.restore_level,
                'assignment_intents': [{'offset': i, 'value': v} for i, v in self.writes],
                'notification_intents': list(self.notifications), 'value': self.value,
                'implicit_framework_dispatch': False}


def _finish(state, writes=(), notifications=(), value=None, restore=None):
    if type(state) is not MRAPropertyState:
        raise EdltError('MRA property state must be typed')
    raw = bytearray(state.record)
    for offset, val in writes:
        raw[offset] = byte(val)
    return MRAPropertyResult(MRAPropertyState(state.family, bytes(raw),
        state.restore_level if restore is None else byte(restore)),
        tuple(writes), tuple(notifications), value)


def read_mra_property(state, property, *, names):
    """Explicit source property read; only the named macro getter mutates."""
    if type(state) is not MRAPropertyState:
        raise EdltError('MRA property state must be typed')
    if type(property) is not str:
        raise EdltError('MRA property name must be a string')
    checked_names(names)
    r, family = state.record, state.family
    simple = {'StatusDisplayType': r[1] & 7, 'StatusDisplayValueEditable': (r[1] & 7) == 5,
              'Zone': (r[1] >> 3) & 7, 'Multiplexer': (r[1] >> 6) & 3,
              'BigIconOnIndex': r[2], 'BigIconOffIndex': r[3], 'FunctionVariant': r[6]}
    if property in simple:
        return _finish(state, value=simple[property])
    if property == 'LabelDisplayType':
        raise EdltError('Zone LabelDisplayType source accessors are unimplemented')
    if property == 'LabelValueIndex':
        return _finish(state, value=state.index('label'))
    if property == 'StatusValueIndex' and family != 'source-control':
        return _finish(state, value=state.index('status'))
    for target in OFFSETS[family]:
        if property == ('LabelValueText' if target == 'label' else 'StatusValueText'):
            index = state.index(target)
            return _finish(state, value=names[index] if 0 <= index <= 63 else '')
    if family == 'zone-control':
        direct = {'LeftButtonMacrofunction': r[7], 'RightButtonMacrofunction': r[8],
                  'RampRate': r[9], 'Offset': r[10],
                  'RampRateEditable': r[7] in RAMP_FUNCTIONS or r[8] in RAMP_FUNCTIONS,
                  'OffsetEditable': r[7] in OFFSET_FUNCTIONS or r[8] in OFFSET_FUNCTIONS}
        if property in direct:
            return _finish(state, value=direct[property])
        if property == 'DualButtonMacrofunction':
            pair = f'{r[7]}|{r[8]}'
            if pair in ('15|16', '21|22'):
                return _finish(state, value=pair)
            return _finish(state, ((7, 15), (8, 16)), ('DualButtonMacrofunction',), '15|16')
    if family == 'source-select':
        direct = {'AbsoluteSource1': r[7], 'AbsoluteSource2': r[8],
                  'AbsoluteSource1Editable': r[6] > 0,
                  'AbsoluteSource2Editable': r[6] > 1,
                  'AnyAbsoluteSourceEditable': r[6] > 0}
        if property in direct:
            return _finish(state, value=direct[property])
    raise EdltError('Property is not implemented by this exact MRA family')


def write_mra_property(state, property, value):
    """Direct bounded byte properties; offered UI domains are adapter-owned."""
    if type(state) is not MRAPropertyState:
        raise EdltError('MRA property state must be typed')
    if type(property) is not str:
        raise EdltError('MRA property name must be a string')
    r, family = state.record, state.family
    if property == 'StatusDisplayType':
        byte(value)
        combined = value + (r[1] & 0xF8)
        if combined > 255:
            raise EdltError('MRA raw addition exceeds the admitted byte-property profile')
        return _finish(state, ((1, combined),), ('StatusDisplayValueEditable',))
    if property == 'Zone':
        if type(value) is not int or not 0 <= value <= 7:
            raise EdltError('MRA Zone source profile is raw0..7')
        return _finish(state, ((1, (value << 3) + (r[1] & 0xC7)),))
    if property == 'Multiplexer':
        if type(value) is not int or not 0 <= value <= 3:
            raise EdltError('MRA Multiplexer source profile is raw0..3')
        return _finish(state, ((1, (value << 6) + (r[1] & 0x3F)),))
    if property == 'FunctionVariant':
        byte(value)
        return _finish(state) if r[6] == value else _finish(state, ((6, value),), ('FunctionVariant',))
    if property == 'BigIconOffIndex':
        return _finish(state, ((3, byte(value)),))
    if property == 'BigIconOnIndex':
        byte(value)
        writes = ((2, value), (3, value)) if family == 'source-select' else (
            ((3, value), (2, value)) if family == 'source-control' else ((2, value),))
        return _finish(state, writes)
    if property == 'LabelDisplayType':
        raise EdltError('Zone LabelDisplayType source accessors are unimplemented')
    if property == 'LabelValueIndex':
        return _finish(state, ((OFFSETS[family]['label'], byte(value)),))
    if property == 'StatusValueIndex' and family != 'source-control':
        return _finish(state, ((OFFSETS[family]['status'], byte(value)),))
    if family == 'zone-control':
        direct = {'LeftButtonMacrofunction': 7, 'RightButtonMacrofunction': 8, 'RampRate': 9, 'Offset': 10}
        if property in direct:
            return _finish(state, ((direct[property], byte(value)),))
        if property == 'DualButtonMacrofunction':
            if value is None:
                return _finish(state)
            # Source splitting/parsing is retained separately. The new explicit
            # profile admits exact offered pairs only, without host null parsing.
            if value not in ('15|16', '21|22'):
                raise EdltError('MRA macro property requires a pinned exact pair')
            left, right = map(int, value.split('|'))
            return _finish(state, ((7, left), (8, right)), ('DualButtonMacrofunction',))
    if family == 'source-select' and property in ('AbsoluteSource1', 'AbsoluteSource2'):
        return _finish(state, ((7 if property.endswith('1') else 8, byte(value)),))
    raise EdltError('Property is not writable by this exact MRA family')


def mra_readonly_view(state, *, names):
    """No mutation getter or unimplemented LabelDisplayType accessor is called."""
    fields = ['StatusDisplayType', 'StatusDisplayValueEditable', 'Zone', 'Multiplexer',
              'BigIconOnIndex', 'BigIconOffIndex', 'FunctionVariant', 'LabelValueIndex', 'LabelValueText']
    if state.family != 'source-control':
        fields += ['StatusValueIndex', 'StatusValueText']
    if state.family == 'zone-control':
        fields += ['LeftButtonMacrofunction', 'RightButtonMacrofunction', 'RampRate', 'Offset',
                   'RampRateEditable', 'OffsetEditable']
    if state.family == 'source-select':
        fields += ['AbsoluteSource1', 'AbsoluteSource2', 'AbsoluteSource1Editable',
                   'AbsoluteSource2Editable', 'AnyAbsoluteSourceEditable']
    return {name: read_mra_property(state, name, names=names).value for name in fields}


def default_mra_properties(state, *, set_text: Callable):
    """Explicit defaults, including transient old Select status ownership."""
    state = MRAPropertyState(state.family, state.record, 0)
    writes, notes, actions, extras = [], [], ['WidgetBaseData.SetToDefault:RestoreLevel=0'], []

    def apply(prop, value):
        nonlocal state
        outcome = write_mra_property(state, prop, value)
        state = outcome.state
        writes.extend(outcome.writes); notes.extend(outcome.notifications)
        actions.append(f'{prop}={value}')

    apply('FunctionVariant', 0)
    apply('StatusDisplayType', 0)
    if state.family == 'zone-control':
        apply('DualButtonMacrofunction', '15|16'); apply('Offset', 13)
        apply('FunctionVariant', 0); apply('RampRate', 3); apply('StatusDisplayType', 0)
        apply('StatusValueIndex', 255); apply('LabelValueIndex', 255)
        apply('BigIconOffIndex', 29); apply('BigIconOnIndex', 30)
    elif state.family == 'source-select':
        apply('FunctionVariant', 0); apply('LabelValueIndex', 255)
        outcome, receipt = set_text(state, 'status', 'Source')
        state = outcome.state; writes.extend(outcome.writes); notes.extend(outcome.notifications)
        extras.append(receipt); actions.append('StatusValueText=Source')
        apply('BigIconOffIndex', 136); apply('BigIconOnIndex', 136)
    else:
        apply('FunctionVariant', 0); apply('LabelValueIndex', 255); apply('BigIconOnIndex', 138)
    return MRAPropertyResult(state, tuple(writes), tuple(notes)), tuple(actions), tuple(extras)
