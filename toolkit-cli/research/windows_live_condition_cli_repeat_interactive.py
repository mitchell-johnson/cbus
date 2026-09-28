"""Run one owned, interactive Windows CLI two-worker registry acceptance.

This is a research harness for the disposable UTM guest. It installs one pinned
wheel into a fresh scratch directory, invokes its public CLI in a child Python
process, and changes only its freshly claimed HKCU Registry32 fixture between
the two worker observations. The raw CLI JSON stays in the private guest root;
the exported result contains no account name or clear SID.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import winreg
import zipfile


ROOT = Path(r'C:\CBusCliOracle118-88d8')
RUN_ID = re.compile(r'p902i-[a-f0-9]{10}\Z')
SOURCE_FILES = (
    'cli.py', '_windows_process_token.py', '_windows_condition_registry_worker.py',
    'windows_condition_registry.py', 'toolkit_live_update_conditions.py',
    'toolkit_live_update_conditions_cli.py', 'toolkit_update_conditions.py',
    '_toolkit_update_registry_conditions.py',
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def claim_key(path):
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    api.RegCreateKeyExW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
    api.RegCreateKeyExW.restype = ctypes.c_long
    api.RegCloseKey.argtypes = [ctypes.c_void_p]
    api.RegCloseKey.restype = ctypes.c_long
    handle, disposition = ctypes.c_void_p(), ctypes.c_uint32()
    status = api.RegCreateKeyExW(ctypes.c_void_p(int(winreg.HKEY_CURRENT_USER)),
        path, 0, None, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_32KEY, None,
        ctypes.byref(handle), ctypes.byref(disposition))
    if status:
        raise OSError(status, 'Owned Registry32 key claim failed')
    try:
        if disposition.value != 1:
            raise RuntimeError('Refusing pre-existing registry fixture')
    finally:
        if api.RegCloseKey(handle):
            raise OSError('Owned registry claim handle close failed')


def marker_matches(path, marker):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            value, kind = winreg.QueryValueEx(key, '_CbusCliAcceptanceOwner')
            return kind == winreg.REG_SZ and value == marker
    except FileNotFoundError:
        return False


def absent(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
            return False
    except FileNotFoundError:
        return True


def set_value(path, value):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY) as key:
        winreg.SetValueEx(key, 'Value', 0, winreg.REG_DWORD, value)


def read_value(path):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                        winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
        return winreg.QueryValueEx(key, 'Value')


def _object_name(handle):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetUserObjectInformationW.argtypes = [ctypes.c_void_p, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    user.GetUserObjectInformationW.restype = ctypes.c_int
    buffer, needed = ctypes.create_unicode_buffer(256), ctypes.c_uint32()
    if not user.GetUserObjectInformationW(handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def desktop():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.GetCurrentProcessId.restype = ctypes.c_uint32
    kernel.ProcessIdToSessionId.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    kernel.ProcessIdToSessionId.restype = ctypes.c_int
    kernel.WTSGetActiveConsoleSessionId.restype = ctypes.c_uint32
    kernel.GetCurrentThreadId.restype = ctypes.c_uint32
    user.GetProcessWindowStation.restype = ctypes.c_void_p
    user.GetThreadDesktop.argtypes = [ctypes.c_uint32]
    user.GetThreadDesktop.restype = ctypes.c_void_p
    session = ctypes.c_uint32()
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    station = user.GetProcessWindowStation()
    thread_desktop = user.GetThreadDesktop(kernel.GetCurrentThreadId())
    if not station or not thread_desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    return {'session_id': session.value,
            'active_console_session_id': kernel.WTSGetActiveConsoleSessionId(),
            'window_station': _object_name(station),
            'thread_desktop': _object_name(thread_desktop)}


def install(wheel, site, manifest):
    if sha(wheel.read_bytes()) != manifest['wheel_sha256']:
        raise ValueError('Wheel differs from admitted host artifact')
    site.mkdir()
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            parts = Path(member.filename).parts
            if member.filename.startswith('/') or '..' in parts or ':' in member.filename:
                raise ValueError('Wheel contains an unsafe member path')
        archive.extractall(site)
    actual = {name: sha((site / 'cbus_toolkit' / name).read_bytes())
              for name in SOURCE_FILES}
    if actual != manifest['source_sha256']:
        raise ValueError('Installed package source differs from admitted source')
    return actual


def worker_gone():
    # No other Windows owner uses this guest during this bounded test.
    image = 'RegistryWorker.exe'
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ' + image, '/FO', 'CSV'],
                            capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and image.lower() not in result.stdout.lower()


def main():
    wheel_arg, manifest_arg, run_id = sys.argv[1:]
    if os.name != 'nt' or RUN_ID.fullmatch(run_id) is None:
        raise SystemExit('Windows and a fresh owned run ID are required')
    wheel, manifest_path = Path(wheel_arg), Path(manifest_arg)
    result_path = ROOT / (run_id + '-live-result.json')
    raw_path = ROOT / (run_id + '-live-raw.json')
    stderr_path = ROOT / (run_id + '-live-stderr.txt')
    scratch = ROOT / (run_id + '-live')
    key_path = 'Software\\CBusToolkitCli\\Tests\\' + run_id + '-live'
    receipt = {'format': 'cbus-p902-live-condition-cli-interactive-repeat-v1',
               'run_id': run_id, 'passed': False, 'checks': {}}
    owner = secrets.token_hex(16)
    claimed = False
    try:
        manifest = json.loads(manifest_path.read_bytes())
        if set(manifest) != {'base_revision', 'wheel_sha256', 'source_sha256'}:
            raise ValueError('Admitted manifest shape differs')
        if set(manifest['source_sha256']) != set(SOURCE_FILES):
            raise ValueError('Admitted source list differs')
        scratch.mkdir()
        site = scratch / 'site'
        installed = install(wheel, site, manifest)
        receipt.update(base_revision=manifest['base_revision'],
            wheel_sha256=manifest['wheel_sha256'], source_sha256=manifest['source_sha256'],
            installed_sha256=installed)
        sys.path.insert(0, str(site))
        from cbus_toolkit._windows_process_token import current_process_user_sid
        sid = current_process_user_sid()
        active = desktop()
        receipt.update(python_version=list(sys.version_info[:3]), python_bits=ctypes.sizeof(ctypes.c_void_p) * 8,
            windows_build=sys.getwindowsversion().build, process_user_sid_sha256=sha(sid.encode()),
            process_user_is_system=sid == 'S-1-5-18', desktop=active)
        receipt['checks']['interactive_desktop'] = (
            sid != 'S-1-5-18' and active['session_id'] > 0
            and active['session_id'] == active['active_console_session_id']
            and active['window_station'].lower() == 'winsta0'
            and active['thread_desktop'].lower() == 'default')
        if not receipt['checks']['interactive_desktop']:
            raise RuntimeError('Owned process is outside active desktop user context')
        claim_key(key_path)
        claimed = True
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY) as key:
            winreg.SetValueEx(key, '_CbusCliAcceptanceOwner', 0, winreg.REG_SZ, owner)
        if not marker_matches(key_path, owner):
            raise RuntimeError('Owned registry marker is not readable')
        set_value(key_path, 0)
        receipt['checks']['initial_registry32_dword_zero'] = read_value(key_path) == (0, winreg.REG_DWORD)
        scope_path = 'HKEY_CURRENT_USER\\' + key_path
        conditions = {'expression': 'A', 'conditions': {'A': {
            'whatToCheck': 6, 'howToCheck': 10, 'comparisonRightSideValue': '0',
            'fileOrRegistryKeyPath': scope_path, 'registryEntryNameOrProductCode': 'Value'}}}
        context = {'format': 'cbus-toolkit-condition-context-v1', 'culture': 'invariant-ascii', 'files': []}
        scope = {'format': 'cbus-toolkit-registry-read-scope-v1', 'queries': [{
            'path': scope_path, 'entry': 'Value', 'default': {
                'kind': 'System.String',
                'value': '23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe'}}]}
        paths = {name: scratch / (name + '.json') for name in ('conditions', 'context', 'scope')}
        for name, value in (('conditions', conditions), ('context', context), ('scope', scope)):
            paths[name].write_text(json.dumps(value, separators=(',', ':')), encoding='ascii')
        receipt['input_sha256'] = {name: sha(path.read_bytes()) for name, path in paths.items()}
        workspace = scratch / 'workers'
        workspace.mkdir()
        change = {'done': False, 'error_type': None, 'first_worker_dir': None,
                  'first_response_seen_ns': None, 'registry_changed_ns': None}
        stop = threading.Event()

        def flip_after_first_response():
            deadline = time.monotonic() + 100
            try:
                while not stop.is_set() and time.monotonic() < deadline:
                    dirs = list(workspace.glob('cbus-registry-observation-*'))
                    if dirs:
                        first = min(dirs, key=lambda item: item.stat().st_ctime_ns)
                        if (first / 'q000.response').is_file():
                            change['first_response_seen_ns'] = time.monotonic_ns()
                            change['first_worker_dir'] = str(first)
                            set_value(key_path, 1)
                            change['registry_changed_ns'] = time.monotonic_ns()
                            change['done'] = True
                            return
                    stop.wait(0.002)
            except BaseException as error:
                change['error_type'] = type(error).__name__

        watcher = threading.Thread(target=flip_after_first_response, daemon=True)
        watcher.start()
        command = [sys.executable, '-c',
            'import sys; sys.path.insert(0, sys.argv.pop(1)); '
            'from cbus_toolkit.cli import main; raise SystemExit(main())',
            str(site), '--compact', 'update-condition-live', str(paths['conditions']),
            '--file-context', str(paths['context']), '--registry-scope', str(paths['scope']),
            '--repeat-once', '--expected-user-sid', sid,
            '--workspace-parent', str(workspace), '--timeout', '35']
        try:
            completed = subprocess.run(command, capture_output=True, timeout=105)
        finally:
            stop.set()
            watcher.join(timeout=2)
        raw_path.write_bytes(completed.stdout)
        stderr_path.write_bytes(completed.stderr)
        receipt.update(cli_exit_code=completed.returncode, raw_stdout_sha256=sha(completed.stdout),
            raw_stderr_sha256=sha(completed.stderr), raw_stdout_bytes=len(completed.stdout),
            raw_stderr_bytes=len(completed.stderr), registry_flip=change)
        report = json.loads(completed.stdout)
        passes = report.get('evaluation_passes', [])
        observers = [row.get('observer_evidence', {}) for row in passes]
        proofs = [row.get('provider_proof') or {} for row in observers]
        identities = [row.get('user_context') or {} for row in observers]
        worker_dirs = [row.get('artifact_directory') for row in observers]
        worker_pids = [row.get('worker_pid') for row in proofs]
        receipt['pass_summary'] = [{
            'condition_result': row.get('condition_result'),
            'condition_result_cache': row.get('condition_result_cache'),
            'registry_observation_count': len(row.get('registry_observations', [])),
            'worker_pid': proofs[index].get('worker_pid'),
            'worker_nonce_sha256': sha(proofs[index].get('nonce', '').encode()),
            'worker_directory_suffix': Path(worker_dirs[index]).name if worker_dirs[index] else None,
            'provider_method_token': proofs[index].get('method_token'),
            'provider_il_sha256': proofs[index].get('method_il_sha256'),
            'runtime_sha256': proofs[index].get('runtime_sha256'),
            'authored_worker_source_sha256': proofs[index].get('authored_source_sha256'),
            'cleanup': row.get('observer_evidence', {}).get('cleanup'),
            'registry_result': (row.get('registry_observations') or [{}])[0].get('result'),
        } for index, row in enumerate(passes)]
        checks = receipt['checks']
        checks.update(
            cli_exit_zero=completed.returncode == 0,
            stderr_empty=completed.stderr == b'',
            registry_flipped_after_first_response=change['done'] and change['error_type'] is None,
            final_registry32_dword_one=read_value(key_path) == (1, winreg.REG_DWORD),
            two_ordered_passes=len(passes) == 2 and report.get('second_evaluation_attempted') is True
                and report.get('repeated_evaluation') is True,
            true_then_false=[row.get('condition_result') for row in passes] == [True, False],
            fresh_condition_cache=[row.get('condition_result_cache') for row in passes]
                == [{'a': True}, {'a': False}],
            top_level_second_result=report.get('condition_result') is False,
            two_verified_observations=len(observers) == 2 and all(
                row.get('registry_provider_identity_verified') is True
                and row.get('capture_completed') is True and row.get('closed') is True
                and len(row.get('observations', [])) == 1 for row in observers),
            distinct_workers=len(worker_dirs) == 2 and len(set(worker_dirs)) == 2
                and None not in worker_dirs and len(set(worker_pids)) == 2
                and None not in worker_pids,
            two_matching_sid_guards=len(identities) == 2 and all(
                row.get('expected_user_sid') == sid and row.get('observed_user_sid') == sid
                and row.get('process_token_user_sid') == sid
                and row.get('process_token_user_verified') is True
                and row.get('sid_requirement_satisfied') is True for row in identities),
            provider_proofs=len(proofs) == 2 and all(
                row.get('method_token') == '060000f3' and row.get('pointer_size') == 4
                and row.get('runtime_sha256') == '93d46bdac1664dba87641925572c789d71a21bb01dc7c7e5aa99c0eca8335e5e'
                for row in proofs),
            workers_closed_cleanly=len(observers) == 2 and all(
                row.get('cause') is None and all(
                    (step.get('status') == 'started' if step.get('stage') == 'evidence_export'
                     else step.get('status') == 'passed')
                    for step in row.get('cleanup', []))
                and {'finish', 'worker_reaped', 'compiler_reaped', 'input_hashes_after'}
                    <= {step.get('stage') for step in row.get('cleanup', [])}
                and any(step.get('stage') == 'evidence_export'
                        for step in row.get('cleanup', []))
                for row in observers),
            source_bytes_unchanged=all(sha(path.read_bytes()) == receipt['input_sha256'][name]
                for name, path in paths.items()),
            no_registry_worker_process=worker_gone(),
        )
        receipt['worker_artifact_count'] = len(list(workspace.glob('cbus-registry-observation-*')))
    except BaseException as error:
        receipt['error_type'] = type(error).__name__
        receipt['error_message'] = str(error)[:300]
    finally:
        try:
            receipt['owned_key_marked_before_cleanup'] = claimed and marker_matches(key_path, owner)
            if receipt['owned_key_marked_before_cleanup']:
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, key_path, winreg.KEY_WOW64_32KEY, 0)
            receipt['owned_key_absent_after_cleanup'] = absent(key_path)
        except BaseException as error:
            receipt['cleanup_error_type'] = type(error).__name__
            receipt['owned_key_absent_after_cleanup'] = False
        receipt['passed'] = (receipt.get('error_type') is None and
            receipt.get('cleanup_error_type') is None and
            receipt['owned_key_marked_before_cleanup'] is True and
            receipt['owned_key_absent_after_cleanup'] is True and
            all(receipt['checks'].values()) and len(receipt['checks']) == 17)
        save_new(result_path, receipt)
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
