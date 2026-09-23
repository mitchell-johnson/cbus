"""Original eDLT unit-wide font, icon, timer-flash and level-wrap settings."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render
from .edlt_mra import MRAPropagation, normalize_mra_globals


@dataclass(frozen=True)
class DisplaySettingsPlan:
    font_style: int
    big_icons: bool
    timer_flash: bool
    fan_level_wrap: bool
    expected: Mapping
    changes: Mapping
    options: Mapping
    mra_propagation: MRAPropagation

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-display-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'large_text': 'status' if self.font_style == 2 else 'label',
                'font_style': self.font_style, 'font_style_ui_canonical': self.font_style in (1, 2),
                'big_icons': self.big_icons, 'timer_flash': self.timer_flash,
                'fan_level_wrap': self.fan_level_wrap, 'applies_to_whole_unit': True,
                'mra_propagation': self.mra_propagation.as_dict(),
                'normalization_changes': {name: list(value) for name, value in self.changes.items()
                                          if name.startswith('Widget') and name != 'WidgetsCRC'},
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False}


class EdltDisplaySettings:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        for name, shape in {'FontStyle': (0x118, 'int', 0, 3), 'UseBigIcon': (0x118, 'bit', 4, 1),
                            'EnableTimerFlash': (0x116, 'bit', 2, 1),
                            'EnableFanControlLevelWrap': (0x117, 'bit', 5, 1)}.items():
            try:
                layout = self.codec.layout(name)
            except (ValueError, KeyError) as error:
                raise EdltError('Unsupported display settings layout: ' + name) from error
            if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size) != shape or (
                    layout.array_size, layout.array_skip) != (1, 0):
                raise EdltError('Unsupported display settings layout: ' + name)

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, large_text=None, big_icons=None, timer_flash=None, fan_level_wrap=None):
        options = dict(large_text=large_text, big_icons=big_icons, timer_flash=timer_flash, fan_level_wrap=fan_level_wrap)
        if large_text is not None and (not isinstance(large_text, str) or large_text not in ('label', 'status')):
            raise EdltError('large_text must be label or status')
        for name in ('big_icons', 'timer_flash', 'fan_level_wrap'):
            if options[name] is not None and type(options[name]) is not bool:
                raise EdltError(name + ' must be boolean')
        original = self.snapshot(current)
        self.common.static_references(original)
        updates = dict(original)
        if large_text is not None:
            updates['FontStyle'] = (2 if large_text == 'status' else 1,)
        for name, field in (('big_icons', 'UseBigIcon'), ('timer_flash', 'EnableTimerFlash'),
                            ('fan_level_wrap', 'EnableFanControlLevelWrap')):
            if options[name] is not None:
                updates[field] = (int(options[name]),)
        font = _int(updates['FontStyle'][0], 'Font style', 0, 7)
        flags = [bool(_int(updates[name][0], name, 0, 1)) for name in
                 ('UseBigIcon', 'EnableTimerFlash', 'EnableFanControlLevelWrap')]
        # Save-hook normalization is independent of the chosen global fields.
        # Re-place an unchanged standby record to preserve all widget bytes.
        mra = normalize_mra_globals(updates, _preserve_stored_multiplexer=True,
                                    _preserve_stored_placement=True)
        updates = self.common._place_record(updates, 1, bytes(updates[_field(1, index)][0] for index in range(32)))
        updates.update(mra.changes)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return DisplaySettingsPlan(font, *flags, original, changes, options, mra)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                    'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted),
                    'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_display_evidence = evidence

    def apply(self, session, plan):
        if not isinstance(plan, DisplaySettingsPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a display plan returned by EdltDisplaySettings.plan')
        _int(plan.font_style, 'Plan font style', 0, 7)
        if any(type(value) is not bool for value in (plan.big_icons, plan.timer_flash, plan.fan_level_wrap)):
            raise EdltError('Plan display flags must be boolean')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid display plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated display settings')
        expected = {**plan.expected, **plan.changes}
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the display plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the display plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted)
            raise
        except Exception as error:
            rollback_errors = []
            try:
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
            except (KeyboardInterrupt, SystemExit) as interrupted:
                self._interrupted(interrupted, plan, attempted, error)
                interrupted.edlt_display_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
