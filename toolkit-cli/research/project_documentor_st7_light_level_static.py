"""Verify fresh ST7 light-level report state by pinned EXE/MAP static reads.

This annex preserves the historical remaining-family receipt. No original
instructions, GUI, project, service or hardware are executed. Published spans
contain hashes only; compiled source coordinates and vendor bytes stay private.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY

SENLL = 'CIS_TSENLL.TST7SENLL.'
UNIT = 'CIS_TCBusST7SensorUnit.TCBusST7LightLevelSensorUnit.'
CORE = 'CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.'
BLOCK = 'CIS_TInputKey.TInputBlock.'
KEY = 'CIS_TInputKey.TInputKey.'
LOAD = 'CIS_TCoreNeoInputCGateAgent.TCoreNeoInputCGateAgent.AfterLoadProgrammingInformation'
ST7_LOAD = 'CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.AfterLoadProgrammingInformation'
METHODS = (
    SENLL+'MaximumKeyCount', SENLL+'GetMaximumVirtualKeyCount',
    CORE+'MaximumVirtualKeyCount', CORE+'GetMaximumVirtualInputCount', CORE+'InternalCreate',
    'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.MaximumBlockCount',
    UNIT+'InternalCreate', UNIT+'DescribeInputGroupDependencyAdvanced', UNIT+'DescribeOtherGroupDependencyAdvanced',
    BLOCK+'InternalCreate', BLOCK+'SetTimer', BLOCK+'SetTimerMin', BLOCK+'GetTimer',
    BLOCK+'HandleTimerAfterChange', BLOCK+'HandleTimerMinAfterChange',
    KEY+'HandleMacroFunctionTemplateAfterChangeEvent',
    'CIS_TCoreKeyInputCGateAgent.GetBlockValues',
    'CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.LoadTimerHighAndLowBytes',
    'CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.AfterLoadProgrammingInformation',
    LOAD, 'CIS_TCoreNeoInputCGateAgent.GetKeyValues', 'CIS_TCoreNeoInputCGateAgent.GetSceneCommands',
    'CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation',
    ST7_LOAD, 'CIS_TCBusST7SensorCGateAgent.LoadOccupancyKeys',
    'CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.RefreshMacroFunctionOverrides',
    'CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.RefreshLightLevelBroadcastBlockFunction',
    'CIS_TST7LightLevelSensorDocumentor.TST7LightLevelSensorDocumentor.DocumentHTML', 'CIS_TProjectDocumentor.TUnitTypeDocumentor.ActionSelectorUse',
)


def inspect(executable: Path, mapping: Path) -> dict:
    exe, symbols = executable.read_bytes(), mapping.read_bytes()
    if (hashlib.sha256(exe).hexdigest(), hashlib.sha256(symbols).hexdigest()) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(exe, symbols)
    exact = {'CIS_TCoreKeyInputCGateAgent.GetBlockValues': 0xcc80c8,
             'CIS_TCoreNeoInputCGateAgent.GetKeyValues': 0xcca51c,
             'CIS_TCoreNeoInputCGateAgent.GetSceneCommands': 0xccaf50}
    for name, address in exact.items():
        if name not in image.symbols[address]:
            raise ValueError('Exact inherited Load target absent')
        image.by_name[name] = address
    methods = {name: image.method(name) for name in METHODS}

    def has(name, address, op, args):
        return (address, op, args) in methods[name]['instructions']

    def calls(name):
        return [sorted(image.symbols.get(int(args, 16), {'?'}))[0]
                for _, op, args in methods[name]['instructions'] if op == 'call' and args.startswith('0x')]

    def call(name, address, target):
        return has(name, address, 'call', hex(image.by_name[target]))

    class_symbol = 'CIS_TSENLL..TST7SENLL'
    profile_rows, _ = image.registrations(UNIT_FACTORY)
    profiles = [list(row) for row in profile_rows if row[0] == 'SENLL']
    key_load = 'CIS_TCoreNeoInputCGateAgent.GetKeyValues'
    scene_load = 'CIS_TCoreNeoInputCGateAgent.GetSceneCommands'
    block_load = 'CIS_TCoreKeyInputCGateAgent.GetBlockValues'
    checks = {
        'exact_SENLL_partitions': sorted(profiles) == sorted([
            ['SENLL', 'CIS_TSENLL..TSENLL', '1.00', '2.0.00'],
            ['SENLL', class_symbol, '2.0.01', '9']]),
        'effective_input_is_light_level_override': image.slot(class_symbol, 0x128) == UNIT+'DescribeInputGroupDependencyAdvanced',
        'effective_other_is_light_level_override': image.slot(class_symbol, 0x130) == UNIT+'DescribeOtherGroupDependencyAdvanced',
        'effective_output_is_empty_base': image.slot(class_symbol, 0x12c) == 'CIS_TCommonCBus.TCBUSUnit.DescribeOutputGroupDependencyAdvanced',
        'action_selector_is_empty_base': image.slot('CIS_TST7LightLevelSensorDocumentor..TST7LightLevelSensorDocumentor', 0x80) == 'CIS_TProjectDocumentor.TUnitTypeDocumentor.ActionSelectorUse',
        'effective_physical_key_limit': image.slot(class_symbol, 0x190) == SENLL+'MaximumKeyCount',
        'effective_virtual_key_limit': image.slot(class_symbol, 0x194) == SENLL+'GetMaximumVirtualKeyCount',
        'input_block2_is_fixed': has(UNIT+'DescribeInputGroupDependencyAdvanced', 0xcfd731, 'mov', 'edx, 2'),
        'derived_constructor_loads_parent_first': calls(UNIT+'InternalCreate')[0].endswith('TCBusST7MultisensorUnit.InternalCreate'),
        'Neo_loader_loads_Core_blocks_first': calls(LOAD)[0].endswith('TCoreKeyInputCGateAgent.AfterLoadProgrammingInformation'),
        'occupancy_load_zero_keys_skips_masks': has('CIS_TCBusST7SensorCGateAgent.LoadOccupancyKeys', 0xcf426e, 'jl', '0xcf436f'),
        'broadcast_template_refresh_zero_keys_skips_mutations': has('CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.RefreshLightLevelBroadcastBlockFunction', 0xcfc78e, 'jl', '0xcfc81a'),
        'zero_physical_keys': has(SENLL+'MaximumKeyCount', 0xcab0e9, 'xor', 'eax, eax'),
        'virtual_key_sentinel': has(SENLL+'GetMaximumVirtualKeyCount', 0xcab07d, 'mov', 'dword ptr [ebp - 8], 0xffffffff'),
        'sentinel_uses_physical_count': all(has(CORE+'MaximumVirtualKeyCount', a, op, args) for a, op, args in (
            (0xc9e1e2, 'call', 'dword ptr [edx + 0x194]'), (0xc9e1eb, 'cmp', 'dword ptr [ebp - 0xc], -1'),
            (0xc9e1f6, 'call', 'dword ptr [edx + 0x190]'))),
        'fresh_key_count_from_effective_limit': call(CORE+'InternalCreate', 0xc9dd18, CORE+'MaximumVirtualKeyCount') and has(CORE+'InternalCreate', 0xc9dd2a, 'call', 'dword ptr [ecx + 0xb4]'),
        'key_load_asserts_effective_count': call(key_load, 0xcca55d, CORE+'MaximumVirtualKeyCount') and has(key_load, 0xcca562, 'cmp', 'ebx, eax'),
        'key_load_zero_count_skips_all_events': all(has(key_load, a, op, args) for a, op, args in (
            (0xcca58d, 'call', 'dword ptr [edx + 0x58]'), (0xcca590, 'dec', 'eax'), (0xcca593, 'jl', '0xccac1a'))),
        'eight_loaded_blocks': has('CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.MaximumBlockCount', 0xd08725, 'mov', 'dword ptr [ebp - 8], 8'),
        'default_block_minimum_zero': has(BLOCK+'InternalCreate', 0xd0ed50, 'xor', 'edx, edx') and call(BLOCK+'InternalCreate', 0xd0ed55, BLOCK+'SetTimerMin'),
        'block4_minimum_ten': all(has(UNIT+'InternalCreate', a, op, args) for a, op, args in (
            (0xcfd8a3, 'mov', 'edx, 4'), (0xcfd8b6, 'mov', 'dx, 0xa'))) and call(UNIT+'InternalCreate', 0xcfd8ba, BLOCK+'SetTimerMin'),
        'timer_callback_registered': has(BLOCK+'InternalCreate', 0xd0ec23, 'mov', 'dword ptr [eax + 0x60], 0xd0f508'),
        'minimum_callback_registered': has(BLOCK+'InternalCreate', 0xd0ec85, 'mov', 'dword ptr [eax + 0x60], 0xd0f544'),
        'timer_change_clamps_below_minimum': has(BLOCK+'HandleTimerAfterChange', 0xd0f527, 'cmp', 'bx, ax') and has(BLOCK+'HandleTimerAfterChange', 0xd0f52a, 'jae', '0xd0f53e') and call(BLOCK+'HandleTimerAfterChange', 0xd0f539, BLOCK+'SetTimer'),
        'minimum_change_clamps_existing_timer': has(BLOCK+'HandleTimerMinAfterChange', 0xd0f563, 'cmp', 'bx, ax') and has(BLOCK+'HandleTimerMinAfterChange', 0xd0f566, 'jae', '0xd0f57a') and call(BLOCK+'HandleTimerMinAfterChange', 0xd0f575, BLOCK+'SetTimer'),
        'block_loader_uses_timer_setter': call(block_load, 0xcc82df, BLOCK+'SetTimer'),
        'timer_high_low_word_order': has('CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.LoadTimerHighAndLowBytes', 0xcc7de6, 'mov', 'byte ptr [ebp - 9], al') and has('CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.LoadTimerHighAndLowBytes', 0xcc7e17, 'mov', 'byte ptr [ebp - 0xa], al') and has('CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.LoadTimerHighAndLowBytes', 0xcc7e5b, 'mov', 'ax, word ptr [ebp - 0xa]'),
        'ST7_load_inherits_NeoPro_first': calls(ST7_LOAD)[0].endswith('TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation'),
        'inherited_scenes_load_before_keys': call(LOAD, 0xccb403, scene_load) and call(LOAD, 0xccb40a, key_load),
        'packed_scene_pairs_and_162_pointer_base': has(scene_load, 0xccb0af, 'add', 'dword ptr [ebp - 8], 2') and has(scene_load, 0xccb0cd, 'add', 'edx, 0xa2'),
        'scene_loader_retains_first_group_per_scene': any(name.endswith('ItemByGroupAddress') for name in calls(scene_load)),
        'scene_loader_completes_eight_slots': has(scene_load, 0xccb132, 'cmp', 'eax, 8'),
        'template_zero_timer_300_is_per_key_callback': has(KEY+'HandleMacroFunctionTemplateAfterChangeEvent', 0xd12b2d, 'mov', 'dx, 0x12c') and call(KEY+'HandleMacroFunctionTemplateAfterChangeEvent', 0xd12b34, BLOCK+'SetTimer'),
        'SENPILL_override_only_loops_existing_keys': has('CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.RefreshMacroFunctionOverrides', 0xcfc8ee, 'jl', '0xcfc91b'),
        'input_exact_roles_no_inherited_consumer': [name.rsplit('.', 1)[-1] for name in calls(UNIT+'DescribeInputGroupDependencyAdvanced') if name.rsplit('.', 1)[-1].startswith('Get')] == ['GetLightLevelMaintBlock', 'GetGroup', 'GetItem', 'GetGroup'],
        'other_exact_roles_no_inherited_consumer': [name.rsplit('.', 1)[-1] for name in calls(UNIT+'DescribeOtherGroupDependencyAdvanced') if name.rsplit('.', 1)[-1].startswith('Get')] == ['GetLightLevelBroadcastBlock', 'GetGroup', 'GetLightLevelMaintEnableGroup'],
        'input_role_resources': [image.resource(image.dword(a)) for a in (0x13c3044, 0x13c201c)] == ['Level Group', 'On/Off Group'],
        'other_role_resources': [image.resource(image.dword(a)) for a in (0x13c3bfc, 0x13c40a0)] == ['Light Level Broadcast Group', 'Enable Group'],
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError('Original source differs: '+', '.join(failures))
    return {'format': 'cbus-project-documentor-st7-light-level-static-v1', 'exe_sha256': EXE_SHA256,
        'map_sha256': MAP_SHA256, 'original_executed': False, 'original_generated_page_comparison': 'not_obtained',
        'factory_profiles': profiles, 'checks': checks, 'fresh_model': {'physical_keys': 0, 'virtual_key_limit': -1,
        'effective_input_keys': 0, 'blocks': 8, 'timer_minima': [0,0,0,0,10,0,0,0],
        'scene_collection_loaded': True, 'scene_dependency_consumer': False, 'scene_action_consumer': False},
        'methods': {name: {'start': hex(row['start']), 'end': hex(row['end']), 'sha256': row['sha256']}
                    for name, row in sorted(methods.items())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.executable, args.map_file)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'checks': len(result['checks']), 'methods': len(result['methods']), 'original_executed': False}))

if __name__ == '__main__':
    main()
