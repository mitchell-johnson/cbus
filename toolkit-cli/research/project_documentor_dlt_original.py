"""Execute only the original bounded TDLTDocumentor wrapper on synthetic data.

The inherited NeoPro documentor, class test, boolean attribute and TStringList
are fixture hooks. This establishes the DLT wrapper's exact appended lines and
ordering only; it is not a complete original generated-page comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX
from unicorn.x86_const import UC_X86_REG_ECX as ECX, UC_X86_REG_EIP as EIP, UC_X86_REG_ESP as ESP

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256
from project_documentor_dlt_static import BODY, UNIT


def inspect(executable: Path, mapping: Path) -> dict:
    exe, symbols = executable.read_bytes(), mapping.read_bytes()
    sha = lambda data: hashlib.sha256(data).hexdigest()
    if sha(exe) != EXE_SHA256 or sha(symbols) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Toolkit(exe, symbols)
    method = image.method(BODY)
    memory = image.pe.get_memory_mapped_image()
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(image.base, (len(memory) + 4095) & ~4095)
    u.mem_write(image.base, memory)
    u.mem_map(0x30000000, 0x10000)
    stack, unit, writer, vmt, add, stop = (0x30008000, 0x30001000, 0x30002000,
                                         0x30003000, 0x30004000, 0x30005000)
    put = lambda address, value: u.mem_write(address, struct.pack("<I", value))
    get = lambda address: struct.unpack("<I", u.mem_read(address, 4))[0]
    put(writer, vmt)
    put(vmt + 0x38, add)
    inherited = image.by_name["CIS_TNeoProInputDocumentor.TNeoProInputDocumentor.DocumentHTML"]
    is_class = image.by_name["System.@IsClass"]
    get_block = image.by_name[UNIT + "GetBlockDynamicUpdates"]
    state = {}

    def ret(value=0):
        sp = u.reg_read(ESP)
        u.reg_write(EAX, value)
        u.reg_write(EIP, get(sp))
        u.reg_write(ESP, sp + 4)

    def hook(_u, address, _size, _data):
        if address == stop:
            u.emu_stop()
        elif address == inherited:
            assert u.reg_read(EDX) == writer and u.reg_read(ECX) == unit
            state["calls"].append("inherited_neopro")
            state["lines"].append("<synthetic inherited body>")
            ret()
        elif address == is_class:
            assert u.reg_read(EAX) == unit
            state["calls"].append("dynamic_label_class_test")
            ret(int(state["is_dlt"]))
        elif address == get_block:
            assert u.reg_read(EAX) == unit
            state["calls"].append("get_block_dynamic_updates")
            ret(int(state["blocked"]))
        elif address == add:
            assert u.reg_read(EAX) == writer
            state["calls"].append("append_suffix")
            state["lines"].append(image.literal(u.reg_read(EDX)))
            ret()
        elif not method["start"] <= address < 0xFFD7A5:
            raise AssertionError(f"Unexpected original execution at {address:#x}")

    u.hook_add(UC_HOOK_CODE, hook)
    observations = []
    for is_dlt, blocked in ((False, False), (False, True), (True, False), (True, True)):
        state.clear()
        state.update(is_dlt=is_dlt, blocked=blocked, calls=[], lines=[])
        put(stack, stop)
        u.reg_write(ESP, stack)
        u.reg_write(EAX, 0x30006000)
        u.reg_write(EDX, writer)
        u.reg_write(ECX, unit)
        u.emu_start(method["start"], stop, count=100)
        if u.reg_read(EIP) != stop:
            raise AssertionError("Original wrapper failed to return")
        expected = ["<synthetic inherited body>"] + (["Labels: Static" if blocked else "Labels: Dynamic"] if is_dlt else [])
        assert state["lines"] == expected
        observations.append(dict(state))
    return {"format": "cbus-project-documentor-dlt-original-leaf-v1", "exe_sha256": EXE_SHA256,
        "map_sha256": MAP_SHA256, "method": {"symbol": BODY, "start": hex(method["start"]),
            "end": hex(method["end"]), "sha256": method["sha256"]}, "observations": observations,
        "original_generated_page_comparison": "not_obtained",
        "boundary": "Original wrapper instructions only; inherited body, class test, boolean storage and string list are synthetic hooks. No GUI, native loader, saved project or physical device."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.executable, args.map)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(report["observations"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
