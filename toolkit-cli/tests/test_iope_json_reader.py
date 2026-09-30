"""Bounded offline IOPE file admission; no native service or connection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cbus_toolkit import iope_workflow_cli as cli


class ObservedStream:
    def __init__(self, raw, reads, allow_read=True):
        self.raw, self.reads, self.allow_read = raw, reads, allow_read
    def __enter__(self): return self
    def __exit__(self, *_args): self.raw.close()
    def fileno(self): return self.raw.fileno()
    def read(self, count):
        if not self.allow_read:
            raise AssertionError('Rejected descriptor must never be read')
        self.reads.append(count)
        return self.raw.read(count)


class IopeJsonReaderTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='iope-json-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'input.json'
        self.source.write_bytes(b'{"value":1}')
        self.real_open, self.real_fdopen, self.real_fstat = os.open, os.fdopen, os.fstat

    def assert_closed(self, descriptor):
        with self.assertRaises(OSError): self.real_fstat(descriptor)

    def test_ordinary_path_string_and_regular_symlink(self):
        self.assertEqual(cli.read_json(self.source), {'value': 1})
        self.assertEqual(cli.read_json(str(self.source)), {'value': 1})
        linked = self.root / 'linked.json'; linked.symlink_to(self.source)
        self.assertEqual(cli.read_json(linked), {'value': 1})
        self.assertEqual(self.source.read_bytes(), b'{"value":1}')

    def test_special_types_refused_before_open(self):
        for mode in (stat.S_IFDIR, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK):
            with self.subTest(mode=mode), patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=mode, st_size=0)), \
                    patch.object(cli.os, 'open') as opening, patch.object(Path, 'open', side_effect=AssertionError('No legacy open')):
                with self.assertRaisesRegex(ValueError, 'regular files'): cli.read_json(self.source)
                opening.assert_not_called()
        with patch.object(cli.os, 'open') as opening:
            with self.assertRaisesRegex(ValueError, 'regular files'): cli.read_json(self.root)
            opening.assert_not_called()

    def test_initial_size_limit_refuses_before_open(self):
        with patch.object(cli, 'LIMIT', 4), patch.object(cli.os, 'open') as opening:
            with self.assertRaisesRegex(ValueError, 'at most'): cli.read_json(self.source)
            opening.assert_not_called()

    def test_opened_descriptor_type_rechecked_before_read_and_closed(self):
        for mode in (stat.S_IFDIR, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK):
            descriptors, reads = [], []
            def opening(path, flags):
                descriptor = self.real_open(path, flags); descriptors.append(descriptor); return descriptor
            def stream(descriptor, mode): return ObservedStream(self.real_fdopen(descriptor, mode), reads, False)
            with self.subTest(mode=mode), patch.object(cli.os, 'open', side_effect=opening), \
                    patch.object(cli.os, 'fstat', return_value=SimpleNamespace(st_mode=mode, st_size=0)), \
                    patch.object(cli.os, 'fdopen', side_effect=stream):
                with self.assertRaisesRegex(ValueError, 'regular files'): cli.read_json(self.source)
            self.assertEqual(reads, []); self.assertEqual(len(descriptors), 1); self.assert_closed(descriptors[0])

    def test_opened_descriptor_size_rechecked_before_read_and_closed(self):
        descriptors, reads = [], []
        def opening(path, flags):
            descriptor = self.real_open(path, flags); descriptors.append(descriptor); return descriptor
        def stream(descriptor, mode): return ObservedStream(self.real_fdopen(descriptor, mode), reads, False)
        with patch.object(cli, 'LIMIT', 4), patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=stat.S_IFREG, st_size=1)), \
                patch.object(cli.os, 'open', side_effect=opening), patch.object(cli.os, 'fdopen', side_effect=stream):
            with self.assertRaisesRegex(ValueError, 'at most'): cli.read_json(self.source)
        self.assertEqual(reads, []); self.assert_closed(descriptors[0])

    def test_actual_bytes_bounded_despite_stale_size_metadata(self):
        self.source.write_bytes(b'{"value":1}' + b' ' * 32)
        reads, descriptors = [], []
        def opening(path, flags):
            descriptor = self.real_open(path, flags); descriptors.append(descriptor); return descriptor
        def stream(descriptor, mode): return ObservedStream(self.real_fdopen(descriptor, mode), reads)
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_size=1)
        with patch.object(cli, 'LIMIT', 16), patch.object(Path, 'stat', return_value=info), \
                patch.object(cli.os, 'fstat', return_value=info), patch.object(cli.os, 'open', side_effect=opening), \
                patch.object(cli.os, 'fdopen', side_effect=stream), patch.object(cli.json, 'loads') as parsing:
            with self.assertRaisesRegex(ValueError, 'at most'): cli.read_json(self.source)
            parsing.assert_not_called()
        self.assertEqual(reads, [17]); self.assert_closed(descriptors[0])

    def test_exact_byte_limit_and_empty_input(self):
        self.source.write_bytes(b'{"value":1}' + b' ' * 5)
        with patch.object(cli, 'LIMIT', 16): self.assertEqual(cli.read_json(self.source), {'value': 1})
        self.source.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'nonempty'): cli.read_json(self.source)

    def test_json_rejections_keep_descriptor_closed(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'{broken', b'\xff'):
            self.source.write_bytes(raw); descriptors = []
            def opening(path, flags):
                descriptor = self.real_open(path, flags); descriptors.append(descriptor); return descriptor
            with self.subTest(raw=raw), patch.object(cli.os, 'open', side_effect=opening):
                with self.assertRaises(ValueError): cli.read_json(self.source)
            self.assert_closed(descriptors[0])

    @unittest.skipUnless(hasattr(os, 'mkfifo') and hasattr(os, 'O_NONBLOCK'), 'FIFO substitution requires POSIX')
    def test_regular_path_or_symlink_substituted_with_fifo_at_open(self):
        fifo = self.root / 'pipe.json'; os.mkfifo(fifo)
        for linked in (False, True):
            path = self.root / ('alias.json' if linked else 'regular.json')
            if linked: path.symlink_to(self.source)
            else: path.write_bytes(b'{"value":1}')
            descriptors, reads = [], []
            def opening(selected, flags):
                # Assert before touching the real FIFO, so a missing flag fails
                # immediately rather than creating a blocking regression probe.
                self.assertTrue(flags & os.O_NONBLOCK)
                Path(selected).unlink(); Path(selected).symlink_to(fifo)
                descriptor = self.real_open(selected, flags); descriptors.append(descriptor); return descriptor
            def stream(descriptor, mode): return ObservedStream(self.real_fdopen(descriptor, mode), reads, False)
            with self.subTest(linked=linked), patch.object(cli.os, 'open', side_effect=opening), \
                    patch.object(cli.os, 'fdopen', side_effect=stream):
                with self.assertRaisesRegex(ValueError, 'regular files'): cli.read_json(path)
            self.assertEqual(reads, []); self.assert_closed(descriptors[0])

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO CLI tests require POSIX')
    def test_all_fifo_input_roles_fail_in_bounded_subprocess_before_client(self):
        fifo = self.root / 'pipe.json'; os.mkfifo(fifo)
        alias = self.root / 'pipe-link.json'; alias.symlink_to(fifo)
        snapshot = self.root / 'snapshot.json'
        snapshot.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'IOPE2R2',
                                       'firmware': '1.2.00', 'catalog_number': '5752PP/2R', 'parameters': {}}))
        script = '''import json,sys
from cbus_toolkit import iope_workflow_cli as c
c._editor=lambda args,identity:(None,object())
def client(*args,**kwargs): raise AssertionError('C-Gate client must not be constructed')
try: c.run(c.parser().parse_args(sys.argv[1:]),client_factory=client)
except (ValueError,OSError) as e: print(json.dumps({'error':str(e),'client_constructed':False}))
else: raise AssertionError('FIFO input must be refused')
'''
        for path in (fifo, alias):
            cases = (["output", "show", path], ["output", "plan", snapshot, "--edits", path],
                     ["output", "database", "--host", "127.0.0.1", "--port", "1", "--source", "/db//SYNTH/254/p/20",
                      "--lock-address", "//SYNTH/254", "--plan", path, "--exclusive-project"])
            for arguments in cases:
                with self.subTest(path=path.name, action=arguments[1]):
                    result = subprocess.run([sys.executable, '-B', '-c', script, *map(str, arguments)],
                                            capture_output=True, text=True, timeout=3, check=False)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    receipt = json.loads(result.stdout)
                    self.assertIn('regular files', receipt['error']); self.assertFalse(receipt['client_constructed'])


if __name__ == '__main__':
    unittest.main()
