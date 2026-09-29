"""Complete original eDLT Page Control workflow capture and its CLI comparison."""
import json
import os
from pathlib import Path
import platform
import socket
import threading
import unittest

from research import original_workflow_capture as capture

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/fixtures/original-workflow-page-control-receipt.json'
REQUIRED = ('CBUS_MONO_MACOS_ROOT', 'CBUS_TOOLKIT_EXE', 'CBUS_LOCAL_CGATE_VENDOR', 'CBUS_CGATE_JAVA', 'CBUS_UNITSPEC_DIR')


class HarnessUnitTests(unittest.TestCase):
    def test_transcript_splits_each_connection_and_direction(self):
        records = [(1, '>', b'&4[1] project use X\n&4[2] pp un'), (1, '<', b'[1] 200 OK.\r\n[2'),
                   (2, '>', b'[1] noop\n'), (1, '>', b'its\n'), (1, '<', b'] 122 none\r\n')]
        lines = capture.transcript(records)
        self.assertEqual([(e['connection'], e['direction'], e['line']) for e in lines],
                         [(1, '>', '&4[1] project use X'), (1, '<', '[1] 200 OK.'), (2, '>', '[1] noop'),
                          (1, '>', '&4[2] pp units'), (1, '<', '[2] 122 none')])
        self.assertEqual(capture.transcript([(1, '>', b'partial')]),
                         [{'connection': 1, 'direction': '>', 'line': 'partial', 'unterminated': True}])

    def test_command_summary_correlates_tags_and_normalizes_names(self):
        lines = capture.transcript([
            (1, '>', b'&4[1] project use ORIGWF\n&4[2] dbgetxml //ORIGWF/254\n'),
            (1, '<', b'[2] 343-Begin\r\n[2] 347-<x/>\r\n[2] 344 End\r\n[1] 401 Bad\r\n'),
            (2, '>', b'[1] PP START cbus_cli_0123456789abcdef lock\n'), (2, '<', b'[1] 200 OK.\r\n')])
        summary = capture.command_summary(lines, project='ORIGWF')
        self.assertEqual([(c['command'], c['codes'], c['final'], c['reply_lines']) for c in summary],
                         [('project use {PROJECT}', ['401'], '401 Bad', 1),
                          ('dbgetxml //{PROJECT}/254', ['343', '344', '347'], '344 End', 3),
                          ('PP START cbus_cli_{SESSION} lock', ['200'], '200 OK.', 1)])
        self.assertEqual(capture.command_sequence_sha256(summary), capture.command_sequence_sha256(
            capture.command_summary(lines, project='ORIGWF')))

    def test_probe_output_parser_keeps_stages_and_failures(self):
        parsed = capture.parse_probe('application:203:1\r\nload-result:True\r\nloaded-pp:A\t0x1\r\nsaved-pp:A\t0x2\r\n'
                                     'changed:A\r\nhost-request:add-level:202/255/255\r\nassembly:X\t/app/X.dll\r\n'
                                     'failure-stage:save\r\nfailure:System.Exception:boom\r\n')
        self.assertEqual(parsed['pp'], {'loaded': {'A': '0x1'}, 'saved': {'A': '0x2'}})
        self.assertEqual((parsed['load_result'], parsed['failure_stage'], parsed['failure']), ('True', 'save', 'System.Exception:boom'))
        self.assertEqual((parsed['changed'], parsed['host_requests'], parsed['assemblies'], parsed['applications']),
                         (['A'], ['add-level:202/255/255'], {'X': '/app/X.dll'}, ['203:1']))

    def test_lifecycle_cache_uses_database_facts_and_fails_closed(self):
        xml = ('<Network><Application><Address>202</Address></Application><Application><Address>56</Address>'
               '<Group><Address>1</Address></Group></Application></Network>')
        requirements = {'applications': [{'application': 202}, {'application': 56}],
                        'groups': [{'application': 202, 'group': 255, 'facts': {'exists': []}, 'conditional_reasons': []},
                                   {'application': 56, 'group': 7, 'facts': {'exists': []}}]}
        self.assertEqual(capture.lifecycle_cache(requirements, xml), {
            'format': 'cbus-edlt-lifecycle-cache-v1', 'applications': [56, 202],
            'groups': [{'application': 202, 'group': 255, 'exists': True}, {'application': 56, 'group': 7, 'exists': False}]})
        with self.assertRaisesRegex(ValueError, 'absent'):
            capture.lifecycle_cache({'applications': [{'application': 203}], 'groups': []}, xml)
        with self.assertRaisesRegex(ValueError, 'existence'):
            capture.lifecycle_cache({'applications': [], 'groups': [{'application': 56, 'group': 1, 'facts': {'levels': []}}]}, xml)

    def test_database_differences_are_leaf_paths(self):
        left = '<Network><OID>a</OID><Unit><Description>null</Description><PP Name="A" Value="1"/></Unit></Network>'
        right = '<Network><OID>b</OID><Unit><PP Name="A" Value="2"/></Unit></Network>'
        self.assertEqual(capture.database_differences(capture.normalized_database(left, 'ORIGWF'), capture.normalized_database(right, 'ORIGWF')),
                         {'/Unit#1/Description#1': ['null', None], '/Unit#1/PP[A]#1': [' @Value=1', ' @Value=2']})

    def test_relay_records_order_without_altering_bytes(self):
        server = socket.create_server(('127.0.0.1', 0))

        def serve():
            connection, _ = server.accept()
            with connection:
                connection.sendall(b'201 ready\r\n')
                data = connection.recv(100)
                connection.sendall(b'[1] 200 ' + data.split(b' ', 1)[1])
        thread = threading.Thread(target=serve)
        thread.start()
        relay = capture.RecordingRelay(server.getsockname()[1])
        try:
            with socket.create_connection(('127.0.0.1', relay.port)) as client:
                self.assertEqual(client.recv(100), b'201 ready\r\n')
                client.sendall(b'[1] noop\n')
                reply = b''
                while not reply.endswith(b'\n'):
                    reply += client.recv(100)
            thread.join(10)
        finally:
            relay.close()
            server.close()
        self.assertEqual(reply, b'[1] 200 noop\n')
        self.assertEqual([(e['direction'], e['line']) for e in capture.transcript(relay.records)],
                         [('<', '201 ready'), ('>', '[1] noop'), ('<', '[1] 200 noop')])

    def test_committed_receipt_is_sanitized_and_complete(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertEqual((receipt['format'], receipt['workflow'], receipt['group']), (capture.FORMAT, capture.WORKFLOW, 42))
        self.assertTrue(receipt['passed'])
        self.assertTrue(all(receipt['stages'].values()) and all(receipt['comparisons'].values()))
        self.assertFalse(receipt['physical_device_verified'])
        self.assertEqual(receipt['inputs']['probe_source_sha256'], capture.sha256(capture.PROBE.read_bytes()))
        for name, digest in capture.ORIGINAL_HASHES.items():
            if name in receipt['original_assemblies']:
                self.assertEqual(receipt['original_assemblies'][name], digest)
        self.assertIn('CBusLogicModel.dll', receipt['original_assemblies'])
        self.assertEqual(receipt['original']['page_control_byte'], receipt['cli']['page_control_byte'])
        self.assertEqual(receipt['original']['final_raw_image_sha256'], receipt['cli']['final_raw_image_sha256'])
        self.assertTrue(receipt['cli_direct']['parameter_differences_from_original'])
        text = RECEIPT.read_text()
        self.assertNotIn(capture.PROJECT, text)
        self.assertNotIn('<Param>', text)  # no unit-specification content, only hashes
        commands = [c['command'] for c in receipt['original']['edit_transcript']]
        self.assertIn('pp set TheLockSession_{PROJECT}_Db_Net254_Unit20 KeySetsEnableGroup "0x2A"', commands)
        self.assertEqual(commands[-1], 'PP CANCEL_LOCK 20')


@unittest.skipUnless(platform.system() == 'Darwin' and all(os.environ.get(name) for name in REQUIRED),
                     'Set CBUS_MONO_MACOS_ROOT, CBUS_TOOLKIT_EXE, CBUS_LOCAL_CGATE_VENDOR, CBUS_CGATE_JAVA and '
                     'CBUS_UNITSPEC_DIR for the complete original workflow capture')
class OriginalWorkflowCaptureTests(unittest.TestCase):
    def test_original_model_workflow_matches_cli_and_committed_receipt(self):
        report = os.environ.get('CBUS_ORIGINAL_WORKFLOW_REPORT')
        receipt = capture.from_environment(runtime_report=report)
        self.assertTrue(all(receipt['stages'].values()), receipt['stages'])
        self.assertTrue(all(receipt['comparisons'].values()), receipt['comparisons'])
        original = receipt['original']
        self.assertEqual(original['identity'], 'KEYGL5:5.5.00:5055EDL')
        self.assertEqual(original['binding_after'], '42:0x2A')
        self.assertEqual(original['page_control_byte'], '2a')
        self.assertIn('KeySetsEnableGroup', original['changed_parameters'])
        self.assertEqual(original['host_requests']['edit'], [])
        self.assertTrue(receipt['cli_direct']['parameter_differences_from_original'])
        committed = json.loads(RECEIPT.read_text())
        # Reproducible fields; run-specific transcripts and harness revisions are excluded.
        for key in ('seed_sha256', 'seeded_database_sha256', 'initial_raw_image_sha256', 'initial_parameters_sha256',
                    'unit_specification_sha256', 'probe_source_sha256'):
            self.assertEqual(receipt['inputs'][key], committed['inputs'][key], key)
        self.assertEqual(receipt['original_assemblies'], committed['original_assemblies'])
        for key in ('saved_parameters_sha256', 'crcs', 'final_raw_image_sha256', 'command_sequence_sha256',
                    'changed_parameters', 'save_stage_changes', 'database_differences_from_cli'):
            self.assertEqual(original[key], committed['original'][key], key)
        for key in ('final_raw_image_sha256', 'command_sequence_sha256'):
            self.assertEqual(receipt['cli'][key], committed['cli'][key], key)
        self.assertEqual(receipt['cli_direct']['parameter_differences_from_original'],
                         committed['cli_direct']['parameter_differences_from_original'])


if __name__ == '__main__':
    unittest.main()
