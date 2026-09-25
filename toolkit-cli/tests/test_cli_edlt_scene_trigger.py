"""CLI composition for one-shot retained eDLT scene trigger invocation."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from tests.test_cli_edlt_scene_live import ConnectedClient
from tests.test_edlt_scene_live import reply, vectors
from tests.test_edlt_scene_manager import cache, fixture, Session


class SceneTriggerCLITests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        session = Session(self.spec)
        source = {**session.current,
                  **{key: value for key, value in vectors()['input'].items()
                     if key in self.spec.parameters}}
        self.document = {'format': 'cbus-cli-parameters-v1',
                         'unit_type': 'KEYGL5', 'firmware': '5.5.00',
                         'catalog_number': '5055EDL', 'parameters': source}
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        self.source = folder / 'source.json'
        self.metadata = folder / 'metadata.json'
        self.source.write_text(json.dumps(self.document))
        self.metadata.write_text(json.dumps(cache()))

    def args(self, *extra):
        return ('cgate', 'edlt-scene-trigger', self.source,
                '--metadata', self.metadata, '--network', '//OWNED/254',
                '--scene', 1, *extra)

    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            actual = cli.main(list(map(str, args)))
        self.assertEqual(actual, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_accepted_trigger_uses_retained_route_and_reports_boundary(self):
        client = ConnectedClient(reply('200 OK'))
        with patch('cbus_toolkit.edlt_global_cli.spec',
                   return_value=self.spec), \
                patch('cbus_toolkit.cgate.CGateClient',
                      return_value=client):
            result = self.invoke(self.args('--force'))

        self.assertEqual(client.commands,
                         ['TRIGGER EVENT //OWNED/254/202/42 1 FORCE'])
        self.assertTrue(result['complete'])
        self.assertTrue(result['native_command_accepted'])
        self.assertFalse(result['physical_scene_execution_verified'])
        self.assertTrue(result['source_profile_identity_verified'])
        self.assertTrue(result['device_side_effect_possible'])
        self.assertEqual(result['automatic_retries'], 0)

    def test_rejection_is_structured_nonzero_and_invalid_input_never_connects(self):
        client = ConnectedClient(reply('401 Owned rejection'))
        with patch('cbus_toolkit.edlt_global_cli.spec',
                   return_value=self.spec), \
                patch('cbus_toolkit.cgate.CGateClient',
                      return_value=client):
            result = self.invoke(self.args(), status=1)
        self.assertEqual(result['status'], 'native-rejected')
        self.assertFalse(result['complete'])
        self.assertEqual(len(client.commands), 1)

        class NoConnect(ConnectedClient):
            def __enter__(self):
                raise AssertionError('Invalid input must fail before connect')

        with patch('cbus_toolkit.edlt_global_cli.spec',
                   return_value=self.spec), \
                patch('cbus_toolkit.cgate.CGateClient',
                      side_effect=lambda *args, **kwargs: NoConnect()):
            result = self.invoke(
                self.args('--network', '//OWNED/0254'), status=1)
        self.assertIn('explicit live network', result['error'])

    def test_raw_or_wrong_profile_source_fails_before_client_creation(self):
        for document in (self.document['parameters'],
                         {**self.document, 'firmware': '5.4.00'}):
            with self.subTest(document_type='raw' if 'format' not in document else 'wrong-profile'):
                self.source.write_text(json.dumps(document))
                with patch('cbus_toolkit.edlt_global_cli.spec',
                           return_value=self.spec), \
                        patch('cbus_toolkit.cgate.CGateClient') as client_factory:
                    result = self.invoke(self.args(), status=1)
                client_factory.assert_not_called()
                self.assertIn('identity-bearing parameter export', result['error'])
