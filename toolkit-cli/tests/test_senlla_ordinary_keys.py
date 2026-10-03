"""Source-derived ordinary SENLLA key vectors, without unit/form/save admission."""
import copy
from itertools import product
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_ordinary_keys import load_ordinary_keys, loaded_template, primary_block_index
from cbus_toolkit.sensors import SensorError


def project(rows=None, masks=None, groups=None, **changes):
    masks = [1] * 8 if masks is None else masks
    groups = [object() for _ in range(8)] if groups is None else groups
    inputs = dict(stages=rows or [(0, 0, 0, 0)] * 8, block_masks=masks,
                  store1=[249] * 8, store2=[2] * 8, timer_seconds=[0] * 8,
                  expiry_commands=[0] * 8, primary_groups=groups)
    inputs.update(changes)
    return load_ordinary_keys(**inputs)


class SENLLAOrdinaryKeysTests(unittest.TestCase):
    def test_independently_authored_source_component_vectors(self):
        source = json.loads((Path(__file__).parents[1] / 'research/fixtures/senlla-ordinary-key-source.json').read_text())
        for case in source['focused_source_literals']:
            raw = case['before']
            objects, groups = {}, []
            for mask in raw['BlockAllocation']:
                if mask.bit_count() != 1:
                    groups.append(None)
                    continue
                block = primary_block_index(mask)
                secondary = bool(raw['SecondApplicationBlocks'][0] & (1 << block))
                identity = (raw['Application'][int(secondary)], raw['GroupAddress'][block])
                groups.append(objects.setdefault(identity, object()))
            rows = list(zip(*(raw[name] for name in ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'))))
            result = load_ordinary_keys(rows, raw['BlockAllocation'], raw['LightLevelStore1'], raw['LightLevelStore2'],
                [(high << 8) | low for high, low in zip(raw['TimerHighByte'], raw['TimerLowByte'])],
                raw['TimerExpiryCommand'], primary_groups=groups)
            with self.subTest(case=case['name']):
                self.assertEqual({**raw, **result.parameters()}, case['expected_component_after'])
                self.assertEqual(list(result.templates), case['expected_key_template_types'])

    def test_all_nibble_patterns_against_ordered_static_registry(self):
        # Independent full group/template registration evidence, rather than
        # the reduced 50-row production lookup.
        source = json.loads((Path(__file__).parents[1] / 'research/fixtures/senlla-ordinary-key-registry-source.json').read_text())
        groups = {row['group_type']: row for row in source['groups']}
        expected = {}
        for template in source['templates_in_registration_order']:
            for identifier in template['groups']:
                row = groups[identifier]
                # Native inputSource=0 bypasses source-type filtering and the
                # four-stage overload ignores the two extra VC/VT stages.
                stages = tuple(row['stages'][:4])
                if all(0 <= value <= 15 for value in stages):
                    expected.setdefault(stages, template['function_type'])
        self.assertEqual(len(expected), 50)
        admitted = set(range(14)) | {16, 21, 34}
        matched = 0
        for stages in product(range(16), repeat=4):
            function = expected.get(stages, 26)
            matched += stages in expected
            want = 17 if function == 14 else 19 if function == 15 else function if function in admitted else 26
            self.assertEqual(loaded_template(stages, store1=249, store2=2), want, stages)
        self.assertEqual(matched, 50)

    def test_explicit_recall_level_remapping(self):
        for level, expected in ((0, 26), (248, 26), (249, 17), (250, 26), (251, 26),
                                (252, 18), (253, 26), (254, 26), (255, 20), (None, 26)):
            with self.subTest(recall=1, level=level):
                self.assertEqual(loaded_template((12, 0, 0, 0), store1=level), expected)
        for level, expected in ((0, 26), (1, 26), (2, 19), (3, 26), (4, 26), (5, 22), (6, 26), (255, 26), (None, 26)):
            with self.subTest(recall=2, level=level):
                self.assertEqual(loaded_template((6, 0, 0, 0), store2=level), expected)

    def test_all_masks_choose_the_first_reference_and_roundtrip_exactly(self):
        for mask in range(256):
            index = next((bit for bit in range(8) if mask & (1 << bit)), None)
            self.assertEqual(primary_block_index(mask), index)
            groups = [object() if mask.bit_count() == 1 else None] * 8
            result = project(masks=[mask] * 8, groups=groups)
            self.assertEqual(result.parameters()['BlockAllocation'], [mask] * 8)
            self.assertEqual(result.templates, (16,) * 8)

    def test_locked_timer_defaults_preserve_original_stage_variants(self):
        rows = [(11, 7, 0, 7), (13, 7, 15, 0), (13, 8, 13, 8), (0, 7, 0, 7),
                (0, 7, 15, 0), (13, 15, 7, 15), (7, 0, 0, 0), (13, 7, 7, 0)]
        result = project(rows=rows, masks=[1 << index for index in range(8)])
        self.assertEqual(result.templates, (6, 6, 6, 6, 6, 34, 26, 26))
        self.assertEqual(result.stages, tuple(rows))
        self.assertEqual(result.timer_seconds, (300,) * 6 + (0, 0))
        self.assertEqual(result.expiry_commands, (15,) * 6 + (0, 0))
        self.assertEqual(len(result.timer_defaults), 12)

    def test_shared_multi_mask_defaults_primary_once_and_nil_timer_does_nothing(self):
        rows = [(11, 7, 0, 7)] * 8
        masks = [0, 0b10100, 0b10000, 0b10100, 0, 0, 0, 0]
        groups = [None, None, object(), None, None, None, None, None]
        result = project(rows=rows, masks=masks, groups=groups)
        self.assertEqual(result.timer_seconds, (0, 0, 300, 0, 300, 0, 0, 0))
        self.assertEqual(result.timer_defaults, ((1, 2, 'timer', 300), (1, 2, 'expiry', 15),
                                               (2, 4, 'timer', 300), (2, 4, 'expiry', 15)))

    def test_nonzero_timer_and_expiry_are_independently_preserved(self):
        rows = [(13, 15, 7, 15)] * 8
        result = project(rows=rows, masks=[1 << index for index in range(8)],
                         timer_seconds=[1, 0, 300, 65535, 0, 0, 0, 0], expiry_commands=[0, 9, 15, 4, 0, 0, 0, 0])
        self.assertEqual(result.timer_seconds, (1, 300, 300, 65535, 300, 300, 300, 300))
        self.assertEqual(result.expiry_commands, (15, 9, 15, 4, 15, 15, 15, 15))

    def test_declared_reference_order_controls_primary_timer_and_recall_store(self):
        references = [(2, 0)] + [()] * 7
        masks, groups = [5] + [0] * 7, [None] * 8
        rows = [(11, 7, 0, 7)] + [(0, 0, 0, 0)] * 7
        result = project(rows=rows, masks=masks, groups=groups, block_references=references)
        self.assertEqual(result.timer_seconds, (0, 0, 300, 0, 0, 0, 0, 0))
        self.assertEqual(result.expiry_commands, (0, 0, 15, 0, 0, 0, 0, 0))
        self.assertEqual(result.parameters()['BlockAllocation'], masks)
        rows[0] = (12, 0, 0, 0)
        result = project(rows=rows, masks=masks, groups=groups, block_references=references,
                         store1=[249, 0, 252, 0, 0, 0, 0, 0])
        self.assertEqual(result.templates[0], 18)
        self.assertEqual(result.stages[0], (12, 0, 0, 0))
        self.assertEqual(references, [(2, 0)] + [()] * 7)

    def test_declared_reference_rows_refuse_mask_mismatch_duplicates_and_wrong_domains(self):
        for row in ((0,), (0, 0), (1, 2), (0, 8), (0, True), '0 2'):
            with self.subTest(row=row), self.assertRaises(SensorError):
                project(masks=[5] + [0] * 7, groups=[None] * 8,
                        block_references=[row] + [()] * 7)
        for rows in ([], [()] * 7, [()] * 9, 'bad'):
            with self.subTest(rows=rows), self.assertRaises(SensorError):
                project(block_references=rows)

    def test_first_recall_category_wins_with_same_group_identity(self):
        group = object()
        rows = [(12, 0, 0, 0), (12, 0, 0, 0), (6, 0, 0, 0), (9, 0, 0, 0)] + [(0, 0, 0, 0)] * 4
        result = project(rows=rows, masks=[1, 2, 4, 8, 1, 1, 1, 1], groups=[group] * 8,
                         store1=[249, 252, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result.templates[:4], (17, 16, 16, 16))
        self.assertEqual(result.stages[:4], ((12, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)))
        self.assertEqual(result.recall_resets, ((0, 1, 18, 16), (0, 2, 19, 16), (0, 3, 21, 16)))

    def test_same_category_pairs_do_not_reset(self):
        group = object()
        rows = [(12, 0, 0, 0), (6, 0, 0, 0)] + [(0, 0, 0, 0)] * 6
        result = project(rows=rows, masks=[1, 2] + [1] * 6, groups=[group] * 8,
                         store1=[252] * 8)
        self.assertEqual(result.templates[:2], (18, 19))
        self.assertEqual(result.recall_resets, ())

    def test_nil_group_conflict_and_distinct_equal_objects(self):
        rows = [(9, 0, 0, 0), (12, 0, 0, 0)] + [(0, 0, 0, 0)] * 6
        result = project(rows=rows, masks=[0, 3] + [0] * 6, groups=[None] * 8,
                         store1=[249] * 8)
        self.assertEqual(result.templates[:2], (21, 16))
        self.assertEqual(result.recall_resets, ((0, 1, 17, 16),))
        # Value equality is insufficient; these represent separate source objects.
        group_a, group_b = [48, 255], [48, 255]
        result = project(rows=rows, masks=[1] * 8, groups=[group_a, group_b] + [object() for _ in range(6)])
        self.assertEqual(result.templates[:2], (21, 17))
        self.assertEqual(result.recall_resets, ())

    def test_inputs_and_detached_parameter_output_cannot_mutate_result(self):
        rows = [[13, 7, 15, 0]] + [[1, 2, 3, 4]] * 7
        before = copy.deepcopy(rows)
        result = project(rows=rows)
        self.assertEqual(rows, before)
        rows[0][0] = 15
        values = result.parameters()
        values['JPCommand'][0] = 15
        values['BlockAllocation'][0] = 0
        self.assertEqual(result.parameters()['JPCommand'][0], 13)
        self.assertEqual(result.parameters()['BlockAllocation'][0], 1)

    def test_invalid_values_and_unestablished_primary_groups_refuse(self):
        for value in (-1, 16, True, 1.5):
            with self.subTest(value=value), self.assertRaises(SensorError):
                loaded_template((value, 0, 0, 0))
        for changes in ({'stages': []}, {'block_masks': [256] * 8}, {'store1': [-1] * 8},
                        {'store2': [True] * 8}, {'timer_seconds': [65536] * 8},
                        {'expiry_commands': [16] * 8}, {'primary_groups': []},
                        {'block_masks': [0] * 8}, {'block_masks': [3] * 8},
                        {'primary_groups': [None] * 8}):
            with self.subTest(changes=changes), self.assertRaises(SensorError):
                project(**changes)
