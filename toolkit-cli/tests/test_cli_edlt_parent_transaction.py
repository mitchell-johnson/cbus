"""CLI coverage for one ordered eDLT parent multi-edit transaction."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import cli
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import cache
from tests.test_edlt_parent_form import fixture
from tests.test_edlt_parent_transaction import activation, lighting, measurement


class ParentTransactionCLITests(unittest.TestCase):
    def invoke(self, arguments, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, stdout.getvalue() + stderr.getvalue())
        return json.loads(stdout.getvalue() or stderr.getvalue())

    def files(self, root, operations=None):
        spec = fixture()
        editor = EdltParentTransaction(spec)
        session = Session(spec)
        values = editor.snapshot(session.values())
        source = Path(root) / 'values.json'
        metadata = Path(root) / 'metadata.json'
        operation_file = Path(root) / 'operations.json'
        source.write_text(json.dumps(values))
        metadata.write_text(json.dumps(cache(editor.lifecycle, values)))
        operation_file.write_text(json.dumps(
            operations or [measurement(), lighting(), activation()]))
        return spec, editor, session, source, metadata, operation_file

    @staticmethod
    def offline(source, metadata, operations):
        return [
            'edlt', 'parent-transaction-plan', source,
            '--metadata', metadata, '--operations', operations,
        ]

    @staticmethod
    def native(session, metadata, operations, *, dry_run=False):
        return [
            'cgate', 'unit', '--lock-address', '//EDLTTEST/254',
            '--source', session.source, *(['--dry-run'] if dry_run else []),
            'edlt-parent-transaction', '--metadata', metadata,
            '--operations', operations,
        ]

    def test_offline_plan_is_read_only_and_reports_operation_order(self):
        with tempfile.TemporaryDirectory() as root:
            _, editor, _, source, metadata, operations = self.files(root)
            before = (source.read_bytes(), metadata.read_bytes(),
                      operations.read_bytes())
            with patch.object(cli, '_edlt_parent_transaction',
                              return_value=editor), patch(
                    'cbus_toolkit.cgate.CGateClient',
                    side_effect=AssertionError('Offline plan must not connect')):
                result = self.invoke(self.offline(source, metadata, operations))
            self.assertEqual(result['format'],
                             'cbus-edlt-parent-transaction-plan-v1')
            self.assertEqual([row['operation']
                              for row in result['operation_results']], [1, 2, 3])
            self.assertEqual(result['operation_results'][2]['percentage']['raw_byte'],
                             127)
            self.assertEqual(result['execution_counts'][
                'terminal_normalization_passes'], 1)
            self.assertEqual((source.read_bytes(), metadata.read_bytes(),
                              operations.read_bytes()), before)

    def test_offline_and_native_parsers_share_exact_files(self):
        offline = cli.build_parser().parse_args([
            'edlt', 'parent-transaction-plan', 'source.json',
            '--metadata', 'cache.json', '--operations', 'operations.json'])
        native = cli.build_parser().parse_args([
            'cgate', 'unit', '--lock-address', '//TEST/254',
            '--source', '/db//TEST/254/p/20', 'edlt-parent-transaction',
            '--metadata', 'cache.json', '--operations', 'operations.json'])
        self.assertEqual(offline.metadata, native.metadata)
        self.assertEqual(offline.operations, native.operations)

    def test_native_database_path_applies_once_then_saves_once(self):
        with tempfile.TemporaryDirectory() as root:
            _, editor, session, _, metadata, operations = self.files(root)
            session.save_to_source = Mock(return_value=SimpleNamespace(code=200))
            session.values = Mock(wraps=session.values)
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), patch(
                    'cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                        load=Mock(return_value=nullcontext(session)))), patch.object(
                    cli, '_edlt_parent_transaction', return_value=editor):
                result = self.invoke(self.native(session, metadata, operations))
            self.assertTrue(result['verified'])
            self.assertTrue(result['saved'])
            self.assertEqual(session.current['ProximityLevel'], '127')
            self.assertEqual(sum(name == 'ProximityLevel'
                                 for name, _ in session.calls), 1)
            self.assertEqual(len([name for name, _ in session.calls]),
                             len({name for name, _ in session.calls}))
            # Initial plan, stale-source guard, then one post-write readback.
            self.assertEqual(session.values.call_count, 3)
            session.save_to_source.assert_called_once_with()

    def test_dry_run_has_no_save_and_hardware_destination_fails(self):
        with tempfile.TemporaryDirectory() as root:
            _, editor, session, _, metadata, operations = self.files(root)
            session.save_to_source = Mock(
                side_effect=AssertionError('dry run must not save'))
            arguments = self.native(
                session, metadata, operations, dry_run=True)
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), patch(
                    'cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                        load=Mock(return_value=nullcontext(session)))), patch.object(
                    cli, '_edlt_parent_transaction', return_value=editor):
                result = self.invoke(arguments)
            self.assertTrue(result['verified'])
            self.assertFalse(result['saved'])
            session.save_to_source.assert_not_called()

            hardware = [
                value if value != session.source else '//EDLTTEST/254/p/20'
                for value in arguments
            ]
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())):
                rejected = self.invoke(hardware, status=1)
            self.assertIn('database destinations only', rejected['error'])

    def test_malformed_operations_fail_before_any_pp_write_or_save(self):
        documents = (
            '[{"op":"measurement","op":"lighting"},{}]',
            json.dumps([measurement(), {'op': 'invented'}]),
            json.dumps([measurement(), {**activation(), 'level_percent': 50}]),
            json.dumps([measurement()]),
        )
        for document in documents:
            with self.subTest(document=document), tempfile.TemporaryDirectory() as root:
                _, editor, session, _, metadata, operations = self.files(root)
                operations.write_text(document)
                session.save_to_source = Mock(
                    side_effect=AssertionError('invalid input must not save'))
                with patch('cbus_toolkit.cgate.CGateClient',
                           return_value=nullcontext(SimpleNamespace())), patch(
                        'cbus_toolkit.programming.Programmer',
                        return_value=SimpleNamespace(load=Mock(
                            return_value=nullcontext(session)))), patch.object(
                        cli, '_edlt_parent_transaction', return_value=editor):
                    result = self.invoke(
                        self.native(session, metadata, operations), status=1)
                self.assertIn('error', result)
                self.assertEqual(session.calls, [])
                session.save_to_source.assert_not_called()

    def test_interrupt_reports_transaction_evidence_without_saving(self):
        with tempfile.TemporaryDirectory() as root:
            _, editor, session, _, metadata, operations = self.files(root)
            original_set = session.set
            interruption = KeyboardInterrupt('interrupted transaction')

            def interrupted(name, value):
                original_set(name, value)
                if name == 'ProximityLevel':
                    raise interruption

            session.set = interrupted
            session.save_to_source = Mock(side_effect=AssertionError('No save'))
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), patch(
                    'cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                        load=Mock(return_value=nullcontext(session)))), patch.object(
                    cli, '_edlt_parent_transaction', return_value=editor):
                result = self.invoke(
                    self.native(session, metadata, operations), status=130)
            evidence = result['edlt_parent_transaction_evidence']
            self.assertIn('ProximityLevel', evidence['attempted_parameters'])
            self.assertTrue(evidence['pp_state_uncertain'])
            self.assertFalse(evidence['saved'])
            session.save_to_source.assert_not_called()

    def test_save_failure_reports_uncertain_persistence_without_retry(self):
        with tempfile.TemporaryDirectory() as root:
            _, editor, session, _, metadata, operations = self.files(root)
            session.save_to_source = Mock(
                side_effect=RuntimeError('SAVE reply was lost'))
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), patch(
                    'cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                        load=Mock(return_value=nullcontext(session)))), patch.object(
                    cli, '_edlt_parent_transaction', return_value=editor):
                result = self.invoke(
                    self.native(session, metadata, operations), status=1)
            evidence = result['edlt_parent_transaction_evidence']
            self.assertTrue(evidence['verified'])
            self.assertTrue(evidence['staging_verified'])
            self.assertTrue(evidence['pp_readback_verified_before_save'])
            self.assertTrue(evidence['pp_state_uncertain'])
            self.assertTrue(evidence['database_state_uncertain'])
            self.assertEqual(evidence['database_persistence'], 'uncertain')
            self.assertFalse(evidence['saved'])
            self.assertTrue(evidence['save_attempted'])
            self.assertTrue(evidence['save_outcome_uncertain'])
            self.assertEqual(evidence['automatic_retries'], 0)
            self.assertEqual(evidence['failure_phase'], 'database_save')
            self.assertEqual(session.current['ProximityLevel'], '127')
            session.save_to_source.assert_called_once_with()

    def test_save_interrupt_reports_uncertain_persistence_without_retry(self):
        with tempfile.TemporaryDirectory() as root:
            _, editor, session, _, metadata, operations = self.files(root)
            session.save_to_source = Mock(
                side_effect=KeyboardInterrupt('SAVE interrupted'))
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), patch(
                    'cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                        load=Mock(return_value=nullcontext(session)))), patch.object(
                    cli, '_edlt_parent_transaction', return_value=editor):
                result = self.invoke(
                    self.native(session, metadata, operations), status=130)
            evidence = result['edlt_parent_transaction_evidence']
            self.assertTrue(evidence['verified'])
            self.assertTrue(evidence['pp_readback_verified_before_save'])
            self.assertTrue(evidence['pp_state_uncertain'])
            self.assertTrue(evidence['database_state_uncertain'])
            self.assertFalse(evidence['saved'])
            self.assertTrue(evidence['save_outcome_uncertain'])
            self.assertEqual(evidence['database_save_calls_attempted'], 1)
            self.assertEqual(evidence['automatic_retries'], 0)
            self.assertEqual(evidence['failure_phase'], 'database_save')
            session.save_to_source.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
