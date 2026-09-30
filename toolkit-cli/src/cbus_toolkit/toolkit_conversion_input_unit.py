"""Original Toolkit InputUnit conversion for fresh classic input models.

All admitted source/target models are non-Neo and have HasApplication2=false.
The CoreKey conversion hook therefore leaves aligned parameter strings alone;
only the inherited learning flags and target brightness predicate are applied.
"""
from __future__ import annotations

from .toolkit_conversion_key_to_neo import CLASSIC_ATTRIBUTES, TWEAKER_IMMUTABLE
from .unitspec import UnitSpec


INPUT_TWEAKER = 'TTweakerInputUnit'
INPUT_TYPES = ('KEY1', 'KEY2', 'KEY4', 'KEYBC2', 'KEYBC4', 'BCNC4A', 'BCNC4B')
BRIGHTNESS_TYPES = ('KEY1', 'KEY2', 'KEY4')
FIRMWARE = '1.2.67'
INPUT_ATTRIBUTES = CLASSIC_ATTRIBUTES
INPUT_IMMUTABLE = TWEAKER_IMMUTABLE[:13]


def require_target_firmware(firmware):
    if firmware != FIRMWARE:
        raise ValueError('InputUnit conversion requires the fresh-target firmware 1.2.67 profile')


def apply_input_hooks(target_type, values, mutable, origin, not_written):
    """Apply original flags without parsing or rewriting aligned value strings."""
    for name in INPUT_IMMUTABLE:
        if name in mutable:
            mutable[name] = False
            not_written[name] = 'InputUnit tweaker makes the attribute immutable'
    # At the exact admitted firmware, CoreKey's lexical >=1.2.63 test is true.
    for name in ('LearnMode', 'LearnAnyApp'):
        mutable[name] = True
        not_written.pop(name, None)
    mutable['LearnedFlag'] = False
    not_written['LearnedFlag'] = 'fresh target model has no original learned-state transition'
    mutable['IndicatorBrightness'] = target_type in BRIGHTNESS_TYPES
    if mutable['IndicatorBrightness']:
        not_written.pop('IndicatorBrightness', None)
    else:
        not_written['IndicatorBrightness'] = 'target brightness property makes the attribute immutable'


def validate_input_spec(unit_type, spec):
    # BCNC4B has this exact catalogue alias in both source and target roles.
    expected_type = 'BCNC4A' if unit_type == 'BCNC4B' else unit_type
    if (unit_type not in INPUT_TYPES or not isinstance(spec, UnitSpec) or spec.unit_type != expected_type
            or spec.filename != expected_type + '.xml' or not spec.supports_version(FIRMWARE)):
        raise ValueError('InputUnit conversion requires matching 1.2.67 source and target specifications')
    shapes = {
        'Application': ('int', 2, 8), 'GroupAddress': ('int', 8, 8),
        'IndicatorFunction': ('int', 4, 2),
        'LearnAnyApp': ('bit', 1, 8), 'LearnMode': ('bit', 1, 8), 'LearnedFlag': ('bit', 1, 8),
    }
    if unit_type in BRIGHTNESS_TYPES:
        shapes['IndicatorBrightness'] = ('int', 1, 8)
    for name, expected in shapes.items():
        parameter = spec.parameters.get(name)
        if parameter is None or (parameter.type, parameter.array_size, parameter.bit_size) != expected:
            raise ValueError(f'Unsupported InputUnit PP shape for {name}')
