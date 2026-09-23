"""Real Win32 CSV-selection persistence in an owned redirected registry key."""
import os
import unittest
import uuid

from cbus_toolkit.toolkit_database_csv_selection import (
    CSV_SELECTION_KEY, CSV_SELECTION_VALUE, ToolkitDatabaseCSVSelectionStore,
)
from cbus_toolkit.windows_csv_selection import WindowsCSVSelectionRegistry


class WindowsCSVSelectionTests(unittest.TestCase):
    def test_windows_is_required_and_construction_has_no_registry_effect(self):
        if os.name != 'nt':
            with self.assertRaisesRegex(RuntimeError, 'requires Windows'):
                WindowsCSVSelectionRegistry()
        else:
            adapter = WindowsCSVSelectionRegistry(test_namespace='constructor-only')
            self.assertEqual(adapter.test_namespace, 'constructor-only')

    @unittest.skipUnless(os.name == 'nt' and
                         os.environ.get('CBUS_WINDOWS_CSV_SELECTION'),
                         'Set CBUS_WINDOWS_CSV_SELECTION on an owned Windows host')
    def test_native_32bit_reg_sz_roundtrip_and_owned_cleanup(self):
        import winreg
        namespace = 'csv-selection-' + uuid.uuid4().hex
        base = 'Software\\CBusToolkitCli\\Tests\\' + namespace
        redirected = base + '\\HKCU\\' + CSV_SELECTION_KEY
        adapter = WindowsCSVSelectionRegistry(test_namespace=namespace)
        store = ToolkitDatabaseCSVSelectionStore(adapter)

        def remove_tree(path):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                                    winreg.KEY_READ | winreg.KEY_WRITE |
                                    winreg.KEY_WOW64_32KEY) as handle:
                    children = []
                    index = 0
                    while True:
                        try:
                            children.append(winreg.EnumKey(handle, index))
                            index += 1
                        except OSError:
                            break
                for child in children:
                    remove_tree(path + '\\' + child)
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path,
                                   winreg.KEY_WOW64_32KEY, 0)
            except FileNotFoundError:
                pass

        try:
            # Missing storage follows the original SelectAll default.
            loaded = store.load()
            self.assertTrue(loaded.default_used)
            self.assertEqual(len(loaded.columns), 26)

            saved = store.save(('address', 'tag_name', 'group_16'))
            self.assertEqual(saved.columns, ('address', 'tag_name', 'group_16'))
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, redirected, 0,
                                winreg.KEY_QUERY_VALUE |
                                winreg.KEY_WOW64_32KEY) as handle:
                value, kind = winreg.QueryValueEx(handle, CSV_SELECTION_VALUE)
            self.assertEqual(kind, winreg.REG_SZ)
            self.assertEqual(value, 'Unit Address,Tag Name,Group 16,')
            self.assertEqual(store.load().columns,
                             ('address', 'tag_name', 'group_16'))

            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, redirected, 0,
                                    winreg.KEY_SET_VALUE |
                                    winreg.KEY_WOW64_32KEY) as handle:
                winreg.SetValueEx(handle, CSV_SELECTION_VALUE, 0,
                                  winreg.REG_DWORD, 7)
            with self.assertRaisesRegex(ValueError, 'requires REG_SZ'):
                store.load()
        finally:
            remove_tree(base)
        with self.assertRaises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, base, 0,
                           winreg.KEY_READ | winreg.KEY_WOW64_32KEY)


if __name__ == '__main__':
    unittest.main()
