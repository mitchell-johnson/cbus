"""Base-gateway CLI entrypoints and preconnect boundaries with no sockets."""
from contextlib import redirect_stderr
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import main
from cbus_toolkit.wireless_connection import FrozenTopology, WirelessConnectionEditor
import test_wireless_connection_cli as connection_cli
from cbus_toolkit.unitspec import UnitSpec
from test_wireless_base_connection import BASE_FIELDS
from test_wireless_connection import xml


class BaseClosedClient(connection_cli.ClosedClient):
    def __init__(self):
        super().__init__()
        self.document = xml().replace(b'WGATE5F', b'WGATE5N')
        self.session.unit_type = 'WGATE5N'
        self.session.current['MapWirelessRemotes'] = '1'


class BaseConnectionCliTest(unittest.TestCase):
    offline = connection_cli.WirelessConnectionCliTest.offline
    native = connection_cli.WirelessConnectionCliTest.native
    invoke = connection_cli.WirelessConnectionCliTest.invoke
    mocked_native = connection_cli.WirelessConnectionCliTest.mocked_native

    def setUp(self):
        connection_cli.WirelessConnectionCliTest.setUp(self)
        document = xml().replace(b'WGATE5F', b'WGATE5N')
        self.project.write_bytes(document)
        snapshot = json.loads(self.snapshot.read_text())
        snapshot['unit_type'] = 'WGATE5N'
        snapshot['parameters']['MapWirelessRemotes'] = '1'
        self.snapshot.write_text(json.dumps(snapshot))
        self.plan = WirelessConnectionEditor(self.spec).plan(
            snapshot['parameters'], topology=FrozenTopology.from_xml(document), source_network=254,
            unit_address=200, application2=202, destination_network=99)
        self.plan_file.write_text(json.dumps(self.plan.as_dict()))

    def test_offline_base_show_and_plan_have_only_six_fields(self):
        with patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
            view = self.invoke(self.offline('show'))
            plan = self.invoke(self.offline('plan', '--application1', '57', '--application2', '202',
                                            '--destination-network', '99'))
        connect.assert_not_called()
        self.assertFalse(view['advanced_controls_available'])
        self.assertEqual(set(view['parameters']), set(BASE_FIELDS))
        self.assertEqual(set(plan['expected']), set(BASE_FIELDS))
        self.assertEqual(plan['changes']['Application'], [57, 202])
        self.assertEqual(plan['changes']['ForwardingRoute'], [27, 123, 99, 255, 255, 255, 255])

    def test_native_base_plan_loads_database_and_saves_once(self):
        client = BaseClosedClient()
        result = self.mocked_native(client, self.native())
        self.assertTrue(result['verified'])
        self.assertTrue(result['saved'])
        self.assertEqual(client.loads, [('//P/254', '/db//P/254/p/200')])
        self.assertEqual(client.session.saves, ['/db//P/254/p/200'])
        self.assertEqual(client.session.current['MapWirelessRemotes'], '1')
        self.assertEqual(client.session.current['Application'], '56 202')
        self.assertFalse(result['whole_dialog_save_executed'])
        self.assertFalse(result['physical_forwarding_verified'])

    def test_physical_mismatched_sources_and_advanced_edits_refuse_before_client(self):
        for argv in (self.native(unit_options=('--source', '//P/254/p/200',
                                                '--destination', '/db//P/254/p/200')),
                     self.native(unit_options=('--source', '/db//OTHER/254/p/200')),
                     self.native(unit_options=('--lock-address', '//P/123')),
                     self.native('--mode', 'remote-switch'), self.native(exclusive=False)):
            with self.subTest(argv=argv), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect:
                result = self.invoke(argv, 1)
                self.assertTrue(result['error'])
                connect.assert_not_called()

    def test_malformed_and_forged_base_plans_refuse_before_connection_or_load(self):
        document = self.plan.as_dict()
        advanced = deepcopy(document)
        advanced['changes']['MapWirelessRemotes'] = [0]
        forged = deepcopy(document)
        forged['changes']['ForwardingRoute'][1] = 80
        for contents in ('{bad json', json.dumps(advanced), json.dumps(forged)):
            self.plan_file.write_text(contents)
            with self.subTest(contents=contents[:30]), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('No socket allowed')) as connect, \
                    patch('cbus_toolkit.programming.Programmer', side_effect=AssertionError('No PP LOAD allowed')) as pp, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(self.native())
            self.assertEqual(error.exception.code, 2)
            connect.assert_not_called()
            pp.assert_not_called()

    def test_base_profile_does_not_admit_advanced_offline_editor(self):
        arguments = ['wireless', '--spec-dir', str(self.folder), 'gateway', 'plan', str(self.snapshot),
                     '--mode', 'remote-switch']
        result = self.invoke(arguments, 1)
        self.assertIn('no remote switch', result['error'].lower())

    def test_base_dry_run_uses_existing_session_path_without_save(self):
        client = BaseClosedClient()
        result = self.mocked_native(client, self.native(unit_options=('--dry-run',)))
        self.assertTrue(result['verified'])
        self.assertFalse(result['saved'])
        self.assertEqual(client.loads, [('//P/254', '/db//P/254/p/200')])
        self.assertEqual(client.session.saves, [])

    def test_native_base_dispatch_has_no_advanced_schema_dependency(self):
        minimal = UnitSpec(self.spec.filename, self.spec.metadata, self.spec.sources,
                           {k: v for k, v in self.spec.parameters.items() if k in BASE_FIELDS})
        connection_cli.write_spec(self.folder, minimal)
        client = BaseClosedClient()
        result = self.mocked_native(client, self.native())
        self.assertTrue(result['saved'])
        self.assertEqual(client.session.current['MapWirelessRemotes'], '1')


if __name__ == '__main__':
    unittest.main()
