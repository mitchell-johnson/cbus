#!/usr/bin/env python3
"""Audit completed installed-wheel reports against one immutable snapshot.

This checks recorded evidence; it neither runs tests nor establishes Toolkit
parity. Input reports and the snapshot must come from trusted local runners.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def relative_file(root, name):
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and '\\' not in name,
            'Invalid snapshot file path: ' + name)
    result = root.joinpath(*path.parts)
    require(result.is_file() and result.resolve().is_relative_to(root), 'Missing or external snapshot file: ' + name)
    return result


def audit(snapshot, report_paths, *, python_versions=('3.13', '3.10')):
    require(report_paths and python_versions, 'At least one report and Python version are required')
    snapshot = Path(snapshot).resolve()
    manifest_path = snapshot / 'snapshot.json'
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get('format') == 'cbus-installed-wheel-snapshot-v1', 'Unsupported snapshot manifest')
    inputs = manifest['input_sha256']
    for name, expected in inputs.items():
        require(digest(relative_file(snapshot, name)) == expected, 'Snapshot file changed: ' + name)
    wheel_path = relative_file(snapshot, manifest['wheel'])
    require(digest(wheel_path) == manifest['wheel_sha256'], 'Wheel hash differs from the snapshot manifest')
    package_hashes = {name.removeprefix('src/'): value for name, value in inputs.items()
                      if name.startswith('src/cbus_toolkit/')}
    require(package_hashes, 'Snapshot has no package source')
    require(sorted(package_hashes) == manifest['package_files'], 'Manifest package file list differs from its source')
    with zipfile.ZipFile(wheel_path) as wheel:
        names = wheel.namelist()
        require(len(names) == len(set(names)), 'Wheel has duplicate entries')
        require({name for name in names if name.startswith('cbus_toolkit/')} == set(package_hashes),
                'Wheel package file list differs from the snapshot')
        for name, expected in package_hashes.items():
            require(hashlib.sha256(wheel.read(name)).hexdigest() == expected, 'Wheel source differs: ' + name)
        ledger = json.loads(wheel.read('cbus_toolkit/capabilities.json'))
        parity = bool(ledger['census_complete'] and all(row['status'] == 'verified' for row in ledger['features']))
    # Snapshots may additionally pin direct documentation files. They are
    # verified above, but acceptance.input_files() does not execute/select them.
    # Keep this exclusion narrow: nested docs and other suffixes are not silently
    # discarded from the exact report-input comparison.
    expected_inputs = {name: value for name, value in inputs.items()
                       if name not in ('README.md', 'COPYING', 'COPYING.LESSER')
                       and re.fullmatch(r'docs/[^/]+\.md', name) is None}
    expected_tests = sorted(name for name in inputs if re.fullmatch(r'tests/test_[^/]+\.py', name))
    require(expected_tests, 'Snapshot has no acceptance tests')
    gates = {'CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_HELP_DIR',
             'CBUS_TOOLKIT_EXE', 'CBUS_SCENE_NATIVE', 'CBUS_NATIVE_TLS_TEST'}
    if 'tests/test_firmware_diagnostics.py' in expected_tests:
        gates.add('CBUS_FIRMWARE_UPDATER')
    if 'tests/test_dfu.py' in expected_tests:
        gates.add('CBUS_DFU_DLL')
    if {'tests/test_edlt_restore_levels_native.py', 'tests/test_edlt_applications_native.py',
        'tests/test_edlt_corridor_native.py'} & set(expected_tests):
        gates.add('CBUS_WINDOWS_BRIDGE')
    if {'tests/test_local_cgate.py', 'tests/test_native_network_oracle.py'} & set(expected_tests):
        gates.update(('CBUS_CGATE_JAVA', 'CBUS_LOCAL_CGATE_VENDOR'))
    firmware_backend = 'research/firmware_oracle.py' in inputs
    selectors_required = firmware_backend or bool({'research/original_oracle.py', 'research/local_cgate.py'} & set(inputs))
    reports, recorded_versions = [], []
    for report_path in report_paths:
        report_path = Path(report_path)
        report = json.loads(report_path.read_text())
        require(report.get('format') == 'cbus-test-acceptance-v1', 'Unsupported test report')
        require(report.get('passed') is True and report.get('test_success') is True
                and report.get('require_no_skips') is True, 'Report is not a successful run requiring no skips')
        for name in ('failures', 'errors', 'expected_failures', 'unexpected_successes'):
            require(type(report.get(name)) is int and report[name] == 0, 'Nonzero or missing report counter: ' + name)
        for name in ('skipped', 'failed_tests', 'inputs_changed_during_run', 'inputs_added_during_run',
                     'inputs_removed_during_run', 'test_files_added_during_run', 'source_files_added_during_run'):
            require(report.get(name) == [], 'Nonempty or missing report field: ' + name)
        require(type(report.get('tests_run')) is int and report['tests_run'] > 0, 'No tests ran')
        require(report.get('toolkit_parity_complete') is parity, 'Report parity differs from the wheel capability ledger')
        require(report.get('test_files') == expected_tests, 'Report does not cover the full snapshot test suite')
        require(report.get('input_sha256') == expected_inputs, 'Report input hashes differ from the snapshot')
        require(all(report.get('enabled_native_gates', {}).get(name) is True for name in gates),
                'Report did not enable every required native gate')
        selectors = report.get('backend_selectors')
        if selectors_required or selectors is not None:
            allowed = {'CBUS_ORIGINAL_MODEL_BACKEND': ('docker', 'windows'),
                       'CBUS_EDLT_LIFECYCLE_ORIGINAL_BACKEND': ('docker', 'windows'),
                       'CBUS_NATIVE_SERVICE_BACKEND': ('docker', 'local'),
                       'CBUS_WINDOWS_BRIDGE': (False, True)}
            if firmware_backend: allowed['CBUS_FIRMWARE_ORACLE_BACKEND'] = ('docker', 'macos-mono')
            require(isinstance(selectors, dict) and set(selectors) == set(allowed),
                    'Missing or invalid backend selectors')
            for name, choices in allowed.items():
                require(selectors[name] in choices and type(selectors[name]) is type(choices[0]),
                        'Invalid backend selector: ' + name)
            if firmware_backend and selectors['CBUS_FIRMWARE_ORACLE_BACKEND'] == 'macos-mono':
                require(report.get('enabled_native_gates', {}).get('CBUS_MONO_MACOS_ROOT') is True,
                        'macos-mono backend requires the owned Mono runtime gate')
        if 'research/windows_provenance.py' in inputs and selectors and selectors['CBUS_WINDOWS_BRIDGE']:
            require(report.get('enabled_native_gates', {}).get('CBUS_WINDOWS_PROVENANCE_ROOT') is True,
                    'Windows bridge requires an explicit owned provenance root')
        location = Path(report.get('package_location', ''))
        require('site-packages' in location.parts and location.name == '__init__.py'
                and location.parent.name == 'cbus_toolkit', 'Report did not import the installed package')
        imported = report.get('imported_package_module_sha256', {})
        require({'cbus_toolkit', 'cbus_toolkit.cli'} <= imported.keys(), 'Report lacks required package import hashes')
        for name, expected in imported.items():
            source = 'cbus_toolkit/__init__.py' if name == 'cbus_toolkit' else name.replace('.', '/') + '.py'
            require(package_hashes.get(source) == expected, 'Imported module differs from the wheel: ' + name)
        version = report.get('python', '')
        require(re.fullmatch(r'\d+\.\d+\.\d+', version), 'Invalid recorded Python version')
        recorded_versions.append('.'.join(version.split('.')[:2]))
        reports.append((report, digest(report_path)))
    require(len(recorded_versions) == len(set(recorded_versions)), 'Duplicate Python minor-version reports')
    require(set(recorded_versions) == set(python_versions), 'Reports do not cover the requested Python versions')
    primary = reports[0][0]
    for report, _ in reports[1:]:
        require(report.get('backend_selectors') == primary.get('backend_selectors'),
                'Reports disagree: backend_selectors')
        for name in ('tests_run', 'test_files', 'input_sha256', 'imported_package_module_sha256',
                     'package_version', 'toolkit_parity_complete'):
            require(report[name] == primary[name], 'Reports disagree: ' + name)
    retained = ('format', 'started_at', 'duration_seconds', 'python', 'openssl', 'package_version',
                'tests_run', 'failures', 'errors', 'skipped', 'passed', 'toolkit_parity_complete', 'scope',
                'enabled_native_gates', 'test_files', 'input_sha256', 'imported_package_module_sha256')
    summary = {name: primary[name] for name in retained}
    if 'backend_selectors' in primary: summary['backend_selectors'] = primary['backend_selectors']
    summary.update(source_report_sha256=reports[0][1], wheel_sha256=manifest['wheel_sha256'],
                   wheel_package_files=manifest['package_files'], snapshot=snapshot.name,
                   snapshot_manifest_sha256=digest(manifest_path), installed_wheel=True,
                   imported_package_matches_snapshot=True, validated_python_versions=[r['python'] for r, _ in reports],
                   checkpoint_note='This checkpoint covers only the exact wheel and source hashes recorded here. '
                                   'Subsequent development changes require separate validation.',
                   additional_python_validation=[])
    for report, report_hash in reports[1:]:
        row = {name: report[name] for name in ('started_at', 'duration_seconds', 'python', 'openssl', 'tests_run',
                                              'failures', 'errors', 'skipped', 'passed', 'enabled_native_gates')}
        row.update(source_report_sha256=report_hash, same_input_hashes=True,
                   same_imported_package_hashes=True, installed_wheel=True)
        if 'backend_selectors' in report: row['backend_selectors'] = report['backend_selectors']
        summary['additional_python_validation'].append(row)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--report', type=Path, action='append', required=True)
    parser.add_argument('--python', dest='versions', action='append', help='Required minor version; defaults to 3.13 and 3.10')
    parser.add_argument('--output', type=Path, help='Write a new summary file; an existing file is never overwritten')
    args = parser.parse_args()
    try:
        summary = audit(args.snapshot, args.report, python_versions=tuple(args.versions or ('3.13', '3.10')))
        if args.output:
            with args.output.open('x') as output:
                output.write(json.dumps(summary, indent=2) + '\n')
        print(json.dumps({key: summary[key] for key in ('passed', 'tests_run', 'validated_python_versions',
                                                       'wheel_sha256', 'toolkit_parity_complete')}))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        print(json.dumps({'passed': False, 'error': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
