"""Windows registry adapter with raw reads for the original x86 Toolkit preference store."""
from __future__ import annotations

import os
import re

from .toolkit_preferences_store import (
    HKCU, HKLM, TOOLKIT_KEY, CGATE_KEY, DISPLAY_KEY, REG_SZ,
    RegistryValue, UnsupportedPreferenceEncoding,
)


class WindowsPreferenceRegistry:
    """Use the 32-bit registry view even under a 64-bit Python interpreter.

    Constructing this adapter opens no registry keys. ``test_namespace`` redirects
    both logical hives to separate subtrees of an owned HKCU test namespace;
    normal use leaves it unset. String writes must satisfy the Windows UTF-16
    termination contract. The adapter never deletes a key or retries a write.
    """
    def __init__(self, *, test_namespace=None):
        if os.name != 'nt':
            raise RuntimeError('Windows preference registry access requires Windows')
        if test_namespace is not None and (type(test_namespace) is not str or
                re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', test_namespace) is None):
            raise ValueError('Test namespace must be a simple owned identifier')
        import ctypes
        from ctypes import wintypes
        import winreg
        self._ctypes, self._types, self._winreg = ctypes, wintypes, winreg
        self.test_namespace = test_namespace
        api = ctypes.WinDLL('advapi32', use_last_error=True)
        self._query = api.RegQueryValueExW
        self._query.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, ctypes.c_void_p,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                               ctypes.POINTER(wintypes.DWORD)]
        self._query.restype = wintypes.LONG
        self._set = api.RegSetValueExW
        self._set.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD,
                             wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self._set.restype = wintypes.LONG
        self._set_default = api.RegSetValueW
        self._set_default.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD,
                                     wintypes.LPCWSTR, wintypes.DWORD]
        self._set_default.restype = wintypes.LONG

    def _location(self, hive, key):
        if type(hive) is not int or hive not in (HKCU, HKLM):
            raise ValueError('Preference hive must be HKCU or HKLM')
        if type(key) is not str or key not in (TOOLKIT_KEY, CGATE_KEY, DISPLAY_KEY):
            raise ValueError('Unknown Toolkit preference registry key')
        if self.test_namespace is not None:
            return HKCU, ('Software\\CBusToolkitCli\\Tests\\' + self.test_namespace +
                          ('\\HKCU\\' if hive == HKCU else '\\HKLM\\') + key)
        return hive, key

    @staticmethod
    def _name(name):
        if type(name) is not str or not name or '\0' in name or len(name) > 256:
            raise ValueError('A nonempty registry value name without NUL is required')
        try: name.encode('utf-16-le')
        except UnicodeError as error: raise ValueError('Registry value name must be valid Unicode') from error

    def read_value(self, hive, key, name):
        self._name(name)
        root, path = self._location(hive, key)
        c, w, t = self._ctypes, self._winreg, self._types
        with w.OpenKey(root, path, 0, w.KEY_QUERY_VALUE | w.KEY_WOW64_32KEY) as handle:
            # A single bounded buffer avoids a size-query/read race and preserves
            # the stored bytes, including terminators and malformed REG_SZ values.
            capacity = t.DWORD(65536)
            kind = t.DWORD()
            data = c.create_string_buffer(capacity.value)
            status = self._query(int(handle), name, None, c.byref(kind), data, c.byref(capacity))
            if status == 234:
                raise UnsupportedPreferenceEncoding('Stored registry value exceeds 65536 bytes')
            if status: raise c.WinError(status)
            if capacity.value > len(data):
                raise RuntimeError('Registry query returned an invalid byte count')
            return RegistryValue(kind.value, bytes(data[:capacity.value]))

    def write_value(self, hive, key, name, value):
        self._name(name)
        root, path = self._location(hive, key)
        if type(value) is not RegistryValue:
            raise ValueError('A validated raw RegistryValue is required')
        if value.win32_type in (1, 2, 7):
            required = 4 if value.win32_type == 7 else 2
            if len(value.data) < required or len(value.data) % 2 or not value.data.endswith(b'\0' * required):
                raise ValueError('Windows string writes require a complete UTF-16 terminator')
            try: value.data.decode('utf-16-le')
            except UnicodeError as error:
                raise ValueError('Windows string writes require valid UTF-16') from error
        c, w = self._ctypes, self._winreg
        data = c.create_string_buffer(value.data, max(1, len(value.data)))
        with w.CreateKeyEx(root, path, 0, w.KEY_SET_VALUE | w.KEY_WOW64_32KEY) as handle:
            status = self._set(int(handle), name, 0, value.win32_type, data, len(value.data))
            if status: raise c.WinError(status)

    def write_default_string(self, hive, key, value):
        root, path = self._location(hive, key)
        if type(value) is not str or value != '':
            raise ValueError('Only the original empty default-string request is supported')
        w = self._winreg
        try:
            with w.CreateKeyEx(root, path, 0, w.KEY_SET_VALUE | w.KEY_WOW64_32KEY) as handle:
                return int(self._set_default(int(handle), None, REG_SZ, value, 0))
        except OSError as error:
            if type(getattr(error, 'winerror', None)) is int:
                return error.winerror & 0xffffffff
            raise
