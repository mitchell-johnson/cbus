"""Execute bounded original Fan body and ErrorReportOutput action methods.

The Fan body and LevelToPercent instructions execute; inherited Output body,
class test, unit getters, DisplayHTMLUnit, TStringList and Delphi string routines
are synthetic leaves. The ErrorReportOutput action method executes with
synthetic object-identity getters. No loader, generated project page, GUI,
network or hardware executes. Receipts contain synthetic output and hashes only.
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

METHODS = {
    "fan_body": "CIS_TFanControllerDocumentor.TFanControllerDocumentor.DocumentHTML",
    "percent": "CIS_CBus.LevelToPercent",
    "error_action": "CIS_TErrorReportOutputDocumentor.TErrorReportOutputDocumentor.ActionSelectorUse",
}
RETURN = 0x30000000
DOC, UNIT, WRITER, RESULT, LEVEL, MASTER = (0x20000100 + n * 0x400 for n in range(6))
STRING_VMT, ADD = 0x20002000, 0x20004000
INHERITED_MARKER = "<synthetic inherited Output body>"
MASTER_HTML = '<a href="#254_7">Master <synthetic></a>'


class OriginalSpecialOutputsProbe:
    def __init__(self, executable: Path, mapping: Path):
        raw, symbols = executable.read_bytes(), mapping.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
            raise ValueError("Original Toolkit EXE/MAP hash mismatch")
        self.toolkit = _Toolkit(raw, symbols)
        self.methods = {kind: self.toolkit.method(name) for kind, name in METHODS.items()}
        self.image = self.toolkit.pe.get_memory_mapped_image()

    def run(self, case: dict, kind: str) -> dict:
        t = self.toolkit
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 4096)  # Synthetic Delphi FS exception-list cell.
        u.mem_map(t.base, (len(self.image) + 4095) & ~4095)
        u.mem_write(t.base, self.image)
        u.mem_map(0x20000000, 0x100000)
        u.mem_map(0x21000000, 0x10000)
        u.mem_map(RETURN, 4096)
        next_string = 0x20080000
        lines, leaf_calls = [], []

        def put(address, value):
            u.mem_write(address, struct.pack("<I", value))

        def get(address):
            return struct.unpack("<I", u.mem_read(address, 4))[0]

        def text(pointer):
            return "" if not pointer else bytes(u.mem_read(pointer, get(pointer - 4) * 2)).decode("utf-16le")

        def write(destination, value):
            nonlocal next_string
            if not value:
                put(destination, 0)
                return
            encoded = value.encode("utf-16le")
            pointer = next_string + 12
            next_string += (len(encoded) + 31) & ~15
            u.mem_write(pointer - 12, struct.pack("<HHiI", 1200, 2, -1, len(encoded) // 2) + encoded + b"\0\0")
            put(destination, pointer)

        def finish(value=None, pop=0):
            if value is not None:
                u.reg_write(EAX, value)
            stack = u.reg_read(ESP)
            u.reg_write(EIP, get(stack))
            u.reg_write(ESP, stack + 4 + pop)

        put(WRITER, STRING_VMT)
        put(STRING_VMT + 0x38, ADD)
        put(UNIT + 0x260, MASTER if case.get("has_master", False) else 0)
        hooks = {}

        def bind(name, callback):
            addresses = [address for address, names in t.symbols.items() if name in names]
            if not addresses:
                raise ValueError("Missing original symbol: " + name)
            for address in addresses:
                hooks[address] = (name, callback)

        def inherited_output(a, d, c):
            assert a == DOC and d == WRITER and c == UNIT
            lines.append(INHERITED_MARKER)
            finish()

        bind("CIS_TOutputDocumentor.TOutputDocumentor.DocumentHTML", inherited_output)
        bind("CIS_TProjectDocumentor.TUnitTypeDocumentor.ActionSelectorUse",
             lambda a, d, c: (write(RESULT, ""), finish(pop=4)))
        bind("System.@IsClass", lambda a, d, c: finish(1))
        fan = "CIS_TCBusFanControllerUnit.TCBusFanControllerUnit."
        bind(fan + "CheckIfMasterUnit", lambda a, d, c: finish(int(case.get("is_master", False))))
        bind(fan + "GetLowMedThreshold", lambda a, d, c: finish(case["low_med"]))
        bind(fan + "GetMedHighThreshold", lambda a, d, c: finish(case["med_high"]))
        for getter, label in (("Off", "off"), ("Low", "low"), ("Med", "medium"), ("High", "high")):
            bind(fan + "GetDLTLabel" + getter,
                 lambda a, d, c, label=label: (write(d, case["labels"][label]), finish()))

        def display_unit(a, d, c):
            assert a == MASTER
            write(d, MASTER_HTML)
            finish()

        bind("CIS_TDocumentorCommon.DisplayHTMLUnit", display_unit)
        error = "CIS_TDIMDUX.TDIMDUX."
        for getter, key in (("GetTriggerErrorAcSel", "report_match"),
                            ("GetTriggerErrorClearAcSel", "clear_match")):
            bind(error + getter, lambda a, d, c, key=key: finish(LEVEL if case[key] else LEVEL + 4))
        bind("SysUtils.IntToStr", lambda a, d, c: (write(d, str(a)), finish()))
        bind("System.LoadResString", lambda a, d, c: (write(d, t.resource(a)), finish()))
        bind("System.@UStrLAsg", lambda a, d, c: (write(a, text(d)), finish()))
        bind("System.@UStrCat3", lambda a, d, c: (write(a, text(d) + text(c)), finish()))
        bind("System.@UStrArrayClr", lambda a, d, c: finish())

        def concatenate(a, count, c):
            stack = u.reg_read(ESP)
            write(a, "".join(reversed([text(get(stack + 4 + n * 4)) for n in range(count)])))
            finish(pop=count * 4)

        bind("System.@UStrCatN", concatenate)
        allowed = [self.methods[kind]] + ([self.methods["percent"]] if kind == "fan_body" else [])
        original_percent_calls = []

        def intercept(_u, pc, _size, _data):
            a, d, c = (u.reg_read(register) for register in (EAX, EDX, ECX))
            if pc in hooks:
                name, callback = hooks[pc]
                leaf_calls.append(name)
                callback(a, d, c)
            elif pc == ADD:
                assert a == WRITER
                lines.append(text(d))
                finish(len(lines) - 1)
            elif not any(method["start"] <= pc < method["end"] for method in allowed):
                raise AssertionError(f"Unexpected original execution at {pc:#x}")
            elif pc == self.methods["percent"]["start"]:
                original_percent_calls.append(a)

        u.hook_add(UC_HOOK_CODE, intercept)
        stack = 0x21008000
        put(stack, RETURN)
        put(stack + 4, RESULT)
        u.reg_write(ESP, stack)
        u.reg_write(EAX, DOC)
        u.reg_write(EDX, WRITER if kind == "fan_body" else LEVEL)
        u.reg_write(ECX, UNIT)
        u.emu_start(self.methods[kind]["start"], RETURN, count=20000)
        if u.reg_read(EIP) != RETURN:
            raise AssertionError("Original special-output method did not return")
        result = {"leaf_calls": leaf_calls}
        if kind == "fan_body":
            result.update(lines=lines, original_percent_inputs=original_percent_calls)
        else:
            result["html"] = text(get(RESULT))
        return result


def fan_cases():
    labels = {"off": "Off <&>", "low": "Low <&>", "medium": "Medium <&>", "high": "High <&>"}
    return [{"name": name, "is_master": master, "has_master": has_master,
             "low_med": low, "med_high": high, "labels": labels}
            for name, master, has_master, low, high in (
                ("master-85-170", True, False, 85, 170),
                ("standalone-collapsed-0-0", False, False, 0, 0),
                ("standalone-equal-100-100", False, False, 100, 100),
                ("standalone-reversed-200-50", False, False, 200, 50),
                ("standalone-high-255", False, False, 85, 255),
                ("slave-no-speed-table", False, True, 85, 170))]


def inspect(executable: Path, mapping: Path) -> dict:
    probe = OriginalSpecialOutputsProbe(executable, mapping)
    fans = [{**case, **probe.run(case, "fan_body")} for case in fan_cases()]
    actions = []
    for mask in range(4):
        case = {"name": f"error-action-{mask}", "report_match": bool(mask & 1), "clear_match": bool(mask & 2)}
        observation = probe.run(case, "error_action")
        expected = ("<li />Trigger Error Report" if case["report_match"] else "")
        expected += "<li />Trigger Error Report Clear" if case["clear_match"] else ""
        assert observation["html"] == expected
        actions.append({**case, **observation})
    assert all(row["lines"][0] == INHERITED_MARKER for row in fans)
    assert not any("<table" in line for line in fans[-1]["lines"])
    return {
        "format": "cbus-project-documentor-special-outputs-original-leaf-v1",
        "exe_sha256": EXE_SHA256, "map_sha256": MAP_SHA256,
        "original_methods_executed": True, "original_loader_executed": False,
        "original_generated_page_compared": False,
        "boundary": "Original Fan DocumentHTML and LevelToPercent instructions; inherited Output documentor, class test, role/threshold/label getters, DisplayHTMLUnit, TStringList and Delphi string operations are synthetic leaves. Original ErrorReportOutput ActionSelectorUse instructions use synthetic object-identity getters and a synthetic empty inherited action. No original loader, generated project page, GUI, network or hardware.",
        "methods": {key: {"symbol": METHODS[key], "start": hex(method["start"]),
                          "end": hex(method["end"]), "sha256": method["sha256"]}
                    for key, method in probe.methods.items()},
        "fan_cases": fans, "error_action_cases": actions,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.exe, args.map)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"fan_cases": len(result["fan_cases"]), "error_action_cases": len(result["error_action_cases"])}))
