"""Tests for trigger_binding_guard scaffold. Structural only."""
import unittest

from cbus_toolkit.trigger_binding_guard import validate_bindings

GROUPS = {1, 2, 3}


class BindingTests(unittest.TestCase):
    def test_valid_sorted(self):
        got = validate_bindings([(3, "recall", 1), (1, "on", 2)], GROUPS)
        self.assertEqual(got.bindings, ((1, "on", 2), (3, "recall", 1)))
        self.assertEqual(got.conflicts, ())
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_duplicate_conflicts(self):
        got = validate_bindings(
            [(1, "on", 2), (1, "off", 3)], GROUPS)
        self.assertEqual(got.bindings, ((1, "on", 2),))
        self.assertEqual(len(got.conflicts), 1)

    def test_bad(self):
        with self.assertRaises(ValueError):
            validate_bindings([(1, "on", 9)], GROUPS)
        with self.assertRaises(ValueError):
            validate_bindings([(1, "", 2)], GROUPS)
        with self.assertRaises((TypeError, ValueError)):
            validate_bindings("xx", GROUPS)
        with self.assertRaises((TypeError, ValueError)):
            validate_bindings([(1, "on", 2)], "xx")


if __name__ == "__main__":
    unittest.main()
