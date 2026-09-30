"""Pin the recovered thermostat quick-zone event graph and its open boundaries.

Static evidence only: no original execution, project creation or public action
acceptance. The receipt records source spans, symbolic edges and checked guards;
it deliberately does not publish original instruction bytes or project data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402
from thermostat_settings_form_static import _fields, _zone_sources  # noqa: E402

PARENT = "CIS_TddThermostat.TddThermostat."
TEMPLATES = "CIS_TcdThermostatTemplates."
PANEL = TEMPLATES + "TcdThermostatTemplates."
PLANT_PANEL = "CIS_TcdThermostatPlant.TcdThermostatPlant."
MODEL = "CIS_TThermostat.TThermostat."
ZONE = "CIS_TThermostat.TZoneManagerService."
PLANT = "CIS_TThermostat.TPlantControlService."
CBUS = "CIS_TThermostat.TCBusParameters."
AGENT = "CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent."
SAVED_CONTROLLED = "CIS_TCBusThermostatCGateAgent.GetControlledZones"
BOOL_SET = "CIS_TBooleanAttribute.TBooleanAttribute.SetAsBoolean"
METHODS = (
    PARENT + "Initialise", PARENT + "InitialiseSubForms",
    PARENT + "HandleEnableDisableZone", PARENT + "UpdateZoneCheckboxes",
    PANEL + "Initialise", PANEL + "SetupComponents", PANEL + "SetupQuickOptions",
    PANEL + "HandleUnitZoneChange", PANEL + "HandleChbUsedZoneClick",
    PANEL + "UpdateQuickOptions", TEMPLATES + "UpdateFlashZoneVariables",
    TEMPLATES + "IncludeZone", TEMPLATES + "ExcludeZone",
    TEMPLATES + "AllZonesUnticked", TEMPLATES + "ZonePartiallyOn",
    TEMPLATES + "ZoneFullyOn", TEMPLATES + "CheckBoxStateForZone",
    PLANT_PANEL + "Initialise", PLANT_PANEL + "EnableDisablePlantModes",
    PLANT_PANEL + "EnableDisableZone",
    "CIS_TcdThermostatUI.TcdThermostatUI.EnableDisableZone",
    "CIS_TcdThermostatZoneManagement.TcdThermostatZoneManagement.EnableDisableZone",
    "CIS_TcdThermostatTempControl.TcdThermostatTempControl.EnableDisableZone",
    ZONE + "HookEvents", ZONE + "HandleZoneAfterChange",
    ZONE + "GetZoneManagerMasterSlave", ZONE + "SetZoneManagerMasterSlave",
    MODEL + "HandleZoneManagerPlantTypeChange", MODEL + "HandleZoneChange",
    MODEL + "HandleInstalledZonesChange", PLANT + "HandleVentPlantTypeChange",
    PLANT + "HandleZoneAfterChange", PLANT + "UpdateDamperGroups",
    CBUS + "HookEvents", CBUS + "HandleInstalledZonesAfterChange",
    AGENT + "AfterLoadProgrammingInformation", AGENT + "BeforeSaveProgrammingInformation",
    AGENT + "CreateSpecialApplications", SAVED_CONTROLLED, BOOL_SET,
    "CIS_TThermostatCommon.TZones.SetZones",
    "CIS_TThermostat.TUIService.HandleZoneAfterChange",
    "CIS_TThermostat.TTemperatureMeasurementService.HandleZoneAfterChange",
    "CIS_TThermostat.TScheduleService.HandleZoneAfterChange",
)
TARGET_ORDER = ["UsedZones", "UIAllocatedZones", "InternalPlantZones", "MeasuredZones",
                "ScheduleControlledZones", "InstalledZones", "ControlledZones",
                "HeatingPlantInstalledZones", "CoolingPlantInstalledZones", "VentingPlantInstalledZones"]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path):
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if sha(exe_raw) != EXE_SHA256 or sha(map_raw) != MAP_SHA256:
        raise ValueError("Pinned original Toolkit EXE/MAP hash mismatch")
    walker = _Walker(_Image(exe_raw, map_raw))
    image = walker.image
    methods = {name: walker.listing(name) for name in METHODS}

    def calls(name):
        return [note for _a, mn, _op, note in methods[name][0] if mn == "call" and note]

    def has(name, mnemonic, operand):
        return any(mn == mnemonic and op == operand for _a, mn, op, _n in methods[name][0])

    def writes(name, offset):
        return [op.rsplit(", ", 1)[1] for _a, mn, op, _n in methods[name][0]
                if mn == "mov" and op.startswith(f"byte ptr [eax + {offset}], ")]

    def at(name, address, mnemonic, operand):
        return any(a == address and mn == mnemonic and op == operand
                   for a, mn, op, _n in methods[name][0])

    fields = _fields(walker, "CIS_TfrmThermostatTemplates..TfrmThermostatTemplates")
    parent_vmt = image.by_name["CIS_TddThermostat..TddThermostat"] + 0x58
    enable_order = ["CIS_TcdThermostat" + n + ".TcdThermostat" + n + ".EnableDisableZone"
                    for n in ("UI", "ZoneManagement", "Plant", "TempControl")]
    create_order = ["CIS_TcdThermostat" + n + ".TcdThermostat" + n + ".Create"
                    for n in ("CBus", "UI", "ZoneManagement", "Plant", "TempControl", "Templates")]
    no_master_set_methods = [TEMPLATES + "IncludeZone", TEMPLATES + "ExcludeZone",
                            ZONE + "HandleZoneAfterChange", MODEL + "HandleZoneChange",
                            MODEL + "HandleInstalledZonesChange", PLANT + "HandleZoneAfterChange"]
    checks = {
        "subforms_created_in_original_order": [n for n in calls(PARENT + "InitialiseSubForms")
                                               if n.endswith(".Create")] == create_order,
        "parent_enable_callback_vmt_slot": walker.name(walker.dword(parent_vmt + 0x90))
                                           == PARENT + "HandleEnableDisableZone",
        "templates_bind_parent_enable_slot": at(PARENT + "InitialiseSubForms", 0x1132c16,
                                                "mov", "edx, dword ptr [edx + 0x90]")
            and at(PARENT + "InitialiseSubForms", 0x1132c1c, "mov", "dword ptr [eax + 0x30], edx"),
        "parent_enable_callback_order": calls(PARENT + "HandleEnableDisableZone") == enable_order,
        "templates_initial_flash_guard": writes(PANEL + "Initialise", "0x29") == ["1", "0"],
        "templates_initial_reentry_guard": writes(PANEL + "Initialise", "0x28") == ["1", "0"],
        "plant_initial_vent_fallback_guard": writes(PLANT_PANEL + "Initialise", "0x2a") == ["1", "0"],
        "basic_quick_zone_group_named": fields[0x39c] == "gbControlledZones",
        "basic_quick_zone_group_hidden": at(PANEL + "SetupComponents", 0x111e2d6,
                                             "mov", "eax, dword ptr [eax + 0x39c]")
            and at(PANEL + "SetupComponents", 0x111e2dc, "xor", "edx, edx")
            and at(PANEL + "SetupComponents", 0x111e2de, "call", "0x6f61c0")
            and any(n == "CIS_TThermostat..TBasicThermostat" for _a, _m, _o, n
                    in methods[PANEL + "SetupComponents"][0]),
        "click_guard_spans_action": has(PANEL + "HandleChbUsedZoneClick", "cmp", "byte ptr [eax + 0x28], 0")
            and writes(PANEL + "HandleChbUsedZoneClick", "0x28") == ["1", "0"],
        "quick_refresh_checks_action_guard": has(PANEL + "UpdateQuickOptions", "cmp", "byte ptr [eax + 0x28], 0"),
        "quick_refresh_checks_initial_flash_guard": has(PANEL + "UpdateQuickOptions", "cmp", "byte ptr [eax + 0x29], 0"),
        "click_has_no_direct_post_action_quick_refresh": PANEL + "UpdateQuickOptions" not in calls(PANEL + "HandleChbUsedZoneClick"),
        "unit_zone_handler_only_refreshes_quick_options": calls(PANEL + "HandleUnitZoneChange") == [PANEL + "UpdateQuickOptions"],
        "include_order": _zone_sources(methods[TEMPLATES + "IncludeZone"][0], "IncludeZone") == TARGET_ORDER,
        "exclude_order": _zone_sources(methods[TEMPLATES + "ExcludeZone"][0], "ExcludeZone") == TARGET_ORDER,
        "zone_empty_types_cleared_in_order": [n for n in calls(ZONE + "HandleZoneAfterChange") if ".Set" in n]
            == [ZONE + "SetHeatingPlantType", ZONE + "SetCoolingPlantType", ZONE + "SetVentingPlantType"],
        "zone_empty_constant_is_zero": image.pe.get_data(0xfde784 - image.base, 1) == b"\0",
        "model_zone_handler_has_reentry_guard": writes(ZONE + "HandleZoneAfterChange", "0x130") == ["1", "0"],
        "selected_zone_handlers_do_not_set_master_slave": all(ZONE + "SetZoneManagerMasterSlave" not in calls(n)
                                                              for n in no_master_set_methods),
        "installed_zone_handler_updates_dampers": calls(MODEL + "HandleInstalledZonesChange")
            == [MODEL + "GetPlantControlService", PLANT + "UpdateDamperGroups"],
        "damper_method_contains_search_and_creation": all(n in calls(PLANT + "UpdateDamperGroups") for n in (
            PLANT + "FindExistingGroup", "CIS_TCommonCBus.TCBusGroupManager.GetNextAvailableAddress",
            "CIS_TCommonCBus.TCBusGroupManager.GroupByAddress")),
        "master_save_reads_installed_not_manager_controlled": CBUS + "GetInstalledZones" in calls(SAVED_CONTROLLED)
            and ZONE + "GetControlledZones" not in calls(SAVED_CONTROLLED)
            and ZONE + "GetZoneManagerMasterSlave" in calls(SAVED_CONTROLLED),
        "common_save_uses_nested_controlled_getter": SAVED_CONTROLLED in calls(AGENT + "BeforeSaveProgrammingInformation"),
        "afterload_sets_master_slave": calls(AGENT + "AfterLoadProgrammingInformation").count(ZONE + "SetZoneManagerMasterSlave") == 2,
        "boolean_set_compares_old_value_before_change": at(BOOL_SET, 0x7f45f2, "cmp", "al, byte ptr [ebp - 5]")
            and at(BOOL_SET, 0x7f45f5, "je", "0x7f4632"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Original quick-zone event graph differs: " + ", ".join(failed))
    spans = {name: {"start": hex(image.by_name[name]),
                    "bytes": next(a for a in image.starts if a > image.by_name[name]) - image.by_name[name],
                    "sha256": method[2]} for name, method in methods.items()}
    # Only selected resolved direct calls are edges. Indirect callback resolution
    # is recorded separately; this is not a complete call graph or an execution.
    selected_edges = {name: [{"at": hex(a), "target": note} for a, mn, _op, note in rows
                             if mn == "call" and note in methods]
                      for name, (rows, _tables, _digest) in methods.items()}
    graph_calls = [{"at": hex(a), "target": note} for a, mn, _op, note in methods[
        AGENT + "AfterLoadProgrammingInformation"][0]
        if mn == "call" and (".GroupBy" in note or ".ApplicationBy" in note
                             or ".GetDefault" in note or note.endswith(".CreateSpecialApplications"))]
    if sha(exe.read_bytes()) != EXE_SHA256 or sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP changed during inspection")
    return {
        "format": "cbus-thermostat-quick-zone-events-static-v1",
        "original_exe_sha256": EXE_SHA256, "original_map_sha256": MAP_SHA256,
        "original_executed": False, "complete_event_graph_reproduced": False,
        "public_quick_zone_action_ready": False, "raw_pp_only_action_admissible": False,
        "method_count": len(methods), "check_count": len(checks), "checks": checks,
        "method_spans": spans, "selected_direct_edges": selected_edges,
        "afterload_project_graph_lookup_sites": graph_calls,
        "zone_target_order": TARGET_ORDER,
        "selected_no_master_set_methods": no_master_set_methods,
        "candidate_phase": "fresh initialized programmable master; one accepted quick-zone click; no plant/type edits",
        "candidate_preconditions_not_yet_admission": [
            "Retain loaded master/slave enum rather than recomputing it after zone edits.",
            "Every nonzero Heating/Cooling/VentingPlantType has nonempty installed zones initially and after the action.",
            "Every surviving installed switched zone already has a resolved non-255 damper object.",
            "Attest all consumed initial applications/groups, exact tags, unused sentinel and fresh cache state.",
            "Close generic attribute dispatch and initial control binding ordering before declaring action acceptance.",
        ],
        "limits": [
            "Selected direct edges and branch guards are pinned; indirect dispatch and all subscribers are not fully closed.",
            "Pure quick_zone_transition only models explicit mask writes, not nested model callbacks or project effects.",
            "No unconditional UpdateFlashZoneVariables or Vent fallback may be added to this click route.",
            "Raw PP cannot prove project object existence, tags, application identity, sentinel or retained damper cache state.",
            "A fresh synthetic project graph can support future bounded acceptance when all reachable effects are modeled or excluded.",
        ],
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
