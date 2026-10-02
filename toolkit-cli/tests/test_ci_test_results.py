"""CI results must distinguish executed calls, setup skips, and subtests."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from research.ci_test_results import AuditError, audit, main


FIRST = "tests/test_first.py::test_with_subtests"
SECOND = "tests/test_second.py::test_setup_skip"


class NewInteropSelectionTests(unittest.TestCase):
    """A green backend job must retain every newly accepted public journey."""

    def test_make_and_ci_retain_exact_new_backend_rosters(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / "toolkit-cli/Makefile").read_text()
        workflow = (root / ".github/workflows/ci.yml").read_text()
        modules = ("test_cgate_toolkit_tweaker_remaining_interop.py",
                   "test_cgate_csv_completion_interop.py",
                   "test_cgate_edlt_parent_add_dialog_interop.py")
        cases = (
            "neo-secondary-mask-removal-before-area-reshape",
            "neo-matching-application-object-removes-primary-too",
            "neo-unused-secondary-keeps-lexical-application",
            "neo-all-secondary-area-is-independent",
            "dali-forward-swap-decimal", "dali-catalogue-alias-forward",
            "dali-reverse-swap", "dali-alias-reverse-swap",
            "older-pir-six-default-fields-and-polarity-aligned",
            "older-pir-self-retains-fresh-learning-history",
            "older-light-level-self-no-st7-lux-rewrite",
            "older-light-level-to-multisensor-rename-and-fresh-unassigned-groups",
            "older-multisensor-self-input-flag-overridden-and-join-reset",
        )
        remaining = "tests/" + modules[0] + "::"
        csv = "tests/" + modules[1] + "::"
        parent = "tests/" + modules[2] + "::"
        for backend, target, selection in (
                ("mock", "check-cgate-interop", "cgate-mock"),
                ("daemon", "check-cmqtt-interop", "cmqttd")):
            with self.subTest(backend=backend):
                expected = {
                    remaining + "test_public_remaining_conversion_literal_and_lifecycle["
                    + case + "-" + operation + "-" + backend + "]"
                    for case in cases for operation in ("create", "replace")}
                expected.update(remaining + "test_public_remaining_conversion_lost_success_never_replays["
                                + action + "-" + backend + "]"
                                for action in ("create-PP SAVE_TO_SOURCE", "replace-DBDELETE"))
                expected.update(csv + name + "[" + suffix + backend + "]" for name, suffix in (
                    ("test_public_csv_completion_all_templates_and_ordered_selection", ""),
                    ("test_public_csv_completion_late_refusal_is_atomic", "bad-profile-"),
                    ("test_public_csv_completion_late_refusal_is_atomic", "missing-application-"),
                    ("test_public_csv_completion_lost_snapshot_is_not_retried", "")))
                expected.update(parent + "test_public_parent_add_history_one_save_and_full_preservation["
                                + case + "-" + backend + "]"
                                for case in ("corridor-and-activation", "cancel-repeat",
                                             "preceding-enable", "scene-interleave",
                                             "initial-scene-getter", "corridor-future-absence",
                                             "application-switch-future-absence"))
                expected.add(parent + "test_public_parent_add_lost_save_success_is_not_replayed["
                             + backend + "]")
                body = make.split(target + ": compile\n", 1)[1].split("\n\n", 1)[0]
                selected = re.findall(r"'(tests/test_[^']+)'", body)
                actual = [node for node in selected
                          if any(node.startswith("tests/" + module + "::") for module in modules)]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                self.assertEqual(len(expected), 40)
                aliases = {"tests/test_cgate_toolkit_tweaker_dlt_interop.py::"
                           "test_public_dlt_tweaker_profile_create_and_replace["
                           "keybir2-literal-keyb2-catalogue-alias-" + operation + "-" + backend + "]"
                           for operation in ("create", "replace")}
                self.assertTrue(aliases <= set(selected))
                audit_body = workflow.split("--selection " + selection + "\n", 1)[1].split(
                    "\n      - name:", 1)[0]
                for module in modules:
                    self.assertEqual(audit_body.count("--require-module tests/" + module), 1)

    def test_final_csv_and_documentation_public_rosters_are_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        csv = 'tests/test_cgate_csv_last_profiles_interop.py'
        document = 'tests/test_cgate_project_documentation_interop.py'
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                            ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {
                    csv + '::test_public_csv_last_profiles_all_literals_and_ordered_selection[' + backend + ']',
                    csv + '::test_public_csv_last_profiles_lost_snapshot_is_terminal_without_replay[' + backend + ']',
                }
                expected.update(csv + '::test_public_csv_last_profiles_refusal_is_atomic[' + fault + '-'
                                + backend + ']' for fault in ('bad-profile', 'missing-application',
                                    'missing-secondary-input-group', 'missing-unused-temperature-group', 'bad-fan-route'))
                expected.update(document + '::' + name + '[' + backend + ']' for name in (
                    'test_public_database_document_snapshot_and_literal_bodies',
                    'test_public_database_document_absent_network_is_atomic',
                    'test_public_database_document_lost_snapshot_has_no_output_or_retry'))
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith((csv + '::', document + '::'))]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                self.assertEqual(len(expected), 10)
                audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                for module in (csv, document):
                    self.assertEqual(audit.count('--require-module ' + module), 1)

    def test_application_reset_add_public_roster_is_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_cgate_edlt_application_reset_add_interop.py'
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                            ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {module + '::test_public_application_reset_add_complete_history[' + case + '-'
                            + backend + ']' for case in ('application-description-group',
                                'cancel-repeated-primary-secondary', 'reset-application-group',
                                'reset-cancelled-application-fresh-primary',
                                'reset-initial-scene-before-action', 'reset-application-scene-corridor',
                                'preceding-and-future-owner', 'expanded-reserved-confirmed')}
                expected.update(module + '::' + name + '[' + backend + ']' for name in (
                    'test_public_application_reset_add_lost_save_is_not_replayed',
                    'test_public_application_add_guards_refuse_without_persistent_send'))
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith(module + '::')]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                self.assertEqual(len(expected), 10)
                audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                self.assertEqual(audit.count('--require-module ' + module), 1)

    def test_static_language_and_recovered_report_public_rosters_are_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        parent = 'tests/test_cgate_edlt_static_language_add_interop.py'
        sensors = 'tests/test_cgate_project_documentation_sensors_interop.py'
        wireless = 'tests/test_cgate_project_documentation_wireless_interop.py'
        l1 = 'tests/test_cgate_project_documentation_l1_interop.py'
        architectural = 'tests/test_cgate_project_documentation_architectural_interop.py'
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                           ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {parent + '::test_public_static_language_parent_complete_history[' + case
                            + '-' + backend + ']' for case in ('default-repair-grid-before-widget',
                                'cancel-repeated-selected-list', 'absent-collection-chinese',
                                'zero-default-first-selected', 'allocated-widget-then-grid',
                                'language-parent-and-scene-add')}
                expected.update(parent + '::test_public_static_language_lost_success_stops_without_replay['
                                + stage + '-' + backend + ']' for stage in ('add', 'set', 'pp-save'))
                expected.add(parent + '::test_public_static_language_invalid_history_never_writes[' + backend + ']')
                if backend == 'daemon':
                    expected.update(parent + '::test_public_static_language_authentication_stops_before_write['
                                    + failure + ']' for failure in ('missing', 'wrong'))
                expected.add(sensors + '::test_public_database_document_sensor_families_preserves_snapshot[' + backend + ']')
                expected.add(wireless + '::test_public_database_document_wireless_families_preserves_snapshot[' + backend + ']')
                expected.add(l1 + '::test_public_database_document_l1_preserves_snapshot_and_literal_body[' + backend + ']')
                expected.add(architectural + '::test_public_database_document_architectural_families_preserves_snapshot[' + backend + ']')
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith((parent + '::', sensors + '::', wireless + '::', l1 + '::', architectural + '::'))]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                audit_body = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                for module in (parent, sensors, wireless, l1, architectural):
                    self.assertEqual(audit_body.count('--require-module ' + module), 1)

    def test_grid_native_address_and_st7_public_rosters_are_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        grid = 'tests/test_cgate_edlt_static_grid_editor_interop.py'
        native = 'tests/test_cgate_project_documentation_native_addresses_interop.py'
        st7 = 'tests/test_cgate_project_documentation_st7_light_level_interop.py'
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {grid + '::test_public_static_grid_history_preview_apply_and_preservation['
                            + case + '-' + backend + ']' for case in
                            ('cell-transactions', 'cached-split-name', 'malformed-preserved')}
                expected.update(grid + '::' + name + '[' + backend + ']' for name in
                                ('test_public_pending_cell_close_refuses_without_write',
                                 'test_public_static_grid_lost_successful_save_is_not_replayed'))
                expected.update(native + '::test_public_native_report_exact_named_identity_and_physical_references['
                                + backend + '-' + kind + ']' for kind in ('thermostat', 'wireless'))
                expected.add(st7 + '::test_public_database_document_st7_zero_timers_stored_scenes_and_direct_roles['
                             + backend + ']')
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith((grid + '::', native + '::', st7 + '::'))]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                for module in (grid, native, st7):
                    self.assertEqual(audit.count('--require-module ' + module), 1)


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
