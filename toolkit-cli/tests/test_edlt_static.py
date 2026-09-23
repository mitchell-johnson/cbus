"""Whole-unit static references and original-DLL allocation vectors."""
from dataclasses import replace
import unittest

from cbus_toolkit.edlt import EdltLighting, EdltError, EdltApplyError
from test_edlt import fixture, Session


# Original unchanged DLL GetUsedStaticText outputs with byte1=35 and byteN=N.
REFERENCE_VECTORS = {0: (), 2: (13, 14), 3: (10, 11), 4: (9, 10, 11, 12, 13),
                     5: (17, 18), 6: (12,), 7: (11, 12), 8: (9, 10), 9: (7,),
                     10: (), 11: (), 12: (10, 11, 13), 13: (6,), 14: (11, 12),
                     15: (8, 9), 16: (9, 10, 11, 12, 13)}
BLANK_VECTORS = {0: (), 2: (), 3: (), 4: (11, 12, 13), 5: (), 6: (), 7: (11,),
                 8: (9, 10), 9: (7,), 10: (), 11: (), 12: (10, 11, 13),
                 13: (6,), 14: (), 15: (), 16: (11, 12, 13)}


def reserved_fixture():
    values = fixture().defaults()
    values.update({'NavWidgetVariant': '6', 'Widget6WidgetType': '2',
                   'Widget6WidgetByteValue1': '53', 'Widget6WidgetByteValue13': '63',
                   'Widget6WidgetByteValue14': '62', 'Scene1StartAddress': '0'})
    for index in range(1, 5): values[f'PageNameIndex{index}'] = str(61 - index)
    values['SceneBucket'] = ' '.join(map(str, [0, 0, 255, 0, 61] + [0xa5] * 227))
    return values


class EdltStaticTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltLighting(self.spec)

    def test_every_widget_reference_matches_original_dll_vector(self):
        for kind, expected in REFERENCE_VECTORS.items():
            values = self.spec.defaults()
            values['Widget1WidgetType'] = str(kind)
            for offset in range(1, 32): values[f'Widget1WidgetByteValue{offset}'] = str(offset)
            values['Widget1WidgetByteValue1'] = '53'
            with self.subTest(kind=kind):
                self.assertEqual(tuple(n for n in self.editor.static_references(values) if n != 255), expected)
                values['Widget1WidgetByteValue1'] = '0'
                self.assertEqual(tuple(n for n in self.editor.static_references(values) if n != 255), BLANK_VECTORS[kind])

    def test_mra_zone_bits_do_not_hide_static_status_reference(self):
        current = self.spec.defaults()
        current.update({'Widget1WidgetType': '7', 'Widget1WidgetByteValue11': '11', 'Widget1WidgetByteValue12': '12'})
        for zone in range(8):
            for multiplexer in range(4):
                current['Widget1WidgetByteValue1'] = str(5 | (zone << 3) | (multiplexer << 6))
                self.assertEqual(set(self.editor.static_references(current)), {11, 12, 255})

    def test_scene_page_widget_reservations_and_native_descending_reuse(self):
        current = reserved_fixture()
        refs = self.editor.static_references(current)
        self.assertEqual(set(refs), {57, 58, 59, 60, 61, 62, 63, 255})
        self.assertEqual(refs[61], ('Scene1NameIndex',))
        first = self.editor.allocate_static_text(current, 'Māori')
        self.assertEqual(first.index, 56)
        self.assertEqual(first.changes['StaticTextString56'], tuple(bytes.fromhex('4dc4816f726900').ljust(64, b'\0')))
        self.assertFalse(first.reused)
        current.update(first.changes)
        same = self.editor.allocate_static_text(current, 'Māori')
        self.assertEqual((same.index, same.reused, dict(same.changes)), (56, True, {}))
        second = self.editor.allocate_static_text(current, 'Second')
        self.assertEqual(second.index, 56)  # Unbound allocation is not a reservation.
        current.update(second.changes)
        current['Widget6WidgetByteValue13'] = '56'
        third = self.editor.allocate_static_text(current, 'Third')
        self.assertEqual(third.index, 63)  # The former label reference was released.

    def test_ordinal_dedup_does_not_reindex_existing_duplicates(self):
        current = self.spec.defaults()
        current['StaticTextString3'] = current['StaticTextString1']
        reused = self.editor.allocate_static_text(current, 'Lamp')
        self.assertEqual((reused.index, reused.reused), (1, True))
        self.assertEqual(dict(reused.changes), {})
        allocated = self.editor.allocate_static_text(current, 'lamp')
        self.assertEqual((allocated.index, allocated.reused), (63, False))

    def test_utf8_byte_limit_and_null_validation(self):
        current = self.spec.defaults()
        allocation = self.editor.allocate_static_text(current, 'ā' * 31 + 'X')
        self.assertEqual(len(allocation.changes['StaticTextString63']), 64)
        self.assertEqual(allocation.changes['StaticTextString63'][-1], 0)
        for bad in ('A' * 64, 'ā' * 32, '\0', 'A\0B', '  ', '', '\ud800', 5):
            with self.subTest(value=repr(bad)), self.assertRaises(EdltError):
                self.editor.allocate_static_text(current, bad)
        current['StaticTextString0'] = (0xc4, 0) + (0,) * 62
        with self.assertRaisesRegex(EdltError, 'UTF-8'):
            self.editor.allocate_static_text(current, 'Valid')

    def test_full_table_and_unknown_references_cannot_be_overwritten(self):
        current = self.spec.defaults()
        for widget in range(1, 14):
            current[f'Widget{widget}WidgetType'] = '4'
            current[f'Widget{widget}WidgetByteValue1'] = '53'
            for slot, offset in enumerate((9, 10, 11, 12, 13)):
                current[f'Widget{widget}WidgetByteValue{offset}'] = str(min(63, (widget - 1) * 5 + slot))
        self.assertEqual(len(self.editor.static_references(current)), 65)
        with self.assertRaisesRegex(EdltError, 'full'):
            self.editor.allocate_static_text(current, 'New')
        self.assertTrue(self.editor.allocate_static_text(current, 'Lamp').reused)
        for changed in ({'Widget1WidgetType': '99'}, {'Widget1WidgetType': '1'},
                        {'Scene1StartAddress': '232'}, {'Scene1StartAddress': '230'},
                        {'Widget1WidgetType': '2', 'Widget1WidgetByteValue1': '48', 'Widget1WidgetByteValue13': '255'}):
            values = self.spec.defaults(); values.update(changed)
            with self.subTest(changed=changed), self.assertRaises(EdltError):
                self.editor.allocate_static_text(values, 'New')

    def test_zero_scene_count_does_not_hide_a_scene_name_reference(self):
        current = reserved_fixture()
        self.assertEqual(current['SceneCount'], '0')
        # Exact original LoadScenes ignores SceneCount and visits all pointers.
        self.assertEqual(self.editor.static_references(current)[61], ('Scene1NameIndex',))
        current['SceneBucket'] = (0, 255, 255, 0, 61) + (0,) * 227
        with self.assertRaisesRegex(EdltError, 'Truncated scene'):
            self.editor.static_references(current)

    def test_widget_allocation_is_atomic_preserves_other_references_and_can_detach(self):
        session = Session(self.spec)
        session.current = reserved_fixture()
        original = self.editor.snapshot(session.values())
        plan = self.editor.plan(session.values(), page=1, position=2, group=42, mode='dimmer', label_text='Māori')
        self.assertEqual(plan.static_allocation.index, 56)
        session.failure = 'StaticTextString56'
        with self.assertRaises(EdltApplyError): self.editor.apply(session, plan)
        self.assertEqual(self.editor.snapshot(session.values()), original)
        self.assertTrue(self.editor.apply(session, plan)['verified'])
        current = self.editor.snapshot(session.values())
        self.assertEqual(current['Widget6WidgetByteValue13'], (63,))
        self.assertEqual(current['SceneBucket'], original['SceneBucket'])
        self.assertEqual(current['Widget7WidgetByteValue13'], (56,))
        self.editor.configure(session, page=1, position=2, group=42, mode='dimmer', label_type='blank')
        self.assertEqual(self.editor.snapshot(session.values())['StaticTextString56'], current['StaticTextString56'])
        self.assertNotIn(56, self.editor.static_references(session.values()))

    def test_forged_allocated_slot_cannot_overwrite_shared_text(self):
        session = Session(self.spec); session.current = reserved_fixture()
        plan = self.editor.plan(session.values(), page=1, position=2, group=42, mode='dimmer', label_text='New')
        forged = replace(plan, static_allocation=replace(plan.static_allocation, index=63))
        with self.assertRaisesRegex(EdltError, 'allocation'):
            self.editor.apply(session, forged)
        self.assertEqual(session.calls, [])

    def test_label_and_status_text_follow_original_property_order_and_dedup(self):
        current = reserved_fixture()
        first = self.editor.plan(current, page=1, position=1, group=0, mode='off-on',
                                 label_text='Pair A', status_text='Pair B')
        self.assertEqual((first.static_allocation.index, first.status_allocation.index), (56, 63))
        self.assertEqual((first.record[13], first.record[14], first.record[1]), (56, 63, 0x35))
        updated = dict(first.expected); updated.update(first.changes)
        same = self.editor.plan(updated, page=1, position=1, group=0, mode='off-on',
                                label_text='Shared', status_text='Shared')
        self.assertEqual((same.static_allocation.index, same.status_allocation.index), (62, 62))
        self.assertTrue(same.status_allocation.reused)
        self.assertEqual(dict(same.status_allocation.changes), {})
        session = Session(self.spec); session.current = current
        self.assertTrue(self.editor.apply(session, first)['verified'])
        self.assertEqual(self.editor.static_references(session.values())[63], ('Widget6WidgetByteValue14',))
        self.assertTrue(self.editor.apply(session, same)['verified'])

    def test_two_new_widget_texts_use_distinct_slots_and_reject_conflicting_options(self):
        session = Session(self.spec)
        plan = self.editor.plan(session.values(), page=1, position=1, group=42, mode='dimmer',
                                label_text='Office', status_text='Occupied')
        self.assertEqual((plan.record[13], plan.record[14]), (63, 62))
        self.assertTrue(self.editor.apply(session, plan)['verified'])
        for bad in ({'status_type': 'level'}, {'status_index': 3}, {'status_text': '\0'}, {'status_text': 'ā' * 32}):
            options = dict(page=1, position=1, group=42, mode='dimmer', status_text='New'); options.update(bad)
            with self.subTest(bad=bad), self.assertRaises(EdltError):
                self.editor.plan(session.values(), **options)

    def test_second_allocation_failure_does_not_stage_first_allocation(self):
        session = Session(self.spec)
        # Missing every free slot is independently covered above. Here a bad
        # second text must also fail before apply/set can stage the first one.
        before = self.editor.snapshot(session.values())
        with self.assertRaises(EdltError):
            self.editor.configure(session, page=1, position=1, group=42, mode='dimmer',
                                  label_text='Valid first', status_text='X' * 64)
        self.assertEqual(session.calls, [])
        self.assertEqual(self.editor.snapshot(session.values()), before)
        for widget in range(1, 14):
            session.current[f'Widget{widget}WidgetType'] = '4'
            session.current[f'Widget{widget}WidgetByteValue1'] = '53'
            for slot, offset in enumerate((9, 10, 11, 12, 13)):
                session.current[f'Widget{widget}WidgetByteValue{offset}'] = str(min(61, (widget - 1) * 5 + slot))
        before = self.editor.snapshot(session.values())
        self.assertEqual(len(self.editor.static_references(before)), 63)
        with self.assertRaisesRegex(EdltError, 'full'):
            self.editor.configure(session, page=4, position=4, page_mode='multiple', group=42,
                                  mode='dimmer', label_text='First fits', status_text='Second exceeds capacity')
        self.assertEqual(session.calls, [])
        self.assertEqual(self.editor.snapshot(session.values()), before)


if __name__ == '__main__':
    unittest.main()
