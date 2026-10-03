"""Fresh zero-key SENLL application callbacks, with independent literal vectors."""
import copy
import json
from pathlib import Path
import unittest

from cbus_toolkit.light_level_sensors import LightLevelSensor
from cbus_toolkit.sensors import SensorError
from test_light_level_sensors import ROWS, fixture
from test_macros import Session


def values(*, applications=(56, 57), groups=(255, 20, 20, 255, 255, 25, 255, 255), mask=4, **extra):
    result = {name: list(row[-1]) for name, row in ROWS.items()}
    result.update(Application=list(applications), GroupAddress=list(groups), SecondApplicationBlocks=[mask],
                  PECEnablerGroup=[255], CorridorLinkEnablerGroup=[255], SingleJoinEnablerGroup=[255],
                  DualJoinEnablerGroup=[255], SingleJoinEnablerControlGroup=[255], DualJoinEnablerControlGroup=[255])
    result.update(extra)
    return result


class SENLLControlHistoryTests(unittest.TestCase):
    def setUp(self):
        self.sensor = LightLevelSensor(fixture())

    def plan(self, current=None, *controls, **options):
        return self.sensor.plan(current or values(), on_off_controls=list(controls) or None, **options)

    def final(self, plan, field):
        return list(plan.changes.get(field, plan.expected[field]))

    def test_primary_collision_clears_own_group_and_preserves_every_key_byte(self):
        before = values()
        snapshot = copy.deepcopy(before)
        plan = self.plan(before, {'application': 'primary'})
        self.assertEqual(self.final(plan, 'GroupAddress'), [255, 20, 255, 255, 255, 25, 255, 255])
        self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [0])
        row = plan.control_history['controls'][0]
        self.assertEqual(row['collision_block_index'], 1)
        self.assertEqual(row['scan'], [1, 5])
        self.assertEqual(plan.control_history['input_key_count'], 0)
        self.assertFalse(plan.control_history['block_allocation_mutated'])
        for name in ('BlockAllocation', 'JPCommand', 'SRCommand', 'LPCommand', 'LRCommand', 'SceneKeySelector'):
            self.assertNotIn(name, plan.changes)
            self.assertEqual(before[name], snapshot[name])
        self.assertEqual(before, snapshot)

    def test_reverse_collision_uses_already_changed_bit(self):
        plan = self.plan(values(mask=2), {'application': 'secondary'})
        self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [6])
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 255)
        self.assertEqual(plan.control_history['controls'][0]['collision_block_index'], 1)

    def test_same_boolean_does_not_invoke_collision_or_hidden_callbacks(self):
        for choice, mask in (('primary', 0), ('secondary', 6)):
            with self.subTest(choice=choice):
                plan = self.plan(values(mask=mask, PECEnablerGroup=[20]), {'application': choice})
                self.assertEqual(self.final(plan, 'GroupAddress')[2], 20)
                row = plan.control_history['controls'][0]
                self.assertFalse(row['secondary_changed'])
                self.assertEqual(row['scan'], [])
                self.assertEqual(row['hidden_group_callbacks'], [])

    def test_same_application_object_still_scans_when_boolean_changes(self):
        plan = self.plan(values(applications=(56, 56)), {'application': 'primary'})
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 255)
        self.assertTrue(plan.control_history['controls'][0]['secondary_changed'])

    def test_all_eight_missing_secondary_load_bits_normalize_in_ascending_order(self):
        current = values(applications=(56, 255), groups=[20] * 8, mask=254)
        plan = self.plan(current, {'application': 'primary'})
        self.assertEqual(self.final(plan, 'GroupAddress'), [20, 255, 255, 255, 255, 255, 255, 255])
        self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [0])
        rows = plan.control_history['load']
        self.assertEqual([row['block_index'] for row in rows], list(range(1, 8)))
        self.assertEqual([row['collision_block_index'] for row in rows], [0] * 7)
        self.assertEqual(current['GroupAddress'], [20] * 8)
        self.assertNotIn('BlockAllocation', plan.changes)

    def test_load_has_no_later_hidden_references(self):
        current = values(applications=(56, 255), groups=(255, 20, 20, 255, 255, 255, 255, 255), mask=2,
                         PECEnablerGroup=[20], CorridorLinkEnablerGroup=[20])
        plan = self.plan(current, {'application': 'primary'})
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 20)
        self.assertEqual(plan.control_history['load'][0]['hidden_group_callbacks'], [])
        self.assertEqual(plan.control_history['unverified_group_lookups'], [])
        # A later getter cannot retroactively establish the missing load object.
        current = values(applications=(56, 255), groups=(255, 255, 20, 255, 255, 255, 255, 255),
                         PECEnablerGroup=[20], CorridorLinkEnablerGroup=[20])
        with self.assertRaisesRegex(SensorError, 'creation/decline'):
            self.plan(current, {'application': 'primary'})

    def test_legacy_flat_initialization_preserves_the_other_seven_raw_bits(self):
        plan = self.plan(values(applications=(56, 255), groups=list(range(8)), mask=254))
        self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [250])
        self.assertEqual(self.final(plan, 'GroupAddress'), list(range(8)))
        self.assertIsNone(plan.control_history)
        with self.assertRaisesRegex(SensorError, 'key-block reassignment'):
            self.plan(values(applications=(56, 255), groups=[20] * 8, mask=254))

    def test_known_loaded_group_is_retained_across_clear_switch_and_selection(self):
        plan = self.plan(values(), {'application': 'primary'}, {'application': 'secondary'}, {'group': 20})
        self.assertEqual(self.final(plan, 'GroupAddress'), [255, 20, 20, 255, 255, 25, 255, 255])
        self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [4])
        rows = plan.control_history['controls']
        self.assertIn(20, rows[1]['offered_after'])
        self.assertEqual(rows[2]['before']['groups'][2], [57, 255])
        self.assertEqual(rows[2]['after']['groups'][2], [57, 20])

    def test_combo_exclusions_rebuild_at_each_step_and_keep_own_current_group(self):
        plan = self.plan(values(groups=(255, 20, 20, 20, 255, 25, 255, 255), mask=8),
                         {'group': 20}, {'application': 'secondary'})
        first, second = plan.control_history['controls']
        self.assertIn(20, first['offered_before'])  # current duplicate stays offered
        self.assertNotIn(20, first['excluded_before'])
        self.assertIn(25, second['excluded_before'])
        self.assertNotIn(25, second['excluded_after'])
        with self.assertRaisesRegex(SensorError, 'excluded'):
            self.plan(values(mask=0), {'group': 25})

    def test_pec_and_inactive_corridor_clear_group_after_application_rebind(self):
        for field, callback in (('PECEnablerGroup', 'pec'), ('CorridorLinkEnablerGroup', 'corridor')):
            for active in (0, 1):
                with self.subTest(field=field, active=active):
                    current = values(groups=(255, 255, 20, 255, 255, 255, 255, 255),
                                     CorridorLinkActive=[active], **{field: [20]})
                    plan = self.plan(current, {'application': 'primary'})
                    self.assertEqual(self.final(plan, 'GroupAddress')[2], 255)
                    row = plan.control_history['controls'][0]
                    self.assertIsNone(row['collision_block_index'])
                    self.assertEqual(row['hidden_group_callbacks'], [callback])

    def test_join_uses_single_group_even_when_only_dual_group_is_assigned(self):
        for single, dual, expected in ((20, 21, 255), (255, 20, 20)):
            with self.subTest(single=single):
                current = values(groups=(255, 255, 20, 255, 255, 255, 255, 255),
                                 CorridorLinkEnablerGroup=[255], PECEnablerGroup=[255],
                                 SingleJoinEnablerGroup=[single], DualJoinEnablerGroup=[dual])
                plan = self.plan(current, {'application': 'primary'})
                self.assertEqual(self.final(plan, 'GroupAddress')[2], expected)
                self.assertEqual(plan.control_history['hidden_groups_after_load']['join'], [56, single])

    def test_dual_join_getter_establishes_a_group_without_reserving_it(self):
        for single in (22, 255):
            with self.subTest(single=single):
                current = values(groups=(255, 255, 20, 255, 255, 255, 255, 255),
                                 SingleJoinEnablerGroup=[single], DualJoinEnablerGroup=[20])
                plan = self.plan(current, {'application': 'primary'})
                self.assertEqual(self.final(plan, 'GroupAddress')[2], 20)
                self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [0])
                self.assertEqual(plan.control_history['dual_join_group_after_load'], [56, 20])
                self.assertEqual(plan.control_history['controls'][0]['hidden_group_callbacks'], [])
        current = values(groups=[255] * 8, mask=0,
                         SingleJoinEnablerGroup=[22], DualJoinEnablerGroup=[20])
        selected = self.plan(current, {'group': 20}, {'group': 22})
        first, second = selected.control_history['controls']
        self.assertEqual(first['after']['groups'][2], [56, 20])
        self.assertEqual(first['hidden_group_callbacks'], [])
        self.assertEqual(second['after']['groups'][2], [56, 255])
        self.assertEqual(second['hidden_group_callbacks'], ['join'])

    def test_control_join_getters_do_not_establish_ignored_ordinary_groups(self):
        current = values(groups=(255, 255, 20, 255, 255, 255, 255, 255),
                         DualJoinEnablerGroup=[20], SingleJoinEnablerControlGroup=[22],
                         DualJoinEnablerControlGroup=[20])
        unchanged = self.plan(current, {'application': 'secondary'})
        self.assertEqual(unchanged.control_history['hidden_groups_after_load']['join'], [203, 22])
        self.assertEqual(unchanged.control_history['dual_join_group_after_load'], [203, 20])
        with self.assertRaisesRegex(SensorError, 'creation/decline'):
            self.plan(current, {'application': 'primary'})

    def test_hidden_pir_enable_getter_establishes_a_group_without_reserving_it(self):
        current = values(groups=(255, 255, 20, 255, 255, 255, 255, 255), PIREnablerGroup=[20])
        plan = self.plan(current, {'application': 'primary'})
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 20)
        self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [0])
        self.assertEqual(plan.control_history['pir_enable_group_after_load'], [56, 20])
        self.assertEqual(plan.control_history['controls'][0]['hidden_group_callbacks'], [])
        self.assertEqual(plan.expected['PIREnablerGroup'], (20,))
        self.assertEqual(self.final(plan, 'PIREnablerGroup'), [255])
        # Its later hidden getter cannot satisfy an earlier load lookup.
        current['Application'] = [56, 255]
        with self.assertRaisesRegex(SensorError, 'creation/decline'):
            self.plan(current, {'application': 'primary'})

    def test_join_control_group_precedence_binds_application203_and_first_single(self):
        for single_control, dual_control in ((20, 21), (255, 20)):
            with self.subTest(single_control=single_control):
                current = values(applications=(56, 56), groups=(255, 255, 20, 255, 255, 255, 255, 255),
                                 SingleJoinEnablerGroup=[20], SingleJoinEnablerControlGroup=[single_control],
                                 DualJoinEnablerControlGroup=[dual_control])
                plan = self.plan(current, {'application': 'primary'})
                self.assertEqual(self.final(plan, 'GroupAddress')[2], 20)
                self.assertEqual(plan.control_history['hidden_groups_after_load']['join'], [203, single_control])
                self.assertEqual(plan.control_history['controls'][0]['hidden_group_callbacks'], [])

    def test_group_selection_invokes_hidden_callback_but_same_object_does_not(self):
        current = values(groups=(255, 255, 20, 255, 255, 255, 255, 255),
                         mask=0, CorridorLinkEnablerGroup=[20])
        unchanged = self.plan(current, {'group': 20})
        self.assertEqual(self.final(unchanged, 'GroupAddress')[2], 20)
        changed = self.plan(current, {'group': 255}, {'group': 20})
        self.assertEqual(self.final(changed, 'GroupAddress')[2], 255)
        self.assertEqual(changed.control_history['controls'][1]['hidden_group_callbacks'], ['corridor'])

    def test_missing_destination_group_requires_original_creation_decision(self):
        current = values(groups=(255, 255, 20, 255, 255, 255, 255, 255))
        for operations in (({'application': 'primary'},), ({'group': 31},)):
            with self.subTest(operations=operations), self.assertRaisesRegex(SensorError, 'creation/decline'):
                self.plan(current, *operations)

    def test_invalid_or_unavailable_applications_refuse_explicit_histories(self):
        for apps in ((255, 255), (255, 57), (192, 57), (56, 202), (0, 57), (56, 203)):
            with self.subTest(apps=apps), self.assertRaisesRegex(SensorError, 'Lighting'):
                self.plan(values(applications=apps), {'application': 'primary'})
        with self.assertRaisesRegex(SensorError, 'disabled'):
            self.plan(values(applications=(56, 255), mask=0), {'application': 'secondary'})

    def test_invalid_histories_and_flat_on_off_mixing_refuse(self):
        for invalid in ([], {}, 'primary', [{'application': True}], [{'group': True}], [{'group': -1}],
                        [{'group': '20'}], [{'group': 256}], [{'application': 'primary', 'group': 20}],
                        [{'cache': {}}], [{'application': 'primary'}] * 65):
            with self.subTest(invalid=invalid), self.assertRaises(SensorError):
                self.sensor.plan(values(), on_off_controls=invalid)
        for flat in ({'on_off_group': 255}, {'on_off_application': 'primary'}, {'level_group': 21},
                     {'broadcast_group': 22}, {'enable_group': 23}):
            with self.subTest(flat=flat), self.assertRaisesRegex(SensorError, 'cannot be mixed'):
                self.plan(values(), {'application': 'primary'}, **flat)

    def test_legacy_flat_collision_refusal_directs_to_explicit_history(self):
        with self.assertRaisesRegex(SensorError, 'explicit ordered'):
            self.sensor.plan(values(), on_off_application='primary')

    def test_forced_save_follows_callbacks_and_preserves_original_expectations(self):
        current = values(groups=(255, 255, 20, 255, 255, 255, 255, 255), CorridorLinkEnablerGroup=[20])
        plan = self.plan(current, {'application': 'primary'}, target_lux=500, margin_percent=59)
        self.assertEqual(plan.expected['CorridorLinkEnablerGroup'], (20,))
        self.assertEqual(plan.control_history['hidden_groups_after_load']['corridor'], [56, 20])
        self.assertEqual(self.final(plan, 'CorridorLinkEnablerGroup'), [255])
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 255)
        self.assertEqual(self.final(plan, 'PECMarginLux'), [29])
        self.assertTrue(plan.control_history['forced_save_last'])

    def test_apply_stale_schema_and_parameter_preservation_are_unchanged(self):
        session = Session(fixture())
        session.unit_type, session.firmware, session.catalog_number = 'SENLL', '2.3.00', '5031PE'
        current = values()
        session.current.update({name: ' '.join(map(str, value)) for name, value in current.items()})
        plan = self.plan(session.values(), {'application': 'primary'})
        session.current['GroupAddress'] = '255 20 22 255 255 25 255 255'
        with self.assertRaisesRegex(SensorError, 'changed since'):
            self.sensor.apply(session, plan)
        self.assertEqual(session.calls, [])
        session.current['GroupAddress'] = ' '.join(map(str, current['GroupAddress']))
        result = self.sensor.apply(session, plan)
        self.assertTrue(result['verified'])
        self.assertFalse(result['saved'])
        self.assertEqual(session.current['BlockAllocation'], '1 2 4 8 16 32 64 128')

    def test_receipts_are_detached_and_source_evidence_is_sanitized(self):
        plan = self.plan(values(), {'application': 'primary'})
        first = plan.as_dict()
        first['control_history']['controls'][0]['after']['groups'][2][1] = 99
        self.assertEqual(plan.as_dict()['control_history']['controls'][0]['after']['groups'][2], [56, 255])
        receipt = Path(__file__).resolve().parents[1] / 'docs/senll-application-controls-source.json'
        source = json.loads(receipt.read_text())
        self.assertFalse(source['original_execution'])
        self.assertEqual(source['source_sha256']['CBusToolkit.exe'],
                         '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab')
        self.assertEqual(source['methods']['0xd0f6cc']['sha256'],
                         'e58499ede4893d79806595e701cde9465c1f6f5802d419137f56e67c6a64e184')
        for private in ('<Param', 'DefaultValue', 'instructions', '/tmp/', 'op_str'):
            self.assertNotIn(private, receipt.read_text())


if __name__ == '__main__':
    unittest.main()
