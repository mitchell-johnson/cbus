"""Tests for scene_binding_plan scaffold (P-D). Structural only."""
import unittest

from cbus_toolkit.scene_binding_plan import plan_bindings

CTRLS = {"K1", "K2"}


class BindTests(unittest.TestCase):
    def test_exclusive_first_wins(self):
        got = plan_bindings(
            [{"scene": "S1", "control": "K1"},
             {"scene": "S2", "control": "K1"},
             {"scene": "S3", "control": "K2"}], CTRLS)
        self.assertEqual(got.bindings, (("S1", "K1"), ("S3", "K2")))
        self.assertEqual(got.escalated, ("S2",))
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_bad(self):
        with self.assertRaises(ValueError):
            plan_bindings([{"scene": "S", "control": "K9"}], CTRLS)
        with self.assertRaises(ValueError):
            plan_bindings([{"scene": "S", "control": "K1"},
                           {"scene": "S", "control": "K2"}], CTRLS)
        with self.assertRaises(ValueError):
            plan_bindings([{"scene": "", "control": "K1"}], CTRLS)
        with self.assertRaises((TypeError, ValueError)):
            plan_bindings("xx", CTRLS)


if __name__ == "__main__":
    unittest.main()
