"""Real Win32 byte-preserving preference storage through the owned VM runner."""
import os
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.windows_preferences import WindowsPreferenceRegistry


class WindowsPreferenceAdapterTests(unittest.TestCase):
    def test_windows_is_required_and_adapter_does_not_open_registry_on_construction(self):
        if os.name != 'nt':
            with self.assertRaisesRegex(RuntimeError, 'requires Windows'):
                WindowsPreferenceRegistry()
        else:
            adapter=WindowsPreferenceRegistry(test_namespace='constructor-only')
            self.assertEqual(adapter.test_namespace,'constructor-only')

    @unittest.skipUnless(os.environ.get('CBUS_WINDOWS_PROVENANCE_ROOT'),
                         'Set the owned Windows provenance root for native registry acceptance')
    def test_native_raw_bytes_full40_store_defaults_and_owned_cleanup(self):
        from research.windows_preferences_probe import run_native_preferences
        root=Path(__file__).resolve().parents[1]/'research/runtime'
        root.mkdir(parents=True,exist_ok=True)
        # Retain the admitted job and raw result for subsequent acceptance audits.
        folder=Path(tempfile.mkdtemp(prefix='windows-preferences-',dir=root))
        result=run_native_preferences(folder)
        self.assertTrue(result['passed'],str(folder))
        native=result['native']
        self.assertEqual(native['tests_run'],13)
        self.assertEqual((native['failures'],native['errors'],native['skipped']),(0,0,0))
        self.assertFalse(native['real_toolkit_registry_touched'])
        self.assertEqual(len(native['cleanup']),13)
        self.assertTrue(all(row['removed'] for row in native['cleanup']))
        self.assertTrue(result['input_hashes_unchanged'])


if __name__=='__main__':unittest.main()
