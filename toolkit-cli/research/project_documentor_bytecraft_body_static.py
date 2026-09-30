"""Verify bounded old Bytecraft body/action rules without executing vendor code.

Inputs are explicit pinned EXE/MAP files. Receipts contain source identifiers,
hashes, checks and public report strings, never host paths or instruction bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit

DOC = 'CIS_TBytecraftDimmerDocumentor.TBytecraftDimmerDocumentor.'
UNIT = 'CIS_TCBusBytecraftDimmerUnit.TBytecraftUnit.'
SCENE = 'CIS_TCBusBytecraftDimmerUnit.TBytecraftScene.'
CHANNEL = 'CIS_TCBusBytecraftDimmerUnit.TBytecraftChannel.'
AGENT = 'CIS_TDIMPR12CGateAgent.TDIMPR12CGateAgent.'
BODY, ACTION, UNUSED = (DOC + suffix for suffix in ('DocumentHTML', 'ActionSelectorUse', 'IsChannelUnused'))
LOAD, CREATE, BITS = (AGENT + suffix for suffix in ('AfterLoadProgrammingInformation', 'InternalCreate', 'GetBitArrayElementValue'))
INIT = 'CIS_TCBusBytecraftDimmerUnit.CIS_TCBusBytecraftDimmerUnit'
GROUP_HTML, LEVEL_HTML = ('CIS_TDocumentorCommon.' + suffix for suffix in ('DisplayHTMLGroup', 'DisplayHTMLLevel'))
FORMAT_HTML = 'CIS_TDocumentorCommon.FormatHTMLString'
ENUM_SET = 'CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.SetAsInteger'
INPUT, OTHER = (UNIT + suffix for suffix in ('DescribeInputGroupDependencyAdvanced', 'DescribeOtherGroupDependencyAdvanced'))
ENABLE_GROUP = 'CIS_TDIMPR12CGateAgent.FindEnableControlGroupBySimpleAddress'
GOC_OTHER = 'CIS_TCBusGOCUnit.TGOCUnit.DescribeOtherGroupDependencyAdvanced'
CURVES = ('Lite 1', 'Lite 2', 'Lite 3', 'Non Dim', 'Lin RMS', '1:1')
FADES = ('Instantaneous', '4 s', '8 s', '12 s', '20 s', '30 s', '40 s', '1 min',
         '1.5 min', '2 min', '3 min', '5 min', '7 min', '10 min', '15 min', '17 min')
ASSESSMENT = Path(__file__).parent / 'experiments/2026-09-30/project-documentor-bytecraft-assessment.json'
METHODS = (BODY, ACTION, UNUSED, INIT, LOAD, CREATE, BITS,
           SCENE + 'IsUnused', SCENE + 'IsOnUnused', SCENE + 'IsOffUnused',
           UNIT + 'GetLogicGroups', CHANNEL + 'SetMaxChannelVoltage',
           CHANNEL + 'GetDMXCbusSwitchOverFadeTime', CHANNEL + 'GetCbusDMXSwitchOverFadeTime',
           GROUP_HTML, LEVEL_HTML, 'CIS_CBus.LevelToPercent', 'CIS_Maths.BytesToWord',
           'CIS_Maths.Int4BitArrayElementWithDefault', 'CIS_Maths.High4Bits', 'CIS_Maths.Low4Bits',
           AGENT + 'GetBitCBusDisable', AGENT + 'GetBitDMXCbusSwitchOverAction',
           FORMAT_HTML, ENUM_SET, CHANNEL + 'SetDMXPatchInfo', CHANNEL + 'SetChannelMinLevel',
           CHANNEL + 'SetChannelMaxLevel', INPUT, OTHER, ENABLE_GROUP, GOC_OTHER,
           'CIS_TCommonCBus.TCBUSUnit.DescribeOtherGroupDependencyAdvanced',
           'CIS_TCommonCBus.TCBusNetwork.GetEnableControlApplication')


def inspect(executable: Path, mapping: Path) -> dict:
    raw, symbols = executable.read_bytes(), mapping.read_bytes()
    if (hashlib.sha256(raw).hexdigest(), hashlib.sha256(symbols).hexdigest()) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(raw, symbols)
    methods = {name: image.method(name) for name in METHODS}
    assessment = json.loads(ASSESSMENT.read_text())

    def has(name, address, op, args):
        return (address, op, args) in methods[name]['instructions']

    def call(name, address, target):
        return has(name, address, 'call', hex(image.by_name[target]))

    def literal(name, address, value):
        return methods[name]['literal_at'].get(address) == value

    checks = {f'retained_span:{name}': methods[name]['sha256'] == assessment['methods'][name]['sha256']
              for name in (BODY, ACTION, UNUSED, LOAD, CREATE, INPUT, OTHER, SCENE + 'IsUnused', SCENE + 'IsOnUnused', SCENE + 'IsOffUnused')}
    checks.update({
        'body_base_first': call(BODY, 0x1012aed, 'CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML'),
        'body_bytecraft_class_guard': has(BODY, 0x1012af5, 'mov', 'edx, dword ptr [0xd38c84]') and has(BODY, 0x1012b02, 'je', '0x1013983'),
        'action_base_first': call(ACTION, 0x101424b, 'CIS_TProjectDocumentor.TUnitTypeDocumentor.ActionSelectorUse'),
        'action_bytecraft_class_guard': has(ACTION, 0x1014253, 'mov', 'edx, dword ptr [0xd38c84]') and has(ACTION, 0x1014260, 'je', '0x101435d'),
        'summary_lock_label': literal(BODY, 0x1012b0e, 'C-Bus Lock Enable Group: '),
        'summary_dmx_label': literal(BODY, 0x1012b43, 'DMX Enable Group: '),
        'restore_enabled_text': literal(BODY, 0x1012b84, 'Control Failure Scene: Enabled<br />'),
        'restore_disabled_text': literal(BODY, 0x1012bde, 'Control Failure Scene: Disabled<br />'),
        'restore_ramp_label': literal(BODY, 0x1012b91, 'Control Failure Scene Ramp Rate: '),
        'restore_ramp_scene_zero': has(BODY, 0x1012b96, 'xor', 'edx, edx') and call(BODY, 0x1012ba6, SCENE + 'GetRampRateOn'),
        'channel_table_open': literal(BODY, 0x1012bf8, '<table border="1">'),
        'channel_header': literal(BODY, 0x1012c08, '<tr><th>Channel</th><th>Groups</th><th>Logic Function</th><th>Curve</th><th>Min</th><th>Max</th>'),
        'lock_header_gate': has(BODY, 0x1012c21, 'jne', '0x1012c30') and literal(BODY, 0x1012c26, '<th>C-Bus Lock</th>'),
        'voltage_header': literal(BODY, 0x1012c33, '<th>Max RMS Voltage</th>'),
        'dmx_header_gate': has(BODY, 0x1012c4c, 'jne', '0x1012c5b') and literal(BODY, 0x1012c51, '<th>DMX</th><th>Take|Update</th><th>C-Bus Fade</th><th>DMX Fade</th>'),
        'restore_header_gate': has(BODY, 0x1012c65, 'je', '0x1012c74') and literal(BODY, 0x1012c6a, '<th>Restore Level</th>'),
        'header_closing_prefix': has(BODY, 0x1012c77, 'mov', 'ecx, dword ptr [ebp - 0x1c]') and literal(BODY, 0x1012c7a, '</tr>') and call(BODY, 0x1012c7f, 'System.@UStrCat3'),
        'channel_unused_group_then_patch': call(UNUSED, 0x10141f0, 'CIS_TCommonCBus.TCBusGroup.IsUnused') and has(UNUSED, 0x10141f7, 'je', '0x1014205') and call(UNUSED, 0x10141fc, CHANNEL + 'GetDMXPatchInfo') and has(UNUSED, 0x1014203, 'je', '0x1014209'),
        'channel_skip_unused': call(BODY, 0x1012cc7, UNUSED) and has(BODY, 0x1012cce, 'jne', '0x101337c'),
        'channel_one_based': has(BODY, 0x1012cdc, 'mov', 'eax, dword ptr [ebp - 0x10]') and has(BODY, 0x1012cdf, 'inc', 'eax'),
        'old_logic_null': has(UNIT + 'GetLogicGroups', 0xd39a61, 'xor', 'eax, eax'),
        'blank_resource': image.resource(image.dword(0x13c26cc)) == '&nbsp;',
        'used_output_gate': call(BODY, 0x1012e9b, 'CIS_TCommonCBus.TCBusGroup.IsUnused') and has(BODY, 0x1012ea2, 'jne', '0x1013022'),
        'voltage_255_line': has(BODY, 0x1012fc9, 'cmp', 'eax, 0xff') and literal(BODY, 0x1012fd3, '<td>LINE</td>'),
        'voltage_zero_normalizes_line': has(CHANNEL + 'SetMaxChannelVoltage', 0xd3af33, 'cmp', 'dword ptr [ebp - 8], 0') and has(CHANNEL + 'SetMaxChannelVoltage', 0xd3af3c, 'mov', 'edx, 0xff'),
        'unused_output_lock_before_four_blanks': has(BODY, 0x1013031, 'jne', '0x101305d') and has(BODY, 0x1013053, 'mov', 'edx, 4') and has(BODY, 0x10130bc, 'mov', 'edx, 0xa'),
        'dmx_cell_gate': has(BODY, 0x10130d5, 'jne', '0x101329f'),
        'dmx_zero_unused': has(BODY, 0x10130f3, 'jne', '0x1013194') and literal(BODY, 0x1013107, '<Unused>') and call(BODY, 0x101310c, 'CIS_TDocumentorCommon.FormatHTMLString'),
        'dmx_update_take': has(BODY, 0x10131ed, 'je', '0x10131fe') and literal(BODY, 0x10131f2, '<td>Update</td>') and literal(BODY, 0x1013201, '<td>Take</td>'),
        'fade_cell_order': call(BODY, 0x1013224, CHANNEL + 'GetCbusDMXSwitchOverFadeTime') and call(BODY, 0x101326e, CHANNEL + 'GetDMXCbusSwitchOverFadeTime'),
        'restore_cell_scene_zero': has(BODY, 0x10132af, 'xor', 'edx, edx') and call(BODY, 0x10132cd, 'CIS_TCBusBytecraftDimmerUnit.TBytecraftSceneOnOffChannel.GetPresetOnChannel') and has(BODY, 0x10132d4, 'je', '0x101332b'),
        'channel_closing_prefix': has(BODY, 0x1013361, 'mov', 'ecx, dword ptr [ebp - 0x1c]') and literal(BODY, 0x1013364, '</tr>') and call(BODY, 0x1013369, 'System.@UStrCat3'),
        'channel_order': has(BODY, 0x101337c, 'inc', 'dword ptr [ebp - 0x10]'),
        'scenes_label': literal(BODY, 0x1013395, 'Scenes: <br />'),
        'scene_table_missing_close_angle': literal(BODY, 0x10133a2, '<table border="1"'),
        'scene_header': literal(BODY, 0x10133af, '<tr><th>Scene</th><th>Scene Type</th><th>Trigger</th><th>Scene On</th><th>Scene Off</th></tr>'),
        'body_scene_start_one': has(BODY, 0x10133d6, 'mov', 'dword ptr [ebp - 0x10], 1'),
        'body_scene_skip_unused': call(BODY, 0x10133ee, SCENE + 'IsUnused') and has(BODY, 0x10133f5, 'jne', '0x101396a'),
        # MAP contains overloaded IntToStr symbols; by_name selects the other overload.
        'body_scene_number_no_increment': has(BODY, 0x1013406, 'mov', 'eax, dword ptr [ebp - 0x10]') and has(BODY, 0x1013409, 'call', '0x6198ac'),
        'advanced_group_trigger': literal(BODY, 0x1013451, '<td>Advanced</td>') and call(BODY, 0x101347f, GROUP_HTML),
        'basic_level_trigger': literal(BODY, 0x10134af, '<td>Basic</td>') and call(BODY, 0x10134dd, LEVEL_HTML),
        'on_subtable_gate': call(BODY, 0x101351c, SCENE + 'IsOnUnused') and has(BODY, 0x1013523, 'jne', '0x10136e7'),
        'on_subtable_open': literal(BODY, 0x1013529, '<td><table border="1">'),
        'nested_header': literal(BODY, 0x1013536, '<tr><th>Group</th><th>Level</th><th>Ramp Rate</th></tr>'),
        'on_entry_used_group_and_inclusion': has(BODY, 0x1013590, 'jne', '0x10136bf') and has(BODY, 0x10135bc, 'je', '0x10136bf'),
        'on_row_normal_suffix': literal(BODY, 0x10136a4, '</tr>') and has(BODY, 0x10136a9, 'mov', 'edx, dword ptr [ebp - 0x1c]'),
        'off_subtable_requires_advanced': call(BODY, 0x1013736, SCENE + 'IsOffUnused') and has(BODY, 0x101373d, 'jne', '0x101391f') and call(BODY, 0x1013754, SCENE + 'GetScenePresetMode') and has(BODY, 0x101375b, 'je', '0x101391f'),
        'off_entry_used_group_and_inclusion': has(BODY, 0x10137c8, 'jne', '0x10138f7') and has(BODY, 0x10137f4, 'je', '0x10138f7'),
        'off_row_normal_suffix': literal(BODY, 0x10138dc, '</tr>') and has(BODY, 0x10138e1, 'mov', 'edx, dword ptr [ebp - 0x1c]'),
        'scene_unused_on_and_off': call(SCENE + 'IsUnused', 0xd3c7dc, SCENE + 'IsOnUnused') and has(SCENE + 'IsUnused', 0xd3c7e3, 'je', '0xd3c7f1') and call(SCENE + 'IsUnused', 0xd3c7e8, SCENE + 'IsOffUnused'),
        'scene_on_use_only_inclusion': call(SCENE + 'IsOnUnused', 0xd3c7b0, 'CIS_TCBusBytecraftDimmerUnit.TBytecraftSceneOnOffChannel.GetPresetOnChannel'),
        'scene_off_use_only_inclusion': call(SCENE + 'IsOffUnused', 0xd3c754, 'CIS_TCBusBytecraftDimmerUnit.TBytecraftSceneOnOffChannel.GetPresetOffChannel'),
        'action_scene_start_zero': has(ACTION, 0x1014287, 'mov', 'dword ptr [ebp - 0x10], 0'),
        'action_skip_unused': call(ACTION, 0x101429f, SCENE + 'IsUnused') and has(ACTION, 0x10142a6, 'jne', '0x1014351'),
        'action_advanced_same_group': call(ACTION, 0x10142d7, SCENE + 'GetCBusRecallGroup') and call(ACTION, 0x10142e1, 'CIS_TCommonCBus.TLevel.GetGroup') and has(ACTION, 0x10142e6, 'cmp', 'ebx, eax'),
        'action_basic_same_level': call(ACTION, 0x1014322, SCENE + 'GetCBusRecallLevel') and has(ACTION, 0x1014327, 'cmp', 'eax, dword ptr [ebp - 8]'),
        'action_advanced_text': literal(ACTION, 0x10142ef, '<li />Advanced Trigger Scene '),
        'action_basic_text': literal(ACTION, 0x1014331, '<li />Trigger Scene '),
        'action_order_no_first_match_break': has(ACTION, 0x1014351, 'inc', 'dword ptr [ebp - 0x10]') and has(ACTION, 0x1014357, 'jne', '0x101428e'),
        'bytecraft_enum_descriptions': tuple(methods[INIT]['literals']) == CURVES + FADES,
        'curve_enum_registration': has(INIT, 0x1387b3e, 'mov', 'ecx, 5') and has(INIT, 0x1387b43, 'mov', 'eax, dword ptr [0xd38b34]'),
        'fade_enum_registration': has(INIT, 0x1387bd0, 'mov', 'ecx, 0xf') and has(INIT, 0x1387bd5, 'mov', 'eax, dword ptr [0xd38bb4]'),
        'percent_add_two': has('CIS_CBus.LevelToPercent', 0x7f2ad4, 'add', 'eax, 2') and has('CIS_CBus.LevelToPercent', 0x7f2ad7, 'imul', 'eax, eax, 0x64') and has('CIS_CBus.LevelToPercent', 0x7f2ada, 'mov', 'ecx, 0xff'),
        'loader_on_mask_setg': has(LOAD, 0x1246eae, 'and', 'edx, dword ptr [ebp - 0x10]') and has(LOAD, 0x1246eb1, 'setg', 'dl'),
        'loader_off_mask_setg': has(LOAD, 0x1246f53, 'and', 'edx, dword ptr [ebp - 0x14]') and has(LOAD, 0x1246f56, 'setg', 'dl'),
        'loader_mode_is_exact_one': has(LOAD, 0x1246bca, 'dec', 'eax') and has(LOAD, 0x1246bcb, 'sete', 'al'),
        'patch_even_high_odd_low': has(LOAD, 0x12467af, 'add', 'edx, edx') and has(LOAD, 0x12467b1, 'inc', 'edx') and has(LOAD, 0x12467e1, 'add', 'edx, edx') and call(LOAD, 0x12467eb, 'CIS_Maths.BytesToWord') and has('CIS_Maths.BytesToWord', 0x7f1e77, 'shl', 'eax, 8'),
        'nibble_even_low_odd_high': has('CIS_Maths.Int4BitArrayElementWithDefault', 0x7f110a, 'test', 'byte ptr [ebp - 8], 1') and call('CIS_Maths.Int4BitArrayElementWithDefault', 0x7f111a, 'CIS_Maths.High4Bits') and call('CIS_Maths.Int4BitArrayElementWithDefault', 0x7f112f, 'CIS_Maths.Low4Bits'),
        'bit_text_length_31': has(BITS, 0x12454ab, 'cmp', 'dword ptr [ebp - 0x1c], 0x1f'),
        'bit_half_rotation': has(BITS, 0x124550c, 'mov', 'ecx, 0xf') and has(BITS, 0x1245511, 'mov', 'edx, 0x11') and has(BITS, 0x1245535, 'mov', 'ecx, 0xf') and has(BITS, 0x124553a, 'mov', 'edx, 1'),
        'bit_true_only_character_one': has(BITS, 0x1245579, 'add', 'eax, eax') and has(BITS, 0x124557e, 'cmp', 'word ptr [edx + eax*2], 0x31'),
        'restore_bit_15': has(LOAD, 0x1246b4a, 'mov', 'edx, 0xf') and call(LOAD, 0x1246b52, AGENT + 'GetBitDMXCbusSwitchOverAction'),
        'dmx_fade_field': has(CHANNEL + 'GetDMXCbusSwitchOverFadeTime', 0xd3ab30, 'mov', 'eax, dword ptr [eax + 0xac]') and has(LOAD, 0x1246a98, 'mov', 'eax, dword ptr [eax + 0xac]'),
        'cbus_fade_field': has(CHANNEL + 'GetCbusDMXSwitchOverFadeTime', 0xd3ab54, 'mov', 'eax, dword ptr [eax + 0xb0]') and has(LOAD, 0x1246b0a, 'mov', 'eax, dword ptr [eax + 0xb0]'),
        'level_link_address_not_value': call(LEVEL_HTML, 0xca5ce9, 'CIS_TCBusObject.TCGateObject.GetAddressAsString'),
        'group_unused_name_escaped': has(GROUP_HTML, 0xca5b56, 'je', '0xca5b76') and call(GROUP_HTML, 0xca5b6f, 'CIS_TDocumentorCommon.FormatHTMLString'),
        'group_used_name_raw': has(GROUP_HTML, 0xca5bc4, 'mov', 'eax, dword ptr [eax + 0x9c]') and has(GROUP_HTML, 0xca5bcc, 'call', 'dword ptr [ecx + 0x2c]'),
        'level_name_raw': has(LEVEL_HTML, 0xca5cfc, 'mov', 'eax, dword ptr [eax + 0x9c]') and has(LEVEL_HTML, 0xca5d04, 'call', 'dword ptr [ecx + 0x2c]'),
        'html_numeric_angle_escaping': literal(FORMAT_HTML, 0xca5dd5, '&#60;') and literal(FORMAT_HTML, 0xca5dda, '<') and literal(FORMAT_HTML, 0xca5df6, '&#62;') and literal(FORMAT_HTML, 0xca5dfb, '>'),
        'enum_invalid_raises_not_clamps': has(ENUM_SET, 0x8483ef, 'jl', '0x8483ff') and has(ENUM_SET, 0x8483fd, 'jle', '0x848415') and literal(ENUM_SET, 0x8483ff, 'Invalid value') and call(ENUM_SET, 0x848410, 'System.@RaiseExcept'),
        'patch_setter_passes_integer': has(CHANNEL + 'SetDMXPatchInfo', 0xd3abd2, 'mov', 'edx, dword ptr [ebp - 8]') and has(CHANNEL + 'SetDMXPatchInfo', 0xd3abe2, 'mov', 'eax, dword ptr [eax + 0x8c]'),
        'min_setter_passes_integer': has(CHANNEL + 'SetChannelMinLevel', 0xd3ad52, 'mov', 'edx, dword ptr [ebp - 8]') and has(CHANNEL + 'SetChannelMinLevel', 0xd3ad62, 'mov', 'eax, dword ptr [eax + 0x9c]'),
        'max_setter_passes_integer': has(CHANNEL + 'SetChannelMaxLevel', 0xd3acf2, 'mov', 'edx, dword ptr [ebp - 8]') and has(CHANNEL + 'SetChannelMaxLevel', 0xd3ad02, 'mov', 'eax, dword ptr [eax + 0x98]'),
        'input_inherited_first': call(INPUT, 0xd39bd5, 'CIS_TCommonCBus.TCBUSUnit.DescribeInputGroupDependencyAdvanced'),
        'input_channel_identity': has(INPUT, 0xd39c12, 'cmp', 'eax, dword ptr [ebp - 8]'),
        'input_scene_start_zero': has(INPUT, 0xd39c36, 'mov', 'dword ptr [ebp - 0x18], 0'),
        'input_used_scene_and_on_or_off': has(INPUT, 0xd39c55, 'jne', '0xd39d70') and has(INPUT, 0xd39c81, 'jne', '0xd39caf') and has(INPUT, 0xd39ca9, 'je', '0xd39d70'),
        'input_recall_nonnull_used': has(INPUT, 0xd39cc7, 'je', '0xd39d2d') and has(INPUT, 0xd39ce6, 'jne', '0xd39d2d'),
        'input_label_resources': image.resource(image.dword(0x13c2f6c)) == 'Scene %d' and image.resource(image.dword(0x13c2f18)) == 'Scene %d (Unused)',
        'input_scene_number_one_based': has(INPUT, 0xd39d04, 'inc', 'edx') and has(INPUT, 0xd39d49, 'inc', 'edx'),
        'input_channel_major_scene_minor': has(INPUT, 0xd39d70, 'inc', 'dword ptr [ebp - 0x18]') and has(INPUT, 0xd39d76, 'jne', '0xd39c3d') and has(INPUT, 0xd39d7c, 'inc', 'dword ptr [ebp - 0x14]') and has(INPUT, 0xd39d82, 'jne', '0xd39bfc'),
        'other_inherited_first': call(OTHER, 0xd39dfb, 'CIS_TCBusGOCUnit.TGOCUnit.DescribeOtherGroupDependencyAdvanced'),
        'other_disable_and_switch_identity_order': has(OTHER, 0xd39e08, 'cmp', 'eax, dword ptr [ebp - 8]') and has(OTHER, 0xd39e3c, 'cmp', 'eax, dword ptr [ebp - 8]'),
        'other_resources': image.resource(0xd38b24) == 'C-Bus Disable Group' and image.resource(0xd38b2c) == 'DMX Switch',
        'old_input_and_other_slots': image.slot('CIS_TDIMPR12..TDIMPR12', 0x128) == INPUT and image.slot('CIS_TDIMPR12..TDIMPR12', 0x130) == OTHER,
        'goc_other_common_first': call(GOC_OTHER, 0xd203fc, 'CIS_TCommonCBus.TCBUSUnit.DescribeOtherGroupDependencyAdvanced'),
        'goc_other_area_identity': call(GOC_OTHER, 0xd20404, 'CIS_TCBusGOCUnit.TGOCUnit.GetAreaGroupAddress') and has(GOC_OTHER, 0xd20409, 'cmp', 'eax, dword ptr [ebp - 8]') and has(GOC_OTHER, 0xd2040c, 'jne', '0xd20435'),
        'goc_other_area_label': image.resource(image.dword(0x13c2550)) == 'Area Group' and literal(GOC_OTHER, 0xd20423, '|'),
        'area_pp_binding': literal(CREATE, 0x1245899, 'AreaGroupAddress') and has(CREATE, 0x12458b9, 'mov', 'dword ptr [edx + 0xf4], eax') and has(LOAD, 0x1246636, 'mov', 'eax, dword ptr [eax + 0xf4]'),
        'area_primary_add_group': has(LOAD, 0x124664f, 'call', 'dword ptr [edx + 0xb0]') and has(LOAD, 0x124665b, 'mov', 'cl, 1') and call(LOAD, 0x124665e, 'CIS_TCommonCBus.TCBusGroupManager.FindGroupByAddress') and call(LOAD, 0x124666d, 'CIS_TCBusGOCUnit.TGOCUnit.SetAreaGroupAddress'),
        'control_enable_helper_both_bindings': call(LOAD, 0x12466f4, ENABLE_GROUP) and call(LOAD, 0x1246725, ENABLE_GROUP),
        'enable_group_application': call(ENABLE_GROUP, 0x12463b4, 'CIS_TCommonCBus.TCBusNetwork.GetEnableControlApplication'),
        'enable_group_add_and_null_fallback255': has(ENABLE_GROUP, 0x12463dc, 'mov', 'cl, 1') and call(ENABLE_GROUP, 0x12463e4, 'CIS_TCommonCBus.TCBusGroupManager.FindGroupByAddress') and has(ENABLE_GROUP, 0x12463f0, 'jne', '0x1246404') and has(ENABLE_GROUP, 0x12463f4, 'mov', 'edx, 0xff'),
    })
    pp_fields = {
        'DMXPatchInfo': (0x114, 0x12459c9, 0x12459e9, 0x124678e),
        'CBusDisable': (0x118, 0x12459ef, 0x1245a0f, 0x12453f6),
        'ChannelMinLevel': (0x11c, 0x1245a15, 0x1245a35, 0x12468d2),
        'ChannelMaxLevel': (0x120, 0x1245a3b, 0x1245a5b, 0x124691d),
        'MaxChannelVoltage': (0x124, 0x1245a61, 0x1245a81, 0x1246968),
        'ChannelDimmerCurve': (0x128, 0x1245a87, 0x1245aa7, 0x12469b6),
        'DMXCbusSwitchOverActionAndRestoreMode': (0x12c, 0x1245aad, 0x1245acd, 0x1245422),
        'DMXCbusSwitchOverFadeTime': (0x130, 0x1245ad3, 0x1245af3, 0x1246a41),
        'CbusDMXSwitchOverFadeTime': (0x134, 0x1245af9, 0x1245b19, 0x1246aad),
    }
    for name, (offset, name_at, store_at, read_at) in pp_fields.items():
        reader = AGENT + 'GetBitCBusDisable' if name == 'CBusDisable' else AGENT + 'GetBitDMXCbusSwitchOverAction' if name == 'DMXCbusSwitchOverActionAndRestoreMode' else LOAD
        register = 'edx' if reader != LOAD else 'eax'
        checks['pp_field:' + name] = (literal(CREATE, name_at, name)
            and has(CREATE, store_at, 'mov', f'dword ptr [edx + {hex(offset)}], eax')
            and has(reader, read_at, 'mov', f'{register}, dword ptr [eax + {hex(offset)}]'))
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError('Bytecraft body source differs: ' + ', '.join(failed))
    return {
        'format': 'cbus-project-documentor-bytecraft-body-static-v1',
        'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256, 'checks': checks,
        'methods': {name: {'sha256': row['sha256'], 'bytes': row['end'] - row['start']} for name, row in methods.items()},
        'curve_descriptions': list(CURVES), 'fade_descriptions': list(FADES), 'placeholder': '&nbsp;',
        'dmx_unpatched_text': '&#60;Unused&#62;',
        'pp_rules': {
            'AreaGroupAddress': 'one explicit address in primary application; inherited Other prints Area Group| first on exact identity, including255',
            'CBusDisableGroupAddress': 'one explicit address in Enable Control application203; lookup add=true, null fallback255',
            'DMXCBusSwitchAddress': 'one explicit address in Enable Control application203; same lookup policy',
            'DMXPatchInfo': '24 bytes: even byte high, odd byte low for each channel',
            'CBusDisable': '16 explicit bit tokens: effective bit c is raw token (c+8)%16',
            'DMXCbusSwitchOverActionAndRestoreMode': 'same half rotation; channel c uses effective bit c; RestoreMode uses effective bit15 (raw token7)',
            'ChannelDimmerCurve': '6 bytes; channel c selects low nibble if even, high if odd',
            'DMXCbusSwitchOverFadeTime': '6 packed bytes; low-even/high-odd; DMX Fade column',
            'CbusDMXSwitchOverFadeTime': '6 packed bytes; low-even/high-odd; C-Bus Fade column',
            'MaxChannelVoltage': '12 values; setter maps zero to255;255 renders LINE',
            'ChannelMinLevel': '12 explicit values; percent=((value+2)*100)//255',
            'ChannelMaxLevel': '12 explicit values; same percentage conversion',
        },
        'assessment_correction': 'Retained assessment omitted SETG DL after both masked scene inclusion values. Channels8..11 preserve inclusion; mode is record0==1.',
        'admission_limits': 'Consumed curve ordinal0..5, fade ordinal0..15, level byte0..255. DMX patch pair can form word0..65535; any narrower adapter patch range is an explicit adapter restriction, not an original setter clamp. Arbitrary attribute callbacks/history and malformed bit strings remain outside this proof.',
        'original_execution': 'not_executed', 'original_generated_page_comparison': 'not_obtained',
        'boundary': 'Static old DIMPR12 body/action consumer proof. No L1 admission, original loader execution, GUI history or whole-page claim.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inspect(args.executable, args.map_file), indent=2) + '\n')


if __name__ == '__main__':
    main()
