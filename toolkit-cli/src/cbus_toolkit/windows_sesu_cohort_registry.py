"""Explicitly owned HKCU Registry32 storage for SESU rollout branch studies.

This adapter cannot address the vendor updater's registry location. The
retained original probe changed both of its static names before invocation.
"""
from __future__ import annotations

import os
import re

from .toolkit_update_rollout_registry import CohortRegistryRead


_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z", re.ASCII)


class WindowsSesuCohortRegistry:
    """Read/write one caller-named scratch key, never the updater's key."""

    def __init__(self, owned_namespace: str, *, ensure_owned_key: bool = False):
        if type(owned_namespace) is not str or not _NAMESPACE.fullmatch(owned_namespace):
            raise ValueError("owned_namespace must be a simple lowercase owned identifier")
        if os.name != "nt":
            raise RuntimeError("owned SESU cohort registry access requires Windows")
        if type(ensure_owned_key) is not bool:
            raise ValueError("ensure_owned_key must be Boolean")
        import winreg
        self._winreg = winreg
        self.owned_namespace = owned_namespace
        self.path = ("Software\\CBusToolkitCli\\Tests\\" + owned_namespace
                     + "\\SESUVisibility")
        self.entry = "Cohort"
        self.ensure_on_read = ensure_owned_key

    def ensure_owned_key(self) -> None:
        """Explicitly create the scratch key, preserving any existing value."""
        w = self._winreg
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, self.path, 0,
                           w.KEY_QUERY_VALUE | w.KEY_SET_VALUE | w.KEY_WOW64_32KEY):
            pass

    def read(self) -> CohortRegistryRead:
        w = self._winreg
        if self.ensure_on_read:
            self.ensure_owned_key()
        try:
            handle = w.OpenKey(w.HKEY_CURRENT_USER, self.path, 0,
                               w.KEY_QUERY_VALUE | w.KEY_SET_VALUE | w.KEY_WOW64_32KEY)
        except FileNotFoundError:
            return CohortRegistryRead("key_absent")
        with handle:
            try:
                value, kind = w.QueryValueEx(handle, self.entry)
            except FileNotFoundError:
                return CohortRegistryRead("entry_absent")
        if kind == w.REG_SZ:
            return CohortRegistryRead("present", "REG_SZ", value)
        if kind == w.REG_DWORD:
            return CohortRegistryRead("present", "REG_DWORD", value)
        return CohortRegistryRead("present", f"REG_{kind}")

    def write_decimal(self, value: str) -> None:
        if (type(value) is not str or not re.fullmatch(r"(?:[0-9]|[1-9][0-9])", value)):
            raise ValueError("sampled cohort must be a canonical decimal string in 0..99")
        w = self._winreg
        with w.OpenKey(w.HKEY_CURRENT_USER, self.path, 0,
                       w.KEY_SET_VALUE | w.KEY_WOW64_32KEY) as handle:
            w.SetValueEx(handle, self.entry, 0, w.REG_SZ, value)
