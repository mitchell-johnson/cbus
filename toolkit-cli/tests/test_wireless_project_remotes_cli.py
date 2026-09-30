"""Project remote CLI routing: frozen inputs, database-only writes, and no PP."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit.cli import main
from cbus_toolkit.wireless_project_remotes import RemoteCreationPlan
from test_wireless_project_remotes import CATALOGUE, DatabasePeer, plan, project, unit


class CliDatabasePeer(DatabasePeer):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class WirelessProjectRemotesCliTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.project_file = self.folder / 'project.xml'
        self.project_file.write_bytes(project())
        self.catalogue_file = self.folder / 'catalogue.xml'
        self.catalogue_file.write_bytes(CATALOGUE)
        self.selected = plan()
        self.plan_file = self.folder / 'plan.json'
        self.plan_file.write_text(json.dumps(self.selected.as_dict()))

    def offline(self, *options):
        return ['wireless', 'project-remote', 'plan', '--project-xml', str(self.project_file),
                '--catalogue-xml', str(self.catalogue_file), '--source-network', '254', '--gateway-address', '200',
                '--serial', '70179.836', *map(str, options)]

    def native(self, *options, unit_options=(), exclusive=True):
        return ['cgate', '--host', '127.0.0.1', '--port', '1', 'unit', '--lock-address', '//TEST/254',
                '--source', '/db//TEST/254/p/200', *map(str, unit_options), 'wireless-gateway',
                '--plan', str(self.plan_file), *(['--exclusive-project'] if exclusive else []), *map(str, options)]

    def invoke(self, arguments, expected=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(arguments)
        self.assertEqual(status, expected, output.getvalue() + errors.getvalue())
        return json.loads(output.getvalue() or errors.getvalue())

    def assert_before_client_refusal(self, arguments):
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No client construction')) as connect:
            result = self.invoke(arguments, expected=1)
        self.assertTrue(result['error'])
        connect.assert_not_called()
        return result

    def test_offline_plan_uses_literal_catalogue_and_first_free_metadata_identity(self):
        self.project_file.write_bytes(project(unit(100, 'Remote 01'), unit(102, 'Remote 03')))
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No client construction')) as connect, \
                patch('cbus_toolkit.programming.Programmer', side_effect=AssertionError('No PP')) as programmer:
            result = self.invoke(self.offline())
        connect.assert_not_called()
        programmer.assert_not_called()
        self.assertEqual(result['format'], 'cbus-wireless-project-remote-plan-v1')
        self.assertEqual((result['created_address'], result['tag_name'], result['serial']), (101, 'Remote 02', '70179.836'))
        self.assertEqual(result['project_save_stages'], ['constructor', 'database_agent', 'creation_caller'])
        self.assertEqual(result['constructor_fields'], {'UnitType': 'WTXU', 'FirmwareVersion': '0', 'UnitName': 'REMOTE'})
        self.assertFalse(result['pp_initialized'])
        self.assertFalse(result['gateway_mappings_changed'])
        self.assertFalse(result['physical_pairing_verified'])
        self.assertEqual(RemoteCreationPlan.from_dict(result).as_dict(), result)

    def test_offline_invalid_serial_profile_or_catalogue_never_connects(self):
        for arguments in (self.offline('--serial', '0.0'), self.offline('--serial', '1234'),
                          self.offline('--gateway-address', '123'), self.offline('--source-network', '123')):
            with self.subTest(arguments=arguments[-2:]):
                self.assert_before_client_refusal(arguments)
        self.project_file.write_bytes(project().replace(b'WGATE5F', b'WGATE5N'))
        self.assert_before_client_refusal(self.offline())
        self.project_file.write_bytes(project())
        self.catalogue_file.write_bytes(CATALOGUE.replace(b'5888TXBA', b'OTHER'))
        self.assert_before_client_refusal(self.offline())

    def test_native_target_ownership_and_mixed_edits_fail_before_client(self):
        temporary = self.native(unit_options=('--firmware', '0'))
        index = temporary.index('--source')
        temporary[index:index + 2] = ['--unit-type', 'WTXU']
        cases = {
            'physical source and database destination': self.native(unit_options=(
                '--source', '//TEST/254/p/200', '--destination', '/db//TEST/254/p/200')),
            'physical source': self.native(unit_options=('--source', '//TEST/254/p/200')),
            'database destination': self.native(unit_options=('--destination', '/db//TEST/254/p/200')),
            'wrong project': self.native(unit_options=('--source', '/db//OTHER/254/p/200')),
            'wrong gateway': self.native(unit_options=('--source', '/db//TEST/254/p/201')),
            'wrong source network': self.native(unit_options=('--source', '/db//TEST/123/p/200')),
            'wrong lock network': self.native(unit_options=('--lock-address', '//TEST/123')),
            'unit lock': self.native(unit_options=('--lock-address', '//TEST/254/p/200')),
            'no exclusive ownership': self.native(exclusive=False),
            'temporary unit': temporary,
            'show': self.native('--show'),
            'mode': self.native('--mode', 'remote-switch'),
            'remote mapping': self.native('--remote', '1'),
            'remote serial': self.native('--serial', '3'),
            'remote key': self.native('--remote-key', '1=group:7'),
            'raw remote slot': self.native('--remote-slot', '1=group:7'),
        }
        for label, arguments in cases.items():
            with self.subTest(case=label):
                self.assert_before_client_refusal(arguments)

    def test_malformed_or_forged_remote_plan_is_rejected_before_client(self):
        valid = self.selected.as_dict()
        wrong_address, wrong_serial, wrong_source, wrong_catalogue = (deepcopy(valid) for _ in range(4))
        wrong_address['created_address'] = 0
        wrong_serial['serial'] = '0.0'
        wrong_source['project']['xml'] = wrong_source['project']['xml'].replace('keep', 'changed')
        wrong_catalogue['catalogue']['profile']['unit_type'] = 'WGATE5N'
        cases = [('missing', None), ('malformed JSON', '{broken'), ('null', 'null'), ('list', '[]'),
                 ('unknown format', '{"format":"unknown"}'), ('empty map', '{}')]
        cases += [(name, json.dumps(document)) for name, document in (
            ('forged address', wrong_address), ('unknown serial', wrong_serial),
            ('tampered source', wrong_source), ('catalogue profile', wrong_catalogue))]
        for label, contents in cases:
            if contents is None:
                self.plan_file.unlink()
            else:
                self.plan_file.write_text(contents)
            with self.subTest(case=label), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No client construction')) as connect, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(self.native())
            self.assertEqual(error.exception.code, 2)
            connect.assert_not_called()

    def test_valid_preview_and_apply_bypass_programming_and_unitspec(self):
        for dry_run in (True, False):
            peer = CliDatabasePeer()
            expected = {'format': 'literal-preview' if dry_run else 'literal-apply', 'saved': not dry_run,
                        'pp_initialized': False, 'gateway_mappings_changed': False}
            with self.subTest(dry_run=dry_run), \
                    patch('cbus_toolkit.cgate.CGateClient', return_value=peer) as connect, \
                    patch('cbus_toolkit.programming.Programmer', side_effect=AssertionError('No PP')) as programmer, \
                    patch('cbus_toolkit.cli._programming', side_effect=AssertionError('No unit programming')) as programming, \
                    patch('cbus_toolkit.wireless_cli.gateway_editor', side_effect=AssertionError('No unit specification')) as editor, \
                    patch('cbus_toolkit.wireless_project_remotes.preview_project_remote', return_value=expected) as preview, \
                    patch('cbus_toolkit.wireless_project_remotes.apply_project_remote', return_value=expected) as apply:
                result = self.invoke(self.native(unit_options=('--dry-run',) if dry_run else ()))
            self.assertEqual(result, expected)
            connect.assert_called_once()
            called, uncalled = (preview, apply) if dry_run else (apply, preview)
            called.assert_called_once()
            self.assertIs(called.call_args.args[0], peer)
            self.assertEqual(called.call_args.args[1].as_dict(), self.selected.as_dict())
            self.assertEqual(called.call_args.kwargs, {'exclusive_project': True})
            uncalled.assert_not_called()
            programmer.assert_not_called()
            programming.assert_not_called()
            editor.assert_not_called()
            self.assertEqual(peer.commands, [])

    def test_real_mock_database_apply_preserves_other_units_and_emits_no_pp(self):
        peer = CliDatabasePeer()
        other_network = ET.tostring(peer.root.findall('Network')[1])
        with patch('cbus_toolkit.cgate.CGateClient', return_value=peer), \
                patch('cbus_toolkit.programming.Programmer', side_effect=AssertionError('No PP')), \
                patch('cbus_toolkit.cli._programming', side_effect=AssertionError('No unit programming')), \
                patch('cbus_toolkit.wireless_project_remotes._closed'):
            result = self.invoke(self.native())
        self.assertTrue(result['saved'])
        self.assertTrue(result['preserved_existing_project'])
        self.assertEqual(result['created_path'], '//TEST/254/p/100')
        self.assertEqual([row['stage'] for row in result['project_save_attempts']],
                         ['constructor', 'database_agent', 'creation_caller'])
        self.assertEqual(ET.tostring(peer.root.findall('Network')[1]), other_network)
        self.assertFalse(any(command.startswith(('PP ', 'NET ', 'DBDELETE')) for command in peer.commands))
        writes = [command for command in peer.commands if command.startswith('DBSETSAFE ')]
        self.assertTrue(all(command.split()[1].startswith('//TEST/254/p/100/') for command in writes))

    def test_valid_plan_is_frozen_before_client_construction_and_never_reloaded(self):
        for replacement in ('null', '{broken', json.dumps(plan(serial='42.8').as_dict())):
            self.plan_file.write_text(json.dumps(self.selected.as_dict()))
            peer = CliDatabasePeer()

            def connect(*args, **kwargs):
                self.plan_file.write_text(replacement)
                return peer

            with self.subTest(replacement=replacement[:30]), patch('cbus_toolkit.cgate.CGateClient', side_effect=connect), \
                    patch('cbus_toolkit.programming.Programmer', side_effect=AssertionError('No PP')), \
                    patch('cbus_toolkit.cli._programming', side_effect=AssertionError('No unit programming')), \
                    patch('cbus_toolkit.wireless_project_remotes._closed'):
                result = self.invoke(self.native())
            self.assertTrue(result['saved'])
            self.assertEqual(peer.root.findall('Network')[0].findall('Unit')[-1].findtext('SerialNumber'), '70179.836')
            self.assertFalse(any(command.startswith('PP ') for command in peer.commands))

    def test_stale_project_and_uncertain_save_preserve_error_receipts_without_pp(self):
        for peer, phrase in ((CliDatabasePeer(project().replace(b'keep', b'changed')), 'changed since'),
                             (CliDatabasePeer(fail_save=2), 'do not replay')):
            with self.subTest(phrase=phrase), patch('cbus_toolkit.cgate.CGateClient', return_value=peer), \
                    patch('cbus_toolkit.programming.Programmer', side_effect=AssertionError('No PP')), \
                    patch('cbus_toolkit.cli._programming', side_effect=AssertionError('No unit programming')), \
                    patch('cbus_toolkit.wireless_project_remotes._closed'):
                result = self.invoke(self.native(), expected=1)
            self.assertIn(phrase, result['error'])
            self.assertFalse(any(command.startswith(('PP ', 'NET ', 'DBDELETE')) for command in peer.commands))
            if peer.fail_save:
                evidence = result['remote_creation_evidence']
                self.assertFalse(evidence['saved'])
                self.assertTrue(evidence['uncertain_save'])
                self.assertFalse(evidence['retry_performed'])
                self.assertFalse(evidence['rollback_performed'])
                self.assertEqual(len(evidence['project_save_attempts']), 2)
                self.assertEqual(peer.commands[-1], 'PROJECT SAVE TEST')
            else:
                self.assertEqual(peer.commands, ['DBGETXML //TEST'])

    def test_other_unit_commands_still_use_existing_programming_dispatch(self):
        peer, marker = CliDatabasePeer(), {'format': 'unchanged-unit-show'}
        arguments = ['cgate', '--host', '127.0.0.1', '--port', '1', 'unit', '--lock-address', '//TEST/254',
                     '--source', '/db//TEST/254/p/200', 'show']
        with patch('cbus_toolkit.cgate.CGateClient', return_value=peer), \
                patch('cbus_toolkit.cli._programming', return_value=marker) as programming, \
                patch('cbus_toolkit.wireless_cli.project_remote_native', side_effect=AssertionError('No remote creation')) as remote:
            self.assertEqual(self.invoke(arguments), marker)
        programming.assert_called_once()
        self.assertIs(programming.call_args.args[1], peer)
        self.assertEqual(programming.call_args.args[0].remote_action, 'show')
        remote.assert_not_called()


if __name__ == '__main__':
    unittest.main()
