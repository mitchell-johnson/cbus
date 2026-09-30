"""Offline thermostat settings editor rules with a synthetic specification."""
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.thermostat_settings import NativeThermostatSettings, admitted, plan_settings
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.unitspec import UnitSpecStore

OUTPUTS = ('CoolActivation', 'CoolStage1', 'CoolStage2', 'CoolStage3', 'CoolFanLow', 'CoolFanMedium',
           'CoolFanHigh', 'HeatActivation', 'HeatStage1', 'HeatStage2', 'HeatStage3', 'HeatFanLow',
           'HeatFanMedium', 'HeatFanHigh')


def _spec(kind, names):
    params = []
    for index, name in enumerate(sorted(names)):
        maximum = '$1F' if 'Zones' in name else '$FF'
        params.append(f'<Param><Name>{name}</Name><Type>int</Type><ProgramMethod>sgiu</ProgramMethod>'
                      f'<Address>${0x100 + index:X}</Address><Protection>none</Protection><MinValue>$00</MinValue>'
                      f'<MaxValue>{maximum}</MaxValue><DefaultValue>0</DefaultValue></Param>')
    return ('<?xml version="1.0"?><UnitSpecification><Type>' + kind + '</Type><MinVersion>0</MinVersion>'
            '<MaxVersion>9</MaxVersion><Parameters>' + ''.join(params) + '</Parameters></UnitSpecification>')


def snapshot(**changes):
    values = {name: 0 for name in admitted('programmable') + admitted('basic')}
    values.update({name + 'Output': 255 for name in OUTPUTS})
    values.update(InternalPlantType=3, InternalPlantModes=0x1e, VentPlantType=2, ControlledZones=1,
                  HeatingPlantFanSpeeds=1, CoolingPlantFanSpeeds=1, HeatingPlantFanSpeedControlEnable=1,
                  CoolingPlantFanSpeedControlEnable=1, InstalledZones=31, EnableHVACRelayDrive=0)
    values.update(changes)
    return {name: hex(value) for name, value in values.items()}


class ThermostatSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.root = root
        names = set(snapshot())
        (root / 'THERMOSTATA.xml').write_text(_spec('THERMOSTATA', names - {'TimerEnable'}))
        (root / 'THERMOSTATB.xml').write_text(_spec('THERMOSTATB', names - set(admitted('programmable'))
                                                    | set(admitted('basic')) | {n + 'Output' for n in OUTPUTS}))
        self.store = UnitSpecStore(root)

    def test_zone_and_plant_edits_plan_changes(self):
        plan = plan_settings(self.store, 'PC_TSA', snapshot(), {'ControlledZones': '7', 'InternalPlantZones': 3,
                                                                  'HeatingPlantStages': '2'})
        rows = {row['name']: row['after'] for row in plan.as_dict()['changed_parameters']}
        self.assertEqual(rows, {'ControlledZones': 7, 'InternalPlantZones': 3, 'HeatingPlantStages': 2})
        self.assertFalse(plan.as_dict()['dialog_enable_rules_reproduced'])
        rules = plan.as_dict()['dialog_rule_subset']
        self.assertTrue(rules['available'])
        self.assertEqual(rules['used_zones'], 3)
        self.assertFalse(rules['dialog_enable_rules_reproduced'])

    def test_range_family_and_admission_refusals(self):
        for edits in ({'InstalledZones': 32}, {'Nope': 1}, {'TimerEnable': 1}, {'ControlledZones': True},
                      {'EvapProgramEnabled': 2}, {}):
            with self.subTest(edits=edits), self.assertRaises(ThermostatTemplateError):
                plan_settings(self.store, 'PC_TSA', snapshot(), edits)
        plan_settings(self.store, 'PC_TSB', snapshot(), {'TimerEnable': 1})
        with self.assertRaises(ThermostatTemplateError):
            plan_settings(self.store, 'PC_TSB', snapshot(), {'SendInterval': 1})
        with self.assertRaises(ThermostatTemplateError):
            plan_settings(self.store, 'KEY4', snapshot(), {'ControlledZones': 1})

    def test_values_the_original_form_save_would_rewrite_are_refused(self):
        with self.assertRaisesRegex(ThermostatTemplateError, 'HeatingPlantFanOnDelay=12'):
            plan_settings(self.store, 'PC_TSA', snapshot(), {'HeatingPlantFanOnDelay': 13})
        plan_settings(self.store, 'PC_TSA', snapshot(), {'HeatingPlantFanOnDelay': 12})
        # Evaporative internal plant doubles damper modulation.
        with self.assertRaisesRegex(ThermostatTemplateError, 'DamperModulationEnable=2'):
            plan_settings(self.store, 'PC_TSA', snapshot(InternalPlantType=2), {'DamperModulationEnable': 1})
        plan = plan_settings(self.store, 'PC_TSA', snapshot(InternalPlantType=2), {'DamperModulationEnable': 2})
        self.assertEqual(plan.expected, {'DamperModulationEnable': 2})
        # Removing the vent mode on a master makes the next form save zero the fan speeds.
        plan = plan_settings(self.store, 'PC_TSA', snapshot(), {'InternalPlantModes': 0x0e})
        dependent = {row['name']: row['form_save'] for row in plan.as_dict()['dependent_form_save_changes']}
        self.assertEqual(dependent['HeatingPlantFanSpeeds'], 0)

    def test_dependent_changes_are_expected_and_an_unchanged_edit_is_not_a_noop(self):
        # Literal expectations from BeforeSave's heating-only master branch;
        # the requested PlantCycleTime is already set, but saving normalises
        # untouched fan flags/speeds, the opposite default and both delays.
        before = snapshot(InternalPlantModes=2, VentPlantType=0,
                          HeatingPlantFanDefaultSpeed=3, CoolingPlantFanDefaultSpeed=2,
                          HeatingPlantFanOnDelay=15, CoolingPlantFanOffDelay=21,
                          EvapProgramEnabled=3, NonEvapProgramEnabled=3)
        plan = plan_settings(self.store, 'PC_TSA', before, {'PlantCycleTime': 0})
        expected = {'PlantCycleTime': 0, 'HeatingPlantFanSpeedControlEnable': 0,
                    'CoolingPlantFanSpeedControlEnable': 0, 'HeatingPlantFanSpeeds': 0,
                    'CoolingPlantFanSpeeds': 0, 'CoolingPlantFanDefaultSpeed': 3,
                    'HeatingPlantFanOnDelay': 12, 'CoolingPlantFanOffDelay': 24,
                    'EvapProgramEnabled': 0, 'NonEvapProgramEnabled': 1}
        self.assertEqual(plan.expected, expected)
        self.assertEqual({r['name']: r['after'] for r in plan.as_dict()['changed_parameters']},
                         {n: v for n, v in expected.items() if n != 'PlantCycleTime'})
        after = before | {n: hex(v) for n, v in expected.items()}
        again = plan_settings(self.store, 'PC_TSA', after, {'PlantCycleTime': 0})
        self.assertEqual(again.dependent, ())
        self.assertEqual(again.as_dict()['changed_parameters'], [])

    def test_dependent_and_unrelated_values_are_verified_separately(self):
        before = snapshot(HeatingPlantFanOnDelay=13)
        settings = plan_settings(self.store, 'PC_TSA', before, {'PlantCycleTime': 0})
        # _changed is pure: no client, PP session or project needed.
        from types import SimpleNamespace
        plan = SimpleNamespace(settings=settings)
        manager = object.__new__(NativeThermostatSettings)
        self.assertEqual(manager._changed(plan, before),
                         {'setting_mismatches': ['HeatingPlantFanOnDelay'], 'unrelated_changes': []})
        after = before | {'HeatingPlantFanOnDelay': '0xc'}
        self.assertEqual(manager._changed(plan, after),
                         {'setting_mismatches': [], 'unrelated_changes': []})
        self.assertEqual(manager._changed(plan, after | {'SetbackLevel': '3'})['unrelated_changes'],
                         ['SetbackLevel'])

    def test_scalar_normalization_and_slave_fields_are_in_the_save(self):
        before = snapshot(DisplayBacklightIdleBrightness=1, DisplayBacklightActiveBrightness=128,
                          KeyBacklightIdleBrightness=254, BeepEnable=3, VariableFanCoilEnable=2,
                          TemperatureUnits=2, TimeUnits=2, SendInterval=7,
                          EnableHVACRelayDrive=1, ControlledZones=0, InternalPlantZones=3)
        plan = plan_settings(self.store, 'PC_TSA', before, {'PlantCycleTime': 0})
        expected = {'DisplayBacklightIdleBrightness': 2, 'DisplayBacklightActiveBrightness': 127,
                    'KeyBacklightIdleBrightness': 255, 'BeepEnable': 1, 'VariableFanCoilEnable': 1,
                    'TemperatureUnits': 0, 'TimeUnits': 0, 'SendInterval': 2,
                    'EnableHVACRelayDrive': 0, 'InternalPlantType': 0, 'InternalPlantZones': 0,
                    'PlantCycleTime': 0}
        self.assertEqual(plan.expected, expected)
        for edit, correction in (({'DisplayBacklightIdleBrightness': 1}, 'Brightness=2'),
                                  ({'TemperatureUnits': 2}, 'TemperatureUnits=0'),
                                  ({'BeepEnable': 2}, 'BeepEnable=1'),
                                  ({'InternalPlantZones': 1}, 'InternalPlantZones=0')):
            with self.subTest(edit=edit), self.assertRaisesRegex(ThermostatTemplateError, correction):
                plan_settings(self.store, 'PC_TSA', before, edit)
        basic = plan_settings(self.store, 'PC_TSB', snapshot(TimerEnable=9), {'PlantCycleTime': 0})
        self.assertEqual(basic.expected, {'PlantCycleTime': 0, 'TimerEnable': 1})

    def test_form_save_is_one_pass_even_when_another_save_would_change_again(self):
        before = snapshot(InternalPlantModes=20, VentPlantType=0,
                          HeatingPlantFanSpeeds=0, CoolingPlantFanSpeeds=0)
        first = plan_settings(self.store, 'PC_TSA', before, {'PlantCycleTime': 0})
        self.assertEqual(first.expected, {'PlantCycleTime': 0, 'CoolingPlantFanSpeeds': 1})
        after = before | {n: str(v) for n, v in first.expected.items()}
        second = plan_settings(self.store, 'PC_TSA', after, {'PlantCycleTime': 0})
        self.assertEqual(second.expected, {'PlantCycleTime': 0, 'HeatingPlantFanSpeeds': 1})
        slave = snapshot(ControlledZones=0, InternalPlantType=2, DamperModulationEnable=1)
        first = plan_settings(self.store, 'PC_TSA', slave, {'PlantCycleTime': 0})
        self.assertEqual(first.expected, {'PlantCycleTime': 0, 'InternalPlantType': 0,
                                         'DamperModulationEnable': 2})
        second = plan_settings(self.store, 'PC_TSA', slave | {n: str(v) for n, v in first.expected.items()},
                               {'PlantCycleTime': 0})
        self.assertEqual(second.expected, {'PlantCycleTime': 0, 'DamperModulationEnable': 0})
        with self.assertRaisesRegex(ThermostatTemplateError, 'InternalPlantType=8'):
            plan_settings(self.store, 'PC_TSA', snapshot(), {'InternalPlantType': 11})

    def test_missing_or_invalid_dependent_specification_is_refused(self):
        before = snapshot(HeatingPlantFanOnDelay=13)
        del before['HeatingPlantFanOnDelay']
        with self.assertRaisesRegex(ThermostatTemplateError, 'form-save dependency'):
            plan_settings(self.store, 'PC_TSA', before, {'PlantCycleTime': 0})
        before = snapshot()
        del before['PlantCycleTime']
        with self.assertRaisesRegex(ThermostatTemplateError, 'snapshot lacks'):
            plan_settings(self.store, 'PC_TSA', before, {'PlantCycleTime': 0})
        # A caller specification can be narrower than the original raw byte;
        # automatic save writes must obey it, as explicit edits already do.
        root = self.root
        text = (root / 'THERMOSTATA.xml').read_text()
        text = text.replace('<Name>HeatingPlantFanOnDelay</Name>',
                            '<Name>HeatingPlantFanOnDelayUnrecognised</Name>')
        (root / 'THERMOSTATA.xml').write_text(text)
        with self.assertRaisesRegex(ThermostatTemplateError, 'form-save setting'):
            plan_settings(UnitSpecStore(root), 'PC_TSA', snapshot(HeatingPlantFanOnDelay=13),
                          {'PlantCycleTime': 0})


if __name__ == '__main__':
    unittest.main()
