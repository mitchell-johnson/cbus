"""Tests for event_stream scaffold (issue #11 box 10). Structural only."""
import unittest

from cbus_toolkit.event_stream import deduplicate, match_filter, route_events

EVS = [
    {"application": 56, "group": 1, "kind": "on"},
    {"application": 56, "group": 2, "kind": "off"},
    {"application": 55, "group": 1, "kind": "on", "extra": [1]},
]


class MatchTests(unittest.TestCase):
    def test_match_and_wildcard(self):
        self.assertTrue(match_filter(EVS[0], {}))
        self.assertTrue(match_filter(EVS[0], {"application": 56}))
        self.assertFalse(match_filter(EVS[0], {"group": 2}))
        self.assertFalse(match_filter(EVS[0], {"kind": "off"}))

    def test_bad_shapes(self):
        with self.assertRaises((TypeError, ValueError)):
            match_filter({"application": 1}, {})
        with self.assertRaises((TypeError, ValueError)):
            match_filter(EVS[0], {"group": "x"})


class RouteTests(unittest.TestCase):
    def test_routes(self):
        got = route_events(
            EVS, {"light56": {"application": 56}, "ones": {"group": 1}})
        self.assertEqual(got.routes, {"light56": (0, 1), "ones": (0, 2)})
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_bad(self):
        with self.assertRaises(ValueError):
            route_events(EVS, {})
        with self.assertRaises(ValueError):
            route_events(EVS, {"": {}})


class DedupTests(unittest.TestCase):
    def test_first_wins(self):
        evs = [dict(EVS[0]), dict(EVS[0]), dict(EVS[1])]
        got = deduplicate(evs)
        self.assertEqual(len(got.unique), 2)
        self.assertEqual(got.duplicate_indices, (1,))
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_missing_key(self):
        with self.assertRaises(ValueError):
            deduplicate([{"application": 1}], ("application", "nope"))


if __name__ == "__main__":
    unittest.main()
