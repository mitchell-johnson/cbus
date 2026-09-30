"""Offline replay of the original thermostat Load Template post-load pipeline.

Expected values below are derived by hand from the recovered routines
(docs/thermostat-templates.md), not from the module tables.
"""
import unittest

from cbus_toolkit.thermostat_post_load import (ThermostatPostLoadError, damper_modulation_save,
                                               form_save_fans, replay_post_load, virtual_plant_type)

OUTPUTS = ('CoolActivation', 'CoolStage1', 'CoolStage2', 'CoolStage3', 'CoolFanLow', 'CoolFanMedium',
           'CoolFanHigh', 'HeatActivation', 'HeatStage1', 'HeatStage2', 'HeatStage3', 'HeatFanLow',
           'HeatFanMedium', 'HeatFanHigh', 'DamperZone1', 'DamperZone2', 'DamperZone3', 'DamperZone4')


def values(**changes):
    result = {name + 'Output': 255 for name in OUTPUTS}
    result.update({f'InternalRelay{n}GroupNumber': 255 for n in range(1, 6)})
    for side in ('Heating', 'Cooling'):
        result.update({side + 'PlantFanSpeedControlEnable': 0, side + 'PlantFanSpeeds': 1,
                       side + 'PlantFanDefaultSpeed': 1, side + 'PlantFanOnDelay': 0,
                       side + 'PlantFanOffDelay': 0, side + 'PlantFanEnable': 1})
    result.update(InternalPlantType=3, InternalPlantModes=0x1e, VentPlantType=2, ZoneGroup=1,
                  ControlledZones=1, DamperModulationEnable=0, EvapProgramEnabled=0,
                  NonEvapProgramEnabled=0, InternalPlantZones=1)
    result.update(changes)
    return result


class PostLoadReplayTests(unittest.TestCase):
    def test_basic_reverse_cycle_assigns_cool_activation_and_creates_prefixed_groups(self):
        loaded = values(CoolStage1Output=1, CoolFanLowOutput=3, HeatActivationOutput=4, HeatStage1Output=1,
                        HeatFanLowOutput=3, InternalRelay1GroupNumber=1, InternalRelay3GroupNumber=3,
                        InternalRelay4GroupNumber=4)
        replay = replay_post_load(loaded, 'programmable', 1, {})
        self.assertEqual(replay.virtual_plant_type, 3)
        self.assertEqual(replay.prefix, '[CG01]')
        expected = replay.expected
        self.assertEqual(expected['CoolActivationOutput'], 2)
        self.assertEqual(expected['InternalRelay2GroupNumber'], 2)
        self.assertEqual([expected[n] for n in ('CoolStage1Output', 'HeatStage1Output', 'HeatFanLowOutput')],
                         [1, 1, 3])
        self.assertEqual({(op.action, op.address, op.tag) for op in replay.group_operations},
                         {('create', 255, '<Unused>'), ('create', 1, '[CG01] Y (heat/cool)'),
                          ('create', 3, '[CG01] G (fan)'), ('create', 4, '[CG01] B (heat activation)'),
                          ('create', 2, '[CG01] B (cool activation)')})
        self.assertEqual(expected['InstallationCode'], 1)
        self.assertEqual(expected['EvapProgramEnabled'], 0)

    def test_zoned_two_stage_uses_installation_specific_names(self):
        loaded = values(CoolStage1Output=1, CoolStage2Output=2, CoolFanLowOutput=3, CoolFanMediumOutput=5,
                        HeatActivationOutput=4, HeatStage1Output=1, HeatStage2Output=2)
        replay = replay_post_load(loaded, 'basic', 3, {})
        tags = {op.address: op.tag for op in replay.group_operations}
        self.assertEqual(tags[1], '[CG01] Y1 (cool/heat)')
        self.assertEqual(tags[5], '[CG01] Heat/cool fan speed')
        self.assertEqual(replay.expected['InternalRelay5GroupNumber'], 5)
        self.assertEqual(replay.expected['DamperZone1Output'], 255)  # basic class: no damper groups

    def test_virtual_fan_coil_plant_and_its_fan_and_modulation_save(self):
        self.assertEqual(virtual_plant_type(values(InternalPlantType=8)), 8)
        loaded = values(InternalPlantType=8, CoolStage1Output=1, CoolStage2Output=2, CoolStage3Output=5,
                        CoolFanLowOutput=3, CoolFanMediumOutput=4, InternalPlantModes=0x14,
                        DamperModulationEnable=7)
        self.assertEqual(virtual_plant_type(loaded), 11)
        replay = replay_post_load(loaded, 'programmable', 6, {})
        expected = replay.expected
        self.assertEqual(expected['InternalPlantType'], 8)
        self.assertEqual(expected['InternalRelay5GroupNumber'], 5)
        # Cooling-only modes with vent: heating fan settings copy the cooling ones.
        self.assertEqual((expected['HeatingPlantFanSpeedControlEnable'], expected['HeatingPlantFanSpeeds'],
                          expected['HeatingPlantFanEnable']), (1, 2, 0))
        self.assertEqual(expected['DamperModulationEnable'], 1)
        self.assertEqual(damper_modulation_save(9, 2), 2)
        self.assertEqual(damper_modulation_save(1, 6), 3)
        self.assertEqual(damper_modulation_save(1, 0), 0)
        self.assertEqual(damper_modulation_save(0, 10), 0)

    def test_evaporative_plant_clears_both_program_flags(self):
        loaded = values(InternalPlantType=2, EvapProgramEnabled=1, NonEvapProgramEnabled=1,
                        CoolStage1Output=1, CoolStage3Output=2, CoolFanLowOutput=3, CoolFanMediumOutput=4,
                        HeatActivationOutput=4)
        expected = replay_post_load(loaded, 'programmable', 5, {}).expected
        self.assertEqual((expected['EvapProgramEnabled'], expected['NonEvapProgramEnabled']), (0, 0))
        self.assertEqual(expected['HeatActivationOutput'], 255)
        loaded = values(NonEvapProgramEnabled=9, CoolStage1Output=1, CoolFanLowOutput=3, HeatActivationOutput=4)
        self.assertEqual(replay_post_load(loaded, 'programmable', 1, {}).expected['NonEvapProgramEnabled'], 1)
        self.assertNotIn('EvapProgramEnabled', replay_post_load(loaded, 'basic', 1, {}).expected)

    def test_slave_writes_restricted_plant_and_unused_dampers(self):
        loaded = values(ControlledZones=0, DamperZone1Output=20, CoolStage1Output=1, CoolFanLowOutput=3,
                        HeatActivationOutput=4)
        expected = replay_post_load(loaded, 'programmable', 2, {}).expected
        self.assertEqual((expected['InternalPlantType'], expected['InternalPlantZones']), (0, 0))
        self.assertEqual(expected['DamperZone1Output'], 255)

    def test_existing_groups_are_reused_or_refused(self):
        loaded = values(CoolStage1Output=1, CoolFanLowOutput=3, HeatActivationOutput=4)
        kept = replay_post_load(loaded, 'programmable', 1, {9: 'Lounge', 255: 'Spare'})
        self.assertNotIn(255, [op.address for op in kept.group_operations])
        with self.assertRaisesRegex(ThermostatPostLoadError, 'GetNewGroup'):
            replay_post_load(loaded, 'programmable', 1, {2: 'Lounge'})
        with self.assertRaisesRegex(ThermostatPostLoadError, 'CG01'):
            replay_post_load(loaded, 'programmable', 1, {7: '[CG01] Old'})
        with self.assertRaisesRegex(ThermostatPostLoadError, 'Relay'):
            replay_post_load(dict(loaded, InternalRelay2GroupNumber=8), 'programmable', 1, {})
        # AfterLoad keeps an unprefixed group at a loaded address, so the
        # later reassignment would need the unreplayed GetNewGroup search.
        with self.assertRaisesRegex(ThermostatPostLoadError, 'GetNewGroup'):
            replay_post_load(loaded, 'programmable', 1, {3: 'Fan'})

    def test_form_save_fan_rules(self):
        # Heating-only plant without vent mode on a master: speed control and speeds are zeroed.
        heat = values(InternalPlantModes=0x02, VentPlantType=0, HeatingPlantFanSpeedControlEnable=1,
                      HeatingPlantFanSpeeds=3, HeatingPlantFanOnDelay=13, CoolingPlantFanSpeeds=2)
        saved = form_save_fans(heat)
        self.assertEqual((saved['HeatingPlantFanSpeedControlEnable'], saved['HeatingPlantFanSpeeds']), (0, 0))
        self.assertEqual(saved['HeatingPlantFanOnDelay'], 12)  # Round(13/6)*6
        self.assertEqual((saved['CoolingPlantFanSpeedControlEnable'], saved['CoolingPlantFanSpeeds']), (0, 0))
        # A slave keeps its own values and lifts zero speeds for an enabled mode.
        slave = form_save_fans(dict(heat, ControlledZones=0, HeatingPlantFanSpeeds=0))
        self.assertEqual((slave['HeatingPlantFanSpeedControlEnable'], slave['HeatingPlantFanSpeeds']), (1, 1))
        self.assertEqual(form_save_fans(dict(heat, HeatingPlantFanOnDelay=15))['HeatingPlantFanOnDelay'], 12)
        self.assertEqual(form_save_fans(dict(heat, HeatingPlantFanOnDelay=21))['HeatingPlantFanOnDelay'], 24)


if __name__ == '__main__':
    unittest.main()
