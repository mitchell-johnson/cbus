"""Tests for thermostat_settings_guard scaffold (issue #11 box 8)."""
import unittest

from cbus_toolkit.thermostat_settings_guard import (
    check_heat_cool,
    check_setting,
)


class SettingTests(unittest.TestCase):
    def test_within_and_edges(self):
        spec = {"min": 5, "max": 30, "step": 0.5}
        for v in (5, 5.5, 30):
            with self.subTest(v=v):
                got = check_setting("setpoint", v, spec)
                self.assertTrue(got.ok)
                self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_out_of_range_and_off_step(self):
        spec = {"min": 5, "max": 30, "step": 0.5}
        self.assertFalse(check_setting("s", 31, spec).ok)
        self.assertFalse(check_setting("s", 5.3, spec).ok)

    def test_no_step(self):
        self.assertTrue(check_setting("h", 7.33, {"min": 0, "max": 10}).ok)

    def test_bad_spec(self):
        for spec in (None, {}, {"min": 0}, {"min": 9, "max": 1},
                     {"min": 0, "max": 1, "step": 0}):
            with self.subTest(spec=repr(spec)):
                with self.assertRaises((TypeError, ValueError)):
                    check_setting("s", 0, spec)
        with self.assertRaises((TypeError, ValueError)):
            check_setting("", 0, {"min": 0, "max": 1})
        with self.assertRaises(TypeError):
            check_setting("s", True, {"min": 0, "max": 1})


class HeatCoolTests(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(check_heat_cool(19, 24, 2).ok)

    def test_violations(self):
        self.assertFalse(check_heat_cool(25, 24, 0).ok)
        self.assertFalse(check_heat_cool(19, 20, 2).ok)

    def test_bad_types(self):
        with self.assertRaises(TypeError):
            check_heat_cool("19", 24, 2)
        with self.assertRaises(ValueError):
            check_heat_cool(19, 24, -1)


if __name__ == "__main__":
    unittest.main()
