"""Typed CLI workflows for the remaining Toolkit command families (#162).

Each command sends Toolkit's own recovered command text and classifies replies
exactly as far as `research/toolkit-client/inventory.json` records them;
unrecorded replies fail closed and the command is never retried.
"""

import json
import subprocess
import sys
import unittest

from tests.test_cgate import peer


class ToolkitCommandFamilyTests(unittest.TestCase):
    def cli(self, host, port, *arguments, status=0):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate",
             "--host", host, "--port", str(port), *map(str, arguments)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, status, process.stderr + process.stdout)
        return json.loads(process.stdout if process.stdout else process.stderr)

    def cli_failure(self, host, port, *arguments):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate",
             "--host", host, "--port", str(port), *map(str, arguments)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, 1, process.stderr + process.stdout)
        return json.loads(process.stderr)

    def cli_argparse_failure(self, *arguments):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate",
             "--host", "127.0.0.1", "--port", "1", *map(str, arguments)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, 2, process.stderr + process.stdout)
        self.assertIn("error:", process.stderr)
        return process.stderr


class ToolkitFamilyWireTests(ToolkitCommandFamilyTests):
    """Every recovered-surface wire/failure case (single copy, no subclasses)."""

    # -- project start ----------------------------------------------------------

    def test_project_start_sends_recovered_text_and_accepts_200(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "project", "start", "TOOLKIT")
        self.assertEqual(sent, [b"[1] PROJECT START TOOLKIT\r\n"])
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["final"], "200 OK.")
        self.assertEqual(result["lines"], ["200 OK."])

    def test_project_start_refuses_408_and_never_replays(self):
        with peer([[b"[1] 408 project not closed\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "project", "start", "TOOLKIT")
        self.assertEqual(sent, [b"[1] PROJECT START TOOLKIT\r\n"])
        self.assertEqual(failure["type"], "CGateError")

    def test_project_start_rejects_invalid_names_before_sending(self):
        self.cli_argparse_failure("project", "start")

    # -- config obget / obset ---------------------------------------------------

    def test_config_obget_streams_rows_and_finishes_on_303(self):
        with peer([[b"[1] 300-x=toolkit.hello\r\n[1] 303 test\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "config", "obget", "//TEST/254", "project.default")
        self.assertEqual(sent, [b"[1] config obget //TEST/254 project.default\r\n"])
        self.assertEqual(result["operation"], "config-obget")
        self.assertEqual(result["rows"], ["300-x=toolkit.hello", "303 test"])
        self.assertTrue(result["cgate_accepted"])
        self.assertFalse(result["device_effects_verified"])
        self.assertFalse(result["durable_override_intended"])

    def test_config_obget_refuses_recovered_errors_text(self):
        for reply in (b"[1] 401 Bad object or device ID\r\n",
                      b"[1] 400 Syntax Error.\r\n"):
            with self.subTest(reply=reply), peer([[reply]]) as ((host, port), sent):
                failure = self.cli_failure(host, port, "config", "obget", "//TEST/254", "key")
            self.assertEqual(sent, [b"[1] config obget //TEST/254 key\r\n"])
            self.assertEqual(failure["reply_classification"], "recorded")

    def test_config_obget_other_finish_fails_closed_as_unmodeled(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "config", "obget", "//TEST/254", "key")
        self.assertEqual(sent, [b"[1] config obget //TEST/254 key\r\n"])
        self.assertEqual(failure["reply_classification"], "unmodeled")

    def test_config_obset_sends_optional_value_and_records_durable_override(self):
        cases = (
            ("FOO", b"[1] config obset //TEST/254 favorite FOO\r\n"),
            (None, b"[1] config obset //TEST/254 favorite\r\n"),
        )
        for value, wire in cases:
            with self.subTest(value=value), peer([[b"[1] 303 test\r\n"]]) as ((host, port), sent):
                arguments = ("config", "obset", "//TEST/254", "favorite")
                if value is not None:
                    arguments = arguments + (value,)
                result = self.cli(host, port, *arguments)
            self.assertEqual(sent, [wire])
            self.assertEqual(result["operation"], "config-obset")
            self.assertTrue(result["cgate_accepted"])
            self.assertTrue(result["durable_override_intended"])

    def test_config_obset_single_token_value_is_enforced(self):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate",
             "--host", "127.0.0.1", "--port", "1",
             "config", "obset", "//TEST/254", "favorite", "TWO WORDS",
             "--host", "127.0.0.1"],
            capture_output=True, text=True, timeout=30)
        self.assertIn("error:", process.stderr)

    # -- label kfiget -----------------------------------------------------------

    def test_label_kfiget_reads_recovered_kfi_rows(self):
        rows = [b"[1] 300-kfi1 light 56\r\n", b"[1] 300 kfi8\r\n"]
        with peer([tuple(rows)]) as ((host, port), sent):
            result = self.cli(host, port, "label", "kfiget", "//TEST/254/56", 8)
        self.assertEqual(sent, [b"[1] label kfiget //TEST/254/56 8\r\n"])
        self.assertEqual(result["operation"], "label-kfiget")
        self.assertEqual(result["rows"], ["300-kfi1 light 56", "300 kfi8"])
        self.assertTrue(result["cgate_accepted"])
        self.assertEqual(result["argument_layout_confidence"], "low")

    def test_label_kfiget_rejects_invalid_group_before_connect(self):
        self.cli_argparse_failure("label", "kfiget", "//TEST/254/56", 300)

    def test_label_kfiget_non_kfi_rows_fail_closed(self):
        with peer([[b"[1] 300 hello world\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "label", "kfiget", "//TEST/254/56", 8)
        self.assertEqual(sent, [b"[1] label kfiget //TEST/254/56 8\r\n"])
        self.assertEqual(failure["reply_classification"], "unmodeled")

    # -- port probe / cniscan ---------------------------------------------------

    def test_port_probe_sends_recovered_text_and_accepts_230_ok(self):
        with peer([[b"[1] 230 ok\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "port", "probe", "COM1")
        self.assertEqual(sent, [b"[1] port probe COM1\r\n"])
        self.assertEqual(result["operation"], "port-probe")
        self.assertTrue(result["cgate_accepted"])

    def test_port_probe_classifies_recorded_errors(self):
        cases = (
            ((b"[1] 431 port not stopped\r\n",), "recorded"),
            ((b"[1] 432 Port would not open\r\n",), "recorded"),
            ((b"[1] 408 No Catalog Available\r\n",), "recorded"),
            ((b"[1] 409 PC interface not detected\r\n",), "recorded"),
            ((b"[1] 200 ok\r\n",), "unmodeled"),
        )
        for reply_rows, classification in cases:
            with self.subTest(reply=reply_rows), peer([reply_rows]) as ((host, port), sent):
                failure = self.cli_failure(host, port, "port", "probe", "COM1")
            self.assertEqual(sent, [b"[1] port probe COM1\r\n"])
            self.assertEqual(failure["cgate_accepted"], False)
            self.assertEqual(failure["reply_classification"], classification)

    def test_port_cniscan_streams_129_rows_and_finishes_on_130(self):
        with peer([[b"[1] 129-10\r\n[1] 130 complete\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "port", "cniscan", "COM2")
        self.assertEqual(sent, [b"[1] port cniscan COM2\r\n"])
        self.assertEqual(result["operation"], "port-cniscan")
        self.assertEqual(result["rows"], ["129-10", "130 complete"])
        self.assertTrue(result["cgate_accepted"])

    def test_port_cniscan_appends_the_recovered_fast_variant(self):
        with peer([[b"[1] 130 complete\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "port", "cniscan", "COM2", "--fast")
        self.assertEqual(sent, [b"[1] port cniscan COM2 fast\r\n"])
        self.assertTrue(result["cgate_accepted"])

    def test_port_cniscan_other_finish_fails_closed(self):
        with peer([[b"[1] 200 ok\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "port", "cniscan", "COM2")
        self.assertEqual(sent, [b"[1] port cniscan COM2\r\n"])
        self.assertEqual(failure["reply_classification"], "unmodeled")

    # -- unit get-parameter -----------------------------------------------------

    def test_unit_get_parameter_reads_recovered_parameters(self):
        cases = (("NetVoltage", b"300 NetVoltage=235"),)
        for parameter, body in cases:
            with self.subTest(parameter=parameter), peer(
                    [[b"[1] " + body + b"\r\n"]]) as ((host, port), sent):
                result = self.cli(host, port, "unit-get", "//TEST/254/p/22", parameter)
            self.assertEqual(sent, [b"[1] GET //TEST/254/p/22 " + parameter.encode() + b"\r\n"])
            self.assertEqual(result["operation"], "unit-get")
            self.assertEqual(result["parameter"], parameter)
            self.assertTrue(result["cgate_accepted"])
            self.assertFalse(result["value_readback_verified"])

    def test_unit_get_parameter_dcpversion_requires_recovered_fragment(self):
        reply_rows = {
            b"[1] 300 dcpversion=2.3.45\r\n": None,
            b"[1] 300 mixed=1.0\r\n": "unmodeled",
        }
        for body, classification in reply_rows.items():
            with self.subTest(body=body), peer([[body]]) as ((host, port), sent):
                if classification is None:
                    self.cli(host, port, "unit-get", "//TEST/254/p/22", "DCPVersion")
                else:
                    failure = self.cli_failure(host, port, "unit-get",
                                               "//TEST/254/p/22", "DCPVersion")
                    self.assertEqual(failure["reply_classification"], classification)

    def test_unit_get_parameter_reads_the_full_recovered_family(self):
        for parameter in ("DSIChannelStatus", "DSIUnitStatus", "Current", "OpStats",
                          "ChannelMode", "ControlMode", "ErrorState",
                          "DCPPanic1InputActive", "DCPPanic2InputActive",
                          "DCPPanic3InputActive", "DCPBackupGenActive",
                          "DCPHalogenCleanupActive", "RawValue"):
            with self.subTest(parameter=parameter), peer(
                    [[b"[1] 300 x=y\r\n"]]) as ((host, port), sent):
                self.cli(host, port, "unit-get", "//TEST/254/p/22", parameter)
            self.assertEqual(sent, [b"[1] GET //TEST/254/p/22 " + parameter.encode() + b"\r\n"])

    def test_unit_get_parameter_unknown_parameter_is_argparse_error(self):
        self.cli_argparse_failure("unit-get", "//TEST/254/p/22", "Voltage")

    def test_unit_get_parameter_text_errors_classify(self):
        with peer([[b"[1] 420 Parameter RawValue not found\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "unit-get",
                                       "//TEST/254/p/22", "RawValue")
        self.assertEqual(sent, [b"[1] GET //TEST/254/p/22 RawValue\r\n"])
        self.assertEqual(failure["reply_classification"], "recorded")

    # -- unit do ----------------------------------------------------------------

    def test_unit_do_readrawvalues_accepts_202_done(self):
        with peer([[b"[1] 202 Done\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "unit-do", "//TEST/254/p/22", "readrawvalues")
        self.assertEqual(sent, [b"[1] DO //TEST/254/p/22 readrawvalues\r\n"])
        self.assertEqual(result["operation"], "unit-do-readrawvalues")
        self.assertTrue(result["cgate_accepted"])
        self.assertFalse(result["device_effects_verified"])
        self.assertFalse(result["automatic_replay"])

    def test_unit_do_unmodeled_fails_closed(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "unit-do", "//TEST/254/p/22", "readrawvalues")
        self.assertEqual(sent, [b"[1] DO //TEST/254/p/22 readrawvalues\r\n"])
        self.assertEqual(failure["reply_classification"], "unmodeled")

    def test_unit_do_unknown_operation_is_argparse_error(self):
        self.cli_argparse_failure("unit-do", "//TEST/254/p/22", "ResetHardware")

    # -- unit reset-hardware ----------------------------------------------------

    def test_unit_reset_hardware_default_only_plans_without_connecting(self):
        result = self.cli("127.0.0.1", 65534, "unit-reset-hardware", "//TEST/254/p/22")
        self.assertEqual(result["operation"], "unit-reset-hardware")
        self.assertEqual(result["planned_command"], "DO //TEST/254/p/22 ResetHardware")
        self.assertFalse(result["request_sent"])

    def test_unit_reset_hardware_request_sends_once_and_never_replays(self):
        with peer([[b"[1] 202 Done\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "unit-reset-hardware", "//TEST/254/p/22", "--request")
        self.assertEqual(sent, [b"[1] DO //TEST/254/p/22 ResetHardware\r\n"])
        self.assertEqual(result["operation"], "unit-reset-hardware")
        self.assertTrue(result["cgate_accepted"])
        self.assertFalse(result["device_effects_verified"])
        self.assertFalse(result["automatic_replay"])

    def test_unit_reset_hardware_recorded_errors_fail_closed(self):
        for reply in (b"[1] 401 Bad object\r\n", b"[1] 420 Access denied\r\n",
                      b"[1] 408 No Catalog Available\r\n"):
            with self.subTest(reply=reply), peer([[reply]]) as ((host, port), sent):
                failure = self.cli_failure(host, port, "unit-reset-hardware",
                                           "//TEST/254/p/22", "--request")
            self.assertEqual(sent, [b"[1] DO //TEST/254/p/22 ResetHardware\r\n"])
            self.assertEqual(failure["reply_classification"], "recorded")

    # -- id ----------------------------------------------------------------------

    def test_id_reads_exactly_one_typed_or_version_row(self):
        for attribute, body in (("type", b"type=5055EDL"), ("version", b"version=2.7.00")):
            with self.subTest(attribute=attribute), peer(
                    [[b"[1] 300 " + body + b"\r\n"]]) as ((host, port), sent):
                result = self.cli(host, port, "id", "//TEST/254/p/22", attribute)
            self.assertEqual(sent, [b"[1] ID //TEST/254/p/22 " + attribute.encode() + b"\r\n"])
            self.assertEqual(result["operation"], "unit-id")
            self.assertEqual(result["attribute"], attribute)
            self.assertTrue(result["cgate_accepted"])
            self.assertFalse(result["device_effects_verified"])

    def test_id_classifies_the_recovered_error_statuses(self):
        cases = (
            b"[1] 827 C-Bus Send Error\r\n",
            b"[1] 821 Unit unavailable\r\n",
        )
        for reply in cases:
            with self.subTest(reply=reply), peer([[reply]]) as ((host, port), sent):
                failure = self.cli_failure(host, port, "id", "//TEST/254/p/22", "type")
            self.assertEqual(sent, [b"[1] ID //TEST/254/p/22 type\r\n"])
            # The transport surfaces 7xx/8xx rows as statusless; the receipt
            # uses the class's recorded fallthrough instead of the code.
            self.assertEqual(failure["reply_classification"], "statusless_row")
            self.assertIn("Could not read unit ID", json.dumps(failure))
        with peer([[b"[1] 401 Bad object or device ID\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "id", "//TEST/254/p/22", "type")
        self.assertEqual(sent, [b"[1] ID //TEST/254/p/22 type\r\n"])
        self.assertEqual(failure["reply_classification"], "recorded")
        with peer([[b"[1] 300 unexpected\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "id", "//TEST/254/p/22", "type")
        self.assertEqual(sent, [b"[1] ID //TEST/254/p/22 type\r\n"])
        self.assertEqual(failure["reply_classification"], "unmodeled")

    def test_id_fallthrough_uses_the_recovered_message(self):
        with peer([[b"[1] 999 garbage\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "id", "//TEST/254/p/22", "type")
        self.assertEqual(sent, [b"[1] ID //TEST/254/p/22 type\r\n"])
        self.assertEqual(failure["reply_classification"], "statusless_row")
        self.assertIn("Could not read unit ID", json.dumps(failure))


if __name__ == "__main__":
    unittest.main()


class TransformMigrateSqlTests(ToolkitCommandFamilyTests):
    """Toolkit's recovered TRANSFORM MIGRATE_SQL lifecycle (#160, #162)."""

    def test_transform_migrate_sql_streams_199_rows_and_finishes_on_200(self):
        with peer([[b"[1] 199-Before: DBVersions match\r\n",
                    b"[1] 199-After: Transform from 2.2 to 2.3\r\n",
                    b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "project", "transform-migrate-sql", "SERVER")
        self.assertEqual(sent, [b"[1] TRANSFORM MIGRATE_SQL SERVER\r\n"])
        self.assertEqual(result["operation"], "transform-migrate-sql")
        self.assertEqual(result["status"], 200)
        self.assertFalse(result["native_upgrade_flow_detected"])
        self.assertTrue(result["cgate_accepted"])
        self.assertFalse(result["device_effects_verified"])
        self.assertFalse(result["automatic_replay"])

    def test_transform_migrate_sql_marks_the_recovered_upgrade_trigger(self):
        with peer([[b"[1] 200 OK dbversion=2.3\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "project", "transform-migrate-sql", "SERVER")
        self.assertEqual(result["native_upgrade_flow_detected"], True)

    def test_transform_migrate_sql_refuses_the_recorded_error_set(self):
        cases = (
            (b"[1] 408 Modification refused: Src filename does not exist\r\n", "408"),
            (b"[1] 420 Access denied\r\n", "Access denied"),
            (b"[1] 460 Validation status: field 2 to be filled\r\n", "to be filled"),
        )
        for reply, fragment in cases:
            with self.subTest(reply=reply), peer([[reply]]) as ((host, port), sent):
                failure = self.cli_failure(host, port, "project", "transform-migrate-sql", "SERVER")
            self.assertEqual(sent, [b"[1] TRANSFORM MIGRATE_SQL SERVER\r\n"])
            self.assertEqual(failure["reply_classification"], "recorded")
            self.assertIn(fragment, json.dumps(failure))

    def test_transform_migrate_sql_lone_199_completion_fails_closed(self):
        with peer([[b"[1] 199-Before: DBVersions match\r\n",
                    b"[1] 199 Transform from 2.2 to 2.3\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "project", "transform-migrate-sql", "SERVER")
        self.assertEqual(sent, [b"[1] TRANSFORM MIGRATE_SQL SERVER\r\n"])
        self.assertEqual(failure["reply_classification"], "unmodeled")

    def test_transform_migrate_sql_name_length_is_verified_before_sending(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "project", "transform-migrate-sql", "WAYTOLONG")
        self.assertEqual(sent, [])


class PortListTests(ToolkitCommandFamilyTests):
    """Toolkit's recovered `port list` family (#161 PortList, #165)."""

    def test_port_list_streams_rows_and_finishes_on_125(self):
        with peer([[b"[1] 125-COM1 availability=yes light=L1\r\n",
                    b"[1] 125-TCP Server\r\n",
                    b"[1] 125 \r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "port", "list")
        self.assertEqual(sent, [b"[1] port list\r\n"])
        self.assertEqual(result["operation"], "port-list")
        self.assertEqual(result["rows"], ["125-COM1 availability=yes light=L1",
                                          "125-TCP Server"])
        self.assertFalse(result["no_ports"])
        self.assertTrue(result["cgate_accepted"])

    def test_port_list_no_ports_is_a_recorded_completion_with_an_empty_list(self):
        cases = (
            (b"[1] 125  no ports\r\n",),
            (b"[1] 126  no ports found\r\n",),
        )
        for reply in cases:
            with self.subTest(reply=reply), peer([[*reply]]) as ((host, port), sent):
                result = self.cli(host, port, "port", "list")
                self.assertEqual(result["no_ports"], True)
                self.assertTrue(result["cgate_accepted"])

    def test_port_list_unmodeled_finish_fails_closed(self):
        with peer([[b"[1] 200 ok\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "port", "list")
        self.assertEqual(failure["reply_classification"], "unmodeled")
