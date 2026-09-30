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
from unittest.mock import patch
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
            expected = plan.settings.expected
            self.assertEqual({n: int(after[n], 0) for n in expected}, expected)
            self.assertEqual({n: v for n, v in after.items() if n not in expected},
                             {n: v for n, v in before.items() if n not in expected})
            again = NativeThermostatSettings(self.client, self.store)
            self.assertEqual(again.apply(again.plan(path, edits, exclusive_project=True))['state'],
                             'already_applied')
            self.evidence['cases'].append({'unit_type': unit_type, 'edits': edits,
                                           'dependent': plan.as_dict()['dependent_form_save_changes'],
                                           'state': result['state']})

    def test_untouched_fields_normalize_once_per_save_for_all_four_unit_types(self):
        # Expectations are literal translations of the pinned load/save blocks,
        # including the one-save heating-before-cooling fan read ordering.
        seed = {'InternalPlantModes': 20, 'VentPlantType': 0, 'ControlledZones': 1,
                'InternalPlantType': 2, 'DamperModulationEnable': 1,
                'HeatingPlantFanSpeeds': 0, 'CoolingPlantFanSpeeds': 0,
                'HeatingPlantFanSpeedControlEnable': 0, 'CoolingPlantFanSpeedControlEnable': 0,
                'HeatingPlantFanDefaultSpeed': 1, 'CoolingPlantFanDefaultSpeed': 1,
                'HeatingPlantFanOnDelay': 15, 'CoolingPlantFanOffDelay': 21,
                'DisplayBacklightIdleBrightness': 1, 'DisplayBacklightActiveBrightness': 128,
                'KeyBacklightIdleBrightness': 254, 'KeyBacklightActiveBrightness': 0,
                'BeepEnable': 3, 'VariableFanCoilEnable': 3, 'TemperatureUnits': 3,
                'EnableHVACRelayDrive': 1}
        first = {'CoolingPlantFanSpeeds': 1, 'HeatingPlantFanOnDelay': 12, 'CoolingPlantFanOffDelay': 24,
                 'DisplayBacklightIdleBrightness': 2, 'DisplayBacklightActiveBrightness': 127,
                 'KeyBacklightIdleBrightness': 255, 'BeepEnable': 1, 'VariableFanCoilEnable': 1,
                 'TemperatureUnits': 0, 'EnableHVACRelayDrive': 0, 'DamperModulationEnable': 2}
        for index, unit_type in enumerate(('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5')):
            family_type = unit_type.removesuffix('5')
            path = self.network + '/p/' + str(50 + index)
            self.database.create_unit(self.network, 50 + index, 'Normalize' + str(index), unit_type, '5.4.01',
                                      catalog_number=FAMILY[family_type][1])
            programmable = family_type == 'PC_TSA'
            family_seed = ({'TimeUnits': 3, 'SendInterval': 7, 'EvapProgramEnabled': 3,
                            'NonEvapProgramEnabled': 3} if programmable else {'TimerEnable': 3})
            family_first = ({'TimeUnits': 0, 'SendInterval': 2, 'EvapProgramEnabled': 0,
                             'NonEvapProgramEnabled': 1} if programmable else {'TimerEnable': 1})
            with Programmer(self.client).load(self.network, '/db' + path) as session:
                for name, value in (seed | family_seed).items():
                    session.set(name, str(value))
                session.save_to_source()
            for action in ('save', 'close', 'load'):
                self.projects.operation(action, self.project)
            before = self.values(path)
            edits = {'PlantCycleTime': int(before['PlantCycleTime'], 0)}
            expected = first | family_first | edits
            manager = NativeThermostatSettings(self.client, self.store)
            plan = manager.plan(path, edits, exclusive_project=True)
            self.assertEqual(plan.settings.expected, expected)
            result = manager.apply(plan)
            self.assertEqual(result['state'], 'verified_saved')
            after = self.values(path)
            self.assertEqual({n: int(after[n], 0) for n in expected}, expected)
            self.assertEqual(int(after['HeatingPlantFanSpeeds'], 0), 0)
            self.assertEqual({n: v for n, v in after.items() if n not in expected},
                             {n: v for n, v in before.items() if n not in expected})
            # Original first save reads cooling's loaded zero while saving
            # heating, then lifts cooling to one. A second form load/save
            # copies that one to heating; never converge by extra hidden saves.
            second = manager.plan(path, edits, exclusive_project=True)
            self.assertEqual(second.settings.expected, edits | {'HeatingPlantFanSpeeds': 1})
            self.assertEqual(manager.apply(second)['state'], 'verified_saved')
            third = manager.plan(path, edits, exclusive_project=True)
            self.assertEqual(manager.apply(third)['state'], 'already_applied')
            self.evidence['cases'].append({'unit_type': unit_type, 'seed': seed | family_seed,
                                           'first_expected': expected, 'first_state': result['state'],
                                           'second_expected': second.settings.expected,
                                           'third_state': 'already_applied',
                                           'unrelated_parameters_preserved': True})

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

    def test_hidden_stored_parameter_change_after_reload_fails_verification(self):
        path = self.unit(90, 'PC_TSA')
        for action in ('save', 'close', 'load'):
            self.projects.operation(action, self.project)
        manager = NativeThermostatSettings(self.client, self.store)
        before = self.values(path)
        plan = manager.plan(path, {'PlantCycleTime': (int(before['PlantCycleTime'], 0) + 1) % 256},
                            exclusive_project=True)
        original_read = manager._read

        def read_with_hidden_change(*args):
            text, identity, values = original_read(*args)
            if manager.last_evidence.get('target_save_confirmed'):
                text = text.replace('</Unit>', '<PP Name="UnreportedParameter" Value="1"/></Unit>')
            return text, identity, values

        # Inject only into returned native XML after a real save/reload: PP GET
        # cannot report this opaque stored field, but preservation must catch it.
        with patch.object(manager, '_read', side_effect=read_with_hidden_change):
            with self.assertRaises(Exception) as caught:
                manager.apply(plan)
        self.assertIsInstance(caught.exception.cause, ThermostatTemplateError)
        self.assertFalse(manager.last_evidence['unit_record_preserved'])
        self.assertTrue(manager.last_evidence['pp_save_confirmed'])
        self.assertTrue(manager.last_evidence['target_save_confirmed'])
        self.assertFalse(manager.last_evidence['persistence_verified'])
        self.evidence['raw_record_fault_injection'] = {
            'native_save_and_reload_completed': True, 'injected_only_into_readback': True,
            'hidden_pp_change_rejected': True, 'persistence_verified': False}


if __name__ == '__main__':
    unittest.main()
