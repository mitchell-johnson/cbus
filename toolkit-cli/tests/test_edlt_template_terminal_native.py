"""Failure evidence of the owned native helper; these tests start no service."""
import unittest

from research.edlt_template_terminal_native import cleanup, error_record


class NativeProofFailureTests(unittest.TestCase):
    def test_cleanup_retains_primary_save_failure_and_attempts_all_owned_cleanup(self):
        evidence, calls = {}, []
        primary = RuntimeError('save outcome unknown')
        def first(): calls.append('first'); raise ValueError('close failed')
        def second(): calls.append('second'); raise OSError('delete failed')
        with self.assertRaises(RuntimeError) as caught:
            try: raise primary
            finally: cleanup(evidence, [('close', first), ('delete', second)])
        self.assertIs(caught.exception, primary)
        self.assertEqual(calls, ['first', 'second'])
        self.assertEqual([row['operation'] for row in evidence['cleanup_errors']], ['close', 'delete'])

    def test_cleanup_failure_without_primary_fails_after_remaining_cleanup(self):
        evidence, calls = {}, []
        failure = KeyboardInterrupt('owned cleanup interruption')
        def first(): raise failure
        with self.assertRaises(KeyboardInterrupt) as caught:
            cleanup(evidence, [('service', first), ('sentinel', lambda: calls.append('closed'))])
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, ['closed'])
        self.assertEqual(evidence['cleanup_errors'][0]['type'], 'KeyboardInterrupt')

    def test_hostile_exception_formatting_cannot_replace_primary_evidence(self):
        class Hostile(RuntimeError):
            def __str__(self): raise KeyboardInterrupt('hostile formatter')
        self.assertEqual(error_record(Hostile()),
                         {'type': 'Hostile', 'message': '<unprintable exception>'})


if __name__ == '__main__': unittest.main()
