import json
from pathlib import Path
import re
import tempfile
import unittest

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.physical_pp_journal import PhysicalPPJournalError
from cbus_toolkit.physical_programming import (
    PhysicalParameter,
    PhysicalProgramming,
    PhysicalProgrammingError,
    PhysicalUnitPath,
    SUPPORTED_METHODS,
    parameter_extent,
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
        self.debug_change_missing = False
        self.fail_load = False
        self.journal_at_save = None
        self.journal_path = None
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
            if self.fail_load:
                raise RuntimeError("physical unit did not answer")
            self.sessions[session] = {
                "source": source,
                "values": dict(self.devices[source]),
                "loaded": dict(self.devices[source]),
                "changed": set(),
            }
            return response("200 OK")
        match = re.fullmatch(r"PP DEBUG mem (\S+) ([0-9a-f]+)", command)
        if match:
            return self._debug(self.sessions[match[1]], int(match[2], 16))
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
                self.sessions[session]["changed"].add(parameter)
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

    def _debug(self, session, start):
        """cmqttd's PP DEBUG rows: one byte per Value_* at $20 + index."""
        names = {32 + index: f"Value_{method}" for index, method in enumerate(SUPPORTED_METHODS)}
        addresses = range(start, min(start + 16, 32 + len(SUPPORTED_METHODS)))

        def byte(values, address):
            return f"{int(values[names[address]], 0) & 0xFF:02x}"

        unit = [byte(session["loaded"], address) for address in addresses]
        current = [byte(session["values"], address) for address in addresses]
        change = ["ff" if names[address] in session["changed"] and not self.debug_change_missing
                  else "00" for address in addresses]
        cells = lambda values: "|".join(values) + "|"
        return response(
            "199---------|" + cells([f"{address & 0xFF:02x}" for address in addresses]),
            "199-    unit>" + cells(unit),
            "199- current>" + cells(current),
            "199-  change>" + cells(change),
            "199 endparam>" + cells(["nn"] * len(unit)),
            status=199,
        )

    def _save(self, session, destination):
        if self.journal_path is not None:
            self.journal_at_save = json.loads(Path(self.journal_path).read_text())
        if self.fail_save is not None:
            failure, self.fail_save = self.fail_save, None
            raise failure
        self.devices[destination] = dict(self.sessions[session]["values"])
        if self.corrupt_after_save:
            first = next(iter(self.sessions[session]["values"]))
            self.devices[destination][first] = "0xEE"
        return response("200 OK")


class PhysicalProgrammingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journals = Path(directory.name)
        self.count = 0

    def journal(self, name=None):
        self.count += 1
        return self.journals / (name or f"attempt-{self.count}.json")

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
                    "//TEST/253/p/4", [(parameter, "0x02")], method=method,
                    journal=self.journal(),
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
            journal=self.journal(),
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
                destination="//TEST/252/p/5", journal=self.journal(),
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
                "//TEST/253/p/4", [("Value_edlt", "2")], method="edlt",
                journal=self.journal(),
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
                        "//TEST/253/p/4", edits, method="direct", journal=self.journal(),
                    )
                self.assertEqual(service.commands, [])

    def test_uncertain_save_is_not_replayed_and_keeps_evidence(self):
        service = PhysicalService()
        service.fail_save = RuntimeError("connection lost after send")
        with self.assertRaisesRegex(RuntimeError, "connection lost") as caught:
            PhysicalProgramming(service, operation_id="uncertain").apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct",
                journal=self.journal(),
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
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct",
                journal=self.journal(),
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
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct",
                journal=self.journal(),
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
                "//TEST/253/p/4", [("Value_ncc", "2")], method="ncc",
                journal=self.journal(),
            )
        self.assertEqual(service.commands, ["CMQTT CAPABILITIES"])

        # cmqttd's native boundary is specification-wide: a device family with
        # any NCC parameter performs Save-to-NVM after another tagged method
        # changes too.  The client learns that only after PP LOAD/INFO, but must
        # still refuse before the first staged mutation.
        service = PhysicalService(nvm=False)
        with self.assertRaisesRegex(
            PhysicalProgrammingError, "specification requires routed C-Bus 3"
        ) as caught:
            PhysicalProgramming(service, operation_id="directnvm").apply(
                "//TEST/253/p/4", [("Value_direct", "2")], method="direct",
                journal=self.journal(),
            )
        self.assertEqual(
            caught.exception.evidence["phase"], "save-capability-preflight"
        )
        self.assertTrue(caught.exception.evidence["physical_load_completed"])
        self.assertFalse(any(command.startswith("PP SET ") for command in service.commands))
        self.assertFalse(any("PP SAVE" in command for command in service.commands))

    def test_parameter_extent_mirrors_cmqttd_layouts(self):
        def param(kind, address="$20", size=1, **layout):
            return PhysicalParameter("P", kind, size, "direct", "none", address, (), **layout)

        self.assertEqual(parameter_extent(param("int", size=3)), (0x20, 3))
        self.assertEqual(parameter_extent(param("int", size=2, bit_size=12)), (0x20, 4))
        self.assertEqual(parameter_extent(param("int", size=3, array_skip=1)), (0x20, 5))
        self.assertEqual(parameter_extent(param("long", size=2, bit_size=32)), (0x20, 8))
        self.assertEqual(parameter_extent(param("bit", size=6, bit_address=5)), (0x20, 2))
        self.assertEqual(parameter_extent(param("string", "$110", 16)), (0x110, 16))
        self.assertEqual(parameter_extent(param("sixbit", "0x30", 8)), (0x30, 6))
        for bad in (param("int", bit_size=17), param("long", bit_size=12),
                    param("float"), param("int", address=None)):
            with self.subTest(bad=bad), self.assertRaises(PhysicalProgrammingError):
                parameter_extent(bad)

    def test_save_requires_a_journal_and_dry_run_refuses_one_before_io(self):
        service = PhysicalService()
        with self.assertRaisesRegex(ValueError, "requires a durable attempt journal"):
            PhysicalProgramming(service).apply(
                "//TEST/253/p/4", [("Value_direct", "2")], method="direct")
        with self.assertRaisesRegex(ValueError, "dry-run never saves"):
            PhysicalProgramming(service).apply(
                "//TEST/253/p/4", [("Value_direct", "2")], method="direct",
                dry_run=True, journal=self.journal())
        self.assertEqual(service.commands, [])

    def test_journal_is_durable_before_save_and_records_every_phase(self):
        service = PhysicalService()
        journal = self.journal()
        service.journal_path = journal
        result = PhysicalProgramming(service, operation_id="journal").apply(
            "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct", journal=journal)
        before_save = service.journal_at_save
        self.assertEqual(before_save["phase"], "save-sent")
        self.assertTrue(before_save["send_may_have_occurred"])
        self.assertTrue(before_save["read_only_recovery_only"])
        self.assertEqual(before_save["ranges"], [{"index": 0, "store_state": "possible"}])
        document = json.loads(journal.read_text())
        self.assertEqual([row["phase"] for row in document["history"]], [
            "planned", "save-sent", "save-confirmed", "readback-verified", "complete"])
        self.assertTrue(document["complete"] and document["resolved"])
        self.assertEqual(document["attempt_id"], result["journal"]["attempt_id"])
        plan = document["plan"]
        self.assertEqual(plan["unit"], {
            "source": "//TEST/253/p/4", "destination": "//TEST/253/p/4",
            "lock_address": "//TEST/253", "project": "TEST", "network": 253, "unit": 4})
        self.assertEqual(plan["pci_generation"], 7)
        self.assertTrue(plan["requires_nvm_commit"])
        self.assertEqual(document["nvm_commit"], "confirmed")
        [row] = plan["ranges"]
        self.assertEqual((row["parameter"], row["logical_address"], row["length"]),
                         ("Value_direct", 0x20, 1))
        import hashlib
        self.assertEqual(row["old_sha256"], hashlib.sha256(b"\x01").hexdigest())
        self.assertEqual(row["new_sha256"], hashlib.sha256(b"\x02").hexdigest())
        debug = [index for index, command in enumerate(service.commands)
                 if command.startswith("PP DEBUG mem cbus_pp_journal_write 20")]
        save = service.commands.index("PP SAVE_TO_SOURCE cbus_pp_journal_write")
        self.assertTrue(debug and debug[-1] < save)

    def test_uncertain_save_journal_states_follow_cmqttd_confirmed_count(self):
        service = PhysicalService()
        service.schema_method = "direct"
        final = "[9] 502 Physical PP save failed after 1 confirmed write(s): PCI response stream lost"
        service.fail_save = CGateError(CGateResponse((final,), final, 502))
        journal = self.journal()
        with self.assertRaises(CGateError) as caught:
            PhysicalProgramming(service, operation_id="partial").apply(
                "//TEST/253/p/4", [("Value_paged", "0x09"), ("Value_direct", "0x08")],
                method="direct", journal=journal)
        document = json.loads(journal.read_text())
        self.assertEqual(document["phase"], "save-uncertain")
        self.assertEqual([row["parameter"] for row in document["plan"]["ranges"]],
                         ["Value_direct", "Value_paged"])
        self.assertEqual([row["store_state"] for row in document["ranges"]],
                         ["confirmed", "uncertain"])
        self.assertEqual(document["save_reply"]["confirmed_writes_reported"], 1)
        # This all-direct schema declares no NCC field, so no NVM phase exists.
        self.assertEqual(document["nvm_commit"], "not-required")
        evidence = caught.exception.physical_programming_evidence
        self.assertEqual(evidence["journal"]["phase"], "save-uncertain")

        service = PhysicalService()
        service.fail_save = RuntimeError("C-Gate connection lost after send")
        # The first journal above is unresolved for this unit, so use another directory.
        (self.journals / "lost").mkdir()
        journal = self.journals / "lost" / "attempt.json"
        with self.assertRaises(RuntimeError):
            PhysicalProgramming(service, operation_id="lost").apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct", journal=journal)
        document = json.loads(journal.read_text())
        self.assertEqual([row["store_state"] for row in document["ranges"]], ["uncertain"])
        self.assertEqual(document["nvm_commit"], "uncertain")
        self.assertFalse(document["save_reply"]["server_reply"])

    def test_layout_disagreement_refuses_before_journal_or_save(self):
        service = PhysicalService()
        service.debug_change_missing = True
        journal = self.journal()
        with self.assertRaisesRegex(PhysicalProgrammingError, "declared extent"):
            PhysicalProgramming(service).apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct", journal=journal)
        self.assertFalse(journal.exists())
        self.assertFalse(any("PP SAVE" in command for command in service.commands))

    def test_unresolved_journal_refuses_repeat_saves_until_recovered(self):
        service = PhysicalService()
        service.fail_save = RuntimeError("lost")
        first = self.journal("first.json")
        with self.assertRaises(RuntimeError):
            PhysicalProgramming(service).apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct", journal=first)
        for path in (first, self.journal("second.json")):
            with self.subTest(path=path.name):
                repeat = PhysicalService()
                with self.assertRaisesRegex(PhysicalPPJournalError, "incomplete save"):
                    PhysicalProgramming(repeat).apply(
                        "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct",
                        journal=path)
                self.assertEqual(repeat.commands, [])
        # Another unit in the same directory is independent.
        other = PhysicalService()
        PhysicalProgramming(other).apply(
            "//TEST/253/p/5", [("Value_direct", "0x12")], method="direct",
            journal=self.journal("other.json"))
        # The lost save never reached the fake unit: recovery sees unchanged.
        recovery = PhysicalService()
        report = PhysicalProgramming(recovery).recover(first)
        self.assertEqual(report["outcome"], "observed_unchanged")
        self.assertTrue(report["conclusive"] and report["resolved"])
        self.assertFalse(any(command.startswith(("PP SET", "PP SAVE"))
                             for command in recovery.commands))
        with self.assertRaisesRegex(PhysicalPPJournalError, "finished attempt"):
            PhysicalProgramming(PhysicalService()).apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct", journal=first)
        PhysicalProgramming(PhysicalService()).apply(
            "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct",
            journal=self.journal("third.json"))

    def test_recover_classifies_each_range_and_resolves_only_when_conclusive(self):
        service = PhysicalService()
        service.schema_method = "direct"
        service.fail_save = RuntimeError("lost")
        journal = self.journal()
        with self.assertRaises(RuntimeError):
            PhysicalProgramming(service).apply(
                "//TEST/253/p/4", [("Value_direct", "0x02"), ("Value_paged", "0x03")],
                method="direct", journal=journal)
        cases = (
            ({"Value_direct": "0x02", "Value_paged": "0x03"}, ["expected", "expected"],
             "observed_expected", True),
            ({"Value_direct": "0x02", "Value_paged": "0x01"}, ["expected", "unchanged"],
             "observed_partial", True),
            ({"Value_direct": "0x77", "Value_paged": "0x01"}, ["mixed", "unchanged"],
             "observed_mixed", False),
        )
        for values, classes, outcome, conclusive in cases:
            with self.subTest(outcome=outcome):
                copy = self.journal()
                copy.write_bytes(journal.read_bytes())
                recovery = PhysicalService()
                recovery.schema_method = "direct"
                recovery.devices["//TEST/253/p/4"].update(values)
                report = PhysicalProgramming(recovery).recover(copy)
                self.assertEqual([row["classification"] for row in report["ranges"]], classes)
                self.assertEqual(report["outcome"], outcome)
                self.assertEqual(report["conclusive"], conclusive)
                document = json.loads(copy.read_text())
                self.assertEqual(document["resolved"], conclusive)
                self.assertEqual(document["recoveries"][-1]["classifications"], classes)
                self.assertEqual(document["phase"], "save-uncertain")
        # An unreadable unit leaves the journal unresolved and never writes.
        recovery = PhysicalService()
        recovery.fail_load = True
        report = PhysicalProgramming(recovery).recover(journal)
        self.assertEqual(report["outcome"], "unreadable")
        self.assertFalse(report["conclusive"])
        self.assertFalse(json.loads(journal.read_text())["resolved"])
        # A changed schema is not a conclusive observation either.
        recovery = PhysicalService()
        report = PhysicalProgramming(recovery).recover(journal)
        self.assertEqual(report["outcome"], "unreadable")
        self.assertEqual(report["errors"][0]["phase"], "schema")

    def test_crash_after_save_sent_leaves_a_recoverable_journal(self):
        service = PhysicalService()
        journal = self.journal()
        service.journal_path = journal
        PhysicalProgramming(service).apply(
            "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct", journal=journal)
        # The bytes on disk when SAVE arrived are what a crashed process leaves.
        crashed = self.journal("crashed.json")
        crashed.write_text(json.dumps(service.journal_at_save))
        with self.assertRaisesRegex(PhysicalPPJournalError, "incomplete save"):
            PhysicalProgramming(PhysicalService()).apply(
                "//TEST/253/p/4", [("Value_direct", "0x03")], method="direct",
                journal=self.journal())
        recovery = PhysicalService()
        recovery.devices["//TEST/253/p/4"]["Value_direct"] = "0x02"
        report = PhysicalProgramming(recovery).recover(crashed)
        self.assertEqual(report["journal_phase"], "save-sent")
        self.assertEqual(report["outcome"], "observed_expected")
        self.assertTrue(report["nvm_commit_uncertain"])

    def test_tampered_journal_is_rejected(self):
        service = PhysicalService()
        journal = self.journal()
        service.fail_save = RuntimeError("lost")
        with self.assertRaises(RuntimeError):
            PhysicalProgramming(service).apply(
                "//TEST/253/p/4", [("Value_direct", "0x02")], method="direct", journal=journal)
        document = json.loads(journal.read_text())
        document["plan"]["ranges"][0]["new_sha256"] = "0" * 64
        journal.write_text(json.dumps(document))
        with self.assertRaisesRegex(PhysicalPPJournalError, "attempt_id"):
            PhysicalProgramming(PhysicalService()).recover(journal)
        document["send_may_have_occurred"] = False
        journal.write_text(json.dumps(document))
        with self.assertRaisesRegex(PhysicalPPJournalError, "send_may_have_occurred"):
            PhysicalProgramming(PhysicalService()).recover(journal)

    def test_rust_evidence_roster_matches_python_workflow(self):
        fixture = Path(__file__).resolve().parents[2] / "rust/testdata/fixtures/native_cgate_routed_pp_methods.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(document["format"], "cmqttd-native-cgate-routed-pp-methods-evidence-v1")
        self.assertTrue(document["passed"])
        self.assertEqual(tuple(document["methods"]), SUPPORTED_METHODS)
        self.assertTrue(any("No live bridge" in item for item in document["evidence_boundaries"]))


if __name__ == "__main__":
    unittest.main()
