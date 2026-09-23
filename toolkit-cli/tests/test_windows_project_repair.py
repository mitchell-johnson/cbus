"""Real Windows file/CLI acceptance with two existing owned Python runtimes."""
import os
import ast
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class WindowsRepairGatewayTests(unittest.TestCase):
    def test_invalid_architecture_precedes_files_and_guest_access(self):
        from research.windows_project_repair_probe import run_native_repair_files
        with patch('research.windows_project_repair_probe.WindowsBridge', side_effect=AssertionError('guest')):
            with self.assertRaisesRegex(ValueError, 'architecture'):
                run_native_repair_files('unused', architecture='arm64')

    def interrupted_gateway(self, first, *, secondary_pull=False, fail_report=False):
        from research.windows_project_repair_probe import run_native_repair_files
        calls = []
        interrupted = [False]
        class Bridge:
            def path(self, value): return 'C:\\owned\\' + value
            def push(self, *args): pass
            def submit(self, script): return 'job-fake'
            def wait(self, job): return {'complete': True, 'exit_code': 0, 'stdout': b'{}', 'stderr': b''}
            def pull(self, *args, **kwargs):
                calls.append(args[0])
                interrupted[0] = True
                if secondary_pull and len(calls) == 2: raise KeyboardInterrupt('second pull')
                raise first
        class Provenance:
            paths = {}
            def as_dict(self): return {}
            def verify(self, bridge): raise AssertionError('No guest I/O after interruption')
        read, write = Path.read_bytes, Path.write_text
        def reading(path):
            if interrupted[0] and not secondary_pull and not fail_report:
                raise SystemExit('secondary live-input read')
            return read(path)
        def writing(path, *args, **kwargs):
            if fail_report and path.name == 'result.json': raise SystemExit('secondary report write')
            return write(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory, \
                patch('research.windows_project_repair_probe.WindowsBridge', Bridge), \
                patch('research.windows_project_repair_probe.resolve_windows_provenance', return_value=Provenance()), \
                patch.object(Path, 'read_bytes', reading), patch.object(Path, 'write_text', writing):
            with self.assertRaises(type(first)) as caught:
                run_native_repair_files(Path(directory) / 'run')
        self.assertIs(caught.exception, first)
        self.assertEqual(len(calls), 2 if secondary_pull else 1)
        self.assertEqual(first.windows_project_repair_gateway_evidence['job_id'], 'job-fake')

    def test_pull_interruption_stops_guest_io_and_survives_final_read_or_write(self):
        for fail_report in (False, True):
            with self.subTest(fail_report=fail_report):
                self.interrupted_gateway(KeyboardInterrupt('first'), fail_report=fail_report)

    def test_first_ordinary_error_survives_later_interrupted_diagnostic(self):
        self.interrupted_gateway(OSError('first'), secondary_pull=True)

    def test_native_harness_cleanup_cannot_replace_runner_interruption(self):
        source = Path(__file__).resolve().parents[1] / 'research/windows_project_repair_cases.py'
        tree = ast.parse(source.read_text())
        start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.FunctionDef) and node.name == 'safe_error')
        first = KeyboardInterrupt('original runner interruption')
        class Unprintable(SystemExit):
            def __str__(self): raise SystemExit('secondary formatting failure')
        class Runner:
            def run(self, suite): raise first
        def cleanup(path): raise Unprintable()
        import hashlib
        namespace = {'unittest': SimpleNamespace(TextTestRunner=lambda **kwargs: Runner(),
                        defaultTestLoader=SimpleNamespace(loadTestsFromTestCase=lambda case: None)),
                     'sys': SimpleNamespace(stderr=io.StringIO(), modules={}),
                     'shutil': SimpleNamespace(rmtree=cleanup), 'root': SimpleNamespace(exists=lambda: True),
                     'NativeRepairFiles': object, 'inputs': {}, 'records': [{'observed': 'partial'}],
                     'denied': [], 'architecture': {}, 'runtime_files': {}, 'hashlib': hashlib, 'json': json,
                     'archive': SimpleNamespace(read_bytes=lambda: b'')}
        with redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt) as caught:
            exec(compile(ast.Module(tree.body[start:], []), str(source), 'exec'), namespace)
        self.assertIs(caught.exception, first)
        evidence = first.windows_project_repair_native_evidence
        self.assertEqual(evidence['evidence'], [{'observed': 'partial'}])
        self.assertEqual(evidence['cleanup_error']['type'], 'Unprintable')
        self.assertEqual(evidence['cleanup_error']['message'], '<exception message unavailable>')


@unittest.skipUnless(os.environ.get('CBUS_WINDOWS_PROVENANCE_ROOT'),
                     'Set the owned Windows provenance root for native repair-file acceptance')
class NativeWindowsProjectRepairTests(unittest.TestCase):
    def check_architecture(self, architecture, bits):
        from research.windows_project_repair_probe import run_native_repair_files
        root = Path(__file__).resolve().parents[1] / 'research/runtime'
        root.mkdir(parents=True, exist_ok=True)
        parent = Path(tempfile.mkdtemp(prefix='windows-project-repair-' + architecture + '-', dir=root))
        result = run_native_repair_files(parent / 'run', architecture=architecture)
        self.assertTrue(result['passed'], str(parent))
        native = result['native']
        self.assertEqual((native['tests_run'], native['failures'], native['errors'], native['skipped']), (16, 0, 0, 0))
        self.assertEqual(native['architecture']['pointer_bits'], bits)
        self.assertEqual(native['architecture']['python_pe_machine'], 0x14c if bits == 32 else 0x8664)
        self.assertEqual(native['architecture']['binary_machine_differs_from_native'],
                         native['architecture']['python_pe_machine'] != native['architecture']['native_machine'])
        self.assertEqual(native['runtime_files'], json.loads(
            (root.parent / ('fixtures/windows-python-runtime' + ('-amd64' if bits == 64 else '') + '.json')).read_bytes())['files'])
        self.assertTrue(native['cleanup']['removed'])
        self.assertIsNone(native['cleanup']['error'])
        self.assertFalse(native['network_or_registry_access_attempted'])
        self.assertEqual(native['denied_external_access'], [])
        self.assertIn('cbus_toolkit.cli', native['loaded_sources'])
        self.assertIn('cbus_toolkit.project_repair_cli', native['loaded_sources'])
        self.assertEqual(result['wait_evidence']['job_resubmitted'], False)
        return result

    def test_x86_actual_files_faults_and_full_cli(self):
        self.check_architecture('x86', 32)

    def test_amd64_actual_files_faults_and_full_cli(self):
        self.check_architecture('amd64', 64)


if __name__ == '__main__':
    unittest.main()
