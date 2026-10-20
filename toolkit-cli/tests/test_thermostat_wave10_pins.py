"""Wave 10 narrow offline pins for P5-P6 thermostat guards (issue #42).

Each method pins ONE pure-offline branch using plain values only: no
hardware, vendor EXE, C-Gate server, decoded vendor spec, or PP session.
Covers modules thermostat_settings.py and thermostat_post_load.py only.
Complements round 13 (group-sort/setback guards) with the adjacent
virtual-plant, damper-factor, scalar-save, preference/admission and
post-load table/prefix guards.
"""
from __future__ import annotations

import unittest

from cbus_toolkit import thermostat_post_load as post_load
from cbus_toolkit import thermostat_settings as settings
from cbus_toolkit.thermostat_post_load import ThermostatPostLoadError
from cbus_toolkit.thermostat_templates import ThermostatTemplateError


def _outputs(value=255, **overrides):
    values = {post_load.pp_name(name): value for name in post_load.VIRTUAL_11_OUTPUTS}
    values.update(overrides)
    return values


def _scalar_values(**overrides):
    values = {
        "DisplayBacklightIdleBrightness": 255,
        "DisplayBacklightActiveBrightness": 128,
        "KeyBacklightIdleBrightness": 0,
        "KeyBacklightActiveBrightness": 64,
        "BeepEnable": 7,
        "VariableFanCoilEnable": 0,
        "TemperatureUnits": 1,
        "ControlledZones": 1,
        "InstalledZones": 3,
        "InternalPlantType": 5,
        "InternalPlantZones": 3,
        "TimeUnits": 0,
        "SendInterval": 2,
        "EvapProgramEnabled": 1,
        "NonEvapProgramEnabled": 0,
        "TimerEnable": 1,
    }
    values.update(overrides)
    return values


class VirtualPlantAndDamperWave10Tests(unittest.TestCase):
    """thermostat_post_load.py: 8->11 rule and damper-modulation factors."""

    def test_virtual_plant_type_8_to_11_rule(self):
        self.assertEqual(
            post_load.virtual_plant_type({"InternalPlantType": 8, **_outputs()}), 8
        )
        self.assertEqual(
            post_load.virtual_plant_type(
                {"InternalPlantType": 8, **_outputs(CoolStage1Output=10)}
            ),
            11,
        )
        self.assertEqual(post_load.virtual_plant_type({"InternalPlantType": 5}), 5)
        self.assertEqual(post_load.virtual_plant_type({"InternalPlantType": 0}), 0)

    def test_damper_modulation_save_factors(self):
        self.assertEqual(post_load.damper_modulation_save(1, 0), 0)
        self.assertEqual(post_load.damper_modulation_save(1, 2), 2)
        self.assertEqual(post_load.damper_modulation_save(1, 6), 3)
        self.assertEqual(post_load.damper_modulation_save(1, 10), 3)
        self.assertEqual(post_load.damper_modulation_save(1, 5), 1)
        self.assertEqual(post_load.damper_modulation_save(1, 11), 1)
        for plant in (0, 2, 5, 6, 10, 11):
            with self.subTest(plant=plant):
                self.assertEqual(post_load.damper_modulation_save(0, plant), 0)


class ScalarSaveAndSettingsAdmissionWave10Tests(unittest.TestCase):
    """thermostat_post_load.py scalar guards + thermostat_settings.py admission."""

    def test_form_save_scalars_family_slave_and_units_guards(self):
        with self.assertRaisesRegex(ThermostatPostLoadError, "Unknown thermostat family"):
            post_load.form_save_scalars(_scalar_values(), "bogus")
        self.assertEqual(
            post_load.form_save_scalars(_scalar_values(TemperatureUnits=5), "basic")[
                "TemperatureUnits"
            ],
            0,
        )
        slave = post_load.form_save_scalars(_scalar_values(ControlledZones=0), "basic")
        self.assertEqual(slave["ControlledZones"], 0)
        self.assertEqual(slave["InternalPlantType"], 0)
        self.assertEqual(slave["InternalPlantZones"], 0)
        master = post_load.form_save_scalars(
            _scalar_values(InternalPlantType=11), "programmable"
        )
        self.assertEqual(master["ControlledZones"], 3)
        self.assertEqual(master["InternalPlantType"], 8)

    def test_settings_temperature_preference_and_family_admission(self):
        self.assertIsNone(settings._temperature_preference(None))
        self.assertIsNone(settings._temperature_preference("celsius"))
        self.assertIsNone(settings._temperature_preference("fahrenheit"))
        for bad in ("kelvin", "", 0, True):
            with self.subTest(bad=repr(bad)), self.assertRaisesRegex(
                ThermostatTemplateError, "must be celsius or fahrenheit"
            ):
                settings._temperature_preference(bad)
        self.assertIn("TimeUnits", settings.admitted("programmable"))
        self.assertIn("TimerEnable", settings.admitted("basic"))
        with self.assertRaises(KeyError):
            settings.admitted("bogus")

    def test_replay_post_load_plant_table_and_prefix_refusals(self):
        with self.assertRaisesRegex(
            ThermostatPostLoadError, "outside the original table"
        ):
            post_load.replay_post_load({"InternalPlantType": 12}, "programmable", 1, {})
        with self.assertRaisesRegex(
            ThermostatPostLoadError, r"already has \[CG03\] groups"
        ):
            post_load.replay_post_load(
                {"InternalPlantType": 5, "ZoneGroup": 3, "ControlledZones": 0},
                "programmable",
                1,
                {7: "[CG03] G (fan)"},
            )


if __name__ == "__main__":
    unittest.main()
