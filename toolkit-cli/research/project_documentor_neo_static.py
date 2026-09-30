"""Pin source-only Neo/NeoPro documentor markup and fresh-model PP rules.

Reads the exact original Toolkit EXE/MAP without executing vendor instructions,
loading projects, or accessing C-Gate/hardware. Method hashes and extracted UI
literals are evidence for bounded adapters, not generated-page acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from project_documentor_static import EXE_SHA256, MAP_SHA256, UNIT_FACTORY, _Toolkit
from project_documentor_classic_key_static import BISTABLE_GUID, _interface_ancestry
from key_preset_families import Image, micro_function_groups, subsets, template_groups

NEO = "CIS_TNeoInputDocumentor.TNeoInputDocumentor.DocumentHTML"
PRO = "CIS_TNeoProInputDocumentor.TNeoProInputDocumentor.DocumentHTML"
HAS_SCENES = "CIS_TNeoInputDocumentor.TNeoInputDocumentor.HasScenes"
CLASSIC = "CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.DocumentHTML"
AGENT = "CIS_TCoreNeoInputCGateAgent.TCoreNeoInputCGateAgent."
KEY_VALUES = "CIS_TCoreNeoInputCGateAgent.GetKeyValues"
SCENE_COMMANDS = "CIS_TCoreNeoInputCGateAgent.GetSceneCommands"
EXTENSION = "CIS_TInputKeyExtensionNeo.TInputKeyExtensionNeo."
KEY = "CIS_TInputKey.TInputKey."
FIRST_GROUP = "CIS_TInputKey.TInputBlockCollection.ItemByGroup"
BLOCK_GROUP = "CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.GetBlockGroup"
MACRO = "CIS_TKeyMacroFunction.TKeyMacroFunction."
TEMPLATE = "CIS_TKeyMacroFunction.TKeyMacroFunctionTemplate."
PHYSICAL_KEYS = {"KEYA3": 3, "KEYB4": 4, "KEYM4": 4, "KEYM8": 8, "KEYE1": 4}
NEO_LITERALS = (
    '<br />', 'Scenes<br />', '<table border="1">',
    '<tr><th>Scene</th><th>Triggers</th><th>Groups</th><th>Level</th></tr>',
    '<tr><td>', '</td>', '<td><table border="1"><tr><th>Action Selector</th><th>Ramp Rate</th></tr>',
    '<tr><td>', '</td>', '<td>', '</td></tr>', '</table></td>', '<td>', '</td>',
    '<td>', '<td>', '%', '<br />', '<br />', '</td>', '</td>', '</tr>', '</table>',
)
METHODS = (
    NEO, PRO, HAS_SCENES, CLASSIC, AGENT + "InternalCreate", AGENT + "AfterLoadProgrammingInformation",
    AGENT + "GetControlAppGroup", KEY_VALUES, SCENE_COMMANDS,
    *(EXTENSION + suffix for suffix in ("InternalCreate", "AfterConstruction", "GetScene", "GetSceneRampRate",
      "GetSceneTriggerLevel", "SetScene", "SetSceneRampRate", "SetSceneTriggerLevel", "HandleSceneAfterChangeEvent")),
    *(KEY + suffix for suffix in ("GetIsSceneKey", "SetMacroFunctionTemplate", "GetPrimaryBlock",
      "GetApplicationForKey", "RefreshKeySecondaryFromBlockSecondary", "RefreshKeyApplicationFromKeySecondary",
      "CalcLinearBlock", "InternalCreate")),
    FIRST_GROUP, BLOCK_GROUP,
    "CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.GetBlockApplications",
    "CIS_TInputKey.TInputBlock.SecondaryApplicationMatchesApplicationState",
    "CIS_TInputKey.TInputBlock.GetApplicationForBlock", "CIS_TCommonCBus.TCBusGroupManager.GroupByAddress",
    "CIS_TDocumentorCommon.DisplayHTMLGroup", "CIS_TDocumentorCommon.DisplayHTMLLevel",
    "CIS_CBus.LevelToPercent", "CIS_Maths.NibblesToInt",
    "CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.IsJoinModeSupported",
    "CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsKeyConnected",
    "CIS_TKEYEx.TKEYEx.IsKeyConnected", "CIS_TKEYEx.TKEYEx.GetDefaultKeyMask",
    "CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.LoadKeyMask",
    "CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.SetDefaultKeysIfNeeded",
    "CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.InternalCreate",
    "CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.InternalCreate",
    *(KEY + suffix for suffix in ("RefreshMacroFunctionFromTemplate", "GetIsSceneModifyKey",
      "HandleMacroFunctionTemplateAfterChangeEvent", "RefreshBlocksFromTemplate", "RefreshBlocksFromTemplateScene")),
    MACRO + "AssignTemplate", MACRO + "AssignTemplate_Microfunctions", TEMPLATE + "GetMicroFunctionGroupDefault",
    "CIS_TKeyMacroFunction.InitialiseKeyMacroFunctionFactory",
    "CIS_TKeyMicroFunctionGroup.InitialiseKeyMicroFunctionGroupFactory",
    "CIS_TKEYEx.TKEYEx.InfraredBankPropertyEnabled",
    "CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.AfterLoadProgrammingInformation",
    "CIS_TCustomFlashObject.TFlashObjectReference.Create", "CIS_TCustomFlashObject.TFlashObjectReference.Clear",
    "CIS_TCommonCBus.TLevelManager.FindLevelByAddress",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_file: Path) -> dict:
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if _sha(raw) != EXE_SHA256 or _sha(symbols) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(raw, symbols)
    methods = {name: image.method(name) for name in METHODS}
    tables = Image(exe, map_file)
    all_subsets = subsets(tables)
    neo_subsets = all_subsets["NEO"]
    macro_groups, templates = micro_function_groups(tables), template_groups(tables)
    first_matches = {}
    for kind, groups in templates.items():
        for group in groups:
            vector = tuple(macro_groups[group])
            if all(0 <= command <= 15 for command in vector):
                first_matches.setdefault(vector, kind)
    first_match_types = set(first_matches.values())
    additional_macro_types = {
        family: {application: sorted(set(values) - set(all_subsets["KEY"].get(application, all_subsets["KEY"]["0"])))
                 for application, values in all_subsets[family].items()}
        for family in ("NEO", "NEOPRO", "NEOPRO_S")}
    registrations, _ = image.registrations(UNIT_FACTORY)
    profile_rows = [row for row in registrations if row[0] in PHYSICAL_KEYS]
    profile_classes = {}
    for unit_type, symbol, minimum, maximum in profile_rows:
        slots = {hex(offset): image.slot(symbol, offset) for offset in (0x16C, 0x190, 0x194, 0x1A4, 0x268)}
        for name in slots.values():
            if name != "?":
                methods[name] = image.method(name)
        profile_classes[symbol] = {"unit_type": unit_type, "firmware_min": minimum, "firmware_max": maximum,
                                   "slots": slots, "ancestry": _interface_ancestry(image, symbol)}

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in methods[name]["instructions"]

    def call(name, address, target):
        return has(name, address, "call", hex(image.by_name[target]))

    def literal(name, address, value):
        return methods[name]["literal_at"].get(address) == value

    def constant_result(name):
        matches = [int(op.rsplit(", ", 1)[1], 0) for _, mnemonic, op in methods[name]["instructions"]
                   if mnemonic == "mov" and re.fullmatch(r"dword ptr \[ebp - 8\], (0x[0-9a-f]+|[0-9]+)", op)]
        if len(matches) != 1:
            raise ValueError("Expected original constant result: " + name)
        return matches[0]

    resources = {hex(pointer): image.resource(image.dword(pointer)) for pointer in
                 (0x13C26CC, 0x13C2E5C, 0x13C2878, 0x13C34B0)}
    checks = {
        "neo_full_ordered_markup": tuple(methods[NEO]["literals"]) == NEO_LITERALS,
        "pro_has_no_additional_markup": methods[PRO]["literals"] == [],
        "neo_inherits_classic_body_first": call(NEO, 0xCA7C7C, CLASSIC),
        "pro_delegates_to_neo_body": call(PRO, 0xCCDDF8, NEO),
        "neo_body_requires_neo_class": has(NEO, 0xCA7C84, "mov", "edx, dword ptr [0xd06b14]")
        and has(NEO, 0xCA7C91, "je", "0xca8022"),
        "neo_body_requires_nonempty_scenes": call(NEO, 0xCA7CA3, HAS_SCENES)
        and has(NEO, 0xCA7CAA, "je", "0xca8022"),
        "has_scenes_checks_commands_not_enabled_flag": (
            has(HAS_SCENES, 0xCA832B, "mov", "eax, dword ptr [eax + 0x80]")
            and has(HAS_SCENES, 0xCA8333, "call", "dword ptr [edx + 0x58]")
            and has(HAS_SCENES, 0xCA8338, "jle", "0xca833e")
            and has(HAS_SCENES, 0xCA833A, "mov", "byte ptr [ebp - 9], 1")),
        "scene_rows_keep_collection_order_and_gaps": (
            has(NEO, 0xCA7CFF, "mov", "dword ptr [ebp - 0x10], 0")
            and has(NEO, 0xCA7D24, "jle", "0xca8009")
            and has(NEO, 0xCA7D32, "mov", "eax, dword ptr [ebp - 0x10]")
            and has(NEO, 0xCA7D35, "inc", "eax")
            and has(NEO, 0xCA8009, "inc", "dword ptr [ebp - 0x10]")),
        "triggers_require_same_scene_identity_and_nonnil_level": (
            has(NEO, 0xCA7DB1, "cmp", "ebx, eax")
            and has(NEO, 0xCA7DB3, "jne", "0xca7e69")
            and call(NEO, 0xCA7DCF, EXTENSION + "GetSceneTriggerLevel")
            and has(NEO, 0xCA7DD6, "je", "0xca7e69")),
        "trigger_level_uses_matching_key": has(NEO, 0xCA7DE4, "mov", "edx, dword ptr [ebp - 0x14]")
        and call(NEO, 0xCA7E02, "CIS_TDocumentorCommon.DisplayHTMLLevel"),
        "original_trigger_ramp_uses_scene_index": (
            has(NEO, 0xCA7E24, "mov", "edx, dword ptr [ebp - 0x10]")
            and call(NEO, 0xCA7E30, "CIS_TInputKey.TInputKeyCollection.GetItem")
            and call(NEO, 0xCA7E3A, EXTENSION + "GetSceneRampRate")
            and has(NEO, 0xCA7E46, "mov", "eax, dword ptr [0x8544e4]")),
        "missing_trigger_cell_is_nbsp": resources["0x13c26cc"] == "&nbsp;"
        and has(NEO, 0xCA7E86, "je", "0xca7e95")
        and has(NEO, 0xCA7EA0, "mov", "eax, dword ptr [0x13c26cc]"),
        "scene_group_and_level_order": (
            call(NEO, 0xCA7F30, "CIS_TDocumentorCommon.DisplayHTMLGroup")
            and call(NEO, 0xCA7F67, "CIS_CBus.LevelToPercent")
            and literal(NEO, 0xCA7FAE, "<br />") and literal(NEO, 0xCA7FBB, "<br />")
            and has(NEO, 0xCA7FA9, "je", "0xca7fc5")),
        "classic_neo_prefix_resources": resources == {
            "0x13c26cc": "&nbsp;", "0x13c2e5c": "Join Key", "0x13c2878": "IR Key",
            "0x13c34b0": "Virtual Key"},
        "classic_unconnected_key_prefix": literal(CLASSIC, 0xCA68B2, "Unconnected Key ")
        and has(CLASSIC, 0xCA68A5, "call", "dword ptr [ecx + 0x268]"),
        "classic_join_key_range": (
            has(CLASSIC, 0xCA68D6, "cmp", "dword ptr [ebp - 0x10], 4")
            and has(CLASSIC, 0xCA68E7, "add", "eax, 4")
            and has(CLASSIC, 0xCA68ED, "jle", "0xca690e")),
        "classic_scene_control_table_markup": (
            literal(CLASSIC, 0xCA6C95, '<table border="1"><tr><th>Scene</th><th>Ramp Rate</th></tr><tr>')
            and literal(CLASSIC, 0xCA6CA2, "<td>Scene ")
            and literal(CLASSIC, 0xCA6D33, "</td></tr></table>")),
        "classic_scene_control_uses_own_key_ramp": (
            call(CLASSIC, 0xCA6C85, KEY + "GetIsSceneKey")
            and has(CLASSIC, 0xCA6D07, "mov", "edx, dword ptr [ebp - 0x10]")
            and call(CLASSIC, 0xCA6D14, EXTENSION + "GetSceneRampRate")),
        "scene_key_types_23_24_25": all(has(KEY + "GetIsSceneKey", address, "cmp", value)
            for address, value in ((0xD115DE, "al, 0x17"), (0xD115EF, "al, 0x18"), (0xD11600, "al, 0x19"))),
        "block_lookup_uses_first_group_object_identity": (
            has(FIRST_GROUP, 0xD104A3, "cmp", "eax, dword ptr [ebp - 8]")
            and has(FIRST_GROUP, 0xD104B6, "jmp", "0xd104c0")),
        "block_group_resolution_is_application_scoped": (
            call(BLOCK_GROUP, 0xCC7699, "CIS_TInputKey.TInputBlock.GetApplicationForBlock")
            and has(BLOCK_GROUP, 0xCC769E, "mov", "eax, dword ptr [eax + 0xb4]")
            and call(BLOCK_GROUP, 0xCC76A9, "CIS_TCommonCBus.TCBusGroupManager.GroupByAddress")),
        "scene_loader_clears_old_collection": has(SCENE_COMMANDS, 0xCCAF9D, "call", "dword ptr [edx + 0x6c]"),
        "empty_or_initial_255_scene_table_skips_commands": (
            has(SCENE_COMMANDS, 0xCCAFCE, "jle", "0xccb11c")
            and has(SCENE_COMMANDS, 0xCCAFD7, "cmp", "dword ptr [eax], 0xff")
            and has(SCENE_COMMANDS, 0xCCAFDD, "je", "0xccb11c")),
        "scene_loader_skips_255_and_later_duplicate_groups": (
            has(SCENE_COMMANDS, 0xCCB035, "cmp", "dword ptr [eax + edx*4], 0xff")
            and call(SCENE_COMMANDS, 0xCCB050, "CIS_TInputKeyExtensionNeo.TNeoSceneCommandManager.ItemByGroupAddress")
            and has(SCENE_COMMANDS, 0xCCB057, "jne", "0xccb0af")),
        "scene_commands_use_primary_application": (
            has(SCENE_COMMANDS, 0xCCB077, "call", "dword ptr [edx + 0xb0]")
            and has(SCENE_COMMANDS, 0xCCB07D, "mov", "eax, dword ptr [eax + 0xb4]")),
        "scene_table_pair_level_and_stride": (
            has(SCENE_COMMANDS, 0xCCB0A3, "mov", "edx, dword ptr [eax + edx*4 + 4]")
            and has(SCENE_COMMANDS, 0xCCB0AF, "add", "dword ptr [ebp - 8], 2")),
        "scene_pointer_boundary_is_next_pointer_equal_offset_plus_162": (
            has(SCENE_COMMANDS, 0xCCB0C6, "mov", "eax, dword ptr [eax + edx*4 + 4]")
            and has(SCENE_COMMANDS, 0xCCB0CD, "add", "edx, 0xa2")
            and has(SCENE_COMMANDS, 0xCCB0D5, "jne", "0xccb0f3")),
        "scene_collection_padded_to_eight": has(SCENE_COMMANDS, 0xCCB132, "cmp", "eax, 8")
        and has(SCENE_COMMANDS, 0xCCB135, "jl", "0xccb106"),
        "scene_selector_one_changes_command_interpretation": (
            has(KEY_VALUES, 0xCCA5C6, "mov", "eax, dword ptr [eax + 0x180]")
            and has(KEY_VALUES, 0xCCA5D6, "dec", "eax")
            and has(KEY_VALUES, 0xCCA5D7, "jne", "0xcca9c3")),
        "scene24_requires_jp_14": has(KEY_VALUES, 0xCCA632, "mov", "dl, 0xe")
        and has(KEY_VALUES, 0xCCA64A, "jne", "0xcca7b1")
        and has(KEY_VALUES, 0xCCA657, "mov", "dl, 0x18")
        and call(KEY_VALUES, 0xCCA663, KEY + "SetMacroFunctionTemplate"),
        "scene24_number_is_indicator_assignment_plus_one": (
            has(KEY_VALUES, 0xCCA66E, "mov", "eax, dword ptr [eax + 0x130]")
            and has(KEY_VALUES, 0xCCA67E, "inc", "eax")
            and call(KEY_VALUES, 0xCCA6B2, EXTENSION + "SetScene")),
        "scene24_trigger_uses_lp_and_lr_nibbles": (
            has(KEY_VALUES, 0xCCA6D8, "mov", "eax, dword ptr [eax + 0x128]")
            and has(KEY_VALUES, 0xCCA70A, "mov", "eax, dword ptr [eax + 0x124]")
            and call(KEY_VALUES, 0xCCA733, "CIS_Maths.NibblesToInt")
            and call(KEY_VALUES, 0xCCA767, EXTENSION + "SetSceneTriggerLevel")),
        "scene24_ramp_uses_sr_command": has(KEY_VALUES, 0xCCA775, "mov", "eax, dword ptr [eax + 0x120]")
        and call(KEY_VALUES, 0xCCA7A7, EXTENSION + "SetSceneRampRate"),
        "scene_modify_is_separate_template25_branch": has(KEY_VALUES, 0xCCA7B8, "mov", "dl, 0x19")
        and call(KEY_VALUES, 0xCCA7C4, KEY + "SetMacroFunctionTemplate"),
        "ordinary_keys_attach_to_scene_one": has(KEY_VALUES, 0xCCABF5, "mov", "edx, 1")
        and call(KEY_VALUES, 0xCCAC09, EXTENSION + "SetScene"),
        "ordinary_keys_use_normal_macro_refresh": has(KEY_VALUES, 0xCCABA9, "xor", "edx, edx")
        and call(KEY_VALUES, 0xCCABAE, KEY + "MacroFunctionRefresh"),
        "cold_extension_scene_change_handler_is_noop": methods[EXTENSION + "HandleSceneAfterChangeEvent"]["sha256"]
        == "ffbe5d93e7a04e08345a2b8ed94a0d88abbd8cf94c102206779f88186dc07f1a",
        "cold_extension_fields_created": methods[EXTENSION + "InternalCreate"]["literals"] == [
            "TNeoInputKey", "Scene", "SceneRampRate", "SceneTriggerLevel", "SceneRampFunction",
            "SceneRampMacroFunctionTemplate", "LabelFlavour"],
        "neo_subset_scene_admission": 23 in neo_subsets["0"] and 24 in neo_subsets["0"]
        and 25 not in neo_subsets["0"] and neo_subsets["255"] == [16],
        "profile_factory_classes": set(profile_rows) == {
            *((name, f"CIS_T{name}..T{name}_A", "1.3.01", "1.5.02") for name in PHYSICAL_KEYS if name != "KEYE1"),
            *((name, f"CIS_T{name}..T{name}", "1.5.03", "2.9.99") for name in PHYSICAL_KEYS if name != "KEYE1"),
            ("KEYE1", "CIS_TKEYEx..TKEYEx", "0", "9")},
        "profiles_have_eight_blocks_and_virtual_keys": all(
            constant_result(row["slots"]["0x16c"]) == 8 and constant_result(row["slots"]["0x194"]) == 8
            for row in profile_classes.values()),
        "profile_physical_key_counts": all(constant_result(row["slots"]["0x190"]) ==
            PHYSICAL_KEYS[row["unit_type"]] for row in profile_classes.values()),
        "profiles_have_no_bistable_interface": all(BISTABLE_GUID not in ancestor["interfaces"]
            for row in profile_classes.values() for ancestor in row["ancestry"]),
        "scene24_default_commands_are_idle": templates[24] == [56] and macro_groups[56] == [0, 0, 0, 0],
        "scene24_assigns_default_macro_commands": (
            call(KEY + "RefreshMacroFunctionFromTemplate", 0xD11C1E, KEY + "GetIsSceneModifyKey")
            and has(KEY + "RefreshMacroFunctionFromTemplate", 0xD11C25, "je", "0xd11c37")
            and call(KEY + "RefreshMacroFunctionFromTemplate", 0xD11C49, MACRO + "AssignTemplate")
            and call(MACRO + "AssignTemplate", 0xC96C92, MACRO + "AssignTemplate_Microfunctions")),
        "scene_modify_skips_ordinary_template_assignment": has(KEY + "GetIsSceneModifyKey", 0xD1167E, "cmp", "al, 0x19")
        and has(KEY + "RefreshMacroFunctionFromTemplate", 0xD11C36, "ret", ""),
        "scene_template_refreshes_blocks_before_lock_check": (
            call(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B60, KEY + "RefreshBlocksFromTemplate")
            and has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B6E, "call", "0xaf9470")
            and call(KEY + "RefreshBlocksFromTemplate", 0xD1267E, KEY + "RefreshBlocksFromTemplateScene")),
        "cold_ramp_enum_starts_at_zero": (
            has("CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.InternalCreate", 0x848361, "xor", "edx, edx")
            and has("CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.InternalCreate", 0x848363, "mov", "dword ptr [eax + 0x70], edx")),
        "cold_object_reference_constructor_clears_reference": call(
            "CIS_TCustomFlashObject.TFlashObjectReference.Create", 0x7ED0C0, "CIS_TCustomFlashObject.TFlashObjectReference.Clear"),
        "scene24_binding_assigns_default_group": call(MACRO + "AssignTemplate_Microfunctions", 0xC96D96,
            TEMPLATE + "GetMicroFunctionGroupDefault") and has(TEMPLATE + "GetMicroFunctionGroupDefault", 0xC97DDE, "xor", "edx, edx"),
        "added_neo_macro_types_are_unreachable_by_first_nibble_match": all(
            not first_match_types.intersection(values) for applications in additional_macro_types.values()
            for values in applications.values()),
        "keyex_mask_missing_bit_zero_uses_type_default": (
            has("CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.SetDefaultKeysIfNeeded", 0x12D27AC, "test", "al, 1")
            and has("CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.SetDefaultKeysIfNeeded", 0x12D27AE, "jne", "0x12d27da")
            and call("CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.SetDefaultKeysIfNeeded", 0x12D27B8,
                     "CIS_TKEYEx.TKEYEx.GetDefaultKeyMask")),
        "keyex_default_masks_follow_last_type_character": (
            has("CIS_TKEYEx.TKEYEx.GetDefaultKeyMask", 0xEA9132, "mov", "ax, word ptr [eax + edx*2 - 2]")
            and has("CIS_TKEYEx.TKEYEx.GetDefaultKeyMask", 0xEA9137, "sub", "ax, 0x31")
            and all(has("CIS_TKEYEx.TKEYEx.GetDefaultKeyMask", address, "mov", value) for address, value in (
                (0xEA914E, "dword ptr [ebp - 8], 1"), (0xEA9157, "dword ptr [ebp - 8], 3"),
                (0xEA9160, "dword ptr [ebp - 8], 7"), (0xEA9169, "dword ptr [ebp - 8], 0xf")))),
        "keyex_loader_keeps_low_four_bits": has(
            "CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.AfterLoadProgrammingInformation", 0x12D2840, "and", "eax, 0xf"),
        "keyex_keys_2_3_4_use_mask_bits": all(has("CIS_TKEYEx.TKEYEx.IsKeyConnected", address, "shr", value)
            for address, value in ((0xEA91EE, "eax, 1"), (0xEA9209, "eax, 2"), (0xEA9225, "eax, 3"))),
        "scene_control_group_is_find_or_create_including_255": call(AGENT + "GetControlAppGroup", 0xCCA3A1,
            "CIS_TCommonCBus.TCBusGroupManager.FindOrCreateGroupByAddress"),
        "scene_trigger_lookup_can_add_by_address": (
            has(KEY_VALUES, 0xCCA73B, "push", "1") and has(KEY_VALUES, 0xCCA753, "mov", "cl, 1")
            and call(KEY_VALUES, 0xCCA758, "CIS_TCommonCBus.TLevelManager.FindLevelByAddress")
            and has("CIS_TCommonCBus.TLevelManager.FindLevelByAddress", 0xF27497, "cmp", "eax, dword ptr [ebp - 8]")),
        "timer_macro_zero_primary_timer_becomes_300_seconds": (
            has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B05, "sub", "al, 6")
            and has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B07, "je", "0xd12b0f")
            and call(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B12, KEY + "GetPrimaryBlock")
            and has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B28, "test", "ax, ax")
            and has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B2B, "jne", "0xd12b39")
            and has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B2D, "mov", "dx, 0x12c")
            and call(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B34, "CIS_TInputKey.TInputBlock.SetTimer")),
        "scene_binding_refresh_removes_references_then_uses_linear_block": (
            call(KEY + "RefreshBlocksFromTemplateScene", 0xD12794, KEY + "RemoveAllBlocks")
            and call(KEY + "RefreshBlocksFromTemplateScene", 0xD127A1, KEY + "CalcLinearBlock")),
    }
    for field, literal_address, store_address, offset in (
        ("ControlAppGroupAddress", 0xCC9D13, 0xCC9D33, 0x160),
        ("SceneKeySelector", 0xCC9E43, 0xCC9E63, 0x180),
        ("SceneTable", 0xCC9E69, 0xCC9E89, 0x184),
        ("SceneTablePointer", 0xCC9E8F, 0xCC9EAF, 0x188),
    ):
        checks[f"pp_{field}"] = literal(AGENT + "InternalCreate", literal_address, field) and has(
            AGENT + "InternalCreate", store_address, "mov", f"dword ptr [edx + {hex(offset)}], eax")
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Source checks failed: " + ", ".join(failed))
    if _sha(exe.read_bytes()) != EXE_SHA256 or _sha(map_file.read_bytes()) != MAP_SHA256:
        raise ValueError("Original Toolkit files changed during inspection")
    return {
        "format": "cbus-project-documentor-neo-static-v1", "original_executed": False,
        "original_generated_page_comparison": "not_obtained", "exe_sha256": EXE_SHA256, "map_sha256": MAP_SHA256,
        "profiles": [
            {"unit_type": name, "firmware_min": minimum, "firmware_max": maximum, "documentor": documentor}
            for name in PHYSICAL_KEYS if name != "KEYE1"
            for minimum, maximum, documentor in (("1.3.01", "1.5.02", "NeoInput"), ("1.5.03", "2.9.99", "NeoProInput"))
        ] + [{"unit_type": "KEYE1", "firmware": "2.5.00", "documentor": "NeoProInput"}],
        "neo_macro_subsets": neo_subsets, "resources": resources, "checks": checks,
        "profile_classes": profile_classes,
        "scene24_macro_group": {"template_type": 24, "group_type": 56, "jp_sr_lp_lr": macro_groups[56]},
        "ordinary_macro_table_proof": {"additional_types_by_family_application": additional_macro_types,
                                       "first_match_types": sorted(first_match_types),
                                       "first_idle_match": first_matches[(0, 0, 0, 0)]},
        "keye1_mask_rule": "If bit 0 is clear use default 1; then retain low four bits. Key 1 is connected; keys 2..4 use bits 1..3.",
        "methods": {name: {"start": hex(method["start"]), "end": hex(method["end"]),
                            "sha256": method["sha256"], "literals": method["literals"]}
                    for name, method in methods.items()},
        "boundary": [
            "Source-only body/loader and class-profile facts; KEYE1 admission is exactly firmware 2.5.00, narrower than its factory registration.",
            "Adapters admit explicit canonical scene pair tables and aligned ordered scene boundaries only; the source loader itself is less restrictive.",
            "SceneKeySelector=1 with JPCommand other than 14 enters SceneModify/template25, which remains outside the admitted adapter.",
            "Fresh extension defaults are scene trigger nil and ramp ordinal zero; an ordinary key is assigned scene one even when its selector is zero.",
            "Pre-existing in-memory extension state and historical block-reference order are not represented by the fresh-model adapter.",
            "Scene template changes refresh block references before the macro lock check. Canonical admission requires mask=1<<key, the linear block unused in the primary application, and no other key sharing it.",
            "Block lookup matches group object identity: adapters must distinguish application plus group address and return the first matching block.",
            "Original trigger-table ramp lookup uses scene index rather than matching key index.",
            "Missing project application/group/level objects require explicit handling; this receipt does not accept invented project metadata or auto-create effects.",
            "No original generated HTML, complete native project load, visual or print acceptance was obtained.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.exe, args.map)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Verified {len(report['checks'])} source checks; wrote {args.output}")


if __name__ == "__main__":
    main()
