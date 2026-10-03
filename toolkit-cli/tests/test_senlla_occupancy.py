"""Independent literal occupancy callbacks; no native instructions or I/O."""
from dataclasses import FrozenInstanceError, astuple
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_banks import BankState
from cbus_toolkit.senlla_occupancy import (
    OccupancyBankEvent, OccupancyState, OccupancyTransition,
    apply_bank_events, occupancy_parameters,
)
from cbus_toolkit.sensors import SensorError


FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-occupancy-transition-source.json'


def facts():
    return json.loads(FIXTURE.read_text())


def snapshots(result):
    return [list(event.flags) for event in result.bank_events]


def banks(*, active=True, allowed=True):
    return tuple(BankState(100, 50, active, allowed, False, 10, 5) for _ in range(8))


class SENLLAOccupancyTests(unittest.TestCase):
    def test_source_fixture_is_qualified_and_pinned(self):
        source = facts()
        self.assertEqual(len(source['method_pins']), 27)
        self.assertEqual(source['authority']['source_exe_sha256'],
                         '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab')
        self.assertFalse(source['authority']['original_instruction_execution'])
        self.assertFalse(source['authority']['native_form_verified'])
        self.assertFalse(source['authority']['physical_acceptance'])
        self.assertEqual(source['rules']['special_macro_types'], [29, 30, 33, 34])
        self.assertEqual(source['rules']['macro_enum_domain'], [0, 58])
        self.assertTrue(source['rules']['direct_GUI338_edits_excluded'])

    def test_eight_literal_fresh_raw_vectors(self):
        vectors = facts()['literal_plain_raw_vectors']
        self.assertEqual(len(vectors), 8)
        for vector in vectors:
            with self.subTest(raw=vector['raw_L_D_S']):
                result = OccupancyState().load_raw(*map(bool, vector['raw_L_D_S']))
                self.assertEqual(list(result.state.flags), vector['final_flags'])
                self.assertEqual(snapshots(result), vector['bank_event_flags'])
                self.assertEqual(astuple(result.state)[4:], (True, True))

    def test_eight_literal_template34_raw_vectors(self):
        vectors = facts()['literal_template34_raw_vectors']
        ordinary = OccupancyState().macro_changed(16, decision_handler_installed=False).state
        seeded = ordinary.macro_changed(34, decision_handler_installed=False).state
        self.assertEqual(astuple(seeded), (False, False, False, True, True, False))
        self.assertEqual(len(vectors), 8)
        for vector in vectors:
            with self.subTest(raw=vector['raw_L_D_S']):
                result = seeded.load_raw(*map(bool, vector['raw_L_D_S']))
                self.assertEqual(list(result.state.flags), vector['final_flags'])
                self.assertEqual(snapshots(result), vector['post_bank_load_event_flags'])
                self.assertEqual(astuple(result.state)[4:], (True, False))

    def test_twenty_literal_smart_macro_vectors(self):
        vectors = facts()['literal_macro_vectors']
        self.assertEqual(len(vectors), 20)
        for vector in vectors:
            with self.subTest(vector=vector['id']):
                state = OccupancyState(*vector['before'])
                result = state.macro_changed(
                    vector['template'],
                    decision_handler_installed=vector['decision_handler_installed'],
                    macro_decision=vector['macro_decision'],
                    broadcast_key=vector['broadcast_key'])
                self.assertEqual(list(astuple(result.state)), vector['after'])
                self.assertEqual(snapshots(result), vector['bank_event_flags'])
                self.assertEqual(list(astuple(state)), vector['before'])

    def test_raw_any_transition_emits_nested_clear_and_duplicate_final(self):
        state = OccupancyState(light=True, sunset=True, decision_pending=False,
                               refresh_from_macro=False)
        result = state.load_raw(True, True, False)
        self.assertEqual(snapshots(result), [[False, False, True, True],
                                            [False, False, True, True],
                                            [False, False, True, False]])
        self.assertEqual(astuple(result.state), (False, False, True, False, False, False))

    def test_raw_light_transition_emits_nested_clear_and_duplicate_final(self):
        for field in ('dark', 'any_movement'):
            with self.subTest(prior=field):
                result = OccupancyState(**{field: True}).load_raw(True, False, False)
                self.assertEqual(snapshots(result), [[True, False, False, False]] * 2)

    def test_equal_false_raw_flags_emit_no_bank_refresh(self):
        result = OccupancyState().load_raw(False, False, False)
        self.assertEqual(result.state, OccupancyState())
        self.assertEqual(result.bank_events, ())

    def test_nil_template_preserves_identity_and_does_not_request_decision(self):
        state = OccupancyState(any_movement=True, sunset=True)
        result = state.macro_changed(None, decision_handler_installed=True)
        self.assertIs(result.state, state)
        self.assertEqual(result.bank_events, ())

    def test_missing_307d_decision_refuses_before_state_or_bank_mutation(self):
        state = OccupancyState(light=True, sunset=True)
        for template in (0, 16, 26, 31, 32, 58):
            with self.subTest(template=template), self.assertRaisesRegex(SensorError, '307d'):
                state.macro_changed(template, decision_handler_installed=True)
        self.assertEqual(astuple(state), (True, False, False, True, True, True))

    def test_explicit_handler_flag_is_required_for_macro_call(self):
        with self.assertRaises(TypeError):
            OccupancyState().macro_changed(16)

    def test_ordinary_without_pending_decision_uses_existing_refresh_flag(self):
        preserved = OccupancyState(light=True, decision_pending=False, refresh_from_macro=False)
        cleared = OccupancyState(light=True, decision_pending=False, refresh_from_macro=True)
        self.assertEqual(preserved.macro_changed(16, decision_handler_installed=True).state, preserved)
        result = cleared.macro_changed(16, decision_handler_installed=True)
        self.assertEqual(result.state.flags, (False,) * 4)
        self.assertEqual(snapshots(result), [[False] * 4])

    def test_parameters_are_literal_eight_key_masks_and_detached(self):
        states = [OccupancyState().load_raw(*map(bool, vector['raw_L_D_S'])).state
                  for vector in facts()['literal_plain_raw_vectors']]
        result = occupancy_parameters(states)
        self.assertEqual(result, {'PIRLightMovement': [170],
                                  'PIRDarkMovement': [204],
                                  'PIRDark': [240]})
        self.assertEqual(result, facts()['literal_packed_parameters'])
        result['PIRLightMovement'][0] = 0
        self.assertEqual(occupancy_parameters(states)['PIRLightMovement'][0], 170)

    def test_state_transition_and_views_are_immutable_or_detached(self):
        result = OccupancyState().load_raw(True, False, True)
        for item, name, value in ((result.state, 'light', False),
                                  (result, 'bank_events', ()),
                                  (result.bank_events[0], 'flags', (False,) * 4)):
            with self.subTest(item=type(item).__name__), self.assertRaises(FrozenInstanceError):
                setattr(item, name, value)
        view = result.as_dict()
        view['state']['flags'][0] = False
        view['bank_events'][0][0] = False
        self.assertTrue(result.state.light)
        self.assertTrue(result.bank_events[0].flags[0])

    def test_occupied_event_clears_active_when_allowed_already_false(self):
        before = banks(allowed=False)
        event = OccupancyBankEvent((False, False, False, True))
        after = apply_bank_events(before, (3, 1), (event,),
                                  maintenance_active=False, maintenance_block=None)
        self.assertFalse(after[3].switch_active)
        self.assertFalse(after[1].switch_active)
        self.assertTrue(after[0].switch_active)
        self.assertFalse(after[3].switch_allowed)
        self.assertTrue(before[3].switch_active)

    def test_false_flag_event_allows_without_reactivating_or_clamping(self):
        before = banks(allowed=False)
        after = apply_bank_events(before, (1,), (OccupancyBankEvent((False,) * 4),),
                                  maintenance_active=False, maintenance_block=None)
        self.assertTrue(after[1].switch_active)
        self.assertTrue(after[1].switch_allowed)
        self.assertEqual((after[1].store1, after[1].store2), (10, 5))

    def test_each_event_notifies_banks_in_supplied_reference_order(self):
        notifications = []

        class ObservedBank(BankState):
            def set_active(self, value):
                if value != self.switch_active:
                    notifications.append(('active', self.store1, value))
                return super().set_active(value)

            def set_allowed(self, value):
                if value != self.switch_allowed:
                    notifications.append(('allowed', self.store1, value))
                return super().set_allowed(value)

        before = tuple(ObservedBank(100, 50, True, True, False, i, 5) for i in range(8))
        events = (OccupancyBankEvent((True, False, False, False)),
                  OccupancyBankEvent((False,) * 4))
        after = apply_bank_events(before, (3, 1), events,
                                  maintenance_active=False, maintenance_block=None)
        self.assertEqual(notifications, [('active', 3, False), ('allowed', 3, False),
                                         ('active', 1, False), ('allowed', 1, False),
                                         ('allowed', 3, True), ('allowed', 1, True)])
        self.assertFalse(after[3].switch_active)
        self.assertTrue(after[3].switch_allowed)

    def test_empty_event_for_later_unoccupied_key_does_not_aggregate_or_allow(self):
        occupied = OccupancyState().load_raw(True, False, False)
        after = apply_bank_events(banks(), (0,), occupied.bank_events,
                                  maintenance_active=False, maintenance_block=None)
        unoccupied = OccupancyState().load_raw(False, False, False)
        after = apply_bank_events(after, (0,), unoccupied.bank_events,
                                  maintenance_active=False, maintenance_block=None)
        self.assertFalse(after[0].switch_active)
        self.assertFalse(after[0].switch_allowed)

    def test_explicit_later_clear_can_allow_shared_bank_without_aggregate(self):
        occupied = OccupancyState().load_raw(True, False, False)
        after = apply_bank_events(banks(), (0,), occupied.bank_events,
                                  maintenance_active=False, maintenance_block=None)
        clear = OccupancyState(sunset=True).load_raw(False, False, False)
        after = apply_bank_events(after, (0,), clear.bank_events,
                                  maintenance_active=False, maintenance_block=None)
        self.assertFalse(after[0].switch_active)
        self.assertTrue(after[0].switch_allowed)

    def test_template34_equal_sunset_after_raw_bank_write_leaves_active(self):
        seeded = OccupancyState().macro_changed(16, decision_handler_installed=False).state
        seed = seeded.macro_changed(34, decision_handler_installed=False)
        loaded = apply_bank_events(banks(active=False), (0,), seed.bank_events,
                                   maintenance_active=False, maintenance_block=None)
        loaded = tuple(bank.load_active_and_enable_off(True, False) for bank in loaded)
        equal = seed.state.load_raw(False, False, True)
        after = apply_bank_events(loaded, (0,), equal.bank_events,
                                  maintenance_active=False, maintenance_block=None)
        self.assertTrue(after[0].switch_active)
        self.assertFalse(after[0].switch_allowed)

    def test_template34_false_sunset_after_raw_bank_write_only_allows(self):
        seeded = OccupancyState(sunset=True, refresh_from_macro=False)
        result = seeded.load_raw(False, False, False)
        after = apply_bank_events(banks(allowed=False), (0,), result.bank_events,
                                  maintenance_active=False, maintenance_block=None)
        self.assertTrue(after[0].switch_active)
        self.assertTrue(after[0].switch_allowed)

    def test_maintenance_dependency_is_per_declared_matching_block(self):
        after = apply_bank_events(banks(), (2, 3), (OccupancyBankEvent((False,) * 4),),
                                  maintenance_active=True, maintenance_block=3)
        self.assertTrue(after[2].switch_active)
        self.assertTrue(after[2].switch_allowed)
        self.assertFalse(after[3].switch_active)
        self.assertFalse(after[3].switch_allowed)

    def test_empty_references_and_events_preserve_all_supplied_banks(self):
        before = banks()
        for refs, events in (((), (OccupancyBankEvent((True, False, False, False)),)),
                             ((7, 0), ())):
            with self.subTest(refs=refs):
                after = apply_bank_events(before, refs, events,
                                          maintenance_active=True, maintenance_block=None)
                self.assertTrue(all(a is b for a, b in zip(after, before)))

    def test_invalid_state_flag_and_macro_domains_refuse(self):
        for name in ('light', 'dark', 'any_movement', 'sunset',
                     'decision_pending', 'refresh_from_macro'):
            for value in (0, 1, None, 'false'):
                with self.subTest(name=name, value=value), self.assertRaises(SensorError):
                    OccupancyState(**{name: value})
        with self.assertRaises(SensorError):
            OccupancyState(light=True, any_movement=True)
        for args in ((1, False, False), (False, 'false', False), (False, False, None)):
            with self.subTest(args=args), self.assertRaises(SensorError):
                OccupancyState().load_raw(*args)
        for template in (-1, 59, True, 1.0, '16'):
            with self.subTest(template=template), self.assertRaises(SensorError):
                OccupancyState().macro_changed(template, decision_handler_installed=False)
        for kwargs in ({'decision_handler_installed': 0},
                       {'decision_handler_installed': True, 'macro_decision': 1},
                       {'decision_handler_installed': False, 'macro_decision': True},
                       {'decision_handler_installed': False, 'broadcast_key': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SensorError):
                OccupancyState().macro_changed(16, **kwargs)

    def test_invalid_events_references_dependencies_and_counts_refuse(self):
        for flags in ([False] * 4, (False,) * 3, (False, False, False, 0)):
            with self.subTest(flags=flags), self.assertRaises(SensorError):
                OccupancyBankEvent(flags)
        for refs in ([0, 0], [8], [-1], [True], list(range(9)), None):
            with self.subTest(refs=refs), self.assertRaises(SensorError):
                apply_bank_events(banks(), refs, (), maintenance_active=False, maintenance_block=None)
        for supplied in (banks()[:7], banks() + banks()[:1], [object()] * 8, None):
            with self.subTest(banks=supplied), self.assertRaises(SensorError):
                apply_bank_events(supplied, (), (), maintenance_active=False, maintenance_block=None)
        for events in ([{}], None):
            with self.assertRaises(SensorError):
                apply_bank_events(banks(), (), events, maintenance_active=False, maintenance_block=None)
        for active, block in ((0, None), (False, True), (True, 8), (True, -1)):
            with self.subTest(active=active, block=block), self.assertRaises(SensorError):
                apply_bank_events(banks(), (), (), maintenance_active=active, maintenance_block=block)
        for states in (None, [OccupancyState()] * 7, [OccupancyState()] * 9, [object()] * 8):
            with self.assertRaises(SensorError):
                occupancy_parameters(states)
        for state, events in ((None, ()), (OccupancyState(), []), (OccupancyState(), ({},))):
            with self.assertRaises(SensorError):
                OccupancyTransition(state, events)


if __name__ == '__main__':
    unittest.main()
