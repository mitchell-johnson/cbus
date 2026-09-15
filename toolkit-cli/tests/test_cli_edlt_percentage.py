"""Percentage arguments feed existing activation plans and session safeguards."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import cli
from cbus_toolkit.edlt_activation import EdltActivation
from cbus_toolkit.edlt_percentage import percentage_to_byte
from tests.test_edlt import Session
from tests.test_edlt_activation import fixture


class PercentageCLITests(unittest.TestCase):
    def invoke(self, arguments, status=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def test_offline_original_percentage_results_and_visibility_guards(self):
        spec = fixture()
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/'values.json'
            original = json.dumps(Session(spec).values()).encode()
            source.write_bytes(original)
            with patch.object(cli, '_edlt_activation', return_value=EdltActivation(spec)), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No connection')):
                # Literal outputs from the captured original percentage getter,
                # including its truncated byte3 setter/getter roundtrip.
                for percentage, expected in [('0',0), ('50',127), ('100',255),
                        ('1.1764705882352941176470588235',2)]:
                    with self.subTest(percentage=percentage):
                        result = self.invoke(['edlt','activation-plan',source,'--wake-mode','primary-event',
                                              '--group','42','--level-percent',percentage])
                        self.assertEqual(result['event_value'], expected)
                        self.assertEqual(result['raw_values']['ProximityLevel'], expected)
                        self.assertEqual(result['event_application'], 56)
                        self.assertFalse(result['saved'])
                        self.assertFalse(result['physical_device_verified'])
                rejected = self.invoke(['edlt','activation-plan',source,'--wake-mode','trigger-event',
                                        '--group','42','--level-percent','50'], status=1)
                self.assertIn('hidden or disabled', rejected['error'])
            self.assertEqual(source.read_bytes(), original)

    def test_invalid_or_conflicting_percentage_arguments_precede_execution(self):
        prefixes = [['edlt','activation-plan','missing.json'],
                    ['cgate','unit','--lock-address','//EDLTTEST/254',
                     '--source','/db//EDLTTEST/254/p/20','edlt-activation']]
        invalid = ['', '-1', '100.1', 'NaN', '1e1', '50%', '50,5', ' 50', '５０',
                   '79.228162514264337593543950336']
        for prefix in prefixes:
            for arguments in [['--level-percent', value] for value in invalid] + [
                    ['--level','127','--level-percent','50'],['--level-percent','50','--level','127']]:
                with self.subTest(prefix=prefix[0], arguments=arguments), \
                        patch.object(cli, 'run', side_effect=AssertionError('Execution must not start')) as run, \
                        redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    cli.main([*prefix,*arguments])
                self.assertEqual(caught.exception.code, 2)
                run.assert_not_called()

    def test_database_session_converts_once_and_uses_existing_write_save_path(self):
        spec = fixture(); session = Session(spec)
        session.save_to_source = Mock(return_value=SimpleNamespace(code=200))
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                    load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_activation', return_value=EdltActivation(spec)), \
                patch('cbus_toolkit.edlt_percentage.percentage_to_byte', wraps=percentage_to_byte) as convert:
            result = self.invoke(['cgate','unit','--lock-address','//EDLTTEST/254','--source',session.source,
                                  'edlt-activation','--wake-mode','primary-event','--level-percent','50'])
        convert.assert_called_once_with('50')
        self.assertEqual(result['raw_values']['ProximityLevel'], 127)
        self.assertEqual(session.current['ProximityLevel'], '127')
        self.assertEqual(sum(name=='ProximityLevel' for name,_ in session.calls), 1)
        session.save_to_source.assert_called_once_with()
        self.assertTrue(result['saved'])
        self.assertFalse(result['physical_device_verified'])

    def test_percentage_write_interruption_preserves_partial_evidence_without_save(self):
        spec = fixture(); session = Session(spec)
        first = KeyboardInterrupt('level write interrupted')
        original_set = session.set
        def interrupted(name, value):
            original_set(name, value)
            if name=='ProximityLevel':raise first
        session.set = interrupted
        session.save_to_source = Mock(side_effect=AssertionError('No save'))
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(
                    load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_activation', return_value=EdltActivation(spec)):
            result = self.invoke(['cgate','unit','--lock-address','//EDLTTEST/254','--source',session.source,
                                  'edlt-activation','--wake-mode','primary-event','--level-percent','50'],status=130)
        evidence = result['edlt_activation_evidence']
        self.assertEqual(session.current['ProximityLevel'], '127')
        self.assertEqual(evidence['attempted_parameters'][-1], 'ProximityLevel')
        self.assertTrue(evidence['pp_state_uncertain'])
        self.assertFalse(evidence['saved'])
        self.assertEqual(evidence['automatic_retries'], 0)
        session.save_to_source.assert_not_called()


if __name__=='__main__':unittest.main()
