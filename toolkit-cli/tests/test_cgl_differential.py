"""Tests for cgl_differential scaffold (issue #11 box 7). Structural only."""
import unittest

from cbus_toolkit.cgl_differential import diff_manifests


def man(units=None, routes=None):
    m: dict = {}
    if units is not None:
        m["units"] = units
    if routes is not None:
        m["routes"] = routes
    return m


class DiffTests(unittest.TestCase):
    def test_empty_manifests(self):
        got = diff_manifests(man(), man())
        self.assertEqual((got.added, got.removed, got.changed), ((), (), ()))
        self.assertEqual(got.route_changes, ())
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_unit_add_remove_change(self):
        before = man({"u1": {"a": 1}, "u2": {"a": 2}, "u3": {"a": 3}})
        after = man({"u2": {"a": 2}, "u3": {"a": 9}, "u4": {"a": 4}})
        got = diff_manifests(before, after)
        self.assertEqual(got.added, ("u4",))
        self.assertEqual(got.removed, ("u1",))
        self.assertEqual(got.changed, ("u3",))

    def test_route_changes(self):
        before = man({}, {"r1": "A", "r2": "B", "r3": "C"})
        after = man({}, {"r2": "B2", "r3": "C", "r4": "D"})
        got = diff_manifests(before, after)
        self.assertEqual(
            got.route_changes,
            ("route r1 removed", "route r2: B -> B2", "route r4 added"),
        )

    def test_bad_manifests(self):
        for before, after in [
            (None, man()), ("x", man()), (man(), [1]),
            ({"units": [1]}, man()), ({"units": {"": {}}}, man()),
            ({"routes": {"r": 1}}, man()),
        ]:
            with self.subTest(before=repr(before)[:14]):
                with self.assertRaises((TypeError, ValueError)):
                    diff_manifests(before, after)

    def test_extra_echo_isolated(self):
        extra = {"k": [1]}
        got = diff_manifests(man(), man(), extra)
        self.assertEqual(got.echo, extra)
        extra["k"].append(2)
        self.assertEqual(got.echo, {"k": [1]})


if __name__ == "__main__":
    unittest.main()
