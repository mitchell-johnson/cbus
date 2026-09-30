"""Bounded original Toolkit classic-key to Neo conversion rules.

The admitted lifecycle creates a fresh target model at firmware 2.5.00 from a
classic source at 1.2.67. It does not reuse an edited target or infer learned
history from PP values. Constructor inventories and hook facts are recorded in
the conversion-specific source evidence, separately from native acceptance.
"""
from __future__ import annotations

import re

from .unitspec import UnitSpec


KEY_TWEAKER = 'TTweakerKeyToNeo'
CLASSIC_TYPES = ('KEY1', 'KEY2', 'KEY4', 'KEYIR1', 'KEYIR4')
NEO_TYPES = ('KEYB2', 'KEYB4', 'KEYB6', 'KEYH1', 'KEYH2', 'KEYH3', 'KEYH4',
             'KEYM2', 'KEYM4', 'KEYM8', 'KEYA1', 'KEYA3', 'KEYA6', 'KEYA8',
             'KEYAV2', 'KEYAV4', 'KEYC1', 'KEYC2', 'KEYC4', 'KEYCIR1', 'KEYCIR4')
SOURCE_FIRMWARE = '1.2.67'
TARGET_FIRMWARE = '2.5.00'
TWEAKER_IMMUTABLE = (
    'InfraRedBank', 'EnableNightlight', 'EnableNightlightControl', 'DisableTimerFlash',
    'FirstKeyThrowAway', 'IndicatorPressedLevel', 'TimerDuration', 'IDBacklightIllumination',
    'PrimaryColour', 'EnableNightlightOnPCx', 'EnableNightlightOnPA6', 'DisableIR', 'DisableIRNEC',
    'ControlAppGroupAddress', 'PatchEnable', 'SceneKeySelector', 'SceneTable', 'SceneTablePointer',
)
NEOPRO_HOOK_IMMUTABLE = (
    'DisableIR', 'DisableIRNEC', 'KeyDisableGroup', 'KeyDisableGroupInvert',
    'CorridorLinkEnable', 'CorridorMasterGroup', 'CorridorGroupBlock', 'CorridorOfficeGroupBlock',
    'JoinPrimaryApplication', 'DualJoinPrimaryApplication', 'JoinSecondaryApplication',
    'DualJoinSecondaryApplication', 'SecondApplicationBlocks',
)
_TOKEN = re.compile(r'[+]?(?:0[xX][0-9a-fA-F]+|\$[0-9a-fA-F]+|[0-9]+)')


def require_target_firmware(firmware):
    if firmware != TARGET_FIRMWARE:
        raise ValueError('Classic-to-Neo conversion requires the fresh-target firmware 2.5.00 profile')


def _array(name, value, size, maximum):
    if not isinstance(value, str):
        raise ValueError(f'{name} requires a complete numeric PP string')
    tokens = value.split()
    if len(tokens) != size or any(_TOKEN.fullmatch(token) is None for token in tokens):
        raise ValueError(f'{name} requires exactly {size} numeric PP elements')
    values = []
    for token in tokens:
        token = token.lstrip('+')
        number = int(token[1:], 16) if token.startswith('$') else int(token, 16 if token.lower().startswith('0x') else 10)
        if not 0 <= number <= maximum:
            raise ValueError(f'{name} elements must be in 0..{maximum}')
        values.append(number)
    return values


def key_assignments(values):
    """Original tweaker then CoreKey hook assignments for a classic source."""
    groups = _array('GroupAddress', values.get('GroupAddress'), 8, 255)
    indicators = _array('IndicatorFunction', values.get('IndicatorFunction'), 4, 3)
    return (
        ('IndicatorFunction', ''.join(str({1: 2, 3: 1}.get(number, number)) + ' ' for number in indicators),
         'KeyToNeo indicator remap'),
        ('GroupAddress', ' '.join(f'0x{number:02X}' for number in groups[:4] + [255] * 4 + [groups[4]]),
         'CoreKey classic-to-Neo hook'),
    )


def apply_key_hooks(values, mutable, origin, not_written):
    """Apply tweaker, Learn, CoreKey and NeoPro hooks in their original order."""
    assignments = key_assignments(values)  # Validate every required array first.
    for name in TWEAKER_IMMUTABLE:
        if name in mutable:
            mutable[name] = False
            not_written[name] = 'KeyToNeo tweaker makes the attribute immutable'
    name, value, reason = assignments[0]
    values[name], origin[name] = value, reason
    # The fresh target model has not loaded PP: its two learned-state Boolean
    # attributes start false. This is distinct from the native PP default (1).
    for name in ('LearnMode', 'LearnAnyApp'):
        mutable[name] = True  # The exact target firmware 2.5.00 passes >=1.2.63.
        not_written.pop(name, None)
    mutable['LearnedFlag'] = False
    not_written['LearnedFlag'] = 'fresh target model has no original learned-state transition'
    # Source HasApplication2 is false, so the dual-to-single branch is skipped.
    name, value, reason = assignments[1]
    values[name], origin[name] = value, reason
    mutable['IndicatorBrightness'] = True
    not_written.pop('IndicatorBrightness', None)
    for name in NEOPRO_HOOK_IMMUTABLE:
        mutable[name] = False
        not_written[name] = 'NeoPro conversion hook retains the fresh target value for a classic source'


def validate_key_spec(unit_type, spec, *, source):
    """Require the schema used by the source-pinned fresh replacement profile."""
    allowed = CLASSIC_TYPES if source else NEO_TYPES
    firmware = SOURCE_FIRMWARE if source else TARGET_FIRMWARE
    if (unit_type not in allowed or not isinstance(spec, UnitSpec) or spec.unit_type != unit_type
            or spec.filename != unit_type + '.xml' or not spec.supports_version(firmware)):
        raise ValueError('Classic-to-Neo conversion requires the matching 1.2.67 source / 2.5.00 target specifications')
    shape = {
        'Application': ('int', 2, 8),
        'GroupAddress': ('int', 8 if source else 9, 8),
        'IndicatorFunction': ('int', 4 if source else 8, 2),
        'IndicatorBrightness': ('int', 1, 8),
        'LearnAnyApp': ('bit', 1, 8), 'LearnMode': ('bit', 1, 8), 'LearnedFlag': ('bit', 1, 8),
    }
    for name, expected in shape.items():
        parameter = spec.parameters.get(name)
        if parameter is None or (parameter.type, parameter.array_size, parameter.bit_size) != expected:
            raise ValueError(f'Unsupported classic-to-Neo PP shape for {name}')


# Original constructor order, including registered subroutine calls and IRBank rename.
CLASSIC_ATTRIBUTES = (
    ('Application', True),
    ('FirmwareVersion', False),
    ('Project', True),
    ('SerialNo', False),
    ('State', False),
    ('UnitAddress', True),
    ('UnitName', True),
    ('UnitType', False),
    ('LearnAnyApp', True),
    ('LearnMode', True),
    ('LearnedFlag', True),
    ('AreaGroupAddress', True),
    ('StatusReportInterval', True),
    ('GroupAddress', True),
    ('DebounceTime', True),
    ('IndicatorBrightness', False),
    ('LongPressTime', True),
    ('EEPROMLevelStore', True),
    ('LightIndex', True),
    ('LightLevel', True),
    ('LightLevelStore1', True),
    ('LightLevelStore2', True),
    ('RampRate', True),
    ('InfraRedBank', True),
    ('JPCommand', True),
    ('SRCommand', True),
    ('LPCommand', True),
    ('LRCommand', True),
    ('BlockAllocation', True),
    ('IndicatorBlockAssignment', True),
    ('IndicatorFunction', True),
    ('TimerHighByte', True),
    ('TimerLowByte', True),
    ('TimerExpiryCommand', True),
    ('GAVBroadcastFlag', False),
)
NEOPRO_ATTRIBUTES = (
    ('Application', True),
    ('FirmwareVersion', False),
    ('Project', True),
    ('SerialNo', False),
    ('State', False),
    ('UnitAddress', True),
    ('UnitName', True),
    ('UnitType', False),
    ('LearnAnyApp', True),
    ('LearnMode', True),
    ('LearnedFlag', True),
    ('AreaGroupAddress', True),
    ('StatusReportInterval', True),
    ('GroupAddress', True),
    ('DebounceTime', True),
    ('IndicatorBrightness', False),
    ('LongPressTime', True),
    ('EEPROMLevelStore', True),
    ('LightIndex', True),
    ('LightLevel', True),
    ('LightLevelStore1', True),
    ('LightLevelStore2', True),
    ('RampRate', True),
    ('IRBank', True),
    ('JPCommand', True),
    ('SRCommand', True),
    ('LPCommand', True),
    ('LRCommand', True),
    ('BlockAllocation', True),
    ('IndicatorBlockAssignment', True),
    ('IndicatorFunction', True),
    ('TimerHighByte', True),
    ('TimerLowByte', True),
    ('TimerExpiryCommand', True),
    ('ControlAppGroupAddress', True),
    ('EnableNightlight', True),
    ('EnableNightlightControl', True),
    ('DisableTimerFlash', True),
    ('FirstKeyThrowAway', True),
    ('IndicatorPressedLevel', True),
    ('TimerDuration', True),
    ('PatchEnable', True),
    ('SceneKeySelector', True),
    ('SceneTable', True),
    ('SceneTablePointer', True),
    ('DisableIR', True),
    ('IDBacklightIllumination', True),
    ('EnableNightlightOnPCx', True),
    ('EnableNightlightOnPA6', True),
    ('PrimaryColour', True),
    ('DisableIRNEC', True),
    ('KeyDisableGroup', True),
    ('KeyDisableGroupInvert', True),
    ('CorridorLinkEnable', True),
    ('CorridorMasterGroup', True),
    ('CorridorGroupBlock', True),
    ('CorridorOfficeGroupBlock', True),
    ('JoinPrimaryApplication', True),
    ('JoinSecondaryApplication', True),
    ('DualJoinPrimaryApplication', True),
    ('DualJoinSecondaryApplication', True),
    ('SecondApplicationBlocks', True),
    ('NightlightColour', True),
)
