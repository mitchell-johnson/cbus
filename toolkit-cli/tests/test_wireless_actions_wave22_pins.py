"""Wave22 offline pins for wireless action guards with zero prior refs.

Narrow characterization only: every peer is a fake, no network is opened,
and no Rust, edlt_shutter, firmware_usb or parity-register behavior is
touched. Each test pins a guard in wireless_actions.py that no earlier
test exercises.
"""
import unittest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.wireless_project_remotes import FrozenRemoteProject
from cbus_toolkit.wireless_actions import (
    WirelessActionCatalogue,
    WirelessActionPlan,
    WirelessActionApplyError,
    apply_wireless_action,
    plan_wireless_action,
    validate_action_execution,
)


CATALOGUE = (b'<CBusUnits><Units><Unit><CatalogNumber>5800WCGA</CatalogNumber>'
             b'<AlternativeCatalogNumbers>5800WCGC</AlternativeCatalogNumbers><FirmwareRevisions>'
             b'<Revision><UnitType>WGATE5F</UnitType><MinVersion>2.4.0</MinVersion>'
             b'<MaxVersion>2.4.99</MaxVersion><UnitSpecName>WGATE5X_2.xml</UnitSpecName>'
             b'<ClassName>WirelessCBusGateway</ClassName></Revision>'
             b'</FirmwareRevisions></Unit></Units></CBusUnits>')
PROJECT = (b'<Project><Address>TEST</Address><TagName>Synthetic</TagName><Network>'
           b'<Address>254</Address><TagName>ClosedSource</TagName><Unit><Address>20</Address>'
           b'<TagName>Gateway</TagName><OID>11111111-2222-3333-4444-555555555555</OID>'
           b'<UnitType>WGATE5F</UnitType><FirmwareVersion>2.4.00</FirmwareVersion>'
           b'<CatalogNumber>5800WCGA</CatalogNumber><SerialNumber>70179.836</SerialNumber>'
           b'<PP><Unknown> preserve </Unknown></PP></Unit></Network></Project>')
SOURCE = '//TEST/254/p/20'


def make_plan(operation='cached-status'):
    return plan_wireless_action(FrozenRemoteProject.from_xml(PROJECT),
                                catalogue=WirelessActionCatalogue.from_xml(CATALOGUE),
                                source_network=254, unit_address=20, operation=operation)


def response(code, *lines):
    return CGateResponse(tuple(lines), lines[-1], code)


class ActionPeer:
    timeout = 10.0

    def __init__(self, **values):
        self.commands = []
        self.project = PROJECT
        self.values = {'Type': 'WGATE5F', 'Version': '2.4.00',
                       'CatalogNumber': '5800WCGA', 'SerialNumber': '70179.836',
                       'UnitTemperature': 'unknown', 'UnitSupplyVoltage': '3.200',
                       'BackgroundSignalPower': '-70.000',
                       'LastPacketReceivedPower': 'unknown'}
        self.values.update(values)
        self.overrides = {}

    def command(self, command):
        self.commands.append(command)
        if command in self.overrides:
            value = self.overrides[command]
            if isinstance(value, BaseException):
                raise value
            return value
        if command == 'DBGETXML //TEST':
            return response(344, *('347-' + line for line in self.project.decode().splitlines()), '344 OK')
        if command.startswith('GET ' + SOURCE + ' '):
            field = command.split()[-1]
            return response(300, f'300 {SOURCE}: {field}={self.values[field]}')
        raise AssertionError('Unexpected command: ' + command)


class Wave22CachedStatusTextTest(unittest.TestCase):
    def test_wave22_cached_status_empty_oversize_control_text_refused(self):
        for field, bad in (('UnitTemperature', ''),
                           ('UnitSupplyVoltage', 'x' * 257),
                           ('BackgroundSignalPower', 'ok\x1ftext')):
            peer = ActionPeer(**{field: bad})
            with self.subTest(field=field), self.assertRaises(WirelessActionApplyError) as failed:
                apply_wireless_action(peer, make_plan('cached-status'))
            self.assertIn('Malformed cached status text', str(failed.exception))
            self.assertFalse(any(cmd.startswith('DO ') for cmd in peer.commands))
            self.assertEqual(failed.exception.details['status'], 'failed')


class Wave22EffectfulTypeGuardTest(unittest.TestCase):
    def test_wave22_non_plan_and_non_bool_flags_refused_before_io(self):
        selected = make_plan()
        with self.assertRaisesRegex(ValueError, 'Expected a wireless action plan'):
            validate_action_execution('not-a-plan', allow_physical_action=True, timeout=10.0)
        with self.assertRaisesRegex(ValueError, 'Expected a wireless action plan'):
            apply_wireless_action(ActionPeer(), 'not-a-plan')
        for allow, preview in ((1, False), (True, 1), ('yes', False), (True, 'no')):
            with self.subTest(allow=allow, preview=preview):
                with self.assertRaisesRegex(ValueError, 'must be booleans'):
                    validate_action_execution(selected, allow_physical_action=allow,
                                              timeout=10.0, preview=preview)
        peer = ActionPeer()
        with self.assertRaisesRegex(ValueError, 'must be booleans'):
            validate_action_execution(selected, allow_physical_action=1,
                                      timeout=peer.timeout, preview=False)
        self.assertEqual(peer.commands, [])
        with self.assertRaisesRegex(ValueError, 'Expected frozen project'):
            WirelessActionPlan('project', WirelessActionCatalogue.from_xml(CATALOGUE),
                               254, 20, 'cached-status')
        with self.assertRaisesRegex(ValueError, 'Expected frozen project'):
            WirelessActionPlan(FrozenRemoteProject.from_xml(PROJECT), 'catalogue',
                               254, 20, 'cached-status')


class Wave22CatalogueRootTest(unittest.TestCase):
    def test_wave22_wrong_catalogue_root_refused(self):
        with self.assertRaisesRegex(ValueError, 'Expected a CBusUnits catalogue'):
            WirelessActionCatalogue.from_xml(b'<Project><Address>TEST</Address></Project>')
        self.assertEqual(WirelessActionCatalogue.from_xml(CATALOGUE).root.tag, 'CBusUnits')


class Wave22EmptyEnvelopeTest(unittest.TestCase):
    def test_wave22_empty_and_final_mismatch_envelopes_refused(self):
        peer = ActionPeer()
        peer.overrides['GET ' + SOURCE + ' Type'] = CGateResponse((), '', 300)
        with self.assertRaises(WirelessActionApplyError):
            apply_wireless_action(peer, make_plan())
        self.assertEqual(peer.commands[-1], 'GET ' + SOURCE + ' Type')
        self.assertFalse(any(cmd.startswith('DO ') for cmd in peer.commands))
        peer = ActionPeer()
        line = f'300 {SOURCE}: Type=WGATE5F'
        peer.overrides['GET ' + SOURCE + ' Type'] = CGateResponse((line,), '300 something-else', 300)
        with self.assertRaises(WirelessActionApplyError):
            apply_wireless_action(peer, make_plan())
        self.assertEqual(peer.commands[-1], 'GET ' + SOURCE + ' Type')


if __name__ == '__main__':
    unittest.main()
