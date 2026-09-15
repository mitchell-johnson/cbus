"""Original eDLT Quick Status model and linked threshold-control semantics."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render
from .edlt_colours import KEY_COLOURS, SCREEN_COLOURS
from .edlt_mra import MRAPropagation, normalize_mra_globals

MODES = ('off', 'page-key', 'background', 'text')
FIELDS = MappingProxyType({'mode': 'QuickStatusMode', 'group': 'QuickStatusGroup',
    'low_colour': 'QuickStatusColour1', 'middle_colour': 'QuickStatusColour2', 'high_colour': 'QuickStatusColour3',
    'low_threshold': 'QuickStatusLevel1', 'high_threshold': 'QuickStatusLevel2'})


def _levels(low, high, requested_low, requested_high):
    """LevelControl.SetValue: early return precedes clamping; low is edited first."""
    values = [low, high]
    def set_value(which, requested, from_other=False):
        previous = values[which]
        if previous == requested:
            return
        value = min(254 if which == 0 else 255, max(0 if which == 0 else 1, requested))
        other = None
        if not from_other:
            if values[1 - which] == previous:
                other = value
            elif which == 0 and values[1] <= value:
                other = value + 1
            elif which == 1 and values[0] >= value:
                other = value - 1
        values[which] = value
        if other is not None and other > -1:
            set_value(1 - which, other, True)
    if requested_low is not None:
        set_value(0, requested_low)
    if requested_high is not None:
        set_value(1, requested_high)
    return tuple(values)


@dataclass(frozen=True)
class QuickStatusPlan:
    values: Mapping
    primary_application: int
    expected: Mapping
    changes: Mapping
    options: Mapping
    mra_propagation: MRAPropagation

    def __post_init__(self):
        for name in ('values', 'expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        values = dict(self.values); mode = values['mode']; palette = SCREEN_COLOURS if mode > 1 else KEY_COLOURS
        canonical = {name: values[name] < len(palette) for name in ('low_colour', 'middle_colour', 'high_colour')}
        displayed = {name: palette[values[name]] if canonical[name] else None for name in canonical}
        low, high = values['low_threshold'], values['high_threshold']
        return {'format': 'cbus-edlt-quick-status-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                **values, **displayed, 'mode': MODES[mode] if mode < len(MODES) else None,
                'raw_values': values, 'mode_ui_canonical': mode < len(MODES),
                'colour_palette': list(palette), 'colour_ui_canonical': canonical,
                'enabled': mode != 0, 'mode_selector_enabled': mode != 0,
                'group_and_threshold_controls_editable': True, 'colour_controls_editable': True,
                'threshold_edit_order': ['low_threshold', 'high_threshold'],
                'thresholds_strictly_ordered': low < high,
                'threshold_controls_ui_canonical': low <= 254 and high >= 1,
                'threshold_adjustments': {name: {'requested': self.options[name], 'effective': values[name]}
                    for name in ('low_threshold', 'high_threshold')
                    if self.options[name] is not None and self.options[name] != values[name]},
                'primary_application': self.primary_application,
                'group_metadata_verified': False, 'database_group_created': False,
                'group_resolution': 'unverified', 'group_is_selectable_address': values['group'] != 255,
                'omitted_colours_preserved_by_model': True, 'windows_palette_transition_verified': False,
                'applies_to_whole_unit': True, 'mra_propagation': self.mra_propagation.as_dict(),
                'normalization_changes': {name: list(value) for name, value in self.changes.items()
                    if name.startswith('Widget') and name != 'WidgetsCRC'},
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False}


class EdltQuickStatus:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        shapes = {'QuickStatusMode': (0x116, 3, 3)}
        shapes.update({field: (address, 0, 8) for field, address in (
            ('QuickStatusGroup', 0x125), ('QuickStatusColour1', 0x126), ('QuickStatusColour2', 0x127),
            ('QuickStatusColour3', 0x128), ('QuickStatusLevel1', 0x129), ('QuickStatusLevel2', 0x12a))})
        for name, (address, bit, size) in shapes.items():
            try:
                layout = self.codec.layout(name)
            except (ValueError, KeyError) as error:
                raise EdltError('Unsupported Quick Status layout: ' + name) from error
            if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size,
                    layout.array_size, layout.array_skip) != (address, 'int', bit, size, 1, 0):
                raise EdltError('Unsupported Quick Status layout: ' + name)

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, mode=None, group=None, low_threshold=None, high_threshold=None,
             low_colour=None, middle_colour=None, high_colour=None):
        options = dict(mode=mode, group=group, low_threshold=low_threshold, high_threshold=high_threshold,
                       low_colour=low_colour, middle_colour=middle_colour, high_colour=high_colour)
        if mode is not None and (not isinstance(mode, str) or mode not in MODES):
            raise EdltError('mode must be one of ' + ', '.join(MODES))
        for name, upper in (('group', 254), ('low_threshold', 255), ('high_threshold', 255)):
            if options[name] is not None:
                _int(options[name], name, 0, upper)
        original = self.snapshot(current); self.common.static_references(original)
        values = {name: _int(original[field][0], field, 0, 7 if name == 'mode' else 255)
                  for name, field in FIELDS.items()}
        if mode is not None:
            values['mode'] = MODES.index(mode)
        palette = SCREEN_COLOURS if values['mode'] > 1 else KEY_COLOURS
        for name in ('low_colour', 'middle_colour', 'high_colour'):
            option = options[name]
            if option is not None:
                if not isinstance(option, str) or option not in palette:
                    raise EdltError(name + ' must be one of ' + ', '.join(palette))
                values[name] = palette.index(option)
        if group is not None:
            values['group'] = group
        values['low_threshold'], values['high_threshold'] = _levels(values['low_threshold'], values['high_threshold'],
                                                                    low_threshold, high_threshold)
        updates = {**original, **{field: (values[name],) for name, field in FIELDS.items()}}
        primary = _int(original['PrimaryApplication'][0], 'PrimaryApplication', 0, 255)
        mra = normalize_mra_globals(updates, _preserve_stored_multiplexer=True, _preserve_stored_placement=True)
        updates = self.common._place_record(updates, 1, bytes(updates[_field(1, index)][0] for index in range(32)))
        updates.update(mra.changes)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return QuickStatusPlan(values, primary, original, changes, options, mra)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                    'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_quick_status_evidence = evidence

    def apply(self, session, plan):
        if not isinstance(plan, QuickStatusPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a Quick Status plan returned by EdltQuickStatus.plan')
        if set(plan.values) != set(FIELDS):
            raise EdltError('Invalid Quick Status plan values')
        for name, value in plan.values.items():
            _int(value, 'Plan ' + name, 0, 7 if name == 'mode' else 255)
        _int(plan.primary_application, 'Plan primary_application', 0, 255)
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid Quick Status plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated Quick Status settings')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the Quick Status plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the Quick Status plan')
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
                interrupted.edlt_quick_status_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
