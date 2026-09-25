"""Tests for wireless_commissioning scaffold (issue #11 box 9). Structural only."""
import unittest

from cbus_toolkit.wireless_commissioning import (
    plan_join,
    validate_gateway_mapping,
)


class PlanJoinTests(unittest.TestCase):
    def test_order_and_repeat(self):
        got = plan_join("new_house", 2)
        self.assertEqual(
            got.steps,
            ("enter_learn", "join_devices[0]", "join_devices[1]",
             "assign_mapping", "exit_learn"),
        )
        self.assertEqual(got.physical_comparison, "unassessed")

    def test_modes(self):
        for mode in ("new_house", "join_existing"):
            with self.subTest(mode=mode):
                self.assertEqual(plan_join(mode, 1).mode, mode)

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            plan_join("auto", 1)

    def test_bad_counts(self):
        for bad in (0, -3, True, "2", None):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises((TypeError, ValueError)):
                    plan_join("new_house", bad)


class GatewayMappingTests(unittest.TestCase):
    def test_valid_sorted(self):
        got = validate_gateway_mapping([(9, 3), (1, 7)])
        self.assertEqual(got.table, ((1, 7), (9, 3)))
        self.assertEqual(got.conflicts, ())
        self.assertEqual(got.physical_comparison, "unassessed")

    def test_duplicates_conflict_first_wins(self):
        got = validate_gateway_mapping([(1, 7), (1, 8), (2, 7)])
        self.assertEqual(got.table, ((1, 7),))
        self.assertEqual(len(got.conflicts), 2)

    def test_bad_shapes(self):
        for bad in ("x", [(1,)], [(1, 2, 3)], [(1, "g")], [None]):
            with self.subTest(bad=repr(bad)[:16]):
                with self.assertRaises((TypeError, ValueError)):
                    validate_gateway_mapping(bad)

    def test_out_of_range(self):
        for bad in ([(256, 1)], [(1, -1)], [(True, 1)]):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises((TypeError, ValueError)):
                    validate_gateway_mapping(bad)

    def test_extra_echo_isolated(self):
        extra = {"n": {"v": [1]}}
        got = validate_gateway_mapping([(1, 2)], extra)
        self.assertEqual(got.echo, extra)
        extra["n"]["v"].append(9)
        self.assertEqual(got.echo, {"n": {"v": [1]}})


if __name__ == "__main__":
    unittest.main()
