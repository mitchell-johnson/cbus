"""Pin PIR report classes, loaders, dependency branches and macro source tables.

All checks read the explicit pinned original EXE/MAP offline. Macro comparisons
use independently decoded native registration tables and refresh rules; they
are source comparisons, not original loader execution or generated-page capture.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import sys
import struct

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY
from project_documentor_classic_key_macro_original import SourceMacroOracle
from key_preset_families import Image, subsets

BODIES = ('CIS_TPIRDocumentor.TPIRDocumentor.DocumentHTML',
          'CIS_TST7PIRSensorDocumentor.TST7PIRSensorDocumentor.DocumentHTML')
METHODS = BODIES + (
    'CIS_TCBusPirSensorInputCGateAgent.GetEnableGroup',
    'CIS_TCBusPirSensorInputCGateAgent.GetKeyValues',
    'CIS_TCBusPirSensorInputCGateAgent.TCBusPirSensorInputCGateAgent.InternalCreate',
    'CIS_TCBusPirSensorInputCGateAgent.TCBusPirSensorInputCGateAgent.AfterLoadProgrammingInformation',
    'CIS_TSENPIRSS.TSENPIRSS.RefreshMacroFunctionOverrides',
    'CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.InternalCreate',
    'CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.AfterLoadProgrammingInformation',
    'CIS_TCBusST7SensorCGateAgent.TCBusST7PIRSensorCGateAgent.AfterLoadProgrammingInformation',
    'CIS_TCBusST7SensorUnit.TCBusST7PIRSensorUnit.RefreshKeyBlockOverrides',
    'CIS_TCBusST7SensorUnit.TCBusST7PIRSensorUnit.RefreshMacroFunctionOverrides',
    'CIS_TCBusPirSensorInputUnit.TCBusPirSensorInputUnit.DescribeOtherGroupDependencyAdvanced',
    'CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.DescribeInputGroupDependencyAdvanced',
    'CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.DescribeOtherGroupDependencyAdvanced',
    'CIS_TKeyMacroFunction.TKeyMacroFunction.ReconcileTemplateAndGroup',
    'CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.LoadCorridorLinkAttributes',
    'CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation',
)


def inspect(executable, mapping):
    exe, symbols = executable.read_bytes(), mapping.read_bytes()
    if hashlib.sha256(exe).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(exe, symbols)
    methods = {name: image.method(name) for name in METHODS}
    rows = list(methods.values())
    instructions = lambda row: [(op, args) for _, op, args in row['instructions']]
    def calls(row):
        return [sorted(image.symbols.get(int(args, 16), {'?'}))[0] for _, op, args in row['instructions']
                if op == 'call' and args.startswith('0x')]
    def resources(row):
        result = []
        for _, op, args in row['instructions']:
            if op == 'mov' and args.startswith('eax, '):
                for token in re.findall(r'0x[0-9a-f]{6,8}', args):
                    address = int(token, 16)
                    try:
                        value = image.resource(image.dword(address) if 'dword ptr' in args else address)
                    except struct.error:
                        value = None
                    if value is not None:
                        result.append(value)
        return result
    checks = {}
    for index, body in enumerate(rows[:2]):
        checks[f'body{index}:classic_first'] = calls(body)[0].endswith('TClassicKeyInputDocumentor.DocumentHTML')
        checks[f'body{index}:labels'] = body['literals'] == ['<br />', 'PIR Enable/Disable Group: ', '<br />',
                                                          'PIR Disable Group: ', '<br />', 'PIR Enable Group: ', '<br />']
        checks[f'body{index}:unused_before_polarity'] = next(i for i, name in enumerate(calls(body)) if name.endswith('IsUnused')) < next(i for i, name in enumerate(calls(body)) if name.endswith('GroupOff'))
        cls = BODIES[index].split('.')[0] + '..' + BODIES[index].split('.')[1]
        checks[f'body{index}:classic_action'] = image.slot(cls, 0x80).endswith('TClassicKeyInputDocumentor.ActionSelectorUse')
    checks.update({
        'old_enable_primary_application': ('call', 'dword ptr [edx + 0xb0]') in instructions(rows[2]),
        'old_enable_logic_zero_inverts': any(op == 'sete' for op, _ in instructions(rows[2])),
        'corridor_unsupported_only_gates_active': ('jmp', '0xced0a8') in instructions(rows[16]),
        'corridor_group_primary_unconditional': ('mov', 'eax, dword ptr [eax + 0x1b0]') in instructions(rows[16]) and ('call', 'dword ptr [edx + 0xb0]') in instructions(rows[16]),
        'st7_corridor_attribute_rename': ('mov', 'eax, dword ptr [eax + 0x1b0]') in instructions(rows[7]),
        'old_enable_pp_names': rows[4]['literals'] == ['EnableGroupAddress', 'EnableGroupLogic'],
        'old_loader_core_first': calls(rows[5])[0].endswith('TCoreKeyInputCGateAgent.AfterLoadProgrammingInformation'),
        'old_pir_macro_override': any(name.endswith('SetMacroFunctionSENPIROverride') for name in calls(rows[6])),
        'st7_sensor_loader_neopro_first': calls(rows[8])[0].endswith('TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation'),
        'st7_pir_loader_multisensor_first': calls(rows[9])[0].endswith('TCBusST7MultisensorCGateAgent.AfterLoadProgrammingInformation'),
        'st7_block_override_no_calls': not calls(rows[10]),
        'st7_pir_macro_override': any(name.endswith('SetMacroFunctionSENPIROverride') for name in calls(rows[11])),
        'old_other_label': resources(rows[12]) == ['PIR Enable Group'],
        'st7_input_labels': resources(rows[13]) == ['Key %d', 'Light Level Maintenance', 'Block (Unused)', 'Scene %d', 'Scene %d (Unused)'],
        'st7_input_unused_gate': ('sub', 'al, 0x10') in instructions(rows[13]),
        'st7_other_labels': resources(rows[14]) == ['Light Level Maintenance Enable', 'Occupancy Enable', 'Corridor Link', 'Light Level Broadcast Group'],
        'st7_other_neopro_first': calls(rows[14])[0].endswith('TCBusNeoProInputUnit.DescribeOtherGroupDependencyAdvanced'),
        'st7_broadcast_ignores_active': not any(name.endswith('GetLightLevelBroadcastActive') for name in calls(rows[14])),
        'st7_enable_pp_names': {'PIREnablerGroup', 'PIREnablerGroupLogic', 'CorridorLinkEnablerGroup', 'PECEnablerGroup', 'PECFunctionActive', 'PECFunctionBlock', 'BroadcastBlock'} <= set(rows[7]['literals']),
    })
    registrations = []
    for kind, cls, low, high in image.registrations(UNIT_FACTORY)[0]:
        if kind not in {'SENPIRSS', 'SENPIROA', 'SENPIRIA', 'SENPIRIB'} or 'CIS_TSENPIRSS..' not in cls:
            continue
        slots = {hex(slot): image.slot(cls, slot) for slot in (0x128, 0x12c, 0x130, 0x16c, 0x190, 0x194, 0x19c, 0x1a0, 0x1a8, 0x1c4)}
        key = kind + ':' + low
        checks[key + ':four_blocks'] = ('mov', 'dword ptr [ebp - 8], 4') in instructions(image.method(slots['0x16c']))
        checks[key + ':four_physical_keys'] = ('mov', 'dword ptr [ebp - 8], 4') in instructions(image.method(slots['0x190']))
        checks[key + ':stored_levels_enabled'] = ('mov', 'byte ptr [ebp - 5], 1') in instructions(image.method(slots['0x1a0']))
        checks[key + ':primary_subset_senpir'] = image.method(slots['0x1c4'])['literals'] == ['SENPIR']
        checks[key + ':brightness_disabled'] = ('mov', 'byte ptr [ebp - 5], 0') in instructions(image.method(slots['0x1a8']))
        checks[key + ':output_base'] = slots['0x12c'].endswith('TCBUSUnit.DescribeOutputGroupDependencyAdvanced')
        if 'TST7' in cls:
            slots['0x1e8'] = image.slot(cls, 0x1e8)
            checks[key + ':secondary_subset_senpir'] = image.method(slots['0x1e8'])['literals'] == ['SENPIR']
            for slot, label in ((0x234, 'join'), (0x238, 'dual_join'), (0x244, 'corridor'), (0x260, 'key_disable')):
                slots[hex(slot)] = image.slot(cls, slot)
                checks[key + ':' + label + '_unsupported'] = ('mov', 'byte ptr [ebp - 5], 0') in instructions(image.method(slots[hex(slot)]))
        registrations.append({'unit_type': kind, 'class': cls, 'firmware': [low, high], 'slots': slots})
    failures = [key for key, passed in checks.items() if not passed]
    if failures:
        raise ValueError('PIR source differs: ' + ', '.join(failures))
    return {'format': 'cbus-project-documentor-pir-static-v1', 'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
        'checks': checks, 'registrations': registrations, 'methods': {name: {'start': hex(row['start']),
        'end': hex(row['end']), 'sha256': row['sha256'], 'resources': resources(row)} for name, row in methods.items()},
        'original_generated_page_comparison': 'not_obtained', 'original_loader_execution': 'not_executed'}


def compare_macros(executable, mapping):
    from cbus_toolkit.project_documentation_pir import pir_macro
    oracle = SourceMacroOracle(executable, mapping)
    permitted = subsets(Image(executable, mapping))['SENPIR']
    scenarios = []
    for app in (56, 202, 255):
        for stored1, stored2 in ((None, None), (0, 0), (249, 2), (252, 5), (255, 0)):
            digest, mismatches = hashlib.sha256(), []
            for commands in itertools.product(range(16), repeat=4):
                kind = oracle.first_match.get(commands, 26)
                if kind == 27:
                    kind = 35  # ReconcileTemplateAndGroup, SENPIR override takes precedence.
                if stored1 is not None and stored2 is not None and app != 202:
                    if kind == 14:
                        kind = {249: 17, 252: 18, 255: 20}.get(stored1, kind)
                    elif kind == 15:
                        kind = {2: 19, 5: 22}.get(stored2, kind)
                if kind not in permitted.get(str(app), permitted['0']):
                    kind = 26
                expected = (kind, oracle.labels[kind])
                actual = pir_macro(commands, app, stored1, stored2)
                if expected != actual:
                    mismatches.append({'commands': commands, 'expected': expected, 'actual': actual})
                digest.update(json.dumps(expected, separators=(',', ':')).encode() + b'\n')
            if mismatches:
                raise ValueError(str(mismatches[:10]))
            scenarios.append({'application': app, 'stored1': stored1, 'stored2': stored2,
                              'vectors': 65536, 'mismatches': 0, 'source_result_sha256': digest.hexdigest()})
    return {'format': 'cbus-project-documentor-pir-macro-source-comparison-v1', 'exe_sha256': EXE_SHA256,
        'map_sha256': MAP_SHA256, 'vectors': sum(row['vectors'] for row in scenarios), 'scenarios': scenarios,
        'boundary': 'Independent native registration/subset decoding and transcribed refresh rules; no original method or GUI execution.',
        'original_generated_page_comparison': 'not_obtained'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--macros-output', type=Path)
    args = parser.parse_args()
    result = inspect(args.executable, args.map_file)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.macros_output:
        args.macros_output.write_text(json.dumps(compare_macros(args.executable, args.map_file), indent=2) + '\n')
    print(json.dumps({'checks': len(result['checks']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
