"""Tests for form_save_order scaffold (P-C). Structural only."""
import unittest

from cbus_toolkit.form_save_order import check_preservation, plan_save_order


class OrderTests(unittest.TestCase):
    def test_order_respects_deps(self):
        got = plan_save_order(
            ["c", "b", "a"], {"c": ["b"], "b": ["a"]})
        self.assertEqual(got.order, ("a", "b", "c"))
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_ties_alphabetical(self):
        got = plan_save_order(["b", "a"], {})
        self.assertEqual(got.order, ("a", "b"))

    def test_cycle_and_self(self):
        with self.assertRaises(ValueError):
            plan_save_order(["a", "b"], {"a": ["b"], "b": ["a"]})
        with self.assertRaises(ValueError):
            plan_save_order(["a"], {"a": ["a"]})
        with self.assertRaises(ValueError):
            plan_save_order(["a", "a"], {})
        with self.assertRaises(ValueError):
            plan_save_order(["a"], {"zzz": []})


class PreservationTests(unittest.TestCase):
    def test_ok(self):
        got = check_preservation({"a": 1, "b": 2}, {"a": 1, "b": 9}, {"b"})
        self.assertTrue(got.ok)

    def test_violations(self):
        got = check_preservation({"a": 1}, {"a": 2}, set())
        self.assertFalse(got.ok)
        self.assertTrue(any("changed" in v for v in got.violations))
        got2 = check_preservation({"a": 1}, {}, set())
        self.assertTrue(any("removed" in v for v in got2.violations))
        got3 = check_preservation({}, {"n": 1}, set())
        self.assertTrue(any("added" in v for v in got3.violations))


if __name__ == "__main__":
    unittest.main()
