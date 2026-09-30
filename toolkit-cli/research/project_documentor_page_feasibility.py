"""Record original Document Project entry dependencies without executing them.

Requires the pinned original EXE/MAP. Output contains method hashes, symbol
names, call counts and bounded storage-operation literals, never vendor code.
This is feasibility evidence, not an original page or native-process capture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit


METHODS = (
    "CIS_TProjectNodeHelper.TProjectNodeHelper.DocumentProject",
    "CIS_TfrmProjectDocumentor.TfrmProjectDocumentor.TimerStartTimer",
    "CIS_TProjectDocumentor.TProjectDocumentor.SetProject",
    "CIS_TProjectDocumentor.TProjectDocumentor.OnDocumentHTMLnew",
    "CIS_TProjectDocumentor.TProjectDocumentor.GetAllProjectInfo",
    "CIS_TProjectDocumentor.TProjectDocumentor.GetAllUnitProgramming",
    "CIS_TProjectDocumentor.TProjectDocumentor.GetUnitProgramming",
    "CIS_TProjectDocumentor.TProjectDocumentor.EnsureUnitsApplicationsGroupsLoaded",
    "CIS_TCBusObject.TCGateObjectManager.LoadAndSort",
    "CIS_TCBusNetworkCGateAgent.TCBusNetworkCGateAgent.LoadAllUnitApplications",
)
SLOTS = (
    ("Classes..TStringList", 0x80, "Classes.TStrings.SaveToFile"),
    ("CIS_TfrmProjectDocumentor..TfrmProjectDocumentor", 0x110, "Forms.TCustomForm.ShowModal"),
    ("CIS_TCommonCBus..TCBUSUnit", 0x88, "CIS_TIdentifiableObject.TPersistableObject.StorageLoad"),
)


def inspect(executable: Path, map_file: Path) -> dict:
    raw, symbols = executable.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError("Requires the pinned original Toolkit EXE/MAP")
    image = _Toolkit(raw, symbols)
    methods = {}
    for name in METHODS:
        method = image.method(name)
        direct, indirect = [], 0
        for _, mnemonic, operands in method["instructions"]:
            if mnemonic != "call":
                continue
            if not operands.startswith("0x"):
                indirect += 1
                continue
            target = int(operands, 16)
            names = sorted(image.symbols.get(target, ()))
            if not names:
                raise ValueError("Unresolved direct call in " + name)
            direct.append(names[0])
        methods[name] = {"start": hex(method["start"]), "end": hex(method["end"]),
                         "sha256": method["sha256"], "direct_calls_in_order": direct,
                         "indirect_call_sites": indirect}
    slots = []
    for name, offset, expected in SLOTS:
        actual = image.slot(name, offset)
        if actual != expected:
            raise ValueError("Original VMT target changed: " + name)
        slots.append({"class": name, "slot": hex(offset), "target": actual})
    programming = image.method(METHODS[6])["literals"]
    expected_programming = ["UnitAttributes", "Database", "ProgrammingParameters", "ProgrammingUnlock"]
    if list(dict.fromkeys(programming)) != expected_programming:
        raise ValueError("Original database programming operations changed")
    return {
        "format": "cbus-project-documentor-page-feasibility-static-v1",
        "executable_sha256": EXE_SHA256, "map_sha256": MAP_SHA256,
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "execution": {"vendor_instructions_executed": False, "guest_job_submitted": False,
                      "project_opened": False, "network_io_performed": False,
                      "original_page_captured": False},
        "pe": {"machine": hex(image.pe.FILE_HEADER.Machine),
               "subsystem": image.pe.OPTIONAL_HEADER.Subsystem,
               "clr_runtime_header_rva": image.pe.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress},
        "methods": methods, "resolved_vmt_slots": slots,
        "unit_programming_storage_literals_in_order": programming,
        "acceptance": {"original_generated_page": "not_captured",
                       "byte_parity": "unassessed", "visual_parity": "unassessed"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.executable, args.map_file)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"method_spans": len(result["methods"]), "output": str(args.output),
                      "vendor_instructions_executed": False}))


if __name__ == "__main__":
    main()
