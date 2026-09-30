"""Pin seven-panel binding sites and quick-zone initialization boundaries.

This is a syntactic source inventory and checked branch evidence, not symbolic
execution of the initializers or a claim that an initialized form is reproduced.
No original code executes, no process is launched, and no network is accessed.
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
from thermostat_settings_form_static import _fields  # noqa: E402
from thermostat_quick_zone_initialization_static import dfm_properties  # noqa: E402

PANELS = {"CBus": 0x24, "UI": 0x18, "ZoneManagement": 0x24, "Plant": 0x20,
          "TempControl": 0x28, "Templates": 0x24, "Scheduling": 0x24}
PARENT = "CIS_TddThermostat.TddThermostat."
TPL = "CIS_TcdThermostatTemplates.TcdThermostatTemplates."
TEMP = "CIS_TcdThermostatTempControl.TcdThermostatTempControl."
PLANT = "CIS_TcdThermostatPlant.TcdThermostatPlant."


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def panel_prefix(panel):
    return "CIS_TcdThermostat" + panel + ".TcdThermostat" + panel + "."


def dynamic_methods(walker, class_symbol):
    """Resolve published Delphi dynamic method IDs, retaining derived overrides."""
    result, vmt = {}, walker.image.by_name[class_symbol] + 0x58
    while vmt:
        table = walker.dword(vmt - 0x3c)
        if table:
            count = struct.unpack("<H", walker.image.pe.get_data(table - walker.image.base, 2))[0]
            for i in range(count):
                key = struct.unpack("<H", walker.image.pe.get_data(table + 2 + 2 * i - walker.image.base, 2))[0]
                result.setdefault(key, walker.dword(table + 2 + 2 * count + 4 * i))
        parent = walker.dword(vmt - 0x30)
        vmt = walker.dword(parent) if parent else 0
    return result


def direct_bindings(image, rows, form_offset, fields):
    """Recognize only straight-line register loads preceding direct Prepare sites.

    Paths are owner-relative pointer dereferences, not claims about live objects.
    Unknown expressions/paths stay explicit; branch reachability is not inferred.
    """
    registers, prepares, callbacks, pushes = {}, [], [], []
    for address, mnemonic, operands, note in rows:
        if mnemonic == "mov":
            target, source = operands.split(", ", 1)
            if target in ("eax", "edx", "ecx"):
                if source == "dword ptr [ebp - 4]":
                    registers[target] = ()
                elif source in registers:
                    registers[target] = registers[source]
                elif match := re.fullmatch(r"dword ptr \[(eax|edx|ecx) \+ (0x[0-9a-f]+|[0-9]+)\]", source):
                    base = registers.get(match[1])
                    registers[target] = base + (int(match[2], 0),) if isinstance(base, tuple) else None
                elif re.fullmatch(r"0x[0-9a-f]+", source):
                    registers[target] = image.literal(int(source, 16))
                else:
                    registers[target] = None
            elif note and (match := re.fullmatch(r"dword ptr \[eax \+ (0x[0-9a-f]+)\]", target)):
                path = registers.get("eax")
                callbacks.append({"at": hex(address), "slot": match[1], "target": note,
                                  "owner_relative_path": list(path) if isinstance(path, tuple) else None})
        if mnemonic == "push":
            pushes.append({"at": hex(address), "operand": operands})
        if mnemonic == "call":
            if note.startswith("CIS_FlashGUI.Prepare"):
                path = registers.get("eax")
                component = fields.get(path[1]) if isinstance(path, tuple) and len(path) == 2 and path[0] == form_offset else None
                link = registers.get("edx")
                binding = {"at": hex(address), "prepare": note, "component": component,
                           "register_ecx_expression": registers.get("ecx"),
                           "link_owner_relative_path": list(link) if isinstance(link, tuple) else None}
                if note == "CIS_FlashGUI.PrepareFlashComboBox":
                    args = pushes[-8:]
                    binding["eight_stack_pushes_in_source_order"] = args
                    binding["value_expression"] = image.literal(int(args[1]["operand"], 16))
                    binding["value_controller_immediate_apply"] = args[-2]["operand"]
                prepares.append(binding)
            registers = {}
            pushes = []
    return {"prepare_sites": prepares, "literal_callback_assignments": callbacks}


def inspect(exe, map_path, seed_path):
    exe_raw, map_raw, seed_raw = exe.read_bytes(), map_path.read_bytes(), seed_path.read_bytes()
    if (sha(exe_raw), sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError("Pinned original EXE/MAP mismatch")
    seed = json.loads(seed_raw)
    image = _Image(exe_raw, map_raw)
    walker, methods, checks = _Walker(image), {}, {}

    def method(name):
        if name not in methods:
            methods[name] = walker.listing(name)
        return methods[name][0]

    def calls(name):
        return [note for _a, mn, _op, note in method(name) if mn == "call" and note]

    def at(name, address, mnemonic, operand):
        return any(a == address and mn == mnemonic and op == operand for a, mn, op, _n in method(name))

    panels = {}
    for panel, offset in PANELS.items():
        prefix = panel_prefix(panel)
        lifecycle = {}
        for suffix in ("Create", "Initialise", "SetupFlashComponents", "SetupComponents", "HookEvents"):
            name = prefix + suffix
            if name in image.by_name:
                lifecycle[suffix] = [{"at": hex(a), "target": note or op}
                                     for a, mn, op, note in method(name) if mn == "call"]
        fields = _fields(walker, "CIS_TfrmThermostat" + panel + "..TfrmThermostat" + panel)
        resource, components = dfm_properties(image, "TFRMTHERMOSTAT" + panel.upper())
        bindings = direct_bindings(image, method(prefix + "SetupFlashComponents"), offset, fields)
        events = [{"component": name, "class": value["class"], "event": key, "handler": handler}
                  for name, value in components.items() for key, handler in value["properties"].items()
                  if key.startswith("On") or ".On" in key]
        checks[panel + "_prepares_have_direct_component"] = all(r["component"] for r in bindings["prepare_sites"])
        checks[panel + "_prepares_have_expression"] = all(isinstance(r["register_ecx_expression"], str) for r in bindings["prepare_sites"])
        panels[panel] = {"form_offset": hex(offset), "lifecycle_direct_calls": lifecycle,
                         "dfm_sha256": sha(resource), "dfm_bytes": len(resource), "dfm_events": events,
                         **bindings}

    parent_enable = PARENT + "HandleEnableDisableZone"
    checks["parent_enable_order"] = calls(parent_enable) == [panel_prefix(p) + "EnableDisableZone"
                                                            for p in ("UI", "ZoneManagement", "Plant", "TempControl")]
    for panel in ("UI", "ZoneManagement", "Plant", "TempControl"):
        method(panel_prefix(panel) + "EnableDisableZone")
    checks["plant_enable_has_no_plantmode_fallback"] = calls(PLANT + "EnableDisableZone") == [
        "CIS_TThermostat.TThermostat.GetZoneManagerService",
        "CIS_TThermostat.TZoneManagerService.GetZoneManagerMasterSlave",
        "CIS_TThermostat.TThermostat.GetPlantControlService",
        "CIS_TThermostat.TPlantControlService.GetInternalPlantType", PLANT + "EnableCycleLimitingControls"]
    checks["cycle_enable_has_no_direct_callee"] = calls(PLANT + "EnableCycleLimitingControls") == []
    checks["temperature_enable_calls_sliders"] = calls(TEMP + "EnableDisableZone") == [TEMP + "EnableSliders"]
    checks["sliders_invoke_min_max_min"] = [n for n in calls(TEMP + "EnableSliders") if n.startswith(TEMP)] == [
        TEMP + "trkMinimumSetTempChange", TEMP + "trkMaximumSetTempChange", TEMP + "trkMinimumSetTempChange"]
    for suffix, branches in (
            ("trkMinimumSetTempChange", ((0x112f329, "jl", "0x112f350"), (0x112f376, "jg", "0x112f39d"),
                                          (0x112f3cf, "je", "0x112f3d9"))),
            ("trkMaximumSetTempChange", ((0x112f21d, "jg", "0x112f244"), (0x112f26a, "jl", "0x112f291"),
                                          (0x112f2c3, "je", "0x112f2cd")))):
        checks[suffix + "_ordered_unguarded_no_write_branches"] = all(at(TEMP + suffix, a, mn, op) for a, mn, op in branches)
    temp_fields = _fields(walker, "CIS_TfrmThermostatTempControl..TfrmThermostatTempControl")
    checks["temperature_component_mapping"] = [temp_fields[n] for n in (0x3f8, 0x3fc, 0x3c0)] == [
        "trkMaximumSetTemp", "trkMinimumSetTemp", "chbEnableGuard"]
    pp = seed["pp"]
    checks["seed_ordered_unguarded_celsius_pair"] = (pp["MinimumSetTemperature"], pp["MaximumSetTemperature"], pp["GuardEnable"],
                                                    seed["toolkit_context"]["temperature_preference"]) == ("0xf", "0x20", "0x0", "celsius")
    checks["ui_panel_only_installed_zone_subscription"] = calls(panel_prefix("UI") + "HookEvents") == [
        "CIS_TThermostat.TThermostat.GetCBusParameters", "CIS_TThermostat.TCBusParameters.InstalledZonesChangeSubscribe"]
    checks["templates_setup_runs_quick_refresh"] = TPL + "UpdateQuickOptions" in calls(TPL + "SetupComponents")
    checks["initial_templates_flash_guard_spans_setup"] = all(at(TPL + "Initialise", *row) for row in (
        (0x111df72, "mov", "byte ptr [eax + 0x29], 1"),
        (0x111e0ba, "call", "0x111e220"), (0x111e0c2, "mov", "byte ptr [eax + 0x29], 0")))
    checks["guarded_initial_refresh_skips_model_mask_rebuild"] = all(at(TPL + "UpdateQuickOptions", *row) for row in (
        (0x111eacf, "cmp", "byte ptr [eax + 0x29], 0"), (0x111ead3, "jne", "0x111eadc"),
        (0x111ead6, "call", "0x111e7d8")))
    rebuild = "CIS_TcdThermostatTemplates.UpdateFlashZoneVariables"
    checks["mask_rebuild_resets_used_and_installed"] = calls(rebuild)[:5] == [
        "CIS_TThermostat.TThermostat.GetUsedZones", "CIS_TThermostatCommon.TZones.SetZones",
        "CIS_TThermostat.TThermostat.GetCBusParameters", "CIS_TThermostat.TCBusParameters.GetInstalledZones",
        "CIS_TThermostatCommon.TZones.SetZones"]
    for name in (PARENT + "Initialise", PARENT + "InitialiseSubForms", PARENT + "UpdateZoneCheckboxes",
                 "CIS_TddThermostat.TddProgrammableThermostat.InitialiseSubForms",
                 PLANT + "EnableDisablePlantModes", "Controls.TControl.SetEnabled", "Controls.TWinControl.CMEnabledChanged",
                 "CIS_TFlashComboBox.TFlashComboBox.DoEnter", "CIS_TFlashComboBox.TFlashComboBox.DoExit",
                 "CIS_TFlashComboBox.TFlashComboBox.PopulateList", "CIS_TFlashComboBox.TFlashComboBox.RenderDisplay",
                 "CIS_TFlashComboBox.TFlashComboBox.DoIndexChange"):
        method(name)
    checks["combo_focus_entry_populates_list"] = "CIS_TFlashComboBox.TFlashComboBox.PopulateList" in calls(
        "CIS_TFlashComboBox.TFlashComboBox.DoEnter")
    checks["combo_focus_exit_applies_then_renders"] = calls("CIS_TFlashComboBox.TFlashComboBox.DoExit") == [
        "Controls.TWinControl.DoExit", "CIS_Handles.TFlashExpressionController.ExitingControl",
        "CIS_TFlashComboBox.TFlashComboBox.RenderDisplay"]
    checks["all_thirteen_prepared_element_combos_immediate_apply"] = (
        len(combos := [r for p in panels.values() for r in p["prepare_sites"]
                       if r["prepare"] == "CIS_FlashGUI.PrepareFlashComboBox"]) == 13
        and all(r["value_controller_immediate_apply"] == "1" for r in combos))
    checks["prepare_combo_sets_value_immediate_apply_from_penultimate_push"] = all(at(
        "CIS_FlashGUI.PrepareFlashComboBox", *row) for row in (
            (0xc0fe1f, "mov", "eax, dword ptr [eax + 0x318]"),
            (0xc0fe25, "mov", "dl, byte ptr [ebp + 0xc]"),
            (0xc0fe28, "mov", "byte ptr [eax + 0x58], dl")))
    checks["immediate_apply_exit_skips_apply"] = all(at("CIS_Handles.TFlashExpressionController.ExitingControl", *row)
        for row in ((0x84da72, "cmp", "byte ptr [eax + 0x58], 0"), (0x84da76, "jne", "0x84da80")))
    combo = "CIS_TFlashComboBox.TFlashComboBox."
    form = "CIS_TfrmThermostatPlant.TfrmThermostatPlant."
    for name in (combo + "Loaded", combo + "RenderedValueChange", combo + "CNCommandHandler", combo + "Change",
                 "StdCtrls.TCustomCombo.CNCommand", "StdCtrls.TCustomCombo.Change", "StdCtrls.TCustomCombo.Select",
                 "Controls.TControl.SetText", "Controls.TControl.SetTextBuf", "Controls.TWinControl.CMTextChanged",
                 form + "cmbInternalPlantTypeChange", form + "HandlePlantTypeChange",
                 PLANT + "HandleInternalPlantTypeAfterChange", PLANT + "UpdateParametersToMatchPlantType"):
        method(name)
    dynamic = dynamic_methods(walker, "CIS_TFlashComboBox..TFlashComboBox")
    checks["combo_dynamic_change_resolves_original_override"] = walker.name(dynamic[0xffb0]) == combo + "Change"
    checks["combo_dynamic_select_is_inherited"] = walker.name(dynamic[0xffaf]) == "StdCtrls.TCustomCombo.Select"
    checks["combo_notification5_enters_dynamic_change"] = (walker.dword(0x6876e0 + 5 * 4) == 0x687714
        and at("StdCtrls.TCustomCombo.CNCommand", 0x687716, "mov", "si, 0xffb0"))
    checks["combo_change_reaches_original_event_dispatch"] = (calls(combo + "Change") == ["StdCtrls.TCustomCombo.Change"]
        and at("StdCtrls.TCustomCombo.Change", 0x68784c, "call", "dword ptr [ebx + 0x288]"))
    checks["stable_display_text_skips_set_text_buffer"] = at("Controls.TControl.SetText", 0x6f6305, "je", "0x6f6317")
    checks["plant_dfm_change_callback"] = panels["Plant"]["dfm_events"] == [{
        "component": "cmbInternalPlantType", "class": "TFlashComboBox", "event": "OnChange",
        "handler": "cmbInternalPlantTypeChange"}]
    checks["plant_change_posts_0423"] = (at(form + "cmbInternalPlantTypeChange", 0x112220c, "push", "0x423")
        and "Windows.PostMessage" in calls(form + "cmbInternalPlantTypeChange"))
    checks["plant_message_dispatches_current_callback"] = at(form + "HandlePlantTypeChange", 0x11221ee,
                                                            "call", "dword ptr [ebx + 0x460]")
    checks["plant_message_callback_wired_after_prepare"] = (at(PLANT + "SetupFlashComponents", 0x1127460, "call", "0xc0fd30")
        and at(PLANT + "SetupFlashComponents", 0x1127493, "mov", "dword ptr [eax + 0x460], 0x112947c"))
    checks["plant_afterchange_runs_parameter_update_without_initialization_guard"] = calls(
        PLANT + "HandleInternalPlantTypeAfterChange")[0] == PLANT + "UpdateParametersToMatchPlantType"
    checks["native_seed_is_synthetic_database_not_original_form"] = (seed["original_form_executed"] is False
        and seed["physical_devices_accessed"] is False and seed["toolkit_context"]["database_unit"] is True)
    if failed := [name for name, okay in checks.items() if not okay]:
        raise ValueError("GUI binding source differs: " + ", ".join(failed))
    if (sha(exe.read_bytes()), sha(map_path.read_bytes()), sha(seed_path.read_bytes())) != (EXE_SHA256, MAP_SHA256, sha(seed_raw)):
        raise ValueError("Evidence inputs changed during inspection")
    return {
        "format": "cbus-thermostat-quick-zone-gui-binding-static-v1",
        "original_exe_sha256": EXE_SHA256, "original_map_sha256": MAP_SHA256,
        "native_seed_sha256": sha(seed_raw), "original_executed": False, "initialized_form_reproduced": False,
        "full_gui_feedback_closed": False, "public_quick_zone_action_ready": False,
        "check_count": len(checks), "checks": checks, "method_count": len(methods),
        "prepare_site_count": sum(len(p["prepare_sites"]) for p in panels.values()), "panels": panels,
        "combo_dynamic_dispatch": {hex(key): {"address": hex(dynamic[key]), "symbol": walker.name(dynamic[key])}
                                   for key in (0xffb0, 0xffaf)},
        "methods": {name: {"address": hex(image.by_name[name]), "sha256": value[2]}
                    for name, value in sorted(methods.items())},
        "proved_conditional_behavior": [
            "Parent enable invokes UI, ZoneManagement, Plant and TempControl only; Plant's route does not call Vent fallback.",
            "TempControl parent enable calls min/max/min handlers; initialized min15<max32 with Guard unchecked bypasses their SetPosition/model writes.",
            "Initial Templates quick checkbox refresh skips model mask rebuilding under +0x29; it does not establish UsedZones=1.",
            "UpdateFlashZoneVariables would reset both UsedZones and InstalledZones, so inserting it changes the candidate premise.",
            "UI panel HookEvents subscribes InstalledZones only and does not call the base TUIService.HookEvents.",
            "Combo focus entry populates lists; all thirteen PrepareFlashComboBox value controllers use immediate Apply, so their ExitingControl skips Apply before rendering."],
        "open_boundaries": [
            "The existing synthetic core fixture's base UI service callback is not proof of the initialized programmable AdvancedUI graph.",
            "Registered Prepare sites are a source inventory; branch reachability, all controller activation and native widget state are not executed.",
            "A quick-zone click also changes focus; pending edits and controller dirty state require an explicit initialized-state proof.",
            "Native combo notifications and queued Plant 0x423 messages can invoke callbacks outside same-controller Apply locking.",
            "Controls.SetEnabled can dispatch CM_ENABLEDCHANGED/EnableWindow; this receipt does not emulate native control messages.",
            "Seven-panel initialization, outer click, project graph and PP save/reload have not been joined into one original run."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.exe, args.map, args.seed)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
