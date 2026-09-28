"""Run the bounded preference repeat case in the logged-in Windows desktop.

This extends the already-owned scratch-key wheel harness with independent
process/session/desktop observations. It does not run the original GUI.
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_preferences_cli_repeat_native import absent, delete_tree, run  # noqa: E402


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
    owned_path = 'Software\\CBusToolkitCli\\Tests\\' + namespace
    receipt = {'format': 'cbus-p9-preference-cli-interactive-repeat-v1', 'passed': False}
    try:
        observation = desktop_observation()
        receipt.update(run(Path(wheel), Path(fixture), namespace, wheel_sha))
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
            delete_tree(owned_path)
            receipt['owned_namespace_absent_after_cleanup'] = absent(owned_path)
        except BaseException as error:
            receipt['cleanup_error_type'] = type(error).__name__
            receipt['owned_namespace_absent_after_cleanup'] = False
        receipt['passed'] = (all(receipt.get('checks', {}).values()) and
                             receipt['owned_namespace_absent_after_cleanup'])
        Path(result).write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n',
                                encoding='utf-8')
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
