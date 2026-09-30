"""Read-only source receipt for KEYC/KEYCIR Classic reports on NeoPro models.

Pins original factories, ancestry, virtual topology and ordinary-key loading.
No original instructions, PP loader, GUI or hardware are executed. This does
not claim that a generated original page was captured or compared.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_documentor_static import EXE_SHA256, MAP_SHA256, UNIT_FACTORY, _Toolkit
from project_documentor_classic_key_static import BISTABLE_GUID, _interface_ancestry
from project_documentor_classic_key_macro_original import SourceMacroOracle
from key_preset_families import Image, agent_registrations, key_count, subsets
from cbus_toolkit import project_documentation_neoclassic as model

PHYSICAL_KEYS = {"KEYC1": 1, "KEYC2": 2, "KEYC4": 4, "KEYCIR1": 0, "KEYCIR4": 4}
CLASSIC = "CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.DocumentHTML"
CLASSIC_CLASS = "CIS_TClassicKeyInputDocumentor..TClassicKeyInputDocumentor"
SHAPE = "CIS_TCBusNeoStandardInputUnit.TCBusNeoProClassicInputUnit."
IR_SHAPE = "CIS_TCBusNeoStandardInputUnit.TCBusNeoProClassicIRInputUnit."
AGENT = "CIS_TCoreNeoInputCGateAgent.TCoreNeoInputCGateAgent."
KEY_VALUES = "CIS_TCoreNeoInputCGateAgent.GetKeyValues"
SCENE_COMMANDS = "CIS_TCoreNeoInputCGateAgent.GetSceneCommands"
KEY = "CIS_TInputKey.TInputKey."
EXTENSION = "CIS_TInputKeyExtensionNeo.TInputKeyExtensionNeo."
PRO_LOAD = "CIS_TCBusNeoProInputCGateAgent.TCBusNeoProInputCGateAgent.AfterLoadProgrammingInformation"
CORE_PRO_LOAD = "CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation"
NEO_UNIT = "CIS_TCBusNeoInputUnit.TCBusNeoInputUnit."
JOIN_KEY = "CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsKeyJoinKey"
BLOCK_STATE = "CIS_TInputKey.TInputBlock.SecondaryApplicationMatchesApplicationState"
METHODS = (
    CLASSIC, SHAPE + "GetScenesEnabled", SHAPE + "SetScenesEnabled", SHAPE + "MacroFunctionSubsetName",
    SHAPE + "IsJoinModeSupported", SHAPE + "IsDualJoinModeSupported", SHAPE + "IsCorridorLinkingSupported",
    SHAPE + "InfraredBankPropertyEnabled", IR_SHAPE + "InfraredBankPropertyEnabled",
    AGENT + "InternalCreate", AGENT + "AfterLoadProgrammingInformation", KEY_VALUES, SCENE_COMMANDS,
    PRO_LOAD, CORE_PRO_LOAD, "CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.InternalCreate",
    KEY + "GetApplicationForKey", KEY + "RefreshKeySecondaryFromBlockSecondary",
    KEY + "RefreshKeyApplicationFromKeySecondary", KEY + "GetPrimaryBlock",
    KEY + "CalcLinearBlock", KEY + "FindBlockUsedByThisKey", BLOCK_STATE,
    KEY + "HandleMacroFunctionTemplateAfterChangeEvent",
    EXTENSION + "InternalCreate", EXTENSION + "HandleSceneAfterChangeEvent",
    "CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsKeyConnected",
    "CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.GetBlockApplications",
    "CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.GetKeyBlocks",
    "CIS_TCoreKeyInputCGateAgent.GetBlockValues",
    NEO_UNIT + "InternalCreate", NEO_UNIT + "GetJoinGroup", NEO_UNIT + "GetDualJoinGroup",
    NEO_UNIT + "SetJoinApplication", NEO_UNIT + "SetJoinGroup", NEO_UNIT + "SetDualJoinGroup",
    NEO_UNIT + "JoinGroupChanged", JOIN_KEY,
)


def inspect(exe: Path, map_file: Path) -> dict:
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError("Pinned original EXE/MAP hash mismatch")
    image, tables = _Toolkit(raw, symbols), Image(exe, map_file)
    methods = {name: image.method(name) for name in METHODS}
    macro = SourceMacroOracle(exe, map_file)
    families, agents = subsets(tables), agent_registrations(tables)
    factory_rows = [row for row in image.registrations(UNIT_FACTORY)[0] if row[0] in PHYSICAL_KEYS]
    documentor_rows = [row for row in image.registrations()[0] if row[0] in PHYSICAL_KEYS]
    profiles, checks = [], {}

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in methods[name]["instructions"]

    def call(name, address, target):
        return has(name, address, "call", hex(image.by_name[target]))

    def constant_bool(name, expected):
        return any(op == "mov" and args == f"byte ptr [ebp - 5], {int(expected)}"
                   for _, op, args in methods[name]["instructions"])

    for typ, symbol, minimum, maximum in factory_rows:
        slots = {hex(offset): image.slot(symbol, offset) for offset in
                 (0x16C, 0x190, 0x194, 0x1A4, 0x1C4, 0x1CC, 0x1DC, 0x1E0, 0x1E8, 0x234, 0x238, 0x268)}
        for name in slots.values():
            methods[name] = image.method(name)
        constructor = f"CIS_T{typ}.T{typ}.InternalCreate"
        methods[constructor] = image.method(constructor)
        ancestry = _interface_ancestry(image, symbol)
        agent = agents[symbol]
        checks[typ + ":exact_factory"] = (symbol, minimum, maximum) == (f"CIS_T{typ}..T{typ}", "1.8.01", "9")
        checks[typ + ":exact_agent"] = agent == ["CIS_TCBusNeoProInputCGateAgent..TCBusNeoProInputCGateAgent"]
        checks[typ + ":effective_loader"] = image.slot(agent[0], 0xA4) == PRO_LOAD
        checks[typ + ":physical_count"] = key_count(tables, symbol, 0x190)[1] == PHYSICAL_KEYS[typ]
        checks[typ + ":virtual_and_block_counts"] = [key_count(tables, symbol, offset)[1] for offset in (0x194, 0x16C)] == [8, 8]
        checks[typ + ":no_bistable"] = not any(BISTABLE_GUID in ancestor["interfaces"] for ancestor in ancestry)
        checks[typ + ":prefix_capability"] = constant_bool(slots["0x1a4"], "IR" in typ)
        checks[typ + ":scene_getter_always_false"] = slots["0x1dc"] == SHAPE + "GetScenesEnabled"
        checks[typ + ":scene_setter_noop"] = slots["0x1e0"] == SHAPE + "SetScenesEnabled"
        checks[typ + ":subsets"] = [methods[slots[hex(offset)]]["literals"] for offset in (0x1C4, 0x1E8)] == [["NEOPRO_CLASSIC"], ["NEOPRO_S"]]
        checks[typ + ":no_macro_override"] = slots["0x1cc"] == "CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.RefreshMacroFunctionOverrides"
        checks[typ + ":no_join_capabilities"] = all(constant_bool(slots[hex(offset)], False) for offset in (0x234, 0x238))
        checks[typ + ":connected_physical_keys"] = slots["0x268"] == "CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsKeyConnected"
        calls = [op for _, mn, op in methods[constructor]["instructions"] if mn == "call"]
        checks[typ + ":constructor_only_delegates"] = calls == [hex(image.by_name["CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.InternalCreate"])]
        profiles.append({"unit_type": typ, "class": symbol, "firmware": [minimum, maximum], "agent": agent[0],
                         "physical_keys": PHYSICAL_KEYS[typ], "virtual_keys": 8, "blocks": 8,
                         "virtual_prefix": "IR Key " if "IR" in typ else "Virtual Key ",
                         "slots": slots, "interface_ancestry": ancestry})
    first_types = set(macro.first_match.values())
    checks.update({
        "five_unit_registrations": len(factory_rows) == 5 and {row[0] for row in factory_rows} == set(PHYSICAL_KEYS),
        "model_profiles_match_source_counts_and_prefix": model.NEOCLASSIC_TYPES
            == {typ: (count, "IR" in typ) for typ, count in PHYSICAL_KEYS.items()},
        "classic_documentor_registrations": set(documentor_rows) == {(typ, CLASSIC_CLASS, "0", "9") for typ in PHYSICAL_KEYS},
        "classic_body_exact_method": image.slot(CLASSIC_CLASS, 0x7C) == CLASSIC,
        "scene_getter_false": constant_bool(SHAPE + "GetScenesEnabled", False),
        "scene_setter_has_no_call_or_object_store": not any(mn == "call" or (mn == "mov" and op.startswith("dword ptr [eax"))
            for _, mn, op in methods[SHAPE + "SetScenesEnabled"]["instructions"]),
        "prefix_literals": [image.resource(image.dword(pointer)) for pointer in (0x13C2878, 0x13C34B0)] == ["IR Key", "Virtual Key"],
        "classic_virtual_prefix_uses_ir_capability": has(CLASSIC, 0xCA6913, "call", "dword ptr [edx + 0x1a4]"),
        "classic_physical_prefix_uses_connection_predicate": has(CLASSIC, 0xCA68A5, "call", "dword ptr [ecx + 0x268]"),
        "classic_join_prefix_uses_supported_flag": has(CLASSIC, 0xCA682C, "call", "dword ptr [edx + 0x234]"),
        "pro_loader_delegates_core_pro": call(PRO_LOAD, 0x1216916, CORE_PRO_LOAD),
        "scene_commands_loaded_before_keys_even_when_disabled": call(AGENT + "AfterLoadProgrammingInformation", 0xCCB403, SCENE_COMMANDS)
            and call(AGENT + "AfterLoadProgrammingInformation", 0xCCB40A, KEY_VALUES),
        "key_selector_still_controls_decode": call(KEY_VALUES, 0xCCA5D1, "CIS_TCGateAttribute.TIntArrayCGateAttribute.AsArrayInteger")
            and has(KEY_VALUES, 0xCCA5D7, "jne", "0xcca9c3"),
        "key_collection_matches_virtual_count": call(KEY_VALUES, 0xCCA55D,
            "CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.MaximumVirtualKeyCount")
            and has(KEY_VALUES, 0xCCA59D, "mov", "dword ptr [ebp - 4], 0"),
        "no_scenes_enabled_getter_call_in_key_decode": not any(mn == "call" and "+ 0x1dc]" in op
            for _, mn, op in methods[KEY_VALUES]["instructions"]),
        "secondary_key_uses_secondary_subset": call(KEY_VALUES, 0xCCAB50, KEY + "GetApplicationState")
            and has(KEY_VALUES, 0xCCAB55, "cmp", "al, 1") and has(KEY_VALUES, 0xCCAB6C, "call", "dword ptr [ecx + 0x1e8]"),
        "primary_key_uses_class_subset": has(KEY_VALUES, 0xCCAB95, "call", "dword ptr [ecx + 0x1c4]"),
        "ordinary_refresh_then_scene_one": call(KEY_VALUES, 0xCCABAE, KEY + "MacroFunctionRefresh")
            and has(KEY_VALUES, 0xCCABF5, "mov", "edx, 1") and call(KEY_VALUES, 0xCCAC09, EXTENSION + "SetScene"),
        "scene_change_handler_noop": methods[EXTENSION + "HandleSceneAfterChangeEvent"]["sha256"]
            == "ffbe5d93e7a04e08345a2b8ed94a0d88abbd8cf94c102206779f88186dc07f1a",
        "secondary_macro_subset_equals_key": families["NEOPRO_S"] == families["KEY"],
        "classic_primary_subset_only_adds_scene_templates": all(set(values) - set(families["KEY"][app]) <= {23, 24}
            and set(families["KEY"][app]) <= set(values) for app, values in families["NEOPRO_CLASSIC"].items()),
        "additional_scene_templates_not_first_nibble_matches": not first_types.intersection({23, 24, 25}),
        "scene_templates_all_share_unused_vector": all(macro.templates[kind] == [56] for kind in (23, 24, 25))
            and macro.groups[56] == [0, 0, 0, 0] and macro.first_match[(0, 0, 0, 0)] == 16,
        "unused_first_match_is_exactly_idle_vector": [vector for vector, kind in macro.first_match.items() if kind == 16]
            == [(0, 0, 0, 0)],
        "mixed_key_application_prefers_linear_block": has(KEY + "RefreshKeyApplicationFromKeySecondary", 0xD12DBC, "cmp", "al, 2")
            and has(KEY + "RefreshKeyApplicationFromKeySecondary", 0xD12DC2, "mov", "dl, 1")
            and call(KEY + "RefreshKeyApplicationFromKeySecondary", 0xD12DC7, KEY + "FindBlockUsedByThisKey")
            and call(KEY + "FindBlockUsedByThisKey", 0xD13B95, KEY + "CalcLinearBlock")
            and call(KEY + "FindBlockUsedByThisKey", 0xD13BA9, KEY + "HasBlock")
            and call(KEY + "FindBlockUsedByThisKey", 0xD13BB8, BLOCK_STATE),
        "mixed_state_accepts_either_block_application": has(BLOCK_STATE, 0xD0FB88, "cmp", "byte ptr [ebp - 5], 2")
            and has(BLOCK_STATE, 0xD0FB8C, "je", "0xd0fb92") and has(BLOCK_STATE, 0xD0FB92, "mov", "al, 1"),
        "mixed_key_fallback_uses_first_matching_reference": call(KEY + "FindBlockUsedByThisKey", 0xD13BF3,
            "CIS_TInputKey.TInputBlockReferenceCollection.GetItem")
            and call(KEY + "FindBlockUsedByThisKey", 0xD13C01, BLOCK_STATE)
            and has(KEY + "FindBlockUsedByThisKey", 0xD13C10, "jmp", "0xd13c1a"),
        "key_application_primary_secondary_and_empty_fallback": has(KEY + "RefreshKeyApplicationFromKeySecondary", 0xD12D96, "call", "dword ptr [edx + 0xb4]")
            and has(KEY + "RefreshKeyApplicationFromKeySecondary", 0xD12E00, "call", "dword ptr [edx + 0xb0]")
            and has(KEY + "RefreshKeyApplicationFromKeySecondary", 0xD12E35, "call", "dword ptr [edx + 0xb0]"),
        "timer_macro_zero_primary_timer_becomes_300_seconds": has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B05, "sub", "al, 6")
            and call(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B12, KEY + "GetPrimaryBlock")
            and has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B28, "test", "ax, ax")
            and has(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B2D, "mov", "dx, 0x12c")
            and call(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B34, "CIS_TInputKey.TInputBlock.SetTimer")
            and call(KEY + "HandleMacroFunctionTemplateAfterChangeEvent", 0xD12B6E, "CIS_TLock.TLock.Locked"),
        "native_loader_still_sets_join_references": call(CORE_PRO_LOAD, 0xCED37B, NEO_UNIT + "SetJoinGroup")
            and call(CORE_PRO_LOAD, 0xCED3B7, NEO_UNIT + "SetDualJoinGroup")
            and call(CORE_PRO_LOAD, 0xCED44B, NEO_UNIT + "SetJoinGroup")
            and call(CORE_PRO_LOAD, 0xCED487, NEO_UNIT + "SetDualJoinGroup"),
        "join_setters_only_assign_reference_attribute": all(
            [args for _, op, args in methods[NEO_UNIT + name]["instructions"] if op == "call"]
            == ["dword ptr [ecx + 0xa8]"]
            for name in ("SetJoinApplication", "SetJoinGroup", "SetDualJoinGroup")),
        "fresh_join_attributes_have_no_change_event_binding": methods[NEO_UNIT + "InternalCreate"]["sha256"]
            == "bdf36a6fb6616e0cf175ea60b5159025db969b231813dbb8b8f9704ad59e4ef4"
            and all(call(NEO_UNIT + "InternalCreate", address,
                         "CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create")
                    for address in (0xD07226, 0xD0724C, 0xD07272))
            and has(NEO_UNIT + "InternalCreate", 0xD0727A, "mov", "dword ptr [edx + 0x260], eax")
            and has(NEO_UNIT + "InternalCreate", 0xD07282, "ret", ""),
        "join_change_event_only_calls_optional_consumer": has(NEO_UNIT + "JoinGroupChanged", 0xD08AE0, "cmp", "word ptr [eax + 0x26a], 0")
            and has(NEO_UNIT + "JoinGroupChanged", 0xD08AE8, "je", "0xd08afc")
            and has(NEO_UNIT + "JoinGroupChanged", 0xD08AF6, "call", "dword ptr [ebx + 0x268]"),
        "join_key_consumer_short_circuits_on_unsupported": has(JOIN_KEY, 0xD0689D, "call", "dword ptr [edx + 0x234]")
            and has(JOIN_KEY, 0xD068A5, "je", "0xd068ec")
            and has(JOIN_KEY, 0xD068EC, "mov", "byte ptr [ebp - 9], 0"),
    })
    failed = [name for name, good in checks.items() if not good]
    if failed:
        raise ValueError("NeoProClassic source evidence changed: " + ", ".join(failed))
    return {"format": "cbus-project-documentor-neoclassic-static-v1", "exe_sha256": EXE_SHA256,
            "map_sha256": MAP_SHA256, "original_executed": False, "original_generated_page_comparison": "not_obtained",
            "model_sha256": hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest(),
            "profiles": profiles, "documentor_registrations": [list(row) for row in documentor_rows], "checks": checks,
            "subsets": {name: families[name] for name in ("KEY", "NEOPRO_CLASSIC", "NEOPRO_S")},
            "methods": {name: {"start": hex(row["start"]), "end": hex(row["end"]), "sha256": row["sha256"],
                               "literals": row["literals"]} for name, row in sorted(methods.items())},
            "body_contract": {"key_count": 8, "block_count": 8, "scene_selector": "Ordinary baseline: eight explicit zeros. Canonical selector=1/JP14 Scene24 extension is pinned separately by project-documentor-neoclassic-scene-static.json.",
                              "raw_commands": "preserved; ordinary macro resolution equals the existing classic matcher",
                              "application_identity": "shared Neo primary/secondary block and key identity model",
                              "joins": "Native raw join references still load; unsupported capabilities and fresh attribute construction make them unconsumed by this report projection.",
                              "output": "Classic timing and key tables only; no Neo Scenes appendix",
                              "scene_data": "SceneTable is loaded natively but unconsumed by zero-selector body; input dependencies inspect it separately"},
            "limits": ["Read-only source evidence only; no original loader or generated-page execution.",
                       "Scene24 and canonical SceneModify use their companion encoded-key receipts. Noncanonical allocation and retained in-memory model history remain outside this profile.",
                       "Input scene dependencies require their own explicit scene-table projection."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", dest="map_file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = inspect(args.exe, args.map_file)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checks": len(receipt["checks"]), "profiles": len(receipt["profiles"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
