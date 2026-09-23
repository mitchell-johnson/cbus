"""Original reset traversal over actual Windows keys in owned test namespaces."""
import os
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.windows_preferences_reset import WindowsDontAskAgainRegistry


class WindowsResetAdapterTests(unittest.TestCase):
    def test_constructor_requires_windows_and_rejects_invalid_test_namespaces(self):
        for value in ('', '../escape', 'two\\parts', True, 'x' * 65):
            with self.assertRaises(ValueError):
                WindowsDontAskAgainRegistry(test_namespace=value)
        if os.name != 'nt':
            with self.assertRaisesRegex(RuntimeError, 'requires Windows'):
                WindowsDontAskAgainRegistry()
        else:
            adapter = WindowsDontAskAgainRegistry(test_namespace='constructor-only')
            self.assertEqual(adapter._handles, {})

    @unittest.skipUnless(os.environ.get('CBUS_WINDOWS_PROVENANCE_ROOT'),
                         'Set the owned Windows provenance root for native registry acceptance')
    def test_native_scoped_deletion_failures_bounds_and_owned_cleanup(self):
        from research.windows_preferences_reset_probe import run_native_reset
        runtime = Path(__file__).resolve().parents[1] / 'research/runtime'
        runtime.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix='windows-preferences-reset-', dir=runtime))
        result = run_native_reset(folder)
        self.assertTrue(result['passed'], str(folder))
        self.assertTrue(result['inputs_unchanged'])
        native = result['native']
        self.assertEqual(native['tests_run'], 8)
        self.assertEqual((native['failures'], native['errors'], native['skipped']), (0, 0, 0))
        self.assertEqual(native['bits'], 32)
        self.assertFalse(native['real_toolkit_registry_touched'])
        self.assertEqual(len(native['cleanup']), 8)
        self.assertTrue(all(row['removed'] for row in native['cleanup']))


if __name__ == '__main__':
    unittest.main()
