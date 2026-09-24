"""Phase 4: coverage gate must stay honest/red (TDD).

Proves ``cbus-toolkit coverage --require-complete`` still exits nonzero
while the ledger is incomplete. This guards against status inflation:
``census_complete`` stays false and unfinished ledger IDs remain until a
later phase supplies independent acceptance evidence.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest


class CoverageRequireCompleteTests(unittest.TestCase):
    def test_require_complete_still_fails(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "coverage", "--require-complete"],
            text=True,
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
        combined = (proc.stdout or "") + (proc.stderr or "")
        start = combined.find("{")
        end = combined.rfind("}")
        self.assertGreaterEqual(start, 0, combined)
        self.assertGreater(end, start, combined)
        payload = json.loads(combined[start : end + 1])
        self.assertFalse(payload["complete"])
        self.assertFalse(payload["census_complete"])
        self.assertEqual(len(payload["features"]), 38)
        self.assertTrue(
            any(feature["status"] != "implemented" for feature in payload["features"])
        )
        by_id = {feature["id"]: feature for feature in payload["features"]}
        for pending_id in (
            "toolkit-differential-acceptance",
            "unit-hardware-acceptance",
        ):
            with self.subTest(area=pending_id):
                self.assertIn(pending_id, by_id)
                self.assertEqual(by_id[pending_id]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
