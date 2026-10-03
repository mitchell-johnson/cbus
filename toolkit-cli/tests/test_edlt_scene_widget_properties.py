"""Literal SceneData properties, hidden indexes and explicit cycle getters."""
from dataclasses import replace
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_widget_properties import (
    LABEL_CHOICES, STATUS_CHOICES, MACRO_CHOICES, SceneWidgetProperties,
    set_display_type, set_index, set_scene_item, set_cycle_variant, set_macro,
    read_scene_cycle, add_cycle_scene, delete_cycle_scene, move_cycle_scene,
)

# Historical unchanged DLL output, also pinned in test_edlt_scene.py. The
# expectations below are source byte rules applied to this independent record.
OPAQUE = bytes.fromhex('068026250405061E1F090A0B0CFF0E0F101112131415161718191A1B1C1D1E1F')


def cycle(values):
    raw = bytearray(OPAQUE)
    raw[13:22] = values
    return SceneWidgetProperties(bytes(raw))


class SceneWidgetPropertyTests(unittest.TestCase):
    def test_source_scene_specific_choice_order_excludes_generic_dynamic10(self):
        self.assertEqual(LABEL_CHOICES, (('Blank', 0), ('Dynamic Label', 1), ('Dynamic Icon', 2), ('Scene Label', 3)))
        self.assertEqual(STATUS_CHOICES, (('Blank', 0), ('Dynamic Label', 6), ('Dynamic Icon', 7), ('Static Text', 5)))
        self.assertEqual(tuple(value for _, value in MACRO_CHOICES), ('30|31', '26|27', '28|29', '32|33'))
        for target in ('label', 'status'):
            with self.subTest(target=target), self.assertRaises(EdltError):
                set_display_type(SceneWidgetProperties(OPAQUE), target=target, value=10)

    def test_base_type_setter_preserves_bit7_and_both_hidden_raw_index_bytes(self):
        source = SceneWidgetProperties(OPAQUE, base_label_index=39, base_status_index=45)
        label = set_display_type(source, target='label', value=2)
        self.assertEqual(label.state.record.hex().upper(), '06A026250405061E1F090A0B0CFF0E0F101112131415161718191A1B1C1D1E1F')
        self.assertEqual((label.state.base_label_index, label.state.base_status_index), (0, 45))
        self.assertEqual(label.notifications, ('LabelDisplayType', 'LabelValueText'))
        status = set_display_type(label.state, target='status', value=7)
        self.assertEqual(status.state.record.hex().upper(), '06A726250405061E1F090A0B0CFF0E0F101112131415161718191A1B1C1D1E1F')
        self.assertEqual(status.state.record[11:13], bytes((11, 12)))
        self.assertEqual((status.state.base_label_index, status.state.base_status_index), (0, 0))
        same = set_display_type(status.state, target='status', value=7)
        self.assertEqual(same.state, status.state)
        self.assertEqual(same.notifications, ())

    def test_selected_variants_write_raw_hidden_fields_without_type_resolution(self):
        result = set_index(SceneWidgetProperties(OPAQUE), target='label', value=3)
        result = set_index(result.state, target='status', value=2)
        self.assertEqual(result.state.record.hex().upper(), '068026250405061E1F090A0302FF0E0F101112131415161718191A1B1C1D1E1F')
        self.assertEqual(result.notifications, ())
        self.assertEqual(result.state.base_label_index, 0)

    def test_scene_item_is_raw_byte_not_a_scene_getter(self):
        result = set_scene_item(SceneWidgetProperties(OPAQUE), 8)
        self.assertEqual(result.state.record.hex().upper(), '068026250405081E1F090A0B0CFF0E0F101112131415161718191A1B1C1D1E1F')
        self.assertFalse(result.as_dict()['state']['cycle_getter_invoked'])

    def test_radio_false_is_the_other_variant_and_never_changes_low_seven_bits(self):
        source = SceneWidgetProperties(bytes.fromhex('069626250000011E1F0FFF0302000100FFFFFFFFFFFF00000000000000000000'))
        for radio, checked, expected in (('cycle', True, 0x16), ('cycle', False, 0x96),
                                         ('select', True, 0x96), ('select', False, 0x16)):
            with self.subTest(radio=radio, checked=checked):
                result = set_cycle_variant(source, radio=radio, checked=checked)
                self.assertEqual(result.state.record[1], expected)
                self.assertEqual(result.state.record[2:], source.record[2:])

    def test_macro_notification_typo_is_not_repaired(self):
        source = SceneWidgetProperties(OPAQUE)
        result = set_macro(source, '28|29')
        self.assertEqual(result.state.record.hex().upper(), '068026250405061C1D090A0B0CFF0E0F101112131415161718191A1B1C1D1E1F')
        self.assertEqual(result.notifications, ('LeftButtonMacrofunction', 'RampRateEditable',
                                              'RightButtonMacrofunction', 'SceneSingleSelectionEditable'))
        raw = bytearray(OPAQUE); raw[7] = 28
        right_only = set_macro(SceneWidgetProperties(bytes(raw)), '28|29')
        self.assertEqual(right_only.notifications, ('RightButtonMacrofunction', 'SceneSingleSelectionEditable'))
        self.assertEqual(set_macro(result.state, '28|29').notifications, ('SceneSingleSelectionEditable',))

    def test_view_does_not_invoke_mutating_scene_cycle(self):
        source = cycle((0, 8, 9, 2, 3, 4, 5, 6, 7))
        before = source.record
        self.assertEqual(source.as_dict()['cycle_storage'], [0, 8, 9, 2, 3, 4, 5, 6, 7])
        self.assertEqual(source.record, before)
        self.assertFalse(source.as_dict()['cycle_getter_invoked'])

    def test_cycle_getter_accepts8_keeps_first_invalid_and_normalizes_only_after_it(self):
        result = read_scene_cycle(cycle((0, 8, 9, 2, 3, 4, 5, 6, 7)))
        self.assertEqual(result.slots, (0, 1))
        self.assertEqual(result.first_invalid_slot, 2)
        self.assertEqual(result.normalized_slots, (3, 4, 5, 6, 7, 8))
        self.assertEqual(tuple(result.state.record[13:22]), (0, 8, 9, 255, 255, 255, 255, 255, 255))
        self.assertFalse(result.as_dict()['configured_scene_existence_tested'])
        self.assertEqual(result.state.record[:13], OPAQUE[:13])
        self.assertEqual(result.state.record[22:], OPAQUE[22:])

    def test_cycle_getter_zero_first_failure_and_full_nine_rows(self):
        empty = read_scene_cycle(cycle((254, 1, 2, 3, 4, 5, 6, 7, 8)))
        self.assertEqual(empty.slots, ())
        self.assertEqual(tuple(empty.state.record[13:22]), (254,) + (255,) * 8)
        full = read_scene_cycle(cycle((8, 7, 6, 5, 4, 3, 2, 1, 0)))
        self.assertEqual(full.slots, tuple(range(9)))
        self.assertEqual(full.normalized_slots, ())

    def test_add_scans_eight_uses_first8_as_free_and_never_changes_ninth(self):
        result, inserted = add_cycle_scene(cycle((0, 1, 8, 3, 4, 5, 6, 7, 6)))
        self.assertEqual(inserted, 2)
        self.assertEqual(tuple(result.record[13:22]), (0, 1, 0, 255, 255, 255, 255, 255, 6))
        full = cycle((0, 1, 2, 3, 4, 5, 6, 7, 99))
        unchanged, inserted = add_cycle_scene(full)
        self.assertEqual(unchanged, full)
        self.assertIsNone(inserted)

    def test_delete_null_does_not_read_and_active_delete_reads_then_shifts_nine(self):
        source = cycle((0, 1, 9, 3, 4, 5, 6, 7, 8))
        self.assertEqual(delete_cycle_scene(source, current_slot=None), (source, None))
        result, getter = delete_cycle_scene(source, current_slot=1)
        self.assertEqual(getter.slots, (0, 1))
        self.assertEqual(tuple(result.record[13:22]), (0, 9, 255, 255, 255, 255, 255, 255, 255))
        with self.assertRaisesRegex(EdltError, 'negative index'):
            delete_cycle_scene(source, current_slot=2)

    def test_move_uses_current_grid_rowcount_and_no_getter(self):
        source = cycle((0, 1, 2, 9, 4, 5, 6, 7, 8))
        moved, position = move_cycle_scene(source, index=1, row_count=3, direction='up')
        self.assertEqual(tuple(moved.record[13:22]), (1, 0, 2, 9, 4, 5, 6, 7, 8))
        self.assertEqual(position, 0)
        self.assertEqual(move_cycle_scene(source, index=None, row_count=0, direction='down'), (source, None))
        self.assertEqual(move_cycle_scene(source, index=2, row_count=3, direction='down'), (source, None))
        with self.assertRaises(EdltError):
            move_cycle_scene(source, index=3, row_count=3, direction='up')

    def test_property_states_reject_bad_record_and_boolean_values(self):
        for bad in (OPAQUE[:-1], bytearray(OPAQUE), b'\x02' + OPAQUE[1:]):
            with self.subTest(bad=bad), self.assertRaises(EdltError): SceneWidgetProperties(bad)
        for setter in (set_scene_item, lambda state, value: set_index(state, target='label', value=value)):
            with self.subTest(setter=setter), self.assertRaises(EdltError): setter(SceneWidgetProperties(OPAQUE), True)
        with self.assertRaises(EdltError): set_macro(SceneWidgetProperties(OPAQUE), 'junk|31')

