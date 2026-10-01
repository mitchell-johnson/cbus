"""Public typed network creation/definition wire boundaries and owned service."""
from pathlib import Path
import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import unittest

from tests.test_cgate import peer


class NetworkNewPublicWireTests(unittest.TestCase):
    def invoke(self, endpoint, *arguments, expected=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', endpoint[0],
                                 '--port', str(endpoint[1]), '--timeout', '1', *map(str, arguments)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout or result.stderr)

    def test_network_new_sends_exact_use_create_load_once_without_implicit_save_or_open(self):
        for creation_status, creation_line in ((200, b'[2] 200 OK.\r\n'),
                                               (301, b'[2] 301 OID=71000000-0000-4000-8000-000000000001\r\n')):
            responses = [[b'[1] 200 OK.\r\n'], [creation_line], [b'[3] 200 OK.\r\n']]
            for kind, address in (('Cni', '127.0.0.1:1'), ('Serial', 'SYNTHETIC_SERIAL'), ('Bridge', '254/p/252')):
                with self.subTest(kind=kind, creation_status=creation_status), peer(responses) as (endpoint, sent):
                    result = self.invoke(endpoint, 'database', 'network-new', 'LAB', 252, 'Owned', kind, address)
                self.assertEqual(result['status'], creation_status)
                self.assertEqual(sent, [b'[1] PROJECT USE LAB\r\n',
                                       f'[2] DBCREATENET 252 Owned {kind} {address}\r\n'.encode(), b'[3] NET LOAD DB\r\n'])

    def test_every_typed_definition_operation_has_one_exact_explicit_project_wire_sequence(self):
        cases = (
            (('list',), 'NET LIST LAB', 132),
            (('create', 'Owned', 'cni', '127.0.0.1:1', '--option', 'alpha=beta', '--option', 'baud=9600'),
             'NET CREATE Owned cni 127.0.0.1:1 alpha=beta baud=9600', 200),
            (('rename', 'Owned', 'Alias', '--no-fix-references'), 'NET RENAME Owned Alias nofixrefs', 200),
            (('rename', 'Owned', 'Alias'), 'NET RENAME Owned Alias', 200),
            (('flush', 'Alias'), 'NET FLUSH Alias', 200),
            (('delete', 'Alias'), 'NET DELETE Alias', 200),
            (('load', 'DB'), 'NET LOAD DB LAB', 200),
            (('save', 'DB'), 'NET SAVE DB LAB', 200),
            (('load', 'FILE'), 'NET LOAD FILE LAB', 200),
            (('save', 'FILE'), 'NET SAVE FILE LAB', 200),
            (('create', 'cgate', 'cni', '127.0.0.1:1'), 'NET CREATE cgate cni 127.0.0.1:1', 200),
            (('create', 'projects', 'cni', '127.0.0.1:1'), 'NET CREATE projects cni 127.0.0.1:1', 200),
            (('create', 'cbus', 'cni', '127.0.0.1:1'), 'NET CREATE cbus cni 127.0.0.1:1', 200),
            (('create', '!71000000-0000-4000-8000-000000000001', 'cni', '127.0.0.1:1'),
             'NET CREATE !71000000-0000-4000-8000-000000000001 cni 127.0.0.1:1', 200),
        )
        for arguments, command, status in cases:
            responses = [[b'[1] 200 OK.\r\n'], [f'[2] {status} fixture reply\r\n'.encode()]]
            with self.subTest(arguments=arguments), peer(responses) as (endpoint, sent):
                result = self.invoke(endpoint, 'network', 'definition', arguments[0], '--project', 'LAB', *arguments[1:])
            self.assertEqual(result['status'], status)
            self.assertEqual(sent, [b'[1] PROJECT USE LAB\r\n', f'[2] {command}\r\n'.encode()])

    def test_malformed_typed_arguments_refuse_before_connecting_to_the_selected_endpoint(self):
        cases = (('create', '--project', 'LAB', 'Owned', 'cni', 'x\nNOOP'),
                 ('create', '--project', 'LAB', 'Owned', 'cni', 'x', '--option', 'alpha="beta"'),
                 ('rename', '--project', 'LAB', 'Owned', 'Two Names'),
                 ('delete', '--project', 'LAB', '//OTHER/254'),
                 ('list', '--project', '../LAB'))
        for arguments in cases:
            with self.subTest(arguments=arguments), socket.socket() as trap:
                trap.bind(('127.0.0.1', 0)); trap.listen(1)
                result = self.invoke(trap.getsockname(), 'network', 'definition', *arguments, expected=1)
                self.assertIn('error', result)
                self.assertFalse(select.select([trap], [], [], .05)[0], 'Invalid input connected before refusal')

    def test_create_and_load_refusals_unknown_response_and_lost_reply_never_replay_or_claim_success(self):
        scenarios = [('create', [b'[2] 408 Operation failed: duplicate\r\n']),
                     ('create-queued', [b'[2] 202 pending\r\n']),
                     ('create-property', [b'[2] 300 unrelated property\r\n']),
                     ('create-malformed-oid', [b'[2] 301 OID=untrusted\r\n']),
                     ('create-wrong-301-envelope', [b'[2] 301 OID=71000000-0000-4000-8000-000000000001 extra\r\n']),
                     ('load-confirmation', [b'[3] 600 Confirmation required\r\n']),
                     ('load-missing', [b'[3] 408 Operation failed: Network definitions file not found\r\n']),
                     ('load-wrong-success', [b'[3] 201 unexpected response\r\n']),
                     ('load-lost', [])]
        for label, final in scenarios:
            responses = [[b'[1] 200 OK.\r\n']]
            if not label.startswith('create'):
                responses.append([b'[2] 200 OK.\r\n'])
            responses.append(final)
            with self.subTest(label=label), peer(responses) as (endpoint, sent):
                result = self.invoke(endpoint, 'database', 'network-new', 'LAB', 252, 'Owned', 'Cni', '127.0.0.1:1', expected=1)
            self.assertIn('error', result)
            self.assertNotIn('code', result)
            self.assertEqual(sent[:2], [b'[1] PROJECT USE LAB\r\n', b'[2] DBCREATENET 252 Owned Cni 127.0.0.1:1\r\n'])
            self.assertEqual(sent[2:], [] if label.startswith('create') else [b'[3] NET LOAD DB\r\n'])

    def test_definition_mutation_refuses_non200_and_retains_exact_project_scoped_sequence(self):
        for response in ([b'[2] 600 Confirmation required\r\n'], [b'[2] 201 unknown success\r\n'], []):
            with self.subTest(response=response), peer([[b'[1] 200 OK.\r\n'], response]) as (endpoint, sent):
                result = self.invoke(endpoint, 'network', 'definition', 'create', '--project', 'LAB',
                                     '252', 'cni', '127.0.0.1:1', '--option', 'auto-reconnect=true', expected=1)
            self.assertIn('error', result)
            self.assertEqual(sent, [b'[1] PROJECT USE LAB\r\n', b'[2] NET CREATE 252 cni 127.0.0.1:1 auto-reconnect=true\r\n'])


@unittest.skipUnless(os.environ.get('CBUS_CMQTTD_BIN'), 'Select CBUS_CMQTTD_BIN for owned public network catalogue acceptance')
class OwnedNetworkCatalogueCLITests(unittest.TestCase):
    def test_public_cli_network_new_and_definition_saved_closed_lifecycle_without_pci_io(self):
        from research.network_definition_cli_acceptance import main
        with tempfile.TemporaryDirectory(prefix='owned-network-cli-') as directory:
            target = Path(directory) / 'raw'
            arguments = ['--cmqttd-bin', os.environ['CBUS_CMQTTD_BIN'], '--python', sys.executable,
                         '--output-dir', str(target)]
            if os.environ.get('CBUS_TOOLKIT_ACCEPTANCE_WHEEL'):
                arguments += ['--wheel', os.environ['CBUS_TOOLKIT_ACCEPTANCE_WHEEL']]
            self.assertEqual(main(arguments), 0)
            receipt = json.loads((target / 'acceptance.json').read_text())
            self.assertEqual(receipt['result'], 'passed')
            self.assertTrue(receipt['completed'])
            self.assertTrue(receipt['saved_reopened_xml_equal'])
            self.assertTrue(receipt['daemon_pci_capture_unchanged'])
            self.assertEqual(receipt['cni_trap_connections'], 0)
            self.assertEqual(len(receipt['network_new_cases']), 3)
            for field in ('empty_db_and_missing_file_loads_are_noop', 'missing_file_nonempty_noop',
                          'db_load_idempotent_graph', 'legacy_custom_snapshot_restored',
                          'renamed_definition_retained', 'conflicting_numeric_runtime_refreshed_from_db',
                          'runtime_refresh_requires_explicit_db_load', 'deleted_db_row_preserves_active_runtime',
                          'stale_numeric_snapshot_not_resurrected', 'file_collision_atomic_refusal',
                          'explicit_project_selection_isolated', 'reserved_and_oid_get_dispatch_preserved'):
                self.assertTrue(receipt[field], field)
            self.assertEqual(len(receipt['generic_get_collision_checks']), 8)
            for check in receipt['generic_get_collision_checks']:
                self.assertEqual(check['before_exit'], check['after_exit'])
                self.assertTrue(check['full_response_equal'])
                self.assertTrue(check['stdout_bytes_equal'])
                self.assertTrue(check['stderr_bytes_equal'])
            self.assertFalse(receipt['native_process_launched'])
            self.assertTrue(receipt['backend']['process_cleanup_verified'])


if __name__ == '__main__':
    unittest.main()
