"""Original eDLT fixed colours, brightness levels and numeric control groups."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render
from .edlt_mra import MRAPropagation, normalize_mra_globals

SCREEN_COLOURS = ('black', 'white', 'red', 'green', 'blue', 'cyan', 'magenta', 'yellow')
KEY_COLOURS = ('none', 'white', 'red', 'green', 'blue', 'cyan', 'magenta', 'yellow', 'orange')
COLOUR_OPTIONS = MappingProxyType({
    'text_colour': ('LCDForeground', SCREEN_COLOURS),
    'background_colour': ('LCDBackground', SCREEN_COLOURS),
    'indicator_on_colour': ('IndicatorOnColour', KEY_COLOURS),
    'indicator_off_colour': ('IndicatorOffColour', KEY_COLOURS),
    'page_key_colour': ('NavigationIndicatorColour', KEY_COLOURS),
})
BRIGHTNESS_OPTIONS = MappingProxyType({
    'active_screen_brightness': 'ActiveBacklightBrightness',
    'idle_screen_brightness': 'IdleBacklightBrightness',
    'active_indicator_brightness': 'ActiveIndicatorBrightness',
    'idle_indicator_brightness': 'IdleIndicatorBrightness',
})
GROUP_OPTIONS = MappingProxyType({
    'active_screen_group': ('BacklightActiveBrightnessControlGroup', 'active_screen_brightness'),
    'idle_screen_group': ('BacklightIdleBrightnessControlGroup', 'idle_screen_brightness'),
    'active_indicator_group': ('IndicatorActiveBrightnessControlGroup', 'active_indicator_brightness'),
    'idle_indicator_group': ('IndicatorIdleBrightnessControlGroup', 'idle_indicator_brightness'),
    'indicator_on_group': ('IndicatorOnColourControlGroup', 'indicator_on_colour'),
    'indicator_off_group': ('IndicatorOffColourControlGroup', 'indicator_off_colour'),
})
FIELDS = MappingProxyType({**{key: value[0] for key, value in COLOUR_OPTIONS.items()},
                          **BRIGHTNESS_OPTIONS, **{key: value[0] for key, value in GROUP_OPTIONS.items()}})
_IDLE_OPTIONS = frozenset(('idle_screen_brightness', 'idle_indicator_brightness', 'idle_screen_group', 'idle_indicator_group'))


@dataclass(frozen=True)
class ColourSettingsPlan:
    values: Mapping
    editable: Mapping
    primary_application: int
    activity_duration: int
    expected: Mapping
    changes: Mapping
    options: Mapping
    mra_propagation: MRAPropagation

    def __post_init__(self):
        for name in ('values', 'editable', 'expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        values = dict(self.values)
        canonical = {}
        for name, (_, palette) in COLOUR_OPTIONS.items():
            canonical[name] = self.values[name] < len(palette)
            values[name] = palette[self.values[name]] if canonical[name] else None
        return {'format': 'cbus-edlt-colours-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00', **values,
                'raw_values': dict(self.values), 'colour_ui_canonical': canonical,
                'editable': dict(self.editable), 'idle_controls_enabled': self.activity_duration != 0,
                'primary_application': self.primary_application,
                'control_groups': {key: {'application': self.primary_application, 'group': self.values[key],
                    'enabled': self.values[key] != 255} for key in GROUP_OPTIONS},
                'group_metadata_verified': False, 'database_group_created': False,
                'applies_to_whole_unit': True, 'mra_propagation': self.mra_propagation.as_dict(),
                'normalization_changes': {name: list(value) for name, value in self.changes.items()
                                          if name.startswith('Widget') and name != 'WidgetsCRC'},
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False}


class EdltColours:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        shapes = {'LCDForeground': (0x113, 3, 3), 'LCDBackground': (0x113, 0, 3),
                  'ActivityDuration': (0x11B, 0, 8)}
        shapes.update({name: (address, 0, 8) for name, address in (
            ('IndicatorOnColour', 0x11C), ('IndicatorOffColour', 0x11D), ('NavigationIndicatorColour', 0x11E),
            ('IdleIndicatorBrightness', 0x11F), ('IdleBacklightBrightness', 0x120),
            ('ActiveIndicatorBrightness', 0x121), ('ActiveBacklightBrightness', 0x122),
            ('IndicatorOnColourControlGroup', 0x12B), ('IndicatorOffColourControlGroup', 0x12C),
            ('IndicatorIdleBrightnessControlGroup', 0x12D), ('BacklightIdleBrightnessControlGroup', 0x12E),
            ('IndicatorActiveBrightnessControlGroup', 0x12F), ('BacklightActiveBrightnessControlGroup', 0x130))})
        for name, (address, bit, size) in shapes.items():
            try:
                layout = self.codec.layout(name)
            except (ValueError, KeyError) as error:
                raise EdltError('Unsupported colour settings layout: ' + name) from error
            if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size,
                    layout.array_size, layout.array_skip) != (address, 'int', bit, size, 1, 0):
                raise EdltError('Unsupported colour settings layout: ' + name)

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, text_colour=None, background_colour=None, indicator_on_colour=None,
             indicator_off_colour=None, page_key_colour=None, active_screen_brightness=None,
             idle_screen_brightness=None, active_indicator_brightness=None, idle_indicator_brightness=None,
             active_screen_group=None, idle_screen_group=None, active_indicator_group=None,
             idle_indicator_group=None, indicator_on_group=None, indicator_off_group=None):
        options = dict(text_colour=text_colour, background_colour=background_colour, indicator_on_colour=indicator_on_colour,
                       indicator_off_colour=indicator_off_colour, page_key_colour=page_key_colour,
                       active_screen_brightness=active_screen_brightness, idle_screen_brightness=idle_screen_brightness,
                       active_indicator_brightness=active_indicator_brightness, idle_indicator_brightness=idle_indicator_brightness,
                       active_screen_group=active_screen_group, idle_screen_group=idle_screen_group,
                       active_indicator_group=active_indicator_group, idle_indicator_group=idle_indicator_group,
                       indicator_on_group=indicator_on_group, indicator_off_group=indicator_off_group)
        for name, (_, palette) in COLOUR_OPTIONS.items():
            if options[name] is not None and (not isinstance(options[name], str) or options[name] not in palette):
                raise EdltError(name + ' must be one of ' + ', '.join(palette))
        for name in (*BRIGHTNESS_OPTIONS, *GROUP_OPTIONS):
            if options[name] is not None:
                _int(options[name], name, 0, 255)
        original = self.snapshot(current); self.common.static_references(original)
        duration = _int(original['ActivityDuration'][0], 'ActivityDuration', 0, 255)
        primary = _int(original['PrimaryApplication'][0], 'PrimaryApplication', 0, 255)
        if not duration and any(options[name] is not None for name in _IDLE_OPTIONS):
            raise EdltError('Standby must already be enabled before editing idle brightness or its control groups')
        updates = dict(original)
        for name, (field, _) in GROUP_OPTIONS.items():
            if options[name] is not None:
                updates[field] = (options[name],)
        editable = {name: name not in _IDLE_OPTIONS or duration != 0 for name in FIELDS}
        for group, (field, fixed) in GROUP_OPTIONS.items():
            editable[fixed] = editable[fixed] and updates[field] == (255,)
            if options[fixed] is not None and not editable[fixed]:
                raise EdltError(f'{fixed} requires fixed mode; select {group}=255 first or in the same plan')
        for name, (field, palette) in COLOUR_OPTIONS.items():
            if options[name] is not None:
                updates[field] = (palette.index(options[name]),)
        for name, field in BRIGHTNESS_OPTIONS.items():
            if options[name] is not None:
                updates[field] = (options[name],)
        values = {name: _int(updates[field][0], field, 0, 255) for name, field in FIELDS.items()}
        mra = normalize_mra_globals(updates, _preserve_stored_multiplexer=True, _preserve_stored_placement=True)
        updates = self.common._place_record(updates, 1, bytes(updates[_field(1, index)][0] for index in range(32)))
        updates.update(mra.changes)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return ColourSettingsPlan(values, editable, primary, duration, original, changes, options, mra)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False, 'attempted_parameters': list(attempted),
                    'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_colours_evidence = evidence

    def apply(self, session, plan):
        if not isinstance(plan, ColourSettingsPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a colour plan returned by EdltColours.plan')
        if set(plan.values) != set(FIELDS) or set(plan.editable) != set(FIELDS):
            raise EdltError('Colour plan fields are incomplete')
        for value in plan.values.values():
            _int(value, 'Plan value', 0, 255)
        if any(type(value) is not bool for value in plan.editable.values()):
            raise EdltError('Plan editable flags must be boolean')
        _int(plan.activity_duration, 'Plan activity duration', 0, 255)
        _int(plan.primary_application, 'Plan primary application', 0, 255)
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid colour plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated colour settings')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the colour plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the colour plan')
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
                interrupted.edlt_colours_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
