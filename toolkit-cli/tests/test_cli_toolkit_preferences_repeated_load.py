"""The original manager's second load observes defaults written by its first."""
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.toolkit_preferences_store import HKCU, TOOLKIT_KEY
import test_cli_toolkit_preferences as base_cli_tests
from test_toolkit_preferences_store import Registry, fixture, text


SID = 'S-1-5-21-100-200-300-1001'


class RepeatedPreferenceLoadTests(unittest.TestCase):
    setUp = base_cli_tests.PreferencesCLITests.setUp
    invoke = base_cli_tests.PreferencesCLITests.invoke

    def test_original_empty_store_two_loads_observe_new_default(self):
        registry = Registry()
        self.state['values'] = fixture()['initial_values']
        self.path.write_text(json.dumps(self.state))
        source = self.path.read_bytes()
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', return_value=registry) as backend:
            report = self.invoke('preferences', 'registry-load', self.path, '--repeat-once')
        backend.assert_called_once()
        self.assertEqual(self.path.read_bytes(), source)
        self.assertTrue(report['complete'])
        self.assertTrue(report['repeated_load'])
        self.assertTrue(report['second_load_attempted'])
        first, second = report['load_passes']
        self.assertEqual(first['values'], fixture()['first_load_values'])
        self.assertEqual(second['values'], fixture()['second_load_values'])
        self.assertFalse(first['values']['ShowProjectManager'])
        self.assertTrue(second['values']['ShowProjectManager'])
        self.assertEqual(report['state']['values'], second['values'])
        self.assertEqual(registry.data[HKCU, TOOLKIT_KEY, 'ShowProjectManager'], text('True'))
        self.assertEqual(sum(row[0] == 'default' for row in registry.calls), 4)
        self.assertEqual([row['action'] for row in first['operations'] if row['name'] == 'ShowProjectManager'],
                         ['read', 'read', 'write-preference-default'])
        second_reads = [row for row in second['operations'] if row['name'] == 'ShowProjectManager']
        self.assertEqual([row['action'] for row in second_reads], ['read'])
        self.assertEqual(second_reads[0]['data_hex'], text('True').data.hex())

    def test_incomplete_first_load_never_starts_second(self):
        registry = Registry()
        registry.default_code = 5
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', return_value=registry):
            report = self.invoke('preferences', 'registry-load', self.path, '--repeat-once', status=1)
        self.assertFalse(report['complete'])
        self.assertTrue(report['algorithm_completed'])
        self.assertFalse(report['second_load_attempted'])
        self.assertEqual(len(report['load_passes']), 1)
        self.assertEqual(sum(row[0] == 'default' for row in registry.calls), 2)

    def test_second_load_failure_keeps_both_passes_and_stops(self):
        registry = Registry()
        defaults = 0
        def fail(row):
            nonlocal defaults
            if row[0] == 'default':
                defaults += 1
                if defaults == 3:
                    raise OSError('second load default write failed')
        registry.fault = fail
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', return_value=registry):
            report = self.invoke('preferences', 'registry-load', self.path, '--repeat-once', status=1)
        self.assertTrue(report['second_load_attempted'])
        first, second = report['load_passes']
        self.assertTrue(first['complete'])
        self.assertFalse(second['complete'])
        self.assertEqual(second['operations'][0]['action'], 'write-default')
        self.assertFalse(second['operations'][0]['completed'])
        self.assertEqual(report['error']['message'], 'second load default write failed')
        self.assertEqual(defaults, 3)

    def test_second_load_interruption_exposes_both_receipts(self):
        registry = Registry()
        defaults = 0
        def interrupt(row):
            nonlocal defaults
            if row[0] == 'default':
                defaults += 1
                if defaults == 3:
                    raise KeyboardInterrupt()
        registry.fault = interrupt
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', return_value=registry):
            report = self.invoke('preferences', 'registry-load', self.path, '--repeat-once', status=130)
        evidence = report['toolkit_preferences_repeated_load']
        self.assertTrue(evidence['first']['complete'])
        self.assertFalse(evidence['second']['complete'])
        self.assertTrue(evidence['second_load_attempted'])
        self.assertEqual(evidence['second'], report['toolkit_preferences_evidence'])
        self.assertEqual(defaults, 3)

    def test_sid_guard_rejects_before_both_loads(self):
        with patch('cbus_toolkit._windows_process_token.current_process_user_sid', return_value='S-1-5-18') as token, \
             patch('cbus_toolkit.toolkit_preferences_cli.registry_backend') as backend:
            report = self.invoke('preferences', 'registry-load', self.path, '--repeat-once',
                                 '--expected-user-sid', SID, status=1)
        token.assert_called_once()
        backend.assert_not_called()
        self.assertFalse(report['toolkit_preferences_user_context']['sid_requirement_satisfied'])


if __name__ == '__main__':
    unittest.main()
