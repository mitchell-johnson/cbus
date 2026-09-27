"""Pinned read-only C-Gate HELP differential evidence."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research import native_cgate_help_census as census
from research.native_cgate_help_census import matrix_paths


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
FIXTURE = ROOT / "research/fixtures/native-cgate-help-differential-acceptance.json"
MATRIX = REPOSITORY / "rust/cbus-cgate/src/capability_matrix.rs"


class NativeCGateHelpCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(FIXTURE.read_text())

    def test_fixture_covers_the_exact_primary_matrix_with_help_only(self):
        document = self.document
        self.assertEqual(document["format"],
                         "native-cgate-help-differential-acceptance-v1")
        self.assertTrue(document["passed"])
        paths = matrix_paths(MATRIX)
        self.assertEqual(document["inventory"]["path_count"], 431)
        for profile in document["profiles"].values():
            rows = profile["rows"]
            self.assertEqual(tuple(row["path"] for row in rows), paths)
            self.assertEqual(len({row["command"] for row in rows}), 431)
            for row in rows:
                with self.subTest(banner=profile["banner"], path=row["path"]):
                    self.assertEqual(row["command"], "HELP " + row["path"])
                    self.assertIn(row["status"], (101, 400))
                    self.assertTrue(row["response"])
                    self.assertEqual(int(row["response"][-1][:3]), row["status"])
                    self.assertEqual(row["response"][-1][3], " ")
                    self.assertTrue(all("\r" not in line and "\n" not in line
                                        for line in row["response"]))
            self.assertEqual(profile["help_star"]["command"], "HELP *")
            self.assertEqual(profile["help_star"]["status"], 101)

    def test_versions_hashes_and_read_only_boundary_are_explicit(self):
        document = self.document
        toolkit = document["original_toolkit_profile"]
        self.assertEqual(toolkit["file_version"], "1.18.0.2754")
        self.assertEqual(
            toolkit["exe_sha256"],
            "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab",
        )
        self.assertEqual(toolkit["gui_process_count"], 0)
        self.assertFalse(toolkit["gui_executed"])

        windows = document["profiles"]["owned_windows_existing_service"]
        target = document["profiles"]["target_cgate_3_4"]
        self.assertEqual((windows["version"], windows["build"]),
                         ("2.11.10", 3342))
        self.assertEqual((target["version"], target["build"]),
                         ("3.4.0", 2001))
        self.assertEqual(
            target["cgate_jar"]["sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630",
        )
        self.assertEqual(document["strict_ledger"]["accepted_slot_gain"], 0)
        self.assertEqual(document["strict_ledger"]["status_promotions"], [])
        boundary = " ".join(document["boundaries"])
        self.assertIn("Only HELP commands", boundary)
        self.assertIn("does not establish", boundary)

    def test_status_transition_summary_is_recomputed_from_exact_rows(self):
        profiles = self.document["profiles"]
        windows = profiles["owned_windows_existing_service"]["rows"]
        target = profiles["target_cgate_3_4"]["rows"]
        transitions = Counter(
            (left["status"], right["status"])
            for left, right in zip(windows, target, strict=True)
        )
        self.assertEqual(transitions, Counter({
            (101, 101): 240,
            (101, 400): 1,
            (400, 101): 153,
            (400, 400): 37,
        }))
        self.assertEqual(
            self.document["differential"]["status_transitions"],
            {"101_to_101": 240, "101_to_400": 1,
             "400_to_101": 153, "400_to_400": 37},
        )
        self.assertEqual(
            set(self.document["differential"]["target_syntax_error_paths"]),
            {row["path"] for row in target if row["status"] == 400},
        )

    def test_high_value_commissioning_and_application_help_is_exact(self):
        profiles = self.document["profiles"]
        windows = {row["path"]: row for row in
                   profiles["owned_windows_existing_service"]["rows"]}
        target = {row["path"]: row for row in
                  profiles["target_cgate_3_4"]["rows"]}
        self.assertEqual(target["NET UNRAVELUNIT"]["response"], [
            "101-Help: syntax: NET UNRAVELUNIT <net-address> <unit-addresses> [MATCHDB]",
            "101 Help: Unravel a unit address, placing all units at unique addresses. <net-address> is a valid network address. <unit-addresses> is a comma delimited list of valid unit addresses. if MATCHDB is specified then the units where possible will move to their addresses in the database.",
        ])
        self.assertEqual(target["NETWORK LOCATE"]["response"], [
            "101-Help: syntax: NETWORK LOCATE <application> <options> <mode>",
            "101-Help: Sends a locate yourself message to the matched units",
            "101-Help:  <application> must resolve to a valid Network application address.",
            "101-Help:  <options> is one of the following:",
            "101-Help:    UNIT <unit-number>",
            "101-Help:    APP <app-number>",
            "101-Help:    GROUP <app-number> <group-number>",
            "101-Help:    SERIAL <manufacturer> <serial-number>",
            "101 Help:  <mode> is ON, OFF, or a number in the range 0 through 255",
        ])
        self.assertEqual(target["DALI ADDRESS_UNKNOWN"]["response"], [
            "101-Help: syntax: dali address_unknown [mode=(auto)] <cdg-object-id> <line>",
            "101-Help: Starts assigning short addresses to all unaddressed devices on specified dali line.",
            "101-Help: Returns 64 bit bitmask of short addresses which have been assigned/discovered.",
            "101-Help: Does not resolve address conflicts.",
            "101-Help: monitor progress via dali address_unknown poll <cdg-object-id> <line>",
            "101-Help: [mode=(auto)] CAL command mode type.",
            "101-Help:    {auto, exec, poll, status, cancel}",
            "101-Help: <cdg-object-id> must be of type CDG (CBus DALI Gateway).",
            "101 Help: <line> refers to dali line A or B.",
        ])
        self.assertEqual(windows["DALI ADDRESS_UNKNOWN"]["response"],
                         ["400 Syntax Error."])
        for rows in (windows, target):
            self.assertEqual(rows["APPLICATIONS GET_CATALOG"]["response"], [
                "101-Help: syntax: APPLICATIONS GET_CATALOG",
                "101 Help: Get the applications catalog as XML",
            ])
        self.assertEqual(target["PP SAVE"]["response"], ["400 Syntax Error."])


class NativeCGateHelpHarnessTests(unittest.TestCase):
    def test_primary_matrix_parser_rejects_drift_and_injected_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.rs"
            path.write_text(
                'CapabilityEntry { path: "SAFE\\nINJECT", class: X, evidence: "x" },\n'
                'pub const SUPPLEMENT_ROUTING: &[X] = &[];\n'
            )
            with self.assertRaisesRegex(ValueError, "Expected 431"):
                matrix_paths(path)

    def test_direct_capture_constructs_help_only_commands(self):
        observed = []

        def exchange(host, port, command, tag, timeout):
            observed.append((host, port, command, tag, timeout))
            return {"command": command, "tag": tag, "banner": "201 ready",
                    "terminal": True, "lines": [f"[{tag}] 101 Help: ok"],
                    "error": None}

        with patch.object(census, "_exchange", side_effect=exchange):
            report = census.direct_capture(("NET UNRAVEL", "DALI ADDRESS_UNKNOWN"),
                                           "127.0.0.1", 20023, 3, "owned")
        self.assertEqual([row[2] for row in observed], [
            "HELP NET UNRAVEL", "HELP DALI ADDRESS_UNKNOWN", "HELP *",
        ])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["project_commands_sent"], 0)
        self.assertEqual(report["mutation_commands_sent"], 0)

    def test_windows_run_id_is_rejected_before_guest_io(self):
        with self.assertRaisesRegex(ValueError, "run-id"):
            census.windows_capture(("HELP",), "../unsafe", 1)


if __name__ == "__main__":
    unittest.main()
