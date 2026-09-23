"""Composed thermostat scheduling against an owned isolated C-Gate."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from uuid import uuid4
from xml.etree import ElementTree as ET

import cbus_toolkit
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.native_thermostat_scheduling import NativeThermostatScheduling
from cbus_toolkit.programming import Programmer, xml_text


FIELDS = ('RemoteScheduleOnGroup', 'RemoteScheduleOffGroup',
          'RemoteScheduleOverrideGroup', 'RemoteScheduleEnable',
          'EvapProgramEnabled', 'NonEvapProgramEnabled')


def owned_name(prefix):
    return prefix + uuid4().hex[:7].upper()


def project_xml(database, project):
    return xml_text(database.get('//' + project, xml=True))


def unit_element(text):
    node = ET.fromstring(text).find('./Project/Network/Unit')
    if node is None:
        raise AssertionError('Expected one native thermostat unit')
    return ET.tostring(node, encoding='unicode')


def groups(text):
    result = {}
    for group in ET.fromstring(text).findall('./Project/Network/Application/NetVar'):
        address = int(group.findtext('Address'))
        if address in result:
            raise AssertionError('Duplicate native NetVar address')
        levels = {}
        for level in group.findall('Level'):
            number = int(level.findtext('Address'))
            levels[number] = (int(level.attrib['Value']), level.findtext('TagName'),
                              level.findtext('OID'))
        result[address] = {'oid': group.findtext('OID'), 'tag': group.findtext('TagName'),
                           'levels': levels}
    return result


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR'),
                     'Select Java11/vendor for isolated native thermostat composition')
class NativeThermostatSchedulingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.addClassCleanup(cls.service.close)
        cls.evidence = {'format': 'native-thermostat-composition-integration-v1',
                        'service': cls.service.report, 'cases': [],
                        'physical_devices_accessed': False, 'cni_connections': []}
        cls.sentinel = socket.socket()
        cls.addClassCleanup(cls.finish)
        cls.sentinel.bind(('127.0.0.1', 0))
        cls.sentinel.listen(1)
        cls.sentinel.settimeout(0.05)
        (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        cls.service.start()

    @classmethod
    def finish(cls):
        first = None
        try:
            cls.service.close()
        except BaseException as error:
            first = error
        try:
            try:
                connection, peer = cls.sentinel.accept()
            except socket.timeout:
                pass
            else:
                cls.evidence['cni_connections'].append(list(peer))
                connection.close()
                raise AssertionError('Closed composition workflow connected to its CNI sentinel')
        except BaseException as error:
            if first is None:
                first = error
        finally:
            cls.sentinel.close()
        cls.evidence['cleanup_passed'] = first is None and cls.service.report['cleanup_complete']
        destination = os.environ.get('CBUS_THERMOSTAT_COMPOSITION_EVIDENCE')
        if destination:
            try:
                with Path(destination).open('x', encoding='utf-8') as stream:
                    json.dump(cls.evidence, stream, indent=2)
                    stream.write('\n')
            except BaseException as error:
                if first is None:
                    first = error
        if first is not None:
            raise first

    def setUp(self):
        self.client = CGateClient('127.0.0.1', self.service.port, timeout=5)
        self.addCleanup(self.client.close)
        self.client.connect()
        self.projects = NativeProjects(self.client)
        self.database = NativeDatabase(self.client)
        self.project = owned_name('C')
        self.projects.operation('new', self.project)
        self.network = '//' + self.project + '/254'
        self.unit = self.network + '/p/4'
        self.database.create_network(self.project, 254, 'OwnedOffline', 'Cni',
                                     '127.0.0.1:' + str(self.sentinel.getsockname()[1]))
        self.database.create_unit(self.network, 4, 'Owned Thermostat', 'PC_TSA', '4.6.00',
                                  catalog_number='5070THP,BK')
        self.reload()
        self.case = {'test': self._testMethodName, 'project': self.project}
        self.evidence['cases'].append(self.case)

    def reload(self):
        for action in ('save', 'close', 'load'):
            self.projects.operation(action, self.project)

    def configure(self, values):
        with Programmer(self.client).load(self.network, '/db' + self.unit) as session:
            before = session.values()
            for name, value in zip(FIELDS, values):
                session.set(name, str(value))
            session.save_to_source()
        self.reload()
        with Programmer(self.client).load(self.network, '/db' + self.unit) as session:
            actual = session.values()
        self.assertEqual({name: int(actual[name], 0) for name in FIELDS}, dict(zip(FIELDS, values)))
        self.assertEqual({name: value for name, value in actual.items() if name not in FIELDS},
                         {name: value for name, value in before.items() if name not in FIELDS})

    def test_manager_creates_application_three_groups_and_levels_with_one_target_save(self):
        self.configure((12, 13, 14, 0, 1, 0))
        before = project_xml(self.database, self.project)
        self.assertEqual(groups(before), {})
        manager = NativeThermostatScheduling(self.client)
        plan = manager.plan(self.unit, exclusive_project=True)
        self.assertEqual(plan.as_dict()['created_group_addresses'], [12, 13, 14])
        backup = owned_name('B')
        result = manager.apply(plan, backup_project=backup).as_dict()
        self.assertTrue(result['complete'] and result['persistence_verified'])
        self.assertTrue(result['unit_record_preserved'])
        self.assertEqual(result['target_project_save_count'], 1)
        after = project_xml(self.database, self.project)
        self.assertEqual(unit_element(after), unit_element(before))
        actual = groups(after)
        self.assertEqual(set(actual), {12, 13, 14})
        self.assertTrue(all(set(group['levels']) == set(range(1, 32))
                            for group in actual.values()))
        self.assertEqual(len({level[2] for group in actual.values()
                              for level in group['levels'].values()}), 93)
        self.projects.operation('load', backup)
        backup_xml = project_xml(self.database, backup)
        self.assertEqual(unit_element(backup_xml), unit_element(before))
        self.assertEqual(groups(backup_xml), {})
        self.case.update(complete=True, result=result, group_addresses=sorted(actual),
                         created_level_count=93, backup=backup)

    def test_public_cli_composes_shared_group_and_then_reports_noop(self):
        self.database.add(self.network, 'application', 203, 'Enable Control')
        self.database.add(self.network + '/203', 'netvar', 12, 'Shared Schedule')
        self.configure((12, 12, 12, 0, 1, 1))
        before = project_xml(self.database, self.project)
        command = [sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', '127.0.0.1',
                   '--port', str(self.service.port), 'thermostat-schedule-compose', self.unit,
                   '--exclusive-project']
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(Path(cbus_toolkit.__file__).resolve().parent.parent)

        def invoke(extra):
            process = subprocess.run(command + extra, capture_output=True, text=True, timeout=45,
                                     env=environment, stdin=subprocess.DEVNULL)
            self.assertEqual(process.returncode, 0, process.stderr)
            return json.loads(process.stdout)

        preview = invoke([])
        self.assertEqual(preview['created_group_addresses'], [])
        self.assertEqual(preview['created_level_addresses']['12'], list(range(1, 32)))
        self.assertEqual(project_xml(self.database, self.project), before)
        backup = owned_name('B')
        result = invoke(['--apply', '--backup-project', backup])
        self.assertTrue(result['persistence_verified'] and result['cli']['complete'])
        after = project_xml(self.database, self.project)
        self.assertEqual(unit_element(after), unit_element(before))
        self.assertEqual(set(groups(after)), {12})
        self.assertEqual(set(groups(after)[12]['levels']), set(range(1, 32)))
        noop = invoke(['--apply'])
        self.assertEqual(noop['state'], 'already_present')
        self.assertFalse(noop['target_mutation_attempted'])
        self.assertEqual(project_xml(self.database, self.project), after)
        self.case.update(complete=True, preview=preview, result=result, noop=noop,
                         group_addresses=[12], created_level_count=31, backup=backup)


if __name__ == '__main__':
    unittest.main()
