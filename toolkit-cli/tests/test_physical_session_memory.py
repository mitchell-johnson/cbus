"""Offline _cell/_session_memory incomplete slice.

Pure offline, no hardware, network, simulator, daemon or C-Gate I/O beyond
the in-process ``PhysicalService`` fake. Covers the two zero-direct-ref
branches at ``toolkit-cli/src/cbus_toolkit/physical_programming.py:340-344``
(``_cell``) and ``:804-806`` (``_journal_plan`` incomplete refuse via
``_session_memory`` ``??`` -> ``None``):

* ``_cell("??")`` maps to ``None``; valid hex parses; ``"ZZ"`` and other
  non-hex pairs raise ``PhysicalProgrammingError("malformed memory cell")``.
* ``_session_memory`` propagates ``??`` as ``None`` via a fake
  ``debug_memory`` (pure, no PP I/O).
* ``PhysicalProgramming.apply`` refuses with
  ``"is incomplete; no PP SAVE was sent"`` when the staged DEBUG rows
  contain ``??``, sending no SAVE and creating no journal file.

Existing ``PhysicalService`` in ``test_physical_programming.py`` never emits
``??`` (it always formats ``%02x`` bytes) and never sends malformed cells,
so these branches had no offline coverage. This pins them directly without
changing workflow semantics.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.physical_programming import (
    SUPPORTED_METHODS,
    PhysicalProgramming,
    PhysicalProgrammingError,
    _cell,
    _session_memory,
)


def response(*lines, status=200):
    lines = lines or (f"{status} OK",)
    return CGateResponse(tuple(lines), lines[-1], status)


class FakeDebugSession:
    """Minimal ``session.debug_memory`` stub for pure ``_session_memory`` pins."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def debug_memory(self, address):
        self.calls.append(address)
        return self._replies.pop(0)


def debug_reply(unit_cells, current_cells, change_cells):
    cells = lambda values: "|".join(values) + "|"
    return response(
        "199-    unit>" + cells(unit_cells),
        "199- current>" + cells(current_cells),
        "199-  change>" + cells(change_cells),
        status=199,
    )


class CellTests(unittest.TestCase):
    def test_unknown_maps_to_none_and_hex_parses(self):
        self.assertIsNone(_cell("??"))
        self.assertEqual(_cell("00"), 0)
        self.assertEqual(_cell("01"), 1)
        self.assertEqual(_cell("ff"), 0xFF)
        self.assertEqual(_cell("FF"), 0xFF)
        self.assertEqual(_cell("0a"), 0x0A)

    def test_malformed_cells_refuse(self):
        for bad in ("ZZ", "", "1", "010", "GG", "zz", "?? ", " ??", "0x01", "0G"):
            with self.subTest(cell=bad):
                with self.assertRaisesRegex(
                    PhysicalProgrammingError, "malformed memory cell"
                ):
                    _cell(bad)


class SessionMemoryTests(unittest.TestCase):
    def test_propagates_unknown_without_io(self):
        session = FakeDebugSession(
            [debug_reply(["??"], ["02"], ["ff"])]
        )
        memory = _session_memory(session, 0x20, 1)
        self.assertEqual(memory["unit"], [None])
        self.assertEqual(memory["current"], [2])
        self.assertEqual(memory["change"], [True])
        self.assertEqual(session.calls, [0x20])

    def test_loops_across_debug_windows(self):
        # Two one-byte windows cover a two-byte extent; second window
        # carries the unknown marker.
        session = FakeDebugSession(
            [
                debug_reply(["01"], ["02"], ["ff"]),
                debug_reply(["??"], ["04"], ["ff"]),
            ]
        )
        memory = _session_memory(session, 0x20, 2)
        self.assertEqual(memory["unit"], [1, None])
        self.assertEqual(memory["current"], [2, 4])
        self.assertEqual(session.calls, [0x20, 0x21])


class PhysicalService:
    """Minimal cmqttd fake mirroring test_physical_programming.PhysicalService."""

    def __init__(self, *, incomplete_debug=False):
        self.commands = []
        self.incomplete_debug = incomplete_debug
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
            "physical_pp_routed_nvm_commit": True,
            "physical_pp_routed_delivery_semantics": (
                "reply-network-unit-parameter-tag-correlated-exactly-once-no-replay"
            ),
            "physical_pp_routed_state_scope": "owned-session-target-network",
            "pci_generation": 7,
            "pci_connected": True,
            "programming_lane_state": "ready",
        }
        self.sessions = {}
        self.devices = {"//TEST/253/p/4": {"Value_direct": "0x01"}}

    def _schema(self):
        return (
            "<Parameters><Param><Name>Value_direct</Name><Type>int</Type>"
            "<Address>$20</Address>"
            "<Protection>none</Protection><Tag>Core</Tag></Param></Parameters>"
        )

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
                "loaded": dict(self.devices[source]),
                "changed": set(),
            }
            return response("200 OK")
        match = re.fullmatch(r"PP DEBUG mem (\S+) ([0-9a-f]+)", command)
        if match:
            if self.incomplete_debug:
                return response(
                    "199-    unit>??|",
                    "199- current>02|",
                    "199-  change>ff|",
                    status=199,
                )
            session = self.sessions[match[1]]
            loaded = int(session["loaded"]["Value_direct"], 0) & 0xFF
            staged = int(session["values"]["Value_direct"], 0) & 0xFF
            changed = "ff" if "Value_direct" in session["changed"] else "00"
            return response(
                f"199-    unit>{loaded:02x}|",
                f"199- current>{staged:02x}|",
                f"199-  change>{changed}|",
                status=199,
            )
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
            self.sessions[session]["values"][parameter] = self._decode(value)
            self.sessions[session]["changed"].add(parameter)
            return response("200 OK")
        match = re.fullmatch(r"PP SAVE_TO_SOURCE (\S+)", command)
        if match:
            self.devices[self.sessions[match[1]]["source"]] = dict(
                self.sessions[match[1]]["values"]
            )
            return response("200 OK")
        match = re.fullmatch(r"PP END (\S+)", command)
        if match:
            self.sessions.pop(match[1], None)
            return response("200 OK")
        raise AssertionError("Unexpected native command: " + command)


class IncompleteMemoryApplyTests(unittest.TestCase):
    def test_apply_refuses_when_session_memory_incomplete(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        journal = Path(directory.name) / "attempt.json"
        service = PhysicalService(incomplete_debug=True)
        with self.assertRaisesRegex(
            PhysicalProgrammingError, "is incomplete; no PP SAVE was sent"
        ) as caught:
            PhysicalProgramming(service, operation_id="incomplete").apply(
                "//TEST/253/p/4",
                [("Value_direct", "0x02")],
                method="direct",
                journal=journal,
            )
        self.assertFalse(journal.exists())
        self.assertFalse(any("PP SAVE" in c for c in service.commands))
        self.assertTrue(any(c.startswith("PP DEBUG mem ") for c in service.commands))

        # Control: the same edit with complete DEBUG rows saves unchanged.
        control_dir = tempfile.TemporaryDirectory()
        self.addCleanup(control_dir.cleanup)
        control_journal = Path(control_dir.name) / "attempt.json"
        control = PhysicalService(incomplete_debug=False)
        result = PhysicalProgramming(control, operation_id="complete").apply(
            "//TEST/253/p/4",
            [("Value_direct", "0x02")],
            method="direct",
            journal=control_journal,
        )
        self.assertTrue(result["complete"])
        self.assertTrue(result["saved"])
        self.assertTrue(control_journal.exists())
        self.assertTrue(any("PP SAVE" in c for c in control.commands))


if __name__ == "__main__":
    unittest.main()
