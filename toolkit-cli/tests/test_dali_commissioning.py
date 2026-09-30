from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.cli import _cgate_timeout, build_parser, main
from cbus_toolkit.dali_commissioning import (
    CONDITIONAL_EXTRACT_TYPES, EXTRACT_TYPES, READ_ONLY_EXTRACT_TYPES,
    DaliCommissioning, DaliCommissioningError, load_edits, validated_edits,
    deployment_edit_dispositions,
)
from cbus_toolkit import dali_extended_proxy
from cbus_toolkit.dali_commissioning_cli import preconnect


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
                selected[int(path[-1]) if isinstance(selected, list) else path[-1]] = value
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

    def test_proxy_plan_requires_runtime_owned_schema_and_fresh_extended_seed(self):
        path = "/cdg/extParams/proxy/deviceID/id"
        edits = [{"path": path, "value": 42}]
        with self.assertRaisesRegex(ValueError, "initial extraction"):
            self.workflow.deploy(TARGET, edits, deploy_type="EXT_ONLY", journal=self.journal())
        self.assertEqual(self.service.commands, [])
        with self.assertRaisesRegex(DaliCommissioningError, "serializer is unavailable"):
            self.workflow.deploy(TARGET, edits, extract_type="EXT_ONLY", deploy_type="EXT_ONLY", journal=self.journal())
        self.assertFalse(any(" SESSION NEW " in command for command in self.service.commands))
        self.service.commands.clear()
        self.service.caps["dali_session_extended_proxy"] = {
            "families": ["deviceID"], "native_reserved_bits": True, "excluded_bytes": True,
            "writable_global_fields": [{"path": path, "address": 556,
                                        "type": "integer", "minimum": 0, "maximum": 255}]}
        self.service.model_transform = lambda model: model["cdg"].update({"extParams": {"proxy": {"deviceID": {"id": 17}}}})
        result = self.workflow.deploy(TARGET, edits, extract_type="EXT_ONLY", deploy_type="EXT_ONLY", journal=self.journal())
        self.assertTrue(result["complete"])
        self.assertEqual(result["edit_dispositions"][0]["disposition"], "planned-native-gateway-proxy-field")
        self.service.commands.clear()
        recovered = self.workflow.recover(self.journal())
        self.assertEqual(recovered["fresh_extraction"]["extract_type"], "EXT_ONLY")
        self.assertFalse(any(" DEPLOY " in command for command in self.service.commands))

    def test_scene_membership_creation_needs_a_scene_object_with_representable_level(self):
        mask = PROPERTY.rsplit("/", 1)[0] + "/sceneMembershipBitmask16"
        scene = PROPERTY.split("/commonParams102")[0] + "/scene/0"
        def empty(model):
            ecg = model["cdg"]["daliLines"][0]["daliEcgs"][3]
            ecg["scene"] = [None] * 16
            ecg["commonParams102"]["sceneMembershipBitmask16"] = 0
        self.service.model_transform = empty
        with self.assertRaisesRegex(DaliCommissioningError, "representable level"):
            self.workflow.deploy(TARGET, [{"path": mask, "value": 1}], journal=self.journal())
        self.assertFalse(any(" DEPLOY " in command for command in self.service.commands))
        # The original DaliEcgScene model owns only level; replace its null slot.
        # This mock uses the same SESSION SET list indexing as the live service.
        self.service.commands.clear()
        plan = deployment_edit_dispositions([{"path": scene, "value": {"level": 37}}, {"path": mask, "value": 1}], "A", [3], dry_run=False)
        self.assertEqual(plan[0]["scene_index"], 0)
        self.assertEqual(plan[0]["step"], "SET_SCENE_VALUES_ECG")
        result = self.workflow.deploy(TARGET, [{"path": scene, "value": {"level": 37}},
                                              {"path": mask, "value": 1}],
                                      addresses=[3], journal=self.journal("scene.json"))
        self.assertTrue(result["complete"])
        self.assertIsNone(result["before_edits"][0]["value"])
        self.assertEqual(result["staged_edits"][0]["value"], {"level": 37})

    def test_excluded_raw_gateway_edits_refuse_before_session_and_dynamic_writes(self):
        with self.assertRaisesRegex(ValueError, "statically excluded"):
            self.workflow.deploy(TARGET, [{"address": 557, "bytes": [9]}],
                                 extract_type="EXT_ONLY", deploy_type="EXT_ONLY", journal=self.journal())
        self.assertEqual(self.service.commands, [])
        self.service.device_ext.update({"7424": 1})
        with self.assertRaisesRegex(DaliCommissioningError, "native dirty-write mask"):
            self.workflow.deploy(TARGET, [{"address": 7424, "bytes": [2]}],
                                 extract_type="EXT_ONLY", deploy_type="EXT_ONLY", journal=self.journal())
        self.assertFalse(any(" DEPLOY " in command for command in self.service.commands))

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
    def test_all_global_proxy_leaf_ranges_and_raw_overlaps_refuse_before_io(self):
        for suffix, (_, maximum, boolean) in dali_extended_proxy.FIELDS.items():
            with self.subTest(path=suffix):
                edit = {"path": dali_extended_proxy.PREFIX + suffix, "value": 1 if boolean else maximum + 1}
                with self.assertRaises(ValueError):
                    deployment_edit_dispositions([edit], "A", None, dry_run=False)
        workflow = DaliCommissioning(ScriptedService())
        with self.assertRaisesRegex(ValueError, "same native family"):
            workflow.deploy(TARGET, [
                {"path": "/cdg/extParams/proxy/lightingApplications/app1", "value": 57},
                {"address": 515, "bytes": [255]}], deploy_type="EXT_ONLY", extract_type="EXT_ONLY", journal="unused")
        self.assertEqual(workflow.client.commands, [])

    def test_fifo_symlink_and_replaced_inputs_are_rejected_without_network_io(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            fifo = folder / "fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "regular file"):
                load_edits(fifo)
            service = ScriptedService()
            with self.assertRaisesRegex(ValueError, "regular file"):
                DaliCommissioning(service).recover(fifo)
            self.assertEqual(service.commands, [])
            original = folder / "input.json"
            original.write_text('[{"path":"' + PROPERTY + '","value":7}]')
            link = folder / "link"
            link.symlink_to(original)
            with self.assertRaises(OSError):
                load_edits(link)
            real_open = os.open
            replacement = folder / "replacement"
            replacement.write_text(original.read_text())
            def replace_after_open(path, flags):
                descriptor = real_open(path, flags)
                replacement.replace(original)
                return descriptor
            with patch("cbus_toolkit.dali_commissioning.os.open", side_effect=replace_after_open):
                with self.assertRaisesRegex(ValueError, "changed while"):
                    load_edits(original)
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

    def test_cli_ext_only_preconnect_admits_all_native_global_proxy_leaves(self):
        parser = build_parser()
        with tempfile.TemporaryDirectory() as folder:
            edits = Path(folder) / "edits.json"
            journal = Path(folder) / "attempt.json"
            for suffix, (_, maximum, boolean) in dali_extended_proxy.FIELDS.items():
                value = [{"path": dali_extended_proxy.PREFIX + suffix,
                          "value": True if boolean else maximum}]
                edits.write_text(json.dumps(value))
                with self.subTest(suffix=suffix):
                    args = parser.parse_args(["cgate", "dali", "deploy", TARGET,
                                              "--extract-type", "EXT_ONLY", "--deploy-type", "EXT_ONLY",
                                              "--edits", str(edits), "--journal", str(journal)])
                    self.assertEqual(preconnect(args), value)
                    self.assertFalse(journal.exists())

    def test_cli_ext_only_proxy_deploy_and_preconnection_refusals(self):
        path = dali_extended_proxy.PREFIX + "deviceID/id"
        with tempfile.TemporaryDirectory() as folder:
            edits = Path(folder) / "edits.json"
            journal = Path(folder) / "attempt.json"
            service = ScriptedService()
            service.caps["dali_session_extended_proxy"] = {
                "families": ["deviceID"], "native_reserved_bits": True, "excluded_bytes": True,
                "writable_global_fields": [{"path": path, "address": 556,
                                            "type": "integer", "minimum": 0, "maximum": 255}]}
            service.model_transform = lambda model: model["cdg"].update(
                {"extParams": {"proxy": {"deviceID": {"id": 17}}}})
            edits.write_text(json.dumps([{"path": path, "value": 42}]))
            stream = io.StringIO()
            arguments = ["cgate", "dali", "deploy", TARGET,
                         "--extract-type", "EXT_ONLY", "--deploy-type", "EXT_ONLY",
                         "--edits", str(edits), "--journal", str(journal)]
            with patch("cbus_toolkit.cgate.CGateClient", return_value=service), redirect_stdout(stream):
                self.assertEqual(main(arguments), 0)
            self.assertTrue(json.loads(stream.getvalue())["complete"])
            self.assertTrue(any(command.startswith("DALI SESSION DEPLOY ") and command.endswith(" A EXT_ONLY")
                                for command in service.commands))
            journal.unlink()
            cases = [
                ([{"path": PROPERTY, "value": 7}], "EXT_ONLY"),
                ([{"path": dali_extended_proxy.PREFIX + "deviceID/unknown", "value": 7}], "EXT_ONLY"),
                ([{"path": path, "value": 256}], "EXT_ONLY"),
                ([{"path": path, "value": True}], "EXT_ONLY"),
                ([{"path": path, "value": 42}], "DALI_ONLY"),
                ([{"path": path, "value": 42}, {"address": 556, "bytes": [42]}], "EXT_ONLY"),
            ]
            for value, initial_extract in cases:
                edits.write_text(json.dumps(value))
                arguments[arguments.index("--extract-type") + 1] = initial_extract
                stream = io.StringIO()
                with self.subTest(value=value, initial_extract=initial_extract):
                    with patch("cbus_toolkit.cgate.CGateClient") as factory, redirect_stderr(stream):
                        self.assertEqual(main(arguments), 1)
                    factory.assert_not_called()
                    self.assertFalse(journal.exists())

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
