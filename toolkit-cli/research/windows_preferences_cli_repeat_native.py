"""One owned Windows CLI repeated-load acceptance, launched from a pinned wheel.

The caller supplies a fresh namespace and a fixture containing the original
manager's first/second values. Only the adapter's disposable HKCU test subtree
may be written. The receipt deliberately omits the current account name/SID.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
import winreg


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixed_snapshot(paths):
    """Compare actual Toolkit keys without exporting names or private values."""
    observed = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for path in paths:
            try:
                with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
                    count = winreg.QueryInfoKey(key)[1]
                    observed.append((root, path, tuple(winreg.EnumValue(key, i) for i in range(count))))
            except FileNotFoundError:
                observed.append((root, path, None))
    return sha(repr(observed).encode('utf-8'))


def absent(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
            return False
    except FileNotFoundError:
        return True


def delete_tree(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            children = []
            index = 0
            while True:
                try:
                    children.append(winreg.EnumKey(key, index))
                    index += 1
                except OSError as error:
                    if error.winerror != 259:
                        raise
                    break
        for child in children:
            delete_tree(path + '\\' + child)
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, winreg.KEY_WOW64_32KEY, 0)
    except FileNotFoundError:
        pass


def session_id():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcessId.restype = ctypes.c_uint32
    kernel.ProcessIdToSessionId.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    kernel.ProcessIdToSessionId.restype = ctypes.c_int
    session = ctypes.c_uint32()
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    return session.value


def run(wheel: Path, fixture_path: Path, namespace: str, expected_wheel_sha: str):
    if os.name != 'nt':
        raise RuntimeError('Windows-only native acceptance')
    if sha(wheel.read_bytes()) != expected_wheel_sha:
        raise RuntimeError('Wheel differs from the admitted exact artifact')
    sys.path.insert(0, str(wheel))
    from cbus_toolkit import cli, toolkit_preferences_cli
    from cbus_toolkit._windows_process_token import current_process_user_sid
    from cbus_toolkit.windows_preferences import WindowsPreferenceRegistry
    from cbus_toolkit.toolkit_preferences_store import (
        HKCU, TOOLKIT_KEY, CGATE_KEY, DISPLAY_KEY, REG_SZ, RegistryValue,
    )

    fixture = json.loads(fixture_path.read_bytes())
    registry = WindowsPreferenceRegistry(test_namespace=namespace)
    owned_path = 'Software\\CBusToolkitCli\\Tests\\' + namespace
    if not absent(owned_path):
        raise RuntimeError('Refusing a previously existing test namespace')
    token_sid = current_process_user_sid()
    fixed_before = fixed_snapshot((TOOLKIT_KEY, CGATE_KEY, DISPLAY_KEY))
    state_path = fixture_path.with_suffix('.state.json')
    state_path.write_text(json.dumps({
        'format': 'cbus-toolkit-preferences-state-v1',
        'values': fixture['initial'], 'display_values': fixture['display'],
    }), encoding='utf-8')
    state_before = sha(state_path.read_bytes())
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error), \
         patch.object(toolkit_preferences_cli, 'registry_backend', return_value=registry):
        status = cli.main(['preferences', 'registry-load', str(state_path),
                           '--repeat-once', '--expected-user-sid', token_sid])
    document = json.loads(output.getvalue() if status == 0 else error.getvalue())
    passes = document.get('load_passes', [])
    first, second = passes if len(passes) == 2 else ({}, {})
    stored = registry.read_value(HKCU, TOOLKIT_KEY, 'ShowProjectManager')
    show = RegistryValue(REG_SZ, 'True\0'.encode('utf-16-le'))
    first_show = [row for row in first.get('operations', []) if row.get('name') == 'ShowProjectManager']
    second_show = [row for row in second.get('operations', []) if row.get('name') == 'ShowProjectManager']
    checks = {
        'cli_exit_zero': status == 0,
        'two_complete_passes': len(passes) == 2 and all(row.get('complete') is True for row in passes),
        'first_40_match_original_fixture': first.get('values') == fixture['first'],
        'second_40_match_original_fixture': second.get('values') == fixture['second'],
        'first_retains_false': first.get('values', {}).get('ShowProjectManager') is False,
        'second_reads_true': second.get('values', {}).get('ShowProjectManager') is True,
        'first_default_written': [row.get('action') for row in first_show] ==
                                 ['read', 'read', 'write-preference-default'],
        'second_direct_read': [row.get('action') for row in second_show] == ['read'],
        'stored_true': stored == show,
        'top_level_final_state': document.get('state', {}).get('values') == fixture['second'],
        'token_guard_satisfied': document.get('user_context', {}).get('sid_requirement_satisfied') is True,
        'state_file_unchanged': sha(state_path.read_bytes()) == state_before,
        'fixed_toolkit_keys_unchanged': fixed_snapshot((TOOLKIT_KEY, CGATE_KEY, DISPLAY_KEY)) == fixed_before,
    }
    version = sys.getwindowsversion()
    return {
        'wheel_sha256': expected_wheel_sha,
        'wheel_import_path_suffix': str(cli.__file__).split(wheel.name, 1)[-1],
        'fixture_sha256': sha(fixture_path.read_bytes()),
        'python_version': list(sys.version_info[:3]),
        'python_bits': ctypes.sizeof(ctypes.c_void_p) * 8,
        'os_build': version.build,
        'os_platform': version.platform,
        'process_user_sid_sha256': sha(token_sid.encode()),
        'process_user_is_system': token_sid == 'S-1-5-18',
        'session_id': session_id(),
        'namespace': namespace,
        'cli_status': status,
        'checks': checks,
        'first_receipt': {
            'complete': first.get('complete'),
            'operation_count': len(first.get('operations', [])),
            'default_write_count': len(first.get('default_writes', [])),
            'show_project_manager': first.get('values', {}).get('ShowProjectManager'),
            'show_project_manager_actions': [row.get('action') for row in first_show],
        },
        'second_receipt': {
            'complete': second.get('complete'),
            'operation_count': len(second.get('operations', [])),
            'default_write_count': len(second.get('default_writes', [])),
            'show_project_manager': second.get('values', {}).get('ShowProjectManager'),
            'show_project_manager_actions': [row.get('action') for row in second_show],
        },
        'original_same_user_executed': False,
        'interactive_desktop_verified': False,
    }


def main():
    wheel, fixture, result, namespace, expected_wheel_sha = sys.argv[1:]
    receipt = {'format': 'cbus-p9-preference-cli-native-repeat-v1', 'passed': False}
    owned_path = 'Software\\CBusToolkitCli\\Tests\\' + namespace
    try:
        receipt.update(run(Path(wheel), Path(fixture), namespace, expected_wheel_sha))
    except BaseException as error:
        # The guest's private paths and account information are never exported.
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
        Path(result).write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
