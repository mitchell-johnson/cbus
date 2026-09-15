import argparse
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from xml.dom import minidom

from cbus_toolkit.project_repair_cli import (
    ProjectRepairFileError, ProjectRepairFileOperation, error_payload, options, run,
)


class ProjectRepairFileTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'source.xml'
        self.target = self.root / 'new.xml'
        self.original = b'<Project><TagName>A&#13;B</TagName><Application><Group><Address>1</Address></Group><Group><Address>1</Address></Group></Application></Project>'
        self.source.write_bytes(self.original)

    def test_new_output_is_complete_synced_and_source_is_unchanged(self):
        operation = ProjectRepairFileOperation()
        result = operation.run(self.source, output=self.target, line_ending='crlf')
        data = self.target.read_bytes()
        self.assertTrue(result['complete'])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(sha256(data).hexdigest(), result['repair']['output_sha256'])
        self.assertEqual(result['output_bytes_confirmed'], len(data))
        self.assertTrue(result['source_closed'] and result['output_closed'])
        self.assertTrue(result['output_write_complete'] and result['output_fsync_succeeded'])
        self.assertTrue(data.endswith(b'\r\n'))
        doc = minidom.parseString(data)
        self.assertEqual(doc.getElementsByTagName('TagName')[0].firstChild.data, 'A\rB')
        self.assertEqual(len(doc.getElementsByTagName('Group')), 1)
        doc.unlink()
        self.assertFalse(result['native_load_verified'])
        result['repair']['db_version'] = 'changed'
        self.assertEqual(operation.last_evidence['repair']['db_version'], '2.2')

    def test_parser_dry_run_needs_no_output_and_has_no_write_calls(self):
        parser = argparse.ArgumentParser()
        options(parser.add_subparsers(dest='action', required=True))
        args = parser.parse_args(['repair', str(self.source), '--dry-run'])
        args.area = 'project'
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=AssertionError('No writes')), \
                patch('cbus_toolkit.project_repair_cli.os.fsync', side_effect=AssertionError('No fsync')):
            result, code = run(args)
        self.assertEqual(code, 0)
        self.assertTrue(result['complete'] and result['dry_run'])
        self.assertFalse(result['output_create_attempted'])
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_invalid_options_precede_source_access(self):
        operation = ProjectRepairFileOperation()
        for settings in ({}, {'dry_run': 1}, {'dry_run': True, 'max_bytes': True},
                         {'dry_run': True, 'max_bytes': 0}, {'dry_run': True, 'line_ending': 'cr'}):
            with self.subTest(settings=settings), \
                    patch('cbus_toolkit.project_repair_cli.os.lstat', side_effect=AssertionError('No stat')):
                with self.assertRaises(ProjectRepairFileError) as caught:
                    operation.run(self.source, **settings)
            self.assertIsInstance(caught.exception.original_error, ValueError)
            self.assertEqual(caught.exception.details['stage'], 'validate')
            self.assertFalse(caught.exception.details['output_create_attempted'])

    def test_existing_output_same_input_and_symlink_are_never_overwritten(self):
        self.target.write_bytes(b'keep existing')
        for target in (self.target, self.source):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=target)
            self.assertIsInstance(caught.exception.original_error, FileExistsError)
            self.assertFalse(caught.exception.details['output_created'])
        if hasattr(os, 'symlink'):
            link = self.root / 'link.xml'
            link.symlink_to(self.target)
            with self.assertRaises(ProjectRepairFileError):
                ProjectRepairFileOperation().run(self.source, output=link)
            self.assertTrue(link.is_symlink())
        self.assertEqual(self.target.read_bytes(), b'keep existing')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_special_source_is_rejected_before_open(self):
        sources = [self.root]
        if hasattr(os, 'mkfifo'):
            fifo = self.root / 'fifo'
            os.mkfifo(fifo)
            sources.append(fifo)
        if hasattr(os, 'symlink'):
            link = self.root / 'source-link'
            link.symlink_to(self.source)
            sources.append(link)
        for source in sources:
            with self.subTest(source=source), \
                    patch('cbus_toolkit.project_repair_cli.os.open', side_effect=AssertionError('No open')):
                with self.assertRaises(ProjectRepairFileError) as caught:
                    ProjectRepairFileOperation().run(source, output=self.target)
            self.assertIsInstance(caught.exception.original_error, ValueError)
        self.assertFalse(self.target.exists())

    def test_size_and_growth_bounds_stop_before_output_creation(self):
        with patch('cbus_toolkit.project_repair_cli.os.read', side_effect=AssertionError('No read')):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target, max_bytes=16)
        self.assertTrue(caught.exception.details['source_closed'])
        info = self.source.stat()
        with patch('cbus_toolkit.project_repair_cli.os.fstat', return_value=SimpleNamespace(st_mode=info.st_mode, st_size=0)):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target, max_bytes=32)
        self.assertEqual(caught.exception.details['source_bytes'], 33)
        self.assertTrue(caught.exception.details['source_closed'])
        self.assertFalse(self.target.exists())

    def test_uncertain_partial_write_is_kept_without_retry_or_fsync(self):
        write = os.write
        first = OSError('write failed after partial mutation')
        def uncertain(fd, data):
            write(fd, data[:7])
            raise first
        operation = ProjectRepairFileOperation()
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=uncertain) as writes, \
                patch('cbus_toolkit.project_repair_cli.os.fsync', side_effect=AssertionError('No fsync')):
            with self.assertRaises(ProjectRepairFileError) as caught:
                operation.run(self.source, output=self.target)
        self.assertIs(caught.exception.original_error, first)
        self.assertIs(caught.exception.__cause__, first)
        self.assertEqual(writes.call_count, 1)
        self.assertEqual(self.target.stat().st_size, 7)
        self.assertEqual(caught.exception.details['output_bytes_confirmed'], 0)
        self.assertTrue(caught.exception.details['output_may_be_partial'])
        self.assertTrue(caught.exception.details['output_closed'])

    def test_zero_write_and_fsync_failures_preserve_created_output(self):
        with patch('cbus_toolkit.project_repair_cli.os.write', return_value=0) as writes:
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=self.target)
        self.assertEqual(writes.call_count, 1)
        self.assertEqual(self.target.stat().st_size, 0)
        self.assertTrue(caught.exception.details['output_closed'])
        other = self.root / 'sync.xml'
        with patch('cbus_toolkit.project_repair_cli.os.fsync', side_effect=OSError('fsync failed')):
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(self.source, output=other)
        self.assertTrue(caught.exception.details['output_write_complete'])
        self.assertFalse(caught.exception.details['output_fsync_succeeded'])
        self.assertTrue(caught.exception.details['output_closed'])
        self.assertEqual(other.stat().st_size, caught.exception.details['output_bytes_confirmed'])

    def test_close_failure_is_never_retried(self):
        close = os.close
        for fail_at in (1, 2):
            calls = []
            target = self.root / ('close-' + str(fail_at) + '.xml')
            def failure(fd):
                calls.append(fd)
                close(fd)
                if len(calls) == fail_at:
                    raise OSError('close uncertain')
            with patch('cbus_toolkit.project_repair_cli.os.close', side_effect=failure):
                with self.assertRaises(ProjectRepairFileError) as caught:
                    ProjectRepairFileOperation().run(self.source, output=target)
            self.assertEqual(len(calls), fail_at)
            self.assertEqual(caught.exception.details['stage'], 'source_close' if fail_at == 1 else 'output_close')
            self.assertEqual(target.exists(), fail_at == 2)

    def test_first_interruption_survives_attachment_getter_and_cleanup_failures(self):
        class First(KeyboardInterrupt):
            def __str__(self):
                raise SystemExit('message failure')
            def __setattr__(self, name, value):
                raise SystemExit('attachment failure')
            def __getattribute__(self, name):
                if name == 'project_repair_evidence':
                    raise SystemExit('getter failure')
                return super().__getattribute__(name)
        first = First()
        close, write = os.close, os.write
        calls = []
        def partial(fd, data):
            write(fd, data[:5])
            raise first
        def closing(fd):
            calls.append(fd)
            close(fd)
            if len(calls) == 2:
                raise SystemExit('second close interruption')
        operation = ProjectRepairFileOperation()
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=partial), \
                patch('cbus_toolkit.project_repair_cli.os.close', side_effect=closing):
            with self.assertRaises(KeyboardInterrupt) as caught:
                operation.run(self.source, output=self.target)
        self.assertIs(caught.exception, first)
        self.assertIs(operation.last_error, first)
        self.assertEqual(self.target.stat().st_size, 5)
        args = SimpleNamespace(area='project', action='repair', _project_repair_operation=operation)
        evidence = error_payload(first, args)['project_repair_evidence']
        self.assertEqual(evidence['cleanup_errors'][0]['type'], 'SystemExit')
        self.assertEqual(evidence['error']['type'], 'First')
        self.assertFalse(evidence['complete'])
        self.assertEqual(error_payload(KeyboardInterrupt('stale'), args), {})

    def test_snapshot_failure_does_not_replace_first_error_and_reuse_clears_evidence(self):
        operation = ProjectRepairFileOperation()
        first = OSError('write failure')
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=first), \
                patch('cbus_toolkit.project_repair_cli.copy.deepcopy', side_effect=KeyboardInterrupt('snapshot')):
            with self.assertRaises(ProjectRepairFileError) as caught:
                operation.run(self.source, output=self.target)
        self.assertIs(caught.exception.original_error, first)
        self.assertTrue(operation.last_evidence['evidence_export_failed'])
        result = operation.run(self.source, dry_run=True)
        self.assertTrue(result['complete'])
        self.assertIsNone(operation.last_error)
        self.assertFalse(result['output_create_attempted'])
        self.assertEqual(result['cleanup_errors'], [])

    def test_transform_failure_stage_is_retained_before_output_creation(self):
        for data, limit, stage in ((b'x', 1, 'manual'), (b'<Project>', 1024, 'repair'),
                                   (b'<OID/>', 1024, 'tidy')):
            with self.subTest(stage=stage):
                self.source.write_bytes(data)
                with self.assertRaises(ProjectRepairFileError) as caught:
                    ProjectRepairFileOperation().run(self.source, output=self.target, max_bytes=limit)
                self.assertEqual(caught.exception.details['stage'], 'repair')
                self.assertEqual(caught.exception.details['repair_failure_stage'], stage)
                self.assertFalse(caught.exception.details['output_create_attempted'])
                self.assertFalse(self.target.exists())

    def invoke_cli(self, *arguments, expected_status=0):
        from cbus_toolkit.cli import main
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No C-Gate connection')):
            status = main(['project', 'repair', *map(str, arguments)])
        self.assertEqual(status, expected_status, out.getvalue() + err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def test_integrated_cli_preview_new_output_and_existing_target_error(self):
        preview = self.invoke_cli(self.source, '--dry-run')
        self.assertTrue(preview['complete'])
        self.assertFalse(preview['output_create_attempted'])
        result = self.invoke_cli(self.source, '--output', self.target)
        self.assertTrue(result['output_fsync_succeeded'] and result['output_closed'])
        before = self.target.read_bytes()
        rejected = self.invoke_cli(self.source, '--output', self.target, expected_status=1)
        self.assertFalse(rejected['complete'])
        self.assertEqual(rejected['error']['type'], 'FileExistsError')
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_integrated_cli_interruption_retains_exact_partial_write_evidence(self):
        class First(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name == 'project_repair_evidence':
                    raise SystemExit('attachment rejected')
                return super().__setattr__(name, value)
            def __getattribute__(self, name):
                if name == 'project_repair_evidence':
                    raise SystemExit('getter rejected')
                return super().__getattribute__(name)
        first = First('primary')
        write = os.write
        def interrupted(fd, data):
            write(fd, data[:9])
            raise first
        with patch('cbus_toolkit.project_repair_cli.os.write', side_effect=interrupted) as writes, \
                patch('cbus_toolkit.project_repair_cli.error_payload', wraps=error_payload) as exported:
            result = self.invoke_cli(self.source, '--output', self.target, expected_status=130)
        self.assertIs(exported.call_args.args[0], first)
        evidence = result['project_repair_evidence']
        self.assertEqual(evidence['output_bytes_confirmed'], 0)
        self.assertTrue(evidence['output_may_be_partial'] and evidence['output_closed'])
        self.assertEqual(self.target.stat().st_size, 9)
        self.assertEqual(writes.call_count, 1)


if __name__ == '__main__':
    unittest.main()
