"""Read-only proof for the fresh architectural dimmer Document Project family.

The pinned EXE/MAP is parsed, never loaded or executed. Public receipts contain
method span hashes, checked facts, safe report literals and invented vectors;
instruction bytes and private compiler coordinates are not published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from csv_factory_registry_static import source_registry
from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit
from cbus_toolkit import project_documentation_architectural as body_model
from cbus_toolkit import project_documentation_architectural_loader as loader
from cbus_toolkit import project_documentation_architectural_usage as usage_model


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
        return any(a == address and m == 'call' and o.startswith('0x')
                   and target in t.symbols.get(int(o, 16), ())
                   for a, m, o in method(name)['instructions'])

    def calls(name, target):
        return any(m == 'call' and o.startswith('0x') and target in t.symbols.get(int(o, 16), ())
                   for _, m, o in method(name)['instructions'])

    def resource(address):
        return t.resource(address) or t.resource(t.dword(address))

    dimmer = 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerUnit.'
    channel = 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerChannel.'
    scene = 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerScene.'
    agent = 'CIS_TDIMARXCGateAgent.TDIMARXCGateAgent.'
    helper = 'CIS_TDIMARXCGateAgent.'
    body = 'CIS_TArchitecturalDimmerDocumentor.TArchitecturalDimmerDocumentor.DocumentHTML'
    action = 'CIS_TArchitecturalDimmerDocumentor.TArchitecturalDimmerDocumentor.ActionSelectorUse'
    profiles = []
    rows = [r for r in source_registry(exe, map_file, ())['registrations']
            if r['unit_type'] in loader.PROFILES]
    actual = sorted((r['unit_type'], r['firmware_min'], r['firmware_max'], r['class'], r['agent']) for r in rows)
    expected = [('DIMAR3', '0', '9', 'TDIMAR3', 'TDIMARXCGateAgent'),
                ('DIMAR6', '0', '9', 'TDIMAR6', 'TDIMARXCGateAgent'),
                ('DIMAR12', '0', '9', 'TDIMAR12', 'TDIMARXCGateAgent'),
                ('C12DIMAR', '0', '9', 'TDIMAR12', 'TDIMARXCGateAgent')]
    checks['exact_four_factory_rows'] = actual == sorted(expected)
    for unit_type, cls, count in [('DIMAR3', 'TDIMAR3', 3), ('DIMAR6', 'TDIMAR6', 6),
                                 ('DIMAR12', 'TDIMAR12', 12), ('C12DIMAR', 'TDIMAR12', 12)]:
        symbol = 'CIS_TDIMARX..' + cls
        slots = {hex(slot): t.slot(symbol, slot) for slot in (0x128, 0x12c, 0x130, 0x188, 0x18c)}
        profiles.append({'unit_type': unit_type, 'class': cls, 'channels': count,
                         'ancestry': t.ancestry(symbol), 'slots': slots})
        checks[unit_type + ':channel_count'] = any(m == 'mov' and o == f'dword ptr [ebp - 8], {count if count < 10 else hex(count)}'
                                                    for _, m, o in method(slots['0x188'])['instructions'])
        checks[unit_type + ':four_logic_groups'] = any(m == 'mov' and o == 'dword ptr [ebp - 8], 4'
                                                      for _, m, o in method(slots['0x18c'])['instructions'])
        checks[unit_type + ':architectural_dependencies'] = all(slots[hex(slot)] == dimmer + f'Describe{kind}GroupDependencyAdvanced'
                                                               for slot, kind in [(0x128, 'Input'), (0x12c, 'Output'), (0x130, 'Other')])
    checks['base_body_first'] = call(body, 0xda62b4, 'CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML')
    checks['body_complete_section_order'] = all(text in method(body)['literals'] for text in
        ['C-Bus Lock Enable Group: ', 'DMX Enable Group: ', '<b>Special Scenes</b><br />', '<b>Scenes</b><br />'])
    checks['body_exact_writer_boundaries'] = all(has(body, address, 'call', 'dword ptr [ecx + 0x38]') for address in
        (0xda6307, 0xda6340, 0xda63b9, 0xda69cb, 0xda69e4, 0xda69f1, 0xda6a26,
         0xda6a33, 0xda6d63, 0xda6d70, 0xda6d7d, 0xda6d8a, 0xda787a, 0xda7887,
         0xda7894, 0xda7cb2, 0xda7cbf))
    # The original channel row intentionally leaves the Logic cell unclosed.
    checks['malformed_logic_cell_preserved'] = has(body, 0xda664e, 'mov', 'edx, 0xda8028') and has(body, 0xda66a9, 'push', '0xda80a0')
    checks['fixed_voltage_report_conversion'] = calls(body, dimmer + 'ConvertLevelToNormalisedRMSVoltageA')
    checks['scene_name_is_raw_string'] = call(body, 0xda78ff, scene + 'GetSceneName')
    checks['ordinary_scene_group_rows'] = calls(body, 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerSceneGroupCollection.GetItem')
    checks['special_scene_channel_rows'] = calls(body, 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerSceneChannelCollection.GetItem')
    checks['ordinary_raw_fade_not_unpacked'] = call(body, 0xda7c43, 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerSceneGroup.GetCompactedFadeTime') and call(body, 0xda7c4e, 'SysUtils.IntToStr')
    checks['ordinary_ramp_description_lookup'] = call(body, 0xda7beb, 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerSceneGroup.GetCompactedFadeTime') and call(body, 0xda7bfd, 'CIS_TEnumeratedTypeAttribute.GetDescriptionFromEnumeratedValueOrdinalValue')
    checks['cross_fade_formatter'] = call(body, 0xda799f, 'CIS_TCBusArchitecturalDimmerUnit.GetValuesFromArchDimmerSceneFadeTime')
    lifecycle = agent + 'AfterLoadProgrammingInformation'
    order = ['LoadUnit', 'LoadDimmingCurves', 'LoadChannels', 'LoadLogic', 'LoadScenes', 'PrepareScenesForUnit', 'LoadSpecialScenes', 'LoadErrorReporting']
    actual_order = [name for _, m, o in method(lifecycle)['instructions'] if m == 'call'
                    for name in order if o == hex(t.by_name[helper + name])]
    checks['exact_loader_order_and_single_preparation'] = actual_order == order
    create = agent + 'InternalCreate'
    fields = ['GroupAddress', 'ChannelMask1', 'ChannelMask2', 'ChannelMask3', 'ChannelMask4',
              'DMXChannelMapping', 'DMXChannelMaskCurrent', 'DMXChannelMask1', 'DMXChannelMask2',
              'DMXChannelMask3', 'DMXChannelMask4', 'DimmingCurve', 'ChannelMaxLevelA', 'NominalLineVoltage',
              'TurnOnThreshold', 'SceneUsed', 'SceneHasName', 'SceneNormal', 'SceneUsesRampRate',
              'SceneDryContact1', 'SceneDryContact2', 'SceneDryContact3', 'SceneLoadShed', 'SceneCBusLoss']
    checks['consumed_parameter_constructor_inventory'] = all(field in method(create)['literals'] for field in fields)
    checks['scene_constructor_128_data_and_name_slots'] = has(create, 0x12341df, 'cmp', 'dword ptr [ebp - 0x10], 0x81') and has(create, 0x123427b, 'cmp', 'dword ptr [ebp - 0x10], 0x81')
    load_scenes = helper + 'LoadScenes'
    checks['scene_loader_128_sparse_slots'] = has(load_scenes, 0x12390cc, 'cmp', 'dword ptr [ebp - 0xc], 0x80') and loader.SCENE_SLOTS == 128
    checks['scene_name_trim'] = call(load_scenes, 0x1238e6e, 'SysUtils.Trim')
    checks['scene_name_38_utf16_units'] = has(scene + 'SetSceneName', 0xd36a58, 'mov', 'ecx, 0x26') and calls(scene + 'SetSceneName', 'System.@UStrCopy')
    checks['scene_default_name'] = resource(0xd302f4) == 'New Scene' and call(scene + 'Init', 0xd363db, scene + 'SetSceneName')
    checks['scene_cross_fade_inverts_normal'] = has(load_scenes, 0x1238ed6, 'xor', 'dl, 1') and call(load_scenes, 0x1238edc, scene + 'SetCrossFadeScene')
    checks['scene_fade_little_endian'] = has(load_scenes, 0x1238f27, 'shl', 'eax, 8') and call(load_scenes, 0x1238f31, scene + 'SetCrossFadeTime')
    checks['scene_four_byte_channel_records'] = all(has(load_scenes, a, 'shl', 'edx, 2') for a in (0x1238f63, 0x1238fa4, 0x1238fbf, 0x1238fd8))
    checks['scene_inhibit_three_low_bits'] = has(load_scenes, 0x1238feb, 'and', 'eax, 7')
    checks['scene_unused_channel_bit8'] = any(m == 'test' and o.endswith(', 8') for _, m, o in method(load_scenes)['instructions'])
    checks['scene_target_scale_254_to_255'] = has(load_scenes, 0x123903e, 'fdiv', 'dword ptr [0x1239100]') and has(load_scenes, 0x1239044, 'fmul', 'dword ptr [0x1239104]') and struct.unpack('<ff', t.pe.get_data(0x1239100 - t.base, 8)) == (254., 255.)
    prepare = helper + 'PrepareScenesForUnit'
    checks['ordinary_scene_collection_only_prepared'] = has(prepare, 0x1239119, 'mov', 'eax, dword ptr [eax + 0x250]') and has(prepare, 0x1239143, 'mov', 'eax, dword ptr [eax + 0x250]')
    checks['first_channel_group_wins'] = call(prepare, 0x123919c, scene + 'IsGroupUsed') and has(prepare, 0x12391a3, 'jne', '0x1239203')
    checks['first_group_target_fade_and_inhibit_copied'] = all(call(prepare, address, 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerSceneGroup.' + name)
        for address, name in [(0x12391da, 'SetTargetLevel'), (0x12391ec, 'SetCompactedFadeTime'), (0x12391fe, 'SetInhibitCode')])
    special = helper + 'LoadSpecialScenes'
    checks['special_raw255_is_absent'] = has(special, 0x12392ab, 'cmp', 'dword ptr [ebp - 0xc], 0xff')
    checks['special_target_scale_254_to_255'] = has(special, 0x12392b7, 'fdiv', 'dword ptr [0x12393e0]') and has(special, 0x12392bd, 'fmul', 'dword ptr [0x12393e4]') and struct.unpack('<ff', t.pe.get_data(0x12393e0 - t.base, 8)) == (254., 255.)
    checks['special_loader_only_fills_channels'] = calls(special, 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerSceneChannelCollection.Add') and not calls(special, 'CIS_TCBusArchitecturalDimmerUnit.TArchDimmerSceneGroupCollection.Add')
    checks['special_fresh_groups_created_separately'] = has(scene + 'InternalCreate', 0xd364a9, 'mov', 'dword ptr [edx + 0x88], eax') and has(scene + 'InternalCreate', 0xd364c9, 'mov', 'dword ptr [edx + 0xa0], eax')
    load_channels = helper + 'LoadChannels'
    checks['cbus_four_masks_inverted'] = all(has(load_channels, address, 'xor', 'al, 1') for address in (0x12380c3, 0x12380fb, 0x1238133, 0x123816b))
    checks['dmx_four_masks_direct'] = all(call(load_channels, address, channel + f'SetDMXChannelMask{number}') for number, address in enumerate((0x12381be, 0x12381f4, 0x123822a, 0x1238260), 1))
    checks['dmx_patch_little_endian'] = has(load_channels, 0x12382fd, 'shl', 'ebx, 8') and call(load_channels, 0x1238335, channel + 'SetDMXChannel')
    checks['dmx_current_mask_guard_when_enable_unused'] = has(load_channels, 0x1238363, 'cmp', 'eax, 0xff') and call(load_channels, 0x123839f, channel + 'SetDMXChannel')
    checks['output_groups_native_lookup'] = call(load_channels, 0x123871d, 'CIS_TCommonCBus.TCBusGroupManager.GroupByAddress') and call(load_channels, 0x123873d, channel + 'SetOutputGroup')
    checks['logic_associations_nonzero_boolean'] = all(call(load_channels, address, 'CIS_Maths.IntToBool') for address in (0x12388be, 0x1238916, 0x123896e)) and calls('CIS_Maths.StrToBool', 'CIS_Maths.IntToBool')
    checks['boolean_array_normalizes_before_xor'] = calls('CIS_Maths.StrToBoolArray', 'CIS_Maths.StrToBool') and calls('CIS_TCGateAttribute.TBooleanArrayCGateAttribute.AsArrayBoolean', 'CIS_Maths.StrToBoolArray')
    checks['invalid_curve_falls_back_to_linear'] = any(m == 'cmp' and o.endswith(', 0xa') for _, m, o in method(channel + 'SetDimmingCurve')['instructions']) and any(m == 'mov' and o.endswith(', 1') for _, m, o in method(channel + 'SetDimmingCurve')['instructions'])
    enum = 'CIS_TCBusArchitecturalDimmerUnit.CIS_TCBusArchitecturalDimmerUnit'
    checks['exact_eleven_curve_descriptions'] = method(enum)['literals'][:11] == list(loader.CURVES) and call(enum, 0x138795c, 'CIS_TEnumeratedTypeAttribute.RegisterEnumeratedValueDescriptions')
    checks['exact_sixteen_ramp_descriptions'] = method('CIS_TCommonCBus.RegisterEnumerations')['literals'][81:97] == list(loader.RAMPS)
    rms_create = dimmer + 'InternalCreate'
    rms = dimmer + 'ConvertLevelToNormalisedRMSVoltageA'
    length = t.dword(0xd32234 - 4)
    rms_text = t.pe.get_data(0xd32234 - t.base, length * 2).decode('utf-16le')
    rms_points = tuple(tuple(map(int, p.strip().split('='))) for p in rms_text.split(','))
    checks['exact_fixed_rms_cache_42_points'] = length == 347 and rms_points == loader.RMS_A
    checks['fixed_rms_cache_constructor'] = has(rms_create, 0xd31b9a, 'mov', 'edx, 0xd32234') and call(rms_create, 0xd31ba8, 'Classes.TStrings.SetCommaText')
    checks['fixed_rms_cache_independent_of_editable_curves'] = has(rms, 0xd30ad7, 'mov', 'eax, dword ptr [eax + 0x26c]') and has(rms, 0xd30afc, 'mov', 'eax, dword ptr [eax + 0x26c]')
    checks['rms_interpolation_round_then_scale_truncation'] = all(call(rms, a, 'System.@ROUND') for a in (0xd30b7d, 0xd30bc3)) and call(rms, 0xd30bf0, dimmer + 'GetNominalLineVoltage') and has(rms, 0xd30bf8, 'mov', 'ecx, 0xff') and has(rms, 0xd30bfe, 'idiv', 'ecx')
    packed = 'CIS_TCBusArchitecturalDimmerUnit.GetSecondsMultiplierFromArchDimmerSceneFadeTime'
    checks['fade_unit_top_two_bits'] = has(packed, 0xd304c8, 'and', 'eax, 0xc000') and has(packed, 0xd304cd, 'shr', 'eax, 0xe')
    unpack = 'CIS_TCBusArchitecturalDimmerUnit.GetValuesFromArchDimmerSceneFadeTime'
    checks['all_four_fade_multipliers'] = all(has(unpack, a, m, o) for a, m, o in
        [(0xd30359, 'add', 'eax, eax'), (0xd3035b, 'lea', 'eax, [eax + eax*4]'),
         (0xd30369, 'imul', 'eax, dword ptr [ebp - 0x18], 0x3c'), (0xd30378, 'xor', 'eax, eax')])
    primary = 'CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetApplicationObject'
    checks['inherited_primary_application_object'] = has(primary, 0xcb80e9, 'mov', 'eax, dword ptr [eax + 0x88]') and call(primary, 0xcb8120, 'CIS_TCommonCBus.TCBUSApplicationManager.ApplicationByAddress')
    checks['halogen_body_uses_unit_selector'] = call(body, 0xda76d8, dimmer + 'GetHalogenCleanActionSelector')
    checks['halogen_action_uses_separate_scene_selector'] = call(action, 0xda618e, dimmer + 'GetSpecialSceneHalogenClean') and calls(action, scene + 'GetActionSelector')
    checks['loader_sets_unit_halogen_selector_only'] = calls(helper + 'LoadUnit', dimmer + 'SetHalogenCleanActionSelector') and not calls(helper + 'LoadUnit', scene + 'SetActionSelector') and not calls(special, scene + 'SetActionSelector')
    checks['special_duration_integer_setters_do_not_truncate_to_byte'] = all(has(dimmer + name, address, 'mov', 'dword ptr [ebp - 8], edx')
        for name, address in [('SetCBusLossFadeTime', 0xd332c3), ('SetHalogenCleanDuration', 0xd334db), ('SetHalogenFadeOn', 0xd3355f)])
    checks['distinct_selector_reference_fields'] = has(scene + 'InternalCreate', 0xd36440, 'mov', 'dword ptr [edx + 0x84], eax') and any(m == 'mov' and o == 'dword ptr [edx + 0x240], eax' for _, m, o in method(rms_create)['instructions'])
    checks['unused_error_level_is_not_network_selector'] = has('CIS_TCBusGOC2Unit.TGOC2Unit.InternalCreate', 0xd2e0d4, 'mov', 'dword ptr [edx + 0x1fc], eax') and calls(helper + 'LoadErrorReporting', 'CIS_TCBusGOC2Unit.TGOC2Unit.GetLevelUnused')
    input_method, output_method, other_method = (dimmer + 'Describe' + kind + 'GroupDependencyAdvanced' for kind in ('Input', 'Output', 'Other'))
    checks['input_scans_prepared_groups_not_special_channels'] = has(input_method, 0xd30e96, 'mov', 'eax, dword ptr [eax + 0xa0]') and has(input_method, 0xd30f39, 'mov', 'eax, dword ptr [eax + 0xa0]')
    checks['input_dmx_mode_and_four_allocated_levels'] = calls(input_method, dimmer + 'GetDMXModeEnabled') and all(calls(input_method, dimmer + f'GetDMXEnableMask{i}Level') for i in range(1, 5))
    checks['exact_dependency_resources'] = [resource(a) for a in (0x13c1e94, 0x13c2f6c, 0x13c21e4, 0x13c28c4, 0x13c2874, 0x13c29a0, 0x13c372c, 0x13c34ac)] == ['DMX Disable Update C-Bus Level', 'Scene %d', 'Channel %d', 'Logic Group', 'Logic Group (Unused)', 'Channel C-Bus disable Group', 'Enable DMX by Set allocation', 'Error Report Enable Group']
    checks['other_exact_three_references'] = all(calls(other_method, target) for target in (dimmer + 'GetChannelEnableGroup', dimmer + 'GetDMXEnableGroup', 'CIS_TCBusGOC2Unit.TGOC2Unit.GetEnableErrorGroup'))
    checks['output_channels_then_logic_groups'] = calls(output_method, dimmer + 'GetLogicGroups') and calls(output_method, channel + 'GetLogicGAAssociation')
    # Bind every consumed loader/helper/setter and report dependency span. The
    # receipt does not expose method instructions or all decoded literals.
    patterns = (r'CIS_TDIMARXCGateAgent\.(LoadUnit|LoadChannels|LoadLogic|LoadDimmingCurves|LoadScenes|PrepareScenesForUnit|LoadSpecialScenes|LoadErrorReporting|FindTriggerControl.*)',
                r'CIS_TDIMARXCGateAgent\.TDIMARXCGateAgent\.(InternalCreate|AfterLoadProgrammingInformation|GetSpecialSceneCGateAttribute)',
                r'CIS_TCBusArchitecturalDimmerUnit\.TArchDimmer(Unit|Channel|Scene|SceneChannel|SceneGroup)\.(InternalCreate|Init|Set.*|Get.*|Convert.*|Describe.*|IsGroupUsed)',
                r'CIS_TCBusArchitecturalDimmerUnit\.(GetValuesFromArchDimmerSceneFadeTime|GetSecondsMultiplierFromArchDimmerSceneFadeTime)',
                r'CIS_TCBusArchitecturalDimmerUnit\.TArchDimmer(HalogenClean|CBusLoss)Scene\.(InternalCreate|SetDirtyFlags)',
                r'CIS_TCBusGOC2Unit\.TGOC2Unit\.(InternalCreate|GetLevelUnused)',
                r'CIS_CBus.LevelToPercent', r'CIS_Maths\.(StrToBool|StrToBoolArray|IntToBool)')
    for name in t.by_name:
        if '..' not in name and any(re.fullmatch(p, name) for p in patterns):
            method(name)
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError('Architectural source checks failed: ' + ', '.join(failed))
    coordinates = [text for m in methods.values() for text in m['literals']
                   if re.search(r'[A-Za-z]:[\\/]|(?:^|[\\/])(?:Users|private)[\\/]|\.pas(?:$|[\s:])', text)]
    return {'format': 'cbus-project-documentor-architectural-static-v1',
            'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
            'original_executed': False, 'original_generated_page_comparison': 'not_obtained',
            'profiles': profiles, 'factory': rows, 'checks': checks,
            'model_module_sha256': {Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                                    for m in (body_model, loader, usage_model)},
            'methods': {name: {'start': hex(m['start']), 'end': hex(m['end']), 'sha256': m['sha256']}
                        for name, m in sorted(methods.items())},
            'literal_disclosure': {'private_compiler_coordinates_omitted': len(coordinates),
                                   'method_hashes_include_omitted_coordinates': True,
                                   'all_unselected_method_literals_omitted': True},
            'rms_a_points': [list(p) for p in rms_points], 'curves': list(loader.CURVES), 'ramps': list(loader.RAMPS),
            'limits': ['Fresh snapshot projection; prior GUI/process object histories are not reconstructed.',
                       'Complete explicit consumed PP and existing native display/link objects are required.',
                       '128 sparse ordinary scenes; special SceneGroups remain unprepared after a fresh load.',
                       'Unit and Halogen special-scene selectors are distinct fresh references.',
                       'Native integer fields admit explicit 0..65535 only; unknown ramp ordinals refuse.',
                       'A scene-name prefix splitting a surrogate refuses until original UTF-8 conversion is proved.',
                       'No original generated-page comparison, vendor execution, programming or physical acceptance.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.exe, args.map)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'checks': len(report['checks']), 'methods': len(report['methods']), 'profiles': len(report['profiles']),
                      'private_coordinates_omitted': report['literal_disclosure']['private_compiler_coordinates_omitted']}))
