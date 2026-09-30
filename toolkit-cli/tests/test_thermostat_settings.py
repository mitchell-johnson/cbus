"""Offline thermostat settings editor rules with a synthetic specification."""
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.thermostat_settings import admitted, plan_settings
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
                  CoolingPlantFanSpeedControlEnable=1, InstalledZones=31)
    values.update(changes)
    return {name: hex(value) for name, value in values.items()}


class ThermostatSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
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


if __name__ == '__main__':
    unittest.main()
