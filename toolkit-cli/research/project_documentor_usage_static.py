"""Verify group dependency VMT dispatch, labels and PP bindings in pinned Toolkit.

This source-only receipt complements the independently executed synthetic classic
ActionSelectorUse cases. It does not assert an original generated-page capture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY
from cbus_toolkit import project_documentation_usage as model

NAMES = (
    "CIS_TProjectDocumentor.TProjectDocumentor.InsertHTMLGroupInput",
    "CIS_TProjectDocumentor.TProjectDocumentor.InsertHTMLGroupOutput",
    "CIS_TProjectDocumentor.TProjectDocumentor.InsertHTMLGroupOther",
    "CIS_TCBusDimmerUnit.TCBusDimmerUnit.DescribeOutputGroupDependencyAdvanced",
    "CIS_TCBusDimmerUnit.TCBusDimmerUnit.DescribeOtherGroupDependencyAdvanced",
    "CIS_TCBus1RelayUnit.TCBus1RelayUnit.DescribeOutputGroupDependencyAdvanced",
    "CIS_TCBus1RelayUnit.TCBus1RelayUnit.DescribeOtherGroupDependencyAdvanced",
    "CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.DescribeInputGroupDependencyAdvanced",
    "CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.DescribeOtherGroupDependencyAdvanced",
    "CIS_TCBusInputUnit.TCBusInputUnit.DescribeOtherGroupDependencyAdvanced",
    "CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.ActionSelectorUse",
    "CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.GetKeyBlocks",
    "CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.GetBlockGroup",
    "CIS_TCoreKeyInputCGateAgent.GetIndicatorBrightness",
    "CIS_TCoreKeyInputCGateAgent.GetBlockValues",
    "CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.InternalCreate",
    "CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CreateEEPROMLevelAttributes",
    "CIS_TCBusInputUnitCGateAgent.TCBusInputUnitCGateAgent.CreateAttributeAreaGroupAddress",
    "CIS_TCBusInputUnitCGateAgent.TCBusInputUnitCGateAgent.LoadAreaGroupAddress",
    "CIS_TCBus1RelayCGateAgent.TCBus1RelayCGateAgent.InternalCreate",
    "CIS_TCBusKeyInputUnit.TCBusKeyInputUnit.MaximumBlockCount",
)


def inspect(executable: Path, map_file: Path) -> dict:
    raw, symbols = executable.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(raw, symbols)
    methods = {name: image.method(name) for name in NAMES}

    def resources(method):
        result = []
        for _, mnemonic, operands in method["instructions"]:
            if mnemonic != "mov" or not operands.startswith("eax, "):
                continue
            for token in re.findall(r"0x[0-9a-f]{6,8}", operands):
                address = int(token, 16)
                text = image.resource(image.dword(address) if "dword ptr" in operands else address)
                if text is not None:
                    result.append(text)
        return result

    def method(suffix):
        return methods[next(name for name in methods if name.endswith(suffix))]

    checks = {}
    expected_labels = {
        "TCBusDimmerUnit.DescribeOutputGroupDependencyAdvanced": ["Channel %d", "Logic Group", "Logic Group (Unused)"],
        "TCBus1RelayUnit.DescribeOutputGroupDependencyAdvanced": ["Logic Group", "Logic Group (Unused)"],
        "TCBus1RelayUnit.DescribeOtherGroupDependencyAdvanced": ["Area Group"],
        "TCoreKeyInputUnit.DescribeInputGroupDependencyAdvanced": ["Key %d", "Block (Unused)"],
        "TCoreKeyInputUnit.DescribeOtherGroupDependencyAdvanced": ["Indicator Brightness Group"],
        "TCBusInputUnit.DescribeOtherGroupDependencyAdvanced": ["Area Group"],
    }
    for suffix, labels in expected_labels.items():
        checks[suffix + ":resources"] = resources(method(suffix)) == labels
    checks["production_labels"] = set(model.GROUP_LABELS) == {label for values in expected_labels.values() for label in values}
    for kind, slot in (("Input", "0x128"), ("Output", "0x12c"), ("Other", "0x130")):
        row = method("InsertHTMLGroup" + kind)
        checks[kind + ":wrapper_literals"] = row["literals"] == [
            {"Input": "Inputs:", "Output": "Outputs:", "Other": "Other:"}[kind],
            "<ul>", "<br/>", "|", "<li />", "<ul>", "</ul>", "</ul>"]
        checks[kind + ":virtual_slot"] = any(op == "call" and f"+ {slot}]" in args for _, op, args in row["instructions"])
    checks["unused_macro_enum"] = any(op == "sub" and args == "al, 0x10"
                                     for _, op, args in method("TCoreKeyInputUnit.DescribeInputGroupDependencyAdvanced")["instructions"])
    checks["four_classic_blocks"] = any(op == "mov" and args == "dword ptr [ebp - 8], 4"
                                       for _, op, args in method("TCBusKeyInputUnit.MaximumBlockCount")["instructions"])
    wanted = set(model.PROFILES) | set(model.CLASSIC_OUTPUT_CHANNELS) | set(model.SUPPORTED_UNITS)
    registrations = []
    for typ, cls, low, high in image.registrations(UNIT_FACTORY)[0]:
        if typ not in wanted:
            continue
        slots = [image.slot(cls, offset).rsplit(".", 2)[-2] for offset in (0x128, 0x12c, 0x130)]
        expected = (["TCBUSUnit", "TCBusDimmerUnit", "TCBusDimmerUnit"] if typ in model.PROFILES else
                    ["TCBUSUnit", "TCBus1RelayUnit", "TCBus1RelayUnit"] if typ in model.CLASSIC_OUTPUT_CHANNELS else
                    ["TCoreKeyInputUnit", "TCBUSUnit", "TCoreKeyInputUnit"])
        checks[typ + ":group_vmt"] = slots == expected
        if typ in model.SUPPORTED_UNITS:
            count = image.method(image.slot(cls, 0x190))
            checks[typ + ":key_count"] = any(op == "mov" and args ==
                f"dword ptr [ebp - 8], {model.SUPPORTED_UNITS[typ]}" for _, op, args in count["instructions"])
            virtual = image.method(image.slot(cls, 0x194))
            checks[typ + ":virtual_count_uses_physical"] = any(op == "mov" and args ==
                "dword ptr [ebp - 8], 0xffffffff" for _, op, args in virtual["instructions"])
            brightness = image.method(image.slot(cls, 0x1A8))
            enabled = int(typ not in model.NO_INDICATOR_BRIGHTNESS)
            checks[typ + ":indicator_brightness_enabled"] = any(op == "mov" and args ==
                f"byte ptr [ebp - 5], {enabled}" for _, op, args in brightness["instructions"])
        registrations.append({"unit_type": typ, "class": cls, "firmware": [low, high], "group_method_owners": slots})
    checks["registered_types"] = {row["unit_type"] for row in registrations} == wanted
    failed = [key for key, good in checks.items() if not good]
    if failed:
        raise ValueError("Documentor usage evidence changed: " + ", ".join(failed))
    return {"format": "cbus-project-documentor-usage-static-v1", "exe_sha256": EXE_SHA256,
            "map_sha256": MAP_SHA256, "checks": checks, "registrations": registrations,
            "methods": {name: {"start": hex(row["start"]), "end": hex(row["end"]), "sha256": row["sha256"],
                               "resources": resources(row)} for name, row in methods.items()},
            "original_generated_page": "unassessed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = inspect(args.executable, args.map_file)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"checks": len(receipt["checks"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
