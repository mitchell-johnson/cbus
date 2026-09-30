"""Three independent classic DLT display/indicator controls, database PP only.

Original Toolkit load/save fragments establish IndicatorMode 0=off,1=normal,
2/3=on (explicit on saves2), direct InvertDisplay and ShowClock=!HideClock.
This explicit-subset editor does not execute the original complete form save;
in particular an omitted IndicatorMode retains raw3. Coupled fallback,
brightness/nightlight controls, physical rendering and transfers are excluded.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from types import MappingProxyType

from .dlt_labels import ClassicDltLabels, DltLabelApplyError, DltLabelError, _values


FORMAT = 'cbus-classic-dlt-display-plan-v1'
VIEW_FORMAT = 'cbus-classic-dlt-display-v1'
ADDRESS = 0x35
KNOWN_MASK = 0x7F
# The complete known PP ownership of byte35; bit7 has no declared PP field and
# is carried through from native GET_RAW_DATA, never synthesized as a zero.
LAYOUT = MappingProxyType({
    'IndicatorMode': (0, 2, 'int'),
    '35bit2': (2, 1, 'bit'),
    'DisableKeySlider': (3, 1, 'bit'),
    'InvertDisplay': (4, 1, 'bit'),
    'HideClock': (5, 1, 'bit'),
    'EnableScheduling': (6, 1, 'bit'),
})
FIELDS = tuple(LAYOUT)
MODES = ('off', 'normal', 'on')
CONTROLS = MappingProxyType({
    'indicator_mode': ('IndicatorMode', 0x03),
    'invert_display': ('InvertDisplay', 0x10),
    'show_clock': ('HideClock', 0x20),
})


def _settings(settings):
    if not isinstance(settings, dict) or not settings or set(settings) - set(CONTROLS):
        raise DltLabelError('Select indicator_mode, invert_display or show_clock display controls')
    result = {}
    for name in CONTROLS:
        if name not in settings:
            continue
        value = settings[name]
        if name == 'indicator_mode':
            if not isinstance(value, str) or value not in MODES:
                raise DltLabelError('indicator_mode must be off, normal or on')
        elif type(value) is not bool:
            raise DltLabelError(name + ' must be a boolean')
        result[name] = value
    return result


def _snapshot(current):
    result = {}
    for name, (_, bits, _) in LAYOUT.items():
        if name not in current:
            raise DltLabelError('Missing current classic DLT display parameter: ' + name)
        values = _values(current[name], name)
        if len(values) != 1 or type(values[0]) is not int or not 0 <= values[0] < (1 << bits):
            raise DltLabelError('Invalid current classic DLT display parameter: ' + name)
        result[name] = values
    return result


def _raw(values):
    return sum(values[name][0] << bit for name, (bit, _, _) in LAYOUT.items())


def _view(values):
    return {'indicator_mode': MODES[min(values['IndicatorMode'][0], 2)],
            'invert_display': bool(values['InvertDisplay'][0]),
            'show_clock': not bool(values['HideClock'][0])}


@dataclass(frozen=True)
class DltDisplayPlan:
    unit_type: str
    identity: tuple | None
    expected: dict
    changes: dict
    settings: dict

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))
        object.__setattr__(self, 'settings', MappingProxyType(dict(self.settings)))
        if self.identity is not None:
            object.__setattr__(self, 'identity', tuple(self.identity))

    def as_dict(self):
        after = {**self.expected, **self.changes}
        before_raw, after_raw = _raw(self.expected), _raw(after)
        return {'format': FORMAT, 'unit_type': self.unit_type,
                'firmware': None if self.identity is None else self.identity[1],
                'catalog_number': None if self.identity is None else self.identity[2],
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()}, 'requested': dict(self.settings),
                'before': _view(self.expected), 'after': _view(after),
                'raw_preview': {'address': ADDRESS, 'known_mask': KNOWN_MASK,
                                'unmodeled_mask': 0x80, 'known_before': before_raw,
                                'known_after': after_raw, 'changed_mask': before_raw ^ after_raw,
                                'owned_mask': sum(CONTROLS[key][1] for key in self.settings)},
                'saved': False, 'device_verified': False, 'labels_transferred': False,
                'raw_verification_scope': 'staged-pp-session-before-save',
                'original_full_form_save_executed': False}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise DltLabelError('Expected a ' + FORMAT + ' document')
        try:
            for name in ('expected', 'changes'):
                if not isinstance(data[name], dict) or any(type(value) is not int for values in data[name].values() for value in values):
                    raise ValueError('Display PP values must be exact integers')
            unit_type = data['unit_type']
            firmware, catalogue = data.get('firmware'), data.get('catalog_number')
            if firmware is None and catalogue is not None:
                raise ValueError('A catalogue requires firmware identity')
            identity = None if firmware is None else (unit_type, firmware, catalogue)
            plan = cls(unit_type, identity, data['expected'], data['changes'], _settings(data['requested']))
            # JSON identity is type-sensitive; Python equality aliases false/0
            # and integer/float values even in derived preview/evidence fields.
            if json.dumps(data, sort_keys=True) != json.dumps(plan.as_dict(), sort_keys=True):
                raise ValueError('Serialized display plan is not canonical')
            return plan
        except (KeyError, TypeError, AttributeError, ValueError, IndexError) as error:
            raise DltLabelError('Invalid classic DLT display plan: ' + str(error)) from error


class ClassicDltDisplay(ClassicDltLabels):
    def __init__(self, spec, unit_type):
        super().__init__(spec, unit_type)
        for name, (bit, bits, kind) in LAYOUT.items():
            try:
                layout = self.codec.layout(name)
            except Exception as error:
                raise DltLabelError('Missing classic DLT display layout: ' + name) from error
            actual = (layout.address, layout.array_size, layout.bit_address, layout.bit_size,
                      layout.array_skip, layout.parameter.type)
            if actual != (ADDRESS, 1, bit, bits, 0, kind):
                raise DltLabelError('Unsupported classic DLT display layout: ' + name)

    def _verify_session(self, session, *, fields=FIELDS):
        return super()._verify_session(session, fields=fields)

    def snapshot(self, current):
        return _snapshot(current)

    def show(self, current, identity=None):
        if identity is not None:
            identity = self.check_identity(*identity)
        values = self.snapshot(current)
        return {'format': VIEW_FORMAT, 'unit_type': self.unit_type,
                'firmware': None if identity is None else identity[1],
                'catalog_number': None if identity is None else identity[2],
                'controls': _view(values), 'raw_parameters': {k: list(v) for k, v in values.items()},
                'address': ADDRESS, 'known_raw_byte': _raw(values), 'known_mask': KNOWN_MASK,
                'unmodeled_mask': 0x80, 'device_verified': False, 'labels_transferred': False,
                'raw_projection_scope': 'named-pp-fields',
                'original_full_form_save_executed': False}

    def plan(self, current, *, settings, identity=None):
        settings = _settings(settings)
        if identity is not None:
            identity = self.check_identity(*identity)
        expected, changes = self.snapshot(current), {}
        for key, value in settings.items():
            field, _ = CONTROLS[key]
            desired = (MODES.index(value) if key == 'indicator_mode' else int(not value) if key == 'show_clock' else int(value),)
            if desired != expected[field]:
                changes[field] = desired
        return DltDisplayPlan(self.unit_type, identity, expected, changes, settings)

    @staticmethod
    def _raw_display(session):
        if not hasattr(session, 'get_raw_data'):
            return None
        line = session.get_raw_data(ADDRESS, 1).lines[-1]
        if 'RawData=' not in line:
            raise DltLabelError('Native display raw readback did not return RawData')
        raw = bytes.fromhex(line.split('RawData=', 1)[1].strip())
        if len(raw) != 1:
            raise DltLabelError('Native display raw readback must contain one byte')
        return raw[0]

    def apply(self, session, plan):
        if (type(plan) is not DltDisplayPlan or plan.unit_type != self.unit_type
                or set(plan.expected) != set(FIELDS)
                or set(plan.changes) - {value[0] for value in CONTROLS.values()}):
            raise DltLabelError('Plan contains fields outside the classic DLT display controls')
        if any(type(v) is not int for values in (*plan.expected.values(), *plan.changes.values()) for v in values):
            raise DltLabelError('Display PP values must be exact integers')
        canonical = self.plan(plan.expected, settings=dict(plan.settings), identity=plan.identity)
        if canonical != plan:
            raise DltLabelError('Classic DLT display plan differs from its requested controls')
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity != identity:
            raise DltLabelError('Plan was created for another unit identity')
        self._verify_session(session, fields=FIELDS)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise DltLabelError('PP parameters changed since the DLT display plan was created')
        before_raw = self._raw_display(session)
        if before_raw is not None and before_raw & KNOWN_MASK != _raw(plan.expected):
            raise DltLabelError('Native display raw bits disagree with PP values')
        expected = {**plan.expected, **plan.changes}
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            if self.snapshot(session.values()) != expected:
                raise DltLabelError('Native DLT display readback differs from the plan')
            after_raw = self._raw_display(session)
            mask = sum(CONTROLS[key][1] for key in plan.settings)
            if before_raw is not None and after_raw != ((before_raw & ~mask) | (_raw(expected) & mask)):
                raise DltLabelError('Native DLT display changed unrelated bits or differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            raise DltLabelApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True,
                'raw_bytes_verified': after_raw is not None,
                'display_raw_before': before_raw, 'display_raw_after': after_raw}

    def configure(self, session, *, settings):
        identity = self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), settings=settings, identity=identity))
