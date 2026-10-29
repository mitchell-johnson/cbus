"""The Toolkit client inventory record (#161) stays schema-checked and bounded.

The record transcribes the recovered native reply checks from the static
decompile; these tests keep the record well-formed, provenance-bearing and
free of invented check fields.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "research" / "toolkit-client" / "inventory.json"

ALLOWED_KEYS = {
    "class", "classes", "command_text", "recording", "accept", "reject",
    "policy", "rows", "finishes_on", "fragments", "progress_fragments",
    "extends", "verbatim", "inferred_low_confidence", "low_confidence",
    "upgrade_trigger",
}
ALLOWED_RECORDINGS = {"complete", "partial"}


class ToolkitClientInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads(INVENTORY.read_text())

    def test_provenance_and_recovery_are_fully_declared(self):
        for key in ("schema_version", "subject", "recovery", "shared_reply_parser",
                    "managed_client_facts", "low_confidence", "classes"):
            self.assertIn(key, self.record)
        recovery = self.record["recovery"]
        self.assertEqual(
            recovery["tools"][0], "REA over the managed DLLs (SharpCGateCommunicator 7.15)")
        self.assertTrue(recovery["tools"][1].startswith("Ghidra 12.1.4"))
        self.assertEqual(recovery["execution"], "Nothing was executed.")
        self.assertLessEqual(recovery["off_repository_bounds"],
                             ["vendor binaries", "decompiled source", "key material"])
        self.assertEqual(recovery["off_repository_bounds"].index("vendor binaries"), 0)

    def test_shared_parser_matches_the_recovered_rules(self):
        parser = self.record["shared_reply_parser"]
        self.assertEqual(parser["command_framing"].startswith("Commands go out as [<id>]"), True)
        self.assertEqual(parser["error_policy"], "Only the first error raised counts.")
        self.assertIn("StrToIntDef", parser["status_code"])
        self.assertIn("OnProcessResults", parser["row_dispatch"])

    def test_managed_client_facts_are_pinned_to_the_decompile(self):
        facts = self.record["managed_client_facts"]
        self.assertEqual(facts["tls_port"], 20123)
        self.assertEqual(facts["plain_port"], 20023)
        self.assertEqual(facts["default_timeout_seconds"], 10)
        self.assertEqual(facts["timeouts_seconds"]["PPLoad"], 60)
        self.assertEqual(facts["timeout_error_code"], 9999)

    def test_every_class_entry_only_uses_recorded_fields(self):
        seen = set()
        for entry in self.record["classes"]:
            self.assertTrue(entry.get("class"), entry)
            recording = entry.get("recording")
            self.assertIn(recording, ALLOWED_RECORDINGS, entry)
            unknown = set(entry) - ALLOWED_KEYS
            self.assertEqual(unknown, set(), entry["class"])
            self.assertTrue(entry["class"] not in seen)
            seen.add(entry["class"])

    def test_low_confidence_rows_are_declared_at_the_top_level(self):
        self.assertEqual(
            self.record["low_confidence"],
            ["argument layouts (from string joins)", "DBGet 401",
             "ProjectSave 408", "the Event 412-421 range"])

    def test_typed_project_start_and_config_families_are_recorded(self):
        names = {entry["class"] for entry in self.record["classes"]}
        for name in ("ProjectStart", "ConfigGet", "ConfigGetSetOB", "APIver",
                     "NetTextFamily", "PortProbe", "PortCNIScan", "KFIGet",
                     "DoPsyncResetHardwareRecallResetOpStats",
                     "SyncReadRawValuesSingleUnravel", "TcgcIdentify",
                     "GetFamily"):
            self.assertIn(name, names)

    def test_configget_and_apiver_record_only_the_recovered_fragments(self):
        classes = {entry["class"]: entry for entry in self.record["classes"]}
        self.assertEqual(
            classes["ConfigGet"]["recording"], "complete")
        self.assertIn("401 Bad object or device ID", classes["ConfigGet"]["reject"])
        self.assertEqual(classes["ConfigGet"]["finishes_on"], {"303": "ends"})
        self.assertEqual(classes["APIver"]["accept"], {"138": "x=a.b form"})


if __name__ == "__main__":
    unittest.main()
