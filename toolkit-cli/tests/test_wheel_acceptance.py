"""Reject incomplete or mismatched installed-wheel acceptance evidence."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from research.acceptance import input_files
from research.audit_wheel_acceptance import audit, main as audit_main


class WheelAcceptanceAuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        payloads = {'src/cbus_toolkit/__init__.py': b'__version__ = "0.1.0"\n',
                    'src/cbus_toolkit/cli.py': b'def main(): return 0\n',
                    'src/cbus_toolkit/capabilities.json': b'{"census_complete":false,"features":[]}',
                    'tests/test_fixture.py': b'# explicit synthetic audit fixture\n',
                    'research/fixtures/original-vectors.txt': b'original:mode=2:colour=8\n',
                    'research/original_oracle.py': b'# synthetic backend marker\n',
                    'pyproject.toml': b'[project]\nname="audit-fixture"\n', 'README.md': b'Audit fixture\n'}
        self.hashes = {}
        for name, contents in payloads.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
            self.hashes[name] = hashlib.sha256(contents).hexdigest()
        wheel = self.root / 'fixture.whl'
        with zipfile.ZipFile(wheel, 'w') as archive:
            for name, contents in payloads.items():
                if name.startswith('src/'):
                    archive.writestr(name.removeprefix('src/'), contents)
        manifest = {'format': 'cbus-installed-wheel-snapshot-v1', 'input_sha256': self.hashes,
                    'wheel': wheel.name, 'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    'package_files': sorted(name.removeprefix('src/') for name in payloads if name.startswith('src/'))}
        (self.root / 'snapshot.json').write_text(json.dumps(manifest))
        self.report = {'format': 'cbus-test-acceptance-v1', 'passed': True, 'test_success': True,
                       'require_no_skips': True, 'tests_run': 1, 'test_files': ['tests/test_fixture.py'],
                       'input_sha256': {k: v for k, v in self.hashes.items() if k != 'README.md'},
                       'package_location': '/owned/venv/lib/python3.13/site-packages/cbus_toolkit/__init__.py',
                       'python': '3.13.1', 'started_at': '2026-01-01T00:00:00+00:00', 'duration_seconds': 1,
                       'openssl': 'synthetic', 'package_version': '0.1.0', 'toolkit_parity_complete': False,
                       'scope': 'Synthetic audit fixture, not a real acceptance run',
                       'backend_selectors': {'CBUS_ORIGINAL_MODEL_BACKEND': 'windows',
                           'CBUS_EDLT_LIFECYCLE_ORIGINAL_BACKEND': 'windows',
                           'CBUS_NATIVE_SERVICE_BACKEND': 'local', 'CBUS_WINDOWS_BRIDGE': True},
                       'imported_package_module_sha256': {'cbus_toolkit': self.hashes['src/cbus_toolkit/__init__.py'],
                                                         'cbus_toolkit.cli': self.hashes['src/cbus_toolkit/cli.py']},
                       'enabled_native_gates': {name: True for name in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR',
                           'CBUS_TOOLKIT_HELP_DIR', 'CBUS_TOOLKIT_EXE', 'CBUS_SCENE_NATIVE', 'CBUS_NATIVE_TLS_TEST')}}
        self.report.update({name: 0 for name in ('failures', 'errors', 'expected_failures', 'unexpected_successes')})
        self.report.update({name: [] for name in ('skipped', 'failed_tests', 'inputs_changed_during_run',
            'inputs_added_during_run', 'inputs_removed_during_run', 'test_files_added_during_run', 'source_files_added_during_run')})

    def run_audit(self, report=None, *, historical=False):
        primary = self.report if report is None else report
        first = self.root / 'first.json'
        first.write_text(json.dumps(primary))
        if not historical:
            return audit(self.root, [first])
        secondary = copy.deepcopy(primary)
        secondary['python'] = '3.10.9'
        paths = [self.root / 'first.json', self.root / 'second.json']
        for path, data in zip(paths, (primary, secondary)):
            path.write_text(json.dumps(data))
        return audit(self.root, paths, python_versions=('3.13', '3.10'))

    def test_matching_full_reports_keep_parity_separate(self):
        result = self.run_audit()
        self.assertTrue(result['passed'])
        self.assertFalse(result['toolkit_parity_complete'])
        self.assertEqual(result['validated_python_versions'], ['3.13.1'])
        self.assertEqual(result['additional_python_validation'], [])

    def test_historical_dual_reports_remain_auditable_with_explicit_versions(self):
        result = self.run_audit(historical=True)
        self.assertEqual(result['validated_python_versions'], ['3.13.1', '3.10.9'])
        self.assertTrue(result['additional_python_validation'][0]['same_input_hashes'])
        paths = [self.root / 'first.json', self.root / 'second.json']
        with self.assertRaisesRegex(ValueError, 'requested Python versions'):
            audit(self.root, paths)

    def test_cli_defaults_to_313_and_accepts_explicit_historical_versions(self):
        self.run_audit(historical=True)
        first, second = self.root / 'first.json', self.root / 'second.json'
        cases = [(['--report', str(first)], 0, ['3.13.1']),
                 (['--report', str(first), '--report', str(second)], 1, None),
                 (['--report', str(first), '--report', str(second),
                   '--python', '3.13', '--python', '3.10'], 0, ['3.13.1', '3.10.9'])]
        for options, expected_exit, versions in cases:
            with self.subTest(options=options):
                output = io.StringIO()
                with patch('sys.argv', ['audit', str(self.root), *options]), redirect_stdout(output):
                    self.assertEqual(audit_main(), expected_exit)
                report = json.loads(output.getvalue())
                self.assertIs(report['passed'], expected_exit == 0)
                if versions is not None:
                    self.assertEqual(report['validated_python_versions'], versions)

    def test_parity_requires_complete_census_and_every_implemented_acceptance_feature(self):
        cases = [(False, 'implemented', False), (True, 'in_progress', False),
                 (True, 'pending', False), (True, 'verified', False), (True, 'implemented', True)]
        for census, acceptance_status, expected in cases:
            with self.subTest(census=census, acceptance_status=acceptance_status):
                ledger = {'census_complete': census, 'features': [
                    {'id': 'project-storage', 'status': 'implemented'},
                    {'id': 'toolkit-differential-acceptance', 'status': acceptance_status},
                    {'id': 'unit-hardware-acceptance', 'status': acceptance_status}]}
                raw = json.dumps(ledger).encode()
                name = 'src/cbus_toolkit/capabilities.json'
                value = self.add_snapshot_input(name, raw)
                self.report['input_sha256'][name] = value
                wheel_path = self.root / 'fixture.whl'
                with zipfile.ZipFile(wheel_path) as wheel:
                    entries = {entry: wheel.read(entry) for entry in wheel.namelist()}
                entries['cbus_toolkit/capabilities.json'] = raw
                with zipfile.ZipFile(wheel_path, 'w') as wheel:
                    for entry, contents in entries.items():
                        wheel.writestr(entry, contents)
                manifest_path = self.root / 'snapshot.json'
                manifest = json.loads(manifest_path.read_text())
                manifest['wheel_sha256'] = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
                manifest_path.write_text(json.dumps(manifest))
                self.report['toolkit_parity_complete'] = expected
                result = self.run_audit()
                self.assertIs(result['toolkit_parity_complete'], expected)
                self.report['toolkit_parity_complete'] = not expected
                with self.assertRaisesRegex(ValueError, 'Report parity differs'):
                    self.run_audit()

    def test_incomplete_failed_or_different_report_is_rejected(self):
        mutations = [('passed', False), ('failures', 1), ('expected_failures', 1), ('skipped', ['fixture']),
                     ('require_no_skips', False), ('tests_run', 0), ('test_files', []), ('input_sha256', {}),
                     ('inputs_added_during_run', ['new.py']), ('enabled_native_gates', {}),
                     ('backend_selectors', {}),
                     ('package_location', '/source/src/cbus_toolkit/__init__.py'),
                     ('imported_package_module_sha256', {'cbus_toolkit': 'wrong', 'cbus_toolkit.cli': 'wrong'}),
                     ('toolkit_parity_complete', True), ('python', '3.12.1')]
        for name, value in mutations:
            with self.subTest(field=name):
                report = copy.deepcopy(self.report)
                report[name] = value
                with self.assertRaises(ValueError):
                    self.run_audit(report)

    def test_modified_snapshot_source_or_wheel_is_rejected(self):
        for name in ('src/cbus_toolkit/cli.py', 'research/fixtures/original-vectors.txt'):
            with self.subTest(input=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(b'changed acceptance input')
                with self.assertRaisesRegex(ValueError, 'Snapshot file changed'):
                    self.run_audit()
                path.write_bytes(original)
        (self.root / 'fixture.whl').write_bytes(b'changed wheel')
        with self.assertRaisesRegex(ValueError, 'Wheel hash differs'):
            self.run_audit()

    def test_duplicate_minor_versions_and_missing_reports_are_rejected(self):
        path = self.root / 'report.json'
        path.write_text(json.dumps(self.report))
        with self.assertRaisesRegex(ValueError, 'Duplicate Python'):
            audit(self.root, [path, path])
        with self.assertRaisesRegex(ValueError, 'At least one report'):
            audit(self.root, [])

    def test_input_selection_keeps_original_vectors_outside_package(self):
        fixture = self.root / 'research/fixtures/original-vectors.txt'
        runtime = self.root / 'research/runtime/transient-output.txt'
        runtime.parent.mkdir(parents=True)
        runtime.write_text('Transient output is not a trusted fixture')
        with patch('research.acceptance.ROOT', self.root):
            selected = input_files('test_*.py')
        self.assertIn(fixture, selected)
        self.assertNotIn(runtime, selected)
        self.assertIn(self.root / 'tests/test_fixture.py', selected)
        with zipfile.ZipFile(self.root / 'fixture.whl') as wheel:
            self.assertNotIn('research/fixtures/original-vectors.txt', wheel.namelist())

    def test_unknown_or_mismatched_backends_are_rejected(self):
        report = copy.deepcopy(self.report)
        report['backend_selectors']['CBUS_ORIGINAL_MODEL_BACKEND'] = 'fallback'
        with self.assertRaisesRegex(ValueError, 'Invalid backend selector'): self.run_audit(report)
        report = copy.deepcopy(self.report)
        report['backend_selectors']['CBUS_WINDOWS_BRIDGE'] = 1
        with self.assertRaisesRegex(ValueError, 'Invalid backend selector'): self.run_audit(report)
        first, second = self.root / 'first.json', self.root / 'second.json'
        first.write_text(json.dumps(self.report))
        report = copy.deepcopy(self.report); report['python'] = '3.10.9'
        report['backend_selectors']['CBUS_NATIVE_SERVICE_BACKEND'] = 'docker'
        second.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'Reports disagree: backend_selectors'):
            audit(self.root, [first, second], python_versions=('3.13', '3.10'))

    def test_macos_firmware_backend_requires_explicit_owned_runtime(self):
        name = 'research/firmware_oracle.py'; raw = b'# owned firmware backend marker\n'
        (self.root / name).write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        manifest = json.loads((self.root / 'snapshot.json').read_text())
        manifest['input_sha256'][name] = digest
        (self.root / 'snapshot.json').write_text(json.dumps(manifest))
        self.report['input_sha256'][name] = digest
        with self.assertRaisesRegex(ValueError, 'backend selectors'): self.run_audit()
        self.report['backend_selectors']['CBUS_FIRMWARE_ORACLE_BACKEND'] = 'automatic-fallback'
        with self.assertRaisesRegex(ValueError, 'Invalid backend selector'): self.run_audit()
        self.report['backend_selectors']['CBUS_FIRMWARE_ORACLE_BACKEND'] = 'macos-mono'
        with self.assertRaisesRegex(ValueError, 'owned Mono runtime gate'): self.run_audit()
        self.report['enabled_native_gates']['CBUS_MONO_MACOS_ROOT'] = True
        self.assertTrue(self.run_audit()['passed'])
        self.report['backend_selectors']['CBUS_FIRMWARE_ORACLE_BACKEND'] = 'docker'
        del self.report['enabled_native_gates']['CBUS_MONO_MACOS_ROOT']
        self.assertTrue(self.run_audit()['passed'])


    def test_windows_provenance_helper_requires_explicit_owned_root(self):
        name = 'research/windows_provenance.py'; raw = b'# live-verified bridge provenance marker\n'
        (self.root / name).write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        manifest = json.loads((self.root / 'snapshot.json').read_text())
        manifest['input_sha256'][name] = digest
        (self.root / 'snapshot.json').write_text(json.dumps(manifest))
        self.report['input_sha256'][name] = digest
        with self.assertRaisesRegex(ValueError, 'explicit owned provenance root'): self.run_audit()
        self.report['enabled_native_gates']['CBUS_WINDOWS_PROVENANCE_ROOT'] = True
        self.assertTrue(self.run_audit()['passed'])
        self.report['backend_selectors']['CBUS_WINDOWS_BRIDGE'] = False
        del self.report['enabled_native_gates']['CBUS_WINDOWS_PROVENANCE_ROOT']
        self.assertTrue(self.run_audit()['passed'])

    def test_mock_test_requires_explicit_gate_and_unchanged_binary_evidence(self):
        name = 'tests/test_rust_cgate_interop.py'
        value = self.add_snapshot_input(name, b'# Explicit mock integration fixture\n')
        self.report['input_sha256'][name] = value
        self.report['test_files'] = sorted([*self.report['test_files'], name])
        self.report['tests_run'] = 2
        with self.assertRaisesRegex(ValueError, 'every required native gate'):
            self.run_audit()
        self.report['enabled_native_gates']['CBUS_CGATE_MOCK_BIN'] = True
        with self.assertRaisesRegex(ValueError, 'explicit mock binary evidence'):
            self.run_audit()
        binary = {'path': '/owned/bin/cgate-mock', 'sha256': 'a' * 64, 'size_bytes': 1234}
        self.report['external_test_binaries_before'] = {'CBUS_CGATE_MOCK_BIN': binary}
        self.report['external_test_binaries_after'] = copy.deepcopy(self.report['external_test_binaries_before'])
        self.report['external_test_binary_errors'] = []
        result = self.run_audit()
        self.assertEqual(result['external_test_binaries_before'], self.report['external_test_binaries_before'])
        for field, value in [('path', 'relative/mock'), ('sha256', 'invalid'), ('size_bytes', True), ('size_bytes', 0)]:
            with self.subTest(field=field, value=value):
                report = copy.deepcopy(self.report)
                report['external_test_binaries_before']['CBUS_CGATE_MOCK_BIN'][field] = value
                with self.assertRaisesRegex(ValueError, 'Invalid explicit mock binary evidence'):
                    self.run_audit(report)
        report = copy.deepcopy(self.report)
        report['external_test_binaries_after']['CBUS_CGATE_MOCK_BIN']['sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'Mock binary changed'):
            self.run_audit(report)
        report = copy.deepcopy(self.report)
        report['external_test_binary_errors'] = ['CBUS_CGATE_MOCK_BIN']
        with self.assertRaisesRegex(ValueError, 'Mock binary changed'):
            self.run_audit(report)

    def add_snapshot_input(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        value = hashlib.sha256(contents).hexdigest()
        manifest = json.loads((self.root / 'snapshot.json').read_text())
        manifest['input_sha256'][name] = value
        (self.root / 'snapshot.json').write_text(json.dumps(manifest))
        return value

    def test_documented_external_snapshot_matches_dual_reports(self):
        self.add_snapshot_input('docs/acceptance.md', b'Pinned scope, separate from executed inputs.\n')
        self.add_snapshot_input('docs/Unicode scope \u0101.md', b'Another pinned document.\n')
        with patch('research.acceptance.ROOT', self.root):
            selected = {str(path.relative_to(self.root)) for path in input_files('test_*.py')}
        self.assertEqual(selected, set(self.report['input_sha256']))
        self.assertNotIn('docs/acceptance.md', selected)
        self.assertFalse(self.root.is_relative_to(Path(__file__).resolve().parents[1]))
        result = self.run_audit(historical=True)
        self.assertTrue(result['passed'])
        self.assertEqual(result['input_sha256'], self.report['input_sha256'])
        self.assertEqual(result['validated_python_versions'], ['3.13.1', '3.10.9'])
        self.assertEqual(result['snapshot_manifest_sha256'],
                         hashlib.sha256((self.root / 'snapshot.json').read_bytes()).hexdigest())

    def test_documentation_is_verified_before_report_input_exclusion(self):
        name = 'docs/acceptance.md'
        contents = b'The exact documented scope.\n'
        self.add_snapshot_input(name, contents)
        path = self.root / name
        path.write_bytes(b'Changed scope.\n')
        with self.assertRaisesRegex(ValueError, 'Snapshot file changed: docs/acceptance.md'):
            self.run_audit()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or external snapshot file: docs/acceptance.md'):
            self.run_audit()
        path.write_bytes(contents)
        with tempfile.TemporaryDirectory() as folder:
            outside = Path(folder) / 'acceptance.md'
            outside.write_bytes(contents)
            path.unlink()
            path.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'Missing or external snapshot file: docs/acceptance.md'):
                self.run_audit()

    def test_documentation_exclusion_is_only_direct_markdown(self):
        for name in ('docs/nested/scope.md', 'docs/scope.txt', 'docs/scope.MD'):
            with self.subTest(name=name):
                value = self.add_snapshot_input(name, b'Not a direct Markdown documentation input.\n')
                with self.assertRaisesRegex(ValueError, 'Report input hashes differ'):
                    self.run_audit()
                self.report['input_sha256'][name] = value
                self.assertTrue(self.run_audit()['passed'])

    def test_extra_report_inputs_and_dual_report_mismatch_still_reject(self):
        self.add_snapshot_input('docs/acceptance.md', b'Pinned documentation.\n')
        for name in ('docs/acceptance.md', 'unknown-input.py', 'docs/nested/unknown.md'):
            with self.subTest(name=name):
                report = copy.deepcopy(self.report)
                report['input_sha256'][name] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'Report input hashes differ'):
                    self.run_audit(report)
        first, second = self.root / 'first.json', self.root / 'second.json'
        first.write_text(json.dumps(self.report))
        report = copy.deepcopy(self.report)
        report['python'] = '3.10.9'
        report['input_sha256']['research/fixtures/original-vectors.txt'] = '0' * 64
        second.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'Report input hashes differ'):
            audit(self.root, [first, second], python_versions=('3.13', '3.10'))

    def test_documentation_path_traversal_is_rejected_before_exclusion(self):
        original = (self.root / 'snapshot.json').read_text()
        for name in ('../outside.md', '/tmp/outside.md', 'docs/../README.md',
                     'docs/../../outside.md', 'docs\\outside.md', ''):
            with self.subTest(name=name):
                manifest = json.loads(original)
                manifest['input_sha256'][name] = '0' * 64
                (self.root / 'snapshot.json').write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, 'Invalid snapshot file path|Missing or external snapshot file'):
                    self.run_audit()
        (self.root / 'snapshot.json').write_text(original)


if __name__ == '__main__':
    unittest.main()
