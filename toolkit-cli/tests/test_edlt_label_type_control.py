import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_label_type_control import (
    LabelTypeState, LightingLabelState, apply_label_type,
    apply_lighting_label_type, set_lighting_label_index, update_label_types,
)

VECTOR = json.loads((Path(__file__).parents[1] / 'research/fixtures/edlt-label-control-vectors.json').read_text())


class LabelTypeTests(unittest.TestCase):
    def test_full_lighting_type_literals(self):
        for case in VECTOR['lighting_types']:
            with self.subTest(case=case['name']):
                result = apply_lighting_label_type(LightingLabelState(*case['before']),
                    target=case['target'], value=case['type'], image_flags=case['images'])
                self.assertEqual([result.state.byte_value, result.state.raw_label_index,
                                  result.state.raw_status_index], case['after'])
                self.assertEqual(list(result.notifications), case['notifications'])

    def test_full_lighting_index_literals(self):
        for case in VECTOR['lighting_indices']:
            with self.subTest(case=case['name']):
                result = set_lighting_label_index(LightingLabelState(*case['before']),
                    target=case['target'], index=case['index'], image_flags=case['images'])
                self.assertEqual([result.state.byte_value, result.state.raw_label_index,
                                  result.state.raw_status_index], case['after'])
                self.assertEqual(result.notifications, ())

    def test_scene_data_does_not_alias_direct_dynamic_types(self):
        state = LabelTypeState(0x16, 3, 2, True)
        self.assertEqual(state.display_type('label'), 1)
        self.assertEqual(state.display_type('status'), 6)
        result = apply_label_type(state, target='label', value=2, image_flags=[])
        self.assertEqual(result.state, LabelTypeState(0x26, 0, 2, True))
        self.assertEqual(result.notifications, ('LabelDisplayType', 'LabelValueText'))
        with self.assertRaisesRegex(EdltError, 'no generic'):
            apply_label_type(state, target='status', value=10, image_flags=[])

    def test_base_negative_index_normalizes_before_same_byte_early_return(self):
        result = apply_label_type(LabelTypeState(0x16, -1, 2),
                                 target='label', value=10, image_flags=[False])
        self.assertEqual(result.state, LabelTypeState(0x16, 0, 2))
        self.assertFalse(result.changed)
        self.assertTrue(result.variant_index_normalized)
        self.assertEqual(result.notifications, ())

    def test_empty_negative_index_original_access_refuses(self):
        with self.assertRaisesRegex(EdltError, 'Original DynamicAll index'):
            apply_label_type(LabelTypeState(0x16, -1, 0), target='label', value=10, image_flags=[])

    def test_source_update_order_status_then_label(self):
        final, results = update_label_types(LabelTypeState(0x16, 1, 0), image_flags=[True, False])
        self.assertEqual([result.target for result in results], ['status', 'label'])
        self.assertEqual(final, LabelTypeState(0x17, 1, 0))
        self.assertEqual(results[0].notifications, ('StatusDisplayType',))
        self.assertEqual(results[1].notifications, ())

    def test_lighting_getters_do_not_repair_raw_storage(self):
        state = LightingLabelState(0x35, 255, 255)
        self.assertEqual((state.index('label'), state.index('status')), (0, 0))
        self.assertEqual((state.raw_label_index, state.raw_status_index), (255, 255))
        self.assertEqual(LightingLabelState(0, 255, 255).index('label'), 255)

    def test_unproven_or_unsupported_type_facts_refuse(self):
        for kwargs in ({'value':True,'image_flags':[]}, {'value':10,'image_flags':[None]},
                       {'value':10,'image_flags':[False]*5}, {'value':2,'image_flags':[]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(EdltError):
                apply_lighting_label_type(LightingLabelState(0,0,0),target='label',**kwargs)
        with self.assertRaises(EdltError):
            set_lighting_label_index(LightingLabelState(0,0,0),target='label',index=-1,image_flags=[])


if __name__ == '__main__':
    unittest.main()
