"""Pin RELDF1 report and DIMDUX error-report output mappings offline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256
from csv_factory_registry_static import source_registry
from cbus_toolkit import project_documentation_special_outputs as model

FAN = "CIS_TFanControllerDocumentor.TFanControllerDocumentor.DocumentHTML"
FAN_AGENT = "CIS_TCBusFanControllerCGateAgent.TCBusFanControllerCGateAgent."
FAN_UNIT = "CIS_TCBusFanControllerUnit.TCBusFanControllerUnit."
ERROR = "CIS_TErrorReportOutputDocumentor.TErrorReportOutputDocumentor.ActionSelectorUse"
ERROR_AGENT = "CIS_TDIMDUXCGateAgent.TDIMDNUXCGateAgent."
SPEC_SHA = "fb2b0b7a91bf76b944a1db5912ef2fe853dd1ee110ff93cdbebba0e4b373ea64"
FIXTURE_MATRIX = Path(__file__).parent / "hardware-fixture-matrix.json"


def inspect(executable: Path, mapping: Path, specification: Path) -> dict:
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    exe, symbols, spec = executable.read_bytes(), mapping.read_bytes(), specification.read_bytes()
    if sha(exe) != EXE_SHA256 or sha(symbols) != MAP_SHA256 or sha(spec) != SPEC_SHA:
        raise ValueError("Pinned Toolkit or RELDF1 specification mismatch")
    image = _Toolkit(exe, symbols)
    methods, checks = {}, {}

    def method(name):
        if name not in methods:
            methods[name] = image.method(name)
        return methods[name]

    def has(name, address, instruction, operands):
        return (address, instruction, operands) in method(name)["instructions"]

    def call(name, address, target):
        return has(name, address, "call", hex(image.by_name[target]))

    def bindings(name):
        result, current = {}, None
        m = method(name)
        for address, instruction, operands in m["instructions"]:
            if address in m["literal_at"]:
                current = m["literal_at"][address]
            found = re.fullmatch(r"dword ptr \[edx \+ (0x[0-9a-f]+)\], eax", operands)
            if instruction == "mov" and found and current:
                result[current] = found[1]
        return result

    wanted = {"RELDF1", *model.ERROR_CHANNELS}
    registrations = [row for row in source_registry(executable, mapping, ())["registrations"]
                     if row["unit_type"] in wanted]
    checks["exact_factories"] = len(registrations) == 5 and all(
        (row["firmware_min"], row["firmware_max"], row["class"], row["agent"]) ==
        ("0", "9", "T" + row["unit_type"], "TCBusFanControllerCGateAgent" if row["unit_type"] == "RELDF1"
         else "TDIMDNUXCGateAgent") for row in registrations)
    profiles = {}
    for row in registrations:
        typ = row["unit_type"]
        symbol = next(name for name in image.by_name if name.endswith("..T" + typ))
        count_method, logic_method = image.slot(symbol, 0x188), image.slot(symbol, 0x18C)
        count = model.ERROR_CHANNELS.get(typ, 1)
        checks[typ + ":channel_count"] = any(i == "mov" and o.startswith("dword ptr [ebp - 8], ")
            and o.rsplit(", ", 1)[1] in (str(count), hex(count))
            for _, i, o in method(count_method)["instructions"])
        checks[typ + ":class"] = ("TCBusFanControllerUnit" if typ == "RELDF1" else "TDIMDUX") in image.ancestry(symbol)
        if typ == "RELDF1":
            checks["fan_zero_logic_groups"] = ("xor", "eax, eax") in [(i, o) for _, i, o in method(logic_method)["instructions"]]
        else:
            checks[typ + ":logic_count_four"] = ("mov", "dword ptr [ebp - 8], 4") in [
                (i, o) for _, i, o in method(logic_method)["instructions"]]
        profiles[typ] = {"channels": count, "logic_groups": 0 if typ == "RELDF1" else 4,
                         "ancestry": image.ancestry(symbol)}
    load = FAN_AGENT + "AfterLoadProgrammingInformation"
    fields = {"LowToMedThresholdLevel": "0x148", "MedToHighThresholdLevel": "0x14c",
        "LabelOff": "0x154", "LabelLow": "0x158", "LabelMed": "0x15c", "LabelHigh": "0x160",
        "LabelOffLength": "0x164", "LabelLowLength": "0x168", "LabelMedLength": "0x16c",
        "LabelHighLength": "0x170", "FanTriggerGroup": "0x174", "MasterUnitAddress": "0x180",
        "StandAloneConfig": "0x184"}
    actual = bindings(FAN_AGENT + "InternalCreate")
    checks["fan_pp_bindings"] = all(actual.get(name) == value for name, value in fields.items())
    checks["fan_inherited_din_load"] = call(load, 0x12305B4,
        "CIS_TDinRailOutputCGateAgent.TDinRailOutputCGateAgent.AfterLoadProgrammingInformation")
    checks["fan_threshold_loaders"] = call(load, 0x12305D4, FAN_UNIT + "SetLowMedThreshold") and call(
        load, 0x12305F4, FAN_UNIT + "SetMedHighThreshold")
    checks["fan_body_inherited_output_first"] = call(FAN, 0x122FA98, "CIS_TOutputDocumentor.TOutputDocumentor.DocumentHTML")
    checks["fan_master_from_trigger_group_not_255"] = call(FAN_UNIT + "CheckIfMasterUnit", 0xDBCE89,
        "CIS_TCBusObject.TCGateObject.GetAddressAsInteger") and has(FAN_UNIT + "CheckIfMasterUnit", 0xDBCE8E, "cmp", "eax, 0xff")
    checks["standalone_clears_master"] = has(load, 0x12309D4, "je", "0x12309f7") and has(
        load, 0x12309EF, "mov", "dword ptr [eax + 0x260], edx")
    checks["slave_resolves_master_pointer"] = call(load, 0x1230A1C, FAN_AGENT + "GetMasterUnit") and has(
        load, 0x1230A2B, "mov", "dword ptr [eax + 0x260], ebx")
    master = FAN_AGENT + "GetMasterUnit"
    checks["database_master_lookup"] = has(master, 0x1231907, "mov", "eax, dword ptr [eax + 0xd8]") and call(
        master, 0x1231910, "CIS_TCommonCBus.TCBUSUnitManager.UnitByAddress")
    checks["master_requires_fan_class"] = has(master, 0x1231921, "mov", "edx, dword ptr [0xdbcbec]") and call(
        master, 0x1231927, "System.@IsClass")
    checks["slave_has_link_and_no_threshold_table"] = has(FAN, 0x122FB48, "jne", "0x122fc9e") and call(
        FAN, 0x122FAFE, "CIS_TDocumentorCommon.DisplayHTMLUnit")
    checks["low_positive_medium_unequal"] = has(FAN, 0x122FB8D, "jle", "0x122fbd4") and has(
        FAN, 0x122FBE8, "je", "0x122fc4d")
    checks["percentage_increments_after_rounding"] = has(FAN, 0x122FBFF, "inc", "eax") and has(
        FAN, 0x122FC62, "inc", "eax")
    checks["label_copy_all_four_max_eleven"] = all(has(load, address, "mov", text) for address, text in (
        (0x1230730, "dword ptr [ebp - 0x10], 0xb"), (0x12307A6, "dword ptr [ebp - 0x24], 0xb"),
        (0x123081C, "dword ptr [ebp - 0x38], 0xb"), (0x1230892, "dword ptr [ebp - 0x4c], 0xb")))
    checks["label_copy_all_four"] = all(call(load, address, "System.@UStrCopy") for address in (
        0x1230761, 0x12307D7, 0x123084D, 0x12308C3))
    # Original output base has no logic column when there are zero logic groups.
    base = "CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.AfterLoadProgrammingInformation"
    checks["output_group_pp_direct_index"] = has(base, 0x122D79C, "mov", "eax, dword ptr [eax + 0x11c]") and has(
        base, 0x122D7BF, "mov", "edx, dword ptr [ebp - 8]")
    create = ERROR_AGENT + "InternalCreate"
    checks["error_pp_bindings"] = all(bindings(create).get(name) == offset for name, offset in {
        "EnableErrorGroup": "0x158", "TriggerErrorGroup": "0x15c", "TriggerErrorAcSel": "0x160",
        "TriggerErrorClearAcSel": "0x164"}.items())
    error_load = ERROR_AGENT + "AfterLoadProgrammingInformation"
    checks["error_inherited_din_loader"] = call(error_load, 0x1242400,
        "CIS_TDinRailOutputCGateAgent.TDinRailOutputCGateAgent.AfterLoadProgrammingInformation")
    checks["error_trigger_app"] = call(error_load, 0x1242447, "CIS_TCommonCBus.TCBusNetwork.GetTriggerControlApplication")
    checks["error_selector_address_not_value"] = all(call(error_load, address,
        "CIS_TCommonCBus.TLevelManager.FindLevelByAddress") for address in (0x1242762, 0x12427A0))
    checks["error_group255_guard"] = has(error_load, 0x1242731, "cmp", "eax, 0xff")
    checks["error_action_first_set_second_append"] = call(ERROR, 0xD25165, "System.@UStrCat3") and call(
        ERROR, 0xD25199, "System.@UStrCatN") and has(ERROR, 0xD2517A, "push", "dword ptr [eax]")
    checks["error_action_labels"] = (image.resource(0xD24F90), image.resource(0xD24F98)) == model.ERROR_LABELS
    other = "CIS_TDIMDUX.TDIMDUX.DescribeOtherGroupDependencyAdvanced"
    checks["other_enable_group_identity"] = call(other, 0xD266D4, "CIS_TDIMDUX.TDIMDUX.GetEnableErrorGroup") and has(
        other, 0xD266D9, "cmp", "eax, dword ptr [ebp - 8]")
    checks["other_enable_label"] = image.resource(image.dword(0x13C34AC)) == "Error Report Enable Group"
    output = "CIS_TCBusDimmerUnit.TCBusDimmerUnit.DescribeOutputGroupDependencyAdvanced"
    checks["fan_output_group_identity_including_255"] = (image.slot("CIS_TRELDF1..TRELDF1", 0x12C) == output
        and call(output, 0xD2B079, "CIS_TCBusDimmerUnit.TDimmerChannel.GetGroup")
        and has(output, 0xD2B07E, "cmp", "eax, dword ptr [ebp - 8]")
        and image.resource(image.dword(0x13C21E4)) == "Channel %d")
    root = ET.fromstring(spec[spec.index(b"<"):])
    params = {node.findtext("Name"): node for node in root.iter("Param")}
    checks["fan_spec_shape"] = params["GroupAddress"].findtext("ArraySize", "1") == "1" and all(
        "Logic" not in name for name in params)
    checks["fan_label_spec_shape"] = all(params["Label" + name].findtext("Type") == "string" and
        params["Label" + name].findtext("ArraySize") == "11" for name in ("Off", "Low", "Med", "High"))
    # Catalogue metadata establishes the software profile range. The original
    # native class/agent registration above is authoritative for class identity;
    # the catalogue's display ClassName is not used as a Delphi class mapping.
    matrix = json.loads(FIXTURE_MATRIX.read_text())
    fixtures = matrix["fixtures"]
    fan_fixture = next(item for item in fixtures if item.get("id") == "fixture:unit:RELDF1")
    catalogue = {"ranges": fan_fixture["firmware"]["catalogue_ranges"],
                 "spec_sha256": fan_fixture["input_digest"]["spec_sha256"],
                 "spec_filename": fan_fixture["spec_filename"]}
    checks["fan_catalogue_uses_same_spec"] = catalogue["spec_sha256"] == SPEC_SHA and catalogue["spec_filename"] == "RELDF1.xml"
    checks["fan_catalogue_ranges"] = catalogue["ranges"] == [list(pair) for pair in model.FAN_FIRMWARE_RANGES] == [
        ["2.4.00", "2.4.99"], ["2.5.00", "2.5.99"], ["2.6.00", "2.6.99"]]
    checks["fan_single_unconditional_spec"] = ([(node.tag, node.text) for node in root.iter()
        if "version" in node.tag.lower()] == [("SpecVersion", "1.0"), ("MinVersion", "1.2.0"), ("MaxVersion", "9")]
        and not any("include" in node.tag.lower() for node in root.iter()))
    consumed = {name: ("int", "1") for name in (
        "GroupAddress", "FanTriggerGroup", "MasterUnitAddress", "LowToMedThresholdLevel", "MedToHighThresholdLevel",
        "LabelOffLength", "LabelLowLength", "LabelMedLength", "LabelHighLength")}
    consumed.update({"Application": ("int", "2"), "StandAloneConfig": ("bit", "1")})
    consumed.update({"Label" + speed: ("string", "11") for speed in ("Off", "Low", "Med", "High")})
    checks["fan_consumed_schema_uniform"] = all((params[name].findtext("Type"), params[name].findtext("ArraySize", "1")) == shape
        for name, shape in consumed.items()) and len(params) == len(list(root.iter("Param")))
    source_mapping = {}
    for name in (FAN_AGENT + "InternalCreate", load, master, FAN_UNIT + "SetLowMedThreshold",
                 FAN_UNIT + "SetMedHighThreshold", FAN_UNIT + "CheckIfMasterUnit", FAN_AGENT + "AgentLoad"):
        source_mapping[name] = sorted({symbol for _, instruction, operands in method(name)["instructions"]
            if instruction == "call" and operands.startswith("0x")
            for symbol in image.symbols.get(int(operands, 16), ())})
    checks["fan_mapping_no_firmware_calls"] = all(not re.search(r"firmware|version", symbol, re.I)
        for symbols in source_mapping.values() for symbol in symbols)
    checks["fan_agentload_master_copy_is_explicit_verb"] = method(FAN_AGENT + "AgentLoad")["literals"] == [
        "LoadParamsFromMaster", "LoadMasterFanTrigger"] and "CIS_TCustomFlashObject.TFlashAgent.IsInVerbs" in source_mapping[FAN_AGENT + "AgentLoad"]
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError("Special output source checks failed: " + ", ".join(failed))
    return {"format": "cbus-project-documentor-special-outputs-static-v2", "exe_sha256": EXE_SHA256,
        "map_sha256": MAP_SHA256, "RELDF1.xml_sha256": SPEC_SHA, "original_executed": False,
        "original_generated_page_comparison": "not_obtained", "checks": checks,
        "profiles": profiles, "registrations": registrations,
        "fan_firmware_ranges": [list(pair) for pair in model.FAN_FIRMWARE_RANGES],
        "fan_catalogue_projection": catalogue, "fan_consumed_schema_parameters": sorted(consumed),
        "fan_source_mapping_calls": source_mapping, "native_firmware_continuum_acceptance": "unassessed",
        "fan_parameter_bindings": fields,
        "methods": {name: {"start": hex(m["start"]), "end": hex(m["end"]), "sha256": m["sha256"]}
                    for name, m in sorted(methods.items())},
        "limits": ["Fresh saved database-unit model only; no original whole loader or page execution.",
            "RELDF1 canonical 2.4.xx, 2.5.xx and 2.6.xx use one source snapshot projection; native firmware continuum is unassessed.",
            "Missing PP does not become defaults. Labels require BMP text. No master-copy AgentLoad verb is projected.",
            "Architectural and Bytecraft bodies remain unrecovered."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--specification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.exe, args.map, args.specification)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checks": len(report["checks"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
