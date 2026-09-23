"""Actual Windows file boundary acceptance; no business-code replacements."""
import ctypes
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

archive = Path(sys.argv[1]).resolve()
namespace = sys.argv[2]
assert re.fullmatch(r'repair-files-[a-f0-9]{16}', namespace)
assert archive.parent == Path(__file__).resolve().parent
sys.path.insert(0, str(archive))
with zipfile.ZipFile(archive) as z:
    runtime = json.loads(z.read('runtime.json'))
    inputs = {name: hashlib.sha256(z.read(name)).hexdigest() for name in z.namelist()}
assert os.name == 'nt'
assert list(sys.version_info[:3]) == runtime['version']
assert struct.calcsize('P') * 8 == runtime['bits']
runtime_files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in Path(sys.executable).parent.iterdir() if p.is_file()}
assert runtime_files == runtime['files'], 'Owned Windows runtime differs from manifest'
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype = ctypes.c_void_p
kernel.IsWow64Process2.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ushort)]
kernel.IsWow64Process2.restype = ctypes.c_int
process_machine, native_machine = ctypes.c_ushort(), ctypes.c_ushort()
assert kernel.IsWow64Process2(kernel.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native_machine))
python_image = Path(sys.executable).read_bytes()
pe_offset = struct.unpack_from('<I', python_image, 0x3c)[0]
assert python_image[:2] == b'MZ' and python_image[pe_offset:pe_offset + 4] == b'PE\0\0'
pe_machine = struct.unpack_from('<H', python_image, pe_offset + 4)[0]
assert pe_machine == (0x14c if runtime['bits'] == 32 else 0x8664)
architecture = {'python': sys.version, 'pointer_bits': struct.calcsize('P') * 8,
                'process_machine': process_machine.value, 'native_machine': native_machine.value,
                'python_pe_machine': pe_machine,
                'platform_machine': platform.machine(), 'windows_version': str(sys.getwindowsversion()),
                'processor_architecture': os.environ.get('PROCESSOR_ARCHITECTURE'),
                'stdout_encoding': sys.stdout.encoding, 'stderr_encoding': sys.stderr.encoding,
                'binary_machine_differs_from_native': pe_machine != native_machine.value,
                'interpretation': 'Raw IsWow64Process2 process value zero does not establish matching PE/native architectures'}

# Audit denial is a fixture guard, not a replacement of package behavior.
denied = []
def audit(event, args):
    if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo') or event.startswith('winreg.'):
        denied.append(event)
        raise AssertionError('Unexpected network/registry access: ' + event)
sys.addaudithook(audit)

from cbus_toolkit.project_repair_cli import ProjectRepairFileError, ProjectRepairFileOperation, error_payload
from cbus_toolkit.cli import main

root = archive.parent / namespace
root.mkdir()  # new owned directory; never adopt an existing tree
records = []
original = ('<Project>\r\n<TagName>Māori 💡 A&#13;B</TagName><Application>'
            '<Group><Address>1</Address><TagName>First</TagName></Group>'
            '<Group><Address>1</Address><TagName>Second</TagName></Group>'
            '</Application></Project>\r\n').encode('utf-8')

class NativeRepairFiles(unittest.TestCase):
    def setUp(self):
        self.folder = root / ('%02d-' % len(records) + self._testMethodName)
        self.folder.mkdir()
        self.source = self.folder / 'Māori 💡 = source.xml'
        self.target = self.folder / '修復 = output.xml'
        self.source.write_bytes(original)
        self.record = {'test': self._testMethodName}
        records.append(self.record)

    def tearDown(self):
        self.record['files'] = {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                                for p in self.folder.iterdir() if p.is_file()}

    def test_new_unicode_file_and_binary_flags(self):
        opened, written, synced, closed = [], [], [], []
        real_open, real_write, real_sync, real_close = os.open, os.write, os.fsync, os.close
        def opening(path, flags, *args):
            opened.append(flags)
            return real_open(path, flags, *args)
        def writing(fd, data):
            written.append(len(data)); return real_write(fd, data)
        def syncing(fd):
            synced.append(fd); return real_sync(fd)
        def closing(fd):
            closed.append(fd); return real_close(fd)
        with patch('cbus_toolkit.project_repair_cli.os.open', side_effect=opening), \
                patch('cbus_toolkit.project_repair_cli.os.write', side_effect=writing), \
                patch('cbus_toolkit.project_repair_cli.os.fsync', side_effect=syncing), \
                patch('cbus_toolkit.project_repair_cli.os.close', side_effect=closing):
            result = ProjectRepairFileOperation().run(self.source, output=self.target)
        data = self.target.read_bytes()
        self.assertTrue(result['complete'] and result['output_fsync_succeeded'] and result['output_closed'])
        self.assertEqual(result['source_bytes'], len(original))
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(result['repair']['output_sha256'], hashlib.sha256(data).hexdigest())
        self.assertIn('Māori 💡'.encode(), data)
        self.assertIn(b'First', data)
        self.assertNotIn(b'Second', data)
        self.assertNotIn(b'\r\n', data)
        self.assertTrue(all(flags & os.O_BINARY for flags in opened))
        self.assertTrue(opened[1] & os.O_EXCL)
        self.assertEqual((len(opened), len(synced), len(closed)), (2, 1, 2))
        self.record.update(evidence=result, open_flags=opened, writes=written)

    def test_crlf_is_binary_without_double_carriage_return(self):
        result = ProjectRepairFileOperation().run(self.source, output=self.target, line_ending='crlf')
        data = self.target.read_bytes()
        self.assertTrue(data.endswith(b'\r\n'))
        self.assertNotIn(b'\r\r\n', data)
        self.assertEqual(data.count(b'\r\n'), data.count(b'\n'))
        self.assertEqual(result['output_bytes_confirmed'], len(data))
        self.record['evidence'] = result

    def test_preview_never_creates_or_writes_output(self):
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=AssertionError('write')), \
                patch('cbus_toolkit.project_repair_cli.os.fsync', side_effect=AssertionError('fsync')):
            result = ProjectRepairFileOperation().run(self.source, output=self.target, dry_run=True)
        self.assertTrue(result['complete'])
        self.assertFalse(result['output_create_attempted'])
        self.assertEqual(list(self.folder.iterdir()), [self.source])
        self.record['evidence'] = result

    def test_existing_destination_and_same_source_are_preserved(self):
        self.target.write_bytes(b'keep existing\r\n\x1a')
        evidence = []
        for target in (self.target, self.source):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=target)
            self.assertIsInstance(caught.exception.original_error, FileExistsError)
            self.assertFalse(caught.exception.details['output_created'])
            evidence.append(caught.exception.details)
        self.assertEqual(self.target.read_bytes(), b'keep existing\r\n\x1a')
        self.assertEqual(self.source.read_bytes(), original)
        self.record['evidence'] = evidence

    def test_directory_and_missing_source_reject_before_open(self):
        for source in (self.folder, self.folder / 'missing.xml'):
            with patch('cbus_toolkit.project_repair_cli.os.open', side_effect=AssertionError('open')):
                with self.assertRaises(ProjectRepairFileError) as caught:
                    ProjectRepairFileOperation().run(source, output=self.target)
            self.assertIsInstance(caught.exception.original_error, (ValueError, FileNotFoundError))
            self.assertFalse(caught.exception.details['output_create_attempted'])
        self.assertFalse(self.target.exists())

    def test_source_size_and_growth_bounds(self):
        evidence = []
        with patch('cbus_toolkit.project_repair_cli.os.read', side_effect=AssertionError('read')):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target, max_bytes=16)
        self.assertTrue(caught.exception.details['source_closed'])
        evidence.append(caught.exception.details)
        mode = self.source.stat().st_mode
        with patch('cbus_toolkit.project_repair_cli.os.fstat', return_value=SimpleNamespace(st_mode=mode, st_size=0)):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target, max_bytes=32)
        self.assertEqual(caught.exception.details['source_bytes'], 33)
        self.assertTrue(caught.exception.details['source_closed'])
        evidence.append(caught.exception.details)
        self.assertFalse(self.target.exists())
        self.record['evidence'] = evidence

    def test_invalid_options_precede_path_access(self):
        for settings in ({}, {'dry_run': 1}, {'dry_run': True, 'max_bytes': True},
                         {'dry_run': True, 'max_bytes': 0}, {'dry_run': True, 'line_ending': 'cr'}):
            with patch('cbus_toolkit.project_repair_cli.os.lstat', side_effect=AssertionError('stat')):
                with self.assertRaises(ProjectRepairFileError) as caught:
                    ProjectRepairFileOperation().run(self.source, **settings)
            self.assertEqual(caught.exception.details['stage'], 'validate')
            self.assertIsInstance(caught.exception.original_error, ValueError)

    def test_malformed_xml_fails_before_output(self):
        evidence = []
        for data, limit, stage in ((b'x', 1, 'manual'), (b'<Project>', 1024, 'repair'), (b'<OID/>', 1024, 'tidy')):
            self.source.write_bytes(data)
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target, max_bytes=limit)
            self.assertEqual(caught.exception.details['repair_failure_stage'], stage)
            self.assertFalse(caught.exception.details['output_create_attempted'])
            self.assertEqual(self.source.read_bytes(), data)
            evidence.append(caught.exception.details)
        self.assertFalse(self.target.exists())
        self.record['evidence'] = evidence

    def test_returned_partial_count_followed_by_error(self):
        real_write = os.write
        calls = []
        first = OSError('second write failed')
        def partial(fd, data):
            calls.append(len(data))
            if len(calls) == 1: return real_write(fd, data[:7])
            raise first
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=partial), \
                patch('cbus_toolkit.project_repair_cli.os.fsync', side_effect=AssertionError('fsync')):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target)
        self.assertIs(caught.exception.original_error, first)
        self.assertEqual((len(calls), self.target.stat().st_size, caught.exception.details['output_bytes_confirmed']), (2, 7, 7))
        self.record['evidence'] = caught.exception.details

    def test_unknown_partial_write_preserves_first_error(self):
        real_write = os.write
        first = OSError('write failed after bytes reached file')
        def partial(fd, data):
            real_write(fd, data[:9]); raise first
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=partial) as writes, \
                patch('cbus_toolkit.project_repair_cli.os.fsync', side_effect=AssertionError('fsync')):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target)
        self.assertIs(caught.exception.original_error, first)
        self.assertIs(caught.exception.__cause__, first)
        self.assertEqual((writes.call_count, self.target.stat().st_size, caught.exception.details['output_bytes_confirmed']), (1, 9, 0))
        self.assertTrue(caught.exception.details['output_closed'])
        self.record['evidence'] = caught.exception.details

    def test_zero_write_stops_after_one_call(self):
        with patch('cbus_toolkit.project_repair_cli.os.write', return_value=0) as writes:
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target)
        self.assertEqual((writes.call_count, self.target.stat().st_size), (1, 0))
        self.assertTrue(caught.exception.details['output_closed'])
        self.record['evidence'] = caught.exception.details

    def test_fsync_failure_keeps_complete_bytes_without_claiming_durability(self):
        first = OSError('fsync failure')
        with patch('cbus_toolkit.project_repair_cli.os.fsync', side_effect=first) as sync:
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target)
        self.assertIs(caught.exception.original_error, first)
        self.assertEqual(sync.call_count, 1)
        self.assertTrue(caught.exception.details['output_write_complete'] and caught.exception.details['output_closed'])
        self.assertFalse(caught.exception.details['output_fsync_succeeded'])
        self.assertEqual(caught.exception.details['output_bytes_confirmed'], self.target.stat().st_size)
        self.record['evidence'] = caught.exception.details

    def test_source_and_output_close_errors_are_never_retried(self):
        real_close = os.close
        evidence = []
        for fail_at in (1, 2):
            calls = []
            first = OSError('close uncertain')
            target = self.folder / ('close-%d.xml' % fail_at)
            def closing(fd):
                calls.append(fd); real_close(fd)
                if len(calls) == fail_at: raise first
            with patch('cbus_toolkit.project_repair_cli.os.close', side_effect=closing):
                with self.assertRaises(ProjectRepairFileError) as caught:
                    ProjectRepairFileOperation().run(self.source, output=target)
            self.assertIs(caught.exception.original_error, first)
            self.assertEqual(len(calls), fail_at)
            self.assertEqual(target.exists(), fail_at == 2)
            evidence.append(caught.exception.details)
        self.record['evidence'] = evidence

    def test_primary_interruptions_survive_cleanup_and_failed_attachment(self):
        evidence = []
        for parent in (KeyboardInterrupt, SystemExit):
            class First(parent):
                def __str__(self): raise SystemExit('secondary rendering')
                def __setattr__(self, name, value): raise SystemExit('secondary attachment')
            first = First()
            real_write, real_close = os.write, os.close
            calls = []
            target = self.folder / (parent.__name__ + '.xml')
            def partial(fd, data): real_write(fd, data[:5]); raise first
            def closing(fd):
                calls.append(fd); real_close(fd)
                if len(calls) == 2: raise KeyboardInterrupt('secondary close')
            operation = ProjectRepairFileOperation()
            with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=partial) as writes, \
                    patch('cbus_toolkit.project_repair_cli.os.close', side_effect=closing):
                with self.assertRaises(parent) as caught:
                    operation.run(self.source, output=target)
            self.assertIs(caught.exception, first)
            self.assertIs(operation.last_error, first)
            self.assertEqual((writes.call_count, target.stat().st_size, len(calls)), (1, 5, 2))
            self.assertEqual(operation.last_evidence['cleanup_errors'][0]['type'], 'KeyboardInterrupt')
            evidence.append(operation.last_evidence)
        self.record['evidence'] = evidence

    def test_full_cli_separate_process_unicode_preview_output_and_rejections(self):
        code = ('import sys;sys.path.insert(0,sys.argv.pop(1));'
                'exec("def guard(event,args):\\n if event.startswith(\\"socket.\\") or event.startswith(\\"winreg.\\"): raise AssertionError(event)");'
                'sys.addaudithook(guard);from cbus_toolkit.cli import main;sys.exit(main(sys.argv[1:]))')
        results = []
        encoding = subprocess.run([sys.executable, '-I', '-S', '-c',
                                   'import sys,json;print(json.dumps({"stdout":sys.stdout.encoding,"stderr":sys.stderr.encoding,"utf8_mode":sys.flags.utf8_mode}))'],
                                  capture_output=True, timeout=30)
        self.assertEqual(encoding.returncode, 0)
        self.record['child_encoding'] = json.loads(encoding.stdout)
        self.record['children'] = results  # preserve all observed stages on assertion failure
        for suffix, expected in ((['--dry-run'], 0), (['--output', str(self.target)], 0),
                                 (['--output', str(self.target)], 1), (['--dry-run', '--max-bytes', '16'], 1)):
            child = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(archive), 'project', 'repair', str(self.source), *suffix],
                                   capture_output=True, timeout=30)
            payload = json.loads((child.stdout or child.stderr).decode('utf-8'))
            results.append({'exit_code': child.returncode, 'expected_exit_code': expected, 'arguments': suffix,
                            'stdout': child.stdout.decode('utf-8'), 'stderr': child.stderr.decode('utf-8'),
                            'output_exists_after': self.target.exists(),
                            'output_sha256_after': hashlib.sha256(self.target.read_bytes()).hexdigest() if self.target.exists() else None})
        self.assertEqual(self.source.read_bytes(), original)
        malformed = self.folder / 'malformed.xml'
        malformed.write_bytes(b'<Project>')
        child = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(archive), 'project', 'repair', str(malformed), '--dry-run'],
                               capture_output=True, timeout=30)
        self.assertEqual(child.returncode, 1, repr((child.stdout, child.stderr)))
        payload = json.loads((child.stdout or child.stderr).decode('utf-8'))
        self.assertEqual(payload['repair_failure_stage'], 'repair')
        self.assertEqual(malformed.read_bytes(), b'<Project>')
        results.append({'exit_code': child.returncode, 'stdout': child.stdout.decode('utf-8'), 'stderr': child.stderr.decode('utf-8')})
        for row in results[:4]:
            self.assertEqual(row['exit_code'], row['expected_exit_code'], row)
            payload = json.loads(row['stdout'] or row['stderr'])
            self.assertEqual(payload['complete'], row['expected_exit_code'] == 0)
            self.assertEqual(payload['source'], str(self.source))
        saved = json.loads(results[1]['stdout'])
        self.assertEqual(saved['output'], str(self.target))
        self.assertTrue(saved['output_created'] and saved['output_write_complete'] and saved['output_fsync_succeeded'] and saved['output_closed'])
        self.assertEqual(saved['repair']['output_sha256'], results[1]['output_sha256_after'])
        self.assertEqual(results[1]['output_sha256_after'], results[2]['output_sha256_after'])
        self.assertFalse(results[0]['output_exists_after'])

    def test_full_cli_cancellation_keeps_partial_output_and_original_object(self):
        first = KeyboardInterrupt('primary cancellation')
        real_write = os.write
        def partial(fd, data): real_write(fd, data[:11]); raise first
        out, err = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=partial) as writes, \
                patch('cbus_toolkit.project_repair_cli.error_payload', wraps=error_payload) as exported, \
                redirect_stdout(out), redirect_stderr(err):
            status = main(['project', 'repair', str(self.source), '--output', str(self.target)])
        self.assertEqual(status, 130)
        self.assertIs(exported.call_args.args[0], first)
        payload = json.loads(out.getvalue() or err.getvalue())
        evidence = payload['project_repair_evidence']
        self.assertEqual((writes.call_count, self.target.stat().st_size, evidence['output_bytes_confirmed']), (1, 11, 0))
        self.assertTrue(evidence['output_may_be_partial'] and evidence['output_closed'])
        self.record['evidence'] = payload

def safe_error(error):
    try: message = str(error)
    except BaseException: message = '<exception message unavailable>'
    return {'type': type(error).__name__, 'message': message[:4096]}

result = None
cleanup_error = None
primary = None
try:
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeRepairFiles))
except BaseException as error:
    primary = error
finally:
    try: shutil.rmtree(root)
    except BaseException as error:
        cleanup_error = safe_error(error)
        if primary is None: primary = error
try:
    loaded = {}
    for name, module in list(sys.modules.items()):
        if name == 'cbus_toolkit' or name.startswith('cbus_toolkit.'):
            path = getattr(module, '__file__', None)
            assert path and str(archive) in path, (name, path)
            member = path[len(str(archive)) + 1:].replace('\\', '/')
            assert member in inputs, member
            loaded[name] = {'archive_member': member, 'sha256': inputs[member]}
    report = {'passed': bool(primary is None and result and result.wasSuccessful() and cleanup_error is None and not root.exists() and not denied),
              'tests_run': result.testsRun if result else 0, 'failures': len(result.failures) if result else None,
              'errors': len(result.errors) if result else None, 'skipped': len(result.skipped) if result else None,
              'architecture': architecture, 'runtime_files': runtime_files, 'loaded_sources': loaded,
              'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'evidence': records,
              'cleanup': {'scratch_path': str(root), 'removed': not root.exists(), 'error': cleanup_error},
              'denied_external_access': denied, 'network_or_registry_access_attempted': bool(denied),
              'scope': {'unix_fifo': 'not applicable on Windows', 'symlink_creation': 'not exercised; no privilege changes',
                        'faults': 'injected at actual Windows file descriptors; no power-loss durability claim',
                        'native_cgate_or_physical_io': False}}
    print(json.dumps(report, ensure_ascii=True))
except BaseException as error:
    if primary is None: primary = error
if primary is not None:
    try:
        primary.windows_project_repair_native_evidence = {'evidence': records, 'cleanup_error': cleanup_error,
                                                         'scratch_path': str(root), 'complete': False}
    except BaseException: pass
    raise primary
raise SystemExit(0 if report['passed'] else 1)
