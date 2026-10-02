"""Reproduce wireless report/model facts by static reads of pinned EXE/MAP.

No original instructions, GUI, network services or site projects are executed.
Only hashes, method identifiers, scalar facts and public report labels leave the
private inputs. This is not an original generated-page comparison.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY
from cbus_toolkit.project_documentation import REGISTRATIONS as DOCUMENTORS
from cbus_toolkit.toolkit_database_csv_registry import REGISTRATIONS as UNITS
from cbus_toolkit.project_documentation_wireless_facts import (
    WIRELESS_TYPES, REMOTE_TYPES, WIRELESS_CLASSES, MICRO_GROUPS, MACRO_TEMPLATES,
    COMMAND_DESCRIPTIONS,
)

METHODS = ('CIS_CBus.LevelToPercent', 'CIS_TCBusRemoteControl.TCBusRemoteControl.DescribeInputGroupDependencyAdvanced', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.CreateRemoteControlUnit', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.CreateScenesFromVectors', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.DecodeScene', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.GetKeyFunction', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.GetRemoteSerial', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.LoadRemote', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.LoadRemoteKeys', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.LoadRemotes', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.LoadScenes', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.LoadUnitInfo', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.TCBusWirelessGatewayAdvancedCGateAgent.AfterLoadProgrammingInformation', 'CIS_TCBusWirelessGatewayAdvancedCGateAgent.TCBusWirelessGatewayAdvancedCGateAgent.InternalCreate', 'CIS_TCBusWirelessGatewayCGateAgent.TCBusWirelessGatewayCGateAgent.AfterLoadProgrammingInformation', 'CIS_TCBusWirelessGatewayCGateAgent.TCBusWirelessGatewayCGateAgent.InternalCreate', 'CIS_TCBusWirelessInputDocumentor.TCBusWirelessInputDocumentor.ActionSelectorUse', 'CIS_TCBusWirelessInputDocumentor.TCBusWirelessInputDocumentor.DocumentHTML', 'CIS_TCBusWirelessInputDocumentor.TCBusWirelessInputDocumentor.DocumentKeyHTML', 'CIS_TCBusWirelessInputDocumentor.TCBusWirelessInputDocumentor.DocumentScenesHTML', 'CIS_TCBusWirelessInputUnit.TCBusWirelessInputUnit.DescribeInputGroupDependencyAdvanced', 'CIS_TCBusWirelessInputUnit.TCBusWirelessInputUnit.DescribeOtherGroupDependencyAdvanced', 'CIS_TCBusWirelessInputUnit.TCBusWirelessInputUnit.DescribeOutputGroupDependencyAdvanced', 'CIS_TCBusWirelessInputUnit.TCBusWirelessInputUnit.GetKeyCount', 'CIS_TCBusWirelessInputUnit.TCBusWirelessInputUnit.GetRemoteKeyMap', 'CIS_TCBusWirelessInputUnit.TCBusWirelessInputUnit.Init', 'CIS_TCBusWirelessInputUnit.TCBusWirelessInputUnit.SetInstalledKeys', 'CIS_TCBusWirelessInputUnitCGateAgent.CreateRemoteControlUnit', 'CIS_TCBusWirelessInputUnitCGateAgent.CreateScenesFromVectors', 'CIS_TCBusWirelessInputUnitCGateAgent.LoadBlocks', 'CIS_TCBusWirelessInputUnitCGateAgent.LoadChannels', 'CIS_TCBusWirelessInputUnitCGateAgent.LoadEvent', 'CIS_TCBusWirelessInputUnitCGateAgent.LoadIndicators', 'CIS_TCBusWirelessInputUnitCGateAgent.LoadKeyMask', 'CIS_TCBusWirelessInputUnitCGateAgent.LoadKeys', 'CIS_TCBusWirelessInputUnitCGateAgent.LoadScenes', 'CIS_TCBusWirelessInputUnitCGateAgent.LoadUnitInfo', 'CIS_TCBusWirelessInputUnitCGateAgent.MapForDecoratorLoad', 'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorFirstParameters', 'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorKeyBlocks', 'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorKeyCommandLookups', 'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorKeys', 'CIS_TCBusWirelessInputUnitCGateAgent.TCBusWirelessInputUnit8RemotesCGateAgent.InternalCreate', 'CIS_TCBusWirelessInputUnitCGateAgent.TCBusWirelessInputUnit8RemotesCGateAgent.LoadRemotes', 'CIS_TCBusWirelessInputUnitCGateAgent.TCBusWirelessInputUnitCGateAgent.AfterLoadProgrammingInformation', 'CIS_TCBusWirelessInputUnitCGateAgent.TCBusWirelessInputUnitCGateAgent.InternalCreate', 'CIS_TCBusWirelessInputUnitCGateAgent.TCBusWirelessInputUnitCGateAgent.LoadRemote', 'CIS_TCBusWirelessInputUnitCGateAgent.TCBusWirelessInputUnitCGateAgent.LoadRemotes', 'CIS_TCommonCBus.TCBUSUnit.DescribeInputGroupDependencyAdvanced', 'CIS_TCommonCBus.TCBUSUnit.DescribeOtherGroupDependencyAdvanced', 'CIS_TCommonCBus.TCBUSUnit.DescribeOutputGroupDependencyAdvanced', 'CIS_TDocumentorCommon.DisplayHTMLGroup', 'CIS_TDocumentorCommon.DisplayHTMLLevel', 'CIS_TKeyCommand.ByteToCommandType', 'CIS_TKeyCommand.CIS_TKeyCommand', 'CIS_TKeyCommand.TKeyCommandFactory.GetKeyCommand', 'CIS_TKeyEvent.TKeyEvent.InternalCreate', 'CIS_TMulletMacroFunction.CIS_TMulletMacroFunction', 'CIS_TMulletMacroFunction.TMulletMacroFunctionTemplateReferenceCollection.ItemAndGroupByMicroFunctions', 'CIS_TMulletMicroFunctionGroup.CIS_TMulletMicroFunctionGroup', 'CIS_TRemoteControlDocumentor.TRemoteControlDocumentor.ActionSelectorUse', 'CIS_TRemoteControlDocumentor.TRemoteControlDocumentor.DocumentHTML', 'CIS_TRemoteControlDocumentor.TRemoteControlDocumentor.IsRemoteKeyUnused', 'CIS_TWTXU.TWTXU.GetKeyCount', 'CIS_TWTXU.TWTXU.GetKeysPerPage', 'CIS_TWTXU.TWTXU.GetRemoteKeyDisplayNumber', 'CIS_TWTXU.TWTXU.GetRemoteKeyDisplayString', 'CIS_TWTXU.TWTXU.GetRemoteKeyMap', 'CIS_TWirelessGatewayAdvancedDocumentor.TWirelessGatewayAdvancedDocumentor.ActionSelectorUse', 'CIS_TWirelessGatewayAdvancedDocumentor.TWirelessGatewayAdvancedDocumentor.DocumentHTML', 'CIS_TWirelessGatewayAdvancedDocumentor.TWirelessGatewayAdvancedDocumentor.DocumentRemotesHTML', 'CIS_TWirelessGatewayAdvancedDocumentor.TWirelessGatewayAdvancedDocumentor.DocumentScenesHTML', 'CIS_TWirelessGatewayDocumentor.TWirelessGatewayDocumentor.DocumentHTML', 'CIS_TWirelessInputKey.TWirelessInputKey.MulletMacroFunctionRefresh', 'CIS_TWirelessInputKey.TWirelessInputKey.RefreshTemplateFromMulletMacroFunction')

def _templates(image):
    rows, dl, description, groups, high = [], 0, '', {}, 0
    method = image.method('CIS_TMulletMacroFunction.CIS_TMulletMacroFunction')
    for address, op, args in method['instructions']:
        if address in method['literal_at']:
            description, groups = method['literal_at'][address], {}
        if op == 'mov':
            match = re.fullmatch(r'byte ptr \[ebp - (0x[0-9a-f]+|[0-9]+)\], (0x[0-9a-f]+|[0-9]+)', args)
            if match:
                groups[int(match[1], 0)] = int(match[2], 0)
            match = re.fullmatch(r'dl, (0x[0-9a-f]+|[0-9]+)', args)
            if match:
                dl = int(match[1], 0)
        if op == 'xor' and args == 'edx, edx':
            dl = 0
        if op == 'push' and re.fullmatch(r'0x[0-9a-f]+|[0-9]+', args) and address not in method['literal_at']:
            high = int(args, 0)
        if op == 'call' and args == hex(image.by_name['CIS_TMulletMacroFunction.TMulletMacroFunctionFactory.RegisterTemplate']):
            ids = [groups[key] for key in sorted(groups, reverse=True)]
            if len(ids) != high + 1:
                raise ValueError('Unparsed ordered macro template group array')
            rows.append((dl, description, tuple(ids)))
    groups, dl, pushes = [], 0, []
    method = image.method('CIS_TMulletMicroFunctionGroup.CIS_TMulletMicroFunctionGroup')
    for _, op, args in method['instructions']:
        if op == 'push' and re.fullmatch(r'0x[0-9a-f]+|[0-9]+', args):
            pushes.append(int(args, 0))
        if op == 'mov' and args.startswith('dl, '):
            dl = int(args[4:], 0)
        if op == 'call':
            if args == hex(image.by_name['CIS_TMulletMicroFunctionGroup.TMulletMicroFunctionGroupFactory.RegisterMulletMicroFunctionGroup']):
                if len(pushes) != 6:
                    raise ValueError('Unparsed six-event micro-function group')
                groups.append((dl, tuple(pushes)))
            pushes = []
    return tuple(rows), dict(groups)


def _public_method(row):
    """Keep technical labels while omitting compiled original host coordinates."""
    def coordinate(value):
        return bool(re.match(r'^[A-Za-z]:[\\/]|^/(?:Users|Volumes|private)/', value))
    def public(values):
        return ['[original source coordinate omitted]' if coordinate(value) else value
                for value in values]
    return {'start': hex(row['start']), 'end': hex(row['end']), 'sha256': row['sha256'],
            'literals': public(row['literals']), 'resources': public(row['resources']),
            'omitted_original_source_coordinates': sum(coordinate(value)
                for value in row['literals'] + row['resources'])}


def inspect(executable: Path, mapping: Path) -> dict:
    raw, symbols = executable.read_bytes(), mapping.read_bytes()
    if (hashlib.sha256(raw).hexdigest(), hashlib.sha256(symbols).hexdigest()) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(raw, symbols)
    # Duplicate local MAP symbols name distinct Load and Save nested methods.
    # These are the exact Load call targets, never the first same-name symbol.
    exact = {
        'CIS_TCBusWirelessInputUnitCGateAgent.MapForDecoratorLoad': 0x1277c88,
        'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorKeys': 0x127df7c,
        'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorFirstParameters': 0x127da44,
        'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorKeyBlocks': 0x127d55c,
        'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorKeyCommandLookups': 0x127d7a8,
        'CIS_TKeyCommand.TKeyCommandFactory.GetKeyCommand': 0xaf7514,
    }
    for name, address in exact.items():
        if name not in image.symbols[address]:
            raise ValueError('Exact original nested method target absent')
        image.by_name[name] = address
    methods = {name: image.method(name) for name in METHODS}
    templates, micro_groups = _templates(image)
    unit_rows, _ = image.registrations(UNIT_FACTORY)
    all_types = WIRELESS_TYPES | REMOTE_TYPES | {'WGATE5N', 'WGATE5F'}
    native_profiles = [row for row in unit_rows if row[0] in all_types]
    classes = {}
    for _, symbol, _, _ in native_profiles:
        short = symbol.split('..')[-1]
        ancestors = image.ancestry(symbol)
        datum = {'symbol': symbol, 'ancestors': ancestors,
                 'dependency_slots': {hex(slot): image.slot(symbol, slot) for slot in (0x128, 0x12c, 0x130)}}
        if 'TCBusWirelessInputUnit' in ancestors:
            name = image.slot(symbol, 0x168)
            instructions = image.method(name)['instructions']
            constants = [int(args.split(', ')[1], 0) for _, op, args in instructions
                         if op == 'mov' and re.fullmatch(r'dword ptr \[ebp - 8\], (0x[0-9a-f]+|\d+)', args)]
            visible = constants[0] if len(constants) == 1 else 0 if any(
                op == 'xor' and args == 'eax, eax' for _, op, args in instructions) else None
            decorator = 'TCBusWirelessDecoratorInputUnit' in ancestors
            packed = 'TCBusWirelessInputUnit8Remotes' in ancestors
            datum['profile'] = [visible, decorator, packed, 8 if packed else 2]
            datum['visible_method'] = name
        classes[short] = datum

    def has(name, address, op, args):
        return (address, op, args) in methods[name]['instructions']

    def call(name, address, target):
        return has(name, address, 'call', hex(image.by_name[target]))

    def lit(name, address, text):
        return methods[name]['literal_at'].get(address) == text

    wi = 'CIS_TCBusWirelessInputUnit.TCBusWirelessInputUnit.'
    key = 'CIS_TCBusWirelessInputDocumentor.TCBusWirelessInputDocumentor.DocumentKeyHTML'
    load = 'CIS_TCBusWirelessInputUnitCGateAgent.TCBusWirelessInputUnitCGateAgent.AfterLoadProgrammingInformation'
    checks = {
        'all_50_input_report_types': {r[0] for r in DOCUMENTORS if r[1] == 'CBusWirelessInput'} == WIRELESS_TYPES and len(WIRELESS_TYPES) == 50,
        'all_7_remote_report_types': {r[0] for r in DOCUMENTORS if r[1] == 'RemoteControl'} == REMOTE_TYPES and len(REMOTE_TYPES) == 7,
        'source_unit_factory_profiles': sorted((t, lo, hi, cls.split('..')[-1]) for t, cls, lo, hi in native_profiles)
            == sorted((r[0], r[1], r[2], r[3]) for r in UNITS if r[0] in all_types),
        '173_wireless_native_partitions': len([r for r in native_profiles if r[0] in WIRELESS_TYPES]) == 173,
        'all_wireless_class_shapes': {name: tuple(row['profile']) for name, row in classes.items() if 'profile' in row} == dict(WIRELESS_CLASSES),
        '48_global_macro_templates_in_source_order': templates == MACRO_TEMPLATES and len(templates) == 48,
        '47_six_event_micro_function_groups': micro_groups == dict(MICRO_GROUPS) and len(micro_groups) == 47,
        '32_event_command_descriptions': tuple(methods['CIS_TKeyCommand.CIS_TKeyCommand']['literals']) == COMMAND_DESCRIPTIONS,
        'fixed16keys_initialization': has(wi+'Init', 0xd4ab2b, 'mov', 'edx, 0x10'),
        'fixed16blocks_initialization': has(wi+'Init', 0xd4ab41, 'mov', 'edx, 0x10'),
        'load_exact_decorator_target': call(load, 0x1280648, 'CIS_TCBusWirelessInputUnitCGateAgent.RemapDecoratorKeys'),
        'load_channels_then_scenes_then_blocks_then_keys': all(call(load, address, target) for address, target in (
            (0x12806a4, 'CIS_TCBusWirelessInputUnitCGateAgent.LoadChannels'),
            (0x12806ab, 'CIS_TCBusWirelessInputUnitCGateAgent.LoadScenes'),
            (0x12806b2, 'CIS_TCBusWirelessInputUnitCGateAgent.LoadBlocks'),
            (0x12806b9, 'CIS_TCBusWirelessInputUnitCGateAgent.LoadKeys'))),
        'key_one_based': has(key, 0xd467d7, 'inc', 'eax'),
        'key_collects_groups_without_deduplication': call(key, 0xd46891, 'Classes.TList.Add'),
        'unused_template22_precedes_scene': has(key, 0xd468b9, 'sub', 'al, 0x16'),
        'scene_cells_use_compacted_scene_ordinal': has(key, 0xd469bb, 'inc', 'eax'),
        'blank_resource': image.resource(image.dword(0x13c26cc)) == '&nbsp;',
        'block_unused_label': image.resource(image.dword(0x13c205c)) == 'Block (Unused)',
        'remote_display_numbers': [image.dword(0x13b822c + 4*(i+1)) for i in range(16)] == list(range(10, 0, -1)) + list(range(11,17)),
        'remote_wire_slot_map': [image.dword(0x13b81f0 + 4*i) for i in range(16)] == [4,3,2,1,0,12,11,10,9,8,7,6,5,15,14,13],
        'advanced_gateway_group_slots_are_inherited_empty': all(
            classes['TCBusWirelessGatewayAdvancedUnit']['dependency_slots'][hex(slot)] == 'CIS_TCommonCBus.TCBUSUnit.' + method
            for slot, method in ((0x128, 'DescribeInputGroupDependencyAdvanced'), (0x12c, 'DescribeOutputGroupDependencyAdvanced'), (0x130, 'DescribeOtherGroupDependencyAdvanced'))),
    }
    if not all(checks.values()):
        raise ValueError('Source checks failed: ' + ', '.join(name for name, result in checks.items() if not result))
    return {'format': 'cbus-project-documentor-wireless-static-v1',
        'sources': {'CBusToolkit.exe': {'sha256': EXE_SHA256, 'bytes': len(raw)},
                    'CBusToolkit.map': {'sha256': MAP_SHA256, 'bytes': len(symbols)}},
        'original_instructions_executed': 0, 'original_generated_page_comparison': 'not_obtained',
        'saved_snapshot_scope': 'Explicit PP plus existing project metadata; undefined defaults, missing remote creation and physical effects are refused.',
        'native_profiles': [list(row) for row in native_profiles], 'classes': classes,
        'macro_templates': [[kind, label, list(groups)] for kind, label, groups in templates],
        'micro_groups': {str(i): list(values) for i, values in micro_groups.items()},
        'methods': {name: _public_method(row) for name, row in methods.items()},
        'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inspect(args.executable, args.map), indent=2, sort_keys=True)+'\n')


if __name__ == '__main__':
    main()
