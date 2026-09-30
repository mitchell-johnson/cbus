#!/usr/bin/env python3
"""Capture native C-Gate 3.4 and cmqttd PP LOAD/SET/SAVE_TO_SOURCE transcripts.

Each case starts one owned loopback ``LocalCGate`` with a disposable project
whose CNI is a research-only ``MethodMemoryFixture`` on an ephemeral loopback
port. The fixture emulates one unit of a real catalogue type per method
family and answers that method's memory protocol from a zero-filled synthetic
memory image: direct/paged/NCC tagged STOREs and ``1A``/``1B`` recalls, ``39``
page selection, ``11`` UNLOCK, OEM ``41``/``42`` selector and data STOREs with
parameter-1 recalls, the GIU ``FC`` run flag, GOC parameter-``FF`` selector and
address-prefixed STOREs, and the C-Bus 3 Save-to-NVM extended CAL. Nothing
connects to a real CNI, PCI or C-Bus network.

The same PP command sequence is then replayed through ``cmqttd --cgate-bind``
against a fresh fixture with identical memory. ``--output`` receives a
sanitized transcript: exact C-Gate commands and replies, each endpoint's
ordered request CALs per phase, the bytes each STORE changed, and a computed
native-versus-cmqttd difference per case. Unit specifications are read from
the private decoded directory and never written to the output; parameter
names, addresses and synthetic values are the only specification facts kept.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from cbus_toolkit.cgate import CGateClient, CGateError  # noqa: E402
from cbus_toolkit.native import NativeDatabase, NativeProjects  # noqa: E402
from cbus_toolkit.networks import NativeNetworks  # noqa: E402
from cbus_toolkit.simulator import PCISimulator, UnitState, synthetic_units  # noqa: E402
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402

FORMAT = "cbus-native-pp-method-transcripts-v1"
SANITIZED_PROJECT = "PPNAT"
NETWORK = 254
REPO = HERE.parents[1]

# One real catalogue type per method family with a native specification.
# ``goc`` has no catalogue revision in C-Gate 3.4.0.2001 (see ``NO_NATIVE``).
UNITS = {
    "direct": {"address": 4, "type": "KEY4", "firmware": "1.2.67"},
    "paged": {"address": 6, "type": "WRD4F1", "firmware": "2.3.0"},
    "ncc": {"address": 7, "type": "RELDN4A", "firmware": "1.0.0"},
    "edlt": {"address": 8, "type": "KEYGL5", "firmware": "5.5.00"},
    "giu": {"address": 9, "type": "PC_GIM", "firmware": "5.5.00"},
    "sgiu": {"address": 10, "type": "PC_TSA", "firmware": "4.6.00"},
    "dali": {"address": 11, "type": "PC_DAL2B", "firmware": "4.6.00"},
    "gocbyt": {"address": 12, "type": "DIMPR12", "firmware": "1.10.0"},
    "goc2": {"address": 13, "type": "DIMAR12", "firmware": "1.0.00"},
}
NO_NATIVE = {"goc": "No C-Gate 3.4.0.2001 cbusunits.xml revision names a specification with a goc parameter."}
GOC2_TYPES = {"DIMAR12"}  # CBusGOC2Dimmer.h() is true: STORE ACKs name the low address byte.
OEM_TYPES = {"KEYGL5", "PC_GIM", "PC_TSA", "PC_DAL2B"}
GOC_TYPES = {"DIMPR12", "DIMAR12"}

# name -> (method, [(parameter, value)])
CASES = {
    "direct_key4_array": ("direct", [("LightLevel", " ".join(["$5A"] * 16))]),
    "paged_wrd4f1_page1_and_lock": ("paged", [("Remote6KeyMap", "$01 $02 $03 $04 $05 $06 $07 $08"),
                                             ("MaxTransmitAttempts", "$03")]),
    "ncc_reldn4a_edit": ("ncc", [("Ch0GroupAddress", "$21")]),
    "ncc_reldn4a_no_edit": ("ncc", []),
    "ncc_reldn4a_same_value": ("ncc", [("Ch0GroupAddress", "$00")]),
    "edlt_keygl5_adjacent": ("edlt", [("ConfigVersionMinor", "$07"), ("ConfigVersionMajor", "$05")]),
    "giu_pc_gim_array": ("giu", [("Port0_ScaleFactorB", "$11 $22 $33 $44")]),
    "sgiu_pc_tsa": ("sgiu", [("ZoneGroup", "$02")]),
    "dali_pc_dal2b": ("dali", [("DaliARestoreLevel", "$40")]),
    "gocbyt_dimpr12_array": ("gocbyt", [("CbusDMXSwitchOverFadeTime", "$01 $02 $03 $04 $05 $06")]),
    "goc2_dimar12_word": ("goc2", [("KeyDebouncePeriod", "$0105")]),
}


# Reviewed native-versus-cmqttd differences.  ``fixed`` rows changed cmqttd;
# ``deliberate`` rows keep a documented cmqttd contract.  The capture and
# ``tests/test_native_pp_method_transcripts.py`` check each against the data.
DIFFERENCES = {
    "goc2_ack_parameter": {
        "methods": ["goc2"], "decision": "fixed",
        "native": "Accepts a GOC2 selector or STORE acknowledgement only when it names the low address byte "
                  "(32 <addr&FF> <tag>); with 32 FF <tag> its address selection fails with 408 and it "
                  "retransmits the STORE three times.",
        "cmqttd": "Previously required parameter FF; now correlates the low address byte for goc2 and keeps FF "
                  "for goc/gocbyt."},
    "lazy_over_reads": {
        "methods": ["direct", "paged", "ncc", "edlt", "giu", "sgiu", "dali", "gocbyt", "goc2"],
        "decision": "deliberate",
        "native": "PP LOAD reads nothing; each first GET reads the covering native group, up to the method's "
                  "recall limit beyond the field (for example 1A 0D 0C for a four-byte tail).",
        "cmqttd": "PP LOAD identifies the unit and reads every selected field's exact extent once."},
    "save_verification": {
        "methods": ["direct", "paged", "ncc", "edlt", "giu", "sgiu", "dali", "gocbyt", "goc2"],
        "decision": "deliberate",
        "native": "SAVE_TO_SOURCE sends only the STOREs (plus page, UNLOCK, GIU run flags and NVM commit), "
                  "with no IDENTIFY, pre-read or readback.",
        "cmqttd": "Re-identifies type and firmware, pre-reads each changed range and reads it back after its "
                  "STOREs; the STORE bytes themselves match native."},
    "giu_halt_during_reads": {
        "methods": ["giu"], "decision": "deliberate",
        "native": "Brackets GET reads, as well as SAVE stores, with the FC 03 00 / FC 03 01 run flag.",
        "cmqttd": "Reads never write; only the STOREs are bracketed by the run flag."},
    "store_tag_scope": {
        "methods": ["paged"], "decision": "deliberate",
        "native": "Numbers STORE tags by group across the whole SAVE (page-0 lock STORE tag 00, page-1 STORE "
                  "tag 01).",
        "cmqttd": "Numbers tags within each verified range, so both STOREs use tag 00; every exchange is "
                  "serialized and correlated by parameter and tag, and each range is read back."},
    "edlt_adjacent_fields": {
        "methods": ["edlt"], "decision": "deliberate",
        "native": "Merges adjacent changed fields into one selector and one two-byte STORE.",
        "cmqttd": "Stores and verifies each changed field range separately; final memory is identical."},
    "ncc_nvm_gating": {
        "methods": ["ncc"], "decision": "deliberate",
        "native": "Every SAVE_TO_SOURCE to a C-Bus 3 unit ends with E3 81 00 04, including a SAVE with no SET "
                  "and one whose SET repeats the current value; a same-value SET is also stored.",
        "cmqttd": "Stores only changed bytes and sends the Save-to-NVM EXECUTE only after a changed ncc range "
                  "was verified, so an unchanged SAVE sends no mutation."},
    "local_checksums": {
        "methods": ["direct", "paged", "ncc", "edlt", "giu", "sgiu", "dali", "gocbyt", "goc2"],
        "decision": "observation",
        "native": "Sent every request without a C-Bus checksum on this simulated CNI, whose interface options "
                  "native C-Gate did not reprogram; this is interface configuration, not a PP method rule.",
        "cmqttd": "Checksums local STORE, RECALL, IDENTIFY and OEM frames and leaves 1B, 39, 11 and E3 "
                  "unchecksummed, as documented."},
}


def _cal_length(cal):
    opcode = cal[0]
    if opcode in (0x1A, 0x2A):
        return 3
    if opcode == 0x1B:
        return 4
    if opcode in (0x11, 0x21, 0x39):
        return 2
    if opcode & 0xE0 in (0xA0, 0xE0):
        return (opcode & 0x1F) + 1
    return None


class MethodMemoryFixture(PCISimulator):
    """PCI plus one synthetic unit per method; records every unit request."""

    def __init__(self, *, methods=tuple(UNITS), goc2_ack="low"):
        pci = synthetic_units()[2]
        selected = [UNITS[method] for method in methods]
        units = [pci] + [
            UnitState(unit["address"], {1: unit["type"].ljust(8).encode(), 2: unit["firmware"].ljust(8).encode()},
                      mmi_state=1)
            for unit in selected]
        super().__init__(units, local_unit=pci.address, profile="synthetic", physical_memory={})
        self.types = {unit["address"]: unit["type"] for unit in selected}
        self.memory = {address: {"cal": bytearray(65536), "oem": bytearray(65536), "goc": bytearray(65536)}
                       for address in self.types}
        self.page = {}
        self.oem_pointer = {}
        self.goc_pointer = {}
        self.goc2_ack = goc2_ack
        self.phase = None
        self.requests = []
        self.writes = []

    def _record(self, connection, direction, data, reason=None):
        super()._record(connection, direction, data, reason)
        self.wire_log[-1]["time"] = time.monotonic()
        self.wire_log[-1]["phase"] = self.phase

    # -- reply helpers ---------------------------------------------------
    def _frames(self, unit, envelope, cals):
        prefix = bytes([0x86, unit, self.local_unit, 0x01, 0x00] if envelope == "oem"
                       else [0x86, unit, self.local_unit, 0x00])
        return b"".join(self._reply(prefix + bytes(cal)) for cal in cals)

    @staticmethod
    def _chunks(parameter, data, advancing, size=16):
        return [bytes([0x80 | (len(data[i:i + size]) + 1), (parameter + i) & 0xFF if advancing else parameter])
                + bytes(data[i:i + size]) for i in range(0, len(data), size)]

    def _write(self, unit, space, address, data):
        memory = self.memory[unit][space]
        before = bytes(memory[address:address + len(data)])
        memory[address:address + len(data)] = data
        self.writes.append({"phase": self.phase, "unit": unit, "space": space, "address": address,
                            "before": before.hex().upper(), "after": bytes(data).hex().upper()})

    # -- request handling ------------------------------------------------
    def _command(self, line, context):
        code = line[-1:] if line and ord("g") <= line[-1] <= ord("z") else b""
        raw = line[:-1] if code else line
        explicit = raw.startswith(b"\\")
        text = raw[1:] if explicit else raw
        if raw.startswith(b"@") or not text or len(text) % 2:
            return super()._command(line, context)
        try:
            payload = bytes.fromhex(text.decode())
        except ValueError:
            return super()._command(line, context)
        packet = payload if explicit or context["header"] is None else context["header"] + payload
        if len(packet) < 4 or packet[0] != 0x46 or packet[1] not in self.types:
            return super()._command(line, context)
        unit = packet[1]
        if packet[2:4] == b"\x09\x00":
            envelope, header, body = "oem", packet[:4], packet[4:]
        elif packet[2] == 0:
            envelope, header, body = "direct", packet[:3], packet[3:]
        else:
            return super()._command(line, context)
        cals, rest = [], body
        while rest:
            if len(rest) == 1 and cals and not sum(packet) & 0xFF:
                break  # Trailing C-Bus checksum, not a one-byte CAL.
            length = _cal_length(rest)
            if length is None or len(rest) < length:
                break
            cals.append(rest[:length])
            rest = rest[length:]
        checksummed = len(rest) == 1 and not sum(packet) & 0xFF
        if not cals or (rest and not checksummed):
            self._log(unit, envelope, body, None, code, packet, "unparsed")
            return (code + b"#") if code else b"!", "Unsupported fixture CAL"
        if explicit:
            context["header"] = header
        replies = []
        for index, cal in enumerate(cals):
            self._log(unit, envelope, cal, checksummed, code, packet, chained=index if len(cals) > 1 else None)
            try:
                replies.append(self._answer(unit, envelope, cal))
            except ValueError as error:
                self.requests[-1]["rejected"] = str(error)
                return (code + b"#") if code else b"!", str(error)
        ack = code + b"." if code else b""
        if len(replies) > 1 and all(len(reply) == 1 for reply in replies):
            # Chained requests share one reply frame, as the base simulator does.
            return ack + self._frames(unit, envelope, [b"".join(reply[0] for reply in replies)]), None
        return ack + b"".join(self._frames(unit, envelope, reply) for reply in replies if reply), None

    def _log(self, unit, envelope, cal, checksummed, code, packet, note=None, chained=None):
        row = {"phase": self.phase, "unit": unit, "envelope": envelope, "cal": bytes(cal).hex().upper(),
               "checksummed": checksummed, "confirmation": bool(code), "time": time.monotonic()}
        if chained is not None:
            row["chained"] = chained
        if note:
            row["rejected"] = note
            row["packet"] = bytes(packet).hex().upper()
        self.requests.append(row)

    def _answer(self, unit, envelope, cal):
        kind = self.types[unit]
        memory = self.memory[unit]
        opcode = cal[0]
        if opcode == 0x21:
            attribute = cal[1]
            if attribute in (1, 2):
                return [bytes([0x89, attribute]) + self.units[unit].attributes[attribute]]
            if attribute == 8:
                return [bytes([0x86, 8]) + bytes(5)]
            if attribute == 0xFE:
                # CBusWirelessUnit.t() polls an eight-byte status block.
                return [bytes([0x89, 0xFE]) + bytes(8)]
            if attribute == 4:
                # Synthetic twelve-byte summary; not a device claim.
                return [bytes([0x8D, 4]) + bytes.fromhex("FFFFFFFFFF0000000000FF00")]
            # Class-specific discovery probes (for example 10 or 51..53)
            # get a zero block so they do not retry into the PP exchanges.
            return [bytes([0x85, attribute]) + bytes(4)]
        if opcode == 0x2A:
            parameter, count = cal[1:]
            return [bytes([0x80 | (count + 1), parameter]) + bytes(count)]
        if opcode == 0x39:
            self.page[unit] = cal[1]
            return [bytes([0x81, cal[1]])]
        if opcode == 0x11:
            return [bytes([0x82, cal[1], 0x5A])]
        if opcode == 0x1B:
            page, parameter, count = cal[1:]
            start = page * 256 + parameter
            return self._chunks(parameter, memory["cal"][start:start + count], advancing=True)
        if opcode == 0xE3 and cal[1:] == b"\x81\x00\x04":
            self.writes.append({"phase": self.phase, "unit": unit, "space": "nvm", "operation": "execute"})
            return [b"\xE4\x83\x00\x04\x00"]
        if opcode == 0x1A:
            parameter, count = cal[1:]
            if envelope == "oem" and parameter == 1 and kind in OEM_TYPES:
                pointer = self.oem_pointer.get(unit)
                if pointer is None:
                    raise ValueError("OEM recall without a selector")
                self.oem_pointer[unit] = pointer + count
                return self._chunks(1, memory["oem"][pointer:pointer + count], advancing=False)
            if parameter == 0xFF and kind in GOC_TYPES:
                pointer = self.goc_pointer.get(unit)
                if pointer is None:
                    raise ValueError("GOC recall without a selector")
                self.goc_pointer[unit] = pointer + count
                return self._chunks(0xFF, memory["goc"][pointer:pointer + count], advancing=False)
            if envelope != "direct":
                raise ValueError("Unsupported OEM recall")
            return self._chunks(parameter, memory["cal"][parameter:parameter + count], advancing=True)
        if opcode & 0xE0 == 0xA0:
            parameter, data = cal[1], cal[2:]
            if not data:
                raise ValueError("STORE without a tag")
            tag = data[0]
            if envelope == "oem":
                if kind not in OEM_TYPES:
                    raise ValueError("OEM STORE to a non-OEM fixture unit")
                if parameter == 0 and tag == 0x41 and 3 <= len(data) <= 5:
                    self.oem_pointer[unit] = int.from_bytes(data[1:], "little")
                    return [bytes([0x32, 0, 0x41])]
                if parameter == 1 and tag == 0x42 and len(data) >= 2 and unit in self.oem_pointer:
                    pointer = self.oem_pointer[unit]
                    self._write(unit, "oem", pointer, data[1:])
                    self.oem_pointer[unit] = pointer + len(data) - 1
                    return [bytes([0x32, 1, 0x42])]
                if parameter == 0xFC and tag == 0x03 and data[1:] in (b"\x00", b"\x01"):
                    self.writes.append({"phase": self.phase, "unit": unit, "space": "run_flag",
                                        "value": data[1]})
                    return [bytes([0x32, 0xFC, 0x03])]
                raise ValueError("Unsupported OEM STORE")
            if parameter == 0xFF and kind in GOC_TYPES:
                ack = parameter
                if len(data) == 3 and tag == 0x42:
                    self.goc_pointer[unit] = int.from_bytes(data[1:3], "big")
                else:
                    if len(data) < 4:
                        raise ValueError("GOC STORE without data")
                    self._write(unit, "goc", int.from_bytes(data[1:3], "big"), data[3:])
                if kind in GOC2_TYPES and self.goc2_ack == "low":
                    ack = data[2]
                return [bytes([0x32, ack, tag])]
            start = self.page.get(unit, 0) * 256 + parameter
            self._write(unit, "cal", start, data[1:])
            return [bytes([0x32, parameter, tag])]
        raise ValueError(f"Unsupported fixture CAL {bytes(cal).hex()}")


# -- C-Gate command driving --------------------------------------------------

def _run(client, command):
    try:
        response = client.command(command)
        return response.status, list(response.lines)
    except CGateError as error:
        return error.response.status, list(error.response.lines)


def drive_case(client, fixture, project, name, method, sets, transcript):
    """Run one LOAD / SET / SAVE_TO_SOURCE session; return its record."""
    unit = UNITS[method]["address"]
    network = f"//{project}/{NETWORK}"
    digest = hashlib.sha256(name.encode()).hexdigest()[:6]
    session, lock = f"s{digest}", f"l{digest}"
    record = {"method": method, "unit_type": UNITS[method]["type"], "firmware": UNITS[method]["firmware"],
              "unit": unit, "sets": [list(item) for item in sets], "commands": []}

    def command(text, phase=None):
        started[phase] = started.get(phase, time.monotonic())
        fixture.phase = phase
        status, lines = _run(client, text)
        fixture.phase = None
        record["commands"].append({"phase": phase, "command": text.replace(project, SANITIZED_PROJECT),
                                   "status": status,
                                   "reply": [line.replace(project, SANITIZED_PROJECT) for line in lines]})
        return status, lines

    started = {}
    first = len(fixture.requests)
    first_write = len(fixture.writes)
    command(f"PROJECT USE {project}", "other")
    command(f"PP LOCK {lock} {network}", "other")
    command(f"PP START {session} {lock}", "other")
    command(f"PP LOAD {session} {network}/p/{unit}", "load")
    for parameter, _ in sets:
        command(f"PP GET {session} {parameter}", "get_before")
    for parameter, value in sets:
        command(f"PP SET {session} {parameter} {value}", "set")
    command(f"PP SAVE_TO_SOURCE {session}", "save")
    for parameter, _ in sets:
        command(f"PP GET {session} {parameter}", "get_after")
    command(f"PP END {session}", "other")
    command(f"PP UNLOCK {lock}", "other")
    requests = fixture.requests[first:]
    record["requests"] = {phase: [_public(row) for row in requests if row["phase"] == phase]
                          for phase in PHASES}
    record["stray_requests"] = [_public(row) for row in requests if row["phase"] not in PHASES]
    record["writes"] = [row for row in fixture.writes[first_write:]]
    record["save_timing"] = _timing(requests, started.get("save"))
    transcript[name] = record
    return record


PHASES = ("load", "get_before", "set", "save", "get_after", "other")
# Native PP LOAD defers memory reads to the first GET; cmqttd reads at LOAD.
READ_PHASES = ("load", "get_before", "set")


def _public(row):
    """Compact request text: envelope initial, CAL hex, ``*`` when checksummed.

    ``d:`` is the direct ``46 unit 00`` envelope and ``o:`` the OEM
    ``46 unit 09 00`` envelope; a rejected request ends in ``!``.
    """
    return (f"{row['envelope'][0]}:{row['cal']}" + ("*" if row["checksummed"] else "")
            + ("!" if row.get("rejected") else ""))


def _parse(text):
    envelope, cal = text.split(":", 1)
    return {"envelope": {"d": "direct", "o": "oem"}[envelope], "cal": cal.rstrip("*!"),
            "checksummed": cal.rstrip("!").endswith("*")}


def _timing(requests, save_started):
    """Largest pause before a SAVE request (DALI's one-second settle)."""
    save = [row for row in requests if row["phase"] == "save"]
    times = [save_started] + [row["time"] for row in save]
    gaps = [round(later - earlier, 1) for earlier, later in zip(times, times[1:]) if earlier is not None]
    return {"max_gap_before_save_request_s": max(gaps) if gaps else None}


# -- native ------------------------------------------------------------------

# Native discovery proceeds in roughly ten-second steps; PP starts only after
# a longer quiet period so a pending discovery step cannot hold the unit.
QUIET_SECONDS = 15


def _native_case(vendor, java, name, goc2_ack):
    """One owned daemon, disposable project and one-unit fixture per case.

    Native discovery of several heterogeneous synthetic units, or of a second
    project in the same daemon, can stall after IDENTIFY 1, so every case
    starts from a fresh owned process and discovers only its own unit.
    """
    method, sets = CASES[name]
    service = LocalCGate(vendor, java=java)
    try:
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
    except BaseException as error:
        service._cleanup_preserving(error)
        raise
    fixture = MethodMemoryFixture(methods=(method,), goc2_ack=goc2_ack)
    project = "PP" + uuid4().hex[:6].upper()
    network = f"//{project}/{NETWORK}"
    unit = UNITS[method]
    transcript = {}
    with service, fixture.running("127.0.0.1", 0) as (_, port):
        with CGateClient("127.0.0.1", service.port, timeout=900) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                db.create_network(project, NETWORK, "PPNative", "Cni", "127.0.0.1:" + str(port))
                db.create_unit(network, unit["address"], method.upper(), unit["type"], unit["firmware"])
                projects.operation("save", project)
                for setting in ("AutoUnravel no", "AutoUpdate no"):
                    _run(client, "SET " + network + " " + setting)
                NativeNetworks(client).open(network)
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if any("running" in line for line in _run(client, "GET " + network + " InterfaceState")[1]):
                        break
                    time.sleep(.2)
                else:
                    raise RuntimeError("No running interface")
                # Native creates the live unit object only after discovery,
                # which continues after NET SYNC returns.  Wait for the
                # firmware IDENTIFY and a quiet stream before PP.
                fixture.phase = "sync"
                _run(client, "NET SYNC " + network)
                deadline = time.monotonic() + int(os.environ.get("CBUS_PP_SYNC_WAIT", "120"))
                while time.monotonic() < deadline:
                    identified = any(row["cal"] == "2102" for row in fixture.requests)
                    if identified and time.monotonic() - fixture.requests[-1]["time"] > QUIET_SECONDS:
                        break
                    time.sleep(1)
                fixture.phase = None
                discovery = [_public(row) for row in fixture.requests]
                fixture.requests.clear()
                fixture.writes.clear()
                drive_case(client, fixture, project, name, method, sets, transcript)
            finally:
                for command in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                    try:
                        client.command(command)
                    except Exception:  # Research cleanup is best effort.
                        pass
    previous, rejected = None, []
    for row in fixture.wire_log:
        if row["direction"] == "rx":
            previous = row
        elif "reason" in row:
            rejected.append({"request_hex": previous and previous["hex"], "reason": row["reason"]})
    dump = os.environ.get("CBUS_PP_WIRE_DUMP")
    if dump:
        Path(dump, name + ".jsonl").write_text("".join(json.dumps(row) + "\n" for row in fixture.wire_log))
    record = transcript[name]
    record["discovery_requests"] = discovery
    record["base_rejections"] = rejected
    return record, service.report


def capture_native(vendor, java, cases, *, goc2_ack="low"):
    transcript, reports = {}, []
    attempts = int(os.environ.get("CBUS_PP_NATIVE_ATTEMPTS", "3"))
    for name in cases:
        for attempt in range(1, attempts + 1):
            record, report = _native_case(vendor, java, name, goc2_ack)
            reports.append(report)
            print("native", name, attempt, [c["status"] for c in record["commands"]], flush=True)
            # A synthetic unit occasionally stalls native's next exchange for
            # about ten seconds and that PP command times out; the whole case
            # is then repeated on a fresh daemon and fixture, never resumed.
            if all(command["status"] < 400 for command in record["commands"]) or goc2_ack != "low":
                break
        record["native_attempts"] = attempt
        transcript[name] = record
    oracle = {key: sorted({str(report.get(key)) for report in reports}) for key in (
        "vendor_jar_sha256", "java_sha256", "listener_ownership_verified", "cleanup_complete",
        "process_exit_confirmed", "work_removed")}
    oracle.update(version="3.4.0 build 2001", physical_endpoint=False, owned_processes=len(reports))
    return transcript, oracle


# -- cmqttd ------------------------------------------------------------------

def _project_xml(path):
    units = "".join(
        f'<Unit oid="u{unit["address"]}"><TagName>{method.upper()}</TagName><Address>{unit["address"]}</Address>'
        f'<UnitType>{unit["type"]}</UnitType><FirmwareVersion>{unit["firmware"]}</FirmwareVersion></Unit>'
        for method, unit in UNITS.items())
    path.write_text(
        f'<Installation><Project oid="project"><TagName>{SANITIZED_PROJECT}</TagName>'
        f'<Network oid="n{NETWORK}"><TagName>PPNative</TagName><Address>{NETWORK}</Address>'
        '<Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:10001</InterfaceAddress>'
        '</Interface><Unit oid="pci"><Address>16</Address><UnitType>PC_CNI2</UnitType></Unit>'
        f'{units}</Network></Project></Installation>', encoding="utf-8")


def _spec_dir(unitspec, vendor, target):
    for source in Path(unitspec).glob("*.xml"):
        shutil.copyfile(source, target / source.name)
    catalogue = Path(vendor) / "unitspec/cbusunits.xml"
    if catalogue.is_file():
        shutil.copyfile(catalogue, target / "cbusunits.xml")


@contextmanager
def _cmqttd(binary, pci, project, specs, work):
    with socket.socket() as broker:
        broker.bind(("127.0.0.1", 0))
        broker.listen(1)
        log_path = work / "cmqttd.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen([
                str(binary), "--tcp", f"{pci[0]}:{pci[1]}", "--broker-address", "127.0.0.1",
                "--broker-port", str(broker.getsockname()[1]), "--broker-disable-tls",
                "--timesync", "0", "--status-resync", "0", "--project-file", str(project),
                "--cgate-bind", "127.0.0.1:0", "--cgate-state", str(work / "state.json"),
                "--cgate-unitspec", str(specs)], stdout=subprocess.DEVNULL, stderr=log)
            try:
                deadline = time.monotonic() + 30
                port = None
                while time.monotonic() < deadline:
                    log.seek(0)
                    match = re.search(r"C-Gate service listening on 127\.0\.0\.1:(\d+)", log.read())
                    if match:
                        port = int(match[1])
                        break
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError("cmqttd exited: " + log.read()[-2000:])
                    time.sleep(0.05)
                if port is None:
                    raise RuntimeError("cmqttd did not start its C-Gate service")
                yield port
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def capture_cmqttd(binary, unitspec, vendor, cases, *, goc2_ack="low"):
    transcript = {}
    with tempfile.TemporaryDirectory(prefix="cbus-pp-cmqttd-") as temporary:
        work = Path(temporary)
        specs = work / "unitspec"
        specs.mkdir()
        _spec_dir(unitspec, vendor, specs)
        project = work / "project.xml"
        _project_xml(project)
        for name in cases:
            # A fresh fixture per case: cmqttd retires its PCI stream after
            # an incomplete transaction, and each case starts from zero memory.
            fixture = MethodMemoryFixture(goc2_ack=goc2_ack)
            case_work = work / name
            case_work.mkdir()
            with fixture.running("127.0.0.1", 0) as pci, _cmqttd(binary, pci, project, specs, case_work) as port:
                with CGateClient("127.0.0.1", port, timeout=300) as client:
                    fixture.requests.clear()
                    method, sets = CASES[name]
                    drive_case(client, fixture, SANITIZED_PROJECT, name, method, sets, transcript)
                    print("cmqttd", name, [c["status"] for c in transcript[name]["commands"]], flush=True)
    return transcript


# -- comparison ----------------------------------------------------------------

def collapse(rows):
    """Drop immediate retransmissions of the same request (native retries)."""
    result = []
    for row in rows:
        key = (row["envelope"], row["cal"])
        if not result or result[-1] != key:
            result.append(key)
    return result


def is_selector(envelope, cal):
    """OEM ``41`` or GOC ``42`` address selection: addressing, not memory."""
    return ((envelope == "oem" and cal.startswith("A") and cal[2:6] == "0041")
            or (envelope == "direct" and cal.startswith("A4FF42")))


def mutations(rows):
    """Memory STOREs, page selection, UNLOCK, GIU run flags and NVM commits."""
    return [(envelope, cal) for envelope, cal in collapse(rows)
            if cal[:1] in ("A", "B") and not is_selector(envelope, cal) or cal[:2] in ("39", "11", "E3")]


def reads(rows):
    return [(envelope, cal) for envelope, cal in collapse(rows) if cal[:2] in ("1A", "1B")]


def compare(native, cmqttd):
    """Per-case request differences; both sides use the same fixture memory."""
    result = {}
    for name in native:
        if name not in cmqttd or not native[name] or not cmqttd[name]:
            continue
        left, right = native[name], cmqttd[name]
        row = {}
        for label, phases in (("before_save", READ_PHASES), ("save", ("save",))):
            lrows = [_parse(r) for phase in phases for r in left["requests"][phase]]
            rrows = [_parse(r) for phase in phases for r in right["requests"][phase]]
            row[label] = {"identical": collapse(lrows) == collapse(rrows),
                          "native_requests": len(collapse(lrows)), "cmqttd_requests": len(collapse(rrows)),
                          "native_reads": len(reads(lrows)), "cmqttd_reads": len(reads(rrows)),
                          "native_identify": sum(r["cal"][:2] == "21" for r in lrows),
                          "cmqttd_identify": sum(r["cal"][:2] == "21" for r in rrows),
                          "native_checksummed_opcodes": sorted({r["cal"][:2] for r in lrows if r["checksummed"]}),
                          "cmqttd_checksummed_opcodes": sorted({r["cal"][:2] for r in rrows if r["checksummed"]})}
        native_mutations = mutations([_parse(r) for r in left["requests"]["save"]])
        cmqttd_mutations = mutations([_parse(r) for r in right["requests"]["save"]])
        row["save_mutations"] = {"identical": native_mutations == cmqttd_mutations,
                                 "native": [cal for _, cal in native_mutations],
                                 "cmqttd": [cal for _, cal in cmqttd_mutations]}
        row["memory_after_save_identical"] = _memory(left) == _memory(right)
        row["save_status"] = {"native": _status(left, "save"), "cmqttd": _status(right, "save")}
        result[name] = row
    return result


def _memory(record):
    """Final bytes written per (space, address), independent of STORE grouping."""
    memory = {}
    for write in record["writes"]:
        if "after" in write:
            data = bytes.fromhex(write["after"])
            for offset, value in enumerate(data):
                memory[(write["space"], write["address"] + offset)] = value
        elif write["space"] == "nvm":
            # Presence, not count: a native retransmission repeats EXECUTE.
            memory[("nvm", write["operation"])] = 1
    return memory


def _status(record, phase):
    return next((c["status"] for c in record["commands"] if c["phase"] == phase), None)


def probe_goc2_ff(vendor, java):
    """Native GOC2 PP when the unit acknowledges with parameter FF instead."""
    name = "goc2_dimar12_word"
    record, report = _native_case(vendor, java, name, "ff")
    get = next(c for c in record["commands"] if c["phase"] == "get_before")
    save = next(c for c in record["commands"] if c["phase"] == "save")
    return {"fixture_store_ack": "32FF<tag>", "cleanup_complete": report.get("cleanup_complete"),
            "get_status": get["status"], "get_reply": get["reply"],
            "get_requests": record["requests"]["get_before"],
            "save_status": save["status"], "save_requests": record["requests"]["save"],
            "finding": "Native address selection fails without a low-address-byte acknowledgement; its GOC "
                       "STORE path checks only for a negative acknowledgement, retransmits the uncorrelated "
                       "STORE and still reports SAVE success."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, default=os.environ.get("CBUS_LOCAL_CGATE_VENDOR"))
    parser.add_argument("--java", type=Path, default=os.environ.get("CBUS_CGATE_JAVA"))
    parser.add_argument("--unitspec", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    parser.add_argument("--cmqttd", type=Path, default=os.environ.get("CBUS_CMQTTD_BIN"))
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    parser.add_argument("--skip-native", action="store_true")
    parser.add_argument("--skip-cmqttd", action="store_true")
    parser.add_argument("--goc2-ack", choices=("low", "ff"), default="low")
    parser.add_argument("--probe-goc2-ff", action="store_true",
                        help="Add the native GOC2 parameter-FF acknowledgement probe to an existing --output")
    parser.add_argument("--output", type=Path,
                        default=REPO / "rust/testdata/fixtures/native_cgate_pp_method_transcripts.json")
    args = parser.parse_args()
    if args.probe_goc2_ff:
        document = json.loads(args.output.read_text())
        document["goc2_parameter_ff_ack_probe"] = probe_goc2_ff(args.vendor, args.java)
        document["differences"] = DIFFERENCES
        document["comparison"] = compare({name: case["native"] for name, case in document["cases"].items()},
                                         {name: case["cmqttd"] for name, case in document["cases"].items()})
        document["capture_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        args.output.write_text(json.dumps(document, indent=1) + "\n")
        return
    cases = args.case or list(CASES)
    native, oracle = ({}, None) if args.skip_native else capture_native(args.vendor, args.java, cases, goc2_ack=args.goc2_ack)
    cmqttd = capture_cmqttd(args.cmqttd, args.unitspec, args.vendor, cases, goc2_ack=args.goc2_ack) \
        if args.cmqttd and not args.skip_cmqttd else {}
    document = {
        "format": FORMAT,
        "scope": "Owned loopback native C-Gate 3.4.0 build 2001 and cmqttd against a research-only synthetic "
                 "method-memory fixture with one unit per programming-method family. Zero-filled memory, "
                 "UNLOCK challenge 5A and NVM status 00 are fixture choices, not device firmware, persistence "
                 "or hardware evidence.",
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "jar_sha256": JAR_SHA256, "oracle": oracle,
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "units": UNITS, "no_native_specification": NO_NATIVE, "differences": DIFFERENCES,
        "fixture": {"memory": "zero-filled 64 KiB standard/paged, OEM and GOC images per unit",
                    "unlock_reply_hex": "82<parameter>5A", "nvm_execute_reply_hex": "E483000400",
                    "goc2_store_ack": "32<low address byte><tag>" if args.goc2_ack == "low" else "32FF<tag>",
                    "reply_fragment_bytes": 16},
        "cases": {name: {"native": native.get(name), "cmqttd": cmqttd.get(name)} for name in cases},
        "comparison": compare(native, cmqttd),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1) + "\n")


if __name__ == "__main__":
    main()
