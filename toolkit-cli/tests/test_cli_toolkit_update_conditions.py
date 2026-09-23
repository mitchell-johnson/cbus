"""CLI status, file admission, and partial evidence for supplied conditions."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli, toolkit_update_conditions as core
from cbus_toolkit import toolkit_update_conditions_cli as helper


def encode(value):
    return json.dumps(value, ensure_ascii=True).encode('ascii')


def leaf(what=1, how=1, path='/supplied/file', right=None):
    return {'whatToCheck': what, 'howToCheck': how, 'fileOrRegistryKeyPath': path,
            'comparisonRightSideValue': right}


class ConditionsCLITests(unittest.TestCase):
    def invoke(self, arguments, expected=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error), \
             patch('socket.socket', side_effect=AssertionError('No network')):
            try:
                status = cli.main(list(map(str, arguments)))
            except SystemExit as exc:
                status = exc.code
        self.assertEqual(status, expected, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue()) if status != 2 else None

    def files(self, directory, expression='A', definitions=None, facts=None):
        condition = Path(directory) / 'conditions.json'
        context = Path(directory) / 'context.json'
        condition.write_bytes(encode({'expression': expression, 'conditions': {'A': leaf()} if definitions is None else definitions}))
        context.write_bytes(encode({'format': 'cbus-toolkit-condition-context-v1', 'culture': 'invariant-ascii',
            'files': [{'path': '/supplied/file', 'exists': True}] if facts is None else facts}))
        return ['--compact', 'update-condition-stages', condition, '--context', context]

    def test_true_and_false_both_exit_zero_with_exact_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            for exists in (True, False):
                args = self.files(directory, facts=[{'path': '/supplied/file', 'exists': exists}])
                before = [Path(args[index]).read_bytes() for index in (2, 4)]
                result = self.invoke(args)
                self.assertIs(result['condition_result_under_supplied_context'], exists)
                self.assertTrue(all(row['status'] == 'passed' for row in result['stages']))
                self.assertEqual(result['source']['conditions_file_sha256'], hashlib.sha256(before[0]).hexdigest())
                self.assertEqual(result['source']['context_file_sha256'], hashlib.sha256(before[1]).hexdigest())
                for key in ('context_verified', 'package_applicability_evaluated', 'metadata_admission_evaluated',
                            'publisher_trust_evaluated', 'machine_observations_performed'):
                    self.assertFalse(result[key])
                self.assertIsNone(result['updates_available'])
                self.assertEqual([Path(args[index]).read_bytes() for index in (2, 4)], before)

    def test_lazy_evaluation_and_cached_lookup_never_request_unreached_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(self.files(directory, expression='A AND a OR B',
                definitions={'A': leaf(), 'B': leaf(what=3, path='/unavailable')}))
            self.assertTrue(result['condition_result_under_supplied_context'])
            self.assertEqual([row['resolution'] for row in result['events']], ['leaf', 'cached'])
            self.assertEqual(result['condition_result_cache'], {'a': True})
            self.assertEqual(result['unrequested_definition_names'], ['B'])
            self.assertEqual(result['events'][1]['observations'], [])
            result = self.invoke(self.files(directory, expression='false AND missing', definitions={}, facts=[]))
            self.assertIs(result['condition_result_under_supplied_context'], False)
            self.assertEqual(result['events'], [])

    def test_version_order_absence_and_invalid_rhs_before_any_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(self.files(directory, definitions={'A': leaf(2, 14, right='1.2.0')},
                facts=[{'path': '/supplied/file', 'exists': True, 'file_version': '1.2'}]))
            self.assertIs(result['condition_result_under_supplied_context'], True)
            self.assertEqual([row['fact'] for row in result['events'][0]['observations']], ['exists', 'file_version'])
            result = self.invoke(self.files(directory, definitions={'A': leaf(2, 11, right='1.2')},
                facts=[{'path': '/supplied/file', 'exists': False}]))
            self.assertIs(result['condition_result_under_supplied_context'], False)
            self.assertEqual([row['fact'] for row in result['events'][0]['observations']], ['exists'])
            result = self.invoke(self.files(directory, definitions={'A': leaf(2, 10, right='invalid')}, facts=[]), expected=1)
            self.assertEqual(result['events'][0]['observations'], [])
            self.assertEqual(result['stages'][-1]['status'], 'failed')

    def test_failed_unsupported_and_argparse_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(self.files(directory, expression='A AND B',
                definitions={'A': leaf(), 'B': leaf(path='/unknown')}), expected=1)
            self.assertEqual(result['condition_result_cache'], {'a': True})
            self.assertEqual(result['stages'][-1]['status'], 'unsupported')
            self.assertEqual(result['events'][-1]['observations'],
                             [{'path': '/unknown', 'fact': 'exists', 'status': 'unknown'}])
            result = self.invoke(self.files(directory, expression='NOT NOT A'), expected=1)
            self.assertEqual(result['stages'][-2]['status'], 'failed')
            self.assertEqual(result['events'], [])
            args = self.files(directory)
            self.invoke(args[:3], expected=2)
            context = Path(args[4])
            context.write_bytes(encode({'format': 'cbus-toolkit-condition-context-v1', 'culture': 'en-NZ', 'files': []}))
            result = self.invoke(args, expected=1)
            self.assertEqual(result['stages'][1]['status'], 'unsupported')
            self.assertEqual(result['events'], [])

    def test_regular_file_and_size_admission_precede_calculation(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.files(directory)
            source = Path(args[2])
            link = Path(directory) / 'link'; link.symlink_to(source)
            paths = [Path(directory), link]
            if hasattr(os, 'mkfifo'):
                fifo = Path(directory) / 'fifo'; os.mkfifo(fifo); paths.append(fifo)
            for path in paths:
                changed = args[:]; changed[2] = path
                with patch.object(core.ToolkitUpdateConditions, 'evaluate', side_effect=AssertionError('No calculation')), \
                     patch('os.open', side_effect=AssertionError('Do not open nonregular file')):
                    self.invoke(changed, expected=1)
            source.write_bytes(b' ' * (core.MAX_JSON_BYTES + 1))
            with patch.object(core.ToolkitUpdateConditions, 'evaluate', side_effect=AssertionError('No calculation')):
                self.invoke(args, expected=1)

    def test_interruption_retains_prior_cache_and_source_without_stale_reuse(self):
        first = KeyboardInterrupt('owned second leaf interruption')
        original = core._leaf
        def interrupt_second(name, *args):
            if name == 'b':
                raise first
            return original(name, *args)
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory, expression='A AND B', definitions={'A': leaf(), 'B': leaf()})
            parsed = cli.build_parser().parse_args(list(map(str, arguments)))
            with patch.object(core, '_leaf', side_effect=interrupt_second), self.assertRaises(KeyboardInterrupt) as caught:
                helper.run(parsed)
            self.assertIs(caught.exception, first)
            evidence = helper.error_payload(first, parsed)['toolkit_update_conditions_evidence']
            self.assertEqual(evidence['condition_result_cache'], {'a': True})
            evidence['condition_result_cache']['a'] = False
            self.assertEqual(helper.error_payload(first, parsed)['toolkit_update_conditions_evidence']['condition_result_cache'], {'a': True})
            self.assertEqual(helper.error_payload(KeyboardInterrupt('unrelated'), parsed), {})
            with patch.object(core, '_leaf', side_effect=interrupt_second):
                result = self.invoke(arguments, expected=130)
            self.assertEqual(result['toolkit_update_conditions_evidence']['condition_result_cache'], {'a': True})
            parsed.file = Path(directory) / 'missing'
            with self.assertRaises(OSError):
                helper.run(parsed)
            self.assertEqual(helper.error_payload(first, parsed), {})

    def test_completed_calculation_survives_result_export_failure(self):
        first = ValueError('owned report export failure')
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.files(directory, facts=[{'path': '/supplied/file', 'exists': False}])
            with patch.object(core.ConditionStageReport, 'as_dict', side_effect=first):
                result = self.invoke(arguments, expected=1)
            evidence = result['toolkit_update_conditions_evidence']
            self.assertIs(evidence['condition_result_under_supplied_context'], False)
            self.assertTrue(evidence['evidence_export_failed'])
            self.assertEqual(evidence['condition_result_cache'], {'a': False})
            self.assertFalse(evidence['package_applicability_evaluated'])
            self.assertIn('source', evidence)
