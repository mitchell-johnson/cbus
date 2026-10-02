"""Complete Corridor/Activation inventories and one guarded parent save."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_application_cache import ApplicationCache
from cbus_toolkit.edlt_display_model import EdltDisplayPreferences
from cbus_toolkit.edlt_parent_add_dialog import resolve, normalize
from cbus_toolkit.edlt_parent_metadata import (
    NativeEdltParentError, NativeEdltParentTransaction, plan_native_parent_metadata,
)
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction, normalize_operations
from tests.test_edlt_parent_cache_panels import fixture
from tests.test_edlt_parent_metadata import MetadataClient, NativeSession, FakeProgrammer, oid

UNIT = '//TEST/254/p/20'


def widget():
    return dict(op='measurement', page=1, position=1, device_id=42, channel=1)


class NamedClient(MetadataClient):
    project_tag = 'Site display name'

    def xml(self):
        text = super().xml()
        return text.replace('<Project>', '<Project><TagName>' + self.project_tag + '</TagName>')


class ParentAddTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.client = NamedClient(self.spec)
        self.client.values.update(ProximityMode='3', ProximityGroup='7')
        self.client.applications[56]['groups'] = {
            0: dict(oid=oid(500), tag='Zulu', levels=()),
            2: dict(oid=oid(502), tag='Alpha', levels=()),
        }
        self.client.applications[202]['groups'] = {
            7: dict(oid=oid(207), tag='Existing trigger', levels=(0, 2),
                    level_names={0: 'Existing action', 2: 'Other action'}),
        }

    def plan(self, rows, *, preferences=EdltDisplayPreferences()):
        return plan_native_parent_metadata(self.client.xml(), UNIT,
            self.editor.snapshot(self.client.values), self.editor, (*rows, widget()),
            display_preferences=preferences)

    def test_corridor_three_adds_compose_complete_sorted_list_and_timer(self):
        plan = self.plan((dict(op='add-corridor-dialog', field='link_group', name='Link'),
                          dict(op='add-corridor-dialog', field='office_group', name='Office'),
                          dict(op='add-corridor-dialog', field='corridor_group', name='Corridor'),
                          dict(op='corridor', edits=[dict(field='seconds', value=300)])))
        self.assertEqual([(row.application, row.address, row.name) for row in plan.creations
                          if row.kind == 'Group'], [(56, 1, 'Link'), (56, 3, 'Office'), (56, 4, 'Corridor')])
        self.assertIsInstance(plan.cache, ApplicationCache)
        self.assertTrue(plan.cache.applications_complete)
        self.assertTrue(all(row.complete for row in plan.cache.group_lists))
        self.assertEqual([row.name for row in plan.cache.find_group_list(56).groups],
                         ['Alpha', 'Corridor', 'Link', 'Office', 'Zulu'])
        final = {**plan.parent_plan.expected, **plan.parent_plan.changes}
        self.assertEqual([final[name] for name in ('CorridorLinkingLinkGroup',
            'CorridorLinkingOfficeGroup', 'CorridorLinkingCorridorGroup')], [(1,), (3,), (4,)])
        self.assertEqual(final['CorridorLinkingCorridorTime'], (300,))
        self.assertEqual(len(self.editor.lifecycle.common.crcs(final)), 5)

    def test_independent_literal_dialog_vector(self):
        vector = json.loads((Path(__file__).resolve().parents[2] /
            'rust/testdata/vectors/edlt_parent_add_dialog.json').read_text())
        values = {name: tuple(row) for name, row in vector['base_values'].items()}
        groups = {int(app): {int(key): name for key, name in rows.items()}
                  for app, rows in vector['groups'].items()}
        levels = {tuple(map(int, key.split('/'))): {int(address): name for address, name in rows.items()}
                  for key, rows in vector['levels'].items()}
        for case in vector['cases']:
            with self.subTest(case['name']):
                call = lambda: resolve(case['operations'], values, vector['project_tag_name'],
                                       groups, levels, lambda index: ())
                if 'error' in case:
                    with self.assertRaisesRegex(EdltError, case['error']): call()
                    continue
                lowered, receipts, _, _ = call()
                self.assertEqual(list(lowered), case['resolved'])
                for key, field in [('addresses', 'address'), ('names', 'name'),
                                   ('first_free', 'first_free_address'), ('outcomes', 'outcome')]:
                    if key in case:
                        self.assertEqual([r.as_dict()[field] for r in receipts], case[key])

    def test_corridor_sort_by_address_uses_explicit_preferences(self):
        p = self.plan((dict(op='add-corridor-dialog', field='link_group', name='Beta'),),
                      preferences=EdltDisplayPreferences(sort_groups_by_address=True))
        self.assertEqual([row.address for row in p.cache.find_group_list(56).groups], [0, 1, 2])
        with self.assertRaisesRegex(ValueError, 'explicit display preferences'):
            self.plan((dict(op='add-corridor-dialog', field='link_group'),), preferences=None)

    def test_repeated_corridor_add_keeps_both_objects_and_last_binding(self):
        p = self.plan((dict(op='add-corridor-dialog', field='link_group', name='First'),
                       dict(op='add-corridor-dialog', field='link_group', name='Second')))
        self.assertEqual([r.as_dict()['address'] for r in p.add_dialogs], [1, 3])
        self.assertEqual(p.parent_plan.changes['CorridorLinkingLinkGroup'], (3,))
        self.assertEqual([c.name for c in p.creations if c.application == 56], ['First', 'Second'])

    def test_cancel_history_does_not_allocate_or_bind(self):
        p = self.plan((dict(op='add-corridor-dialog', field='link_group', cancel=True, name=''),
                       dict(op='add-corridor-dialog', field='link_group', name='Accepted'),
                       dict(op='add-corridor-dialog', field='office_group', cancel=True)))
        rows = [r.as_dict() for r in p.add_dialogs]
        self.assertEqual([r['outcome'] for r in rows], ['cancelled', 'accepted', 'cancelled'])
        self.assertEqual([r['first_free_address'] for r in rows], [1, 1, 3])
        self.assertEqual(p.parent_plan.changes['CorridorLinkingLinkGroup'], (1,))
        self.assertNotIn('CorridorLinkingOfficeGroup', p.parent_plan.changes)
        self.assertEqual(p.as_dict()['add_dialog_boundary']['cancelled_dialogs'], 2)

    def test_disabled_corridor_controls_refuse_before_metadata(self):
        for field in ('office_group', 'corridor_group'):
            with self.subTest(field):
                with self.assertRaisesRegex(EdltError, 'disabled'):
                    self.plan((dict(op='add-corridor-dialog', field=field),))
        self.assertEqual(self.client.commands, [])

    def test_corridor_missing_stored_link_is_cleared_before_add(self):
        self.client.values['CorridorLinkingLinkGroup'] = '99'
        with self.assertRaisesRegex(EdltError, 'disabled'):
            self.plan((dict(op='add-corridor-dialog', field='office_group'),))

    def test_group_names_compare_exact_project_tag_and_ascii_duplicate(self):
        for name, message in [('Site display name', '2204'), (' ALPHA ', '2203'), ('  ', '2202')]:
            with self.subTest(name):
                with self.assertRaisesRegex(EdltError, message):
                    self.plan((dict(op='add-corridor-dialog', field='link_group', name=name),))
        p = self.plan((dict(op='add-corridor-dialog', field='link_group', name='TEST'),))
        self.assertEqual(next(c for c in p.creations if c.application == 56).name, 'TEST')

    def test_activation_action_first_free_value_and_default_name(self):
        p = self.plan((dict(op='add-activation-action-dialog', address=40),))
        action = next(c for c in p.creations if c.kind == 'Level')
        self.assertEqual((action.application, action.group, action.address, action.value, action.name),
                         (202, 7, 40, 40, 'Level 1'))
        self.assertEqual(p.parent_plan.changes['ProximityLevel'], (40,))
        self.assertEqual(p.cache.lifecycle.find(202, 7).levels, (0, 2, 40))

    def test_activation_group_then_two_actions_preserves_history(self):
        p = self.plan((dict(op='add-activation-group-dialog', name='New trigger'),
                       dict(op='add-activation-action-dialog', name='First action'),
                       dict(op='add-activation-action-dialog', name='Second action')))
        self.assertEqual([r.as_dict()['address'] for r in p.add_dialogs], [0, 0, 1])
        self.assertEqual(p.parent_plan.changes['ProximityGroup'], (0,))
        self.assertEqual(p.parent_plan.changes['ProximityLevel'], (1,))
        self.assertEqual(p.cache.lifecycle.find(202, 0).levels, (0, 1))
        self.assertEqual(self.client.applications[202]['groups'][7]['levels'], (0, 2))

    def test_cancelled_activation_action_keeps_value_and_inventory(self):
        p = self.plan((dict(op='add-activation-action-dialog', cancel=True),))
        self.assertFalse(any(c.kind == 'Level' for c in p.creations))
        self.assertNotIn('ProximityLevel', p.parent_plan.changes)
        self.assertEqual(p.add_dialogs[0].as_dict()['outcome'], 'cancelled')

    def test_level_duplicate_entered_name_rule_differs_from_group_trim(self):
        with self.assertRaisesRegex(EdltError, '2212'):
            self.plan((dict(op='add-activation-action-dialog', name='EXISTING ACTION'),))
        p = self.plan((dict(op='add-activation-action-dialog', name=' Existing action '),))
        self.assertEqual(next(c.name for c in p.creations if c.kind == 'Level'), 'Existing action')
        with self.assertRaisesRegex(EdltError, '2213'):
            self.plan((dict(op='add-activation-action-dialog', name='Site display name'),))

    def test_activation_visibility_and_list_application_fences(self):
        for changes, op in [({'ActivityDuration': '0'}, 'add-activation-group-dialog'),
                            ({'ProximityMode': '1'}, 'add-activation-group-dialog'),
                            ({'ProximityMode': '2'}, 'add-activation-action-dialog'),
                            ({'ProximityGroup': '255'}, 'add-activation-action-dialog')]:
            with self.subTest(changes):
                old = dict(self.client.values); self.client.values.update(changes)
                with self.assertRaises(EdltError): self.plan((dict(op=op),))
                self.client.values = old
        self.client.values['ProximityMode'] = '2'
        p = self.plan((dict(op='add-activation-group-dialog'),))
        self.assertEqual(p.add_dialogs[0].as_dict()['application'], 56)

    def test_earlier_activation_enables_add_without_borrowing_future_state(self):
        self.client.values['ProximityMode'] = '0'
        p = self.plan((dict(op='activation', wake_mode='trigger-event', group=7),
                       dict(op='add-activation-action-dialog', name='Enabled action')))
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['ProximityMode'], final['ProximityLevel']), ((3,), (1,)))
        with self.assertRaisesRegex(EdltError, 'event wake mode'):
            self.plan((dict(op='add-activation-action-dialog'),
                       dict(op='activation', wake_mode='trigger-event', group=7)))
        self.client.values['ActivityDuration'] = '0'
        p = self.plan((dict(op='standby', enabled=True),
                       dict(op='activation', wake_mode='trigger-event', group=7),
                       dict(op='add-activation-action-dialog')))
        self.assertEqual(p.parent_plan.changes['ActivityDuration'], (3,))
        with self.assertRaisesRegex(EdltError, 'enabled standby'):
            self.plan((dict(op='add-activation-action-dialog'), dict(op='standby', enabled=True)))

    def test_explicit_panels_and_dialog_bindings_keep_actual_order(self):
        p = self.plan((dict(op='corridor', edits=[dict(field='link_group', value=2)]),
                       dict(op='add-corridor-dialog', field='office_group', name='Office')))
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['CorridorLinkingLinkGroup'], final['CorridorLinkingOfficeGroup']), ((2,), (1,)))
        p = self.plan((dict(op='add-activation-group-dialog', name='Retained new group'),
                       dict(op='activation', group=7), dict(op='add-activation-action-dialog')))
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual(final['ProximityGroup'], (7,))
        self.assertEqual(next(c for c in p.creations if c.name == 'Retained new group').address, 0)
        self.assertEqual(next(c for c in p.creations if c.kind == 'Level').group, 7)
        with self.assertRaisesRegex(EdltError, 'only one activation'):
            self.plan((dict(op='activation'), dict(op='activation'),
                       dict(op='add-activation-action-dialog')))

    def test_old_group_add_and_new_add_share_allocator_and_binding_history(self):
        p = self.plan((dict(op='add-dialog', field='ProximityGroup', name='First group'),
                       dict(op='add-activation-action-dialog', name='First action'),
                       dict(op='add-activation-group-dialog', name='Second group'),
                       dict(op='add-activation-action-dialog', name='Second action')))
        self.assertEqual([r.as_dict()['address'] for r in p.add_dialogs], [0, 0, 1, 0])
        self.assertEqual([(c.group, c.address) for c in p.creations if c.kind == 'Level'], [(0, 0), (1, 0)])
        self.assertEqual(p.parent_plan.changes['ProximityGroup'], (1,))
        self.assertEqual(p.parent_plan.changes['ProximityLevel'], (0,))

    def test_scene_manager_dialogs_and_parent_adds_share_complete_history(self):
        p = self.plan((dict(op='add-activation-group-dialog', name='Parent group'),
                       dict(op='add-activation-action-dialog', name='Parent action'),
                       dict(op='scene-manager', operations=[dict(op='set-trigger', scene=1, group=0),
                           dict(op='add-action-dialog', scene=1, name='Scene action')]),
                       dict(op='add-activation-action-dialog', name='Later parent action')))
        self.assertEqual([(c.group, c.address, c.name) for c in p.creations if c.kind == 'Level'],
                         [(0, 0, 'Parent action'), (0, 1, 'Scene action'), (0, 2, 'Later parent action')])
        self.assertEqual(p.cache.application_cache.lifecycle.find(202, 0).levels, (0, 1, 2))
        self.assertEqual(p.parent_plan.changes['ProximityLevel'], (2,))
        self.assertEqual(p.scene_metadata.operations[-1], dict(op='set-action', scene=1, action=1))
        self.assertEqual(p.parent_plan.as_dict()['execution_counts']['terminal_crc_passes'], 1)

    def test_complete_allocator_bound_and_occupied_refuse(self):
        for op in (dict(op='add-corridor-dialog', field='link_group', address=0),
                   dict(op='add-activation-action-dialog', address=2)):
            with self.subTest(op):
                with self.assertRaisesRegex(EdltError, 'listed free'): self.plan((op,))
        self.client.applications[202]['groups'][7]['levels'] = tuple(range(255))
        with self.assertRaisesRegex(EdltError, '2271'):
            self.plan((dict(op='add-activation-action-dialog', cancel=True),))

    def test_missing_selected_trigger_getter_precedes_action_add(self):
        del self.client.applications[202]['groups'][7]
        p = self.plan((dict(op='add-activation-action-dialog', name='First action'),))
        self.assertEqual([(c.kind, c.address, c.name) for c in p.creations if c.application == 202],
                         [('Group', 7, 'Group 7'), ('Level', 0, 'First action')])
        self.assertEqual(p.add_dialogs[0].as_dict()['group'], 7)
        self.assertEqual(p.parent_plan.changes['ProximityLevel'], (0,))

    def test_parent_load_scene_getter_occupies_action_before_add(self):
        bucket = [255] * 232
        bucket[:5] = [2, 0, 7, 1, 255]
        self.client.values.update(SceneBucket=' '.join(map(str, bucket)),
                                  Scene1StartAddress='0', SceneCount='1')
        p = self.plan((dict(op='add-activation-action-dialog', name='After initial getter'),
                       dict(op='scene-manager', operations=[dict(op='get-action', scene=1)])))
        self.assertEqual([(c.group, c.address, c.name) for c in p.creations if c.kind == 'Level'],
                         [(7, 1, 'Action Selector 1'), (7, 3, 'After initial getter')])
        self.assertEqual(p.add_dialogs[0].as_dict()['first_free_address'], 3)

    def test_initial_scene_getter_occupies_level_without_scene_manager(self):
        bucket = [255] * 232
        bucket[:5] = [2, 0, 7, 1, 255]
        self.client.values.update(SceneBucket=' '.join(map(str, bucket)),
                                  Scene1StartAddress='0', SceneCount='1')
        p = self.plan((dict(op='add-activation-action-dialog', name='After getter'),))
        self.assertIsNone(p.scene_metadata)
        self.assertEqual([(c.address, c.name) for c in p.creations if c.kind == 'Level'],
                         [(1, 'Action Selector 1'), (3, 'After getter')])
        self.assertEqual(p.add_dialogs[0].as_dict()['first_free_address'], 3)
        self.assertEqual(p.parent_plan.changes['ProximityLevel'], (3,))

    def test_initial_corridor_missing_role_cannot_see_future_created_group(self):
        self.client.values['CorridorLinkingLinkGroup'] = '255'
        self.client.values['CorridorLinkingOfficeGroup'] = '99'
        p = self.plan((dict(op='add-corridor-dialog', field='link_group', address=99,
                            name='Future link'),))
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['CorridorLinkingLinkGroup'], final['CorridorLinkingOfficeGroup']),
                         ((99,), (255,)))
        self.assertEqual(p.parent_plan.dialog_initial_missing, ('CorridorLinkingOfficeGroup',))
        self.assertEqual(p.parent_plan.expected['CorridorLinkingOfficeGroup'], (99,))
        manager, _ = self.manager()
        issued = manager.plan(UNIT, operations=(dict(op='add-corridor-dialog', field='link_group',
                              address=99, name='Future link'), widget()), exclusive_project=True)
        result = manager.apply(issued, backup_project='BACKUP').as_dict()
        self.assertTrue(result['saved'] and result['persistence_verified'])
        self.assertEqual(self.client.values['CorridorLinkingOfficeGroup'], '255')
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)

    def test_scene_manager_precedes_parent_group_and_action_add(self):
        p = self.plan((dict(op='scene-manager', operations=[dict(op='add-trigger-dialog', scene=1,
                          name='Scene group'), dict(op='add-action-dialog', scene=1, name='Scene action')]),
                       dict(op='add-activation-group-dialog', name='Parent group'),
                       dict(op='add-activation-action-dialog', name='Parent action')))
        self.assertEqual([r.as_dict()['address'] for r in p.add_dialogs], [1, 0])
        self.assertEqual([(c.address, c.name) for c in p.creations if c.kind == 'Group' and c.application == 202],
                         [(0, 'Scene group'), (1, 'Parent group')])
        self.assertEqual([(c.group, c.address) for c in p.creations if c.kind == 'Level'], [(0, 0), (1, 0)])

    def test_applications_before_corridor_add_uses_selected_existing_application(self):
        self.client.applications[57] = dict(oid=oid(570), tag='Secondary lighting',
                                           groups={0: dict(oid=oid(571), tag='Existing', levels=())})
        p = self.plan((dict(op='applications', edits=[dict(field='secondary', address=255),
                                                    dict(field='primary', address=57)]),
                       dict(op='add-corridor-dialog', field='link_group', name='New link')))
        self.assertEqual(p.add_dialogs[0].as_dict()['application'], 57)
        self.assertEqual(p.parent_plan.changes['PrimaryApplication'], (57,))
        self.assertEqual(p.parent_plan.changes['CorridorLinkingLinkGroup'], (1,))

    def switched_corridor(self):
        self.client.applications[56]['groups'][99] = dict(
            oid=oid(599), tag='Old Office', levels=())
        self.client.applications[57] = dict(oid=oid(570), tag='Secondary lighting',
            groups={0: dict(oid=oid(571), tag='Existing', levels=())})
        self.client.values.update(CorridorLinkingLinkGroup='0', CorridorLinkingOfficeGroup='99')
        return dict(op='applications', edits=[dict(field='secondary', address=255),
                                              dict(field='primary', address=57)])

    def test_switched_corridor_cannot_see_later_quick_status_creation(self):
        rows = (self.switched_corridor(),
                dict(op='add-corridor-dialog', field='link_group', address=1, name='New link'),
                dict(op='add-dialog', field='QuickStatusGroup', address=99, name='Future status'))
        p = self.plan(rows)
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['PrimaryApplication'], final['CorridorLinkingOfficeGroup'],
                          final['QuickStatusGroup']), ((57,), (255,), (99,)))
        self.assertEqual(p.parent_plan.dialog_initial_missing, ())
        self.assertEqual(p.parent_plan.dialog_missing_by_operation,
                         ((2, 57, (('CorridorLinkingOfficeGroup', 99),)),))
        self.assertEqual(p.add_dialogs[0].as_dict()['show_missing']['application'], 57)
        manager, _ = self.manager()
        issued = manager.plan(UNIT, operations=(*rows, widget()), exclusive_project=True)
        result = manager.apply(issued, backup_project='BACKUP').as_dict()
        self.assertTrue(result['saved'] and result['persistence_verified'])
        self.assertEqual(self.client.values['CorridorLinkingOfficeGroup'], '255')
        self.assertEqual(self.client.applications[56]['groups'][99]['tag'], 'Old Office')
        self.assertEqual(self.client.applications[57]['groups'][99]['tag'], 'Future status')
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)

    def test_switched_corridor_missing_office_does_not_exclude_new_link(self):
        p = self.plan((self.switched_corridor(),
                      dict(op='add-corridor-dialog', field='link_group', address=99,
                           name='New link')))
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['CorridorLinkingLinkGroup'], final['CorridorLinkingOfficeGroup']),
                         ((99,), (255,)))
        self.assertEqual(p.parent_plan.dialog_missing_by_operation,
                         ((2, 57, (('CorridorLinkingOfficeGroup', 99),)),))

    def test_switched_ordinary_corridor_show_cannot_see_future_add(self):
        p = self.plan((self.switched_corridor(),
                      dict(op='corridor', edits=[dict(field='seconds', value=300)]),
                      dict(op='add-corridor-dialog', field='link_group', address=99,
                           name='New link')))
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['CorridorLinkingLinkGroup'], final['CorridorLinkingOfficeGroup']),
                         ((99,), (255,)))
        self.assertEqual(p.parent_plan.dialog_missing_by_operation,
                         ((2, 57, (('CorridorLinkingOfficeGroup', 99),)),))

    def test_ordered_show_context_is_validated_during_canonical_apply(self):
        p = self.plan((self.switched_corridor(),
                      dict(op='add-corridor-dialog', field='link_group', address=99,
                           name='New link')))
        forged = replace(p.parent_plan, dialog_missing_by_operation=
                         ((2, 56, (('CorridorLinkingOfficeGroup', 99),)),))
        _, session = self.manager()
        with self.assertRaisesRegex(EdltError, 'absence facts differ'):
            self.editor.apply(session, forged)
        self.assertEqual(self.client.commands, [])

    def test_mixed_old_quick_status_add_and_corridor_add_keep_both(self):
        p = self.plan((dict(op='add-dialog', field='QuickStatusGroup', name='Status'),
                       dict(op='add-corridor-dialog', field='link_group', name='Link')))
        self.assertEqual([r.as_dict()['address'] for r in p.add_dialogs], [1, 3])
        self.assertEqual(p.parent_plan.changes['QuickStatusGroup'], (1,))
        self.assertEqual(p.parent_plan.changes['CorridorLinkingLinkGroup'], (3,))

    def test_no_partial_cache_path_or_unknown_application_add(self):
        with self.assertRaisesRegex(EdltError, 'automatic'):
            normalize_operations((dict(op='add-activation-action-dialog'), widget()))
        with self.assertRaisesRegex(EdltError, 'pointer'):
            self.plan((dict(op='add-dialog', field='PrimaryApplication'),))
        for row in (dict(op='add-corridor-dialog', field='seconds'),
                    dict(op='add-activation-action-dialog', address=255),
                    dict(op='add-activation-action-dialog', cancel=1)):
            with self.subTest(row):
                with self.assertRaises(EdltError): normalize(row)

    def test_transport_bound_names_and_missing_project_tag_fail_locally(self):
        for name in ('bad#name', 'bad  name', 'bad\uffffname'):
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    self.plan((dict(op='add-activation-action-dialog', name=name),))
        text = self.client.xml().replace('<TagName>Site display name</TagName>', '')
        with self.assertRaises(ValueError):
            plan_native_parent_metadata(text, UNIT, self.editor.snapshot(self.client.values),
                self.editor, (dict(op='add-activation-action-dialog'), widget()))
        self.assertEqual(self.client.commands, [])

    def manager(self):
        session = NativeSession(self.spec, self.client)
        return NativeEdltParentTransaction(self.client, self.editor,
            programmer=FakeProgrammer(session), display_preferences=EdltDisplayPreferences()), session

    def test_guarded_apply_creates_action_then_one_pp_save_and_reload(self):
        manager, _ = self.manager()
        p = manager.plan(UNIT, operations=(dict(op='add-activation-action-dialog', name='New action'),
                                          widget()), exclusive_project=True)
        result = manager.apply(p, backup_project='BACKUP').as_dict()
        self.assertTrue(result['saved'] and result['persistence_verified'])
        self.assertEqual(self.client.applications[202]['groups'][7]['levels'], (0, 1, 2))
        self.assertEqual(self.client.values['ProximityLevel'], '1')
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertEqual(self.client.commands.count('PROJECT COPY TEST BACKUP'), 1)
        self.assertEqual(self.client.commands.count('PROJECT CLOSE TEST'), 1)
        self.assertEqual(self.client.commands.count('PROJECT LOAD TEST'), 1)
        self.assertEqual(self.client.applications[56]['groups'][0]['tag'], 'Zulu')
        with self.assertRaises(NativeEdltParentError): manager.apply(p, backup_project='BACKUP')

    def test_stale_plan_refuses_before_backup_or_add(self):
        manager, _ = self.manager()
        p = manager.plan(UNIT, operations=(dict(op='add-activation-action-dialog'), widget()),
                         exclusive_project=True)
        self.client.applications[202]['groups'][7]['tag'] = 'Changed'
        with self.assertRaises(NativeEdltParentError): manager.apply(p, backup_project='BACKUP')
        self.assertFalse(any(c.startswith(('DBADD', 'PROJECT SAVE', 'PROJECT COPY', 'PP SAVE'))
                             for c in self.client.commands))

    def test_lost_pp_save_does_not_replay_delete_or_restore(self):
        manager, session = self.manager()
        p = manager.plan(UNIT, operations=(dict(op='add-activation-action-dialog'), widget()),
                         exclusive_project=True)
        session.save_error = RuntimeError('save receipt lost')
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(p, backup_project='BACKUP')
        result = caught.exception.result.as_dict()
        self.assertFalse(result['persistence_verified'])
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertFalse(any(c.startswith('DBDELETE') for c in self.client.commands))
        self.assertNotIn('PROJECT LOAD TEST', self.client.commands)


if __name__ == '__main__':
    unittest.main()
