"""Pin Toolkit 1.18.0.2754 barcode-scanner rules to the original x86 executable.

Supply the original EXE and MAP explicitly; both are hash checked. The static
pass disassembles the barcode routines, requires their branch constants,
literals and resource strings to equal ``cbus_toolkit.barcode_scanner`` and
records the negative PICED search. The dynamic pass runs the unchanged original
instructions of TfrmBarcode.FormKeyPress/Timer1Timer, IsSerialNumber,
ProcessBarCode, AddUnitByCatalogCode, GetDisplayableSerialNumber,
FormatSerialNumber, SetSerialNumber and TCBUSUnitManager.UnitBySerialNumber
under Unicorn. Delphi runtime string helpers, dialogs, the tree view, the unit
catalogue and project objects are Python fixtures at their call boundaries; the
receipt names every fixture. Only hashes, addresses and short identifiers are
recorded, never instruction bytes.

    python research/barcode_scanner_original.py EXE MAP --output receipt.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EFLAGS,
                               UC_X86_REG_EIP, UC_X86_REG_ESP)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))
from cbus_toolkit import barcode_scanner as model  # noqa: E402
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402

FORMAT = "cbus-toolkit-barcode-scanner-original-v1"
METHODS = (
    "CIS_tfrmBarcode.TfrmBarcode.FormKeyPress",
    "CIS_tfrmBarcode.TfrmBarcode.FormKeyDown",
    "CIS_tfrmBarcode.TfrmBarcode.Timer1Timer",
    "CIS_tfrmBarcode.TfrmBarcode.UserAfterShow",
    "CIS_TApplicationManager.TApplicationManager.AcquireBarCode",
    "CIS_TfrmKipperMain.TfrmKipperMain.FormKeyDown",
    "CIS_TfrmKipperMain.TfrmKipperMain.AcquireBarcodeFromScanner",
    "CIS_TfrmKipperMain.TfrmKipperMain.ProcessBarCode",
    "CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode",
    "CIS_TfrmKipperMain.TfrmKipperMain.HandleScannedSerialNumber",
    "CIS_TfrmKipperMain.TfrmKipperMain.AddUnit",
    "CIS_TfrmKipperMain.TfrmKipperMain.SetupUnitData",
    "CIS_TfrmSoftwareLabel.IsSerialNumber",
    "CIS_TfrmSoftwareLabel.ShowWrongBarCodeForm",
    "CIS_TfrmCBusUnitBase.TfrmCBusUnitBase.FormKeyDown",
    "CIS_TfrmUnitIDBase.TfrmUnitIDBase.StartBarcodeScan",
    "CIS_TfrmUnitIDBase.TfrmUnitIDBase.ProcessScannedBarCode",
    "CIS_TddCBusUnit.TddCBusUnit.StartBarCodeScan",
    "CIS_TddCBusUnit.TddCBusUnit.ProcessScannedBarCode",
    "CIS_TfrmGetTagName.TfrmGetTagName.FormActivate",
    "CIS_TfrmGetTagName.TfrmGetTagName.btnOKClick",
    "CIS_TUnitType.TUnitTypeManager.FindUnitByCatalogCode",
    "CIS_TUnitType.TUnitType.HasCatalogNumberInAlternates",
    "CIS_TUnitType.TUnitTypeManager.AddAlternativeCatalogNumberUnits",
    "CIS_TUnitType.TUnitTypeManager.GetDefaultFirmwareForType",
    "CIS_TUnitType.TUnitType.CalcCategoryAndFamilyName",
    "CIS_TCommonCBus.TCBUSUnitManager.GetNextAvailableAddress",
    "CIS_TCommonCBus.TCBUSUnitManager.GetMaximumPossibleAddress",
    "CIS_TCommonCBus.TCBUSUnitManager.UnitBySerialNumber",
    "CIS_TCommonCBus.TCBUSUnit.SetSerialNumber",
    "CIS_CBus.GetDisplayableSerialNumber",
    "CIS_CBus.FormatSerialNumber",
)
# (method, mnemonic, operands) that carry each recovered constant.
MARKERS = (
    ("CIS_tfrmBarcode.TfrmBarcode.FormKeyPress", "cmp", "ax, 0xd"),
    ("CIS_tfrmBarcode.TfrmBarcode.FormKeyDown", "cmp", "word ptr [eax], 0xd"),
    ("CIS_tfrmBarcode.TfrmBarcode.Timer1Timer", "cmp", "eax, 0x4b"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.FormKeyDown", "cmp", "word ptr [eax], 0x79"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.FormKeyDown", "mov", "edx, 0x8fc"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.ProcessBarCode", "cmp", "dword ptr [ebp - 0xc], 0x1c"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode", "mov", "ecx, 0x10"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode", "mov", "edx, 0x11"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode", "cmp", "eax, 0xff"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode", "mov", "edx, 0x833"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode", "mov", "edx, 0x812"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode", "mov", "edx, 0xb05f"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode", "mov", "edx, 0xb060"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.HandleScannedSerialNumber", "mov", "edx, 0x830"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnit", "cmp", "eax, 0x64"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnit", "mov", "edx, 0x8df"),
    ("CIS_TfrmKipperMain.TfrmKipperMain.AddUnit", "mov", "edx, 0x832"),
    ("CIS_TfrmSoftwareLabel.IsSerialNumber", "cmp", "dword ptr [ebp - 0x10], 0xa"),
    ("CIS_TfrmSoftwareLabel.IsSerialNumber", "cmp", "dword ptr [ebp - 0x20], 0xc"),
    ("CIS_TfrmSoftwareLabel.IsSerialNumber", "cmp", "dword ptr [ebp - 0x24], 0x1c"),
    ("CIS_TfrmSoftwareLabel.IsSerialNumber", "mov", "edx, 0x866"),
    ("CIS_TfrmCBusUnitBase.TfrmCBusUnitBase.FormKeyDown", "cmp", "word ptr [eax], 0x79"),
    ("CIS_TfrmGetTagName.TfrmGetTagName.FormActivate", "cmp", "dword ptr [ebp - 8], 0xff"),
    ("CIS_TCommonCBus.TCBUSUnitManager.GetNextAvailableAddress", "mov", "dword ptr [ebp - 0xc], 1"),
    ("CIS_TCommonCBus.TCBUSUnitManager.GetMaximumPossibleAddress", "mov", "dword ptr [ebp - 8], 0xff"),
)
LITERALS = {  # UTF-16 literals in instruction order, excluding the "WHITE" dialog style.
    "CIS_TfrmSoftwareLabel.IsSerialNumber": [model.RETAIL_PREFIX, " ", "OK"],
    "CIS_TfrmKipperMain.TfrmKipperMain.ProcessBarCode": [model.SERIAL_LOOKUP_PREFIX],
    "CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode": [
        ",", model.COMMA_SUBSTITUTE, "-", "-", ",", ",", " ", " ", "wireless", "wireless",
        model.MESSAGES[2066]],
    "CIS_TfrmKipperMain.TfrmKipperMain.AddUnit": [
        model.NEW_UNIT_STATE, model.DEFAULT_NAME, model.DEFAULT_NAME, "Database", "ProjectSave", "Unit"],
    "CIS_CBus.GetDisplayableSerialNumber": list(model.UNIDENTIFIED_SERIALS),
    "CIS_TUnitType.TUnitTypeManager.GetDefaultFirmwareForType": [model.DEFAULT_FIRMWARE],
}
# Error registrations: id -> resource string, from CIS_TKipperErrors and CIS_CBusErrors.
REGISTRATIONS = ("CIS_TKipperErrors.CIS_TKipperErrors", "CIS_CBusErrors.CIS_CBusErrors")
REGISTER_CALLS = (0x7D9898, 0x7D9910)
DIALOG_RESOURCE = 0x13C3CBC  # PResStringRec used by IsSerialNumber's wrong-barcode form.
PICED_PATTERN = re.compile(rb"(?i)p\x00i\x00c\x00e\x00d\x00")

# Runtime helper entry points hooked as fixtures.
RTL = {
    0x60890C: "UStrAddRef", 0x608914: "UStrClr", 0x60891C: "UStrArrayClr", 0x608924: "UStrAsg",
    0x608978: "UStrLAsg", 0x609114: "UStrCopy", 0x6090AC: "UStrEqual", 0x6094D4: "Pos",
    0x623ECC: "StringReplace", 0x781F58: "StrBefore", 0x618F9C: "Trim", 0x608AA0: "UStrFromWChar",
    0x608D48: "UStrCat", 0x608E08: "UStrCat3", 0x608EEC: "UStrCatN", 0x608CA4: "UStrLen",
    0x60C470: "LoadResString", 0x60E610: "GetTickCount", 0x606414: "IsClass", 0x62F578: "VarFromUStr",
    0x629F1C: "VarClr",
}
ORIGINAL_SYMBOLS = {
    "FormKeyPress": "CIS_tfrmBarcode.TfrmBarcode.FormKeyPress",
    "Timer1Timer": "CIS_tfrmBarcode.TfrmBarcode.Timer1Timer",
    "IsSerialNumber": "CIS_TfrmSoftwareLabel.IsSerialNumber",
    "ProcessBarCode": "CIS_TfrmKipperMain.TfrmKipperMain.ProcessBarCode",
    "AddUnitByCatalogCode": "CIS_TfrmKipperMain.TfrmKipperMain.AddUnitByCatalogCode",
    "CopyTrim": "CIS_Strings.CopyTrim",
    "GetDisplayableSerialNumber": "CIS_CBus.GetDisplayableSerialNumber",
    "FormatSerialNumber": "CIS_CBus.FormatSerialNumber",
    "SetSerialNumber": "CIS_TCommonCBus.TCBUSUnit.SetSerialNumber",
    "UnitBySerialNumber": "CIS_TCommonCBus.TCBUSUnitManager.UnitBySerialNumber",
    "DisplayableSerialNumber": "CIS_TCommonCBus.TCBUSUnit.DisplayableSerialNumber",
}
ORIGINAL: dict[str, tuple[int, int]] = {}
STOP = 0x30000000
STUBS = 0x50000000


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


HANDLE_ON_EXCEPTION = 0x606A9C


def _sweep(image: _Image, start: int, end: int) -> list[tuple[int, str, str]]:
    """Linear sweep that steps over Delphi except-handler tables after HandleOnException."""
    raw = image.pe.get_data(start - image.base, end - start)
    result, position = [], 0
    while position < len(raw):
        progressed = False
        for instruction in image.decoder.disasm(raw[position:], start + position):
            result.append((instruction.address, instruction.mnemonic, instruction.op_str))
            position = instruction.address + instruction.size - start
            progressed = True
            if instruction.mnemonic == "jmp" and instruction.op_str == f"{HANDLE_ON_EXCEPTION:#x}":
                count = struct.unpack_from("<I", raw, position)[0]
                if count > 16:
                    raise ValueError(f"Implausible except table at {start + position:#x}")
                position += 4 + 8 * count
                break
        if not progressed:
            position += 1
    return result


class _Emulator:
    """One fresh Unicorn instance per vector; Delphi UnicodeStrings are fixtures."""

    def __init__(self, image: _Image, fixtures: dict[int, object]) -> None:
        self.image, self.fixtures = image, fixtures
        memory = image.pe.get_memory_mapped_image()
        self.u = u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(image.base, (len(memory) + 0xFFF) & ~0xFFF)
        u.mem_write(image.base, memory)
        for address, size in ((0, 0x1000), (0x10000000, 0x400000), (0x20000000, 0x40000), (STOP, 0x1000), (STUBS, 0x10000)):
            u.mem_map(address, size)
        self.heap, self.trace, self.executed = 0x10000000, [], set()
        u.hook_add(UC_HOOK_CODE, self._hook)

    # -- memory helpers
    def alloc(self, size: int) -> int:
        address = self.heap
        self.heap = (self.heap + size + 15) & ~15
        return address

    def get(self, address: int) -> int:
        return struct.unpack("<I", self.u.mem_read(address, 4))[0]

    def put(self, address: int, value: int) -> None:
        self.u.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def string(self, value: str) -> int:
        if not value:
            return 0
        raw = value.encode("utf-16-le")
        address = self.alloc(len(raw) + 14)
        self.u.mem_write(address, struct.pack("<HHiI", 1200, 2, -1, len(raw) // 2) + raw + b"\0\0")
        return address + 12

    def read(self, address: int) -> str:
        if not address:
            return ""
        length = self.get(address - 4)
        assert length <= 4096
        return bytes(self.u.mem_read(address, length * 2)).decode("utf-16-le")

    def reg(self, name: int) -> int:
        return self.u.reg_read(name)

    def ret(self, value: int | None = None, pop: int = 0, zero: bool | None = None) -> None:
        esp = self.reg(UC_X86_REG_ESP)
        if value is not None:
            self.u.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)
        if zero is not None:
            flags = self.reg(UC_X86_REG_EFLAGS)
            self.u.reg_write(UC_X86_REG_EFLAGS, flags | 0x40 if zero else flags & ~0x40)
        self.u.reg_write(UC_X86_REG_EIP, self.get(esp))
        self.u.reg_write(UC_X86_REG_ESP, esp + 4 + pop)

    # -- dispatch
    def _hook(self, _u, address: int, _size: int, _data) -> None:
        if address in RTL:
            return self._rtl(RTL[address])
        if address in self.fixtures:
            self.trace.append(address)
            return self.fixtures[address](self)
        if not any(start <= address < end for start, end in ORIGINAL.values()):
            raise AssertionError(f"unexpected original execution at {address:#x}")
        self.executed.add(address)

    def _rtl(self, name: str) -> None:
        eax, edx, ecx = self.reg(UC_X86_REG_EAX), self.reg(UC_X86_REG_EDX), self.reg(UC_X86_REG_ECX)
        esp = self.reg(UC_X86_REG_ESP)
        if name == "UStrAddRef":
            return self.ret()
        if name == "UStrClr":
            self.put(eax, 0)
            return self.ret(eax)
        if name == "UStrArrayClr":
            for index in range(edx):
                self.put(eax + 4 * index, 0)
            return self.ret()
        if name in ("UStrAsg", "UStrLAsg"):
            self.put(eax, edx)
            return self.ret()
        if name == "UStrCopy":
            text, index, count = self.read(eax), edx if edx < 0x80000000 else edx - 2**32, ecx if ecx < 0x80000000 else ecx - 2**32
            index = max(index, 1)
            count = max(0, min(count, len(text) - index + 1))
            self.put(self.get(esp + 4), self.string(text[index - 1:index - 1 + count]))
            return self.ret(pop=4)
        if name == "UStrEqual":
            return self.ret(zero=self.read(eax) == self.read(edx))
        if name == "Pos":
            sub, text = self.read(eax), self.read(edx)
            return self.ret(text.find(sub) + 1 if sub and text else 0)
        if name == "StringReplace":
            text, old, new = self.read(eax), self.read(edx), self.read(ecx)
            flags = self.get(esp + 8) & 0xFF
            assert flags == 1, "only [rfReplaceAll] is used by the pinned callers"
            self.put(self.get(esp + 4), self.string(text.replace(old, new)))
            return self.ret(pop=8)
        if name == "StrBefore":
            sub, text = self.read(eax), self.read(edx)
            position = text.find(sub)
            self.put(ecx, self.string(text[:position] if position >= 0 else text))
            return self.ret()
        if name == "Trim":
            self.put(edx, self.string(model._delphi_trim(self.read(eax))))
            return self.ret()
        if name == "UStrFromWChar":
            self.put(eax, self.string(chr(edx & 0xFFFF)))
            return self.ret()
        if name == "UStrCat":
            self.put(eax, self.string(self.read(self.get(eax)) + self.read(edx)))
            return self.ret()
        if name == "UStrCat3":
            self.put(eax, self.string(self.read(edx) + self.read(ecx)))
            return self.ret()
        if name == "UStrCatN":
            parts = [self.read(self.get(esp + 4 * index)) for index in range(edx, 0, -1)]
            self.put(eax, self.string("".join(parts)))
            return self.ret(pop=4 * edx)
        if name == "UStrLen":
            return self.ret(self.get(eax - 4) if eax else 0)
        if name == "LoadResString":
            text = self.image.resource(eax)
            assert text is not None
            self.put(edx, self.string(text))
            return self.ret()
        if name == "GetTickCount":
            return self.ret(self.fixtures["tick"]())
        if name == "IsClass":
            return self.ret(int(self.fixtures["is_class"](eax, edx)))
        if name == "VarFromUStr":
            self.put(eax, 0x100)
            self.put(eax + 8, edx)
            return self.ret()
        if name == "VarClr":
            return self.ret()
        raise AssertionError(name)

    def run(self, start: int, registers: dict[int, int], stack: list[int] = ()) -> int:
        esp = 0x20030000 - 4 * len(stack)
        for index, value in enumerate(stack):
            self.put(esp + 4 + 4 * index, value)
        self.put(esp, STOP)
        self.u.reg_write(UC_X86_REG_ESP, esp)
        for register, value in registers.items():
            self.u.reg_write(register, value)
        self.u.emu_start(start, STOP, timeout=5_000_000, count=500_000)
        assert self.reg(UC_X86_REG_EIP) == STOP
        return self.reg(UC_X86_REG_EAX)


def _stub(emulator: _Emulator, handler) -> int:
    """Allocate an address in the stub page that dispatches to a Python handler."""
    address = STUBS + 16 * len([key for key in emulator.fixtures if isinstance(key, int) and key >= STUBS])
    emulator.fixtures[address] = handler
    return address


def _vtable_object(emulator: _Emulator, slots: dict[int, object], fields: dict[int, int] | None = None) -> int:
    table, instance = emulator.alloc(0x200), emulator.alloc(0x200)
    for offset, handler in slots.items():
        emulator.put(table + offset, _stub(emulator, handler))
    emulator.put(instance, table)
    for offset, value in (fields or {}).items():
        emulator.put(instance + offset, value)
    return instance


def _string_attribute(emulator: _Emulator, value_ref: list[str], writes: list | None = None) -> int:
    def getter(e: _Emulator) -> None:
        e.put(e.reg(UC_X86_REG_EDX), e.string(value_ref[0]))
        e.ret()

    def setter(e: _Emulator) -> None:
        variant = e.reg(UC_X86_REG_EDX)
        assert e.get(variant) == 0x100
        value_ref[0] = e.read(e.get(variant + 8))
        if writes is not None:
            writes.append(value_ref[0])
        e.ret()

    return _vtable_object(emulator, {0x2C: getter, 0x7C: setter})


# ---------------------------------------------------------------------------
# Dynamic vectors

def keystrokes(image: _Image, events: list[tuple[str, str | None, int]]) -> dict:
    """Original FormKeyPress / Timer1Timer over a key and timer event list."""
    now = [0]
    e = _Emulator(image, {"tick": lambda: now[0], "is_class": lambda *_: False})
    form = e.alloc(0x400)
    for kind, value, tick in events:
        now[0] = tick
        if kind == "key":
            key = e.alloc(4)
            e.u.mem_write(key, struct.pack("<H", ord(value)))
            e.run(ORIGINAL["FormKeyPress"][0], {UC_X86_REG_EAX: form, UC_X86_REG_EDX: form, UC_X86_REG_ECX: key})
        else:
            e.run(ORIGINAL["Timer1Timer"][0], {UC_X86_REG_EAX: form, UC_X86_REG_EDX: form})
            if e.get(form + 0x2B8) == 1:
                break
    return {"events": [list(item) for item in events], "buffer": e.read(e.get(form + 0x39C)),
            "last_tick": e.get(form + 0x3A0), "modal_result": e.get(form + 0x2B8)}


def is_serial_number(image: _Image, barcode: str) -> dict:
    wrong, errors = [], []

    def show_wrong(e: _Emulator) -> None:
        wrong.append(e.read(e.reg(UC_X86_REG_EAX)))
        e.ret()

    def cis_error(e: _Emulator) -> None:
        errors.append(e.reg(UC_X86_REG_EDX))
        e.ret(pop=12)

    e = _Emulator(image, {0xD90710: show_wrong, 0x7D9B54: cis_error, "tick": lambda: 0, "is_class": lambda *_: False})
    out = e.alloc(4)
    accepted = e.run(ORIGINAL["IsSerialNumber"][0], {UC_X86_REG_EAX: e.string(barcode), UC_X86_REG_EDX: out}) & 0xFF
    return {"input": barcode, "accepted": bool(accepted), "serial": e.read(e.get(out)),
            "wrong_barcode_form": wrong, "message_ids": errors}


def process_barcode(image: _Image, barcode: str) -> dict:
    calls = []

    def add(e: _Emulator) -> None:
        calls.append({"call": "AddUnitByCatalogCode", "text": e.read(e.reg(UC_X86_REG_EDX))})
        e.ret()

    def handle(e: _Emulator) -> None:
        calls.append({"call": "HandleScannedSerialNumber", "serial": e.read(e.reg(UC_X86_REG_EDX)),
                      "report_missing": bool(e.reg(UC_X86_REG_ECX) & 0xFF)})
        e.ret(0)

    e = _Emulator(image, {0xEA165C: add, 0xEA1FF4: handle, "tick": lambda: 0, "is_class": lambda *_: False})
    e.run(ORIGINAL["ProcessBarCode"][0], {UC_X86_REG_EAX: e.alloc(0x600), UC_X86_REG_EDX: e.string(barcode)})
    return {"input": barcode, "calls": calls}


def add_by_catalog_code(image: _Image, barcode: str, *, site_open: bool = True, serial_found: bool = False,
                        type_known: bool = True, units_node: bool = True, unit_count: int = 0,
                        network_wireless: bool = False, network_wired: bool = True,
                        family: str = "Wired") -> dict:
    """Original AddUnitByCatalogCode with project, tree and catalogue fixtures."""
    calls, errors = [], []
    fixtures: dict = {"tick": lambda: 0}
    e = _Emulator(image, fixtures)
    element, network, unit_type = e.alloc(0x100), e.alloc(0x100), 0

    def site(e: _Emulator) -> None:
        e.ret(int(site_open))

    def handle(e: _Emulator) -> None:
        calls.append({"call": "HandleScannedSerialNumber", "serial": e.read(e.reg(UC_X86_REG_EDX)),
                      "report_missing": bool(e.reg(UC_X86_REG_ECX) & 0xFF)})
        e.ret(int(serial_found))

    def find(e: _Emulator) -> None:
        calls.append({"call": "FindUnitByCatalogCode", "catalog": e.read(e.reg(UC_X86_REG_EDX))})
        e.ret(unit_type if type_known else 0)

    def selected(e: _Emulator) -> None:
        e.ret(element_object)

    def get_network(e: _Emulator) -> None:
        e.ret(network)

    def cis_error(pop: int):
        def handler(e: _Emulator) -> None:
            errors.append(e.reg(UC_X86_REG_EDX))
            e.ret(pop=pop)
        return handler

    def lower(e: _Emulator) -> None:
        e.put(e.reg(UC_X86_REG_EDX), e.string(family.lower()))
        e.ret()

    def add_unit(e: _Emulator) -> None:
        calls.append({"call": "AddUnit", "serial": e.read(e.reg(UC_X86_REG_EDX)),
                      "unit_type": e.read(e.reg(UC_X86_REG_ECX)),
                      "catalog_number": e.read(e.get(e.reg(UC_X86_REG_ESP) + 4))})
        e.ret(pop=4)

    element_object = _vtable_object(e, {0x58: lambda em: em.ret(unit_count)})
    code_attribute = _string_attribute(e, ["UNITCODE"])
    unit_type = _vtable_object(e, {}, {0x78: code_attribute, 0xA0: e.alloc(16)})
    self_object = e.alloc(0x600)
    manager_holder, installation = e.alloc(0x100), e.alloc(0x100)
    e.put(self_object + 0x518, installation)
    e.put(installation + 0xC4, manager_holder)
    e.put(manager_holder + 0x78, e.alloc(16))
    fixtures.update({
        0xE9C570: site, 0xEA1FF4: handle, 0xF3FFE4: find, 0xDD868C: selected, 0xF2E0B0: get_network,
        0xF2B734: lambda em: em.ret(int(network_wireless)), 0xF2B604: lambda em: em.ret(int(network_wired)),
        0x7F3A78: lower, 0x7D9D00: cis_error(4), 0x7D9B54: cis_error(12), 0xEA1A6C: add_unit,
        0xDDC2C8: lambda em: em.ret(),
        "is_class": lambda obj, _cls: obj == element_object and units_node,
    })
    e.run(ORIGINAL["AddUnitByCatalogCode"][0], {UC_X86_REG_EAX: self_object, UC_X86_REG_EDX: e.string(barcode)})
    return {"input": barcode, "fixtures": {"site_open": site_open, "serial_found": serial_found,
                                           "type_known": type_known, "units_node": units_node,
                                           "unit_count": unit_count, "network_wireless": network_wireless,
                                           "network_wired": network_wired, "family": family},
            "calls": calls, "message_ids": errors}


def displayable(image: _Image, serial: str) -> dict:
    e = _Emulator(image, {"tick": lambda: 0, "is_class": lambda *_: False})
    out = e.alloc(4)
    e.run(ORIGINAL["GetDisplayableSerialNumber"][0], {UC_X86_REG_EAX: e.string(serial), UC_X86_REG_EDX: out})
    return {"input": serial, "displayable": e.read(e.get(out))}


def set_serial(image: _Image, serial: str) -> dict:
    e = _Emulator(image, {"tick": lambda: 0, "is_class": lambda *_: False})
    stored, writes = [""], []
    unit = e.alloc(0x200)
    e.put(unit + 0xEC, _string_attribute(e, stored, writes))
    e.run(ORIGINAL["SetSerialNumber"][0], {UC_X86_REG_EAX: unit, UC_X86_REG_EDX: e.string(serial)})
    return {"input": serial, "stored": writes}


def unit_by_serial(image: _Image, serial: str, existing: list[str]) -> dict:
    e = _Emulator(image, {"tick": lambda: 0, "is_class": lambda *_: False})
    units = []
    for value in existing:
        unit = e.alloc(0x200)
        e.put(unit + 0xEC, _string_attribute(e, [value]))
        units.append(unit)
    manager = _vtable_object(e, {0x58: lambda em: em.ret(len(units))})
    e.fixtures[0xF2E08C] = lambda em: em.ret(units[em.reg(UC_X86_REG_EDX)])
    found = e.run(ORIGINAL["UnitBySerialNumber"][0], {UC_X86_REG_EAX: manager, UC_X86_REG_EDX: e.string(serial)})
    return {"input": serial, "existing": existing, "match_index": units.index(found) if found else None}


KEY_CASES = (
    [("key", "A", 0), ("key", "B", 10), ("timer", None, 80), ("timer", None, 86)],
    [("key", "1", 0), ("key", "\r", 30), ("timer", None, 100), ("timer", None, 106)],
    [("timer", None, 500)],
    [("key", "\r", 0), ("timer", None, 1000)],
    [("key", "X", 0), ("key", "\r", 10), ("key", "Y", 20), ("timer", None, 95), ("timer", None, 96)],
)
SERIAL_INPUTS = (
    "123456789012", "12345678901", "1234567890123", "1234 5678 90", "93123456789012", "9312345678",
    "931234567890", "5031NL          123456789012", "5031NL          1234 5678 90", "93" + "x" * 26,
    "5031NL          1234567890123", "", "0", "000000000000", "            ",
)
PROCESS_INPUTS = ("0123", "5031NL          123456789012", "0" * 28, "1" * 27, "0", "", "A" * 40)
CATALOG_INPUTS = (
    "5031NL          123456789012", "  5031NL-XX     000123456789 ", "L5504D1A,B      1",
    "E3031D¼X       000000000007", "AB CD           999", "                123456789012",
)
DISPLAY_INPUTS = ("1234.5", "123456789012", "0", "000000000000", "1048575.4095", "12.34.56",
                  "abc12x", "", "12345678901234", "123456789.12345", ".", "00000000.0000")


def inspect(exe_path: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe_path.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Image(exe_raw, map_raw)
    for key, symbol in ORIGINAL_SYMBOLS.items():
        method = image.method(symbol)
        ORIGINAL[key] = (method["start"], method["end"])
    methods = {name: image.method(name) for name in METHODS}
    swept = {name: _sweep(image, value["start"], value["end"]) for name, value in methods.items()}
    for name, mnemonic, operands in MARKERS:
        if (mnemonic, operands) not in {(m, o) for _, m, o in swept[name]}:
            raise ValueError(f"Missing original branch constant {mnemonic} {operands} in {name}")
    for name, expected in LITERALS.items():
        found = [text for _, _, operands in swept[name] for token in re.findall(r"0x[0-9a-f]{6,8}", operands)
                 if (text := image.literal(int(token, 16))) is not None and text != "WHITE"]
        if found != expected:
            raise ValueError(f"Unexpected original literals in {name}: {found!r}")
    registered = _registrations(image)
    for identifier, text in {**model.MESSAGES, **model.UNREFERENCED_MESSAGES}.items():
        original = registered.get(identifier)
        expected = text.replace('"{network}"', '"%1"').replace("a new Unit.", "a new %1.")
        if identifier == 2066:
            expected = "%1"  # Generic registration; AddUnitByCatalogCode passes the literal text.
        if original != expected:
            raise ValueError(f"Registered message {identifier} differs: {original!r}")
    dialog_text = image.resource(struct.unpack("<I", image.pe.get_data(DIALOG_RESOURCE - image.base, 4))[0])
    if dialog_text != model.WRONG_BARCODE_TEXT:
        raise ValueError("Wrong-barcode dialog text differs")
    piced = {
        "map_symbol_matches": sum(1 for line in map_raw.decode("ascii").splitlines() if "piced" in line.lower()),
        "exe_ascii_matches": len(re.findall(rb"(?i)piced", exe_raw)),
        "exe_utf16_matches": len(PICED_PATTERN.findall(exe_raw)),
        "resource_strings": sorted(identifier for identifier, text in image.strings.items() if "piced" in text.lower()),
    }
    vectors = {
        "keystrokes": [keystrokes(image, list(case)) for case in KEY_CASES],
        "is_serial_number": [is_serial_number(image, value) for value in SERIAL_INPUTS],
        "process_barcode": [process_barcode(image, value) for value in PROCESS_INPUTS],
        "add_by_catalog_code": [add_by_catalog_code(image, value) for value in CATALOG_INPUTS] + [
            add_by_catalog_code(image, CATALOG_INPUTS[0], site_open=False),
            add_by_catalog_code(image, CATALOG_INPUTS[0], serial_found=True),
            add_by_catalog_code(image, CATALOG_INPUTS[0], type_known=False),
            add_by_catalog_code(image, CATALOG_INPUTS[0], units_node=False),
            add_by_catalog_code(image, CATALOG_INPUTS[0], unit_count=254),
            add_by_catalog_code(image, CATALOG_INPUTS[0], unit_count=255),
            add_by_catalog_code(image, CATALOG_INPUTS[0], network_wireless=True, network_wired=False),
            add_by_catalog_code(image, CATALOG_INPUTS[0], network_wireless=True, network_wired=False, family="Wireless"),
            add_by_catalog_code(image, CATALOG_INPUTS[0], family="Wireless"),
            add_by_catalog_code(image, CATALOG_INPUTS[0], network_wireless=True, network_wired=True, family="Wireless"),
            add_by_catalog_code(image, CATALOG_INPUTS[0], network_wired=False, family="Wireless"),
        ],
        "displayable_serial": [displayable(image, value) for value in DISPLAY_INPUTS],
        "set_serial_number": [set_serial(image, value) for value in DISPLAY_INPUTS],
        "unit_by_serial_number": [
            unit_by_serial(image, "123456789012", ["1.2", "12345678.9012", "123456789012"]),
            unit_by_serial(image, "000012340005", ["1234.5"]),
            unit_by_serial(image, "000000000000", ["0.0", ""]),
            unit_by_serial(image, "1048575.4095", ["010485754095"]),
            unit_by_serial(image, "7", ["", "7.0", "0.7", "7"]),
        ],
    }
    return {
        "format": FORMAT,
        "executable_sha256": EXE_SHA256,
        "map_sha256": MAP_SHA256,
        "probe_sha256": _sha(Path(__file__).read_bytes()),
        "methods": {name: {"start": f"{value['start']:#x}", "end": f"{value['end']:#x}", "sha256": value["sha256"]}
                    for name, value in methods.items()},
        "markers": [list(item) for item in MARKERS],
        "literals": LITERALS,
        "registered_messages": {str(key): registered[key] for key in sorted({*model.MESSAGES, *model.UNREFERENCED_MESSAGES})},
        "piced_negative_search": piced,
        "fixtures": {
            "runtime": sorted(RTL.values()),
            "dialogs": ["ShowWrongBarCodeForm", "TErrorManager.CISError"],
            "objects": ["IsSiteOpen", "HandleScannedSerialNumber", "FindUnitByCatalogCode", "GetSelectedFlashElement",
                        "TCBUSUnitManager.GetNetwork/GetItem/Count", "TCBusNetwork.GetIsWireless/GetIsWired",
                        "TStringAttribute get/set/asLowerCaseString", "AddUnit", "RefreshNodeDialog"],
        },
        "vectors": vectors,
    }


def _registrations(image: _Image) -> dict[int, str]:
    """Pair each RegisterError id with the resource string loaded immediately before it."""
    result: dict[int, str] = {}
    for symbol in REGISTRATIONS:
        start = image.by_name[symbol]
        end = next(address for address in image.starts if address > start)
        raw = image.pe.get_data(start - image.base, end - start)
        last, identifier = None, None
        for instruction in image.decoder.disasm(raw, start):
            operands = instruction.op_str
            if instruction.mnemonic == "mov" and operands.startswith("eax, 0x"):
                value = int(operands.split(", ")[1], 16)
                text = image.resource(value)
                if text is None:
                    try:
                        text = image.resource(struct.unpack("<I", image.pe.get_data(value - image.base, 4))[0])
                    except Exception:  # noqa: BLE001 - not a resource pointer
                        text = None
                last = text if text is not None else last
            elif instruction.mnemonic == "push" and operands.startswith("0x"):
                literal = image.literal(int(operands, 16))
                last = literal if literal is not None else last
            elif instruction.mnemonic == "mov" and operands.startswith("edx, 0x"):
                identifier = int(operands.split(", ")[1], 16)
            elif instruction.mnemonic == "call" and operands.startswith("0x") and int(operands, 16) in REGISTER_CALLS:
                if identifier is not None and last is not None:
                    result.setdefault(identifier, last)
                last = None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", type=Path)
    parser.add_argument("map", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(inspect(args.exe, args.map), indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
