"""Tests for duplicate_resolution scaffold (issue #11 box 2)."""
import unittest

from cbus_toolkit.duplicate_resolution import resolve_duplicates


class ResolveTests(unittest.TestCase):
    def test_keep_lowest_relocate_rest(self):
        got = resolve_duplicates(
            [{"serial": "S1", "locations": [9, 3, 7]}], [100, 101]
        )
        self.assertEqual(len(got), 1)
        r = got[0]
        self.assertEqual((r.keep, r.relocations, r.escalated),
                         (3, ((7, 100), (9, 101)), ()))
        self.assertEqual(r.physical_comparison, "unassessed")

    def test_singleton_no_action(self):
        (r,) = resolve_duplicates([{"serial": "S", "locations": [5]}], [9])
        self.assertEqual((r.keep, r.relocations, r.escalated), (5, (), ()))

    def test_exhaustion_escalates(self):
        (r,) = resolve_duplicates(
            [{"serial": "S", "locations": [1, 2, 3]}], [50]
        )
        self.assertEqual(r.relocations, ((2, 50),))
        self.assertEqual(r.escalated, (3,))

    def test_sorted_by_serial(self):
        got = resolve_duplicates(
            [{"serial": "B", "locations": [2]},
             {"serial": "A", "locations": [8, 1]}], []
        )
        self.assertEqual([r.serial for r in got], ["A", "B"])
        self.assertEqual(got[0].escalated, (8,))

    def test_bad_inputs(self):
        with self.assertRaises(TypeError):
            resolve_duplicates("x", [])
        with self.assertRaises(TypeError):
            resolve_duplicates([], "x")
        for bad in ({"serial": "", "locations": [1]},
                    {"serial": "S", "locations": []},
                    {"serial": "S", "locations": [1, 1]},
                    {"serial": "S"}):
            with self.subTest(bad=repr(bad)[:26]):
                with self.assertRaises((TypeError, ValueError)):
                    resolve_duplicates([bad], [])
        with self.assertRaises(ValueError):
            resolve_duplicates([{"serial": "S", "locations": [1]}], [4, 4])


if __name__ == "__main__":
    unittest.main()
