"""Read-only UTM artifact races; no guest, subprocess, or model execution."""
import json
import subprocess
import unittest
from unittest.mock import patch

from research.windows_bridge import WindowsBridge, WindowsFileBusyError


JOB = 'job-probe-owned-result'
RESULT = json.dumps(dict(complete=True, exit_code=0, admitted=True)).encode()


def busy_message(bridge, name):
    return ("Error from event: The operation couldn’t be completed. (OSStatus error -2700.)\n"
            "failed to open file '" + bridge.path(name) + "': The process cannot access the file because it is being used by another process.\n").encode()


class Clock:
    now = 0.0
    def monotonic(self): return self.now
    def sleep(self, delay): self.now += delay


class WindowsBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = WindowsBridge()
        self.clock = Clock()
        self.calls = []
        self.data = {JOB+'.result.json': RESULT, JOB+'.stdout.txt': b'original CRC output', JOB+'.stderr.txt': b''}
        self.busy = {}
        self.fault = None
        self.addCleanup(patch.stopall)
        patch('research.windows_bridge.time.monotonic', self.clock.monotonic).start()
        patch('research.windows_bridge.time.sleep', self.clock.sleep).start()
        self.process = patch('research.windows_bridge.subprocess.run', side_effect=self.execute).start()
        self.submit = patch.object(self.bridge, 'submit', side_effect=AssertionError('never replay a job')).start()

    def execute(self, argv, **options):
        name = argv[-1].rsplit('\\', 1)[-1]
        self.calls.append((tuple(argv), dict(options), name))
        self.assertEqual(argv[1:3], ['file', 'pull'])
        if self.fault is not None:
            return self.fault(name, argv, options)
        if self.busy.get(name, 0):
            self.busy[name] -= 1
            return subprocess.CompletedProcess(argv, 0, b'', busy_message(self.bridge, name))
        if name not in self.data:
            return subprocess.CompletedProcess(argv, 0, b'', b'The system cannot find the file specified')
        return subprocess.CompletedProcess(argv, 0, self.data[name], b'')

    def test_exact_sharing_error_classification_preserves_operation_path_and_stderr(self):
        name = JOB+'.result.json'
        self.busy[name] = 1
        with self.assertRaises(WindowsFileBusyError) as caught: self.bridge.pull(name)
        error = caught.exception
        self.assertEqual(error.as_dict(), dict(operation='pull', relative=name, guest_path=self.bridge.path(name), returncode=0,
                                              stderr=busy_message(self.bridge, name).decode()))
        self.assertEqual(len(self.calls), 1)
        for changed in (busy_message(self.bridge, 'job-other.result.json'), busy_message(self.bridge, name).replace(b'being used', b'not accessible'),
                        b'permission denied', b'prefix\n'+busy_message(self.bridge, name)):
            with self.subTest(stderr=changed), patch('research.windows_bridge.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'', changed)):
                with self.assertRaises(RuntimeError) as ordinary: self.bridge.pull(name)
                self.assertNotIsInstance(ordinary.exception, WindowsFileBusyError)
        for operation, code in (('push', 0), ('pull', 1)):
            with self.subTest(operation=operation, code=code), patch('research.windows_bridge.subprocess.run', return_value=subprocess.CompletedProcess([], code, b'', busy_message(self.bridge, name))):
                with self.assertRaises(RuntimeError) as ordinary: self.bridge._file(operation, name)
                self.assertNotIsInstance(ordinary.exception, WindowsFileBusyError)

    def test_direct_result_raises_busy_without_polling(self):
        self.busy[JOB+'.stdout.txt'] = 1
        with self.assertRaises(WindowsFileBusyError): self.bridge.result(JOB)
        self.assertEqual([row[2] for row in self.calls], [JOB+'.result.json', JOB+'.stdout.txt'])
        self.assertIsNone(self.bridge.last_wait_evidence)
        self.submit.assert_not_called()

    def test_wait_retrieves_same_job_after_each_artifact_busy_and_detaches_evidence(self):
        self.busy = {name: 1 for name in self.data}
        result = self.bridge.wait(JOB, timeout=5)
        self.assertEqual((result['stdout'], result['stderr']), (b'original CRC output', b''))
        self.assertEqual(result['job_id'], JOB)
        evidence = result['wait_evidence']
        self.assertEqual([row['relative'] for row in evidence['file_busy_attempts']], list(self.data))
        self.assertEqual([row['attempt'] for row in evidence['file_busy_attempts']], [1, 2, 3])
        self.assertEqual(evidence['state'], 'retrieved')
        self.assertFalse(evidence['job_resubmitted'])
        self.assertTrue(all(row[2] in self.data for row in self.calls))
        evidence['file_busy_attempts'][0]['relative'] = 'tampered'
        self.assertEqual(self.bridge.last_wait_evidence['file_busy_attempts'][0]['relative'], JOB+'.result.json')
        again = self.bridge.wait(JOB)
        self.assertEqual(again['wait_evidence']['file_busy_attempts'], [])
        self.assertIsNone(self.bridge.last_wait_error)
        self.submit.assert_not_called()

    def test_missing_result_then_busy_uses_existing_job(self):
        count = 0
        def fault(name, argv, options):
            nonlocal count
            count += 1
            if count == 1: return subprocess.CompletedProcess(argv, 0, b'', b'The system cannot find the file specified')
            if count == 2: return subprocess.CompletedProcess(argv, 0, b'', busy_message(self.bridge, name))
            return subprocess.CompletedProcess(argv, 0, self.data[name], b'')
        self.fault = fault
        self.assertTrue(self.bridge.wait(JOB, timeout=5)['complete'])
        self.assertEqual(count, 5)
        self.assertEqual(self.clock.now, 1)
        self.submit.assert_not_called()

    def test_retry_count_is_bounded_and_keeps_terminal_busy_error(self):
        for bound in (0, 1, 8):
            with self.subTest(bound=bound):
                self.calls.clear(); self.busy = {JOB+'.result.json': 100}
                with self.assertRaises(WindowsFileBusyError) as caught: self.bridge.wait(JOB, timeout=30, max_busy_retries=bound)
                self.assertIs(self.bridge.last_wait_error, caught.exception)
                self.assertEqual(len(self.calls), bound+1)
                self.assertEqual(len(caught.exception.windows_bridge_wait_evidence['file_busy_attempts']), bound+1)
                self.assertEqual(self.bridge.last_wait_evidence['state'], 'error')
        self.submit.assert_not_called()

    def test_one_deadline_bounds_busy_wait_and_each_artifact_subprocess(self):
        self.busy = {JOB+'.result.json': 100}
        with self.assertRaises(TimeoutError): self.bridge.wait(JOB, timeout=.75)
        self.assertEqual([row[1]['timeout'] for row in self.calls], [.75, .25])
        self.assertEqual(self.clock.now, .75)
        self.calls.clear(); self.busy.clear(); self.clock.now = 0
        def fault(name, argv, options):
            self.clock.now += .4
            return subprocess.CompletedProcess(argv, 0, self.data[name], b'')
        self.fault = fault
        with self.assertRaisesRegex(TimeoutError, 'after its deadline'): self.bridge.wait(JOB, timeout=1)
        budgets = [row[1]['timeout'] for row in self.calls]
        self.assertEqual(len(budgets), 3)
        for actual, expected in zip(budgets, (1, .6, .2)): self.assertAlmostEqual(actual, expected)
        self.assertEqual(self.bridge.last_wait_evidence['state'], 'error')

    def test_timeout_expired_from_subprocess_is_preserved_without_retry(self):
        error = subprocess.TimeoutExpired(['utmctl', 'file', 'pull'], .2)
        self.fault = lambda *unused: (_ for _ in ()).throw(error)
        with self.assertRaises(subprocess.TimeoutExpired) as caught: self.bridge.wait(JOB, timeout=.2)
        self.assertIs(caught.exception, error)
        self.assertIs(self.bridge.last_wait_error, error)
        self.assertEqual(len(self.calls), 1)

    def test_unrelated_busy_path_and_nonsharing_failures_are_never_retried(self):
        other = WindowsFileBusyError('pull', 'job-other.result.json', self.bridge.path('job-other.result.json'), 0, 'busy')
        with patch.object(self.bridge, 'result', side_effect=other) as read:
            with self.assertRaises(WindowsFileBusyError) as caught: self.bridge.wait(JOB)
            self.assertIs(caught.exception, other); self.assertEqual(read.call_count, 1)
            self.assertEqual(self.bridge.last_wait_evidence['file_busy_attempts'], [])
        for data, stderr in ((b'{', b''), (b'', b'access denied')):
            self.calls.clear()
            self.fault = lambda name, argv, opts: subprocess.CompletedProcess(argv, 0, data, stderr)
            with self.assertRaises((RuntimeError, json.JSONDecodeError)): self.bridge.wait(JOB)
            self.assertEqual(len(self.calls), 1)

    def test_invalid_options_reset_evidence_before_submission_or_read(self):
        options = [{'timeout': value} for value in (True, 0, -1, '1', float('inf'), float('nan'), 1<<2048)]
        options += [{'max_busy_retries': value} for value in (True, -1, 257, 1.5, '2')]
        for settings in options:
            for method in (lambda: self.bridge.wait(JOB, **settings), lambda: self.bridge.run('owned script', **settings)):
                self.bridge.last_wait_evidence = {'stale': True}; self.bridge.last_wait_error = RuntimeError('old')
                with self.assertRaises(ValueError): method()
                self.assertIsNone(self.bridge.last_wait_evidence); self.assertIsNone(self.bridge.last_wait_error)
        self.submit.assert_not_called(); self.process.assert_not_called()

    def test_interruption_identity_survives_refused_evidence_and_next_wait_is_fresh(self):
        class First(KeyboardInterrupt):
            def __str__(self): raise SystemExit('format refused')
            def __setattr__(self, name, value): raise SystemExit('attachment refused')
        first = First()
        self.fault = lambda *unused: (_ for _ in ()).throw(first)
        with self.assertRaises(KeyboardInterrupt) as caught: self.bridge.wait(JOB)
        self.assertIs(caught.exception, first); self.assertIs(self.bridge.last_wait_error, first)
        self.assertEqual(self.bridge.last_wait_evidence['job_id'], JOB)
        self.fault = None
        self.assertTrue(self.bridge.wait(JOB)['complete'])
        self.assertIsNone(self.bridge.last_wait_error)

    def test_run_submits_once_then_only_reads_and_keeps_recording_override_compatible(self):
        class RecordingBridge(WindowsBridge):
            def run(self, script, **kwargs):
                result = super().run(script, **kwargs)
                self.recorded = result['wait_evidence']
                return result
        recording = RecordingBridge()
        self.busy[JOB+'.result.json'] = 2
        with patch.object(recording, 'submit', return_value=JOB) as submit:
            result = recording.run('owned script', job_id=JOB, timeout=5, max_busy_retries=3)
        submit.assert_called_once_with('owned script', job_id=JOB)
        self.assertEqual(len(recording.recorded['file_busy_attempts']), 2)
        self.assertTrue(result['complete'])


if __name__ == '__main__': unittest.main()
