import json
from pathlib import Path
import re
import unittest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.physical_programming import (
    PhysicalProgramming,
    PhysicalProgrammingError,
    PhysicalUnitPath,
    SUPPORTED_METHODS,
)


def response(*lines, status=200):
    lines = lines or (f"{status} OK",)
    return CGateResponse(tuple(lines), lines[-1], status)


class PhysicalService:
    def __init__(self, *, nvm=True):
        self.connected = True
        self.commands = []
        self.capabilities = {
            "service": "cmqttd",
            "physical_pp_load": True,
            "physical_pp_save": True,
            "physical_pp_routed_load": True,
            "physical_pp_routed_save": True,
            "physical_pp_routed_methods": list(SUPPORTED_METHODS),
            "physical_pp_routed_save_protection": ["none", "checksum", "lock"],
            "physical_pp_routed_lock_methods": ["direct", "ncc", "paged"],
            "physical_pp_routed_unsupported_methods": [],
            "physical_pp_routed_lock": True,
            "physical_pp_routed_nvm_commit": nvm,
            "physical_pp_routed_delivery_semantics": (
                "reply-network-unit-parameter-tag-correlated-exactly-once-no-replay"
            ),
            "physical_pp_routed_state_scope": "owned-session-target-network",
            "pci_generation": 7,
            "pci_connected": True,
            "programming_lane_state": "ready",
        }
        self.schema_method = None
        self.fail_save = None
        self.corrupt_after_save = False
        self.ignore_sets = False
        self.sessions = {}
        self.devices = {
            "//TEST/253/p/4": {
                f"Value_{method}": "0x01" for method in SUPPORTED_METHODS
            },
            "//TEST/253/p/5": {
                f"Value_{method}": "0x11" for method in SUPPORTED_METHODS
            },
        }

    def _schema(self):
        rows = []
        for index, method in enumerate(SUPPORTED_METHODS):
            emitted = self.schema_method if self.schema_method is not None else method
            method_field = "" if emitted == "direct" and index == 0 else (
                f"<ProgramMethod>{emitted}</ProgramMethod>"
            )
            rows.append(
                "<Param>"
                f"<Name>Value_{method}</Name><Type>int</Type>"
                f"<Address>${index + 32:02X}</Address>{method_field}"
                "<Protection>none</Protection><Tag>Core</Tag>"
                "</Param>"
            )
        return "<Parameters>" + "".join(rows) + "</Parameters>"

    @staticmethod
    def _decode(value):
        assert value.startswith('"') and value.endswith('"')
        value = value[1:-1]
        result = []
        escaped = False
        for character in value:
            if escaped:
                result.append(character)
                escaped = False
            elif character == "\\":
                escaped = True
            else:
                result.append(character)
        assert not escaped
        return "".join(result)

    def command(self, command):
        self.commands.append(command)
        if command == "CMQTT CAPABILITIES":
            payload = json.dumps(self.capabilities, separators=(",", ":"))
            return response("200-" + payload, "200 OK")
        if command.startswith(("PROJECT USE ", "PP LOCK ", "PP UNLOCK ")):
            return response("200 OK")
        match = re.fullmatch(r"PP START (\S+) (\S+)", command)
        if match:
            self.sessions[match[1]] = {"source": None, "values": {}}
            return response("200 OK")
        match = re.fullmatch(r"PP LOAD (\S+) (\S+)", command)
        if match:
            session, source = match.groups()
            self.sessions[session] = {
                "source": source,
                "values": dict(self.devices[source]),
            }
            return response("200 OK")
        match = re.fullmatch(r"PP INFO (\S+) \*", command)
        if match:
            return response(
                "343-Begin XML snippet",
                "347-" + self._schema(),
                "344 End XML snippet",
                status=344,
            )
        match = re.fullmatch(r"PP GET (\S+) (\S+)", command)
        if match:
            session, parameter = match.groups()
            value = self.sessions[session]["values"][parameter]
            return response(f"315 {parameter}={value}", status=315)
        match = re.fullmatch(r"PP SET (\S+) (\S+) (.+)", command)
        if match:
            session, parameter, value = match.groups()
            if not self.ignore_sets:
                self.sessions[session]["values"][parameter] = self._decode(value)
            return response("200 OK")
        match = re.fullmatch(r"PP SAVE_TO_SOURCE (\S+)", command)
        if match:
            return self._save(match[1], self.sessions[match[1]]["source"])
        match = re.fullmatch(r"PP SAVE (\S+) (\S+)", command)
        if match:
            return self._save(match[1], match[2])
        match = re.fullmatch(r"PP END (\S+)", command)
        if match:
            self.sessions.pop(match[1], None)
            return response("200 OK")
        raise AssertionError("Unexpected native command: " + command)

    def _save(self, session, destination):
        if self.fail_save is not None:
            failure, self.fail_save = self.fail_save, None
            raise failure
        self.devices[destination] = dict(self.sessions[session]["values"])
        if self.corrupt_after_save:
            first = next(iter(self.sessions[session]["values"]))
            self.devices[destination][first] = "0xEE"
        return response("200 OK")


class PhysicalProgrammingTests(unittest.TestCase):
    def test_paths_are_canonical_unique_physical_units(self):
        parsed = PhysicalUnitPath.parse("//TEST/003/p/004")
        self.assertEqual(parsed.value, "//TEST/3/p/4")
        self.assertEqual(parsed.lock_address, "//TEST/3")
        for value in ("/db//TEST/3/p/4", "//TOO_LONG9/3/p/4", "//TEST/256/p/4",
                      "//TEST/3/p/0", "//TEST/3/p/255", "//TEST/3/p/4/x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PhysicalUnitPath.parse(value)

    def test_inspect_loads_and_classifies_every_supported_method(self):
        for method in SUPPORTED_METHODS:
            with self.subTest(method=method):
                service = PhysicalService()
                result = PhysicalProgramming(service, operation_id="inspect").inspect(
                    "//TEST/253/p/4", method=method
                )
                self.assertTrue(result["complete"])
                self.assertEqual(result["method"], method)
                self.assertEqual(list(result["values"]), [f"Value_{method}"])
                self.assertEqual(result["parameters"][0]["program_method"], method)
                self.assertFalse(result["saved"])
                self.assertEqual(service.commands[0], "CMQTT CAPABILITIES")
                self.assertEqual(
                    [command for command in service.commands if command.startswith("PP LOAD ")],
                    ["PP LOAD cbus_pp_inspect_inspect //TEST/253/p/4"],
                )
                self.assertFalse(any("SAVE" in command for command in service.commands))

    def test_apply_save_to_source_and_fresh_readback_for_every_method(self):
        for method in SUPPORTED_METHODS:
            with self.subTest(method=method):
                service = PhysicalService()
                parameter = f"Value_{method}"
                result = PhysicalProgramming(service, operation_id="allmethods").apply(
                    "//TEST/253/p/4", [(parameter, "0x02")], method=method
                )
                self.assertTrue(result["complete"])
                self.assertTrue(result["saved"])
                self.assertTrue(result["staged_readback_verified"])
                self.assertTrue(result["fresh_physical_readback_verified"])
                self.assertFalse(result["power_cycle_persistence_verified"])
                self.assertFalse(result["hardware_method_matrix_accepted"])
                self.assertEqual(result["before"], {parameter: "0x01"})
                self.assertEqual(result["staged"], {parameter: "0x02"})
                self.assertEqual(result["verified"], {parameter: "0x02"})
                self.assertEqual(result["save_attempts"], 1)
                self.assertEqual(result["automatic_write_retries"], 0)
                saves = [command for command in service.commands if "PP SAVE" in command]
                self.assertEqual(
                    saves,
                    ["PP SAVE_TO_SOURCE cbus_pp_allmethods_write"],
                )
                self.assertEqual(
                    len([command for command in service.commands if command.startswith("PP LOAD ")]),
                    2,
                )

    def test_explicit_destination_uses_save_and_verifies_destination(self):
        service = PhysicalService()
        result = PhysicalProgramming(service, operation_id="destination").apply(
            "//TEST/253/p/4",
            [("Value_goc2", "0x77")],
            method="goc2",
            destination="//TEST/253/p/5",
        )
        self.assertEqual(result["native_save_operation"], "PP SAVE")
        self.assertEqual(result["destination"], "//TEST/253/p/5")
        self.assertIn(
            "PP SAVE cbus_pp_destination_write //TEST/253/p/5",
            service.commands,
        )
        self.assertIn(
            "PP LOAD cbus_pp_destination_verify //TEST/253/p/5",
            service.commands,
        )
        self.assertEqual(service.devices["//TEST/253/p/5"]["Value_goc2"], "0x77")
        with self.assertRaisesRegex(ValueError, "source project/network lock"):
            PhysicalProgramming(PhysicalService(), operation_id="badtarget").apply(
                "//TEST/253/p/4", [("Value_direct", "2")], method="direct",
                destination="//TEST/252/p/5",
            )

    def test_dry_run_stages_without_save_or_second_load(self):
        service = PhysicalService()
        result = PhysicalProgramming(service, operation_id="dryrun").apply(
            "//TEST/253/p/4", [("Value_paged", "0x88")],
            method="paged", dry_run=True,
        )
        self.assertTrue(result["complete"])
        self.assertTrue(result["staged_readback_verified"])
        self.assertFalse(result["saved"])
        self.assertFalse(result["fresh_physical_readback_performed"])
        self.assertFalse(any("SAVE" in command for command in service.commands))
        self.assertEqual(
            len([command for command in service.commands if command.startswith("PP LOAD ")]), 1
        )
        self.assertEqual(service.devices["//TEST/253/p/4"]["Value_paged"], "0x01")

    def test_capability_and_schema_guards_precede_mutation(self):
        cases = (
            ("physical_pp_routed_load", False, "routed physical PP LOAD"),
            ("pci_connected", False, "no connected PCI"),
            ("programming_lane_state", "reconnect-required", "requires reconnect"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                service = PhysicalService()
                service.capabilities[field] = value
                with self.assertRaisesRegex(PhysicalProgrammingError, message) as caught:
                    PhysicalProgramming(service, operation_id="guard").inspect(
                        "//TEST/253/p/4", method="direct"
                    )
                self.assertEqual(service.commands, ["CMQTT CAPABILITIES"])
                self.assertFalse(caught.exception.evidence["save_attempted"])

        service = PhysicalService()
        service.schema_method = "direct"
        with self.assertRaisesRegex(PhysicalProgrammingError, "do not use requested method"):
            PhysicalProgramming(service, operation_id="schema").apply(
                "//TEST/253/p/4", [("Value_edlt", "2")], method="edlt"
            )
        self.assertFalse(any(command.startswith("PP SET ") for command in service.commands))
        self.assertFalse(any("PP SAVE" in command for command in service.commands))

    def test_input_validation_performs_no_cgate_command(self):
        for edits, message in (
            ([('Value_direct', '1'), ('Value_direct', '2')], "more than once"),
            ([('Value_direct', 'bad\nvalue')], "control characters"),
            ([], "at least one"),
        ):
            with self.subTest(edits=edits):
                service = PhysicalService()
                with self.assertRaisesRegex((ValueError, RuntimeError), message):
                    PhysicalProgramming(service, operation_id="input").apply(
                        "//TEST/253/p/4", edits, method="direct"
                    )
                self.assertEqual(service.commands, [])

    def test_uncertain_save_is_not_replayed_and_keeps_evidence(self):
        service = PhysicalService()
        service.fail_save = RuntimeError("connection lost after send")
        with self.assertRaisesRegex(RuntimeError, "connection lost") as caught:
            PhysicalProgramming(service, operation_id="uncertain").apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct"
            )
        evidence = caught.exception.details["physical_programming_evidence"]
        self.assertTrue(evidence["save_attempted"])
        self.assertEqual(evidence["save_attempts"], 1)
        self.assertTrue(evidence["save_outcome_uncertain"])
        self.assertFalse(evidence["saved"])
        self.assertEqual(
            len([command for command in service.commands if "PP SAVE" in command]), 1
        )
        self.assertEqual(
            len([command for command in service.commands if command.startswith("PP LOAD ")]), 1
        )

    def test_staged_readback_mismatch_refuses_save(self):
        service = PhysicalService()
        service.ignore_sets = True
        with self.assertRaisesRegex(PhysicalProgrammingError, "Staged PP readback") as caught:
            PhysicalProgramming(service, operation_id="stagefail").apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct"
            )
        evidence = caught.exception.evidence
        self.assertFalse(evidence["staged_readback_verified"])
        self.assertFalse(evidence["save_attempted"])
        self.assertEqual(evidence["staged_readback_mismatches"]["Value_direct"], {
            "requested": "0x02", "staged": "0x01",
        })
        self.assertFalse(any("PP SAVE" in command for command in service.commands))

    def test_fresh_mismatch_reports_confirmed_save_without_false_success(self):
        service = PhysicalService()
        service.corrupt_after_save = True
        with self.assertRaisesRegex(PhysicalProgrammingError, "readback differed") as caught:
            PhysicalProgramming(service, operation_id="mismatch").apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct"
            )
        evidence = caught.exception.evidence
        self.assertTrue(evidence["saved"])
        self.assertFalse(evidence["save_outcome_uncertain"])
        self.assertFalse(evidence["fresh_physical_readback_verified"])
        self.assertEqual(evidence["verification_mismatches"]["Value_direct"], {
            "staged": "0x02", "verified": "0xEE",
        })
        self.assertEqual(
            len([command for command in service.commands if "PP SAVE" in command]), 1
        )

    def test_ncc_nonvolatile_capability_is_separately_gated_for_apply(self):
        service = PhysicalService(nvm=False)
        inspection = PhysicalProgramming(service, operation_id="nccread").inspect(
            "//TEST/253/p/4", method="ncc"
        )
        self.assertTrue(inspection["complete"])

        service = PhysicalService(nvm=False)
        with self.assertRaisesRegex(PhysicalProgrammingError, "NCC Save-to-NVM"):
            PhysicalProgramming(service, operation_id="nccwrite").apply(
                "//TEST/253/p/4", [("Value_ncc", "2")], method="ncc"
            )
        self.assertEqual(service.commands, ["CMQTT CAPABILITIES"])

    def test_rust_evidence_roster_matches_python_workflow(self):
        fixture = Path(__file__).resolve().parents[2] / "rust/testdata/fixtures/native_cgate_routed_pp_methods.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(document["format"], "cmqttd-native-cgate-routed-pp-methods-evidence-v1")
        self.assertTrue(document["passed"])
        self.assertEqual(tuple(document["methods"]), SUPPORTED_METHODS)
        self.assertTrue(any("No live bridge" in item for item in document["evidence_boundaries"]))


if __name__ == "__main__":
    unittest.main()
