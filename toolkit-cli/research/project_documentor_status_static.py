"""Verify documentor input-interface membership and status-report PP projection.

Reads explicitly supplied pinned EXE/MAP. Never executes vendor code, loads
projects, or contacts C-Gate. Output contains hashes/symbols/facts, no code bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "src")]
from project_documentor_static import _Toolkit, UNIT_FACTORY  # noqa: E402
from topology_generator_static import EXE_SHA256, MAP_SHA256  # noqa: E402
from cbus_toolkit import project_documentation_status as model  # noqa: E402
from cbus_toolkit.toolkit_database_csv_registry import REGISTRATIONS  # noqa: E402

METHODS = (
    "CIS_TProjectDocumentor.TProjectDocumentor.GetNetworkMinimumStatusReportInterval",
    "CIS_TProjectDocumentor.TProjectDocumentor.GetAllUnitProgramming",
    "CIS_TCISUnitFactory.TUnitTypeFactory.GetUnit",
    "CIS_TCISUnitFactory.TUnitTypeFactory.UnitTypeRegIdxByTypeDescAndFirmware",
    "CIS_TCISUnitFactory.TUnitTypeRegistration.FirmwareWithinLimits",
    "CIS_TCBusInputUnit.TCBusInputUnit.InternalCreate",
    "CIS_TCBusInputUnit.TCBusInputUnit.GetStatusReportInterval",
    "CIS_TCBusInputUnit.TCBusInputUnit.SetStatusReportInterval",
    "CIS_TCBusInputUnitCGateAgent.TCBusInputUnitCGateAgent.InternalCreate",
    "CIS_TCBusInputUnitCGateAgent.TCBusInputUnitCGateAgent.CreateAttributeStatusReportInterval",
    "CIS_TCBusInputUnitCGateAgent.TCBusInputUnitCGateAgent.LoadStatusReportInterval",
    "CIS_TCBusInputUnitCGateAgent.TCBusInputUnitCGateAgent.AfterLoadProgrammingInformation",
    "CIS_TIOPEUnit.TIOPEUnit.GetStatusReportInterval",
    "CIS_TIOPEUnit.TIOPEUnit.SetStatusReportInterval",
    "CIS_TIOPECGateAgent.TIOPECGateAgent.InternalCreate",
    "CIS_TIOPECGateAgent.TIOPECGateAgent.AfterLoadProgrammingInformation",
)


def inspect(exe: Path, map_file: Path) -> dict:
    raw, map_raw = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(map_raw).hexdigest() != MAP_SHA256:
        raise ValueError("Pinned original EXE/MAP hash mismatch")
    image = _Toolkit(raw, map_raw)
    methods = {name: image.method(name) for name in METHODS}
    checks = {}

    def instructions(name):
        return [(m, op) for _, m, op in methods[name]["instructions"]]

    native = instructions(METHODS[0])
    checks["native_sentinel_99999"] = ("mov", "dword ptr [ebp - 0x18], 0x1869f") in native
    checks["native_loaded_gate"] = ("cmp", "byte ptr [eax + 0x16d], 0") in native
    checks["native_strict_minimum"] = ("cmp", "eax, dword ptr [ebp - 0x18]") in native and ("jge", "0xf051b8") in native
    checks["native_interface_getter_slot"] = native.count(("call", "dword ptr [edx + 0x10]")) == 2
    checks["native_output_literals"] = methods[METHODS[0]]["literals"] == ["None", "secs on Unit "]
    guid_raw = image.pe.get_data(0xf05230 - image.base, 16)
    checks["input_interface_guid"] = str(uuid.UUID(bytes_le=guid_raw)) == model.ICBUS_INPUT_UNIT_GUID
    checks["native_guid_at_supports_call"] = ("mov", "edx, 0xf05230") in native
    checks["loaded_before_attempt"] = ("mov", "byte ptr [eax + 0x16d], 1") in instructions(METHODS[1])
    # Delphi exception tables interrupt a linear decode. These are the original
    # table's 14 handler entry points, each containing the same failed-load gate.
    handlers = (0xf05669, 0xf05690, 0xf056b7, 0xf056de, 0xf05705, 0xf0572c, 0xf05753,
                0xf0577a, 0xf057a1, 0xf057c8, 0xf057ef, 0xf05813, 0xf05837, 0xf0585b)
    checks["failed_load_handlers_clear_flag"] = all(
        any(i.mnemonic == "mov" and i.op_str == "byte ptr [eax + 0x16d], 0"
            for i in image.decoder.disasm(image.pe.get_data(address - image.base, 35), address))
        for address in handlers)
    expected_getters = {"TCBusInputUnit": "CIS_TCBusInputUnit.TCBusInputUnit.GetStatusReportInterval",
                        "TIOPEUnit": "CIS_TIOPEUnit.TIOPEUnit.GetStatusReportInterval"}
    registry, _ = image.registrations(UNIT_FACTORY)
    checks["factory_registration_rows"] = tuple((t, lo, hi, cls.split("..")[-1]) for t, cls, lo, hi in registry) == tuple(
        row[:4] for row in REGISTRATIONS)
    classes = {}
    for _, symbol, _, _ in registry:
        short = symbol.split("..")[-1]
        if short in classes:
            continue
        vmt, found = image.vmt(symbol), None
        while vmt:
            table = image.dword(vmt - 0x54)
            if table:
                count = image.dword(table)
                if count > 100:
                    raise ValueError("Unexpected interface-table size")
                for index in range(count):
                    entry = table + 4 + index * 28
                    if image.pe.get_data(entry - image.base, 16) != guid_raw:
                        continue
                    owner = image.class_name(vmt)
                    getter = image.dword(image.dword(entry + 16) + 0x10)
                    thunk = list(image.decoder.disasm(image.pe.get_data(getter - image.base, 10), getter))
                    target = expected_getters.get(owner)
                    if len(thunk) != 2 or thunk[0].mnemonic != "add" or thunk[1].mnemonic != "jmp" \
                            or target is None or int(thunk[1].op_str, 16) != image.by_name[target]:
                        raise ValueError("Unrecovered interface getter thunk")
                    found = {"owner": owner, "getter": target}
            parent = image.dword(vmt - 0x30)
            vmt = image.dword(parent) if parent else 0
        classes[short] = found
    checks["input_classes"] = {name for name, value in classes.items() if value} == model.INPUT_CLASSES
    checks["noninput_classes"] = {name for name, value in classes.items() if not value} == model.NONINPUT_CLASSES
    checks["plain_integer_getters"] = all(
        ("mov", f"eax, dword ptr [eax + {offset}]") in instructions(name)
        and ("call", "dword ptr [edx + 0x94]") in instructions(name)
        and not any(m in {"imul", "mul", "div", "idiv", "shl", "shr", "cmp"} for m, _ in instructions(name))
        for name, offset in ((METHODS[6], "0x1b4"), (METHODS[12], "0x1c0")))
    checks["common_pp_name"] = methods[METHODS[9]]["literals"] == ["StatusReportInterval"]
    checks["common_pp_loader"] = ("mov", "eax, dword ptr [eax + 0xf4]") in instructions(METHODS[10]) \
        and ("call", hex(image.by_name[METHODS[7]])) in instructions(METHODS[10])
    checks["iope_pp_name"] = "StatusReportInterval" in methods[METHODS[14]]["literals"]
    checks["iope_pp_loader"] = ("mov", "eax, dword ptr [eax + 0x104]") in instructions(METHODS[15]) \
        and ("call", hex(image.by_name[METHODS[13]])) in instructions(METHODS[15])

    agents = {}
    base_loader = METHODS[11]
    def calls_loader(name, visited):
        if name == base_loader:
            return True
        if name in visited:
            return False
        visited.add(name)
        for _, mnemonic, operand in image.method(name)["instructions"]:
            if mnemonic == "call" and operand.startswith("0x"):
                for target in image.symbols.get(int(operand, 16), ()):
                    if target.endswith(".AfterLoadProgrammingInformation") and calls_loader(target, visited):
                        return True
        return False
    for row in REGISTRATIONS:
        _, _, _, klass, agent, _ = row
        if klass not in model.INPUT_CLASSES or klass in model.UNMAPPED_INPUT_CLASSES or agent in agents:
            continue
        if agent == "TIOPECGateAgent":
            agents[agent] = {"pp_mapping": "dedicated IOPE StatusReportInterval scalar"}
            continue
        symbols = [name for name in image.by_name if name.endswith(".." + agent)]
        if len(symbols) != 1:
            raise ValueError("Unresolved exact agent " + agent)
        ancestry = image.ancestry(symbols[0])
        effective = next((name for ancestor in ancestry for name in image.by_name
                          if name.endswith("." + ancestor + ".AfterLoadProgrammingInformation")), None)
        checks["agent_pp_loader:" + agent] = effective is not None and calls_loader(effective, set())
        agents[agent] = {"effective_after_load": effective, "common_status_pp_loader_reached": checks["agent_pp_loader:" + agent]}
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise ValueError("Source verification failed: " + ", ".join(failed))
    return {
        "format": "cbus-toolkit-project-documentor-status-static-v1",
        "original_exe_sha256": EXE_SHA256, "original_map_sha256": MAP_SHA256,
        "original_executed": False, "original_generated_page_compared": False,
        "model_module_sha256": hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest(),
        "status_report_basis": model.STATUS_REPORT_BASIS,
        "interface_guid": model.ICBUS_INPUT_UNIT_GUID,
        "registration_count": len(registry), "input_registration_count": sum(bool(classes[cls.split("..")[-1]]) for _, cls, _, _ in registry),
        "classes": classes, "admitted_pp_agent_mappings": agents,
        "unmapped_input_classes": sorted(model.UNMAPPED_INPUT_CLASSES),
        "method_spans": {name: {"start": hex(m["start"]), "end": hex(m["end"]), "sha256": m["sha256"]}
                         for name, m in methods.items()},
        "failed_load_handler_entries": [hex(address) for address in handlers],
        "checks": checks,
        "limit": "Stored PP projection cannot observe original programming-load failures or cancellation. Unknown class/firmware or unrecovered/missing scalar stays unknown, not None. Unit-manager order controls first-tie selection. No native page or hardware acceptance.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
