"""One bounded original x86 preference-manager load pair in an owned Windows guest.

This research probe executes the pinned original manager instructions through the
historical Unicorn fixture. Its registry boundary uses this process's Registry32
provider; the Delphi runtime, allocation, and exception delivery remain fixtures.
It is not a native GUI or full Toolkit startup probe.
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import winreg

ROOT = Path(r"C:\CBusCliOracle118-88d8")
EXE_SHA = "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab"
KEY = r"Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0"


def _load_modules():
    stage = ROOT / "p902-original"
    for path in (stage / "site", stage / "toolkit-preferences",
                 stage / "toolkit-preferences" / "persistence"):
        sys.path.insert(0, str(path))
    from persistence_probe import Probe  # noqa: PLC0415
    source = ROOT / "p902-original-backup.py"
    spec = importlib.util.spec_from_file_location("p902_original_backup", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Owned backup source unavailable")
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    return Probe, backup


def _read(hive, name):
    try:
        with winreg.OpenKey(hive, KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            return winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None


def _user_context():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.ProcessIdToSessionId.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    kernel.WTSGetActiveConsoleSessionId.restype = ctypes.c_uint32
    session = ctypes.c_uint32()
    if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    if session.value == 0 or session.value != kernel.WTSGetActiveConsoleSessionId():
        raise RuntimeError("Original probe requires the active console user")
    return session.value


def run(tag: str) -> dict:
    Probe, backup = _load_modules()
    if backup.original_toolkit_process_present():
        raise RuntimeError("An original Toolkit process is already running")
    if hashlib.sha256((ROOT / "vendor" / "CBusToolkit.exe").read_bytes()).hexdigest() != EXE_SHA:
        raise RuntimeError("Original executable changed")
    if _read(winreg.HKEY_LOCAL_MACHINE, "ShowProjectManager") is not None:
        raise RuntimeError("Selected case requires missing HKLM ShowProjectManager")

    class LiveProbe(Probe):
        def hook(self, machine, address, size, data):
            if address not in (0x783cac, 0x783d10, 0x783bc4):
                return super().hook(machine, address, size, data)
            from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EDX,
                                           UC_X86_REG_ECX, UC_X86_REG_ESP)
            eax, edx, ecx, esp = (machine.reg_read(reg) for reg in
                                   (UC_X86_REG_EAX, UC_X86_REG_EDX,
                                    UC_X86_REG_ECX, UC_X86_REG_ESP))
            hive = winreg.HKEY_CURRENT_USER if eax == 0x80000001 else winreg.HKEY_LOCAL_MACHINE
            key_path = self.read(edx).strip("\\")
            if key_path not in (KEY, r"Software\Schneider Electric\C-Gate\CurrentVersion"):
                raise RuntimeError("Unexpected original preference key")
            if address == 0x783cac:
                if hive != winreg.HKEY_CURRENT_USER:
                    raise RuntimeError("Unexpected machine-hive default write")
                with winreg.CreateKeyEx(hive, key_path, 0,
                                        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "")
                self.trace.append({"call": "create-key", "hive": hex(eax),
                                   "key": key_path, "phase": self.phase, "provider": "Registry32"})
                self.ret()
                return
            name = self.read(ecx)
            if name != "ShowProjectManager" or key_path != KEY:
                raise RuntimeError("Unexpected preference identity")
            if address == 0x783d10:
                if self.get(esp + 4) != 1:
                    raise RuntimeError("Unexpected read type")
                value = _read(hive, name)
                self.trace.append({"call": "read", "hive": hex(eax), "name": name,
                                   "present": value is not None, "phase": self.phase,
                                   "provider": "Registry32"})
                if value is None:
                    self.fail()
                    return
                text, kind = value
                if kind != winreg.REG_SZ or type(text) is not str:
                    raise RuntimeError("Unexpected stored type")
                self.put(self.get(esp + 8), self.text(text))
                self.ret(12)
                return
            if hive != winreg.HKEY_CURRENT_USER:
                raise RuntimeError("Unexpected machine-hive preference write")
            length, ptr, kind = self.get(esp + 4), self.get(esp + 8), self.get(esp + 12) & 255
            raw = bytes(machine.mem_read(ptr, length))
            if kind != winreg.REG_SZ or raw != "True\0".encode("utf-16-le"):
                raise RuntimeError("Unexpected original write bytes")
            with winreg.CreateKeyEx(hive, key_path, 0,
                                    winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY) as key:
                winreg.SetValueEx(key, name, 0, kind, "True")
            self.trace.append({"call": "write", "hive": hex(eax), "name": name,
                               "value": "True", "utf16le_hex": raw.hex(),
                               "phase": self.phase, "provider": "Registry32"})
            self.ret(16)

    result = {"format": "cbus-p902-original-same-instance-registry32-v1",
              "complete": False, "session": _user_context(),
              "original_executable_sha256": EXE_SHA, "registry_backup_verified": False}
    records = backup.backup(tag)
    result["backup_export_count"] = sum(row["present"] for row in records)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY) as key:
            try:
                winreg.DeleteValue(key, "ShowProjectManager")
            except FileNotFoundError:
                pass
        if _read(winreg.HKEY_CURRENT_USER, "ShowProjectManager") is not None:
            raise RuntimeError("Missing-value seed did not hold")
        probe = LiveProbe()
        probe.initialize()
        names = [row["name"] for row in probe.snapshot()]
        probe.items = [probe.items[names.index("ShowProjectManager")]]
        result["initial"] = probe.snapshot()[0]["value"]
        probe.call(0x851ae4, "first-load", probe.manager)
        result["first"] = probe.snapshot()[0]["value"]
        result["stored_after_first"] = _read(winreg.HKEY_CURRENT_USER, "ShowProjectManager")
        probe.call(0x851ae4, "second-load", probe.manager)
        result["second"] = probe.snapshot()[0]["value"]
        result["trace"] = probe.trace
        result["selected_case_passed"] = (result["initial"] is False and
            result["first"] is False and result["second"] is True and
            result["stored_after_first"] == ("True", winreg.REG_SZ))
    except BaseException as error:
        result["error_type"] = type(error).__name__
        result["error_message"] = str(error)[:200]
    finally:
        try:
            result["registry_backup_verified"] = (backup.hkcu_unchanged(records) or
                                                   backup.restore_hkcu(records))
            result["hklm_unchanged"] = all(
                backup.tree_hash(row["hive"], row["path"]) == row["before_sha256"]
                for row in records if row["hive"] == "HKLM")
        except BaseException as error:
            result["restore_error_type"] = type(error).__name__
        result["complete"] = (result.get("selected_case_passed") is True and
                              result.get("registry_backup_verified") is True and
                              result.get("hklm_unchanged") is True and
                              "error_type" not in result)
        if result["registry_backup_verified"] and result.get("hklm_unchanged"):
            for row in records:
                Path(row["backup_path"]).unlink(missing_ok=True)
            result["backup_exports_removed"] = all(
                not Path(row["backup_path"]).exists() for row in records)
            result["complete"] = result["complete"] and result["backup_exports_removed"]
    return result


def main() -> int:
    tag, path = sys.argv[1:]
    try:
        result = run(tag)
    except BaseException as error:
        result = {"format": "cbus-p902-original-same-instance-registry32-v1",
                  "complete": False, "preparation_error_type": type(error).__name__,
                  "preparation_error_message": str(error)[:200]}
    Path(path).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
