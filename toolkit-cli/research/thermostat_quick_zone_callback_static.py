"""Pin thermostat checkbox feedback barriers without claiming full GUI closure."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_toolkit_executable_surface import _resource_leaves, parse_binary_dfm  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402
from thermostat_settings_form_static import _fields  # noqa: E402
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402

CHECKBOX = "CIS_TFlashCheckBox.TFlashCheckBox."
CONTROLLER = "CIS_Handles.TFlashExpressionController."
TRACKED = "CIS_Handles.TFlashTrackedHandle."
TEMPLATES = "CIS_TcdThermostatTemplates.TcdThermostatTemplates."
PANELS = {"UI": (0x18, "chbZone1", "UIAllocatedZones.Zone1"),
          "Plant": (0x20, "chbPlantZone1", "InternalPlantZones.Zone1"),
          "TempControl": (0x28, "chbMeasuredZone1", "MeasuredZones.Zone1")}
METHODS = (
    *(CHECKBOX + n for n in ("Create", "ControllerValueChange", "ActiveStateChanged", "Change", "CMChanged")),
    "StdCtrls.TCustomCheckBox.SetChecked", "StdCtrls.TCustomCheckBox.SetState",
    "StdCtrls.TCustomCheckBox.Click", "CIS_FlashGUI.PrepareFlashCheckbox",
    *(CONTROLLER + n for n in ("DoFlashHandleChanged", "LockUpdate", "UnlockUpdate", "GetUpdateLocked",
                              "Apply", "Changed", "ExpressionElementChanged", "SetActive")),
    *("CIS_Handles.TFlash" + kind + "Controller.Apply" for kind in ("Boolean", "String", "Element")),
    "CIS_Handles.TFlashStringController.SetAsString",
    *(TRACKED + n for n in ("SetRootElement", "Update", "Changed", "DoRootElementChanged", "DoListChanged")),
    "CIS_Handles.TFlashExpression.RootElementChanged",
    "CIS_TFlashComboBox.TFlashComboBox.FlashHandleListChanged",
    "CIS_TFlashComboBox.TFlashComboBox.FlashHandleListRootChanged",
    "CIS_TFlashComboBox.TFlashComboBox.UpdateEnableState",
    "CIS_TFlashComboBox.TFlashComboBox.PopulateList",
    "CIS_TFlashComboBox.TFlashComboBox.DropDown",
    "CIS_TFlashComboBox.TFlashComboBox.DoMouseWheelDown",
    "CIS_TFlashComboBox.TFlashComboBox.DoMouseWheelUp",
    "CIS_TFlashComboBox.TFlashComboBox.KeyDown",
    "CIS_TFlashComboBox.TFlashComboBox.RenderDisplay",
    "CIS_TFlashComboBox.TFlashComboBox.DoIndexChange",
    "CIS_TfrmThermostatPlant.TfrmThermostatPlant.cmbInternalPlantTypeChange",
    "CIS_TfrmThermostatPlant.TfrmThermostatPlant.HandlePlantTypeChange",
    *("CIS_TcdThermostat" + panel + ".TcdThermostat" + panel + ".SetupFlashComponents" for panel in PANELS),
    TEMPLATES + "HandleUnitZoneChange", TEMPLATES + "UpdateQuickOptions",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _bindings(image, rows, form_offset, fields):
    """Track only the direct owner -> form -> published-component load pattern."""
    current, component, expression = None, None, None
    prepares, callbacks = {}, []
    for address, mnemonic, operand, note in rows:
        if mnemonic == "mov" and operand.startswith("eax, "):
            if operand == "eax, dword ptr [ebp - 4]":
                current, component = "owner", None
            else:
                match = re.fullmatch(r"eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]", operand)
                offset = int(match[1], 16) if match else None
                if current == "owner" and offset == form_offset:
                    current = "form"
                elif current == "form" and offset in fields:
                    current, component = "component", fields[offset]
                else:
                    current, component = None, None
        if mnemonic == "mov" and re.fullmatch(r"ecx, 0x[0-9a-f]+", operand):
            expression = image.literal(int(operand.split(", ")[1], 16))
        if mnemonic == "mov" and current == "component" and note:
            match = re.fullmatch(r"dword ptr \[eax \+ (0x[0-9a-f]+)\], 0x[0-9a-f]+", operand)
            if match:
                callbacks.append({"component": component, "slot": match[1], "target": note, "at": hex(address)})
        if mnemonic == "call":
            if note == "CIS_FlashGUI.PrepareFlashCheckbox" and current == "component":
                prepares[component] = {"expression": expression, "at": hex(address)}
            current, component, expression = None, None, None
    return prepares, callbacks


def inspect(exe: Path, map_path: Path):
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if sha(exe_raw) != EXE_SHA256 or sha(map_raw) != MAP_SHA256:
        raise ValueError("Pinned Toolkit source mismatch")
    walker = _Walker(_Image(exe_raw, map_raw))
    image = walker.image
    methods = {name: walker.listing(name) for name in METHODS}

    def at(name, address, mnemonic, operand):
        return any(a == address and mn == mnemonic and op == operand
                   for a, mn, op, _n in methods[name][0])

    def calls(name):
        return [n for _a, m, _o, n in methods[name][0] if m == "call" and n]

    dfms = {}
    wanted = {"TFRMTHERMOSTAT" + p.upper() for p in PANELS}
    for resource_type in image.pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if resource_type.struct.Id != 10:
            continue
        for entry in resource_type.directory.entries:
            if str(entry.name) not in wanted:
                continue
            leaves = _resource_leaves(entry)
            if len(leaves) != 1:
                raise ValueError("Unexpected thermostat DFM resource multiplicity")
            leaf = leaves[0]
            raw = image.pe.get_data(leaf.data.struct.OffsetToData, leaf.data.struct.Size)
            parsed = parse_binary_dfm(raw)
            dfms[str(entry.name)] = {"sha256": sha(raw), "event_bindings": parsed["event_bindings"],
                                     "components": parsed["components"]}
    checks = {
        "checkbox_update_disables_clicks": at(CHECKBOX + "ControllerValueChange", 0xae8163,
                                              "mov", "byte ptr [eax + 0x270], 1"),
        "checkbox_update_restores_click_flag": at(CHECKBOX + "ControllerValueChange", 0xae81d2,
                                                  "mov", "byte ptr [eax + 0x270], dl"),
        "checkbox_setstate_respects_click_flag": at("StdCtrls.TCustomCheckBox.SetState", 0x68a085,
                                                    "cmp", "byte ptr [ebx + 0x270], 0")
            and at("StdCtrls.TCustomCheckBox.SetState", 0x68a08c, "jne", "0x68a099"),
        "checkbox_optional_value_callback_retained": at(CHECKBOX + "ControllerValueChange", 0xae81b9,
                                                        "call", "dword ptr [ebx + 0x288]"),
        "refresh_locks_before_callbacks": at(CONTROLLER + "DoFlashHandleChanged", 0x84d8f7,
                                            "call", "0x84dd64"),
        "refresh_unlocks_after_callbacks": at(CONTROLLER + "DoFlashHandleChanged", 0x84da34,
                                             "call", "0x84e008"),
        "lock_is_nesting_counter": at(CONTROLLER + "LockUpdate", 0x84dd6e,
                                      "inc", "dword ptr [eax + 0x54]"),
        "update_lock_reads_counter": at(CONTROLLER + "GetUpdateLocked", 0x84dd28,
                                        "cmp", "dword ptr [eax + 0x54], 0"),
        "base_apply_clears_pending_dirty": at(CONTROLLER + "Apply", 0x84d7da,
                                             "mov", "byte ptr [eax + 5], 0"),
        "same_tracked_root_returns": at(TRACKED + "SetRootElement", 0x84ed2e,
                                         "cmp", "eax, dword ptr [ebp - 8]")
            and at(TRACKED + "SetRootElement", 0x84ed31, "je", "0x84ed83"),
        "same_current_leaf_skips_value_event": at(TRACKED + "Update", 0x84eede,
                                                  "cmp", "eax, dword ptr [edx + 0x3c]")
            and at(TRACKED + "Update", 0x84eee1, "je", "0x84ef39"),
        "enum_collection_root_still_emits_list_event": TRACKED + "DoListChanged"
            in calls(TRACKED + "DoRootElementChanged"),
        "combo_list_change_only_updates_enabled": calls("CIS_TFlashComboBox.TFlashComboBox.FlashHandleListChanged")
            == ["CIS_TFlashComboBox.TFlashComboBox.UpdateEnableState"],
        "combo_list_root_change_only_updates_enabled": calls("CIS_TFlashComboBox.TFlashComboBox.FlashHandleListRootChanged")
            == ["CIS_TFlashComboBox.TFlashComboBox.UpdateEnableState"],
        "combo_list_change_marks_deferred_dirty": at("CIS_TFlashComboBox.TFlashComboBox.FlashHandleListChanged",
                                                     0xae61af, "mov", "byte ptr [eax + 0x320], 1"),
        "combo_list_root_change_marks_deferred_dirty": at("CIS_TFlashComboBox.TFlashComboBox.FlashHandleListRootChanged",
                                                          0xae61d3, "mov", "byte ptr [eax + 0x320], 1"),
        "combo_enabled_update_only_reads_acceptance": calls("CIS_TFlashComboBox.TFlashComboBox.UpdateEnableState")
            == [CONTROLLER + "CanAcceptValue"],
        "plant_type_form_callback_posts_message": "Windows.PostMessage"
            in calls("CIS_TfrmThermostatPlant.TfrmThermostatPlant.cmbInternalPlantTypeChange"),
        "plant_type_form_message_has_external_callback": at(
            "CIS_TfrmThermostatPlant.TfrmThermostatPlant.HandlePlantTypeChange", 0x11221ee,
            "call", "dword ptr [ebx + 0x460]"),
        "quick_refresh_guard_still_present": at(TEMPLATES + "UpdateQuickOptions", 0x111e986,
                                                "cmp", "byte ptr [eax + 0x28], 0"),
    }
    for kind, test_address, skip_address, skip_target in (
            ("Boolean", 0x84f107, 0x84f10e, "0x84f176"),
            ("String", 0x84f323, 0x84f32a, "0x84f37b"),
            ("Element", 0x84f4af, 0x84f4b6, "0x84f4f5")):
        name = "CIS_Handles.TFlash" + kind + "Controller.Apply"
        checks[kind.lower() + "_apply_refuses_locked_writeback"] = (
            at(name, test_address, "call", "0x84dd1c") and at(name, skip_address, "jne", skip_target)
            and CONTROLLER + "Apply" in calls(name))
    vmt = image.by_name["CIS_TFlashCheckBox..TFlashCheckBox"] + 0x58
    checks["checkbox_checked_setter_vmt"] = walker.name(walker.dword(vmt + 0xf0)) == "StdCtrls.TCustomCheckBox.SetChecked"
    combo_vmt = image.by_name["CIS_TFlashComboBox..TFlashComboBox"] + 0x58
    checks["combo_enabled_setter_vmt"] = walker.name(walker.dword(combo_vmt + 0x74)) == "Controls.TControl.SetEnabled"
    bindings = {}
    for panel, (offset, checkbox, expression) in PANELS.items():
        name = "CIS_TcdThermostat" + panel + ".TcdThermostat" + panel + ".SetupFlashComponents"
        fields = _fields(walker, "CIS_TfrmThermostat" + panel + "..TfrmThermostat" + panel)
        prepares, callbacks = _bindings(image, methods[name][0], offset, fields)
        bindings[panel] = {"checkbox_bindings": prepares, "component_callback_assignments": callbacks}
        dfm = dfms["TFRMTHERMOSTAT" + panel.upper()]
        checks[panel + "_zone1_expression"] = prepares[checkbox]["expression"] == expression
        checks[panel + "_zone1_checkbox_class"] = any(c["name"] == checkbox and c["class"] == "TFlashCheckBox"
                                                     for c in dfm["components"])
        checks[panel + "_zone1_has_no_dfm_event"] = not any(e["component_path"].endswith("/" + checkbox)
                                                           for e in dfm["event_bindings"])
        checks[panel + "_zone1_has_no_runtime_value_callback"] = not any(
            c["component"] == checkbox and c["slot"] == "0x288" for c in callbacks)
        del dfm["components"]
    failures = [name for name, okay in checks.items() if not okay]
    if failures:
        raise ValueError("Callback barrier source changed: " + ", ".join(failures))
    if sha(exe.read_bytes()) != EXE_SHA256 or sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError("Original Toolkit sources changed during inspection")
    return {
        "format": "cbus-thermostat-quick-zone-callback-static-v1",
        "original_exe_sha256": EXE_SHA256, "original_map_sha256": MAP_SHA256,
        "original_executed": False, "full_gui_feedback_closed": False,
        "public_quick_zone_action_ready": False,
        "method_count": len(methods), "check_count": len(checks), "checks": checks,
        "method_spans": {name: {"start": hex(image.by_name[name]), "sha256": value[2],
                               "bytes": next(a for a in image.starts if a > image.by_name[name]) - image.by_name[name]}
                         for name, value in methods.items()},
        "dfm_resources": dfms, "panel_setup_bindings": bindings,
        "proven_scope": ["The three changed zone1 checkbox bindings have no optional value callback in DFM/setup.",
                         "Their programmatic checked-state update suppresses Click and ordinary model writeback.",
                         "Same-controller Boolean/String/Element Apply refuses writes under notification lock and clears dirty state.",
                         "Stable scalar leaf handles skip value events when the current element pointer is unchanged.",
                         "FlashComboBox list callbacks only mark deferred dirty state and update Enabled; they do not PopulateList."],
        "open_boundary": ["Enum/collection root refresh can still issue DoListChanged even for an unchanged current pointer.",
                          "Further combo input/list population, native notification and posted parent message ordering remain outside this proof.",
                          "Direct model setters in custom callbacks bypass same-controller Apply; the lock is not a global model lock.",
                          "Initial project graph, complete initialized form and native GUI action/save/reload are not reproduced."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
