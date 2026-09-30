"""Ordered classic DLT fallback, pressed-brightness and nightlight controls.

This replays the recovered Indicators component initialization and selected
events, then stages its coupled PP fields. It is not a complete Toolkit form,
physical programmer or label transport. Evidence lives in classic DLT
brightness/indicator original receipts under research/fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from types import MappingProxyType

from .dlt_labels import ClassicDltLabels, DltLabelApplyError, DltLabelError, _values

FORMAT = 'cbus-classic-dlt-indicator-plan-v1'
VIEW_FORMAT = 'cbus-classic-dlt-indicators-v1'
ADDRESS = 0x33
LAYOUT = MappingProxyType({
    'TimerDuration': (0x33, 0, 4, 'int'),
    'IndicatorPressedLevel': (0x33, 4, 4, 'int'),
    'EnableNightlight': (0x34, 0, 1, 'bit'),
    'DisableTimerFlash': (0x34, 1, 1, 'bit'),
    'EnablePageFallback': (0x34, 2, 1, 'bit'),
    'EnableIndicatorPressedLevel': (0x34, 3, 1, 'bit'),
    'FirstKeyThrowAway': (0x34, 4, 1, 'bit'),
    'EnableNightlightOnUserKeys': (0x34, 5, 1, 'bit'),
    'EnableNightlightOnToggleKey': (0x34, 6, 1, 'bit'),
    'EnableNightlightControl': (0x34, 7, 1, 'bit'),
})
FIELDS = tuple(LAYOUT)
CONTROL_FIELDS = MappingProxyType({
    'page_fallback': 'EnablePageFallback',
    'pressed_enabled': 'EnableIndicatorPressedLevel',
    'duration_seconds': 'TimerDuration',
    'pressed_level': 'IndicatorPressedLevel',
    'nightlight_keys': 'EnableNightlightOnUserKeys',
    'nightlight_toggle': 'EnableNightlightOnToggleKey',
    'first_key_throwaway': 'FirstKeyThrowAway',
})
OWNED = (*CONTROL_FIELDS.values(), 'EnableNightlight')
MAX_OPERATIONS = 64  # Local input/resource bound, not an original GUI limit.


def _snapshot(current):
    result = {}
    for name, (_, _, width, _) in LAYOUT.items():
        if name not in current:
            raise DltLabelError('Missing current classic DLT indicator parameter: ' + name)
        values = _values(current[name], name)
        if len(values) != 1 or type(values[0]) is not int or not 0 <= values[0] < (1 << width):
            raise DltLabelError('Invalid current classic DLT indicator parameter: ' + name)
        result[name] = values
    return result


def _operations(rows):
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= MAX_OPERATIONS:
        raise DltLabelError(f'Supply 1..{MAX_OPERATIONS} ordered indicator operations')
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'control', 'value'}:
            raise DltLabelError('Each indicator operation requires exactly control and value')
        control, value = row['control'], row['value']
        if not isinstance(control, str) or control not in CONTROL_FIELDS:
            raise DltLabelError('Unknown classic DLT indicator control')
        if control in ('duration_seconds', 'pressed_level'):
            low = 2 if control == 'duration_seconds' else 0
            if type(value) is not int or not low <= value <= 15:
                raise DltLabelError(f'{control} must be an integer in {low}..15')
        elif type(value) is not bool:
            raise DltLabelError(control + ' must be a boolean')
        result.append((control, value))
    return tuple(result)


def _raw(values):
    result = [0, 0]
    for name, (address, bit, _, _) in LAYOUT.items():
        result[address - ADDRESS] |= values[name][0] << bit
    return bytes(result)


def _enabled(state):
    return {'page_fallback': True, 'pressed_enabled': True,
            'duration_seconds': state['page_fallback'] or state['pressed_enabled'],
            'pressed_level': state['pressed_enabled'],
            'nightlight_keys': state['pressed_enabled'],
            'nightlight_toggle': state['pressed_enabled'],
            'first_key_throwaway': state['nightlight_keys'] or state['nightlight_toggle']}


def _nightlight(state):
    if not (state['nightlight_keys'] or state['nightlight_toggle']):
        state['first_key_throwaway'] = False


def _store_duration(state):
    state['duration_seconds'] = (state['duration_selected_seconds']
                                 if _enabled(state)['duration_seconds'] else 0)


def _fallback(state):
    if not state['pressed_enabled']:
        state['nightlight_keys'] = state['nightlight_toggle'] = False
    _nightlight(state)
    if state['page_fallback'] and state['duration_seconds'] == 0:
        state['duration_selected_seconds'] = 15
        _store_duration(state)


def _load(expected):
    state = {control: (expected[field][0] if control in ('duration_seconds', 'pressed_level')
                       else bool(expected[field][0])) for control, field in CONTROL_FIELDS.items()}
    duration = state['duration_seconds']
    state['page_fallback'] &= duration > 0
    state['pressed_enabled'] &= duration > 0
    state['duration_selected_seconds'] = duration if duration > 1 else 2
    return state


def _initialize(state):
    # PopulateNonFlashComponents_Other invokes the pressed-checkbox handler, then
    # UpdateFallbackEnabled. The handler updates dependencies before storing.
    _fallback(state)
    _store_duration(state)
    _fallback(state)


def _step(state, control, value):
    if not _enabled(state)[control]:
        raise DltLabelError('Original classic DLT control is disabled: ' + control)
    if control == 'duration_seconds':
        state['duration_selected_seconds'] = value
        _store_duration(state)
    elif state[control] != value:
        # Original SetChecked writes the bound property, then emits a callback
        # only when checked state changed. Numeric pressed level is direct.
        state[control] = value
        if control == 'page_fallback':
            _fallback(state)
        elif control == 'pressed_enabled':
            _fallback(state)
            _store_duration(state)
        elif control in ('nightlight_keys', 'nightlight_toggle'):
            _nightlight(state)


def _saved(expected, state):
    result = dict(expected)
    for control, field in CONTROL_FIELDS.items():
        result[field] = (int(state[control]),)
    # Original DLT BeforeSaveProgrammingInformation clears this inherited
    # bit; it is a visible save normalization, not a generic nightlight toggle.
    result['EnableNightlight'] = (0,)
    return result


def _trace(expected, operations):
    state = _load(expected)
    loaded = dict(state)
    _initialize(state)
    initialized = dict(state)
    initial_pp = _saved(expected, state)
    steps = []
    for index, (control, value) in enumerate(operations, 1):
        before = dict(state)
        _step(state, control, value)
        steps.append({'index': index, 'control': control, 'value': value,
                      'before': before, 'after': dict(state), 'enabled_after': _enabled(state)})
    after = _saved(expected, state)
    return {'loaded': loaded, 'before': initialized, 'after': dict(state),
            'initialization_changes': {k: list(v) for k, v in initial_pp.items()
                                       if k != 'EnableNightlight' and v != expected[k]},
            'save_normalizations': ({'EnableNightlight': [0]} if expected['EnableNightlight'] != (0,) else {}),
            'enabled_before': _enabled(initialized), 'enabled_after': _enabled(state), 'steps': steps}, after


@dataclass(frozen=True)
class DltIndicatorPlan:
    unit_type: str
    identity: tuple | None
    expected: dict
    changes: dict
    operations: tuple

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))
        object.__setattr__(self, 'operations', tuple(tuple(row) for row in self.operations))
        if self.identity is not None:
            object.__setattr__(self, 'identity', tuple(self.identity))

    def as_dict(self):
        trace, _ = _trace(self.expected, self.operations)
        before_raw, after_raw = _raw(self.expected), _raw({**self.expected, **self.changes})
        return {'format': FORMAT, 'unit_type': self.unit_type,
                'firmware': None if self.identity is None else self.identity[1],
                'catalog_number': None if self.identity is None else self.identity[2],
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'requested': [{'control': k, 'value': v} for k, v in self.operations], **trace,
                'raw_preview': [{'address': ADDRESS + i, 'before': a, 'after': b,
                                 'changed_mask': a ^ b, 'owned_mask': (0xFF, 0x7D)[i]}
                                for i, (a, b) in enumerate(zip(before_raw, after_raw))],
                'saved': False, 'device_verified': False, 'labels_transferred': False,
                'raw_verification_scope': 'staged-pp-session-before-save',
                'original_full_form_save_executed': False}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise DltLabelError('Expected a ' + FORMAT + ' document')
        try:
            for key in ('expected', 'changes'):
                if not isinstance(data[key], dict) or any(type(v) is not int for row in data[key].values() for v in row):
                    raise ValueError('Indicator PP values must be exact integers')
            unit_type, firmware, catalog = data['unit_type'], data.get('firmware'), data.get('catalog_number')
            if firmware is None and catalog is not None:
                raise ValueError('A catalogue requires firmware identity')
            identity = None if firmware is None else (unit_type, firmware, catalog)
            plan = cls(unit_type, identity, _snapshot(data['expected']), data['changes'], _operations(data['requested']))
            if set(data['expected']) != set(FIELDS) or set(data['changes']) - set(OWNED):
                raise ValueError('Unexpected PP fields')
            if json.dumps(data, sort_keys=True) != json.dumps(plan.as_dict(), sort_keys=True):
                raise ValueError('Serialized indicator plan is not canonical')
            return plan
        except (KeyError, TypeError, AttributeError, ValueError, IndexError) as error:
            raise DltLabelError('Invalid classic DLT indicator plan: ' + str(error)) from error


class ClassicDltIndicators(ClassicDltLabels):
    def __init__(self, spec, unit_type):
        super().__init__(spec, unit_type)
        for name, (address, bit, width, kind) in LAYOUT.items():
            try:
                field = self.codec.layout(name)
            except Exception as error:
                raise DltLabelError('Missing classic DLT indicator layout: ' + name) from error
            if (field.address, field.array_size, field.bit_address, field.bit_size, field.array_skip,
                    field.parameter.type) != (address, 1, bit, width, 0, kind):
                raise DltLabelError('Unsupported classic DLT indicator layout: ' + name)

    def _verify_session(self, session, *, fields=FIELDS):
        return super()._verify_session(session, fields=fields)

    def snapshot(self, current):
        return _snapshot(current)

    def show(self, current, identity=None):
        if identity is not None:
            identity = self.check_identity(*identity)
        expected = self.snapshot(current)
        trace, _ = _trace(expected, ())
        return {'format': VIEW_FORMAT, 'unit_type': self.unit_type,
                'firmware': None if identity is None else identity[1],
                'catalog_number': None if identity is None else identity[2],
                'controls': trace['before'], 'enabled': trace['enabled_before'],
                'initialization_changes': trace['initialization_changes'],
                'save_normalizations': trace['save_normalizations'],
                'raw_parameters': {k: list(v) for k, v in expected.items()},
                'saved': False, 'device_verified': False, 'original_full_form_save_executed': False}

    def plan(self, current, *, operations, identity=None):
        operations = _operations(operations)
        if identity is not None:
            identity = self.check_identity(*identity)
        expected = self.snapshot(current)
        _, after = _trace(expected, operations)
        changes = {k: v for k, v in after.items() if v != expected[k]}
        return DltIndicatorPlan(self.unit_type, identity, expected, changes, operations)

    @staticmethod
    def _raw_indicators(session):
        if not hasattr(session, 'get_raw_data'):
            return None
        line = session.get_raw_data(ADDRESS, 2).lines[-1]
        if 'RawData=' not in line:
            raise DltLabelError('Native indicator raw readback did not return RawData')
        raw = bytes.fromhex(line.split('RawData=', 1)[1].strip())
        if len(raw) != 2:
            raise DltLabelError('Native indicator raw readback must contain two bytes')
        return raw

    def apply(self, session, plan):
        if (type(plan) is not DltIndicatorPlan or plan.unit_type != self.unit_type
                or set(plan.expected) != set(FIELDS) or set(plan.changes) - set(OWNED)):
            raise DltLabelError('Plan contains fields outside the classic DLT indicator controls')
        if any(type(v) is not int for row in (*plan.expected.values(), *plan.changes.values()) for v in row):
            raise DltLabelError('Indicator PP values must be exact integers')
        canonical = self.plan(plan.expected, operations=[{'control': k, 'value': v} for k, v in plan.operations],
                              identity=plan.identity)
        if canonical != plan:
            raise DltLabelError('Classic DLT indicator plan differs from its ordered operations')
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity != identity:
            raise DltLabelError('Plan was created for another unit identity')
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise DltLabelError('PP parameters changed since the DLT indicator plan was created')
        before_raw = self._raw_indicators(session)
        if before_raw is not None and before_raw != _raw(plan.expected):
            raise DltLabelError('Native indicator raw bytes disagree with PP values')
        expected, attempted = {**plan.expected, **plan.changes}, []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            if self.snapshot(session.values()) != expected:
                raise DltLabelError('Native DLT indicator readback differs from the plan')
            after_raw = self._raw_indicators(session)
            if before_raw is not None and after_raw != _raw(expected):
                raise DltLabelError('Native DLT indicator changed unrelated bits or differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            raise DltLabelApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True,
                'raw_bytes_verified': after_raw is not None,
                'raw_before_hex': None if before_raw is None else before_raw.hex(),
                'raw_after_hex': None if after_raw is None else after_raw.hex()}

    def configure(self, session, *, operations):
        identity = self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), operations=operations, identity=identity))
