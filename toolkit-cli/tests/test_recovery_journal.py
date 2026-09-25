"""Tests for recovery_journal scaffold (issue #11 box 2). Structural only."""
import unittest

from cbus_toolkit.recovery_journal import (
    JournalEntry,
    append_entry,
    load,
    serialize,
    verify_journal,
)


class JournalTests(unittest.TestCase):
    def test_append_assigns_seq_and_immutable(self):
        e0 = append_entry((), "move", "u1", {"a": [1]})
        self.assertEqual([e.seq for e in e0], [0])
        e1 = append_entry(e0, "verify", "u1")
        self.assertEqual([e.seq for e in e1], [0, 1])
        self.assertEqual(len(e0), 1)

    def test_verify_ok(self):
        entries = append_entry((), "address", "u2")
        entries = append_entry(entries, "save", "u2")
        got = verify_journal(entries)
        self.assertTrue(got.ok)
        self.assertEqual(got.problems, ())
        self.assertEqual(got.physical_comparison, "unassessed")

    def test_verify_breaks(self):
        bad = (JournalEntry(0, "move", "u1"), JournalEntry(5, "save", "u1"))
        got = verify_journal(bad)
        self.assertFalse(got.ok)
        self.assertTrue(any("continuity" in p for p in got.problems))
        bad_op = (JournalEntry(0, "zap", "u1"),)
        self.assertFalse(verify_journal(bad_op).ok)

    def test_bad_inputs(self):
        for fn in (append_entry, verify_journal, serialize, load):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(TypeError):
                    fn("x")
        with self.assertRaises(ValueError):
            append_entry((), "zap", "u1")
        with self.assertRaises(ValueError):
            append_entry((), "move", "")

    def test_roundtrip(self):
        entries = append_entry((), "move", "u1", {"k": {"v": 1}})
        entries = append_entry(entries, "rollback_note", "u1")
        data = serialize(entries)
        back = load(data)
        self.assertEqual(back, entries)
        data[0]["detail"]["k"]["v"] = 99
        self.assertEqual(back[0].detail, {"k": {"v": 1}})

    def test_load_rejects(self):
        with self.assertRaises(ValueError):
            load([{"seq": 1, "op": "move", "target": "u"}])
        with self.assertRaises(ValueError):
            load([{"seq": 0, "op": "zap", "target": "u"}])


if __name__ == "__main__":
    unittest.main()
