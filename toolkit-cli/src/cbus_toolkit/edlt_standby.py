"""Original eDLT standby timeout, destination and nightlight settings."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render
from .edlt_mra import MRAPropagation, normalize_mra_globals

DESTINATIONS = MappingProxyType({'current': 1, 'page-1': 0, 'standby': 2})
NIGHTLIGHT_COLOURS = MappingProxyType({'off-colour': 0, 'on-colour': 1,
                                     'page-key-colour': 2, 'quick-status-colour': 3})


@dataclass(frozen=True)
class StandbyPlan:
    activity_duration: int
    destination_raw: int
    nightlight_user_keys: bool
    nightlight_page_key: bool
    nightlight_colour: str
    expected: Mapping
    changes: Mapping
    options: Mapping
    mra_propagation: MRAPropagation

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-standby-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'enabled': self.activity_duration != 0, 'after_seconds': self.activity_duration,
                'timeout_page': next((name for name, value in DESTINATIONS.items() if value == self.destination_raw), None),
                'timeout_page_raw': self.destination_raw, 'timeout_page_ui_canonical': self.destination_raw in DESTINATIONS.values(),
                'nightlight_user_keys': self.nightlight_user_keys, 'nightlight_page_key': self.nightlight_page_key,
                'nightlight_colour': self.nightlight_colour,
                'nightlight_colour_control_enabled': self.activity_duration != 0 and (self.nightlight_user_keys or self.nightlight_page_key),
                'applies_to_whole_unit': True, 'mra_propagation': self.mra_propagation.as_dict(),
                'normalization_changes': {name: list(value) for name, value in self.changes.items()
                                          if name.startswith('Widget') and name != 'WidgetsCRC'},
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False}


class EdltStandby:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        for name, shape in {'ActivityDuration': (0x11B, 'int', 0, 8), 'TimeoutPage': (0x11A, 'int', 5, 2),
                            'EnableNightlightUserKey': (0x116, 'bit', 6, 1),
                            'EnableNightlightPageKey': (0x116, 'bit', 7, 1),
                            'NightlightColour': (0x117, 'int', 3, 2)}.items():
            try:
                layout = self.codec.layout(name)
            except (ValueError, KeyError) as error:
                raise EdltError('Unsupported standby layout: ' + name) from error
            if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size) != shape or (
                    layout.array_size, layout.array_skip) != (1, 0):
                raise EdltError('Unsupported standby layout: ' + name)

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, enabled=None, after_seconds=None, destination=None,
             nightlight_user_keys=None, nightlight_page_key=None, nightlight_colour=None):
        options = dict(enabled=enabled, after_seconds=after_seconds, destination=destination,
                       nightlight_user_keys=nightlight_user_keys, nightlight_page_key=nightlight_page_key,
                       nightlight_colour=nightlight_colour)
        for name in ('enabled', 'nightlight_user_keys', 'nightlight_page_key'):
            if options[name] is not None and type(options[name]) is not bool:
                raise EdltError(name + ' must be boolean')
        if after_seconds is not None:
            _int(after_seconds, 'after_seconds', 1, 255)
        for name, choices in (('destination', DESTINATIONS), ('nightlight_colour', NIGHTLIGHT_COLOURS)):
            if options[name] is not None and (not isinstance(options[name], str) or options[name] not in choices):
                raise EdltError(name + ' must be one of ' + ', '.join(choices))
        original = self.snapshot(current)
        self.common.static_references(original)
        updates = dict(original)
        duration = _int(original['ActivityDuration'][0], 'ActivityDuration', 0, 255)
        # The original setter compares its integer argument with the stored
        # duration, then sets 3 when enabling. A stored 1 is left unchanged.
        if enabled is not None and duration != int(enabled):
            duration = 3 if enabled else 0
        dependent = any(options[name] is not None for name in
                        ('after_seconds', 'destination', 'nightlight_user_keys', 'nightlight_page_key', 'nightlight_colour'))
        if not duration and dependent:
            raise EdltError('Standby must be enabled before editing its dependent controls')
        if after_seconds is not None:
            duration = after_seconds
        updates['ActivityDuration'] = (duration,)
        if destination is not None:
            updates['TimeoutPage'] = (DESTINATIONS[destination],)
        for name, field in (('nightlight_user_keys', 'EnableNightlightUserKey'),
                            ('nightlight_page_key', 'EnableNightlightPageKey')):
            if options[name] is not None:
                updates[field] = (int(options[name]),)
        user, page = [bool(_int(updates[name][0], name, 0, 1)) for name in
                      ('EnableNightlightUserKey', 'EnableNightlightPageKey')]
        if nightlight_colour is not None:
            if not (user or page):
                raise EdltError('A nightlight key option must be enabled before editing its colour source')
            updates['NightlightColour'] = (NIGHTLIGHT_COLOURS[nightlight_colour],)
        target = _int(updates['TimeoutPage'][0], 'TimeoutPage', 0, 3)
        colour = _int(updates['NightlightColour'][0], 'NightlightColour', 0, 3)
        colour_name = next(name for name, value in NIGHTLIGHT_COLOURS.items() if value == colour)
        # Exact direct BeforeSavePPData stage, preserving unrelated attributes.
        mra = normalize_mra_globals(updates, _preserve_stored_multiplexer=True,
                                    _preserve_stored_placement=True)
        updates = self.common._place_record(updates, 1, bytes(updates[_field(1, index)][0] for index in range(32)))
        updates.update(mra.changes)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return StandbyPlan(duration, target, user, page, colour_name, original, changes, options, mra)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                    'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted),
                    'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_standby_evidence = evidence

    def apply(self, session, plan):
        if not isinstance(plan, StandbyPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a standby plan returned by EdltStandby.plan')
        _int(plan.activity_duration, 'Plan activity duration', 0, 255)
        _int(plan.destination_raw, 'Plan timeout page', 0, 3)
        if any(type(value) is not bool for value in (plan.nightlight_user_keys, plan.nightlight_page_key)):
            raise EdltError('Plan nightlight flags must be boolean')
        if not isinstance(plan.nightlight_colour, str) or plan.nightlight_colour not in NIGHTLIGHT_COLOURS:
            raise EdltError('Plan nightlight colour is invalid')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid standby plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated standby settings')
        expected = {**plan.expected, **plan.changes}
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the standby plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the standby plan')
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
                interrupted.edlt_standby_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
