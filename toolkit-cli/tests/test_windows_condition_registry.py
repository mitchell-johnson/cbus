"""Host-side registry transport tests; these never execute the Windows worker.

Synthetic frames test correlation and failure behavior only. They are not
evidence of a Framework registry read or a live Windows provider identity.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import _toolkit_update_registry_conditions as leaves
from cbus_toolkit import windows_condition_registry as subject


QUERY = {'path': 'HKEY_CURRENT_USER\\Software\\CbusCliOwnedTest', 'entry': 'Value',
         'default': {'kind': 'System.String', 'value': leaves.SENTINEL}}


def encode(value):
    return json.dumps(value).encode('ascii')


def scope(*queries):
    return subject.RegistryReadScope.from_json(encode(
        {'format': subject.SCOPE_FORMAT, 'queries': list(queries or (QUERY,))}))


def observer(**kwargs):
    return subject.WindowsConditionRegistry(compiler_path=subject.COMPILER, scope=scope(), **kwargs)


class RegistryScopeAndCaptureTests(unittest.TestCase):
    def test_scope_validation_is_inert_and_duplicate_identities_are_rejected(self):
        with patch.object(subject.WindowsConditionRegistry, '_start') as start:
            instance = observer()
            instance.close()
            start.assert_not_called()
        self.assertEqual(instance.last_report.as_dict()['observations'], [])
        for queries in ([], [QUERY] * 2, [QUERY] * 9):
            with self.subTest(count=len(queries)), self.assertRaises(subject._Outcome):
                subject.RegistryReadScope.from_json(encode({'format': subject.SCOPE_FORMAT, 'queries': queries}))

    def test_invalid_or_out_of_scope_queries_do_not_start_a_process(self):
        for query in ({**QUERY, 'entry': 'Other'}, {**QUERY, 'path': 'HKCU\\Software\\Owned'},
                      {**QUERY, 'default': {'kind': 'System.Int32', 'value': True}}):
            with self.subTest(query=query):
                instance = observer()
                with patch.object(instance, '_start') as start, self.assertRaises(subject._Outcome):
                    instance.read(query)
                start.assert_not_called()
                self.assertEqual(instance._records, [])
                instance.close()

    def test_capture_preflights_all_queries_before_first_read(self):
        instance = observer()
        queries = encode({'format': subject.QUERY_FORMAT, 'queries': [QUERY, {**QUERY, 'entry': 'Other'}]})
        with patch.object(instance, 'read') as read, self.assertRaises(subject._Outcome):
            instance.capture(queries)
        read.assert_not_called()

    def test_export_preserves_typed_results_but_rejects_repeated_observation_identity(self):
        observation = {'query': QUERY, 'result': {'kind': 'null', 'value': None}}
        report = subject.RegistryCaptureReport(json.dumps(
            {'capture_completed': True, 'cause': None, 'observations': [observation]}))
        exported = report.context_v2()
        self.assertEqual(exported['registry_reads'][0], {**QUERY, 'result': observation['result']})
        self.assertEqual(leaves.facts(exported)[subject._query(QUERY)], ('null', None))
        repeated = subject.RegistryCaptureReport(json.dumps(
            {'capture_completed': True, 'cause': None, 'observations': [observation, observation]}))
        with self.assertRaisesRegex(ValueError, 'Repeated query'):
            repeated.context_v2()

    def test_forged_tampered_and_cross_observer_receipts_are_rejected(self):
        instance, other = observer(), observer()
        instance._proof = {'synthetic_transport_test_only': True}
        other._proof = {'synthetic_transport_test_only': True}
        receipt = subject.RegistryObservation('{"sequence":0}')
        with self.assertRaises(ValueError):
            instance._validate_observation(receipt)
        instance._issued[id(receipt)] = (receipt, receipt._document)
        self.assertEqual(instance._validate_observation(receipt), {'sequence': 0})
        with self.assertRaises(ValueError):
            other._validate_observation(receipt)
        object.__setattr__(receipt, '_document', '{"sequence":1}')
        with self.assertRaises(ValueError):
            instance._validate_observation(receipt)


class RegistryTransportTests(unittest.TestCase):
    def test_publication_preserves_existing_and_concurrently_created_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'request'
            target.write_bytes(b'existing')
            with self.assertRaises(ValueError):
                subject._publish(target, b'replacement')
            self.assertEqual(target.read_bytes(), b'existing')
            self.assertFalse(target.with_name(target.name + '.host-partial').exists())
            target.unlink()
            def competing_link(source, destination):
                Path(destination).write_bytes(b'concurrent')
                raise FileExistsError('concurrent publication')
            with patch.object(subject.os, 'link', side_effect=competing_link), self.assertRaises(ValueError):
                subject._publish(target, b'replacement')
            self.assertEqual(target.read_bytes(), b'concurrent')
            self.assertFalse(target.with_name(target.name + '.host-partial').exists())

    def test_unsupported_hardlinks_stop_without_rename_or_partial_leak(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'request'
            with patch.object(subject.os, 'link', side_effect=OSError('unsupported')), \
                 patch.object(subject.os, 'rename') as rename, self.assertRaisesRegex(OSError, 'hard-link'):
                subject._publish(target, b'request')
            rename.assert_not_called()
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_bounded_read_and_publication_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'request'
            subject._publish(target, b'hello')
            self.assertEqual(subject._read(target, limit=5), b'hello')
            self.assertEqual(subject._read(target, limit=5, digest=True), hashlib.sha256(b'hello').hexdigest())
            with self.assertRaises(ValueError):
                subject._read(target, limit=4)
            link = Path(temporary) / 'link'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                subject._read(link)
            with self.assertRaises(ValueError):
                subject._read(Path(temporary))

    def test_ready_frame_requires_launched_pid_nonce_exact_runtime_and_helper(self):
        instance = observer()
        instance._nonce = 'a' * 32
        instance._helper_hash = 'b' * 64
        instance._process = Mock(pid=4321)
        executable = r'C:\Owned\RegistryWorker.exe'
        fields = ['READY1', instance._nonce, '4321', '4', subject._b64(subject.RUNTIME),
                  subject.RUNTIME_SHA256, subject.RUNTIME_MVID, '060000f3', subject.PROVIDER_IL_SHA256,
                  subject._b64(executable), instance._helper_hash, subject._b64('S-1-5-21-123-456-789-1001')]
        proof = instance._ready('\t'.join(fields), executable)
        self.assertEqual(proof['worker_pid'], 4321)
        self.assertEqual(proof['registry_view'], 'x86-process-default')
        for index in range(len(fields)):
            with self.subTest(field=index), self.assertRaises(ValueError):
                changed = list(fields)
                changed[index] = subject._b64('wrong') if index in (4, 9, 11) else 'wrong'
                instance._ready('\t'.join(changed), executable)
        with self.assertRaises(ValueError):
            instance._ready('\t'.join(fields) + '\textra', executable)

    def test_response_keeps_null_empty_sentinel_and_signed_int32_distinct(self):
        instance = observer()
        instance._nonce = 'a' * 32
        request = b'exact-request'
        prefix = ['RESPONSE1', instance._nonce, '0', hashlib.sha256(request).hexdigest(), 'VALUE']
        for kind, value, expected in (('N', '', ('null', None)), ('S', '', ('System.String', '')),
                ('S', subject._b64(leaves.SENTINEL), ('System.String', leaves.SENTINEL)),
                ('I', subject._b64('-2147483648'), ('System.Int32', -2147483648))):
            with self.subTest(expected=expected):
                record = {'sequence': 0}
                result = instance._response('\t'.join(prefix + [kind, value]), request, record)
                self.assertEqual(result, expected)
                self.assertEqual(record['status'], 'observed')

    def test_wrong_response_correlation_or_noncanonical_integer_never_becomes_observed(self):
        instance = observer()
        instance._nonce = 'a' * 32
        request = b'exact-request'
        fields = ['RESPONSE1', instance._nonce, '0', hashlib.sha256(request).hexdigest(),
                  'VALUE', 'I', subject._b64('1')]
        for index in range(4):
            changed = list(fields)
            changed[index] = 'wrong'
            with self.subTest(field=index), self.assertRaises(ValueError):
                instance._response('\t'.join(changed), request, {'sequence': 0})
        for integer in ('01', '-0', '+1', '2147483648'):
            record = {'sequence': 0}
            changed = fields[:-1] + [subject._b64(integer)]
            with self.subTest(integer=integer), self.assertRaises((ValueError, subject._Outcome)):
                instance._response('\t'.join(changed), request, record)
            self.assertNotIn('result', record)

    def test_provider_error_and_unsupported_kind_stop_session_without_converting(self):
        for status in ('ERROR', 'UNSUPPORTED'):
            with self.subTest(status=status):
                instance = observer()
                instance._nonce = 'a' * 32
                request = b'exact-request'
                record = {'sequence': 0}
                fields = ['RESPONSE1', instance._nonce, '0', hashlib.sha256(request).hexdigest(), status,
                          subject._b64('System.Byte[]'), subject._b64('outside profile')]
                with self.assertRaises(subject._Outcome) as caught:
                    instance._response('\t'.join(fields), request, record)
                self.assertEqual(caught.exception.details['status'], 'failed' if status == 'ERROR' else 'unsupported')
                self.assertTrue(instance._terminal)
                self.assertNotIn('result', record)
                with self.assertRaises(ValueError):
                    instance.read(QUERY)

    def test_worker_exit_does_not_lose_an_already_published_response(self):
        instance = observer()
        instance._directory = Path('/unused-owned-transport-test')
        instance._process = Mock()
        instance._process.poll.return_value = 0
        with patch.object(instance, '_remaining', return_value=1), \
             patch.object(subject, '_read', side_effect=[FileNotFoundError(), b'last-response']):
            self.assertEqual(instance._wait_file('response'), 'last-response')
        with patch.object(instance, '_remaining', return_value=1), \
             patch.object(subject, '_read', side_effect=FileNotFoundError()), \
             self.assertRaisesRegex(RuntimeError, 'exited before publishing'):
            instance._wait_file('response')

    def test_response_that_finishes_after_deadline_is_not_accepted(self):
        instance = observer()
        instance._directory = Path('/unused-owned-transport-test')
        with patch.object(instance, '_remaining', side_effect=[1, TimeoutError('expired')]), \
             patch.object(subject, '_read', return_value=b'response'), self.assertRaises(TimeoutError):
            instance._wait_file('response')


class RegistryCleanupTests(unittest.TestCase):
    def test_reap_is_attempted_after_termination_error_and_first_failure_is_preserved(self):
        instance = observer()
        first = KeyboardInterrupt('owned kill interrupted')
        process = Mock()
        process.poll.return_value = None
        process.kill.side_effect = first
        process.wait.side_effect = SystemExit('secondary wait')
        instance._process = process
        instance._terminal = True
        with self.assertRaises(KeyboardInterrupt) as caught:
            instance.close()
        self.assertIs(caught.exception, first)
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5.0)
        self.assertTrue(instance.last_report.as_dict()['closed'])
        self.assertFalse(instance.last_report.as_dict()['capture_completed'])
        self.assertIs(instance.last_report.cause, first)

    def test_read_failure_survives_compiler_worker_and_file_cleanup_failures(self):
        instance = observer()
        first = KeyboardInterrupt('first read')
        instance._failure = first
        for name in ('_process', '_compiler_process'):
            process = Mock()
            process.poll.return_value = 0
            process.wait.side_effect = SystemExit('secondary reap')
            setattr(instance, name, process)
        handle = Mock()
        handle.close.side_effect = OSError('secondary close')
        instance._handles = [handle]
        with self.assertRaises(KeyboardInterrupt) as caught:
            instance.close()
        self.assertIs(caught.exception, first)
        instance._process.wait.assert_called_once_with(timeout=5.0)
        instance._compiler_process.wait.assert_called_once_with(timeout=5.0)
        handle.close.assert_called_once_with()
        instance.close()
        handle.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
