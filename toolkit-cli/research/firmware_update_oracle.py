"""Original FirmwareUpdater step-sequence oracle under the owned macOS Mono runtime.

Runs NativeFirmwareUpdateProbe.cs, which invokes the unchanged private
UnzipFirmwarePackage and UpgradeFirmware methods of Toolkit 1.18's updater,
with a dfuprog stub that records argv and the SHA-256 of each -f file. The
report is sanitized: temporary paths become ``<extracted:NAME>``, and neither
the package password nor plaintext image data is retained. No USB device,
driver, dfuprog.exe or physical serial port is executed or opened.

    CBUS_MONO_MACOS_ROOT=.../Mono.framework/Versions/6.12.0 \\
    CBUS_FIRMWARE_UPDATER=.../toolkit/app/FirmwareUpdater.exe \\
    python research/firmware_update_oracle.py --output report.json \\
        [--package-password-file private-file]
"""
from __future__ import annotations
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))
from research import firmware_oracle  # noqa: E402
from cbus_toolkit import firmware_update_plan as plans  # noqa: E402
from cbus_toolkit.firmware_diagnostics import package_version  # noqa: E402

PROBE = Path(__file__).resolve().with_name('NativeFirmwareUpdateProbe.cs')
PROBE_SHA256 = 'becd82054938d3b427e90245a4d526cde6d8e6cec3ca4350540b792d3b419c58'
RUNTIME_HASHES = {**firmware_oracle.RUNTIME_HASHES,
    'lib/mono/4.5/System.Windows.Forms.dll': 'fa3a88fd4a3c19af300a34ca2884c6271cb77b4765776b1bc1580a8381d11c96',
    'lib/mono/4.5/System.Drawing.dll': '0938e49c506ff253de33c4a5c85af732381bcefdb71fe439d23828b5bfbfb805',
    'lib/mono/gac/System.Windows.Forms/4.0.0.0__b77a5c561934e089/System.Windows.Forms.dll': 'fa3a88fd4a3c19af300a34ca2884c6271cb77b4765776b1bc1580a8381d11c96',
    'lib/mono/gac/System.Drawing/4.0.0.0__b03f5f7f11d50a3a/System.Drawing.dll': '0938e49c506ff253de33c4a5c85af732381bcefdb71fe439d23828b5bfbfb805'}
VENDOR_HASHES = {**firmware_oracle.VENDOR_HASHES,
    'EDLTCommon.dll': '41c740d2376f98cfcce20a58eb1ba2a7ea0629a8a2f56ef6a1bf134cae5da3e2',
    'GlobalCommon.dll': '9f1328be4fab00366add4fc25239ed1c3feaea698b4a3413b1ee37e78abc210c',
    'Firmware/eDLTFirmware/dfuprog.exe': 'fb3f46f81fd1878cba2cde47f72dceaa9e1b4ac1be0e083c33901a34d130aa0e'}
PACKAGES = tuple(sorted(Path(name).name for name in VENDOR_HASHES if name.endswith('.zip')))
STUB_EXIT_CODE = 3
STUB = '''#!{python}
import hashlib, json, os, sys, time
from pathlib import Path
log = Path(__file__).with_name('invocations.jsonl')
index = sum(1 for _ in log.open()) + 1 if log.exists() else 1
row = {{'index': index, 'argv': sys.argv[1:], 'time': time.time()}}
if '-f' in sys.argv[1:-1]:
    target = Path(sys.argv[sys.argv.index('-f') + 1])
    if target.is_file():
        data = target.read_bytes(); row.update(file_bytes=len(data), file_sha256=hashlib.sha256(data).hexdigest())
    else:
        row['file_missing'] = True
code = {code} if os.environ.get('STUB_FAIL_AT') == str(index) else 0
row['exit_code'] = code
with log.open('a') as out: out.write(json.dumps(row) + '\\n')
sys.exit(code)
'''


def _files(directory, hashes):
    firmware_oracle.MacOSFirmwareOracle._check_files(directory, hashes)


def parse_output(text):
    rows = []
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) != 3:
            raise ValueError('Unexpected probe output line')
        rows.append(tuple([parts[0]] + [base64.b64decode(part).decode('utf-8') for part in parts[1:]]))
    return rows


class UpdateOracle:
    """Pinned inputs, one compile and independent per-case directories."""

    def __init__(self, app, *, mono_root=None, timeout=120):
        if platform.system() != 'Darwin':
            raise ValueError('macos-mono requires macOS')
        root = mono_root or os.environ.get('CBUS_MONO_MACOS_ROOT')
        if not root:
            raise ValueError('Explicit CBUS_MONO_MACOS_ROOT is required')
        self.runtime, self.app, self.timeout = Path(root).resolve(), Path(app).resolve(), timeout
        self.verify()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith(('MONO_', 'DYLD_'))}
        self.env.update(MONO_CFG_DIR=str(self.runtime / 'etc'),
                        MONO_PATH=str(self.app) + ':' + str(self.runtime / 'lib/mono/4.5'),
                        DYLD_FALLBACK_LIBRARY_PATH=str(self.runtime / 'lib'))
        self._temporary = tempfile.TemporaryDirectory(prefix='cbus-firmware-update-')
        self.work = Path(self._temporary.name).resolve()
        self.compiled = None

    def verify(self):
        _files(self.runtime, RUNTIME_HASHES)
        _files(self.app, VENDOR_HASHES)
        if hashlib.sha256(PROBE.read_bytes()).hexdigest() != PROBE_SHA256:
            raise ValueError('Pinned firmware update probe differs')

    def compile(self):
        if self.compiled is not None:
            raise RuntimeError('One compile per oracle')
        (self.work / PROBE.name).write_bytes(PROBE.read_bytes())
        (self.work / 'NativeFirmwareUpdateProbe.exe.config').write_bytes(firmware_oracle.DLLMAP)
        self.compiled = subprocess.run([str(self.runtime / 'bin/mono-sgen64'), str(self.runtime / 'lib/mono/4.5/mcs.exe'),
            '-r:' + str(self.app / 'FirmwareUpdater.exe'), '-r:System.Windows.Forms.dll', PROBE.name],
            cwd=self.work, env=self.env, capture_output=True, text=True, timeout=self.timeout)
        self.verify()
        if self.compiled.returncode:
            raise RuntimeError('Probe compilation failed: ' + self.compiled.stderr[-2000:])
        return hashlib.sha256((self.work / 'NativeFirmwareUpdateProbe.exe').read_bytes()).hexdigest()

    def run_case(self, name, package, variant, force, *, fail_at=None, serial_replies=None):
        case = self.work / name
        (case / 'tmp').mkdir(parents=True)
        (case / 'stub').mkdir()
        stub = case / 'stub' / 'dfuprog.exe'
        stub.write_text(STUB.format(python=sys.executable, code=STUB_EXIT_CODE))
        stub.chmod(0o700)
        env = dict(self.env, TMPDIR=str(case / 'tmp') + '/')
        if fail_at is not None:
            env['STUB_FAIL_AT'] = str(fail_at)
        args = [str(self.runtime / 'bin/mono-sgen64'), str(self.work / 'NativeFirmwareUpdateProbe.exe'),
                str(self.app / 'Firmware/eDLTFirmware' / package), plans.VARIANT_HARDWARE[variant],
                '1' if force else '0', str(case / 'stub')]
        if serial_replies is not None:
            args.append('|'.join(serial_replies))
        started = time.time()
        completed = subprocess.run(args, cwd=self.work, env=env, capture_output=True, text=True, timeout=self.timeout)
        leftovers = sorted(path.name for path in (case / 'tmp').iterdir())
        log = case / 'stub' / 'invocations.jsonl'
        invocations = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return self._record(package, variant, force, fail_at, completed, invocations, leftovers, case, started)

    @staticmethod
    def _record(package, variant, force, fail_at, completed, invocations, leftovers, case, started):
        prefix, stub = str(case / 'tmp') + '/', str(case / 'stub') + '/'

        def clean(text):
            return text.replace(prefix, '$TMP/').replace(stub, '$UPDATER/')
        rows = parse_output(completed.stdout)
        extracted = {}
        for category, key, value in rows:
            if category == 'extracted' and value:
                parts = value.split('|')
                extracted[key] = {'entry': parts[0], 'bytes': int(parts[1]), 'sha256': parts[2]} if len(parts) == 3 else {'entry': parts[0], 'missing': True}
        dfuprog, previous = [], started
        for row in invocations:
            argv = [('<extracted:' + item[len(prefix):] + '>') if item.startswith(prefix) else item for item in row['argv']]
            dfuprog.append({'argv': argv, 'file_bytes': row.get('file_bytes'), 'file_sha256': row.get('file_sha256'),
                            'exit_code': row['exit_code'], 'gap_seconds': round(row['time'] - previous, 1)})
            previous = row['time']
        results = [(key, clean(value)) for category, key, value in rows if category == 'result']
        return {'package': package, 'variant': variant, 'hardware_version': plans.VARIANT_HARDWARE[variant],
                'force_font': force, 'fail_at': fail_at, 'probe_exit_code': completed.returncode,
                'stderr_empty': not completed.stderr.strip(),
                'assembly_version': next((value for category, key, value in rows if category == 'assembly'), None),
                'native_variant': next((value for category, key, value in rows if category == 'variant'), None),
                'package_version': next((value for category, key, value in rows if category == 'package'), None),
                'extracted': extracted, 'dfuprog': dfuprog,
                'serial_commands': [value for category, key, value in rows if category == 'serial-command'],
                'progress': [clean(value) for category, key, value in rows if category == 'progress' and value],
                'result': results[-1] if results else None, 'temporary_files_left': leftovers}

    def close(self):
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


def default_cases():
    cases = []
    for package in PACKAGES:
        for variant in plans.MAIN_ADDRESS_TEXT:
            for force in (False, True):
                cases.append({'package': package, 'variant': variant, 'force': force})
    for fail_at in range(1, 6):
        cases.append({'package': 'eDLTFirmware_1.7.0.zip', 'variant': 'TivaPCI', 'force': True, 'fail_at': fail_at})
    return cases


def ncc_replies(version):
    identity = ('Manufacturer=Clipsal\\r\\nProduct=eDLT\\r\\nSerial Number=1\\r\\nHW Version=3.0 (Tiva + NCC)\\r\\n'
                'FW Version=' + version + '\\r\\nCPU Speed=120\\r\\nUnit Address=20\\r\\n')
    return [identity, 'NCC current version: 1.0.0\\r\\nNCC embedded version: 1.1.0\\r\\n']


def compare(case, plan, decrypted=None):
    """Compare one original execution with update-plan; return named checks."""
    expected = [step['argv'] for step in plan['dfuprog_steps']]
    if case['fail_at'] is not None:
        expected = expected[:case['fail_at']]
    observed = [row['argv'] for row in case['dfuprog']]
    checks = {'argv_sequence': observed == expected,
              'native_variant': case['native_variant'] == plan['variant'],
              'package_version': case['package_version'] == plan['package']['version'],
              'temporary_files_removed': not case['temporary_files_left']}
    extracted = {row['entry']: row for row in case['extracted'].values()}
    checks['extracted_entries'] = sorted(extracted) == sorted(plan['package']['extracted_entries'])
    files = []
    for step, row in zip(plan['dfuprog_steps'], case['dfuprog']):
        if 'entry' in step:
            files.append(row['file_sha256'] == extracted.get(step['entry'], {}).get('sha256')
                         and row['file_bytes'] == step['bytes'])
    checks['file_arguments'] = all(files)
    delays = [row['gap_seconds'] >= step['delay_before_ms'] / 1000 - 0.05
              for step, row in zip(plan['dfuprog_steps'][1:], case['dfuprog'][1:])]
    checks['delays'] = all(delays)
    if decrypted is not None:
        checks['decrypt_adapter_hashes'] = all(decrypted.get(name) == row['sha256'] for name, row in extracted.items())
    result = case['result']
    if not plan['supported']:
        checks['refusal'] = result is not None and result[0] == 'dowork' and result[1] in plan['issues'] and not observed
    elif case['fail_at'] is not None:
        message = plan['dfuprog_steps'][case['fail_at'] - 1]['failure_message'].format(exit_code=STUB_EXIT_CODE)
        checks['failure_stop'] = result == ('exception', 'Exception|' + message + '|False')
    elif plan['variant'] == 'TivaNCC':
        # Mono never raises SerialPort.DataReceived, so the original times out
        # after sending the first post-write identify request.
        checks['ncc_first_request'] = case['serial_commands'] == ['id']
        checks['ncc_mono_limit'] = result == ('exception', 'Exception|Timed out while waiting for response from unit|False')
    else:
        checks['success'] = result == ('upgrade', 'returned') and not case['serial_commands']
    return checks


def build_report(app, *, mono_root=None, password=None, cases=None, workers=6):
    app = Path(app).resolve()
    package_dir = app / 'Firmware/eDLTFirmware'
    decrypted = {}
    if password is not None:
        for package in PACKAGES:
            inspection = plans.inspect_package_images(package_dir / package, password)
            decrypted[package] = {row['name']: row['sha256'] for row in inspection['images']}
    oracle = UpdateOracle(app, mono_root=mono_root)
    try:
        compiled = oracle.compile()
        work = []
        for index, spec in enumerate(cases or default_cases()):
            package, variant, force = spec['package'], spec['variant'], spec['force']
            replies = ncc_replies(package_version(package)) if variant == 'TivaNCC' else None
            work.append((f'case{index:02d}', package, variant, force, spec.get('fail_at'), replies))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            records = list(pool.map(lambda item: oracle.run_case(item[0], item[1], item[2], item[3],
                                    fail_at=item[4], serial_replies=item[5]), work))
        oracle.verify()
    finally:
        oracle.close()
    rows = []
    for record in records:
        plan = plans.update_plan(package_dir / record['package'], variant=record['variant'], force_font=record['force_font'])
        record['plan_argv'] = [step['argv'] for step in plan['dfuprog_steps']]
        record['plan_supported'] = plan['supported']
        record['checks'] = compare(record, plan, decrypted.get(record['package']) if decrypted else None)
        rows.append(record)
    passed = all(all(row['checks'].values()) and row['probe_exit_code'] == 0 for row in rows)
    return {'format': 'cbus-firmware-update-plan-original-oracle-v1', 'status': 'passed' if passed else 'failed',
            'scope': ('Unchanged Toolkit 1.18 FirmwareUpdater UnzipFirmwarePackage/UpgradeFirmware under task-local macOS Mono '
                      'with an argv-recording dfuprog stub; no USB, driver, dfuprog.exe or physical serial device'),
            'backend': 'macos-mono', 'runtime_version': '6.12.0.206',
            'runtime_hashes': dict(RUNTIME_HASHES), 'vendor_hashes': dict(VENDOR_HASHES),
            'probe_sha256': PROBE_SHA256, 'compiled_probe_sha256': compiled,
            'source_hashes': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (
                'src/cbus_toolkit/firmware_update_plan.py', 'research/firmware_update_oracle.py',
                'research/NativeFirmwareUpdateProbe.cs')},
            'retyped_glue': 'FirmwareUpgrader_DoWork argument assignments and required-file check (unit discovery uses WMI)',
            'mono_limits': ['System.IO.Ports.SerialPort.DataReceived is not raised, so the NCC branch stops at the first id timeout',
                            'The ForceFontUpgradeCheckBox is an uninitialized CheckBox whose check_state is set; constructing one needs GDI+'],
            'decrypt_adapter_compared': password is not None,
            'password_reported': False, 'plaintext_retained': False, 'physical_hardware_accessed': False,
            'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--package-password-file', type=Path)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    updater = os.environ.get('CBUS_FIRMWARE_UPDATER')
    if not updater:
        raise SystemExit('CBUS_FIRMWARE_UPDATER must name the original FirmwareUpdater.exe')
    password = plans.read_password_file(args.package_password_file)[0] if args.package_password_file else None
    report = build_report(Path(updater).parent, password=password, workers=args.workers)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(report['status'], len(report['cases']))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
