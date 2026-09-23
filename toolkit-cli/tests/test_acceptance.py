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
            suite = unittest.TestSuite([unittest.FunctionTestCase(lambda: binary.write_bytes(b'after'))])
            with patch.object(acceptance, 'ROOT', root), \
                 patch.object(acceptance.resources, 'files', return_value=package), \
                 patch.object(unittest.defaultTestLoader, 'discover', return_value=suite), \
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

    def test_report_uses_census_and_implemented_status_including_acceptance_ids(self):
        cases = [(False, 'implemented', False), (True, 'pending', False),
                 (True, 'in_progress', False), (True, 'verified', False), (True, 'implemented', True)]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tests').mkdir()
            (root / 'tests/test_fixture.py').write_text('# Synthetic passing test selection.\n')
            package = root / 'src/cbus_toolkit'
            package.mkdir(parents=True)
            output = root / 'report.json'
            for census, acceptance_status, expected in cases:
                with self.subTest(census=census, acceptance_status=acceptance_status):
                    ledger = {'census_complete': census, 'features': [
                        {'id': 'project-storage', 'status': 'implemented'},
                        {'id': 'toolkit-differential-acceptance', 'status': acceptance_status},
                        {'id': 'unit-hardware-acceptance', 'status': acceptance_status}]}
                    (package / 'capabilities.json').write_text(json.dumps(ledger))
                    suite = unittest.TestSuite([unittest.FunctionTestCase(lambda: None)])
                    with patch.object(acceptance, 'ROOT', root), \
                         patch.object(acceptance.resources, 'files', return_value=package), \
                         patch.object(unittest.defaultTestLoader, 'discover', return_value=suite), \
                         patch.object(sys, 'path', list(sys.path)), \
                         patch.object(sys, 'argv', ['acceptance', '--require-no-skips', '--output', str(output)]), \
                         redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(acceptance.main(), 0)
                    report = json.loads(output.read_text())
                    self.assertIs(report['toolkit_parity_complete'], expected)
                    self.assertTrue(report['passed'])
                    self.assertEqual(report['tests_run'], 1)
                    self.assertEqual(report['skipped'], [])
                    self.assertEqual(report['inputs_changed_during_run'], [])


if __name__ == '__main__':
    unittest.main()
