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
        with redirect_stdout(output), redirect_stderr(error), \
             patch.object(helper, 'WindowsConditionRegistry', return_value=observer) as factory, \
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
