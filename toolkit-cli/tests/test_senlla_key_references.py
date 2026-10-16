"""Independent source literals for internal SENLLA ordered references."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_key_references import SENLLAKeyReferences
from cbus_toolkit.sensors import SensorError


def state(first=None):
    return SENLLAKeyReferences.from_ordered([first or []] + [[] for _ in range(7)])


class SENLLAKeyReferencesTests(unittest.TestCase):
    def test_independent_source_literals(self):
        evidence = json.loads((Path(__file__).parents[1] /
                               'research/fixtures/senlla-key-references-source.json').read_text())
        for case in evidence['focused_source_literals']:
            with self.subTest(case=case['name']):
                before = case['before']
                graph = SENLLAKeyReferences.from_ordered(before['ordered_references'], masks=before['masks'])
                operation = case['operation']
                kind = operation['type']
                if kind == 'transfer':
                    result = graph.transfer_block(operation['source'], operation['destination'])
                elif kind == 'swap':
                    result = graph.swap_mappings(operation['first'], operation['second'])
                elif kind == 'add':
                    result = graph.add_block(operation['key'], operation['block'])
                else:
                    result = graph.remove_block(operation['key'], operation['block'])
                self.assertEqual(result.state.as_dict(), case['after'])
                self.assertEqual([[event.key, event.operation, event.block] for event in result.events],
                                 case['expected_operation_order'])
                self.assertEqual([event.key for event in result.events
                                  if event.operation == 'add' and not event.changed], case['no_op_add_keys'])
                self.assertEqual([[request.key, request.from_block_number, request.to_block_number,
                                   request.after_event_count] for request in result.indicator_requests],
                                 case.get('expected_indicator_requests', []))
                self.assertEqual(graph.as_dict()['ordered_references'], before['ordered_references'])

    def test_all_raw_masks_load_ascending_and_roundtrip(self):
        for mask in range(256):
            with self.subTest(mask=mask):
                graph = SENLLAKeyReferences.from_masks([mask] * 8)
                row = tuple(block for block in range(8) if mask & (1 << block))
                self.assertEqual(graph.ordered_references, (row,) * 8)
                self.assertEqual(graph.parameters(), {'BlockAllocation': [mask] * 8})
                self.assertEqual(graph.primary_block(0), row[0] if row else None)

    def test_primary_block_uses_retained_order_after_transfer(self):
        graph = SENLLAKeyReferences.from_masks([6] + [0] * 7)
        result = graph.transfer_block(1, 0)
        self.assertEqual(result.state.ordered_references[0], (2, 0))
        self.assertEqual(result.state.primary_block(0), 2)
        self.assertEqual(result.state.masks()[0], 5)
        # Re-loading raw bytes is a different lifecycle and restores ascending
        # order; it must not replace the current in-memory graph.
        self.assertEqual(SENLLAKeyReferences.from_masks(result.state.masks()).primary_block(0), 0)

    def test_transfer_records_intermediate_add_before_remove_callbacks(self):
        result = state([1, 2]).transfer_block(1, 0)
        add, remove = result.events
        self.assertEqual((add.before, add.after), ((1, 2), (1, 2, 0)))
        self.assertEqual((remove.before, remove.after), ((1, 2, 0), (2, 0)))
        self.assertEqual(add.direct_refreshes, (
            ('RefreshKeysSecondaryFromBlockSecondary', 'block', 0),
            ('RefreshPrimaryGroupFromBlockGroups', 'key', 0)))
        self.assertEqual(remove.direct_refreshes, (
            ('RefreshPrimaryGroupFromBlockGroups', 'key', 0),
            ('RefreshKeysSecondaryFromBlockSecondary', 'block', 1)))

    def test_duplicate_add_and_absent_remove_have_no_callback_requests(self):
        graph = state([5, 3])
        for result in (graph.add_block(0, 3), graph.remove_block(0, 2)):
            with self.subTest(operation=result.events[0].operation):
                self.assertIs(result.state, graph)
                self.assertFalse(result.events[0].changed)
                self.assertEqual(result.events[0].direct_refreshes, ())
                self.assertFalse(result.events[0].as_dict()['reference_list_changed'])
        self.assertEqual(graph.transfer_block(7, 1).events, ())

    def test_update_guard_suppresses_only_direct_refresh_requests(self):
        graph = SENLLAKeyReferences.from_ordered([[1, 2], [1]] + [[] for _ in range(6)])
        result = graph.transfer_block(1, 0, key_updating=[True, False] + [False] * 6)
        self.assertTrue(all(event.changed for event in result.events))
        self.assertTrue(all(event.as_dict()['reference_list_changed'] for event in result.events))
        self.assertEqual([len(event.direct_refreshes) for event in result.events], [0, 0, 2, 2])
        self.assertEqual(result.state.ordered_references[:2], ((2, 0), (0,)))

    def test_remove_all_scans_block_collection_ascending(self):
        result = state([5, 0, 3]).remove_all_blocks(0)
        self.assertEqual([event.block for event in result.events], [0, 3, 5])
        self.assertEqual([event.after for event in result.events], [(5, 3), (5,), ()])
        self.assertEqual(result.state.masks(), [0] * 8)

    def test_swap_both_and_neither_are_unchanged_and_requests_are_conditional(self):
        graph = SENLLAKeyReferences.from_ordered([[1, 3], [], [3, 5]] + [[] for _ in range(5)])
        result = graph.swap_mappings(1, 3)
        self.assertEqual([event.key for event in result.events], [2, 2])
        self.assertEqual(result.state.ordered_references[:3], ((1, 3), (), (5, 1)))
        request, = result.indicator_requests
        self.assertEqual(request.as_dict(), {
            'key': 2, 'from_block_number': 4, 'to_block_number': 2, 'after_event_count': 2,
            'condition': 'current indicator block number equals from_block_number'})
        identical = graph.swap_mappings(1, 1)
        self.assertIs(identical.state, graph)
        self.assertEqual(identical.events, ())
        self.assertEqual(identical.indicator_requests, ())

    def test_inputs_and_all_outputs_are_detached(self):
        rows = [[5, 3]] + [[] for _ in range(7)]
        graph = SENLLAKeyReferences.from_ordered(rows, masks=[40] + [0] * 7)
        rows[0].clear()
        masks = graph.masks()
        masks[0] = 0
        values = graph.parameters()
        values['BlockAllocation'][0] = 0
        result = graph.transfer_block(3, 0)
        output = result.as_dict()
        output['state']['ordered_references'][0].clear()
        output['events'][0]['after'].clear()
        output['events'][0]['direct_refreshes'].clear()
        self.assertEqual(graph.ordered_references[0], (5, 3))
        self.assertEqual(graph.masks()[0], 40)
        self.assertEqual(result.state.ordered_references[0], (5, 0))
        self.assertEqual(result.events[0].after, (5, 3, 0))
        self.assertEqual(replace(graph).ordered_references, graph.ordered_references)
        with self.assertRaises(FrozenInstanceError):
            graph.ordered_references = ()
        with self.assertRaises(FrozenInstanceError):
            result.events[0].changed = False

    def test_invalid_raw_or_ordered_layouts_refuse(self):
        for masks in (None, [], [0] * 7, [True] * 8, [-1] * 8, [256] * 8, [1.0] * 8, '00000000'):
            with self.subTest(masks=masks), self.assertRaises(SensorError):
                SENLLAKeyReferences.from_masks(masks)
        for rows in (None, [], [[]] * 7, [None] * 8, [[1, 1]] + [[]] * 7,
                     [[True]] + [[]] * 7, [[-1]] + [[]] * 7, [[8]] + [[]] * 7,
                     [[1.0]] + [[]] * 7, ['1'] + [[]] * 7):
            with self.subTest(rows=rows), self.assertRaises(SensorError):
                SENLLAKeyReferences.from_ordered(rows)
        with self.assertRaises(SensorError):
            SENLLAKeyReferences.from_ordered([[5, 3]] + [[]] * 7, masks=[8] + [0] * 7)

    def test_invalid_indices_and_update_states_refuse(self):
        graph = state([1])
        for value in (True, -1, 8, 1.0, None):
            for action in (lambda: graph.primary_block(value), lambda: graph.add_block(value, 0),
                           lambda: graph.remove_block(0, value), lambda: graph.transfer_block(value, 0),
                           lambda: graph.swap_mappings(0, value)):
                with self.subTest(value=value, action=action), self.assertRaises(SensorError):
                    action()
        for value in (0, 1, None, 'false'):
            with self.subTest(value=value), self.assertRaises(SensorError):
                graph.add_block(0, 0, key_updating=value)
        for values in ([], [False] * 7, [0] * 8, [None] * 8):
            with self.subTest(values=values), self.assertRaises(SensorError):
                graph.transfer_block(1, 0, key_updating=values)
        with self.assertRaises(SensorError):
            graph.transfer_block(1, 1)


if __name__ == '__main__':
    unittest.main()
