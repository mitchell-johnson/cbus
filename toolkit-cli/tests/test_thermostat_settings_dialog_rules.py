"""Independent expected cases from the pinned original thermostat methods.

See research/experiments/2026-09-30/thermostat-settings-form-static.json.
These are method-level source comparisons, not an executed original dialog.
"""
import unittest

from cbus_toolkit.thermostat_settings_guard import (
    quick_zone_state, quick_zone_transition, recovered_dialog_rules,
)


def snapshot():
    return {
        "InstalledZones": 31, "ControlledZones": 1, "UIAllocatedZones": 3,
        "InternalPlantZones": 5, "MeasuredZones": 9,
        "HeatingPlantInstalledZones": 1, "CoolingPlantInstalledZones": 17,
        "VentingPlantInstalledZones": 1, "ScheduleControlledZones": 1,
        "InternalPlantType": 3, "InternalPlantModes": 31, "VentPlantType": 1,
        "HeatingPlantType": 1, "CoolingPlantType": 0, "VentingPlantType": 2,
        "HeatCoolPlantType": 3, "Unrelated": 201,
    }


class OriginalDialogRuleTests(unittest.TestCase):
    def test_zone_checkbox_union_intersection_and_gray(self):
        values = snapshot()
        original = dict(values)
        self.assertEqual(quick_zone_state(values, "programmable"), {
            "used_zones": 31, "fully_selected_zones": 1,
            "checkbox_states": (1, 2, 2, 2, 2),
        })
        self.assertEqual(values, original)
        values.update(InstalledZones=0, ControlledZones=0)
        self.assertEqual(quick_zone_state(values, "programmable")["checkbox_states"], (1, 2, 2, 2, 2))

    def test_schedule_is_only_a_programmable_zone_source(self):
        values = {name: 0 for name in snapshot()}
        values["ScheduleControlledZones"] = 16
        self.assertEqual(quick_zone_state(values, "programmable")["used_zones"], 16)
        self.assertEqual(quick_zone_state(values, "basic")["used_zones"], 0)
        values["UIAllocatedZones"] = 0xE0
        self.assertEqual(quick_zone_state(values, "basic")["used_zones"], 0)

    def test_master_slave_and_absent_plant_zone_controls(self):
        values = snapshot()
        self.assertEqual(recovered_dialog_rules(values, "programmable")["zone_control_enabled_masks"], {
            "UIAllocatedZones": 31, "MeasuredZones": 31, "InternalPlantZones": 31,
            "HeatingPlantInstalledZones": 31, "CoolingPlantInstalledZones": 0,
            "VentingPlantInstalledZones": 31,
        })
        values["ControlledZones"] = 0
        state = recovered_dialog_rules(values, "basic")
        self.assertEqual(state["zone_control_enabled_masks"], {
            "UIAllocatedZones": 31, "MeasuredZones": 31, "InternalPlantZones": 0,
            "HeatingPlantInstalledZones": 0, "CoolingPlantInstalledZones": 0,
            "VentingPlantInstalledZones": 0,
        })
        self.assertEqual(state["basic_hidden_controls"], ("gbPlantZones", "btnDamperGroups"))
        self.assertFalse(state["dialog_enable_rules_reproduced"])
        self.assertFalse(state["original_dialog_executed"])

    def test_original_allowed_mode_constants_and_virtual_fan_coil(self):
        # Literal table recovered from twelve distinct original jump entries.
        for plant, allowed in enumerate((1, 19, 21, 31, 19, 21, 31, 31, 3, 31, 31, 31)):
            with self.subTest(plant=plant):
                values = snapshot() | {"InternalPlantType": plant}
                if plant == 8:
                    values.update({name: 255 for name in (
                        "CoolActivationOutput", "CoolStage1Output", "CoolStage2Output",
                        "CoolStage3Output", "CoolFanLowOutput", "CoolFanMediumOutput",
                        "CoolFanHighOutput", "HeatFanLowOutput", "HeatFanMediumOutput",
                        "HeatFanHighOutput")})
                self.assertEqual(recovered_dialog_rules(values, "basic")["allowed_plant_modes"], allowed)
                if plant == 8:
                    values["CoolStage1Output"] = 4
                    state = recovered_dialog_rules(values, "basic")
                    self.assertEqual(state["virtual_plant_type"], 11)
                    self.assertEqual(state["allowed_plant_modes"], 31)
        self.assertEqual(recovered_dialog_rules(snapshot() | {"InternalPlantType": 128}, "basic")[
            "allowed_plant_modes"], 1)

    def test_vent_fallback_uses_available_modes_not_checked_modes(self):
        for plant, before, expected in ((0, 2, 0), (1, 2, 1), (2, 1, 2), (3, 2, 2), (5, 1, 2)):
            with self.subTest(plant=plant):
                values = snapshot() | {"InternalPlantType": plant, "VentPlantType": before,
                                       "InternalPlantModes": 0}
                state = recovered_dialog_rules(values, "basic")
                self.assertFalse(state["vent_plant_type_enabled"])
                self.assertEqual(state["unguarded_enable_modes_vent_result"], expected)
                values["ControlledZones"] = 0
                self.assertEqual(recovered_dialog_rules(values, "basic")[
                    "unguarded_enable_modes_vent_result"], before)

    def test_action_enabled_rules_are_not_silently_master_gated(self):
        values = snapshot() | {"InternalPlantType": 11, "InternalPlantModes": 16, "ControlledZones": 0}
        state = recovered_dialog_rules(values, "basic")
        self.assertTrue(state["fan_control_action_enabled"])
        self.assertTrue(state["fan_coil_action_enabled"])
        self.assertTrue(state["evaporative_cooling_action_enabled"])
        self.assertFalse(state["vent_plant_type_enabled"])
        self.assertEqual(state["plant_mode_checkbox_enabled_mask"], 0)
        for modes in (0, 1):
            self.assertFalse(recovered_dialog_rules(values | {"InternalPlantModes": modes}, "basic")[
                "fan_coil_action_enabled"])

    def test_include_zone_uses_pretransition_slave_state_and_plant_types(self):
        values = snapshot() | {"ControlledZones": 0, "InternalPlantZones": 1,
                               "MeasuredZones": 1, "UIAllocatedZones": 1, "InstalledZones": 1,
                               "CoolingPlantInstalledZones": 1}
        original = dict(values)
        after = quick_zone_transition(values, "programmable", 2, True)
        self.assertEqual({name: after[name] for name in (
            "ControlledZones", "InternalPlantZones", "ScheduleControlledZones", "MeasuredZones",
            "UIAllocatedZones", "InstalledZones", "HeatingPlantInstalledZones",
            "CoolingPlantInstalledZones", "VentingPlantInstalledZones", "Unrelated")}, {
                "ControlledZones": 4, "InternalPlantZones": 1, "ScheduleControlledZones": 1,
                "MeasuredZones": 5, "UIAllocatedZones": 5, "InstalledZones": 5,
                "HeatingPlantInstalledZones": 5, "CoolingPlantInstalledZones": 1,
                "VentingPlantInstalledZones": 5, "Unrelated": 201,
            })
        self.assertEqual(values, original)

    def test_exclude_zone_clears_all_owned_masks_and_preserves_others(self):
        values = snapshot()
        after = quick_zone_transition(values, "programmable", 0, False, unswitched_removal_confirmed=True)
        expected = values | {"InstalledZones": 30, "ControlledZones": 0, "UIAllocatedZones": 2,
                             "InternalPlantZones": 4, "MeasuredZones": 8,
                             "HeatingPlantInstalledZones": 0, "CoolingPlantInstalledZones": 16,
                             "VentingPlantInstalledZones": 0, "ScheduleControlledZones": 0}
        self.assertEqual(after, expected)
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            quick_zone_transition(values, "programmable", 0, False)
        with self.assertRaisesRegex(ValueError, "last zone"):
            quick_zone_transition({name: 1 for name in values}, "programmable", 0, False,
                                  unswitched_removal_confirmed=True)

    def test_missing_or_malformed_evidence_is_not_defaulted(self):
        with self.assertRaises(KeyError):
            recovered_dialog_rules({}, "basic")
        with self.assertRaises(ValueError):
            recovered_dialog_rules(snapshot() | {"UIAllocatedZones": True}, "basic")
        for bad in (True, -1, "255"):
            with self.subTest(bad_output=bad), self.assertRaises(ValueError):
                recovered_dialog_rules(snapshot() | {"InternalPlantType": 8, "CoolActivationOutput": bad},
                                       "basic")
        with self.assertRaises(KeyError):
            recovered_dialog_rules(snapshot() | {"InternalPlantType": 8, "CoolActivationOutput": 4}, "basic")
        with self.assertRaises(ValueError):
            quick_zone_state(snapshot(), "unknown")
        with self.assertRaises(ValueError):
            quick_zone_transition(snapshot(), "basic", 5, True)


if __name__ == "__main__":
    unittest.main()
