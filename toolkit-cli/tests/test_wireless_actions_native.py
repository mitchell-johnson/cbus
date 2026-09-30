"""Native cached wireless GET acceptance; every DO and sync command is forbidden.

This proves that database metadata does not materialize runtime caches and that
cached reads and the typed API reject that absence. Positive cache values and
reply grammar are supported separately by static source and synthetic peers.
No refresh, reset, recall, MAISync, network open, PP or physical action is allowed.
"""
import hashlib
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text


ENABLED = os.environ.get('CBUS_NATIVE_SERVICE_BACKEND') == 'local' and all(
    os.environ.get(name) for name in ('CBUS_LOCAL_CGATE_VENDOR', 'CBUS_CGATE_JAVA'))
STATUS = ('UnitTemperature', 'UnitSupplyVoltage', 'BackgroundSignalPower', 'LastPacketReceivedPower')
MAI = ('ManufacturerCode', 'ProductClass', 'MediaType', 'ProcessSelector', 'FeatureSet')


class CachedOnlyClient(CGateClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commands = []

    def command(self, command):
        allowed = ('PROJECT NEW ', 'PROJECT USE ', 'PROJECT CLOSE ', 'PROJECT SAVE ', 'PROJECT LOAD ', 'DBCREATENET ',
                   'DBADDSAFE ', 'DBSETSAFE ', 'DBGETXML ', 'GET ')
        if command != 'NET LOAD DB' and not command.startswith(allowed):
            raise AssertionError('Only synthetic setup and proven cached GET are admitted: ' + command)
        if command.startswith('GET '):
            words = command.split()
            fields = {'Type', 'Version', 'CatalogNumber', 'SerialNumber', 'OpStats',
                      'InterfaceState', 'TargetInterfaceState', 'SyncState',
                      *STATUS, *MAI}
            if len(words) != 3 or words[2] not in fields:
                raise AssertionError('GET is outside the source-reviewed cached property set')
        self.commands.append(command)
        return super().command(command)

    def command_document(self, *_):
        raise AssertionError('Cached acceptance does not submit native documents')


@unittest.skipUnless(ENABLED, 'Select an explicitly owned local native C-Gate for cached wireless GET acceptance')
class WirelessActionsNativeTest(unittest.TestCase):
    def test_database_units_do_not_invent_runtime_caches_or_trigger_physical_refresh(self):
        from research.local_cgate import LocalCGate
        service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        self.addCleanup(service.close)
        (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        service.start()
        name = 'WA' + uuid4().hex[:6].upper()
        network = f'//{name}/254'
        report = {'format': 'cbus-wireless-actions-native-cache-acceptance-v1',
                  'scope': 'Owned closed synthetic database units; runtime cache absent and cached GET returns 401',
                  'physical_actions_executed': False, 'physical_hardware_verified': False,
                  'original_toolkit_executed': False, 'fresh_measurements_verified': False,
                  'profiles': [], 'passed': False,
                  'executed_test_id': ('tests/test_wireless_actions_native.py::WirelessActionsNativeTest::'
                    'test_database_units_do_not_invent_runtime_caches_or_trigger_physical_refresh')}
        root = Path(__file__).resolve().parents[1]
        source_names = ('tests/test_wireless_actions_native.py', 'src/cbus_toolkit/wireless_commissioning.py',
                        'src/cbus_toolkit/wireless_actions.py')
        report['source_sha256'] = {path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                                   for path in source_names}
        with CachedOnlyClient('127.0.0.1', service.port, timeout=30) as client:
            report['greeting'] = client.greeting
            db = NativeDatabase(client)
            client.command('PROJECT NEW ' + name)
            try:
                db.create_network(name, 254, 'Synthetic', 'Cni', '127.0.0.1:29999')
                profiles = ((20, 'WGATE5F', '2.4.00', '5800WCGA'),
                            (21, 'WRM4R2', '2.4.00', '5854R4F2AA'),
                            (22, 'KEY4', '1.2.67', '5034N'))
                for address, unit_type, firmware, catalogue in profiles:
                    db.add(network, 'unit', address, f'Synthetic {address}')
                    path = f'{network}/p/{address}'
                    for field, value in (('UnitType', unit_type), ('UnitName', unit_type),
                                         ('FirmwareVersion', firmware), ('CatalogNumber', catalogue),
                                         ('SerialNumber', f'70179.{800 + address}')):
                        db.set(path + '/' + field, value)
                for action in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
                    client.command(f'PROJECT {action} {name}')
                client.command('NET LOAD DB')
                snapshot = db.get('//' + name, xml=True)
                before = xml_text(snapshot)
                report['project_xml_envelope'] = [
                    line for line in snapshot.lines if not line.startswith(('347-', '347 '))]
                for field, value in (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle')):
                    reply = client.command(f'GET {network} {field}')
                    self.assertEqual(reply.lines, (f'300 {network}: {field}={value}',))
                for address, unit_type, firmware, catalogue in profiles[:2]:
                    path = f'{network}/p/{address}'
                    responses = {}
                    metadata = xml_text(db.get(path, xml=True))
                    self.assertIn('<UnitType>' + unit_type + '</UnitType>', metadata)
                    self.assertIn('<FirmwareVersion>' + firmware + '</FirmwareVersion>', metadata)
                    for field in ('Type', 'Version', 'CatalogNumber', 'SerialNumber', *STATUS, *MAI, 'OpStats'):
                        with self.assertRaises(CGateError) as error:
                            client.command(f'GET {path} {field}')
                        response = error.exception.response
                        self.assertEqual(response.code, 401)
                        self.assertEqual(response.lines, (f'401 Bad object or device ID: {path} (Unit not found)',))
                        responses[field] = response.final.replace(name, 'SYNTH')
                    report['profiles'].append({'unit_type': unit_type, 'firmware': firmware,
                                               'catalog_number': catalogue, 'database_metadata_present': True,
                                               'runtime_unit_cache_present': False,
                                               'sanitized_responses': responses})
                with self.assertRaises(CGateError) as error:
                    client.command(f'GET {network}/p/23 UnitTemperature')
                self.assertEqual(error.exception.response.code, 401)
                from cbus_toolkit.wireless_actions import (
                    WirelessActionCatalogue, WirelessActionApplyError,
                    apply_wireless_action, plan_wireless_action,
                )
                from cbus_toolkit.wireless_project_remotes import FrozenRemoteProject
                catalogue = WirelessActionCatalogue.from_xml(
                    (Path(os.environ['CBUS_LOCAL_CGATE_VENDOR']) / 'unitspec/cbusunits.xml').read_bytes())
                project = FrozenRemoteProject.from_xml(before.encode())
                for address, unit_type, _, _ in profiles[:2]:
                    with self.subTest(unit_type=unit_type):
                        plan = plan_wireless_action(project, catalogue=catalogue, source_network=254,
                                                    unit_address=address, operation='cached-status')
                        with self.assertRaises(WirelessActionApplyError) as failure:
                            apply_wireless_action(client, plan)
                        self.assertIsInstance(failure.exception.__cause__, CGateError)
                        self.assertEqual(failure.exception.__cause__.response.code, 401)
                        self.assertEqual(failure.exception.details['stage'], 'preflight')
                        self.assertFalse(failure.exception.details['command_attempted'])
                        self.assertFalse(failure.exception.details['retry_performed'])
                report['typed_cached_api_refused_absent_runtime_before_action'] = True
                self.assertEqual(xml_text(db.get('//' + name, xml=True)), before)
                for field, value in (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle')):
                    reply = client.command(f'GET {network} {field}')
                    self.assertEqual(reply.lines, (f'300 {network}: {field}={value}',))
                report['project_unchanged'] = True
                report['network_closed_and_idle_before_and_after'] = True
                report['database_presence_does_not_establish_runtime_presence'] = True
                report['positive_cached_values_verified'] = False
                report['missing_unit_rejected_401'] = True
                report['do_sync_pp_network_open_commands'] = 0
                self.assertFalse(any(command.startswith(('DO ', 'PP ', 'NET OPEN', 'NET SYNC')) for command in client.commands))
                report['cached_get_commands'] = sum(command.startswith('GET ') for command in client.commands)
            finally:
                client.command('PROJECT CLOSE ' + name)
        report['service'] = {field: service.report[field] for field in (
            'vendor_jar_sha256', 'java_version', 'listener_ownership_verified', 'projects_adopted')}
        service.close()
        for field in ('cleanup_complete', 'process_exit_confirmed', 'work_removed'):
            self.assertTrue(service.report[field])
            report['service'][field] = service.report[field]
        report['passed'] = True
        if os.environ.get('CBUS_WIRELESS_ACTIONS_CACHE_REPORT'):
            Path(os.environ['CBUS_WIRELESS_ACTIONS_CACHE_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


class WirelessActionsSourceReceiptTest(unittest.TestCase):
    def test_source_proves_cached_reads_and_uint32_counters_without_physical_acceptance(self):
        folder = Path(__file__).resolve().parents[1] / 'research/fixtures'
        source = json.loads((folder / 'wireless-actions-cgate-source-review.json').read_text())
        self.assertEqual(source['command_contract']['success']['code'], 202)
        for field in ('status', 'mai', 'op_stats'):
            self.assertFalse(source['cache_contract'][field]['get_performs_physical_io'])
        self.assertEqual(source['cache_contract']['op_stats']['counter_range'], [0, 4294967295])
        self.assertEqual(len(source['inputs']['class_sha256']), 39)
        self.assertTrue(all(len(value) == 64 for value in source['inputs']['class_sha256'].values()))
        self.assertFalse(source['acceptance_boundary']['physical_actions_executed'])
        self.assertFalse(source['acceptance_boundary']['native_positive_cache_values_verified'])
        native = json.loads((folder / 'wireless-actions-native-acceptance.json').read_text())
        self.assertTrue(native['passed'])
        self.assertTrue(native['database_presence_does_not_establish_runtime_presence'])
        self.assertFalse(native['positive_cached_values_verified'])
        self.assertFalse(native['physical_actions_executed'])
        self.assertEqual(native['do_sync_pp_network_open_commands'], 0)
        self.assertTrue(native['project_unchanged'])
        self.assertTrue(native['network_closed_and_idle_before_and_after'])
        for row in native['profiles']:
            self.assertTrue(row['database_metadata_present'])
            self.assertFalse(row['runtime_unit_cache_present'])
        self.assertTrue(native['service']['cleanup_complete'])

    def test_guard_rejects_physical_commands_before_a_connection(self):
        client = CachedOnlyClient('127.0.0.1', 1)
        for command in ('DO //SYNTH/254/p/20 MAISync', 'DO //SYNTH/254/p/20 ResetOpStats',
                        'DO //SYNTH/254/p/20 RecallOpStats', 'DO //SYNTH/254/p/20 PSync',
                        'NET OPEN //SYNTH/254', 'NET SYNC //SYNTH/254', 'PP LOAD session //SYNTH/254/p/20',
                        'GET //SYNTH/254/p/20 *'):
            with self.subTest(command=command), self.assertRaises(AssertionError):
                client.command(command)
        self.assertEqual(client.commands, [])
        self.assertFalse(client.connected)


if __name__ == '__main__':
    unittest.main()
