"""Toolkit client-side conversion tweakers for bounded DIN and key-input pairs.

Toolkit 1.18 converts units without C-Gate CONVERTUNIT. It creates the
replacement unit, copies every same-named writable agent attribute from the
source, applies the tweaker registered for the (source type, target type)
pair and issues PP SET only for attributes that remain writable. The complete
registry (292 registrations, 13 tweaker classes) and each class's recovered
rules are recorded in ``research/fixtures/toolkit-conversion-tweaker-registry.json``.

The DIMDUx and RELDN tweaker rules are recovered; their agents inherit the
empty base conversion hook. KeyToNeo conversion models the inherited
Learn/CoreKey/NeoPro hooks and CouplerPro's final brightness suppression only
for the source-pinned fresh-target profiles.
Ten non-sensor InputUnit pairs apply only the recovered Learn and brightness
flags; their non-Neo models leave all aligned parameter strings unchanged.
Unsupported relay PP shapes are refused. Every other
registered pair, and every unregistered pair, is refused before any I/O with
the receipt's reason. Database metadata (tag, description, serial), source
deletion, readdressing and project save are outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType

from .cgate import CGateError
from .native import NativeDatabase
from .programming import Programmer, ProgrammingCommandError
from . import toolkit_conversion_coupler_to_neo as coupler
from . import toolkit_conversion_input_unit as input_unit
from .toolkit_conversion_key_to_neo import (
    CLASSIC_ATTRIBUTES, CLASSIC_TYPES, KEY_TWEAKER, NEO_TYPES, NEOPRO_ATTRIBUTES,
    SOURCE_FIRMWARE, TARGET_FIRMWARE, apply_key_hooks, require_target_firmware, validate_key_spec,
)
from .toolkit_conversion_reldn import RELAY_FIELDS, RELAY_TWEAKERS, relay_assignments
from .unitspec import UnitSpec


class TweakerRefused(ValueError):
    def __init__(self, source_type, target_type, tweaker_class, reason):
        self.source_type, self.target_type = source_type, target_type
        self.tweaker_class, self.reason = tweaker_class, reason
        super().__init__(f"Toolkit conversion {source_type} -> {target_type} is refused: {reason}")


class TweakerConversionError(RuntimeError):
    def __init__(self, message, *, details=None):
        self.details = dict(details or {})
        super().__init__(message)


# (source>target) registrations per tweaker class, in original registration order.
_REGISTRATIONS = {
    'TTweakerPC_DAL2': (
        'PC_DAL2>PC_DAL2B PC_DAL2>PC_DAL2C'
    ),
    'TTweakerPC_DAL2B': (
        'PC_DAL2B>PC_DAL2 PC_DAL2C>PC_DAL2'
    ),
    'TTweakerRELDN8_TO_X': (
        'RELDN8>RELDN12 RELDN8>RELDN4 RELDN8>RELDN8B RELDN8>RELSM8'
    ),
    'TTweakerRELDNX_TO_8': (
        'RELDN12>RELDN8 RELDN4>RELDN8 RELDN8B>RELDN8 RELSM8>RELDN8'
    ),
    'TTweakerDIMDN_TO_DIMDU4': (
        'DIMDN8>DIMDU4 DIMDN8F>DIMDU4 DIMDN4>DIMDU4 DIMDN4F>DIMDU4'
    ),
    'TTweakerDIMDU4_TO_DIMDN': (
        'DIMDU4>DIMDN8 DIMDU4>DIMDN8F DIMDU4>DIMDN4 DIMDU4>DIMDN4F'
    ),
    'TTweakerDLT': (
        'KEYM2>KEYDL4 KEYM4>KEYDL4 KEYM6>KEYDL4 KEYM8>KEYDL4 KEYB2>KEYDL4 KEYB4>KEYDL4 KEYB6>KEYDL4 '
        'KEYH1>KEYDL4 KEYH2>KEYDL4 KEYH3>KEYDL4 KEYH4>KEYDL4 KEYBIR2>KEYDL4 KEYBIR4>KEYDL4 KEYBIR6>KEYDL4 '
        'KEYA1>KEYDL4 KEYA3>KEYDL4 KEYA6>KEYDL4 KEYA8>KEYDL4 KEYAV2>KEYDL4 KEYAV4>KEYDL4 KEYCIR1>KEYDL4 '
        'KEYCIR4>KEYDL4 KEYC1>KEYDL4 KEYC2>KEYDL4 KEYC4>KEYDL4 KEYE1>KEYDL4 KEYE2>KEYDL4 KEYE3>KEYDL4 '
        'KEYE4>KEYDL4 KEYP2>KEYDL4 KEYP4>KEYDL4 KEYP6>KEYDL4 KEYEIR1>KEYDL4 KEYEIR2>KEYDL4 KEYEIR3>KEYDL4 '
        'KEYEIR4>KEYDL4 KEYM2>KEYML5 KEYM4>KEYML5 KEYM6>KEYML5 KEYM8>KEYML5 KEYB2>KEYML5 KEYB4>KEYML5 '
        'KEYB6>KEYML5 KEYH1>KEYML5 KEYH2>KEYML5 KEYH3>KEYML5 KEYH4>KEYML5 KEYBIR2>KEYML5 KEYBIR4>KEYML5 '
        'KEYBIR6>KEYML5 KEYA1>KEYML5 KEYA3>KEYML5 KEYA6>KEYML5 KEYA8>KEYML5 KEYAV2>KEYML5 KEYAV4>KEYML5 '
        'KEYCIR1>KEYML5 KEYCIR4>KEYML5 KEYC1>KEYML5 KEYC2>KEYML5 KEYC4>KEYML5 KEYE1>KEYML5 KEYE2>KEYML5 '
        'KEYE3>KEYML5 KEYE4>KEYML5 KEYP2>KEYML5 KEYP4>KEYML5 KEYP6>KEYML5 KEYEIR1>KEYML5 KEYEIR2>KEYML5 '
        'KEYEIR3>KEYML5 KEYEIR4>KEYML5 KEYM2>KEYBL5 KEYM4>KEYBL5 KEYM6>KEYBL5 KEYM8>KEYBL5 KEYB2>KEYBL5 '
        'KEYB4>KEYBL5 KEYB6>KEYBL5 KEYH1>KEYBL5 KEYH2>KEYBL5 KEYH3>KEYBL5 KEYH4>KEYBL5 KEYBIR2>KEYBL5 '
        'KEYBIR4>KEYBL5 KEYBIR6>KEYBL5 KEYA1>KEYBL5 KEYA3>KEYBL5 KEYA6>KEYBL5 KEYA8>KEYBL5 KEYAV2>KEYBL5 '
        'KEYAV4>KEYBL5 KEYCIR1>KEYBL5 KEYCIR4>KEYBL5 KEYC1>KEYBL5 KEYC2>KEYBL5 KEYC4>KEYBL5 KEYE1>KEYBL5 '
        'KEYE2>KEYBL5 KEYE3>KEYBL5 KEYE4>KEYBL5 KEYP2>KEYBL5 KEYP4>KEYBL5 KEYP6>KEYBL5 KEYEIR1>KEYBL5 '
        'KEYEIR2>KEYBL5 KEYEIR3>KEYBL5 KEYEIR4>KEYBL5 KEYDL4>KEYDL4 KEYDL4>KEYML5 KEYDL4>KEYBL5 '
        'KEYML5>KEYML5 KEYML5>KEYDL4 KEYML5>KEYBL5 KEYBL5>KEYBL5 KEYBL5>KEYDL4 KEYBL5>KEYML5'
    ),
    'TTweakerKeyToDLT': (
        'KEY1>KEYBL5 KEY2>KEYBL5 KEY4>KEYBL5 KEYIR1>KEYBL5 KEYIR4>KEYBL5 KEY1>KEYML5 KEY2>KEYML5 '
        'KEY4>KEYML5 KEYIR1>KEYML5 KEYIR4>KEYML5 KEY1>KEYDL4 KEY2>KEYDL4 KEY4>KEYDL4 KEYIR1>KEYDL4 '
        'KEYIR4>KEYDL4'
    ),
    'TTweakerInputUnit': (
        'KEY1>KEY2 KEY1>KEY4 KEY2>KEY1 KEY2>KEY4 KEY4>KEY1 KEY4>KEY2 KEYBC2>KEYBC4 KEYBC4>KEYBC2 '
        'BCNC4A>BCNC4B BCNC4B>BCNC4A SENPILL>SENPILL'
    ),
    'TTweakerKeyToNeo': (
        'KEYBC2>BCN2B KEYBC2>BCN4B KEYBC4>BCN2B KEYBC4>BCN4B DINAUX4>BCI4A KEY1>KEYB2 KEY2>KEYB2 '
        'KEY4>KEYB2 KEYIR1>KEYB2 KEYIR4>KEYB2 KEY1>KEYB4 KEY2>KEYB4 KEY4>KEYB4 KEYIR1>KEYB4 KEYIR4>KEYB4 '
        'KEY1>KEYB6 KEY2>KEYB6 KEY4>KEYB6 KEYIR1>KEYB6 KEYIR4>KEYB6 KEY1>KEYH1 KEY2>KEYH1 KEY4>KEYH1 '
        'KEYIR1>KEYH1 KEYIR4>KEYH1 KEY1>KEYH2 KEY2>KEYH2 KEY4>KEYH2 KEYIR1>KEYH2 KEYIR4>KEYH2 KEY1>KEYH3 '
        'KEY2>KEYH3 KEY4>KEYH3 KEYIR1>KEYH3 KEYIR4>KEYH3 KEY1>KEYH4 KEY2>KEYH4 KEY4>KEYH4 KEYIR1>KEYH4 '
        'KEYIR4>KEYH4 KEY1>KEYM2 KEY2>KEYM2 KEY4>KEYM2 KEYIR1>KEYM2 KEYIR4>KEYM2 KEY1>KEYM4 KEY2>KEYM4 '
        'KEY4>KEYM4 KEYIR1>KEYM4 KEYIR4>KEYM4 KEY1>KEYM8 KEY2>KEYM8 KEY4>KEYM8 KEYIR1>KEYM8 KEYIR4>KEYM8 '
        'KEY1>KEYA1 KEY2>KEYA1 KEY4>KEYA1 KEYIR1>KEYA1 KEYIR4>KEYA1 KEY1>KEYA3 KEY2>KEYA3 KEY4>KEYA3 '
        'KEYIR1>KEYA3 KEYIR4>KEYA3 KEY1>KEYA6 KEY2>KEYA6 KEY4>KEYA6 KEYIR1>KEYA6 KEYIR4>KEYA6 KEY1>KEYA8 '
        'KEY2>KEYA8 KEY4>KEYA8 KEYIR1>KEYA8 KEYIR4>KEYA8 KEY1>KEYAV2 KEY2>KEYAV2 KEY4>KEYAV2 '
        'KEYIR1>KEYAV2 KEYIR4>KEYAV2 KEY1>KEYAV4 KEY2>KEYAV4 KEY4>KEYAV4 KEYIR1>KEYAV4 KEYIR4>KEYAV4 '
        'KEY1>KEYC1 KEY1>KEYC2 KEY1>KEYC4 KEY2>KEYC1 KEY2>KEYC2 KEY2>KEYC4 KEY4>KEYC1 KEY4>KEYC2 '
        'KEY4>KEYC4 KEYIR1>KEYCIR1 KEYIR1>KEYCIR4 KEYIR4>KEYCIR1 KEYIR4>KEYCIR4'
    ),
    'TTweakerNeoToKey': (
        'KEYC1>KEY1 KEYC1>KEY2 KEYC1>KEY4 KEYC2>KEY1 KEYC2>KEY2 KEYC2>KEY4 KEYC4>KEY1 KEYC4>KEY2 '
        'KEYC4>KEY4 KEYCIR1>KEYIR1 KEYCIR1>KEYIR4 KEYCIR4>KEYIR1 KEYCIR4>KEYIR4'
    ),
    'TTweakerSENPIR': (
        'SENPIRSS>SENPIRSS SENPIRSS>SENPIROA SENPIRSS>SENPIRIA SENPIRSS>SENPIRIB SENPIROA>SENPIRSS '
        'SENPIROA>SENPIROA SENPIROA>SENPIRIA SENPIROA>SENPIRIB SENPIRIA>SENPIRSS SENPIRIA>SENPIROA '
        'SENPIRIA>SENPIRIA SENPIRIA>SENPIRIB SENPIRIB>SENPIRSS SENPIRIB>SENPIROA SENPIRIB>SENPIRIA '
        'SENPIRIB>SENPIRIB'
    ),
    'TTweakerSENLL': (
        'SENLL>SENLL SENLL>SENPILL'
    ),
}


_HOOK_KEY = ('target key-input agent overrides BeforeUnitConversionSave (TCoreKeyInputCGateAgent chain); '
             'its application/block rewrite depends on the Toolkit in-memory unit model and is not recovered')
_HOOK_DLT = ('target TCBusDynamicLabelInputCGateAgent overrides BeforeUnitConversionSave; '
             'the hook depends on the Toolkit in-memory unit model and is not recovered')
_HOOK_SENSOR = ('target sensor agent overrides BeforeUnitConversionSave (PIR, SENLL, ST7 or multisensor chain); '
                'the hook depends on the Toolkit in-memory unit model and is not recovered')
_NOT_NATIVE = 'rule recovered and target agent has no conversion hook, but no native acceptance exists yet'
NO_TWEAKER = ('no Toolkit tweaker is registered for this pair; untweaked Toolkit alignment is outside '
              'the admitted scope')
# Receipt refusal reason per class; None marks the natively accepted classes.
REFUSALS = MappingProxyType({
    'TTweakerInputUnit': None, 'TTweakerNeoToKey': _HOOK_KEY, 'TTweakerKeyToNeo': None,
    'TTweakerDLT': _HOOK_DLT, 'TTweakerKeyToDLT': _HOOK_DLT,
    'TTweakerSENPIR': _HOOK_SENSOR, 'TTweakerSENLL': _HOOK_SENSOR,
    'TTweakerPC_DAL2': _NOT_NATIVE, 'TTweakerPC_DAL2B': _NOT_NATIVE,
    'TTweakerRELDN8_TO_X': None, 'TTweakerRELDNX_TO_8': None,
    'TTweakerDIMDN_TO_DIMDU4': None, 'TTweakerDIMDU4_TO_DIMDN': None,
})
PAIR_REFUSALS = MappingProxyType({
    ('RELDN4', 'RELDN8'): ('native RELDN4 logic arrays have four elements, but the original reverse tweaker '
                          'reads eight without padding; no defined safe conversion is established'),
    ('SENPILL', 'SENPILL'): _HOOK_SENSOR,
})


def _registry():
    result = {}
    for tweaker, text in _REGISTRATIONS.items():
        for pair in text.split():
            source, target = pair.split('>')
            # GetConversionTweaker compares upper-cased types; the first registration wins.
            result.setdefault((source.upper(), target.upper()), tweaker)
    return MappingProxyType(result)


REGISTRY = _registry()

_BASE = (('Application', True), ('FirmwareVersion', False), ('Project', True), ('SerialNo', False),
         ('State', False), ('UnitAddress', True), ('UnitName', True), ('UnitType', False))
_DIN = tuple((name, name != 'Burden') for name in (
    'CheckSum', 'Burden', 'LocalToggleEnable', 'ClockGenEnable', 'LearnMode', 'LearnAnyApplication', 'LearnedFlag',
    'AreaGroupAddress', 'PowerUpDelay', 'NetworkPriority', 'LightLevel', 'LogicGA13Associations',
    'LogicGA14Associations', 'LogicGA15Associations', 'LogicGA16Associations', 'LogicFunction', 'GroupAddress',
    'MinDimmingLevel', 'MaxDimmingLevel', 'LevelStoreEnable', 'LogicLevelStoreEnable', 'InterLockingChannel',
    'RestrikeChannel', 'RestrikeDelay'))
_DIMDUX = tuple((name, True) for name in (
    'ErrorMode', 'ErrorRefreshTime', 'EnableErrorGroup', 'TriggerErrorGroup', 'TriggerErrorAcSel',
    'TriggerErrorClearAcSel', 'ErrorReportDeviceID', 'DimmingCurveBit1', 'DimmingCurveBit2'))
# The basic relay constructor explicitly makes Burden immutable. The
# bus-powered agent stops before the three full-DIN interlock/restrike fields;
# the marshalling-box agent used by RELDN8 adds no attributes to full DIN.
# Constructor-order agent attributes with their initial mutable flag:
# TDinRailOutputCGateAgent for DIMDN types, TDIMDNUXCGateAgent for DIMDU4.
AGENT_ATTRIBUTES = MappingProxyType({
    **{unit_type: _BASE + _DIN for unit_type in ('DIMDN4', 'DIMDN4F', 'DIMDN8', 'DIMDN8F')},
    'DIMDU4': _BASE + _DIN + _DIMDUX,
    **{unit_type: _BASE + _DIN for unit_type in ('RELDN8', 'RELDN12', 'RELDN4', 'RELDN8B')},
    'RELSM8': _BASE + _DIN[:-3],
    **{unit_type: CLASSIC_ATTRIBUTES for unit_type in CLASSIC_TYPES},
    **{unit_type: NEOPRO_ATTRIBUTES for unit_type in NEO_TYPES},
    **{unit_type: CLASSIC_ATTRIBUTES for unit_type in coupler.COUPLER_SOURCE_TYPES},
    **{unit_type: coupler.COUPLER_ATTRIBUTES for unit_type in coupler.COUPLER_TARGET_TYPES},
    **{unit_type: input_unit.INPUT_ATTRIBUTES for unit_type in ('BCNC4A', 'BCNC4B')},
})
# Ordered TweakParameters rules: (target attribute, 'literal' | 'from', value or source attribute).
ASSIGNMENTS = MappingProxyType({
    'TTweakerDIMDN_TO_DIMDU4': (('InterLockingChannel', 'literal', '4'), ('PowerUpDelay', 'from', 'MaxDimmingLevel'),
                                ('MaxDimmingLevel', 'literal', '0 0 0 0')),
    'TTweakerDIMDU4_TO_DIMDN': (('InterLockingChannel', 'literal', '0'), ('MaxDimmingLevel', 'from', 'PowerUpDelay'),
                                ('PowerUpDelay', 'literal', '0 0 0 0')),
})


def lookup(source_type, target_type):
    """Return the registered tweaker class name, or None."""
    return REGISTRY.get((str(source_type).upper(), str(target_type).upper()))


def admitted(source_type, target_type):
    """Return the admitted tweaker class or raise TweakerRefused before any I/O."""
    tweaker = lookup(source_type, target_type)
    if tweaker is None:
        raise TweakerRefused(source_type, target_type, None, NO_TWEAKER)
    pair_reason = PAIR_REFUSALS.get((str(source_type).upper(), str(target_type).upper()))
    if pair_reason is not None:
        raise TweakerRefused(source_type, target_type, tweaker, pair_reason)
    if REFUSALS[tweaker] is not None:
        raise TweakerRefused(source_type, target_type, tweaker, REFUSALS[tweaker])
    return tweaker


@dataclass(frozen=True)
class TweakPlan:
    source_type: str
    target_type: str
    tweaker_class: str
    writes: tuple
    not_written: MappingProxyType
    model_context: MappingProxyType | None = None

    def as_dict(self):
        result = {'format': 'cbus-toolkit-conversion-tweak-plan-v1', 'source_type': self.source_type,
                'target_type': self.target_type, 'tweaker_class': self.tweaker_class,
                'writes': [{'parameter': name, 'value': value, 'origin': origin} for name, value, origin in self.writes],
                'not_written': dict(self.not_written)}
        if self.model_context is not None:
            result['model_context'] = dict(self.model_context)
        return result


def plan_writes(source_type, target_type, source_values, target_parameters, *, target_firmware=None):
    """Model AlignUnitNoSave + TweakParameters + the PP SET gate for an admitted pair.

    ``source_values`` are the source PP strings, as Toolkit loads them into
    its attributes. ``target_parameters`` names the target's native PP
    parameters; an agent attribute without one would fail PP SET, which
    Toolkit swallows, so it is reported and not written.

    Classic-to-Neo plans require ``target_firmware='2.5.00'``; coupler-to-Neo
    plans require ``target_firmware='2.2.00'``. Both describe a fresh model
    converted from source firmware 1.2.67. They must not be applied
    to an existing edited target; ``ToolkitTweakerConversion.apply`` enforces
    the runtime source firmware and creates the fresh replacement.
    The ten non-sensor InputUnit pairs use source and target firmware 1.2.67.
    """
    tweaker = admitted(source_type, target_type)
    coupler_profile = source_type.upper() in coupler.COUPLER_SOURCE_TYPES
    model_context = None
    if tweaker == input_unit.INPUT_TWEAKER:
        try:
            input_unit.require_target_firmware(target_firmware)
        except ValueError as error:
            raise TweakerConversionError(str(error)) from error
        model_context = MappingProxyType({
            'profile': 'input-1.2.67-to-fresh-input-1.2.67',
            'source_firmware': input_unit.FIRMWARE, 'target_firmware': input_unit.FIRMWARE,
            'fresh_target_model': True, 'target_learned_flag': False, 'target_learned_flag_original': False,
            'source_has_application2': False, 'target_has_application2': False,
            'source_is_neo': False, 'target_is_neo': False,
            'indicator_brightness_property_enabled': target_type.upper() in input_unit.BRIGHTNESS_TYPES,
            'target_programming_loaded_before_hook': False,
        })
    if tweaker == KEY_TWEAKER:
        try:
            (coupler.require_target_firmware if coupler_profile else require_target_firmware)(target_firmware)
        except ValueError as error:
            raise TweakerConversionError(str(error)) from error
        model_context = MappingProxyType({
            'profile': ('coupler-1.2.67-to-fresh-neo-2.2.00' if coupler_profile
                        else 'classic-1.2.67-to-fresh-neo-2.5.00'),
            'source_firmware': SOURCE_FIRMWARE,
            'target_firmware': coupler.TARGET_FIRMWARE if coupler_profile else TARGET_FIRMWARE,
            'fresh_target_model': True, 'target_learned_flag': False, 'target_learned_flag_original': False,
            'source_has_application2': False, 'indicator_brightness_property_enabled': True,
            'target_programming_loaded_before_hook': False,
            **({'learn_mode_property_enabled': True, 'coupler_brightness_mutable_override': False}
               if coupler_profile else {}),
        })
    source_attributes = {name for name, _ in AGENT_ATTRIBUTES[source_type.upper()]}
    target = AGENT_ATTRIBUTES[target_type.upper()]
    values, mutable, origin, not_written = {}, {}, {}, {}
    for name, initially_mutable in target:
        mutable[name] = initially_mutable
        if name in source_attributes:
            value = source_values.get(name, '')
            values[name], origin[name] = value, 'copied'
            if not initially_mutable:
                not_written[name] = 'initially immutable agent attribute'
            elif value == '':
                mutable[name] = False
                not_written[name] = 'empty source value clears the mutable flag'
        else:
            not_written[name] = 'no source agent attribute; freshly created target value retained'
    if tweaker in RELAY_TWEAKERS:
        try:
            assignments = relay_assignments(tweaker, values)
        except ValueError as error:
            raise TweakerConversionError(str(error)) from error
        for name, value, value_origin in assignments:
            values[name], origin[name] = value, value_origin
            if mutable[name]:
                not_written.pop(name, None)
    if tweaker == KEY_TWEAKER:
        try:
            (coupler.apply_coupler_hooks if coupler_profile else apply_key_hooks)(
                values, mutable, origin, not_written)
        except ValueError as error:
            raise TweakerConversionError(str(error)) from error
    if tweaker == input_unit.INPUT_TWEAKER:
        input_unit.apply_input_hooks(target_type.upper(), values, mutable, origin, not_written)
    for name, kind, operand in ASSIGNMENTS.get(tweaker, ()):
        if kind == 'from':
            if origin.get(operand) != 'copied' or values[operand] == '':
                raise TweakerConversionError('Tweaker source attribute was not aligned: ' + operand)
            values[name], origin[name] = values[operand], 'moved from ' + operand
        else:
            values[name], origin[name] = operand, 'literal'
        if mutable[name]:
            not_written.pop(name, None)
    writes = []
    for name, _ in target:
        if name not in values or not mutable[name]:
            continue
        if name not in target_parameters:
            not_written[name] = 'no native target parameter; Toolkit swallows the PP SET error'
            continue
        writes.append((name, values[name], origin[name]))
    return TweakPlan(source_type.upper(), target_type.upper(), tweaker, tuple(writes),
                     MappingProxyType(dict(sorted(not_written.items()))), model_context)


def _numbers(value):
    if isinstance(value, tuple):
        return value
    try:
        return tuple(int(token.replace('$', '0x'), 0) for token in str(value).split())
    except ValueError as error:
        raise TweakerConversionError('Expected numeric PP value: ' + repr(value)) from error


def normalized(parameter, value):
    """Comparable form of one PP value under its specification."""
    if parameter.type == 'sixbit':
        return str(value).upper().ljust(parameter.array_size)[:parameter.array_size]
    return _numbers(value)


def staged(parameter, current, value):
    """Native C-Gate 3.4 PP SET result on a staged value.

    Owned native acceptance shows an over-long array is truncated and a short
    array replaces only its leading elements; sixbit text is upper-cased and
    space padded to the parameter length.
    """
    if parameter.type == 'sixbit':
        return normalized(parameter, value)
    tokens, existing = _numbers(value), normalized(parameter, current)
    size = parameter.array_size
    return tokens[:size] + existing[len(tokens):size]


def expected_values(spec: UnitSpec, defaults, plan: TweakPlan):
    result = {name: normalized(spec.parameters[name], value) for name, value in defaults.items()
              if name in spec.parameters}
    for name, value, _ in plan.writes:
        result[name] = staged(spec.parameters[name], result[name], value)
    return result


_UNIT = re.compile(r'//([A-Za-z0-9_]{1,8})/([0-9]{1,3})/p/([0-9]{1,3})')


class ToolkitTweakerConversion:
    """Create a replacement database unit the way Toolkit aligns an admitted pair.

    The source unit is read only. The replacement is created at an unused
    database address with native defaults, receives the modelled PP SET
    sequence, is saved to the C-Gate database with PP SAVE_TO_SOURCE and is
    verified in a fresh PP session. No project file is saved, nothing is
    deleted or readdressed and no physical unit is contacted.
    """
    def __init__(self, client, source_type, source_spec: UnitSpec, target_type, target_spec: UnitSpec):
        self.tweaker = admitted(source_type, target_type)
        self.source_type, self.target_type = source_type.upper(), target_type.upper()
        if self.tweaker in RELAY_TWEAKERS:
            self._relay_spec(self.source_type, source_spec, source=True)
            self._relay_spec(self.target_type, target_spec, source=False)
        if self.tweaker == input_unit.INPUT_TWEAKER:
            try:
                input_unit.validate_input_spec(self.source_type, source_spec)
                input_unit.validate_input_spec(self.target_type, target_spec)
            except ValueError as error:
                raise TweakerConversionError(str(error)) from error
        if self.tweaker == KEY_TWEAKER:
            try:
                validate_spec = (coupler.validate_coupler_spec
                                 if self.source_type in coupler.COUPLER_SOURCE_TYPES else validate_key_spec)
                validate_spec(self.source_type, source_spec, source=True)
                validate_spec(self.target_type, target_spec, source=False)
            except ValueError as error:
                raise TweakerConversionError(str(error)) from error
        self.client, self.source_spec, self.target_spec = client, source_spec, target_spec
        self.database, self.programmer = NativeDatabase(client), Programmer(client)

    @staticmethod
    def _relay_spec(unit_type, spec, *, source):
        # RELDN8B is the catalogue's explicit alias of the RELDN8 PP schema.
        expected_type = 'RELDN8' if unit_type == 'RELDN8B' else unit_type
        if not isinstance(spec, UnitSpec) or spec.unit_type.upper() != expected_type:
            raise TweakerConversionError('RELDN conversion requires the matching source and target specifications')
        for name in RELAY_FIELDS:
            parameter = spec.parameters.get(name)
            size = 16 if name == 'GroupAddress' else (4 if unit_type == 'RELDN4' else 12)
            width = 8 if name == 'GroupAddress' else 1
            if parameter is None or (parameter.type, parameter.array_size, parameter.bit_size) != ('int', size, width):
                raise TweakerConversionError(f'Unsupported {unit_type} relay PP shape for {name}')
            if source and size == 4:
                raise TweakerConversionError('RELDN4 source logic has four elements; the original reverse tweaker '
                                             'reads eight and no safe padding rule is established')

    def _unit_type(self, path):
        reply = self.client.command('DBGET ' + path + '/UnitType')
        found = [line.split('=', 1)[1].strip() for line in reply.lines if 'UnitType=' in line]
        return found[-1] if found else ''

    def _unit_firmware(self, path):
        reply = self.client.command('DBGET ' + path + '/FirmwareVersion')
        found = [line.split('=', 1)[1].strip() for line in reply.lines if 'FirmwareVersion=' in line]
        return found[-1] if found else ''

    def apply(self, source, target_address, *, target_firmware, target_catalog, tag_name=None):
        match = _UNIT.fullmatch(str(source))
        if match is None or int(match[2]) > 255 or int(match[3]) > 255:
            raise ValueError('Use a database unit path such as //PROJECT/254/p/20')
        if type(target_address) is not int or not 0 <= target_address <= 255 or target_address == int(match[3]):
            raise ValueError('Target address must be a different unit address 0..255')
        if self.tweaker in RELAY_TWEAKERS and not self.target_spec.supports_version(target_firmware):
            raise TweakerConversionError('Target firmware is outside the supplied relay specification')
        if self.tweaker == input_unit.INPUT_TWEAKER:
            try:
                input_unit.require_target_firmware(target_firmware)
            except ValueError as error:
                raise TweakerConversionError(str(error)) from error
        if self.tweaker == KEY_TWEAKER:
            try:
                validate_firmware = (coupler.require_target_firmware
                                     if self.source_type in coupler.COUPLER_SOURCE_TYPES else require_target_firmware)
                validate_firmware(target_firmware)
            except ValueError as error:
                raise TweakerConversionError(str(error)) from error
        network = source.rsplit('/p/', 1)[0]
        target = f'{network}/p/{target_address}'
        if self._unit_type(source).upper() != self.source_type:
            raise TweakerConversionError('Source database unit type differs from the requested source type')
        if self.tweaker == KEY_TWEAKER and self._unit_firmware(source) != SOURCE_FIRMWARE:
            raise TweakerConversionError('KeyToNeo conversion requires source firmware 1.2.67')
        if self.tweaker == input_unit.INPUT_TWEAKER and self._unit_firmware(source) != input_unit.FIRMWARE:
            raise TweakerConversionError('InputUnit conversion requires source firmware 1.2.67')
        with self.programmer.load(network, '/db' + source) as session:
            source_values = session.values()
        # Validate and transform the complete source before creating a target.
        # RELDN routines contain unchecked native array accesses; a short or
        # malformed image must never leave a partially created replacement.
        preflight = plan_writes(self.source_type, self.target_type, source_values, set(self.target_spec.parameters),
                                target_firmware=target_firmware)
        self.database.create_unit(network, target_address, tag_name or f'Tweaked{target_address}',
                                  self.target_type, target_firmware, catalog_number=target_catalog)
        details = {'target': target}
        with self.programmer.load(network, '/db' + target) as session:
            defaults = session.values()
            plan = preflight if set(defaults) == set(self.target_spec.parameters) else plan_writes(
                self.source_type, self.target_type, source_values, set(defaults), target_firmware=target_firmware)
            expected = expected_values(self.target_spec, defaults, plan)
            failed = {}
            for name, value, _ in plan.writes:
                try:
                    session.set(name, value)
                except (CGateError, ProgrammingCommandError) as error:
                    # Match ignored, complete PP SET rejection replies. A lost
                    # transport is uncertain: stop without further writes/save.
                    failed[name] = str(error)
                    expected[name] = normalized(self.target_spec.parameters[name], defaults[name])
            session.save_to_source()
        with self.programmer.load(network, '/db' + target) as session:
            readback = {name: normalized(self.target_spec.parameters[name], value)
                        for name, value in session.values().items() if name in self.target_spec.parameters}
        mismatches = sorted(name for name in expected if readback.get(name) != expected[name])
        details.update(plan=plan.as_dict(), failed_writes=failed, mismatches=mismatches)
        if mismatches:
            raise TweakerConversionError('Replacement readback differs from the modelled Toolkit alignment',
                                         details=details)
        source_address = source_values.get('UnitAddress', '')
        return {'format': 'cbus-toolkit-conversion-tweak-result-v1', 'source': source, 'target': target,
                'source_type': self.source_type, 'target_type': self.target_type,
                'tweaker_class': self.tweaker, 'target_firmware': target_firmware,
                'target_catalog': target_catalog, 'plan': plan.as_dict(), 'failed_writes': failed,
                'verified_parameters': len(expected), 'saved_to_database': True, 'project_saved': False,
                'source_deleted': False, 'readdressed': False, 'hardware_programmed': False,
                'parameter_address_matches_database': bool(source_address) and
                _numbers(source_address) == (target_address,)}
