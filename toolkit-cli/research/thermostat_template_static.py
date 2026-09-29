"""Verify the original thermostat Load Template rules used by ``thermostat template``.

Supply the original EXE and MAP explicitly; optionally the Toolkit help
directory, C-Gate jar and decoded unit specifications. Nothing is executed. The
pinned routines are disassembled and their literals, call order and class
checks must equal ``cbus_toolkit.thermostat_templates``. The report contains
hashes, addresses, symbol names and help topic IDs, not instruction bytes or
specification content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cbus_toolkit import thermostat_templates as model  # noqa: E402

AGENT = "CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent."
UNIT_AGENT = "CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent."
DIALOG = "CIS_TcdThermostatTemplates.TcdThermostatTemplates."
METHODS = (
    AGENT + "LoadThermostatInstallations",
    DIALOG + "HandleBtnLoadClick",
    DIALOG + "ClearOriginalDamperGroups",
    DIALOG + "UpdateEvapProgramParameters",
    UNIT_AGENT + "AgentLoad",
    UNIT_AGENT + "ParameterProgrammingLoadFromTemplate",
    "CIS_TcgcPPLoadFromFile.TcgcPPLoadFromFile.GenerateCommandText",
    "CIS_TddThermostat.TddThermostat.HandleBeforeLoadTemplate",
    "CIS_TddThermostat.TddThermostat.HandleLoadTemplate",
)
# Ordered calls HandleBtnLoadClick must make (a subsequence of its calls).
LOAD_CLICK_ORDER = (
    "CIS_TfrmThermostatLoadTemplate.LoadTypicalInstallation",
    DIALOG + "ClearOriginalDamperGroups",
    "CIS_TThermostat.TZoneManagerService.SetZoneManagerMasterSlave",
    "CIS_TThermostat.TThermostatInstallation.GetTemplateFileName",
    "CIS_TThermostat.TThermostatInstallations.SetCurrentInstallation",
    DIALOG + "UpdateQuickOptions",
    "CIS_TThermostat.TPlantControlService.UpdateParametersForPlantType",
    DIALOG + "UpdateEvapProgramParameters",
)
LOAD_FROM_TEMPLATE_ORDER = (
    UNIT_AGENT + "ExecuteCommandPPResetToDefaults",
    UNIT_AGENT + "ExecuteCommandPPLoadFromFile",
    UNIT_AGENT + "ParameterProgrammingGetAll",
    UNIT_AGENT + "EnsureTagNameIsNotBlank",
    UNIT_AGENT + "SetUnitEditedState",
    UNIT_AGENT + "SaveBurdenOriginalState",
)
CLASSES = {"TPC_TSA": "TProgrammableThermostat", "TPC_TSA5": "TProgrammableThermostat",
           "TPC_TSB": "TBasicThermostat", "TPC_TSB5": "TBasicThermostat"}
# Thermostat topics whose text could document the dialog; all were searched.
HELP_TOPICS = ("2770", "2919", "3054", "3850", "2975", "2982", "2990", "2995", "3813")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _calls(image: _Image, method: dict) -> list[str]:
    result = []
    for _address, mnemonic, operands in method["instructions"]:
        if mnemonic == "call" and re.fullmatch(r"0x[0-9a-f]+", operands):
            names = image.symbols.get(int(operands, 16))
            if names:
                result.append(sorted(names)[0])
    return result


def _subsequence(needle, haystack) -> bool:
    iterator = iter(haystack)
    return all(any(item == value for value in iterator) for item in needle)


def _dword(image: _Image, va: int) -> int:
    return struct.unpack("<I", image.pe.get_data(va - image.base, 4))[0]


def _class_chain(image: _Image, name: str) -> list[str]:
    """Delphi 32-bit VMT: vmtClassName -56, vmtParent -48 (pointer to pointer)."""
    vmt, chain = _dword(image, image.by_name["CIS_TThermostat.." + name]), []
    while vmt:
        text = _dword(image, vmt - 56)
        length = image.pe.get_data(text - image.base, 1)[0]
        chain.append(image.pe.get_data(text - image.base + 1, length).decode("ascii"))
        parent = _dword(image, vmt - 48)
        vmt = _dword(image, parent) if parent else 0
    return chain


def _installations(method: dict) -> dict[int, dict[str, str]]:
    """Pair each installation index store with the template literals after it."""
    table: dict[int, dict[str, str]] = {}
    current = None
    for address, mnemonic, operands in method["instructions"]:
        match = re.fullmatch(r"dword ptr \[eax \+ 0x88\], (0x[0-9a-f]+|[0-9]+)", operands)
        if mnemonic == "mov" and match:
            current = int(match[1], 0)
            table[current] = {}
        text = method["literal_at"].get(address)
        if current is not None and text and re.fullmatch(r"THERMOSTATA?_TEMPLATE\d\d\.xml", text):
            table[current]["programmable" if text.startswith("THERMOSTATA") else "basic"] = text
    return table


def inspect(exe: Path, map_path: Path, help_dir: Path | None, cgate_jar: Path | None,
            spec_dir: Path | None) -> dict:
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Image(exe_raw, map_raw)
    methods = {name: image.method(name) for name in METHODS}
    table = _installations(methods[AGENT + "LoadThermostatInstallations"])
    derived = {family: tuple(sorted(n for n, row in table.items() if family in row))
               for family in ("programmable", "basic")}
    checks = {
        # Index 0 (<Custom>) is stored from a zeroed register with a nil file.
        "installation_indexes": sorted(table) == list(range(1, 10)),
        "installation_numbering": all(row.get(f) == model.template_filename(f, n)
                                      for n, row in table.items() for f in row),
    }
    for family, record in model.FAMILIES.items():
        checks["offered:" + family] = derived[family] == record["offered"]
    checks["programmable_only"] = tuple(sorted(set(derived["programmable"]) - set(derived["basic"]))) == model.PROGRAMMABLE_ONLY
    chains = {name: _class_chain(image, name) for name in CLASSES}
    for name, parent in CLASSES.items():
        checks["class:" + name] = parent in chains[name]
    checks["class_guard"] = "CIS_TThermostat..TProgrammableThermostat" in {
        sorted(image.symbols.get(int(tok, 16), {""}))[0]
        for _a, _m, op in methods[AGENT + "LoadThermostatInstallations"]["instructions"]
        for tok in re.findall(r"0x[0-9a-f]{6,8}", op)}
    click = methods[DIALOG + "HandleBtnLoadClick"]
    checks["load_click_order"] = _subsequence(LOAD_CLICK_ORDER, _calls(image, click))
    checks["load_click_verb"] = "LoadFromTemplate" in click["literals"]
    checks["no_reset_verb_in_dialog"] = "ResetToDefaults" not in click["literals"]
    agent = methods[UNIT_AGENT + "AgentLoad"]
    checks["agent_verbs"] = {"LoadFromTemplate", "ResetToDefaults"} <= set(agent["literals"])
    checks["load_from_template_sequence"] = _subsequence(
        LOAD_FROM_TEMPLATE_ORDER, _calls(image, methods[UNIT_AGENT + "ParameterProgrammingLoadFromTemplate"]))
    checks["native_command_text"] = "PP LOAD_FROM_FILE " in methods[
        "CIS_TcgcPPLoadFromFile.TcgcPPLoadFromFile.GenerateCommandText"]["literals"]
    evap = methods[DIALOG + "UpdateEvapProgramParameters"]
    checks["evap_adjustment"] = (_subsequence(("CIS_TThermostat.TAdvancedUIService.SetEvapProgramEnabled",
                                               "CIS_TThermostat.TPlantControlService.GetInternalPlantType",
                                               "CIS_TThermostat.TAdvancedUIService.SetNonEvapProgramEnabled"),
                                              _calls(image, evap))
                                 and ("sub", "al, 2") in [(m, o) for _a, m, o in evap["instructions"]])
    checks["damper_clear_four_fields"] = sum(
        1 for _a, m, o in methods[DIALOG + "ClearOriginalDamperGroups"]["instructions"]
        if m == "mov" and re.fullmatch(r"dword ptr \[eax \+ 0x16[048c]\], edx", o)) == 4
    help_report = None
    if help_dir is not None:
        pages = {}
        for topic in HELP_TOPICS:
            raw = (help_dir / (topic + ".htm")).read_bytes()
            text = re.sub(r"<[^>]+>", " ", raw.decode("latin-1"))
            pages[topic] = {"sha256": _sha(raw), "mentions_load_template": bool(
                re.search(r"load\s+template|typical\s+installation", text, re.I))}
        help_report = {"topics": pages, "load_template_documented": any(
            page["mentions_load_template"] for page in pages.values())}
    templates = None
    if spec_dir is not None:
        catalog = model.ThermostatTemplateCatalog(spec_dir)
        templates = [{key: row[key] for key in ("family", "number", "filename", "offered_by_original",
                                                 "specification_sha256", "parameter_count")
                      if key in row} for row in catalog.listing()]
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise ValueError("Original thermostat template source differs from the model: " + ", ".join(failed))
    if _sha(exe.read_bytes()) != EXE_SHA256 or _sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError("Original files changed during inspection")
    return {
        "format": "cbus-toolkit-thermostat-template-static-v1",
        "original_exe_sha256": EXE_SHA256,
        "original_map_sha256": MAP_SHA256,
        "cgate_jar_sha256": None if cgate_jar is None else _sha(cgate_jar.read_bytes()),
        "original_executed": False,
        "model_module_sha256": _sha(Path(model.__file__).read_bytes()),
        "method_spans": {name: {"start": hex(value["start"]), "bytes": value["end"] - value["start"],
                                "sha256": value["sha256"]} for name, value in methods.items()},
        "installation_table": {str(n): row for n, row in sorted(table.items())},
        "class_chains": {name: chain[:4] for name, chain in chains.items()},
        "load_click_order": list(LOAD_CLICK_ORDER),
        "load_from_template_order": list(LOAD_FROM_TEMPLATE_ORDER),
        "help": help_report,
        "template_specifications": templates,
        "checks": {name: True for name in sorted(checks)},
        "limit": ("Static source evidence only. Resource-string captions, UpdateParametersForPlantType's "
                  "per-plant group reassignment, AfterLoad/BeforeSave model round-trips and form save "
                  "are not reproduced; the Toolkit was not executed."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--help-dir", type=Path)
    parser.add_argument("--cgate-jar", type=Path)
    parser.add_argument("--spec-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map, args.help_dir, args.cgate_jar, args.spec_dir),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
