"""Reproduce source-only receipts for classic-output and DMX documentor bodies.

No vendor execution, C-Gate, project data, or hardware is used. This reads the
pinned EXE/MAP, verifies PP loader fields and exact branch/concat instructions,
and records method hashes rather than proprietary instruction bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit
from cbus_toolkit import project_documentation_devices as model

CLASSIC = "CIS_TClassicOutputDocumentor.TClassicOutputDocumentor.DocumentHTML"
RELAY_AGENT = "CIS_TCBus1RelayCGateAgent.TCBus1RelayCGateAgent."
DMX = "CIS_TDMXGatewayDocumentor.TDMXGatewayDocumentor.DocumentHTML"
DMX_AGENT = "CIS_TCBusDMXGatewayCGateAgent."
METHODS = (
    CLASSIC, RELAY_AGENT + "InternalCreate", RELAY_AGENT + "LoadLogicAssociationsAndGroups",
    RELAY_AGENT + "AfterLoadProgrammingInformation", "CIS_TCBus1RelayUnit.TCBus1RelayUnit.Init",
    DMX, DMX_AGENT + "TCBusDMXGatewayCGateAgent.InternalCreate", DMX_AGENT + "LoadChannels",
    DMX_AGENT + "LoadSlotMappings", DMX_AGENT + "TCBusDMXGatewayCGateAgent.AfterLoadProgrammingInformation",
    "CIS_TDMXDO12.TDMXDO12.GetMaxChannels", "CIS_Maths.IntToBool",
    *(f"CIS_T{name}.T{name}.GetMaxChannels" for name in model.CLASSIC_OUTPUT_CHANNELS),
)


def inspect(exe: Path, map_file: Path) -> dict:
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(raw, symbols)
    methods = {name: image.method(name) for name in METHODS}

    def instructions(name):
        return {(a, m, op) for a, m, op in methods[name]["instructions"]}

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in instructions(name)

    def channel_count(name):
        matches = [int(op.rsplit(", ", 1)[1], 0) for _, m, op in methods[name]["instructions"]
                   if m == "mov" and re.fullmatch(r"dword ptr \[ebp - 8\], (0x[0-9a-f]+|[0-9]+)", op)]
        if len(matches) != 1:
            raise ValueError("Cannot recover channel count: " + name)
        return matches[0]

    counts = {name: channel_count(f"CIS_T{name}.T{name}.GetMaxChannels")
              for name in model.CLASSIC_OUTPUT_CHANNELS}
    relay_create = methods[RELAY_AGENT + "InternalCreate"]["literals"]
    dmx_create = methods[DMX_AGENT + "TCBusDMXGatewayCGateAgent.InternalCreate"]["literals"]
    checks = {
        "classic_counts": counts == model.CLASSIC_OUTPUT_CHANNELS,
        "classic_six_logic_groups": has("CIS_TCBus1RelayUnit.TCBus1RelayUnit.Init", 0xd23895, "cmp", "eax, 6"),
        "classic_pp_names": all(name in relay_create for name in (
            "GroupAddress", "LogicFunctionAndPowerUpDelay", *(f"LogicGA{k}Associations" for k in range(6)))),
        "classic_group_pp_offset": has(RELAY_AGENT + "InternalCreate", 0x1249793, "mov", "dword ptr [edx + 0x110], eax"),
        "classic_loader_group_offset": has(RELAY_AGENT + "LoadLogicAssociationsAndGroups", 0x124a47b, "mov", "eax, dword ptr [eax + 0x110]"),
        "classic_function_pp_offset": has(RELAY_AGENT + "InternalCreate", 0x124976d, "mov", "dword ptr [edx + 0x100], eax"),
        "classic_function_low_bit": has(RELAY_AGENT + "AfterLoadProgrammingInformation", 0x1249c12, "and", "eax, 1"),
        "classic_nonzero_association": has("CIS_Maths.IntToBool", 0x7f17d2, "setne", "byte ptr [ebp - 6]"),
        "classic_ga5_tests_slot5": has(CLASSIC, 0x1018132, "mov", "edx, 5"),
        "classic_ga5_appends_slot0": has(CLASSIC, 0x101815c, "xor", "edx, edx") and has(CLASSIC, 0x101815e, "call", hex(image.by_name["CIS_TCBus1RelayUnit.TLogicGroupCollection.GetItem"])),
        "classic_logic_column_always": '<tr><th>Channel</th><th>Groups</th><th>Logic Function</th></tr>' in methods[CLASSIC]["literals"],
        "classic_logic_requires_two_members": has(CLASSIC, 0x1018215, "cmp", "dword ptr [eax + 8], 1"),
        "dmx_count": channel_count("CIS_TDMXDO12.TDMXDO12.GetMaxChannels") == model.DMX_CHANNELS,
        "dmx_pp_names": all(name in dmx_create for name in ("GroupAddress", "DMXSlotMapping", "%d")),
        "dmx_mapping_banks": has(DMX_AGENT + "TCBusDMXGatewayCGateAgent.InternalCreate", 0x123ff17, "cmp", "dword ptr [ebp - 8], 0x11"),
        "dmx_mapping_loader_dimensions": has(DMX_AGENT + "LoadSlotMappings", 0x1240fb7, "cmp", "dword ptr [ebp - 0xc], 0x20") and has(DMX_AGENT + "LoadSlotMappings", 0x1240fc0, "cmp", "dword ptr [ebp - 8], 0x10"),
        "dmx_group_pp_offset": has(DMX_AGENT + "TCBusDMXGatewayCGateAgent.InternalCreate", 0x123fd7e, "mov", "dword ptr [edx + 0xf4], eax"),
        "dmx_loader_group_offset": has(DMX_AGENT + "LoadChannels", 0x1240df6, "mov", "eax, dword ptr [eax + 0xf4]"),
        "dmx_mapping_one_based_channel": has(DMX_AGENT + "LoadSlotMappings", 0x1240f95, "dec", "edx"),
        "dmx_mapping_one_based_slot": has(DMX_AGENT + "LoadSlotMappings", 0x1240fa8, "inc", "edx"),
        "dmx_group_identity_comparison": has(DMX, 0x123f5e7, "cmp", "ebx, eax"),
        "dmx_row_original_prefix": has(DMX, 0x123f6b9, "mov", "ecx, dword ptr [ebp - 0x14]") and methods[DMX]["literal_at"].get(0x123f6bc) == "</td></tr>" and has(DMX, 0x123f6c1, "call", hex(image.by_name["System.@UStrCat3"])),
    }
    for slot in range(6):
        store = 0x1249689 + slot * 0x26
        load = (0x124a224, 0x124a276, 0x124a2c8, 0x124a31a, 0x124a36c, 0x124a3be)[slot]
        offset = 0xe8 + slot * 4
        checks[f"classic_association_{slot}_loader_field"] = (
            has(RELAY_AGENT + "InternalCreate", store, "mov", f"dword ptr [edx + {hex(offset)}], eax")
            and has(RELAY_AGENT + "LoadLogicAssociationsAndGroups", load, "mov", f"eax, dword ptr [eax + {hex(offset)}]"))
    if not all(checks.values()):
        raise ValueError("Source checks failed: " + ", ".join(name for name, value in checks.items() if not value))
    return {
        "format": "cbus-project-documentor-devices-static-v1", "original_executed": False,
        "original_generated_page_comparison": "not_obtained",
        "exe_sha256": EXE_SHA256, "map_sha256": MAP_SHA256,
        "classic_channel_counts": counts, "dmx_channel_count": model.DMX_CHANNELS,
        "checks": checks,
        "methods": {name: {"start": hex(method["start"]), "end": hex(method["end"]),
                            "sha256": method["sha256"], "literals": method["literals"]}
                    for name, method in methods.items()},
        "boundary": ["Complete explicit consumed PP arrays only; missing/truncated/invalid fields remain partial.",
                     "Displayed groups must resolve in the supplied snapshot; original auto-create side effects are not modeled.",
                     "Classic GA5 tests group 5 but appends group 0; duplicated groups remain duplicated.",
                     "DMX rows repeat for shared channel groups and prepend the closing cells before row text.",
                     "Key/Neo macro templates, enumerations and scenes remain unrecovered by these bodies.",
                     "Static instruction/data mapping is not original generated HTML, visual or print acceptance."],
    }


def main():
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
