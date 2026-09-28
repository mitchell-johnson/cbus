"""CLI boundary for checked live Windows registry condition evaluation."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit import toolkit_live_update_conditions as live
from cbus_toolkit import toolkit_live_update_conditions_cli as helper

from tests.test_toolkit_live_update_conditions import PATH, StubObserver, condition_json, file_context


def scope_json():
    return json.dumps({'format': 'cbus-toolkit-registry-read-scope-v1', 'queries': [{
        'path': PATH, 'entry': 'Value',
        'default': {'kind': 'System.Int32', 'value': 1},
    }]}, separators=(',', ':')).encode()


class LiveConditionsCLITests(unittest.TestCase):
    def files(self, directory):
        conditions = Path(directory) / 'conditions.json'
        context = Path(directory) / 'context.json'
        scope = Path(directory) / 'scope.json'
        conditions.write_bytes(condition_json())
        context.write_bytes(file_context())
        scope.write_bytes(scope_json())
        return ['--compact', 'update-condition-live', conditions,
                '--file-context', context, '--registry-scope', scope]

    def invoke(self, arguments, observer, expected=0):
        output, error = io.StringIO(), io.StringIO()
        factory_options = ({'side_effect': observer} if isinstance(observer, list)
                           else {'return_value': observer})
        with redirect_stdout(output), redirect_stderr(error), \
             patch.object(helper, 'WindowsConditionRegistry', **factory_options) as factory, \
             patch('socket.socket', side_effect=AssertionError('No network')):
            status = cli.main(list(map(str, arguments)))
        self.assertEqual(status, expected, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue()), factory

    def test_true_and_false_are_completed_with_exact_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory)
            sources = [Path(arguments[index]).read_bytes() for index in (2, 4, 6)]
            for observed, expected in ((0, True), (1, False)):
                observer = StubObserver(observed)
                observer.last_report = None
                value, factory = self.invoke(arguments, observer)
                self.assertIs(value['condition_result'], expected)
                self.assertTrue(value['evaluation_completed'])
                self.assertTrue(value['observer_closed'])
                self.assertEqual(observer.close_calls, 1)
                self.assertEqual(len(observer.queries), 1)
                self.assertEqual(value['source'], {
                    'conditions_file_sha256': hashlib.sha256(sources[0]).hexdigest(),
                    'file_context_sha256': hashlib.sha256(sources[1]).hexdigest(),
                    'registry_scope_sha256': hashlib.sha256(sources[2]).hexdigest(),
                    'representation': 'Exact supplied bytes; normalized model and observed requests reported separately',
                })
                self.assertFalse(value['registry_provider_identity_verified'])
                self.assertFalse(value['package_applicability_evaluated'])
                self.assertFalse(value['publisher_trust_evaluated'])
                self.assertIsNone(value['updates_available'])
                self.assertEqual([Path(arguments[index]).read_bytes() for index in (2, 4, 6)], sources)
                factory.assert_called_once()

    def test_repeat_once_matches_original_public_true_then_false_cache_reset(self):
        native_path = Path(__file__).resolve().parents[1] / 'research/experiments/2026-09-28/registry-lazy-culture-native.json'
        native = json.loads(native_path.read_bytes())
        rows = {row['id']: row for row in native['native_rows']}
        first, second = StubObserver(0), StubObserver(1)
        first.last_report = second.last_report = None
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory)
            value, factory = self.invoke(arguments + ['--repeat-once'], [first, second])
        self.assertEqual(factory.call_count, 2)
        self.assertTrue(value['repeated_evaluation'])
        self.assertTrue(value['second_evaluation_attempted'])
        self.assertEqual([row['condition_result'] for row in value['evaluation_passes']],
                         [rows['public-first-true']['result'], rows['public-fresh-evaluate-false']['result']])
        self.assertEqual([row['condition_result_cache'] for row in value['evaluation_passes']],
                         [rows['public-first-true']['cache'], rows['public-fresh-evaluate-false']['cache']])
        self.assertIs(value['condition_result'], False)
        self.assertEqual([len(first.queries), len(second.queries)], [1, 1])
        self.assertEqual([first.close_calls, second.close_calls], [1, 1])
        self.assertNotEqual(value['evaluation_passes'][0]['registry_observations'][0]['result'],
                            value['evaluation_passes'][1]['registry_observations'][0]['result'])

    def test_repeat_once_stops_after_incomplete_first_pass_without_second_observer(self):
        first = StubObserver(0)
        first.last_report = None
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory)
            Path(arguments[4]).write_text(json.dumps({'format': 'cbus-toolkit-condition-context-v1',
                'culture': 'tr-TR', 'files': []}))
            value, factory = self.invoke(arguments + ['--repeat-once'], [first], expected=1)
        factory.assert_called_once()
        self.assertFalse(value['evaluation_completed'])
        self.assertFalse(value['second_evaluation_attempted'])
        self.assertEqual(len(value['evaluation_passes']), 1)
        self.assertEqual(first.queries, [])
        self.assertEqual(first.close_calls, 1)

    def test_repeat_once_second_interruption_retains_both_receipts(self):
        interruption = KeyboardInterrupt('second observation interrupted')
        first, second = StubObserver(0), StubObserver(error=interruption)
        first.last_report = second.last_report = None
        with tempfile.TemporaryDirectory() as directory:
            value, factory = self.invoke(self.files(directory) + ['--repeat-once'],
                                         [first, second], expected=130)
        self.assertEqual(factory.call_count, 2)
        evidence = value[helper.EVIDENCE]
        self.assertTrue(evidence['repeated_evaluation'])
        self.assertTrue(evidence['second_evaluation_attempted'])
        self.assertEqual(len(evidence['evaluation_passes']), 2)
        self.assertTrue(evidence['evaluation_passes'][0]['evaluation_completed'])
        self.assertFalse(evidence['evaluation_passes'][1]['evaluation_completed'])
        self.assertTrue(evidence['evaluation_passes'][1]['observer_closed'])
        self.assertEqual([first.close_calls, second.close_calls], [1, 1])

    def test_repeat_once_second_observer_construction_failure_keeps_first(self):
        first = StubObserver(0)
        first.last_report = None
        with tempfile.TemporaryDirectory() as directory:
            value, factory = self.invoke(self.files(directory) + ['--repeat-once'],
                                         [first, OSError('second worker unavailable')], expected=1)
        self.assertEqual(factory.call_count, 2)
        evidence = value[helper.EVIDENCE]
        self.assertFalse(evidence['second_evaluation_attempted'])
        self.assertEqual(len(evidence['evaluation_passes']), 1)
        self.assertTrue(evidence['evaluation_passes'][0]['evaluation_completed'])
        self.assertEqual(first.close_calls, 1)

    def test_repeat_once_reused_observer_is_rejected_without_second_read(self):
        first = StubObserver(0)
        first.last_report = None
        with tempfile.TemporaryDirectory() as directory:
            value, factory = self.invoke(self.files(directory) + ['--repeat-once'],
                                         [first, first], expected=1)
        self.assertEqual(factory.call_count, 2)
        evidence = value[helper.EVIDENCE]
        self.assertTrue(evidence['second_evaluation_attempted'])
        self.assertEqual(len(evidence['evaluation_passes']), 1)
        self.assertEqual(len(first.queries), 1)
        self.assertEqual(first.close_calls, 1)

    def test_repeat_once_output_failure_does_not_nest_incomplete_first_receipt(self):
        first = StubObserver(0)
        first.last_report = None
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory) + ['--repeat-once']
            Path(arguments[4]).write_text(json.dumps({'format': 'cbus-toolkit-condition-context-v1',
                'culture': 'tr-TR', 'files': []}))
            args = cli.build_parser().parse_args(list(map(str, arguments)))
            with patch.object(helper, 'WindowsConditionRegistry', return_value=first):
                result, status = helper.run(args)
            self.assertEqual(status, 1)
            self.assertEqual(len(result['evaluation_passes']), 1)
            failure = OSError('stdout failed')
            helper.record_output_error(args, failure)
            evidence = helper.error_payload(failure, args)[helper.EVIDENCE]
        self.assertEqual(len(evidence['evaluation_passes']), 1)
        self.assertNotIn('evaluation_passes', evidence['evaluation_passes'][0])
        self.assertEqual(first.close_calls, 1)

    def test_explicit_user_sid_is_forwarded_and_invalid_sid_precedes_file_reads(self):
        sid = 'S-1-5-21-123-456-789-1001'
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory)
            observer = StubObserver(0)
            value, factory = self.invoke(arguments + ['--expected-user-sid', sid], observer)
            self.assertEqual(factory.call_args.kwargs['expected_user_sid'], sid)
            self.assertTrue(value['evaluation_completed'])
            with patch.object(helper, '_read', side_effect=AssertionError('No file reads')):
                value, factory = self.invoke(arguments + ['--expected-user-sid', 'not-a-sid'],
                                             StubObserver(0), expected=1)
            factory.assert_not_called()
            self.assertEqual(value['type'], 'ValueError')

    def test_scope_and_regular_file_admission_precede_observer_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory)
            scope = Path(arguments[6])
            for invalid in (b'{not json', json.dumps({'format': 'wrong', 'queries': []}).encode()):
                scope.write_bytes(invalid)
                with patch.object(helper, 'WindowsConditionRegistry',
                                  side_effect=AssertionError('No observer construction')), \
                     patch('socket.socket', side_effect=AssertionError('No network')):
                    output, error = io.StringIO(), io.StringIO()
                    with redirect_stdout(output), redirect_stderr(error):
                        self.assertEqual(cli.main(list(map(str, arguments))), 1)
            scope.write_bytes(scope_json())
            conditions = Path(arguments[2])
            link = Path(directory) / 'conditions-link.json'
            link.symlink_to(conditions)
            arguments[2] = link
            with patch.object(helper, 'WindowsConditionRegistry',
                              side_effect=AssertionError('No observer construction')), \
                 patch('os.open', side_effect=AssertionError('Do not open a nonregular path')), \
                 patch('socket.socket', side_effect=AssertionError('No network')):
                output, error = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    self.assertEqual(cli.main(list(map(str, arguments))), 1)

    def test_keyboard_interrupt_retains_partial_evidence_and_closes_once(self):
        first = KeyboardInterrupt('registry read interrupted')
        observer = StubObserver(error=first)
        observer.last_report = None
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory)
            value, _ = self.invoke(arguments, observer, expected=130)
        evidence = value['toolkit_live_update_conditions_evidence']
        self.assertEqual(value['error'], 'Interrupted')
        self.assertFalse(evidence['evaluation_completed'])
        self.assertTrue(evidence['observer_closed'])
        self.assertEqual(evidence['registry_observations'][0]['status'], 'failed')
        self.assertIn('source', evidence)
        self.assertEqual(observer.close_calls, 1)

    def test_completed_result_survives_report_export_failure_without_stale_reuse(self):
        first = ValueError('report export failed')
        observer = StubObserver(1)
        observer.last_report = None
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory)
            parsed = cli.build_parser().parse_args(list(map(str, arguments)))
            with patch.object(helper, 'WindowsConditionRegistry', return_value=observer), \
                 patch.object(live.LiveConditionReport, 'as_dict', side_effect=first):
                with self.assertRaises(ValueError) as caught:
                    helper.run(parsed)
                self.assertIs(caught.exception, first)
                evidence = helper.error_payload(first, parsed)[helper.EVIDENCE]
            self.assertIs(evidence['condition_result'], False)
            self.assertTrue(evidence['evaluation_completed'])
            self.assertTrue(evidence['evidence_export_failed'])
            self.assertIn('source', evidence)
            evidence['condition_result'] = True
            self.assertIs(helper.error_payload(first, parsed)[helper.EVIDENCE]['condition_result'], False)
            self.assertEqual(helper.error_payload(ValueError('unrelated'), parsed), {})
            self.assertEqual(observer.close_calls, 1)

            output_observer = StubObserver(0)
            output_observer.last_report = None
            output_args = cli.build_parser().parse_args(list(map(str, arguments)))
            with patch.object(helper, 'WindowsConditionRegistry', return_value=output_observer):
                helper.run(output_args)
            output_error = OSError('stdout failed')
            helper.record_output_error(output_args, output_error)
            output_evidence = helper.error_payload(output_error, output_args)[helper.EVIDENCE]
            self.assertIs(output_evidence['condition_result'], True)
            self.assertTrue(output_evidence['evaluation_completed'])
            self.assertEqual(helper.error_payload(OSError('unrelated'), output_args), {})
            self.assertEqual(output_observer.close_calls, 1)

    def test_invalid_timeout_and_argparse_requirements_do_not_start_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory)
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error), \
                 patch.object(helper.WindowsConditionRegistry, 'read',
                              side_effect=AssertionError('No registry read')):
                self.assertEqual(cli.main(list(map(str, arguments + ['--timeout', '0']))), 1)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(list(map(str, arguments[:4])))
            self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
