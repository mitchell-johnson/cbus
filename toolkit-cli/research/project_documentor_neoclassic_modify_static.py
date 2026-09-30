"""Pin SceneModify's special refresh branch and its canonical consumer state.

Reuses accepted macro registrations and the existing scene-loader receipt.
No original CPU instructions, PP loader, GUI, network or hardware execute.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_documentor_classic_key_macro_original import SourceMacroOracle
from project_documentor_neoclassic_scene_static import inspect as scene_inspect
from project_documentor_neoclassic_static import CLASSIC, EXTENSION, KEY, KEY_VALUES, PHYSICAL_KEYS
from project_documentor_neoclassic_usage_static import INPUT
from project_documentor_static import EXE_SHA256, MAP_SHA256
from cbus_toolkit.project_documentation_neoclassic_modify import scene_modify_projection

MACRO = "CIS_TKeyMacroFunction.TKeyMacroFunction."
LOCK = "CIS_TLock.TLock."
UNIT = "CIS_TCoreKeyInputUnit.TCoreKeyInputUnit."


def inspect(exe: Path, map_file: Path) -> dict:
    inherited = scene_inspect(exe, map_file)
    oracle = SourceMacroOracle(exe, map_file)
    image = oracle.toolkit
    names = (
        KEY_VALUES, CLASSIC, INPUT,
        *(KEY + suffix for suffix in ("InternalCreate", "GetIsSceneKey", "GetIsSceneModifyKey",
            "SetMicroFunction", "SetMacroFunctionSubsetName", "MacroFunctionRefresh",
            "RefreshTemplateFromMacroFunction", "RefreshMacroFunctionFromTemplate",
            "RefreshSceneRampMacroFunctionFromTemplate", "RefreshMacroFunctionFromSceneRampTemplate",
            "HandleMacroFunctionTemplateAfterChangeEvent", "RefreshBlocksFromTemplateScene")),
        *(EXTENSION + suffix for suffix in ("InternalCreate", "SetSceneRampMacroFunctionTemplate",
            "HandleSceneRampMacroFunctionTemplateAfterChangeEvent")),
        *(MACRO + suffix for suffix in ("SetMicroFunctionByStage", "RefreshFromMicroFunctions")),
        UNIT + "InputKeyBlocksChanged", UNIT + "RefreshKeyIndicatorStateFromMacrofunction",
        "CIS_TInputKey.TInputIndicator.SetBlockNumber",
        "CIS_TKeyMicroFunctionGroup.TKeyMicroFunctionGroup.SetGroupType",
    )
    methods = {name: image.method(name) for name in names}

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in methods[name]["instructions"]

    def call(name, address, target):
        return has(name, address, "call", hex(image.by_name[target]))

    refresh = KEY + "RefreshTemplateFromMacroFunction"
    handler = EXTENSION + "HandleSceneRampMacroFunctionTemplateAfterChangeEvent"
    template_handler = KEY + "HandleMacroFunctionTemplateAfterChangeEvent"
    checks = {
        "scene_modify_is_key_template25": has(KEY + "GetIsSceneModifyKey", 0xD1167E, "cmp", "al, 0x19"),
        "scene_key_predicate_includes25": has(KEY + "GetIsSceneKey", 0xD11600, "cmp", "al, 0x19"),
        "raw_jp_also_sets_extension_ramp_function": call(KEY_VALUES, 0xCCA626, EXTENSION + "SetSceneRampFunction"),
        "macro_refresh_order": call(KEY + "MacroFunctionRefresh", 0xD11A2F, MACRO + "RefreshMacroFunction")
            and call(KEY + "MacroFunctionRefresh", 0xD11A37, KEY + "IdenticalMacroFunctionRefresh")
            and call(KEY + "MacroFunctionRefresh", 0xD11A3F, refresh),
        "special_modify_branch_precedes_subset_filter": call(refresh, 0xD11A7B, KEY + "GetIsSceneModifyKey")
            and has(refresh, 0xD11A82, "je", "0xd11b03")
            and call(refresh, 0xD11A87, KEY + "GetExtensionNeo"),
        "special_branch_locks_extension_ramp_reference": has(refresh, 0xD11A98, "mov", "eax, dword ptr [eax + 0x98]")
            and call(refresh, 0xD11A9E, LOCK + "Lock")
            and call(refresh, 0xD11AF6, LOCK + "Unlock"),
        "special_branch_assigns_resolved_ramp_template": call(refresh, 0xD11AB9, MACRO + "GetFunctionType")
            and call(refresh, 0xD11AC7, "CIS_TKeyMacroFunction.TKeyMacroFunctionFactory.GetTemplate")
            and call(refresh, 0xD11AD6, EXTENSION + "SetSceneRampMacroFunctionTemplate"),
        "special_branch_exits_past_normal_subset_and_key_template_assignment": has(refresh, 0xD11AE3, "push", "0xd11bf1")
            and has(refresh, 0xD11AFB, "ret", "")
            and call(refresh, 0xD11B86, "CIS_TKeyMacrofunctionSubset.TKeyMacroFunctionSubsetFactory.CheckKeyMacroFunctionSubset")
            and call(refresh, 0xD11BC9, KEY + "SetMacroFunctionTemplate"),
        "ramp_reference_handler_is_bound": has(EXTENSION + "InternalCreate", 0xC99AA3, "mov", "dword ptr [eax + 0x60], 0xc99eb8"),
        "fresh_scene_ramp_constructor_uses_zero_default": has(EXTENSION + "InternalCreate", 0xC99A03, "push", "0")
            and has(EXTENSION + "InternalCreate", 0xC99A05, "push", "0")
            and has(EXTENSION + "InternalCreate", 0xC99A1C, "mov", "dword ptr [edx + 0x88], eax"),
        "modify_loader_does_not_set_scene_rate_or_trigger": not any(op == "call" and arg in {
            hex(image.by_name[EXTENSION + "SetSceneRampRate"]), hex(image.by_name[EXTENSION + "SetSceneTriggerLevel"])}
            for address, op, arg in methods[KEY_VALUES]["instructions"] if 0xCCA7B1 <= address <= 0xCCA9BE),
        "ramp_handler_reverse_copy_is_disabled_while_extension_locked": has(handler, 0xC99F1F, "mov", "eax, dword ptr [eax + 0x98]")
            and call(handler, 0xC99F25, LOCK + "Locked")
            and has(handler, 0xC99F2C, "jne", "0xc99f36")
            and has(handler, 0xC99F33, "call", "dword ptr [edx + 0x18]"),
        "raw_stage_assignment_adds_macro_lock_when_pin_locked": call(KEY + "SetMicroFunction", 0xD117CC, LOCK + "Locked")
            and call(KEY + "SetMicroFunction", 0xD117E3, LOCK + "Lock")
            and call(KEY + "SetMicroFunction", 0xD11804, MACRO + "SetKeyPressMicroFunction")
            and call(KEY + "SetMicroFunction", 0xD11824, LOCK + "Unlock"),
        "macro_lock_suppresses_each_raw_stage_refresh": call(MACRO + "SetMicroFunctionByStage", 0xC97030, LOCK + "Locked")
            and has(MACRO + "SetMicroFunctionByStage", 0xC97037, "jne", "0xc97043"),
        "scene_modify_skips_template_command_copy": call(KEY + "RefreshMacroFunctionFromTemplate", 0xD11C1E, KEY + "GetIsSceneModifyKey")
            and has(KEY + "RefreshMacroFunctionFromTemplate", 0xD11C36, "ret", ""),
        "template25_timer_default_gate_is_false": has(template_handler, 0xD12B05, "sub", "al, 6")
            and has(template_handler, 0xD12B09, "add", "al, 0xe9")
            and has(template_handler, 0xD12B0B, "sub", "al, 7")
            and has(template_handler, 0xD12B0D, "jae", "0xd12b5d")
            and ((25 - 6 + 0xE9) & 255) >= 7,
        "initial_modify_ramp_template_defaults_to_dimmer": has(KEY + "RefreshSceneRampMacroFunctionFromTemplate", 0xD11C96, "cmp", "al, 0x10")
            and has(KEY + "RefreshSceneRampMacroFunctionFromTemplate", 0xD11CA1, "mov", "dl, 3")
            and call(KEY + "RefreshSceneRampMacroFunctionFromTemplate", 0xD11CB2, EXTENSION + "SetSceneRampMacroFunctionTemplate"),
        "global_refresh_changes_group_type_without_copying_stages": call(MACRO + "RefreshFromMicroFunctions", 0xC976D6, MACRO + "AssignTemplate_FunctionType")
            and call(MACRO + "RefreshFromMicroFunctions", 0xC976EE, "CIS_TKeyMicroFunctionGroup.TKeyMicroFunctionGroup.SetGroupType")
            and not any(op == "call" and arg == hex(image.by_name["CIS_TKeyMicroFunctionGroup.TKeyMicroFunctionGroup.Assign"])
                        for _, op, arg in methods["CIS_TKeyMicroFunctionGroup.TKeyMicroFunctionGroup.SetGroupType"]["instructions"]),
        "classic_body_label_comes_from_key_template": call(CLASSIC, 0xCA6AAC, KEY + "GetMacroFunctionTemplate"),
        "classic_microfunctions_only_for_template_custom": has(CLASSIC, 0xCA6AF4, "sub", "al, 0x1a")
            and has(CLASSIC, 0xCA6AF6, "jne", "0xca6c1e"),
        "classic_scene_controls_use_scene_object_and_separate_ramp_rate": call(CLASSIC, 0xCA6C85, KEY + "GetIsSceneKey")
            and call(CLASSIC, 0xCA6CBD, EXTENSION + "GetScene")
            and call(CLASSIC, 0xCA6D14, EXTENSION + "GetSceneRampRate"),
        "input_key_activity_uses_template_unused_gate": has(INPUT, 0xD076DF, "sub", "al, 0x10"),
        "input_scene_usage_reads_scene_pointer_from_all_keys": has(INPUT, 0xD07840, "mov", "eax, dword ptr [eax + 0x1e8]")
            and call(INPUT, 0xD07871, EXTENSION + "GetScene")
            and has(INPUT, 0xD07889, "cmp", "ebx, eax"),
        "indicator_final_assignment_stores_only_block_number": has("CIS_TInputKey.TInputIndicator.SetBlockNumber", 0xD10A77, "mov", "dword ptr [eax + 0x78], edx")
            and not any(op == "call" and arg == hex(image.by_name[EXTENSION + "SetScene"])
                        for _, op, arg in methods["CIS_TInputKey.TInputIndicator.SetBlockNumber"]["instructions"]),
        "template25_description": oracle.labels[25] == "<Scene Modify>",
        "template25_has_default_unused_group": oracle.templates[25] == [56] and oracle.groups[56] == [0, 0, 0, 0],
    }
    callbacks = {}
    for typ in PHYSICAL_KEYS:
        slots = {hex(slot): image.slot(f"CIS_T{typ}..T{typ}", slot) for slot in (0x174, 0x1D8)}
        callbacks[typ] = slots
        checks[typ + ":canonical_block_and_indicator_callbacks_are_noops"] = (
            slots == {"0x174": UNIT + "InputKeyBlocksChanged", "0x1d8": UNIT + "RefreshKeyIndicatorStateFromMacrofunction"}
            and all(not any(op == "call" for _, op, _ in methods[name]["instructions"]) for name in slots.values()))
    failed = [name for name, valid in checks.items() if not valid]
    if failed:
        raise ValueError("SceneModify source check failed: " + ", ".join(failed))
    # Reuse ordered global matching, without the KEY subset filter from resolve.
    # Keep first-match sensor/AUX reconciliation and primary stored-level aliases.
    samples = []
    vectors = tuple(vector for vector in oracle.first_match if vector[0] != 14) + ((1, 2, 3, 4),)
    for commands in vectors:
        matched = oracle.first_match.get(commands, 26)
        reconciled = 26 if matched in (31, 33) else matched
        for application, stored1, stored2 in ((56, 249, 2), (202, 249, 2), (255, 255, 5)):
            resolved = reconciled
            if application != 202:
                if resolved == 14:
                    resolved = {249: 17, 252: 18, 255: 20}.get(stored1, resolved)
                elif resolved == 15:
                    resolved = {2: 19, 5: 22}.get(stored2, resolved)
            projection = scene_modify_projection(0, commands, masks=tuple(1 << index for index in range(8)), groups=(255,) * 8, secondary=0)
            samples.append({"raw_commands": list(commands), "application": application,
                "primary_stored1": stored1, "primary_stored2": stored2,
                "global_match_type": matched, "resolved_ramp_template_type": resolved,
                "final_key_template_type": projection.macro_type, "consumer_commands_preserved": projection.commands == commands,
                "extension_scene_number": projection.scene_index + 1, "extension_ramp_ordinal": projection.scene_ramp})
    return {"format": "cbus-project-documentor-neoclassic-scene-modify-static-v1",
        "exe_sha256": EXE_SHA256, "map_sha256": MAP_SHA256,
        "original_executed": False, "original_generated_page_captured": False,
        "checks": checks, "inherited_scene_loader_checks": inherited["checks"],
        "methods": {name: {"start": hex(row["start"]), "end": hex(row["end"]), "sha256": row["sha256"]} for name, row in methods.items()},
        "reused_macro_methods": {name: {"start": hex(row["start"]), "sha256": row["sha256"]}
            for name, row in oracle.methods.items()},
        "effective_callbacks": callbacks, "source_table_transition_cases": samples,
        "contract": {"admission": "Fresh exact KEYC/CIR model; selector1/JP!=14; unshared linear primary group255 block.",
            "final_key_template": "25, <Scene Modify>; subset filter is bypassed by the special branch.",
            "scene": "Scene1, ramp ordinal0, nil trigger level; raw JP also remains extension SceneRampFunction.",
            "microfunctions": "Four raw stages remain intact; global match and identical aliases affect only the derived macro/ramp-template reference.",
            "block_timer": "Template25 misses timer default gate; final ramp assignment is locked against reverse-copy events.",
            "indicator": "Final PP IndicatorBlockAssignment plus1 stores indicator block number only; consumers here do not read it.",
            "correction": "The earlier scene-scope receipt inferred that final refresh could replace template25. Its ordinary branch checks are true but unreachable on the admitted SceneModify special branch."},
        "supporting_receipts": ["project-documentor-classic-key-macro-source-comparison.json", "project-documentor-neoclassic-static.json", "project-documentor-neo-static.json", "project-documentor-neoclassic-usage-static.json"],
        "limits": ["Static source plus synthetic consumer projection only; no original loader or generated-page acceptance.",
            "Internal ramp-template ordinal is deliberately unconsumed by body/input/actions; no KEY-filtered ordinal is substituted.",
            "Noncanonical block relocation, shared references, retained GUI history and scene-loader success with missing PP data remain outside admission."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", dest="map_file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inspect(args.exe, args.map_file), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
