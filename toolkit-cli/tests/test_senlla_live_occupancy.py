"""Authored source callback vectors on shared actual attributes."""
from types import SimpleNamespace
import unittest

from cbus_toolkit.senlla_lifecycle import (AttributeManager, FlashObject,
    ObjectReferenceAttribute)
from cbus_toolkit.senlla_live_occupancy import SENLLALiveOccupancy
from cbus_toolkit.sensors import SensorError


class Template(FlashObject):
    def __init__(self, identity):
        super().__init__(f'template:{identity}')
        self.identity = identity


class SENLLALiveOccupancyTests(unittest.TestCase):
    def setUp(self):
        self.unit = FlashObject('unit')
        self.templates = {value: Template(value) for value in range(59)}
        self.keys = []
        for index in range(8):
            actual = FlashObject(f'key:{index}')
            self.keys.append(SimpleNamespace(object=actual,
                template=ObjectReferenceAttribute(AttributeManager(actual))))
        self.events = []
        self.joined = self.broadcast_enabled = False
        self.block = None
        self.references = [set() for _ in range(8)]
        self.occupancy = SENLLALiveOccupancy(self.unit, self.keys,
            bank_refresh=self.bank_refresh,
            join_active=lambda occ: self.joined,
            broadcast_active=lambda occ: self.broadcast_enabled,
            broadcast_block=lambda occ: self.block,
            has_block=lambda occ, block: block in self.references[occ.index],
            set_template=self.set_template)

    def bank_refresh(self, occupancy):
        flags = tuple(occupancy.get_flag(flag) for flag in range(4))
        self.events.append((occupancy.index, flags, occupancy.object.depth))

    def set_template(self, occupancy, kind):
        self.keys[occupancy.index].template.set(self.templates[kind])

    def test_constructor_retains_shared_key_references_and_false_attributes(self):
        self.assertEqual(self.events, [])
        for index, occupancy in enumerate(self.occupancy.keys):
            self.assertIs(occupancy.input_key.value, self.keys[index].object)
            self.assertIs(occupancy._link.root, self.keys[index].template)
            self.assertIs(occupancy.manager.parent, occupancy.object)
            self.assertEqual(occupancy.snapshot()['flags'], [False] * 4)
            self.assertTrue(occupancy.decision_pending)
            self.assertTrue(occupancy.refresh_from_macro)
            self.assertFalse(occupancy.refreshing_flags)
            self.assertFalse(occupancy.refreshing_template)

    def test_equal_false_writes_emit_nothing_even_inside_owner_update(self):
        occupancy = self.occupancy.keys[0]
        occupancy.object.begin_update()
        for flag in range(4):
            self.occupancy.set_flag(0, flag, False)
        self.assertEqual(self.events, [])
        self.assertEqual(occupancy.object.depth, 1)
        occupancy.object.end_update()

    def test_nested_dark_clear_finishes_before_initiating_light_event(self):
        occupancy = self.occupancy.keys[0]
        self.occupancy.set_flag(0, 'DarkAndMovement', True)
        self.events.clear()
        transient = []
        occupancy.attribute('LightAndMovement').publisher.subscribe(
            lambda _: transient.append(tuple(occupancy.attribute(flag)._value for flag in range(4))))
        self.occupancy.set_flag(0, 'LightAndMovement', True)
        self.assertEqual(transient, [(True, True, False, False)])
        self.assertEqual(self.events, [(0, (True, False, False, False), 2),
                                      (0, (True, False, False, False), 1)])
        self.assertEqual(occupancy.object.depth, 0)

    def test_getter_rearms_exact_flag_and_its_actual_owner(self):
        occupancy = self.occupancy.keys[0]
        attr = occupancy.attribute('Sunset')
        # The source getter itself, distinct from inspecting constructor/cache.
        attr._published = occupancy.object._published = True
        self.assertFalse(self.occupancy.get_flag(0, 'Sunset'))
        self.assertFalse(attr._published)
        self.assertFalse(occupancy.object._published)
        self.assertIs(attr.manager, occupancy.manager)

    def test_macro_special34_and_nil_handler_decision_preserve_source_state(self):
        self.keys[0].template.set(self.templates[34])
        occupancy = self.occupancy.keys[0]
        self.assertEqual(self.events, [(0, (False, False, False, True), 1)])
        self.assertTrue(occupancy.decision_pending)
        self.assertTrue(occupancy.refresh_from_macro)
        self.events.clear()
        self.keys[0].template.set(self.templates[6])
        self.assertEqual(self.events, [])
        self.assertEqual(occupancy.snapshot()['flags'], [False, False, False, True])
        self.assertFalse(occupancy.decision_pending)
        self.assertFalse(occupancy.refresh_from_macro)

    def test_scene23_is_special_and_direct_quickset_preserves_decision_bytes(self):
        occupancy = self.occupancy.keys[0]
        self.keys[0].template.set(self.templates[34])
        self.keys[0].template.set(self.templates[6])
        self.events.clear()
        self.keys[0].template.set(self.templates[23])
        self.assertEqual(self.events, [(0, (False, False, False, False), 1)])
        self.assertTrue(occupancy.decision_pending)
        self.assertFalse(occupancy.refresh_from_macro)

        self.occupancy.set_flag(0, 'Sunset', True)
        self.events.clear()
        self.occupancy.refresh_flags(0)
        self.assertEqual(self.events, [(0, (False, False, False, False), 1)])
        self.assertTrue(occupancy.decision_pending)
        self.assertFalse(occupancy.refresh_from_macro)

    def test_smart_scene_predicate_rereads_current_template_in_source_order(self):
        occupancy = self.occupancy.keys[0]
        reads = []
        for name, attr in (('InputKey', occupancy.input_key),
                           ('Template', self.keys[0].template)):
            original = attr.resolve_change
            def observed(name=name, original=original):
                reads.append(name)
                original()
            attr.resolve_change = observed
        occupancy.refresh_flags = lambda: reads.append('QuickSet')
        for kind, scene_reads in ((29, 0), (23, 2), (24, 3), (25, 4), (6, 4)):
            with self.subTest(kind=kind):
                self.keys[0].template._value = self.templates[kind]
                occupancy.decision_pending = True
                occupancy.refresh_from_macro = False
                reads.clear()
                occupancy.refresh_flags_smart()
                expected = ['InputKey', 'Template', 'InputKey', 'Template']
                if scene_reads:
                    expected += ['InputKey'] + ['Template'] * scene_reads
                if kind != 6:
                    expected += ['QuickSet']
                self.assertEqual(reads, expected)

    def test_smart_decision_mutates_actual_bytes_and_quickset_rereads_template(self):
        occupancy = self.occupancy.keys[0]
        self.keys[0].template.set(self.templates[34])
        observed = []
        def decision(actual, mutable):
            self.assertIs(actual, occupancy)
            mutable.refresh_from_macro = True
            observed.append((actual.decision_pending, actual.refresh_from_macro,
                             actual.refreshing_flags))
            # Source callback can change CURRENT Template before QuickSet.
            actual.refreshing_template = True
            try:
                self.keys[0].template.set(self.templates[29])
            finally:
                actual.refreshing_template = False
        self.occupancy.install_macro_decision(decision)
        self.events.clear()
        self.keys[0].template.set(self.templates[6])
        self.assertEqual(observed, [(True, True, True)])
        self.assertEqual(self.events, [(0, (True, False, False, True), 1),
                                      (0, (True, False, False, False), 1)])
        self.assertFalse(occupancy.decision_pending)

    def test_broadcast_membership_precedes_active_and_skips_actual_decision(self):
        self.keys[0].template.set(self.templates[34])
        self.block = object()
        self.references[0].add(self.block)
        self.broadcast_enabled = True
        calls = []
        self.occupancy.install_macro_decision(lambda *args: calls.append(args))
        self.keys[0].template.set(self.templates[6])
        self.assertEqual(calls, [])
        self.assertEqual(self.occupancy.keys[0].snapshot()['flags'], [False] * 4)

    def test_joined_upper_keys_skip_smart_and_quickset(self):
        self.joined = True
        self.keys[4].template.set(self.templates[34])
        self.occupancy.refresh_flags(4)
        self.assertEqual(self.events, [])
        self.assertEqual(self.occupancy.keys[4].snapshot()['flags'], [False] * 4)
        self.assertTrue(self.occupancy.keys[4].decision_pending)

    def test_event_callback_runs_under_macro_guard_before_bank_refresh(self):
        calls = []
        def event(actual, decision):
            calls.append(('callback', actual.refreshing_flags, actual.object.depth))
            decision.refresh_template = True
        self.occupancy.install_event_template_callback(event)
        self.keys[0].template.set(self.templates[34])
        self.assertEqual(calls, [('callback', True, 1)])
        self.assertIs(self.keys[0].template.value, self.templates[34])
        self.assertEqual(self.events, [(0, (False, False, False, True), 1)])

    def test_event_refresh_template_sets29_with_source96_guard_and_then_bank(self):
        def event(actual, decision):
            decision.refresh_template = True
        self.occupancy.install_event_template_callback(event)
        observed = []
        self.keys[0].template.publisher.subscribe(lambda _: observed.append(
            self.occupancy.keys[0].refreshing_template))
        self.occupancy.set_flag(0, 'LightAndMovement', True)
        self.assertIs(self.keys[0].template.value, self.templates[29])
        self.assertEqual(observed, [True])
        self.assertEqual(self.events, [(0, (True, False, False, False), 1)])
        self.assertFalse(self.occupancy.keys[0].refreshing_template)

    def test_unresolved_installed_callback_preserves_committed_value_and_interrupts(self):
        def unresolved(actual, decision):
            raise SensorError('Actual native338 owner decision required')
        self.occupancy.install_event_template_callback(unresolved)
        with self.assertRaisesRegex(SensorError, 'native338'):
            self.occupancy.set_flag(0, 'Sunset', True)
        occupancy = self.occupancy.keys[0]
        self.assertTrue(occupancy.attribute('Sunset')._value)
        self.assertEqual(occupancy.attribute('Sunset').depth, 0)
        self.assertEqual(occupancy.manager.depth, 1)
        self.assertEqual(occupancy.object.depth, 1)
        self.assertEqual(self.events, [])
        self.assertTrue(self.occupancy.failed)
        with self.assertRaisesRegex(SensorError, 'cannot be resumed'):
            self.occupancy.set_flag(0, 'Sunset', False)

    def test_missing_installed_callbacks_refuse_instead_of_acknowledging(self):
        with self.assertRaises(SensorError):
            self.occupancy.install_macro_decision(None)
        with self.assertRaises(SensorError):
            self.occupancy.install_event_template_callback(None)
        self.assertFalse(self.occupancy.snapshot()['macro_decision_installed'])
        self.assertFalse(self.occupancy.snapshot()['event_template_installed'])

    def test_late_attachment_refuses_before_constructing_replacement_objects(self):
        self.keys[0].template.set(self.templates[16])
        with self.assertRaisesRegex(SensorError, 'before key PP'):
            SENLLALiveOccupancy(self.unit, self.keys, bank_refresh=self.bank_refresh,
                join_active=lambda occ: False, broadcast_active=lambda occ: False,
                broadcast_block=lambda occ: None, has_block=lambda occ, block: False,
                set_template=self.set_template)


if __name__ == '__main__':
    unittest.main()
