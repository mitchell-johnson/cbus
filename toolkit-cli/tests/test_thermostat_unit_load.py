import json
from pathlib import Path
import unittest

from cbus_toolkit.thermostat_unit_load import (
    ThermostatLoadGroup, ThermostatUnitLoader,
)


ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / 'research/fixtures/thermostat-unit-load-original-vectors.json'


class ThermostatUnitLoadTests(unittest.TestCase):
    def test_twelve_original_afterload_outcomes(self):
        cases = json.loads(VECTORS.read_text())
        self.assertEqual([case['id'] for case in cases], [f'L{i:02}' for i in range(1, 13)])
        for case in cases:
            with self.subTest(case=case['id']):
                groups = tuple(ThermostatLoadGroup(**group) for group in case['groups'])
                result = ThermostatUnitLoader().load(case['raw'],
                    application_present=case['application_present'], groups=groups,
                    group_name='Fixture Group', unused_name='Fixture Unused')
                actual = result.as_dict()
                self.assertEqual({key: actual[key] for key in case['expected']}, case['expected'])

    def test_remote_raw_byte_is_overwritten_after_asymmetric_normalization(self):
        raw = {'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13,
               'RemoteScheduleOverrideGroup': 14, 'RemoteScheduleEnable': 255,
               'EvapProgramEnabled': 2, 'NonEvapProgramEnabled': 0}
        result = ThermostatUnitLoader().load(raw, application_present=True)
        self.assertFalse(result.remote)
        self.assertEqual(result.normalized_flags, (0, 0))
        raw['NonEvapProgramEnabled'] = 255
        result = ThermostatUnitLoader().load(raw, application_present=True)
        self.assertTrue(result.remote)
        self.assertEqual(result.normalized_flags, (0, 1))

    def test_disabled_load_creates_application_but_not_missing_unused_group(self):
        raw = {name: 0 for name in ('RemoteScheduleOnGroup', 'RemoteScheduleOffGroup',
            'RemoteScheduleOverrideGroup', 'RemoteScheduleEnable', 'EvapProgramEnabled',
            'NonEvapProgramEnabled')}
        result = ThermostatUnitLoader().load(raw, application_present=False)
        self.assertTrue(result.application_created)
        self.assertEqual(result.saved, ('application',))
        self.assertEqual(result.roles, (None, None, None))
        self.assertEqual(result.groups, ())

    def test_scheduling_state_bridges_to_existing_cli_schema(self):
        raw = {'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 12,
               'RemoteScheduleOverrideGroup': 12, 'RemoteScheduleEnable': 0,
               'EvapProgramEnabled': 1, 'NonEvapProgramEnabled': 0}
        result = ThermostatUnitLoader().load(raw, application_present=True,
            groups=(ThermostatLoadGroup('shared', 12, 'Existing'),))
        self.assertEqual(result.scheduling_state(), {
            'groups': [{'identity': 'shared', 'address': 12, 'levels': []}],
            'roles': {'on': 'shared', 'off': 'shared', 'override': 'shared'},
            'enabled': True})

    def test_strict_input_and_detached_group_collection(self):
        raw = {'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13,
               'RemoteScheduleOverrideGroup': 14, 'RemoteScheduleEnable': 0,
               'EvapProgramEnabled': 1, 'NonEvapProgramEnabled': 0}
        groups = [ThermostatLoadGroup('kept', 12, 'Existing')]
        result = ThermostatUnitLoader().load(raw, application_present=True, groups=groups)
        groups.clear();raw['EvapProgramEnabled'] = 0
        self.assertEqual(result.groups[0].identity, 'kept')
        self.assertTrue(result.remote)
        for change in (
            lambda value: value.pop('RemoteScheduleEnable'),
            lambda value: value.__setitem__('EvapProgramEnabled', True),
            lambda value: value.__setitem__('NonEvapProgramEnabled', 256)):
            invalid = {'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13,
                'RemoteScheduleOverrideGroup': 14, 'RemoteScheduleEnable': 0,
                'EvapProgramEnabled': 1, 'NonEvapProgramEnabled': 0}
            change(invalid)
            with self.assertRaises(ValueError):
                ThermostatUnitLoader().load(invalid, application_present=True)


if __name__ == '__main__':
    unittest.main()
