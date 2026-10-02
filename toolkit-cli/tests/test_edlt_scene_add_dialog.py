"""Source-pinned accepted/cancelled SceneManager Add dialog composition."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_add_dialog import normalize, resolve
from cbus_toolkit.edlt_scene_metadata import NativeSceneMetadataError, NativeSceneMetadataTransaction
from cbus_toolkit.edlt_parent_metadata import NativeEdltParentTransaction
from tests import test_edlt_scene_metadata as scene_support
from tests import test_edlt_parent_scene_metadata as parent_support
from tests.test_edlt_parent_metadata import FakeProgrammer, NativeSession
from tests.test_edlt_parent_transaction import measurement
from tests.test_edlt_parent_scene_manager import scene_manager

VECTOR = Path(__file__).resolve().parents[2] / 'rust/testdata/vectors/edlt_scene_add_dialog.json'


def add_project_tag(client):
    original = client.xml
    client.dialog_project_tag = 'Scene Project'
    def xml():
        text = original()
        tag = client.dialog_project_tag
        field = '' if tag is None else '<TagName>' + escape(tag) + '</TagName>'
        return text.replace('<Project><Address>TEST</Address>',
                            '<Project><Address>TEST</Address>' + field, 1)
    client.xml = xml


class DialogRulesTests(unittest.TestCase):
    def test_exact_vector(self):
        data = json.loads(VECTOR.read_text())
        for row in data['rules']:
            with self.subTest(row['id']):
                existing = ({n: f'Owned {n}' for n in range(255)} if row['existing'] == '0..254'
                            else {int(k): v for k, v in row['existing'].items()})
                call = lambda: resolve(row['operation'], existing, 'TEST', group=42)
                if 'error' in row:
                    with self.assertRaisesRegex(EdltError, row['error']): call()
                else:
                    result = call()
                    for key, value in row['expected'].items():
                        self.assertEqual(result[key], value, key)

    def test_shape_is_strict_and_all_scenes_admitted(self):
        for kind in ('add-trigger-dialog', 'add-action-dialog'):
            for scene in range(1, 9):
                self.assertEqual(normalize({'op': kind, 'scene': scene})['scene'], scene)
        for changes in ({'scene': True}, {'scene': 0}, {'address': 255}, {'address': True},
                        {'cancel': 1}, {'name': 42}, {'unknown': 1}):
            with self.subTest(changes), self.assertRaises(EdltError):
                normalize({'op': 'add-action-dialog', 'scene': 1, **changes})


class SceneDialogTests(unittest.TestCase):
    def setUp(self):
        scene_support.SceneMetadataTests.setUp(self)
        add_project_tag(self.client)
    plan = scene_support.SceneMetadataTests.plan

    def manager(self, *, failure=None, save_error=None):
        session = NativeSession(self.spec, self.client)
        session.failure, session.save_error = failure, save_error
        return NativeSceneMetadataTransaction(self.client, self.editor,
                   programmer=FakeProgrammer(session)), session

    def test_group_then_action_creates_native_dialog_names_and_binds_graph(self):
        rows = ({'op': 'add-trigger-dialog', 'scene': 1},
                {'op': 'add-action-dialog', 'scene': 1})
        before = self.client.xml()
        plan = self.plan(rows)
        self.assertEqual(self.client.xml(), before)
        self.assertEqual([(r.as_dict()['kind'], r.address, r.name) for r in plan.resolved.creations],
                         [('Group', 70, 'Trigger Group 70'), ('Level', 0, 'Level 0')])
        self.assertEqual(plan.resolved.requested_operations, rows)
        self.assertEqual(plan.resolved.operations, (
            {'op': 'set-trigger', 'scene': 1, 'group': 70},
            {'op': 'set-action', 'scene': 1, 'action': 0}))
        first = plan.scene_plan.terminal.scenes[0]
        self.assertEqual((first.raw_trigger, first.raw_action), (70, 0))
        self.assertEqual(plan.scene_plan.terminal.scenes[1].raw_trigger, 42)
        self.assertEqual(plan.resolved.cache.labels(70, 0)[0].name, '')

    def test_creation_and_ordered_list_follow_dialog_history_not_address_sort(self):
        rows = ({'op': 'add-trigger-dialog', 'scene': 1, 'address': 90},
                {'op': 'add-trigger-dialog', 'scene': 2, 'address': 80},
                {'op': 'add-action-dialog', 'scene': 1, 'address': 9},
                {'op': 'add-action-dialog', 'scene': 1, 'address': 3, 'name': 'Third'})
        plan = self.plan(rows)
        self.assertEqual([(r.address, r.name) for r in plan.resolved.creations[:2]],
                         [(90, 'Trigger Group 90'), (80, 'Trigger Group 80')])
        self.assertEqual([r.address for r in plan.resolved.cache.application_cache.find_group_list(202).groups if r.address != 255][-2:], [90, 80])
        self.assertEqual([(r.group, r.address, r.name) for r in plan.resolved.creations[2:4]],
                         [(90, 9, 'Level 0'), (90, 3, 'Third')])
        # Changing the action address preserves a non-default-looking Level seed;
        # the next dialog sees9 occupied and requires an explicit distinct name.
        self.assertEqual([json.loads(r)['first_free_address'] for r in plan.resolved.add_dialogs], [70, 70, 0, 0])

    def test_repeated_seed_name_conflict_is_atomic_and_previous_plan_is_unchanged(self):
        rows = ({'op': 'add-trigger-dialog', 'scene': 1},
                {'op': 'add-action-dialog', 'scene': 1, 'address': 9},
                {'op': 'add-action-dialog', 'scene': 1})
        before = self.client.xml()
        with self.assertRaisesRegex(EdltError, '2212'): self.plan(rows)
        self.assertEqual(self.client.xml(), before)
        self.assertFalse(any(c.startswith(('DBADD', 'PROJECT ')) for c in self.client.commands))

    def test_preceding_getter_creation_and_cancelled_seed_affect_allocator_correctly(self):
        rows = ({'op': 'set-action', 'scene': 1, 'action': 8},
                {'op': 'add-action-dialog', 'scene': 1, 'cancel': True, 'name': ''},
                {'op': 'add-action-dialog', 'scene': 1})
        plan = self.plan(rows)
        self.assertEqual([(r.address, r.name) for r in plan.resolved.creations],
                         [(8, 'Action Selector 8'), (9, 'Level 9')])
        dialogs = [json.loads(r) for r in plan.resolved.add_dialogs]
        self.assertEqual([r['first_free_address'] for r in dialogs], [9, 9])
        self.assertEqual(dialogs[0]['outcome'], 'cancelled')
        self.assertNotIn('address', dialogs[0])
        self.assertEqual(plan.scene_plan.terminal.scenes[0].raw_action, 9)

    def test_cancel_retains_bindings_and_has_no_dialog_creation(self):
        plan = self.plan(({'op': 'add-trigger-dialog', 'scene': 1, 'cancel': True},
                          {'op': 'add-action-dialog', 'scene': 1, 'cancel': True}))
        self.assertEqual(plan.resolved.creations, ())
        self.assertEqual(plan.resolved.operations, ())
        self.assertEqual(len(plan.resolved.add_dialogs), 2)
        self.assertEqual((plan.scene_plan.terminal.scenes[0].raw_trigger,
                          plan.scene_plan.terminal.scenes[0].raw_action), (42, 1))

    def test_action_without_trigger_and_transport_unsafe_names_refuse_atomically(self):
        for rows, error in ((({'op': 'add-action-dialog', 'scene': 3},), 'non-255'),
                            (({'op': 'add-trigger-dialog', 'scene': 1, 'name': 'a\nb'},), 'without controls'),
                            (({'op': 'add-action-dialog', 'scene': 1, 'name': '\udfff'},), 'surrogates')):
            before = self.client.xml()
            with self.subTest(rows), self.assertRaisesRegex((EdltError, ValueError), error): self.plan(rows)
            self.assertEqual(self.client.xml(), before)
            self.assertFalse(any(c.startswith(('DBADD', 'PROJECT ')) for c in self.client.commands))

    def test_dialog_uses_exact_project_tag_name_and_requires_its_scalar(self):
        cases = json.loads(VECTOR.read_text())['project_name_guard']
        self.assertEqual(cases['project_tag_name'], self.client.dialog_project_tag)
        for kind, code in (('add-trigger-dialog', cases['same_tag_trigger_error']),
                           ('add-action-dialog', cases['same_tag_action_error'])):
            with self.subTest(kind), self.assertRaisesRegex(EdltError, code):
                self.plan(({'op': kind, 'scene': 1, 'name': cases['project_tag_name']},))
            plan = self.plan(({'op': kind, 'scene': 1, 'name': cases['project_address']},))
            self.assertEqual(plan.resolved.creations[0].name, cases['project_address'])
        for cancel in (False, True):
            self.client.dialog_project_tag = None
            with self.subTest(cancel), self.assertRaisesRegex(ValueError, 'TagName'):
                self.plan(({'op': 'add-trigger-dialog', 'scene': 1, 'cancel': cancel},))
        self.assertFalse(any(c.startswith(('DBADD', 'DBSET', 'PROJECT ')) for c in self.client.commands))

    def test_dialog_transport_name_refusal_precedes_native_backup(self):
        for kind in ('add-trigger-dialog', 'add-action-dialog'):
            for row in json.loads(VECTOR.read_text())['software_transport_cases']:
                if row.get('accepted'): continue
                name, message = row['name'], row['error']
                manager, _session = self.manager()
                before = self.client.xml()
                with self.subTest(kind=kind, name=name), self.assertRaisesRegex(NativeSceneMetadataError, message):
                    manager.plan('/db//TEST/254/p/20',
                                 operations=({'op': kind, 'scene': 1, 'name': name},),
                                 exclusive_project=True)
                self.assertEqual(self.client.xml(), before)
                self.assertFalse(any(c.startswith(('DBADD', 'DBSET', 'PROJECT SAVE', 'PROJECT COPY'))
                                     for c in self.client.commands))
        name = next(row['name'] for row in json.loads(VECTOR.read_text())['software_transport_cases'] if row.get('accepted'))
        accepted = self.plan(({'op': 'add-action-dialog', 'scene': 1, 'name': name},))
        self.assertEqual(accepted.resolved.creations[0].name, name)

    def test_accept_apply_preserves_all_old_metadata_and_reopens_once(self):
        manager, session = self.manager()
        rows = ({'op': 'add-trigger-dialog', 'scene': 1, 'name': ' Evening '},
                {'op': 'add-action-dialog', 'scene': 1, 'name': ' Off '})
        before = deepcopy(self.client.applications)
        plan = manager.plan('/db//TEST/254/p/20', operations=rows, exclusive_project=True)
        result = manager.apply(plan, backup_project='SCBACKUP').as_dict()
        self.assertTrue(result['persistence_verified'] and result['existing_metadata_preserved'])
        retained = deepcopy(self.client.applications)
        created = retained[202]['groups'].pop(70)
        self.assertEqual(retained, before)
        self.assertEqual((created['tag'], created['level_names'][0], created['level_values'][0]), ('Evening', 'Off', 0))
        self.assertEqual(sum(c == 'PP SAVE' for c in self.client.commands), 1)
        self.assertEqual(sum(c == 'PROJECT SAVE TEST' for c in self.client.commands), 2)
        self.assertEqual(sum(c == 'PROJECT CLOSE TEST' for c in self.client.commands), 1)
        self.assertEqual(sum(c == 'PROJECT LOAD TEST' for c in self.client.commands), 1)
        self.assertEqual(len(result['objects']), 2)

    def test_stale_allocator_refuses_before_backup_or_mutation(self):
        manager, _ = self.manager()
        plan = manager.plan('/db//TEST/254/p/20', operations=({'op': 'add-trigger-dialog', 'scene': 1},), exclusive_project=True)
        self.client.applications[202]['groups'][70] = deepcopy(self.client.applications[202]['groups'][69])
        self.client.applications[202]['groups'][70]['oid'] = '00000000-0000-0000-0000-000000009999'
        with self.assertRaisesRegex(NativeSceneMetadataError, 'changed since planning'): manager.apply(plan)
        self.assertFalse(any(c.startswith(('DBADD', 'PROJECT SAVE', 'PROJECT COPY')) for c in self.client.commands))

    def test_pre_save_failure_rolls_back_known_dialog_objects_in_reverse(self):
        manager, session = self.manager()
        before = deepcopy(self.client.applications)
        plan = manager.plan('/db//TEST/254/p/20', operations=(
            {'op': 'add-trigger-dialog', 'scene': 1}, {'op': 'add-action-dialog', 'scene': 1}), exclusive_project=True)
        session.failure = next(iter(plan.scene_plan.changes))
        with self.assertRaises(NativeSceneMetadataError): manager.apply(plan, backup_project='SCBACKUP')
        result = manager.last_result.as_dict()
        self.assertTrue(result['rollback_verified'])
        self.assertFalse(result['pp_save_attempted'])
        self.assertEqual(self.client.applications, before)
        self.assertEqual([c for c in self.client.commands if c.startswith('DBDELETE !')],
                         ['DBDELETE !' + r['oid'] for r in reversed(result['objects'])])

    def test_lost_pp_save_is_uncertain_and_never_replayed_or_rolled_back(self):
        manager, _ = self.manager(save_error=ConnectionError('lost save reply'))
        plan = manager.plan('/db//TEST/254/p/20', operations=(
            {'op': 'add-trigger-dialog', 'scene': 1}, {'op': 'add-action-dialog', 'scene': 1}), exclusive_project=True)
        with self.assertRaises(NativeSceneMetadataError): manager.apply(plan, backup_project='SCBACKUP')
        result = manager.last_result.as_dict()
        self.assertTrue(result['pp_save_attempted'])
        self.assertFalse(result['rollback_attempted'])
        self.assertTrue(result['database_state_uncertain'])
        self.assertEqual(sum(c == 'PP SAVE' for c in self.client.commands), 1)
        with self.assertRaisesRegex(NativeSceneMetadataError, 'already had an apply'): manager.apply(plan)
        self.assertEqual(sum(c == 'PP SAVE' for c in self.client.commands), 1)


class ParentDialogTests(unittest.TestCase):
    def setUp(self):
        parent_support.ParentSceneMetadataTests.setUp(self)
        add_project_tag(self.client)
    offline = parent_support.ParentSceneMetadataTests.offline
    manager = parent_support.ParentSceneMetadataTests.manager

    def test_parent_plan_and_apply_share_one_save_and_preserve_graph(self):
        rows = (scene_manager({'op': 'add-trigger-dialog', 'scene': 1},
                              {'op': 'add-action-dialog', 'scene': 1}), measurement())
        plan = self.offline(rows)
        self.assertEqual(json.loads(json.dumps(plan.operations)), json.loads(json.dumps(rows)))
        self.assertEqual(plan.resolved_operations[0]['operations'][0]['op'], 'set-trigger')
        self.assertEqual(plan.parent_plan.as_dict()['execution_counts']['terminal_crc_passes'], 1)
        manager, session = self.manager()
        issued = manager.plan('/db//TEST/254/p/20', operations=rows, exclusive_project=True)
        result = manager.apply(issued, backup_project='SCBACKUP').as_dict()
        self.assertTrue(result['persistence_verified'])
        self.assertEqual(result['metadata_objects_created'], 2)


class DialogCLITests(unittest.TestCase):
    def test_offline_public_dialog_tag_name_and_transport_refusals(self):
        setup = SceneDialogTests(); setup.setUp()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            values, project, ops = [root / n for n in ('values.json', 'project.xml', 'ops.json')]
            values.write_text(json.dumps(setup.values)); project.write_text(setup.client.xml())
            common = ('edlt', 'scene-manager-plan', values, '--operations', ops,
                      '--project-xml', project, '--unit', '//TEST/254/p/20')
            with patch('cbus_toolkit.edlt_scene_manager_cli.editor', return_value=setup.editor), patch(
                    'cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('offline connected')):
                for name, message in (('Scene Project', '2213'), ('bad#name', 'containing #'),
                                      ('two  spaces', 'whitespace'), ('non\u00a0ascii', 'whitespace')):
                    ops.write_text(json.dumps([{'op': 'add-action-dialog', 'scene': 1, 'name': name}]))
                    err = io.StringIO()
                    with redirect_stderr(err): status = cli.main(list(map(str, common)))
                    self.assertNotEqual(status, 0)
                    self.assertIn(message, err.getvalue())
                ops.write_text(json.dumps([{'op': 'add-action-dialog', 'scene': 1, 'name': 'TEST'}]))
                out = io.StringIO()
                with redirect_stdout(out): status = cli.main(list(map(str, common)))
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(out.getvalue())['planned_creations'][0]['name'], 'TEST')

    def test_offline_public_plan_state_and_manual_refusal(self):
        setup = SceneDialogTests(); setup.setUp()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            values, project, ops, metadata = [root / n for n in ('values.json', 'project.xml', 'ops.json', 'metadata.json')]
            values.write_text(json.dumps(setup.values)); project.write_text(setup.client.xml())
            ops.write_text(json.dumps([{'op': 'add-trigger-dialog', 'scene': 1}, {'op': 'add-action-dialog', 'scene': 1}]))
            metadata.write_text(json.dumps(setup.plan(()).resolved.cache.as_dict()))
            common = (values, '--operations', ops)
            with patch('cbus_toolkit.edlt_scene_manager_cli.editor', return_value=setup.editor), patch(
                    'cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('offline connected')):
                for command in ('scene-manager-plan', 'scene-manager-state'):
                    out = io.StringIO()
                    with redirect_stdout(out):
                        status = cli.main(list(map(str, ('edlt', command, *common, '--project-xml', project, '--unit', '//TEST/254/p/20'))))
                    self.assertEqual(status, 0)
                    self.assertEqual(len(json.loads(out.getvalue())['automatic_metadata']['add_dialogs']), 2)
                err = io.StringIO()
                with redirect_stderr(err):
                    status = cli.main(list(map(str, ('edlt', 'scene-manager-plan', *common, '--metadata', metadata))))
                self.assertNotEqual(status, 0)
                self.assertIn('automatic', err.getvalue())
