"""Tests for topology_navigation scaffold (box 7). Structural only."""
import unittest

from cbus_toolkit.topology_navigation import find_path, neighbors

GRAPH = {0: [1, 2], 1: [0, 3], 2: [0], 3: [1], 9: []}


class NavTests(unittest.TestCase):
    def test_neighbors(self):
        self.assertEqual(neighbors(GRAPH, 0), (1, 2))
        self.assertEqual(neighbors(GRAPH, 9), ())

    def test_path(self):
        got = find_path(GRAPH, 2, 3)
        self.assertTrue(got.found)
        self.assertEqual(got.path, (2, 0, 1, 3))
        self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_same_and_disconnected(self):
        self.assertEqual(find_path(GRAPH, 1, 1).path, (1,))
        got = find_path(GRAPH, 0, 9)
        self.assertFalse(got.found)
        self.assertEqual(got.path, ())

    def test_bad(self):
        with self.assertRaises(ValueError):
            neighbors(GRAPH, 99)
        with self.assertRaises(ValueError):
            find_path({0: [1]}, 0, 1)
        with self.assertRaises(ValueError):
            find_path({0: [0]}, 0, 0)
        with self.assertRaises(ValueError):
            find_path({}, 0, 0)


if __name__ == "__main__":
    unittest.main()
