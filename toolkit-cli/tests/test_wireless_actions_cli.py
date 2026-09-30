"""Typed wireless-action CLI guards; every effectful dispatch uses a fake peer."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.cli import build_parser, main


CATALOGUE = b'''<CBusUnits><Units><Unit><CatalogNumber>5800WCGA</CatalogNumber>
<AlternativeCatalogNumbers>5800WCGC</AlternativeCatalogNumbers><FirmwareRevisions><Revision>
<UnitType>WGATE5F</UnitType><MinVersion>2.4.0</MinVersion><MaxVersion>2.4.99</MaxVersion>
<UnitSpecName>WGATE5X_2.xml</UnitSpecName><ClassName>WirelessCBusGateway</ClassName>
<IsDefault>true</IsDefault></Revision></FirmwareRevisions><InputCount>0</InputCount>
<OutputCount>0</OutputCount><GroupCount>0</GroupCount><IsAddressable>true</IsAddressable>
</Unit></Units></CBusUnits>'''

PROJECT = b'''<Project><Address>TEST</Address><TagName>Synthetic</TagName>
<Network><Address>254</Address><TagName>Local</TagName><Interface><InterfaceType>CNI</InterfaceType>
<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface><Unit><Address>20</Address>
<OID>12345678-1234-1234-1234-123456789012</OID><TagName>Gateway</TagName>
<UnitType>WGATE5F</UnitType><FirmwareVersion>2.4.00</FirmwareVersion><CatalogNumber>5800WCGA</CatalogNumber>
<SerialNumber>70179.836</SerialNumber></Unit></Network></Project>'''

OP_STATS = ('{PacketsReceived=1; PacketsReceivedWithError=2; PacketsNAKd=3; PacketsNCAd=4; '
            'CollisionsDetected=5; TransmitAttempts=6; TransmitCancellations=7; CollisionsDetectedinTAP=8; '
            'CollisionsNotifiedDetected=9; TransmissionsDropped=10; SuccessfulTransmissions=11; TransmissionsNAKd=12}')


def reply(code, *lines):
    return CGateResponse(tuple(lines), lines[-1], code)


class ActionPeer:
    """Closed fake command surface: no PP, NET, real sockets, retries or threads."""
    def __init__(self):
        self.commands = []
        self.timeout = 10
        self.project = PROJECT
        self.second_project = None
        self.project_reads = 0
        self.do_failure = None
        self.do_response = reply(202, '202 Done: //TEST/254/p/20')
        self.values = {
            'Type': 'WGATE5F', 'Version': '2.4.00', 'CatalogNumber': '5800WCGA',
            'SerialNumber': '70179.836',
            'UnitTemperature': 'unknown', 'UnitSupplyVoltage': '3300mv',
            'BackgroundSignalPower': '-95dBm', 'LastPacketReceivedPower': '-50dBm',
            'OpStats': OP_STATS,
            'ManufacturerCode': '1', 'ProductClass': '2', 'MediaType': '3',
            'ProcessSelector': '4', 'FeatureSet': '5',
        }

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def command(self, command):
        self.commands.append(command)
        if command == 'DBGETXML //TEST':
            self.project_reads += 1
            body = self.second_project if self.second_project is not None and self.project_reads > 1 else self.project
            return reply(344, *('347-' + line for line in body.decode().splitlines()), '344 End XML')
        if command.startswith('GET //TEST/254/p/20 '):
            field = command.split()[-1]
            if field not in self.values:
                raise AssertionError('Unexpected GET field: ' + field)
            return reply(300, f'300 //TEST/254/p/20: {field}={self.values[field]}')
        if command in ('DO //TEST/254/p/20 MAISync', 'DO //TEST/254/p/20 RecallOpStats',
                       'DO //TEST/254/p/20 ResetOpStats'):
            if self.do_failure is not None:
                raise self.do_failure
            return self.do_response
        raise AssertionError('Unexpected command: ' + command)


class WirelessActionsCliTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.project = self.folder / 'project.xml'
        self.project.write_bytes(PROJECT)
        self.catalogue = self.folder / 'catalogue.xml'
        self.catalogue.write_bytes(CATALOGUE)
        self.plan_file = self.folder / 'plan.json'

    def offline(self, operation='cached-status'):
        return ['wireless', 'action', 'plan', '--project-xml', str(self.project),
                '--catalogue-xml', str(self.catalogue), '--source-network', '254', '--unit-address', '20',
                '--operation', operation]

    def native(self, *, physical=False, dry_run=False, unit_options=(), cgate_options=()):
        return ['cgate', '--host', '127.0.0.1', '--port', '1', *map(str, cgate_options), 'unit',
                '--source', '//TEST/254/p/20', '--lock-address', '//TEST/254', *map(str, unit_options),
                *(['--dry-run'] if dry_run else []), 'wireless-action', '--plan', str(self.plan_file),
                *(['--allow-physical-action'] if physical else [])]

    def invoke(self, argv, expected=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(argv)
        self.assertEqual(status, expected, output.getvalue() + errors.getvalue())
        return json.loads(output.getvalue() or errors.getvalue())

    def make_plan(self, operation='cached-status'):
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline plan cannot connect')) as connect:
            document = self.invoke(self.offline(operation))
        connect.assert_not_called()
        self.plan_file.write_text(json.dumps(document))
        return document

    def apply(self, peer, arguments=None, expected=0):
        def connect(*_args, **kwargs):
            peer.timeout = kwargs['timeout']
            return peer
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=connect), \
                patch('cbus_toolkit.programming.Programmer', side_effect=AssertionError('Actions must not use PP')):
            return self.invoke(arguments or self.native(), expected)

    def test_offline_all_five_operation_plans_and_native_parser(self):
        for operation in ('cached-status', 'cached-op-stats', 'mai-sync', 'recall-op-stats', 'reset-op-stats'):
            with self.subTest(operation=operation):
                document = self.make_plan(operation)
                self.assertEqual(document['operation'], operation)
                parsed = build_parser().parse_args(self.native(physical=True))
                self.assertEqual(parsed.remote_action, 'wireless-action')
                self.assertEqual(parsed.wireless_action_plan, self.plan_file)
                self.assertTrue(parsed.allow_physical_action)

    def test_offline_required_inputs_and_unknown_operation_are_usage_errors(self):
        for option in ('--project-xml', '--catalogue-xml', '--source-network', '--unit-address', '--operation'):
            args = self.offline()
            index = args.index(option)
            del args[index:index + 2]
            with self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                main(args)
            self.assertEqual(failure.exception.code, 2)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            main(self.offline('psync'))
        self.assertEqual(failure.exception.code, 2)

    def test_invalid_plan_documents_stop_before_client_construction(self):
        for contents in (None, '{bad JSON', 'null', '[]', '{}', '{"format":"unknown"}'):
            if contents is None:
                self.plan_file.unlink(missing_ok=True)
            else:
                self.plan_file.write_text(contents)
            with self.subTest(contents=contents), redirect_stderr(io.StringIO()), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No connection allowed')) as connect, \
                    self.assertRaises(SystemExit) as failure:
                main(self.native())
            self.assertEqual(failure.exception.code, 2)
            connect.assert_not_called()

    def test_valid_plan_unsafe_targets_stop_before_client_construction(self):
        self.make_plan()
        new_unit = self.native(unit_options=('--firmware', '2.4.00'))
        index = new_unit.index('--source')
        new_unit[index:index + 2] = ['--unit-type', 'WGATE5F']
        cases = {
            'database source': self.native(unit_options=('--source', '/db//TEST/254/p/20')),
            'other unit': self.native(unit_options=('--source', '//TEST/254/p/21')),
            'other network': self.native(unit_options=('--source', '//TEST/123/p/20')),
            'other project': self.native(unit_options=('--source', '//OTHER/254/p/20')),
            'wrong lock': self.native(unit_options=('--lock-address', '//TEST/123')),
            'destination': self.native(unit_options=('--destination', '//TEST/254/p/20')),
            'database destination': self.native(unit_options=('--destination', '/db//TEST/254/p/20')),
            'new unit': new_unit,
        }
        for label, args in cases.items():
            with self.subTest(case=label), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No connection allowed')) as connect:
                self.assertTrue(self.invoke(args, 1)['error'])
            connect.assert_not_called()

    def test_forged_plan_facts_and_snapshots_are_usage_errors_before_connection(self):
        original = self.make_plan('reset-op-stats')
        mutations = (
            ('source', '//TEST/254/p/21'), ('source_network', 123), ('unit_address', 21),
            ('operation', 'cached-status'), ('physical_action', False),
            ('original_timeout_ms', None), ('hardware_verified', True), ('implicit_refresh', True),
        )
        documents = []
        for key, value in mutations:
            document = deepcopy(original)
            document[key] = value
            documents.append((key, document))
        for key in ('project', 'catalogue'):
            document = deepcopy(original)
            document[key]['xml'] += '\n<!-- changed after planning -->'
            documents.append((key, document))
        document = deepcopy(original)
        document['target']['serial_number'] = '1.2'
        documents.append(('target serial', document))
        for label, document in documents:
            self.plan_file.write_text(json.dumps(document))
            with self.subTest(forged=label), redirect_stderr(io.StringIO()), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No connection allowed')) as connect, \
                    self.assertRaises(SystemExit) as failure:
                main(self.native(physical=True))
            self.assertEqual(failure.exception.code, 2)
            connect.assert_not_called()

    def test_unsupported_or_unbound_offline_identity_cannot_be_planned(self):
        cases = (
            PROJECT.replace(b'WGATE5F', b'WGATE5N'),
            PROJECT.replace(b'2.4.00', b'2.5.00'),
            PROJECT.replace(b'70179.836', b'unknown'),
            PROJECT.replace(b'12345678-1234-1234-1234-123456789012', b'unknown'),
        )
        for project in cases:
            self.project.write_bytes(project)
            with self.subTest(project=project), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No connection allowed')) as connect:
                self.assertTrue(self.invoke(self.offline(), 1)['error'])
            connect.assert_not_called()

    def test_effectful_opt_in_and_minimum_timeout_refused_before_connection(self):
        for operation in ('mai-sync', 'recall-op-stats', 'reset-op-stats'):
            self.make_plan(operation)
            cases = [self.native()]
            if operation != 'mai-sync':
                cases.append(self.native(physical=True, cgate_options=('--timeout', '7.99')))
            for arguments in cases:
                with self.subTest(operation=operation, arguments=arguments), \
                        patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No connection allowed')) as connect:
                    self.assertTrue(self.invoke(arguments, 1)['error'])
                connect.assert_not_called()

    def test_nonpositive_or_nonfinite_timeout_refuses_before_connection(self):
        self.make_plan()
        for timeout in ('0', '-1', 'nan', 'inf'):
            with self.subTest(timeout=timeout), redirect_stderr(io.StringIO()), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No connection allowed')) as connect, \
                    self.assertRaises(SystemExit) as failure:
                main(self.native(cgate_options=('--timeout', timeout)))
            self.assertEqual(failure.exception.code, 2)
            connect.assert_not_called()

    def test_effectful_dry_run_needs_no_opt_in_and_only_checks_database_and_cached_identity(self):
        self.make_plan('reset-op-stats')
        peer = ActionPeer()
        result = self.apply(peer, self.native(dry_run=True, cgate_options=('--timeout', '0.5')))
        self.assertEqual(peer.commands, ['DBGETXML //TEST', 'GET //TEST/254/p/20 Type',
                                         'GET //TEST/254/p/20 Version', 'GET //TEST/254/p/20 CatalogNumber',
                                         'GET //TEST/254/p/20 SerialNumber',
                                         'DBGETXML //TEST'])
        self.assertEqual(result['status'], 'verified-preview')
        self.assertFalse(result['command_attempted'])
        self.assertFalse(result['send_completed'])

    def test_cached_status_gets_all_four_native_fields_without_do_or_pp(self):
        self.make_plan()
        peer = ActionPeer()
        result = self.apply(peer)
        self.assertEqual([command for command in peer.commands if command.startswith('GET ')], [
            'GET //TEST/254/p/20 Type', 'GET //TEST/254/p/20 Version', 'GET //TEST/254/p/20 CatalogNumber',
            'GET //TEST/254/p/20 SerialNumber',
            'GET //TEST/254/p/20 UnitTemperature', 'GET //TEST/254/p/20 UnitSupplyVoltage',
            'GET //TEST/254/p/20 BackgroundSignalPower', 'GET //TEST/254/p/20 LastPacketReceivedPower',
        ])
        self.assertEqual(peer.commands.count('DBGETXML //TEST'), 2)
        self.assertFalse(any(command.startswith(('DO ', 'PP ', 'NET ', 'PROJECT ')) for command in peer.commands))
        self.assertTrue(result['cached_only'])
        self.assertTrue(result['cache_unknown'])
        self.assertFalse(result['fresh_recall'])
        self.assertFalse(result['hardware_verified'])
        self.assertFalse(result['physical_identity_verified'])
        self.assertFalse(result['implicit_refresh'])

    def test_cached_op_stats_reads_without_recall(self):
        self.make_plan('cached-op-stats')
        peer = ActionPeer()
        self.apply(peer)
        self.assertEqual([command for command in peer.commands if 'OpStats' in command],
                         ['GET //TEST/254/p/20 OpStats'])
        self.assertFalse(any(command.startswith(('DO ', 'PP ', 'NET ', 'PROJECT ')) for command in peer.commands))

    def test_each_explicit_action_dispatches_one_do_and_accepts_exact_202_done(self):
        for operation, native in (('mai-sync', 'MAISync'), ('recall-op-stats', 'RecallOpStats'),
                                   ('reset-op-stats', 'ResetOpStats')):
            self.make_plan(operation)
            peer = ActionPeer()
            with self.subTest(operation=operation):
                result = self.apply(peer, self.native(physical=True))
            self.assertEqual([command for command in peer.commands if command.startswith('DO ')],
                             [f'DO //TEST/254/p/20 {native}'])
            self.assertFalse(any(command.startswith(('PP ', 'NET ', 'PROJECT ')) for command in peer.commands))
            self.assertTrue(result['command_attempted'])
            self.assertTrue(result['send_completed'])
            self.assertFalse(result['uncertain_send'])
            self.assertFalse(result['hardware_verified'])
            self.assertFalse(result['physical_transmissions_verified'])
            self.assertFalse(result['database_save_performed'])
            if operation == 'reset-op-stats':
                self.assertFalse(result['cache_invalidated'])
                self.assertFalse(result['reset_effect_verified'])

    def test_exact_recall_reset_timeout_and_short_mai_timeout_are_admitted(self):
        for operation, timeout in (('recall-op-stats', '8'), ('reset-op-stats', '8'), ('mai-sync', '0.5')):
            self.make_plan(operation)
            peer = ActionPeer()
            with self.subTest(operation=operation, timeout=timeout):
                result = self.apply(peer, self.native(physical=True, cgate_options=('--timeout', timeout)))
            self.assertEqual(result['client_timeout_seconds'], float(timeout))
            self.assertEqual(sum(command.startswith('DO ') for command in peer.commands), 1)

    def test_empty_cached_statistics_are_unknown_but_empty_after_recall_is_failure(self):
        self.make_plan('cached-op-stats')
        peer = ActionPeer()
        peer.values['OpStats'] = '{}'
        cached = self.apply(peer)
        self.assertIsNone(cached['values'])
        self.assertTrue(cached['cache_unknown'])
        self.assertFalse(cached['fresh_recall'])
        self.assertFalse(any(command.startswith('DO ') for command in peer.commands))

        self.make_plan('recall-op-stats')
        peer = ActionPeer()
        peer.values['OpStats'] = '{}'
        result = self.apply(peer, self.native(physical=True), 1)
        evidence = result['wireless_action_evidence']
        self.assertTrue(evidence['send_completed'])
        self.assertFalse(evidence['uncertain_send'])
        self.assertFalse(evidence['retry_performed'])
        self.assertEqual(peer.commands[-2:], ['DO //TEST/254/p/20 RecallOpStats', 'GET //TEST/254/p/20 OpStats'])
        self.assertEqual(sum(command.startswith('DO ') for command in peer.commands), 1)

    def test_uncertain_do_failure_has_one_attempt_and_no_automatic_retry(self):
        self.make_plan('reset-op-stats')
        peer = ActionPeer()
        peer.do_failure = OSError('Simulated lost DO reply')
        result = self.apply(peer, self.native(physical=True), 1)
        self.assertIn('wireless_action_evidence', result)
        self.assertEqual([command for command in peer.commands if command.startswith('DO ')],
                         ['DO //TEST/254/p/20 ResetOpStats'])
        self.assertEqual(peer.commands[-1], 'DO //TEST/254/p/20 ResetOpStats')
        evidence = result['wireless_action_evidence']
        self.assertTrue(evidence['command_attempted'])
        self.assertTrue(evidence['uncertain_send'])
        self.assertFalse(evidence['send_completed'])
        self.assertFalse(evidence['retry_performed'])
        self.assertFalse(evidence['cli_replay_performed'])

    def test_wrong_do_completion_code_text_or_target_is_not_success_or_retried(self):
        self.make_plan('recall-op-stats')
        replies = [reply(200, '200 Done: //TEST/254/p/20'), reply(202, '202 Done: //TEST/254/p/21'),
                   reply(202, '202 OK: //TEST/254/p/20'), reply(408, '408 Operation failed')]
        for response in replies:
            peer = ActionPeer()
            peer.do_response = response
            with self.subTest(response=response.final):
                self.apply(peer, self.native(physical=True), 1)
            self.assertEqual([command for command in peer.commands if command.startswith('DO ')],
                             ['DO //TEST/254/p/20 RecallOpStats'])

    def test_database_or_runtime_identity_drift_refuses_before_do(self):
        self.make_plan('mai-sync')
        peers = []
        changed_database = ActionPeer()
        changed_database.project = PROJECT.replace(b'70179.836', b'1.2')
        peers.append(changed_database)
        changed_runtime = ActionPeer()
        changed_runtime.values['Type'] = 'DIMDN4'
        peers.append(changed_runtime)
        changed_runtime_serial = ActionPeer()
        changed_runtime_serial.values['SerialNumber'] = '1.2'
        peers.append(changed_runtime_serial)
        changed_during_guard = ActionPeer()
        changed_during_guard.second_project = PROJECT.replace(b'70179.836', b'1.2')
        peers.append(changed_during_guard)
        for peer in peers:
            with self.subTest(values=peer.values, second_project=peer.second_project):
                self.apply(peer, self.native(physical=True), 1)
            self.assertFalse(any(command.startswith(('DO ', 'PP ', 'NET ', 'PROJECT ')) for command in peer.commands))

    def test_plan_file_replacement_after_preflight_does_not_reinterpret_operation(self):
        self.make_plan('reset-op-stats')
        replacement = self.plan_file.read_text()
        original = self.make_plan('cached-status')
        peer = ActionPeer()

        def connect(*_args, **kwargs):
            peer.timeout = kwargs['timeout']
            self.plan_file.write_text(replacement)
            return peer

        with patch('cbus_toolkit.cgate.CGateClient', side_effect=connect), \
                patch('cbus_toolkit.programming.Programmer', side_effect=AssertionError('No PP allowed')):
            self.invoke(self.native())
        self.assertEqual(original['operation'], 'cached-status')
        self.assertIn('GET //TEST/254/p/20 UnitSupplyVoltage', peer.commands)
        self.assertFalse(any(command.startswith('DO ') for command in peer.commands))

    def test_existing_offline_boundary_remains_available_without_catalogue_or_client(self):
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
            result = self.invoke(['wireless', 'boundary', '--unit', '20'])
        connect.assert_not_called()
        self.assertFalse(result['io_performed'])
        self.assertEqual(result['unit_actions']['ResetOpStats']['commands'], ['\\46140008'])


if __name__ == '__main__':
    unittest.main()
