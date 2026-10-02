"""Literal grid bytes and ordered parent ownership, independent of a GUI."""
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_static_text_dialog import normalize, project
from tests import test_edlt_parent_transaction as parent_fixture


def edit(index, text, *, close='button'):
    return {'op': 'static-text-dialog', 'close': close,
            'edits': [{'index': index, 'text': text}]}


class StaticTextDialogTests(unittest.TestCase):
    def setUp(self):
        self.base = {f'StaticTextString{i}': (0,) * 64 for i in range(64)}

    def test_indexed_repeated_edits_keep_allocation_and_references_unchanged(self):
        op = {'op': 'static-text-dialog', 'edits': [
            {'index': 3, 'text': 'first'}, {'index': 63, 'text': 'other'},
            {'index': 3, 'text': 'last'}]}
        changes, receipt = project(self.base, op)
        self.assertEqual(changes['StaticTextString3'][:5], (108, 97, 115, 116, 0))
        self.assertEqual(set(changes), {'StaticTextString3', 'StaticTextString63'})
        self.assertEqual(receipt['allocated_indices'], [])
        self.assertFalse(receipt['existing_references_reindexed'])

    def test_literal_utf8_prefix_limit_including_split_character(self):
        cases = [('A' * 64, [65] * 63 + [0]),
                 ('A' * 62 + 'ā', [65] * 62 + [196, 0]),
                 ('ā' * 31 + 'X', [196, 129] * 31 + [88, 0]),
                 ('A\0B', [65, 0, 0] + [0] * 61)]
        for text, expected in cases:
            with self.subTest(text=text):
                changes, receipt = project(self.base, edit(0, text))
                self.assertEqual(list(changes['StaticTextString0']), expected)
                self.assertEqual(receipt['rows'][0]['utf8_prefix_split'], text == 'A' * 62 + 'ā')

    def test_window_close_saves_committed_edits_like_button(self):
        button, _ = project(self.base, edit(2, 'Lamp'))
        window, receipt = project(self.base, edit(2, 'Lamp', close='window'))
        self.assertEqual(button, window)
        self.assertTrue(receipt['save_static_text_called_on_close'])
        self.assertFalse(receipt['accepted_result_checked'])
        self.assertFalse(receipt['cancel_rollback'])

    def test_empty_and_whitespace_are_real_grid_names(self):
        base = {**self.base, 'StaticTextString1': tuple(b'old\0'.ljust(64, b'\0'))}
        changes, _ = project(base, edit(1, ''))
        self.assertEqual(changes['StaticTextString1'], (0,) * 64)
        changes, _ = project(base, edit(1, '  '))
        self.assertEqual(changes['StaticTextString1'][:3], (32, 32, 0))

    def test_unchanged_text_preserves_trailing_bytes(self):
        base = {**self.base, 'StaticTextString1': (65, 0) + (165,) * 62}
        changes, receipt = project(base, edit(1, 'A'))
        self.assertEqual(changes, {})
        self.assertEqual(receipt['rows'], [])

    def test_ui_uses_utf16_units_not_codepoints(self):
        normalize(edit(0, '😀' * 32))
        for text in ('😀' * 33, 'A' * 65, '\ud800'):
            with self.subTest(text=repr(text)), self.assertRaises(EdltError):
                normalize(edit(0, text))

    def test_refuse_unknown_shape_cancel_allocator_and_incomplete_or_invalid_rows(self):
        for op in ({**edit(0, 'A'), 'cancel': True}, edit(64, 'A'), edit(True, 'A'),
                   edit(-1, 'A'), edit(0, 3), edit(0, 'A', close='cancel')):
            with self.subTest(op=op), self.assertRaises(EdltError): normalize(op)
        for values in ({}, {**self.base, 'StaticTextString1': (0,) * 63},
                       {**self.base, 'StaticTextString1': (196, 0) + (0,) * 62}):
            with self.subTest(values=list(values)[:1]), self.assertRaises(EdltError):
                project(values, edit(0, 'A'))


class StaticTextParentTests(unittest.TestCase):
    def setUp(self):
        self.helper = parent_fixture.ParentTransactionTests()
        self.helper.setUp()

    def test_grid_before_widget_is_reused_and_one_terminal_crc_pass(self):
        plan = self.helper.plan((edit(3, 'New'), parent_fixture.lighting(label_text='New'), parent_fixture.measurement()))
        self.assertEqual(plan.after_controls['Widget7WidgetByteValue13'], (3,))
        self.assertEqual(plan.after_controls['StaticTextString3'][:4], (78, 101, 119, 0))
        self.assertEqual(plan.as_dict()['execution_counts']['terminal_crc_passes'], 1)

    def test_grid_after_widget_changes_referenced_row_without_reindex(self):
        plan = self.helper.plan((parent_fixture.lighting(label_text='New'), edit(63, 'Edited'), parent_fixture.measurement()))
        self.assertEqual(plan.after_controls['Widget7WidgetByteValue13'], (63,))
        self.assertEqual(plan.after_controls['StaticTextString63'][:7], (69, 100, 105, 116, 101, 100, 0))

    def test_repeated_dialog_keeps_last_row_and_unchanged_other_pp(self):
        plan = self.helper.plan((edit(3, 'First'), edit(3, 'Final')))
        self.assertEqual(plan.after_controls['StaticTextString3'][:6], (70, 105, 110, 97, 108, 0))
        for name, value in plan.after_load.items():
            if name != 'StaticTextString3':
                self.assertEqual(plan.after_controls[name], value, name)


if __name__ == '__main__':
    unittest.main()
