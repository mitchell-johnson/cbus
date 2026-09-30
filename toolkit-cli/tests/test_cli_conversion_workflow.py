"""Public conversion inputs fail locally before a C-Gate connection."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import build_parser, run
from cbus_toolkit.conversion_workflow_cli import execute


class ConversionWorkflowCLIInputs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def refused_without_connection(self, words, pattern):
        args = build_parser().parse_args(["cgate", *words])
        with patch("cbus_toolkit.cgate.CGateClient") as client:
            with self.assertRaisesRegex(ValueError, pattern):
                run(args)
            client.assert_not_called()

    def test_plan_requires_exclusive_project_and_never_overwrites(self):
        output = self.directory / "plan.json"
        words = ["conversion", "plan-move", "//TEST/254/p/20", "//TEST/254/p/21",
                 "--backup-project", "BACKUP", "--spec-dir", str(self.directory),
                 "--output", str(output)]
        self.refused_without_connection(words, "exclusive-project")
        output.write_text("operator-held plan")
        self.refused_without_connection([*words, "--exclusive-project"], "already exists")
        self.assertEqual(output.read_text(), "operator-held plan")

    def test_malformed_or_duplicate_plan_and_journal_fail_before_connection(self):
        plan = self.directory / "plan.json"
        for raw in ("{", '{"format":1,"format":2}', json.dumps({"format": "unknown"})):
            with self.subTest(raw=raw):
                plan.write_text(raw)
                self.refused_without_connection(
                    ["conversion", "apply-move", "--plan", str(plan), "--journal",
                     str(self.directory / "attempt.json"), "--spec-dir", str(self.directory),
                     "--exclusive-project"], ".+")
                self.refused_without_connection(
                    ["conversion", "recover", "--journal", str(plan)], ".+")

    def test_unavailable_recovery_has_nonzero_exit_and_retains_observation_error(self):
        args = build_parser().parse_args(
            ["cgate", "conversion", "recover", "--journal", str(self.directory / "attempt.json")])
        cases = [
            ({"disposition": "read-unavailable", "error": "server unavailable",
              "persistence_verified": False, "replay_authorized": False}, 1),
            ({"disposition": "observed-before", "backup_verified_fresh": True,
              "observation": {"matched": False, "read_error": {
                  "type": "OSError", "message": "fresh PP read unavailable"}},
              "persistence_verified": False, "replay_authorized": False}, 1),
            ({"disposition": "observed-before", "backup_verified_fresh": True,
              "observation": {"matched": False}, "persistence_verified": False,
              "replay_authorized": False}, 0),
        ]
        for evidence, expected_status in cases:
            with self.subTest(evidence=evidence):
                with patch("cbus_toolkit.conversion_workflow_cli.ConversionWorkflow") as workflow:
                    workflow.return_value.recover.return_value = evidence
                    result, status = execute(args, object())
                self.assertEqual(status, expected_status)
                self.assertEqual(result, evidence)


if __name__ == "__main__":
    unittest.main()
