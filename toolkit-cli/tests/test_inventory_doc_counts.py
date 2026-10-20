"""Inventory counts quoted in planning docs match the computed ledger (#71)."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import unittest

from cbus_toolkit import differential
from cbus_toolkit.evidence_audit import audit_evidence


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LEDGER_PATH = ROOT / "src" / "cbus_toolkit" / "capabilities.json"


def ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


class InventoryDocCountTests(unittest.TestCase):
    def test_ledger_area_counts_match_the_differential_matrix(self):
        areas = differential.build_matrix()["ledger_areas"]
        self.assertEqual(areas, len(ledger()["features"]))
        quoted = {
            "docs/parity-register.md": r"The (\d+)-row feature ledger remains",
            "docs/differential-plan.md": (
                r"\*\*(\d+) areas\*\*", r"One row per ledger area \((\d+) rows\)",
                r"`ledger_areas: (\d+)`", r"enumerates all (\d+) areas x",
            ),
            "src/cbus_toolkit/differential.py": r"(\d+)-area ledger in ``capabilities.json``",
        }
        for path, patterns in quoted.items():
            text = (ROOT / path).read_text(encoding="utf-8")
            for pattern in (patterns,) if isinstance(patterns, str) else patterns:
                with self.subTest(path, pattern=pattern):
                    match = re.search(pattern, text)
                    self.assertIsNotNone(match)
                    self.assertEqual(int(match[1]), areas)

    def test_issue11_scaffold_index_counts_and_files_are_current(self):
        text = (DOCS / "issue11-scaffolds.md").read_text(encoding="utf-8")
        statuses = Counter(feature["status"] for feature in ledger()["features"])
        match = re.search(r"\((\d+) implemented / (\d+) in_progress / (\d+) pending,", text)
        self.assertIsNotNone(match)
        self.assertEqual(
            tuple(int(value) for value in match.groups()),
            (statuses["implemented"], statuses["in_progress"], statuses["pending"]),
        )
        audit = audit_evidence(ledger(), ROOT)
        match = re.search(r"live ledger currently ([\d,]+) paths / (\d+) missing", text)
        self.assertIsNotNone(match)
        self.assertEqual(int(match[2]), len(audit.missing))
        for name in sorted(set(re.findall(r"`(test_[a-z0-9_]+\.py)`", text))):
            with self.subTest(test=name):
                self.assertTrue((ROOT / "tests" / name).is_file())
        for name in sorted(set(re.findall(r"`([a-z_]+\.py)`", text)) - {""}):
            if name.startswith("test_"):
                continue
            with self.subTest(module=name):
                self.assertTrue((ROOT / "src" / "cbus_toolkit" / name).is_file())


if __name__ == "__main__":
    unittest.main()
