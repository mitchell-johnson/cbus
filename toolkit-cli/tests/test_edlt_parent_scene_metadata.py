"""Automatic SceneManager metadata inside the ordered parent transaction."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltError, _render
from cbus_toolkit.edlt_parent_metadata import (
    NativeEdltParentError, NativeEdltParentTransaction,
    plan_native_parent_metadata,
)
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from cbus_toolkit.edlt_scene_manager import SceneManagerCache
from tests.test_edlt_parent_form import fixture
from tests.test_edlt_parent_metadata import (
    FakeProgrammer, NativeSession,
)
from tests.test_edlt_parent_scene_manager import (
    capacity_operations, scene_manager,
)
from tests.test_edlt_parent_transaction import lighting, measurement
from tests.test_edlt_scene_manager import op, operations, vectors
from tests.test_edlt_scene_metadata import SceneMetadataClient


def parent_operations():
    return (
        scene_manager(*operations('sync')),
        measurement(),
        lighting(),
    )


class ParentSceneMetadataTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.client = SceneMetadataClient(self.spec)
        source = self.editor.snapshot(self.client.values)
        source.update({
            name: value for name, value in vectors()['input'].items()
            if name in self.spec.parameters
        })
        self.values = self.editor.snapshot(source)
        self.client.values = {
            name: _render(value) for name, value in self.values.items()
        }
        self.client.saved_values = deepcopy(self.client.values)

    def offline(self, rows=None):
        return plan_native_parent_metadata(
            self.client.xml(), '//TEST/254/p/20', self.values,
            self.editor, parent_operations() if rows is None else rows)

    def remove_scene_and_lighting_metadata(self):
        del self.client.applications[202]
        del self.client.saved_applications[202]
        del self.client.applications[56]['groups'][12]
        del self.client.saved_applications[56]['groups'][12]

    def manager(self):
        session = NativeSession(self.spec, self.client)
        manager = NativeEdltParentTransaction(
            self.client, self.editor, programmer=FakeProgrammer(session))
        return manager, session

    def test_offline_plan_composes_exact_scene_resolver_and_parent_cache(self):
        plan = self.offline()
        document = plan.as_dict()
        self.assertIsInstance(plan.cache, SceneManagerCache)
        self.assertEqual(document['automatic_scene_metadata']['format'],
                         'cbus-native-edlt-scene-cache-v3')
        self.assertEqual(document['automatic_scene_metadata'][
            'consumed_trigger_actions'], [
                {'group': 42, 'action': 1},
                {'group': 42, 'action': 2},
            ])
        self.assertEqual(
            [row['format'] for row in document['parent_transaction'][
                'operation_results']],
            ['cbus-edlt-parent-scene-manager-operation-v1',
             'cbus-edlt-measurement-plan-v1',
             'cbus-edlt-lighting-plan-v1'])
        self.assertEqual(document['parent_transaction']['execution_counts'][
            'terminal_crc_passes'], 1)
        self.assertEqual(document['parent_transaction']['ownership'][
            'scene_graph']['item_count'], 3)
        self.assertEqual(document['planned_creations'], [])

    def test_missing_parent_and_scene_objects_are_projected_in_dependency_order(self):
        self.remove_scene_and_lighting_metadata()
        plan = self.offline()
        document = plan.as_dict()
        self.assertEqual(
            [(row['kind'], row.get('application'), row.get('group'),
              row['address']) for row in document['planned_creations']],
            [('Application', None, None, 202),
             ('Group', 56, None, 12),
             ('Group', 202, None, 42),
             ('Level', 202, 42, 1),
             ('Level', 202, 42, 2)])
        for row in document['planned_creations'][1:]:
            self.assertEqual(row['default_dynamic_labels'], [
                {'value': str(index), 'name': '', 'image_present': False}
                for index in range(4)
            ])
        cache = plan.cache.application_cache
        self.assertTrue(cache.applications_complete)
        self.assertTrue(cache.find_group_list(56).complete)
        self.assertEqual(cache.lifecycle.find(202, 42).levels, (1, 2))
        self.assertFalse(any(command.startswith(('DBADD', 'PROJECT '))
                             for command in self.client.commands))

    def test_graph_capacity_owner_order_and_unmerged_contracts_fail_closed(self):
        partial = (*capacity_operations(),
                   op('add-groups', 2, groups=[64]))
        with self.assertRaisesRegex(ValueError, 'partial scene graphs'):
            self.offline((scene_manager(*partial), measurement()))
        with self.assertRaisesRegex(EdltError, 'only one scene-manager'):
            self.offline((scene_manager(op('get-trigger')),
                          scene_manager(op('get-action'))))
        with self.assertRaisesRegex(EdltError,
                                    'must precede every scene widget'):
            self.offline((
                {'op': 'scene', 'page': 1, 'position': 1, 'scene': 1},
                scene_manager(op('get-trigger')),
            ))
        with self.assertRaisesRegex(ValueError,
                                    'separate cache/raw contract.*applications'):
            self.offline((
                {'op': 'applications', 'edits': []},
                scene_manager(op('get-trigger')),
            ))
        self.assertFalse(any(command.startswith(('DBADD', 'PROJECT ', 'PP '))
                             for command in self.client.commands))

    def test_stale_ambiguous_and_image_dependent_sources_fail_closed(self):
        stale = dict(self.values)
        stale['PrimaryApplication'] = (57,)
        with self.assertRaisesRegex(ValueError, 'PP snapshot differs'):
            plan_native_parent_metadata(
                self.client.xml(), '//TEST/254/p/20', stale,
                self.editor, parent_operations())

        xml = self.client.xml()
        application = ('<Application>' + xml.split('<Application>', 1)[1]
                       .split('</Application>', 1)[0] + '</Application>')
        with self.assertRaisesRegex(ValueError, 'unique addresses'):
            plan_native_parent_metadata(
                xml.replace('</Application>',
                            '</Application>' + application, 1),
                '//TEST/254/p/20', self.values,
                self.editor, parent_operations())

        self.client.applications[202]['groups'][42]['level_tags'][1] = (
            {'variant': 0, 'type': 'ICON', 'value': '17'},)
        with self.assertRaisesRegex(ValueError,
                                    'image metadata is not derivable'):
            self.offline()

    def test_native_apply_creates_once_stages_once_and_verifies_reload(self):
        self.remove_scene_and_lighting_metadata()
        manager, _session = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=parent_operations(),
            exclusive_project=True)
        result = manager.apply(plan, backup_project='PSBACKUP').as_dict()
        self.assertTrue(result['saved'] and result['persistence_verified'])
        self.assertTrue(result['pp_readback_verified'])
        self.assertEqual(
            [(row['kind'], row['address'], row.get('group'))
             for row in result['objects']],
            [('Application', 202, None), ('Group', 12, None),
             ('Group', 42, None), ('Level', 1, 42), ('Level', 2, 42)])
        self.assertTrue(all(row['created'] for row in result['objects']))
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 2)
        self.assertLess(self.client.commands.index('PROJECT COPY TEST PSBACKUP'),
                        self.client.commands.index(
                            'DBADDSAFE //TEST/254 Application 202 Trigger Control'))
        self.assertFalse(result['physical_device_programmed'])
        self.assertFalse(result['full_scene_manager_control_binding_verified'])

    def test_pre_save_rollback_and_lost_save_uncertainty_do_not_retry(self):
        self.remove_scene_and_lighting_metadata()
        manager, session = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=parent_operations(),
            exclusive_project=True)
        session.failure = 'SceneBucket'
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(plan, backup_project='PSBACKUP')
        evidence = caught.exception.details['edlt_parent_metadata_evidence']
        self.assertTrue(evidence['rollback_attempted'])
        self.assertTrue(evidence['rollback_verified'])
        self.assertFalse(evidence['pp_save_attempted'])
        self.assertNotIn(202, self.client.applications)
        self.assertNotIn(12, self.client.applications[56]['groups'])

        self.setUp()
        self.remove_scene_and_lighting_metadata()
        manager, session = self.manager()
        plan = manager.plan(
            '//TEST/254/p/20', operations=parent_operations(),
            exclusive_project=True)
        session.save_error = RuntimeError('PP SAVE reply lost')
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(plan, backup_project='PSBACKUP')
        evidence = caught.exception.details['edlt_parent_metadata_evidence']
        self.assertTrue(evidence['pp_save_attempted'])
        self.assertFalse(evidence['pp_save_confirmed'])
        self.assertTrue(evidence['database_state_uncertain'])
        self.assertFalse(evidence['rollback_attempted'])
        self.assertEqual(evidence['automatic_retries'], 0)
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertFalse(any(command.startswith('DBDELETE')
                             for command in self.client.commands))

    @unittest.skipUnless(
        os.environ.get('CBUS_EDLT_PARENT_SCENE_METADATA_ACCEPTANCE') == '1'
        and os.environ.get('CBUS_EDLT_PARENT_METADATA_UNIT')
        and os.environ.get('CBUS_EDLT_PARENT_METADATA_BACKUP')
        and os.environ.get('CBUS_CGATE_TEST_HOST')
        and os.environ.get('CBUS_UNITSPEC_DIR'),
        'Set the explicit disposable parent SceneManager acceptance environment')
    def test_optional_native_parent_scene_metadata_transaction(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.unitspec import UnitSpecStore

        editor = EdltParentTransaction(
            UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml'))
        rows = (scene_manager(op('get-trigger')),
                {'op': 'general', 'long_press_ms': 500})
        host = os.environ['CBUS_CGATE_TEST_HOST']
        port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        with CGateClient(host, port, timeout=30) as client:
            manager = NativeEdltParentTransaction(client, editor)
            plan = manager.plan(
                os.environ['CBUS_EDLT_PARENT_METADATA_UNIT'],
                operations=rows, exclusive_project=True)
            result = manager.apply(
                plan, backup_project=os.environ[
                    'CBUS_EDLT_PARENT_METADATA_BACKUP']).as_dict()
        self.assertTrue(result['persistence_verified'])
        self.assertTrue(result['pp_save_confirmed'])
        self.assertFalse(result['physical_device_programmed'])


class ParentSceneMetadataCLITests(unittest.TestCase):
    def setUp(self):
        self.case = ParentSceneMetadataTests('runTest')
        self.case.setUp()
        self.editor = self.case.editor
        self.client = self.case.client

    def invoke(self, arguments, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, stdout.getvalue() + stderr.getvalue())
        return json.loads(stdout.getvalue() or stderr.getvalue())

    def files(self, root):
        values = Path(root) / 'values.json'
        project = Path(root) / 'project.xml'
        rows = Path(root) / 'operations.json'
        values.write_text(json.dumps(self.case.values), encoding='utf-8')
        project.write_text(self.client.xml(), encoding='utf-8')
        rows.write_text(json.dumps(parent_operations()), encoding='utf-8')
        return values, project, rows

    def test_offline_and_native_cli_use_the_combined_scene_parent_manager(self):
        self.case.remove_scene_and_lighting_metadata()
        with tempfile.TemporaryDirectory() as root:
            values, project, rows = self.files(root)
            with patch.object(cli, '_edlt_parent_transaction',
                              return_value=self.editor), patch(
                    'cbus_toolkit.cgate.CGateClient',
                    side_effect=AssertionError('offline plan connected')):
                preview = self.invoke([
                    'edlt', 'parent-transaction-plan', values,
                    '--project-xml', project, '--unit', '//TEST/254/p/20',
                    '--operations', rows,
                ])
            self.assertEqual(preview['automatic_scene_metadata']['format'],
                             'cbus-native-edlt-scene-cache-v3')
            self.assertEqual(len(preview['planned_creations']), 5)

            session = NativeSession(self.case.spec, self.client)
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(self.client)), patch.object(
                    cli, '_edlt_parent_transaction',
                    return_value=self.editor), patch(
                    'cbus_toolkit.edlt_parent_metadata.Programmer',
                    return_value=FakeProgrammer(session)):
                result = self.invoke([
                    'cgate', 'unit', '--lock-address', '//TEST/254',
                    '--source', '/db//TEST/254/p/20',
                    'edlt-parent-transaction', '--auto-metadata',
                    '--exclusive-project', '--backup-project', 'PSBACKUP',
                    '--operations', rows,
                ])
            self.assertTrue(result['saved'] and result['persistence_verified'])
            self.assertEqual(self.client.commands.count('PP SAVE'), 1)


if __name__ == '__main__':
    unittest.main()
