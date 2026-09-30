"""Pin additional classic report profiles and compare AUX source-table results.

Reads only the pinned EXE/MAP. It does not execute vendor code or access a
project, network, unit specification, or physical device. Method receipts and
UI labels contain no proprietary instruction bytes or site data.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path

from project_documentor_static import EXE_SHA256, MAP_SHA256, UNIT_FACTORY, _Toolkit
from project_documentor_classic_key_static import BISTABLE_GUID, DOCUMENT, _interface_ancestry
from project_documentor_classic_key_macro_original import SourceMacroOracle, STORED_PAIRS
from key_preset_families import Image, agent_registrations, key_count, subsets
from cbus_toolkit.project_documentation_classic_profiles import CLASSIC_PROFILE_COUNTS, AUX_TYPES, auxiliary_key_macro

CORE = "CIS_TCoreKeyInputUnit.TCoreKeyInputUnit."
AUX = "CIS_TCBusKeyAuxInputUnit.TCBusKeyAuxInputUnit."
KEY = "CIS_TInputKey.TInputKey."
MACRO = "CIS_TKeyMacroFunction.TKeyMacroFunction."
BCNC_SAVE = "CIS_TBCNC4CGateAgent.TBCNC4CGateAgent.BeforeSaveProgrammingInformation"
CLASSIC_LOAD = "CIS_TKeyInputCGateAgent.TCBusKeyInputCGateAgent.AfterLoadProgrammingInformation"
METHODS = (
    DOCUMENT, CORE + "InternalCreate", CORE + "MaximumVirtualKeyCount",
    AUX + "InternalCreate", AUX + "RefreshMacroFunctionOverrides", AUX + "MacroFunctionSubsetName",
    KEY + "SetMacroFunctionAUXOverride", MACRO + "ReconcileTemplateAndGroup", CLASSIC_LOAD,
    "CIS_TBCNC.TBCNC.InternalCreate", BCNC_SAVE,
)


def _aux_compare(oracle, aux_subsets):
    """Independent ordered source table -> override -> alias -> subset model."""
    checked, mismatches = 0, []
    for application in (56, 202, 255):
        allowed = aux_subsets.get(str(application), aux_subsets["0"])
        for stored1, stored2 in STORED_PAIRS:
            for commands in itertools.product(range(16), repeat=4):
                kind = oracle.first_match.get(commands, 26)
                if kind in (7, 27):
                    kind = 28
                if kind in (31, 33):
                    kind = 26
                if application != 202 and stored1 is not None and stored2 is not None:
                    if kind == 14:
                        kind = {249: 17, 252: 18, 255: 20}.get(stored1, kind)
                    elif kind == 15:
                        kind = {2: 19, 5: 22}.get(stored2, kind)
                if kind not in allowed:
                    kind = 26
                expected = kind, oracle.labels[kind]
                actual = auxiliary_key_macro(commands, application, stored1, stored2)
                checked += 1
                if expected != actual and len(mismatches) < 10:
                    mismatches.append({"commands": commands, "application": application,
                                       "stored": [stored1, stored2], "expected": expected, "actual": actual})
    return {"source": "ordered original macro/group/subset registration tables with original AUX override",
            "checked": checked, "equal": not mismatches, "mismatches": mismatches}


def inspect(exe: Path, map_file: Path) -> dict:
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError("Pinned original EXE/MAP hash mismatch")
    image, tables = _Toolkit(raw, symbols), Image(exe, map_file)
    oracle = SourceMacroOracle(exe, map_file)
    methods = {name: image.method(name) for name in METHODS}
    agents, families = agent_registrations(tables), subsets(tables)
    registrations, checks = [], {}
    for typ, symbol, minimum, maximum in image.registrations(UNIT_FACTORY)[0]:
        if typ not in CLASSIC_PROFILE_COUNTS:
            continue
        slots = {hex(offset): image.slot(symbol, offset) for offset in
                 (0x128, 0x12C, 0x130, 0x16C, 0x190, 0x194, 0x1A8, 0x1C4, 0x1CC)}
        for name in slots.values():
            methods[name] = image.method(name)
        ancestry = _interface_ancestry(image, symbol)
        agent = agents[symbol][0]
        load = image.slot(agent, 0xA4)
        count = key_count(tables, symbol, 0x190)[1]
        brightness = methods[slots["0x1a8"]]["instructions"]
        brightness_enabled = any(op == "mov" and arg == "byte ptr [ebp - 5], 1" for _, op, arg in brightness)
        brightness_disabled = any(op == "mov" and arg == "byte ptr [ebp - 5], 0" for _, op, arg in brightness)
        checks[typ + ":exact_registration"] = (minimum, maximum) == ("0", "9")
        checks[typ + ":physical_keys"] = count == CLASSIC_PROFILE_COUNTS[typ]
        checks[typ + ":no_bistable"] = not any(BISTABLE_GUID in row["interfaces"] for row in ancestry)
        checks[typ + ":classic_loader"] = load == CLASSIC_LOAD
        checks[typ + ":four_blocks"] = key_count(tables, symbol, 0x16C)[1] == 4
        checks[typ + ":virtual_uses_physical"] = key_count(tables, symbol, 0x194)[1] == 0xFFFFFFFF
        checks[typ + ":subset"] = methods[slots["0x1c4"]]["literals"] == ["AUX" if typ in AUX_TYPES else "KEY"]
        checks[typ + ":group_usage_methods"] = [slots[hex(offset)].rsplit(".", 2)[-2]
                                                 for offset in (0x128, 0x12C, 0x130)] == [
                                                     "TCoreKeyInputUnit", "TCBUSUnit", "TCoreKeyInputUnit"]
        checks[typ + ":brightness_constant"] = brightness_enabled != brightness_disabled
        checks[typ + ":override"] = slots["0x1cc"] == (AUX + "RefreshMacroFunctionOverrides" if typ in AUX_TYPES
                                                        else CORE + "RefreshMacroFunctionOverrides")
        registrations.append({"unit_type": typ, "class": symbol, "firmware": [minimum, maximum],
                              "agent": agent, "after_load": load, "slots": slots,
                              "indicator_brightness_enabled": brightness_enabled,
                              "interface_ancestry": ancestry})

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in methods[name]["instructions"]

    def call(name, address, target):
        return has(name, address, "call", hex(image.by_name[target]))

    reconcile = MACRO + "ReconcileTemplateAndGroup"
    checks.update({
        "registered_types_complete": {row["unit_type"] for row in registrations} == set(CLASSIC_PROFILE_COUNTS),
        "fresh_key_construction_calls_virtual_override": has(CORE + "InternalCreate", 0xC9DE2F, "call", "dword ptr [edx + 0x1cc]"),
        "aux_reconcile_checks_override_flag": has(reconcile, 0xC97A5F, "cmp", "byte ptr [eax + 0x8e], 0"),
        "aux_reconcile_accepts_bell_press": has(reconcile, 0xC97A7B, "mov", "dl, 7"),
        "aux_reconcile_selects_type28_group58": has(reconcile, 0xC97A8E, "mov", "dl, 0x1c") and
                                               has(reconcile, 0xC97AA6, "mov", "dl, 0x3a"),
        "aux_groups_preserve_microfunctions": oracle.groups[41] == oracle.groups[57] == oracle.groups[58] == [13, 15, 0, 15],
        "aux_subsets_only_replace_bell_press": all(set(families["AUX"][app]) ==
                                                   ({28 if kind == 7 else kind for kind in kinds})
                                                   for app, kinds in families["KEY"].items()),
        "aux_label": oracle.labels[28] == "Aux On/Off",
        "bcnc_constructor_delegates_classic": call("CIS_TBCNC.TBCNC.InternalCreate", 0xFB4122,
                                                  "CIS_TCBusKeyInputUnit.TCBusKeyInputUnit.InternalCreate"),
        "bcnc_defaults_are_before_save": call(BCNC_SAVE, 0x129A5A3, "CIS_TBCNC.TBCNC4.ApplyMicroFunctionDefaults") and
                                          call(BCNC_SAVE, 0x129A5B0, "CIS_TBCNC.TBCNC4.ApplyLearnModeDefaults"),
        "bcnc_micro_defaults_only_direct_call_is_before_save": list(tables.calls("CIS_TBCNC.TBCNC4.ApplyMicroFunctionDefaults")) == [0x129A5A3],
    })
    action = image.slot("CIS_TClassicKeyInputDocumentor..TClassicKeyInputDocumentor", 0x80)
    checks["classic_action_selector_inherited_by_profiles"] = action == "CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.ActionSelectorUse"
    comparison = _aux_compare(oracle, families["AUX"])
    checks["aux_exhaustive_source_table_comparison"] = comparison["equal"]
    failed = [name for name, good in checks.items() if not good]
    if failed:
        raise ValueError("Original classic profile evidence changed: " + ", ".join(failed))
    return {"format": "cbus-project-documentor-classic-profiles-static-v1", "exe_sha256": EXE_SHA256,
            "map_sha256": MAP_SHA256, "original_executed": False,
            "original_generated_page_comparison": "not_obtained", "classic_profile_counts": CLASSIC_PROFILE_COUNTS,
            "registrations": registrations, "checks": checks, "aux_macro_comparison": comparison,
            "methods": {name: {"start": hex(row["start"]), "end": hex(row["end"]), "sha256": row["sha256"],
                               "literals": row["literals"]} for name, row in methods.items()},
            "boundary": "Fresh complete PP snapshots only; BCNC save normalization is not run. NeoProClassic KEYC/CIR profiles remain unsupported."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", dest="map_file", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = inspect(args.exe, args.map_file)
    text = json.dumps(receipt, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
