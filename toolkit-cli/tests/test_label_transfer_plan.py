"""Tests for label_transfer_plan scaffold (P-D). Structural only."""
import unittest

from cbus_toolkit.label_transfer_plan import plan_transfer


class TransferTests(unittest.TestCase):
    def test_auto_fills_lowest(self):
        got = plan_transfer([{"text": "A"}, {"text": "B"}], 4)
        self.assertEqual(got.assignments, (("A", 0), ("B", 1)))
        self.assertEqual(got.escalated, ())
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_requested_first_wins(self):
        got = plan_transfer(
            [{"text": "A", "slot": 2}, {"text": "B", "slot": 2},
             {"text": "C"}], 4)
        self.assertIn(("A", 2), got.assignments)
        self.assertIn("B", got.escalated)
        self.assertTrue(any(t == "C" for t, _ in got.assignments))

    def test_overflow_escalates(self):
        got = plan_transfer([{"text": "A"}, {"text": "B"}], 1)
        self.assertEqual(got.assignments, (("A", 0),))
        self.assertEqual(got.escalated, ("B",))

    def test_bad(self):
        with self.assertRaises(ValueError):
            plan_transfer([{"text": ""}], 4)
        with self.assertRaises(ValueError):
            plan_transfer([{"text": "A", "slot": 9}], 4)
        with self.assertRaises((TypeError, ValueError)):
            plan_transfer("AB", 4)
        with self.assertRaises(ValueError):
            plan_transfer([{"text": "A"}], 0)


if __name__ == "__main__":
    unittest.main()
