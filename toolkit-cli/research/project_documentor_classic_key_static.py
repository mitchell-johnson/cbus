"""Verify source-only classic-key documentor timing, PP and object-model rules.

Reads the pinned original EXE/MAP without executing vendor code or accessing a
project, C-Gate, or hardware. The receipt records identifiers, UI literals and
method hashes, never instruction bytes. Original generated-page acceptance is
separate and has not been obtained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import uuid

from project_documentor_static import EXE_SHA256, MAP_SHA256, UNIT_FACTORY, _Toolkit
from project_documentor_classic_key_macro_original import SourceMacroOracle

DOCUMENT = "CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.DocumentHTML"
CORE_AGENT = "CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent."
KEY_AGENT = "CIS_TKeyInputCGateAgent."
CUSTOM_UNIT = "CIS_TCustomKeyInputUnit.TCustomKeyInputUnit."
CORE_UNIT = "CIS_TCoreKeyInputUnit.TCoreKeyInputUnit."
ENUM = "CIS_TEnumeratedTypeAttribute."
REGISTER = "CIS_TCommonCBus.RegisterEnumerations"
RAMP_CONVERT = "CIS_TCommonCBus.IntegerToCBusRampRate"
FIRST_BLOCK = "CIS_TInputKey.TInputBlockCollection.ItemByGroup"
BLOCK = "CIS_TInputKey.TInputBlock."
INPUT_KEY = "CIS_TInputKey.TInputKey."
BLOCK_VALUES = "CIS_TCoreKeyInputCGateAgent.GetBlockValues"
EXPIRY_OPTIONS = "CIS_TKeyMicroFunction.TKeyMicroFunctionFactory.GetKeyMicroFunctionsForTimerExpiry"
KEY_COUNTS = {"KEY1": 1, "KEY2": 2, "KEY4": 4}
BISTABLE_GUID = "902a2db4-674b-460f-b9e7-a69f18a2a117"
TIMING_DESCRIPTIONS = tuple(f"{16 * n} ms" for n in range(64))
RAMP_DESCRIPTIONS = (
    "Instant", "4 secs", "8 secs", "12 secs", "20 secs", "30 secs", "40 secs", "60 secs",
    "90 secs", "120 secs", "180 secs", "300 secs", "420 secs", "600 secs", "900 secs", "1020 secs",
)
METHODS = (
    DOCUMENT, CORE_AGENT + "InternalCreate", CORE_AGENT + "AfterLoadProgrammingInformation",
    CORE_AGENT + "GetKeyBlocks", "CIS_TCoreKeyInputCGateAgent.GetBlockValues",
    KEY_AGENT + "TCBusKeyInputCGateAgent.AfterLoadProgrammingInformation",
    KEY_AGENT + "GetKeyValues", KEY_AGENT + "GetIndicatorBlocks",
    CUSTOM_UNIT + "InternalCreate", CUSTOM_UNIT + "GetDebounceTime", CUSTOM_UNIT + "GetLongPressTime",
    CUSTOM_UNIT + "GetRampRate1", CUSTOM_UNIT + "GetRampRate2",
    CUSTOM_UNIT + "SetRampRate1", CUSTOM_UNIT + "SetRampRate2",
    CORE_UNIT + "MaximumVirtualKeyCount", CORE_UNIT + "GetMaximumVirtualKeyCount",
    "CIS_TCBusKeyInputUnit.TCBusKeyInputUnit.MaximumBlockCount",
    *(f"CIS_TKey{n}.TKey{n}.MaximumKeyCount" for n in (1, 2, 4)),
    REGISTER, RAMP_CONVERT, ENUM + "RegisterEnumeratedValueDescriptions",
    ENUM + "GetDescriptionFromEnumeratedValueOrdinalValue",
    ENUM + "TEnumeratedValues.IntegerToDescriptiveText",
    ENUM + "TEnumeratedTypeAttribute.SetAsInteger", FIRST_BLOCK,
    "CIS_CBus.LevelToPercent", "CIS_Dates.CBusTimeToStr", "System.TObject.GetInterfaceEntry",
    CORE_AGENT + "LoadTimerHighAndLowBytes", CORE_AGENT + "LoadTimerExpiryCommand",
    CORE_AGENT + "GetBlockGroup", CORE_AGENT + "CreateEEPROMLevelAttributes",
    *(CORE_AGENT + "CreateAttribute" + suffix for suffix in
      ("TimerHighByte", "TimerLowByte", "TimerExpiryCommand")),
    BLOCK + "SetTimer", BLOCK + "GetTimer", EXPIRY_OPTIONS, "CIS_Dates.DecodeCBusTime",
    INPUT_KEY + "GetPrimaryBlock", INPUT_KEY + "GetApplicationForKey",
    INPUT_KEY + "RefreshKeyApplicationFromKeySecondary", INPUT_KEY + "RefreshKeySecondaryFromBlockSecondary",
    INPUT_KEY + "InternalCreate", CORE_UNIT + "InternalCreate", CORE_UNIT + "InputKeysChanged",
    CORE_UNIT + "InputKeyBlocksChanged", CORE_UNIT + "RefreshKeyBlockOverrides",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _interface_ancestry(image: _Toolkit, symbol: str) -> list[dict]:
    """Follow the original GetInterfaceEntry VMT and 28-byte entry layout."""
    result, seen, vmt = [], set(), image.vmt(symbol)
    while vmt:
        if vmt in seen:
            raise ValueError("Cyclic original class ancestry")
        seen.add(vmt)
        table = image.dword(vmt - 0x54)
        interfaces = []
        table_hash = None
        if table:
            count = image.dword(table)
            if count > 256:
                raise ValueError("Unbounded original interface table")
            raw = image.pe.get_data(table - image.base, 4 + 28 * count)
            table_hash = _sha(raw)
            interfaces = [str(uuid.UUID(bytes_le=raw[4 + 28 * n:20 + 28 * n])) for n in range(count)]
        result.append({"class": image.class_name(vmt), "vmt": hex(vmt),
                       "interface_table": hex(table), "interface_table_sha256": table_hash,
                       "interfaces": interfaces})
        parent = image.dword(vmt - 0x30)
        vmt = image.dword(parent) if parent else 0
    return result


def _enum_type(image: _Toolkit, pointer: int) -> dict:
    """Read Delphi tkEnumeration RTTI bounds and ordinal names."""
    start = image.dword(pointer)
    data = image.pe.get_data(start - image.base, 4096)
    if data[0] != 3:
        raise ValueError("Expected original enumeration RTTI")
    size = data[1]
    name = data[2:2 + size].decode("ascii")
    offset = 2 + size
    minimum, maximum = struct.unpack_from("<ii", data, offset + 1)
    if not 0 <= maximum - minimum <= 255:
        raise ValueError("Unbounded original enumeration RTTI")
    offset += 13
    names = []
    for _ in range(minimum, maximum + 1):
        size = data[offset]
        names.append(data[offset + 1:offset + 1 + size].decode("ascii"))
        offset += size + 1
    return {"name": name, "pointer": hex(pointer), "type_info": hex(start),
            "minimum": minimum, "maximum": maximum, "ordinal_names": names,
            "rtti_prefix_sha256": _sha(data[:offset])}


def inspect(exe: Path, map_file: Path) -> dict:
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if _sha(raw) != EXE_SHA256 or _sha(symbols) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(raw, symbols)
    methods = {name: image.method(name) for name in METHODS}
    macro = SourceMacroOracle(exe, map_file)
    methods.update(macro.methods)

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in methods[name]["instructions"]

    def call(name, address, target):
        return has(name, address, "call", hex(image.by_name[target]))

    def constant_result(name):
        matches = [int(op.rsplit(", ", 1)[1], 0) for _, mnemonic, op in methods[name]["instructions"]
                   if mnemonic == "mov" and re.fullmatch(r"dword ptr \[ebp - 8\], (0x[0-9a-f]+|[0-9]+)", op)]
        if len(matches) != 1:
            raise ValueError("Cannot recover original result: " + name)
        return matches[0]

    registrations, _ = image.registrations(UNIT_FACTORY)
    key_registrations = [row for row in registrations if row[0] in KEY_COUNTS]
    ancestry = {row[0]: _interface_ancestry(image, row[1]) for row in key_registrations}
    timing_type = _enum_type(image, 0x8545DC)
    ramp_type = _enum_type(image, 0x8544E4)
    counts = {f"KEY{n}": constant_result(f"CIS_TKey{n}.TKey{n}.MaximumKeyCount") for n in (1, 2, 4)}
    markup = methods[DOCUMENT]["literal_at"]
    checks = {
        "unit_registrations": key_registrations == [
            (f"KEY{n}", f"CIS_TKey{n}..TKey{n}", "0", "9") for n in (1, 2, 4)],
        "key_counts": counts == KEY_COUNTS,
        "four_blocks": constant_result("CIS_TCBusKeyInputUnit.TCBusKeyInputUnit.MaximumBlockCount") == 4,
        "virtual_key_count_falls_back_to_physical": (
            constant_result(CORE_UNIT + "GetMaximumVirtualKeyCount") == 0xFFFFFFFF
            and has(CORE_UNIT + "MaximumVirtualKeyCount", 0xC9E1EB, "cmp", "dword ptr [ebp - 0xc], -1")
            and has(CORE_UNIT + "MaximumVirtualKeyCount", 0xC9E1F6, "call", "dword ptr [edx + 0x190]")),
        "bistable_guid": str(uuid.UUID(bytes_le=image.pe.get_data(0xCA7444 - image.base, 16))) == BISTABLE_GUID,
        "no_bistable_for_admitted_keys": set(ancestry) == set(KEY_COUNTS) and all(
            BISTABLE_GUID not in row["interfaces"] for rows in ancestry.values() for row in rows),
        "interface_table_layout": (
            has("System.TObject.GetInterfaceEntry", 0x60639C, "mov", "eax, dword ptr [ebx - 0x54]")
            and has("System.TObject.GetInterfaceEntry", 0x6063C6, "add", "eax, 0x1c")
            and has("System.TObject.GetInterfaceEntry", 0x6063CC, "mov", "ebx, dword ptr [ebx - 0x30]")),
        "timing_type_bounds": timing_type["name"] == "TCBusMSecSetting"
        and (timing_type["minimum"], timing_type["maximum"]) == (0, 63),
        "ramp_type_bounds": ramp_type["name"] == "TCBusRampRate"
        and (ramp_type["minimum"], ramp_type["maximum"]) == (0, 15),
        "timing_descriptions": tuple(methods[REGISTER]["literals"][:64]) == TIMING_DESCRIPTIONS,
        "ramp_descriptions": tuple(methods[REGISTER]["literals"][81:97]) == RAMP_DESCRIPTIONS,
        "timing_registration": (
            has(REGISTER, 0xF2428B, "mov", "ecx, 0x3f")
            and has(REGISTER, 0xF24290, "mov", "eax, dword ptr [0x8545dc]")
            and call(REGISTER, 0xF24295, ENUM + "RegisterEnumeratedValueDescriptions")),
        "ramp_registration": (
            has(REGISTER, 0xF24420, "mov", "ecx, 0xf")
            and has(REGISTER, 0xF24425, "mov", "eax, dword ptr [0x8544e4]")
            and call(REGISTER, 0xF2442A, ENUM + "RegisterEnumeratedValueDescriptions")),
        "descriptions_registered_in_ordinal_order": (
            has(ENUM + "RegisterEnumeratedValueDescriptions", 0x847F4A, "mov", "dword ptr [ebp - 0x10], 0")
            and has(ENUM + "RegisterEnumeratedValueDescriptions", 0x847F65, "mov", "edx, dword ptr [edx + ecx*4]")
            and has(ENUM + "RegisterEnumeratedValueDescriptions", 0x847F6D, "inc", "dword ptr [ebp - 0x10]")),
        "ramp_ordinal_and_255_conversion": (
            has(RAMP_CONVERT, 0xF2513F, "cmp", "dword ptr [ebp - 4], 0xf")
            and has(RAMP_CONVERT, 0xF25145, "mov", "al, byte ptr [ebp - 4]")
            and has(RAMP_CONVERT, 0xF2514D, "cmp", "dword ptr [ebp - 4], 0xff")
            and has(RAMP_CONVERT, 0xF25156, "mov", "byte ptr [ebp - 5], 1")
            and has(RAMP_CONVERT, 0xF2515C, "mov", "byte ptr [ebp - 5], 0xf")),
        "key_loader_calls_core": call(KEY_AGENT + "TCBusKeyInputCGateAgent.AfterLoadProgrammingInformation",
                                      0x12162EA, CORE_AGENT + "AfterLoadProgrammingInformation"),
        "document_calls_base_first": call(DOCUMENT, 0xCA6644,
                                          "CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML"),
        "timing_rows_order": [markup.get(address) for address in (0xCA668F, 0xCA66CD, 0xCA670B, 0xCA6749)] == [
            "<tr><th>Debounce</th><td>", "<tr><th>Long Press</th><td>",
            "<tr><th>Ramp 1</th><td>", "<tr><th>Ramp 2</th><td>"],
        "timing_followed_by_key_table": [markup.get(address) for address in
                                        (0xCA6787, 0xCA6794, 0xCA67A1, 0xCA67B1)] == [
                                            "</table>", "<br/>", '<table border="1">', "<tr><th>Key</th>"],
        "key_columns_order": [markup.get(address) for address in (0xCA67E6, 0xCA67F3, 0xCA6800)] == [
            "<th>Macro Function</th>", "<th>Micro Functions</th>", "<th>Controls</th></tr>"],
        "advanced_microfunction_table_only": has(DOCUMENT, 0xCA6AF4, "sub", "al, 0x1a"),
        "unused_function_controls_blank": has(DOCUMENT, 0xCA6C46, "sub", "al, 0x10"),
        "controls_exclude_group_255": call(DOCUMENT, 0xCA69A9, "CIS_TCommonCBus.TCBusGroup.IsUnused"),
        "controls_preserve_duplicate_groups": call(DOCUMENT, 0xCA69DB, "Classes.TList.Add"),
        "first_matching_block_identity": (
            has(FIRST_BLOCK, 0xD104A3, "cmp", "eax, dword ptr [ebp - 8]")
            and has(FIRST_BLOCK, 0xD104B6, "jmp", "0xd104c0")),
        "presets_use_first_block": all(call(DOCUMENT, address, FIRST_BLOCK) for address in
                                       (0xCA6ED6, 0xCA6F10, 0xCA6F4E, 0xCA6F9B, 0xCA700E,
                                        0xCA7048, 0xCA7086, 0xCA70D3, 0xCA714C, 0xCA718F)),
        "preset_timer_column_ordinals": [
            next(op for address, mnemonic, op in methods[DOCUMENT]["instructions"] if address == value)
            for value in (0xCA6D78, 0xCA6DB4, 0xCA6DF0)] == ["dl, 0xc", "dl, 6", "dl, 7"],
        "macro_refresh_uses_source_filter_zero": (
            has(KEY_AGENT + "GetKeyValues", 0x1215F89, "xor", "edx, edx")
            and call(KEY_AGENT + "GetKeyValues", 0x1215F8E, INPUT_KEY + "MacroFunctionRefresh")),
        "macro_primary_block_and_application_guard": (
            call(INPUT_KEY + "IdenticalMacroFunctionRefresh", 0xD10B2A, INPUT_KEY + "GetPrimaryBlock")
            and call(INPUT_KEY + "IdenticalMacroFunctionRefresh", 0xD10B3A, INPUT_KEY + "GetApplicationForKey")
            and has(INPUT_KEY + "IdenticalMacroFunctionRefresh", 0xD10B44, "cmp", "eax, 0xca")),
        "macro_registered_labels": (macro.labels[12], macro.labels[13], macro.labels[26])
        == ("Preset 1", "Preset 2", "<Custom>"),
        "macro_key_application_subsets": macro.subsets == {
            "0": [16, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17, 18, 19, 20, 21, 22, 26],
            "202": [16, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21, 22, 26],
            "255": [16]},
        "timer_high_low_little_endian_word": (
            has(CORE_AGENT + "LoadTimerHighAndLowBytes", 0xCC7DBE, "mov", "eax, dword ptr [eax + 0x148]")
            and has(CORE_AGENT + "LoadTimerHighAndLowBytes", 0xCC7DE6, "mov", "byte ptr [ebp - 9], al")
            and has(CORE_AGENT + "LoadTimerHighAndLowBytes", 0xCC7DEF, "mov", "eax, dword ptr [eax + 0x14c]")
            and has(CORE_AGENT + "LoadTimerHighAndLowBytes", 0xCC7E17, "mov", "byte ptr [ebp - 0xa], al")
            and has(CORE_AGENT + "LoadTimerHighAndLowBytes", 0xCC7E5B, "mov", "ax, word ptr [ebp - 0xa]")),
        "timer_loaded_without_scaling": (
            call(BLOCK_VALUES, 0xCC82D5, CORE_AGENT + "LoadTimerHighAndLowBytes")
            and has(BLOCK_VALUES, 0xCC82DA, "mov", "edx, eax")
            and call(BLOCK_VALUES, 0xCC82DF, BLOCK + "SetTimer")),
        "timer_decoded_as_unsigned_seconds": (
            has("CIS_Dates.DecodeCBusTime", 0xC0D695, "movzx", "eax, word ptr [ebp - 0x10]")
            and has("CIS_Dates.DecodeCBusTime", 0xC0D699, "mov", "ecx, 0xe10")
            and has("CIS_Dates.DecodeCBusTime", 0xC0D6A0, "div", "ecx")
            and has("CIS_Dates.DecodeCBusTime", 0xC0D6B7, "mov", "ecx, 0x3c")
            and has("CIS_Dates.DecodeCBusTime", 0xC0D6BE, "div", "ecx")),
        "timer_expiry_allowed_ordinals": (
            has(EXPIRY_OPTIONS, 0xC8FDBB, "xor", "edx, edx")
            and all(has(EXPIRY_OPTIONS, address, "mov", operand) for address, operand in (
                (0xC8FDDE, "dl, 0xf"), (0xC8FE01, "dl, 4"), (0xC8FE24, "dl, 9"),
                (0xC8FE47, "dl, 0xc"), (0xC8FE6A, "dl, 6"), (0xC8FE8D, "dl, 0xa")))),
        "timer_expiry_other_ordinals_normalized_to_off": (
            call(BLOCK_VALUES, 0xCC8323, EXPIRY_OPTIONS)
            and has(BLOCK_VALUES, 0xCC8390, "cmp", "byte ptr [ebp - 0x11], 0")
            and has(BLOCK_VALUES, 0xCC8394, "jne", "0xcc83ae")
            and has(BLOCK_VALUES, 0xCC839D, "mov", "dl, 0xf")
            and call(BLOCK_VALUES, 0xCC83A9, BLOCK + "SetTimerExpiryCommand")),
        "level_percentage_rounding": (
            has("CIS_CBus.LevelToPercent", 0x7F2AD4, "add", "eax, 2")
            and has("CIS_CBus.LevelToPercent", 0x7F2AD7, "imul", "eax, eax, 0x64")
            and has("CIS_CBus.LevelToPercent", 0x7F2ADA, "mov", "ecx, 0xff")
            and has("CIS_CBus.LevelToPercent", 0x7F2AE0, "idiv", "ecx")),
    }
    pp_commands = (
        ("JPCommand", 0xCC6E29, 0xCC6E49, 0x11C, 0x1215E2B, 0x1215E68),
        ("SRCommand", 0xCC6E4F, 0xCC6E6F, 0x120, 0x1215E76, 0x1215EB3),
        ("LPCommand", 0xCC6E75, 0xCC6E95, 0x124, 0x1215EC1, 0x1215EFE),
        ("LRCommand", 0xCC6E9B, 0xCC6EBB, 0x128, 0x1215F0C, 0x1215F49),
    )
    for name, literal, store, offset, load, setter in pp_commands:
        checks[f"pp_{name}_mapping"] = (
            methods[CORE_AGENT + "InternalCreate"]["literal_at"].get(literal) == name
            and has(CORE_AGENT + "InternalCreate", store, "mov", f"dword ptr [edx + {hex(offset)}], eax")
            and has(KEY_AGENT + "GetKeyValues", load, "mov", f"eax, dword ptr [eax + {hex(offset)}]")
            and call(KEY_AGENT + "GetKeyValues", setter, INPUT_KEY + "SetMicroFunction"))
    checks["pp_group_address_mapping"] = (
        methods[CORE_AGENT + "InternalCreate"]["literal_at"].get(0xCC6D27) == "GroupAddress"
        and has(CORE_AGENT + "InternalCreate", 0xCC6D47, "mov", "dword ptr [edx + 0x100], eax")
        and has(CORE_AGENT + "GetBlockGroup", 0xCC7610, "mov", "eax, dword ptr [eax + 0x100]"))
    checks["pp_block_allocation_mapping"] = (
        methods[CORE_AGENT + "InternalCreate"]["literal_at"].get(0xCC6EC1) == "BlockAllocation"
        and has(CORE_AGENT + "InternalCreate", 0xCC6EE1, "mov", "dword ptr [edx + 0x12c], eax")
        and has(CORE_AGENT + "GetKeyBlocks", 0xCC7779, "mov", "eax, dword ptr [eax + 0x12c]")
        and has(CORE_AGENT + "GetKeyBlocks", 0xCC77B2, "call", "dword ptr [edx + 0x16c]"))
    field_checks = (
        ("debounce", "DebounceTime", 0xCC6D4D, 0xCC6D6D, 0x104, 0xCC8622, 0xCC8648, 0x1CC),
        ("long_press", "LongPressTime", 0xCC6DAF, 0xCC6DCF, 0x10C, 0xCC865E, 0xCC8684, 0x1D0),
    )
    for label, name, literal, store, offset, load, destination, attr in field_checks:
        checks[f"pp_{label}_mapping"] = (
            methods[CORE_AGENT + "InternalCreate"]["literal_at"].get(literal) == name
            and has(CORE_AGENT + "InternalCreate", store, "mov", f"dword ptr [edx + {hex(offset)}], eax")
            and has(CORE_AGENT + "AfterLoadProgrammingInformation", load, "mov", f"eax, dword ptr [eax + {hex(offset)}]")
            and has(CORE_AGENT + "AfterLoadProgrammingInformation", destination, "mov", f"eax, dword ptr [eax + {hex(attr)}]"))
    checks["pp_ramp_mapping"] = (
        methods[CORE_AGENT + "InternalCreate"]["literal_at"].get(0xCC6DDD) == "RampRate"
        and has(CORE_AGENT + "InternalCreate", 0xCC6DFD, "mov", "dword ptr [edx + 0x114], eax")
        and has(CORE_AGENT + "AfterLoadProgrammingInformation", 0xCC869E, "mov", "eax, dword ptr [eax + 0x114]")
        and has(CORE_AGENT + "AfterLoadProgrammingInformation", 0xCC86BE, "xor", "edx, edx")
        and has(CORE_AGENT + "AfterLoadProgrammingInformation", 0xCC86FF, "mov", "edx, 1")
        and call(CORE_AGENT + "AfterLoadProgrammingInformation", 0xCC86C5, RAMP_CONVERT)
        and call(CORE_AGENT + "AfterLoadProgrammingInformation", 0xCC8709, RAMP_CONVERT)
        and call(CORE_AGENT + "AfterLoadProgrammingInformation", 0xCC86D4, CUSTOM_UNIT + "SetRampRate1")
        and call(CORE_AGENT + "AfterLoadProgrammingInformation", 0xCC8718, CUSTOM_UNIT + "SetRampRate2"))
    for kind, symbol, _, _ in key_registrations:
        checks[f"class_slots_{kind}"] = (
            image.slot(symbol, 0x190) == f"CIS_TKey{KEY_COUNTS[kind]}.TKey{KEY_COUNTS[kind]}.MaximumKeyCount"
            and image.slot(symbol, 0x194) == CORE_UNIT + "GetMaximumVirtualKeyCount"
            and image.slot(symbol, 0x16C) == "CIS_TCBusKeyInputUnit.TCBusKeyInputUnit.MaximumBlockCount")
    failed = [name for name, value in checks.items() if not value]
    if failed:
        raise ValueError("Source checks failed: " + ", ".join(failed))
    if _sha(exe.read_bytes()) != EXE_SHA256 or _sha(map_file.read_bytes()) != MAP_SHA256:
        raise ValueError("Original files changed during inspection")
    return {
        "format": "cbus-project-documentor-classic-key-static-v1",
        "original_executed": False, "original_generated_page_comparison": "not_obtained",
        "exe_sha256": EXE_SHA256, "map_sha256": MAP_SHA256,
        "key_counts": counts, "block_count": 4,
        "timing_descriptions": list(TIMING_DESCRIPTIONS), "ramp_descriptions": list(RAMP_DESCRIPTIONS),
        "timing_type": timing_type, "ramp_type": ramp_type,
        "bistable_guid": BISTABLE_GUID, "no_bistable_ancestry": ancestry,
        "macro_source": {
            "labels": {str(k): macro.labels[k] for k in sorted(set(macro.subsets["202"]))},
            "key_subsets": macro.subsets,
            "first_global_matches_admitted_by_KEY": [
                {"jp_sr_lp_lr": list(vector), "template_type": kind}
                for vector, kind in macro.first_match.items() if kind in macro.subsets["202"]],
            "non_202_primary_block_shutter_remaps": {
                "type_14_stored1": {"249": 17, "252": 18, "255": 20}, "type_15_stored2": {"2": 19, "5": 22}},
            "pipeline": "First ordered global match, primary-block shutter conversion, then KEY application subset; disallowed becomes 26.",
        },
        "timer_source": {"seconds": "(TimerHighByte << 8) | TimerLowByte",
                         "expiry_allowed_ordinals": [0, 15, 4, 9, 12, 6, 10],
                         "other_expiry_ordinals": 15},
        "checks": checks,
        "methods": {name: {"start": hex(method["start"]), "end": hex(method["end"]),
                            "sha256": method["sha256"], "literals": method["literals"]}
                    for name, method in methods.items()},
        "boundary": [
            "KEY1, KEY2 and KEY4 source mappings only; this receipt does not admit other key families.",
            "Timing values require explicit 0..63 ordinals; original enum setters reject invalid values.",
            "RampRate elements pass through the source conversion, including 255 to ordinal 1.",
            "Block lookup uses first matching group identity; duplicate controls remain duplicated.",
            "Ascending BlockAllocation describes a fresh native object-model load; existing in-memory block-reference history is not modeled.",
            "Source method inventory does not mean every macro, timer or scene branch is implemented.",
            "No original generated HTML, visual, print or native project-load acceptance was obtained.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.exe, args.map)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Verified {len(report['checks'])} source checks; wrote {args.output}")


if __name__ == "__main__":
    main()
