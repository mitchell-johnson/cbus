"""Execute pinned ActionSelectorUse methods against synthetic object accessors.

Only the selected original method's instructions run. Every called Delphi string routine,
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

METHOD = "CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.ActionSelectorUse"
RETURN = 0x30000000
UNIT, LEVEL, RESULT, KEYS = 0x20000100, 0x20000400, 0x20000800, 0x20000A00
UNIT_VMT, LIST_VMT = 0x20001000, 0x20001400
PRIMARY, GROUP, MICRO = 0x20001800, 0x20001A00, 0x20001C00
COUNT_HOOK, APPLICATION_HOOK = 0x20002000, 0x20002010


class OriginalActionSelectorProbe:
    def __init__(self, executable: Path, map_file: Path, method_name: str = METHOD):
        raw, symbols = executable.read_bytes(), map_file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
            raise ValueError("Original Toolkit EXE/MAP hash mismatch")
        self.toolkit = _Toolkit(raw, symbols)
        self.method = self.toolkit.method(method_name)
        self.image = self.toolkit.pe.get_memory_mapped_image()

    def run(self, case: dict) -> str:
        t, method = self.toolkit, self.method
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
        lists = {KEYS: key_objects}
        for index, (key_address, key) in enumerate(zip(key_objects, case["keys"])):
            collection = 0x20020000 + index * 0x100
            put(key_address + 0xAC, collection)
            lists[collection] = [block_objects[b] for b in key["blocks"]]
        for collection in lists:
            put(collection, LIST_VMT)
        put(LIST_VMT + 0x58, COUNT_HOOK)
        put(UNIT, UNIT_VMT)
        put(UNIT_VMT + 0xB0, APPLICATION_HOOK)
        put(UNIT + 0x1E8, KEYS)

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
        bind("TInputBlock.GetGroup", lambda a, d, c: finish(GROUP if blocks_by_address[a]["group"] == case["group"] else GROUP + 4))
        bind("TInputBlock.GetLightStoredLevel1", lambda a, d, c: finish(blocks_by_address[a]["stored1"]))
        bind("TInputBlock.GetLightStoredLevel2", lambda a, d, c: finish(blocks_by_address[a]["stored2"]))
        bind("TCGateObject.GetAddressAsInteger", lambda a, d, c: finish(case["address"]))
        bind("TLevel.GetValue", lambda a, d, c: finish(case["value"]))
        bind("TKeyMicroFunctionFactory.GetKeyMicroFunction", lambda a, d, c: finish(MICRO + (d & 255)))
        bind("TInputKey.GetMicroFunctionGroup", lambda a, d, c: finish(a))
        bind("TKeyMicroFunctionGroup.ContainsMicroFunction", lambda a, d, c: finish(int(d - MICRO in keys_by_address[a]["commands"])))
        bind("TInputBlock.GetTimerExpiryCommand", lambda a, d, c: finish(MICRO + blocks_by_address[a]["expiry"]))
        bind("SysUtils.IntToStr", lambda a, d, c: (write_string(d, str(a)), finish()))
        bind("System.@UStrCat", lambda a, d, c: (write_string(a, read_string(get(a)) + read_string(d)), finish()))
        bind("System.@UStrArrayClr", lambda a, d, c: finish())
        bind("System.@UStrClr", lambda a, d, c: finish())
        bind("System.@UStrCat3", lambda a, d, c: (write_string(a, read_string(d) + read_string(c)), finish()))
        bind("System.LoadResString", lambda a, d, c: (write_string(d, t.resource(a)), finish()))
        for getter in ("TCBusFanControllerUnit.GetFanActionSelector", "TSENTEMPPro.GetBroadcastActionSelector",
                       "TCBusDigitalTemperatureSensor.GetErrorReportingActionSelector",
                       "TCBusDigitalTemperatureSensor.GetTriggerBroadcastActionSelector"):
            bind(getter, lambda a, d, c, name=getter: finish(LEVEL if case.get("matches", {}).get(name, False) else 0))

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
                finish(PRIMARY if case.get("same_application", True) else PRIMARY + 4)
            elif not method["start"] <= pc < method["end"]:
                raise AssertionError(f"Unexpected original execution at {pc:#x}")
        u.hook_add(UC_HOOK_CODE, intercept)
        stack = 0x21008000
        put(stack, RETURN)
        put(stack + 4, RESULT)
        u.reg_write(UC_X86_REG_ESP, stack)
        u.reg_write(UC_X86_REG_EAX, 0x20000080)
        u.reg_write(UC_X86_REG_EDX, LEVEL)
        u.reg_write(UC_X86_REG_ECX, UNIT)
        u.emu_start(method["start"], RETURN, count=20000)
        if u.reg_read(UC_X86_REG_EIP) != RETURN:
            raise AssertionError("Original ActionSelectorUse did not return")
        return read_string(get(RESULT))


def cases():
    blocks = [{"group": 8, "stored1": 11, "stored2": 22, "expiry": code} for code in (12, 6, 15)]
    rows = []
    for name, commands, address, value in (
        ("recall1", [12], 11, 22), ("recall2", [6], 11, 22),
        ("both-duplicate", [12, 6], 11, 22), ("stored1-gates-recall2", [6], 99, 22),
        ("distinct-address-value", [12, 6], 11, 99), ("timer-expiry", [7], 11, 22),
        ("start-not-retrigger", [8], 11, 22), ("unused", [0], 11, 22),
    ):
        rows.append({"name": name, "group": 8, "address": address, "value": value, "blocks": blocks,
                     "keys": [{"commands": commands, "blocks": [0, 1, 2]}]})
    rows.append({**rows[2], "name": "key-major-order", "keys": [
        {"commands": [12, 6], "blocks": [0, 1]}, {"commands": [12], "blocks": [0]}]})
    rows.append({**rows[2], "name": "different-application", "same_application": False})
    return rows


DIRECT_METHODS = {
    "FanController": ("CIS_TFanControllerDocumentor.TFanControllerDocumentor.ActionSelectorUse",
                      ("TCBusFanControllerUnit.GetFanActionSelector",)),
    "SENTEMPPro": ("CIS_TSENTEMPProDocumentor.TSENTEMPProDocumentor.ActionSelectorUse",
                   ("TSENTEMPPro.GetBroadcastActionSelector",)),
    "DigitalTemperatureSensor": ("CIS_TDigitalTemperatureSensorDocumentor.TDigitalTemperatureSensorDocumentor.ActionSelectorUse",
                                 ("TCBusDigitalTemperatureSensor.GetErrorReportingActionSelector",
                                  "TCBusDigitalTemperatureSensor.GetTriggerBroadcastActionSelector")),
}


def direct_cases():
    for documentor, (_, getters) in DIRECT_METHODS.items():
        for mask in range(1 << len(getters)):
            yield {"name": documentor + ":" + str(mask), "documentor": documentor,
                   "group": 8, "address": 11, "value": 22, "blocks": [], "keys": [],
                   "matches": {getter: bool(mask & (1 << index)) for index, getter in enumerate(getters)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--direct-actions", action="store_true")
    args = parser.parse_args()
    probe = OriginalActionSelectorProbe(args.executable, args.map_file)
    if args.direct_actions:
        probes = {name: OriginalActionSelectorProbe(args.executable, args.map_file, method)
                  for name, (method, _) in DIRECT_METHODS.items()}
        rows = [{**case, "html": probes[case["documentor"]].run(case)} for case in direct_cases()]
    else:
        rows = [{**case, "html": probe.run(case)} for case in cases()]
    result = {"format": "cbus-project-documentor-action-original-v1", "exe_sha256": EXE_SHA256,
              "map_sha256": MAP_SHA256, "method": METHOD, "method_sha256": probe.method["sha256"],
              "boundary": "original method instructions with synthetic getters/string/collection stubs; no original page", "cases": rows}
    if args.direct_actions:
        result.pop("method")
        result.pop("method_sha256")
        result["methods"] = {name: {"symbol": DIRECT_METHODS[name][0], "sha256": item.method["sha256"]}
                             for name, item in probes.items()}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(rows), "methods": result.get("methods", result.get("method_sha256")), "output": str(args.output)}))


if __name__ == "__main__":
    main()
