#!/usr/bin/env python3
"""Build and validate the Toolkit client-side conversion tweaker registry receipt.

Toolkit 1.18 converts units without C-Gate CONVERTUNIT: it creates the
replacement unit, copies same-named writable agent attributes, applies the
tweaker registered for the (source type, target type) pair and then runs the
target agent's own conversion hook before PP SET. The receipt is the
denominator for those Toolkit-side conversions: every registration, the
recovered rule summary of each tweaker class and the resulting decision.

The facts were recovered by static inspection of the pinned original EXE and
MAP (hashes below); this script does not disassemble anything. ``--build``
turns a tab-separated registration list (call VA, source, target, class)
into the receipt; ``--validate`` checks the committed receipt's internal
consistency: counts, uniqueness, class coverage, decisions and the admitted
set used by ``cbus_toolkit.toolkit_conversion_tweakers``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/fixtures/toolkit-conversion-tweaker-registry.json'
FORMAT = 'cbus-toolkit-conversion-tweaker-registry-v1'
EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA256 = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
REGISTRATION_COUNT = 292

HOOK_KEY = ('target key-input agent overrides BeforeUnitConversionSave (TCoreKeyInputCGateAgent chain); '
            'its application/block rewrite depends on the Toolkit in-memory unit model and is not recovered')
HOOK_DLT = ('target TCBusDynamicLabelInputCGateAgent overrides BeforeUnitConversionSave; '
            'the hook depends on the Toolkit in-memory unit model and is not recovered')
HOOK_SENSOR = ('target sensor agent overrides BeforeUnitConversionSave (PIR, SENLL, ST7 or multisensor chain); '
               'the hook depends on the Toolkit in-memory unit model and is not recovered')
NOT_NATIVE = 'rule recovered and target agent has no conversion hook, but no native acceptance exists yet'

INPUT_UNIT_IMMUTABLE = ['InfraRedBank', 'EnableNightlight', 'EnableNightlightControl', 'DisableTimerFlash',
                        'FirstKeyThrowAway', 'IndicatorPressedLevel', 'TimerDuration', 'IDBacklightIllumination',
                        'PrimaryColour', 'EnableNightlightOnPCx', 'EnableNightlightOnPA6', 'DisableIR', 'DisableIRNEC']
KEY_TO_NEO_IMMUTABLE = ['ControlAppGroupAddress', 'PatchEnable', 'SceneKeySelector', 'SceneTable', 'SceneTablePointer']
DLT_IMMUTABLE = ['IRBank', 'IDBacklightIllumination', 'PrimaryColour', 'EnableNightlight', 'EnableNightlightOnPCx',
                 'EnableNightlightOnPA6', 'DisableIR', 'DisableIRNEC']
INDICATOR_REMAP = {'attribute': 'IndicatorFunction', 'element_map': {'1': 2, '3': 1},
                   'rewrite': 'space-separated decimal elements, each followed by one space'}

CLASSES = {
    'TTweakerInputUnit': {
        'recovered': True, 'renames': {}, 'immutable': INPUT_UNIT_IMMUTABLE, 'assignments': [],
        'summary': 'marks 13 Neo/IR attributes immutable (target default retained)', 'refusal': None,
        'profile': 'input-1.2.67-to-fresh-input-1.2.67',
        'source_firmware': '1.2.67', 'target_firmware': '1.2.67',
        'hook_summary': ('fresh Learn flags are true/true/false; non-Neo sources and targets with '
                         'HasApplication2=false leave group and indicator strings unchanged; '
                         'brightness is writable for KEY1/2/4 and immutable for KEYBC2/4 and BCNC4A/B')},
    'TTweakerNeoToKey': {
        'recovered': True, 'inherits': 'TTweakerInputUnit', 'renames': {}, 'immutable': INPUT_UNIT_IMMUTABLE,
        'assignments': [], 'summary': 'TTweakerInputUnit rules only', 'refusal': HOOK_KEY},
    'TTweakerKeyToNeo': {
        'recovered': True, 'inherits': 'TTweakerInputUnit', 'renames': {},
        'immutable': INPUT_UNIT_IMMUTABLE + KEY_TO_NEO_IMMUTABLE, 'assignments': [], 'element_remap': INDICATOR_REMAP,
        'summary': 'TTweakerInputUnit rules, five more immutable attributes, IndicatorFunction 1->2 and 3->1',
        'refusal': None,
        'profiles': ['classic-1.2.67-to-fresh-neo-2.5.00', 'coupler-1.2.67-to-fresh-neo-2.2.00'],
        'source_firmware': '1.2.67', 'target_firmwares': ['2.5.00', '2.2.00'],
        'hook_summary': ('fresh target Learn hook enables LearnMode/LearnAnyApp and disables LearnedFlag; '
                         'CoreKey moves group index4 to index8 and enables IndicatorBrightness; '
                         'NeoPro suppresses 13 fields for a non-NeoPro source; '
                         'CouplerPro then makes IndicatorBrightness immutable')},
    'TTweakerDLT': {
        'recovered': True, 'renames': {}, 'immutable': DLT_IMMUTABLE,
        'assignments': [{'target': 'LabelFlavourLSB', 'literal': '0'}, {'target': 'LabelFlavourMSB', 'literal': '0'}],
        'summary': 'marks eight attributes immutable and sets LabelFlavourLSB/MSB to one-element 0',
        'refusal': None, 'profile': 'source-pinned-to-fresh-dlt-2.1.00',
        'target_firmware': '2.1.00', 'evidence': 'static source recovery and owned synthetic CLI acceptance'},
    'TTweakerKeyToDLT': {
        'recovered': True, 'inherits': 'TTweakerDLT', 'renames': {},
        'immutable': DLT_IMMUTABLE + KEY_TO_NEO_IMMUTABLE,
        'assignments': [{'target': 'LabelFlavourLSB', 'literal': '0'}, {'target': 'LabelFlavourMSB', 'literal': '0'}],
        'element_remap': INDICATOR_REMAP,
        'summary': 'TTweakerDLT rules, five more immutable attributes, IndicatorFunction 1->2 and 3->1',
        'refusal': None, 'profile': 'classic-1.2.67-to-fresh-dlt-2.1.00',
        'source_firmware': '1.2.67', 'target_firmware': '2.1.00',
        'evidence': 'static source recovery and owned synthetic CLI acceptance'},
    'TTweakerSENPIR': {
        'recovered': True,
        'renames': {'PIREnablerGroup': 'EnableGroupAddress', 'PIREnablerGroupLogic': 'EnableGroupLogic',
                    'EnableGroupAddress': 'PIREnablerGroup', 'EnableGroupLogic': 'PIREnablerGroupLogic'},
        'immutable': [], 'assignments': [], 'summary': 'renames only (target <- source), no value rule',
        'refusal': HOOK_SENSOR},
    'TTweakerSENLL': {
        'recovered': True, 'renames': {'PECEnablerGroup': 'EnableGroupAddress', 'EnableGroupAddress': 'PECEnablerGroup'},
        'immutable': [], 'assignments': [], 'summary': 'renames only (target <- source), no value rule',
        'refusal': HOOK_SENSOR},
    'TTweakerDIMDN_TO_DIMDU4': {
        'recovered': True, 'renames': {}, 'immutable': [],
        'assignments': [{'target': 'InterLockingChannel', 'literal': '4'},
                        {'target': 'PowerUpDelay', 'from': 'MaxDimmingLevel'},
                        {'target': 'MaxDimmingLevel', 'literal': '0 0 0 0'}],
        'summary': 'InterLockingChannel=4, PowerUpDelay takes the aligned MaxDimmingLevel, MaxDimmingLevel=0 0 0 0',
        'refusal': None},
    'TTweakerDIMDU4_TO_DIMDN': {
        'recovered': True, 'renames': {}, 'immutable': [],
        'assignments': [{'target': 'InterLockingChannel', 'literal': '0'},
                        {'target': 'MaxDimmingLevel', 'from': 'PowerUpDelay'},
                        {'target': 'PowerUpDelay', 'literal': '0 0 0 0'}],
        'summary': 'InterLockingChannel=0, MaxDimmingLevel takes the aligned PowerUpDelay, PowerUpDelay=0 0 0 0',
        'refusal': None},
    'TTweakerPC_DAL2': {
        'recovered': True, 'renames': {}, 'immutable': [], 'assignments': [],
        'application_swap': 'Application becomes decimal element 1, one space, decimal element 0',
        'summary': 'swaps the two Application values', 'refusal': NOT_NATIVE},
    'TTweakerPC_DAL2B': {
        'recovered': True, 'renames': {}, 'immutable': [], 'assignments': [],
        'application_swap': 'Application becomes decimal element 1, one space, decimal element 0',
        'summary': 'swaps the two Application values', 'refusal': NOT_NATIVE},
    'TTweakerRELDN8_TO_X': {
        'recovered': True, 'touched': ['GroupAddress', 'LogicGA13Associations', 'LogicGA14Associations',
                                        'LogicGA15Associations', 'LogicGA16Associations'],
        'summary': 'Group=s[1:5]+s[7:11]+[255]*4+s[12:16]; each logic=s[1:5]+s[7:11]+[0]*4',
        'refusal': None},
    'TTweakerRELDNX_TO_8': {
        'recovered': True, 'touched': ['GroupAddress', 'LogicGA13Associations', 'LogicGA14Associations',
                                        'LogicGA15Associations', 'LogicGA16Associations'],
        'summary': 'Group=[255]+s[0:4]+[255]*2+s[4:8]+[255]+s[12:16]; each logic=[0]+s[0:4]+[0]*2+s[4:8]+[0]',
        'refusal': None},
}
PAIR_REFUSALS = {
    **{('KEYM6', target): ('KEYM6 has no recovered static Toolkit unit factory/model; '
                          'its DLT registrations remain refused')
       for target in ('KEYDL4', 'KEYML5', 'KEYBL5')},
    **{(source, target): ('KEYBIR source specification identity or catalogue alias is not established '
                          'for the recovered DLT profile')
       for source in ('KEYBIR2', 'KEYBIR4', 'KEYBIR6') for target in ('KEYDL4', 'KEYML5', 'KEYBL5')},
    ('RELDN4', 'RELDN8'): ('native RELDN4 logic arrays have four elements, but the original reverse tweaker '
                          'reads eight without padding; no defined safe conversion is established'),
    ('SENPILL', 'SENPILL'): HOOK_SENSOR,
}
_BASE = [('Application', True), ('FirmwareVersion', False), ('Project', True), ('SerialNo', False),
         ('State', False), ('UnitAddress', True), ('UnitName', True), ('UnitType', False)]
_DIN = [(name, name != 'Burden') for name in (
    'CheckSum', 'Burden', 'LocalToggleEnable', 'ClockGenEnable', 'LearnMode', 'LearnAnyApplication', 'LearnedFlag',
    'AreaGroupAddress', 'PowerUpDelay', 'NetworkPriority', 'LightLevel', 'LogicGA13Associations',
    'LogicGA14Associations', 'LogicGA15Associations', 'LogicGA16Associations', 'LogicFunction', 'GroupAddress',
    'MinDimmingLevel', 'MaxDimmingLevel', 'LevelStoreEnable', 'LogicLevelStoreEnable', 'InterLockingChannel',
    'RestrikeChannel', 'RestrikeDelay')]
_DIMDUX = [(name, True) for name in (
    'ErrorMode', 'ErrorRefreshTime', 'EnableErrorGroup', 'TriggerErrorGroup', 'TriggerErrorAcSel',
    'TriggerErrorClearAcSel', 'ErrorReportDeviceID', 'DimmingCurveBit1', 'DimmingCurveBit2')]
# Constructor order and initial mutable flag of the agents used by admitted pairs.
AGENTS = {
    'TDinRailOutputCGateAgent': {'unit_types': ['DIMDN4', 'DIMDN4F', 'DIMDN8', 'DIMDN8F', 'RELDN12', 'RELDN4', 'RELDN8B'],
                                 'overrides_before_unit_conversion_save': False,
                                 'attributes': [[n, m] for n, m in _BASE + _DIN]},
    'TDIMDNUXCGateAgent': {'unit_types': ['DIMDU4'], 'overrides_before_unit_conversion_save': False,
                           'attributes': [[n, m] for n, m in _BASE + _DIN + _DIMDUX]},
    'TMarshallingBoxCGateAgent': {'unit_types': ['RELDN8'], 'overrides_before_unit_conversion_save': False,
                                  'attributes': [[n, m] for n, m in _BASE + _DIN]},
    'TBusPoweredDinRailOutputCGateAgent': {'unit_types': ['RELSM8'], 'overrides_before_unit_conversion_save': False,
                                          'attributes': [[n, m] for n, m in _BASE + _DIN[:-3]]},
}
# Source-pinned modern key profile; these are constructor flags, before hooks.
AGENTS.update({'TCBusKeyInputCGateAgent': {'unit_types': ['KEY1', 'KEY2', 'KEY4', 'KEYIR1', 'KEYIR4',
                                                      'KEYBC2', 'KEYBC4', 'DINAUX4'],
                             'overrides_before_unit_conversion_save': True,
                             'conversion_hook_profile': 'input-1.2.67-to-fresh-input-1.2.67',
                             'source_firmware': '1.2.67',
                             'target_firmware': '1.2.67',
                             'attributes': [['Application', True],
                                            ['FirmwareVersion', False],
                                            ['Project', True],
                                            ['SerialNo', False],
                                            ['State', False],
                                            ['UnitAddress', True],
                                            ['UnitName', True],
                                            ['UnitType', False],
                                            ['LearnAnyApp', True],
                                            ['LearnMode', True],
                                            ['LearnedFlag', True],
                                            ['AreaGroupAddress', True],
                                            ['StatusReportInterval', True],
                                            ['GroupAddress', True],
                                            ['DebounceTime', True],
                                            ['IndicatorBrightness', False],
                                            ['LongPressTime', True],
                                            ['EEPROMLevelStore', True],
                                            ['LightIndex', True],
                                            ['LightLevel', True],
                                            ['LightLevelStore1', True],
                                            ['LightLevelStore2', True],
                                            ['RampRate', True],
                                            ['InfraRedBank', True],
                                            ['JPCommand', True],
                                            ['SRCommand', True],
                                            ['LPCommand', True],
                                            ['LRCommand', True],
                                            ['BlockAllocation', True],
                                            ['IndicatorBlockAssignment', True],
                                            ['IndicatorFunction', True],
                                            ['TimerHighByte', True],
                                            ['TimerLowByte', True],
                                            ['TimerExpiryCommand', True],
                                            ['GAVBroadcastFlag', False]]},
 'TCBusNeoProInputCGateAgent': {'unit_types': ['KEYB2',
                                               'KEYB4',
                                               'KEYB6',
                                               'KEYH1',
                                               'KEYH2',
                                               'KEYH3',
                                               'KEYH4',
                                               'KEYM2',
                                               'KEYM4',
                                               'KEYM8',
                                               'KEYA1',
                                               'KEYA3',
                                               'KEYA6',
                                               'KEYA8',
                                               'KEYAV2',
                                               'KEYAV4',
                                               'KEYC1',
                                               'KEYC2',
                                               'KEYC4',
                                               'KEYCIR1',
                                               'KEYCIR4'],
                                'overrides_before_unit_conversion_save': True,
                                'conversion_hook_profile': 'classic-1.2.67-to-fresh-neo-2.5.00',
                                'target_firmware': '2.5.00',
                                'attributes': [['Application', True],
                                               ['FirmwareVersion', False],
                                               ['Project', True],
                                               ['SerialNo', False],
                                               ['State', False],
                                               ['UnitAddress', True],
                                               ['UnitName', True],
                                               ['UnitType', False],
                                               ['LearnAnyApp', True],
                                               ['LearnMode', True],
                                               ['LearnedFlag', True],
                                               ['AreaGroupAddress', True],
                                               ['StatusReportInterval', True],
                                               ['GroupAddress', True],
                                               ['DebounceTime', True],
                                               ['IndicatorBrightness', False],
                                               ['LongPressTime', True],
                                               ['EEPROMLevelStore', True],
                                               ['LightIndex', True],
                                               ['LightLevel', True],
                                               ['LightLevelStore1', True],
                                               ['LightLevelStore2', True],
                                               ['RampRate', True],
                                               ['IRBank', True],
                                               ['JPCommand', True],
                                               ['SRCommand', True],
                                               ['LPCommand', True],
                                               ['LRCommand', True],
                                               ['BlockAllocation', True],
                                               ['IndicatorBlockAssignment', True],
                                               ['IndicatorFunction', True],
                                               ['TimerHighByte', True],
                                               ['TimerLowByte', True],
                                               ['TimerExpiryCommand', True],
                                               ['ControlAppGroupAddress', True],
                                               ['EnableNightlight', True],
                                               ['EnableNightlightControl', True],
                                               ['DisableTimerFlash', True],
                                               ['FirstKeyThrowAway', True],
                                               ['IndicatorPressedLevel', True],
                                               ['TimerDuration', True],
                                               ['PatchEnable', True],
                                               ['SceneKeySelector', True],
                                               ['SceneTable', True],
                                               ['SceneTablePointer', True],
                                               ['DisableIR', True],
                                               ['IDBacklightIllumination', True],
                                               ['EnableNightlightOnPCx', True],
                                               ['EnableNightlightOnPA6', True],
                                               ['PrimaryColour', True],
                                               ['DisableIRNEC', True],
                                               ['KeyDisableGroup', True],
                                               ['KeyDisableGroupInvert', True],
                                               ['CorridorLinkEnable', True],
                                               ['CorridorMasterGroup', True],
                                               ['CorridorGroupBlock', True],
                                               ['CorridorOfficeGroupBlock', True],
                                               ['JoinPrimaryApplication', True],
                                               ['JoinSecondaryApplication', True],
                                               ['DualJoinPrimaryApplication', True],
                                               ['DualJoinSecondaryApplication', True],
                                               ['SecondApplicationBlocks', True],
                                               ['NightlightColour', True]]}})

# The coupler constructor inherits the 62 CoreNeoPro attributes directly, then
# adds its two fields; it does not call the NeoPro NightlightColour constructor.
AGENTS['TCBusCouplerProInputCGateAgent'] = {
    'unit_types': ['BCN2B', 'BCN4B', 'BCI4A'],
    'overrides_before_unit_conversion_save': True,
    'conversion_hook_profile': 'coupler-1.2.67-to-fresh-neo-2.2.00',
    'target_firmware': '2.2.00',
    'attributes': AGENTS['TCBusNeoProInputCGateAgent']['attributes'][:-1]
                  + [['BistableSwitchBlock', True], ['GroupAssertOnPowerup', True]],
}
AGENTS['TBCNC4CGateAgent'] = {
    'unit_types': ['BCNC4A', 'BCNC4B'],
    'overrides_before_unit_conversion_save': True,
    'conversion_hook_profile': 'input-1.2.67-to-fresh-input-1.2.67',
    'source_firmware': '1.2.67', 'target_firmware': '1.2.67',
    'attributes': AGENTS['TCBusKeyInputCGateAgent']['attributes'],
}

NATIVE_ACCEPTED = ('TTweakerDIMDN_TO_DIMDU4', 'TTweakerDIMDU4_TO_DIMDN', 'TTweakerRELDN8_TO_X', 'TTweakerRELDNX_TO_8',
                   'TTweakerKeyToNeo', 'TTweakerInputUnit')
SOURCE_ADMITTED = ('TTweakerDLT', 'TTweakerKeyToDLT')
# This receipt contains derived constructor names/flags and digests only.
DLT_PROOF = json.loads((ROOT / 'research/fixtures/toolkit-dlt-conversion-source-proof.json').read_text())
DLT_PROFILE = 'source-pinned-to-fresh-dlt-2.1.00'
AGENTS['TCBusNeoProInputCGateAgent']['unit_types'] = sorted(set(
    AGENTS['TCBusNeoProInputCGateAgent']['unit_types']) | {
        t for t in DLT_PROOF['source_profiles']['modern']['types'] if not t.startswith('KEYE')})
AGENTS['TCBusKEYExCGateAgent'] = {
    'unit_types': [t for t in DLT_PROOF['source_profiles']['modern']['types'] if t.startswith('KEYE')],
    'overrides_before_unit_conversion_save': True, 'conversion_role': 'source_only',
    'attributes': AGENTS['TCBusNeoProInputCGateAgent']['attributes'] + [['KeyMask', True]],
}
AGENTS['TCBusDynamicLabelInputCGateAgent'] = {
    'unit_types': ['KEYDL4', 'KEYML5', 'KEYBL5'], 'overrides_before_unit_conversion_save': True,
    'conversion_hook_profile': DLT_PROFILE, 'target_firmware': '2.1.00',
    'attributes': DLT_PROOF['constructor_attributes'],
}
TOOLKIT_SEMANTICS = {
    'uses_cgate_convertunit': False,
    'lookup': 'case-insensitive (source type, target type); first registration wins',
    'alignment': ('for each target agent attribute, copy the same-named source attribute (never OID); an empty '
                  'source value clears the target mutable flag; when absent, a tweaker rename names the source '
                  'attribute; then TweakParameters, then target BeforeUnitConversionSave'),
    'immutable': 'SetMutableFalse clears the mutable flag, so no PP SET is issued and the target default remains',
    'pp_set': ('ParameterProgrammingSetAll issues PP SET, in attribute order, only for attributes that are both '
               'mutable and aligned; a failed PP SET is caught and ignored'),
    'initially_immutable_base_attributes': ['FirmwareVersion', 'SerialNo', 'State', 'UnitType'],
}
LIMITS = ('Static facts from the pinned Toolkit EXE/MAP; no original code was executed. Database metadata '
          '(tag, description, serial, readdress, source deletion and project save) is outside this receipt. '
          'The DIMDUx and RELDN classes are admitted with native C-Gate PP acceptance, except RELDN4 to RELDN8: '
          'its four-element source logic would cause undefined original array reads. '
          'Classic KeyToNeo conversion admits 93 registrations only for source firmware 1.2.67 and a fresh '
          'target model at 2.5.00. Its five coupler/auxiliary registrations use a separate fresh 2.2.00 '
          'target model profile with the CouplerPro brightness suppression. '
          'InputUnit admits ten non-sensor registrations at source and fresh-target firmware 1.2.67; '
          'its SENPILL self-conversion remains refused pending the separate sensor hook. '
          'DLT/KeyToDLT admits 120 additional registrations with source recovery and owned synthetic '
          'CLI proof, separately from native acceptance: classic 1.2.67, modern 2.5.00 and DLT 2.1.00 '
          'sources into fresh DLT 2.1.00. KEYM6 has three registrations without a recovered factory model. '
          'Every other registered or unregistered pair is refused with the reason recorded here. '
          'Static evidence is separate from native C-Gate execution and does not establish original '
          'Toolkit GUI or physical acceptance.')


def build(tsv: Path) -> dict:
    rows = []
    for line in tsv.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        call_va, source, target, tweaker = line.split('\t')
        spec = CLASSES[tweaker]
        reason = PAIR_REFUSALS.get((source.upper(), target.upper()), spec['refusal'])
        admitted = tweaker in NATIVE_ACCEPTED + SOURCE_ADMITTED and reason is None
        rows.append({'source': source, 'target': target, 'tweaker_class': tweaker, 'call_va': call_va,
                     'decision': 'admitted' if admitted else 'refused',
                     'refusal_reason': reason})
    counts = Counter(row['tweaker_class'] for row in rows)
    return {
        'format': FORMAT, 'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_code_executed': False, 'registration_count': len(rows),
        'class_counts': dict(sorted(counts.items())), 'toolkit_semantics': TOOLKIT_SEMANTICS,
        'classes': {name: {**CLASSES[name], 'call_sites': counts[name]} for name in sorted(CLASSES)},
        'agents': AGENTS, 'native_accepted_classes': list(NATIVE_ACCEPTED),
        'source_admitted_classes': list(SOURCE_ADMITTED),
        'pair_refusals': [{'source': s, 'target': t, 'reason': reason} for (s, t), reason in PAIR_REFUSALS.items()],
        'registrations': rows, 'limits': LIMITS,
    }


def validate(receipt: dict) -> list[str]:
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    check(receipt.get('format') == FORMAT, 'format')
    check(receipt.get('original_exe_sha256') == EXE_SHA256 and receipt.get('original_map_sha256') == MAP_SHA256, 'input hashes')
    rows = receipt.get('registrations', [])
    check(len(rows) == receipt.get('registration_count') == REGISTRATION_COUNT, 'registration count')
    keys = [(row['source'].upper(), row['target'].upper()) for row in rows]
    check(len(set(keys)) == len(keys), 'duplicate (source, target) registration')
    check(len({row['call_va'] for row in rows}) == len(rows), 'duplicate call site')
    counts = Counter(row['tweaker_class'] for row in rows)
    check(dict(sorted(counts.items())) == receipt.get('class_counts'), 'class counts')
    classes = receipt.get('classes', {})
    check(set(classes) == set(counts), 'class coverage')
    for name, spec in classes.items():
        check(spec.get('call_sites') == counts.get(name), 'call sites for ' + name)
        check(bool(spec.get('summary')), 'summary for ' + name)
        admitted = name in receipt.get('native_accepted_classes', []) + receipt.get('source_admitted_classes', [])
        check(admitted == (spec.get('refusal') is None), 'refusal/admission for ' + name)
        check(admitted <= bool(spec.get('recovered')), 'admitted class must be recovered: ' + name)
        for rule in spec.get('assignments', []):
            check(('literal' in rule) != ('from' in rule), 'assignment shape for ' + name)
    pair_refusals = {(item['source'], item['target']): item['reason'] for item in receipt.get('pair_refusals', [])}
    check(pair_refusals == PAIR_REFUSALS, 'pair-specific refusals')
    for row in rows:
        spec = classes.get(row['tweaker_class'], {})
        reason = pair_refusals.get((row['source'], row['target']), spec.get('refusal'))
        admitted = row['tweaker_class'] in (receipt.get('native_accepted_classes', [])
                                           + receipt.get('source_admitted_classes', [])) and reason is None
        check(row['decision'] == ('admitted' if admitted else 'refused'), 'decision ' + repr(row))
        check(row['refusal_reason'] == reason, 'reason ' + repr(row))
    agents = receipt.get('agents', {})
    covered = {unit for agent in agents.values() for unit in agent['unit_types']}
    for row in rows:
        if row['decision'] == 'admitted':
            check({row['source'], row['target']} <= covered, 'agent attributes for ' + repr(row))
    for name, agent in agents.items():
        names = [attribute[0] for attribute in agent['attributes']]
        expected_dlt = name == 'TCBusDynamicLabelInputCGateAgent'
        check((agent['attributes'] == DLT_PROOF['constructor_attributes']) if expected_dlt
              else len(set(names)) == len(names), 'duplicate agent attribute in ' + name)
        source_only = agent.get('conversion_role') == 'source_only'
        if source_only:
            check(not any(row['target'] in agent['unit_types'] and row['decision'] == 'admitted' for row in rows),
                  'source-only agent used as an admitted target in ' + name)
        check(not agent['overrides_before_unit_conversion_save'] or source_only
              or agent.get('conversion_hook_profile') in ('classic-1.2.67-to-fresh-neo-2.5.00',
                                                          'coupler-1.2.67-to-fresh-neo-2.2.00',
                                                          'input-1.2.67-to-fresh-input-1.2.67', DLT_PROFILE),
              'admitted agent hook in ' + name)
    text = json.dumps(receipt)
    for marker in ('<Param', 'DefaultValue', '<Address>'):
        check(marker not in text, 'unsanitized marker ' + marker)
    return errors


def render(receipt: dict) -> str:
    return json.dumps(receipt, indent=1) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--build', type=Path, help='tab-separated call VA, source, target, class')
    group.add_argument('--validate', action='store_true')
    parser.add_argument('--output', type=Path, default=RECEIPT)
    args = parser.parse_args()
    if args.build:
        receipt = build(args.build)
        errors = validate(receipt)
        if errors:
            print('\n'.join(errors), file=sys.stderr)
            return 1
        args.output.write_text(render(receipt), encoding='utf-8')
        return 0
    errors = validate(json.loads(args.output.read_text(encoding='utf-8')))
    print('\n'.join(errors) if errors else 'ok')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
