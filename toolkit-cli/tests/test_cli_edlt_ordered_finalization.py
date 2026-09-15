"""Do not lose successful staging when the following read/save/cleanup fails."""
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import cli
from cbus_toolkit.edlt_applications import EdltApplications
from cbus_toolkit.edlt_corridor import EdltCorridor
from cbus_toolkit.edlt_control_cli import program, OrderedControlCommandError
from tests.test_edlt_applications import cache_for
from tests.test_edlt_corridor import fixture, cache as corridor_cache
from tests.test_edlt import Session


class OrderedControlFinalizationTests(unittest.TestCase):
    def test_cli_keeps_verified_edit_evidence_after_read_save_or_cleanup_failure(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name.startswith('edlt_'): raise SystemExit('Secondary attachment failure')
                super().__setattr__(name, value)
        for kind, factory in (('applications', EdltApplications), ('corridor', EdltCorridor)):
            for phase in ('readback', 'save', 'cleanup', 'connection_cleanup'):
                for error_type in (KeyboardInterrupt, OSError, RejectEvidence):
                    with self.subTest(kind=kind, phase=phase, error=error_type.__name__):
                        spec = fixture(); editor = factory(spec); session = Session(spec)
                        cache = cache_for(editor, session.values()) if kind == 'applications' else corridor_cache()
                        error = error_type('Owned failure after staging'); completed = []
                        configure = editor.configure
                        def staged(*args, **kwargs):
                            result = configure(*args, **kwargs); completed.append(result)
                            if phase == 'readback': session.values = Mock(side_effect=error)
                            return result
                        session.save_to_source = Mock(side_effect=error if phase == 'save' else None, return_value=object())
                        @contextmanager
                        def context():
                            yield session
                            if phase == 'cleanup': raise error
                        @contextmanager
                        def connection():
                            yield SimpleNamespace()
                            if phase == 'connection_cleanup': raise error
                        with tempfile.TemporaryDirectory() as folder:
                            metadata = Path(folder) / 'cache.json'; metadata.write_text(json.dumps(cache.as_dict()))
                            out, err = io.StringIO(), io.StringIO()
                            with patch.object(editor, 'configure', side_effect=staged), \
                                    patch.object(cli, '_edlt_' + kind, return_value=editor), \
                                    patch('cbus_toolkit.cgate.CGateClient', return_value=connection()), \
                                    patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=context()))), \
                                    redirect_stdout(out), redirect_stderr(err):
                                status = cli.main(['cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                                                   'edlt-' + kind, '--metadata', str(metadata)])
                        self.assertEqual(status, 130 if isinstance(error, KeyboardInterrupt) else 1, err.getvalue())
                        payload = json.loads(err.getvalue()); evidence = payload['edlt_' + kind + '_evidence']
                        self.assertEqual(len(completed), 1)
                        self.assertEqual(evidence['phases'], completed[0]['phases'])
                        self.assertEqual(evidence['attempted_parameters'], list(completed[0]['changes']))
                        self.assertEqual(evidence['failure_phase'], phase)
                        self.assertTrue(evidence['staging_verified']); self.assertFalse(evidence['operation_completed'])
                        self.assertFalse(evidence['rollback_performed'])
                        self.assertEqual(evidence['save_attempted'], phase != 'readback')
                        self.assertEqual(evidence['saved'], phase in ('cleanup', 'connection_cleanup'))
                        self.assertEqual(evidence['destination'], session.source)
                        self.assertEqual(evidence['save_outcome_uncertain'], phase == 'save')
                        self.assertEqual(session.save_to_source.call_count, int(phase != 'readback'))

    def test_unprintable_error_preserves_cause_and_cleanup_evidence(self):
        class BadError(RuntimeError):
            def __str__(self): raise KeyboardInterrupt('Secondary formatter failure')
        cause = BadError(); cleanup = OSError('cleanup'); cause.cgate_cleanup_errors = (cleanup,)
        result = {'changes': {'Example': [1]}, 'phases': {}, 'verified': True, 'saved': False}
        editor = SimpleNamespace(configure=Mock(return_value=result))
        session = SimpleNamespace(values=Mock(side_effect=cause), save_to_source=Mock())
        with self.assertRaises(OrderedControlCommandError) as caught:
            program(nullcontext(session), editor, {}, kind='applications', destination='/db//OWNED/254/p/20',
                    explicit_destination=False, dry_run=False)
        self.assertIs(caught.exception.cause, cause); self.assertIs(caught.exception.__cause__, cause)
        self.assertEqual(caught.exception.cgate_cleanup_errors, (cleanup,))
        self.assertIn('unprintable BadError', str(caught.exception))
        self.assertEqual(caught.exception.edlt_applications_evidence['failure_phase'], 'readback')
        session.save_to_source.assert_not_called()

    def test_interruption_identity_survives_rejected_evidence_attachment(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name.startswith('edlt_'): raise SystemExit('Secondary attachment failure')
                super().__setattr__(name, value)
        cause = RejectEvidence('First interruption')
        editor = SimpleNamespace(configure=Mock(return_value={'changes': {}, 'verified': True, 'phases': {}}))
        session = SimpleNamespace(values=Mock(side_effect=cause), save_to_source=Mock())
        with self.assertRaises(RejectEvidence) as caught:
            program(nullcontext(session), editor, {}, kind='corridor', destination='/db//OWNED/254/p/20',
                    explicit_destination=False, dry_run=True)
        self.assertIs(caught.exception, cause)
        self.assertEqual(editor.last_evidence['failure_phase'], 'readback')
        self.assertFalse(editor.last_evidence['save_attempted'])
        session.save_to_source.assert_not_called()


    def test_explicit_database_destination_is_saved_once(self):
        source = {'changes': {'Example': [1]}, 'phases': {}, 'verified': True}
        editor = SimpleNamespace(configure=Mock(return_value=source))
        session = SimpleNamespace(values=Mock(return_value={'Example': '1'}),
                                  save=Mock(return_value=object()), save_to_source=Mock())
        destination = '/db//OWNED/254/p/21'; state = {}
        result = program(nullcontext(session), editor, {}, kind='corridor', destination=destination,
                         explicit_destination=True, dry_run=False, state=state)
        session.save.assert_called_once_with(destination); session.save_to_source.assert_not_called()
        self.assertTrue(result['saved']); self.assertEqual(result['destination'], destination)
        self.assertTrue(state['evidence']['operation_completed'])
        self.assertFalse(state['evidence']['save_outcome_uncertain'])


    def test_configure_fallback_reaches_cli_and_never_reuses_old_evidence(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name.startswith('edlt_'): raise SystemExit('Secondary attachment failure')
                super().__setattr__(name, value)
        for kind, factory in (('applications', EdltApplications), ('corridor', EdltCorridor)):
            spec = fixture(); editor = factory(spec); session = Session(spec)
            cache = cache_for(editor, session.values()) if kind == 'applications' else corridor_cache()
            error = RejectEvidence('First write interrupted'); session.set = Mock(side_effect=error)
            session.save_to_source = Mock()
            with tempfile.TemporaryDirectory() as folder:
                metadata = Path(folder) / 'cache.json'; metadata.write_text(json.dumps(cache.as_dict()))
                out, err = io.StringIO(), io.StringIO()
                with patch.object(cli, '_edlt_' + kind, return_value=editor), \
                        patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                        patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                        redirect_stdout(out), redirect_stderr(err):
                    status = cli.main(['cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                                       'edlt-' + kind, '--metadata', str(metadata)])
            self.assertEqual(status, 130, err.getvalue())
            evidence = json.loads(err.getvalue())['edlt_' + kind + '_evidence']
            self.assertEqual(evidence['failure_phase'], 'configure')
            self.assertFalse(evidence['staging_verified']); self.assertFalse(evidence['save_attempted'])
            self.assertEqual(evidence['attempted_parameters'], [session.set.call_args.args[0]])
            self.assertEqual(session.set.call_count, 1); session.save_to_source.assert_not_called()
        editor = SimpleNamespace(last_evidence={'saved': True}, configure=Mock(side_effect=error))
        state = {}
        with self.assertRaises(RejectEvidence) as caught:
            program(nullcontext(SimpleNamespace()), editor, {}, kind='corridor', destination='/db//OWNED/254/p/20',
                    explicit_destination=False, dry_run=False, state=state)
        self.assertIs(caught.exception, error); self.assertEqual(state, {})


if __name__ == '__main__': unittest.main()
