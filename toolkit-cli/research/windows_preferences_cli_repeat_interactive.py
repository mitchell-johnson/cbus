"""Run the bounded preference repeat case in the logged-in Windows desktop.

This extends the already-owned scratch-key wheel harness with independent
process/session/desktop observations. It does not run the original GUI.
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import re
import secrets
import sys
from unittest.mock import patch
import winreg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import windows_preferences_cli_repeat_native as base  # noqa: E402

absent = base.absent
delete_tree = base.delete_tree

EXPECTED_CHECKS = frozenset({
    'cli_exit_zero',
    'two_complete_passes',
    'first_40_match_original_fixture',
    'second_40_match_original_fixture',
    'first_retains_false',
    'second_reads_true',
    'first_default_written',
    'second_direct_read',
    'stored_true',
    'top_level_final_state',
    'token_guard_satisfied',
    'state_file_unchanged',
    'fixed_toolkit_keys_unchanged',
    'interactive_desktop_verified',
})
NAMESPACE_PATTERN = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')


def valid_namespace(value: str) -> bool:
    """Match the adapter guard before making any registry call."""
    return NAMESPACE_PATTERN.fullmatch(value) is not None


def accepted(receipt: dict) -> bool:
    checks = receipt.get('checks')
    return (
        'error_type' not in receipt and
        'cleanup_error_type' not in receipt and
        receipt.get('cli_status') == 0 and
        receipt.get('interactive_desktop_verified') is True and
        receipt.get('process_user_is_system') is False and
        receipt.get('namespace_claimed_fresh') is True and
        receipt.get('namespace_ownership_confirmed_before_cleanup') is True and
        isinstance(checks, dict) and
        frozenset(checks) == EXPECTED_CHECKS and
        len(checks) == len(EXPECTED_CHECKS) == 14 and
        all(value is True for value in checks.values()) and
        receipt.get('owned_namespace_absent_after_cleanup') is True
    )


def claim_new_namespace(path: str) -> bool:
    """Atomically distinguish a new Registry32 key from a pre-existing one."""
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.RegCreateKeyExW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi.RegCreateKeyExW.restype = ctypes.c_long
    advapi.RegCloseKey.argtypes = [ctypes.c_void_p]
    advapi.RegCloseKey.restype = ctypes.c_long
    handle = ctypes.c_void_p()
    disposition = ctypes.c_uint32()
    status = advapi.RegCreateKeyExW(
        ctypes.c_void_p(int(winreg.HKEY_CURRENT_USER)), path, 0, None, 0,
        winreg.KEY_WRITE | winreg.KEY_WOW64_32KEY, None,
        ctypes.byref(handle), ctypes.byref(disposition),
    )
    if status != 0:
        raise OSError(status, 'Registry32 namespace claim failed')
    try:
        return disposition.value == 1  # REG_CREATED_NEW_KEY
    finally:
        if advapi.RegCloseKey(handle) != 0:
            raise RuntimeError('Registry32 namespace claim handle close failed')


def marker_matches(path: str, marker: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            value, kind = winreg.QueryValueEx(key, '_CbusCliAcceptanceOwner')
            return kind == winreg.REG_SZ and value == marker
    except FileNotFoundError:
        return False


def preexisting_namespace_negative_case(namespace: str) -> bool:
    path = 'Software\\CBusToolkitCli\\Tests\\' + namespace + '-collision'
    negative_owner = secrets.token_hex(16)
    if not claim_new_namespace(path):
        raise RuntimeError('Refusing existing collision-test namespace')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY) as key:
            winreg.SetValueEx(key, '_CbusCliAcceptanceOwner', 0,
                              winreg.REG_SZ, negative_owner)
            winreg.SetValueEx(key, 'Sentinel', 0, winreg.REG_SZ, 'preserve')
        collision_rejected = not claim_new_namespace(path)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            value, kind = winreg.QueryValueEx(key, 'Sentinel')
        return collision_rejected and kind == winreg.REG_SZ and value == 'preserve'
    finally:
        # A failed marker write leaves an unmarked key for inspection; never
        # remove a namespace without proving that this probe still owns it.
        if marker_matches(path, negative_owner):
            delete_tree(path)


def _user_object_name(handle: int) -> str:
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetUserObjectInformationW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                 ctypes.c_void_p, ctypes.c_uint32,
                                                 ctypes.POINTER(ctypes.c_uint32)]
    user32.GetUserObjectInformationW.restype = ctypes.c_int
    buffer = ctypes.create_unicode_buffer(256)
    needed = ctypes.c_uint32()
    if not user32.GetUserObjectInformationW(handle, 2, buffer, ctypes.sizeof(buffer),
                                            ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def desktop_observation() -> dict:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel.WTSGetActiveConsoleSessionId.restype = ctypes.c_uint32
    kernel.GetCurrentThreadId.restype = ctypes.c_uint32
    user32.GetProcessWindowStation.restype = ctypes.c_void_p
    user32.GetThreadDesktop.argtypes = [ctypes.c_uint32]
    user32.GetThreadDesktop.restype = ctypes.c_void_p
    station = user32.GetProcessWindowStation()
    desktop = user32.GetThreadDesktop(kernel.GetCurrentThreadId())
    if not station or not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        'active_console_session_id': kernel.WTSGetActiveConsoleSessionId(),
        'window_station': _user_object_name(station),
        'thread_desktop': _user_object_name(desktop),
    }


def main() -> int:
    wheel, fixture, result, namespace, wheel_sha = sys.argv[1:]
    receipt = {'format': 'cbus-p9-preference-cli-interactive-repeat-v1', 'passed': False}
    receipt['negative_invalid_namespace_rejected'] = all(
        not valid_namespace(value) for value in ('', 'Uppercase', 'bad\\escape',
                                                 'bad/escape', 'a' * 65)
    )
    if not valid_namespace(namespace):
        # Keep this return ahead of owned_path construction and any registry
        # access. In particular, a crafted path cannot become a cleanup target.
        receipt['error_type'] = 'InvalidNamespace'
        Path(result).write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n',
                                encoding='utf-8')
        return 1
    owned_path = 'Software\\CBusToolkitCli\\Tests\\' + namespace
    # Generate the token before creating a key. A close/marker-write failure
    # can leave an unmarked key, but must not delete any unproven namespace.
    owner_marker = secrets.token_hex(16)
    try:
        receipt['negative_preexisting_namespace_preserved'] = (
            preexisting_namespace_negative_case(namespace)
        )
        if not receipt['negative_preexisting_namespace_preserved']:
            raise RuntimeError('Pre-existing namespace preservation probe failed')
        if not claim_new_namespace(owned_path):
            raise RuntimeError('Refusing a pre-existing test namespace')
        receipt['namespace_claimed_fresh'] = True
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, owned_path, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY) as key:
            winreg.SetValueEx(key, '_CbusCliAcceptanceOwner', 0,
                              winreg.REG_SZ, owner_marker)
        if not marker_matches(owned_path, owner_marker):
            raise RuntimeError('Newly claimed namespace ownership marker not readable')
        observation = desktop_observation()
        # The base harness rejects any existing namespace. This exact root is
        # now pre-created by us, with an ownership marker; permit only its
        # initial guard while leaving every other absence check unchanged.
        def admitted_absent(path: str) -> bool:
            if path == owned_path:
                return marker_matches(path, owner_marker)
            return absent(path)

        with patch.object(base, 'absent', side_effect=admitted_absent):
            receipt.update(base.run(Path(wheel), Path(fixture), namespace, wheel_sha))
        receipt['desktop'] = observation
        session = receipt['session_id']
        receipt['interactive_desktop_verified'] = (
            session > 0 and session == observation['active_console_session_id']
            and observation['window_station'].lower() == 'winsta0'
            and observation['thread_desktop'].lower() == 'default'
            and receipt['process_user_is_system'] is False
        )
        receipt['checks']['interactive_desktop_verified'] = receipt['interactive_desktop_verified']
        receipt['original_same_user_executed'] = False
    except BaseException as error:
        receipt['error_type'] = type(error).__name__
    finally:
        try:
            receipt['namespace_ownership_confirmed_before_cleanup'] = (
                owner_marker is not None and marker_matches(owned_path, owner_marker)
            )
            if receipt['namespace_ownership_confirmed_before_cleanup']:
                delete_tree(owned_path)
                receipt['owned_namespace_absent_after_cleanup'] = absent(owned_path)
            else:
                # Never remove a pre-existing, replaced, or unmarked namespace.
                # A partial claim can leave an unmarked key for manual review.
                receipt['owned_namespace_absent_after_cleanup'] = False
            receipt['namespace_never_deleted_without_owner'] = True
        except BaseException as error:
            receipt['cleanup_error_type'] = type(error).__name__
            receipt['owned_namespace_absent_after_cleanup'] = False
        receipt['negative_empty_checks_rejected'] = not accepted({
            'error_type': 'ForcedEarlyError',
            'checks': {},
            'owned_namespace_absent_after_cleanup': True,
        })
        receipt['negative_missing_required_check_rejected'] = not accepted({
            **receipt,
            'checks': {key: value for key, value in receipt.get('checks', {}).items()
                       if key != 'second_direct_read'},
        })
        receipt['passed'] = (
            accepted(receipt) and
            receipt.get('negative_preexisting_namespace_preserved') is True and
            receipt['negative_invalid_namespace_rejected'] and
            receipt['negative_empty_checks_rejected'] and
            receipt['negative_missing_required_check_rejected']
        )
        Path(result).write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n',
                                encoding='utf-8')
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
