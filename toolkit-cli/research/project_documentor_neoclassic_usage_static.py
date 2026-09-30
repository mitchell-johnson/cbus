"""Pin KEYC/CIR dependency and action consumers without executing vendor code."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY

TYPES = {'KEYC1': 1, 'KEYC2': 2, 'KEYC4': 4, 'KEYCIR1': 0, 'KEYCIR4': 4}
ACTION = 'CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.ActionSelectorUse'
INPUT = 'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.DescribeInputGroupDependencyAdvanced'
OTHER_NEO = 'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.DescribeOtherGroupDependencyAdvanced'
OTHER_PRO = 'CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.DescribeOtherGroupDependencyAdvanced'
LOAD = 'CIS_TCoreNeoInputCGateAgent.TCoreNeoInputCGateAgent.AfterLoadProgrammingInformation'
SCENES = 'CIS_TCoreNeoInputCGateAgent.GetSceneCommands'
KEYS = 'CIS_TCoreNeoInputCGateAgent.GetKeyValues'
CORRIDOR = 'CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.LoadCorridorLinkAttributes'
BRIGHTNESS = 'CIS_TCoreKeyInputCGateAgent.GetIndicatorBrightness'
DISABLE = 'CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation'
METHODS = (ACTION, INPUT, OTHER_NEO, OTHER_PRO, LOAD, SCENES, KEYS, CORRIDOR, BRIGHTNESS, DISABLE)


def inspect(executable, mapping):
    exe, symbols = executable.read_bytes(), mapping.read_bytes()
    if hashlib.sha256(exe).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(exe, symbols)
    methods = {name: image.method(name) for name in METHODS}
    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in methods[name]['instructions']
    def call(name, address, destination):
        return has(name, address, 'call', hex(image.by_name[destination]))
    checks = {
        'classic_action_primary_application': has(ACTION, 0xCA62E5, 'call', 'dword ptr [edx + 0xb0]'),
        'classic_action_uses_all_key_collection': any(op == 'mov' and args == 'eax, dword ptr [eax + 0x1e8]'
            for _, op, args in methods[ACTION]['instructions']),
        'neo_input_join_capability_before_getter': has(INPUT, 0xD07618, 'je', '0xd0762b'),
        'neo_input_dual_join_capability_before_getter': has(INPUT, 0xD07641, 'je', '0xd07654'),
        'neo_input_unused_macro_gate': has(INPUT, 0xD076DF, 'sub', 'al, 0x10'),
        'neo_input_physical_count_gate': has(INPUT, 0xD0771D, 'call', 'dword ptr [edx + 0x190]') and has(INPUT, 0xD07726, 'jg', '0xd0778b'),
        'neo_scene_used_scans_all_key_objects': has(INPUT, 0xD07840, 'mov', 'eax, dword ptr [eax + 0x1e8]'),
        'neo_scene_use_is_scene_pointer_identity': call(INPUT, 0xD07871, 'CIS_TInputKeyExtensionNeo.TInputKeyExtensionNeo.GetScene') and has(INPUT, 0xD07889, 'cmp', 'ebx, eax'),
        'other_join_capability_before_getter': has(OTHER_NEO, 0xD07A21, 'je', '0xd07a57'),
        'other_dual_join_capability_before_getter': has(OTHER_NEO, 0xD07A64, 'je', '0xd07a9a'),
        'scene_loader_unconditional_before_keys': call(LOAD, 0xCCB403, SCENES) and call(LOAD, 0xCCB40A, KEYS),
        'scene_selector_independent_of_scenes_enabled': has(KEYS, 0xCCA5C6, 'mov', 'eax, dword ptr [eax + 0x180]') and has(KEYS, 0xCCA5D7, 'jne', '0xcca9c3'),
        'scene_clear_before_decode': has(SCENES, 0xCCAF9D, 'call', 'dword ptr [edx + 0x6c]'),
        'empty_table_skips_pointers': has(SCENES, 0xCCAFCE, 'jle', '0xccb11c'),
        'initial_unused_skips_pointers': has(SCENES, 0xCCAFD7, 'cmp', 'dword ptr [eax], 0xff') and has(SCENES, 0xCCAFDD, 'je', '0xccb11c'),
        'scene_group_unused_skip': has(SCENES, 0xCCB03C, 'je', '0xccb0af'),
        'scene_duplicate_group_skip': call(SCENES, 0xCCB050, 'CIS_TInputKeyExtensionNeo.TNeoSceneCommandManager.ItemByGroupAddress') and has(SCENES, 0xCCB057, 'jne', '0xccb0af'),
        'scene_groups_primary_application': has(SCENES, 0xCCB077, 'call', 'dword ptr [edx + 0xb0]'),
        'scene_pairs_stride_two': has(SCENES, 0xCCB0AF, 'add', 'dword ptr [ebp - 8], 2'),
        'scene_boundary_next_pointer_plus162': has(SCENES, 0xCCB0C6, 'mov', 'eax, dword ptr [eax + edx*4 + 4]') and has(SCENES, 0xCCB0CD, 'add', 'edx, 0xa2'),
        'scene_pad_eight': has(SCENES, 0xCCB132, 'cmp', 'eax, 8') and has(SCENES, 0xCCB135, 'jl', '0xccb106'),
        'unsupported_corridor_still_loads_group': has(CORRIDOR, 0xCED086, 'jmp', '0xced0a8') and has(CORRIDOR, 0xCED0C4, 'call', 'dword ptr [edx + 0xb0]'),
        'brightness_ninth_group_index_maxblocks': any(op == 'call' and args == 'dword ptr [edx + 0x16c]' for _, op, args in methods[BRIGHTNESS]['instructions']),
    }
    records = []
    for kind, cls, low, high in image.registrations(UNIT_FACTORY)[0]:
        if kind not in TYPES:
            continue
        slots = {hex(slot): image.slot(cls, slot) for slot in (0x128, 0x12c, 0x130, 0x16c, 0x190, 0x194, 0x234, 0x238, 0x244, 0x260)}
        def ins(slot):
            return [(op, args) for _, op, args in image.method(slots[hex(slot)])['instructions']]
        checks[kind + ':input_inherited_neo'] = slots['0x128'] == INPUT
        checks[kind + ':other_inherited_neopro'] = slots['0x130'] == OTHER_PRO
        checks[kind + ':output_empty_base'] = slots['0x12c'].endswith('TCBUSUnit.DescribeOutputGroupDependencyAdvanced')
        checks[kind + ':eight_blocks'] = ('mov', 'dword ptr [ebp - 8], 8') in ins(0x16c)
        checks[kind + ':eight_virtual_keys'] = ('mov', 'dword ptr [ebp - 8], 8') in ins(0x194)
        checks[kind + ':physical_keys'] = (('xor', 'eax, eax') if TYPES[kind] == 0 else ('mov', f'dword ptr [ebp - 8], {TYPES[kind]}')) in ins(0x190)
        for slot in (0x234, 0x238, 0x244):
            checks[kind + ':' + hex(slot) + '_unsupported'] = ('mov', 'byte ptr [ebp - 5], 0') in ins(slot)
        checks[kind + ':key_disable_supported'] = ('mov', 'byte ptr [ebp - 5], 1') in ins(0x260)
        records.append({'unit_type': kind, 'class': cls, 'firmware': [low, high], 'slots': slots})
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError('NeoProClassic usage source differs: ' + ', '.join(failures))
    return {'format': 'cbus-project-documentor-neoclassic-usage-static-v1', 'exe_sha256': EXE_SHA256,
        'map_sha256': MAP_SHA256, 'checks': checks, 'registrations': records,
        'methods': {name: {'start': hex(row['start']), 'end': hex(row['end']), 'sha256': row['sha256']} for name, row in methods.items()},
        'original_generated_page_comparison': 'not_obtained', 'original_loader_execution': 'not_executed',
        'boundary': 'Pinned static methods and virtual slots only. No native CPU probe or original GUI execution.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.executable, args.map_file)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'checks': len(result['checks'])}))


if __name__ == '__main__':
    main()
