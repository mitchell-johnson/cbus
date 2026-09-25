"""Tests for evidence_audit scaffold (boxes 14/16). Structural only."""
import unittest

from cbus_toolkit.evidence_audit import audit_evidence

import os
import tempfile


class AuditTests(unittest.TestCase):
    def test_all_present(self):
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, "a.md"), "w").write("x")
            ledger = {"features": [{"id": "f1", "evidence": ["a.md"]}]}
            got = audit_evidence(ledger, root)
            self.assertEqual((got.checked, got.missing), (1, ()))
            self.assertEqual(got.behavioral_comparison, "unassessed")

    def test_missing_reported_sorted(self):
        ledger = {"features": [
            {"id": "b", "evidence": ["gone2.md", "gone1.md"]},
            {"id": "a", "evidence": []},
        ]}
        with tempfile.TemporaryDirectory() as root:
            got = audit_evidence(ledger, root)
            self.assertEqual(got.checked, 2)
            self.assertEqual(got.missing, ("b:gone1.md", "b:gone2.md"))

    def test_bad_shapes(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises((TypeError, ValueError)):
                audit_evidence({}, root)
            with self.assertRaises((TypeError, ValueError)):
                audit_evidence({"features": [{"id": ""}]}, root)
            with self.assertRaises((TypeError, ValueError)):
                audit_evidence(
                    {"features": [{"id": "f", "evidence": [""]}]}, root)
            with self.assertRaises(ValueError):
                audit_evidence({"features": []},
                               os.path.join(root, "nope"))


if __name__ == "__main__":
    unittest.main()
