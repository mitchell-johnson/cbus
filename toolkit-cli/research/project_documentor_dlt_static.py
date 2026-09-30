"""Pin classic DLT documentor glue and its bounded NeoPro model profile.

Reads only explicitly supplied private EXE/MAP and decoded specifications.
No original process, project, C-Gate or hardware is opened. The report contains
hashes and derived facts, never proprietary instruction bytes or source dumps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY
from project_documentor_classic_key_static import _interface_ancestry, BISTABLE_GUID

TYPES = ("KEYBL5", "KEYML5", "KEYDL4")
BODY = "CIS_TDLTDocumentor.TDLTDocumentor.DocumentHTML"
UNIT = "CIS_TCBusDynamicLabelInputUnit.TCBusDynamicLabelInputUnit."
AGENT = "CIS_TCBusDynamicLabelInputCGateAgent.TCBusDynamicLabelInputCGateAgent."
NEO = "CIS_TCBusNeoInputUnit.TCBusNeoInputUnit."
METHODS = (
    BODY, UNIT + "InternalCreate", UNIT + "GetBlockDynamicUpdates",
    UNIT + "InfraredBankPropertyEnabled", AGENT + "InternalCreate",
    AGENT + "AfterLoadProgrammingInformation", AGENT + "GetKeyFunctionIndicators",
    NEO + "MaximumBlockCount", NEO + "GetMaximumVirtualKeyCount",
    "CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsKeyConnected",
    *(f"CIS_T{kind}.T{kind}.{method}" for kind in TYPES
      for method in ("InternalCreate", "MaximumKeyCount")),
)
SPEC_HASHES = {
    "KEYL5.xml": "c3f29166c59b03a76c4545ca3dd79de89b277fe5f0a3188b5bd686a3795a8095",
    "KEYL4.xml": "8d045edada38377378d01c76d5c48c7a84126aea7e3e1a1973dac312f26fd995",
    "I_DLT.xml": "48fcff154e8172e254323e766f795650bab7d0dd572beebbf68a08c4922e2133",
    "I_NEOCORE.xml": "5a26c87fe11a87208815436e00e07ad46e1b65981adab9c93e743a3e1c763af7",
}


def inspect(executable: Path, mapping: Path, specifications: Path) -> dict:
    exe, symbols = executable.read_bytes(), mapping.read_bytes()
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    if sha(exe) != EXE_SHA256 or sha(symbols) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(exe, symbols)
    methods = {name: image.method(name) for name in METHODS}
    checks = {}

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in methods[name]["instructions"]

    def call(name, address, target):
        return has(name, address, "call", hex(image.by_name[target]))

    def constant(name):
        results = [int(op.rsplit(", ", 1)[1], 0) for _, m, op in methods[name]["instructions"]
                   if m == "mov" and re.fullmatch(r"dword ptr \[ebp - 8\], (0x[0-9a-f]+|[0-9]+)", op)]
        return results[0] if len(results) == 1 else None

    checks["inherited_documentor_first"] = call(
        BODY, 0xFFD75C, "CIS_TNeoProInputDocumentor.TNeoProInputDocumentor.DocumentHTML")
    checks["dynamic_label_class_guard"] = (has(BODY, 0xFFD764, "mov", "edx, dword ptr [0xce42ac]")
        and call(BODY, 0xFFD76A, "System.@IsClass") and has(BODY, 0xFFD771, "je", "0xffd7a1"))
    checks["block_dynamic_updates_getter"] = call(BODY, 0xFFD77C, UNIT + "GetBlockDynamicUpdates")
    checks["exact_suffixes_without_break"] = methods[BODY]["literals"] == ["Labels: Static", "Labels: Dynamic"]
    checks["true_static_false_dynamic"] = (has(BODY, 0xFFD783, "je", "0xffd794")
        and methods[BODY]["literal_at"].get(0xFFD785) == "Labels: Static"
        and methods[BODY]["literal_at"].get(0xFFD794) == "Labels: Dynamic"
        and has(BODY, 0xFFD78F, "call", "dword ptr [ecx + 0x38]")
        and has(BODY, 0xFFD79E, "call", "dword ptr [ecx + 0x38]"))
    checks["model_property_binding"] = (methods[UNIT + "InternalCreate"]["literal_at"].get(0xCE47ED)
        == "BlockDynamicUpdates" and has(UNIT + "InternalCreate", 0xCE480D, "mov", "dword ptr [edx + 0x2dc], eax")
        and has(UNIT + "GetBlockDynamicUpdates", 0xCE4CD8, "mov", "eax, dword ptr [eax + 0x2dc]"))
    checks["pp_load_inverts_enable_dynamic_labels"] = (
        has(AGENT + "AfterLoadProgrammingInformation", 0x121C109, "mov", "eax, dword ptr [eax + 0x200]")
        and has(AGENT + "AfterLoadProgrammingInformation", 0x121C117, "xor", "al, 1")
        and call(AGENT + "AfterLoadProgrammingInformation", 0x121C123, UNIT + "SetBlockDynamicUpdates"))
    checks["pp_attribute_binding"] = (methods[AGENT + "InternalCreate"]["literal_at"].get(0x121B877)
        == "EnableDynamicLabels" and has(AGENT + "InternalCreate", 0x121B897,
            "mov", "dword ptr [edx + 0x200], eax"))
    checks["inherited_neopro_loader"] = call(AGENT + "AfterLoadProgrammingInformation", 0x121BF60,
        "CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation")
    checks["inherited_neopro_constructor"] = call(UNIT + "InternalCreate", 0xCE468E,
        "CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.InternalCreate")
    checks["scene_command_capacity_40"] = (call(UNIT + "InternalCreate", 0xCE4862, NEO + "GetSceneManager")
        and has(UNIT + "InternalCreate", 0xCE4867, "mov", "eax, dword ptr [eax + 0x8c]")
        and has(UNIT + "InternalCreate", 0xCE4871, "mov", "edx, 0x28"))
    checks["eight_blocks_and_virtual_keys"] = constant(NEO + "MaximumBlockCount") == constant(
        NEO + "GetMaximumVirtualKeyCount") == 8
    checks["infrared_property_disabled"] = has(UNIT + "InfraredBankPropertyEnabled", 0xCE5105,
        "mov", "byte ptr [ebp - 5], 0")
    connectivity = "CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsKeyConnected"
    checks["physical_keys_connected_without_mask"] = (has(connectivity, 0xD06618,
        "cmp", "dword ptr [ebp - 8], 1") and has(connectivity, 0xD06623, "call",
        "dword ptr [edx + 0x190]") and has(connectivity, 0xD0662C, "jge", "0xd06632")
        and has(connectivity, 0xD06632, "mov", "al, 1"))
    registrations = [row for row in image.registrations(UNIT_FACTORY)[0] if row[0] in TYPES]
    checks["exact_concrete_classes"] = sorted(registrations) == sorted(
        (kind, f"CIS_T{kind}..T{kind}", "0", "9") for kind in TYPES)
    ancestry = {kind: _interface_ancestry(image, symbol) for kind, symbol, _, _ in registrations}
    checks["no_bistable_interface"] = all(BISTABLE_GUID not in row["interfaces"]
        for rows in ancestry.values() for row in rows)
    for kind, symbol, _, _ in registrations:
        checks[f"profile:{kind}"] = (constant(f"CIS_T{kind}.T{kind}.MaximumKeyCount") == 8
            and image.slot(symbol, 0x190) == f"CIS_T{kind}.T{kind}.MaximumKeyCount"
            and image.slot(symbol, 0x16C) == NEO + "MaximumBlockCount"
            and image.slot(symbol, 0x194) == NEO + "GetMaximumVirtualKeyCount"
            and image.slot(symbol, 0x1A4) == UNIT + "InfraredBankPropertyEnabled"
            and image.slot(symbol, 0x268) == connectivity
            and "TCBusNeoProInputUnit" in image.ancestry(symbol))

    specs, roots = {}, {}
    for name, expected in SPEC_HASHES.items():
        raw = (specifications / name).read_bytes()
        if sha(raw) != expected:
            raise ValueError("Decoded specification hash mismatch: " + name)
        root = roots[name] = ET.fromstring(raw[raw.index(b"<"):])
        specs[name] = {"sha256": expected, "includes": [node.text for node in root.iter("Include")]}
    checks["spec_inheritance"] = [specs[name]["includes"] for name in SPEC_HASHES] == [
        ["I_DLT.xml"], ["I_DLT.xml"], ["I_NEOCORE.xml"], []]
    expected_counts = {"Application": 2, "GroupAddress": 9, "SecondApplicationBlocks": 1,
        "SceneKeySelector": 8, "SceneTablePointer": 8, "SceneTable": 80,
        "JoinPrimaryApplication": 1, "DualJoinPrimaryApplication": 1,
        "JoinSecondaryApplication": 1, "DualJoinSecondaryApplication": 1}
    params = {p.findtext("Name"): p for p in roots["I_NEOCORE.xml"].iter("Param")}
    counts = {name: int(params[name].findtext("ArraySize", "1")) for name in expected_counts}
    checks["shared_neopro_array_sizes"] = counts == expected_counts
    flag = next(p for p in roots["I_DLT.xml"].iter("Param") if p.findtext("Name") == "EnableDynamicLabels")
    signature = {name: flag.findtext(name) for name in ("Type", "Address", "BitAddress")}
    checks["dynamic_labels_bit_parameter"] = signature == {"Type": "bit", "Address": "$3E", "BitAddress": "6"}
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError("Source checks failed: " + ", ".join(failed))
    return {"format": "cbus-project-documentor-dlt-static-v1", "original_executed": False,
        "original_generated_page_comparison": "not_obtained", "exe_sha256": EXE_SHA256,
        "map_sha256": MAP_SHA256, "admitted_firmware": "3.0.00", "types": list(TYPES),
        "counts": {"physical_keys": 8, "virtual_keys": 8, "blocks": 8, "scene_commands": 40},
        "suffix": {"EnableDynamicLabels=0": "Labels: Static", "EnableDynamicLabels=1": "Labels: Dynamic"},
        "specifications": specs, "shared_parameter_counts": counts, "checks": checks,
        "no_bistable_ancestry": ancestry,
        "methods": {name: {"start": hex(row["start"]), "end": hex(row["end"]),
            "sha256": row["sha256"]} for name, row in methods.items()},
        "boundary": ["Source reconstruction; inherited NeoPro acceptance is separately bounded.",
            "The report suffix describes blocking dynamic updates, not label text, images or device display.",
            "No original generated page, GUI, native PP loader or hardware acceptance."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--specifications", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.executable, args.map, args.specifications)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checks": len(report["checks"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
