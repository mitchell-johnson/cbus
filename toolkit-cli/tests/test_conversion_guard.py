"""Tests for conversion_guard scaffold (issue #11 box 5)."""
import unittest

from cbus_toolkit.conversion_guard import plan_conversion, supported_pairs

TABLE = {("KEY1", "KEY2"): {}, ("KEY2", "KEY4"): {}}


class GuardTests(unittest.TestCase):
    def test_supported_pairs(self):
        self.assertEqual(
            supported_pairs(TABLE), (("KEY1", "KEY2"), ("KEY2", "KEY4")))
        self.assertEqual(supported_pairs([("B", "A")]), (("B", "A"),))

    def test_plan_ok(self):
        got = plan_conversion("KEY1", "KEY2", TABLE, {"g": 1})
        self.assertEqual(got.steps[0], "validate_profiles")
        self.assertEqual(got.steps[-1], "verify_no_transfer")
        self.assertEqual(got.behavioral_comparison, "unassessed")
        self.assertEqual(got.echo["params"], {"g": 1})

    def test_rejections(self):
        with self.assertRaises(ValueError):
            plan_conversion("KEY1", "KEY1", TABLE, {})
        with self.assertRaises(ValueError):
            plan_conversion("KEY1", "KEY9", TABLE, {})
        with self.assertRaises(ValueError):
            plan_conversion("", "KEY2", TABLE, {})
        with self.assertRaises(TypeError):
            plan_conversion("KEY1", "KEY2", TABLE, [1])
        with self.assertRaises((TypeError, ValueError)):
            plan_conversion("KEY1", "KEY2", {"bad": 1}, {})

    def test_echo_isolated(self):
        params = {"g": [1]}
        got = plan_conversion("KEY1", "KEY2", TABLE, params)
        params["g"].append(2)
        self.assertEqual(got.echo["params"], {"g": [1]})


if __name__ == "__main__":
    unittest.main()
