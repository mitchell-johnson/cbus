"""Shared error evidence must not invoke an unsafe exception formatter."""
import unittest
from cbus_toolkit.edlt import EdltApplyError, EdltLighting
from tests.test_edlt import fixture, Session


class EdltApplyErrorTests(unittest.TestCase):
    def test_printable_error_text_and_json_remain_exact(self):
        cause = RuntimeError('ordinary original error')
        for rollback in ((), ('restore failed',)):
            with self.subTest(rollback=rollback):
                error = EdltApplyError(cause, rollback, ('Field',))
                self.assertIs(error.cause, cause)
                self.assertEqual(str(error), 'eDLT edit failed; ' +
                    ('rollback had errors' if rollback else 'original PP values were restored') +
                    ': ordinary original error')
                expected = {'error': 'ordinary original error', 'attempted_parameters': ['Field'],
                    'rollback_errors': list(rollback), 'saved': False, 'rollback_verified': not rollback}
                self.assertEqual(error.details, expected)
                self.assertEqual(error.as_dict(), expected)
        long = 'x' * 4096
        self.assertEqual(EdltApplyError(RuntimeError(long)).as_dict()['error'], long)

    def test_unprintable_cause_preserves_identity_and_repeatable_evidence(self):
        for secondary in (KeyboardInterrupt('format interrupt'), SystemExit(7), RuntimeError('format error')):
            with self.subTest(secondary=type(secondary).__name__):
                class Unprintable(RuntimeError):
                    def __str__(self): raise secondary
                cause = Unprintable()
                error = EdltApplyError(cause, ('rollback failed',), ('Field',))
                self.assertIs(error.cause, cause)
                self.assertEqual(error.details['error'], '<unprintable Unprintable>')
                self.assertEqual(error.as_dict(), error.details)
                self.assertIn('<unprintable Unprintable>', str(error))
                self.assertFalse(error.details['rollback_verified'])

    def test_unprintable_type_name_falls_back_without_replacing_cause(self):
        class Meta(type):
            def __getattribute__(self, name):
                if name == '__name__': raise KeyboardInterrupt('type formatting interrupted')
                return super().__getattribute__(name)
        class Odd(RuntimeError, metaclass=Meta):
            def __str__(self): raise SystemExit('string formatting interrupted')
        cause = Odd()
        error = EdltApplyError(cause)
        self.assertIs(error.cause, cause)
        self.assertEqual(error.details['error'], '<unprintable exception>')
        self.assertEqual(error.as_dict(), error.details)

    def test_actual_staging_error_retains_cause_after_verified_rollback(self):
        class Unprintable(RuntimeError):
            def __str__(self): raise KeyboardInterrupt('formatter only')
        cause = Unprintable()
        spec = fixture(); session = Session(spec); editor = EdltLighting(spec)
        plan = editor.plan(session.values(), page=1, position=1, group=42, mode='dimmer')
        original = editor.snapshot(session.values()); actual_set = session.set; calls = []
        def fail_once(name, value):
            calls.append(name); actual_set(name, value)
            if len(calls) == 1: raise cause
        session.set = fail_once
        with self.assertRaises(EdltApplyError) as caught: editor.apply(session, plan)
        error = caught.exception
        self.assertIs(error.cause, cause); self.assertIs(error.__cause__, cause)
        self.assertTrue(error.details['rollback_verified'])
        self.assertEqual(editor.snapshot(session.values()), original)
        self.assertEqual(calls, [next(iter(plan.changes))] * 2)

    def test_actual_failed_rollback_keeps_primary_and_partial_state_evidence(self):
        class Unprintable(RuntimeError):
            def __str__(self): raise SystemExit('formatter only')
        cause = Unprintable()
        spec = fixture(); session = Session(spec); editor = EdltLighting(spec)
        plan = editor.plan(session.values(), page=1, position=1, group=42, mode='dimmer')
        actual_set = session.set; calls = []
        def fail(name, value):
            calls.append(name)
            if len(calls) == 1:
                actual_set(name, value); raise cause
            raise RuntimeError('rollback failed')
        session.set = fail
        with self.assertRaises(EdltApplyError) as caught: editor.apply(session, plan)
        error = caught.exception
        self.assertIs(error.cause, cause); self.assertIs(error.__cause__, cause)
        self.assertFalse(error.details['rollback_verified'])
        self.assertIn('rollback failed', error.details['rollback_errors'])
        self.assertEqual(error.details['attempted_parameters'], [next(iter(plan.changes))])
        self.assertEqual(len(calls), 2)


if __name__ == '__main__': unittest.main()
