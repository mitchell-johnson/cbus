"""Read the pinned SESU 3.0.7 cohort in this process's HKCU Registry32 view.

This is an observation, not an updater decision. It never creates a key,
samples a cohort, or requests registry write access.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

from .windows_condition_registry import validate_user_sid


ORIGINAL_SHA256 = "21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c"
ORIGINAL_SIZE = 69704
ORIGINAL_HELPER_IL_SHA256 = "f6dd553c61e7af5a6d216422a6040102de46330e1bc7dad3dc7259f25bfead56"
REGISTRY_KEY = r"Software\Schneider Electric\Software Update\Persistent"
REGISTRY_ENTRY = "VisibilityExpectedGreaterThan"
_COHORT = re.compile(r"[0-9]{1,2}\Z", re.ASCII)


def _source_sha256(path: Path) -> str:
    info = os.lstat(path)
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_size != ORIGINAL_SIZE):
        raise ValueError("Source assembly must be the ordinary pinned SESU DLL")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != ORIGINAL_SIZE:
            raise ValueError("Source assembly changed before verification")
        data = bytearray()
        while len(data) <= ORIGINAL_SIZE:
            chunk = os.read(descriptor, ORIGINAL_SIZE + 1 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) != ORIGINAL_SIZE:
            raise ValueError("Source assembly changed during verification")
        return hashlib.sha256(data).hexdigest()
    finally:
        failure = sys.exc_info()[1]
        try:
            os.close(descriptor)
        except OSError:
            if failure is None:
                raise
            failure.add_note("Source assembly descriptor close also failed")


def _current_process_sid() -> str:
    if os.name != "nt":
        raise OSError("Current-user SESU registry observation requires Windows")
    from ._windows_process_token import _sid

    handle = ctypes.c_void_p
    dword = ctypes.c_uint32
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True, winmode=0x800)
    security = ctypes.WinDLL("advapi32.dll", use_last_error=True, winmode=0x800)
    kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], handle
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [handle], ctypes.c_int
    security.OpenProcessToken.argtypes = [handle, dword, ctypes.POINTER(handle)]
    security.OpenProcessToken.restype = ctypes.c_int
    security.GetTokenInformation.argtypes = [handle, ctypes.c_int, handle, dword,
                                             ctypes.POINTER(dword)]
    security.GetTokenInformation.restype = ctypes.c_int
    token = handle()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise OSError("OpenProcessToken failed for the current process")
    if not token.value:
        raise OSError("OpenProcessToken returned an invalid handle")
    try:
        buffer = ctypes.create_string_buffer(256)
        length = dword()
        if not security.GetTokenInformation(token, 1, buffer, len(buffer), ctypes.byref(length)):
            raise OSError("GetTokenInformation(TokenUser) failed for the current process")
        return _sid(buffer, length.value)
    finally:
        failure = sys.exc_info()[1]
        if not kernel.CloseHandle(token):
            if failure is None:
                raise OSError("Current-process token handle close failed")
            failure.add_note("Current-process token handle close also failed")


def _read_hkcu_registry32() -> tuple[str, str | int | None, int | None]:
    if os.name != "nt":
        raise OSError("Current-user SESU registry observation requires Windows")
    import winreg

    access = winreg.KEY_QUERY_VALUE | winreg.KEY_WOW64_32KEY
    try:
        handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, access)
    except FileNotFoundError:
        return "key_absent", None, None
    with handle:
        try:
            value, kind = winreg.QueryValueEx(handle, REGISTRY_ENTRY)
        except FileNotFoundError:
            return "entry_absent", None, None
    return "present", value, kind


@dataclass(frozen=True)
class CurrentUserCohortObservation:
    user_sid: str
    read_state: str
    stored_cohort: int | None
    value_kind: str | None
    registry_error_type: str | None = None

    @property
    def status(self) -> str:
        return ("observed" if self.registry_error_type is None
                and self.read_state == "present" and self.stored_cohort is not None
                else "unsupported")

    def as_dict(self) -> dict:
        return {
            "format": "cbus-toolkit-update-rollout-current-user-v1",
            "scope": "Read-only observation of one pinned SESU cohort value in the current process user",
            "status": self.status,
            "read_state": self.read_state,
            "stored_cohort": self.stored_cohort,
            "value_kind": self.value_kind,
            "registry_error_type": self.registry_error_type,
            "user_sid": self.user_sid,
            "source_assembly_sha256": ORIGINAL_SHA256,
            "source_assembly_verified": True,
            "user_sid_verified": True,
            "original_rollout_helper_token": "0x0600012C",
            "original_rollout_helper_il_sha256": ORIGINAL_HELPER_IL_SHA256,
            "registry_hive": "HKCU",
            "registry_view": "Registry32",
            "registry_key": REGISTRY_KEY,
            "registry_entry": REGISTRY_ENTRY,
            "registry_read_attempted": True,
            "registry_write_attempted": False,
            "cohort_generated": False,
            "cohort_persisted": False,
            "rollout_gate_evaluated": False,
            "full_machine_applicability_evaluated": False,
            "publisher_trust_evaluated": False,
            "updates_available": None,
            "install_permitted": False,
            "network_request_initiated": False,
        }


def observe_current_user_cohort(
    source_assembly: Path, *, expected_source_sha256: str, expected_user_sid: str,
) -> CurrentUserCohortObservation:
    """Verify exact original bytes and current token before one read-only query."""
    if expected_source_sha256 != ORIGINAL_SHA256:
        raise ValueError("Expected source SHA-256 must name the pinned original SESU assembly")
    validate_user_sid(expected_user_sid)
    if _source_sha256(source_assembly) != ORIGINAL_SHA256:
        raise ValueError("Source assembly hash differs from the pinned original SESU assembly")
    observed_sid = _current_process_sid()
    if observed_sid != expected_user_sid:
        raise ValueError("Current process user SID differs from the explicitly expected user")
    try:
        state, value, kind = _read_hkcu_registry32()
    except OSError as error:
        return CurrentUserCohortObservation(observed_sid, "read_error", None, None,
                                            type(error).__name__)
    if state in {"key_absent", "entry_absent"}:
        return CurrentUserCohortObservation(observed_sid, state, None, None)
    if state != "present":
        raise ValueError("Registry reader returned an invalid state")
    # Original ToString/Int32 parsing is deliberately narrower here. No
    # unknown kind or unusual string is converted to a usable cohort.
    import winreg
    if kind == winreg.REG_SZ and type(value) is str:
        if value == "-1":
            return CurrentUserCohortObservation(observed_sid, "sentinel", None, "REG_SZ")
        if _COHORT.fullmatch(value) and int(value) <= 99:
            return CurrentUserCohortObservation(observed_sid, "present", int(value), "REG_SZ")
    elif kind == winreg.REG_DWORD and type(value) is int and 0 <= value <= 99:
        return CurrentUserCohortObservation(observed_sid, "present", value, "REG_DWORD")
    return CurrentUserCohortObservation(observed_sid, "unsupported", None,
                                        "REG_SZ" if kind == winreg.REG_SZ else
                                        "REG_DWORD" if kind == winreg.REG_DWORD else "other")
