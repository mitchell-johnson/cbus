"""Literal shared bank/counter tests, without vendor execution or device I/O."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_key_events import SENLLAKeyEvents
from cbus_toolkit.senlla_lifecycle import (AttributeManager, BooleanAttribute,
    FlashObject, ObjectReferenceAttribute)
from cbus_toolkit.senlla_live_banks import SENLLALiveBanks
from cbus_toolkit.senlla_live_occupancy import SENLLALiveOccupancy
from cbus_toolkit.sensors import SensorError


FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-live-banks-source.json'


def owner():
    runtime = SENLLAKeyEvents.fresh()
    active = BooleanAttribute(runtime.unit_manager, name='unit.maintenance_active')
    block = ObjectReferenceAttribute(runtime.unit_manager, name='unit.maintenance_block')
    banks = SENLLALiveBanks(runtime, maintenance_active=active, maintenance_block=block)
    return runtime, banks


def flags(runtime, key, **changes):
    occupancy = list(runtime.graph.occupancy)
    occupancy[key] = replace(occupancy[key], **changes)
    runtime.graph = replace(runtime.graph, occupancy=tuple(occupancy))


class SENLLALiveBanksTest(unittest.TestCase):
    def test_bound_constructor_actual_attrs_and_same_identity(self):
        runtime, banks = owner()
        for index, bank in enumerate(banks.banks):
            with self.subTest(index=index):
                self.assertIs(bank.block.value, runtime.blocks[index].object)
                self.assertIs(bank.manager.parent, bank.object)
                self.assertTrue(bank.allowed.value)
                self.assertFalse(bank.active.value)
                self.assertFalse(bank.use_low.value)
                self.assertFalse(bank.use_high.value)
                self.assertEqual((bank.high_lux.value, bank.low_lux.value), (0, 0))
                self.assertEqual(bank.object.depth, 0)
                self.assertEqual(bank.manager.depth, 0)
                self.assertIs(bank.attributes['UseLowLevelGroup'], bank.use_low)
        self.assertIs(runtime.live_bank_dispatch, banks)
        self.assertEqual(runtime.unit.depth, 0)

    def test_external_store_publication_refreshes_during_unit_update(self):
        runtime, banks = owner()
        runtime.unit.begin_update()
        try:
            runtime.blocks[0].store1.set(5)
            runtime.blocks[0].store2.set(9)
        finally:
            runtime.unit.end_update()
        bank = banks.banks[0]
        self.assertEqual((bank.high_lux.value, bank.low_lux.value), (50, 90))
        bank.active.set(True)
        bank.off.set(True)
        self.assertEqual((bank.high_lux.value, bank.low_lux.value), (50, 50))
        self.assertEqual(runtime.blocks[0].store2.value, 5)
        self.assertTrue(bank.off.value)

    def test_high_low_actual_attributes_publish_at_parent_depth_one(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        observed = []
        callback = lambda attr: observed.append((attr.value, bank.object.depth,
                                                  bank.manager.depth))
        bank.high_lux.publisher.subscribe(callback)
        bank.high_lux.set(1234)
        self.assertEqual(observed, [(1234, 1, 1)])
        self.assertEqual(runtime.blocks[0].store1.value, 124)
        self.assertEqual(bank.high_lux.value, 1234)
        self.assertEqual(bank.object.depth, 0)

    def test_owned_store_feedback_skips_aggregate_and_no_deferred_refresh(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        bank.active.set(True)
        bank.allowed.set(False)
        bank.active.set(True)
        before = len([event for event in runtime.events
                      if event['operation'] == 'live_bank_block_refresh'])
        bank.low_lux.set(25)
        self.assertTrue(bank.active.value)
        self.assertFalse(bank.allowed.value)
        self.assertEqual((bank.low_lux.value, bank.high_lux.value), (25, 25))
        after = len([event for event in runtime.events
                     if event['operation'] == 'live_bank_block_refresh'])
        self.assertEqual(after, before)
        self.assertTrue(any(event['operation'] == 'live_bank_block_suppressed'
                            for event in runtime.events))

    def test_equal_allowed_false_preserves_raw_active_true(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        bank.allowed.set(False)
        bank.active.set(True)
        bank.allowed.set(False)
        self.assertTrue(bank.active.value)
        banks.maintenance_block.set(runtime.blocks[0].object)
        banks.maintenance_active.set(True)
        runtime.blocks[0].store1.set(7)
        self.assertTrue(bank.active.value)
        self.assertFalse(bank.allowed.value)

    def test_aggregate_reads_maintenance_before_capturing_both_stores(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        bank.active.set(True)
        banks.maintenance_block.set(runtime.blocks[0].object)
        banks.maintenance_active.set(True)
        # An actual observer changes Store2 during the Allowed publication.
        bank.allowed.publisher.subscribe(lambda _: runtime.blocks[0].store2.set(9))
        runtime.blocks[0].store1.set(5)
        self.assertFalse(bank.active.value)
        self.assertEqual((bank.high_lux.value, bank.low_lux.value), (50, 90))

    def test_captured_low_survives_high_callback_store2_change(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        seen = []
        def callback(attr):
            if not seen:
                seen.append(True)
                runtime.blocks[0].store2.set(3)
        bank.high_lux.publisher.subscribe(callback)
        runtime.blocks[0].object.begin_update()
        try:
            runtime.blocks[0].store1.set(5)
            runtime.blocks[0].store2.set(9)
        finally:
            runtime.blocks[0].object.end_update()
        self.assertEqual((bank.high_lux.value, bank.low_lux.value), (50, 90))
        self.assertEqual(runtime.blocks[0].store2.value, 9)

    def test_native_unbounded_signed_lux_saturation_and_observation_boundary(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        for value, expected in ((-1, 0), (0, 0), (1, 1), (9, 1), (10, 1),
                                (11, 2), (2550, 255), (2551, 255),
                                (-(1 << 31), 0), ((1 << 31) - 1, 255)):
            with self.subTest(value=value):
                bank.high_lux.set(value)
                self.assertEqual(runtime.blocks[0].store1.value, expected)
                self.assertEqual(bank.high_lux.value, value)
                self.assertEqual(banks.sync_graph_observation(), 0 <= value <= 2550)
        self.assertEqual(banks.snapshot()['banks'][0]['high_lux'], (1 << 31) - 1)
        with self.assertRaises(SensorError):
            bank.high_lux.set(True)

    def test_signed_store_loader_clamps_lux_and_preserves_equal_setter_guard(self):
        for store, raw, initial, lux, saved in (
                ('store1', -1, 0, 0, -1), ('store2', -1, 0, 0, -1),
                ('store1', 256, 0, 2550, 255), ('store2', 256, 0, 2550, 255),
                ('store1', 256, 2550, 2550, 256),
                ('store2', 256, 2550, 2550, 256)):
            with self.subTest(store=store, raw=raw, initial=initial):
                runtime, banks = owner()
                bank = banks.banks[0]
                attribute = bank.high_lux if store == 'store1' else bank.low_lux
                attribute.set(initial)
                getattr(runtime.blocks[0], store).set(raw)
                self.assertEqual(attribute.value, lux)
                self.assertEqual(getattr(runtime.blocks[0], store).value, saved)
                self.assertEqual(banks.sync_graph_observation(), 0 <= saved <= 255)
                self.assertEqual(banks.snapshot()['banks'][0][store], saved)

    def test_one_key_event_overrides_aggregate_other_key_blocking(self):
        runtime, banks = owner()
        runtime.keys[0].refs[:] = [0]
        runtime.keys[1].refs[:] = [0]
        flags(runtime, 0, sunset=True)
        flags(runtime, 1, light=True)
        banks.occupancy_bank_event(0, runtime)
        self.assertFalse(banks.banks[0].allowed.value)
        flags(runtime, 0, sunset=False)
        banks.occupancy_bank_event(0, runtime)
        self.assertTrue(banks.banks[0].allowed.value)
        runtime.blocks[0].store1.set(5)
        self.assertFalse(banks.banks[0].allowed.value)

    def test_event_rereads_flags_after_active_setter(self):
        runtime, banks = owner()
        runtime.keys[0].refs[:] = [0]
        bank = banks.banks[0]
        bank.active.set(True)
        flags(runtime, 0, sunset=True)
        bank.active.publisher.subscribe(lambda _: flags(runtime, 0, sunset=False))
        banks.occupancy_bank_event(0, runtime)
        self.assertFalse(bank.active.value)
        self.assertTrue(bank.allowed.value)

    def test_aggregate_and_event_native_flag_getter_orders(self):
        runtime, banks = owner()
        runtime.keys[0].refs[:] = [0]
        observed = []
        def read_flag(key, flag):
            observed.append(flag)
            return False
        runtime.get_occupancy_flag = read_flag
        banks.banks[0].refresh_allowed()
        self.assertEqual(observed, [1, 0, 2, 3])
        observed.clear()
        banks.occupancy_bank_event(0, runtime)
        self.assertEqual(observed, [0, 1, 2, 3, 0, 2, 1, 3])

    def test_native_short_circuit_rearms_only_actual_accessed_flag_attrs(self):
        runtime, banks = owner()
        runtime.keys[0].refs[:] = [0]
        actual = FlashObject('occupancy:0')
        manager = AttributeManager(actual)
        attributes = tuple(BooleanAttribute(manager, name=f'flag:{flag}')
                           for flag in range(4))
        attributes[0].set(True)
        seen = []
        def read_flag(key, flag):
            self.assertEqual(key, 0)
            seen.append(flag)
            return attributes[flag].value
        runtime.get_occupancy_flag = read_flag
        # Inspection is explicitly not a native predicate getter.
        runtime.current_occupancy_flags = lambda _: self.fail('eager flags inspection')
        for attr in attributes:
            attr._published = True
        actual._published = True
        banks.banks[0].refresh_allowed()
        self.assertEqual(seen, [1, 0])
        self.assertEqual([attr._published for attr in attributes],
                         [False, False, True, True])
        self.assertFalse(actual._published)
        seen.clear()
        for attr in attributes:
            attr._published = True
        banks.occupancy_bank_event(0, runtime)
        self.assertEqual(seen, [0, 0])
        self.assertEqual([attr._published for attr in attributes],
                         [False, True, True, True])
        self.assertFalse(banks.banks[0].allowed._value)

    def test_event_reads_actual_input_key_before_count_and_each_current_item(self):
        runtime, banks = owner()
        actual = FlashObject('occupancy:0')
        input_key = ObjectReferenceAttribute(AttributeManager(actual),
                                             name='occupancy:0.InputKey')
        input_key.set(runtime.keys[0].object)
        seen = []
        def current_key(index):
            seen.append(index)
            self.assertIs(input_key.value, runtime.keys[0].object)
            return runtime.keys[0]
        runtime.occupancy_input_key = current_key
        input_key._published = actual._published = True
        banks.occupancy_bank_event(0, runtime)
        self.assertEqual(seen, [0])
        self.assertFalse(input_key._published)
        self.assertFalse(actual._published)
        runtime.keys[0].refs[:] = [2, 0]
        seen.clear()
        banks.occupancy_bank_event(0, runtime)
        self.assertEqual(seen, [0, 0, 0])

    def test_actual_occupancy_constructed_before_banks_owns_flag_events(self):
        runtime = SENLLAKeyEvents.fresh(defer_smart_observers=True)
        occupancy = SENLLALiveOccupancy(runtime.unit, runtime.keys,
            bank_refresh=lambda current: banks.occupancy_bank_event(current.index, runtime),
            join_active=lambda current: False,
            broadcast_active=lambda current: runtime.broadcast_active.value,
            broadcast_block=lambda current: runtime.broadcast_block.value,
            has_block=lambda current, block: runtime._block_indices[block]
                in runtime.keys[current.index].refs,
            set_template=lambda current, kind: runtime.keys[current.index].template.set(
                runtime.templates[kind]))
        runtime.live_occupancy_dispatch = occupancy
        active = BooleanAttribute(runtime.unit_manager, name='unit.maintenance_active')
        block = ObjectReferenceAttribute(runtime.unit_manager, name='unit.maintenance_block')
        banks = SENLLALiveBanks(runtime, maintenance_active=active, maintenance_block=block)
        runtime.keys[0].refs[:] = [0]
        bank = banks.banks[0]
        bank.active.set(True)
        runtime._set_flag(0, 1, True)
        self.assertFalse(bank.active._value)
        self.assertFalse(bank.allowed._value)
        runtime._set_flag(0, 0, True)
        self.assertEqual(runtime.current_occupancy_flags(0), (True, False, False, False))
        self.assertEqual(runtime.graph.occupancy[0].flags, (False,) * 4)
        self.assertIs(runtime.occupancy_input_key(0), runtime.keys[0])
        self.assertIs(occupancy.keys[0].input_key._value, runtime.keys[0].object)
        self.assertFalse(runtime.keys[0].smart.active)
        current = occupancy.keys[0]
        for flag in range(4):
            current.attribute(flag)._published = True
        banks.occupancy_bank_event(0, runtime)
        self.assertEqual([current.attribute(flag)._published for flag in range(4)],
                         [False, True, True, True])

    def test_event_captures_count_but_rereads_later_current_reference(self):
        runtime, banks = owner()
        runtime.keys[0].refs[:] = [2, 0]
        flags(runtime, 0, sunset=True)
        banks.banks[2].active.set(True)
        banks.banks[2].active.publisher.subscribe(lambda _: runtime.keys[0].refs.__setitem__(1, 1))
        banks.occupancy_bank_event(0, runtime)
        self.assertFalse(banks.banks[2].allowed.value)
        self.assertFalse(banks.banks[1].allowed.value)
        self.assertTrue(banks.banks[0].allowed.value)

    def test_event_reference_removed_during_callback_refuses_native_index(self):
        runtime, banks = owner()
        runtime.keys[0].refs[:] = [0, 1]
        flags(runtime, 0, sunset=True)
        banks.banks[0].active.set(True)
        banks.banks[0].active.publisher.subscribe(lambda _: runtime.keys[0].refs.pop())
        with self.assertRaisesRegex(SensorError, 'ordinal became unavailable'):
            banks.occupancy_bank_event(0, runtime)

    def test_same_pointer_and_rebound_block_target_followers(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        bank.set_block(runtime.blocks[1].object)
        # Reference changes while bank updating do not synthesize a deferred
        # refresh. Subsequent ACTUAL target publication uses the new object.
        runtime.blocks[0].store1.set(5)
        self.assertEqual(bank.high_lux.value, 0)
        runtime.blocks[1].store1.set(7)
        self.assertEqual(bank.high_lux.value, 70)
        self.assertFalse(banks.sync_graph_observation())
        with self.assertRaises(SensorError):
            bank.set_block(object())

    def test_snapshot_and_graph_observation_do_not_rearm_publication_guards(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        bank.use_low.set(True)
        before = (bank.use_low._published, bank.object._published)
        detached = banks.snapshot()
        banks.sync_graph_observation()
        self.assertEqual((bank.use_low._published, bank.object._published), before)
        detached['banks'][0]['use_low'] = False
        self.assertTrue(bank.use_low._value)

    def test_actual_use_attributes_publish_without_bank_refresh(self):
        runtime, banks = owner()
        bank = banks.banks[0]
        observed = []
        bank.use_low.publisher.subscribe(lambda attr: observed.append(attr.value))
        bank.use_low.set(True)
        bank.use_low.set(True)
        self.assertEqual(observed, [True])
        self.assertEqual((runtime.blocks[0].store1.value, runtime.blocks[0].store2.value), (0, 0))

    def test_kernel_replays_recursive_flag_events_on_same_live_banks(self):
        runtime, banks = owner()
        runtime.keys[0].refs[:] = [0]
        runtime._set_flag(0, 1, True)
        before = len(runtime.events)
        runtime._set_flag(0, 0, True)
        events = [event['flags'] for event in runtime.events[before:]
                  if event['operation'] == 'occupancy_live_event']
        self.assertEqual(events, [[True, False, False, False]] * 2)
        self.assertEqual(runtime.current_occupancy_flags(0), (True, False, False, False))
        self.assertFalse(banks.banks[0].allowed.value)
        self.assertEqual(runtime.graph.banks[0].switch_allowed, banks.banks[0].allowed._value)

    def test_prekey_load_keeps_same_bank_attrs_and_actual_block_callbacks(self):
        from test_senlla_prekey import fresh, raw
        # Authored source/inherited executors isolate the prekey/bank seam;
        # this test does not establish native metadata or complete owner save.
        prekey, _ = fresh(raw(LightLevelStore1=[5] * 8, LightLevelStore2=[9] * 8))
        runtime = prekey.runtime
        maintenance = BooleanAttribute(runtime.unit_manager, name='unit.maintenance_active')
        maintenance_block = ObjectReferenceAttribute(runtime.unit_manager,
                                                       name='unit.maintenance_block')
        banks = SENLLALiveBanks(runtime, maintenance_active=maintenance,
                                maintenance_block=maintenance_block)
        retained = tuple((bank.object, bank.high_lux, bank.low_lux, bank.block)
                         for bank in banks.banks)
        result = prekey.load_to_key_blocks()
        self.assertIs(result, runtime)
        self.assertEqual(runtime.unit.depth, 1)
        for index, bank in enumerate(banks.banks):
            with self.subTest(index=index):
                self.assertEqual(retained[index], (bank.object, bank.high_lux,
                                                   bank.low_lux, bank.block))
                self.assertIs(bank.block._value, runtime.blocks[index].object)
                self.assertEqual((bank.high_lux.value, bank.low_lux.value), (50, 90))
                self.assertEqual(bank.object.depth, 0)

    def test_requires_same_unit_attrs_and_single_fresh_attachment(self):
        runtime, banks = owner()
        other = SENLLAKeyEvents.fresh()
        with self.assertRaises(SensorError):
            SENLLALiveBanks(other, maintenance_active=banks.maintenance_active,
                            maintenance_block=banks.maintenance_block)
        with self.assertRaises(SensorError):
            SENLLALiveBanks(runtime, maintenance_active=banks.maintenance_active,
                            maintenance_block=banks.maintenance_block)
        with self.assertRaises(SensorError):
            banks.occupancy_bank_event(0, other)

    def test_source_receipt_qualifies_component_and_native_acceptance(self):
        facts = json.loads(FIXTURE.read_text())
        self.assertFalse(facts['authority']['original_instruction_execution'])
        self.assertFalse(facts['authority']['native_form_verified'])
        self.assertFalse(facts['authority']['physical_acceptance'])
        self.assertGreater(len(facts['method_pins']), 25)
        self.assertEqual(facts['native_integer_attribute_domain'], [-(1 << 31), (1 << 31) - 1])


if __name__ == '__main__':
    unittest.main()
