"""Tests for scene_sequence scaffold (issue #11 box 3). Structural only."""
import unittest

from cbus_toolkit.scene_sequence import DOCUMENTED_CAPACITY, plan_sequence


class SequenceTests(unittest.TestCase):
    def test_order_preserved(self):
        got = plan_sequence([
            {"action": "recall", "target": "S1"},
            {"action": "set_level", "target": "G5", "arg": 50},
            {"action": "delay", "target": "T", "arg": 10},
        ])
        self.assertEqual([s.action for s in got.steps],
                         ["recall", "set_level", "delay"])
        self.assertEqual(got.capacity, DOCUMENTED_CAPACITY)
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_capacity_bound(self):
        self.assertEqual(DOCUMENTED_CAPACITY, 64)
        with self.assertRaises(ValueError):
            plan_sequence([{"action": "recall", "target": "S"}] * 65)
        with self.assertRaises(ValueError):
            plan_sequence([{"action": "recall", "target": "S"}], capacity=65)
        ok = plan_sequence([{"action": "recall", "target": "S"}] * 64)
        self.assertEqual(len(ok.steps), 64)
        small = plan_sequence(
            [{"action": "recall", "target": "S"}], capacity=1)
        self.assertEqual(small.capacity, 1)

    def test_bad_steps(self):
        for bad in ("x", [{"action": "zap", "target": "S"}],
                    [{"action": "recall", "target": ""}],
                    [{"action": "set_level", "target": "G", "arg": 101}],
                    [{"action": "recall", "target": "S", "arg": -1}],
                    [{"action": "recall"}]):
            with self.subTest(bad=repr(bad)[:26]):
                with self.assertRaises((TypeError, ValueError)):
                    plan_sequence(bad)

    def test_extra_echo_isolated(self):
        extra = {"k": [1]}
        got = plan_sequence([{"action": "recall", "target": "S"}], extra=extra)
        self.assertEqual(got.echo, extra)
        extra["k"].append(2)
        self.assertEqual(got.echo, {"k": [1]})


if __name__ == "__main__":
    unittest.main()
