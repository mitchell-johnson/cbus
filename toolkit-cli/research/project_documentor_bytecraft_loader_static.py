"""Verify old DIMPR12 scene decoding from bounded static methods and schema."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit
from project_documentor_bytecraft_usage_static import inspect as inspect_usage

ASSESSMENT = Path(__file__).parent / 'experiments/2026-09-30/project-documentor-bytecraft-assessment.json'
PREFIX = 'CIS_TCBusBytecraftDimmerUnit.'
METHODS = {
    'load': 'CIS_TDIMPR12CGateAgent.TDIMPR12CGateAgent.AfterLoadProgrammingInformation',
    'create': 'CIS_TDIMPR12CGateAgent.TDIMPR12CGateAgent.InternalCreate',
    'count': 'CIS_TDIMPR12.TDIMPR12.GetMaxScenes',
    'create_scenes': PREFIX + 'TBytecraftUnit.CreateScenes',
    'mode': PREFIX + 'TBytecraftScene.SetScenePresetMode',
    'on': PREFIX + 'TBytecraftSceneOnOffChannel.SetPresetOnChannel',
    'off': PREFIX + 'TBytecraftSceneOnOffChannel.SetPresetOffChannel',
    'variant_bool': 'Variants.@VarFromBool',
    'array': 'CIS_Maths.IntArrayElementWithDefault',
    'nibble': 'CIS_Maths.Int4BitArrayElementWithDefault',
    'high': 'CIS_Maths.High4Bits',
    'low': 'CIS_Maths.Low4Bits',
    'find_group': 'CIS_TDIMPR12CGateAgent.FindTriggerControlGroupBySimpleAddress',
    'find_level': 'CIS_TDIMPR12CGateAgent.FindTriggerControlGroupLevelBySimpleAddress',
    'group_lookup': 'CIS_TCommonCBus.TCBusGroupManager.GroupByAddress',
    'level_lookup': 'CIS_TCommonCBus.TLevelManager.FindLevelByAddress',
    'find_enable': 'CIS_TDIMPR12CGateAgent.FindEnableControlGroupBySimpleAddress',
    'enable_application': 'CIS_TCommonCBus.TCBusNetwork.GetEnableControlApplication',
}


def inspect(executable: Path, mapping: Path, specification: Path) -> dict:
    raw, symbols, schema = executable.read_bytes(), mapping.read_bytes(), specification.read_bytes()
    digest = lambda value: hashlib.sha256(value).hexdigest()
    assessment = json.loads(ASSESSMENT.read_text())
    if (digest(raw), digest(symbols)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    if digest(schema) != assessment['spec_sha256']['DIMPR12.xml']:
        raise ValueError('Original DIMPR12 schema hash mismatch')
    usage = inspect_usage(executable, mapping)
    image = _Toolkit(raw, symbols)
    methods = {key: image.method(name) for key, name in METHODS.items()}
    retained = {name: image.method(name) for name in assessment['methods']}
    checks = {'output_registration_checks': all(usage['checks'].values()),
              'all_13_assessment_spans_reproduced': len(retained) == 13 and all(
                  (hex(row['start']), hex(row['end']), row['sha256']) ==
                  (assessment['methods'][name]['start'], assessment['methods'][name]['end'],
                   assessment['methods'][name]['sha256']) for name, row in retained.items())}
    sites = {
        'count_33': ('count', 0x1014651, 'mov', 'dword ptr [ebp - 8], 0x21'),
        'scene_count_vmt': ('create_scenes', 0xd399d0, 'call', 'dword ptr [edx + 0x190]'),
        'scene_channel_count_vmt': ('create_scenes', 0xd399eb, 'call', 'dword ptr [edx + 0x188]'),
        'record_count_33': ('create', 0x1245b6d, 'cmp', 'dword ptr [ebp - 8], 0x21'),
        'mode_exact_one': ('load', 0x1246bca, 'dec', 'eax'),
        'mode_normalize_low_byte': ('load', 0x1246bcb, 'sete', 'al'),
        'recall_group_index_1': ('load', 0x1246c22, 'mov', 'edx, 1'),
        'selector_address_index_2': ('load', 0x1246c90, 'mov', 'edx, 2'),
        'link_group_index_3': ('load', 0x1246d10, 'mov', 'edx, 3'),
        'on_mask_index_4': ('load', 0x1246d6d, 'mov', 'edx, 4'),
        'on_mask_index_5': ('load', 0x1246db2, 'mov', 'edx, 5'),
        'off_mask_index_18': ('load', 0x1246df7, 'mov', 'edx, 0x12'),
        'off_mask_index_19': ('load', 0x1246e3c, 'mov', 'edx, 0x13'),
        'on_bit_shift': ('load', 0x1246eac, 'shl', 'edx, cl'),
        'on_mask': ('load', 0x1246eae, 'and', 'edx, dword ptr [ebp - 0x10]'),
        'on_normalize_low_byte': ('load', 0x1246eb1, 'setg', 'dl'),
        'off_bit_shift': ('load', 0x1246f51, 'shl', 'edx, cl'),
        'off_mask': ('load', 0x1246f53, 'and', 'edx, dword ptr [ebp - 0x14]'),
        'off_normalize_low_byte': ('load', 0x1246f56, 'setg', 'dl'),
        'on_mask_high_byte': ('load', 0x1246d79, 'shl', 'ebx, 8'),
        'on_mask_add_low': ('load', 0x1246dbc, 'add', 'ebx, eax'),
        'off_mask_high_byte': ('load', 0x1246e03, 'shl', 'ebx, 8'),
        'off_mask_add_low': ('load', 0x1246e46, 'add', 'ebx, eax'),
        'on_level_offset_6': ('load', 0x1246ef0, 'add', 'edx, 6'),
        'off_level_offset_20': ('load', 0x1246f95, 'add', 'edx, 0x14'),
        'ramp_on_nibble_9': ('load', 0x124700c, 'mov', 'edx, 9'),
        'ramp_off_nibble_37': ('load', 0x1247069, 'mov', 'edx, 0x25'),
        'mode_setter_low_byte': ('mode', 0xd3cabf, 'mov', 'byte ptr [ebp - 5], dl'),
        'on_setter_low_byte': ('on', 0xd3d66f, 'mov', 'byte ptr [ebp - 5], dl'),
        'off_setter_low_byte': ('off', 0xd3d6ef, 'mov', 'byte ptr [ebp - 5], dl'),
        'variant_boolean_type': ('variant_bool', 0x62f4c4, 'mov', 'word ptr [esi], 0xb'),
        'variant_boolean_compare': ('variant_bool', 0x62f4c9, 'cmp', 'bl, 1'),
        'variant_boolean_invert_carry': ('variant_bool', 0x62f4cc, 'cmc', ''),
        'variant_boolean_zero_or_minus_one': ('variant_bool', 0x62f4cd, 'sbb', 'eax, eax'),
        'variant_boolean_word': ('variant_bool', 0x62f4cf, 'mov', 'word ptr [esi + 8], ax'),
        'missing_array_returns_default': ('array', 0x7f0f8a, 'mov', 'eax, dword ptr [ebp - 0xc]'),
        'missing_nibble_returns_default': ('nibble', 0x7f113a, 'mov', 'eax, dword ptr [ebp - 0xc]'),
        'nibble_index_divided_by_2': ('nibble', 0x7f10f6, 'shr', 'eax, 1'),
        'odd_nibble_high': ('nibble', 0x7f111a, 'call', hex(methods['high']['start'])),
        'even_nibble_low': ('nibble', 0x7f112f, 'call', hex(methods['low']['start'])),
        'high_nibble_mask': ('high', 0x7f1084, 'and', 'eax, 0xf0'),
        'high_nibble_shift': ('high', 0x7f1089, 'shr', 'eax, 4'),
        'low_nibble_mask': ('low', 0x7f10a4, 'and', 'eax, 0xf'),
        'group_add_true': ('find_group', 0x124606c, 'mov', 'cl, 1'),
        'level_find_address': ('find_level', 0x124621e, 'call', hex(image.by_name[
            'CIS_TCommonCBus.TLevelManager.FindLevelByAddress'])),
        'level_add_true': ('find_level', 0x1246216, 'mov', 'cl, 1'),
        'nil_group_only_level_branch': ('find_level', 0x12461e8, 'cmp', 'dword ptr [ebp - 4], 0'),
        'group_creation_capacity': ('group_lookup', 0xf28bc0, 'cmp', 'eax, 0x100'),
        'group_created_before_255_name_branch': ('group_lookup', 0xf28bce, 'call', hex(image.by_name[
            'CIS_TCommonCBus.TCBusGroupManager.Add'])),
        'group_255_name_branch': ('group_lookup', 0xf28be1, 'cmp', 'dword ptr [ebp - 8], 0xff'),
        'level_address_match': ('level_lookup', 0xf27497, 'cmp', 'eax, dword ptr [ebp - 8]'),
        'level_created_if_missing': ('level_lookup', 0xf274ce, 'call', hex(image.by_name[
            'CIS_TCommonCBus.TLevelManager.Add'])),
        'new_level_address_set': ('level_lookup', 0xf274dc, 'call', hex(image.by_name[
            'CIS_TCBusObject.TCGateObject.SetAddressAsInteger'])),
        'new_level_value_set': ('level_lookup', 0xf274e7, 'call', hex(image.by_name[
            'CIS_TCommonCBus.TLevel.SetValue'])),
        'dmx_switch_enable_group': ('load', 0x12466f4, 'call', hex(methods['find_enable']['start'])),
        'disable_enable_group': ('load', 0x1246725, 'call', hex(methods['find_enable']['start'])),
        'enable_application_lookup': ('find_enable', 0x12463b4, 'call', hex(methods['enable_application']['start'])),
        'enable_application_203': ('enable_application', 0xf2b13d, 'mov', 'edx, 0xcb'),
        'enable_add_group': ('find_enable', 0x12463dc, 'mov', 'cl, 1'),
        'enable_fallback_255': ('find_enable', 0x12463f4, 'mov', 'edx, 0xff'),
    }
    for name, (key, address, op, args) in sites.items():
        checks[name] = (address, op, args) in methods[key]['instructions']
    checks['scene_count_slot'] = image.slot('CIS_TDIMPR12..TDIMPR12', 0x190) == METHODS['count']
    checks['record_name_format'] = 'PresetRec%2.2d' in methods['create']['literals']
    variant = hex(methods['variant_bool']['start'])
    checks['all_bool_setters_use_variant_bool'] = all(
        any(op == 'call' and args == variant for _, op, args in methods[key]['instructions'])
        for key in ('mode', 'on', 'off'))
    # Each consumed packed getter passes ECX=0 immediately before its index.
    defaults = (0x1246bc1, 0x1246c20, 0x1246c8e, 0x1246d0e, 0x1246d6b,
                0x1246db0, 0x1246df5, 0x1246e3a, 0x1246ef3, 0x1246f98,
                0x124700a, 0x1247067)
    checks['all_12_packed_getters_default_zero'] = all(
        (address, 'xor', 'ecx, ecx') in methods['load']['instructions'] for address in defaults)
    # The hash-pinned decoded specification retains its vendor copyright line.
    parameters = {row.findtext('Name'): row for row in ET.fromstring(
        schema[schema.index(b'<?xml'):]).iter('Param')}
    records = [parameters.get(f'PresetRec{index:02d}') for index in range(33)]
    checks['schema_all_33_records_32_zero_defaults'] = all(row is not None
        and row.findtext('ArraySize') == '32' and row.findtext('Type') == 'int'
        and row.findtext('ProgramMethod') == 'gocbyt'
        and row.findtext('DefaultValue', '').split() == ['0'] * 32 for row in records)
    if not all(checks.values()):
        raise ValueError('Bytecraft loader source differs: ' + ', '.join(
            name for name, passed in checks.items() if not passed))
    return {
        'format': 'cbus-project-documentor-bytecraft-loader-static-v1',
        'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256, 'spec_sha256': digest(schema),
        'checks': checks,
        'methods': {METHODS[key]: {field: hex(row[field]) if field in ('start', 'end') else row[field]
            for field in ('start', 'end', 'sha256')} for key, row in methods.items()},
        'assessment_spans_reproduced': list(retained),
        'scene_count': 33, 'channel_count': 12, 'record_size': 32,
        'native_packed_array_default': 0,
        'adapter_policy': 'Complete explicit records only; no saved defaults synthesized.',
        'assessment_correction': 'The previous hazard omitted SETG DL after both mask ANDs. '
            'Inclusions normalize before the low-byte setter; channels 8..11 remain usable. '
            'Mode likewise uses SETE AL for exact value 1.',
        'original_loader_execution': 'not_executed',
        'original_generated_page_comparison': 'not_obtained',
        'prior_scene_history': 'not_modeled',
        'recall_binding': 'Group 255 is an unused group object, not a nil sentinel. '
            'Selector 255 is an Address lookup, not a nil sentinel. Missing groups can be '
            'created below manager capacity 256; missing levels are created with '
            'Address=Value. A nil group yields a nil level. No metadata creation is admitted.',
        'summary_group_application': 203,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map-file', required=True, type=Path)
    parser.add_argument('--specification', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inspect(args.executable, args.map_file, args.specification), indent=2) + '\n')


if __name__ == '__main__':
    main()
