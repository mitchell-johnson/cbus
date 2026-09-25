"""Tests for sensor_threshold_guard scaffold (issue #11 box 1)."""
import unittest

from cbus_toolkit.sensor_threshold_guard import (
    check_enable_dependency,
    classify_zone,
)


class ZoneTests(unittest.TestCase):
    def test_zones(self):
        self.assertEqual(classify_zone(100, 10, 115).zone, "trigger")
        self.assertEqual(classify_zone(100, 10, 85).zone, "clear")
        self.assertEqual(classify_zone(100, 10, 100).zone, "deadband")
        self.assertEqual(classify_zone(100, 0, 100).zone, "trigger")
        self.assertEqual(
            classify_zone(1, 1, 1).behavioral_comparison, "unassessed")

    def test_bad(self):
        with self.assertRaises(ValueError):
            classify_zone(100, -1, 100)
        with self.assertRaises(TypeError):
            classify_zone(True, 1, 1)


class DependencyTests(unittest.TestCase):
    def test_matrix(self):
        self.assertTrue(check_enable_dependency(False, False).ok)
        self.assertTrue(check_enable_dependency(False, True).ok)
        self.assertTrue(check_enable_dependency(True, True).ok)
        bad = check_enable_dependency(True, False)
        self.assertFalse(bad.ok)
        self.assertIn("master", bad.note)

    def test_non_bool(self):
        with self.assertRaises(TypeError):
            check_enable_dependency(1, True)


if __name__ == "__main__":
    unittest.main()
