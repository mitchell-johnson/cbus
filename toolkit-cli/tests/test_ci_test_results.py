"""CI results must distinguish executed calls, setup skips, and subtests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from research.ci_test_results import AuditError, audit, main


FIRST = "tests/test_first.py::test_with_subtests"
SECOND = "tests/test_second.py::test_setup_skip"


class CITestResultsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.junit = self.folder / "result.xml"
        self.trace = self.folder / "trace.json"
        self.write_junit()
        self.write_trace()

    def write_junit(self, *, tests=4, skipped=1, omit_nodeid=False):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", tests=str(tests), failures="0",
                              errors="0", skipped=str(skipped))
        first = ET.SubElement(suite, "testcase", classname="tests.test_first",
                              name="test_with_subtests")
        second = ET.SubElement(suite, "testcase", classname="tests.test_second",
                               name="test_setup_skip")
        ET.SubElement(second, "skipped", message="private fixture unavailable")
        for case, nodeid in ((first, FIRST), (second, SECOND)):
            properties = ET.SubElement(case, "properties")
            if not omit_nodeid:
                ET.SubElement(properties, "property", name="cbus_ci_nodeid", value=nodeid)
        self.junit.write_bytes(ET.tostring(root))

    def write_trace(self, *, started=None, calls=None, exitstatus=0):
        value = {
            "format": "cbus-ci-pytest-trace-v1",
            "collected": [FIRST, SECOND], "deselected": [],
            "started": [FIRST, SECOND] if started is None else started,
            "call_events": ([{"id": FIRST, "outcome": "passed"}] * 3
                            if calls is None else calls),
            "session_exitstatus": exitstatus,
        }
        self.trace.write_text(json.dumps(value))

    def test_receipt_counts_executed_subtests_and_setup_skip(self):
        receipt = audit(self.junit, self.trace, ["tests/test_first.py"])
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["counts"], {"tests": 4, "passed": 3,
                                               "skipped": 1, "failures": 0, "errors": 0})
        self.assertEqual(receipt["unitemized_subtests"]["reported"], 2)
        self.assertEqual([event["ordinal"] for event in receipt["call_events"]], [1, 2, 3])
        self.assertEqual([case["outcome"] for case in receipt["cases"]],
                         ["passed", "skipped"])

    def test_required_module_with_only_skips_fails_but_preserves_counts(self):
        receipt = audit(self.junit, self.trace, ["tests/test_second.py"])
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["missing_required_modules"], ["tests/test_second.py"])
        self.assertEqual(receipt["counts"]["skipped"], 1)

    def test_an_entirely_skipped_selection_is_not_green(self):
        root = ET.parse(self.junit).getroot()
        suite = root.find("testsuite")
        suite.set("tests", "2")
        suite.set("skipped", "2")
        ET.SubElement(suite.findall("testcase")[0], "skipped", message="missing binary")
        self.junit.write_bytes(ET.tostring(root))
        self.write_trace(calls=[])
        receipt = audit(self.junit, self.trace, [])
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["counts"]["skipped"], 2)

    def test_junit_counter_must_match_calls_and_setup_only_cases(self):
        self.write_junit(tests=5)
        with self.assertRaisesRegex(AuditError, "counter does not match"):
            audit(self.junit, self.trace, [])

    def test_junit_cases_need_trace_identity(self):
        self.write_junit(omit_nodeid=True)
        with self.assertRaisesRegex(AuditError, "lacks one CI trace node ID"):
            audit(self.junit, self.trace, [])

    def test_every_collected_test_must_start(self):
        self.write_trace(started=[FIRST])
        with self.assertRaisesRegex(AuditError, "did not start"):
            audit(self.junit, self.trace, [])

    def test_junit_skip_total_must_match_actual_skip_events(self):
        self.write_trace(calls=[{"id": FIRST, "outcome": "passed"},
                                {"id": FIRST, "outcome": "skipped"},
                                {"id": FIRST, "outcome": "passed"}])
        with self.assertRaisesRegex(AuditError, "skipped counter does not match"):
            audit(self.junit, self.trace, [])

    def test_failures_do_not_create_green_receipt(self):
        self.write_trace(exitstatus=1)
        self.assertFalse(audit(self.junit, self.trace, ["tests/test_first.py"])["passed"])

    def test_failed_and_errored_junit_cases_keep_detailed_red_receipts(self):
        for outcome, counter, calls in (
            ("failure", "failures", [{"id": FIRST, "outcome": "failed"}]),
            ("error", "errors", []),
        ):
            with self.subTest(outcome=outcome):
                root = ET.parse(self.junit).getroot()
                suite = root.find("testsuite")
                suite.set("tests", "2")
                suite.set(counter, "1")
                ET.SubElement(suite.findall("testcase")[0], outcome,
                              message="owned synthetic failure")
                self.junit.write_bytes(ET.tostring(root))
                self.write_trace(calls=calls, exitstatus=1)
                receipt = audit(self.junit, self.trace, [])
                self.assertFalse(receipt["passed"])
                self.assertEqual(receipt["counts"][counter], 1)
                self.assertEqual(receipt["cases"][0]["outcome"], outcome)
                self.assertEqual(receipt["unitemized_subtests"][counter], 0)
                self.write_junit()

    def test_missing_input_writes_a_path_free_failure_receipt(self):
        output = self.folder / "receipt.json"
        arguments = ["ci_test_results.py", "--junit", str(self.folder / "private.xml"),
                     "--trace", str(self.trace), "--output", str(output),
                     "--selection", "offline"]
        with patch("sys.argv", arguments):
            self.assertEqual(main(), 1)
        receipt = json.loads(output.read_text())
        self.assertEqual(receipt["error"], "Cannot audit CI test result: FileNotFoundError")
        self.assertNotIn(str(self.folder), output.read_text())


if __name__ == "__main__":
    unittest.main()
