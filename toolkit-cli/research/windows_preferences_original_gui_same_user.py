"""Bounded original GUI startup observation with registry snapshot/restore.

Run only in the disposable Windows VM's logged-in desktop account. Original
vendor binaries stay in the guest and all registry export files remain there.
The public receipt contains hashes and selected preference behavior only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import winreg

ROOT = Path(r'C:\CBusCliOracle118-88d8')
EXE_SHA = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
KEYS = (
    ('HKCU', r'Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0'),
    ('HKCU', r'Software\Schneider Electric\C-Gate\CurrentVersion'),
    ('HKCU', r'Software\Clipsal Integrated Systems\Global\Preferences'),
    ('HKLM', r'Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0'),
    ('HKLM', r'Software\Schneider Electric\C-Gate\CurrentVersion'),
    ('HKLM', r'Software\Clipsal Integrated Systems\Global\Preferences'),
)
TOOLKIT_KEY = r'Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_handle(hive: str):
    return winreg.HKEY_CURRENT_USER if hive == 'HKCU' else winreg.HKEY_LOCAL_MACHINE


def key_exists(hive: str, path: str) -> bool:
    try:
        with winreg.OpenKey(key_handle(hive), path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
            return True
    except FileNotFoundError:
        return False


def tree_hash(hive: str, path: str) -> str | None:
    if not key_exists(hive, path):
        return None
    rows = []

    def visit(name: str):
        with winreg.OpenKey(key_handle(hive), name, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            subkeys, values, _ = winreg.QueryInfoKey(key)
            value_rows = []
            for index in range(values):
                value_name, value, value_type = winreg.EnumValue(key, index)
                if isinstance(value, bytes):
                    value = value.hex()
                value_rows.append((value_name, value_type, value))
            rows.append((name, sorted(value_rows, key=lambda row: row[0])))
            children = [winreg.EnumKey(key, index) for index in range(subkeys)]
        for child in sorted(children):
            visit(name + '\\' + child)

    visit(path)
    return sha(repr(rows).encode('utf-8'))


def reg(*args: str, allow_missing: bool = False) -> None:
    done = subprocess.run(('reg.exe', *args), capture_output=True, text=True,
                          timeout=30, check=False)
    if done.returncode != 0 and not (allow_missing and 'unable to find' in
                                     (done.stdout + done.stderr).lower()):
        raise RuntimeError('reg.exe ' + args[0] + ' failed with status ' +
                           str(done.returncode))


def backup(tag: str) -> list[dict]:
    records = []
    for index, (hive, path) in enumerate(KEYS):
        present = key_exists(hive, path)
        before = tree_hash(hive, path)
        target = ROOT / (tag + '-registry-' + str(index) + '.reg')
        if present:
            if target.exists():
                raise RuntimeError('Refusing existing registry backup')
            reg('export', hive + '\\' + path, str(target), '/y', '/reg:32')
        records.append({
            'hive': hive, 'path': path, 'present': present,
            'before_sha256': before, 'backup_path': str(target),
            'backup_sha256': sha(target.read_bytes()) if present else None,
        })
    return records


def restore_hkcu(records: list[dict]) -> bool:
    for row in records:
        if row['hive'] != 'HKCU':
            continue
        if key_exists(row['hive'], row['path']):
            reg('delete', row['hive'] + '\\' + row['path'], '/f', '/reg:32')
        if row['present']:
            reg('import', row['backup_path'], '/reg:32')
    return all(tree_hash(row['hive'], row['path']) == row['before_sha256']
               for row in records if row['hive'] == 'HKCU')


def show_project_manager():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TOOLKIT_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            value, kind = winreg.QueryValueEx(key, 'ShowProjectManager')
            return value if kind == winreg.REG_SZ and value in ('True', 'False') else 'other'
    except FileNotFoundError:
        return None


def stage_vendor(tag: str) -> Path:
    existing = subprocess.run(
        ('tasklist.exe', '/fo', 'csv', '/nh', '/fi', 'imagename eq CBusToolkit.exe'),
        capture_output=True, text=True, timeout=15, check=False)
    if existing.returncode != 0 or '"CBusToolkit.exe"' in existing.stdout:
        raise RuntimeError('An original Toolkit process is already running')
    directory = ROOT / (tag + '-vendor')
    if directory.exists():
        raise RuntimeError('Refusing existing vendor staging directory')
    directory.mkdir()
    manifest = json.loads((ROOT / 'guest-vendor-manifest.json').read_bytes())
    if len(manifest) != 25:
        raise RuntimeError('Unexpected original vendor manifest')
    for row in manifest:
        name = row['name']
        if Path(name).name != name or not (ROOT / 'vendor' / name).is_file():
            raise RuntimeError('Unsafe or missing original vendor file')
        source = ROOT / 'vendor' / name
        if source.stat().st_size != row['size'] or sha(source.read_bytes()) != row['sha256']:
            raise RuntimeError('Original vendor source changed')
        shutil.copy2(source, directory / name)
    if sha((directory / 'CBusToolkit.exe').read_bytes()) != EXE_SHA:
        raise RuntimeError('Wrong original GUI executable')
    return directory


def start_once(exe: Path, wait_seconds: int) -> dict:
    process = subprocess.Popen((str(exe),), cwd=str(exe.parent),
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    started = time.monotonic()
    try:
        while time.monotonic() - started < wait_seconds and process.poll() is None:
            time.sleep(0.25)
        still_running = process.poll() is None
        if still_running:
            process.terminate()
        try:
            exit_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            exit_code = process.wait(timeout=10)
        return {
            'created': True,
            'ran_seconds': round(time.monotonic() - started, 3),
            'still_running_at_bound': still_running,
            'exit_code_after_bounded_stop': exit_code,
            'show_project_manager_after': show_project_manager(),
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def run(tag: str, state_path: Path) -> dict:
    sys.path.insert(0, str(ROOT / (tag + '.whl')))
    from cbus_toolkit._windows_process_token import current_process_user_sid
    sid = current_process_user_sid()
    if sid == 'S-1-5-18':
        raise RuntimeError('Original GUI comparison must run under interactive user')
    receipt = {
        'format': 'cbus-p902-original-gui-same-user-v1',
        'same_user_sid_sha256': sha(sid.encode()),
        'original_executable_sha256': EXE_SHA,
        'complete': False,
    }
    state_before = state_path.read_bytes()
    records = backup(tag)
    receipt['registry_before_sha256'] = {
        row['hive'] + ':' + row['path']: row['before_sha256'] for row in records
    }
    receipt['state_file_sha256'] = sha(state_before)
    directory = ROOT / (tag + '-vendor')
    try:
        stage_vendor(tag)
        receipt['initial_show_project_manager'] = show_project_manager()
        if key_exists('HKCU', TOOLKIT_KEY):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TOOLKIT_KEY, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY) as key:
                try:
                    winreg.DeleteValue(key, 'ShowProjectManager')
                except FileNotFoundError:
                    pass
        receipt['seeded_missing_show_project_manager'] = show_project_manager() is None
        exe = directory / 'CBusToolkit.exe'
        receipt['first_gui'] = start_once(exe, 20)
        receipt['second_gui'] = start_once(exe, 10)
        receipt['original_manager_default_observed'] = (
            receipt['first_gui']['show_project_manager_after'] == 'True' and
            receipt['second_gui']['show_project_manager_after'] == 'True'
        )
    except BaseException as error:
        receipt['error_type'] = type(error).__name__
    finally:
        try:
            receipt['hkcu_restore_verified'] = restore_hkcu(records)
        except BaseException as error:
            receipt['hkcu_restore_verified'] = False
            receipt['restore_error_type'] = type(error).__name__
        try:
            receipt['hklm_unchanged'] = all(
                tree_hash(row['hive'], row['path']) == row['before_sha256']
                for row in records if row['hive'] == 'HKLM'
            )
        except BaseException as error:
            receipt['hklm_unchanged'] = False
            receipt['hklm_check_error_type'] = type(error).__name__
        try:
            receipt['state_file_unchanged'] = state_path.read_bytes() == state_before
            if not receipt['state_file_unchanged']:
                state_path.write_bytes(state_before)
                receipt['state_file_restored'] = state_path.read_bytes() == state_before
            else:
                receipt['state_file_restored'] = True
        except BaseException as error:
            receipt['state_file_restored'] = False
            receipt['state_restore_error_type'] = type(error).__name__
        try:
            if directory.exists():
                shutil.rmtree(directory)
            receipt['vendor_staging_removed'] = not directory.exists()
        except BaseException as error:
            receipt['vendor_staging_removed'] = False
            receipt['vendor_cleanup_error_type'] = type(error).__name__
        receipt['complete'] = ('error_type' not in receipt and
                               receipt.get('hkcu_restore_verified') is True and
                               receipt.get('hklm_unchanged') is True and
                               receipt.get('state_file_restored') is True and
                               receipt.get('vendor_staging_removed') is True)
        # Keep private .reg backups in the guest if restoration is uncertain.
        try:
            if receipt['complete']:
                for row in records:
                    Path(row['backup_path']).unlink(missing_ok=True)
            receipt['registry_backups_removed'] = (
                receipt['complete'] and
                all(not Path(row['backup_path']).exists() for row in records)
            )
        except BaseException as error:
            receipt['registry_backups_removed'] = False
            receipt['backup_cleanup_error_type'] = type(error).__name__
    return receipt


def main() -> int:
    tag, state, result = sys.argv[1:]
    receipt = {'format': 'cbus-p902-original-gui-same-user-v1', 'complete': False}
    try:
        receipt = run(tag, Path(state))
    except BaseException as error:
        receipt['error_type'] = type(error).__name__
    Path(result).write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n',
                            encoding='utf-8')
    return 0 if receipt.get('complete') else 1


if __name__ == '__main__':
    raise SystemExit(main())
