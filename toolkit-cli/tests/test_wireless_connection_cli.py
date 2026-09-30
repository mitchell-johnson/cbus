"""Connection CLI boundaries with literal project data and no socket I/O."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateResponse
from cbus_toolkit.cli import build_parser, main
from cbus_toolkit.programming import xml_text
from cbus_toolkit.wireless_cli import preflight
from cbus_toolkit.wireless_connection import FrozenTopology, WirelessConnectionEditor, WirelessConnectionError
from cbus_toolkit.wireless_gateway import WirelessGatewayEditor
from test_wireless_connection import ConnectionSession, fixture, network, source, unit, xml


def write_spec(folder, spec):
    root = ET.Element('UnitSpecification')
    ET.SubElement(root, 'Type').text = spec.metadata['Type']
    parameters = ET.SubElement(root, 'Parameters')
    for parameter in spec.parameters.values():
        node = ET.SubElement(parameters, 'Param')
        for key, value in parameter.fields.items():
            ET.SubElement(node, key).text = value
    ET.ElementTree(root).write(folder / spec.filename, encoding='utf-8', xml_declaration=True)


def response(*lines):
    return CGateResponse(tuple(lines), lines[-1], int(lines[-1][:3]))


class MockSession(ConnectionSession):
    def __init__(self):
        super().__init__()
        self.saves = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def save_to_source(self):
        self.saves.append(self.source)
        return response('200 Saved')


class ClosedClient:
    """The complete mocked wire surface is one XML read and closed-state GETs."""
    def __init__(self):
        self.commands, self.loads = [], []
        self.document = xml()
        self.open_network = None
        self.session = MockSession()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def command(self, command):
        self.commands.append(command)
        if command == 'DBGETXML //P':
            return response('347-' + self.document.decode(), '344 End XML')
        if command in ('GET //P/99 *', 'GET //P/123 *', 'GET //P/200 *', 'GET //P/254 *'):
            path = command.split()[1]
            values = {
                'Name': 'Synthetic', 'Type': 'Cni', 'InterfaceAddress': '127.0.0.1:1',
                'NetworkType': 'CBus', 'InterfaceState': 'closed', 'TargetInterfaceState': 'closed',
                'SyncState': 'idle', 'State': 'error', 'Options': '', 'AutoSync': 'no',
                'AutoUnravel': 'no', 'AutoUpdate': 'no', 'DefaultApplication': '56',
                'EventLevel': '255', 'FastResponse': 'no', 'QuickDetect': 'no',
                'ResponseDelay': '0', 'Retries': '0', 'ShortSync': 'no', 'SyncTime': '0', 'TxEnable': 'no',
            }
            if path == self.open_network:
                values['TargetInterfaceState'] = 'open'
            rows = [f'300-{path}: {key}={value}' for key, value in values.items()]
            rows[-1] = rows[-1].replace('300-', '300 ', 1)
            return response(*rows)
        raise AssertionError('Unexpected mock command: ' + command)


class MockProgrammer:
    def __init__(self, client):
        self.client = client

    def load(self, lock_address, source):
        self.client.loads.append((lock_address, source))
        session = self.client.session
        session.lock_address, session.source, session.programmer = lock_address, source, self
        return session


class WirelessConnectionCliTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.spec = fixture()
        write_spec(self.folder, self.spec)
        self.snapshot = self.folder / 'snapshot.json'
        self.snapshot.write_text(json.dumps({
            'format': 'cbus-cli-parameters-v1', 'unit_type': 'WGATE5F', 'firmware': '2.4.00',
            'catalog_number': None, 'parameters': self.spec.defaults(),
        }))
        self.project = self.folder / 'project.xml'
        self.project.write_bytes(xml())
        self.plan = WirelessConnectionEditor(self.spec).plan(
            self.spec.defaults(), topology=FrozenTopology.from_xml(xml()), source_network=254,
            unit_address=200, identity=('WGATE5F', '2.4.00', None), application2=202,
            destination_network=99)
        self.plan_file = self.folder / 'plan.json'
        self.plan_file.write_text(json.dumps(self.plan.as_dict()))

    def offline(self, action, *options):
        return ['wireless', '--spec-dir', str(self.folder), 'connection', action, str(self.snapshot),
                '--project-xml', str(self.project), '--source-network', '254', '--gateway-address', '200',
                *map(str, options)]

    def native(self, *options, unit_options=(), exclusive=True):
        return ['cgate', '--host', '127.0.0.1', '--port', '1', 'unit', '--lock-address', '//P/254',
                '--source', '/db//P/254/p/200', *map(str, unit_options), 'wireless-gateway',
                '--spec-dir', str(self.folder), '--plan', str(self.plan_file),
                *(['--exclusive-project'] if exclusive else []), *map(str, options)]

    def invoke(self, argv, expected=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(argv)
        self.assertEqual(status, expected, output.getvalue() + errors.getvalue())
        return json.loads(output.getvalue() or errors.getvalue())

    def mocked_native(self, client, argv, expected=0):
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client), \
                patch('cbus_toolkit.programming.Programmer', MockProgrammer):
            return self.invoke(argv, expected)

    def test_offline_show_and_plan_map_all_connection_flags(self):
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
            view = self.invoke(self.offline('show'))
            plan = self.invoke(self.offline(
                'plan', '--application1', '0x38', '--application2', '202', '--adjacent-network', 'on',
                '--synchronise-to-wired', 'on', '--destination-network', '0x63',
                '--status-monitor-application', '57'))
            connect.assert_not_called()
        self.assertEqual(view['format'], 'cbus-wireless-connection-v1')
        self.assertEqual(view['remote_destinations'], [99, 123])
        self.assertTrue(view['application2_enabled'])
        self.assertFalse(view['synchronise_to_wired_enabled'])
        self.assertEqual(plan['format'], 'cbus-wireless-connection-plan-v1')
        self.assertEqual(plan['changes'], {
            'Application': [56, 202], 'ApplicationConnectEnabled': [1], 'SynchroniseToWired': [1],
            'ForwardingMode': [1], 'ForwardingRoute': [27, 123, 99, 255, 255, 255, 255],
            'StatusMonitorApplication': [57],
        })
        self.assertEqual(plan['options'], {'application1': 56, 'application2': 202,
                                           'adjacent_network': True, 'synchronise_to_wired': True,
                                           'destination_network': 99, 'status_monitor_application': 57})
        for field in ('saved', 'device_verified', 'original_toolkit_executed', 'physical_forwarding_verified'):
            self.assertFalse(plan[field])

    def test_offline_none_and_off_options_differ_from_omission(self):
        snapshot = json.loads(self.snapshot.read_text())
        snapshot['parameters'].update(ApplicationConnectEnabled='1', SynchroniseToWired='1',
                                      ForwardingMode='1', ForwardingRoute='27 123 99 255 255 255 255')
        self.snapshot.write_text(json.dumps(snapshot))
        untouched = self.invoke(self.offline('plan'))
        clear = self.invoke(self.offline('plan', '--destination-network', 'NoNe', '--adjacent-network', 'off'))
        self.assertEqual(untouched['changes'], {})
        self.assertEqual(untouched['options'], {})
        self.assertEqual(clear['changes'], {'ApplicationConnectEnabled': [0], 'SynchroniseToWired': [0],
                                           'ForwardingMode': [0], 'ForwardingRoute': [255] * 7})
        self.assertEqual(clear['options'], {'adjacent_network': False, 'destination_network': None})

    def test_offline_requires_complete_topology_selection(self):
        for option in ('--project-xml', '--source-network', '--gateway-address'):
            arguments = self.offline('plan')
            index = arguments.index(option)
            del arguments[index:index + 2]
            with self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(arguments)
            self.assertEqual(error.exception.code, 2)

    def test_offline_invalid_dependency_profile_and_identity_are_json_refusals(self):
        for flags in (('--adjacent-network', 'off', '--synchronise-to-wired', 'on'),
                      ('--application2', '88'), ('--unit-type', 'WGATE5N')):
            with self.subTest(flags=flags):
                refusal = self.invoke(self.offline('plan', *flags), 1)
                self.assertTrue(refusal['error'])
        snapshot = json.loads(self.snapshot.read_text())
        snapshot['unit_type'] = 'WGATE5N'
        self.snapshot.write_text(json.dumps(snapshot))
        self.assertIn('identity', self.invoke(self.offline('show'), 1)['error'].lower())

    def test_native_parser_recognizes_connection_plan_and_exclusive_project(self):
        parsed = build_parser().parse_args(self.native())
        self.assertEqual(parsed.wireless_plan, self.plan_file)
        self.assertTrue(parsed.exclusive_project)
        self.assertEqual(parsed.remote_action, 'wireless-gateway')

    def test_valid_connection_plan_command_mismatches_fail_before_client_construction(self):
        temporary_unit = self.native(unit_options=('--firmware', '2.4.00'))
        source_index = temporary_unit.index('--source')
        temporary_unit[source_index:source_index + 2] = ['--unit-type', 'WGATE5F']
        cases = {
            'physical source plus database destination': self.native(unit_options=(
                '--source', '//P/254/p/200', '--destination', '/db//P/254/p/200')),
            'physical source': self.native(unit_options=('--source', '//P/254/p/200')),
            'wrong source project': self.native(unit_options=('--source', '/db//OTHER/254/p/200')),
            'wrong source unit': self.native(unit_options=('--source', '/db//P/254/p/199')),
            'wrong lock': self.native(unit_options=('--lock-address', '//P/123')),
            'missing ownership': self.native(exclusive=False),
            'temporary unit': temporary_unit,
            'show': self.native('--show'),
            'mode edit': self.native('--mode', 'network-gateway'),
            'remote edit': self.native('--remote', '1'),
            'serial edit': self.native('--serial', '123'),
            'key edit': self.native('--remote-key', '1=group:5'),
            'slot edit': self.native('--remote-slot', '1=group:5'),
        }
        for label, arguments in cases.items():
            with self.subTest(case=label), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
                result = self.invoke(arguments, 1)
            self.assertTrue(result['error'])
            connect.assert_not_called()

    def test_invalid_saved_connection_plans_fail_before_client_construction(self):
        valid = self.plan.as_dict()
        forged = deepcopy(valid)
        forged['changes']['ForwardingRoute'][1] = 80
        absent = deepcopy(valid)
        absent['topology'] = FrozenTopology.from_xml(xml([source(), network(200), network(99)])).as_dict()
        cyclic = deepcopy(valid)
        cyclic['topology'] = FrozenTopology.from_xml(xml([
            source(), network(200, [unit(123)]), network(123, [unit(80)]),
            network(80, [unit(200), unit(99)]), network(99),
        ])).as_dict()
        unsupported = deepcopy(valid)
        unsupported['unit_type'] = 'WGATE5N'
        digest = deepcopy(valid)
        digest['topology']['facts_sha256'] = '0' * 64
        for label, document in (('forged', forged), ('missing route', absent), ('cycle', cyclic),
                                ('unsupported profile', unsupported), ('digest', digest)):
            self.plan_file.write_text(json.dumps(document))
            with self.subTest(case=label), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(self.native())
            self.assertEqual(error.exception.code, 2)
            connect.assert_not_called()

    def test_missing_or_malformed_plan_file_fails_before_client_construction(self):
        for contents in (None, '{not JSON', 'null', '[]', '{}', '{"format":"unknown"}'):
            if contents is None:
                self.plan_file.unlink()
            else:
                self.plan_file.write_text(contents)
            with self.subTest(contents=contents), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(self.native())
            self.assertEqual(error.exception.code, 2)
            connect.assert_not_called()

    def test_mocked_native_apply_refreshes_closed_topology_and_saves_exact_source_once(self):
        client = ClosedClient()
        result = self.mocked_native(client, self.native())
        self.assertTrue(result['verified'])
        self.assertTrue(result['saved'])
        self.assertEqual(result['destination'], '/db//P/254/p/200')
        self.assertEqual(client.commands, ['DBGETXML //P', 'GET //P/99 *', 'GET //P/123 *',
                                           'GET //P/200 *', 'GET //P/254 *'])
        self.assertEqual(client.loads, [('//P/254', '/db//P/254/p/200')])
        self.assertEqual(client.session.saves, ['/db//P/254/p/200'])
        self.assertEqual(client.session.current['ForwardingRoute'], '27 123 99 255 255 255 255')
        for field in ('device_verified', 'physical_forwarding_verified', 'original_toolkit_executed'):
            self.assertFalse(result[field])

    def test_connection_plan_expands_transport_limits_for_large_valid_project(self):
        client = ClosedClient()
        client.document = xml().replace(b'<Installation>', b'<Installation><!--' + b'x' * (1024 * 1024) + b'-->')
        self.assertGreater(len(client.document), 1024 * 1024)
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client) as connect, \
                patch('cbus_toolkit.programming.Programmer', MockProgrammer):
            result = self.invoke(self.native())
        self.assertEqual(connect.call_args.kwargs['max_line_bytes'], 16 * 1024 * 1024 + 4096)
        self.assertEqual(connect.call_args.kwargs['max_response_bytes'], 16 * 1024 * 1024 + 65536)
        self.assertTrue(result['saved'])
        self.assertEqual(client.session.saves, ['/db//P/254/p/200'])

    def memory_transport(self, document, **limits):
        """Exercise the real parser against literal reply bytes without a socket."""
        stream = io.BytesIO(b'[1] 347-' + document + b'\r\n[1] 344 End XML\r\n')
        memory_socket = Mock(spec=('recv', 'settimeout', 'sendall', 'close'))
        memory_socket.recv.side_effect = stream.read
        client = CGateClient('memory-peer', timeout=30, **limits)
        client._socket = memory_socket
        self.addCleanup(client.close)
        return client, memory_socket

    def test_actual_reply_parser_accepts_large_scoped_xml_and_default_limit_rejects_identical_wire(self):
        document = xml().replace(b'<Installation>', b'<Installation><!--' + b'x' * (1024 * 1024) + b'-->')
        self.assertGreater(len(document), 1024 * 1024)
        scoped_limits = preflight(build_parser().parse_args(self.native()))
        scoped, scoped_socket = self.memory_transport(document, **scoped_limits)
        default, default_socket = self.memory_transport(document)
        with patch('socket.create_connection', side_effect=AssertionError('No socket may open')) as connect:
            reply = scoped.command('DBGETXML //P')
            self.assertEqual(reply.code, 344)
            observed = FrozenTopology.from_xml(xml_text(reply).encode())
            self.assertEqual(observed.fingerprint, self.plan.topology.fingerprint)
            with self.assertRaisesRegex(RuntimeError, 'line exceeded configured limit'):
                default.command('DBGETXML //P')
        connect.assert_not_called()
        scoped_socket.sendall.assert_called_once_with(b'[1] DBGETXML //P\r\n')
        default_socket.sendall.assert_called_once_with(b'[1] DBGETXML //P\r\n')
        scoped_socket.close.assert_not_called()
        default_socket.close.assert_called_once_with()
        self.assertFalse(default.connected)

    def test_actual_reply_parser_overhead_allowance_does_not_expand_xml_payload_cap(self):
        base = xml()
        target_size = 16 * 1024 * 1024 + 1
        padding = b'x' * (target_size - len(base) - len(b'<!---->'))
        document = base.replace(b'<Installation>', b'<Installation><!--' + padding + b'-->')
        self.assertEqual(len(document), target_size)
        scoped_limits = preflight(build_parser().parse_args(self.native()))
        client, memory_socket = self.memory_transport(document, **scoped_limits)
        with patch('socket.create_connection', side_effect=AssertionError('No socket may open')) as connect:
            reply = client.command('DBGETXML //P')
        self.assertEqual(reply.code, 344, 'Transport overhead allowance must admit this literal reply')
        with self.assertRaisesRegex(WirelessConnectionError, '16 MiB'):
            FrozenTopology.from_xml(xml_text(reply).encode())
        connect.assert_not_called()
        memory_socket.sendall.assert_called_once_with(b'[1] DBGETXML //P\r\n')
        self.assertTrue(client.connected)

    def test_connection_project_larger_than_sixteen_mib_refuses_before_set_or_save(self):
        client = ClosedClient()
        client.document = xml().replace(b'<Installation>', b'<Installation><!--' + b'x' * (16 * 1024 * 1024) + b'-->')
        result = self.mocked_native(client, self.native(), 1)
        self.assertIn('16 MiB', result['error'])
        self.assertEqual(client.session.calls, [])
        self.assertEqual(client.session.saves, [])

    def test_connection_transport_limits_do_not_change_legacy_remote_show_or_plan(self):
        show = self.native()
        plan_index = show.index('--plan')
        del show[plan_index:plan_index + 2]
        show.append('--show')
        legacy_plan = WirelessGatewayEditor(self.spec).plan(
            self.spec.defaults(), mode='remote-switch', identity=('WGATE5F', '2.4.00', None))
        self.plan_file.write_text(json.dumps(legacy_plan.as_dict()))
        for label, arguments in (('show', show), ('remote plan', self.native())):
            client = ClosedClient()
            with self.subTest(case=label), patch('cbus_toolkit.cgate.CGateClient', return_value=client) as connect, \
                    patch('cbus_toolkit.programming.Programmer', MockProgrammer):
                self.invoke(arguments)
            self.assertNotIn('max_line_bytes', connect.call_args.kwargs)
            self.assertNotIn('max_response_bytes', connect.call_args.kwargs)

    def test_plan_file_mutation_after_preflight_cannot_replace_cached_connection_plan(self):
        redirected = WirelessConnectionEditor(self.spec).plan(
            self.spec.defaults(), topology=FrozenTopology.from_xml(xml()), source_network=254,
            unit_address=200, identity=('WGATE5F', '2.4.00', None), application2=202,
            destination_network=123)
        remote_plan = WirelessGatewayEditor(self.spec).plan(
            self.spec.defaults(), mode='remote-switch', identity=('WGATE5F', '2.4.00', None))
        replacements = ('{a replacement file must never be reread', json.dumps(redirected.as_dict()),
                        json.dumps(remote_plan.as_dict()))
        for replacement in replacements:
            client = ClosedClient()
            self.plan_file.write_text(json.dumps(self.plan.as_dict()))

            def connect_after_preflight(*_args, **_kwargs):
                self.plan_file.write_text(replacement)
                return client

            with self.subTest(replacement=replacement[:100]), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=connect_after_preflight), \
                    patch('cbus_toolkit.programming.Programmer', MockProgrammer):
                result = self.invoke(self.native())
            self.assertEqual(result['changes'], {'Application': [56, 202], 'ForwardingMode': [1],
                                                 'ForwardingRoute': [27, 123, 99, 255, 255, 255, 255]})
            self.assertTrue(result['saved'])
            self.assertEqual(client.session.saves, ['/db//P/254/p/200'])

    def test_cached_legacy_remote_plan_cannot_be_reclassified_after_client_construction(self):
        legacy_plan = WirelessGatewayEditor(self.spec).plan(
            self.spec.defaults(), mode='remote-switch', identity=('WGATE5F', '2.4.00', None))
        self.plan_file.write_text(json.dumps(legacy_plan.as_dict()))
        client = ClosedClient()

        def replace_with_connection(*_args, **_kwargs):
            self.plan_file.write_text(json.dumps(self.plan.as_dict()))
            return client

        with patch('cbus_toolkit.cgate.CGateClient', side_effect=replace_with_connection) as connect, \
                patch('cbus_toolkit.programming.Programmer', MockProgrammer):
            result = self.invoke(self.native())
        self.assertEqual(result['format'], 'cbus-wireless-gateway-remotes-plan-v1')
        self.assertEqual(result['changes'], {'MapWirelessRemotes': [1]})
        self.assertEqual(client.session.calls, [('MapWirelessRemotes', '1')])
        self.assertEqual(client.session.saves, ['/db//P/254/p/200'])
        self.assertEqual(client.commands, [], 'The replaced file must not trigger a topology read')
        self.assertNotIn('max_line_bytes', connect.call_args.kwargs)
        self.assertNotIn('max_response_bytes', connect.call_args.kwargs)

    def test_mocked_native_dry_run_stages_without_saving(self):
        client = ClosedClient()
        result = self.mocked_native(client, self.native(unit_options=('--dry-run',)))
        self.assertTrue(result['verified'])
        self.assertFalse(result['saved'])
        self.assertIsNone(result['destination'])
        self.assertTrue(client.session.calls)
        self.assertEqual(client.session.saves, [])

    def test_mocked_native_missing_ownership_or_mixed_options_refuses_before_project_read(self):
        cases = [self.native(exclusive=False), self.native('--show'), self.native('--mode', 'network-gateway'),
                 self.native(unit_options=('--destination', '/db//P/254/p/201'))]
        for arguments in cases:
            client = ClosedClient()
            with self.subTest(arguments=arguments):
                self.mocked_native(client, arguments, 1)
            self.assertEqual(client.commands, [])
            self.assertEqual(client.session.calls, [])
            self.assertEqual(client.session.saves, [])

    def test_mocked_native_physical_destination_refused_before_session_load(self):
        client = ClosedClient()
        result = self.mocked_native(client, self.native(unit_options=('--destination', '//P/254/p/200')), 1)
        self.assertIn('loaded database source', result['error'])
        self.assertEqual(client.loads, [])
        self.assertEqual(client.commands, [])

    def test_mocked_native_open_or_changed_project_refuses_before_parameter_writes(self):
        changed = xml().replace(b'<Address>99</Address>', b'<Address>98</Address>')
        for opened, document in (('//P/123', xml()), (None, changed)):
            client = ClosedClient()
            client.open_network, client.document = opened, document
            with self.subTest(opened=opened):
                self.mocked_native(client, self.native(), 1)
            self.assertEqual(client.session.calls, [])
            self.assertEqual(client.session.saves, [])

    def test_mocked_native_stale_parameters_refuse_before_set_or_save(self):
        client = ClosedClient()
        client.session.current['Application'] = '57 255'
        refusal = self.mocked_native(client, self.native(), 1)
        self.assertIn('changed since', refusal['error'])
        self.assertEqual(client.session.calls, [])
        self.assertEqual(client.session.saves, [])


if __name__ == '__main__':
    unittest.main()
