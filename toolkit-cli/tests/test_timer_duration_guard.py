"""Tests for timer_duration_guard scaffold (issue #11 box 3)."""
import unittest

from cbus_toolkit.timer_duration_guard import check_timer


class TimerTests(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(check_timer("toggle", 0, 100, 0, 600).ok)
        self.assertTrue(check_timer("retrigger", 30, 100, 0, 600).ok)
        self.assertEqual(
            check_timer("toggle", 1, 1, 1, 1).behavioral_comparison,
            "unassessed")

    def test_violations(self):
        self.assertFalse(check_timer("toggle", 700, 100, 0, 600).ok)
        self.assertFalse(check_timer("retrigger", 0, 100, 0, 600).ok)

    def test_bad(self):
        with self.assertRaises(ValueError):
            check_timer("pulse", 1, 1, 1, 600)
        with self.assertRaises(ValueError):
            check_timer("toggle", 1, 101, 0, 600)
        with self.assertRaises(ValueError):
            check_timer("toggle", 1, 1, 1, -1)
        with self.assertRaises(TypeError):
            check_timer("toggle", True, 1, 1, 600)


if __name__ == "__main__":
    unittest.main()
