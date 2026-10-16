"""Owning bank callback composition; synthetic data, no device I/O."""
from dataclasses import FrozenInstanceError, astuple, replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_bank_graph import SENLLABankGraph
from cbus_toolkit.senlla_banks import BankState
from cbus_toolkit.senlla_key_references import SENLLAKeyReferences
from cbus_toolkit.senlla_occupancy import OccupancyState, occupancy_parameters
from cbus_toolkit.senlla_surface_banks import fresh_surface_banks
from cbus_toolkit.sensors import SensorError


FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-bank-graph-source.json'


def references(*rows):
    return SENLLAKeyReferences((*rows, *((),) * (8 - len(rows))))


def with_bank(graph, index, bank):
    banks = list(graph.banks)
    banks[index] = bank
    return replace(graph, banks=banks)


PRE_DIRECTOR = {'event_template_handler_installed': False}


class SENLLABankGraphTests(unittest.TestCase):
    def test_fresh_bound_constructor_and_derived_source_authority(self):
        facts = json.loads(FIXTURE.read_text())
        graph = SENLLABankGraph.fresh()
        self.assertEqual(graph.as_dict()['banks'][0], facts['fresh_bound_bank'])
        self.assertEqual(len(facts['sources']), 3)
        self.assertGreater(len(facts['method_pins']), 100)
        self.assertEqual(graph.references.ordered_references, ((),) * 8)
        self.assertEqual(graph.occupancy, (OccupancyState(),) * 8)
        self.assertFalse(graph.maintenance_active)
        self.assertIsNone(graph.maintenance_block)

    def test_constructor_store_load_then_later_raw_activation(self):
        graph = SENLLABankGraph.fresh().load_stored_levels([5] * 8, [9] * 8)
        self.assertEqual(astuple(graph.banks[0]), (50, 90, False, True, False, 5, 9))
        graph = graph.load_active_and_enable_off([True] * 8, [True] * 8)
        self.assertEqual(astuple(graph.banks[0]), (50, 50, True, True, True, 5, 5))

    def test_template_sunset_before_raw_bank_then_equal_raw_flag(self):
        graph = SENLLABankGraph.fresh().load_stored_levels([5] * 8, [9] * 8)
        graph = graph.with_references(references((0,)))
        graph = graph.macro_changed(0, 34, decision_handler_installed=False)
        self.assertEqual((graph.banks[0].switch_active, graph.banks[0].switch_allowed),
                         (False, False))
        graph = graph.load_active_and_enable_off([True] * 8, [False] * 8)
        graph = graph.load_raw_occupancy(0, 0, 1)
        self.assertEqual(astuple(graph.banks[0]), (50, 50, True, False, False, 5, 5))
        self.assertEqual(occupancy_parameters(graph.occupancy)['PIRDark'], [1])

    def test_unequal_raw_clear_after_template_sunset_allows_loaded_active_bank(self):
        graph = SENLLABankGraph.fresh().with_references(references((0,)))
        graph = graph.macro_changed(0, 34, decision_handler_installed=False)
        graph = graph.load_active_and_enable_off([True] * 8, [False] * 8)
        graph = graph.load_raw_occupancy(0, 0, 0)
        self.assertEqual((graph.banks[0].switch_active, graph.banks[0].switch_allowed),
                         (True, True))

    def test_direct_this_key_event_can_allow_bank_despite_another_occupied_key(self):
        graph = SENLLABankGraph.fresh().with_references(references((0,), (0,)))
        graph = graph.macro_changed(0, 29, decision_handler_installed=False)
        graph = graph.macro_changed(1, 34, decision_handler_installed=False)
        graph = graph.apply_occupancy_transition(1, graph.occupancy[1].load_raw(False, False, False))
        self.assertTrue(graph.banks[0].switch_allowed)
        self.assertFalse(graph.aggregate_allowed(0))
        graph = graph.write_stored_level(0, 1, 5)
        self.assertFalse(graph.banks[0].switch_allowed)

    def test_added_occupied_reference_with_equal_flags_does_not_refresh_bank(self):
        graph = SENLLABankGraph.fresh().macro_changed(0, 29, decision_handler_installed=False)
        graph = graph.load_active_and_enable_off([True] * 8, [False] * 8)
        graph = graph.with_references(references((0,)))
        graph = graph.macro_changed(0, 29, decision_handler_installed=False)
        self.assertEqual((graph.banks[0].switch_active, graph.banks[0].switch_allowed),
                         (True, True))
        self.assertFalse(graph.aggregate_allowed(0))
        graph = graph.block_changed(0)
        self.assertEqual((graph.banks[0].switch_active, graph.banks[0].switch_allowed),
                         (False, False))

    def test_added_reference_then_unequal_macro_flags_deliver_direct_event(self):
        graph = SENLLABankGraph.fresh().load_active_and_enable_off([True] * 8, [False] * 8)
        graph = graph.with_references(references((0,)))
        graph = graph.macro_changed(0, 29, decision_handler_installed=False)
        self.assertEqual((graph.banks[0].switch_active, graph.banks[0].switch_allowed),
                         (False, False))

    def test_reference_quickset_clears_flags_despite_smart_refresh_disabled(self):
        graph = SENLLABankGraph.fresh().with_references(references((0,)))
        graph = graph.macro_changed(0, 16, decision_handler_installed=False)
        graph = graph.load_raw_occupancy(0, 0, 1)
        self.assertFalse(graph.occupancy[0].refresh_from_macro)
        smart = graph.macro_changed(0, 16, decision_handler_installed=False)
        self.assertTrue(smart.occupancy[0].sunset)
        direct = graph.refresh_event_flags(0, 16, join_active=False, **PRE_DIRECTOR)
        self.assertFalse(direct.occupancy[0].sunset)
        self.assertTrue(direct.banks[0].switch_allowed)
        self.assertEqual((direct.occupancy[0].decision_pending, direct.occupancy[0].refresh_from_macro),
                         (graph.occupancy[0].decision_pending, graph.occupancy[0].refresh_from_macro))

    def test_reference_quickset_nil_and_join_guard_preserve_flags(self):
        graph = SENLLABankGraph.fresh().with_references(references((0,), (), (), (), (1,)))
        graph = graph.load_raw_occupancy(0, 0, 17)
        self.assertEqual(graph.refresh_event_flags(0, None, join_active=False, **PRE_DIRECTOR), graph)
        self.assertEqual(graph.refresh_event_flags(4, 16, join_active=True, **PRE_DIRECTOR), graph)
        direct = graph.refresh_event_flags(0, 16, join_active=True, **PRE_DIRECTOR)
        self.assertFalse(direct.occupancy[0].sunset)
        self.assertTrue(direct.occupancy[4].sunset)
        self.assertTrue(direct.banks[0].switch_allowed)
        self.assertFalse(direct.banks[1].switch_allowed)

    def test_installed_reference_handler_requires_owner_replay(self):
        graph = SENLLABankGraph.fresh().with_references(references((0,)))
        graph = graph.load_raw_occupancy(0, 0, 1)
        with self.assertRaises(SensorError):
            graph.refresh_event_flags(0, 16, join_active=False,
                                      event_template_handler_installed=True)
        equal = graph.refresh_event_flags(0, 34, join_active=False,
                                         event_template_handler_installed=True)
        self.assertEqual(equal, graph)

    def test_removed_reference_is_absent_from_next_direct_flag_event(self):
        graph = SENLLABankGraph.fresh().with_references(references((0, 2)))
        graph = graph.macro_changed(0, 29, decision_handler_installed=False)
        graph = graph.with_references(references((2,)))
        graph = graph.apply_occupancy_transition(0, graph.occupancy[0].load_raw(False, False, False))
        self.assertFalse(graph.banks[0].switch_allowed)
        self.assertTrue(graph.banks[2].switch_allowed)
        self.assertTrue(graph.aggregate_allowed(0))

    def test_maintenance_assignment_leaves_permission_until_actual_block_event(self):
        graph = SENLLABankGraph.fresh().load_active_and_enable_off([True] * 8, [False] * 8)
        graph = graph.with_maintenance(active=True, block=0)
        self.assertEqual((graph.banks[0].switch_active, graph.banks[0].switch_allowed),
                         (True, True))
        graph = graph.block_changed(0)
        self.assertEqual((graph.banks[0].switch_active, graph.banks[0].switch_allowed),
                         (False, False))
        self.assertTrue(graph.banks[1].switch_active)

    def test_empty_direct_event_uses_loaded_maintenance_context(self):
        graph = SENLLABankGraph.fresh().with_references(references((0,)))
        graph = graph.macro_changed(0, 34, decision_handler_installed=False)
        graph = graph.refresh_allowed(0).load_active_and_enable_off([True] * 8, [False] * 8)
        # Establish a true Allowed state to distinguish its unequal callback.
        graph = with_bank(graph, 0, replace(graph.banks[0], switch_allowed=True))
        graph = graph.with_maintenance(active=True, block=0)
        graph = graph.apply_occupancy_transition(0, graph.occupancy[0].load_raw(False, False, False))
        self.assertEqual((graph.banks[0].switch_active, graph.banks[0].switch_allowed),
                         (False, False))

    def test_owned_lux_writes_do_not_recompute_aggregate_permission(self):
        graph = SENLLABankGraph.fresh().with_maintenance(active=True, block=0)
        graph = with_bank(graph, 0, BankState(50, 50, True, True, False, 5, 5))
        graph = graph.set_low_lux(0, 0).set_high_lux(0, 2550)
        self.assertEqual(astuple(graph.banks[0]), (2550, 0, True, True, False, 255, 0))
        self.assertFalse(graph.aggregate_allowed(0))
        graph = graph.write_stored_level(0, 1, 254)
        self.assertEqual(astuple(graph.banks[0]), (2540, 0, False, False, False, 254, 0))

    def test_equal_store_write_has_no_callback_and_equal_allowed_preserves_active(self):
        graph = SENLLABankGraph.fresh().with_maintenance(active=True, block=0)
        graph = with_bank(graph, 0, BankState(50, 50, True, False, False, 5, 5))
        self.assertIs(graph.write_stored_level(0, 1, 5), graph)
        self.assertTrue(graph.block_changed(0).banks[0].switch_active)

    def test_owned_store_feedback_literals_and_fresh_surface_composition(self):
        facts = json.loads(FIXTURE.read_text())
        for vector in facts['owned_lux_literals']:
            with self.subTest(case=vector['id']):
                graph = with_bank(SENLLABankGraph.fresh(), 0, BankState(*vector['before']))
                graph = graph.with_maintenance(active=vector['maintenance_active'],
                                               block=vector['maintenance_block'])
                for kind, *args in vector['operations']:
                    if kind == 'store':
                        graph = graph.write_stored_level(0, *args)
                    else:
                        graph = getattr(graph, f'set_{kind}_lux')(0, *args)
                self.assertEqual(list(astuple(graph.banks[0])), vector['after'])
        graph = with_bank(SENLLABankGraph.fresh(), 0, BankState(50, 50, True, False, False, 5, 5))
        graph = graph.set_low_lux(0, 0)
        frame = fresh_surface_banks(graph.banks, use_low=[True] + [False] * 7,
                                    use_high=[False] * 8)
        self.assertEqual(astuple(frame.banks[0]), (2550, 0, True, False, False, 255, 0))

    def test_graph_state_and_exports_are_detached(self):
        banks = list(SENLLABankGraph.fresh().banks)
        states = [OccupancyState()] * 8
        graph = SENLLABankGraph(banks, states, references((2, 0)))
        banks[0] = BankState(10, 0, True, True, False, 1, 0)
        states[0] = OccupancyState(sunset=True)
        exported = graph.as_dict()
        exported['banks'][0]['store1'] = 255
        exported['references']['ordered_references'][0].clear()
        parameters = graph.parameters()
        parameters['LightLevelStore1'][0] = 255
        self.assertEqual(graph.parameters()['LightLevelStore1'], [0] * 8)
        self.assertEqual(graph.references.ordered_references[0], (2, 0))
        self.assertFalse(graph.occupancy[0].sunset)
        with self.assertRaises(FrozenInstanceError):
            graph.maintenance_active = True

    def test_invalid_domains_context_and_transitions_refuse(self):
        graph = SENLLABankGraph.fresh()
        for index in (-1, 8, True, 0.0):
            with self.subTest(index=index), self.assertRaises(SensorError):
                graph.block_changed(index)
        for store, value in ((0, 1), (3, 1), (True, 1), (1, -1), (2, 256), (1, True)):
            with self.subTest(store=store, value=value), self.assertRaises(SensorError):
                graph.write_stored_level(0, store, value)
        for kwargs in ({'active': 1, 'block': 0}, {'active': True, 'block': 8},
                       {'active': False, 'block': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SensorError):
                graph.with_maintenance(**kwargs)
        for changes in ({'banks': graph.banks[:7]}, {'occupancy': [None] * 8}, {'references': None}):
            with self.subTest(changes=changes), self.assertRaises(SensorError):
                replace(graph, **changes)
        for args in ((-1, 0, 0), (0, 256, 0), (0, 0, True)):
            with self.subTest(args=args), self.assertRaises(SensorError):
                graph.load_raw_occupancy(*args)
        with self.assertRaises(SensorError):
            graph.apply_occupancy_transition(0, None)
        with self.assertRaises(SensorError):
            graph.load_stored_levels([True] * 8, [0] * 8)
        with self.assertRaises(SensorError):
            graph.load_active_and_enable_off([1] * 8, [False] * 8)
        for template, join in ((True, False), (59, False), (16, 1)):
            with self.subTest(template=template, join=join), self.assertRaises(SensorError):
                graph.refresh_event_flags(0, template, join_active=join, **PRE_DIRECTOR)
        with self.assertRaises(SensorError):
            graph.refresh_event_flags(0, 16, join_active=False,
                                      event_template_handler_installed=0)


if __name__ == '__main__':
    unittest.main()
