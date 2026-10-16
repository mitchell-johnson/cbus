"""Ordered, source-pinned DIN slider callbacks over a loaded settings snapshot.

This is a bounded explicit-control profile, not complete GUI initialization.
The old targeted editor and its agent-save projection retain their own formats.
"""
from dataclasses import dataclass, replace
from fractions import Fraction
import json
from types import MappingProxyType

from .din_output_settings import (
    DinPlan, DinSettingsError, LOGIC_ASSOCIATIONS, LOGIC_GROUP_INDEX,
    _flag, _integer, _strict_plan_values, level_to_percent, percent_to_level,
)


CONTROL_PLAN_FORMAT = 'cbus-din-output-controls-plan-v1'
# Exact little-endian x87 extended literal at 0xef76ec, not the inverse of
# the display's ten-second scale. All admitted stagger products avoid a ceil tie.
DELAY_STAGGER_SCALE = Fraction(14316875997505920657, 147573952589676412928)
INITIALIZATION = 'snapshot-derived-slider-positions; implicit-binding-callbacks-excluded'


def _freeze(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (dict, MappingProxyType)) and all(type(key) is str for key in value):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    raise DinSettingsError('DIN controls metadata must contain strict JSON integers, booleans and strings')


def _thaw(value):
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _canonical(value):
    return json.dumps(_thaw(_freeze(value)), sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class DinControlPlan:
    settings_plan: DinPlan
    operations: tuple
    initial_controls: dict
    final_controls: dict
    control_history: tuple

    def __post_init__(self):
        if not isinstance(self.settings_plan, DinPlan):
            raise DinSettingsError('DIN controls require a settings plan')
        for name in ('operations', 'initial_controls', 'final_controls', 'control_history'):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    @property
    def expected(self):
        return self.settings_plan.expected

    @property
    def changes(self):
        return self.settings_plan.changes

    @property
    def unit_type(self):
        return self.settings_plan.unit_type

    @property
    def identity(self):
        return self.settings_plan.identity

    @property
    def toolkit_save(self):
        return self.settings_plan.toolkit_save

    def as_dict(self):
        settings = self.settings_plan.as_dict()
        return {
            'format': CONTROL_PLAN_FORMAT,
            **{name: settings[name] for name in (
                'unit_type', 'firmware', 'catalog_number', 'expected', 'changes',
                'saved', 'device_verified')},
            'toolkit_save': self.toolkit_save,
            'initialization': INITIALIZATION,
            'operations': _thaw(self.operations),
            'initial_controls': _thaw(self.initial_controls),
            'final_controls': _thaw(self.final_controls),
            'control_history': _thaw(self.control_history),
            'settings_plan': settings,
        }

    @classmethod
    def from_dict(cls, document):
        if not isinstance(document, dict) or document.get('format') != CONTROL_PLAN_FORMAT:
            raise DinSettingsError('Expected a DIN output controls plan document')
        try:
            settings = DinPlan.from_dict(document['settings_plan'])
            for field in ('expected', 'changes'):
                _strict_plan_values(getattr(settings, field), settings.unit_type, field,
                                    complete=field == 'expected')
            result = cls(settings, document['operations'], document['initial_controls'],
                         document['final_controls'], document['control_history'])
        except (KeyError, TypeError, AttributeError) as error:
            raise DinSettingsError('Incomplete DIN output controls plan') from error
        if _canonical(document) != _canonical(result.as_dict()):
            raise DinSettingsError('DIN controls plan summaries or metadata are not canonical')
        return result


def _operations(operations, profile):
    if not isinstance(operations, (list, tuple)) or not operations:
        raise DinSettingsError('DIN controls must be a nonempty ordered JSON array')
    result = []
    schemas = {
        'synchronise': {'op', 'tab', 'enabled'},
        'minimum': {'op', 'channel', 'percent'},
        'maximum': {'op', 'channel', 'percent'},
        'recovery-delay': {'op', 'channel', 'raw'},
        'stagger-minimum': {'op', 'step_percent'},
        'stagger-maximum': {'op', 'step_percent'},
        'stagger-turn-on': {'op', 'step_percent'},
        'stagger-recovery-delay': {'op', 'step_seconds'},
    }
    for ordinal, operation in enumerate(operations, 1):
        if not isinstance(operation, (dict, MappingProxyType)):
            raise DinSettingsError(f'DIN control operation {ordinal} must be an object')
        row = dict(operation)
        op = row.get('op')
        if not isinstance(op, str) or op not in schemas or set(row) != schemas[op]:
            raise DinSettingsError(f'DIN control operation {ordinal} has unsupported keys or operation')
        if profile.relay and op in ('maximum', 'recovery-delay', 'stagger-minimum',
                                    'stagger-maximum', 'stagger-recovery-delay'):
            raise DinSettingsError(f'Toolkit hides {op} for relay profiles')
        if not profile.relay and op == 'stagger-turn-on':
            raise DinSettingsError('Stagger turn-on is the relay control; use stagger-maximum for dimmers')
        if op == 'synchronise':
            if row['tab'] not in ('turn-on', 'recovery'):
                raise DinSettingsError('Synchronise tab must be turn-on or recovery')
            _flag(row['enabled'], 'Synchronise enabled')
        if 'channel' in row:
            _integer(row['channel'], 'Channel', 1, profile.channels)
        if 'percent' in row:
            _integer(row['percent'], 'Slider percent', 0, 100)
        if 'step_percent' in row:
            _integer(row['step_percent'], 'Stagger percent', 1, 100 // profile.channels)
        if 'raw' in row:
            _integer(row['raw'], 'Recovery delay', 5, 255)
        if 'step_seconds' in row:
            _integer(row['step_seconds'], 'Stagger seconds', 5, 30)
            if row['step_seconds'] not in (5, 10, 20, 30):
                raise DinSettingsError('Toolkit stagger delay choices are 5, 10, 20 or 30 seconds')
        result.append(row)
    return result


class _Controls:
    def __init__(self, editor, expected):
        self.profile = editor.profile
        self.values = {name: list(row) for name, row in expected.items()}
        self.sync = {'turn-on': False, 'recovery': False}
        self.guard = [False] * self.profile.channels
        self.positions = {
            'minimum': [level_to_percent(expected['MinDimmingLevel'][i]) for i in self.profile.indices],
        }
        if not self.profile.relay:
            self.positions.update(
                maximum=[level_to_percent(expected['MaxDimmingLevel'][i]) for i in self.profile.indices],
                **{'recovery-delay': [max(5, expected['PowerUpDelay'][i]) for i in self.profile.indices]})
        self.events = []

    def state(self):
        return {'synchronise': dict(self.sync),
                'positions': {key: list(row) for key, row in self.positions.items()}}

    def write(self, channel, slider):
        name = {'minimum': 'MinDimmingLevel', 'maximum': 'MaxDimmingLevel',
                'recovery-delay': 'PowerUpDelay'}[slider]
        position = self.positions[slider][channel]
        value = position if slider == 'recovery-delay' else percent_to_level(position)
        index = self.profile.indices[channel]
        before = self.values[name][index]
        self.values[name][index] = value
        self.events.append({'event': 'parameter-write', 'channel': channel + 1,
                            'parameter': name, 'pp_index': index, 'before': before, 'value': value})

    def setter(self, channel, slider, value):
        # SetMin/SetMax +0x2d8 and SetDelayValue +0x2f2 suppress parent callbacks.
        if self.guard[channel]:
            self.events.append({'event': 'guarded-setter', 'channel': channel + 1, 'slider': slider})
            return
        self.guard[channel] = True
        try:
            self.position(channel, slider, value)
        finally:
            self.guard[channel] = False

    def propagate(self, channel, slider):
        tab = 'recovery' if slider == 'recovery-delay' else 'turn-on'
        if self.guard[channel] or not self.sync[tab]:
            return
        # TurnOn callbacks hold the source guard while calling their parent.
        # RecoveryDelay's handler does not; its same-position SetDelayValue is
        # still harmless and suppresses nested parent notifications.
        hold = slider != 'recovery-delay'
        if hold:
            self.guard[channel] = True
        try:
            value = self.positions[slider][channel]
            self.events.append({'event': 'synchronise', 'channel': channel + 1,
                                'slider': slider, 'value': value})
            for target in range(self.profile.channels):
                self.setter(target, slider, value)
        finally:
            if hold:
                self.guard[channel] = False

    def position(self, channel, slider, value):
        minimum, maximum = (5, 255) if slider == 'recovery-delay' else (0, 100)
        value = max(minimum, min(value, maximum))
        before = self.positions[slider][channel]
        if value == before:
            self.events.append({'event': 'same-position', 'channel': channel + 1,
                                'slider': slider, 'value': value})
            return
        self.positions[slider][channel] = value
        self.events.append({'event': 'position', 'channel': channel + 1,
                            'slider': slider, 'before': before, 'value': value})
        if slider == 'recovery-delay':
            # trkRecoveryDelayPropertiesChange invokes the parent before Changed.
            self.propagate(channel, slider)
            self.write(channel, slider)
            return
        # Both TurnOn handlers commit through Properties.Changed before coupling.
        self.write(channel, slider)
        if not self.profile.relay:
            if slider == 'minimum' and self.positions['maximum'][channel] <= value:
                self.position(channel, 'maximum', value + 1)
            elif slider == 'maximum' and self.positions['minimum'][channel] >= value:
                self.position(channel, 'minimum', value - 1)
        self.propagate(channel, slider)

    def run(self, row):
        self.events = []
        op = row['op']
        if op == 'synchronise':
            self.sync[row['tab']] = row['enabled']
            self.events.append({'event': 'synchronise-checkbox', 'tab': row['tab'],
                                'enabled': row['enabled']})
        elif op in ('minimum', 'maximum', 'recovery-delay'):
            self.position(row['channel'] - 1, op, row.get('percent', row.get('raw')))
        else:
            delay = op == 'stagger-recovery-delay'
            tab = 'recovery' if delay else 'turn-on'
            self.sync[tab] = False
            self.events.append({'event': 'synchronise-checkbox', 'tab': tab, 'enabled': False})
            slider = ('recovery-delay' if delay else 'maximum' if op == 'stagger-maximum' else 'minimum')
            for channel in range(self.profile.channels):
                if delay:
                    seconds = (channel + 1) * row['step_seconds']
                    scaled = (seconds - 60) * DELAY_STAGGER_SCALE
                    value = seconds if seconds < 60 else 60 - (-scaled.numerator // scaled.denominator)
                elif op == 'stagger-maximum':
                    value = 100 - row['step_percent'] * (self.profile.channels - channel - 1)
                else:
                    value = row['step_percent'] * (channel + 1)
                self.setter(channel, slider, value)
            # BtnStaggerMaxClick forces the last slider to100 at the last
            # combo choice, including relay thresholds (e.g.8*12=96 ->100).
            if (op in ('stagger-maximum', 'stagger-turn-on')
                    and row['step_percent'] == 100 // self.profile.channels):
                self.setter(self.profile.channels - 1, slider, 100)
        return {'operation': dict(row), 'events': list(self.events), 'controls': self.state()}


def control_plan(editor, current, operations, *, identity=None, toolkit_save=False):
    _flag(toolkit_save, 'toolkit_save')
    operations = _operations(operations, editor.profile)
    baseline = editor.plan(current, identity=identity)
    expected = _strict_plan_values(baseline.expected, editor.unit_type, 'expected', complete=True)
    if any(row['op'] in ('recovery-delay', 'stagger-recovery-delay') for row in operations):
        if any(expected['PowerUpDelay'][index] < 5 for index in editor.profile.indices):
            raise DinSettingsError('Recovery delay history requires stored delays in 5..255; initial clamp callbacks are not admitted')
    controls = _Controls(editor, expected)
    initial = controls.state()
    history = [controls.run(row) for row in operations]
    before_save = controls.values
    final = editor._toolkit_save(before_save) if toolkit_save else before_save
    for group, name in enumerate(LOGIC_ASSOCIATIONS):
        if final['GroupAddress'][LOGIC_GROUP_INDEX + group] == 255 and any(
                final[name][index] for index in editor.profile.indices):
            raise DinSettingsError(f'Logic group {group + 1} is associated with a channel but has no group address')
    changes = editor._difference(expected, final)
    editor.codec.encode_many(changes)
    settings = DinPlan(editor.unit_type, None, None, expected, changes, (), baseline.identity,
                       toolkit_save, editor._difference(expected, before_save) if toolkit_save else None,
                       editor._difference(before_save, final) if toolkit_save else None)
    return DinControlPlan(settings, tuple(operations), initial, controls.state(), tuple(history))


def apply_controls(editor, session, plan):
    if not isinstance(plan, DinControlPlan) or plan.unit_type != editor.unit_type:
        raise DinSettingsError('DIN controls plan belongs to another profile')
    # Strict serialization and full deterministic replay precede every PP call.
    imported = DinControlPlan.from_dict(plan.as_dict())
    replayed = control_plan(editor, imported.expected, imported.operations,
                            identity=imported.identity, toolkit_save=imported.toolkit_save)
    if _canonical(imported.as_dict()) != _canonical(replayed.as_dict()):
        raise DinSettingsError('DIN controls plan differs from its ordered control history')
    result = editor.apply(session, replayed.settings_plan, _strict_width=True)
    identity = (result['unit_type'], result['firmware'], result['catalog_number'])
    return {**replace(replayed, settings_plan=replace(replayed.settings_plan, identity=identity)).as_dict(),
            'verified': True}
