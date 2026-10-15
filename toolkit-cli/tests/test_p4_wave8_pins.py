"""Offline P4 wave-8 pin: protections / recovery / typed-edit / event edges.

Pure offline: no hardware, network, simulator, daemon or C-Gate I/O beyond
in-process fakes. One narrow pin advancing P4 issues 33-37 without touching
``rust/`` or device dialogs:

* P4.02 (#34): a ``special``-protected edit is journaled ``write_planned=False``
  (``physical_programming.py:_journal_plan`` via ``_save_writable``) while the
  ordinary parameter stays write-planned; the save still completes once.
* P4.03 (#35): a failed SAVE journals every planned range ``uncertain`` and a
  read-only ``recover`` classifies the untouched unit ``observed_unchanged``,
  resolves the journal, and issues no state-changing command.
* P4.04 (#36): the optional typed ``validate_session`` callback observes the
  ``loaded`` → ``staged`` → ``fresh`` phases in order on a full apply.
* P4.05/P4.03 (#37/#35): a PCI-generation move between SAVE and fresh LOAD
  refuses on the stale confirmation, marks the journal ``readback-unavailable``
  with ranges ``uncertain``, and sends no second SAVE (no replay).
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.physical_pp_journal import PhysicalPPJournal
from cbus_toolkit.physical_programming import (
    SUPPORTED_METHODS,
    PhysicalProgramming,
    PhysicalProgrammingError,
)


def response(*lines, status=200):
    lines = lines or (f"{status} OK",)
    return CGateResponse(tuple(lines), lines[-1], status)


CAPABILITIES = {
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
    "physical_pp_routed_nvm_commit": True,
    "physical_pp_routed_delivery_semantics": (
        "reply-network-unit-parameter-tag-correlated-exactly-once-no-replay"
    ),
    "physical_pp_routed_state_scope": "owned-session-target-network",
    "pci_generation": 7,
    "pci_connected": True,
    "programming_lane_state": "ready",
}

UNIT = "//TEST/253/p/4"


class FakeService:
    """Minimal offline cmqttd fake with two direct-method parameters."""

    PARAMS = (
        ("Value_direct", "$20", "none"),
        ("Special_field", "$21", "special"),
    )

    def __init__(self):
        self.commands: list[str] = []
        self.capabilities = dict(CAPABILITIES)
        self.sessions: dict[str, dict] = {}
        self.devices = {UNIT: {"Value_direct": "0x01", "Special_field": "0x01"}}
        self.fail_save: BaseException | None = None
        self.bump_generation_on_save: bool = False

    def _schema(self):
        rows = "".join(
            "<Param><Name>%s</Name><Type>int</Type><Address>%s</Address>"
            "<Protection>%s</Protection><Tag>Core</Tag></Param>" % param
            for param in self.PARAMS
        )
        return "<Parameters>" + rows + "</Parameters>"

    @staticmethod
    def _decode(value):
        assert value.startswith('"') and value.endswith('"')
        out, escaped = [], False
        for character in value[1:-1]:
            if escaped:
                out.append(character)
                escaped = False
            elif character == "\\":
                escaped = True
            else:
                out.append(character)
        assert not escaped
        return "".join(out)

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
            return response(
                f"315 {parameter}={self.sessions[session]['values'][parameter]}",
                status=315,
            )
        match = re.fullmatch(r"PP SET (\S+) (\S+) (.+)", command)
        if match:
            session, parameter, value = match.groups()
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
        order = [name for name, _, _ in self.PARAMS]
        base = 0x20
        addresses = [a for a in range(start, min(start + 16, base + len(order)))
                     if base <= a < base + len(order)]

        def byte(values, address):
            return f"{int(values[order[address - base]], 0) & 0xFF:02x}"

        cells = lambda values: "|".join(values) + "|"
        return response(
            "199-    unit>" + cells([byte(session["loaded"], a) for a in addresses]),
            "199- current>" + cells([byte(session["values"], a) for a in addresses]),
            "199-  change>"
            + cells(["ff" if order[a - base] in session["changed"] else "00"
                     for a in addresses]),
            status=199,
        )

    def _save(self, session, destination):
        if self.fail_save is not None:
            failure, self.fail_save = self.fail_save, None
            raise failure
        self.devices[destination] = dict(self.sessions[session]["values"])
        if self.bump_generation_on_save:
            self.capabilities["pci_generation"] = 8
        return response("200 OK")

    def state_changing(self):
        return [c for c in self.commands
                if c.startswith(("PP SET ", "PP SAVE", "PP SAVE_TO_SOURCE"))]


class Wave8PinTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def test_special_protection_journaled_not_write_planned(self):
        """P4.02: ``special`` edits stage but are never write-planned."""
        service = FakeService()
        journal = self.tmp / "attempt.json"
        result = PhysicalProgramming(service, operation_id="wave8prot").apply(
            UNIT, [("Value_direct", "0x02"), ("Special_field", "0x03")],
            method="direct", journal=journal,
        )
        self.assertTrue(result["complete"])
        self.assertTrue(result["saved"])
        document = PhysicalPPJournal.open(journal).document
        planned = {row["parameter"]: row for row in document["plan"]["ranges"]}
        self.assertTrue(planned["Value_direct"]["write_planned"])
        self.assertFalse(planned["Special_field"]["write_planned"])
        progress = {row["index"]: row["store_state"]
                    for row in document["ranges"]}
        plan_index = {row["parameter"]: row["index"]
                      for row in document["plan"]["ranges"]}
        self.assertEqual(progress[plan_index["Special_field"]], "not-planned")

    def test_failed_save_recovers_read_only_without_replay(self):
        """P4.03: failed SAVE journals ``uncertain``; recovery is read-only."""
        service = FakeService()
        service.fail_save = CGateError(response("500 SAVE failed", status=500))
        journal = self.tmp / "attempt.json"
        with self.assertRaises(CGateError):
            PhysicalProgramming(service, operation_id="wave8rec").apply(
                UNIT, [("Value_direct", "0x02")],
                method="direct", journal=journal,
            )
        document = PhysicalPPJournal.open(journal).document
        self.assertEqual(document["phase"], "save-uncertain")
        self.assertTrue(all(row["store_state"] == "uncertain"
                            for row in document["ranges"]
                            if document["plan"]["ranges"][row["index"]]["write_planned"]))
        recovery = FakeService()
        report = PhysicalProgramming(recovery, operation_id="wave8rec2").recover(journal)
        self.assertEqual(report["outcome"], "observed_unchanged")
        self.assertTrue(report["conclusive"])
        self.assertTrue(report["resolved"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["save_attempted"])
        self.assertEqual(recovery.state_changing(), [])

    def test_typed_validator_observes_loaded_staged_fresh(self):
        """P4.04: typed validator sees loaded/staged/fresh phases in order."""
        service = FakeService()
        seen: list[str] = []

        def validate(session, schema, phase, capabilities):
            seen.append(phase)
            self.assertIn("Value_direct", schema)
            self.assertTrue(capabilities["physical_pp_routed_load"])
            return {"phase": phase, "parameters": sorted(schema)}

        journal = self.tmp / "attempt.json"
        result = PhysicalProgramming(service, operation_id="wave8typed").apply(
            UNIT, [("Value_direct", "0x02")],
            method="direct", journal=journal, validate_session=validate,
        )
        self.assertEqual(seen, ["loaded", "staged", "fresh"])
        self.assertEqual(set(result["typed_validation"]), {"loaded", "staged", "fresh"})
        self.assertTrue(result["complete"])
        self.assertTrue(result["fresh_physical_readback_verified"])

    def test_generation_move_after_save_refuses_without_second_save(self):
        """P4.03/P4.05: stale SAVE confirmation never completes a new generation."""
        service = FakeService()
        service.bump_generation_on_save = True
        journal = self.tmp / "attempt.json"
        with self.assertRaisesRegex(PhysicalProgrammingError, "generation changed"):
            PhysicalProgramming(service, operation_id="wave8gen").apply(
                UNIT, [("Value_direct", "0x02")],
                method="direct", journal=journal,
            )
        saves = [c for c in service.commands if "SAVE" in c]
        self.assertEqual(len(saves), 1)
        document = PhysicalPPJournal.open(journal).document
        self.assertEqual(document["phase"], "readback-unavailable")
        self.assertTrue(all(row["store_state"] == "uncertain"
                            for row in document["ranges"]
                            if document["plan"]["ranges"][row["index"]]["write_planned"]))


if __name__ == "__main__":
    unittest.main()
