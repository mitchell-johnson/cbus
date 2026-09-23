"""Original eDLT key timing, status-report, tools-page and restore-mode settings."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render
from .edlt_mra import MRAPropagation, normalize_mra_globals


@dataclass(frozen=True)
class GeneralSettingsPlan:
    long_press_ms: int
    debounce_ms: int
    status_report_seconds: int
    tools_page_locked: bool
    power_restore: str
    expected: Mapping
    changes: Mapping
    options: Mapping
    mra_propagation: MRAPropagation

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-general-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'long_press_ms': self.long_press_ms, 'debounce_ms': self.debounce_ms,
                'status_report_seconds': self.status_report_seconds,
                'long_press_ui_canonical': self.long_press_ms >= 25,
                'status_report_ui_canonical': self.status_report_seconds >= 3,
                'tools_page_locked': self.tools_page_locked, 'power_restore': self.power_restore,
                'applies_to_whole_unit': True, 'mra_propagation': self.mra_propagation.as_dict(),
                'normalization_changes': {name: list(value) for name, value in self.changes.items()
                                          if name.startswith('Widget') and name != 'WidgetsCRC'},
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False, 'power_cycle_verified': False}


class EdltGeneralSettings:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        for name, shape in {'LongPressTime': (0x114, 'int', 0, 8), 'DebounceTime': (0x115, 'int', 0, 8),
                            'StatusRequestInterval': (0x112, 'int', 0, 8),
                            'ToolsPageLocked': (0x11a, 'bit', 4, 1),
                            'EnableLevelStore': (0x116, 'bit', 1, 1)}.items():
            try:
                layout = self.codec.layout(name)
            except (ValueError, KeyError) as error:
                raise EdltError('Unsupported general settings layout: ' + name) from error
            if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size) != shape or (
                    layout.array_size, layout.array_skip) != (1, 0):
                raise EdltError('Unsupported general settings layout: ' + name)

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, long_press_ms=None, debounce_ms=None, status_report_seconds=None,
             tools_page_locked=None, power_restore=None):
        options = dict(long_press_ms=long_press_ms, debounce_ms=debounce_ms, status_report_seconds=status_report_seconds,
                       tools_page_locked=tools_page_locked, power_restore=power_restore)
        for name, low in (('long_press_ms', 25), ('debounce_ms', 0)):
            if options[name] is not None:
                _int(options[name], name, low, 6375)
                if options[name] % 25:
                    raise EdltError(name + ' must be a multiple of25 milliseconds')
        if status_report_seconds is not None:
            _int(status_report_seconds, 'Status report seconds', 3, 255)
        if tools_page_locked is not None and type(tools_page_locked) is not bool:
            raise EdltError('tools_page_locked must be boolean')
        if power_restore is not None and (not isinstance(power_restore, str) or power_restore not in ('previous', 'preset')):
            raise EdltError('power_restore must be previous or preset')
        original = self.snapshot(current); self.common.static_references(original)
        updates = dict(original)
        for name, value in (('LongPressTime', None if long_press_ms is None else long_press_ms // 25),
                            ('DebounceTime', None if debounce_ms is None else debounce_ms // 25),
                            ('StatusRequestInterval', status_report_seconds),
                            ('ToolsPageLocked', None if tools_page_locked is None else int(tools_page_locked)),
                            ('EnableLevelStore', None if power_restore is None else int(power_restore == 'previous'))):
            if value is not None:
                updates[name] = (value,)
        long_press, debounce, interval = [_int(updates[name][0], name) for name in
                                         ('LongPressTime', 'DebounceTime', 'StatusRequestInterval')]
        locked, store = [_int(updates[name][0], name, 0, 1) for name in ('ToolsPageLocked', 'EnableLevelStore')]
        mra = normalize_mra_globals(updates, _preserve_stored_multiplexer=True, _preserve_stored_placement=True)
        updates = self.common._place_record(updates, 1, bytes(updates[_field(1, index)][0] for index in range(32)))
        updates.update(mra.changes)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return GeneralSettingsPlan(long_press * 25, debounce * 25, interval, bool(locked), 'previous' if store else 'preset',
                                   original, changes, options, mra)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                    'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_general_evidence = evidence

    def apply(self, session, plan):
        if not isinstance(plan, GeneralSettingsPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a general plan returned by EdltGeneralSettings.plan')
        for name, high in (('long_press_ms', 6375), ('debounce_ms', 6375), ('status_report_seconds', 255)):
            _int(getattr(plan, name), 'Plan ' + name, 0, high)
        if type(plan.tools_page_locked) is not bool:
            raise EdltError('Plan tools_page_locked must be boolean')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid general plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated general settings')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the general plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the general plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted); raise
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
                interrupted.edlt_general_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
