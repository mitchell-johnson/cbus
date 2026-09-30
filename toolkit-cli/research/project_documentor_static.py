"""Verify the source-only Toolkit 1.18 "Document Project" rules used by ``project document``.

Supply the original EXE and MAP explicitly. This never executes vendor code,
opens a project, accesses C-Gate, or inspects site data. It disassembles the
pinned TProjectDocumentor, TDocumentorCommon, per-type documentor and
TProjectNodeHelper.DocumentProject routines, recovers the documentor factory
registrations from the unit initialization sections, resolves each
documentor's effective DocumentHTML/ActionSelectorUse VMT slots, and requires
them to equal the constants in ``cbus_toolkit.project_documentation``. It also
inventories the string literals of every per-type documentor so unrecovered
bodies stay visible. It reports hashes, addresses, identifiers and UI strings,
not proprietary instruction bytes.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
from cbus_toolkit import project_documentation as model  # noqa: E402
from cbus_toolkit.din_output_settings import PROFILES  # noqa: E402
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402

FORMAT = "cbus-toolkit-project-documentor-static-v1"
FACTORY = "CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType"
UNIT_FACTORY = "CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType"
# Delphi 32-bit VMT: the MAP class symbol is vmtSelfPtr (-0x58).
VMT_SELF, VMT_CLASS_NAME, VMT_PARENT = 0x58, 0x38, 0x30
SLOT_DOCUMENT_HTML, SLOT_ACTION_SELECTOR_USE = 0x7C, 0x80
RESOURCES = {
    62334: model.LEVELS_NAME,
    62345: model.DATE_FORMAT_DELPHI,
    62346: model.PROGRESS_TEXT,
    62347: model.PROGRESS_TITLE,
    63389: "An Error occurred during the Project Document procedure.\r\nParts of the document may not be correct",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _full_name(short: str) -> str:
    if short.startswith(("TProjectDocumentor.", "TUnitTypeDocumentor.")):
        return "CIS_TProjectDocumentor." + short
    if short.startswith("TProjectNodeHelper."):
        return "CIS_TProjectNodeHelper." + short
    if "." not in short:
        return "CIS_TDocumentorCommon." + short
    cls = short.split(".", 1)[0]
    return f"CIS_{cls}.{short}"


class _Toolkit(_Image):
    def dword(self, va: int) -> int:
        return struct.unpack("<I", self.pe.get_data(va - self.base, 4))[0]

    def class_name(self, vmt: int) -> str:
        pointer = self.dword(vmt - VMT_CLASS_NAME)
        size = self.pe.get_data(pointer - self.base, 1)[0]
        return self.pe.get_data(pointer - self.base + 1, size).decode("latin-1")

    def vmt(self, symbol: str) -> int:
        start = self.by_name.get(symbol)
        if start is None:
            raise ValueError("Missing exact original MAP class symbol: " + symbol)
        return start + VMT_SELF

    def ancestry(self, symbol: str) -> list[str]:
        vmt, names = self.vmt(symbol), []
        while vmt:
            names.append(self.class_name(vmt))
            parent = self.dword(vmt - VMT_PARENT)
            vmt = self.dword(parent) if parent else 0
            if names[-1] == "TObject":
                break
        return names

    def slot(self, symbol: str, offset: int) -> str:
        target = self.dword(self.vmt(symbol) + offset)
        return sorted(self.symbols.get(target, {"?"}))[0]

    def registrations(self, factory: str = FACTORY) -> tuple[list[tuple[str, str, str, str]], list[dict]]:
        """(unit type, registered class symbol, min, max firmware) in .itext order."""
        target = self.by_name[factory]
        section = next(s for s in self.pe.sections if s.Name.startswith(b".itext"))
        data, origin = section.get_data(), self.base + section.VirtualAddress
        calls = [origin + i for i in range(len(data) - 5)
                 if data[i] == 0xE8 and origin + i + 5 + struct.unpack_from("<i", data, i + 1)[0] == target]
        starts = sorted({self.starts[bisect.bisect_right(self.starts, call) - 1] for call in calls})
        rows, spans = [], []
        for start in starts:
            end = next(address for address in self.starts if address > start)
            raw = self.pe.get_data(start - self.base, end - start)
            pushes, documentor, unit_type = [], None, None
            for insn in self.decoder.disasm(raw, start):
                if insn.mnemonic == "push" and insn.op_str.startswith("0x"):
                    pushes.append(self.literal(int(insn.op_str, 16)))
                match = re.fullmatch(r"ecx, dword ptr \[(0x[0-9a-f]+)\]", insn.op_str)
                if insn.mnemonic == "mov" and match:
                    documentor = sorted(self.symbols[int(match[1], 16)])[0]
                match = re.fullmatch(r"edx, (0x[0-9a-f]+)", insn.op_str)
                if insn.mnemonic == "mov" and match:
                    unit_type = self.literal(int(match[1], 16))
                if insn.mnemonic == "call":
                    if insn.op_str == hex(target):
                        # Extra register-convention arguments are pushed left to right: Min, Max.
                        rows.append((unit_type, documentor, pushes[-2], pushes[-1]))
                    pushes = []
            spans.append({"symbol": sorted(self.symbols[start])[0], "start": hex(start), "bytes": end - start,
                          "sha256": _sha(raw)})
        if len(rows) != len(calls):
            raise ValueError("Unparsed documentor registration")
        return rows, spans

    def levels_names(self) -> dict[int, str]:
        name = "CIS_TStandardCBusApplications.CIS_TStandardCBusApplications"
        method = self.method(name)
        application, current, result = None, None, {}
        for _, mnemonic, operands in method["instructions"]:
            if mnemonic == "mov" and operands.startswith("eax, 0x"):
                text = self.resource(int(operands[5:], 16))
                if text is not None:
                    current = text
            elif mnemonic == "mov" and re.fullmatch(r"edx, 0x[0-9a-f]+", operands):
                application = int(operands[5:], 16)
            elif mnemonic == "call":
                target = sorted(self.symbols.get(int(operands, 16), {"?"}))[0] if operands.startswith("0x") else "?"
                if target.endswith("TStandardCBusApplication.SetLevelsName"):
                    result[application] = current
        return result


def inspect(exe_path: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe_path.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(exe_raw, map_raw)
    checks: dict[str, bool] = {}
    methods = {}
    for short, expected in model.ORIGINAL_LITERALS.items():
        method = image.method(_full_name(short))
        methods[short] = method
        checks[f"literals:{short}"] = tuple(method["literals"]) == tuple(expected)
    for identifier, text in RESOURCES.items():
        checks[f"resource:{identifier}"] = image.strings.get(identifier) == text
    checks["resource_use:date_format"] = model.DATE_FORMAT_DELPHI in methods[
        "TProjectDocumentor.OnDocumentHTMLnew"]["resources"]
    for name, text in (("SetCurrentNetwork", model.PROGRESS_TEXT), ("GeneratingDocumentation", model.PROGRESS_TITLE)):
        method = image.method(f"CIS_TfrmProjectDocumentor.TfrmProjectDocumentor.{name}")
        checks[f"resource_use:{name}"] = text in method["resources"]

    registered, registration_spans = image.registrations()
    registrations = [(unit_type, symbol.split("..")[-1][1:-len("Documentor")], low, high)
                     for unit_type, symbol, low, high in registered]
    checks["registration_symbols"] = all(re.fullmatch(r"CIS_T\w+Documentor\.\.T\w+Documentor", row[1])
                                         for row in registered)
    checks["registrations"] = tuple(registrations) == model.REGISTRATIONS

    classes = sorted({row[1] for row in registrations} | {"UnitType"})
    slots, ancestry = {}, {}
    for short in classes:
        symbol = (f"CIS_TProjectDocumentor..TUnitTypeDocumentor" if short == "UnitType"
                  else f"CIS_T{short}Documentor..T{short}Documentor")
        ancestry[short] = image.ancestry(symbol)
        body, use = (image.slot(symbol, offset) for offset in (SLOT_DOCUMENT_HTML, SLOT_ACTION_SELECTOR_USE))
        slots[short] = tuple(re.fullmatch(r".*\.T(\w+)Documentor\.\w+", item)[1] for item in (body, use))
    checks["documentor_methods"] = slots == model.DOCUMENTOR_METHODS
    wrapper = image.method("CIS_TCustomSceneKeyUnitDocumentor.TCustomSceneKeyUnitDocumentor.DocumentHTML")
    checks["custom_scene_key_unit_base_only"] = (
        not wrapper["literals"]
        and [op for _, m, op in wrapper["instructions"] if m == "call"]
        == [hex(image.by_name["CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML"])])

    unit_classes, _ = image.registrations(UNIT_FACTORY)
    dimmer_units = {}
    for unit_type in sorted(PROFILES):
        symbols = {symbol for registered_type, symbol, _, _ in unit_classes if registered_type == unit_type}
        dimmer_units[unit_type] = {"classes": sorted(symbol.split("..")[-1] for symbol in symbols),
                                   "dimmer_unit": bool(symbols) and all(
                                       "TCBusDimmerUnit" in image.ancestry(symbol) for symbol in symbols)}
    checks["din_profiles_are_dimmer_units"] = all(row["dimmer_unit"] for row in dimmer_units.values())

    levels = image.levels_names()
    checks["levels_names"] = levels == model.LEVELS_NAMES

    def instructions(name: str) -> list[tuple[str, str]]:
        return [(m, op) for _, m, op in image.method(name)["instructions"]]

    checks["format_html_string_replace_all_ignore_case"] = image.pe.get_data(
        int(re.search(r"0x[0-9a-f]+", next(op for m, op in instructions("CIS_TDocumentorCommon.FormatHTMLString")
                                           if m == "mov" and op.startswith("al, byte ptr")))[0], 16)
        - image.base, 1) == b"\x03"
    checks["hex_address_format"] = "%.2x" in image.method(
        "CIS_TCBusObject.TCGateAddressAttribute.PopulateCacheValues")["literals"]
    checks["unassigned_application_255"] = ("mov", "edx, 0xff") in instructions(
        "CIS_TCommonCBus.TCBusNetwork.GetUnassignedApplication")
    checks["trigger_application_202"] = ("mov", "edx, 0xca") in instructions(
        "CIS_TCommonCBus.TCBusNetwork.GetTriggerControlApplication")
    checks["unused_group_255"] = ("cmp", "eax, 0xff") in instructions("CIS_TCommonCBus.TCBusGroup.IsUnused")
    compare = hex(image.by_name["CIS_Strings.VersionStringCompare"])
    within = instructions("CIS_TProjectDocumentor.TUnitTypeDocumentorRegistration.FirmwareWithinLimits")
    checks["firmware_within_limits"] = (within.count(("call", compare)) == 2
                                        and ("jg", next(op for m, op in within if m == "jg")) in within
                                        and any(m == "jge" for m, _ in within))
    project = instructions("CIS_TProjectNodeHelper.TProjectNodeHelper.DocumentProject")
    checks["save_utf8"] = ("call", hex(image.by_name["System.SysUtils.TEncoding.GetUTF8"])) in project \
        if "System.SysUtils.TEncoding.GetUTF8" in image.by_name else any(
            sorted(image.symbols.get(int(op, 16), {""}))[0].endswith("TEncoding.GetUTF8")
            for m, op in project if m == "call" and op.startswith("0x"))
    checks["save_app_path"] = any(sorted(image.symbols.get(int(op, 16), {""}))[0].endswith("GetAppPath")
                                  for m, op in project if m == "call" and op.startswith("0x"))

    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise ValueError("Original documentor source differs from the reproduced model: " + ", ".join(failed))

    inventory = {}
    for symbol in sorted(name for name in image.by_name
                         if re.fullmatch(r"CIS_T\w+Documentor\.T\w+Documentor\.\w+", name)
                         and not name.startswith(("CIS_TProjectDocumentor.", "CIS_TfrmProjectDocumentor."))):
        method = image.method(symbol)
        inventory[symbol.split(".", 1)[1]] = {
            "bytes": method["end"] - method["start"], "sha256": method["sha256"],
            "literals": method["literals"], "resources": method["resources"]}
    if _sha(exe_path.read_bytes()) != EXE_SHA256 or _sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError("Original files changed during inspection")
    status = {short: model.RECOVERED_BODIES.get(slots[short][0], "unrecovered") for short in classes}
    return {
        "format": FORMAT,
        "original_exe_sha256": EXE_SHA256,
        "original_map_sha256": MAP_SHA256,
        "original_executed": False,
        "model_module_sha256": _sha(Path(model.__file__).read_bytes()),
        "supporting_module_sha256": {
            name: _sha(Path(model.__file__).with_name(name + ".py").read_bytes())
            for name in ("project_documentation_devices", "project_documentation_native",
                         "project_documentation_status", "project_documentation_usage",
                         "project_documentation_outputs")
        },
        "method_spans": {short: {"start": hex(m["start"]), "end": hex(m["end"]), "bytes": m["end"] - m["start"],
                                 "sha256": m["sha256"]} for short, m in methods.items()},
        "registration_initializers": registration_spans,
        "registrations": [list(row) for row in registrations],
        "documentor_classes": {short: {"ancestry": ancestry[short], "document_html": slots[short][0],
                                       "action_selector_use": slots[short][1], "body_status": status[short]}
                               for short in classes},
        "din_profile_dimmer_units": dimmer_units,
        "levels_names": {str(key): value for key, value in sorted(levels.items())},
        "resources": {str(key): value for key, value in sorted(RESOURCES.items())},
        "per_type_string_inventory": inventory,
        "checks": {name: True for name in sorted(checks)},
        "limit": ("This verifies pinned original routines, factory registrations, VMT slots and the "
                  "strings the CLI reproduces. It does not execute the Toolkit, load a project, compare a "
                  "generated page, print, or show the progress dialog. Separate bridge/device/status/usage "
                  "receipts pin the additional bounded recovery; unsupported bodies remain open."),
    }


def render(result: dict) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.write(render(inspect(args.exe, args.map)))


if __name__ == "__main__":
    main()
