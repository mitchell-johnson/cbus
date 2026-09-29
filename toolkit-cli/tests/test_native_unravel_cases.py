"""Native NET UNRAVELUNIT captures on general duplicate topologies.

The committed fixture was captured from owned loopback C-Gate 3.4.0 build 2001
against the research-only ``UnravelBusFixture``. The executable plan in
``duplicate_resolution`` must predict every captured final topology and move
sequence. The native re-capture runs only with an explicit pinned Java11 and
vendor directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from cbus_toolkit.duplicate_resolution import LEGACY_ADDRESS, SELECTED_SERIAL, plan_unravel
from research.unravel_bus_fixture import UnravelBusFixture, keye1

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_unravel_cases.json"
SCRIPT = ROOT / "toolkit-cli/research/native_unravel_cases.py"
BUS = ROOT / "toolkit-cli/research/unravel_bus_fixture.py"
PCI_SERIAL = "100966.1187"
MOVED = re.compile(r"120-Unravel: Readdressed unit (?:with serial number (\S+) )? ?from address (\d+) \(0x[0-9A-F]{2}\) "
                   r"to address (\d+) \(0x[0-9A-F]{2}\)\.$")


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def predict(case):
    setup = case["setup"]
    physical = {16: [PCI_SERIAL]}
    for node in setup["nodes"]:
        physical.setdefault(node["address"], []).append(node["serial"])
    words = setup["command"].split()
    return plan_unravel(physical, {int(a): s for a, s in setup["database"].items()},
                        selection=[int(a) for a in words[3].split(",")],
                        match_database=words[-1] == "MATCHDB", local_unit=16, local_serial=PCI_SERIAL)


class CapturedUnravelTests(unittest.TestCase):
    def test_capture_provenance(self):
        captured = load()
        self.assertEqual(captured["format"], "cbus-native-unravel-cases-v1")
        self.assertEqual(captured["capture_script_sha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        self.assertEqual(captured["fixture_sha256"], hashlib.sha256(BUS.read_bytes()).hexdigest())
        oracle = captured["oracle"]
        self.assertEqual(oracle["vendor_jar_sha256"], "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630")
        self.assertEqual((oracle["version"], oracle["physical_endpoint"]), ("3.4.0 build 2001", False))
        for key in ("listener_ownership_verified", "cleanup_complete", "process_exit_confirmed", "work_removed"):
            self.assertIs(oracle[key], True)
        self.assertEqual(len(captured["cases"]), 14)
        for name, case in captured["cases"].items():
            with self.subTest(name=name):
                self.assertTrue(case["passed"])
                self.assertEqual((case["status"], case["reply"][-1]), (200, "200 OK."))
                self.assertEqual((case["cleanup_errors"], case["rejected_writes"]), ([], []))
                self.assertTrue(case["database_unchanged"])
                self.assertNotRegex(json.dumps(case), r"//UV[0-9A-F]{6}")

    def test_plan_predicts_every_native_final_topology_and_move_order(self):
        for name, case in load()["cases"].items():
            with self.subTest(name=name):
                plan = predict(case)
                self.assertIsNone(plan.refusal)
                final = {serial: address for serial, address in plan.final.items() if serial != PCI_SERIAL}
                self.assertEqual(final, case["after_topology"])
                native = [MOVED.match(line).groups() for line in case["reply"] if MOVED.match(line)]
                self.assertEqual([(m.source, m.destination) for m in plan.moves],
                                 [(int(source), int(target)) for _, source, target in native])
                # Native names the serial only for selected-serial broadcasts.
                self.assertEqual([m.serial if m.native_method == SELECTED_SERIAL else None for m in plan.moves],
                                 [serial for serial, _, _ in native])

    def test_plan_predicts_native_address_mechanism(self):
        for name, case in load()["cases"].items():
            with self.subTest(name=name):
                plan = predict(case)
                selected = [(op["serial"], op["requested"]) for op in case["co_operations"]]
                legacy = [(op["old"], op["new"]) for op in case["store_operations"]]
                self.assertEqual(selected, [(m.serial, m.destination) for m in plan.moves
                                            if m.native_method == SELECTED_SERIAL])
                self.assertEqual(legacy, [(m.source, m.destination) for m in plan.moves
                                          if m.native_method == LEGACY_ADDRESS])
                self.assertTrue(all(op["outcome"] == "moved" for op in case["co_operations"] + case["store_operations"]))

    def test_notable_native_outcomes(self):
        cases = load()["cases"]
        # A two-unit swap and an unknown healthy singleton are left alone.
        for name in ("swap_cycle", "unknown_serial_ordinary"):
            self.assertEqual(cases[name]["after_topology"], cases[name]["before_topology"])
            self.assertEqual(cases[name]["co_operations"] + cases[name]["store_operations"], [])
        # An occupied MATCHDB target is cleared to the lowest free address first,
        # ignoring the occupant's own database address.
        for name in ("matchdb_target_occupied_unknown", "matchdb_target_occupied_known"):
            self.assertEqual([(op["old"], op["new"]) for op in cases[name]["store_operations"]], [(6, 2), (255, 6)])
        # Free addresses skip database-assigned ones; order is descending serial.
        self.assertEqual(cases["free_address_skips_database"]["after_topology"], {"101136.1562": 4})
        self.assertEqual(cases["n3_at_255_reordered_no_db"]["after_topology"],
                         {"101136.1560": 2, "101136.1558": 4, "101136.1559": 3})
        # MATCHDB without a database keeper clears an ordinary duplicate address.
        self.assertNotIn(20, cases["n3_ordinary_matchdb_no_keeper"]["after_topology"].values())


class PlanValidationTests(unittest.TestCase):
    def test_refusals_and_input_validation(self):
        plan = plan_unravel({255: ["1.1"], 6: ["1.2"], 7: ["1.3"]}, {6: "1.1"}, selection=[255],
                            match_database=True)
        self.assertEqual([(m.serial, m.source, m.destination, m.reason) for m in plan.moves],
                         [("1.2", 6, 2, "displacement"), ("1.1", 255, 6, "database_match")])
        crowded = plan_unravel({255: ["1.1"], 6: ["1.2", "1.3"]}, {6: "1.1"}, selection=[255], match_database=True)
        self.assertRegex(crowded.refusal, "several units")
        local = plan_unravel({255: ["1.1"], 16: ["9.9"]}, {16: "1.1"}, selection=[255], match_database=True)
        self.assertRegex(local.refusal, "local PCI")
        full = plan_unravel({255: ["1.1", "1.2"], **{a: [f"2.{a}"] for a in range(2, 255) if a != 16}},
                            {}, selection=[255])
        self.assertRegex(full.refusal, "No free unit address")
        for bad in (lambda: plan_unravel({255: ["0.0"]}, {}), lambda: plan_unravel({255: []}, {}),
                    lambda: plan_unravel({2: ["1.1"], 3: ["1.1"]}, {}),
                    lambda: plan_unravel({256: ["1.1"]}, {}),
                    lambda: plan_unravel({2: ["1.1"]}, {}, match_database="yes"),
                    lambda: plan_unravel({2: ["1.1"]}, {}, local_serial="1.2")):
            with self.assertRaises(ValueError):
                bad()

    def test_numeric_not_lexicographic_serial_order(self):
        plan = plan_unravel({255: ["5.999", "5.1000"]}, {}, selection=[255])
        self.assertEqual([m.serial for m in plan.moves], ["5.1000", "5.999"])
        keeper = plan_unravel({20: ["5.999", "5.1000"]}, {}, selection=[20])
        self.assertEqual(keeper.kept, ((20, "5.999"),))


class BusFixtureTests(unittest.TestCase):
    def test_moves_record_occupancy_and_silent_nodes(self):
        fixture = UnravelBusFixture([keye1(255, 0x16), keye1(6, 0x17)], response_delay=0)
        context = {"header": None}
        reply, reason = fixture._command(b"\\05FF000F0018B106160615g", context)
        self.assertIsNone(reason)
        self.assertEqual(fixture.topology(), {"101136.1558": 6, "101136.1559": 6})
        self.assertEqual(fixture.co_operations[0]["outcome"], "moved_into_occupied")
        reply, _ = fixture._command(b"\\4606001120h", context)
        self.assertEqual(reply.count(b"82205A"), 2)
        reply, _ = fixture._command(b"\\460600A3204E075Aj", context)
        self.assertEqual(reply.count(b"32204E"), 2)
        self.assertEqual(fixture.topology(), {"101136.1558": 7, "101136.1559": 7})
        reply, _ = fixture._command(b"\\4607001A4201k", context)
        self.assertEqual(reply, b"k.")
        self.assertEqual(len(fixture.silent_reads), 2)


@unittest.skipUnless(all(os.environ.get(name) for name in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
                     "Select pinned Java11/vendor for owned original C-Gate unravel capture")
class NativeRecaptureTests(unittest.TestCase):
    def test_owned_native_recapture_matches_committed_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cases.json"
            subprocess.run([sys.executable, str(SCRIPT), "--output", str(output), "--runtime", directory],
                           check=True, cwd=ROOT / "toolkit-cli", timeout=900)
            fresh = json.loads(output.read_text())["cases"]
        for name, case in load()["cases"].items():
            with self.subTest(name=name):
                for key in ("status", "reply", "after_topology", "co_operations", "store_operations"):
                    self.assertEqual(fresh[name][key], case[key])


if __name__ == "__main__":
    unittest.main()
