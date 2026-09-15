"""Original eDLT wake settings with explicit numeric event references."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render
from .edlt_mra import MRAPropagation, normalize_mra_globals

WAKE_MODES = MappingProxyType({'key-press': 0, 'wake-unit': 1, 'primary-event': 2, 'trigger-event': 3})
ACTIVATION_PAGES = MappingProxyType({'last-active': 0, 'page-1': 1})
FIELDS = MappingProxyType({'wake_mode': 'ProximityMode', 'group': 'ProximityGroup',
                          'level': 'ProximityLevel', 'action': 'ProximityLevel',
                          'activation_page': 'DeafultPage', 'ignore_first_key_press': 'IgnoreFirstKeyPress'})


def _reference_application(mode, primary):
    return 202 if mode == 3 else primary if mode in (0, 1, 2) else None


@dataclass(frozen=True)
class ActivationPlan:
    mode: int
    group: int
    event_value: int
    page: int
    ignore_first_key_press: bool
    primary_application: int
    activity_duration: int
    timeout_page: int
    editable: Mapping
    expected: Mapping
    changes: Mapping
    options: Mapping
    mra_propagation: MRAPropagation

    def __post_init__(self):
        for name in ('editable', 'expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        application = _reference_application(self.mode, self.primary_application)
        previous = _reference_application(self.expected['ProximityMode'][0], self.primary_application)
        return {'format': 'cbus-edlt-activation-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'wake_mode': next((key for key, value in WAKE_MODES.items() if value == self.mode), None),
                'wake_mode_ui_canonical': self.mode in WAKE_MODES.values(),
                'group': self.group, 'event_value': self.event_value,
                'level': self.event_value if self.mode == 2 else None,
                'action': self.event_value if self.mode == 3 else None,
                'activation_page': next((key for key, value in ACTIVATION_PAGES.items() if value == self.page), None),
                'activation_page_ui_canonical': self.page in ACTIVATION_PAGES.values(),
                'ignore_first_key_press': self.ignore_first_key_press,
                'raw_values': {'ProximityMode': self.mode, 'ProximityGroup': self.group,
                    'ProximityLevel': self.event_value, 'DeafultPage': self.page,
                    'IgnoreFirstKeyPress': int(self.ignore_first_key_press)},
                'primary_application': self.primary_application, 'activity_duration': self.activity_duration,
                'timeout_page': self.timeout_page, 'activation_controls_enabled': self.activity_duration != 0,
                'editable': dict(self.editable), 'reference_application': application,
                'previous_reference_application': previous,
                'reference_application_changed': self.group != 255 and previous != application,
                'event_application': application if self.mode in (2, 3) else None,
                'event_configured': self.mode in (2, 3) and self.group != 255,
                'database_group_created': False, 'database_group_verified': False,
                'database_action_verified': False, 'applies_to_whole_unit': True,
                'mra_propagation': self.mra_propagation.as_dict(),
                'normalization_changes': {name: list(value) for name, value in self.changes.items()
                                          if name.startswith('Widget') and name != 'WidgetsCRC'},
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False, 'wake_event_verified': False}


class EdltActivation:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        for name, shape in {'ProximityMode': (0x117, 'int', 0, 3),
                            'ProximityGroup': (0x123, 'int', 0, 8), 'ProximityLevel': (0x124, 'int', 0, 8),
                            'DeafultPage': (0x11A, 'int', 0, 4), 'IgnoreFirstKeyPress': (0x116, 'bit', 0, 1),
                            'ActivityDuration': (0x11B, 'int', 0, 8), 'TimeoutPage': (0x11A, 'int', 5, 2)}.items():
            try:
                layout = self.codec.layout(name)
            except (ValueError, KeyError) as error:
                raise EdltError('Unsupported activation settings layout: ' + name) from error
            if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size) != shape or (
                    layout.array_size, layout.array_skip) != (1, 0):
                raise EdltError('Unsupported activation settings layout: ' + name)

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, wake_mode=None, group=None, level=None, action=None,
             activation_page=None, ignore_first_key_press=None):
        options = dict(wake_mode=wake_mode, group=group, level=level, action=action,
                       activation_page=activation_page, ignore_first_key_press=ignore_first_key_press)
        for name, choices in (('wake_mode', WAKE_MODES), ('activation_page', ACTIVATION_PAGES)):
            if options[name] is not None and (not isinstance(options[name], str) or options[name] not in choices):
                raise EdltError(name + ' must be one of ' + ', '.join(choices))
        for name in ('group', 'level', 'action'):
            if options[name] is not None:
                _int(options[name], name, 0, 255)
        if level is not None and action is not None:
            raise EdltError('level and action select the same ProximityLevel field and are mutually exclusive')
        if ignore_first_key_press is not None and type(ignore_first_key_press) is not bool:
            raise EdltError('ignore_first_key_press must be boolean')
        original = self.snapshot(current); self.common.static_references(original)
        duration = _int(original['ActivityDuration'][0], 'ActivityDuration', 0, 255)
        timeout = _int(original['TimeoutPage'][0], 'TimeoutPage', 0, 3)
        primary = _int(original['PrimaryApplication'][0], 'PrimaryApplication', 0, 255)
        if not duration and any(value is not None for value in options.values()):
            raise EdltError('Standby must already be enabled before editing activation controls')
        mode = original['ProximityMode'][0] if wake_mode is None else WAKE_MODES[wake_mode]
        _int(mode, 'ProximityMode', 0, 7)
        selected_group = original['ProximityGroup'][0] if group is None else group
        _int(selected_group, 'ProximityGroup', 0, 255)
        editable = {'wake_mode': bool(duration), 'group': bool(duration) and mode in (2, 3),
                    'level': bool(duration) and mode == 2,
                    'action': bool(duration) and mode == 3 and selected_group != 255,
                    'activation_page': bool(duration) and timeout == 2,
                    'ignore_first_key_press': bool(duration) and timeout < 2 and mode == 0}
        for name, value in options.items():
            if value is not None and not editable[name]:
                raise EdltError(name + ' is hidden or disabled for the resulting wake mode, group or existing TimeoutPage')
        updates = dict(original)
        updates['ProximityMode'], updates['ProximityGroup'] = (mode,), (selected_group,)
        if level is not None or action is not None:
            updates['ProximityLevel'] = (level if level is not None else action,)
        if activation_page is not None:
            updates['DeafultPage'] = (ACTIVATION_PAGES[activation_page],)
        if ignore_first_key_press is not None:
            updates['IgnoreFirstKeyPress'] = (int(ignore_first_key_press),)
        value = _int(updates['ProximityLevel'][0], 'ProximityLevel', 0, 255)
        page = _int(updates['DeafultPage'][0], 'DeafultPage', 0, 4)
        ignore = bool(_int(updates['IgnoreFirstKeyPress'][0], 'IgnoreFirstKeyPress', 0, 1))
        mra = normalize_mra_globals(updates, _preserve_stored_multiplexer=True, _preserve_stored_placement=True)
        updates = self.common._place_record(updates, 1, bytes(updates[_field(1, index)][0] for index in range(32)))
        updates.update(mra.changes)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: item for name, item in updates.items() if item != original[name]}
        return ActivationPlan(mode, selected_group, value, page, ignore, primary, duration, timeout,
                              editable, original, changes, options, mra)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False, 'attempted_parameters': list(attempted),
                    'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_activation_evidence = evidence

    def apply(self, session, plan):
        if type(plan) is not ActivationPlan or not isinstance(plan.options, Mapping):
            raise EdltError('Use an activation plan returned by EdltActivation.plan')
        for name, high in (('mode', 7), ('group', 255), ('event_value', 255), ('page', 4),
                           ('primary_application', 255), ('activity_duration', 255), ('timeout_page', 3)):
            _int(getattr(plan, name), 'Plan ' + name, 0, high)
        if type(plan.ignore_first_key_press) is not bool or set(plan.editable) != set(FIELDS) or any(
                type(value) is not bool for value in plan.editable.values()):
            raise EdltError('Plan boolean fields are invalid')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid activation plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated activation settings')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the activation plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the activation plan')
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
                interrupted.edlt_activation_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
