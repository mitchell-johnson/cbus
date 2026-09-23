"""Independent adapter guards; never accesses host Docker or the Windows guest."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from research.original_oracle import OriginalOracleError
from research.original_source_oracle import OriginalSourceSetOracle


class SourceSetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name); self.app = self.root / 'app'; self.app.mkdir()
        self.sources = (self.root / 'Main.cs', self.root / 'Helper.cs')
        self.sources[0].write_bytes(b'class Main { static void Main() {} }\r\n')
        self.sources[1].write_bytes(b'// distinct owned bytes\nclass Helper {}\n')
        (self.app / 'CBusLogicModel.dll').write_bytes(b'unit-test placeholder')

    def oracle(self, **options):
        return OriginalSourceSetOracle(self.sources, self.app, entry_point='Main', **options)

    def test_source_order_fingerprint_and_strict_configuration_before_io(self):
        first = self.oracle(); reverse = OriginalSourceSetOracle(tuple(reversed(self.sources)), self.app, entry_point='Main')
        self.assertNotEqual(first.source_sha256, reverse.source_sha256)
        self.assertEqual([row['name'] for row in first.source_hashes], ['Main.cs', 'Helper.cs'])
        with patch('research.original_source_oracle.WindowsBridge', side_effect=AssertionError('no guest')), patch('research.original_oracle.subprocess.run', side_effect=AssertionError('no process')):
            for sources in (str(self.sources[0]), (), self.sources[:1], self.sources * 5, (self.sources[0], self.sources[0]), (self.sources[0], self.root / 'Missing.cs')):
                with self.assertRaises(ValueError): OriginalSourceSetOracle(sources, self.app, entry_point='Main')
            for entry in ('', 'Main;whoami', 'Main Other', '.Main', 'Main..Class', '/main:Main', 'M' * 121, False):
                with self.assertRaises(ValueError): OriginalSourceSetOracle(self.sources, self.app, entry_point=entry)
            for options in ({'backend': 'auto'}, {'references': ('../eDLT.dll',)}, {'references': ('Absent.dll',)}, {'gui': 1}, {'timeout': True}, {'docker_image': 'bad image'}):
                with self.assertRaises(ValueError): self.oracle(**options)
            other = self.root / 'helper.cs'; other.write_bytes(b'class Helper2 {}')
            with self.assertRaises(ValueError): OriginalSourceSetOracle((self.sources[1], other), self.app, entry_point='Main')

    def test_runtime_file_and_argument_validation_precedes_lazy_compile(self):
        with patch('research.original_source_oracle.WindowsBridge', side_effect=AssertionError('no guest')) as bridge, patch('research.original_oracle.subprocess.run', side_effect=AssertionError('no process')) as process:
            for backend in ('windows', 'docker'):
                oracle = self.oracle(backend=backend)
                for args, files in ((['x;whoami'], {}), (['@65'], {}), (['@00'], {}), ([], {'Main.cs': b'x'}), ([], {'Helper.dll': b'x'}), ([], {'../x.tsv': b'x'}), ([], {'a.tsv': 'text'}), ([], {'a.tsv': b'x', 'A.tsv': b'y'})):
                    with self.assertRaises(ValueError): oracle.run(args, files=files)
            bridge.assert_not_called(); process.assert_not_called()

    def test_changed_secondary_source_prevents_any_compilation(self):
        oracle = self.oracle(backend='windows'); self.sources[1].write_text('changed')
        with patch('research.original_source_oracle.WindowsBridge', side_effect=AssertionError('no guest')) as bridge:
            with self.assertRaisesRegex(ValueError, 'source set changed'): oracle.run()
            bridge.assert_not_called()

    def test_docker_keeps_order_exact_bytes_entry_point_gui_and_real_failure(self):
        def process(args, **kwargs):
            if 'mcs' in args:
                directory = Path(args[args.index('-w') - 1].removesuffix(':/work'))
                self.assertEqual((directory / 'Main.cs').read_bytes(), self.sources[0].read_bytes())
                self.assertEqual((directory / 'Helper.cs').read_bytes(), self.sources[1].read_bytes())
                self.assertEqual(args[-4:], ['-main:Main', '-out:OriginalProbe.exe', 'Main.cs', 'Helper.cs'])
                return subprocess.CompletedProcess(args, 0, 'compile output', '')
            self.assertEqual(args[-6:], ['xvfb-run', '-a', 'mono', 'OriginalProbe.exe', 'values.tsv', 'keep'])
            return subprocess.CompletedProcess(args, 17, 'partial original output', 'original failure')
        with patch('research.original_oracle.subprocess.run', side_effect=process) as run, patch('research.original_source_oracle.WindowsBridge', side_effect=AssertionError('no fallback')):
            with self.oracle(backend='docker', gui=True) as oracle:
                result = oracle.run_result(('values.tsv', 'keep'), files={'values.tsv': b'key\tvalue\n'})
                self.assertEqual((result.returncode, result.stdout, result.stderr), (17, 'partial original output', 'original failure'))
                self.assertEqual(result.process_evidence['source_hashes'], list(oracle.source_hashes))
                self.assertEqual(result.process_evidence['entry_point'], 'Main')
                self.assertEqual(run.call_count, 2)
                self.assertTrue(all('sh' not in call.args[0] and 'none' in call.args[0] for call in run.call_args_list))

    def test_compile_failure_never_runs_or_switches_backend(self):
        with patch('research.original_oracle.subprocess.run', return_value=subprocess.CompletedProcess([], 2, 'bad original source', 'compiler failure')) as run, patch('research.original_source_oracle.WindowsBridge', side_effect=AssertionError('no fallback')):
            with self.assertRaises(OriginalOracleError) as caught: self.oracle(backend='docker').run()
            self.assertEqual(caught.exception.stage, 'compile'); self.assertEqual(run.call_count, 1)

    def fake_guest(self, *, compile_exit=0, run_exit=0):
        rows = []
        for name in ['CBusToolkit.exe', 'CBusLogicModel.dll', 'eDLT.dll', *[f'Owned{i}.dll' for i in range(22)]]:
            data = ('fake assembly ' + name).encode(); (self.app / name).write_bytes(data)
            rows.append({'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'file_version': '1.18.0.2754', 'product_version': '1.18.0'})
        manifest = json.dumps(rows).encode()
        class Guest:
            def __init__(self): self.pushed = []; self.scripts = []
            def path(self, name): return 'C:\\Owned\\' + name
            def pull(self, name): return manifest
            def push(self, name, data): self.pushed.append((name, data)); return hashlib.sha256(data).hexdigest()
            def run(self, script):
                self.scripts.append(script); code = compile_exit if 'csc.exe' in script else run_exit
                return {'complete': code == 0, 'exit_code': code, 'stdout': b'compiler\r\n' if 'csc.exe' in script else b'actual output\r\n', 'stderr': b'' if code == 0 else b'original error', 'admitted': True, 'job_id': 'job-owned'}
        return Guest(), hashlib.sha256(manifest).hexdigest()

    def test_windows_compiles_exact_sources_and_exposes_actual_runtime_failure(self):
        guest, digest = self.fake_guest(run_exit=23)
        with patch('research.original_source_oracle.STAGED_MANIFEST_SHA256', digest), patch('research.original_source_oracle.WindowsBridge', return_value=guest), patch('research.original_oracle.subprocess.run', side_effect=AssertionError('Docker forbidden')):
            oracle = self.oracle(backend='windows', references=('eDLT.dll',))
            result = oracle.run_result(('values.tsv',), files={'values.tsv': b'Key\t7\n'})
            self.assertEqual([data for _, data in guest.pushed[:2]], [path.read_bytes() for path in self.sources])
            compile_script = guest.scripts[0]
            self.assertIn('/main:Main', compile_script); self.assertIn('/r:eDLT.dll', compile_script)
            self.assertLess(compile_script.index('-source0.cs'), compile_script.index('-source1.cs'))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (23, 'actual output\r\n', 'original error'))
            self.assertTrue(result.process_evidence['admitted']); self.assertEqual(len(guest.scripts), 2)
            original_hashes = list(oracle.source_hashes)
            result.process_evidence['source_hashes'][0]['sha256'] = 'mutated result'
            exposed = oracle.source_hashes; exposed[1]['sha256'] = 'mutated property'
            next_result = oracle.run_result()
            self.assertEqual(next_result.process_evidence['source_hashes'], original_hashes)
            self.assertEqual(next_result.source_sha256, result.source_sha256)
            with self.assertRaises(OriginalOracleError): oracle.run()
            self.assertEqual(len(guest.scripts), 4)

    def test_manifest_and_reference_mismatch_never_upload_or_compile(self):
        guest, digest = self.fake_guest()
        with patch('research.original_source_oracle.WindowsBridge', return_value=guest):
            with self.assertRaisesRegex(RuntimeError, 'manifest fingerprint'): self.oracle(backend='windows').run()
            self.assertEqual(guest.pushed, []); self.assertEqual(guest.scripts, [])
        (self.app / 'Extra.dll').write_bytes(b'not in staged manifest')
        with patch('research.original_source_oracle.STAGED_MANIFEST_SHA256', digest), patch('research.original_source_oracle.WindowsBridge', return_value=guest):
            with self.assertRaisesRegex(ValueError, 'reference'): self.oracle(backend='windows', references=('Extra.dll',)).run()
            self.assertEqual(guest.pushed, []); self.assertEqual(guest.scripts, [])
            (self.app / 'eDLT.dll').write_bytes(b'modified local original')
            with self.assertRaisesRegex(RuntimeError, 'differs from local'): self.oracle(backend='windows').run()
            self.assertEqual(guest.pushed, []); self.assertEqual(guest.scripts, [])

    def test_windows_compile_failure_stops_before_runtime(self):
        guest, digest = self.fake_guest(compile_exit=2)
        with patch('research.original_source_oracle.STAGED_MANIFEST_SHA256', digest), patch('research.original_source_oracle.WindowsBridge', return_value=guest), patch('research.original_oracle.subprocess.run', side_effect=AssertionError('no fallback')):
            with self.assertRaisesRegex(RuntimeError, 'Windows original-model job failed'): self.oracle(backend='windows').run()
            self.assertEqual(len(guest.scripts), 1)


if __name__ == '__main__': unittest.main()
