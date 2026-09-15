import json
import unittest
from unittest.mock import patch

import test_cli_toolkit_preferences as base_cli_tests
from test_toolkit_preferences_store import seeded, text
from cbus_toolkit.toolkit_preferences_store import HKCU, HKLM, TOOLKIT_KEY


class NumericPreferencesCLITests(unittest.TestCase):
    setUp = base_cli_tests.PreferencesCLITests.setUp
    invoke = base_cli_tests.PreferencesCLITests.invoke

    def test_explicit_locale_controls_and_heap_conversion_preserve_input(self):
        before = self.path.read_bytes()
        for locale, separators, expected in [('dot', ['.', ','], 64), ('comma', [',', '.'], 645)]:
            shown = self.invoke('preferences', 'controls', self.path, '--numeric-locale', locale)
            self.assertEqual(shown['numeric_locale'], separators)
            result = self.invoke('preferences', 'plan', self.path, '--numeric-locale', locale,
                                 '--edit', 'cmbJavaHeapMax="64.5"')
            self.assertEqual(result['values']['JavaHeapMax'], expected)
            self.assertEqual(result['heap_conversion']['value'], expected)
            self.assertEqual(result['controls']['controls']['cmbJavaHeapMax'], '64.5')
            self.assertEqual(result['numeric_locale'], separators)
            self.assertEqual(result['state']['values']['JavaHeapMax'], expected)
            self.assertFalse(result['storage_applied'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_wrapped_integer_is_reported_and_unsupported_heap_is_rejected(self):
        result = self.invoke('preferences', 'plan', self.path, '--numeric-locale', 'dot',
                             '--edit', 'cmbJavaHeapMax="4294967360"')
        self.assertEqual(result['values']['JavaHeapMax'], 64)
        self.assertTrue(result['heap_conversion']['int32_wrapped'])
        self.assertEqual(result['heap_conversion']['truncated_integer'], 4294967360)
        for value in ('9223372036854775808', '.2.3', '６４', '63.9'):
            self.invoke('preferences', 'plan', self.path, '--numeric-locale', 'dot',
                        '--edit', 'cmbJavaHeapMax=' + json.dumps(value), status=1)

    def test_registry_load_uses_explicit_locale_and_preserves_fallback_bytes(self):
        for locale, expected in [('dot', 64), ('comma', 645)]:
            registry = seeded()
            registry.data.pop((HKCU, TOOLKIT_KEY, 'TemperatureUnit'))
            original = text('64.5')
            registry.data[HKLM, TOOLKIT_KEY, 'TemperatureUnit'] = original
            with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', return_value=registry):
                result = self.invoke('preferences', 'registry-load', self.path, '--numeric-locale', locale)
            self.assertTrue(result['complete'])
            self.assertEqual(result['values']['TemperatureUnit'], expected)
            self.assertEqual(result['state']['values']['TemperatureUnit'], expected)
            self.assertEqual(registry.data[HKCU, TOOLKIT_KEY, 'TemperatureUnit'], original)

    def test_known_conversion_error_reports_copied_prefix_and_retained_state(self):
        registry = seeded()
        registry.data.pop((HKCU, TOOLKIT_KEY, 'TemperatureUnit'))
        original = text('.2.3')
        registry.data[HKLM, TOOLKIT_KEY, 'TemperatureUnit'] = original
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', return_value=registry):
            result = self.invoke('preferences', 'registry-load', self.path, '--numeric-locale', 'dot', status=1)
        self.assertFalse(result['complete'])
        self.assertFalse(result['algorithm_completed'])
        self.assertEqual(result['error']['type'], 'ToolkitNumericConversionError')
        self.assertEqual(result['values']['TemperatureUnit'], self.state['values']['TemperatureUnit'])
        self.assertEqual(registry.data[HKCU, TOOLKIT_KEY, 'TemperatureUnit'], original)
        self.assertFalse(any(row['name'] == 'DoNotPauseEventsWhileLoadingProject' for row in result['operations']))

    def test_default_cli_remains_canonical_without_numeric_metadata(self):
        shown = self.invoke('preferences', 'controls', self.path)
        self.assertNotIn('numeric_locale', shown)
        result = self.invoke('preferences', 'plan', self.path)
        self.assertNotIn('numeric_locale', result)
        self.assertNotIn('heap_conversion', result)
        self.invoke('preferences', 'plan', self.path, '--edit', 'cmbJavaHeapMax="64.5"', status=1)
        registry = seeded()
        registry.data.pop((HKCU, TOOLKIT_KEY, 'TemperatureUnit'))
        registry.data[HKLM, TOOLKIT_KEY, 'TemperatureUnit'] = text('64.5')
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', return_value=registry):
            result = self.invoke('preferences', 'registry-load', self.path, status=1)
        self.assertNotIn('numeric_locale', result)
        self.assertNotIn((HKCU, TOOLKIT_KEY, 'TemperatureUnit'), registry.data)


if __name__ == '__main__':
    unittest.main()
