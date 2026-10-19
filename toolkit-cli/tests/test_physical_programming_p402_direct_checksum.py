"""Offline P4.02 slice: one verified protection pair, ``direct/checksum``.

Pure offline: no hardware, network, simulator, daemon or C-Gate I/O beyond
an in-process fake.  This pins the smallest safe programming-protections
subset for parity issue #34 against literal vectors:

* ``direct/checksum`` is the largest admitted pair in
  ``docs/pp-protection-matrix.json`` (1608 declarations, 108 files) and its
  native save contract is identical to ``direct/none``: changed bytes use
  the method's tagged STORE, the tag is a transaction index, and no
  checksum field is rewritten.  The direct space is linear, so there is no
  page edge; lock, factory-bit, special and other pairs stay out of scope.
* A changed edit (``Target`` ``0x01`` -> ``0x02``) is journaled
  ``changed=True``/``write_planned=True`` while a staged-but-unchanged edit
  (``Unchanged_direct`` ``0x0A`` -> ``0x0A``) is journaled
  ``changed=False``/``write_planned=False`` (``not-planned``).
* Neighbor preservation: unedited schema parameters on both sides, an
  unedited NCC field, and undeclared guard bytes must be byte-identical
  after the save.
* Unit-wide NCC commit gating: the schema declares an unedited NCC field,
  so the plan requires the C-Bus 3 Save-to-NVM phase and refuses before the
  first SET when ``physical_pp_routed_nvm_commit`` is absent.
* Journal uncertainty: a failed SAVE with literal per-range rows
  (``uncertain`` for the changed range, ``skipped-unchanged`` for the
  staged-but-unchanged range) journals ``uncertain``/``not-planned``, and a
  read-only ``recover`` classifies the untouched unit without any
  state-changing command.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.physical_pp_journal import PhysicalPPJournal
from cbus_toolkit.physical_programming import (
    P402_VERIFIED_PAIR,
    SUPPORTED_METHODS,
    PhysicalProgramming,
    PhysicalProgrammingError,
)

UNIT = "//TEST/253/p/4"

SCHEMA = (
    "<Parameters>"
    "<Param><Name>Left</Name><Type>int</Type><Address>$1F</Address>"
    "<ProgramMethod>direct</ProgramMethod>"
    "<Protection>checksum</Protection><Tag>Core</Tag></Param>"
    "<Param><Name>Target</Name><Type>int</Type><Address>$20</Address>"
    "<ProgramMethod>direct</ProgramMethod>"
    "<Protection>checksum</Protection><Tag>Core</Tag></Param>"
    "<Param><Name>Unchanged_direct</Name><Type>int</Type><Address>$21</Address>"
    "<ProgramMethod>direct</ProgramMethod>"
    "<Protection>checksum</Protection><Tag>Core</Tag></Param>"
    "<Param><Name>Right</Name><Type>int</Type><Address>$22</Address>"
    "<ProgramMethod>direct</ProgramMethod>"
    "<Protection>checksum</Protection><Tag>Core</Tag></Param>"
    "<Param><Name>NccField</Name><Type>int</Type><Address>$300</Address>"
    "<ArraySize>2</ArraySize><ProgramMethod>ncc</ProgramMethod>"
    "<Protection>checksum</Protection><Tag>Core</Tag></Param>"
    "</Parameters>"
)

# Literal logical layout backing the schema above.
EXTENTS = {
    "Left": (0x1F, 1),
    "Target": (0x20, 1),
    "Unchanged_direct": (0x21, 1),
    "Right": (0x22, 1),
    "NccField": (0x300, 2),
}

INITIAL_VALUES = {
    "Left": "0xB0",
    "Target": "0x01",
    "Unchanged_direct": "0x0A",
    "Right": "0xC0",
    "NccField": "0x33 0x44",
}

# Undeclared guard bytes: no schema parameter covers them, so no PP
# DEBUG/GET/SET ever names them; only a whole-memory snapshot can prove
# they survived.
INITIAL_RAW = {0x1E: 0xAA, 0x23: 0xBB, 0x2FF: 0xCC, 0x302: 0xDD}


def response(*lines, status=200):
    lines = lines or (f"{status} OK",)
    return CGateResponse(tuple(lines), lines[-1], status)


class FakeChecksumService:
    """Minimal offline cmqttd fake for the direct/checksum P4.02 slice."""

    def __init__(self, *, schema_text=SCHEMA, nvm=True, **capabilities):
        self.commands: list[str] = []
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
        self.capabilities.update(capabilities)
        self.schema_text = schema_text
        self.sessions: dict[str, dict] = {}
        self.device = dict(INITIAL_VALUES)
        self.raw = dict(INITIAL_RAW)
        self.fail_save: BaseException | None = None

    def snapshot(self):
        return {"params": dict(self.device), "raw": dict(self.raw)}

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

    def _byte(self, values, address):
        for name, (base, length) in EXTENTS.items():
            if base <= address < base + length:
                tokens = values[name].split()
                return f"{int(tokens[address - base], 0) & 0xFF:02x}"
        if address in self.raw:
            return f"{self.raw[address] & 0xFF:02x}"
        return "00"

    def _owner(self, address):
        for name, (base, length) in EXTENTS.items():
            if base <= address < base + length:
                return name
        return None

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
                "values": dict(self.device),
                "loaded": dict(self.device),
                "changed": set(),
            }
            return response("200 OK")
        match = re.fullmatch(r"PP DEBUG mem (\S+) ([0-9a-f]+)", command)
        if match:
            session, start = match.groups()
            state = self.sessions[session]
            addresses = range(int(start, 16), int(start, 16) + 16)
            cells = lambda values: "|".join(values) + "|"
            return response(
                "199-    unit>" + cells([self._byte(state["loaded"], a) for a in addresses]),
                "199- current>" + cells([self._byte(state["values"], a) for a in addresses]),
                "199-  change>" + cells(
                    ["ff" if self._owner(a) in state["changed"] else "00" for a in addresses]
                ),
                status=199,
            )
        match = re.fullmatch(r"PP INFO (\S+) \*", command)
        if match:
            return response(
                "343-Begin XML snippet",
                "347-" + self.schema_text,
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
            return self._save(match[1])
        match = re.fullmatch(r"PP SAVE (\S+) (\S+)", command)
        if match:
            return self._save(match[1])
        match = re.fullmatch(r"PP END (\S+)", command)
        if match:
            self.sessions.pop(match[1], None)
            return response("200 OK")
        raise AssertionError("Unexpected native command: " + command)

    def _save(self, session):
        if self.fail_save is not None:
            failure, self.fail_save = self.fail_save, None
            raise failure
        state = self.sessions[session]
        for parameter in state["changed"]:
            self.device[parameter] = state["values"][parameter]
        return response("200 OK")

    def state_changing(self):
        return [c for c in self.commands if c.startswith(("PP SET ", "PP SAVE"))]


class DirectChecksumP402Tests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.count = 0

    def journal(self, name=None):
        self.count += 1
        return self.tmp / (name or f"attempt-{self.count}.json")

    def test_verified_pair_identity(self):
        self.assertEqual(P402_VERIFIED_PAIR, ("direct", "checksum"))

    def test_changed_unchanged_neighbor_and_unit_wide_nvm_commit(self):
        """P4.02: changed/unchanged journaling with neighbor preservation."""
        service = FakeChecksumService()
        before = service.snapshot()
        journal = self.journal()
        result = PhysicalProgramming(service, operation_id="p402ok").apply(
            UNIT, [("Target", "0x02"), ("Unchanged_direct", "0x0A")],
            method="direct", journal=journal,
        )
        self.assertTrue(result["complete"])
        self.assertTrue(result["saved"])
        self.assertFalse(result["save_outcome_uncertain"])
        self.assertTrue(result["staged_readback_verified"])
        self.assertTrue(result["fresh_physical_readback_verified"])
        self.assertFalse(result["power_cycle_persistence_verified"])
        self.assertEqual(result["save_attempts"], 1)
        self.assertEqual(result["automatic_write_retries"], 0)
        self.assertEqual(result["before"], {"Target": "0x01", "Unchanged_direct": "0x0A"})
        self.assertEqual(result["staged"], {"Target": "0x02", "Unchanged_direct": "0x0A"})
        self.assertEqual(result["verified"], {"Target": "0x02", "Unchanged_direct": "0x0A"})
        admission = result["protection_admission"]
        self.assertEqual(admission["pairs"], ["direct/checksum", "direct/checksum"])
        self.assertEqual(admission["verified_pair"], "direct/checksum")
        self.assertIn("checksum", admission["save_protection"])

        document = PhysicalPPJournal.open(journal).document
        self.assertEqual(document["phase"], "complete")
        plan = document["plan"]
        # Unit-specification order, with the unedited NCC field marking the
        # whole unit as requiring the C-Bus 3 Save-to-NVM phase.
        self.assertEqual(
            [(row["parameter"], row["logical_address"], row["length"],
              row["changed"], row["write_planned"]) for row in plan["ranges"]],
            [("Target", 0x20, 1, True, True),
             ("Unchanged_direct", 0x21, 1, False, False)],
        )
        self.assertTrue(plan["requires_nvm_commit"])
        self.assertEqual(document["nvm_commit"], "confirmed")
        self.assertEqual(
            [row["store_state"] for row in document["ranges"]],
            ["confirmed", "not-planned"],
        )
        self.assertEqual(
            plan["ranges"][0]["old_sha256"], hashlib.sha256(b"\x01").hexdigest())
        self.assertEqual(
            plan["ranges"][0]["new_sha256"], hashlib.sha256(b"\x02").hexdigest())
        self.assertEqual(
            plan["ranges"][1]["old_sha256"], hashlib.sha256(b"\x0a").hexdigest())
        self.assertEqual(
            plan["ranges"][1]["new_sha256"], hashlib.sha256(b"\x0a").hexdigest())

        # Neighbor preservation: only the changed byte moved; unedited
        # schema parameters, the unedited NCC field and every undeclared
        # guard byte are byte-identical.
        after = service.snapshot()
        changed = [name for name in before["params"]
                   if before["params"][name] != after["params"][name]]
        self.assertEqual(changed, ["Target"])
        self.assertEqual(after["params"]["Target"], "0x02")
        self.assertEqual(after["raw"], before["raw"])

    def test_save_protection_unavailable_refuses_before_mutation(self):
        """P4.02: an unadvertised checksum protection refuses with no I/O."""
        service = FakeChecksumService(physical_pp_routed_save_protection=["none", "lock"])
        journal = self.journal()
        with self.assertRaisesRegex(PhysicalProgrammingError, "save protection") as caught:
            PhysicalProgramming(service, operation_id="p402noprot").apply(
                UNIT, [("Target", "0x02")], method="direct", journal=journal,
            )
        evidence = caught.exception.evidence
        self.assertEqual(evidence["phase"], "save-capability-preflight")
        self.assertFalse(evidence["complete"])
        self.assertFalse(evidence["save_attempted"])
        self.assertEqual(
            evidence["protection_admission"]["pairs"], ["direct/checksum"])
        self.assertFalse(journal.exists())
        self.assertEqual(
            [c for c in service.commands
             if c.startswith(("PP SET ", "PP SAVE", "PP DEBUG ", "PP GET "))], [])

    def test_unknown_protection_refuses_before_mutation(self):
        """P4.02: a protection outside the matrix refuses with no I/O."""
        schema = SCHEMA.replace(
            "<Param><Name>Target</Name><Type>int</Type><Address>$20</Address>"
            "<ProgramMethod>direct</ProgramMethod>"
            "<Protection>checksum</Protection>",
            "<Param><Name>Target</Name><Type>int</Type><Address>$20</Address>"
            "<ProgramMethod>direct</ProgramMethod>"
            "<Protection>weird</Protection>",
        )
        service = FakeChecksumService(schema_text=schema)
        journal = self.journal()
        with self.assertRaisesRegex(PhysicalProgrammingError, "not an admitted"):
            PhysicalProgramming(service, operation_id="p402weird").apply(
                UNIT, [("Target", "0x02")], method="direct", journal=journal,
            )
        self.assertFalse(journal.exists())
        self.assertEqual(service.state_changing(), [])

    def test_malformed_save_protection_refuses_before_mutation(self):
        """P4.02: a malformed server declaration refuses rather than guessing."""
        service = FakeChecksumService(physical_pp_routed_save_protection="checksum")
        journal = self.journal()
        with self.assertRaisesRegex(PhysicalProgrammingError, "malformed"):
            PhysicalProgramming(service, operation_id="p402malformed").apply(
                UNIT, [("Target", "0x02")], method="direct", journal=journal,
            )
        self.assertFalse(journal.exists())
        self.assertEqual(service.state_changing(), [])

    def test_unit_wide_ncc_commit_gating_refuses_before_mutation(self):
        """P4.02: a unit declaring NCC needs Save-to-NVM even for direct edits."""
        service = FakeChecksumService(nvm=False)
        journal = self.journal()
        with self.assertRaisesRegex(PhysicalProgrammingError, "Save-to-NVM"):
            PhysicalProgramming(service, operation_id="p402nonvm").apply(
                UNIT, [("Target", "0x02")], method="direct", journal=journal,
            )
        self.assertFalse(journal.exists())
        self.assertEqual(service.state_changing(), [])

    def test_failed_save_is_uncertain_and_recovers_read_only(self):
        """P4.02: literal range rows journal uncertainty; recover is read-only."""
        service = FakeChecksumService()
        rows = (
            "502-range 0 direct 32+1 stores=0/1 readback=0 uncertain",
            "502-range 1 direct 33+1 stores=0/0 readback=0 skipped-unchanged",
        )
        final = "[9] 502 Physical PP save failed after 0 confirmed write(s): PCI response stream lost"
        service.fail_save = CGateError(CGateResponse(rows + (final,), final, 502))
        journal = self.journal()
        with self.assertRaises(CGateError):
            PhysicalProgramming(service, operation_id="p402fail").apply(
                UNIT, [("Target", "0x02"), ("Unchanged_direct", "0x0A")],
                method="direct", journal=journal,
            )
        document = PhysicalPPJournal.open(journal).document
        self.assertEqual(document["phase"], "save-uncertain")
        # The changed range follows its literal uncertain row; the
        # staged-but-unchanged range was never write-planned.
        self.assertEqual(
            [row["store_state"] for row in document["ranges"]],
            ["uncertain", "not-planned"],
        )
        self.assertEqual(
            [(row["start"], row["len"], row["outcome"])
             for row in document["save_reply"]["ranges"]],
            [(32, 1, "uncertain"), (33, 1, "skipped-unchanged")],
        )
        self.assertEqual(document["save_reply"]["confirmed_writes_reported"], 0)
        self.assertEqual(document["nvm_commit"], "not-reached")

        recovery = FakeChecksumService()
        untouched = recovery.snapshot()
        report = PhysicalProgramming(recovery, operation_id="p402rec").recover(journal)
        self.assertTrue(report["read_only"])
        self.assertFalse(report["save_attempted"])
        self.assertEqual(report["method"], "direct")
        # Fresh bytes match the staged digest for the unchanged edit and the
        # loaded digest for the interrupted edit: conclusive partial.
        self.assertEqual(
            [(row["parameter"], row["classification"]) for row in report["ranges"]],
            [("Target", "unchanged"), ("Unchanged_direct", "expected")],
        )
        self.assertEqual(report["outcome"], "observed_partial")
        self.assertTrue(report["conclusive"])
        self.assertTrue(report["resolved"])
        self.assertEqual(recovery.state_changing(), [])
        self.assertEqual(recovery.snapshot(), untouched)
        self.assertTrue(PhysicalPPJournal.open(journal).document["resolved"])


if __name__ == "__main__":
    unittest.main()
