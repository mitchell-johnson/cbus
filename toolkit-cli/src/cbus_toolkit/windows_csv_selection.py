"""Windows 32-bit registry adapter for Toolkit's database CSV selection."""
from __future__ import annotations

import os
import re

from .toolkit_database_csv_selection import (
    CSV_SELECTION_KEY, CSV_SELECTION_VALUE, MAX_SELECTION_UTF16_UNITS,
)
from .toolkit_preferences_store import HKCU


class WindowsCSVSelectionRegistry:
    """Read and write the exact Toolkit value in the 32-bit registry view."""

    def __init__(self, *, test_namespace=None):
        if os.name != "nt":
            raise RuntimeError("Windows CSV selection registry access requires Windows")
        if test_namespace is not None and (
            type(test_namespace) is not str
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", test_namespace) is None
        ):
            raise ValueError("Test namespace must be a simple owned identifier")
        import winreg
        self._winreg = winreg
        self.test_namespace = test_namespace

    def _location(self, hive, key, name):
        if hive != HKCU or type(hive) is not int:
            raise ValueError("CSV selection hive must be HKCU")
        if key != CSV_SELECTION_KEY or type(key) is not str:
            raise ValueError("Unknown CSV selection registry key")
        if name != CSV_SELECTION_VALUE or type(name) is not str:
            raise ValueError("Unknown CSV selection registry value")
        if self.test_namespace is None:
            return HKCU, key
        return HKCU, (
            "Software\\CBusToolkitCli\\Tests\\" + self.test_namespace
            + "\\HKCU\\" + key
        )

    def read_selection(self, hive, key, name):
        root, path = self._location(hive, key, name)
        w = self._winreg
        with w.OpenKey(root, path, 0, w.KEY_QUERY_VALUE | w.KEY_WOW64_32KEY) as handle:
            value, kind = w.QueryValueEx(handle, name)
        if kind != w.REG_SZ or type(value) is not str:
            raise ValueError("Toolkit CSV selection requires REG_SZ storage")
        if "\0" in value:
            raise ValueError("Toolkit CSV selection must not contain NUL")
        try:
            units = len(value.encode("utf-16-le")) // 2
        except UnicodeError as error:
            raise ValueError("Toolkit CSV selection must contain valid Unicode") from error
        if units > MAX_SELECTION_UTF16_UNITS:
            raise ValueError("Toolkit CSV selection exceeds 32767 UTF-16 code units")
        return value

    def write_selection(self, hive, key, name, value):
        root, path = self._location(hive, key, name)
        if type(value) is not str or "\0" in value:
            raise ValueError("Toolkit CSV selection must be text without NUL")
        try:
            units = len(value.encode("utf-16-le")) // 2
        except UnicodeError as error:
            raise ValueError("Toolkit CSV selection must contain valid Unicode") from error
        if units > MAX_SELECTION_UTF16_UNITS:
            raise ValueError("Toolkit CSV selection exceeds 32767 UTF-16 code units")
        w = self._winreg
        with w.CreateKeyEx(root, path, 0, w.KEY_SET_VALUE | w.KEY_WOW64_32KEY) as handle:
            w.SetValueEx(handle, name, 0, w.REG_SZ, value)
