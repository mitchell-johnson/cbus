"""Literal actual-attribute owner regressions; no complete Show/Apply claim."""
import unittest

from cbus_toolkit.sensors import SensorError
import test_senlla_owner as owner_tests
from test_senlla_inherited_owner import snapshot


class SENLLAOwnerLiveOccupancyTest(unittest.TestCase):
    owner = owner_tests.SENLLAOwnerLoadTest.owner

    def observe_getters(self, attributes):
        reads = []
        for name, attribute in attributes:
            original = attribute.resolve_change
            def observed(name=name, original=original):
                reads.append(name)
                original()
            attribute.resolve_change = observed
        return reads

    def test_actual_occupancy_binds_before_banks_without_historical_activation(self):
        owner, _, _ = self.owner()
        runtime = owner.runtime
        self.assertTrue(runtime.defer_smart_observers)
        self.assertTrue(all(not key.smart.active for key in runtime.keys))
        self.assertIs(runtime.live_occupancy_dispatch, owner.occupancy)
        operations = [event['operation'] for event in runtime.events]
        self.assertLess(operations.index('actual_occupancy_constructor_bound'),
                        operations.index('live_bank_block_refresh'))
        self.assertNotIn('constructor_bank_link_activation', operations)
        retained = []
        for index, actual in enumerate(owner.occupancy.keys):
            self.assertIs(actual._key, runtime.keys[index])
            self.assertIs(actual.input_key._value, runtime.keys[index].object)
            self.assertIs(actual._link.root, runtime.keys[index].template)
            self.assertTrue(actual._link.active)
            self.assertIs(actual.manager.parent, actual.object)
            retained.append((actual.object, actual.manager, *actual.attributes.values()))
        owner.load()
        self.assertEqual(retained, [(actual.object, actual.manager, *actual.attributes.values())
                                     for actual in owner.occupancy.keys])
        self.assertTrue(all(not key.smart.active for key in runtime.keys))
        self.assertFalse(owner.snapshot()['complete_toolkit_save'])

    def test_complete_owner_refuses_early_historical_smart_activation(self):
        with self.assertRaisesRegex(SensorError, 'constructor-deferred'):
            self.owner(defer_smart_observers=False)

    def test_all_eight_raw_masks_use_actual_flags_and_current_bank_events(self):
        owner, _, raw = self.owner(snapshot(PIRLightMovement=[170],
            PIRDarkMovement=[204], PIRDark=[240], BlockAllocation=[1]*8,
            BlockBankSwitchActive=[1]*8))
        owner.load()
        self.assertEqual([owner.runtime.current_occupancy_flags(index) for index in range(8)], [
            (False,False,False,False), (True,False,False,False),
            (False,True,False,False), (False,False,True,False),
            (False,False,False,True), (True,False,False,True),
            (False,True,False,True), (False,False,True,True)])
        self.assertEqual([(bank.active._value, bank.allowed._value)
                          for bank in owner.late.live_banks.banks],
                         [(False,False)] + [(True,True)]*7)
        self.assertEqual(raw.expected['PIRLightMovement'], (170,))
        self.assertEqual(raw.expected['PIRDarkMovement'], (204,))
        self.assertEqual(raw.expected['PIRDark'], (240,))
        self.assertTrue(all(actual.object.depth == actual.manager.depth == 0
                            for actual in owner.occupancy.keys))

    def test_nested_flag_events_complete_on_same_banks_at_original_parent_depths(self):
        owner, _, _ = self.owner(snapshot(BlockAllocation=[1]+[0]*7))
        owner.load()
        occupancy = owner.occupancy.keys[0]
        bank = owner.late.live_banks.banks[0]
        owner.occupancy.set_flag(0, 1, True)
        bank.active.set(True)  # equal Allowed=false does not prohibit this.
        events = []
        original = owner.occupancy.bank_refresh
        def observed(actual):
            events.append((actual.object.depth,
                owner.runtime.current_occupancy_flags(actual.index),
                owner.runtime.unit.depth))
            return original(actual)
        owner.occupancy.bank_refresh = observed
        owner.occupancy.set_flag(0, 0, True)
        self.assertEqual(events, [
            (2,(True,False,False,False),0), (1,(True,False,False,False),0)])
        self.assertFalse(bank.active._value)
        self.assertFalse(bank.allowed._value)
        self.assertEqual(occupancy.object.depth, 0)

    def test_detached_inspection_does_not_rearm_live_flags(self):
        owner, _, _ = self.owner()
        actual = owner.occupancy.keys[0]
        flags = [actual.attribute(index) for index in range(4)]
        for flag in flags:
            flag._published = True
        actual.object._published = True
        inspected = owner.runtime.snapshot()
        inspected['live_occupancy']['keys'][0]['flags'][0] = True
        self.assertEqual(owner.runtime.current_occupancy_flags(0), (False,)*4)
        self.assertTrue(all(flag._published for flag in flags))
        self.assertTrue(actual.object._published)
        self.assertFalse(owner.runtime.get_occupancy_flag(0, 2))
        self.assertEqual([flag._published for flag in flags], [True,True,False,True])
        self.assertFalse(actual.object._published)

    def test_reassignment_uses_single_native_compatible_predicate_per_key(self):
        owner, _, _ = self.owner()
        owner.load()
        for key, flag in ((0,3),(1,0),(2,1),(3,2)):
            owner.occupancy.set_flag(key, flag, True)
        attributes = [((key,flag), actual.attribute(flag))
                      for key, actual in enumerate(owner.occupancy.keys) for flag in range(4)]
        reads = self.observe_getters(attributes)
        owner.runtime._refs_changed(7)
        self.assertEqual(reads, [
            (0,0),(0,1),(0,2),(0,3), (1,0), (2,0),(2,1),
            (3,0),(3,1),(3,2),
            *[(key,flag) for key in range(4,8) for flag in range(4)]])

    def test_event_template_callback_does_not_add_an_input_key_getter(self):
        owner, _, _ = self.owner()
        actual = owner.occupancy.keys[0]
        owner.occupancy.set_flag(0, 0, True)
        reads = self.observe_getters([('InputKey', actual.input_key)])
        # This is the exact guard installed by EventFlagChanged around its
        # source template refresh; no director decision is substituted.
        actual.refreshing_template = True
        try:
            actual.refresh_macro_from_flags()
        finally:
            actual.refreshing_template = False
        self.assertEqual(reads, ['InputKey'])
        self.assertIs(owner.runtime.keys[0].template._value, owner.runtime.templates[29])

    def test_actual_event_template_defaults_use_native_registry_commands(self):
        for flag, kind, commands in ((0,29,(7,0,0,0)), (1,30,(13,7,7,0)),
                                     (2,33,(13,7,0,7))):
            with self.subTest(flag=flag):
                owner, _, _ = self.owner()
                actual = owner.occupancy.keys[0]
                owner.occupancy.set_flag(0, flag, True)
                actual.refreshing_template = True
                try:
                    actual.refresh_macro_from_flags()
                finally:
                    actual.refreshing_template = False
                self.assertIs(owner.runtime.keys[0].template._value, owner.runtime.templates[kind])
                self.assertEqual(owner.runtime.keys[0].stages, commands)

    def test_broadcast_handler_reads_actual_maintenance_in_native_order(self):
        owner, _, _ = self.owner()
        runtime = owner.runtime
        banks = owner.late.live_banks
        reads = self.observe_getters([
            ('MaintActive', banks.maintenance_active), ('MaintBlock', banks.maintenance_block),
            ('BroadcastActive', runtime.broadcast_active), ('BroadcastBlock', runtime.broadcast_block)])
        runtime._broadcast_changed()
        # Each equal nil override setter publishes its block and runs the
        # newer actual bank listener. Its eight aggregate maintenance reads
        # are retained between the timer handler's current-row reads.
        self.assertEqual(reads, ['MaintActive'] +
            [name for _ in range(8) for name in ('BroadcastBlock', *('MaintBlock',)*8)] +
            ['BroadcastActive'])
        banks.maintenance_active.set(True)
        banks.maintenance_block.set(runtime.blocks[0].object)
        runtime.broadcast_block.set(runtime.blocks[0].object)
        runtime.broadcast_active.set(True)
        reads.clear()
        runtime._broadcast_changed()
        self.assertEqual(reads, ['MaintActive','BroadcastActive','MaintBlock','BroadcastBlock'])


if __name__ == '__main__':
    unittest.main()
