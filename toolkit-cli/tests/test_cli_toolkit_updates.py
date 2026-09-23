from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit import toolkit_updates_cli
from cbus_toolkit.toolkit_preferences_initial_state import constructor_state
from tests.test_toolkit_updates import Transport, reply


class UpdateCLITests(unittest.TestCase):
    def invoke(self, *args, status=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
             patch('socket.create_connection', side_effect=AssertionError('No unexpected network')), \
             patch('cbus_toolkit.windows_preferences.WindowsPreferenceRegistry', side_effect=AssertionError('No registry')):
            result = cli.main(list(map(str, args)))
        self.assertEqual(result, status, out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def test_link_default_and_explicit_state_preserve_exact_text_without_launch(self):
        default = self.invoke('update-link')
        self.assertEqual(default['url'], constructor_state()['values']['CISDownloadsURL'])
        self.assertEqual(default['preference_source'], 'observed-constructor-state')
        self.assertFalse(default['current_host_preferences_read']); self.assertFalse(default['browser_opened'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'; state = constructor_state()
            state['values']['CISDownloadsURL'] = '  https://example.invalid/更新  '
            path.write_text(json.dumps(state)); before = path.read_bytes()
            result = self.invoke('update-link', '--state', path)
            self.assertEqual(result['url'], state['values']['CISDownloadsURL'])
            self.assertEqual(result['preference_source'], 'explicit-state-file')
            self.assertEqual(path.read_bytes(), before)
            for text in ('{}', '{"format":1,"format":2}', ' '* (1024*1024+1)):
                path.write_text(text); self.invoke('update-link', '--state', path, status=1)

    def test_catalogue_success_and_failure_do_not_claim_update_availability(self):
        backend = Transport()
        with patch.object(toolkit_updates_cli, 'catalogue_transport', return_value=backend):
            result = self.invoke('update-catalogue', '--installed-version', ' 01.18.0 ', '--timeout', '2')
        self.assertTrue(result['complete']); self.assertEqual(len(result['candidates']), 7)
        self.assertEqual(result['installed_version'], ' 01.18.0 ')
        self.assertFalse(result['metadata_signature_verified']); self.assertFalse(result['applicability_verified'])
        self.assertIsNone(result['updates_available']); self.assertIsNone(result['latest_version'])
        self.assertEqual(backend.calls[0][1]['timeout'], 2)
        with patch.object(toolkit_updates_cli, 'catalogue_transport', return_value=Transport(reply(b'{}', 503))):
            result = self.invoke('update-catalogue', '--installed-version', '1.18.0', status=1)
        self.assertFalse(result['complete']); self.assertEqual(result['error']['stage'], 'http_status')
        self.assertIsNone(result['updates_available'])

    def test_invalid_version_and_timeout_precede_transport_construction(self):
        with patch.object(toolkit_updates_cli, 'catalogue_transport', side_effect=AssertionError('No transport construction')):
            for version in ('', 'x'*257, 'bad\0version'):
                self.invoke('update-catalogue', '--installed-version', version, status=1)
            for timeout in ('nan', 'inf', '0', '-1', '301'):
                self.invoke('update-catalogue', '--installed-version', '1.18.0', '--timeout', timeout, status=1)

    def test_interrupt_identity_and_cli_fallback_reject_stale_or_attached_evidence(self):
        class Reject(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name == 'toolkit_update_evidence': raise SystemExit('attachment rejected')
                super().__setattr__(name, value)
        for first in (KeyboardInterrupt('owned'), Reject('owned')):
            class Interrupted(Transport):
                def post(self, *args, **kwargs):
                    self.last_reply = reply(b'partial')
                    raise first
            args = cli.build_parser().parse_args(['update-catalogue', '--installed-version', '1.18.0'])
            with patch.object(toolkit_updates_cli, 'catalogue_transport', return_value=Interrupted()):
                with self.assertRaises(KeyboardInterrupt) as observed: toolkit_updates_cli.run(args)
            self.assertIs(observed.exception, first)
            self.assertIn('toolkit_update_evidence', toolkit_updates_cli.error_payload(first, args))
            self.assertEqual(toolkit_updates_cli.error_payload(KeyboardInterrupt('different'), args), {})
            with patch.object(toolkit_updates_cli, 'catalogue_transport', return_value=Interrupted()):
                result = self.invoke('update-catalogue', '--installed-version', '1.18.0', status=130)
            evidence = result['toolkit_update_evidence']
            self.assertFalse(evidence['complete']); self.assertEqual(evidence['http']['body_bytes_retained'], 7)
            args.installed_version = ''
            with self.assertRaises(ValueError): toolkit_updates_cli.run(args)
            self.assertEqual(toolkit_updates_cli.error_payload(first, args), {})


if __name__ == '__main__': unittest.main()
