"""Verify new light-level/WHAA/DALI source contracts without vendor execution.

Read only the explicit pinned EXE/MAP. Receipts contain source hashes, symbol
identities, UI literals and derived semantic facts; no instruction bytes, unit
specifications, project data or original generated-page claims are published.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import re
import struct

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256
from csv_factory_registry_static import source_registry

TYPES = frozenset({"SENLL", "PE_CELL", "PC_WHAD", "PC_WHAR", "PC_WHARB", "PC_DAL2B", "PC_DAL2C"})
BODY_GETTERS = {
    "LightLevelSensor": ["GetLevelGroupAddress", "GetOnOffGroupAddress", "GetEnableGroupAddress",
                         *[name for _ in range(4) for name in ("GetTargetLuxAsByte", "GetTargetMarginAsByte")]],
    "ST7LightLevelSensor": ["GetLightLevelMaintBlock", "GetGroup", "GetItem", "GetGroup",
        "GetLightLevelMaintEnableGroup", "GetLightLevelBroadcastBlock", "GetGroup",
        "GetLightLevelBroadcastBlock", "GetTimer", "GetLightLevelTargetLux", "GetLightLevelMarginPerc"],
    "WHAA": ["GetUsePnP", "GetMatrixSwitcherNumber", "GetRelativeProgrammedZoneNumber", "GetAlternateApplication",
        "GetAddressAsInteger", "GetAlternateApplication", "GetAlternateVolumeControlGroup", "GetAlternateBassControlGroup",
        "GetAlternateTrebleControlGroup", "GetAlternateNextSourceGroup", "GetAlternatePrevSourceGroup",
        "GetAlternateAbsoluteSourceGroup", "GetAlternateButtonAGroup", "GetAlternateButtonBGroup"],
    "DALI2B": [name for network in ("A", "B") for name in (
        f"GetDali{network}ErrorReportingStatus", f"GetDali{network}ErrorRefreshTime",
        f"GetDali{network}EnableErrorGroup", f"GetDali{network}EnableErrorGroup", f"GetDali{network}EnableErrorLevel",
        f"GetDali{network}DisableErrorGroup", f"GetDali{network}DisableErrorGroup", f"GetDali{network}DisableErrorLevel",
        f"GetDali{network}TriggerErrorGroup", f"GetDali{network}TriggerErrorGroup", f"GetDali{network}TriggerErrorAcSel",
        f"GetDali{network}RampMatching", f"GetDali{network}StatusCorrection", f"GetDali{network}RestoreLevel",
        f"GetDali{network}ToCBusMapping", "GetDescriptionFromEnumeratedValueOrdinalValue",
        f"GetDali{network}ToCBusMapping", "GetDescriptionFromEnumeratedValueOrdinalValue")]
        + ["GetCBusToDali", "GetCBusToDali", "GetCBusToDali", "GetDaliToCBus"],
}


def inspect(executable, mapping):
    exe, symbols = executable.read_bytes(), mapping.read_bytes()
    if hashlib.sha256(exe).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(exe, symbols)
    methods, checks = {}, {}

    def method(name):
        if name not in methods:
            methods[name] = image.method(name)
        return methods[name]

    def ops(name):
        return {(mnemonic, operands) for _, mnemonic, operands in method(name)["instructions"]}

    def calls(name):
        return [sorted(image.symbols.get(int(args, 16), {"?"}))[0]
                for _, op, args in method(name)["instructions"] if op == "call" and args.startswith("0x")]

    def offsets(name):
        fields, current = {}, None
        for _, op, args in method(name)["instructions"]:
            if op == "push" and args.startswith("0x"):
                literal = image.literal(int(args, 16))
                if literal:
                    current = literal
            match = re.fullmatch(r"dword ptr \[edx \+ (0x[0-9a-f]+)\], eax", args)
            if op == "mov" and match and current:
                fields[current] = int(match[1], 16)
        return fields

    bodies = {}
    for family, expected in BODY_GETTERS.items():
        name = f"CIS_T{family}Documentor.T{family}Documentor.DocumentHTML"
        row = method(name)
        bodies[family] = {"literals": row["literals"], "getters": expected}
        checks[family + ":base_first"] = calls(name)[0].endswith("TUnitTypeDocumentor.DocumentHTML")
        checks[family + ":exact_getters"] = [name.rsplit(".", 1)[-1] for name in calls(name)
                                             if name.rsplit(".", 1)[-1].startswith("Get")] == expected
        action = image.slot(f"CIS_T{family}Documentor..T{family}Documentor", 0x80)
        checks[family + ":action_slot"] = action.endswith(
            ("TDALI2BDocumentor" if family == "DALI2B" else "TUnitTypeDocumentor") + ".ActionSelectorUse")
    rows = [row for row in source_registry(executable, mapping, ())["registrations"] if row["unit_type"] in TYPES]
    actual = [(row["unit_type"], row["firmware_min"], row["firmware_max"], row["class"], row["agent"]) for row in rows]
    expected = [("SENLL", "1.00", "2.0.00", "TSENLL", "TSENLLCGateAgent"),
        ("PE_CELL", "1.00", "2.0.00", "TSENLL", "TSENLLCGateAgent"),
        ("SENLL", "2.0.01", "9", "TST7SENLL", "TCBusST7LightLevelSensorCGateAgent"),
        ("PC_DAL2B", "0", "9", "TPC_DAL2B", "TCBusPC_DAL2BCGateAgent"),
        ("PC_DAL2C", "0", "9", "TPC_DAL2C", "TCBusPC_DAL2BCGateAgent"),
        *[(typ, "0", "9", "T" + typ, "TCBusPC_WHAACGateAgent") for typ in ("PC_WHAD", "PC_WHAR", "PC_WHARB")]]
    checks["exact_factory_profiles"] = sorted(actual) == sorted(expected)
    old_create = "CIS_TSENLLCGateAgent.TSENLLCGateAgent.InternalCreate"
    checks["old:PP_offsets"] = offsets(old_create) == dict(zip(
        ("TargetLUX", "Hystersis", "LevelGroupAddress", "OnOffGroupAddress", "EnableGroupAddress", "LED", "IndicatorFunction"),
        range(0x100, 0x11C, 4)))
    old_load = "CIS_TSENLLCGateAgent.TSENLLCGateAgent.AfterLoadProgrammingInformation"
    checks["old:direct_field_load"] = [name.rsplit(".", 1)[-1] for name in calls(old_load) if ".Set" in name] == [
        "SetTargetLuxAsByte", "SetTargetMarginAsByte", "SetLevelGroupAddress", "SetOnOffGroupAddress", "SetEnableGroupAddress", "SetLED"]
    for field in ("Input", "Other"):
        method(f"CIS_TSENLL.TSENLL.Describe{field}GroupDependencyAdvanced")
    exponent = "CIS_CBus.ByteToLux1600"
    checks["old:power"] = any(name.endswith("Math.Power") for name in calls(exponent))
    checks["old:extended_base"] = {("push", "0x4000"), ("push", "0xadf3b645"),
                                   ("push", "0xa1cac083")} <= ops(exponent)
    checks["old:divisor_multiplier"] = [struct.unpack("<f", image.pe.get_data(address - image.base, 4))[0]
                                          for address in (0x7F2750, 0x7F2754)] == [52.0, 25.0]
    checks["old:midpoint_percentage_constants"] = [struct.unpack("<f", image.pe.get_data(address - image.base, 4))[0]
                                                    for address in (0xCA9654, 0xCA9658)] == [2.0, 100.0]
    checks["old:percentage_upper_clamp"] = ("mov", "dword ptr [ebp - 0x1c], 0x64") in ops(
        "CIS_TLightLevelSensorDocumentor.TLightLevelSensorDocumentor.DocumentHTML")
    checks["foot_candle:extended_constant"] = all(struct.unpack("<QH", image.pe.get_data(address - image.base, 10)) ==
        (13715050917036238853, 16379) for address in (0xCA96A0, 0xCA9C08))
    checks["report:unit_resources"] = [image.resource(image.dword(address)) for address in
                                        (0x13C3278, 0x13C198C, 0x13C26CC)] == ["Lux", "ft-candle", "&nbsp;"]
    timers = "CIS_Dates.CBusTimeToStr"
    checks["st7:timer_format"] = method(timers)["literals"] == ["%dh%s%dm%s%ds"]
    for getter, instruction in (("MaximumKeyCount", ("xor", "eax, eax")),
                                 ("GetMaximumVirtualKeyCount", ("mov", "dword ptr [ebp - 8], 0xffffffff")),
                                 ("IsJoinModeSupported", ("mov", "byte ptr [ebp - 5], 0")),
                                 ("IsDualJoinModeSupported", ("mov", "byte ptr [ebp - 5], 0"))):
        checks["st7:" + getter] = instruction in ops("CIS_TSENLL.TST7SENLL." + getter)
    shared_load = "CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.AfterLoadProgrammingInformation"
    checks["st7:neopro_loader_first"] = calls(shared_load)[0].endswith("TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation")
    checks["st7:margin_math"] = {("fdivrp", "st(1)"), ("fmul", "dword ptr [0xcf4cb4]")} <= ops(shared_load)
    for name in ("CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.DescribeInputGroupDependencyAdvanced",
                 "CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.DescribeOtherGroupDependencyAdvanced"):
        method(name)
    wha_create = "CIS_TCBusPC_WHAACGateAgent.TCBusPC_WHAACGateAgent.InternalCreate"
    wha_offsets = offsets(wha_create)
    checks["whaa:PP_offsets"] = all(wha_offsets[name] == offset for name, offset in {
        "ZoneNumber": 0xE8, "UsePnP": 0xF4, "AlternateApplication": 0x12C,
        "AlternateVolumeControlGroup": 0x130, "AlternateBassControlGroup": 0x134,
        "AlternateTrebleControlGroup": 0x138, "AlternateNextSourceGroup": 0x13C,
        "AlternatePrevSourceGroup": 0x140, "AlternateButtonAGroup": 0x144,
        "AlternateButtonBGroup": 0x148, "AlternateLanguageGroup": 0x14C, "AlternateAbsoluteSourceGroup": 0x150}.items())
    wha_load = "CIS_TCBusPC_WHAACGateAgent.TCBusPC_WHAACGateAgent.AfterLoadProgrammingInformation"
    checks["whaa:pnp_positive"] = ("setg", "al") in ops(wha_load)
    relative = "CIS_TPC_WHAA.TPC_WHAA.ZoneToAmpNo"
    checks["whaa:zone_final_clamp"] = ("mov", "dword ptr [ebp - 0xc], 7") in ops(relative)
    method("CIS_TPC_WHAA.TPC_WHAA.ZoneToMSNo")
    method("CIS_TPC_WHAA.TPC_WHAA.DescribeOtherGroupDependencyAdvanced")
    dali_create = "CIS_TCBusPC_DAL2BCGateAgent.TCBusPC_DAL2BCGateAgent.InternalCreate"
    fields = ["ErrorReportDeviceID", "DaliMonitorRate", *["Dali" + side + name for side in ("A", "B") for name in (
        "RampMatching", "RestoreLevel", "ErrorReportingStatus", "ErrorRefreshTime", "EnableErrorGroup",
        "EnableErrorLevel", "DisableErrorGroup", "DisableErrorLevel", "TriggerErrorGroup", "TriggerErrorAcSel")],
        "CBusToDali", "DaliToCBus"]
    checks["dali:PP_offsets"] = offsets(dali_create) == dict(zip(fields, range(0xE8, 0x148, 4)))
    dali_load = "CIS_TCBusPC_DAL2BCGateAgent.TCBusPC_DAL2BCGateAgent.AfterLoadProgrammingInformation"
    checks["dali:all_256_mapping_slots"] = {("cmp", "dword ptr [ebp - 8], 0x100"),
        ("xor", "ecx, ecx")} <= ops(dali_load) and sum(name.endswith("IntArrayElementWithDefault") for name in calls(dali_load)) == 2
    checks["dali:refresh_clamp"] = ("mov", "dword ptr [ebp - 0x18], 0x3b") in ops(dali_load)
    for name in ("SetCBusToDali", "SetDaliToCBus"):
        checks["dali:" + name + ":earlier_duplicate_clear"] = {
            ("cmp", "byte ptr [eax + 0xc28], 0"), ("mov", "ecx, 0xff"),
            ("cmp", "dword ptr [ebp - 0x10], 0x100")} <= ops("CIS_TPC_DAL2B.TPC_DAL2B." + name)
    method("CIS_TPC_DAL2B.TPC_DAL2B.InternalCreate")
    actions = "CIS_TCBusPC_DAL2BCGateAgent.TCBusPC_DAL2BCGateAgent.LoadDaliActions"
    checks["dali:action_ranges"] = {("cmp", "dword ptr [ebp - 8], " + endpoint) for endpoint in
        ("0x40", "0x50", "0x60", "0xc0", "0xd0", "0xe0")} <= ops(actions)
    checks["dali:restore_percent"] = {("add", "eax, 2"), ("imul", "eax, eax, 0x64"),
                                      ("mov", "ecx, 0xff")} <= ops("CIS_CBus.LevelToPercent")
    for label in ("Input", "Output", "Other"):
        method("CIS_TPC_DAL2B.TPC_DAL2B.Describe" + label + "GroupDependencyAdvanced")
    method("CIS_TDALI2BDocumentor.TDALI2BDocumentor.ActionSelectorUse")
    with localcontext() as context:
        context.prec = 90
        base = Decimal(12534562598085640323) / Decimal(4611686018427387904)
        values = [25 * base ** (Decimal(value) / 52) for value in range(-255, 511)]
        distance = min(abs(value - (Decimal(int(value)) + Decimal("0.5"))) for value in values)
        rounding = [round(value) for value in values]
        context.prec = 60
        checks["old:bounded_precision_stability"] = rounding == [round(25 * base ** (Decimal(value) / 52))
                                                                for value in range(-255, 511)]
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("Original source differs: " + ", ".join(failures))
    return {"format": "cbus-project-documentor-remaining-static-v1", "exe_sha256": EXE_SHA256,
        "map_sha256": MAP_SHA256, "original_executed": False, "original_generated_page_comparison": "not_obtained",
        "factory_profiles": [{key: row[key] for key in ("unit_type", "firmware_min", "firmware_max", "class", "agent")}
                             for row in rows], "checks": checks, "bodies": bodies,
        "lux1600": {"bounded_exponents": [-255, 510], "vectors": 766,
                     "minimum_distance_from_half_integer": str(distance),
                     "rounded_result_sha256": hashlib.sha256(json.dumps(rounding, separators=(",", ":")).encode()).hexdigest()},
        "methods": {name: {"start": hex(row["start"]), "end": hex(row["end"]), "sha256": row["sha256"]}
                    for name, row in sorted(methods.items())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--map-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.executable, args.map_file)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": len(result["checks"]), "methods": len(result["methods"]),
                      "factory_profiles": len(result["factory_profiles"]), "original_executed": False}))


if __name__ == "__main__":
    main()
