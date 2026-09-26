"""Automatic project metadata for retained eDLT Scene Manager edits."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_scene_manager_cli import SceneCLIEditor
from cbus_toolkit.edlt_scene_metadata import (
    NativeSceneMetadataError, NativeSceneMetadataTransaction,
    plan_native_scene_metadata, resolve_native_scene_metadata,
)
from tests.test_edlt_parent_metadata import (
    FakeProgrammer, MetadataClient, NativeSession, oid,
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

    def _group_xml(self, application, address, group):
        value = super()._group_xml(application, address, group)
        for level, rows in group.get('level_tags', {}).items():
            marker = '<Level Value="' + str(level) + '">'
            label_xml = ''.join(
                '<TagDLT><LanguageID>' + str(row.get('language', 1))
                + '</LanguageID><FlavourID>' + str(row['variant'] + 1)
                + '</FlavourID><TagType>' + row['type']
                + '</TagType><TagValue>' + row['value']
                + '</TagValue></TagDLT>' for row in rows)
            value = value.replace(
                marker, marker + '<TagsDLT>' + label_xml + '</TagsDLT>', 1)
        return value


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
                         'cbus-native-edlt-scene-metadata-plan-v1')
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
            'validate-missing-action', 'validate-missing-name',
            'validate-all-four', 'validate-shortcut-first',
            'validate-shortcut-second', 'validate-empty-duplicates',
            'validate-action255', 'validate-missing-action-duplicate',
            'validate-all-empty', 'get-new-missing-trigger',
            'get-set-action-valid', 'get-set-action-missing',
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

    def test_missing_requested_trigger_or_action_is_not_created(self):
        rows = (
            {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'set-action', 'scene': 1, 'action': 2},
            {'op': 'get-action', 'scene': 1},
        )
        plan = self.plan(rows)
        result = plan.scene_plan.source.as_dict()
        self.assertEqual(result['scenes'][0]['raw_trigger'], 43)
        self.assertEqual(result['scenes'][0]['raw_action'], -1)
        self.assertFalse(plan.as_dict()['automatic_metadata']
                         ['missing_objects_auto_created'])
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
        self.assertEqual(self.client.applications, before)
        self.assertFalse(any(command.startswith(('DBADD', 'DBDELETE'))
                             for command in self.client.commands))

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
                         'cbus-edlt-scene-metadata-evidence-v1')
        self.assertTrue(evidence['implemented_boundary']
                        ['automatic_existing_metadata_resolution'])
        self.assertFalse(evidence['evidence_boundaries']
                         ['full_scene_manager_control_binding_verified'])
        self.assertFalse(evidence['implemented_boundary']
                         ['missing_level_creation'])
        self.assertEqual(acceptance['format'],
                         'cbus-edlt-scene-metadata-acceptance-v1')
        self.assertTrue(acceptance['passed'])


if __name__ == '__main__':
    unittest.main()
