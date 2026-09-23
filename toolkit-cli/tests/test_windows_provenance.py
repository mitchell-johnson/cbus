"""Portable owned provenance, with an independent recording file/job peer."""
from copy import deepcopy
import json
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

from research.windows_provenance import ENVIRONMENT, resolve_windows_provenance


def fixture(directory):
    ready = {'format': 'cbus-windows-bridge-v2', 'pid': 484,
             'job_directory': r'C:\OwnedOracle', 'network_listener': False}
    runtime = {'os_version': 'Owned Windows', 'process_architecture': 'AMD64', 'framework': 533509,
               'compiler': {'path': 'csc.exe', 'sha256': 'a' * 64, 'version': '4.8'},
               'mscorlib': {'path': 'mscorlib.dll', 'sha256': 'b' * 64, 'version': '4.8'}}
    relative = {'NativeWindowsBridgeV2.exe': 'windows-bridge/v2/NativeWindowsBridgeV2.exe',
                'bridge-ready.json': 'windows-bridge/v2/bridge-ready.json',
                'windows-runtime.json': 'edlt-lifecycle/windows-runtime.json'}
    raw = {'NativeWindowsBridgeV2.exe': b'MZ-owned-literal-runner',
           'bridge-ready.json': json.dumps(ready).encode(), 'windows-runtime.json': json.dumps(runtime).encode()}
    paths = {name: directory / value for name, value in relative.items()}
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw[name])
    return paths, raw, ready, runtime


class Peer:
    guest_root = r'C:\OwnedOracle'
    def __init__(self, raw, ready, runtime):
        self.files = {name: raw[name] for name in ('NativeWindowsBridgeV2.exe', 'bridge-ready.json')}
        self.calls = []; self.scripts = []; self.callback = None
        self.observed = {'runner_pid': ready['pid'], 'runner_executable': self.path('NativeWindowsBridgeV2.exe'),
                         'runtime': deepcopy(runtime)}
        self.result = {'job_id': 'job-owned-provenance', 'complete': True, 'exit_code': 0, 'stderr': b''}
    def path(self, name): return str(PureWindowsPath(self.guest_root) / name)
    def pull(self, name, **kwargs):
        self.calls.append(('pull', name)); return self.files.get(name)
    def run(self, script):
        self.calls.append(('run',)); self.scripts.append(script)
        if self.callback: self.callback()
        return {'stdout': json.dumps(self.observed).encode(), **self.result}


class WindowsProvenanceTests(unittest.TestCase):
    def setup_owned(self, folder):
        paths, raw, ready, runtime = fixture(Path(folder) / 'external')
        return paths, raw, ready, runtime, Peer(raw, ready, runtime)

    def test_explicit_external_root_works_without_snapshot_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            paths, raw, ready, runtime, peer = self.setup_owned(folder)
            snapshot = Path(folder) / 'empty-snapshot'; snapshot.mkdir()
            with patch.dict('os.environ', {ENVIRONMENT: str(Path(folder) / 'external')}):
                proof = resolve_windows_provenance(snapshot, peer)
            self.assertEqual(dict(proof.paths), {name: path.resolve() for name, path in paths.items()})
            self.assertEqual(len(peer.scripts), 1)
            self.assertIn('Get-Process -Id 484', peer.scripts[0])
            self.assertNotIn('Owned Windows', peer.scripts[0])
            self.assertTrue(proof.as_dict()['current_generation_verified'])
            self.assertEqual(proof.as_dict()['query']['job_id'], 'job-owned-provenance')
            proof.verify(peer); self.assertEqual(len(peer.scripts), 1)
            evidence = proof.as_dict(); evidence['file_sha256']['bridge-ready.json'] = 'forged'
            self.assertNotEqual(evidence, proof.as_dict()); proof.verify(peer)
            self.assertFalse((snapshot / 'research/runtime').exists())

    def test_fallback_and_explicit_relative_empty_path_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); paths, raw, ready, runtime = fixture(root / 'research/runtime')
            peer = Peer(raw, ready, runtime)
            with patch.dict('os.environ', {}, clear=True):
                proof = resolve_windows_provenance(root, peer)
            self.assertIsNone(proof.as_dict()['environment'])
            for value in ('', 'relative/runtime'):
                with self.subTest(value=value), patch.dict('os.environ', {ENVIRONMENT: value}):
                    before = len(peer.calls)
                    with self.assertRaises(ValueError): resolve_windows_provenance(root, peer)
                    self.assertEqual(len(peer.calls), before)

    def test_missing_empty_and_duplicate_files_fail_before_bridge(self):
        for kind in ('missing', 'empty', 'duplicate'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                paths, raw, ready, runtime, peer = self.setup_owned(folder)
                if kind == 'missing': paths['windows-runtime.json'].unlink()
                elif kind == 'empty': paths['windows-runtime.json'].write_bytes(b'')
                else: paths['bridge-ready.json'].write_bytes(b'{"pid":1,"pid":2}')
                with patch.dict('os.environ', {ENVIRONMENT: str(Path(folder) / 'external')}):
                    with self.assertRaises((ValueError, FileNotFoundError)): resolve_windows_provenance(Path(folder), peer)
                self.assertEqual(peer.calls, [])

    def test_invalid_ready_identity_and_runtime_fields_do_not_query(self):
        for field, value in (('format', 'v1'), ('pid', True), ('pid', 0), ('network_listener', 0),
                             ('job_directory', r'C:\Other')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                paths, raw, ready, runtime, peer = self.setup_owned(folder)
                ready[field] = value; paths['bridge-ready.json'].write_text(json.dumps(ready))
                with patch.dict('os.environ', {ENVIRONMENT: str(Path(folder) / 'external')}):
                    with self.assertRaises(ValueError): resolve_windows_provenance(Path(folder), peer)
                self.assertEqual(peer.calls, [])

    def test_stale_ready_binary_or_stopped_bridge_fails_before_query(self):
        for name in ('bridge-ready.json', 'NativeWindowsBridgeV2.exe', 'bridge-stopped.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                paths, raw, ready, runtime, peer = self.setup_owned(folder)
                peer.files[name] = b'stale or stopped'
                with patch.dict('os.environ', {ENVIRONMENT: str(Path(folder) / 'external')}):
                    with self.assertRaises(RuntimeError): resolve_windows_provenance(Path(folder), peer)
                self.assertEqual(peer.scripts, [])

    def test_actual_runtime_and_runner_must_match(self):
        for kind in ('runtime', 'pid', 'path'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                paths, raw, ready, runtime, peer = self.setup_owned(folder)
                if kind == 'runtime': peer.observed['runtime']['compiler']['sha256'] = 'c' * 64
                elif kind == 'pid': peer.observed['runner_pid'] += 1
                else: peer.observed['runner_executable'] = r'C:\Foreign\runner.exe'
                with patch.dict('os.environ', {ENVIRONMENT: str(Path(folder) / 'external')}):
                    with self.assertRaises(RuntimeError): resolve_windows_provenance(Path(folder), peer)
                self.assertEqual(len(peer.scripts), 1)

    def test_failed_query_not_accepted_or_replayed(self):
        for result in ({'exit_code': 1}, {'exit_code': False}, {'complete': False}, {'stderr': b'failure'},
                       {'stdout': b'{'}, {'stdout': None}):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as folder:
                paths, raw, ready, runtime, peer = self.setup_owned(folder); peer.result.update(result)
                with patch.dict('os.environ', {ENVIRONMENT: str(Path(folder) / 'external')}):
                    with self.assertRaises((ValueError, RuntimeError)): resolve_windows_provenance(Path(folder), peer)
                self.assertEqual(len(peer.scripts), 1)

    def test_generation_change_during_query_and_later_file_change_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            paths, raw, ready, runtime, peer = self.setup_owned(folder)
            peer.callback = lambda: peer.files.update({'bridge-ready.json': b'new-generation'})
            with patch.dict('os.environ', {ENVIRONMENT: str(Path(folder) / 'external')}):
                with self.assertRaises(RuntimeError): resolve_windows_provenance(Path(folder), peer)
                peer.callback = None; peer.files['bridge-ready.json'] = raw['bridge-ready.json']
                proof = resolve_windows_provenance(Path(folder), peer)
            paths['windows-runtime.json'].write_bytes(b'changed')
            with self.assertRaises(RuntimeError): proof.verify(peer)
            self.assertEqual(len(peer.scripts), 2)

    def test_query_interruption_keeps_original_without_followup(self):
        with tempfile.TemporaryDirectory() as folder:
            paths, raw, ready, runtime, peer = self.setup_owned(folder)
            interruption = KeyboardInterrupt('owned query interruption')
            def stop(): raise interruption
            peer.callback = stop
            with patch.dict('os.environ', {ENVIRONMENT: str(Path(folder) / 'external')}):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    resolve_windows_provenance(Path(folder), peer)
            self.assertIs(caught.exception, interruption)
            self.assertEqual(len(peer.scripts), 1)
            self.assertEqual(peer.calls[-1], ('run',))


if __name__ == '__main__': unittest.main()
