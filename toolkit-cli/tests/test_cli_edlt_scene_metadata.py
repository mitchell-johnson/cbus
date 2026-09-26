"""CLI surfaces for automatic native eDLT Scene Manager metadata."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_scene_manager_cli import SceneCLIEditor
from tests.test_edlt_parent_metadata import FakeProgrammer, NativeSession
from tests.test_edlt_scene_manager import operations, vectors
from tests.test_edlt_scene_metadata import SceneMetadataClient
from tests.test_edlt_lifecycle import fixture


class SceneMetadataCLITests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = SceneCLIEditor(self.spec)
        self.client = SceneMetadataClient(self.spec)
        source = self.editor.snapshot(self.client.values)
        source.update({name: value for name, value in vectors()['input'].items()
                       if name in self.spec.parameters})
        source = self.editor.snapshot(source)
        self.client.values = {name: _render(value)
                              for name, value in source.items()}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.values = root / 'values.json'
        self.project = root / 'project.xml'
        self.ops = root / 'operations.json'
        self.values.write_text(json.dumps(
            self.editor.snapshot(self.client.values)))
        self.project.write_text(self.client.xml())
        self.ops.write_text(json.dumps(operations('sync')))

    def invoke(self, arguments, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, stdout.getvalue() + stderr.getvalue())
        return json.loads(stdout.getvalue() or stderr.getvalue())

    def test_offline_project_plan_and_state_need_no_connection(self):
        common = (
            self.values, '--project-xml', self.project,
            '--unit', '//TEST/254/p/20', '--operations', self.ops,
        )
        with patch('cbus_toolkit.edlt_scene_manager_cli.editor',
                   return_value=self.editor), patch(
                'cbus_toolkit.cgate.CGateClient',
                side_effect=AssertionError('offline plan connected')):
            plan = self.invoke(('edlt', 'scene-manager-plan', *common))
            state = self.invoke((
                'edlt', 'scene-manager-state', *common,
                '--list-groups', 1))
        self.assertEqual(plan['format'],
                         'cbus-native-edlt-scene-metadata-plan-v2')
        self.assertEqual(state['format'],
                         'cbus-native-edlt-scene-metadata-state-v1')
        self.assertIn('automatic_metadata', state)
        self.assertIn('1', state['available_groups'])
        self.assertFalse(plan['metadata_mutation_planned'])
        self.assertFalse(plan['physical_device_programmed'])

    def test_native_auto_metadata_dry_run_and_apply(self):
        session = NativeSession(self.spec, self.client)
        programmer = FakeProgrammer(session)
        arguments = (
            'cgate', 'unit', '--lock-address', '//TEST/254',
            '--source', '/db//TEST/254/p/20', 'edlt-scene-manager',
            '--auto-metadata', '--exclusive-project',
            '--operations', self.ops,
        )
        with patch('cbus_toolkit.cgate.CGateClient',
                   return_value=nullcontext(self.client)), patch.object(
                cli, '_edlt_scene_manager', return_value=self.editor), patch(
                'cbus_toolkit.edlt_scene_metadata.Programmer',
                return_value=programmer):
            preview = self.invoke((*arguments[:6], '--dry-run',
                                   *arguments[6:]))
        self.assertFalse(preview['saved'])
        self.assertFalse(preview['applied'])
        self.assertFalse(any(command.startswith(('DBADD', 'DBDELETE'))
                             for command in self.client.commands))

        editor = SceneCLIEditor(self.spec)
        session = NativeSession(self.spec, self.client)
        programmer = FakeProgrammer(session)
        with patch('cbus_toolkit.cgate.CGateClient',
                   return_value=nullcontext(self.client)), patch.object(
                cli, '_edlt_scene_manager', return_value=editor), patch(
                'cbus_toolkit.edlt_scene_metadata.Programmer',
                return_value=programmer):
            saved = self.invoke(arguments)
        self.assertTrue(saved['saved'])
        self.assertTrue(saved['persistence_verified'])
        self.assertTrue(saved['existing_metadata_preserved'])

    def test_native_missing_action_uses_reviewed_backup_and_creation(self):
        self.ops.write_text(json.dumps([
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
        ]))
        session = NativeSession(self.spec, self.client)
        arguments = (
            'cgate', 'unit', '--lock-address', '//TEST/254',
            '--source', '/db//TEST/254/p/20', 'edlt-scene-manager',
            '--auto-metadata', '--exclusive-project',
            '--backup-project', 'SCBACKUP', '--operations', self.ops,
        )
        with patch('cbus_toolkit.cgate.CGateClient',
                   return_value=nullcontext(self.client)), patch.object(
                cli, '_edlt_scene_manager', return_value=self.editor), patch(
                'cbus_toolkit.edlt_scene_metadata.Programmer',
                return_value=FakeProgrammer(session)):
            saved = self.invoke(arguments)
        self.assertTrue(saved['backup_created'])
        self.assertTrue(saved['target_project_save_confirmed'])
        self.assertEqual(saved['objects'][0]['name'], 'Action Selector 2')

        with patch('cbus_toolkit.cgate.CGateClient',
                   return_value=nullcontext(self.client)), patch.object(
                cli, '_edlt_scene_manager', return_value=SceneCLIEditor(
                    self.spec)):
            rejected = self.invoke((
                *arguments[:6], '--dry-run', *arguments[6:]), status=1)
        self.assertIn('--backup-project requires an apply', rejected['error'])

    def test_interrupted_native_save_keeps_uncertainty_evidence(self):
        session = NativeSession(self.spec, self.client)
        session.save_error = KeyboardInterrupt('lost save reply')
        arguments = (
            'cgate', 'unit', '--lock-address', '//TEST/254',
            '--source', '/db//TEST/254/p/20', 'edlt-scene-manager',
            '--auto-metadata', '--exclusive-project',
            '--operations', self.ops,
        )
        with patch('cbus_toolkit.cgate.CGateClient',
                   return_value=nullcontext(self.client)), patch.object(
                cli, '_edlt_scene_manager', return_value=self.editor), patch(
                'cbus_toolkit.edlt_scene_metadata.Programmer',
                return_value=FakeProgrammer(session)):
            result = self.invoke(arguments, status=130)
        evidence = result['edlt_scene_metadata_evidence']
        self.assertTrue(evidence['pp_save_attempted'])
        self.assertFalse(evidence['pp_save_confirmed'])
        self.assertTrue(evidence['pp_save_outcome_uncertain'])
        self.assertTrue(evidence['database_state_uncertain'])
        self.assertFalse(evidence['saved'])

    def test_surface_guards_fail_before_programming(self):
        base = (
            'cgate', 'unit', '--lock-address', '//TEST/254',
            '--source', '/db//TEST/254/p/20', '--dry-run',
            'edlt-scene-manager', '--auto-metadata',
            '--operations', self.ops,
        )
        with patch('cbus_toolkit.cgate.CGateClient',
                   return_value=nullcontext(self.client)), patch.object(
                cli, '_edlt_scene_manager', return_value=self.editor):
            missing = self.invoke(base, status=1)
        self.assertIn('--exclusive-project', missing['error'])

        wrong = list(base)
        wrong[3] = '//TEST/253'
        wrong.extend(('--exclusive-project',))
        with patch('cbus_toolkit.cgate.CGateClient',
                   return_value=nullcontext(self.client)), patch.object(
                cli, '_edlt_scene_manager', return_value=self.editor):
            result = self.invoke(wrong, status=1)
        self.assertIn('--lock-address //TEST/254', result['error'])

        with patch('cbus_toolkit.edlt_scene_manager_cli.editor',
                   return_value=self.editor):
            result = self.invoke((
                'edlt', 'scene-manager-plan', self.values,
                '--project-xml', self.project,
                '--operations', self.ops,
            ), status=1)
        self.assertIn('--unit is required', result['error'])


if __name__ == '__main__':
    unittest.main()
