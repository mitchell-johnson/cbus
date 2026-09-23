"""Deterministic-provider acceptance for lazy live update conditions.

Uses stub read(query)->tagged-primitive observers only. No Windows registry,
no live machine observation, and no package-applicability or trust decision.
WindowsConditionRegistry provenance remains untested on non-Windows hosts.
"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit import toolkit_update_conditions as core
from cbus_toolkit import toolkit_live_update_conditions as live
from cbus_toolkit.toolkit_live_update_conditions import ToolkitLiveUpdateConditions
from cbus_toolkit.windows_condition_registry import RegistryReadScope, WindowsConditionRegistry

PATH = 'HKEY_CURRENT_USER\\Software\\Example'


def encode(value):
    return json.dumps(value, separators=(',', ':')).encode()


def condition_json(what=6, how=10, right='0', path=PATH, entry='Value'):
    return encode({'expression': 'A', 'conditions': {'A': {
        'whatToCheck': what, 'howToCheck': how,
        'comparisonRightSideValue': right, 'fileOrRegistryKeyPath': path,
        'registryEntryNameOrProductCode': entry}}})


def file_context():
    return encode({'format': core.CONTEXT_FORMAT, 'culture': 'invariant-ascii', 'files': []})


class StubObserver:
    """Deterministic read(query)->tagged-primitive provider for tests."""

    def __init__(self, value=0, error=None):
        self.value = value
        self.error = error
        self.queries = []
        self.close_calls = 0

    def read(self, query):
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return {'kind': 'System.Int32', 'value': self.value}

    def close(self):
        self.close_calls += 1


class LiveUpdateConditionsTests(unittest.TestCase):
    def test_stub_integer_equality_drives_true_and_false(self):
        for value, expected in ((0, True), (1, False)):
            observer = StubObserver(value=value)
            wrapper = ToolkitLiveUpdateConditions(observer)
            report = wrapper.evaluate(condition_json(), file_context=file_context())
            self.assertTrue(report.computed)
            self.assertIs(report.result, expected)
            self.assertEqual(observer.close_calls, 1)
            self.assertEqual(len(observer.queries), 1)

    def test_observation_is_recorded_without_trust_or_applicability_claims(self):
        observer = StubObserver(value=0)
        wrapper = ToolkitLiveUpdateConditions(observer)
        report = wrapper.evaluate(condition_json(), file_context=file_context())
        document = report.as_dict()
        self.assertTrue(document['evaluation_completed'])
        self.assertTrue(document['observer_closed'])
        self.assertEqual(len(document['registry_observations']), 1)
        row = document['registry_observations'][0]
        self.assertEqual(row['status'], 'observed')
        self.assertEqual(row['source'], 'unverified_external_provider')
        self.assertFalse(row['provider_identity_verified'])
        self.assertFalse(document['registry_provider_identity_verified'])
        self.assertFalse(document['package_applicability_evaluated'])
        self.assertFalse(document['publisher_trust_evaluated'])
        self.assertIsNone(document['updates_available'])
        self.assertFalse(document['atomic_machine_snapshot'])

    def test_observer_failure_retains_report_and_still_closes_once(self):
        failure = OSError('denied')
        observer = StubObserver(error=failure)
        wrapper = ToolkitLiveUpdateConditions(observer)
        with self.assertRaises(OSError) as caught:
            wrapper.evaluate(condition_json(), file_context=file_context())
        self.assertIs(caught.exception, failure)
        self.assertEqual(observer.close_calls, 1)
        report = wrapper.last_report
        self.assertIsNotNone(report)
        self.assertFalse(report.computed)
        document = report.as_dict()
        self.assertTrue(document['observer_closed'])
        self.assertEqual(document['registry_observations'][0]['status'], 'failed')

    def test_wrapper_and_observer_are_single_use(self):
        observer = StubObserver(value=0)
        wrapper = ToolkitLiveUpdateConditions(observer)
        completed = wrapper.evaluate(condition_json(), file_context=file_context())
        with self.assertRaisesRegex(ValueError, 'fresh observer'):
            wrapper.evaluate(condition_json(), file_context=file_context())
        self.assertIs(wrapper.last_report, completed)
        self.assertEqual(observer.close_calls, 1)

    def test_malformed_condition_reports_failed_stage_without_any_registry_read(self):
        observer = StubObserver(value=0)
        wrapper = ToolkitLiveUpdateConditions(observer)
        report = wrapper.evaluate(b'{not json', file_context=file_context())
        self.assertFalse(report.computed)
        stages = {row['stage']: row['status'] for row in report.as_dict()['stages']}
        self.assertEqual(stages['typed_input'], 'failed')
        self.assertEqual(observer.queries, [])
        self.assertEqual(observer.close_calls, 1)

    def test_repeated_name_is_cached_but_another_name_observes_changed_value(self):
        observer = StubObserver()
        values = iter((0, 1))
        def read(query):
            observer.queries.append(query)
            return {'kind': 'System.Int32', 'value': next(values)}
        observer.read = read
        definition = json.loads(condition_json())['conditions']['A']
        document = encode({'expression': 'A AND A AND B', 'conditions': {'A': definition, 'B': definition}})
        report = ToolkitLiveUpdateConditions(observer).evaluate(document, file_context=file_context())
        self.assertTrue(report.computed)
        self.assertIs(report.result, False)
        evidence = report.as_dict()
        self.assertEqual(observer.queries[0], observer.queries[1])
        self.assertEqual(len(observer.queries), 2)
        self.assertEqual([row['resolution'] for row in evidence['events']], ['leaf', 'cached', 'leaf'])
        self.assertEqual([row['lookup_name'] for row in evidence['registry_observations']], ['a', 'b'])
        self.assertEqual([row['result']['value'] for row in evidence['registry_observations']], [0, 1])
        self.assertEqual(evidence['condition_result_cache'], {'a': True, 'b': False})
        self.assertNotIn('registry_observation_sequence', evidence['events'][1])

    def test_short_circuit_does_not_request_unreached_registry_definition(self):
        definition = json.loads(condition_json())['conditions']['A']
        for expression, value, expected in (('A OR B', 0, True), ('A AND B', 1, False),
                                             ('true OR A', 0, True), ('false AND A', 0, False)):
            with self.subTest(expression=expression):
                observer = StubObserver(value=value)
                report = ToolkitLiveUpdateConditions(observer).evaluate(
                    encode({'expression': expression, 'conditions': {'A': definition, 'B': definition}}),
                    file_context=file_context())
                self.assertIs(report.result, expected)
                self.assertEqual(len(observer.queries), 1 if expression.startswith('A') else 0)
                self.assertEqual(observer.close_calls, 1)

    def test_missing_content_shortcut_precedes_invalid_integer_rhs(self):
        observer = StubObserver()
        observer.read = lambda query: {'kind': 'null', 'value': None}
        report = ToolkitLiveUpdateConditions(observer).evaluate(
            condition_json(how=11, right='not an integer'), file_context=file_context())
        self.assertTrue(report.computed)
        self.assertIs(report.result, True)
        steps = report.as_dict()['events'][0]['registry_steps']
        self.assertEqual([row['step'] for row in steps], ['null_or_exact_sentinel', 'missing_content_shortcut'])

    def test_successful_read_precedes_integer_rhs_failure_and_failed_leaf_is_not_cached(self):
        observer = StubObserver()
        report = ToolkitLiveUpdateConditions(observer).evaluate(
            condition_json(right='not an integer'), file_context=file_context())
        self.assertFalse(report.computed)
        self.assertEqual(len(observer.queries), 1)
        document = report.as_dict()
        self.assertEqual(document['registry_observations'][0]['status'], 'observed')
        self.assertEqual(document['condition_result_cache'], {})
        self.assertEqual(document['events'][0]['status'], 'failed')

    def test_close_failure_after_boolean_result_is_not_computed(self):
        observer = StubObserver()
        failure = OSError('close failed')
        def close():
            observer.close_calls += 1
            raise failure
        observer.close = close
        wrapper = ToolkitLiveUpdateConditions(observer)
        with self.assertRaises(OSError) as caught:
            wrapper.evaluate(condition_json(), file_context=file_context())
        self.assertIs(caught.exception, failure)
        self.assertIs(wrapper.last_report.result, True)
        self.assertFalse(wrapper.last_report.computed)
        self.assertFalse(wrapper.last_report.as_dict()['observer_closed'])
        self.assertEqual(observer.close_calls, 1)

    def test_first_interrupt_survives_close_and_report_export_failures(self):
        failure = KeyboardInterrupt('read interrupted')
        observer = StubObserver(error=failure)
        def close():
            observer.close_calls += 1
            raise SystemExit('secondary close')
        observer.close = close
        raw, context = condition_json(), file_context()
        wrapper = ToolkitLiveUpdateConditions(observer)
        with patch.object(live.json, 'dumps', side_effect=RuntimeError('secondary export')):
            with self.assertRaises(KeyboardInterrupt) as caught:
                wrapper.evaluate(raw, file_context=context)
        self.assertIs(caught.exception, failure)
        self.assertIs(wrapper.last_report.cause, failure)
        self.assertFalse(wrapper.last_report.computed)
        self.assertTrue(wrapper.last_report.as_dict()['evidence_export_failed'])
        self.assertEqual(observer.close_calls, 1)

    def test_external_provider_cannot_supply_a_forged_verified_receipt(self):
        observer = StubObserver()
        observer.read = lambda query: {'kind': 'System.Int32', 'value': 0,
                                      'provider_identity_verified': True}
        report = ToolkitLiveUpdateConditions(observer).evaluate(condition_json(), file_context=file_context())
        self.assertFalse(report.computed)
        self.assertFalse(report.as_dict()['registry_provider_identity_verified'])
        self.assertEqual(report.as_dict()['registry_observations'][0]['source'], 'unverified_external_provider')

    def test_previously_used_windows_observer_is_rejected_before_another_read(self):
        scope = RegistryReadScope.from_json(encode({'format': 'cbus-toolkit-registry-read-scope-v1',
            'queries': [{'path': PATH, 'entry': 'Value', 'default': {'kind': 'System.Int32', 'value': 1}}]}))
        for field, value in (('_records', [{'sequence': 0}]), ('_closed', True), ('_terminal', True),
                             ('_failure', OSError('prior failure'))):
            with self.subTest(field=field):
                observer = WindowsConditionRegistry(compiler_path='not opened during validation', scope=scope)
                setattr(observer, field, value)
                with patch.object(observer, 'read') as read, patch.object(observer, 'close') as close:
                    with self.assertRaisesRegex(ValueError, 'fresh Windows registry observer'):
                        ToolkitLiveUpdateConditions(observer).evaluate(condition_json(), file_context=file_context())
                read.assert_not_called()
                close.assert_not_called()

    def test_retained_original_registry_vectors_through_lazy_wrapper(self):
        vectors = json.loads((Path(__file__).resolve().parents[1] / 'research/fixtures' /
                              'toolkit-update-registry-conditions-vectors.json').read_bytes())
        self.assertEqual(len(vectors['cases']), 12)
        for case in vectors['cases']:
            with self.subTest(id=case['id']):
                observer = StubObserver()
                witness = case['witness']
                def read(query):
                    observer.queries.append(query)
                    return dict(witness['result'])
                observer.read = read
                raw = encode({'expression': 'A', 'conditions': {'A': case['condition']}})
                report = ToolkitLiveUpdateConditions(observer).evaluate(raw, file_context=file_context())
                self.assertEqual(observer.queries, [{'path': witness['path'], 'entry': witness['entry'],
                                                    'default': witness['default_value']}])
                document = report.as_dict()
                self.assertEqual(document['registry_observations'][0]['result'], witness['result'])
                self.assertFalse(document['registry_provider_identity_verified'])
                event = document['events'][0]
                if not case['portable_supported']:
                    self.assertFalse(report.computed)
                    self.assertEqual(event['status'], 'unsupported')
                elif case['original']['error'] is None:
                    self.assertTrue(report.computed)
                    self.assertIs(report.result, case['original']['result'])
                else:
                    self.assertFalse(report.computed)
                    self.assertEqual(event['original_error_type'], case['original']['error']['type'])
                    # Captures invoked the leaf directly with its Rxx name;
                    # this wrapper intentionally binds the same definition as A.
                    expected = case['original']['error']['message'].replace(
                        "condition '" + case['condition']['name'] + "'", "condition 'a'")
                    self.assertEqual(event['original_error_message'], expected)
                self.assertEqual(observer.close_calls, 1)


if __name__ == '__main__':
    unittest.main()
