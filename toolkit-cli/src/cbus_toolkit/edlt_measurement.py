"""Exact KEYGL5 Measurement fields and static references in database PP.

Scaling accepts either explicit signed mantissa/exponent pairs or the original
Measurement editor's intentionally lossy decimal composite conversion.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import math
import re
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render

_STANDBY_TYPES = frozenset((0, 10, 11, 12, 13, 255))
_FUNCTION_TYPES = frozenset((0, *range(2, 11), *range(12, 17), 255))
BUILTIN_ICON_INDICES = frozenset((*range(39), *range(128, 142), 252, 253, 254))
_COMPOSITE_RE = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')


def _signed(value):
    return value - 256 if value >= 128 else value


def _word(record, offset):
    return int.from_bytes(bytes(record[offset:offset+2]), 'little', signed=True)


def _decimal_value(mantissa, exponent):
    # Construct an exact value without depending on the caller's Decimal
    # precision/traps or rounding through a binary floating-point conversion.
    return format(Decimal((int(mantissa < 0), tuple(map(int, str(abs(mantissa)))), exponent)), 'f')


def _format_double_without_e(number):
    """Reproduce the original Framework/Mono ``F50`` display boundary.

    Toolkit 1.18 was built against the legacy .NET formatter, which carries
    fifteen significant double digits into a fixed 50-decimal representation.
    The final fixed-place rounding is needed for values below 1e-50.
    """
    significant = format(number, '.15g')
    with localcontext() as context:
        context.prec = max(128, len(significant) + 64)
        value = Decimal(significant)
        quantum = Decimal(1).scaleb(-50)
        text = format(value.quantize(quantum, rounding=ROUND_HALF_EVEN), 'f')
    return text.rstrip('0').rstrip('.') or '0'


def _try_break_number(number):
    text = _format_double_without_e(number)
    point = text.find('.')
    if point >= 0:
        text = text.rstrip('0')
        point = text.find('.')
        exponent = -(len(text) - point - 1)
        integer = math.trunc(number * math.pow(10.0, -exponent))
    else:
        trimmed = text.rstrip('0')
        exponent = len(text) - len(trimmed)
        integer = math.trunc(number / math.pow(10.0, exponent))
        if integer == 0:
            exponent = 0
    return integer, exponent


def measurement_composite(value, *, gain=False):
    """Convert one invariant decimal exactly as Toolkit's Measurement editor.

    The returned dictionary retains whether the value was representable on the
    first pass. ``gain=True`` applies the original zero-to-one Gain rule.
    Invalid input is rejected rather than silently retaining an earlier GUI
    value, which is the only sensible contract for a non-interactive CLI.
    """
    if not isinstance(value, str):
        raise EdltError('Measurement composite value must be text')
    if len(value) > 20:
        raise EdltError('Measurement composite value exceeds the original 20-character field')
    source = value.strip()
    if not source or not _COMPOSITE_RE.fullmatch(source):
        raise EdltError('Measurement composite value must be an invariant decimal number')
    try:
        number = float(source)
    except ValueError as error:
        raise EdltError('Measurement composite value must be an invariant decimal number') from error
    if not math.isfinite(number):
        raise EdltError('Measurement composite value must be finite')
    if gain and number == 0.0:
        number = 1.0
    adjusted = number
    integer, exponent = _try_break_number(adjusted)
    exact = -32768 <= integer <= 32767
    iterations = 0
    while not (-32768 <= integer <= 32767):
        text = _format_double_without_e(adjusted)
        point = text.find('.')
        if point < 0:
            candidate = adjusted
            digits = 1
            while candidate == adjusted:
                power = math.pow(10.0, digits)
                candidate = math.trunc(candidate / power) * power
                digits += 1
            adjusted = candidate
        else:
            places = len(text) - point - 1
            adjusted = round(adjusted, places - 1)
        integer, exponent = _try_break_number(adjusted)
        iterations += 1
        if iterations > 128:
            raise EdltError('Measurement composite value could not be represented')
    if not -128 <= exponent <= 127:
        raise EdltError('Measurement composite exponent is outside the stored signed-byte range')
    if gain and integer == 0:
        integer, exponent = 1, 0
    return {
        'input': value,
        'normalized_value': _format_double_without_e(adjusted),
        'mantissa': integer,
        'exponent': exponent,
        'stored_value': _decimal_value(integer, exponent),
        'exact': exact,
    }


@dataclass(frozen=True)
class MeasurementWidgetPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    device_id: int
    channel: int
    decimal_places: int
    gain_mantissa: int
    gain_exponent: int
    offset_mantissa: int
    offset_exponent: int
    gain_normalized: bool
    icon_index: int
    icon_editable: bool
    restore_level: int | None
    expected: Mapping
    changes: Mapping
    record: bytes
    allocations: Mapping
    composite_conversions: Mapping
    options: Mapping

    def __post_init__(self):
        for name in ('expected', 'changes', 'allocations', 'composite_conversions', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-measurement-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'page': self.page, 'position': self.position, 'widget': self.widget,
                'page_mode': self.page_mode, 'device_id': self.device_id, 'channel': self.channel,
                'decimal_places': self.decimal_places, 'gain_mantissa': self.gain_mantissa,
                'gain_exponent': self.gain_exponent, 'offset_mantissa': self.offset_mantissa,
                'offset_exponent': self.offset_exponent,
                'gain_value': _decimal_value(self.gain_mantissa, self.gain_exponent),
                'offset_value': _decimal_value(self.offset_mantissa, self.offset_exponent),
                'gain_normalized': self.gain_normalized, 'restore_level': self.restore_level,
                'icon_index': self.icon_index, 'icon_editable': self.icon_editable,
                'text_indices': dict(zip(('prefix', 'suffix', 'label'), (self.record[10], self.record[11], self.record[13]))),
                'record_hex': self.record.hex(),
                'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
                'allocations': {k: v.as_dict() if v else None for k, v in self.allocations.items()},
                'composite_conversions': {k: dict(v) for k, v in self.composite_conversions.items()},
                'ui_composite_conversion': bool(self.composite_conversions),
                'saved': False, 'physical_device_verified': False}


class EdltMeasurementWidget:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        try:
            layout = self.codec.layout('UseBigIcon')
        except (ValueError, KeyError) as error:
            raise EdltError('Unsupported Measurement UseBigIcon layout') from error
        if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size,
                layout.array_size, layout.array_skip) != (0x118, 'bit', 4, 1, 1, 0):
            raise EdltError('Unsupported Measurement UseBigIcon layout')

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, page, position, device_id, channel, decimal_places=None,
             gain_mantissa=None, gain_exponent=None, offset_mantissa=None, offset_exponent=None,
             gain_value=None, offset_value=None,
             page_mode=None, prefix_text=None, prefix_index=None, suffix_text=None, suffix_index=None,
             label_text=None, label_index=None, icon_index=None):
        options = dict(page=page, position=position, device_id=device_id, channel=channel,
                       decimal_places=decimal_places, gain_mantissa=gain_mantissa, gain_exponent=gain_exponent,
                       offset_mantissa=offset_mantissa, offset_exponent=offset_exponent,
                       gain_value=gain_value, offset_value=offset_value, page_mode=page_mode,
                       prefix_text=prefix_text, prefix_index=prefix_index, suffix_text=suffix_text,
                       suffix_index=suffix_index, label_text=label_text, label_index=label_index,
                       icon_index=icon_index)
        conversions = {}
        for name, value, mantissa, exponent, is_gain in (
                ('gain', gain_value, gain_mantissa, gain_exponent, True),
                ('offset', offset_value, offset_mantissa, offset_exponent, False)):
            if value is None:
                continue
            if mantissa is not None or exponent is not None:
                raise EdltError(f'{name}_value cannot accompany an explicit mantissa or exponent')
            conversions[name] = measurement_composite(value, gain=is_gain)
        if 'gain' in conversions:
            gain_mantissa = conversions['gain']['mantissa']
            gain_exponent = conversions['gain']['exponent']
        if 'offset' in conversions:
            offset_mantissa = conversions['offset']['mantissa']
            offset_exponent = conversions['offset']['exponent']
        _int(device_id, 'Measurement device ID', 0, 254)
        _int(channel, 'Measurement channel', 0, 254)
        if decimal_places is not None:
            _int(decimal_places, 'Measurement decimal places', 0, 5)
        if icon_index is not None:
            _int(icon_index, 'Measurement icon index')
            if icon_index not in BUILTIN_ICON_INDICES:
                raise EdltError('Measurement icon is outside the original built-in selector')
        for name, value in (('gain_mantissa', gain_mantissa), ('offset_mantissa', offset_mantissa)):
            if value is not None:
                _int(value, name, -32768, 32767)
        if gain_mantissa == 0:
            raise EdltError('Gain mantissa must be nonzero; original Gain setter replaces zero with one')
        for name, value in (('gain_exponent', gain_exponent), ('offset_exponent', offset_exponent)):
            if value is not None:
                _int(value, name, -128, 127)
        text_options = (('prefix', 10, prefix_text, prefix_index), ('suffix', 11, suffix_text, suffix_index),
                        ('label', 13, label_text, label_index))
        for name, _, text, index in text_options:
            if text is not None and (not isinstance(text, str) or index is not None):
                raise EdltError(f'{name}_text must be a string and cannot accompany {name}_index')
            if index is not None:
                _int(index, name + ' index')
                if index not in range(64) and index != 255 and not (name == 'label' and index == 64):
                    raise EdltError('Static index must be0..63 or255, with64 allowed only for the Measurement label')
        original = self.snapshot(current)
        self.common.static_references(original)
        for index in range(1, 22):
            kind = original[_field(index)][0]
            allowed = _STANDBY_TYPES if index < 6 else _FUNCTION_TYPES
            if kind not in allowed or (index == 5 and kind == 11):
                raise EdltError(f'Existing widget{index} type is outside the original UI placements')
        updates = dict(original)
        nav = original['NavWidgetType'][0]
        if nav not in (0, 1, 255):
            raise EdltError('Unsupported navigation widget mode')
        if page_mode is None:
            page_mode = 'multiple' if nav == 1 else 'single'
        if page_mode not in ('single', 'multiple'):
            raise EdltError('page_mode must be single or multiple')
        _int(page, 'Page', 0, 1 if page_mode == 'single' else 4)
        _int(position, 'Position', 1, 5 if page == 0 or page_mode == 'single' else 4)
        widget = position if page == 0 else 6 + (page-1)*4 + position-1
        use_icon = _int(original['UseBigIcon'][0], 'Existing UseBigIcon', 0, 1)
        icon_editable = widget >= 6 and use_icon == 1
        if icon_index is not None and not icon_editable:
            raise EdltError('Icon editing requires a functional widget and existing UseBigIcon1')
        if page == 0 and position > 1 and original[_field(widget - 1)] == (11,):
            raise EdltError('This standby slot is covered by the previous two-slice widget; shrink it first')
        record = [original[_field(widget, index)][0] for index in range(32)]
        if record[0] not in (0, 12, 255):
            raise EdltError('Selected widget is another type; replacing it is outside this workflow')
        restore = original[f'Widget{widget}RestoreLevel'][0] if widget >= 6 else None
        if record[0] != 12:
            record[:14] = (12, 0, 0, 2, 1, 0, 0, 0, 0, 0, 255, 255, 135, 64)
            if widget >= 6:
                restore = 0
        record[1:3] = (device_id, channel)
        if icon_index is not None:
            record[12] = icon_index
        if decimal_places is not None:
            record[3] = decimal_places
        if not 0 <= record[3] <= 5:
            raise EdltError('Invalid existing precision; supply decimal_places in0..5')
        for offset, value in ((4, gain_mantissa), (8, offset_mantissa)):
            if value is not None:
                record[offset:offset+2] = value.to_bytes(2, 'little', signed=True)
        for offset, value in ((6, gain_exponent), (7, offset_exponent)):
            if value is not None:
                record[offset] = value & 255
        gain_normalized = _word(record, 4) == 0
        if gain_normalized:
            # MeasurementData.Gain getter performs this mutation, unlike its
            # no-op SetForcedValues hook. Report the normalization explicitly.
            record[4:6] = (1, 0)
        allocations = {}
        for name, slot, text, index in text_options:
            if index is not None:
                record[slot] = index
            allocations[name] = None
            if text is not None:
                if not text.strip():
                    record[slot] = 255
                else:
                    view = self.common._place_record(updates, widget, record)
                    allocation = self.common.allocate_static_text(view, text)
                    allocations[name] = allocation
                    updates.update(allocation.changes)
                    record[slot] = allocation.index
        updates = self.common._place_record(updates, widget, record)
        if widget >= 6:
            updates[f'Widget{widget}RestoreLevel'] = (restore,)
        updates['NavWidgetType'] = (1 if page_mode == 'multiple' else 0,)
        for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
            if original[name] == (255,):
                updates[name] = (value,)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        self.common.static_references(updates)
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return MeasurementWidgetPlan(page, position, widget, page_mode, device_id, channel, record[3],
                                     _word(record, 4), _signed(record[6]), _word(record, 8), _signed(record[7]),
                                     gain_normalized, record[12], icon_editable, restore,
                                     original, changes, bytes(record), allocations, conversions, options)

    def apply(self, session, plan):
        if not isinstance(plan, MeasurementWidgetPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a Measurement widget plan returned by EdltMeasurementWidget.plan')
        _int(plan.widget, 'Plan widget', 1, 21)
        _int(plan.page, 'Plan page', 0, 4)
        _int(plan.position, 'Plan position', 1, 5)
        _int(plan.device_id, 'Plan device ID', 0, 254)
        _int(plan.channel, 'Plan channel', 0, 254)
        _int(plan.decimal_places, 'Plan decimal places', 0, 5)
        for value in (plan.gain_mantissa, plan.offset_mantissa):
            _int(value, 'Plan mantissa', -32768, 32767)
        for value in (plan.gain_exponent, plan.offset_exponent):
            _int(value, 'Plan exponent', -128, 127)
        if not isinstance(plan.gain_normalized, bool):
            raise EdltError('Plan gain_normalized must be boolean')
        _int(plan.icon_index, 'Plan icon index')
        if type(plan.icon_editable) is not bool:
            raise EdltError('Plan icon_editable must be boolean')
        if plan.widget >= 6:
            _int(plan.restore_level, 'Plan restore level')
        elif plan.restore_level is not None:
            raise EdltError('Standby widgets have no RestoreLevel parameter')
        if not isinstance(plan.record, bytes) or len(plan.record) != 32:
            raise EdltError('Plan widget record must contain 32 bytes')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid Measurement plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated Measurement settings')
        expected = dict(plan.expected)
        expected.update(plan.changes)
        self.snapshot(expected)
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the Measurement plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the Measurement plan')
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
