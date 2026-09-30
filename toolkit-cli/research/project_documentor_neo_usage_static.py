"""Pin Neo/DLT group and action-use branches to the original EXE/MAP.

This is static source evidence. The companion original probe executes only the
Classic/Neo/NeoPro action instruction chain with synthetic accessor stubs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY

METHODS = (
    "CIS_TNeoInputDocumentor.TNeoInputDocumentor.ActionSelectorUse",
    "CIS_TNeoProInputDocumentor.TNeoProInputDocumentor.ActionSelectorUse",
    "CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.DescribeInputGroupDependencyAdvanced",
    "CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.DescribeOtherGroupDependencyAdvanced",
    "CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.DescribeOtherGroupDependencyAdvanced",
    "CIS_TCBusDynamicLabelInputUnit.TCBusDynamicLabelInputUnit.DescribeInputGroupDependencyAdvanced",
    "CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.InternalCreate",
    "CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation",
    "CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.CreateCorridorLinkAttributes",
    "CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.LoadCorridorLinkAttributes",
    "CIS_TCoreKeyInputCGateAgent.GetIndicatorBrightness",
    "CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsJoinModeSupported",
)
PINNED = (
    "bca3bb35da7f846239a7db0527573a28c2f11fc8202a883190af8d7a7787631b",
    "086af6b075b371a2763e640c9822f1caa6c9ecbdb454ba07d234b64a39a76f9e",
    "df1e6a8ecf2c7ed2fe15bf5a802f909ded412f4b797bc0e6bc498e1a67f1b892",
    "3983a28c79a0a306b96ef2bfd078d7b36b6ea6ec0f8d480e87b6059d4cc17b32",
    "b207387846cc725a4a675545e5b46c422c1a024c02de1eda28da2490b615a354",
    "eca104106ac736ea48608093e0017a0836c37778280f4f591403cb03339dbff6",
)


def inspect(executable: Path, map_file: Path) -> dict:
    raw, symbols = executable.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(raw, symbols)
    methods = {name: image.method(name) for name in METHODS}
    rows = list(methods.values())

    def instructions(row):
        return [(mnemonic, operands) for _, mnemonic, operands in row["instructions"]]

    def calls(row):
        return [sorted(image.symbols.get(int(operands, 16), {"?"}))[0]
                for _, mnemonic, operands in row["instructions"]
                if mnemonic == "call" and operands.startswith("0x")]

    def resources(row):
        result = []
        for _, mnemonic, operands in row["instructions"]:
            if mnemonic == "mov" and operands.startswith("eax, "):
                for token in re.findall(r"0x[0-9a-f]{6,8}", operands):
                    address = int(token, 16)
                    value = image.resource(image.dword(address) if "dword ptr" in operands else address)
                    if value is not None:
                        result.append(value)
        return result

    checks = {"method_hash:" + name: methods[name]["sha256"] == expected
              for name, expected in zip(METHODS, PINNED)}
    checks.update({
        "neo_parent_classic_first": calls(rows[0])[0].endswith("TClassicKeyInputDocumentor.ActionSelectorUse"),
        "neo_scene_label": resources(rows[0]) == ["Triggers Scene "],
        "neo_scene_replaces_result": calls(rows[0]).count("System.@UStrCat3") == 1 and "System.@UStrCatN" not in calls(rows[0]),
        "neo_scene_index_plus_one": ("inc", "eax") in instructions(rows[0]) and ("call", "dword ptr [ecx + 0x78]") in instructions(rows[0]),
        "pro_parent_neo_first": calls(rows[1])[0].endswith("TNeoInputDocumentor.ActionSelectorUse"),
        "pro_secondary_application": ("call", "dword ptr [edx + 0xb4]") in instructions(rows[1]),
        "pro_repeated_key_labels": rows[1]["literals"] == ["<br/>", "Key ", "<br/>", "Key "],
        "pro_stored1_outer_gate": ("jne", "0xccdd6e") in instructions(rows[1]),
        "pro_distinct_address_value": any(n.endswith("TCGateObject.GetAddressAsInteger") for n in calls(rows[1])) and any(n.endswith("TLevel.GetValue") for n in calls(rows[1])),
        "neo_group_labels": resources(rows[2]) == ["Key %d", "Block (Unused)", "Scene %d", "Scene %d (Unused)"],
        "neo_group_unused_macro_16": ("sub", "al, 0x10") in instructions(rows[2]),
        "neo_group_physical_or_join_windows": all(("cmp", f"dword ptr [ebp - 0x18], {offset}") in instructions(rows[2]) for offset in (2, 4, 6)),
        "neo_scene_usage_from_key_scene": any(n.endswith("TInputKeyExtensionNeo.GetScene") for n in calls(rows[2])),
        "neo_other_labels": resources(rows[3]) == ["Join Group", "DualJoinGroup"],
        "pro_other_labels": resources(rows[4]) == ["Key Disable Group", "Corridor Link Group", "Control App Group"],
        "dlt_group_labels_no_unused_scenes": resources(rows[5]) == ["Key %d", "Block (Unused)", "Scene %d"],
        "dlt_scene_ignores_key_scene": not any(n.endswith("TInputKeyExtensionNeo.GetScene") for n in calls(rows[5])),
        "dlt_keys_per_page_join_gate": ("call", "dword ptr [edx + 0x27c]") in instructions(rows[5]) and ("add", "eax, eax") in instructions(rows[5]),
        "pro_disable_pp_binding": "KeyDisableGroup" in rows[6]["literals"] and ("mov", "dword ptr [edx + 0x1a4], eax") in instructions(rows[6]),
        "pro_disable_enable_application": any(n.endswith("TCBusNetwork.GetEnableControlApplication") for n in calls(rows[7])),
        "corridor_group_pp_binding": "CorridorMasterGroup" in rows[8]["literals"] and ("mov", "dword ptr [edx + 0x1b0], eax") in instructions(rows[8]),
        "corridor_group_primary_unconditional": ("call", "dword ptr [edx + 0xb0]") in instructions(rows[9]) and ("mov", "eax, dword ptr [eax + 0x1b0]") in instructions(rows[9]),
        "brightness_maximum_block_index": ("call", "dword ptr [edx + 0x16c]") in instructions(rows[10]),
        "brightness_nonempty_string_gate": ("cmp", "dword ptr [ebp - 8], 0") in instructions(rows[10]),
        "pro_join_max_four_keys": ("cmp", "eax, 4") in instructions(rows[11]),
    })
    registrations = []
    for typ, cls, low, high in image.registrations(UNIT_FACTORY)[0]:
        if typ not in {"KEYM8", "KEYM4", "KEYA3", "KEYB4", "KEYE1", "KEYML5", "KEYBL5", "KEYDL4"}:
            continue
        slots = {hex(slot): image.slot(cls, slot) for slot in (0x128, 0x12c, 0x130, 0x16c, 0x190, 0x1a8)}
        key = typ + ":" + low
        checks[key + ":output_base"] = slots["0x12c"].endswith("TCBUSUnit.DescribeOutputGroupDependencyAdvanced")
        checks[key + ":eight_blocks"] = ("mov", "dword ptr [ebp - 8], 8") in instructions(image.method(slots["0x16c"]))
        checks[key + ":brightness_enabled"] = ("mov", "byte ptr [ebp - 5], 1") in instructions(image.method(slots["0x1a8"]))
        count = {"KEYE1": 4, "KEYM4": 4, "KEYA3": 3, "KEYB4": 4}.get(typ, 8)
        checks[key + ":native_key_count"] = ("mov", f"dword ptr [ebp - 8], {count}") in instructions(image.method(slots["0x190"]))
        registrations.append({"unit_type": typ, "class": cls, "firmware": [low, high], "slots": slots})
    failed = [name for name, value in checks.items() if not value]
    if failed:
        raise ValueError("Neo usage source differs: " + ", ".join(failed))
    return {"format": "cbus-project-documentor-neo-usage-static-v1", "exe_sha256": EXE_SHA256,
            "map_sha256": MAP_SHA256, "checks": checks, "registrations": registrations,
            "methods": {name: {"start": hex(row["start"]), "end": hex(row["end"]), "sha256": row["sha256"],
                               "resources": resources(row)} for name, row in methods.items()},
            "original_generated_page": "unassessed", "original_loader_execution": "not executed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.executable, args.map_file)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": len(result["checks"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
