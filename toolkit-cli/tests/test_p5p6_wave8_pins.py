"""Wave 8 narrow offline pins for P5-P6 (thermostat/sensor/DIN settings).

Each method pins ONE pure-offline branch using plain values only: no
hardware, vendor EXE, C-Gate server, decoded vendor spec, or PP session.
Covers modules thermostat_settings.py, sensors.py, din_output_settings.py.
"""
from __future__ import annotations

import unittest

from cbus_toolkit import thermostat_settings as ts_settings
from cbus_toolkit.din_output_settings import (
    DinPlan,
    DinSettingsError,
    level_to_percent,
    logic_group_level,
    percent_to_level,
    profile_refusal as din_refusal,
    recovery_delay_seconds,
)
from cbus_toolkit.sensors import (
    SensorError,
    check_profile,
    margin_percent,
    profile_refusal as sensor_refusal,
    saved_margin,
)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError


class SensorProfileAndMarginWave8Tests(unittest.TestCase):
    """sensors.py: REFUSED catalogue entries and x87 margin arithmetic."""

    def test_refused_types_firmware_and_catalogue(self):
        self.assertIn("ST7 PIR sensor class", sensor_refusal("SENPIROA", "2.3.00", "5753PEIRL"))
        self.assertIn("light-level sensor class", sensor_refusal("SENLL", "2.3.00", "5753PEIRL"))
        self.assertIn("TSENPILLA", sensor_refusal("SENPILLA", "2.3.00", "5753PEIRL"))
        self.assertEqual(sensor_refusal("NOPE", "2.3.00", "5753PEIRL"), "Only SENPILL multisensors use this workflow")
        self.assertIn("outside 2.0.01..2.3.9", sensor_refusal("SENPILL", "2.3.10", "5753PEIRL"))
        self.assertIn("5753PEIRL", sensor_refusal("SENPILL", "2.3.00", "BAD"))
        self.assertIsNone(sensor_refusal("SENPILL", "2.3.00", "5753PEIRL"))
        self.assertIsNone(sensor_refusal("SENPILL", "2.0.01", "SLC5753PEIRL"))
        with self.assertRaisesRegex(SensorError, "SENPILL 2.0.01..2.3.9"):
            check_profile("SENLL", "2.3.00", "5753PEIRL")

    def test_margin_arithmetic_exact_vectors(self):
        self.assertEqual(margin_percent(0, 0), 0)
        self.assertEqual(margin_percent(0, 255), 0)
        self.assertEqual(margin_percent(100, 10), 10)
        self.assertEqual(margin_percent(200, 10), 5)
        self.assertEqual(saved_margin(0, 100), 0)
        self.assertEqual(saved_margin(10, 50), 5)
        self.assertEqual(saved_margin(255, 100), 255)


class DinConversionAndProfileWave8Tests(unittest.TestCase):
    """din_output_settings.py: percent/level conversions and profile refusals."""

    def test_conversions_match_original_toolkit_arithmetic(self):
        self.assertEqual(percent_to_level(0), 0)
        self.assertEqual(percent_to_level(50), 127)
        self.assertEqual(percent_to_level(100), 255)
        self.assertEqual(percent_to_level(1), 2)
        self.assertEqual(level_to_percent(0), 0)
        self.assertEqual(level_to_percent(127), 50)
        self.assertEqual(level_to_percent(255), 100)
        self.assertEqual(logic_group_level(0), 0)
        self.assertEqual(logic_group_level(50), 128)
        self.assertEqual(logic_group_level(100), 255)
        self.assertEqual(logic_group_level(1), 3)
        self.assertEqual(recovery_delay_seconds(59), 59)
        self.assertEqual(recovery_delay_seconds(60), 60)
        self.assertEqual(recovery_delay_seconds(61), 70)
        self.assertEqual(recovery_delay_seconds(255), 2010)
        with self.assertRaises(DinSettingsError):
            percent_to_level(True)
        with self.assertRaises(DinSettingsError):
            level_to_percent(256)

    def test_refused_units_and_firmware_mismatch(self):
        self.assertIn("nine channels", din_refusal("RELDN8SP", "2.7.00"))
        self.assertIn("TfrmCBus1Relay", din_refusal("RELAY4", "2.7.00"))
        self.assertIn("TfrmCBus1Relay", din_refusal("DIMMER4", "2.7.00"))
        self.assertIn("Only RELDN4", din_refusal("NOPE", "2.7.00"))
        self.assertIn("other than 2.7.00", din_refusal("RELDN4", "2.6.00"))
        self.assertIsNone(din_refusal("RELDN4", "2.7.00"))


class DinPlanFromDictWave8Tests(unittest.TestCase):
    """din_output_settings.py: DinPlan.from_dict shape guards (no session)."""

    def test_bad_documents_and_toolkit_save_mismatch(self):
        for bad in (None, [], "x", {}):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                DinSettingsError, "Expected a DIN output settings"
            ):
                DinPlan.from_dict(bad)
        base = {
            "format": "cbus-din-output-settings-plan-v1",
            "unit_type": "RELDN4",
            "expected": {},
            "changes": {},
        }
        with self.assertRaisesRegex(DinSettingsError, "expected and changes"):
            DinPlan.from_dict({k: v for k, v in base.items() if k != "expected"})
        with self.assertRaisesRegex(DinSettingsError, "expected and changes"):
            DinPlan.from_dict({**base, "changes": 1})
        with self.assertRaisesRegex(DinSettingsError, "Targeted plans cannot contain"):
            DinPlan.from_dict({**base, "pre_save_changes": {}})
        with self.assertRaisesRegex(DinSettingsError, "not admitted"):
            DinPlan.from_dict({**base, "unit_type": "NOPE"})
        with self.assertRaisesRegex(DinSettingsError, "exactly one normalization pass"):
            DinPlan.from_dict(
                {**base, "format": "cbus-din-output-settings-plan-v2", "toolkit_save": True}
            )


class ThermostatSettingsWave8Tests(unittest.TestCase):
    """thermostat_settings.py: admission, preference, and plan projection."""

    def test_admitted_families_preference_and_projection(self):
        self.assertIn("SendInterval", ts_settings.admitted("programmable"))
        self.assertIn("TimerEnable", ts_settings.admitted("basic"))
        self.assertNotIn("SendInterval", ts_settings.admitted("basic"))
        self.assertIsNone(ts_settings._temperature_preference(None))
        self.assertIsNone(ts_settings._temperature_preference("celsius"))
        for bad in (b"celsius", "kelvin", 1, True):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                ThermostatTemplateError, "celsius or fahrenheit"
            ):
                ts_settings._temperature_preference(bad)
        plan = ts_settings.SettingsPlan(
            family="programmable",
            unit_type="PC_TSA",
            before=(("A", "1"), ("B", "2")),
            edits=(("A", 5),),
            dependent=(("B", 2, 3),),
            dialog_rules_json='{"x": 1}',
        )
        self.assertEqual(plan.expected, {"A": 5, "B": 3})
        document = plan.as_dict()
        self.assertEqual(
            document["changed_parameters"],
            [{"name": "A", "before": 1, "after": 5}, {"name": "B", "before": 2, "after": 3}],
        )
        self.assertFalse(document["temperature_normalization"]["reproduced"])
        self.assertFalse(document["complete_form_lifecycle_reproduced"])
        self.assertFalse(document["physical_device_programmed"])


if __name__ == "__main__":
    unittest.main()
