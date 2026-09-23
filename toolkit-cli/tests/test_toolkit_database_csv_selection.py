import os
import unittest

from cbus_toolkit.toolkit_database_csv import COLUMNS, COLUMN_LABELS
from cbus_toolkit.toolkit_database_csv_selection import (
    ALL_COLUMNS_MASK, CSV_SELECTION_KEY, CSV_SELECTION_VALUE, HKCU,
    SELECT_ALL_SENTINEL, ToolkitDatabaseCSVSelectionStore,
    columns_mask, decode_selection, encode_selection,
)
from cbus_toolkit.windows_csv_selection import WindowsCSVSelectionRegistry


class MemoryRegistry:
    def __init__(self, value=...):
        self.value = value
        self.calls = []
        self.error = None

    def read_selection(self, hive, key, name):
        self.calls.append(('read', hive, key, name))
        if self.error is not None:
            raise self.error
        if self.value is ...:
            raise FileNotFoundError(name)
        return self.value

    def write_selection(self, hive, key, name, value):
        self.calls.append(('write', hive, key, name, value))
        if self.error is not None:
            raise self.error
        self.value = value


class ToolkitDatabaseCSVSelectionTests(unittest.TestCase):
    def test_absent_original_value_uses_select_all_default(self):
        registry = MemoryRegistry()
        store = ToolkitDatabaseCSVSelectionStore(registry)
        selection = store.load()
        self.assertEqual(selection.columns, COLUMNS)
        self.assertEqual(selection.mask, ALL_COLUMNS_MASK)
        self.assertEqual(selection.stored_text, SELECT_ALL_SENTINEL)
        self.assertTrue(selection.default_used)
        self.assertTrue(selection.ok_enabled)
        self.assertEqual(registry.calls, [('read', HKCU, CSV_SELECTION_KEY,
                                           CSV_SELECTION_VALUE)])
        self.assertFalse(store.last_evidence['value_present'])
        self.assertTrue(store.last_evidence['complete'])

    def test_original_case_sensitive_substring_selection_and_ordinal_order(self):
        value = 'ignored,Group 16,XUnit Address,Tag Name,Group 1,tag name,'
        selection = decode_selection(value)
        # Pos(label + ',', storage) is not tokenized: XUnit Address still selects
        # Unit Address, while lower-case tag name remains ignored.
        self.assertEqual(selection.columns,
                         ('address', 'tag_name', 'group_1', 'group_16'))
        self.assertEqual(selection.mask, ((1 << 0) | (1 << 2) |
                                          (1 << 10) | (1 << 25)))
        self.assertFalse(selection.default_used)
        self.assertTrue(selection.ok_enabled)

    def test_empty_and_unknown_values_disable_original_ok_button(self):
        for value in ('', 'Select All', 'Unknown,', 'unit address,'):
            with self.subTest(value=value):
                selection = decode_selection(value)
                self.assertEqual(selection.columns, ())
                self.assertEqual(selection.mask, 0)
                self.assertFalse(selection.ok_enabled)

    def test_ok_handler_encoding_is_canonical_and_comma_terminated(self):
        columns = ('address', 'tag_name', 'group_16')
        text = encode_selection(columns)
        self.assertEqual(text, 'Unit Address,Tag Name,Group 16,')
        self.assertEqual(decode_selection(text).columns, columns)
        self.assertEqual(columns_mask(columns), (1 << 0) | (1 << 2) | (1 << 25))
        all_text = encode_selection(COLUMNS)
        self.assertNotEqual(all_text, SELECT_ALL_SENTINEL)
        self.assertTrue(all_text.endswith(COLUMN_LABELS['group_16'] + ','))
        self.assertEqual(decode_selection(all_text).mask, ALL_COLUMNS_MASK)

    def test_save_writes_exact_original_location_and_text(self):
        registry = MemoryRegistry()
        store = ToolkitDatabaseCSVSelectionStore(registry)
        result = store.save(('address', 'serial'))
        self.assertEqual(result.columns, ('address', 'serial'))
        self.assertEqual(registry.value, 'Unit Address,Serial Number,')
        self.assertEqual(registry.calls, [('write', HKCU, CSV_SELECTION_KEY,
            CSV_SELECTION_VALUE, 'Unit Address,Serial Number,')])
        self.assertTrue(store.last_evidence['complete'])

    def test_backend_error_preserves_partial_evidence(self):
        registry = MemoryRegistry('Unit Address,')
        registry.error = OSError('registry denied')
        store = ToolkitDatabaseCSVSelectionStore(registry)
        with self.assertRaisesRegex(OSError, 'registry denied') as caught:
            store.load()
        self.assertIs(store.last_error, caught.exception)
        self.assertFalse(store.last_evidence['complete'])
        self.assertTrue(store.last_evidence['read_attempted'])
        self.assertEqual(store.last_evidence['error']['type'], 'OSError')

    def test_invalid_inputs_and_non_windows_adapter_reject(self):
        for value in (None, 1, 'bad\0value', '\ud800'):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                decode_selection(value)
        with self.assertRaises(ValueError):
            encode_selection(())
        if os.name != 'nt':
            with self.assertRaisesRegex(RuntimeError, 'requires Windows'):
                WindowsCSVSelectionRegistry()


if __name__ == '__main__':
    unittest.main()
