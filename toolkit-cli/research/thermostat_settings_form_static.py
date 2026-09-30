"""Inspect pinned Toolkit thermostat dialog rules without executing originals.

The receipt contains method boundaries/digests, recovered constants, model
attribute/control names and checks. Original binaries, MAP and instruction
bytes remain private. This verifies a method subset, not GUI lifecycle parity.
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
from thermostat_post_load_static import _Walker  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cbus_toolkit import thermostat_settings_guard as model  # noqa: E402

PLANT = "CIS_TcdThermostatPlant.TcdThermostatPlant."
TEMPLATES = "CIS_TcdThermostatTemplates."
ZONE = "CIS_TcdThermostatZoneManagement.TcdThermostatZoneManagement."
METHODS = (
    "CIS_TThermostat.TPlantTypeAttribute.GetAllowedPlantModes",
    "CIS_TThermostat.TPlantTypeAttribute.GetDefaultPlantModes",
    "CIS_TThermostat.TThermostat.EvaporativeControlEnabled",
    "CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation",
    TEMPLATES + "ZonePartiallyOn", TEMPLATES + "ZoneFullyOn", TEMPLATES + "CheckBoxStateForZone",
    TEMPLATES + "UpdateFlashZoneVariables", TEMPLATES + "IncludeZone", TEMPLATES + "ExcludeZone",
    TEMPLATES + "TcdThermostatTemplates.Initialise",
    TEMPLATES + "TcdThermostatTemplates.UpdateQuickOptions",
    TEMPLATES + "TcdThermostatTemplates.HandleChbUsedZoneClick",
    PLANT + "EnableDisablePlantModes", PLANT + "EnableDisableVentPlantType",
    PLANT + "EnableDisableZone", PLANT + "EnableControlsForMasterDisableForSlave",
    PLANT + "SetupComponents", PLANT + "HandleFanCoilUpdate", PLANT + "HandleFanSpeedsUpdate",
    PLANT + "HandleEvaporativeCoolingUpdate", ZONE + "EnableDisableZone",
    "CIS_TcdThermostatUI.TcdThermostatUI.EnableDisableZone",
    "CIS_TcdThermostatTempControl.TcdThermostatTempControl.EnableDisableZone",
    "CIS_TddThermostat.TddThermostat.HandleEnableDisableZone",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fields(walker, symbol):
    """Published Delphi 32-bit field table; offsets independently name controls."""
    result, vmt = {}, walker.image.by_name[symbol] + 0x58
    while vmt:
        table = walker.dword(vmt - 0x44)
        if table:
            count = struct.unpack("<H", walker.image.pe.get_data(table - walker.image.base, 2))[0]
            position = table + 6
            for _ in range(count):
                offset = walker.dword(position)
                length = walker.image.pe.get_data(position + 6 - walker.image.base, 1)[0]
                result.setdefault(offset, walker.image.pe.get_data(
                    position + 7 - walker.image.base, length).decode("ascii"))
                position += 7 + length
        parent = walker.dword(vmt - 0x30)
        vmt = walker.dword(parent) if parent else 0
    return result


def _constant_table(walker, method):
    rows, tables, _digest = method
    by_address = {row[0]: row for row in rows}
    result = []
    for address in tables[0]:
        _a, mnemonic, operand, _note = by_address[address]
        match = re.fullmatch(r"al, byte ptr \[(0x[0-9a-f]+)\]", operand)
        if mnemonic != "mov" or match is None:
            raise ValueError("Unexpected original plant-mode table entry")
        result.append(walker.image.pe.get_data(int(match[1], 16) - walker.image.base, 1)[0])
    return result


def _zone_sources(rows, operation):
    result, last = [], None
    for _address, mnemonic, _operand, note in rows:
        if mnemonic != "call":
            continue
        if ".Get" in note and ".TZones.GetZones" not in note:
            last = note
        if note.endswith(".TZones." + operation):
            name = last.rsplit(".Get", 1)[1]
            if name == "ControlledZones" and ".TScheduleService." in last:
                name = "ScheduleControlledZones"
            result.append(name)
    return result


def inspect(exe: Path, map_path: Path):
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if sha(exe_raw) != EXE_SHA256 or sha(map_raw) != MAP_SHA256:
        raise ValueError("Pinned original Toolkit EXE/MAP hash mismatch")
    image = _Image(exe_raw, map_raw)
    walker = _Walker(image)
    methods = {name: walker.listing(name) for name in METHODS}
    allowed = _constant_table(walker, methods[METHODS[0]])
    defaults = _constant_table(walker, methods[METHODS[1]])
    partial = _zone_sources(methods[TEMPLATES + "ZonePartiallyOn"][0], "GetZones")
    full = _zone_sources(methods[TEMPLATES + "ZoneFullyOn"][0], "GetZones")
    include = _zone_sources(methods[TEMPLATES + "IncludeZone"][0], "IncludeZone")
    exclude = _zone_sources(methods[TEMPLATES + "ExcludeZone"][0], "ExcludeZone")
    fields = {name: _fields(walker, "CIS_" + name + ".." + name) for name in (
        "TfrmThermostatPlant", "TfrmThermostatUI", "TfrmThermostatTempControl",
        "TfrmThermostatZoneManagement")}
    checks = {
        "allowed_modes_match_model": allowed == list(model.ALLOWED_PLANT_MODES),
        "zone_partial_and_full_same_source_fields": partial == full,
        "zone_source_fields_match_model": set(partial) == set(model.ZONE_STATE_PARAMETERS) | {"ScheduleControlledZones"},
        "installed_and_manager_controlled_not_zone_state_sources": not {"InstalledZones", "ControlledZones"} & set(partial),
        "include_and_exclude_same_target_fields": include == exclude,
        "zone_transition_target_fields_match_model": set(include) == set(model.ZONE_TRANSITION_PARAMETERS) | {"UsedZones", "ScheduleControlledZones"},
        "mode_checkbox_field_names": [fields["TfrmThermostatPlant"][n] for n in (0x3b8, 0x3bc, 0x3c0, 0x3c4)] == [
            "chbPlantModeHeat", "chbPlantModeCool", "chbPlantModeHeatCool", "chbPlantModeVent"],
        "vent_selector_field_name": fields["TfrmThermostatPlant"][0x428] == "cmbVentPlantType",
        "basic_hidden_field_names": [fields["TfrmThermostatPlant"][n] for n in (0x390, 0x41c)] == ["gbPlantZones", "btnDamperGroups"],
        "plant_mode_bit_tests": [int(op.split(", ")[1], 0) for _a, mn, op, _n in methods[
            PLANT + "EnableDisablePlantModes"][0] if mn == "test" and re.fullmatch(r"al, (2|4|8|0x10)", op)] == [2, 4, 8, 16],
    }
    for suffix in ("Plant", "ZoneManagement"):
        rows = methods["CIS_TcdThermostat" + suffix + ".TcdThermostat" + suffix + ".EnableDisableZone"][0]
        checks[suffix + "_zone_master_and"] = any(mn == "and" and op == "al, byte ptr [ebp - 7]"
                                                    for _a, mn, op, _n in rows)
    checkbox_vmt = image.by_name["StdCtrls..TCheckBox"] + 0x58
    checks["checkbox_enabled_checked_vmt_slots"] = {
        slot: walker.name(walker.dword(checkbox_vmt + slot)) for slot in (0x5c, 0x74, 0xec)
    } == {0x5c: "Controls.TControl.GetEnabled", 0x74: "Controls.TControl.SetEnabled",
          0xec: "StdCtrls.TCustomCheckBox.GetChecked"}
    # The initialization guard suppresses UpdateFlashZoneVariables while
    # SetupComponents performs its initial quick-option refresh.
    init = methods[TEMPLATES + "TcdThermostatTemplates.Initialise"][0]
    quick = methods[TEMPLATES + "TcdThermostatTemplates.UpdateQuickOptions"][0]
    checks["initialization_sets_and_clears_flash_guard"] = [op for _a, mn, op, _n in init
        if mn == "mov" and op.startswith("byte ptr [eax + 0x29], ")] == [
            "byte ptr [eax + 0x29], 1", "byte ptr [eax + 0x29], 0"]
    checks["quick_refresh_checks_flash_guard"] = any(mn == "cmp" and op == "byte ptr [eax + 0x29], 0"
                                                     for _a, mn, op, _n in quick)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Original thermostat form differs: " + ", ".join(failed))
    if sha(exe.read_bytes()) != EXE_SHA256 or sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP changed during inspection")
    return {
        "format": "cbus-thermostat-settings-form-static-v1",
        "original_exe_sha256": EXE_SHA256, "original_map_sha256": MAP_SHA256,
        "original_executed": False, "complete_dialog_reproduced": False,
        "model_module_sha256": sha(Path(model.__file__).read_bytes()),
        "method_spans": {name: {"start": hex(image.by_name[name]),
            "bytes": next(a for a in image.starts if a > image.by_name[name]) - image.by_name[name],
            "sha256": method[2]} for name, method in methods.items()},
        "allowed_plant_modes": allowed, "default_plant_modes": defaults,
        "zone_state_sources_in_original_order": partial,
        "zone_transition_targets_in_original_order": include,
        "published_control_fields": {name: {hex(offset): value for offset, value in mapping.items()
                                             if offset >= 0x390} for name, mapping in fields.items()},
        "checks": checks,
        "limits": ["Static inspection only; original GUI and its complete event order were not executed.",
                   "Quick-zone union is not an InstalledZones subset validation rule.",
                   "InstalledZones rewrite and VentPlantType fallback are guarded event effects, not unconditional PP load normalization.",
                   "Remaining controls, parent visibility, edit admission and group creation remain open."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
