"""Automatic project metadata for retained eDLT Scene Manager edits."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_scene_manager_cli import SceneCLIEditor
from cbus_toolkit.edlt_scene_metadata import (
    NativeSceneMetadataError, NativeSceneMetadataTransaction,
    plan_native_scene_metadata, resolve_native_scene_metadata,
)
from tests.test_edlt_parent_metadata import (
    FakeProgrammer, MetadataClient, NativeSession, oid, response,
)
from tests.test_edlt_scene_manager import cache as scene_cache, operations, vectors
from tests.test_edlt_lifecycle import fixture


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/edlt-scene-metadata-evidence.json'
ACCEPTANCE = ROOT / 'research/fixtures/edlt-scene-metadata-acceptance.json'


def applications():
    result = {}
    for application in (56, 57, 172, 202, 203):
        groups = {}
        for group in (*range(70), 254):
            groups[group] = {
                'oid': oid(100000 + application * 300 + group),
                'tag': f'Owned {application}/{group}',
                'levels': (0, 1, 2, 3, 4, 5, 6, 7, 42, 254, 255)
                if application == 202 and group == 42 else (),
                'tags': ({'variant': 0, 'type': 'TEXT',
                          'value': f'Group {application}/{group}'},),
            }
            if application == 202 and group == 42:
                groups[group]['level_tags'] = {
                    level: tuple({'variant': variant, 'type': 'TEXT',
                                  'value': f'Owned action {level}'}
                                 for variant in range(4))
                    for level in groups[group]['levels']
                }
        result[application] = {
            'oid': oid(50000 + application),
            'tag': f'Owned application {application}',
            'groups': groups,
        }
    return result


class SceneMetadataClient(MetadataClient):
    def __init__(self, spec):
        super().__init__(spec, applications=applications())


class SceneMetadataTests(unittest.TestCase):
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
        self.values = self.editor.snapshot(self.client.values)

    def plan(self, rows=None):
        return plan_native_scene_metadata(
            self.client.xml(), '//TEST/254/p/20', self.values,
            self.editor, operations('sync') if rows is None else rows)

    def test_resolves_complete_lists_trigger_actions_and_retained_plan(self):
        plan = self.plan()
        document = plan.as_dict()
        self.assertEqual(document['format'],
                         'cbus-native-edlt-scene-metadata-plan-v2')
        self.assertEqual(document['automatic_metadata']
                         ['metadata_provenance'],
                         'one-admitted-native-project-xml-snapshot')
        pairs = document['automatic_metadata']['consumed_trigger_actions']
        self.assertEqual(pairs, [
            {'group': 42, 'action': 1},
            {'group': 42, 'action': 2},
        ])
        cache = plan.resolved.cache
        self.assertTrue(cache.application_cache.applications_complete)
        self.assertTrue(cache.application_cache.find_group_list(56).complete)
        self.assertEqual(
            cache.application_cache.lifecycle.find(202, 42).levels,
            (0, 1, 2, 3, 4, 5, 6, 7, 42, 254, 255))
        self.assertEqual(cache.labels(42, 1)[0].as_dict(), {
            'value': '0', 'name': 'Owned action 1',
            'image_present': False})
        self.assertTrue(document['scene_manager']['changes'])
        self.assertFalse(document['metadata_mutation_planned'])
        self.assertFalse(document['full_scene_manager_control_binding_verified'])

    def test_all_retained_operation_families_match_the_manual_cache_plan(self):
        names = (
            'baseline', 'add-remove', 'cross-application', 'copy-paste',
            'clear-items', 'clear-scene', 'level-percent', 'ramp', 'sync',
            'validate-valid', 'validate-trigger-duplicate',
            'validate-name-duplicate', 'validate-missing-trigger',
            'validate-missing-name',
            'validate-all-four', 'validate-shortcut-first',
            'validate-shortcut-second', 'validate-empty-duplicates',
            'validate-action255',
            'validate-all-empty', 'get-new-missing-trigger',
            'get-set-action-valid',
            'get-disabled-trigger',
        )
        for name in names:
            with self.subTest(name=name):
                rows = operations(name)
                automatic = self.plan(rows).scene_plan
                manual = self.editor.plan(
                    self.values, metadata=scene_cache(), operations=rows)
                self.assertEqual(dict(automatic.changes), dict(manual.changes))
                self.assertEqual(automatic.terminal.as_dict(),
                                 manual.terminal.as_dict())
                self.assertEqual(automatic.validation, manual.validation)

    def test_get_trigger_does_not_normalize_action_before_later_group_change(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'get-trigger', 'scene': 1},
            {'op': 'set-trigger', 'scene': 1, 'group': 42},
        )
        automatic = self.plan(rows).scene_plan
        manual = self.editor.plan(
            self.values, metadata=scene_cache(), operations=rows)
        self.assertEqual(automatic.terminal.scenes[0].raw_action, 1)
        self.assertEqual(dict(automatic.changes), dict(manual.changes))
        self.assertEqual(automatic.terminal.as_dict(),
                         manual.terminal.as_dict())

    def test_absent_trigger_action_access_preserves_raw_action_for_new_group(self):
        trigger = self.client.applications[202]['groups'][44]
        trigger['levels'] = (0, 1)
        trigger['level_tags'] = {
            level: tuple({'variant': variant, 'type': 'TEXT',
                          'value': f'Group 44 action {level}'}
                         for variant in range(4))
            for level in trigger['levels']
        }
        for kind in ('set-action', 'get-action'):
            with self.subTest(kind=kind):
                action = ({'op': kind, 'scene': 1, 'action': 2}
                          if kind == 'set-action'
                          else {'op': kind, 'scene': 1})
                rows = (
                    {'op': 'set-trigger', 'scene': 1, 'group': 200},
                    action,
                    {'op': 'set-trigger', 'scene': 1, 'group': 44},
                    {'op': 'get-action', 'scene': 1},
                )
                plan = self.plan(rows)
                self.assertEqual(plan.scene_plan.terminal.scenes[0].raw_action,
                                 1)
                self.assertIn((44, 1), plan.resolved.action_pairs)
                self.assertNotIn((44, 0), plan.resolved.action_pairs)

    def test_stale_ambiguous_and_image_dependent_sources_fail_closed(self):
        stale = dict(self.values)
        stale['PrimaryApplication'] = (57,)
        with self.assertRaisesRegex(ValueError, 'PP snapshot differs'):
            plan_native_scene_metadata(
                self.client.xml(), '//TEST/254/p/20', stale,
                self.editor, operations('sync'))

        xml = self.client.xml()
        first = ('<Application>' + xml.split('<Application>', 1)[1]
                 .split('</Application>', 1)[0] + '</Application>')
        duplicate = xml.replace('</Application>',
                                '</Application>' + first, 1)
        with self.assertRaisesRegex(ValueError, 'unique addresses'):
            resolve_native_scene_metadata(
                duplicate, '//TEST/254/p/20', self.values,
                self.editor.engine, operations('sync'))

        image = deepcopy(self.client.applications)
        image[202]['groups'][42]['level_tags'] = {
            1: ({'variant': 0, 'type': 'ICON', 'value': '17'},),
        }
        client = SceneMetadataClient(self.spec)
        client.applications = image
        client.values = deepcopy(self.client.values)
        with self.assertRaisesRegex(ValueError,
                                    'image metadata is not derivable'):
            resolve_native_scene_metadata(
                client.xml(), '//TEST/254/p/20', self.values,
                self.editor.engine, operations('sync'))

    def test_missing_requested_action_is_projected_with_native_defaults(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
            {'op': 'get-action', 'scene': 1},
        )
        plan = self.plan(rows)
        result = plan.scene_plan.source.as_dict()
        self.assertEqual(result['scenes'][0]['raw_trigger'], 43)
        self.assertEqual(result['scenes'][0]['raw_action'], 2)
        document = plan.as_dict()
        self.assertFalse(document['automatic_metadata']
                         ['missing_objects_auto_created'])
        self.assertTrue(document['automatic_metadata']
                        ['missing_objects_projected_for_creation'])
        self.assertTrue(document['metadata_mutation_planned'])
        self.assertEqual(document['planned_creations'], [{
            'kind': 'Level', 'application': 202, 'group': 43,
            'address': 2, 'value': 2, 'name': 'Action Selector 2',
            'default_dynamic_labels': [
                {'value': str(index), 'name': '', 'image_present': False}
                for index in range(4)],
            'reasons': ['operation 2 set-action'],
        }])
        self.assertEqual(
            plan.resolved.cache.application_cache.lifecycle.find(
                202, 43).levels, (2,))
        self.assertEqual(
            [row.as_dict() for row in plan.resolved.cache.labels(43, 2)],
            [{'value': str(index), 'name': '', 'image_present': False}
             for index in range(4)])
        self.assertFalse(any(command.startswith('DBADD')
                             for command in self.client.commands))

    def test_native_apply_verifies_persistence_and_metadata_preservation(self):
        session = NativeSession(self.spec, self.client)
        manager = NativeSceneMetadataTransaction(
            self.client, self.editor,
            programmer=FakeProgrammer(session))
        plan = manager.plan(
            '/db//TEST/254/p/20', operations=operations('sync'),
            validate=True, exclusive_project=True)
        before = deepcopy(self.client.applications)
        result = manager.apply(plan).as_dict()
        self.assertTrue(result['saved'])
        self.assertTrue(result['persistence_verified'])
        self.assertTrue(result['existing_metadata_preserved'])
        self.assertFalse(result['backup_created'])
        self.assertFalse(result['target_project_save_attempted'])
        self.assertEqual(self.client.applications, before)
        self.assertFalse(any(command.startswith(('DBADD', 'DBDELETE'))
                             for command in self.client.commands))
        self.assertFalse(any(command.startswith('PROJECT ')
                             for command in self.client.commands))

    def test_native_missing_action_backup_create_save_reload_and_preserve(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
        )
        session = NativeSession(self.spec, self.client)
        manager = NativeSceneMetadataTransaction(
            self.client, self.editor,
            programmer=FakeProgrammer(session))
        plan = manager.plan(
            '/db//TEST/254/p/20', operations=rows,
            exclusive_project=True)
        before = deepcopy(self.client.applications)
        result = manager.apply(
            plan, backup_project='SCBACKUP').as_dict()
        self.assertTrue(result['saved'] and result['persistence_verified'])
        self.assertTrue(result['backup_created'])
        self.assertTrue(result['pp_save_confirmed'])
        self.assertTrue(result['target_project_save_confirmed'])
        self.assertEqual(result['database_persistence'],
                         'verified-after-project-reload')
        self.assertEqual(len(result['objects']), 1)
        created = result['objects'][0]
        self.assertEqual((created['group'], created['address'],
                          created['value'], created['name']),
                         (43, 2, 2, 'Action Selector 2'))
        group = self.client.applications[202]['groups'][43]
        self.assertIn(2, group['levels'])
        self.assertEqual(group['level_names'][2], 'Action Selector 2')
        self.assertEqual(group['level_values'][2], 2)
        retained = deepcopy(self.client.applications)
        for mapping in ('level_oids', 'level_names', 'level_values'):
            retained[202]['groups'][43].pop(mapping, None)
        retained[202]['groups'][43]['levels'] = ()
        self.assertEqual(retained, before)
        add = ('DBADDSAFE //TEST/254/202/43 Level 2 '
               'Action Selector 2')
        self.assertIn(add, self.client.commands)
        self.assertLess(self.client.commands.index('PROJECT COPY TEST SCBACKUP'),
                        self.client.commands.index(add))
        self.assertLess(self.client.commands.index(add),
                        self.client.commands.index('PP SAVE'))
        self.assertEqual(sum(command == 'PROJECT SAVE TEST'
                             for command in self.client.commands), 2)

    def test_creation_conflict_and_pre_save_failure_restore_original(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
        )
        original = deepcopy(self.client.applications)
        manager = NativeSceneMetadataTransaction(
            self.client, self.editor,
            programmer=FakeProgrammer(NativeSession(
                self.spec, self.client)))
        plan = manager.plan('/db//TEST/254/p/20', operations=rows,
                            exclusive_project=True)
        self.client.failure = lambda command: (
            response(401, 'Level capacity or address conflict')
            if command.startswith('DBADDSAFE ') else None)
        with self.assertRaisesRegex(NativeSceneMetadataError,
                                    'capacity or address conflict'):
            manager.apply(plan, backup_project='SCBACKUP')
        evidence = manager.last_result.as_dict()
        self.assertTrue(evidence['rollback_attempted'])
        self.assertTrue(evidence['rollback_verified'])
        self.assertFalse(evidence['pp_save_attempted'])
        self.assertFalse(evidence['database_state_uncertain'])
        self.assertEqual(self.client.applications, original)

        client = SceneMetadataClient(self.spec)
        client.values = deepcopy(self.client.saved_values)
        editor = SceneCLIEditor(self.spec)
        session = NativeSession(self.spec, client)
        manager = NativeSceneMetadataTransaction(
            client, editor, programmer=FakeProgrammer(session))
        plan = manager.plan('/db//TEST/254/p/20', operations=rows,
                            exclusive_project=True)
        session.failure = next(iter(plan.scene_plan.changes))
        with self.assertRaises(NativeSceneMetadataError):
            manager.apply(plan, backup_project='SCBACKUP')
        evidence = manager.last_result.as_dict()
        self.assertTrue(evidence['rollback_attempted'])
        self.assertTrue(evidence['rollback_verified'])
        self.assertFalse(evidence['pp_save_attempted'])
        self.assertNotIn(2, client.applications[202]['groups'][43]['levels'])

    def test_ambiguous_add_receipt_discards_unsaved_unknown_object(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
        )
        original = deepcopy(self.client.applications)
        manager = NativeSceneMetadataTransaction(
            self.client, self.editor,
            programmer=FakeProgrammer(NativeSession(
                self.spec, self.client)))
        plan = manager.plan('/db//TEST/254/p/20', operations=rows,
                            exclusive_project=True)

        def ambiguous(command):
            if not command.startswith('DBADDSAFE '):
                return None
            group = self.client.applications[202]['groups'][43]
            identity = self.client._new_oid()
            group['levels'] = (2,)
            group['level_oids'] = {2: identity}
            group['level_names'] = {2: 'Action Selector 2'}
            group['level_values'] = {2: 0}
            return response(301, 'created without an OID receipt')

        self.client.failure = ambiguous
        with self.assertRaisesRegex(NativeSceneMetadataError,
                                    'did not return one OID'):
            manager.apply(plan, backup_project='SCBACKUP')
        evidence = manager.last_result.as_dict()
        self.assertTrue(evidence['unidentified_metadata_mutation'])
        self.assertTrue(evidence['rollback_verified'])
        self.assertNotIn('rollback_project_save_confirmed', evidence)
        self.assertFalse(evidence['database_state_uncertain'])
        self.assertEqual(self.client.applications, original)

    def test_lost_project_save_after_pp_save_is_partial_and_not_retried(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
        )
        session = NativeSession(self.spec, self.client)
        manager = NativeSceneMetadataTransaction(
            self.client, self.editor, programmer=FakeProgrammer(session))
        plan = manager.plan('/db//TEST/254/p/20', operations=rows,
                            exclusive_project=True)
        saves = 0

        def fail_second_save(command):
            nonlocal saves
            if command == 'PROJECT SAVE TEST':
                saves += 1
                if saves == 2:
                    return ConnectionError('lost project save reply')
            return None

        self.client.failure = fail_second_save
        with self.assertRaises(NativeSceneMetadataError):
            manager.apply(plan, backup_project='SCBACKUP')
        evidence = manager.last_result.as_dict()
        self.assertTrue(evidence['pp_save_confirmed'])
        self.assertTrue(evidence['target_project_save_attempted'])
        self.assertFalse(evidence['target_project_save_confirmed'])
        self.assertTrue(evidence['target_project_save_outcome_uncertain'])
        self.assertTrue(evidence['partial_failure_possible'])
        self.assertFalse(evidence['rollback_attempted'])
        self.assertEqual(evidence['automatic_retries'], 0)

    def test_lost_project_save_without_pp_changes_is_not_rolled_back(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
        )
        source = self.plan(rows)
        for name, value in source.scene_plan.changes.items():
            self.client.values[name] = _render(value)

        session = NativeSession(self.spec, self.client)
        manager = NativeSceneMetadataTransaction(
            self.client, self.editor, programmer=FakeProgrammer(session))
        plan = manager.plan(
            '/db//TEST/254/p/20',
            operations=({'op': 'get-action', 'scene': 1},),
            exclusive_project=True)
        self.assertTrue(plan.resolved.creations)
        self.assertFalse(plan.scene_plan.changes)
        saves = 0

        def fail_second_save(command):
            nonlocal saves
            if command == 'PROJECT SAVE TEST':
                saves += 1
                if saves == 2:
                    return ConnectionError('lost project save reply')
            return None

        self.client.failure = fail_second_save
        with self.assertRaises(NativeSceneMetadataError):
            manager.apply(plan, backup_project='SCBACKUP')
        evidence = manager.last_result.as_dict()
        self.assertFalse(evidence['pp_save_attempted'])
        self.assertTrue(evidence['target_project_save_attempted'])
        self.assertFalse(evidence['target_project_save_confirmed'])
        self.assertTrue(evidence['target_project_save_outcome_uncertain'])
        self.assertTrue(evidence['database_state_uncertain'])
        self.assertFalse(evidence['rollback_attempted'])
        self.assertEqual(evidence['automatic_retries'], 0)

    def test_after_backup_stale_guard_and_interruption_evidence(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
        )
        manager = NativeSceneMetadataTransaction(
            self.client, self.editor,
            programmer=FakeProgrammer(NativeSession(
                self.spec, self.client)))
        plan = manager.plan('/db//TEST/254/p/20', operations=rows,
                            exclusive_project=True)
        reads = 0

        def change_after_backup(command):
            nonlocal reads
            if command == 'DBGETXML //TEST':
                reads += 1
                if reads == 2:
                    self.client.applications[56]['tag'] = 'Concurrent edit'
            return None

        self.client.failure = change_after_backup
        with self.assertRaisesRegex(NativeSceneMetadataError,
                                    'changed since planning'):
            manager.apply(plan, backup_project='SCBACKUP')
        evidence = manager.last_result.as_dict()
        self.assertTrue(evidence['backup_created'])
        self.assertFalse(evidence['metadata_mutation_attempted'])
        self.assertFalse(evidence['pp_mutation_attempted'])

        client = SceneMetadataClient(self.spec)
        client.values = deepcopy(self.client.saved_values)
        editor = SceneCLIEditor(self.spec)
        manager = NativeSceneMetadataTransaction(
            client, editor,
            programmer=FakeProgrammer(NativeSession(self.spec, client)))
        plan = manager.plan('/db//TEST/254/p/20', operations=rows,
                            exclusive_project=True)
        saves = 0

        def interrupt_target_save(command):
            nonlocal saves
            if command == 'PROJECT SAVE TEST':
                saves += 1
                if saves == 2:
                    return KeyboardInterrupt('interrupted project save')
            return None

        client.failure = interrupt_target_save
        with self.assertRaises(KeyboardInterrupt) as caught:
            manager.apply(plan, backup_project='SCBACKUP')
        evidence = caught.exception.edlt_scene_metadata_evidence
        self.assertTrue(evidence['pp_save_confirmed'])
        self.assertTrue(evidence['target_project_save_attempted'])
        self.assertTrue(evidence['target_project_save_outcome_uncertain'])
        self.assertFalse(evidence['rollback_attempted'])
        self.assertEqual(evidence['automatic_retries'], 0)

    def test_exact_requested_255_bypasses_blank_dialog_254_capacity(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 255},
        )
        plan = self.plan(rows)
        self.assertEqual(
            [(row.group, row.address, row.name)
             for row in plan.resolved.creations],
            [(43, 255, 'Action Selector 255')])
        self.assertEqual(plan.as_dict()['native_blank_add_dialog_allocation'],
                         ('first free address 0..254; outside this automatic '
                          'exact-address path'))

    def test_native_stale_capacity_rollback_and_lost_save_boundaries(self):
        capacity_client = SceneMetadataClient(self.spec)
        capacity_client.values = deepcopy(self.client.values)
        capacity_editor = SceneCLIEditor(self.spec)
        capacity = NativeSceneMetadataTransaction(
            capacity_client, capacity_editor,
            programmer=FakeProgrammer(NativeSession(
                self.spec, capacity_client)))
        with self.assertRaisesRegex(NativeSceneMetadataError, 'capacity'):
            capacity.plan(
                '/db//TEST/254/p/20', operations=operations('capacity-add'),
                exclusive_project=True)
        self.assertFalse(any(command.startswith(('DBADD', 'DBDELETE'))
                             for command in capacity_client.commands))

        stale_client = SceneMetadataClient(self.spec)
        stale_client.values = deepcopy(self.client.values)
        stale_editor = SceneCLIEditor(self.spec)
        stale = NativeSceneMetadataTransaction(
            stale_client, stale_editor,
            programmer=FakeProgrammer(NativeSession(self.spec, stale_client)))
        stale_plan = stale.plan(
            '/db//TEST/254/p/20', operations=operations('sync'),
            exclusive_project=True)
        stale_client.applications[56]['groups'][12]['tag'] = 'Changed'
        with self.assertRaisesRegex(NativeSceneMetadataError,
                                    'changed since planning'):
            stale.apply(stale_plan)
        self.assertFalse(stale.last_result.as_dict()['pp_mutation_attempted'])

        rollback_client = SceneMetadataClient(self.spec)
        rollback_client.values = deepcopy(self.client.values)
        rollback_editor = SceneCLIEditor(self.spec)
        rollback_session = NativeSession(self.spec, rollback_client)
        rollback = NativeSceneMetadataTransaction(
            rollback_client, rollback_editor,
            programmer=FakeProgrammer(rollback_session))
        rollback_plan = rollback.plan(
            '/db//TEST/254/p/20', operations=operations('sync'),
            exclusive_project=True)
        rollback_session.failure = next(iter(rollback_plan.scene_plan.changes))
        with self.assertRaises(NativeSceneMetadataError):
            rollback.apply(rollback_plan)
        evidence = rollback.last_result.as_dict()
        self.assertTrue(evidence['rollback_attempted'])
        self.assertTrue(evidence['rollback_verified'])
        self.assertFalse(evidence['pp_state_uncertain'])

        uncertain_client = SceneMetadataClient(self.spec)
        uncertain_client.values = deepcopy(self.client.values)
        uncertain_editor = SceneCLIEditor(self.spec)
        uncertain_session = NativeSession(self.spec, uncertain_client)
        uncertain_session.save_error = ConnectionError('lost save reply')
        uncertain = NativeSceneMetadataTransaction(
            uncertain_client, uncertain_editor,
            programmer=FakeProgrammer(uncertain_session))
        uncertain_plan = uncertain.plan(
            '/db//TEST/254/p/20', operations=operations('sync'),
            exclusive_project=True)
        with self.assertRaises(NativeSceneMetadataError):
            uncertain.apply(uncertain_plan)
        evidence = uncertain.last_result.as_dict()
        self.assertTrue(evidence['pp_save_attempted'])
        self.assertFalse(evidence['pp_save_confirmed'])
        self.assertTrue(evidence['pp_save_outcome_uncertain'])
        self.assertTrue(evidence['database_state_uncertain'])
        self.assertEqual(evidence['automatic_retries'], 0)

    def test_evidence_documents_are_strict_and_honest(self):
        evidence = json.loads(EVIDENCE.read_text())
        acceptance = json.loads(ACCEPTANCE.read_text())
        self.assertEqual(evidence['format'],
                         'cbus-edlt-scene-metadata-evidence-v2')
        self.assertTrue(evidence['implemented_boundary']
                        ['automatic_existing_metadata_resolution'])
        self.assertFalse(evidence['evidence_boundaries']
                         ['full_scene_manager_control_binding_verified'])
        self.assertTrue(evidence['implemented_boundary']
                        ['missing_exact_action_level_creation'])
        self.assertEqual(evidence['original_sources'][0]['sha256'],
                         ('9d01721abab3beb4724511e7d65e39328c0518e0721caa53'
                          'f4601cded20655ab'))
        self.assertEqual(acceptance['format'],
                         'cbus-edlt-scene-metadata-acceptance-v2')
        self.assertTrue(acceptance['passed'])

    @unittest.skipUnless(
        os.environ.get('CBUS_EDLT_SCENE_LEVEL_ACCEPTANCE') == '1'
        and os.environ.get('CBUS_EDLT_SCENE_LEVEL_UNIT')
        and os.environ.get('CBUS_EDLT_SCENE_LEVEL_BACKUP')
        and os.environ.get('CBUS_EDLT_SCENE_LEVEL_GROUP')
        and os.environ.get('CBUS_EDLT_SCENE_LEVEL_ACTION')
        and os.environ.get('CBUS_CGATE_TEST_HOST')
        and os.environ.get('CBUS_UNITSPEC_DIR'),
        'Set the explicit disposable closed-project scene-level acceptance environment')
    def test_optional_native_missing_action_level_transaction(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.unitspec import UnitSpecStore

        group = int(os.environ['CBUS_EDLT_SCENE_LEVEL_GROUP'])
        action = int(os.environ['CBUS_EDLT_SCENE_LEVEL_ACTION'])
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': group},
            {'op': 'set-action', 'scene': 1, 'action': action},
        )
        editor = SceneCLIEditor(
            UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml'))
        with CGateClient(
                os.environ['CBUS_CGATE_TEST_HOST'],
                int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')),
                timeout=30) as client:
            manager = NativeSceneMetadataTransaction(client, editor)
            plan = manager.plan(
                os.environ['CBUS_EDLT_SCENE_LEVEL_UNIT'], operations=rows,
                exclusive_project=True)
            self.assertEqual(
                [(row.group, row.address) for row in plan.resolved.creations],
                [(group, action)])
            result = manager.apply(
                plan, backup_project=os.environ[
                    'CBUS_EDLT_SCENE_LEVEL_BACKUP']).as_dict()
        self.assertTrue(result['persistence_verified'])
        self.assertTrue(result['pp_save_confirmed'])
        self.assertTrue(result['target_project_save_confirmed'])
        self.assertFalse(result['physical_device_programmed'])


if __name__ == '__main__':
    unittest.main()
