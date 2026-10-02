"""Source-bound fresh-model Neo Classic, PCI/DALI and older sensor conversions.

Only the fixed factory/specification/firmware profiles below are admitted.
Static original instructions establish these transformations; no original
Toolkit process or physical programming is claimed by this module.
"""
from __future__ import annotations

from .toolkit_conversion_key_to_neo import CLASSIC_ATTRIBUTES, NEOPRO_ATTRIBUTES, _array
from .toolkit_conversion_input_unit import INPUT_IMMUTABLE
from .unitspec import UnitSpec

NEO_TWEAKER = 'TTweakerNeoToKey'
DALI_TWEAKERS = frozenset(('TTweakerPC_DAL2', 'TTweakerPC_DAL2B'))
PIR_TWEAKER = 'TTweakerSENPIR'
LL_TWEAKER = 'TTweakerSENLL'
INPUT_TWEAKER = 'TTweakerInputUnit'
TWEAKERS = frozenset((NEO_TWEAKER, PIR_TWEAKER, LL_TWEAKER)) | DALI_TWEAKERS
NEO_TYPES = ('KEYC1', 'KEYC2', 'KEYC4', 'KEYCIR1', 'KEYCIR4')
CLASSIC_TYPES = ('KEY1', 'KEY2', 'KEY4', 'KEYIR1', 'KEYIR4')
DALI_TYPES = ('PC_DAL2', 'PC_DAL2B', 'PC_DAL2C')
PIR_TYPES = ('SENPIRSS', 'SENPIROA', 'SENPIRIA', 'SENPIRIB')
SENSOR_TYPES = PIR_TYPES + ('SENLL', 'SENPILL')
_BASE = CLASSIC_ATTRIBUTES[:8]
PCI_ATTRIBUTES = _BASE + (('Burden', False), ('ClockGenEnable', True))
DALI_ATTRIBUTES = PCI_ATTRIBUTES + tuple((name, True) for name in (
    'ErrorReportDeviceID', 'DaliMonitorRate', 'DaliARampMatching', 'DaliARestoreLevel',
    'DaliAErrorReportingStatus', 'DaliAErrorRefreshTime', 'DaliAEnableErrorGroup',
    'DaliAEnableErrorLevel', 'DaliADisableErrorGroup', 'DaliADisableErrorLevel',
    'DaliATriggerErrorGroup', 'DaliATriggerErrorAcSel', 'DaliBRampMatching',
    'DaliBRestoreLevel', 'DaliBErrorReportingStatus', 'DaliBErrorRefreshTime',
    'DaliBEnableErrorGroup', 'DaliBEnableErrorLevel', 'DaliBDisableErrorGroup',
    'DaliBDisableErrorLevel', 'DaliBTriggerErrorGroup', 'DaliBTriggerErrorAcSel',
    'CBusToDali', 'DaliToCBus'))
# PIR calls CoreKey InternalCreate directly; the classic KeyInput subclass's
# final GAVBroadcastFlag is absent. Its two sensor fields are appended.
PIR_ATTRIBUTES = CLASSIC_ATTRIBUTES[:-1] + (('EnableGroupAddress', True), ('EnableGroupLogic', True))
MULTI_ATTRIBUTES = tuple(('IRBank' if n == 'InfraRedBank' else n, flag)
                         for n, flag in CLASSIC_ATTRIBUTES[:-1]) + tuple((n, True) for n in (
    'ControlAppGroupAddress', 'EnableNightlight', 'EnableNightlightControl', 'DisableTimerFlash',
    'FirstKeyThrowAway', 'IndicatorPressedLevel', 'TimerDuration', 'PatchEnable',
    'SceneKeySelector', 'SceneTable', 'SceneTablePointer', 'DisableIR',
    'IDBacklightIllumination', 'EnableNightlightOnPCx', 'EnableNightlightOnPA6', 'PrimaryColour',
    'PIRLightMovement', 'PIRDarkMovement', 'PIRDark', 'IRBankKeyOffset', 'CorridorLinkOfficeBlock',
    'CorridorLinkBlock', 'CorridorLinkActive', 'BroadcastBlock', 'BroadcastActive', 'IndicatorControl',
    'PECTargetLux', 'PECMarginLux', 'PECScaleFactor', 'BlockGroupLogic', 'BlockBankSwitchActive',
    'PIREnablerGroup', 'PECEnablerGroup', 'SingleJoinEnablerGroup', 'DualJoinEnablerGroup',
    'CorridorLinkEnablerGroup', 'SingleJoinEnablerControlGroup', 'DualJoinEnablerControlGroup',
    'PECFunctionBlock', 'PECFunctionActive', 'PECFunctionIRKey', 'PECFunctionIRActive',
    'PIRFunctionIRKey', 'PIRFunctionIRActive', 'PECLevelStore', 'PIRLevelStore', 'PECEnablerGroupLogic',
    'PIREnablerGroupLogic', 'PotentiometerAFunction', 'PotentiometerBFunction', 'PotentiometerATimerBlock',
    'PotentiometerBTimerBlock', 'PotentiometerBBankSwitchEnable'))
LL_ATTRIBUTES = CLASSIC_ATTRIBUTES[:13] + tuple((n, True) for n in (
    'TargetLUX', 'Hystersis', 'LevelGroupAddress', 'OnOffGroupAddress', 'EnableGroupAddress', 'LED', 'IndicatorFunction'))
JOIN_FIELDS = ('SingleJoinEnablerGroup', 'DualJoinEnablerGroup',
               'SingleJoinEnablerControlGroup', 'DualJoinEnablerControlGroup')
ATTRIBUTES = {**{t: NEOPRO_ATTRIBUTES for t in NEO_TYPES},
              **{t: CLASSIC_ATTRIBUTES for t in CLASSIC_TYPES},
              'PC_DAL2': PCI_ATTRIBUTES,
              **{t: DALI_ATTRIBUTES for t in ('PC_DAL2B', 'PC_DAL2C')},
              **{t: PIR_ATTRIBUTES for t in PIR_TYPES},
              'SENPILL': MULTI_ATTRIBUTES, 'SENLL': LL_ATTRIBUTES}
PIR_IMMUTABLE = ('EEPROMLevelStore', 'InfraRedBank', 'LightIndex', 'LightLevel',
                 'LightLevelStore1', 'LightLevelStore2')


def handles(tweaker, source_type, target_type):
    return tweaker in TWEAKERS or (tweaker == INPUT_TWEAKER and source_type.upper() == target_type.upper() == 'SENPILL')


def renames(tweaker):
    return {'PECEnablerGroup': 'EnableGroupAddress', 'EnableGroupAddress': 'PECEnablerGroup'} if tweaker == LL_TWEAKER else {}


def unit_firmware(unit_type):
    kind = unit_type.upper()
    if kind in NEO_TYPES:
        return '2.5.00'
    if kind in CLASSIC_TYPES or kind in ('SENPIRSS', 'SENLL'):
        return '1.2.67'
    if kind == 'SENPILL':
        return '1.6.00'
    if kind in PIR_TYPES:
        return '1.2.68'
    if kind in DALI_TYPES:
        return '4.5.00'
    raise ValueError('No recovered conversion model for ' + kind)


def require_target_firmware(unit_type, firmware):
    if firmware != unit_firmware(unit_type):
        raise ValueError('Conversion requires the source-pinned fresh-target firmware ' + unit_firmware(unit_type))


def specification(unit_type):
    kind = unit_type.upper()
    alias = ('PC_DAL2B' if kind == 'PC_DAL2C' else 'SENPIRSS' if kind in PIR_TYPES
             else 'SENPILL_1' if kind == 'SENPILL' else kind)
    return alias + '.xml', 'SENPILL' if kind == 'SENPILL' else alias


def validate_spec(unit_type, spec, *, source):
    kind = unit_type.upper()
    filename, declared = specification(kind)
    if (kind not in ATTRIBUTES or not isinstance(spec, UnitSpec) or spec.filename != filename
            or spec.unit_type != declared or not spec.supports_version(unit_firmware(kind))):
        raise ValueError('Conversion requires the matching source-pinned specification and firmware')
    shape = {'Application': ('int', 2, 8)}
    if kind in DALI_TYPES:
        shape.update({'Burden': ('bit', 1, 8), 'ClockGenEnable': ('bit', 1, 8)})
    elif kind in ('SENLL', 'SENPILL'):
        shape.update({n: ('bit', 1, 8) for n in ('LearnAnyApp', 'LearnMode', 'LearnedFlag')})
        if kind == 'SENLL':
            shape.update({n: ('int', 1, 8) for n in ('TargetLUX', 'Hystersis', 'LevelGroupAddress', 'OnOffGroupAddress', 'EnableGroupAddress')})
            shape['IndicatorFunction'] = ('int', 1, 2)
        else:
            shape.update({'GroupAddress': ('int', 8, 8), 'DisableIR': ('bit', 1, 8),
                          'PECEnablerGroup': ('int', 1, 8), 'PECTargetLux': ('int', 1, 8),
                          'PECMarginLux': ('int', 1, 8), **{n: ('int', 1, 8) for n in JOIN_FIELDS}})
    else:
        shape.update({'GroupAddress': ('int', 9 if kind in NEO_TYPES else 4 if kind in PIR_TYPES else 8, 8),
                      'IndicatorFunction': ('int', 8 if kind in NEO_TYPES else 1 if kind in PIR_TYPES else 4, 2),
                      **{n: ('bit', 1, 8) for n in ('LearnAnyApp', 'LearnMode', 'LearnedFlag')}})
        if kind in NEO_TYPES:
            shape['SecondApplicationBlocks'] = ('int', 1, 8)
        if kind in NEO_TYPES or kind in CLASSIC_TYPES:
            shape['IndicatorBrightness'] = ('int', 1, 8)
        if kind in PIR_TYPES:
            shape.update({'EnableGroupAddress': ('int', 1, 8), 'EnableGroupLogic': ('int', 1, 8)})
    for name, expected in shape.items():
        p = spec.parameters.get(name)
        if p is None or (p.type, p.array_size, p.bit_size) != expected:
            raise ValueError('Unsupported source-pinned conversion PP shape for ' + name)


def context(source_type, target_type):
    return {'profile': ('neo-classic-to-fresh-classic' if source_type in NEO_TYPES
                        else 'pci-dali-fresh-swap' if source_type in DALI_TYPES else 'older-sensor-fresh'),
            'source_firmware': unit_firmware(source_type), 'target_firmware': unit_firmware(target_type),
            'fresh_target_model': True, 'target_programming_loaded_before_hook': False,
            'original_code_executed': False,
            **({'target_learned_flag': False, 'target_learned_flag_original': False}
               if source_type not in DALI_TYPES else {})}


def _learn(mutable, not_written):
    for name in ('LearnMode', 'LearnAnyApp'):
        mutable[name] = True
        not_written.pop(name, None)
    mutable['LearnedFlag'] = False
    not_written['LearnedFlag'] = 'fresh target model has no original learned-state transition'


def apply_hooks(tweaker, source_type, target_type, source_values, values, mutable, origin, not_written):
    if tweaker in DALI_TWEAKERS:
        apps = _array('Application', values.get('Application'), 2, 255)
        values['Application'] = f'{apps[1]} {apps[0]}'
        origin['Application'] = 'PCI/DALI tweaker swaps Application elements'
        return
    if target_type in ('SENLL', 'SENPILL'):
        if tweaker == INPUT_TWEAKER:
            for name in INPUT_IMMUTABLE:
                if name in mutable:
                    mutable[name] = False
                    not_written[name] = 'InputUnit tweaker retains the fresh target default'
        _learn(mutable, not_written)
        if target_type == 'SENPILL':
            mutable['IndicatorBrightness'] = False
            not_written['IndicatorBrightness'] = 'older multisensor brightness property is disabled'
            if source_type == 'SENLL':
                # No GroupAddress source attribute exists. The fresh agent
                # string is empty; original IntArrayElementWithDefault uses
                # 255 for each index, producing nine entries before PP truncation.
                values['GroupAddress'] = ' '.join(['0xFF'] * 9)
                origin['GroupAddress'] = 'CoreKey non-Neo to Neo empty fresh group reshape'
            mutable['DisableIR'] = True
            not_written.pop('DisableIR', None)
            for name in JOIN_FIELDS:
                values[name], origin[name] = '255', 'multisensor pre-2.0.0 join mode reset'
                if mutable[name]: not_written.pop(name, None)
        # These exact source profiles are older sensors, never ST7: the
        # original ST7 lux/polarity translation branches are not reached.
        return
    if tweaker == PIR_TWEAKER:
        _learn(mutable, not_written)
        mutable['IndicatorBrightness'] = False
        not_written['IndicatorBrightness'] = 'older PIR target brightness property is disabled'
        for name in PIR_IMMUTABLE:
            mutable[name] = False
            not_written[name] = 'older PIR conversion hook retains the fresh target default'
        # Every admitted source is the older PIR model, not ST7. The original
        # occupancy-polarity/disable-PIR rewrite is therefore not reached.
        return
    apps = _array('Application', source_values.get('Application'), 2, 255)
    groups = _array('GroupAddress', source_values.get('GroupAddress'), 9, 255)
    mask = _array('SecondApplicationBlocks', source_values.get('SecondApplicationBlocks'), 1, 255)[0]
    if apps[0] == 255:
        raise ValueError('NeoToKey requires a concrete primary application model')
    for name in INPUT_IMMUTABLE:
        if name in mutable:
            mutable[name] = False
            not_written[name] = 'NeoToKey inherited InputUnit tweaker retains the fresh target default'
    _learn(mutable, not_written)
    # CoreKey compares actual application object identity, not merely the
    # mask bit: equal primary/secondary identities remove every first-eight
    # block even when its secondary bit is clear. Slot8 is the Area tail and
    # lies outside MaximumBlockCount=8, so it survives this pass.
    if apps[1] != 255:
        groups = [255 if index < 8 and (apps[0] == apps[1] or mask & (1 << index))
                  else group for index, group in enumerate(groups)]
        values['Application'] = f'{apps[0]} 255'
        origin['Application'] = 'CoreKey dual-to-single primary application'
    result = groups[:4] + [groups[8], 255, 255, 255]
    values['GroupAddress'] = ' '.join(f'0x{n:02X}' for n in result)
    origin['GroupAddress'] = 'CoreKey Neo-to-classic group reshape after secondary identity removal'
    mutable['IndicatorBrightness'] = True
    not_written.pop('IndicatorBrightness', None)
