"""CLI coverage for the bounded Measurement/Percentage parent composition."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import cli
from cbus_toolkit.edlt_parent_form import EdltParentForm
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import cache
from tests.test_edlt_parent_form import activation, fixture, measurement


class ParentFormCLITests(unittest.TestCase):
    def invoke(self, arguments, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, stdout.getvalue() + stderr.getvalue())
        return json.loads(stdout.getvalue() or stderr.getvalue())

    @staticmethod
    def arguments(source, metadata):
        return [
            'edlt', 'parent-form-plan', source, '--metadata', metadata,
            '--page', '1', '--position', '1', '--device-id', '42', '--channel', '3',
            '--decimal-places', '1', '--gain-value', '1.5', '--offset-value', '-2.5',
            '--measurement-culture', 'en-NZ', '--wake-mode', 'primary-event',
            '--group', '42', '--level-percent', '50',
        ]

    def files(self, root):
        spec = fixture()
        editor = EdltParentForm(spec)
        session = Session(spec)
        values = editor.snapshot(session.values())
        source = Path(root) / 'values.json'
        metadata = Path(root) / 'metadata.json'
        source.write_text(json.dumps(values))
        metadata.write_text(json.dumps(cache(editor.lifecycle, values)))
        return spec, editor, session, source, metadata

    def test_offline_plan_reports_parent_phases_without_changing_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            spec, editor, _, source, metadata = self.files(root)
            before = (source.read_bytes(), metadata.read_bytes())
            with patch.object(cli, '_edlt_parent_form', return_value=editor), \
                    patch('cbus_toolkit.cgate.CGateClient',
                          side_effect=AssertionError('Offline plan must not connect')):
                result = self.invoke(self.arguments(source, metadata))
            self.assertEqual(result['format'], 'cbus-edlt-parent-form-plan-v1')
            self.assertEqual(result['measurement']['device_id'], 42)
            self.assertEqual(result['activation']['percentage']['raw_byte'], 127)
            self.assertEqual(set(result['phases']), {'after_load', 'controls', 'before_save', 'crc'})
            self.assertFalse(result['native_parent_form_executed'])
            self.assertEqual((source.read_bytes(), metadata.read_bytes()), before)

    def test_offline_and_native_parsers_expose_the_same_control_values(self):
        controls = [
            '--metadata', 'cache.json', '--page', '4', '--position', '2',
            '--device-id', '254', '--channel', '7', '--gain-value', '1,5',
            '--measurement-culture', 'de-DE', '--wake-mode', 'primary-event',
            '--group', '3', '--level-percent', '12.5', '--activation-page', 'page-1',
        ]
        offline = cli.build_parser().parse_args(
            ['edlt', 'parent-form-plan', 'source.json', *controls])
        native = cli.build_parser().parse_args([
            'cgate', 'unit', '--lock-address', '//TEST/254',
            '--source', '/db//TEST/254/p/20', 'edlt-parent-form', *controls])
        self.assertEqual(cli._edlt_measurement_settings(offline),
                         cli._edlt_measurement_settings(native))
        for name in ('wake_mode', 'proximity_group', 'level_percent',
                     'activation_page', 'ignore_first_key_press'):
            self.assertEqual(getattr(offline, name), getattr(native, name))

    def test_invalid_percentage_is_rejected_before_execution_or_file_reads(self):
        for value in ('', '-1', '100.1', 'NaN', '1e1', '50%', '50,5', ' 50'):
            with self.subTest(value=value), \
                    patch.object(cli, 'run', side_effect=AssertionError('Execution must not start')) as run, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                cli.main([
                    'edlt', 'parent-form-plan', 'missing.json', '--metadata', 'missing-cache.json',
                    '--page', '1', '--position', '1', '--device-id', '0', '--channel', '0',
                    '--level-percent', value,
                ])
            self.assertEqual(caught.exception.code, 2)
            run.assert_not_called()

    def test_native_database_path_applies_once_then_saves(self):
        with tempfile.TemporaryDirectory() as root:
            spec, editor, session, _, metadata = self.files(root)
            session.save_to_source = Mock(return_value=SimpleNamespace(code=200))
            arguments = [
                'cgate', 'unit', '--lock-address', '//EDLTTEST/254',
                '--source', session.source, 'edlt-parent-form',
                '--metadata', metadata, '--page', '1', '--position', '1',
                '--device-id', '42', '--channel', '3', '--gain-value', '1.5',
                '--measurement-culture', 'en-NZ', '--wake-mode', 'primary-event',
                '--group', '42', '--level-percent', '50',
            ]
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), \
                    patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                        load=Mock(return_value=nullcontext(session)))), \
                    patch.object(cli, '_edlt_parent_form', return_value=editor):
                result = self.invoke(arguments)
            self.assertTrue(result['verified'])
            self.assertTrue(result['saved'])
            self.assertEqual(session.current['ProximityLevel'], '127')
            self.assertEqual(sum(name == 'ProximityLevel' for name, _ in session.calls), 1)
            session.save_to_source.assert_called_once_with()

    def test_native_dry_run_verifies_without_save_and_hardware_destination_fails(self):
        with tempfile.TemporaryDirectory() as root:
            _, editor, session, _, metadata = self.files(root)
            session.save_to_source = Mock(side_effect=AssertionError('dry run must not save'))
            base = [
                'cgate', 'unit', '--lock-address', '//EDLTTEST/254',
                '--source', session.source, '--dry-run', 'edlt-parent-form',
                '--metadata', metadata, '--page', '1', '--position', '1',
                '--device-id', '42', '--channel', '3', '--wake-mode', 'primary-event',
                '--group', '42', '--level-percent', '50',
            ]
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), \
                    patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                        load=Mock(return_value=nullcontext(session)))), \
                    patch.object(cli, '_edlt_parent_form', return_value=editor):
                result = self.invoke(base)
            self.assertTrue(result['verified'])
            self.assertFalse(result['saved'])
            session.save_to_source.assert_not_called()

            hardware = [value if value != session.source else '//EDLTTEST/254/p/20'
                        for value in base]
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())):
                rejected = self.invoke(hardware, status=1)
            self.assertIn('database destinations only', rejected['error'])

    def test_interrupt_returns_composition_evidence_without_saving(self):
        with tempfile.TemporaryDirectory() as root:
            _, editor, session, _, metadata = self.files(root)
            original_set = session.set
            interruption = KeyboardInterrupt('interrupted write')
            def interrupted(name, value):
                original_set(name, value)
                if name == 'ProximityLevel':
                    raise interruption
            session.set = interrupted
            session.save_to_source = Mock(side_effect=AssertionError('No save'))
            arguments = [
                'cgate', 'unit', '--lock-address', '//EDLTTEST/254',
                '--source', session.source, 'edlt-parent-form',
                '--metadata', metadata, '--page', '1', '--position', '1',
                '--device-id', '42', '--channel', '3', '--wake-mode', 'primary-event',
                '--group', '42', '--level-percent', '50',
            ]
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), \
                    patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                        load=Mock(return_value=nullcontext(session)))), \
                    patch.object(cli, '_edlt_parent_form', return_value=editor):
                result = self.invoke(arguments, status=130)
            evidence = result['edlt_parent_form_evidence']
            self.assertIn('ProximityLevel', evidence['attempted_parameters'])
            self.assertTrue(evidence['pp_state_uncertain'])
            self.assertFalse(evidence['saved'])
            session.save_to_source.assert_not_called()


if __name__ == '__main__':
    unittest.main()
