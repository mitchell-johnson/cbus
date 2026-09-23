from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli, toolkit_database_csv_cli as boundary
from cbus_toolkit.toolkit_database_csv import COLUMNS
from tests.test_toolkit_database_csv import captured, unit
from tests.test_toolkit_database_csv_projection import projection_input


class DatabaseCSVCLITests(unittest.TestCase):
    def execute(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch('socket.socket', side_effect=AssertionError('No network')):
            code = cli.main(['toolkit-database-csv', *map(str, args)])
        return code, json.loads(out.getvalue() or err.getvalue())

    def files(self, folder):
        source, output = Path(folder) / '捕獲 💡.json', Path(folder) / '报告 💡.csv'
        source.write_bytes(json.dumps(captured(unit(tag_name='灯, "💡"'))).encode())
        return source, output

    def test_real_dispatch_unicode_utf8_exclusive_output_and_original_order(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder); before = source.read_bytes()
            code, result = self.execute([source, '--output', output, '--columns', 'tag_name', 'address'])
            self.assertEqual(code, 0); self.assertTrue(result['complete'])
            self.assertTrue(result['source_identity_verified'])
            self.assertEqual(output.read_bytes(), 'Unit Address,Tag Name,\r\n7,"灯, ""💡""",\r\n\r\n'.encode())
            self.assertEqual(result['report']['columns'], ['address', 'tag_name'])
            self.assertEqual(source.read_bytes(), before)
            saved = output.read_bytes()
            code, result = self.execute([source, '--output', output])
            self.assertEqual(code, 1); evidence = result['toolkit_database_csv_evidence']
            self.assertFalse(evidence['output_created']); self.assertEqual(output.read_bytes(), saved)
            self.assertEqual(evidence['stage'], 'output_create')

    def test_default_all_and_empty_report_extra_blank_line(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder); source.write_text(json.dumps(captured()))
            code, result = self.execute([source, '--output', output])
            self.assertEqual(code, 0); self.assertEqual(result['report']['columns'], list(COLUMNS))
            self.assertEqual(result['report']['unit_count'], 0)
            self.assertTrue(output.read_bytes().endswith(b'Group 16,\r\n\r\n'))

    def test_cached_projection_mode_exports_original_backed_row_and_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'cached.json'; output = Path(folder) / 'report.csv'
            source.write_text(json.dumps(projection_input()))
            code, result = self.execute([source, '--output', output, '--cached-projection',
                                         '--columns', 'area', 'address'])
            self.assertEqual(code, 0)
            self.assertEqual(result['input_mode'], 'cached_projection')
            self.assertTrue(result['projection']['complete'])
            self.assertEqual(result['projection']['selected_class'], 'TRELAY4')
            self.assertEqual(output.read_bytes(), b'Unit Address,Area,\r\n4,Area12,\r\n\r\n')

    def test_cached_projection_provider_stop_creates_no_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'cached.json'; output = Path(folder) / 'report.csv'
            value = projection_input(observations=('12', '12'))
            value['area_observations'][0]['completed'] = False
            source.write_text(json.dumps(value))
            code, result = self.execute([source, '--output', output, '--cached-projection'])
            self.assertEqual(code, 1)
            evidence = result['toolkit_database_csv_evidence']
            self.assertEqual(evidence['stage'], 'project_cached_unit')
            self.assertEqual(evidence['projection']['stop_reason'], 'area_load_failed')
            self.assertFalse(evidence['output_create_attempted'])
            self.assertFalse(output.exists())

    def test_columns_invalid_before_input_io_and_capture_invalid_before_output_creation(self):
        for columns in (['all', 'address'], ['address', 'address'], ['unknown']):
            with patch.object(boundary.os, 'lstat', side_effect=AssertionError('No input read')):
                code, result = self.execute(['missing', '--output', 'missing-output', '--columns', *columns])
            self.assertEqual(code, 1); self.assertEqual(result['toolkit_database_csv_evidence']['stage'], 'validate')
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder)
            for raw in (b'<Project/>', b'{}', b'{"format":"x","format":"y"}',
                        json.dumps(captured(unit())).replace('"address": 7', '"address": true').encode()):
                source.write_bytes(raw)
                code, result = self.execute([source, '--output', output])
                self.assertEqual(code, 1); self.assertFalse(output.exists())
                self.assertFalse(result['toolkit_database_csv_evidence']['output_create_attempted'])

    def test_regular_file_bounds_symlink_and_open_replacement_reject(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder); link = Path(folder) / 'link'; link.symlink_to(source)
            values = [Path(folder), link]
            if hasattr(os, 'mkfifo'):
                fifo = Path(folder) / 'fifo'; os.mkfifo(fifo); values.append(fifo)
            for path in values:
                code, _ = self.execute([path, '--output', output]); self.assertEqual(code, 1)
            source.write_bytes(b'')
            code, _ = self.execute([source, '--output', output]); self.assertEqual(code, 1)
            with source.open('wb') as handle: handle.truncate(boundary.MAX_CAPTURE_BYTES + 1)
            code, _ = self.execute([source, '--output', output]); self.assertEqual(code, 1)
            source.write_text(json.dumps(captured()))
            target = Path(folder) / 'alternate'; target.write_bytes(source.read_bytes())
            real_open = os.open
            def replaced(path, flags, *args):
                if Path(path) == source:
                    source.unlink(); source.symlink_to(target)
                    # Simulate a platform with no O_NOFOLLOW.
                    flags &= ~getattr(os, 'O_NOFOLLOW', 0)
                return real_open(path, flags, *args)
            with patch.object(boundary.os, 'open', side_effect=replaced):
                code, result = self.execute([source, '--output', output])
            self.assertEqual(code, 1); self.assertFalse(output.exists())
            self.assertFalse(result['toolkit_database_csv_evidence']['source_identity_verified'])

    def test_partial_writes_are_completed_without_recreating_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder); write = os.write; opened = os.open
            def small(fd, data): return write(fd, data[:3])
            with patch.object(boundary.os, 'write', side_effect=small) as writes, patch.object(boundary.os, 'open', wraps=opened) as opens:
                code, result = self.execute([source, '--output', output, '--columns', 'address'])
            self.assertEqual(code, 0); self.assertGreater(writes.call_count, 1)
            self.assertEqual(sum(bool(call.args[1] & os.O_CREAT) for call in opens.call_args_list), 1)
            self.assertEqual(output.read_bytes(), b'Unit Address,\r\n7,\r\n\r\n')
            self.assertEqual(result['output_bytes_confirmed'], output.stat().st_size)

    def test_partial_write_then_error_and_cleanup_interrupt_retain_first_cause(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder); write, close = os.write, os.close
            first = OSError('write failed'); second = KeyboardInterrupt('close failed'); writes = 0
            def fail_write(fd, data):
                nonlocal writes
                writes += 1
                if writes == 1: return write(fd, data[:5])
                raise first
            closed = 0
            def fail_close(fd):
                nonlocal closed
                closed += 1; close(fd)
                if closed == 2: raise second
            op = boundary.DatabaseCSVFileOperation()
            with patch.object(boundary.os, 'write', side_effect=fail_write), patch.object(boundary.os, 'close', side_effect=fail_close):
                with self.assertRaises(boundary.DatabaseCSVFileError) as raised:
                    op.run(source, output=output, columns=('address',))
            self.assertIs(raised.exception.__cause__, first)
            self.assertIs(raised.exception.original_error, first)
            self.assertEqual(output.read_bytes(), b'Unit ')
            self.assertEqual(op.last_evidence['output_bytes_confirmed'], 5)
            self.assertTrue(op.last_evidence['output_may_be_partial'])
            self.assertEqual(op.last_evidence['cleanup_errors'][0]['type'], 'KeyboardInterrupt')
            self.assertEqual(closed, 2)

    def test_first_interruption_identity_survives_secondary_unprintable_close(self):
        class Broken(SystemExit):
            def __str__(self): raise KeyboardInterrupt('message failed')
        first, second = KeyboardInterrupt('read interrupted'), Broken()
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder); close = os.close
            def fail_close(fd): close(fd); raise second
            op = boundary.DatabaseCSVFileOperation()
            with patch.object(boundary.os, 'read', side_effect=first), patch.object(boundary.os, 'close', side_effect=fail_close):
                with self.assertRaises(KeyboardInterrupt) as raised: op.run(source, output=output, columns=('address',))
            self.assertIs(raised.exception, first); self.assertFalse(output.exists())
            self.assertEqual(op.last_evidence['cleanup_errors'][0]['message'], '<exception message unavailable>')

    def test_fsync_and_close_failures_mark_existing_output_uncertain_and_no_retry(self):
        for stage in ('fsync', 'close'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                source, output = self.files(folder); close = os.close; calls = 0
                first = OSError(stage + ' failed')
                def close_output(fd):
                    nonlocal calls
                    calls += 1; close(fd)
                    if calls == 2: raise first
                with patch.object(boundary.os, 'close', side_effect=close_output if stage == 'close' else close), \
                     patch.object(boundary.os, 'fsync', side_effect=first if stage == 'fsync' else None):
                    code, result = self.execute([source, '--output', output, '--columns', 'address'])
                self.assertEqual(code, 1); self.assertTrue(output.exists())
                state = result['toolkit_database_csv_evidence']
                self.assertTrue(state['output_write_complete']); self.assertFalse(state['complete'])
                self.assertEqual(state['error']['message'], stage + ' failed')
                if stage == 'close': self.assertEqual(calls, 2)

    def test_actual_main_interruption_and_evidence_copy_failure_preserve_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder); first = KeyboardInterrupt('read stopped')
            with patch.object(boundary.os, 'read', side_effect=first):
                code, result = self.execute([source, '--output', output])
            self.assertEqual(code, 130); self.assertFalse(output.exists())
            self.assertEqual(result['toolkit_database_csv_evidence']['stage'], 'source_read')
            op = boundary.DatabaseCSVFileOperation()
            with patch.object(boundary.os, 'read', side_effect=first), patch.object(boundary.copy, 'deepcopy', side_effect=SystemExit(5)):
                with self.assertRaises(KeyboardInterrupt) as stopped: op.run(source, output=output, columns=('address',))
            self.assertIs(stopped.exception, first); self.assertTrue(op.last_evidence['evidence_export_failed'])

    def test_lost_creation_return_retains_possible_empty_output_without_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = self.files(folder); opened, close = os.open, os.close
            first = KeyboardInterrupt('creation return interrupted')
            def lost(path, flags, *args):
                descriptor = opened(path, flags, *args)
                if flags & os.O_CREAT:
                    close(descriptor)  # Fixture owns this otherwise unreturned handle.
                    raise first
                return descriptor
            with patch.object(boundary.os, 'open', side_effect=lost) as calls:
                code, result = self.execute([source, '--output', output])
            self.assertEqual(code, 130); self.assertEqual(output.read_bytes(), b'')
            evidence = result['toolkit_database_csv_evidence']
            self.assertFalse(evidence['output_created'])
            self.assertTrue(evidence['output_may_exist']); self.assertTrue(evidence['output_may_be_partial'])
            self.assertEqual(evidence['output_bytes_confirmed'], 0)
            self.assertEqual(sum(bool(c.args[1] & os.O_CREAT) for c in calls.call_args_list), 1)


if __name__ == '__main__': unittest.main()
