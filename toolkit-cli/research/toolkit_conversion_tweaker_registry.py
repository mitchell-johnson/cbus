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
        'summary': 'marks 13 Neo/IR attributes immutable (target default retained)', 'refusal': HOOK_KEY},
    'TTweakerNeoToKey': {
        'recovered': True, 'inherits': 'TTweakerInputUnit', 'renames': {}, 'immutable': INPUT_UNIT_IMMUTABLE,
        'assignments': [], 'summary': 'TTweakerInputUnit rules only', 'refusal': HOOK_KEY},
    'TTweakerKeyToNeo': {
        'recovered': True, 'inherits': 'TTweakerInputUnit', 'renames': {},
        'immutable': INPUT_UNIT_IMMUTABLE + KEY_TO_NEO_IMMUTABLE, 'assignments': [], 'element_remap': INDICATOR_REMAP,
        'summary': 'TTweakerInputUnit rules, five more immutable attributes, IndicatorFunction 1->2 and 3->1',
        'refusal': HOOK_KEY},
    'TTweakerDLT': {
        'recovered': True, 'renames': {}, 'immutable': DLT_IMMUTABLE,
        'assignments': [{'target': 'LabelFlavourLSB', 'literal': '0'}, {'target': 'LabelFlavourMSB', 'literal': '0'}],
        'summary': 'marks eight attributes immutable and sets LabelFlavourLSB/MSB to 0', 'refusal': HOOK_DLT},
    'TTweakerKeyToDLT': {
        'recovered': True, 'inherits': 'TTweakerDLT', 'renames': {},
        'immutable': DLT_IMMUTABLE + KEY_TO_NEO_IMMUTABLE,
        'assignments': [{'target': 'LabelFlavourLSB', 'literal': '0'}, {'target': 'LabelFlavourMSB', 'literal': '0'}],
        'element_remap': INDICATOR_REMAP,
        'summary': 'TTweakerDLT rules, five more immutable attributes, IndicatorFunction 1->2 and 3->1',
        'refusal': HOOK_DLT},
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
        'recovered': False, 'touched': ['GroupAddress', 'LogicGA13Associations', 'LogicGA14Associations',
                                        'LogicGA15Associations', 'LogicGA16Associations'],
        'summary': 'repacks GroupAddress and LogicGA13-16 arrays; element rule not recovered',
        'refusal': 'tweaker value rule for GroupAddress/LogicGA13-16 repacking is not recovered'},
    'TTweakerRELDNX_TO_8': {
        'recovered': False, 'touched': ['GroupAddress', 'LogicGA13Associations', 'LogicGA14Associations',
                                        'LogicGA15Associations', 'LogicGA16Associations'],
        'summary': 'repacks GroupAddress and LogicGA13-16 arrays; element rule not recovered',
        'refusal': 'tweaker value rule for GroupAddress/LogicGA13-16 repacking is not recovered'},
}
_BASE = [('Application', True), ('FirmwareVersion', False), ('Project', True), ('SerialNo', False),
         ('State', False), ('UnitAddress', True), ('UnitName', True), ('UnitType', False)]
_DIN = [(name, True) for name in (
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
    'TDinRailOutputCGateAgent': {'unit_types': ['DIMDN4', 'DIMDN4F', 'DIMDN8', 'DIMDN8F'],
                                 'overrides_before_unit_conversion_save': False,
                                 'attributes': [[n, m] for n, m in _BASE + _DIN]},
    'TDIMDNUXCGateAgent': {'unit_types': ['DIMDU4'], 'overrides_before_unit_conversion_save': False,
                           'attributes': [[n, m] for n, m in _BASE + _DIN + _DIMDUX]},
}
NATIVE_ACCEPTED = ('TTweakerDIMDN_TO_DIMDU4', 'TTweakerDIMDU4_TO_DIMDN')
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
          'Only the DIMDUx classes are admitted, with native C-Gate PP acceptance; every other registered or '
          'unregistered pair is refused with the reason recorded here.')


def build(tsv: Path) -> dict:
    rows = []
    for line in tsv.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        call_va, source, target, tweaker = line.split('\t')
        spec = CLASSES[tweaker]
        admitted = tweaker in NATIVE_ACCEPTED
        rows.append({'source': source, 'target': target, 'tweaker_class': tweaker, 'call_va': call_va,
                     'decision': 'admitted' if admitted else 'refused',
                     'refusal_reason': None if admitted else spec['refusal']})
    counts = Counter(row['tweaker_class'] for row in rows)
    return {
        'format': FORMAT, 'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_code_executed': False, 'registration_count': len(rows),
        'class_counts': dict(sorted(counts.items())), 'toolkit_semantics': TOOLKIT_SEMANTICS,
        'classes': {name: {**CLASSES[name], 'call_sites': counts[name]} for name in sorted(CLASSES)},
        'agents': AGENTS, 'native_accepted_classes': list(NATIVE_ACCEPTED),
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
        admitted = name in receipt.get('native_accepted_classes', [])
        check(admitted == (spec.get('refusal') is None), 'refusal/admission for ' + name)
        check(admitted <= bool(spec.get('recovered')), 'admitted class must be recovered: ' + name)
        for rule in spec.get('assignments', []):
            check(('literal' in rule) != ('from' in rule), 'assignment shape for ' + name)
    for row in rows:
        spec = classes.get(row['tweaker_class'], {})
        admitted = row['tweaker_class'] in receipt.get('native_accepted_classes', [])
        check(row['decision'] == ('admitted' if admitted else 'refused'), 'decision ' + repr(row))
        check(row['refusal_reason'] == spec.get('refusal'), 'reason ' + repr(row))
    agents = receipt.get('agents', {})
    covered = {unit for agent in agents.values() for unit in agent['unit_types']}
    for row in rows:
        if row['decision'] == 'admitted':
            check({row['source'], row['target']} <= covered, 'agent attributes for ' + repr(row))
    for name, agent in agents.items():
        names = [attribute[0] for attribute in agent['attributes']]
        check(len(set(names)) == len(names), 'duplicate agent attribute in ' + name)
        check(not agent['overrides_before_unit_conversion_save'], 'admitted agent hook in ' + name)
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
