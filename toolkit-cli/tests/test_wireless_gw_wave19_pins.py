"""Wave-19 offline pins for wireless-gateway guards (P5.07, issue 44).

Each test pins a branch of ``toolkit-cli/src/cbus_toolkit/wireless_gateway.py``
with zero prior test refs (verified via grep -rn across tests/ before writing):
- ``WirelessGatewayEditor.connection_editor``: grep -rn "\\.connection_editor("
  tests/*.py -> 0 hits.
- ``verify_native_schema`` duplicate/type refusals: grep -rn "Duplicate native
  parameter schema" / "Native parameter type mismatch" tests/*.py -> 0 assert
  hits (the only mention is a Round12 docstring noting both as unpinned).
- ``apply`` divergent-readback guard: grep -rn "Native wireless gateway
  readback" tests/*.py -> 0 hits.
- ``WirelessGatewayApplyError`` message/details: grep -rn "stopped; PP"
  tests/*.py -> 0 hits (test_wireless_gateway.py pins only ``.attempted`` and
  ``details['saved']``).

Synthetic WGATE fixture only; no hardware, vendor EXE, C-Gate server, or
decoded vendor spec is required.
"""
import json
import unittest

from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from cbus_toolkit.wireless_gateway import (
    FIELDS,
    SPEC_FILENAME,
    WirelessGatewayApplyError,
    WirelessGatewayEditor,
    WirelessGatewayError,
    WirelessGatewayPlan,
    verify_native_schema,
)
from test_macros import Reply, Session
from test_wireless_gateway import fixture, remote_switch

# Connection profile layout (wireless_connection.WirelessConnectionEditor.OWNED)
# needed so the delegated editor accepts the same verified spec. Application
# and StatusMonitorApplication already match via the gateway fixture; the
# remaining four are added to a copy of it. Tuples are
# (address, count, bit size, bit offset, array skip, type).
CONNECTION_EXTRA = {
    'ApplicationConnectEnabled': (0x41, 1, 1, 0, 0, 'bit'),
    'SynchroniseToWired': (0x41, 1, 1, 2, 0, 'bit'),
    'ForwardingMode': (0x41, 1, 1, 1, 0, 'bit'),
    'ForwardingRoute': (0x42, 7, 8, 0, 0, 'int'),
    'StatusMonitorApplication': (0x37, 1, 8, 0, 0, 'int'),
}


def connection_fixture():
    """Gateway fixture extended with the Connection profile parameters."""
    base = fixture()
    parameters = dict(base.parameters)
    for name, (address, size, bits, bit, skip, kind) in CONNECTION_EXTRA.items():
        fields = {'Name': name, 'Type': kind, 'Address': str(address),
                  'ArraySize': str(size), 'BitAddress': str(bit),
                  'ArraySkip': str(skip),
                  'DefaultValue': ' '.join(['0' if kind == 'bit' else '255'] * size)}
        if kind == 'int':
            fields.update(BitSize=str(bits), MinValue='0', MaxValue='255')
        parameters[name] = ParameterSpec(name, kind, 'literal-wgate-connection-fixture.xml',
                                         fields)
    return UnitSpec(SPEC_FILENAME, dict(base.metadata), base.sources, parameters)


class FakeSchemaSession:
    """Minimal native session returning canned PP schema XML text."""

    def __init__(self, text):
        self.text = text

    def info(self, _name):
        return Reply(self.text)


class WirelessGatewayWave19Pins(unittest.TestCase):
    def test_connection_editor_reuses_verified_spec(self):
        spec = connection_fixture()
        editor = WirelessGatewayEditor(spec)
        connection = editor.connection_editor()
        self.assertEqual(type(connection).__name__, 'WirelessConnectionEditor')
        self.assertIs(connection.spec, spec)
        self.assertIs(editor.spec, spec)

    def test_verify_native_schema_refuses_duplicate_and_type_mismatch(self):
        from cbus_toolkit.programming import xml_text

        spec = fixture()
        live = Session(spec)
        self.assertIsNone(verify_native_schema(live, spec, FIELDS, WirelessGatewayError))
        valid = xml_text(live.info('*'))
        duplicate = valid.replace(
            '</Parameters>',
            '<Param><Name>MapWirelessRemotes</Name><Type>bit</Type></Param></Parameters>',
        )
        self.assertNotEqual(duplicate, valid)
        with self.assertRaisesRegex(WirelessGatewayError, 'Duplicate native parameter schema'):
            verify_native_schema(FakeSchemaSession(duplicate), spec, FIELDS,
                                 WirelessGatewayError)
        mistyped = valid.replace('<Type>bit</Type>', '<Type>int</Type>', 1)
        self.assertNotEqual(mistyped, valid)
        with self.assertRaisesRegex(WirelessGatewayError,
                                    'Native parameter type mismatch: MapWirelessRemotes'):
            verify_native_schema(FakeSchemaSession(mistyped), spec, FIELDS,
                                 WirelessGatewayError)

    def test_apply_refuses_divergent_readback(self):
        class DivergentSession(Session):
            """Native PP write succeeds but the readback disagrees with the plan."""

            def values(self):
                current = dict(self.current)
                if self.calls:
                    current['MapWirelessRemotes'] = (
                        '0' if current['MapWirelessRemotes'] == '1' else '1')
                return current

        editor = WirelessGatewayEditor(fixture())
        base = remote_switch()
        live = DivergentSession(fixture())
        live.unit_type, live.firmware, live.catalog_number = 'WGATE5F', '2.4.00', '5800WCGA'
        live.current.update(base.current)
        plan = editor.plan(live.values(), mode='network-gateway')
        self.assertEqual(dict(plan.changes), {'MapWirelessRemotes': (0,)})
        # The readback guard raises inside the guarded PP-write region, so the
        # divergence surfaces as an apply error whose cause names the guard
        # (no recovery I/O is issued after the uncertain write).
        with self.assertRaises(WirelessGatewayApplyError) as caught:
            editor.apply(live, plan)
        error = caught.exception
        self.assertEqual(error.attempted, ('MapWirelessRemotes',))
        self.assertIn('Native wireless gateway readback differs from the plan',
                      str(error.cause))
        self.assertFalse(error.details['saved'])
        self.assertEqual([name for name, _ in live.calls], ['MapWirelessRemotes'])

    def test_apply_error_reports_attempt_and_uncertainty(self):
        editor, live = WirelessGatewayEditor(fixture()), remote_switch()
        plan = editor.plan(live.values(), remote=4, serial=5, slots={3: 'scene-toggle:1'},
                           identity=('WGATE5F', '2.2.90', None))
        document = json.loads(json.dumps(plan.as_dict()))
        live.firmware = '2.2.90'
        live.failure = 'KeySceneMask4'
        with self.assertRaises(WirelessGatewayApplyError) as caught:
            editor.apply(live, WirelessGatewayPlan.from_dict(document))
        error = caught.exception
        self.assertEqual(error.attempted, ('RemoteIdentity4', 'KeySceneMask4'))
        self.assertEqual(error.details, {'attempted_parameters': ['RemoteIdentity4',
                                                                  'KeySceneMask4'],
                                         'saved': False, 'device_verified': False})
        self.assertIsInstance(error.cause, RuntimeError)
        self.assertIn('stopped; PP changes may be partial', str(error))


if __name__ == '__main__':
    unittest.main()
