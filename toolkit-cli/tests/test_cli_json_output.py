"""CLI output must preserve Unicode on restricted redirected text streams."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import cli


class CLIJSONOutputTests(unittest.TestCase):
    def invoke(self, arguments, encoding, *, status=0):
        raw_out, raw_err = io.BytesIO(), io.BytesIO()
        out = io.TextIOWrapper(raw_out, encoding=encoding, errors='strict')
        err = io.TextIOWrapper(raw_err, encoding=encoding, errors='strict')
        try:
            with redirect_stdout(out), redirect_stderr(err):
                actual = cli.main(arguments)
            out.flush()
            err.flush()
            stdout, stderr = raw_out.getvalue(), raw_err.getvalue()
            self.assertEqual(actual, status, repr((stdout, stderr)))
            self.assertTrue(stdout.isascii() and stderr.isascii())
            return stdout.decode('ascii'), stderr.decode('ascii')
        finally:
            out.close()
            err.close()

    def test_unicode_repair_preview_write_and_rejection_preserve_exact_paths(self):
        for encoding in ('cp1252', 'ascii'):
            for compact in (False, True):
                with self.subTest(encoding=encoding, compact=compact), tempfile.TemporaryDirectory() as root:
                    source = Path(root) / '原本-é-\U0001f4a1.xml'
                    target = Path(root) / '修復-\U0001f4a1.xml'
                    original = '<Project><TagName>照明</TagName></Project>'.encode('utf-8')
                    source.write_bytes(original)
                    arguments = (['--compact'] if compact else []) + ['project', 'repair', str(source)]
                    stdout, stderr = self.invoke([*arguments, '--dry-run'], encoding)
                    preview = json.loads(stdout)
                    self.assertEqual(stderr, '')
                    self.assertTrue(preview['complete'])
                    self.assertEqual(preview['source'], str(source))
                    self.assertFalse(target.exists())
                    with patch('cbus_toolkit.project_repair_cli.os.write', wraps=os.write) as writes:
                        stdout, stderr = self.invoke([*arguments, '--output', str(target)], encoding)
                    result = json.loads(stdout)
                    self.assertEqual(stderr, '')
                    self.assertTrue(result['complete'] and result['output_closed'])
                    self.assertEqual((result['source'], result['output']), (str(source), str(target)))
                    self.assertEqual(writes.call_count, 1)
                    repaired = target.read_bytes()
                    self.assertEqual(result['repair']['output_sha256'], sha256(repaired).hexdigest())
                    self.assertIn('照明'.encode('utf-8'), repaired)
                    stdout, stderr = self.invoke([*arguments, '--output', str(target)], encoding, status=1)
                    self.assertEqual(stdout, '')
                    rejected = json.loads(stderr)
                    self.assertEqual(rejected['error']['type'], 'FileExistsError')
                    self.assertEqual(rejected['output'], str(target))
                    self.assertEqual(target.read_bytes(), repaired)
                    self.assertEqual(source.read_bytes(), original)

    def test_unicode_event_and_summary_are_valid_json_lines(self):
        for encoding in ('cp1252', 'ascii'):
            with self.subTest(encoding=encoding):
                client = Mock(events_lost=False)
                client.__enter__ = Mock(return_value=client)
                client.__exit__ = Mock(return_value=False)
                client.command.return_value = SimpleNamespace(code=200)
                raw = '#s# 照明-é-\U0001f4a1'
                client.read_event.return_value = raw
                with patch('cbus_toolkit.cgate.CGateClient', return_value=client):
                    stdout, stderr = self.invoke(['cgate', 'events', '--count', '1'], encoding)
                self.assertEqual(stderr, '')
                event, summary = [json.loads(line) for line in stdout.splitlines()]
                self.assertEqual(event['raw'], raw)
                self.assertEqual(event['text'], raw[4:])
                self.assertEqual(summary, {'type': 'event-summary', 'received': 1, 'events_lost': False})
                client.read_event.assert_called_once_with()
                client.command.assert_called_once_with('EVENT e8s1c1')

    def test_general_results_preserve_custom_types_and_unicode_without_replay(self):
        class Choice(Enum):
            VALUE = '照明'
        @dataclass
        class Result:
            path: Path
            choice: Choice
            raw: bytes
        result = Result(Path('原本-\U0001f4a1.xml'), Choice.VALUE, b'\xff')
        for encoding in ('cp1252', 'ascii'):
            with self.subTest(encoding=encoding), patch('cbus_toolkit.cli.run', return_value=(result, 0)) as run:
                stdout, stderr = self.invoke(['coverage'], encoding)
            self.assertEqual(stderr, '')
            self.assertEqual(json.loads(stdout), {'path': str(result.path), 'choice': '照明', 'raw': 'ff'})
            run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
