"""Pin SCNCTL5 report/factory/PP facts; no original instructions execute."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256
from csv_factory_registry_static import source_registry
from cbus_toolkit import project_documentation_scene_controller as model

DOC = 'CIS_TCustomSceneControllerDocumentor.TCustomSceneControllerDocumentor.'
AGENT = 'CIS_TCustomSceneControllerCGateAgent.'
SCENE = 'CIS_TScene.'


def inspect(exe, map_file):
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    t = _Toolkit(raw, symbols)
    methods, checks = {}, {}

    def method(name):
        if name not in methods:
            methods[name] = t.method(name)
        return methods[name]

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in method(name)['instructions']

    def call(name, address, target):
        return has(name, address, 'call', hex(t.by_name[target]))

    rows = [r for r in source_registry(exe, map_file, ())['registrations'] if r['unit_type'] == 'SCNCTL5']
    checks['factory'] = len(rows) == 1 and (rows[0]['class'], rows[0]['agent'], rows[0]['firmware_min'], rows[0]['firmware_max']) == (
        'TSCNCTL5', 'TCustomSceneControllerCGateAgent', '0', '9')
    cls = 'CIS_TSCNCTL5..TSCNCTL5'
    checks['group_method_slots'] = [t.slot(cls, offset).rsplit('.', 2)[-2] for offset in (0x128, 0x12c, 0x130)] == [
        'TCustomSceneUnit', 'TCBUSUnit', 'TCBusInputUnit']
    checks['five_scenes'] = has('CIS_TSCNCTL5.TSCNCTL5.MaximumSceneCount', 0x100a155, 'mov', 'dword ptr [ebp - 8], 5')
    checks['nine_commands'] = has('CIS_TSCNCTL5.TSCNCTL5.MaximumCommandCount', 0x100a13d, 'mov', 'dword ptr [ebp - 8], 9')
    create = AGENT + 'TCustomSceneControllerCGateAgent.InternalCreate'
    checks['three_primary_six_secondary'] = has(create, 0x1227326, 'mov', 'dword ptr [eax + 0x108], 3') and has(create, 0x1227333, 'mov', 'dword ptr [eax + 0x10c], 6')
    fields = {'PrimaryGroupAddressLevel': (0x122735d, 0x110), 'MasterOffRampRate': (0x1227383, 0x114),
              'SceneRampRate': (0x12273a9, 0x118), 'MasterOffCustomRampRate': (0x12273cf, 0x11c),
              'SceneCustomRampRate': (0x12273f5, 0x120), 'SecondaryMasterOffEnabled': (0x122741b, 0x124),
              'MasterOffTriggerLevel': (0x1227467, 0x12c), 'SceneTriggerLevel': (0x122748d, 0x130),
              'PrimaryGroupAddress': (0x1227609, 0x158), 'ControlAppGroupAddress': (0x122762f, 0x15c),
              **{f'Scene{i + 1}SecondaryGroupTable': (0x1227655 + i * 0x26, 0x160 + i * 4) for i in range(5)}}
    for field, (address, offset) in fields.items():
        checks['pp:' + field] = field in method(create)['literals'] and has(create, address, 'mov', f'dword ptr [edx + {hex(offset)}], eax')
    load = AGENT + 'LoadScenes'
    facts = [(0x1228227, 'mov', 'eax, dword ptr [eax + 0x158]'),
             (0x1228269, 'lea', 'edx, [edx + edx*2]'), (0x122826c, 'add', 'edx, dword ptr [ebp - 8]'),
             (0x1228275, 'mov', 'eax, dword ptr [eax + 0x110]'),
             (0x12283b4, 'lea', 'edx, [edx + edx*2]'), (0x12283b7, 'inc', 'edx'),
             (0x12283f4, 'add', 'edx, 2'), (0x1228435, 'shr', 'eax, 3'),
             (0x1228438, 'and', 'eax, 0x8000000f'), (0x122847d, 'imul', 'edx, dword ptr [ebp - 4]'),
             (0x1228481, 'add', 'edx, dword ptr [ebp - 0xc]')]
    checks['loader_indexing'] = all(has(load, *fact) for fact in facts)
    checks['primary_report_ramp_is_generic_custom'] = call(load, 0x12282da, 'CIS_TCustomSceneControllerUnit.TCustomSceneControllerUnit.GetCustomRampRate') and call(load, 0x12282e4, SCENE + 'TSceneCommand.SetRampRate') and has(SCENE + 'TSceneCommand.GetRampRate', 0xd15de4, 'mov', 'eax, dword ptr [eax + 0x90]')
    checks['primary_master_off_true'] = has(load, 0x1228309, 'mov', 'dl, 1') and call(load, 0x122830e, SCENE + 'TSceneCommand.SetMasterOffAllowed')
    checks['control_application_202'] = call(AGENT + 'LoadControlAppGroup', 0x1227e4c, 'CIS_TCommonCBus.TCBusNetwork.GetTriggerControlApplication')
    checks['master_selector_by_address'] = call(AGENT + 'LoadMasterOff', 0x12280a5, 'CIS_TCommonCBus.TLevelManager.FindLevelByAddress')
    checks['scene_selector_by_address'] = call(load, 0x122819a, 'CIS_TCommonCBus.TLevelManager.FindLevelByAddress')
    checks['level_percent_updates'] = call(SCENE + 'TSceneCommand.HandleLevelAfterChange', 0xd160d9, 'CIS_CBus.LevelToPercent')
    checks['body_base_first'] = call(DOC + 'DocumentHTML', 0x10096e1, 'CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML')
    checks['body_generic_ramp_getter'] = call(DOC + 'DocumentHTML', 0x1009a30, SCENE + 'TSceneCommand.GetRampRate')
    checks['body_unused_scene_and_command_filters'] = call(DOC + 'DocumentHTML', 0x1009850, DOC + 'IsSceneUnused') and has(DOC + 'DocumentHTML', 0x1009964, 'jne', '0x1009ab7')
    checks['body_no_trailing_break'] = has(DOC + 'DocumentHTML', 0x1009adc, 'mov', 'edx, 0x1009ea0') and t.literal(0x1009ea0) == '</table>' and has(DOC + 'DocumentHTML', 0x1009ae9, 'xor', 'eax, eax')
    checks['master_as_string_not_level_link'] = has(DOC + 'DocumentHTML', 0x100975a, 'call', 'dword ptr [ecx + 0x2c]') and t.slot('CIS_TCommonCBus..TLevel', 0x2c) == 'CIS_TCustomFlashObject.TCustomFlashObject.GetAsString'
    checks['master_as_string_extended_tag_chain'] = t.slot('CIS_TCommonCBus..TLevel', 0x58) == 'CIS_TCommonCBus.TLevel.GetDefaultRepresentation' and t.slot('CIS_TCommonCBus..TLevel', 0x94) == 'CIS_TCommonCBus.TLevel.GetExtendedTagName'
    checks['master_standard_format_fresh_default'] = has('CIS_GlobalSoftwareParameters.LoadParametersFromRegistry', 0x85b687, 'mov', 'byte ptr [0x144df24], 0') and 'DisplayAddressValue' in method('CIS_GlobalSoftwareParameters.LoadParametersFromRegistry')['literals']
    checks['master_extended_tag_format_branch'] = call('CIS_TCommonCBus.TLevel.GetExtendedTagName', 0xf270fa, 'CIS_GlobalSoftwareParameters.UseAddressValueFormat') and has('CIS_TCommonCBus.TLevel.GetExtendedTagName', 0xf27101, 'je', '0xf27140')
    method('CIS_TCustomFlashObject.TCustomFlashObject.GetAsString')
    method('CIS_TCustomFlashObject.TCustomFlashObject.InternalGetDefaultRepresentation')
    method('CIS_TCommonCBus.TLevel.GetDefaultRepresentation')
    checks['action_identity_not_value'] = has(DOC + 'ActionSelectorUse', 0x1009539, 'cmp', 'eax, dword ptr [ebp - 8]') and has(DOC + 'ActionSelectorUse', 0x1009583, 'cmp', 'eax, dword ptr [ebp - 8]')
    checks['action_labels_separator'] = all(s in method(DOC + 'ActionSelectorUse')['literals'] for s in ('Scene Master Off', '<br />', 'Triggers Scene '))
    group = 'CIS_TCustomSceneUnit.TCustomSceneUnit.DescribeInputGroupDependencyAdvanced'
    checks['group_label'] = t.resource(t.dword(0x13c2f6c)) == 'Scene %d'
    checks['group_matches_each_command'] = has(group, 0xd16c5a, 'cmp', 'eax, dword ptr [ebp - 8]') and has(group, 0xd16ca8, 'jne', '0xd16c36')
    dragan = SCENE + 'DraganRampRateToCBusRampRate'
    method(dragan)
    targets = [t.dword(0xd151e3 + i * 4) for i in range(6)]
    branches = [list(t.decoder.disasm(t.pe.get_data(address - t.base, 6), address)) for address in targets]
    checks['master_dragan_mapping'] = [part[0].op_str for part in branches] == [
        'byte ptr [ebp - 3], 0', 'byte ptr [ebp - 3], 1', 'byte ptr [ebp - 3], 3',
        'byte ptr [ebp - 3], 7', 'byte ptr [ebp - 3], 0xd', 'al, byte ptr [ebp - 2]']
    checks['dragan_255_is_one_other_invalid_raises'] = has(SCENE + 'IntegerToDraganRampRate', 0xd15142, 'mov', 'byte ptr [ebp - 5], 1') and call(SCENE + 'IntegerToDraganRampRate', 0xd15159, 'System.@RaiseExcept')
    method('CIS_TCommonCBus.IntegerToCBusRampRate')
    method('CIS_TCBusInputUnit.TCBusInputUnit.DescribeOtherGroupDependencyAdvanced')
    failed = [name for name, value in checks.items() if not value]
    if failed:
        raise ValueError('SCNCTL5 source checks failed: ' + ', '.join(failed))
    return {'format': 'cbus-project-documentor-scene-controller-static-v1',
            'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
            'original_executed': False, 'original_generated_page_comparison': 'not_obtained',
            'model_sha256': hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest(),
            'master_selector_format_basis': model.MASTER_SELECTOR_FORMAT_BASIS,
            'checks': checks, 'factory': rows,
            'methods': {name: {'start': hex(m['start']), 'end': hex(m['end']), 'sha256': m['sha256']}
                        for name, m in sorted(methods.items())},
            'limits': ['Complete consumed PP arrays; invalid Dragan values and implicit loader defaults are not admitted.',
                       'Existing displayed group and selector records required; no original auto-creation is projected.',
                       'Fresh five-scene, nine-command model only; prior in-memory added objects are not represented.',
                       'Master selector uses the original standard tag-name default; registry DisplayAddressValue prefixes are not projected.',
                       'Source reconstruction and isolated original-method probes do not establish original generated-page acceptance.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.exe, args.map)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(f"Verified {len(report['checks'])} SCNCTL5 source checks")
