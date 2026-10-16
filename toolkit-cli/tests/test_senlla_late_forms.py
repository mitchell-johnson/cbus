"""Authored late handler interactions on actual owned project objects."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cbus_toolkit.senlla_control_primitives import NativeTextRequired, SourceDisplayPreferences
from cbus_toolkit.senlla_inherited_owner import SENLLAInheritedOwner
from cbus_toolkit.senlla_late_forms import SENLLALateForms
from cbus_toolkit.senlla_late_unit import SENLLALateUnit
from cbus_toolkit.senlla_owner import SENLLAParameterJournal
from cbus_toolkit.senlla_project_bridge import SENLLAProjectBridge
from cbus_toolkit.sensors import SensorError
from test_senlla_inherited_owner import document, english_metadata_name, snapshot


class SENLLALateFormsTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'owned.xml'
        self.project = document(path)
        display = SourceDisplayPreferences(False, False)
        bridge = SENLLAProjectBridge.from_document(self.project, 254, 42,
            storage_path=path, metadata_name=english_metadata_name,
            creation_dispatch=lambda request, bridge, runtime: None,
            manager_order=lambda app, rows, runtime: tuple(row['address'] for row in rows),
            display_text=lambda actual, row, source, runtime: display.object_text(
                actual.kind, address=row['address'], tag_name=row['tag_name']))
        raw = snapshot(BlockAllocation=[1, 0, 0, 0, 0, 0, 0, 0])
        self.inherited = SENLLAInheritedOwner(raw, bridge)
        self.runtime = self.inherited.runtime
        self.late = SENLLALateUnit(self.inherited, SENLLAParameterJournal(raw))
        self.inherited.prekey.load_to_key_blocks()
        self.runtime.load_allocations(raw.expected['BlockAllocation'])
        self.runtime.finish_corekey_application_refresh()
        self.late.load_st7()
        self.late.load_surface()
        self.forms = SENLLALateForms(self.late)

    def group(self, application, address):
        app = self.runtime.get_source_application(application, source='authored.existing.manager')
        return self.runtime.get_source_group(app, address, source='authored.existing.group')

    def set(self, name, value):
        self.late.set(name, value, source='authored.control.setup')

    def test_broadcast_population_short_circuits_actual_managed_flag_getters(self):
        from test_senlla_owner import SENLLAOwnerLoadTest
        helper = SENLLAOwnerLoadTest()
        self.addCleanup(helper.doCleanups)
        for true_flag in range(4):
            with self.subTest(true_flag=true_flag):
                owner, _, _ = helper.owner(snapshot(BlockAllocation=[1] + [0] * 7))
                owner.load()
                runtime = owner.runtime
                runtime._set_flag(0, true_flag, True)
                forms = SENLLALateForms(owner.late)
                actual = runtime.live_occupancy_dispatch.key(0)
                for flag in range(4):
                    actual.attribute(flag)._published = True
                forms.populate_broadcast()
                self.assertEqual(forms.broadcast_collection.items,
                                 [block.object for block in runtime.blocks[1:]])
                self.assertEqual([(event['key'], event['flag']) for event in forms.events
                    if event['operation'] == 'occupancy_getter'],
                    [(0, flag) for flag in range(true_flag + 1)])
                # Actual getters rearm only the reached managed attributes.
                self.assertEqual([actual.attribute(flag)._published for flag in range(4)],
                                 [False] * (true_flag + 1) + [True] * (3 - true_flag))

    def test_scene_broadcast_filter_skips_managed_occupancy_predicate(self):
        self.runtime.set_template(0, 24)
        self.forms.populate_broadcast()
        self.assertNotIn(self.runtime.blocks[0].object, self.forms.broadcast_collection.items)
        self.assertFalse(any(event['operation'] == 'occupancy_getter' for event in self.forms.events))

    def test_scene_predicate_rereads_current_template_at_each_comparison(self):
        attribute = self.runtime.keys[0].template
        original_trace = attribute._trace
        for kind, count in ((None, 1), (23, 2), (24, 3), (25, 4), (16, 4)):
            with self.subTest(kind=kind):
                # Authored getter-only current state, not a template mutation workflow.
                attribute._value = None if kind is None else self.runtime.templates[kind]
                observed = []
                def trace(event):
                    if event.operation == 'resolve' and event.object_name == attribute.name:
                        observed.append(event)
                    original_trace(event)
                attribute._trace = trace
                self.assertEqual(self.forms._is_scene(0), kind in (23, 24, 25))
                self.assertEqual(len(observed), count)
        attribute._trace = original_trace

    def test_scene_predicate_refuses_nil_after_nonnull_initial_getter(self):
        attribute = self.runtime.keys[0].template
        attribute._value = self.runtime.templates[24]
        observed = []
        original_trace = attribute._trace
        def trace(event):
            if event.operation == 'resolve' and event.object_name == attribute.name:
                observed.append(event)
                if len(observed) == 2:
                    attribute._value = None
            original_trace(event)
        attribute._trace = trace
        with self.assertRaisesRegex(SensorError, 'CURRENT nil template'):
            self.forms._is_scene(0)
        self.assertEqual(len(observed), 2)

    def test_maintenance_uses_actual_bank_active_and_manager_order(self):
        first, second = self.group(56, 9), self.group(57, 8)
        self.late.live_banks.banks[3].active.set(True)
        self.forms.populate_maintenance()
        objects = [actual for actual, _ in self.forms.maintenance_combo.items]
        surface_group = self.late.attribute('BankSwitchHighGroup').value
        self.assertEqual(objects, [block.object for i, block in enumerate(self.runtime.blocks) if i != 3]
                         + [surface_group, first, second])
        self.assertEqual(self.forms.maintenance_combo.items[-2:],
                         [(first, 'Group 9 (Lighting)'), (second, 'Group 8 (57)')])
        self.assertEqual(self.forms.maintenance_combo.update_depth, 0)

    def test_broadcast_population_rereads_current_maintenance_after_each_append(self):
        self.set('LightLevelMaintActive', True)
        self.set('LightLevelMaintBlock', self.runtime.blocks[2].object)
        self.set('LightLevelBroadcastBlock', self.runtime.blocks[2].object)
        self.set('LightLevelBroadcastActive', True)
        observed = []
        def appended(collection):
            observed.append(len(collection.items))
            if len(collection.items) == 1:
                self.set('LightLevelMaintBlock', self.runtime.blocks[4].object)
        self.forms.broadcast_collection.publisher.subscribe(appended)
        self.forms.populate_broadcast()
        self.assertEqual(self.forms.broadcast_collection.items,
                         [block.object for i, block in enumerate(self.runtime.blocks) if i != 4])
        self.assertEqual(observed, list(range(1, 8)))
        self.assertTrue(self.forms.broadcast_combo.dirty)
        # Flash list change never pretends to have rendered actual string items.
        self.assertEqual(self.forms.broadcast_combo.items, [])

    def test_pec_collision_is_checked_when_maintenance_is_inactive(self):
        group = self.group(56, 7)
        self.set('JoinGroup', group)
        self.set('LightLevelMaintEnableGroup', group)
        self.set('LightLevelMaintEnableGroupOff', True)
        self.forms.maintenance_checked()
        self.assertEqual(self.late.attribute('LightLevelMaintEnableGroup').value.identity, (56, 255))
        self.assertFalse(self.late.attribute('LightLevelMaintEnableGroupOff').value)
        self.assertFalse(self.forms.pec_logic_enabled)
        getters = [row['field'] for row in self.forms.events if row['operation'] == 'unit_getter']
        self.assertNotIn('CorridorLinkActive', getters)

    def test_native_pec_active_getter_rearms_its_managed_attribute(self):
        self.set('LightLevelMaintEnableGroup', self.group(56, 7))
        active = self.late.attribute('LightLevelMaintActive')
        observed = []
        active.publisher.subscribe(lambda attr: observed.append(attr._value))
        self.set('LightLevelMaintActive', True)
        self.forms.pec_enable_changed()
        self.set('LightLevelMaintActive', False)
        self.assertEqual(observed, [True, False])

    def test_ordinary_combo_callback_allocates_same_selected_group_while_click_locked(self):
        group = self.group(57, 8)
        self.forms.populate_maintenance()
        combo = self.forms.maintenance_combo
        self.forms.install_maintenance_change()
        observed = []
        self.late.attribute('LightLevelMaintBlock').publisher.subscribe(
            lambda attr: observed.append((combo.click_depth, attr._value,
                                          self.runtime.blocks[0].group._value)))
        ordinal = next(i for i, (actual, _) in enumerate(combo.items) if actual is group)
        combo.set_index(ordinal)
        self.assertIs(self.runtime.blocks[0].group.value, group)
        self.assertTrue(self.runtime.blocks[0].secondary.value)
        self.assertIs(self.late.attribute('LightLevelMaintBlock').value, self.runtime.blocks[0].object)
        self.assertEqual(observed, [(1, self.runtime.blocks[0].object, group)])
        self.assertEqual(combo.click_depth, 0)

    def test_broadcast_handler_finishes_four_flag_setters_for_each_admitted_key(self):
        self.runtime.set_template(0, 16)
        self.set('LightLevelBroadcastBlock', self.runtime.blocks[0].object)
        self.set('LightLevelBroadcastActive', True)
        self.forms.broadcast_checked()
        rows = [row for row in self.forms.events if row['operation'] == 'occupancy_setter']
        self.assertEqual([(row['key'], row['flag']) for row in rows], [(0, i) for i in range(4)])

    def test_unresolved_windows_indexof_refuses_before_selection_and_fails_owner(self):
        self.forms.populate_maintenance()
        with self.assertRaises(NativeTextRequired):
            self.forms.setup_maintenance_selection()
        self.assertEqual(self.forms.maintenance_combo.item_index, -1)
        self.assertTrue(self.runtime.failed)


if __name__ == '__main__':
    unittest.main()
