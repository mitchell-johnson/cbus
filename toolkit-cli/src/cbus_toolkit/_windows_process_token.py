"""Bounded primary-token user query on the original owned process handle.

This does not attest thread impersonation, interactive sessions, or host trust.
No token handle or token contents are exported; only the canonical user SID is.
"""
from __future__ import annotations

import ctypes
import os
import sys

DWORD = ctypes.c_uint32
HANDLE = ctypes.c_void_p


class _TokenUser(ctypes.Structure):
    _fields_ = [('sid', HANDLE), ('attributes', DWORD)]


def _apis():
    if os.name != 'nt':
        raise OSError('Process token verification requires Windows')
    kernel = ctypes.WinDLL('kernel32.dll', use_last_error=True, winmode=0x800)
    security = ctypes.WinDLL('advapi32.dll', use_last_error=True, winmode=0x800)
    for library, name, args, result in (
        (kernel, 'GetProcessId', [HANDLE], DWORD),
        (kernel, 'WaitForSingleObject', [HANDLE, DWORD], DWORD),
        (kernel, 'CloseHandle', [HANDLE], ctypes.c_int),
        (security, 'OpenProcessToken', [HANDLE, DWORD, ctypes.POINTER(HANDLE)], ctypes.c_int),
        (security, 'GetTokenInformation', [HANDLE, ctypes.c_int, HANDLE, DWORD,
                                          ctypes.POINTER(DWORD)], ctypes.c_int),
    ):
        method = getattr(library, name)
        method.argtypes, method.restype = args, result
    return kernel, security


def _live(kernel, handle, pid):
    if kernel.GetProcessId(handle) != pid:
        raise OSError('Owned worker process handle/PID mismatch')
    # WAIT_TIMEOUT means the exact process object has not terminated. Any other
    # result (including WAIT_FAILED) rejects admission, without waiting.
    if kernel.WaitForSingleObject(handle, 0) != 258:
        raise OSError('Owned worker is not live during token verification')


def _sid(buffer, length):
    start = ctypes.addressof(buffer)
    if not ctypes.sizeof(_TokenUser) <= length <= ctypes.sizeof(buffer):
        raise ValueError('TokenUser result length is outside bounds')
    pointer = _TokenUser.from_buffer(buffer).sid
    # Check before dereferencing an OS-returned pointer. The SID must be fully
    # contained in the returned TOKEN_USER buffer, after its fixed structure.
    if pointer is None or not start + ctypes.sizeof(_TokenUser) <= pointer <= start + length - 8:
        raise ValueError('TokenUser SID pointer is outside its result buffer')
    header = ctypes.string_at(pointer, 8)
    revision, count = header[0], header[1]
    if revision != 1 or not 1 <= count <= 15 or pointer + 8 + 4 * count > start + length:
        raise ValueError('TokenUser SID layout is outside supported bounds')
    raw = ctypes.string_at(pointer, 8 + 4 * count)
    authority = int.from_bytes(raw[2:8], 'big')
    parts = [int.from_bytes(raw[n:n + 4], 'little') for n in range(8, len(raw), 4)]
    return 'S-1-' + '-'.join(map(str, [authority, *parts]))


def process_token_user_sid(process):
    """Read TokenUser while retaining the original Popen process handle.

    CPython Windows Popen owns the handle until the Popen object is finalized.
    Never reopen by PID, close the borrowed process handle, or fall back to a
    worker's self-reported identity if this platform contract is unavailable.
    """
    pid = process.pid
    try:
        handle = int(process._handle)
    except (AttributeError, TypeError, ValueError):
        raise OSError('Original owned worker process handle is unavailable') from None
    if type(pid) is not int or not 0 < pid <= 0xffffffff or handle <= 0:
        raise OSError('Invalid owned worker process identity')
    kernel, security = _apis()
    _live(kernel, handle, pid)
    token = HANDLE()
    if not security.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
        raise OSError('OpenProcessToken failed for owned worker')
    if not token.value:
        raise OSError('OpenProcessToken returned an invalid handle')
    try:
        # TOKEN_USER plus a maximum-size SID is below 256 bytes on both x86
        # and x64. Fixed capacity avoids attacker-controlled allocation/retry.
        buffer = ctypes.create_string_buffer(256)
        length = DWORD()
        if not security.GetTokenInformation(token, 1, buffer, len(buffer), ctypes.byref(length)):
            raise OSError('GetTokenInformation(TokenUser) failed for owned worker')
        sid = _sid(buffer, length.value)
        _live(kernel, handle, pid)
        return sid
    finally:
        failure = sys.exc_info()[1]
        if not kernel.CloseHandle(token):
            if failure is None:
                raise OSError('Owned worker token handle close failed')
            failure.add_note('Owned worker token handle close also failed')


def current_process_user_sid():
    """Read the current process primary-token SID without opening a registry key.

    A primary token does not attest a thread's impersonation state or an
    interactive desktop session. Callers must state those limits separately.
    """
    if os.name != 'nt':
        raise OSError('Current-process token verification requires Windows')
    kernel, security = _apis()
    kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], HANDLE
    token = HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise OSError('OpenProcessToken failed for the current process')
    if not token.value:
        raise OSError('OpenProcessToken returned an invalid handle')
    try:
        buffer = ctypes.create_string_buffer(256)
        length = DWORD()
        if not security.GetTokenInformation(token, 1, buffer, len(buffer), ctypes.byref(length)):
            raise OSError('GetTokenInformation(TokenUser) failed for the current process')
        return _sid(buffer, length.value)
    finally:
        failure = sys.exc_info()[1]
        if not kernel.CloseHandle(token):
            if failure is None:
                raise OSError('Current-process token handle close failed')
            failure.add_note('Current-process token handle close also failed')
