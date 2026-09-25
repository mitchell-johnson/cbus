"""Offline and database-only CLI surfaces for automatic parent metadata."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from tests.test_edlt_parent_form import fixture
from tests.test_edlt_parent_metadata import (
    FakeProgrammer, MetadataClient, NativeSession,
)
from tests.test_edlt_parent_transaction import activation, lighting, measurement


class ParentMetadataCLITests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)

    def invoke(self, arguments, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, stdout.getvalue() + stderr.getvalue())
        return json.loads(stdout.getvalue() or stderr.getvalue())

    def files(self, root, client):
        values = Path(root) / 'values.json'
        project = Path(root) / 'project.xml'
        operations = Path(root) / 'operations.json'
        values.write_text(json.dumps(self.editor.snapshot(client.values)))
        project.write_text(client.xml())
        operations.write_text(json.dumps(
            [measurement(), lighting(), activation()]))
        return values, project, operations

    def test_offline_project_snapshot_plan_has_no_connection_or_mutation(self):
        client = MetadataClient(self.spec)
        with tempfile.TemporaryDirectory() as root:
            values, project, operations = self.files(root, client)
            before = (values.read_bytes(), project.read_bytes(),
                      operations.read_bytes())
            with patch.object(cli, '_edlt_parent_transaction',
                              return_value=self.editor), patch(
                    'cbus_toolkit.cgate.CGateClient',
                    side_effect=AssertionError('offline plan connected')):
                result = self.invoke([
                    'edlt', 'parent-transaction-plan', values,
                    '--project-xml', project, '--unit', '//TEST/254/p/20',
                    '--operations', operations,
                ])
            self.assertEqual(result['format'],
                             'cbus-native-edlt-parent-metadata-plan-v1')
            self.assertEqual(len(result['planned_creations']), 3)
            self.assertFalse(result['physical_device_programmed'])
            self.assertEqual((values.read_bytes(), project.read_bytes(),
                              operations.read_bytes()), before)

    def test_database_auto_metadata_dry_run_reads_only(self):
        client = MetadataClient(self.spec)
        with tempfile.TemporaryDirectory() as root:
            _, _, operations = self.files(root, client)
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(client)), patch.object(
                    cli, '_edlt_parent_transaction', return_value=self.editor):
                result = self.invoke([
                    'cgate', 'unit', '--lock-address', '//TEST/254',
                    '--source', '/db//TEST/254/p/20', '--dry-run',
                    'edlt-parent-transaction', '--auto-metadata',
                    '--exclusive-project', '--operations', operations,
                ])
            self.assertFalse(result['applied'])
            self.assertFalse(result['saved'])
            self.assertFalse(any(command.startswith(('DBADD', 'PROJECT '))
                                 for command in client.commands))

    def test_database_auto_metadata_apply_uses_combined_manager(self):
        client = MetadataClient(self.spec)
        session = NativeSession(self.spec, client)
        programmer = FakeProgrammer(session)
        with tempfile.TemporaryDirectory() as root:
            _, _, operations = self.files(root, client)
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(client)), patch.object(
                    cli, '_edlt_parent_transaction', return_value=self.editor), patch(
                    'cbus_toolkit.edlt_parent_metadata.Programmer',
                    return_value=programmer):
                result = self.invoke([
                    'cgate', 'unit', '--lock-address', '//TEST/254',
                    '--source', '/db//TEST/254/p/20',
                    'edlt-parent-transaction', '--auto-metadata',
                    '--exclusive-project', '--backup-project', 'BACKUP',
                    '--operations', operations,
                ])
            self.assertTrue(result['complete'])
            self.assertTrue(result['persistence_verified'])
            self.assertEqual(result['backup_project'], 'BACKUP')
            self.assertEqual(client.values['ProximityLevel'], '127')

    def test_surface_guards_reject_mixed_or_unreviewable_inputs(self):
        parsed = cli.build_parser().parse_args([
            'edlt', 'parent-transaction-plan', 'values.json',
            '--project-xml', 'project.xml', '--operations', 'operations.json'])
        self.assertIsNone(parsed.unit)
        with tempfile.TemporaryDirectory() as root:
            client = MetadataClient(self.spec)
            _, _, operations = self.files(root, client)
            with patch.object(cli, '_edlt_parent_transaction',
                              return_value=self.editor):
                missing_unit = self.invoke([
                    'edlt', 'parent-transaction-plan', Path(root) / 'values.json',
                    '--project-xml', Path(root) / 'project.xml',
                    '--operations', operations,
                ], status=1)
            self.assertIn('--unit is required', missing_unit['error'])
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(client)), patch.object(
                    cli, '_edlt_parent_transaction', return_value=self.editor):
                missing_exclusive = self.invoke([
                    'cgate', 'unit', '--lock-address', '//TEST/254',
                    '--source', '/db//TEST/254/p/20', '--dry-run',
                    'edlt-parent-transaction', '--auto-metadata',
                    '--operations', operations,
                ], status=1)
            self.assertIn('--exclusive-project', missing_exclusive['error'])
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(client)), patch.object(
                    cli, '_edlt_parent_transaction', return_value=self.editor):
                wrong_lock = self.invoke([
                    'cgate', 'unit', '--lock-address', '//TEST/253',
                    '--source', '/db//TEST/254/p/20', '--dry-run',
                    'edlt-parent-transaction', '--auto-metadata',
                    '--exclusive-project', '--operations', operations,
                ], status=1)
            self.assertIn('--lock-address //TEST/254', wrong_lock['error'])


if __name__ == '__main__':
    unittest.main()
