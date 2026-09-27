"""Windows adapter access masks and owned-path guard with an injected API."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from cbus_toolkit import windows_sesu_cohort_registry as module
from cbus_toolkit.toolkit_update_rollout_registry import CohortRegistryRead


class Handle:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class WinReg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    KEY_WOW64_32KEY = 4
    REG_SZ = 1
    REG_DWORD = 4

    def __init__(self):
        self.keys = {}
        self.calls = []

    def OpenKey(self, hive, path, reserved, rights):
        self.calls.append(("open", hive, path, reserved, rights))
        if path not in self.keys:
            raise FileNotFoundError(path)
        return Handle(path)

    def CreateKeyEx(self, hive, path, reserved, rights):
        self.calls.append(("create", hive, path, reserved, rights))
        self.keys.setdefault(path, {})
        return Handle(path)

    def QueryValueEx(self, handle, name):
        self.calls.append(("query", handle.path, name))
        if name not in self.keys[handle.path]:
            raise FileNotFoundError(name)
        return self.keys[handle.path][name]

    def SetValueEx(self, handle, name, reserved, kind, value):
        self.calls.append(("set", handle.path, name, reserved, kind, value))
        self.keys[handle.path][name] = value, kind


def adapter(monkeypatch, *, ensure=False):
    fake = WinReg()
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    return module.WindowsSesuCohortRegistry("owned-case", ensure_owned_key=ensure), fake


def test_adapter_absent_key_missing_entry_sentinel_and_write(monkeypatch):
    backend, fake = adapter(monkeypatch)
    assert backend.path == "Software\\CBusToolkitCli\\Tests\\owned-case\\SESUVisibility"
    assert backend.entry == "Cohort"
    assert backend.read() == CohortRegistryRead("key_absent")
    assert fake.calls[0] == ("open", "HKCU", backend.path, 0, 7)
    assert all("CBusToolkitCli\\Tests\\owned-case" in call[2]
               for call in fake.calls if call[0] == "open")
    backend.ensure_owned_key()
    assert fake.calls[-1] == ("create", "HKCU", backend.path, 0, 7)
    assert backend.read() == CohortRegistryRead("entry_absent")
    fake.keys[backend.path]["Cohort"] = "-1", fake.REG_SZ
    assert backend.read() == CohortRegistryRead("present", "REG_SZ", "-1")
    backend.write_decimal("87")
    assert fake.keys[backend.path]["Cohort"] == ("87", fake.REG_SZ)
    assert fake.calls[-1] == ("set", backend.path, "Cohort", 0, fake.REG_SZ, "87")


def test_adapter_ensure_is_explicit_and_preserves_existing_entry(monkeypatch):
    backend, fake = adapter(monkeypatch, ensure=True)
    assert backend.read() == CohortRegistryRead("entry_absent")
    assert fake.calls[0] == ("create", "HKCU", backend.path, 0, 7)
    fake.keys[backend.path]["Cohort"] = 41, fake.REG_DWORD
    assert backend.read() == CohortRegistryRead("present", "REG_DWORD", 41)
    assert fake.keys[backend.path]["Cohort"] == (41, fake.REG_DWORD)


@pytest.mark.parametrize("namespace", ["", "UPPER", "../other", "a\\b", "a/b", "a" * 65])
def test_adapter_rejects_nonowned_namespace_before_platform_or_io(monkeypatch, namespace):
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    with pytest.raises(ValueError, match="owned_namespace"):
        module.WindowsSesuCohortRegistry(namespace)


@pytest.mark.parametrize("value", ["-1", "00", "100", " 1", 41, True])
def test_adapter_rejects_noncanonical_write_before_io(monkeypatch, value):
    backend, fake = adapter(monkeypatch)
    with pytest.raises(ValueError, match="canonical decimal"):
        backend.write_decimal(value)
    assert fake.calls == []
