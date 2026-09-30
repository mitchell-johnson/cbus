"""Execute pinned ActionSelectorUse methods against synthetic object accessors.

The original Classic/Neo/NeoPro ActionSelectorUse chain runs. Every called Delphi string routine,
collection accessor and unit getter is intercepted; no GUI, project, network or
hardware code executes. This is independent branch/order evidence, not a complete
original page or PP-loader capture. Receipts contain synthetic cases and hashes,
never vendor bytes. Require the exact original Toolkit EXE and MAP explicitly.
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

METHODS = tuple(f"CIS_T{name}Documentor.T{name}Documentor.ActionSelectorUse"
                for name in ("ClassicKeyInput", "NeoInput", "NeoProInput"))
INPUT_METHODS = tuple(f"CIS_T{name}.T{name}.DescribeInputGroupDependencyAdvanced"
                      for name in ("CBusNeoInputUnit", "CBusDynamicLabelInputUnit"))
METHOD = METHODS[-1]
BLOCKS, FALSE_HOOK, PHYSICAL_HOOK, PAGE_HOOK = 0x20002400, 0x20002040, 0x20002050, 0x20002060
SCENES, INDEX_HOOK, SECONDARY_HOOK = 0x20002200, 0x20002020, 0x20002030
RETURN = 0x30000000
UNIT, LEVEL, RESULT, KEYS = 0x20000100, 0x20000400, 0x20000800, 0x20000A00
UNIT_VMT, LIST_VMT = 0x20001000, 0x20001400
PRIMARY, GROUP, MICRO = 0x20001800, 0x20001A00, 0x20001C00
COUNT_HOOK, APPLICATION_HOOK = 0x20002000, 0x20002010


class OriginalNeoActionSelectorProbe:
    def __init__(self, executable: Path, map_file: Path, method_name: str = METHOD):
        raw, symbols = executable.read_bytes(), map_file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
            raise ValueError("Original Toolkit EXE/MAP hash mismatch")
        self.toolkit = _Toolkit(raw, symbols)
        self.method = self.toolkit.method(method_name)
        self.methods = [self.toolkit.method(name) for name in METHODS + INPUT_METHODS]
        self.image = self.toolkit.pe.get_memory_mapped_image()

    def run(self, case: dict) -> str:
        t = self.toolkit
        method = t.method(INPUT_METHODS[int(case["dlt"])]) if "dlt" in case else self.method
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 4096)  # Delphi FS exception-list cell, never a host exception handler.
        u.mem_map(t.base, (len(self.image) + 4095) & ~4095)
        u.mem_write(t.base, self.image)
        u.mem_map(0x20000000, 0x100000)
        u.mem_map(0x21000000, 0x10000)
        u.mem_map(RETURN, 4096)
        next_string = 0x20080000

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
            u.mem_write(pointer - 12, struct.pack("<HHiI", 1200, 2, -1, len(value)) + encoded + b"\0\0")
            put(destination, pointer)

        def finish(value=None, stack_arguments=0):
            if value is not None:
                u.reg_write(UC_X86_REG_EAX, value)
            stack = u.reg_read(UC_X86_REG_ESP)
            u.reg_write(UC_X86_REG_EIP, get(stack))
            u.reg_write(UC_X86_REG_ESP, stack + 4 + stack_arguments)

        key_objects = [0x20003000 + index * 0x200 for index in range(len(case["keys"]))]
        block_objects = [0x20010000 + index * 0x200 for index in range(len(case["blocks"]))]
        keys_by_address = dict(zip(key_objects, case["keys"]))
        blocks_by_address = dict(zip(block_objects, case["blocks"]))
        scene_objects = [0x20030000 + index * 0x100 for index in range(8)]
        commands_by_address = {}
        lists = {KEYS: key_objects, BLOCKS: block_objects, SCENES: scene_objects}
        command_address = 0x20040000
        for index, scene in enumerate(case.get("scenes", [[], [], [], [], [], [], [], []])):
            collection = 0x20032000 + index * 0x100
            put(scene_objects[index] + 0x80, collection)
            lists[collection] = []
            for group in scene:
                lists[collection].append(command_address)
                commands_by_address[command_address] = group
                command_address += 0x100
        for index, (key_address, key) in enumerate(zip(key_objects, case["keys"])):
            collection = 0x20020000 + index * 0x100
            put(key_address + 0xAC, collection)
            lists[collection] = [block_objects[b] for b in key["blocks"]]
        for collection in lists:
            put(collection, LIST_VMT)
        put(LIST_VMT + 0x58, COUNT_HOOK)
        put(UNIT, UNIT_VMT)
        put(UNIT_VMT + 0xB0, APPLICATION_HOOK)
        put(UNIT_VMT + 0xB4, SECONDARY_HOOK)
        put(UNIT + 0x244, SCENES)
        put(SCENES, LIST_VMT)
        put(LIST_VMT + 0x78, INDEX_HOOK)
        put(UNIT + 0x1E8, KEYS)
        put(UNIT + 0x1C8, BLOCKS)
        put(UNIT_VMT + 0x234, FALSE_HOOK)
        put(UNIT_VMT + 0x238, FALSE_HOOK)
        put(UNIT_VMT + 0x190, PHYSICAL_HOOK)
        put(UNIT_VMT + 0x27C, PAGE_HOOK)

        hooks = {}

        def bind(suffix, callback):
            matches = [address for address, names in t.symbols.items()
                       if any(name.endswith(suffix) for name in names)]
            if not matches:
                raise ValueError("Missing original symbol: " + suffix)
            for address in matches:
                hooks[address] = callback

        bind("TUnitTypeDocumentor.ActionSelectorUse", lambda a, d, c: (write_string(RESULT, ""), finish(stack_arguments=4)))
        bind("System.@IsClass", lambda a, d, c: finish(1))
        bind("TLevel.GetGroup", lambda a, d, c: finish(GROUP))
        bind("TCBusGroup.GetApplication", lambda a, d, c: finish(PRIMARY))
        bind("TInputKeyCollection.GetItem", lambda a, d, c: finish(lists[a][d]))
        bind("TInputBlockReferenceCollection.GetItem", lambda a, d, c: finish(lists[a][d]))
        bind("TInputBlockCollection.GetItem", lambda a, d, c: finish(lists[a][d]))
        bind("TNeoSceneCollection.GetItem", lambda a, d, c: finish(lists[a][d]))
        bind("TNeoSceneCommandManager.GetItem", lambda a, d, c: finish(lists[a][d]))
        bind("TNeoSceneCommand.GetGroup", lambda a, d, c: finish(
            GROUP if commands_by_address[a] == case["group"] and case["application"] == case["applications"][0] else GROUP + 4))
        bind("TInputKey.GetMacroFunctionTemplate", lambda a, d, c: finish(a))
        bind("TKeyMacroFunctionTemplate.GetFunctionType", lambda a, d, c: finish(keys_by_address[a]["macro_type"]))
        bind("TInputKey.HasBlock", lambda a, d, c: finish(int(block_objects.index(d) in keys_by_address[a]["blocks"])))
        bind("TInputBlock.GetGroup", lambda a, d, c: finish(GROUP if blocks_by_address[a]["group"] == case["group"] and blocks_by_address[a]["application"] == case["application"] else GROUP + 4))
        bind("TInputBlock.GetLightStoredLevel1", lambda a, d, c: finish(blocks_by_address[a]["stored1"]))
        bind("TInputBlock.GetLightStoredLevel2", lambda a, d, c: finish(blocks_by_address[a]["stored2"]))
        bind("TCGateObject.GetAddressAsInteger", lambda a, d, c: finish(case["address"]))
        bind("TLevel.GetValue", lambda a, d, c: finish(case["value"]))
        bind("TKeyMicroFunctionFactory.GetKeyMicroFunction", lambda a, d, c: finish(MICRO + (d & 255)))
        bind("TInputKey.GetMicroFunctionGroup", lambda a, d, c: finish(a))
        bind("TInputKey.GetExtensionNeo", lambda a, d, c: finish(a))
        bind("TInputKeyExtensionNeo.GetSceneTriggerLevel", lambda a, d, c: finish(
            LEVEL if keys_by_address[a].get("trigger") == case["address"] else 0))
        bind("TInputKeyExtensionNeo.GetScene", lambda a, d, c: finish(scene_objects[keys_by_address[a].get("scene", 0)]))
        bind("TCBusNeoInputUnit.GetControlAppGroup", lambda a, d, c: finish(
            GROUP if case["application"] == 202 and case["control_group"] == case["group"] else GROUP + 4))
        bind("TKeyMicroFunctionGroup.ContainsMicroFunction", lambda a, d, c: finish(int(d - MICRO in keys_by_address[a]["commands"])))
        bind("TInputBlock.GetTimerExpiryCommand", lambda a, d, c: finish(MICRO + blocks_by_address[a]["expiry"]))
        bind("SysUtils.IntToStr", lambda a, d, c: (write_string(d, str(a)), finish()))
        bind("System.@UStrAsg", lambda a, d, c: (write_string(a, read_string(d)), finish()))
        bind("System.@UStrCat", lambda a, d, c: (write_string(a, read_string(get(a)) + read_string(d)), finish()))
        bind("System.@UStrArrayClr", lambda a, d, c: finish())
        bind("System.@UStrClr", lambda a, d, c: finish())
        bind("System.@UStrCat3", lambda a, d, c: (write_string(a, read_string(d) + read_string(c)), finish()))
        bind("System.LoadResString", lambda a, d, c: (write_string(d, t.resource(a)), finish()))

        def format_string(a, d, c):
            destination = get(u.reg_read(UC_X86_REG_ESP) + 4)
            write_string(destination, read_string(a) % get(d))
            finish(stack_arguments=4)
        bind("SysUtils.Format", format_string)

        def concatenate(a, count, c):
            stack = u.reg_read(UC_X86_REG_ESP)
            values = [read_string(get(stack + 4 + k * 4)) for k in range(count)]
            write_string(a, "".join(reversed(values)))
            finish(stack_arguments=count * 4)
        bind("System.@UStrCatN", concatenate)

        def intercept(_u, pc, _size, _data):
            a, d, c = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
            if pc in hooks:
                hooks[pc](a, d, c)
            elif pc == COUNT_HOOK:
                finish(len(lists[a]))
            elif pc == APPLICATION_HOOK:
                finish(PRIMARY if case["applications"][0] == case["application"] else PRIMARY + 4)
            elif pc == SECONDARY_HOOK:
                finish(PRIMARY if case["applications"][1] == case["application"] else PRIMARY + 4)
            elif pc == INDEX_HOOK:
                finish(scene_objects.index(d))
            elif pc == FALSE_HOOK:
                finish(0)  # Explicit disabled join state in these synthetic cases.
            elif pc == PHYSICAL_HOOK:
                finish(case["physical_count"])
            elif pc == PAGE_HOOK:
                finish(3)
            elif not any(m["start"] <= pc < m["end"] for m in self.methods):
                raise AssertionError(f"Unexpected original execution at {pc:#x}")
        u.hook_add(UC_HOOK_CODE, intercept)
        stack = 0x21008000
        put(stack, RETURN)
        put(stack + 4, RESULT)
        u.reg_write(UC_X86_REG_ESP, stack)
        u.reg_write(UC_X86_REG_EAX, UNIT if "dlt" in case else 0x20000080)
        u.reg_write(UC_X86_REG_EDX, GROUP if "dlt" in case else LEVEL)
        u.reg_write(UC_X86_REG_ECX, RESULT if "dlt" in case else UNIT)
        u.emu_start(method["start"], RETURN, count=20000)
        if u.reg_read(UC_X86_REG_EIP) != RETURN:
            raise AssertionError("Original ActionSelectorUse did not return")
        return read_string(get(RESULT))


def cases():
    block = {"application": 202, "group": 8, "stored1": 11, "stored2": 22, "expiry": 15}
    key = {"commands": [12, 6], "blocks": [0], "scene": 0, "trigger": None}
    base = {"application": 202, "group": 8, "address": 11, "value": 22,
            "applications": [202, 56], "control_group": 9, "blocks": [block], "keys": [key]}
    rows = [{**base, "name": "primary-recall"},
            {**base, "name": "secondary-recall", "applications": [56, 202]},
            {**base, "name": "same-app-two-passes", "applications": [202, 202]},
            {**base, "name": "secondary-stored1-gates-recall2", "applications": [56, 202], "address": 99},
            {**base, "name": "secondary-value-distinct", "applications": [56, 202], "value": 99},
            {**base, "name": "different-block-application", "blocks": [{**block, "application": 56}]},
            {**base, "name": "scene-overwrites-primary", "control_group": 8,
             "keys": [{**key, "trigger": 11, "scene": 2}]},
            {**base, "name": "last-scene-wins", "control_group": 8,
             "keys": [{**key, "trigger": 11, "scene": 2}, {**key, "trigger": 11, "scene": 6}]},
            {**base, "name": "scene-then-secondary", "control_group": 8, "applications": [56, 202],
             "keys": [{**key, "commands": [0], "blocks": [], "trigger": 11, "scene": 3}, key]},
            {**base, "name": "scene-selector-address-not-value", "control_group": 8,
             "keys": [{**key, "commands": [0], "trigger": 22, "scene": 3}]},
            {**base, "name": "nil-scene-trigger", "control_group": 8,
             "keys": [{**key, "commands": [0], "trigger": None, "scene": 0}]},
            {**base, "name": "selector-255-is-real", "control_group": 8, "address": 255,
             "keys": [{**key, "commands": [0], "trigger": 255, "scene": 7}]},
            {**base, "name": "secondary-timer-expiry", "applications": [56, 202],
             "blocks": [{**block, "expiry": 12}, {**block, "expiry": 6}],
             "keys": [{**key, "commands": [7], "blocks": [0, 1]}]},
            {**base, "name": "secondary-start-does-not-retrigger", "applications": [56, 202],
             "blocks": [{**block, "expiry": 12}], "keys": [{**key, "commands": [8]}]}]
    rows.append({**base, "name": "control-group-255-is-real", "group": 255,
                 "control_group": 255, "keys": [{**key, "commands": [0], "trigger": 11, "scene": 4}]})
    return rows


def group_cases():
    key = {"commands": [12], "blocks": [0, 1], "scene": 0, "trigger": None, "macro_type": 26}
    base = {"application": 56, "applications": [56, 202], "group": 8, "physical_count": 2,
            "blocks": [{"application": 56, "group": 8}, {"application": 56, "group": 8},
                       {"application": 56, "group": 9}],
            "keys": [key, {**key, "blocks": [0]}, {**key, "blocks": [0], "scene": 2}],
            "scenes": [[8], [8], [8], [], [], [], [], []], "dlt": False}
    rows = [{**base, "name": "neo-blocks-then-scenes"},
            {**base, "name": "dlt-all-scenes-used", "dlt": True},
            {**base, "name": "unused-macro", "keys": [{**key, "macro_type": 16}], "physical_count": 1},
            {**base, "name": "virtual-key-scene-reference-still-used"},
            {**base, "name": "different-application", "application": 202},
            {**base, "name": "unallocated-block", "group": 9},
            {**base, "name": "duplicate-scene-commands", "scenes": [[8, 8]] + [[]] * 7}]
    return rows


def inspect_groups(executable: Path, map_file: Path) -> dict:
    probe = OriginalNeoActionSelectorProbe(executable, map_file)
    return {"format": "cbus-project-documentor-neo-input-original-v1", "exe_sha256": EXE_SHA256,
            "map_sha256": MAP_SHA256,
            "methods": {name: {"sha256": method["sha256"], "start": hex(method["start"]),
                                "end": hex(method["end"])} for name, method in zip(INPUT_METHODS, probe.methods[-2:])},
            "boundary": "original Neo/DLT input method instructions with synthetic getters/string/collection stubs and disabled joins; no PP loader or original page",
            "cases": [{**case, "html": probe.run(case).removesuffix("|").replace("|", "<br/>")}
                      for case in group_cases()]}


def inspect(executable: Path, map_file: Path) -> dict:
    probe = OriginalNeoActionSelectorProbe(executable, map_file)
    rows = [{**case, "html": probe.run(case)} for case in cases()]
    return {"format": "cbus-project-documentor-neo-action-original-v1", "exe_sha256": EXE_SHA256,
            "map_sha256": MAP_SHA256,
            "methods": {name: {"sha256": method["sha256"], "start": hex(method["start"]),
                                "end": hex(method["end"])} for name, method in zip(METHODS, probe.methods)},
            "boundary": "original Classic/Neo/NeoPro method instructions with synthetic getters/string/collection stubs; no PP loader or original page",
            "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group-inputs", action="store_true")
    args = parser.parse_args()
    result = (inspect_groups if args.group_inputs else inspect)(args.executable, args.map_file)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(result["cases"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
