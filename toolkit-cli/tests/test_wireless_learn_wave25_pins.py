"""Wave-25 offline pins for wireless-gateway guards (P5.07, issue 44).

No wireless_learn/join module exists (glob ``src/cbus_toolkit/wireless*.py``
finds only wireless_gateway.py and friends), so per the wave fallback this
file pins remaining ``toolkit-cli/src/cbus_toolkit/wireless_gateway.py``
guards instead. Each test pins a branch with zero prior exact-message refs
(verified via grep -rn across tests/ before writing):
- ``verify_native_schema`` layout mismatch: grep -rn "layout mismatch"
  tests/test_wireless*.py tests/test_wireless_gw_wave19_pins.py -> 0 hits
  (the only "Native parameter layout mismatch" asserts are SensorError pins
  in test_senll_global_status.py / test_senll_source_inventory.py; Wave-19
  pinned only duplicate and type-mismatch for the gateway).
- ``plan`` Remotes-tab refusal: grep -rn "Remotes tab only" tests/*.py ->
  0 hits (test_wireless_gateway.py:130 exercises the branch via the shorter
  "Remote Switch mode" pattern; the exact message is never asserted).
- ``plan`` key/slot collision: grep -rn "also selected by" tests/*.py ->
  0 hits (test_wireless_gateway.py:165-166 exercises the branch via the
  shorter "also selected" pattern; the exact "Slot 5 is also selected by
  key 1" message is never asserted).
- ``WirelessGatewayPlan.from_dict`` format refusal: grep -rn "Expected a
  cbus-wireless" tests/*.py -> 0 hits (test_wireless_gateway.py:241-243 and
  Round4 pin only the short "Expected a" / generic matches; the exact
  document message is never asserted).

Synthetic WGATE fixture only; no hardware, vendor EXE, C-Gate server, or
decoded vendor spec is required.
"""
import unittest

from cbus_toolkit.wireless_gateway import (
    FIELDS,
    WirelessGatewayEditor,
    WirelessGatewayError,
    WirelessGatewayPlan,
    verify_native_schema,
)
from test_macros import Reply, Session
from test_wireless_gateway import fixture, remote_switch, session


class FakeSchemaSession:
    """Minimal native session returning canned PP schema XML text."""

    def __init__(self, text):
        self.text = text

    def info(self, _name):
        return Reply(self.text)


class WirelessGatewayWave25Pins(unittest.TestCase):
    def test_verify_native_schema_refuses_layout_mismatch(self):
        from cbus_toolkit.programming import xml_text

        spec = fixture()
        live = Session(spec)
        valid = xml_text(live.info('*'))
        # MapWirelessRemotes lives at 0x41 (65); no other gateway parameter
        # uses that address, so this single substitution only corrupts its
        # layout row.
        self.assertIn('<Address>65</Address>', valid)
        mistyped = valid.replace('<Address>65</Address>', '<Address>66</Address>', 1)
        self.assertNotEqual(mistyped, valid)
        with self.assertRaisesRegex(
            WirelessGatewayError,
            r'Native parameter layout mismatch: MapWirelessRemotes/Address',
        ):
            verify_native_schema(FakeSchemaSession(mistyped), spec, FIELDS,
                                 WirelessGatewayError)

    def test_plan_refuses_remote_edits_outside_remote_switch_mode(self):
        editor = WirelessGatewayEditor(fixture())
        live = session()
        self.assertEqual(live.current['MapWirelessRemotes'], '0')
        for options in ({'remote': 1, 'serial': 5},
                        {'remote': 2, 'serial': 9, 'keys': {1: 'group:5'}}):
            with self.subTest(options=options), self.assertRaisesRegex(
                WirelessGatewayError,
                'Toolkit shows the Remotes tab only in Remote Switch mode',
            ):
                editor.plan(live.values(), **options)

    def test_plan_refuses_key_slot_collision_exact_message(self):
        editor = WirelessGatewayEditor(fixture())
        values = remote_switch().values()
        # Dialog key 1 maps to raw PP slot 5 (WTXU_KEY_MAP[0] == 4), so an
        # explicit slot-5 edit collides with it.
        with self.assertRaisesRegex(
            WirelessGatewayError, r'Slot 5 is also selected by key 1'
        ):
            editor.plan(values, remote=1, serial=1,
                        keys={1: 'group:1'}, slots={5: 'group:2'})

    def test_plan_document_refuses_non_plan_format_exact_message(self):
        for bad in (None, [], 'x', {}, {'format': 'other'}):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                WirelessGatewayError,
                r'Expected a cbus-wireless-gateway-remotes-plan-v1 document',
            ):
                WirelessGatewayPlan.from_dict(bad)


if __name__ == '__main__':
    unittest.main()
