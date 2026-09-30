"""Run original InsertHTMLTriggerGroup instructions with explicit synthetic leaves.

Every called routine is intercepted: no original factory, ActionSelectorUse,
PP loader, GUI, project or hardware runs. The probe independently checks the
root wrapper's traversal, nesting and empty-result behavior. Supply exact
pinned EXE/MAP. Receipts contain synthetic facts/results, not vendor bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256

METHOD = "CIS_TProjectDocumentor.TProjectDocumentor.InsertHTMLTriggerGroup"
RETURN = 0x30000000
DOC, STRINGS, GROUP, NETWORK, APPLICATION = [0x20000100 + n * 0x400 for n in range(5)]
LEVELS, UNITS, LEVEL_VMT, UNIT_VMT, STRING_VMT, ATTR_VMT, ACTION_VMT = [0x20002000 + n * 0x400 for n in range(7)]
COUNT_HOOK, ADD_HOOK, TAG_HOOK, ACTION_HOOK = [0x20005000 + n * 0x10 for n in range(4)]
ACTION = 0x20006000


class OriginalTriggerGroupProbe:
    def __init__(self, executable: Path, map_file: Path):
        raw, symbols = executable.read_bytes(), map_file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
            raise ValueError("Original Toolkit EXE/MAP hash mismatch")
        self.toolkit = _Toolkit(raw, symbols)
        self.method = self.toolkit.method(METHOD)
        self.image = self.toolkit.pe.get_memory_mapped_image()

    def run(self, case: dict) -> dict:
        t, method = self.toolkit, self.method
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 4096)  # Synthetic Delphi FS exception-list cell.
        u.mem_map(t.base, (len(self.image) + 4095) & ~4095)
        u.mem_write(t.base, self.image)
        u.mem_map(0x20000000, 0x100000)
        u.mem_map(0x21000000, 0x10000)
        u.mem_map(RETURN, 4096)
        next_string = 0x20080000
        lines, factory_calls, action_calls = [], [], []

        def put(address, value):
            u.mem_write(address, struct.pack("<I", value))

        def get(address):
            return struct.unpack("<I", u.mem_read(address, 4))[0]

        def read_string(pointer):
            return "" if not pointer else bytes(u.mem_read(pointer, get(pointer - 4) * 2)).decode("utf-16le")

        def write_string(destination, value):
            nonlocal next_string
            if not value:
                put(destination, 0)
                return
            encoded = value.encode("utf-16le")
            pointer = next_string + 12
            next_string += (len(encoded) + 31) & ~15
            u.mem_write(pointer - 12, struct.pack("<HHiI", 1200, 2, -1, len(encoded) // 2) + encoded + b"\0\0")
            put(destination, pointer)

        def finish(value=None, stack_arguments=0):
            if value is not None:
                u.reg_write(UC_X86_REG_EAX, value)
            stack = u.reg_read(UC_X86_REG_ESP)
            u.reg_write(UC_X86_REG_EIP, get(stack))
            u.reg_write(UC_X86_REG_ESP, stack + 4 + stack_arguments)

        level_objects = [0x20010000 + n * 0x400 for n in range(len(case["levels"]))]
        unit_objects = [0x20020000 + n * 0x400 for n in range(len(case["units"]))]
        level_info = dict(zip(level_objects, case["levels"]))
        unit_info = dict(zip(unit_objects, case["units"]))
        addresses = {GROUP: case["group"], NETWORK: case["network"], APPLICATION: 202,
                     **{ptr: row["address"] for ptr, row in level_info.items()}}
        tags = {GROUP: case["tag"], **{ptr: row["tag"] for ptr, row in level_info.items()}}
        tag_attributes = {}
        for index, (ptr, tag) in enumerate(tags.items()):
            attr = 0x20030000 + index * 0x100
            put(ptr + 0x9C, attr)
            put(attr, ATTR_VMT)
            tag_attributes[attr] = tag
        put(ATTR_VMT + 0x2C, TAG_HOOK)
        put(GROUP + 0xD0, LEVELS)
        put(NETWORK + 0xD8, UNITS)
        put(LEVELS, LEVEL_VMT)
        put(UNITS, UNIT_VMT)
        put(LEVEL_VMT + 0x58, COUNT_HOOK)
        put(UNIT_VMT + 0x58, COUNT_HOOK)
        put(STRINGS, STRING_VMT)
        put(STRING_VMT + 0x38, ADD_HOOK)
        put(ACTION, ACTION_VMT)
        put(ACTION_VMT + 0x80, ACTION_HOOK)
        lists = {LEVELS: level_objects, UNITS: unit_objects}
        hooks = {}

        def bind(suffix, callback):
            found = [address for address, names in t.symbols.items()
                     if any(name.endswith(suffix) for name in names)]
            if not found:
                raise ValueError("Missing exact original symbol: " + suffix)
            for address in found:
                hooks[address] = callback

        bind("TCBusGroup.Network", lambda a, d, c: finish(NETWORK))
        bind("TCBusGroup.GetApplication", lambda a, d, c: finish(APPLICATION))
        bind("TCGateObject.GetAddressAsString", lambda a, d, c: (write_string(d, str(addresses[a])), finish()))
        bind("TCGateObject.GetAddressAsStringHex", lambda a, d, c: (write_string(d, f"{addresses[a]:02X}"), finish()))
        bind("TCGateObject.GetDescription", lambda a, d, c: (write_string(d, case["description"]), finish()))
        bind("TDocumentorCommon.FormatHTMLString", lambda a, d, c: (
            write_string(d, read_string(a).replace("<", "&#60;").replace(">", "&#62;")), finish()))
        bind("TLevelManager.GetDisplayName", lambda a, d, c: (write_string(d, "Action Selectors"), finish()))
        bind("TLevelManager.GetItem", lambda a, d, c: finish(lists[a][d]))
        bind("TCBUSUnitManager.GetItem", lambda a, d, c: finish(lists[a][d]))
        bind("TCBUSUnit.GetFirmwareVersion", lambda a, d, c: (write_string(d, unit_info[a]["firmware"]), finish()))
        bind("TCBUSUnit.GetUnitType", lambda a, d, c: (write_string(d, unit_info[a]["type"]), finish()))
        bind("TDocumentorCommon.DisplayHTMLUnit", lambda a, d, c: (
            write_string(d, f'<a href="#{case["network"]}_unit_{unit_info[a]["address"]}">'
                         f'{unit_info[a]["tag"]} - {unit_info[a]["type"]}</a>'), finish()))
        bind("System.TObject.Free", lambda a, d, c: finish())
        bind("System.@UStrClr", lambda a, d, c: (put(a, 0), finish()))
        bind("System.@UStrArrayClr", lambda a, d, c: finish())
        bind("System.@UStrCat", lambda a, d, c: (write_string(a, read_string(get(a)) + read_string(d)), finish()))

        def concatenate(a, count, c):
            stack = u.reg_read(UC_X86_REG_ESP)
            values = [read_string(get(stack + 4 + n * 4)) for n in range(count)]
            write_string(a, "".join(reversed(values)))
            finish(stack_arguments=count * 4)
        bind("System.@UStrCatN", concatenate)

        def factory(a, d, c):
            factory_calls.append({"type": read_string(d), "firmware": read_string(c)})
            finish(ACTION)
        bind("TUnitTypeDocumentorFactory.GetDocumentor", factory)

        def intercept(_u, pc, _size, _data):
            a, d, c = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
            if pc in hooks:
                hooks[pc](a, d, c)
            elif pc == COUNT_HOOK:
                finish(len(lists[a]))
            elif pc == ADD_HOOK:
                lines.append(read_string(d))
                finish(len(lines) - 1)
            elif pc == TAG_HOOK:
                write_string(d, tag_attributes[a])
                finish()
            elif pc == ACTION_HOOK:
                level, unit = level_info[d], unit_info[c]
                action_calls.append({"unit": unit["address"], "address": level["address"], "value": level["value"]})
                output = get(u.reg_read(UC_X86_REG_ESP) + 4)
                write_string(output, case["action_html"].get(f'{level["address"]}/{unit["address"]}', ""))
                finish(stack_arguments=4)
            elif not method["start"] <= pc < method["end"]:
                raise AssertionError(f"Unexpected original execution at {pc:#x}")
        u.hook_add(UC_HOOK_CODE, intercept)
        stack = 0x21008000
        put(stack, RETURN)
        u.reg_write(UC_X86_REG_ESP, stack)
        u.reg_write(UC_X86_REG_EAX, DOC)
        u.reg_write(UC_X86_REG_EDX, STRINGS)
        u.reg_write(UC_X86_REG_ECX, GROUP)
        u.emu_start(method["start"], RETURN, count=100000)
        if u.reg_read(UC_X86_REG_EIP) != RETURN:
            raise AssertionError("Original trigger-group method did not return")
        return {"lines": lines, "factory_calls": factory_calls, "action_calls": action_calls}


def cases():
    levels = [{"address": 22, "value": 11, "tag": "Second"},
              {"address": 11, "value": 22, "tag": "First<raw>"}]
    units = [{"address": 9, "type": "KEY1", "firmware": "1.2.67", "tag": "Nine"},
             {"address": 2, "type": "KEY2", "firmware": "1.2.67", "tag": "Two"},
             {"address": 15, "type": "KEY4", "firmware": "1.2.67", "tag": "Fifteen"}]
    base = {"network": 254, "group": 8, "tag": "Trigger<raw>", "description": "A < B > C & D",
            "levels": levels, "units": units, "action_html": {}}
    return [
        {**base, "name": "no-levels", "levels": []},
        {**base, "name": "no-units", "units": []},
        {**base, "name": "all-empty"},
        {**base, "name": "one-used", "action_html": {"22/9": "Key 1"}},
        {**base, "name": "interleaved-multi-unit", "action_html": {
            "22/2": "Key 2", "22/15": "Key 1<br/>Key 1", "11/9": "Key 1", "11/15": "Key 4"}},
        {**base, "name": "nonempty-markup-leaf", "action_html": {"11/2": "<li />Scene 1<br/>Scene 2"}},
    ]


def capture(executable: Path, map_file: Path) -> dict:
    probe = OriginalTriggerGroupProbe(executable, map_file)
    return {"format": "cbus-project-documentor-trigger-original-v1", "exe_sha256": EXE_SHA256,
            "map_sha256": MAP_SHA256, "method": METHOD, "method_sha256": probe.method["sha256"],
            "method_start": hex(probe.method["start"]), "method_end": hex(probe.method["end"]),
            "original_wrapper_instructions_executed": True,
            "original_factory_or_action_methods_executed": False,
            "original_generated_page_compared": False,
            "boundary": "Only InsertHTMLTriggerGroup instructions; all called routines intercepted with explicit synthetic getters, factory/action outputs, HTML/string and collection leaves. No original loader, GUI, project, network, or hardware.",
            "cases": [{**case, "result": probe.run(case)} for case in cases()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.executable, args.map_file)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(result["cases"]), "method_sha256": result["method_sha256"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
