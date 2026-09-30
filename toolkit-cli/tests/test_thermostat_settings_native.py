"""Thermostat settings editor against an owned isolated C-Gate.

Covers THERMOSTATA (PC_TSA) and THERMOSTATB (PC_TSB) units including their
family-specific parameters.  Requires CBUS_CGATE_JAVA, CBUS_LOCAL_CGATE_VENDOR
and CBUS_UNITSPEC_DIR.
"""
import json
import os
from pathlib import Path
import socket
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.thermostat_settings import NativeThermostatSettings
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.unitspec import UnitSpecStore

SPEC_DIR = os.environ.get('CBUS_UNITSPEC_DIR')
COMMON = {'InstalledZones': 31, 'ControlledZones': 7, 'HeatingPlantInstalledZones': 3,
          'CoolingPlantInstalledZones': 0, 'MeasuredZones': 1, 'UIAllocatedZones': 5,
          'HeatingPlantType': 1, 'CoolingPlantType': 9, 'HeatingPlantStages': 2, 'CoolingPlantStages': 3,
          'PlantCycleTime': 20, 'CoolingPlantFanOnDelay': 12, 'KeyBacklightIdleBrightness': 255,
          'BacklightDimTime': 0, 'HeatCoolIntegralFactor': 150, 'TemperatureOffset': 254}
FAMILY = {'PC_TSA': ({'TimeUnits': 1, 'SendInterval': 6, 'EvapProgramEnabled': 1, 'NonEvapProgramEnabled': 1,
                      'ScheduleControlledZones': 3}, '5070THP,BK'),
          'PC_TSB': ({'TimerEnable': 0}, '5070THB,BK')}
UNRELATED = {'SetbackLevel': '3', 'BeepEnable': '0'}


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR')
                     and SPEC_DIR, 'Select Java11/vendor/unit specifications for native thermostat settings')
class NativeThermostatSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from research.local_cgate import LocalCGate
        cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        cls.sentinel = socket.socket()
        cls.addClassCleanup(cls.sentinel.close)
        cls.addClassCleanup(cls.finish)
        cls.addClassCleanup(cls.service.close)
        cls.sentinel.bind(('127.0.0.1', 0))
        cls.sentinel.listen(1)
        cls.sentinel.settimeout(0.05)
        (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        cls.evidence = {}
        cls.service.start()
        cls.evidence = {'format': 'native-thermostat-settings-integration-v1',
                        'service': cls.service.report, 'cases': [], 'physical_devices_accessed': False}

    @classmethod
    def finish(cls):
        try:
            connection, peer = cls.sentinel.accept()
        except socket.timeout:
            cls.evidence['cni_connections'] = []
        else:
            connection.close()
            raise AssertionError('Closed settings workflow connected to its CNI sentinel: ' + repr(peer))
        destination = os.environ.get('CBUS_THERMOSTAT_SETTINGS_EVIDENCE')
        if destination:
            with Path(destination).open('x', encoding='utf-8') as stream:
                json.dump(cls.evidence, stream, indent=2, default=str)
                stream.write('\n')

    def setUp(self):
        self.client = CGateClient('127.0.0.1', self.service.port, timeout=30)
        self.addCleanup(self.client.close)
        self.client.connect()
        self.projects, self.database = NativeProjects(self.client), NativeDatabase(self.client)
        self.project = 'T' + uuid4().hex[:7].upper()
        self.projects.operation('new', self.project)
        self.network = '//' + self.project + '/254'
        self.database.create_network(self.project, 254, 'OwnedOffline', 'Cni',
                                     '127.0.0.1:' + str(self.sentinel.getsockname()[1]))
        self.store = UnitSpecStore(SPEC_DIR)

    def values(self, path):
        with Programmer(self.client).load(self.network, '/db' + path) as session:
            return session.values()

    def unit(self, address, unit_type):
        path = self.network + '/p/' + str(address)
        self.database.create_unit(self.network, address, 'T' + str(address), unit_type, '5.4.01',
                                  catalog_number=FAMILY[unit_type][1])
        with Programmer(self.client).load(self.network, '/db' + path) as session:
            for name, value in UNRELATED.items():
                session.set(name, value)
            session.save_to_source()
        return path

    def test_family_settings_roundtrip_and_preserve_unrelated_values(self):
        paths = {unit_type: self.unit(20 + index, unit_type) for index, unit_type in enumerate(FAMILY)}
        for action in ('save', 'close', 'load'):
            self.projects.operation(action, self.project)
        for unit_type, path in paths.items():
            edits = dict(COMMON, **FAMILY[unit_type][0])
            before = self.values(path)
            manager = NativeThermostatSettings(self.client, self.store)
            plan = manager.plan(path, {n: str(v) for n, v in edits.items()}, exclusive_project=True)
            result = manager.apply(plan, backup_project='B' + uuid4().hex[:7].upper())
            self.assertEqual(result['state'], 'verified_saved', result)
            self.projects.operation('use', self.project)
            after = self.values(path)
            self.assertEqual({n: int(after[n], 0) for n in edits}, edits)
            self.assertEqual({n: v for n, v in after.items() if n not in edits},
                             {n: v for n, v in before.items() if n not in edits})
            again = NativeThermostatSettings(self.client, self.store)
            self.assertEqual(again.apply(again.plan(path, edits, exclusive_project=True))['state'],
                             'already_applied')
            self.evidence['cases'].append({'unit_type': unit_type, 'edits': edits,
                                           'dependent': plan.as_dict()['dependent_form_save_changes'],
                                           'state': result['state']})

    def test_invalid_family_and_form_save_refusals_do_not_write(self):
        a, b = self.unit(30, 'PC_TSA'), self.unit(31, 'PC_TSB')
        for action in ('save', 'close', 'load'):
            self.projects.operation(action, self.project)
        before = xml_text(self.database.get('//' + self.project, xml=True))
        refusals = []
        for path, edits in ((a, {'InstalledZones': '32'}), (a, {'TimerEnable': '1'}), (b, {'SendInterval': '1'}),
                            (a, {'HeatingPlantFanOnDelay': '13'}), (a, {'EvapProgramEnabled': '2'}),
                            (b, {'CoolStage1Output': '4'})):
            manager = NativeThermostatSettings(self.client, self.store)
            with self.assertRaises(Exception) as caught:
                manager.plan(path, edits, exclusive_project=True)
            self.assertIsInstance(caught.exception.cause, ThermostatTemplateError)
            refusals.append({'path': path, 'edits': edits, 'error': str(caught.exception.cause)})
        self.assertEqual(xml_text(self.database.get('//' + self.project, xml=True)), before)
        self.evidence['refusals'] = refusals


if __name__ == '__main__':
    unittest.main()
