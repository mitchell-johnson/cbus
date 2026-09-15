import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_cli_toolkit_preferences as base_cli_tests
from cbus_toolkit.toolkit_preferences_cli import error_payload, read_state
from cbus_toolkit.toolkit_preferences_initial_state import constructor_state
from cbus_toolkit.toolkit_preferences_reset import DONT_ASK_AGAIN_KEY
from test_toolkit_preferences_reset import MemoryRegistry


class PreferenceActionCLITests(unittest.TestCase):
    setUp = base_cli_tests.PreferencesCLITests.setUp
    invoke = base_cli_tests.PreferencesCLITests.invoke

    def test_initial_state_exact_format_is_reusable_without_registry_access(self):
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', side_effect=AssertionError('No registry access')):
            result = self.invoke('preferences', 'initial-state')
        self.assertEqual(result, constructor_state())
        self.assertEqual(set(result), {'format', 'values', 'display_values'})
        self.assertEqual((len(result['values']), len(result['display_values'])), (40, 5))
        self.path.write_text(json.dumps(result))
        values, flags = read_state(self.path)
        self.assertEqual(values, result['values'])
        self.assertEqual(flags, result['display_values'])

    def test_constructor_values_remain_distinct_from_runtime_and_registry_defaults(self):
        state = self.invoke('preferences', 'initial-state')
        self.assertFalse(state['values']['ShowProjectManager'])
        self.assertEqual(state['values']['JavaHeapMax'], 0)
        self.path.write_text(json.dumps(state))
        self.invoke('preferences', 'plan', self.path, status=1)
        plan = self.invoke('preferences', 'plan', self.path, '--edit', 'cmbJavaHeapMax="512"')
        self.assertEqual(plan['values']['JavaHeapMax'], 512)
        self.assertEqual(plan['values']['JavaHeapMin'], 32)
        self.assertEqual(plan['controls']['address_preview'], 'Level 10')

    def test_reset_preview_exact_target_and_bounds_never_construct_backend(self):
        with patch('cbus_toolkit.toolkit_preferences_cli.reset_registry_backend', side_effect=AssertionError('No registry access')):
            result = self.invoke('preferences', 'reset-dont-ask-again', '--dry-run', '--max-keys', '301')
            for option, value in [('--max-keys', '0'), ('--max-depth', '-1'), ('--max-name-units', '1000001')]:
                self.invoke('preferences', 'reset-dont-ask-again', option, value, status=1)
        self.assertEqual(result['key'], DONT_ASK_AGAIN_KEY)
        self.assertEqual(result['limits'], {'max_keys': 301, 'max_depth': 32, 'max_name_units': 1024})
        self.assertFalse(result['registry_accessed'])
        self.assertFalse(result['writes_applied'])
        self.assertNotIn('complete', result)

    def test_reset_success_preserves_original_notice_and_reports_status_only(self):
        backend = MemoryRegistry(['parent\\child', 'Māori'])
        with patch('cbus_toolkit.toolkit_preferences_cli.reset_registry_backend', return_value=backend):
            result = self.invoke('preferences', 'reset-dont-ask-again')
        self.assertTrue(result['complete'])
        self.assertTrue(result['target_delete_succeeded'])
        self.assertTrue(result['original_notice_requested'])
        self.assertFalse(result['absence_verified'])
        self.assertFalse(result['notice_displayed'])
        self.assertEqual(backend.nodes, {})
        self.assertEqual(backend.handles, {})

    def test_missing_target_retains_status_and_original_notice_without_success(self):
        backend = MemoryRegistry(None)
        with patch('cbus_toolkit.toolkit_preferences_cli.reset_registry_backend', return_value=backend):
            result = self.invoke('preferences', 'reset-dont-ask-again', status=1)
        self.assertFalse(result['complete'])
        self.assertFalse(result['target_delete_succeeded'])
        self.assertTrue(result['already_absent'])
        self.assertTrue(result['original_notice_requested'])
        self.assertEqual([row['operation'] for row in result['operations']], ['open', 'delete'])
        self.assertEqual(result['operations'][-1]['status'], 2)

    def test_uncertain_delete_keeps_prefix_and_never_replays(self):
        backend = MemoryRegistry(['child'])
        def fault(row):
            if row == ('delete', DONT_ASK_AGAIN_KEY + '\\child'):
                del backend.nodes[row[1]]
                raise OSError('Reply lost after child deletion')
        backend.fault = fault
        with patch('cbus_toolkit.toolkit_preferences_cli.reset_registry_backend', return_value=backend):
            result = self.invoke('preferences', 'reset-dont-ask-again', status=1)
        self.assertFalse(result['complete'])
        self.assertFalse(result['original_notice_requested'])
        self.assertEqual(result['error']['message'], 'Reply lost after child deletion')
        self.assertEqual(sum(row[0] == 'delete' for row in backend.calls), 1)
        self.assertIn(DONT_ASK_AGAIN_KEY, backend.nodes)
        self.assertEqual(backend.handles, {})

    def test_interruption_fallback_keeps_primary_error_and_cleanup_evidence(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name == 'toolkit_preferences_reset_evidence':
                    raise SystemExit('Evidence attachment rejected')
                return super().__setattr__(name, value)
        backend = MemoryRegistry(['child'])
        def fault(row):
            if row == ('delete', DONT_ASK_AGAIN_KEY + '\\child'):
                raise RejectEvidence('primary')
            if row == ('close', DONT_ASK_AGAIN_KEY):
                raise SystemExit('secondary')
        backend.fault = fault
        with patch('cbus_toolkit.toolkit_preferences_cli.reset_registry_backend', return_value=backend):
            result = self.invoke('preferences', 'reset-dont-ask-again', status=130)
        evidence = result['toolkit_preferences_reset_evidence']
        self.assertEqual(evidence['error']['message'], 'primary')
        self.assertEqual(evidence['cleanup_errors'][0]['message'], 'secondary')
        self.assertFalse(evidence['complete'])
        self.assertEqual(sum(row[0] == 'delete' for row in backend.calls), 1)

    def test_hostile_getters_use_only_matching_manager_evidence(self):
        for action, manager_name, evidence_name in (
                ('reset-dont-ask-again', '_preferences_reset', 'toolkit_preferences_reset_evidence'),
                ('registry-save', '_preferences_store', 'toolkit_preferences_evidence')):
            for primary_type in (OSError, KeyboardInterrupt, SystemExit):
                for secondary_type in (OSError, KeyboardInterrupt, SystemExit):
                    with self.subTest(action=action, primary=primary_type, secondary=secondary_type):
                        class RefuseGetter(primary_type):
                            def __getattribute__(self, name):
                                if name == evidence_name:
                                    raise secondary_type('secondary getter refusal')
                                return super().__getattribute__(name)
                        first = RefuseGetter('primary')
                        evidence = {'complete': False, 'marker': 'matching first error'}
                        manager = SimpleNamespace(last_error=first, last_evidence=evidence)
                        args = SimpleNamespace(area='preferences', action=action,
                                               **{manager_name: manager})
                        self.assertEqual(error_payload(first, args), {evidence_name: evidence})
                        self.assertIs(manager.last_error, first)
                        manager.last_error = OSError('stale previous operation')
                        self.assertEqual(error_payload(first, args), {})
                        delattr(args, manager_name)
                        self.assertEqual(error_payload(first, args), {})

    def test_reset_hostile_evidence_getter_preserves_cli_primary_and_cleanup(self):
        class RefuseGetter(KeyboardInterrupt):
            def __getattribute__(self, name):
                if name == 'toolkit_preferences_reset_evidence':
                    raise SystemExit('secondary getter refusal')
                return super().__getattribute__(name)
        first = RefuseGetter('primary reset interruption')
        backend = MemoryRegistry(['child'])
        def fault(row):
            if row == ('delete', DONT_ASK_AGAIN_KEY + '\\child'):
                del backend.nodes[row[1]]
                raise first
            if row == ('close', DONT_ASK_AGAIN_KEY):
                raise OSError('secondary close failure')
        backend.fault = fault
        with patch('cbus_toolkit.toolkit_preferences_cli.reset_registry_backend', return_value=backend), \
                patch('cbus_toolkit.toolkit_preferences_cli.error_payload', wraps=error_payload) as exported:
            result = self.invoke('preferences', 'reset-dont-ask-again', status=130)
        self.assertIs(exported.call_args.args[0], first)
        evidence = result['toolkit_preferences_reset_evidence']
        self.assertEqual(evidence['error']['message'], 'primary reset interruption')
        self.assertEqual(evidence['cleanup_errors'][0]['message'], 'secondary close failure')
        self.assertFalse(evidence['complete'])
        self.assertEqual(sum(row[0] == 'delete' for row in backend.calls), 1)
        self.assertNotIn(DONT_ASK_AGAIN_KEY + '\\child', backend.nodes)
        self.assertIn(DONT_ASK_AGAIN_KEY, backend.nodes)
        self.assertEqual(backend.handles, {})

    def test_store_hostile_evidence_getter_preserves_cli_primary_and_write_prefix(self):
        from test_toolkit_preferences_store import Registry
        class RefuseGetter(KeyboardInterrupt):
            def __getattribute__(self, name):
                if name == 'toolkit_preferences_evidence':
                    raise SystemExit('secondary getter refusal')
                return super().__getattribute__(name)
        first = RefuseGetter('primary store interruption')
        backend = Registry()
        def fault(row):
            if row[0] == 'write' and row[3] == 'SortModeGroups':
                raise first
        backend.fault = fault
        with patch('cbus_toolkit.toolkit_preferences_cli.registry_backend', return_value=backend), \
                patch('cbus_toolkit.toolkit_preferences_cli.error_payload', wraps=error_payload) as exported:
            result = self.invoke('preferences', 'registry-save', self.path, status=130)
        self.assertIs(exported.call_args.args[0], first)
        evidence = result['toolkit_preferences_evidence']
        self.assertEqual(evidence['error']['message'], 'primary store interruption')
        self.assertFalse(evidence['complete'])
        self.assertEqual(evidence['operations'][-1]['name'], 'SortModeGroups')
        self.assertFalse(evidence['operations'][-1]['completed'])
        self.assertEqual(len(backend.calls), 4)
        self.assertEqual(sum(row[0] == 'write' and row[3] == 'SortModeGroups'
                             for row in backend.calls), 1)


if __name__ == '__main__':
    unittest.main()
