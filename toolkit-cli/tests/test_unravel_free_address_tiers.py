"""Second-tier free-address fallback for unravel planning (P3.03 offline slice).

Pure offline: a canned JSON fixture is written to a tmp dir and read back;
no hardware, network, simulator, daemon or C-Gate I/O is performed. This locks
the documented two-tier rule in
``toolkit-cli/src/cbus_toolkit/duplicate_resolution.py:129-135``
(``free_address``: lowest in 2..254 absent from both network and database,
then absent from the network only): when every network-free candidate is
database-assigned, the planner falls back to network-only vacancy instead of
refusing. The mirrored Rust closures
(``rust/cbus-cgate/src/service/unravel_plan.rs:130-147`` and ``:243-254``)
carry the same two-tier shape; this test pins the Python side only and makes
no semantic change.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cbus_toolkit.duplicate_resolution import SELECTED_SERIAL, plan_unravel


class SecondTierFreeAddressTests(unittest.TestCase):
    def test_dense_database_falls_back_to_network_only_vacancy(self):
        with tempfile.TemporaryDirectory(prefix="unravel-second-tier-") as tmp:
            fixture = Path(tmp) / "dense_db.json"
            payload = {
                "physical": {"255": ["1.1", "1.2"]},
                # Every network-free candidate (2..254) is database-assigned,
                # so tier 1 (network+database vacancy) finds nothing and tier 2
                # (network-only vacancy) must supply the destinations.
                "database": {str(address): f"10.{address}" for address in range(2, 255)},
                "selection": [255],
                "match_database": False,
            }
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            loaded = json.loads(fixture.read_text(encoding="utf-8"))
            physical = {int(address): serials for address, serials in loaded["physical"].items()}
            database = {int(address): serial for address, serial in loaded["database"].items()}
            plan = plan_unravel(
                physical,
                database,
                selection=loaded["selection"],
                match_database=loaded["match_database"],
            )
            self.assertIsNone(plan.refusal)
            # Descending serial order; both leave 255 together so the native
            # mechanism is the selected-serial broadcast.
            self.assertEqual(
                [(m.serial, m.source, m.destination, m.reason, m.native_method) for m in plan.moves],
                [
                    ("1.2", 255, 2, "free_address", SELECTED_SERIAL),
                    ("1.1", 255, 3, "free_address", SELECTED_SERIAL),
                ],
            )
            # Address 2 is database-assigned in the canned fixture, proving the
            # network-only fallback: tier 1 would have skipped it.
            self.assertIn("2", loaded["database"])
            self.assertEqual(plan.final, {"1.2": 2, "1.1": 3})
            self.assertEqual(plan.kept, ())


if __name__ == "__main__":
    unittest.main()
