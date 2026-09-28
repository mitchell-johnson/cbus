"""Explicit preference-user admission precedes every effectful registry path."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from cbus_toolkit.toolkit_preferences_store import HKCU, TOOLKIT_KEY, REG_SZ, RegistryValue
from test_cli_toolkit_preferences import PreferencesCLITests
from test_toolkit_preferences_reset import MemoryRegistry
from test_toolkit_preferences_store import Registry


SID = 'S-1-5-21-100-200-300-1001'
OTHER_SID = 'S-1-5-18'


class PreferenceUserGuardTests(unittest.TestCase):
    setUp = PreferencesCLITests.setUp
    invoke = PreferencesCLITests.invoke

    def test_invalid_sid_rejects_before_state_file_and_registry_backend(self):
        self.path.unlink()
        with patch('cbus_toolkit._windows_process_token.current_process_user_sid') as token, \
             patch('cbus_toolkit.toolkit_preferences_cli.registry_backend') as backend:
            for action in ('registry-load', 'registry-save'):
                result = self.invoke('preferences', action, self.path,
                                     '--expected-user-sid', 'S-1-5-021', status=1)
                self.assertIn('canonical', result['error'])
        token.assert_not_called()
        backend.assert_not_called()

    def test_wrong_process_user_prevents_load_save_and_reset_before_backend(self):
        with patch('cbus_toolkit._windows_process_token.current_process_user_sid',
                   return_value=OTHER_SID) as token, \
             patch('cbus_toolkit.toolkit_preferences_cli.registry_backend') as store_backend, \
             patch('cbus_toolkit.toolkit_preferences_cli.reset_registry_backend') as reset_backend:
            for action in ('registry-load', 'registry-save', 'reset-dont-ask-again'):
                args = (self.path,) if action != 'reset-dont-ask-again' else ()
                result = self.invoke('preferences', action, *args,
                                     '--expected-user-sid', SID, status=1)
                context = result['toolkit_preferences_user_context']
                self.assertEqual(context['expected_user_sid'], SID)
                self.assertEqual(context['process_token_user_sid'], OTHER_SID)
                self.assertTrue(context['primary_process_token_verified'])
                self.assertFalse(context['sid_requirement_satisfied'])
                self.assertFalse(context['interactive_user_context_verified'])
        self.assertEqual(token.call_count, 3)
        store_backend.assert_not_called()
        reset_backend.assert_not_called()

    def test_token_query_failure_prevents_any_registry_backend(self):
        with patch('cbus_toolkit._windows_process_token.current_process_user_sid',
                   side_effect=OSError('token query failed')), \
             patch('cbus_toolkit.toolkit_preferences_cli.registry_backend') as backend:
            result = self.invoke('preferences', 'registry-load', self.path,
                                 '--expected-user-sid', SID, status=1)
        backend.assert_not_called()
        self.assertIn('token query failed', result['error'])
        self.assertFalse(result['toolkit_preferences_user_context']['primary_process_token_verified'])

    def test_matching_process_user_admits_repeated_registry_reads(self):
        registry = Registry()
        with patch('cbus_toolkit._windows_process_token.current_process_user_sid',
                   return_value=SID) as token, \
             patch('cbus_toolkit.toolkit_preferences_cli.registry_backend',
                   return_value=registry):
            saved = self.invoke('preferences', 'registry-save', self.path,
                                '--expected-user-sid', SID)
            first = self.invoke('preferences', 'registry-load', self.path,
                                '--expected-user-sid', SID)
            registry.data[HKCU, TOOLKIT_KEY, 'TemperatureUnit'] = RegistryValue(
                REG_SZ, '1\0'.encode('utf-16-le'))
            second = self.invoke('preferences', 'registry-load', self.path,
                                 '--expected-user-sid', SID)
        self.assertEqual(token.call_count, 3)
        self.assertEqual(first['state']['values']['TemperatureUnit'], 0)
        self.assertEqual(second['state']['values']['TemperatureUnit'], 1)
        self.assertTrue(saved['user_context']['sid_requirement_satisfied'])
        self.assertTrue(second['user_context']['primary_process_token_verified'])
        self.assertFalse(second['user_context']['interactive_user_context_verified'])

    def test_matching_user_reset_and_dry_runs(self):
        backend = MemoryRegistry(['child'])
        with patch('cbus_toolkit._windows_process_token.current_process_user_sid',
                   return_value=SID) as token, \
             patch('cbus_toolkit.toolkit_preferences_cli.registry_backend') as store_backend, \
             patch('cbus_toolkit.toolkit_preferences_cli.reset_registry_backend',
                   return_value=backend) as reset_backend:
            save_preview = self.invoke('preferences', 'registry-save', self.path,
                                       '--dry-run', '--expected-user-sid', SID)
            reset_preview = self.invoke('preferences', 'reset-dont-ask-again',
                                        '--dry-run', '--expected-user-sid', SID)
            self.assertFalse(save_preview['sid_admission_performed'])
            self.assertFalse(reset_preview['sid_admission_performed'])
            token.assert_not_called()
            store_backend.assert_not_called()
            reset_backend.assert_not_called()
            result = self.invoke('preferences', 'reset-dont-ask-again',
                                 '--expected-user-sid', SID)
        self.assertTrue(result['complete'])
        self.assertTrue(result['user_context']['sid_requirement_satisfied'])
        token.assert_called_once()
        reset_backend.assert_called_once()
