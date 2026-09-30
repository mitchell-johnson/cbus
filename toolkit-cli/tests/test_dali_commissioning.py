from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.cli import _cgate_timeout, build_parser, main
from cbus_toolkit.dali_commissioning import (
    CONDITIONAL_EXTRACT_TYPES, EXTRACT_TYPES, READ_ONLY_EXTRACT_TYPES,
    DaliCommissioning, DaliCommissioningError, load_edits, validated_edits,
)


TARGET = "//TEST/254/p/20"
PROPERTY = "/cdg/daliLines/0/daliEcgs/3/commonParams102/minimumLevel"


def response(*lines, status=200):
    lines = lines or (f"{status} OK.",)
    return CGateResponse(tuple(lines), lines[-1], status)


def capabilities():
    return {
        "service": "cmqttd", "pci_connected": True, "pci_generation": 7,
        "programming_lane_state": "ready", "dali_extended_cal": True,
        "dali_delivery_semantics": "source-correlated-exactly-once-no-replay",
        "dali_session_ext_only": True,
        "dali_session_typed_extract_plans": list(EXTRACT_TYPES[1:]),
        "dali_session_typed_deploy_plans": ["EXT_ONLY", "DALI_ONLY", "FULL"],
        "dali_session_conditional_extract_commit": "atomic-before-address-unknown-step-by-step-after",
        "dali_session_typed_deploy_failure": "stop-at-first-fault-no-rollback-no-replay",
        "dali_session_typed_deploy_readback": "none-native",
        "dali_commissioning_journal": "cmqttd-dali-commissioning-journal-v1",
    }


def model(level=1):
    return {
        "cdg": {"daliLines": [{"daliEcgs": [
            {"commonParams102": {"minimumLevel": level, "sceneMembershipBitmask16": 1},
             "name": "old", "isKnown": True, "shortAddress": address,
             "deviceTypes": {"deviceTypes": ["EMERGENCY"] if address == 3 else ["LED"]},
             "ledParams207": {"dimmCurve": "LINEAR"}, "scene": [{"level": 1}]}
            for address in range(64)
        ]}, {"daliEcgs": []}]},
        "catalog": {"catalogueLines": []},
        "extParams": {"values": {"256": 0, "257": 0}, "targetValues": {}},
    }


class ScriptedService:
    def __init__(self):
        self.commands = []
        self.connected = True
        self.caps = capabilities()
        self.sessions = {}
        self.device_level = 1
        self.device_ext = {"256": 0, "257": 0}
        self.failure = None
        self.ignore_set = False
        self.journal = None
        self.journal_at_write = None
        self.advance_generation_on_set = False
        self.advance_generation_on_extract = False
        self.end_failure = None
        self.model_transform = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connected = False

    @staticmethod
    def decode(value):
        if not value.startswith('"') or not value.endswith('"'):
            raise AssertionError(value)
        result, escaped = [], False
        for char in value[1:-1]:
            if escaped:
                result.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            else:
                result.append(char)
        return json.loads("".join(result))

    def command(self, command):
        self.commands.append(command)
        if command == "CMQTT CAPABILITIES":
            return response("200-" + json.dumps(self.caps), "200 OK")
        tokens = command.split()
        operation, session = tokens[2:4]
        if operation == "NEW":
            self.sessions[session] = model(self.device_level)
            return response("120-created new session: " + session, "200 OK.")
        if operation == "END":
            if self.end_failure is not None:
                raise self.end_failure
            self.sessions.pop(session)
            return response("200 OK.")
        if operation == "GET":
            return response("120-/", "120-" + json.dumps(self.sessions[session]), "200 OK.")
        if operation == "EXTRACT":
            self.sessions[session] = model(self.device_level)
            self.sessions[session]["extParams"]["values"] = dict(self.device_ext)
            if self.model_transform is not None:
                self.model_transform(self.sessions[session])
            if tokens[6] in CONDITIONAL_EXTRACT_TYPES and self.failure:
                raise self.failure
            if self.advance_generation_on_extract:
                self.caps["pci_generation"] += 1
            return response("120-start extraction", "200 OK.")
        if operation == "SET":
            value = self.decode(command.split(" ", 5)[5])
            if not self.ignore_set:
                selected = self.sessions[session]
                path = tokens[4].strip("/").split("/")
                for component in path[:-1]:
                    selected = selected[int(component)] if isinstance(selected, list) else selected[component]
                selected[path[-1]] = value
            if self.advance_generation_on_set:
                self.caps["pci_generation"] += 1
            return response("200 OK.")
        if operation == "SET_EXT_PARAMS":
            for offset, value in enumerate(tokens[5:]):
                self.sessions[session]["extParams"]["targetValues"][str(int(tokens[4]) + offset)] = int(value)
            return response("200 OK.")
        if operation == "DEPLOY":
            if self.journal:
                self.journal_at_write = json.loads(self.journal.read_text())
            if self.failure:
                if isinstance(self.failure, RuntimeError) and not isinstance(self.failure, CGateError):
                    self.connected = False
                raise self.failure
            self.device_level = self.sessions[session]["cdg"]["daliLines"][0]["daliEcgs"][3]["commonParams102"]["minimumLevel"]
            self.device_ext.update(self.sessions[session]["extParams"]["targetValues"])
            return response("120-start deploy", "120-progress: 1/4, plan: SET_COMMON_PARAMS_ECG", "200 OK.")
        raise AssertionError(command)


class DaliCommissioningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.service = ScriptedService()
        self.workflow = DaliCommissioning(self.service)

    def journal(self, name="attempt.json"):
        return self.folder / name

    @staticmethod
    def edit(value=7):
        return [{"path": PROPERTY, "value": value}]

    def test_all_read_only_modes_use_exact_native_grammar_and_cleanup(self):
        for mode in READ_ONLY_EXTRACT_TYPES:
            with self.subTest(mode=mode):
                self.service.commands.clear()
                result = self.workflow.extract(TARGET, line="BOTH", extract_type=mode, addresses=[3, 5])
                commands = self.service.commands
                self.assertEqual(commands[0], "CMQTT CAPABILITIES")
                self.assertEqual(commands[2], f"DALI SESSION EXTRACT {result['session']} {TARGET} BOTH {mode} 3,5")
                self.assertTrue(result["complete"])
                self.assertTrue(result["session_ended"])
                self.assertFalse(result["send_may_have_occurred"])
                self.assertFalse(result["physical_effect_verified"])
                self.assertFalse(self.service.sessions)

    def test_conditional_modes_require_permission_and_durable_attempt(self):
        for mode in CONDITIONAL_EXTRACT_TYPES:
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "assigns DALI addresses"):
                    self.workflow.extract(TARGET, extract_type=mode)
                self.assertEqual(self.service.commands, [])
                result = self.workflow.extract(TARGET, extract_type=mode,
                    seed_extract="DALI_ONLY", allow_address_assignment=True, journal=self.journal(mode + ".json"))
                self.assertTrue(result["address_assignment_attempted"])
                self.assertTrue(result["mutation_terminal_received"])
                self.assertFalse(result["outcome_uncertain"])
                self.assertEqual(result["automatic_retries"], 0)
                self.service.commands.clear()

    def test_capability_denials_happen_before_session_or_physical_read(self):
        cases = {"service": "cgate-mock", "pci_connected": False, "pci_generation": True,
                 "programming_lane_state": "faulted", "dali_extended_cal": False,
                 "dali_delivery_semantics": "unknown", "dali_session_typed_extract_plans": []}
        for name, value in cases.items():
            with self.subTest(name=name):
                self.service.commands.clear()
                self.service.caps = capabilities()
                self.service.caps[name] = value
                with self.assertRaises(DaliCommissioningError) as caught:
                    self.workflow.extract(TARGET)
                self.assertEqual(self.service.commands, ["CMQTT CAPABILITIES"])
                self.assertFalse(caught.exception.dali_commissioning_evidence["extract_attempted"])

    def test_dry_run_stages_only_and_retains_readback_without_deploy(self):
        result = self.workflow.deploy(TARGET, self.edit(), dry_run=True)
        self.assertEqual(result["staged_edits"][0]["value"], 7)
        self.assertEqual(result["before_edits"][0]["value"], 1)
        self.assertFalse(result["deploy_attempted"])
        self.assertFalse(any(" DEPLOY " in command for command in self.service.commands))
        self.assertEqual(self.service.device_level, 1)

    def test_deploy_attempt_is_fsynced_before_single_command_and_no_readback_claim(self):
        path = self.journal()
        self.service.journal = path
        result = self.workflow.deploy(TARGET, self.edit(), journal=path)
        attempted = self.service.journal_at_write
        self.assertEqual(attempted["phase"], "deploy-attempt")
        self.assertTrue(attempted["outcome_uncertain"])
        self.assertTrue(attempted["send_may_have_occurred"])
        self.assertTrue(attempted["journal_update"]["file_synced"])
        self.assertTrue(attempted["journal_update"]["directory_synced"])
        self.assertEqual(attempted["staged_edits"][0]["value"], 7)
        self.assertEqual(sum(" DEPLOY " in value for value in self.service.commands), 1)
        self.assertEqual(json.loads(path.read_text())["phase"], "complete")
        self.assertFalse(result["physical_write_readback_verified"])
        self.assertFalse(result["persistence_verified"])

    def test_missing_or_ignored_staged_property_prevents_deploy(self):
        with self.assertRaises(ValueError):
            self.workflow.deploy(TARGET, [{"path": "/cdg/absent", "value": 7}], journal=self.journal())
        self.assertFalse(any(" SET " in value or " DEPLOY " in value for value in self.service.commands))
        self.service.ignore_set = True
        with self.assertRaisesRegex(DaliCommissioningError, "does not retain"):
            self.workflow.deploy(TARGET, self.edit(), journal=self.journal("ignored.json"))
        self.assertFalse(any(" DEPLOY " in value for value in self.service.commands))

    def test_edits_outside_selected_line_or_ecg_and_metadata_refuse_before_io(self):
        for line, addresses, path in (("B", [3], PROPERTY), ("A", [5], PROPERTY),
                                      ("A", None, PROPERTY.rsplit("/", 2)[0] + "/name")):
            with self.subTest(line=line, addresses=addresses, path=path):
                with self.assertRaises(ValueError):
                    self.workflow.deploy(TARGET, [{"path": path, "value": 7}],
                                         line=line, addresses=addresses, journal=self.journal())
                self.assertEqual(self.service.commands, [])

    def test_model_exclusions_and_device_type_gate_cannot_silently_omit_edit(self):
        for flag, value in (("isKnown", False), ("isMissing", True), ("isConflicting", True),
                            ("shortAddress", 5)):
            with self.subTest(flag=flag):
                self.service = ScriptedService()
                self.workflow = DaliCommissioning(self.service)
                self.service.model_transform = lambda root, key=flag, val=value: root["cdg"]["daliLines"][0]["daliEcgs"][3].update({key: val})
                with self.assertRaises(DaliCommissioningError):
                    self.workflow.deploy(TARGET, self.edit(), journal=self.journal(flag + ".json"))
                self.assertFalse(any(" DEPLOY " in command for command in self.service.commands))
        self.service = ScriptedService()
        self.workflow = DaliCommissioning(self.service)
        led_path = "/cdg/daliLines/0/daliEcgs/3/ledParams207/dimmCurve"
        with self.assertRaisesRegex(DaliCommissioningError, "device type"):
            self.workflow.deploy(TARGET, [{"path": led_path, "value": "LOGARITHMIC"}], journal=self.journal("type.json"))
        self.assertFalse(any(" DEPLOY " in command for command in self.service.commands))

    def test_scene_membership_gate_is_checked_after_staged_edits(self):
        self.service.model_transform = lambda root: root["cdg"]["daliLines"][0]["daliEcgs"][3]["commonParams102"].update({"sceneMembershipBitmask16": 0})
        scene_path = "/cdg/daliLines/0/daliEcgs/3/scene/0/level"
        with self.assertRaisesRegex(DaliCommissioningError, "scene membership"):
            self.workflow.deploy(TARGET, [{"path": scene_path, "value": 7}], journal=self.journal())
        self.assertFalse(any(" DEPLOY " in command for command in self.service.commands))
        result = self.workflow.deploy(TARGET, [
            {"path": "/cdg/daliLines/0/daliEcgs/3/commonParams102/sceneMembershipBitmask16", "value": 1},
            {"path": scene_path, "value": 7}], journal=self.journal("member.json"))
        self.assertTrue(result["complete"])

    def test_dry_run_metadata_has_explicit_session_only_disposition(self):
        result = self.workflow.deploy(TARGET, [{"path": "/cdg/daliLines/0/daliEcgs/3/name", "value": "new name"}], dry_run=True)
        self.assertEqual(result["edit_dispositions"][0]["disposition"], "session-only-metadata")
        self.assertFalse(result["deploy_attempted"])

    def test_uncertain_server_errors_and_lost_transport_are_never_replayed(self):
        cases = [RuntimeError("connection closed; outcome unknown"),
                 CGateError(response("503 network error: timed out", status=503)),
                 CGateError(response("502 reply status error: error response: IN_PROGRESS during SET", status=502)),
                 CGateError(response("502 reply status error: error response: FAIL_BUSY during SET", status=502))]
        for index, error in enumerate(cases):
            with self.subTest(error=error):
                self.service = ScriptedService()
                self.workflow = DaliCommissioning(self.service)
                self.service.failure = error
                path = self.journal(f"failed-{index}.json")
                with self.assertRaises(type(error)) as caught:
                    self.workflow.deploy(TARGET, self.edit(), journal=path)
                receipt = caught.exception.dali_commissioning_evidence
                self.assertTrue(receipt["outcome_uncertain"])
                self.assertEqual(receipt["automatic_retries"], 0)
                self.assertEqual(sum(" DEPLOY " in value for value in self.service.commands), 1)
                self.assertTrue(json.loads(path.read_text())["outcome_uncertain"])
                if not self.service.connected:
                    self.assertFalse(any(" END " in value for value in self.service.commands))

    def test_definite_native_device_error_retains_partial_failure_without_replay(self):
        self.service.failure = CGateError(response(
            "502 reply status error: error response: FAIL_INVALID_PARAMETER during SET_SCENE_VALUES", status=502))
        with self.assertRaises(CGateError) as caught:
            self.workflow.deploy(TARGET, self.edit(), journal=self.journal())
        evidence = caught.exception.dali_commissioning_evidence
        self.assertFalse(evidence["outcome_uncertain"])
        self.assertTrue(evidence["mutation_terminal_received"])
        self.assertFalse(evidence["complete"])
        self.assertFalse(evidence["rolled_back"])

    def test_existing_journal_and_create_failure_prevent_mutating_command(self):
        path = self.journal()
        path.write_text("operator receipt")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.workflow.deploy(TARGET, self.edit(), journal=path)
        self.assertEqual(self.service.commands, [])
        with patch("cbus_toolkit.dali_commissioning._Journal._sync_directory", side_effect=OSError("fsync failed")):
            with self.assertRaises(OSError):
                self.workflow.deploy(TARGET, self.edit(), journal=self.journal("fault.json"))
        self.assertEqual(self.service.commands, ["CMQTT CAPABILITIES"])

    def test_generation_change_after_staging_refuses_deploy(self):
        self.service.advance_generation_on_set = True
        with self.assertRaisesRegex(DaliCommissioningError, "PCI generation changed") as caught:
            self.workflow.deploy(TARGET, self.edit(), journal=self.journal())
        receipt = caught.exception.dali_commissioning_evidence
        self.assertFalse(receipt["deploy_attempted"])
        self.assertFalse(receipt["mutating_command_issued"])
        self.assertFalse(any(" DEPLOY " in command for command in self.service.commands))

    def test_generation_change_after_seed_refuses_conditional_address_assignment(self):
        self.service.advance_generation_on_extract = True
        path = self.journal()
        with self.assertRaisesRegex(DaliCommissioningError, "PCI generation changed") as caught:
            self.workflow.extract(TARGET, extract_type="COND_QUICK", seed_extract="DALI_ONLY",
                                  allow_address_assignment=True, journal=path)
        receipt = caught.exception.dali_commissioning_evidence
        self.assertFalse(receipt["address_assignment_attempted"])
        self.assertFalse(receipt["mutating_command_issued"])
        self.assertEqual(receipt["previous_capabilities"]["pci_generation"], 7)
        self.assertEqual(receipt["capabilities"]["pci_generation"], 8)
        self.assertFalse(any(" COND_QUICK" in command for command in self.service.commands))
        self.assertFalse(json.loads(path.read_text())["send_may_have_occurred"])

    def test_cleanup_failure_does_not_publish_complete_workflow_or_lose_confirmed_mutation(self):
        self.service.end_failure = CGateError(response("501 session could not end", status=501))
        path = self.journal()
        with self.assertRaises(CGateError) as caught:
            self.workflow.deploy(TARGET, self.edit(), journal=path)
        receipt = caught.exception.dali_commissioning_evidence
        self.assertEqual(receipt["phase"], "cleanup-failed")
        self.assertFalse(receipt["complete"])
        self.assertTrue(receipt["operation_completed"])
        self.assertTrue(receipt["mutation_terminal_received"])
        self.assertFalse(receipt["outcome_uncertain"])
        self.assertFalse(receipt["session_ended"])
        self.assertIn("cleanup_error", receipt)
        saved = json.loads(path.read_text())
        self.assertFalse(saved["complete"])
        self.assertEqual(saved["phase"], "cleanup-failed")
        self.assertEqual(saved["cleanup_error"], receipt["cleanup_error"])
        self.assertEqual(sum(" DEPLOY " in command for command in self.service.commands), 1)

    def test_original_error_survives_cleanup_failure_with_both_errors_journaled(self):
        first = CGateError(response("503 network error: timed out", status=503))
        self.service.failure = first
        self.service.end_failure = CGateError(response("501 session could not end", status=501))
        path = self.journal()
        with self.assertRaises(CGateError) as caught:
            self.workflow.deploy(TARGET, self.edit(), journal=path)
        self.assertIs(caught.exception, first)
        receipt = caught.exception.dali_commissioning_evidence
        self.assertEqual(receipt["phase"], "outcome-uncertain")
        self.assertTrue(receipt["outcome_uncertain"])
        self.assertIn("timed out", receipt["error"]["message"])
        self.assertIn("could not end", receipt["cleanup_error"]["message"])
        saved = json.loads(path.read_text())
        self.assertEqual(saved["cleanup_error"], receipt["cleanup_error"])
        self.assertFalse(saved["complete"])

    def test_full_and_extended_only_deployment_preserve_native_byte_staging(self):
        edits = [{"address": 256, "bytes": [7, 8]}]
        result = self.workflow.deploy(TARGET, edits, extract_type="EXT_ONLY", deploy_type="EXT_ONLY", journal=self.journal())
        self.assertEqual(result["staged_edits"][0]["value"], [7, 8])
        self.assertEqual(self.service.device_ext, {"256": 7, "257": 8})
        self.assertTrue(any(" SET_EXT_PARAMS " in command for command in self.service.commands))
        result = self.workflow.deploy(TARGET, self.edit(9) + edits, extract_type="FULL", deploy_type="FULL", journal=self.journal("full.json"))
        self.assertTrue(result["complete"])

    def test_recovery_classifies_expected_unchanged_mixed_and_never_replays(self):
        path = self.journal()
        self.workflow.deploy(TARGET, self.edit(), journal=path)
        raw = path.read_bytes()
        for level, expected in ((7, "expected"), (1, "unchanged"), (9, "mixed")):
            self.service.device_level = level
            self.service.commands.clear()
            result = self.workflow.recover(path)
            self.assertEqual(result["classification"], expected)
            self.assertTrue(result["conclusive"])
            self.assertFalse(result["writes_attempted"])
            self.assertFalse(result["attempt_replay_authorized"])
            self.assertFalse(any(" DEPLOY " in value or " SET " in value or " SET_EXT_PARAMS " in value for value in self.service.commands))
            self.assertEqual(path.read_bytes(), raw)

    def test_extended_recovery_reads_actual_values_and_keeps_unknown_fields_unreadable(self):
        path = self.journal()
        self.workflow.deploy(TARGET, [{"address": 256, "bytes": [7, 8]}],
                             extract_type="EXT_ONLY", deploy_type="EXT_ONLY", journal=path)
        result = self.workflow.recover(path)
        self.assertEqual(result["classification"], "expected")
        self.assertEqual(result["fresh_extraction"]["extract_type"], "EXT_ONLY")
        self.service.device_ext = {}
        result = self.workflow.recover(path)
        self.assertEqual(result["classification"], "unreadable")
        self.assertFalse(result["conclusive"])

    def test_recovery_refuses_tampered_plan_before_server_requests(self):
        path = self.journal()
        self.workflow.deploy(TARGET, self.edit(), journal=path)
        saved = json.loads(path.read_text())
        saved["target"] = "//TEST/254/p/21"
        path.write_text(json.dumps(saved))
        self.service.commands.clear()
        with self.assertRaisesRegex(ValueError, "bound plan"):
            self.workflow.recover(path)
        self.assertEqual(self.service.commands, [])

    def test_native_fixture_owns_supported_mutating_command_selectors(self):
        fixture = Path(__file__).resolve().parents[2] / "rust/testdata/fixtures/native_cgate_dali_commissioning.json"
        native = json.loads(fixture.read_text())
        commands = [case["command"] for case in native["cases"].values()]
        for mode in CONDITIONAL_EXTRACT_TYPES:
            self.assertTrue(any(command.endswith(" A " + mode) for command in commands))
        for mode in ("DALI_ONLY", "FULL"):
            self.assertTrue(any(" DEPLOY " in command and command.endswith(" A " + mode) for command in commands))
        self.assertTrue(native["oracle"]["cleanup_complete"])


class DaliInputAndCLITests(unittest.TestCase):
    def test_invalid_edits_are_rejected_as_a_whole(self):
        cases = [[], [{"path": PROPERTY, "value": float("nan")}],
                 [{"path": "/cdg/x[*]", "value": 1}],
                 [{"path": "/extParams/values/256", "value": 1}],
                 [{"path": PROPERTY, "value": 1}, {"path": PROPERTY, "value": 2}],
                 [{"path": "/cdg/x", "value": {}}, {"path": "/cdg/x/a", "value": 2}],
                 [{"address": True, "bytes": [1]}], [{"address": 256, "bytes": [True]}],
                 [{"address": 11375, "bytes": [1, 2]}],
                 [{"address": 256, "bytes": [1, 2]}, {"address": 257, "bytes": [1]}]]
        for edits in cases:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                validated_edits(edits)

    def test_duplicate_file_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "edits.json"
            file.write_text('[{"path":"/cdg/x","value":1,"value":2}]')
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_edits(file)

    def test_default_long_timeout_and_explicit_override(self):
        parser = build_parser()
        self.assertEqual(_cgate_timeout(parser.parse_args(["cgate", "dali", "extract", TARGET])), 14400)
        self.assertEqual(_cgate_timeout(parser.parse_args(["cgate", "--timeout", "23", "dali", "extract", TARGET])), 23)

    def test_cli_conditional_refusal_and_invalid_file_happen_before_connection(self):
        stream = io.StringIO()
        with patch("cbus_toolkit.cgate.CGateClient") as factory, redirect_stderr(stream):
            status = main(["cgate", "dali", "extract", TARGET, "--extract-type", "COND_QUICK"])
        self.assertEqual(status, 1)
        factory.assert_not_called()
        self.assertIn("--allow-address-assignment", json.loads(stream.getvalue())["error"])

    def test_cli_extract_returns_serializable_receipt(self):
        stream = io.StringIO()
        with patch("cbus_toolkit.cgate.CGateClient", return_value=ScriptedService()), redirect_stdout(stream):
            status = main(["cgate", "dali", "extract", TARGET, "--line", "BOTH", "--ecg", "3"])
        self.assertEqual(status, 0)
        result = json.loads(stream.getvalue())
        self.assertTrue(result["complete"])
        self.assertEqual(result["ecg_addresses"], [3])

    def test_cli_interrupt_exports_attempt_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            edits = Path(folder) / "edits.json"
            edits.write_text(json.dumps([{ "path": PROPERTY, "value": 7}]))
            service = ScriptedService()
            service.failure = KeyboardInterrupt()
            stream = io.StringIO()
            with patch("cbus_toolkit.cgate.CGateClient", return_value=service), redirect_stderr(stream):
                status = main(["cgate", "dali", "deploy", TARGET, "--edits", str(edits),
                               "--journal", str(Path(folder) / "attempt.json")])
            self.assertEqual(status, 130)
            receipt = json.loads(stream.getvalue())["dali_commissioning_evidence"]
            self.assertTrue(receipt["outcome_uncertain"])
            self.assertEqual(receipt["automatic_retries"], 0)


if __name__ == "__main__":
    unittest.main()
