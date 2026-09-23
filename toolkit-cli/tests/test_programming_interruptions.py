"""Resource cleanup retains the first failure and stops after cancellation."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.programming import Programmer, ProgrammingCleanupError
from tests.test_programming import Client


class ProgrammingInterruptionTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(); self.client.connected = True
        self.programmer = Programmer(self.client)
        self.session = self.programmer.session('//OWNED/254', name='OWNED_SESSION', lock_name='OWNED_LOCK')

    def test_body_failure_survives_secondary_cleanup_interrupt_without_later_io(self):
        for kind in (KeyboardInterrupt, SystemExit):
            with self.subTest(kind=kind.__name__):
                self.setUp(); primary = RuntimeError('original SET failed'); secondary = kind('cleanup interrupted')
                self.client.failures['PP END OWNED_SESSION'] = secondary
                with self.assertRaises(RuntimeError) as observed:
                    with self.session: raise primary
                self.assertIs(observed.exception, primary)
                self.assertEqual(primary.programming_cleanup_errors, [secondary])
                self.assertEqual(self.session.cleanup_errors, [secondary])
                self.assertTrue(self.session._started); self.assertTrue(self.session._locked)
                self.assertEqual(self.client.commands[-1], 'PP END OWNED_SESSION')
                self.assertNotIn('PP UNLOCK OWNED_LOCK', self.client.commands)

    def test_body_interrupt_survives_secondary_interrupt(self):
        primary, secondary = KeyboardInterrupt('first'), KeyboardInterrupt('second')
        self.client.failures['PP END OWNED_SESSION'] = secondary
        with self.assertRaises(KeyboardInterrupt) as observed:
            with self.session: raise primary
        self.assertIs(observed.exception, primary); self.assertEqual(primary.programming_cleanup_errors, [secondary])

    def test_initializer_interrupt_cleans_confirmed_owned_resources_if_connected(self):
        for kind in (KeyboardInterrupt, SystemExit):
            with self.subTest(kind=kind.__name__):
                self.setUp(); original = kind('NEW interrupted')
                self.client.failures['PP NEW OWNED_SESSION KEY4 1.2.67'] = original
                session = self.programmer.new('//OWNED/254', 'KEY4', '1.2.67', name='OWNED_SESSION', lock_name='OWNED_LOCK')
                with self.assertRaises(kind) as observed: session.open()
                self.assertIs(observed.exception, original)
                self.assertEqual(self.client.commands[-2:], ['PP END OWNED_SESSION', 'PP UNLOCK OWNED_LOCK'])
                self.assertFalse(session._started); self.assertFalse(session._locked)

    def test_initializer_failure_retained_when_cleanup_is_interrupted(self):
        primary, secondary = KeyboardInterrupt('initializer'), SystemExit('cleanup')
        self.client.failures['PP NEW OWNED_SESSION KEY4 1.2.67'] = primary
        self.client.failures['PP END OWNED_SESSION'] = secondary
        session = self.programmer.new('//OWNED/254', 'KEY4', '1.2.67', name='OWNED_SESSION', lock_name='OWNED_LOCK')
        with self.assertRaises(KeyboardInterrupt) as observed: session.open()
        self.assertIs(observed.exception, primary); self.assertEqual(primary.programming_cleanup_errors, [secondary])
        self.assertEqual(self.client.commands[-1], 'PP END OWNED_SESSION')

    def test_start_interrupt_releases_only_confirmed_lock(self):
        original = KeyboardInterrupt('START interrupted')
        self.client.failures['PP START OWNED_SESSION OWNED_LOCK'] = original
        with self.assertRaises(KeyboardInterrupt) as observed: self.session.open()
        self.assertIs(observed.exception, original); self.assertFalse(self.session._locked)
        self.assertEqual(self.client.commands[-1], 'PP UNLOCK OWNED_LOCK')
        self.assertNotIn('PP END OWNED_SESSION', self.client.commands)

    def test_lock_interrupt_does_not_assume_ownership_or_cancel_other_locks(self):
        original = KeyboardInterrupt('LOCK interrupted')
        self.client.failures['PP LOCK OWNED_LOCK //OWNED/254'] = original
        with self.assertRaises(KeyboardInterrupt) as observed: self.session.open()
        self.assertIs(observed.exception, original)
        self.assertEqual(self.client.commands, ['PROJECT USE OWNED', 'PP LOCK OWNED_LOCK //OWNED/254'])
        self.assertFalse(self.session._locked)

    def test_disconnected_failure_and_cleanup_disconnect_stop_without_reconnect(self):
        original = RuntimeError('connection ended')
        with self.assertRaises(RuntimeError) as observed:
            with self.session:
                self.client.connected = False
                raise original
        self.assertIs(observed.exception, original)
        self.assertEqual(self.client.commands[-1], 'PP START OWNED_SESSION OWNED_LOCK')
        self.assertIn('without I/O', str(original.programming_cleanup_errors[0]))
        self.assertTrue(self.session._started); self.assertTrue(self.session._locked)
        self.setUp(); command = self.client.command
        def disconnect(request):
            if request == 'PP END OWNED_SESSION':
                self.client.commands.append(request); self.client.connected = False
                raise RuntimeError('cleanup connection ended')
            return command(request)
        self.client.command = disconnect
        with self.assertRaises(ProgrammingCleanupError) as observed:
            with self.session: pass
        self.assertEqual(self.client.commands[-1], 'PP END OWNED_SESSION')
        self.assertEqual(len(observed.exception.errors), 2)

    def test_cleanup_only_interrupt_remains_original_cancellation(self):
        for method in ('context', 'close'):
            for kind in (KeyboardInterrupt, SystemExit):
                with self.subTest(method=method, kind=kind.__name__):
                    self.setUp(); original = kind('END interrupted')
                    self.client.failures['PP END OWNED_SESSION'] = original
                    with self.assertRaises(kind) as observed:
                        if method == 'context':
                            with self.session: pass
                        else:
                            self.session.open(); self.session.close()
                    self.assertIs(observed.exception, original); self.assertEqual(self.session.cleanup_errors, [original])
                    self.assertEqual(self.client.commands[-1], 'PP END OWNED_SESSION')

    def test_cli_real_programmer_retains_body_error_and_emits_cleanup_cancellation(self):
        class InterruptedClient(Client):
            def __enter__(self): self.connected = True; return self
            def __exit__(self, *_): self.connected = False
            def command(self, request):
                response = super().command(request)
                if request.startswith('PP GET '): raise RuntimeError('original parameter read failed')
                if request.startswith('PP END '): raise KeyboardInterrupt('session end interrupted')
                return response
        client = InterruptedClient(); output, error = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client), redirect_stdout(output), redirect_stderr(error):
            code = cli.main(['cgate', 'unit', '--lock-address', '//OWNED/254', '--source', '/db//OWNED/254/p/20', 'show'])
        self.assertEqual(code, 1); self.assertEqual(output.getvalue(), '')
        result = json.loads(error.getvalue())
        self.assertEqual(result['error'], 'original parameter read failed')
        self.assertEqual(result['type'], 'RuntimeError')
        self.assertEqual(result['programming_cleanup_errors'], [{'type': 'KeyboardInterrupt', 'error': 'session end interrupted'}])
        self.assertFalse(result['programming_cleanup_errors_truncated'])
        self.assertTrue(client.commands[-1].startswith('PP END ')); self.assertFalse(client.connected)
        self.assertFalse(any(request.startswith('PP UNLOCK ') for request in client.commands))


if __name__ == '__main__': unittest.main()
