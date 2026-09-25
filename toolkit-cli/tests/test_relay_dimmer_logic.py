"""Tests for relay_dimmer_logic scaffold (issue #11 box 3). Structural only."""
import unittest

from cbus_toolkit.relay_dimmer_logic import (
    LOGIC_ENGINE_BOUNDARY,
    validate_bank,
)


class BankTests(unittest.TestCase):
    def test_valid_sorted_and_boundary(self):
        self.assertEqual(LOGIC_ENGINE_BOUNDARY, "external")
        got = validate_bank([(3, "dimmer", 50, 10), (0, "relay", 100, 0)])
        self.assertEqual(
            got.table, ((0, "relay", 100, 0), (3, "dimmer", 50, 10))
        )
        self.assertEqual(got.conflicts, ())
        self.assertEqual(got.physical_comparison, "unassessed")

    def test_relay_levels(self):
        for level in (0, 100):
            with self.subTest(level=level):
                got = validate_bank([(0, "relay", level, 0)])
                self.assertEqual(got.table[0][2], level)
        for level in (1, 50, -1, 101):
            with self.subTest(level=level):
                with self.assertRaises(ValueError):
                    validate_bank([(0, "relay", level, 0)])

    def test_relay_ramp_must_be_zero(self):
        with self.assertRaises(ValueError):
            validate_bank([(0, "relay", 100, 5)])

    def test_dimmer_bounds(self):
        with self.assertRaises(ValueError):
            validate_bank([(1, "dimmer", 101, 0)])
        with self.assertRaises(ValueError):
            validate_bank([(1, "dimmer", 50, 601)])

    def test_duplicates_and_unused_flagged(self):
        got = validate_bank(
            [(0, "relay", 0, 0), (0, "dimmer", 10, 0), (5, "unused", 20, 0)]
        )
        self.assertEqual(len(got.conflicts), 2)
        self.assertEqual(got.table[0], (0, "relay", 0, 0))

    def test_bad_shapes(self):
        for bad in ("x", [(0,)], [(0, "relay", 0)], [(0, "bogus", 0, 0)],
                    [(-1, "relay", 0, 0)], [(True, "relay", 0, 0)]):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises((TypeError, ValueError)):
                    validate_bank(bad)

    def test_extra_echo_isolated(self):
        extra = {"k": [1]}
        got = validate_bank([(0, "relay", 0, 0)], extra)
        self.assertEqual(got.echo, extra)
        extra["k"].append(2)
        self.assertEqual(got.echo, {"k": [1]})


if __name__ == "__main__":
    unittest.main()
