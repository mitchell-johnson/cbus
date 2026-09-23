"""Exact Windows text encoding used by Toolkit's CSV file writer."""
from __future__ import annotations

import os


CP_ACP = 0
MAX_UTF16_UNITS = 32 * 1024 * 1024


class WindowsToolkitCSVEncoder:
    """Encode Unicode through ``WideCharToMultiByte(CP_ACP, 0, ...)``.

    Toolkit 1.18 calls the no-encoding ``TStrings.SaveToFile`` overload. Its
    Delphi runtime selects ``TEncoding.Default``, which creates
    ``TMBCSEncoding`` for CP_ACP and performs this exact Windows conversion.
    """

    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Toolkit native CSV encoding requires Windows")
        import ctypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._get_acp = self._kernel32.GetACP
        self._get_acp.argtypes = ()
        self._get_acp.restype = ctypes.c_uint
        self._convert = self._kernel32.WideCharToMultiByte
        self._convert.argtypes = (
            ctypes.c_uint, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        )
        self._convert.restype = ctypes.c_int
        self.code_page = int(self._get_acp())
        if not 1 <= self.code_page <= 65535:
            raise RuntimeError("Windows returned an invalid ANSI code page")

    def encode(self, text: str) -> bytes:
        if type(text) is not str or "\0" in text:
            raise ValueError("Toolkit native CSV input must be text without NUL")
        try:
            utf16_units = len(text.encode("utf-16-le")) // 2
        except UnicodeEncodeError as error:
            raise ValueError(
                "Toolkit native CSV input must not contain unpaired surrogates"
            ) from error
        if utf16_units > MAX_UTF16_UNITS:
            raise ValueError("Toolkit native CSV input exceeds the conversion bound")
        if utf16_units == 0:
            return b""

        ctypes = self._ctypes
        ctypes.set_last_error(0)
        size = self._convert(
            CP_ACP, 0, text, utf16_units, None, 0, None, None)
        if size <= 0:
            error = ctypes.get_last_error()
            raise OSError(error, "WideCharToMultiByte size query failed")
        output = ctypes.create_string_buffer(size)
        ctypes.set_last_error(0)
        written = self._convert(
            CP_ACP, 0, text, utf16_units, output, size, None, None)
        if written != size:
            error = ctypes.get_last_error()
            raise OSError(error, "WideCharToMultiByte conversion failed")
        return output.raw[:written]
