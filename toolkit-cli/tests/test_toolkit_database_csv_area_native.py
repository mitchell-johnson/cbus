"""Opt-in owned C-Gate acceptance for captured B03 Area creation."""
import json
import os
from pathlib import Path
import socket
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import quote_value
from cbus_toolkit.toolkit_database_csv import COLUMNS
from cbus_toolkit.toolkit_database_csv_area import NativeCSVAreaGroups
from cbus_toolkit.toolkit_database_csv_native import project_native_xml_unit
from research.local_cgate import LocalCGate


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA'),
                     'set CBUS_CGATE_JAVA to an explicit Java 11 runtime')
class NativeMissingAreaGroupTests(unittest.TestCase):
    def test_owned_b03_backup_create_save_reload_project_and_cleanup(self):
        root = Path(__file__).resolve().parents[1]
        vendor = Path(os.environ.get('CBUS_LOCAL_CGATE_VENDOR',
                                     root / 'research/vendor/cgate/app'))
        project = 'A' + uuid4().hex[:7].upper()
        backup = 'B' + project[1:]
        network = f'//{project}/254'; unit = network + '/p/4'
        sentinel = socket.socket(); sentinel.bind(('127.0.0.1', 0))
        sentinel.listen(1); sentinel.setblocking(False)
        service = LocalCGate(vendor, java=os.environ['CBUS_CGATE_JAVA'])
        (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        client = None; created = backup_created = False
        report = {'format': 'csv-native-missing-area-acceptance-v1',
                  'passed': False, 'project': project, 'backup': backup,
                  'commands': [], 'cleanup_errors': []}
        try:
            service.start()
            client = CGateClient('127.0.0.1', service.port, timeout=20)
            client.connect(); projects = NativeProjects(client); database = NativeDatabase(client)
            def command(text):
                response = client.command(text)
                report['commands'].append(text)
                return response
            command('PROJECT NEW ' + project); created = True
            command('PROJECT USE ' + project)
            command(f'DBCREATENET 254 OwnedNet Cni 127.0.0.1:{sentinel.getsockname()[1]}')
            command('NET LOAD DB')
            command(f'DBADDSAFE {network} Application 56 Lighting')
            for address in (*range(1, 9), 12, 255):
                command(f'DBADDSAFE {network}/56 Group {address} ' +
                        ('<Unused>' if address == 255 else 'Group' + str(address)))
            command(f'DBADDSAFE {network} Unit 4 OwnedUnit')
            for name, value in (('UnitType', 'RELAY4'), ('UnitName', 'NativeUnit'),
                                ('FirmwareVersion', '4.4'), ('CatalogNumber', 'OWNED'),
                                ('SerialNumber', '1.2.3')):
                command(f'DBSETSAFE {unit}/{name} {value}')
            command('PP LOCK CSVLOCK ' + network); command('PP START CSVSESSION CSVLOCK')
            command('PP LOAD CSVSESSION /db' + unit); command('PP RESET_TO_DEFAULTS CSVSESSION')
            for name, value in (('UnitAddress', '4'), ('Application', '56 255'),
                                ('Project', project), ('UnitName', 'NATUNIT'),
                                ('AreaGroupAddress', '13'),
                                ('GroupAddress', '1 2 3 4 5 6 7 8 ' + ' '.join(['255'] * 8))):
                command(f'PP SET CSVSESSION {name} {quote_value(value)}')
            command('PP SAVE_TO_SOURCE CSVSESSION'); command('PP END CSVSESSION')
            command('PP UNLOCK CSVLOCK'); command('PROJECT SAVE ' + project)
            command('PROJECT CLOSE ' + project); command('PROJECT LOAD ' + project)

            manager = NativeCSVAreaGroups(client)
            result = manager.apply(manager.plan(unit), backup_project=backup)
            backup_created = True
            projected = project_native_xml_unit(result.final_xml, unit, columns=COLUMNS)
            self.assertTrue(result.as_dict()['reload_verified'])
            self.assertIn(',Group 13,', projected.report.rows[1])
            self.assertEqual(projected.cached.selected_class, 'TRELAY4')
            report.update(result=result.as_dict(), row=projected.report.rows[1],
                          passed=True, physical_device_accessed=False)
        finally:
            if client is not None and client.connected:
                for text in (('PROJECT CLOSE ' + project, 'PROJECT DELETE ' + project)
                             if created else ()):
                    try: client.command(text)
                    except BaseException as error: report['cleanup_errors'].append(type(error).__name__)
                if backup_created:
                    try: client.command('PROJECT DELETE ' + backup)
                    except BaseException as error: report['cleanup_errors'].append(type(error).__name__)
                try: client.close()
                except BaseException as error: report['cleanup_errors'].append(type(error).__name__)
            try:
                service_report = service.close()
                report['service_cleanup_complete'] = service_report['cleanup_complete']
            except BaseException as error:
                report['cleanup_errors'].append(type(error).__name__)
                report['service_cleanup_complete'] = False
            try:
                peer, _address = sentinel.accept(); peer.close()
                report['sentinel_connections'] = 1
            except BlockingIOError:
                report['sentinel_connections'] = 0
            finally:
                sentinel.close()
            if os.environ.get('CBUS_CSV_AREA_REPORT'):
                Path(os.environ['CBUS_CSV_AREA_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
        self.assertTrue(report['passed'])
        self.assertTrue(report['service_cleanup_complete'])
        self.assertEqual(report['sentinel_connections'], 0)
        self.assertEqual(report['cleanup_errors'], [])


if __name__ == '__main__':
    unittest.main()
