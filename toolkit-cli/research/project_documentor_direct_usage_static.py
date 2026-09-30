"""Pin direct fan/temperature documentor action and group dependencies.

Reads the exact original EXE/MAP only. Captures VMT dispatch, PP attribute
bindings, loader branch constants, helper calls and documentor strings. No
original page, PP loader or GUI is executed by this source-only inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY
from cbus_toolkit import project_documentation_usage as model

PREFIXES = {
    "Fan": "CIS_TCBusFanControllerCGateAgent.TCBusFanControllerCGateAgent",
    "Pro": "CIS_TSENTEMPProCGateAgent.TSENTEMPProCGateAgent",
    "Digital": "CIS_TCBusDigitalTemperatureSensorCGateAgent.TCBusDigitalTemperatureSensorCGateAgent",
}
METHODS = (
    "CIS_TFanControllerDocumentor.TFanControllerDocumentor.ActionSelectorUse",
    "CIS_TSENTEMPProDocumentor.TSENTEMPProDocumentor.ActionSelectorUse",
    "CIS_TDigitalTemperatureSensorDocumentor.TDigitalTemperatureSensorDocumentor.ActionSelectorUse",
    "CIS_TCBusFanControllerUnit.TCBusFanControllerUnit.DescribeInputGroupDependencyAdvanced",
    "CIS_TCBusFanControllerUnit.TCBusFanControllerUnit.CheckIfMasterUnit",
    "CIS_TCBusDigitalTemperatureSensor.TCBusDigitalTemperatureSensor.DescribeOtherGroupDependencyAdvanced",
    "CIS_TCBusDigitalTemperatureSensor.TCBusDigitalTemperatureSensor.GetMaxChannels",
    "CIS_TCBusDigitalTemperatureSensorCGateAgent.TCBusDigitalTemperatureSensorChannelParameters.Create",
    "CIS_TCBusDigitalTemperatureSensorCGateAgent.TCBusDigitalTemperatureSensorChannelParameters.AfterLoadProgrammingInformation",
    "CIS_TCBusFanControllerCGateAgent.TCBusFanControllerCGateAgent.FindTriggerGroupBySimpleAddress",
    "CIS_TCBusFanControllerCGateAgent.TCBusFanControllerCGateAgent.FindActionSelectorBySimpleAddress",
    *(prefix + "." + name for prefix in PREFIXES.values()
      for name in ("InternalCreate", "AfterLoadProgrammingInformation")),
)


def inspect(executable: Path, map_file: Path) -> dict:
    raw, symbols = executable.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(raw, symbols)
    methods = {name: image.method(name) for name in METHODS}

    def find(suffix):
        return methods[next(name for name in methods if name.endswith(suffix))]

    def instructions(row):
        return [(mnemonic, operands) for _, mnemonic, operands in row["instructions"]]

    def calls(row):
        return [next(iter(image.symbols.get(int(operands, 16), {"?"}))) for _, mnemonic, operands in row["instructions"]
                if mnemonic == "call" and operands.startswith("0x")]

    def resources(row):
        found = []
        for _, mnemonic, operands in row["instructions"]:
            if mnemonic != "mov" or not operands.startswith("eax, "):
                continue
            for token in re.findall(r"0x[0-9a-f]{6,8}", operands):
                address = int(token, 16)
                value = image.resource(image.dword(address) if "dword ptr" in operands else address)
                if value is not None:
                    found.append(value)
        return found

    def bindings(row):
        result, current = {}, None
        for address, mnemonic, operands in row["instructions"]:
            if address in row["literal_at"]:
                current = row["literal_at"][address]
            match = re.fullmatch(r"dword ptr \[edx \+ (0x[0-9a-f]+)\], eax", operands)
            if mnemonic == "mov" and match and current:
                result[current] = match[1]
        return result

    checks = {}
    expected = {
        "Fan": {"FanTriggerGroup": "0x174", "FanActionSelector": "0x178"},
        "Pro": {"BroadcastTriggerGroup": "0x100", "BroadcastTriggerLevel": "0x104"},
        "Digital": {"BroadcastTriggerGroup": "0xec", "BroadcastActionSelector": "0xf0",
                    "ErrorReportingTriggerGroup": "0xf8", "ErrorReportingActionSelector": "0xfc",
                    "ErrorReportingEnableGroup": "0x108"},
    }
    attribute_bindings = {}
    for family, values in expected.items():
        prefix = PREFIXES[family]
        actual = bindings(methods[prefix + ".InternalCreate"])
        attribute_bindings[family] = {name: actual.get(name) for name in values}
        checks[family + ":pp_bindings"] = attribute_bindings[family] == values
        loader = instructions(methods[prefix + ".AfterLoadProgrammingInformation"])
        checks[family + ":loader_consumes_attributes"] = all(
            ("mov", f"eax, dword ptr [eax + {offset}]") in loader for offset in values.values())
        checks[family + ":trigger_application"] = any(name.endswith("TCBusNetwork.GetTriggerControlApplication")
            for name in calls(methods[prefix + ".AfterLoadProgrammingInformation"])) if family != "Fan" else any(
                name.endswith("TCBusNetwork.GetTriggerControlApplication") for name in
                calls(find("FindTriggerGroupBySimpleAddress")))
    action_names = {
        "FanController": ("TFanControllerDocumentor.ActionSelectorUse", ["Fan Speed Cycle"], "System.@UStrCatN", 1),
        "SENTEMPPro": ("TSENTEMPProDocumentor.ActionSelectorUse", ["Trigger Temperature Broadcast"], "System.@UStrCat3", 1),
        "DigitalTemperatureSensor": ("TDigitalTemperatureSensorDocumentor.ActionSelectorUse",
                                     ["Trigger Error Report", "Trigger Temperature Report"], "System.@UStrCat3", 2),
    }
    for name, (suffix, labels, concatenation, count) in action_names.items():
        row = find(suffix)
        checks[name + ":labels"] = resources(row) == labels
        checks[name + ":concatenation"] = calls(row).count(concatenation) == count
        checks[name + ":li_literal"] = row["literals"] == ["<li />"] * count
    checks["production_action_labels"] = ([model.DIRECT_ACTIONS["FanController"][3], model.DIRECT_ACTIONS["SENTEMPPro"][3]]
        + [item[2] for item in model.DIGITAL_ACTIONS] == ["Fan Speed Cycle", "Trigger Temperature Broadcast",
                                                       "Trigger Error Report", "Trigger Temperature Report"])
    checks["fan_master_nonunused_group"] = ("cmp", "eax, 0xff") in instructions(find("CheckIfMasterUnit"))
    checks["fan_group_description"] = find("TCBusFanControllerUnit.DescribeInputGroupDependencyAdvanced")["literals"] == ["Fan Speed Cycle", "|"]
    checks["fan_first_channel"] = ("xor", "edx, edx") in instructions(find("TCBusFanControllerUnit.DescribeInputGroupDependencyAdvanced"))
    checks["digital_four_channels"] = model.DIGITAL_CHANNEL_COUNT == 4 and ("mov", "dword ptr [ebp - 8], 4") in instructions(find("GetMaxChannels"))
    channel = find("TCBusDigitalTemperatureSensorChannelParameters.Create")
    checks["digital_channel_pp_names"] = channel["literals"] == ["Channel%d", "ChannelMode", "ChannelName", "TemperatureOffset",
                                                                "BroadcastInterval", "BroadcastThreshold", "HVACCommunicationGroup", "HVACZones"]
    channel_load = instructions(find("TCBusDigitalTemperatureSensorChannelParameters.AfterLoadProgrammingInformation"))
    checks["digital_channel_mode_172"] = ("cmp", "eax, 0xac") in channel_load
    checks["digital_other_modes_group_255"] = ("mov", "edx, 0xff") in channel_load
    checks["digital_other_labels"] = resources(find("TCBusDigitalTemperatureSensor.DescribeOtherGroupDependencyAdvanced")) == [
        "Error Report Enable Group", "Communication Group Channel %d"]
    digital_loader = methods[PREFIXES["Digital"] + ".AfterLoadProgrammingInformation"]
    checks["digital_ac_application_172"] = ("mov", "edx, 0xac") in instructions(digital_loader)
    checks["digital_enable_application_203"] = any(name.endswith("TCBusNetwork.GetEnableControlApplication") for name in calls(digital_loader))
    registrations = []
    expected_owners = {
        "RELDF1": ["TCBusFanControllerUnit", "TCBusDimmerUnit", "TCBusDimmerUnit"],
        "SENTEMPB": ["TSENTEMPPro", "TCBUSUnit", "TSENTEMPPro"],
        "SENTEMP4": ["TCBUSUnit", "TCBUSUnit", "TCBusDigitalTemperatureSensor"],
    }
    for typ, cls, low, high in image.registrations(UNIT_FACTORY)[0]:
        if typ in expected_owners:
            owners = [image.slot(cls, offset).rsplit(".", 2)[-2] for offset in (0x128, 0x12c, 0x130)]
            checks[typ + ":group_vmt"] = owners == expected_owners[typ]
            registrations.append({"unit_type": typ, "class": cls, "firmware": [low, high], "group_method_owners": owners})
    checks["all_registered"] = {row["unit_type"] for row in registrations} == set(expected_owners)
    failed = [key for key, good in checks.items() if not good]
    if failed:
        raise ValueError("Direct usage source differs: " + ", ".join(failed))
    return {"format": "cbus-project-documentor-direct-usage-static-v1", "exe_sha256": EXE_SHA256,
            "map_sha256": MAP_SHA256, "checks": checks, "attribute_bindings": attribute_bindings,
            "registrations": registrations,
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
