"""Independent block/index/expiry literals; no native or physical execution."""
import copy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_block_values import (BlockLoadPlan, TIMER_EXPIRY_TYPES,
                                            block_load_plan, loaded_expiry_type,
                                            rebuild_light_levels)
from cbus_toolkit.senlla_inputs import SCHEMA, SENLLAInputSnapshot
from cbus_toolkit.sensors import SensorError


IDENTITY = ('SENLLA', '2.4.00', '5754PE')


def snapshot(**changes):
    # Authored complete raw binding. This test does not consume a vendor spec.
    values = {name: 'INPUT' if row[0] == 'sixbit' else [0] * row[2]
              for name, row in SCHEMA.items()}
    values.update(LightLevel=[10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
                  LightLevelStore1=[1, 2, 3, 4, 5, 6, 7, 8],
                  LightLevelStore2=[8, 7, 6, 5, 4, 3, 2, 1],
                  TimerHighByte=[0, 1, 0, 255, 0, 0, 0, 0],
                  TimerLowByte=[255, 44, 0, 255, 0, 0, 0, 0],
                  TimerExpiryCommand=[0, 1, 3, 4, 6, 9, 10, 15],
                  GroupAddress=[255, 20, 30, 40, 50, 60, 70, 80],
                  SecondApplicationBlocks=[165])
    values.update(changes)
    return SENLLAInputSnapshot(IDENTITY, values)


class SENLLABlockValuesTests(unittest.TestCase):
    def test_all_secondary_bits_precede_index_and_every_block_row(self):
        plan = block_load_plan(snapshot())
        requests = plan.requests()
        self.assertEqual(len(requests), 66)
        self.assertEqual([(item.block, item.value, item.source) for item in requests[:8]],
                         [(0, True, '0xced02e'), (1, False, '0xced02e'),
                          (2, True, '0xced02e'), (3, False, '0xced02e'),
                          (4, False, '0xced02e'), (5, True, '0xced02e'),
                          (6, False, '0xced02e'), (7, True, '0xced02e')])
        self.assertEqual([(item.field, item.value) for item in requests[8:10]],
                         [('light_index', 0), ('loaded_light_count', 10)])
        fields = ('light_level', 'store1', 'store2', 'timer', 'expiry', 'expiry', 'group')
        for block in range(8):
            row = requests[10 + block * 7:17 + block * 7]
            with self.subTest(block=block):
                self.assertEqual(tuple(item.field for item in row), fields)
                self.assertEqual(tuple(item.block for item in row), (block,) * 7)
        self.assertFalse(any(item.field in ('timer_cached', 'expiry_override', 'timer_min')
                             for item in requests))

    def test_raw_row_scalar_values_and_unsigned_timer_word(self):
        rows = block_load_plan(snapshot()).value_requests()[2:]
        self.assertEqual([rows[index * 7].value for index in range(8)],
                         [10, 20, 30, 40, 50, 60, 70, 80])
        self.assertEqual([rows[index * 7 + 1].value for index in range(8)],
                         [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual([rows[index * 7 + 2].value for index in range(8)],
                         [8, 7, 6, 5, 4, 3, 2, 1])
        self.assertEqual([rows[index * 7 + 3].value for index in range(8)],
                         [255, 300, 0, 65535, 0, 0, 0, 0])
        self.assertEqual([rows[index * 7 + 6].value for index in range(8)],
                         [255, 20, 30, 40, 50, 60, 70, 80])

    def test_indexed_reads_and_rebuild_independent_literal_vectors(self):
        source = json.loads((Path(__file__).parents[1] /
                             'research/fixtures/senlla-block-values-source.json').read_text())
        for case in source['indexed_literals']:
            with self.subTest(index=case['LightIndex']):
                plan = block_load_plan(snapshot(LightIndex=[case['LightIndex']]))
                loaded = tuple(plan.level_for_block(block) for block in range(8))
                self.assertEqual(list(loaded), case['loaded_block_levels'])
                saved = plan.parameters(case['current_block_levels'])
                self.assertEqual(saved['LightIndex'], [case['LightIndex']])
                self.assertEqual(saved['LightLevel'], case['saved_light_levels'])
                self.assertEqual(len(saved['LightLevel']), case['saved_length'])

    def test_prefix_and_tail_are_unused255_instead_of_raw_values(self):
        current = [11, 22, 33, 44, 55, 66, 77, 88]
        for index, expected in (
            (0, [11, 22, 33, 44, 55, 66, 77, 88, 255, 255]),
            (1, [255, 11, 22, 33, 44, 55, 66, 77, 88, 255]),
            (2, [255, 255, 11, 22, 33, 44, 55, 66, 77, 88]),
            (3, [255, 255, 255, 11, 22, 33, 44, 55, 66, 77, 88]),
        ):
            with self.subTest(index=index):
                result = block_load_plan(snapshot(LightIndex=[index])).parameters(current)
                self.assertEqual(result['LightLevel'], expected)
                self.assertEqual(current, [11, 22, 33, 44, 55, 66, 77, 88])

    def test_current_index_and_current_block_values_override_load_projection(self):
        plan = block_load_plan(snapshot(LightIndex=[1]))
        self.assertEqual(plan.level_for_block(0), 20)
        self.assertEqual(plan.level_for_block(0, light_index=2), 30)
        self.assertEqual(plan.level_for_block(7, light_index=3), 0)
        saved = plan.parameters([1, 2, 3, 4, 5, 6, 7, 8], light_index=2)
        self.assertEqual(saved, {'LightIndex': [2],
                                 'LightLevel': [255, 255, 1, 2, 3, 4, 5, 6, 7, 8]})
        self.assertEqual(plan.light_index, 1)

    def test_registered_expiry_zero_and_every_nibble_membership(self):
        self.assertEqual(TIMER_EXPIRY_TYPES, (0, 15, 4, 9, 12, 6, 10))
        expected = (0, 15, 15, 15, 4, 15, 6, 15, 15, 9, 10, 15, 12, 15, 15, 15)
        for raw, loaded in enumerate(expected):
            with self.subTest(raw=raw):
                self.assertEqual(loaded_expiry_type(raw), loaded)
                plan = block_load_plan(snapshot(TimerExpiryCommand=[raw] * 8))
                row = plan.value_requests()[2:9]
                self.assertEqual((row[4].operation, row[4].value, row[4].source),
                                 ('set_microfunction', raw, '0xcc82f7'))
                self.assertEqual((row[5].operation, row[5].value, row[5].source),
                                 ('check_expiry', expected_allowed(), '0xcc8357'))
                # No optional fallback is flattened into an unconditional raw
                # setter. A live owner decides after the initial publication.
                self.assertFalse(any(item.operation == 'set' and item.field == 'expiry'
                                     for item in plan.requests()))

    def test_live_expiry_and_group_reads_stay_executor_boundaries(self):
        plan = block_load_plan(snapshot(TimerExpiryCommand=[3] * 8,
                                       Application=[56, 255]))
        row = plan.value_requests()[2:9]
        self.assertEqual(row[4].value, 3)
        self.assertEqual(row[5].operation, 'check_expiry')
        # Initial raw3 would normalize15 in a detached projection. A native
        # publication that leaves CURRENT6 instead must preserve6.
        self.assertEqual(loaded_expiry_type(6), 6)
        self.assertEqual(row[6].as_dict(), {'operation': 'get_group', 'field': 'group',
                         'block': 0, 'value': 255, 'source': '0xcc83ba'})
        self.assertNotIn('application', row[6].as_dict())
        self.assertNotIn('group_identity', row[6].as_dict())

    def test_full_expected_and_every_export_are_detached(self):
        raw = snapshot()
        before = raw.parameters()
        plan = block_load_plan(raw)
        exported = plan.as_dict()
        exported['expected']['LightLevel'][0] = 0
        exported['requests'][15]['value'][0] = 99
        exported['identity'][0] = 'other'
        saved = plan.parameters([11] * 8)
        saved['LightLevel'][0] = 0
        self.assertEqual(raw.parameters(), before)
        self.assertEqual(plan.snapshot.parameters(), before)
        self.assertEqual(plan.parameters([11] * 8)['LightLevel'][0], 11)
        self.assertEqual(replace(plan).as_dict(), plan.as_dict())
        self.assertIsNot(plan.snapshot, raw)
        with self.assertRaises(FrozenInstanceError):
            plan.snapshot = None
        with self.assertRaises(FrozenInstanceError):
            plan.requests()[0].value = False
        for flag in ('complete_toolkit_save', 'original_execution', 'physical_acceptance'):
            self.assertFalse(plan.as_dict()[flag])
        self.assertTrue(plan.as_dict()['owner_executor_required'])

    def test_raw_mapping_and_partial_or_wrong_snapshot_refuse(self):
        for value in (None, True, {}, snapshot().parameters(), [], 'snapshot'):
            with self.subTest(value=type(value).__name__), self.assertRaises(SensorError):
                block_load_plan(value)
        partial = snapshot().parameters()
        del partial['SceneTable']
        with self.assertRaises(SensorError):
            SENLLAInputSnapshot(IDENTITY, partial)
        with self.assertRaises(SensorError):
            SENLLAInputSnapshot(('SENLL', '2.4.00', '5031PE'), snapshot().parameters())

    def test_direct_helper_domains_refuse_without_mutation(self):
        good = [11, 22, 33, 44, 55, 66, 77, 88]
        invalid_indices = (True, False, None, -1, 256, 1.0, '1')
        for value in invalid_indices:
            with self.subTest(index=value), self.assertRaises(SensorError):
                rebuild_light_levels(value, 10, good)
        for count in (True, False, None, -1, 0, 8, 9, 11, 10.0, '10'):
            with self.subTest(count=count), self.assertRaises(SensorError):
                rebuild_light_levels(0, count, good)
        for levels in (None, '', [0] * 7, [0] * 9, [True] + [0] * 7,
                       [False] + [0] * 7, [256] + [0] * 7, [-1] + [0] * 7,
                       [1.0] + [0] * 7):
            original = copy.deepcopy(levels)
            with self.subTest(levels=levels), self.assertRaises(SensorError):
                rebuild_light_levels(0, 10, levels)
            self.assertEqual(levels, original)
        for value in (True, False, None, -1, 16, 1.0, '0'):
            with self.subTest(expiry=value), self.assertRaises(SensorError):
                loaded_expiry_type(value)

    def test_live_indexed_read_and_save_domains_refuse(self):
        plan = block_load_plan(snapshot())
        for block in (True, False, None, -1, 8, 1.0, '0'):
            with self.subTest(block=block), self.assertRaises(SensorError):
                plan.level_for_block(block)
        for index in (True, False, -1, 256, 1.0, '1'):
            with self.subTest(index=index), self.assertRaises(SensorError):
                plan.level_for_block(0, light_index=index)
            with self.subTest(save_index=index), self.assertRaises(SensorError):
                plan.parameters([0] * 8, light_index=index)


def expected_allowed():
    return (0, 15, 4, 9, 12, 6, 10)


if __name__ == '__main__':
    unittest.main()
