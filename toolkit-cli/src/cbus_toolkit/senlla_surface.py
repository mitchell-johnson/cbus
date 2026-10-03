"""Read-only SENLLA surface components, without the inherited Toolkit save.

The surface agent loads target/margin, power-up and bank usage after its ST7
ancestor. These thirteen fields admit a detached getter view and the proven
surface serialization overlay. Eight-key marshalling, bank threshold loading,
Scene, Global, control notifications and group creation are separate pipelines.
No method in this module applies a plan or opens a programming session.
"""
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from collections.abc import Mapping
import re

from .macros import _numbers
from .memory import MemoryCodec
from .sensors import SensorError, _integer, margin_percent, saved_margin


PROFILE = MappingProxyType({
    'unit_type': 'SENLLA', 'toolkit_class': 'TSENLLA', 'catalog_number': '5754PE',
    'firmware': ('2.4.00', '2.4.99'), 'spec_filename': 'SENLLA.xml',
    'runtime_input_key_count': 8,
})
# Recovered numeric layout facts; this is a consumed component schema, not the
# complete 93-parameter specification or its inherited input-key inventory.
LAYOUTS = MappingProxyType({
    'PowerUpTargetGroupLevel': (16, 1, 8, 0, 0),
    'PowerUpMarginGroupLevel': (17, 1, 8, 0, 0),
    'PowerUpBankSwitchGroupLevel': (18, 1, 8, 0, 0),
    'LightLevelTargetGroup': (19, 1, 8, 0, 0),
    'LightLevelMarginGroup': (20, 1, 8, 0, 0),
    'BankSwitchThresholdGroup': (21, 1, 8, 0, 0),
    'LightLevelTargetGroupLevelStore': (22, 1, 1, 0, 0),
    'LightLevelMarginGroupLevelStore': (22, 1, 1, 1, 0),
    'BankSwitchGroupLevelStore': (22, 1, 1, 2, 0),
    'BankSwitchThresholdBehaviour': (22, 1, 2, 4, 0),
    'PECTargetLux': (27, 1, 8, 0, 0),
    'PECMarginLux': (28, 1, 8, 0, 0),
    'BankSwitchGroupUsed': (72, 8, 1, 6, 0),
})
BITS = frozenset(('LightLevelTargetGroupLevelStore', 'LightLevelMarginGroupLevelStore',
                  'BankSwitchGroupLevelStore'))
EXCLUDED_PIPELINES = (
    'inherited_eight_key_load_and_save', 'raw_bank_threshold_load_and_save',
    'scene_load_and_save', 'global_initialization_and_save', 'fresh_form_notifications',
    'group_object_lookup_and_creation', 'live_group_control',
)


def check_profile(unit_type, firmware, catalog_number, *, subject='Unit identity'):
    """Admit the canonical firmware band justified by the SENLLA catalogue."""
    if (unit_type != 'SENLLA' or catalog_number != '5754PE'
            or not isinstance(firmware, str) or re.fullmatch(r'2\.4\.[0-9]{2}', firmware) is None):
        raise SensorError(f'{subject} must be SENLLA 2.4.00..2.4.99 / 5754PE with SENLLA.xml')
    return unit_type, firmware, catalog_number


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _json_value(value):
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _flags(values, name):
    if (not isinstance(values, (list, tuple)) or len(values) != 8
            or any(type(value) is not bool for value in values)):
        raise SensorError(f'{name} requires exactly eight logical Boolean values')
    return tuple(values)


def logical_bank_usage_parameters(*, low_group, high_group, use_low, use_high):
    """Serialize declared unit flags; this does not establish their raw loader."""
    low_group = _integer(low_group, 'Low bank group', 0, 255)
    high_group = _integer(high_group, 'High bank group', 0, 255)
    low, high = _flags(use_low, 'use_low'), _flags(use_high, 'use_high')
    if any(low) and low_group == 255 or any(high) and high_group == 255:
        raise SensorError('A used logical bank group must be assigned')
    group, behaviour = 255, 0
    if any(low):
        group, behaviour = low_group, 1
    if any(high):
        group, behaviour = high_group, 2
    return {
        'BankSwitchThresholdGroup': (group,), 'BankSwitchThresholdBehaviour': (behaviour,),
        'BankSwitchGroupUsed': tuple(int(a or b) for a, b in zip(low, high)),
    }


def logical_bank_level_overlay(index, *, use_low=False, use_high=False, high_lux=None):
    """Expose indexed surface writes for one explicitly supplied logical bank.

    This helper accepts the byte-representable 0..2550 lux domain only. The
    13-field view omits both store arrays, so these writes cannot be inferred
    from it. Signed/out-of-range logical levels require a separate source slice.
    """
    index = _integer(index, 'Bank index', 0, 7)
    if type(use_low) is not bool or type(use_high) is not bool:
        raise SensorError('Logical bank use_low/use_high must be Boolean values')
    writes = {}
    if use_low:
        lux = _integer(high_lux, 'Logical high lux', 0, 2550)
        writes['LightLevelStore2'] = {index: lux // 10}
    elif high_lux is not None:
        raise SensorError('Logical high lux is consumed only by a low-group bank')
    if use_high:
        writes['LightLevelStore1'] = {index: 255}
    return {'format': 'cbus-senlla-logical-bank-overlay-v1', 'indexed_parameters': writes,
            'logical_state_only': True, 'raw_loader_binding_verified': False,
            'complete_toolkit_save': False, 'saved': False, 'physical_acceptance': False}


def display_target_lux(current_level):
    """Read-only current-level display; unknown levels are not substituted."""
    level = _integer(current_level, 'Current group level', 0, 255)
    return round(Fraction((level + 1) * 2000, 256))


def display_margin_percent(current_level):
    level = _integer(current_level, 'Current group level', 0, 255)
    return round(Fraction((level + 1) * 100, 256))


@dataclass(frozen=True)
class SurfaceView:
    identity: tuple
    expected: Mapping
    loaded: Mapping
    component_overlay: Mapping

    def __post_init__(self):
        if not isinstance(self.identity, tuple) or len(self.identity) != 3:
            raise SensorError('Identity must be (unit_type, firmware, catalog_number)')
        check_profile(*self.identity)
        for name in ('expected', 'loaded', 'component_overlay'):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    def as_dict(self):
        return {
            'format': 'cbus-senlla-surface-view-v1', 'unit_type': self.identity[0],
            'firmware': self.identity[1], 'catalog_number': self.identity[2],
            'spec_filename': 'SENLLA.xml', 'toolkit_class': 'TSENLLA', 'runtime_input_key_count': 8,
            'consumed_parameter_count': 13, 'expected': _json_value(self.expected),
            'loaded': _json_value(self.loaded), 'component_overlay': _json_value(self.component_overlay),
            'component_parameters': _json_value({**self.expected, **self.component_overlay}),
            'excluded_pipelines': list(EXCLUDED_PIPELINES), 'read_only': True,
            'complete_toolkit_save': False, 'saved': False, 'device_verified': False,
            'original_execution': False, 'physical_acceptance': False,
        }


class SENLLASurface:
    def __init__(self, spec):
        if spec.filename != 'SENLLA.xml':
            raise SensorError('Use SENLLA.xml for SENLLA surface components')
        self.spec, self.codec = spec, MemoryCodec(spec)
        self._verify_layouts()

    def _verify_layouts(self):
        for name, expected in LAYOUTS.items():
            try:
                parameter = self.spec.get(name)
                layout = self.codec.layout(name)
                # Native bit packing ignores BitSize and ArraySkip, including
                # the schema's default BitSize8 when that field is absent.
                actual = (layout.address, layout.array_size, layout.bit_size,
                          layout.bit_address, 0 if parameter.type == 'bit' else layout.array_skip)
                kind = 'bit' if name in BITS else 'int'
                valid = actual == expected and parameter.type == kind
            except (KeyError, ValueError):
                valid = False
            if not valid:
                raise SensorError('Unsupported SENLLA surface parameter layout: ' + name)

    def snapshot(self, current):
        self._verify_layouts()
        if not isinstance(current, Mapping):
            raise SensorError('SENLLA surface view requires a current PP mapping')
        result = {}
        for name in LAYOUTS:
            if name not in current:
                raise SensorError('Missing SENLLA surface parameter: ' + name)
            try:
                values = _numbers(current[name])
            except ValueError:
                raise SensorError('Invalid SENLLA surface parameter: ' + name) from None
            _address, count, bits, _bit, _skip = LAYOUTS[name]
            if len(values) != count or any(not 0 <= number < (1 << bits) for number in values):
                raise SensorError('Invalid unsigned SENLLA surface parameter: ' + name)
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise SensorError('Invalid SENLLA surface parameter: ' + name)
            result[name] = values
        return result

    def view(self, current, *, identity):
        if not isinstance(identity, tuple) or len(identity) != 3:
            raise SensorError('Identity must be (unit_type, firmware, catalog_number)')
        identity = check_profile(*identity)
        raw = self.snapshot(current)
        value = lambda name: raw[name][0]
        target_group, margin_group = value('LightLevelTargetGroup'), value('LightLevelMarginGroup')
        bank_group = value('BankSwitchThresholdGroup')
        power = {
            name: {
                'state': int(bool(value(store)) or value(group) == 255),
                'preset_level': value(preset),
            }
            for name, store, group, preset in (
                ('target', 'LightLevelTargetGroupLevelStore', 'LightLevelTargetGroup', 'PowerUpTargetGroupLevel'),
                ('margin', 'LightLevelMarginGroupLevelStore', 'LightLevelMarginGroup', 'PowerUpMarginGroupLevel'),
                ('bank', 'BankSwitchGroupLevelStore', 'BankSwitchThresholdGroup', 'PowerUpBankSwitchGroupLevel'),
            )
        }
        using_target = target_group != 255
        if using_target:
            margin_group = 255
        using_margin = margin_group != 255
        percent = margin_percent(value('PECTargetLux'), value('PECMarginLux'))
        if using_margin:
            percent = 9
        low_group, high_group = (bank_group, 255) if value('BankSwitchThresholdBehaviour') == 1 else (255, bank_group)
        low = tuple(bool(used) and low_group != 255 for used in raw['BankSwitchGroupUsed'])
        high = tuple(bool(used) and high_group != 255 for used in raw['BankSwitchGroupUsed'])
        loaded = {
            'target_group': target_group, 'using_target_group': using_target,
            'target_byte': 45 if using_target else value('PECTargetLux'),
            'margin_group': margin_group, 'using_margin_group': using_margin, 'margin_percent': percent,
            'bank_low_group': low_group, 'bank_high_group': high_group, 'use_low': low, 'use_high': high,
            'power_up': power,
        }
        projected = dict(raw)
        if using_target:
            # The surface VariantReal/double path has no half ties in the
            # byte-admitted domain: ROUND(200 * double(percent/100)) = 2*percent.
            margin = _integer(2 * percent, 'Surface margin projection', 0, 255)
            projected.update(LightLevelMarginGroup=(target_group,), PECTargetLux=(200,), PECMarginLux=(margin,))
        elif using_margin:
            projected['PECMarginLux'] = raw['PECTargetLux']
        else:
            margin = _integer(saved_margin(value('PECTargetLux'), percent), 'Surface margin projection', 0, 255)
            projected['PECMarginLux'] = (margin,)
        projected.update(logical_bank_usage_parameters(low_group=low_group, high_group=high_group,
                                                      use_low=low, use_high=high))
        target_store = int(using_target and power['target']['state'] == 1)
        projected['LightLevelTargetGroupLevelStore'] = (target_store,)
        projected['LightLevelMarginGroupLevelStore'] = (
            target_store if using_target else int(using_margin and power['margin']['state'] == 1),)
        projected['BankSwitchGroupLevelStore'] = (int((any(low) or any(high)) and power['bank']['state'] == 1),)
        if using_target:
            projected['PowerUpMarginGroupLevel'] = raw['PowerUpTargetGroupLevel']
        changes = {name: values for name, values in projected.items() if values != raw[name]}
        self.codec.encode_many(changes)
        return SurfaceView(identity, raw, loaded, changes)


__all__ = ['BITS', 'EXCLUDED_PIPELINES', 'LAYOUTS', 'PROFILE', 'SENLLASurface', 'SurfaceView',
           'check_profile', 'display_margin_percent', 'display_target_lux',
           'logical_bank_level_overlay', 'logical_bank_usage_parameters']
