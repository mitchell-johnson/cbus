"""Acceptance success and ledger completion remain independent decisions."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from research import acceptance


class AcceptanceRunnerTests(unittest.TestCase):
    @staticmethod
    def successful_outcome(test_file='tests/test_fixture.py'):
        return acceptance.PytestOutcome(
            exit_code=0,
            tests_run=1,
            collected_by_file={test_file: 1},
        )

    def test_pytest_function_is_collected_and_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tests = root / 'tests'
            tests.mkdir()
            marker = root / 'executed'
            module = tests / 'test_pytest_function_exec.py'
            module.write_text(
                'from pathlib import Path\n\n'
                'def test_function_executes():\n'
                f'    Path({str(marker)!r}).write_text("executed\\n")\n'
            )
            with patch.object(acceptance, 'ROOT', root):
                outcome = acceptance.run_pytest([module], verbose=False)
            self.assertTrue(outcome.was_successful())
            self.assertEqual(outcome.tests_run, 1)
            self.assertEqual(outcome.collected_by_file,
                             {'tests/test_pytest_function_exec.py': 1})
            self.assertEqual(outcome.uncollected_test_files, [])
            self.assertEqual(marker.read_text(), 'executed\n')

    def test_selected_nonempty_zero_collection_module_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tests = root / 'tests'
            tests.mkdir()
            passing = tests / 'test_has_function.py'
            passing.write_text('def test_passes():\n    assert True\n')
            uncollected = tests / 'test_has_no_tests.py'
            uncollected.write_text('SENTINEL = "nonempty module"\n')
            with patch.object(acceptance, 'ROOT', root):
                outcome = acceptance.run_pytest([passing, uncollected], verbose=False)
            self.assertEqual(outcome.exit_code, 0)
            self.assertEqual(outcome.tests_run, 1)
            self.assertFalse(outcome.was_successful())
            self.assertEqual(outcome.collected_by_file, {
                'tests/test_has_function.py': 1,
                'tests/test_has_no_tests.py': 0,
            })
            self.assertEqual(outcome.uncollected_test_files,
                             ['tests/test_has_no_tests.py'])
            self.assertEqual(outcome.errors, [{
                'test': 'tests/test_has_no_tests.py',
                'traceback': 'Selected nonempty test module collected zero tests',
            }])

    def test_inherited_collect_only_and_deselection_options_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tests = root / 'tests'
            tests.mkdir()
            marker = root / 'executed'
            module = tests / 'test_environment_options.py'
            module.write_text(
                'from pathlib import Path\n\n'
                'def test_must_execute():\n'
                f'    Path({str(marker)!r}).write_text("executed\\n")\n'
            )
            original = '--collect-only -k never_selected'
            with patch.object(acceptance, 'ROOT', root), patch.dict(
                os.environ,
                {'PYTEST_ADDOPTS': original, 'PYTEST_PLUGINS': 'missing_plugin'},
                clear=False,
            ):
                outcome = acceptance.run_pytest([module], verbose=False)
                self.assertEqual(os.environ['PYTEST_ADDOPTS'], original)
                self.assertEqual(os.environ['PYTEST_PLUGINS'], 'missing_plugin')
            self.assertTrue(outcome.was_successful())
            self.assertEqual(outcome.tests_run, 1)
            self.assertEqual(marker.read_text(), 'executed\n')

    def test_collected_without_execution_cannot_succeed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tests = root / 'tests'
            tests.mkdir()
            module = tests / 'test_collect_only.py'
            module.write_text('def test_would_fail():\n    assert False\n')

            # Exercise the outcome invariant directly because run_pytest blocks
            # external plugins and environment/config options by design.
            plugin = acceptance._AcceptancePlugin([module])
            plugin.nodeids = ['tests/test_collect_only.py::test_would_fail']
            plugin.collected_by_path[module.resolve()] = 1
            outcome = plugin.outcome([module], 0)
            self.assertFalse(outcome.was_successful())
            self.assertEqual(outcome.tests_run, 0)
            self.assertIn('no execution result', outcome.errors[0]['traceback'])

    def test_local_pytest_hook_cannot_silently_deselect_a_selected_case(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tests = root / 'tests'
            tests.mkdir()
            (tests / 'conftest.py').write_text(
                'def pytest_collection_modifyitems(items):\n'
                '    kept = [item for item in items if item.name == "test_passes"]\n'
                '    removed = [item for item in items if item.name != "test_passes"]\n'
                '    items[:] = kept\n'
                '    if removed:\n'
                '        removed[0].config.hook.pytest_deselected(items=removed)\n'
            )
            module = tests / 'test_conftest_selection.py'
            module.write_text(
                'def test_passes():\n    assert True\n\n'
                'def test_must_not_disappear():\n    assert False\n'
            )
            with patch.object(acceptance, 'ROOT', root):
                outcome = acceptance.run_pytest([module], verbose=False)
            self.assertFalse(outcome.was_successful())
            self.assertEqual(outcome.tests_run, 1)
            self.assertTrue(any(row['test'] == 'pytest-selection' for row in outcome.errors))

    def test_acceptance_receipt_rejects_selected_zero_collection_module(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tests = root / 'tests'
            tests.mkdir()
            (tests / 'test_fixture_pass.py').write_text(
                'def test_pytest_function():\n    assert True\n'
            )
            (tests / 'test_fixture_empty.py').write_text(
                'SENTINEL = "selected but has no tests"\n'
            )
            package = root / 'src/cbus_toolkit'
            package.mkdir(parents=True)
            (package / 'capabilities.json').write_text(
                '{"census_complete":false,"features":[]}'
            )
            output = root / 'report.json'
            arguments = ['acceptance', '--pattern', 'test_fixture_*.py',
                         '--output', str(output)]
            with patch.object(acceptance, 'ROOT', root), \
                 patch.object(acceptance.resources, 'files', return_value=package), \
                 patch.object(sys, 'path', list(sys.path)), \
                 patch.object(sys, 'argv', arguments), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(acceptance.main(), 1)
            report = json.loads(output.read_text())
            self.assertFalse(report['passed'])
            self.assertFalse(report['test_success'])
            self.assertEqual(report['tests_run'], 1)
            self.assertEqual(report['errors'], 1)
            self.assertEqual(report['pytest_exit_code'], 0)
            self.assertEqual(report['uncollected_test_files'],
                             ['tests/test_fixture_empty.py'])
            self.assertEqual(report['collected_tests_by_file'], {
                'tests/test_fixture_empty.py': 0,
                'tests/test_fixture_pass.py': 1,
            })

    def test_mock_binary_observation_requires_selected_test_and_explicit_executable(self):
        selected = [Path('tests/test_rust_cgate_interop.py')]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            binary = Path(folder) / 'mock'
            binary.write_bytes(b'Explicit synthetic executable fixture\n')
            binary.chmod(0o700)
            self.assertEqual(acceptance.test_binary_inputs(selected), {})
            os.environ['CBUS_CGATE_MOCK_BIN'] = str(binary)
            self.assertEqual(acceptance.test_binary_inputs([]), {})
            observed = acceptance.test_binary_inputs(selected)['CBUS_CGATE_MOCK_BIN']
            self.assertEqual(observed, {'path': str(binary.resolve()), 'size_bytes': binary.stat().st_size,
                                       'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()})
            binary.chmod(0o600)
            self.assertEqual(acceptance.test_binary_inputs(selected)['CBUS_CGATE_MOCK_BIN']['error'], 'ValueError')
            binary.unlink()
            os.mkfifo(binary)
            self.assertEqual(acceptance.test_binary_inputs(selected)['CBUS_CGATE_MOCK_BIN']['error'], 'ValueError')
            binary.unlink()
            self.assertEqual(acceptance.test_binary_inputs(selected)['CBUS_CGATE_MOCK_BIN']['error'], 'FileNotFoundError')

    def test_each_selected_rust_server_binary_is_hash_bound(self):
        selected = [
            Path('tests/test_rust_cgate_interop.py'),
            Path('tests/test_cmqtt_programming_methods_interop.py'),
        ]
        with tempfile.TemporaryDirectory() as folder:
            cgate = Path(folder) / 'cgate-mock'
            cmqttd = Path(folder) / 'cmqttd'
            cgate.write_bytes(b'cgate fixture')
            cmqttd.write_bytes(b'cmqttd fixture')
            cgate.chmod(0o700)
            cmqttd.chmod(0o700)
            with patch.dict(os.environ, {
                'CBUS_CGATE_MOCK_BIN': str(cgate),
                'CBUS_CMQTTD_BIN': str(cmqttd),
            }, clear=True):
                evidence = acceptance.test_binary_inputs(selected)
            self.assertEqual(set(evidence), {
                'CBUS_CGATE_MOCK_BIN', 'CBUS_CMQTTD_BIN'
            })
            self.assertEqual(evidence['CBUS_CGATE_MOCK_BIN']['size_bytes'], 13)
            self.assertEqual(evidence['CBUS_CMQTTD_BIN']['size_bytes'], 14)
            self.assertNotEqual(
                evidence['CBUS_CGATE_MOCK_BIN']['sha256'],
                evidence['CBUS_CMQTTD_BIN']['sha256'],
            )

    def test_unselected_rust_server_binary_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            cmqttd = Path(folder) / 'cmqttd'
            cmqttd.write_bytes(b'cmqttd fixture')
            cmqttd.chmod(0o700)
            with patch.dict(os.environ, {'CBUS_CMQTTD_BIN': str(cmqttd)}, clear=True):
                evidence = acceptance.test_binary_inputs([
                    Path('tests/test_fixture.py')
                ])
            self.assertEqual(evidence, {})

    def test_changed_mock_binary_fails_otherwise_successful_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tests').mkdir()
            (root / 'tests/test_rust_cgate_interop.py').write_text('# Synthetic binary-mutation test.\n')
            package = root / 'src/cbus_toolkit'
            package.mkdir(parents=True)
            (package / 'capabilities.json').write_text('{"census_complete":false,"features":[]}')
            binary = root / 'mock'
            binary.write_bytes(b'before')
            binary.chmod(0o700)
            output = root / 'report.json'
            def mutate_binary(*_args, **_kwargs):
                binary.write_bytes(b'after')
                return self.successful_outcome('tests/test_rust_cgate_interop.py')

            with patch.object(acceptance, 'ROOT', root), \
                 patch.object(acceptance.resources, 'files', return_value=package), \
                 patch.object(acceptance, 'run_pytest', side_effect=mutate_binary), \
                 patch.object(sys, 'path', list(sys.path)), \
                 patch.dict(os.environ, {'CBUS_CGATE_MOCK_BIN': str(binary)}), \
                 patch.object(sys, 'argv', ['acceptance', '--require-no-skips', '--output', str(output)]), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(acceptance.main(), 1)
            report = json.loads(output.read_text())
            self.assertTrue(report['test_success'])
            self.assertFalse(report['passed'])
            self.assertEqual(report['external_test_binary_errors'], ['CBUS_CGATE_MOCK_BIN'])
            self.assertTrue(report['enabled_native_gates']['CBUS_CGATE_MOCK_BIN'])
            self.assertEqual(report['external_test_binaries_before']['CBUS_CGATE_MOCK_BIN']['sha256'],
                             hashlib.sha256(b'before').hexdigest())
            self.assertEqual(report['external_test_binaries_after']['CBUS_CGATE_MOCK_BIN']['sha256'],
                             hashlib.sha256(b'after').hexdigest())

    def test_report_never_infers_parity_from_legacy_category_status(self):
        cases = [(False, 'implemented'), (True, 'pending'),
                 (True, 'in_progress'), (True, 'verified'), (True, 'implemented')]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tests').mkdir()
            (root / 'tests/test_fixture.py').write_text('# Synthetic passing test selection.\n')
            package = root / 'src/cbus_toolkit'
            package.mkdir(parents=True)
            output = root / 'report.json'
            for census, acceptance_status in cases:
                with self.subTest(census=census, acceptance_status=acceptance_status):
                    ledger = {'census_complete': census, 'features': [
                        {'id': 'project-storage', 'status': 'implemented'},
                        {'id': 'toolkit-differential-acceptance', 'status': acceptance_status},
                        {'id': 'unit-hardware-acceptance', 'status': acceptance_status}]}
                    (package / 'capabilities.json').write_text(json.dumps(ledger))
                    with patch.object(acceptance, 'ROOT', root), \
                         patch.object(acceptance.resources, 'files', return_value=package), \
                         patch.object(acceptance, 'run_pytest',
                                      return_value=self.successful_outcome()), \
                         patch.object(sys, 'path', list(sys.path)), \
                         patch.object(sys, 'argv', ['acceptance', '--require-no-skips', '--output', str(output)]), \
                         redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(acceptance.main(), 0)
                    report = json.loads(output.read_text())
                    self.assertIs(report['toolkit_parity_complete'], False)
                    self.assertFalse(report['toolkit_parity_progress']['complete'])
                    self.assertIn(
                        'no parity obligation register',
                        report['toolkit_parity_progress']['blockers'][0],
                    )
                    self.assertTrue(report['passed'])
                    self.assertEqual(report['tests_run'], 1)
                    self.assertEqual(report['pytest_exit_code'], 0)
                    self.assertEqual(report['collected_tests_by_file'],
                                     {'tests/test_fixture.py': 1})
                    self.assertEqual(report['uncollected_test_files'], [])
                    self.assertEqual(report['skipped'], [])
                    self.assertEqual(report['inputs_changed_during_run'], [])


if __name__ == '__main__':
    unittest.main()
