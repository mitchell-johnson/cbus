"""Literal bounded action cases. Every DO response comes from a fake peer."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.wireless_project_remotes import FrozenRemoteProject
from cbus_toolkit.wireless_actions import (
    WirelessActionCatalogue, WirelessActionPlan, WirelessActionApplyError,
    plan_wireless_action, preview_wireless_action, apply_wireless_action,
    validate_action_execution,
)


CATALOGUE = b'''<CBusUnits><Units><Unit><CatalogNumber>5800WCGA</CatalogNumber>
<AlternativeCatalogNumbers>5800WCGC</AlternativeCatalogNumbers><FirmwareRevisions>
<Revision><UnitType>WGATE5F</UnitType><MinVersion>2.4.0</MinVersion><MaxVersion>2.4.99</MaxVersion>
<UnitSpecName>WGATE5X_2.xml</UnitSpecName><ClassName>WirelessCBusGateway</ClassName></Revision>
</FirmwareRevisions></Unit></Units></CBusUnits>'''
PROJECT = b'''<Project><Address>TEST</Address><TagName>Synthetic</TagName><Network>
<Address>254</Address><TagName>ClosedSource</TagName><Unit><Address>20</Address>
<TagName>Gateway</TagName><OID>11111111-2222-3333-4444-555555555555</OID>
<UnitType>WGATE5F</UnitType><FirmwareVersion>2.4.00</FirmwareVersion>
<CatalogNumber>5800WCGA</CatalogNumber><SerialNumber>70179.836</SerialNumber>
<PP><Unknown> preserve </Unknown></PP></Unit></Network></Project>'''
SOURCE = '//TEST/254/p/20'
# Literal native counter names and independent boundary values, not generated
# from the implementation's counter list.
STATS = ('{PacketsReceived=0; PacketsReceivedWithError=1; PacketsNAKd=2; PacketsNCAd=3; '
         'CollisionsDetected=4; TransmitAttempts=5; TransmitCancellations=6; '
         'CollisionsDetectedinTAP=7; CollisionsNotifiedDetected=8; TransmissionsDropped=9; '
         'SuccessfulTransmissions=2147483648; TransmissionsNAKd=4294967295}')


def plan(operation='cached-status', *, project=PROJECT, catalogue=CATALOGUE, **kwargs):
    values = dict(source_network=254, unit_address=20, operation=operation)
    values.update(kwargs)
    return plan_wireless_action(FrozenRemoteProject.from_xml(project),
                               catalogue=WirelessActionCatalogue.from_xml(catalogue), **values)


def response(code, *lines):
    return CGateResponse(tuple(lines), lines[-1], code)


class ActionPeer:
    timeout = 10.0

    def __init__(self, **values):
        self.commands = []
        self.project = PROJECT
        self.values = dict(Type='WGATE5F', Version='2.4.00', CatalogNumber='5800WCGA', SerialNumber='70179.836',
                           UnitTemperature='unknown', UnitSupplyVoltage='3.200',
                           BackgroundSignalPower='-70.000', LastPacketReceivedPower='unknown',
                           OpStats=STATS, ManufacturerCode='0', ProductClass='255',
                           MediaType='2', ProcessSelector='6', FeatureSet='7')
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
        if command in ('DO ' + SOURCE + ' MAISync', 'DO ' + SOURCE + ' RecallOpStats',
                       'DO ' + SOURCE + ' ResetOpStats'):
            return response(202, '202 Done: ' + SOURCE)
        raise AssertionError('Unexpected command: ' + command)


class WirelessActionsTest(unittest.TestCase):
    def test_immutable_plan_round_trip_and_forgery_refusal(self):
        selected = plan('recall-op-stats')
        self.assertEqual((selected.source, selected.network_path), (SOURCE, '//TEST/254'))
        with self.assertRaises(FrozenInstanceError):
            selected.unit_address = 21
        data = selected.as_dict()
        self.assertEqual(WirelessActionPlan.from_dict(json.loads(json.dumps(data))).as_dict(), data)
        for key, value in (('source', SOURCE + '/db'), ('physical_action', False),
                           ('original_timeout_ms', 0), ('hardware_verified', True), ('extra', 1)):
            altered = deepcopy(data)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                WirelessActionPlan.from_dict(altered)
        altered = deepcopy(data)
        altered['catalogue']['xml'] = altered['catalogue']['xml'].replace('5800WCGA', 'invented')
        with self.assertRaises(ValueError):
            WirelessActionPlan.from_dict(altered)

    def test_unsupported_selection_identity_and_profiles_fail_offline(self):
        for change in ({'source_network': 255}, {'unit_address': 255}, {'unit_address': True},
                       {'source_network': 5}, {'operation': 'psync'}, {'operation': 'net-learn'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                plan(**change)
        for old, new in ((b'WGATE5F', b'WGATE5N'), (b'2.4.00', b'2.5.00'),
                         (b'70179.836', b'0.0'), (b'70179.836', b'1048575.4095'),
                         (b'70179.836', b'070179.836'), (b'70179.836', b'11223344'),
                         (b'11111111-2222-3333-4444-555555555555', b'not-an-oid')):
            with self.subTest(new=new), self.assertRaises(ValueError):
                plan(project=PROJECT.replace(old, new))
        for old, new in ((b'WirelessCBusGateway', b'CBusUnit'), (b'WGATE5X_2.xml', b'OTHER.xml'),
                         (b'2.4.99', b'9.9.99'), (b'5800WCGC', b'Invented')):
            with self.subTest(new=new), self.assertRaises(ValueError):
                plan(catalogue=CATALOGUE.replace(old, new))
        duplicate = CATALOGUE.replace(b'</Units>', CATALOGUE.split(b'<Units>')[1].split(b'</Units>')[0] + b'</Units>')
        with self.assertRaises(ValueError):
            plan(catalogue=duplicate)

    def test_literal_wrm_alternative_catalogue_profile(self):
        catalogue = CATALOGUE.replace(b'WGATE5F', b'WRM8R2').replace(b'WGATE5X_2.xml', b'WRM8R2_2.xml')
        catalogue = catalogue.replace(b'WirelessCBusGateway', b'CBusWirelessIOUnit')
        catalogue = catalogue.replace(b'5800WCGA', b'E5858R4F2TA').replace(b'5800WCGC', b'E5858R4F2EC')
        project = PROJECT.replace(b'WGATE5F', b'WRM8R2').replace(b'5800WCGA', b'E5858R4F2EC')
        self.assertEqual(plan(project=project, catalogue=catalogue).target['unit_type'], 'WRM8R2')

    def test_gateway_catalogue_shares_number_with_distinct_unadmitted_type(self):
        revision = CATALOGUE.split(b'<FirmwareRevisions>')[1].split(b'</FirmwareRevisions>')[0]
        catalogue = CATALOGUE.replace(b'</FirmwareRevisions>', revision.replace(b'WGATE5F', b'WGATE5N')
                                      + b'</FirmwareRevisions>')
        self.assertEqual(plan(catalogue=catalogue).target['unit_type'], 'WGATE5F')
        with self.assertRaises(ValueError):
            plan(project=PROJECT.replace(b'WGATE5F', b'WGATE5N'), catalogue=catalogue)

    def test_plan_serialization_cap_includes_json_escaping(self):
        selected = plan()
        with patch('cbus_toolkit.wireless_actions.MAX_PLAN_JSON_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'size cap'):
                selected.as_dict()

    def test_xml_declaration_and_encoding_refusals(self):
        for payload in (b'<!DOCTYPE CBusUnits><CBusUnits/>', CATALOGUE.decode().encode('utf-16le'),
                        b'<!ENTITY a "text"><CBusUnits/>', b'\xff'):
            with self.subTest(payload=payload[:30]), self.assertRaises(ValueError):
                WirelessActionCatalogue.from_xml(payload)

    def test_effectful_optin_and_timeout_checked_before_any_io(self):
        for operation in ('mai-sync', 'recall-op-stats', 'reset-op-stats'):
            peer = ActionPeer()
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                apply_wireless_action(peer, plan(operation))
            self.assertEqual(peer.commands, [])
        for timeout in (0, -1, float('nan'), float('inf'), True, '8'):
            peer = ActionPeer()
            peer.timeout = timeout
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                apply_wireless_action(peer, plan())
            self.assertEqual(peer.commands, [])
        for operation in ('recall-op-stats', 'reset-op-stats'):
            with self.assertRaises(ValueError):
                validate_action_execution(plan(operation), allow_physical_action=True, timeout=7.999)
        validate_action_execution(plan('mai-sync'), allow_physical_action=True, timeout=0.5)
        self.assertIsNone(plan('mai-sync').original_timeout_ms)

    def test_preview_checks_runtime_and_stale_without_optin_or_do(self):
        peer = ActionPeer()
        peer.timeout = 0.5
        receipt = preview_wireless_action(peer, plan('reset-op-stats'))
        self.assertEqual(receipt['status'], 'verified-preview')
        self.assertEqual(peer.commands, ['DBGETXML //TEST', 'GET ' + SOURCE + ' Type',
                                        'GET ' + SOURCE + ' Version', 'GET ' + SOURCE + ' CatalogNumber',
                                        'GET ' + SOURCE + ' SerialNumber',
                                        'DBGETXML //TEST'])
        self.assertFalse(receipt['command_attempted'])

    def test_stale_runtime_mismatch_and_absence_refuse_before_do(self):
        for key, value in (('project', PROJECT.replace(b' preserve ', b'changed')),
                           ('Type', 'WGATE5N'), ('Version', '2.4.01'), ('CatalogNumber', 'OTHER'),
                           ('SerialNumber', '1.2'), ('SerialNumber', '070179.836')):
            peer = ActionPeer()
            if key == 'project':
                peer.project = value
            else:
                peer.values[key] = value
            with self.subTest(key=key), self.assertRaises(WirelessActionApplyError) as failed:
                apply_wireless_action(peer, plan('reset-op-stats'), allow_physical_action=True)
            self.assertFalse(failed.exception.details['command_attempted'])
            self.assertFalse(any(cmd.startswith('DO ') for cmd in peer.commands))
        peer = ActionPeer()
        peer.overrides['GET ' + SOURCE + ' Type'] = response(401, '401 Bad object or device ID: Unit not found')
        with self.assertRaises(WirelessActionApplyError):
            apply_wireless_action(peer, plan('reset-op-stats'), allow_physical_action=True)
        self.assertFalse(any(cmd.startswith('DO ') for cmd in peer.commands))

    def test_second_snapshot_catches_change_during_runtime_identity_checks(self):
        class ChangingPeer(ActionPeer):
            def command(self, command):
                reply = super().command(command)
                if command == 'GET ' + SOURCE + ' SerialNumber':
                    self.project = self.project.replace(b' preserve ', b' changed ')
                return reply

        peer = ChangingPeer()
        with self.assertRaises(WirelessActionApplyError) as failed:
            apply_wireless_action(peer, plan('reset-op-stats'), allow_physical_action=True)
        self.assertIn('Stale project', str(failed.exception))
        self.assertFalse(failed.exception.details['command_attempted'])
        self.assertEqual(peer.commands[-1], 'DBGETXML //TEST')

    def test_cached_status_keeps_unknown_and_has_no_physical_claim(self):
        peer = ActionPeer()
        receipt = apply_wireless_action(peer, plan())
        self.assertEqual(receipt['values'], {'UnitTemperature': 'unknown', 'UnitSupplyVoltage': '3.200',
                                           'BackgroundSignalPower': '-70.000', 'LastPacketReceivedPower': 'unknown'})
        self.assertTrue(receipt['cached_only'])
        self.assertTrue(receipt['cache_unknown'])
        self.assertFalse(receipt['hardware_verified'])
        self.assertFalse(receipt['physical_identity_verified'])
        self.assertFalse(any(cmd.startswith(('DO ', 'PP ', 'NET ', 'PROJECT ')) for cmd in peer.commands))

    def test_cached_empty_stats_is_unknown_not_zero(self):
        receipt = apply_wireless_action(ActionPeer(OpStats='{}'), plan('cached-op-stats'))
        self.assertIsNone(receipt['values'])
        self.assertTrue(receipt['cache_unknown'])
        self.assertFalse(receipt['fresh_recall'])

    def test_recall_has_all_uint32_values_and_followup_cache_read(self):
        peer = ActionPeer()
        receipt = apply_wireless_action(peer, plan('recall-op-stats'), allow_physical_action=True)
        self.assertTrue(receipt['send_completed'])
        self.assertTrue(receipt['fresh_recall'])
        self.assertEqual(len(receipt['values']), 12)
        self.assertEqual(receipt['values']['TransmissionsNAKd'], 4294967295)
        self.assertEqual(peer.commands[-2:], ['DO ' + SOURCE + ' RecallOpStats', 'GET ' + SOURCE + ' OpStats'])

    def test_malformed_or_incomplete_statistics_fail(self):
        for value in ('{}', STATS.replace('4294967295', '4294967296'), STATS.replace('PacketsNAKd=2; ', ''),
                      STATS.replace('PacketsNAKd', 'PacketsNCAd'), STATS.replace('=2;', '=-2;'),
                      STATS.replace('PacketsNAKd', 'Injected')):
            peer = ActionPeer(OpStats=value)
            with self.subTest(value=value), self.assertRaises(WirelessActionApplyError) as failed:
                apply_wireless_action(peer, plan('recall-op-stats'), allow_physical_action=True)
            self.assertTrue(failed.exception.details['send_completed'])
            self.assertFalse(failed.exception.details['fresh_recall'])
            self.assertFalse(failed.exception.details['uncertain_send'])

    def test_reset_does_not_read_or_clear_old_cache(self):
        peer = ActionPeer()
        receipt = apply_wireless_action(peer, plan('reset-op-stats'), allow_physical_action=True)
        self.assertEqual(peer.commands[-1], 'DO ' + SOURCE + ' ResetOpStats')
        self.assertFalse(receipt['cache_invalidated'])
        self.assertFalse(receipt['reset_effect_verified'])
        self.assertFalse(receipt['fresh_recall'])
        self.assertEqual(peer.values['OpStats'], STATS)

    def test_mai_byte_fields_and_unknown_after_sync_refusal(self):
        peer = ActionPeer()
        receipt = apply_wireless_action(peer, plan('mai-sync'), allow_physical_action=True)
        self.assertEqual(receipt['values'], dict(ManufacturerCode=0, ProductClass=255, MediaType=2,
                                               ProcessSelector=6, FeatureSet=7))
        self.assertFalse(receipt['cli_replay_performed'])
        self.assertIn('not overridden', receipt['backend_retry_behavior'])
        for value in ('-1', '256', '01', 'unknown'):
            with self.subTest(value=value), self.assertRaises(WirelessActionApplyError):
                apply_wireless_action(ActionPeer(MediaType=value), plan('mai-sync'), allow_physical_action=True)

    def test_failed_and_uncertain_actions_stop_without_readback_replay_or_rollback(self):
        command = 'DO ' + SOURCE + ' RecallOpStats'
        for failure in (OSError('reply lost'), KeyboardInterrupt(),
                        response(408, '408 Operation failed: ' + SOURCE + ' (Op stats recall failed)'),
                        response(202, '408-Operation failed', '202 Done: ' + SOURCE),
                        response(202, '202 Done: //TEST/254/p/21'),
                        response(200, '200 OK')):
            peer = ActionPeer()
            peer.overrides[command] = failure
            with self.subTest(failure=failure), self.assertRaises(WirelessActionApplyError) as failed:
                apply_wireless_action(peer, plan('recall-op-stats'), allow_physical_action=True)
            self.assertEqual(peer.commands[-1], command)
            self.assertEqual(peer.commands.count(command), 1)
            self.assertTrue(failed.exception.details['command_attempted'])
            self.assertFalse(failed.exception.details['send_completed'])
            self.assertFalse(failed.exception.details['cli_replay_performed'])

    def test_native_project_xml_envelope_is_accepted_without_broadening_other_rows(self):
        peer = ActionPeer()
        rows = tuple('347-' + line for line in PROJECT.decode().splitlines())
        peer.overrides['DBGETXML //TEST'] = response(344, '343-Begin XML snippet', *rows, '344 End XML snippet')
        self.assertEqual(preview_wireless_action(peer, plan())['status'], 'verified-preview')
        self.assertFalse(any(command.startswith('DO ') for command in peer.commands))
        for prefix in ('343-Unknown header', '343-Begin XML snippet\n401 hidden', '202-Unrelated operation'):
            peer = ActionPeer()
            peer.overrides['DBGETXML //TEST'] = response(344, prefix, *rows, '344 End XML snippet')
            with self.subTest(prefix=prefix), self.assertRaises(WirelessActionApplyError):
                apply_wireless_action(peer, plan('reset-op-stats'), allow_physical_action=True)
            self.assertEqual(peer.commands, ['DBGETXML //TEST'])

    def test_correlation_and_embedded_error_rows_checked_for_all_reads(self):
        for command, reply in (
            ('GET ' + SOURCE + ' Type', response(300, '300 //TEST/254/p/21: Type=WGATE5F')),
            ('GET ' + SOURCE + ' Type', response(300, '420-Permission denied', '300 ' + SOURCE + ': Type=WGATE5F')),
            ('DBGETXML //TEST', response(344, '401-Unit not found', '347-' + PROJECT.decode(), '344 OK')),
            ('GET ' + SOURCE + ' UnitTemperature', response(300, '300 ' + SOURCE + ': Other=0'))):
            peer = ActionPeer()
            peer.overrides[command] = reply
            with self.subTest(command=command), self.assertRaises(WirelessActionApplyError):
                apply_wireless_action(peer, plan())
            self.assertEqual(peer.commands[-1], command)


if __name__ == '__main__':
    unittest.main()
