"""Python CLI -> cmqttd -> independent PCI programming acceptance.

The peer in this module deliberately does not reuse the Rust protocol encoder,
decoder, transport, or cmqttd test support.  It implements only the literal
wire forms needed by the ten admitted PP methods and records every request.

Expected transcripts are derived by ``expected_transcript`` below, not copied
from daemon output.  Its sources are:

* C-Gate 3.4 ``lP`` (owned CFR output): per-method STORE limits ``lP.P``
  (direct/paged/ncc/eDLT/GIU/SGIU/DALI 12, GOC/GOCBYT 10, GOC2 11), RECALL
  limits ``lP.N`` (direct/paged/GIU/SGIU/DALI 12, GOC/GOCBYT 6, GOC2/NCC 255),
  the save-loop group index used as the STORE tag, page-bounded groups, the
  ``dd`` UNLOCK before each lock-protected group, GIU's ``bm`` run-flag halt
  before and resume after its STOREs, and DALI's one-second settle before its
  first STORE.  The same facts are summarised in
  ``research/simulator-protocol-evidence.md``.
* ``ct``/``cg``/``K``/``L``/``dd``/``aV``/``aU``/``bm``/``bn``/``bo`` CAL bodies:
  tagged ``A0|n`` STORE, ``1A`` RECALL, ``39`` page select, ``1B`` paged
  RECALL whose fragments name ``start + received``, ``11`` UNLOCK, OEM ``41``
  little-endian selector and ``42`` data tag, GOC ``42`` big-endian selector
  and ``[tag, hi, lo, data]`` STORE.
* Native literal frames retained in ``rust/testdata/vectors``:
  ``tp-0101-cgate-protected-parameter-unlock`` (unchecksummed local UNLOCK),
  ``tp-cgate-cbus3-save-nvm-execute``/``-poll`` (unchecksummed local
  EXECUTE/POLL); ``rust/testdata/fixtures/native_cgate_routed_pp_methods.json``
  and ``native_cgate_routed_nvm_commit.json`` (routed frames); and
  ``research/fixtures/pci-routed-identify-original-vectors.json`` (original
  route byte ``9 x hops`` and bridge order) plus
  ``pci-routed-recall-original-vectors.json`` (Reply Network shape).
* cmqttd's own documented contract (``docs/cmqttd-cgate.md``): IDENTIFY type
  and firmware before LOAD and SAVE, a pre-read of each changed range, exact
  readback after every STORE range, reads that never write (no GIU halt during
  LOAD), exact parameter extents instead of native N-byte over-reads, a page
  selection at the start of every paged STORE range, and the checksummed
  PCI profile for local STORE, RECALL, IDENTIFY and OEM frames.

These are scripted-PCI integration tests, not physical-device, live-bridge or
power-cycle acceptance.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time

import pytest
from cbus_toolkit.simulator import PCISimulator


ROOT = Path(__file__).resolve().parents[2]


def find_cmqttd():
    override = os.environ.get("CBUS_CMQTTD_BIN")
    candidate = Path(override) if override else ROOT / "rust/target/debug/cmqttd"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate.resolve()
    return None


BIN = find_cmqttd()
needs_cmqttd = pytest.mark.skipif(BIN is None, reason="Build cmqttd before cross-language interop")

METHODS = ("direct", "paged", "ncc", "edlt", "giu", "sgiu", "dali", "goc", "gocbyt", "goc2")
PAGED = ("paged", "ncc")
OEM = ("edlt", "giu", "sgiu", "dali")
GOC = ("goc", "gocbyt", "goc2")
UNIT = 5
LOCAL_PCI = 16
ROUTES = {
    "local": (),
    "one-bridge": (253,),
    "six-bridges": (253, 252, 251, 250, 249, 248),
}
# One representative per method family crosses the longest admitted route.
SIX_BRIDGE_METHODS = ("direct", "ncc", "giu", "gocbyt")

STORE_LIMIT = {"direct": 12, "paged": 12, "ncc": 12, "edlt": 12, "giu": 12,
               "sgiu": 12, "dali": 12, "goc": 10, "gocbyt": 10, "goc2": 11}
RECALL_LIMIT = {"direct": 12, "paged": 12, "ncc": 255, "giu": 12, "sgiu": 12,
                "dali": 12, "goc": 6, "gocbyt": 6, "goc2": 255,
                # Native bj accepts 255; cmqttd retains its captured 128 block.
                "edlt": 128}
# Local frames that native C-Gate sends without a C-Bus checksum.
UNCHECKSUMMED_LOCAL = (0x1B, 0x39, 0x11, 0xE3)

ADDRESSES = {
    "direct": 0x20, "paged": 0x1FF, "ncc": 0x300,
    "edlt": 0x110, "giu": 0x120, "sgiu": 0x130, "dali": 0x140,
    "goc": 0x150, "gocbyt": 0x160, "goc2": 0x170,
}
# Multi-chunk layouts: 25 bytes cross two twelve-byte groups and leave one
# byte; paged and NCC also cross a page; GOC stores cross two groups.
MULTI = {
    "direct": (0x20, 25), "paged": (0x1F4, 25), "ncc": (0x3F4, 25),
    "edlt": (0x110, 25), "giu": (0x110, 25), "sgiu": (0x110, 25), "dali": (0x110, 25),
    "goc": (0x150, 23), "gocbyt": (0x150, 23), "goc2": (0x150, 23),
}


# Native groups for the MULTI layouts: twelve-byte groups (paged/NCC split
# again at their page boundary), GOC/GOCBYT ten and GOC2 eleven bytes.
MULTI_CHUNKS = {
    **{method: (12, 12, 1) for method in ("direct", "paged", "ncc", *OEM)},
    "goc": (10, 10, 3), "gocbyt": (10, 10, 3), "goc2": (11, 11, 1),
}


class _DropConnection(Exception):
    pass


def _checksum(body):
    return bytes((*body, -sum(body) & 0xFF))


def _hex(data):
    return data.hex().upper()


def _reply(parameter, data):
    return bytes((0x80 | (len(data) + 1), parameter, *data))


def _write(parameter, data):
    return bytes((0xA0 | (len(data) + 1), parameter, *data))


# --------------------------------------------------------------------------
# Independent wire model
# --------------------------------------------------------------------------

def request_wire(route, cal, envelope="direct"):
    """Encode one outgoing request as the hex text between ``\\`` and CR."""
    cal = bytes(cal)
    if route:
        header = bytes((0x46, route[0], 9 * len(route), *route[1:], UNIT))
        return _hex(_checksum(header + cal))
    if envelope == "oem":
        return _hex(_checksum(bytes((0x46, UNIT, 0x09, 0x00)) + cal))
    body = bytes((0x46, UNIT, 0x00)) + cal
    return _hex(body if cal[0] in UNCHECKSUMMED_LOCAL else _checksum(body))


def reply_frame(route, cal, *, unit=UNIT, envelope="direct"):
    if route:
        body = bytes((0x86, route[0], LOCAL_PCI, len(route), *route[1:], unit)) + bytes(cal)
    elif envelope == "oem":
        body = bytes((0x86, unit, LOCAL_PCI, 0x01, 0x00)) + bytes(cal)
    else:
        body = bytes((0x86, unit, LOCAL_PCI, 0x00)) + bytes(cal)
    return _hex(_checksum(body)).encode("ascii") + b"\r\n"


def physical(method, address):
    return address - 256 if method in OEM + GOC else address


def read_steps(method, address, count):
    """cmqttd read of exactly one range with the method's native limit."""
    steps = []
    start = physical(method, address)
    offset = 0
    while offset < count:
        position = start + offset
        if method in PAGED:
            page, parameter = divmod(position, 256)
            size = min(count - offset, 256 - parameter, RECALL_LIMIT[method])
            steps.append((bytes((0x1B, page, parameter, size)), "direct"))
        elif method in OEM:
            size = min(count - offset, RECALL_LIMIT[method])
            steps.append((_write(0, bytes((0x41, *position.to_bytes(2, "little")))), "oem"))
            steps.append((bytes((0x1A, 0x01, size)), "oem"))
        elif method in GOC:
            size = min(count - offset, RECALL_LIMIT[method])
            steps.append((_write(0xFF, bytes((0x42, *position.to_bytes(2, "big")))), "direct"))
            steps.append((bytes((0x1A, 0xFF, size)), "direct"))
        else:
            size = min(count - offset, RECALL_LIMIT[method])
            steps.append((bytes((0x1A, position, size)), "direct"))
        offset += size
    return steps


@dataclass
class Store:
    method: str
    tag: int
    address: int
    data: bytes


@dataclass
class Plan:
    wires: list = field(default_factory=list)
    stores: list = field(default_factory=list)
    unlocks: list = field(default_factory=list)
    nvm: list = field(default_factory=list)
    first_store_index: int | None = None


# cmqttd pre-reads merged ranges in its SAVE space order.
SPACE_ORDER = {method: index for index, method in enumerate(
    ("direct", "paged", "ncc", "edlt", "giu", "sgiu", "dali", "goc", "gocbyt", "goc2"))}
# cmqttd LOAD reads standard, then paged, OEM and GOC ranges.
LOAD_ORDER = {"direct": 0, **dict.fromkeys(PAGED, 1), **dict.fromkeys(OEM, 2),
              **dict.fromkeys(GOC, 3)}


def store_steps(method, address, data, *, locked):
    """Native lP save groups for one changed range, then cmqttd readback."""
    steps, stores, unlocks = [], [], []
    start = physical(method, address)
    limit = STORE_LIMIT[method]
    groups = []
    offset = 0
    while offset < len(data):
        position = start + offset
        size = min(len(data) - offset, limit)
        if method in PAGED:
            size = min(size, 256 - position % 256)
        groups.append((position, data[offset:offset + size]))
        offset += size
    if method == "giu":
        steps.append((_write(0xFC, b"\x03\x00"), "oem"))
    selected_page = None
    for tag, (position, chunk) in enumerate(groups):
        if method in PAGED:
            page, parameter = divmod(position, 256)
            if page != selected_page:
                steps.append((bytes((0x39, page)), "direct"))
                selected_page = page
            if locked:
                steps.append((bytes((0x11, parameter)), "direct"))
                unlocks.append((page, parameter))
            steps.append((_write(parameter, bytes((tag, *chunk))), "direct"))
            stores.append(Store(method, tag, position, chunk))
        elif method in OEM:
            steps.append((_write(0, bytes((0x41, *position.to_bytes(2, "little")))), "oem"))
            steps.append((_write(1, bytes((0x42, *chunk))), "oem"))
            stores.append(Store(method, 0x42, position, chunk))
        elif method in GOC:
            steps.append((_write(0xFF, bytes((tag, *position.to_bytes(2, "big"), *chunk))),
                          "direct"))
            stores.append(Store(method, tag, position, chunk))
        else:
            if locked:
                steps.append((bytes((0x11, position)), "direct"))
                unlocks.append((None, position))
            steps.append((_write(position, bytes((tag, *chunk))), "direct"))
            stores.append(Store(method, tag, position, chunk))
    if method == "giu":
        steps.append((_write(0xFC, b"\x03\x01"), "oem"))
    steps.extend(read_steps(method, address, len(data)))
    return steps, stores, unlocks


IDENTIFY = [(b"\x21\x01", "direct"), (b"\x21\x02", "direct")]
NVM_EXECUTE = b"\xE3\x81\x00\x04"
NVM_POLL = b"\xE3\x82\x00\x04"


def expected_transcript(route, parameters, edits, *, nvm_spec=False, nvm_running=False,
                        written=None):
    """Complete LOAD, one SAVE_TO_SOURCE and fresh LOAD request sequence.

    ``parameters`` is the declared schema: ``(name, method, address, size,
    protection)``.  ``edits`` maps names to ``(before, after)`` bytes.
    ``written`` selects which edited names reach the unit; by default every
    changed non-factory/special field does.
    """
    plan = Plan()
    load = []
    for _, method, address, size, _ in sorted(parameters,
                                              key=lambda row: (LOAD_ORDER[row[1]], row[2])):
        load.extend(read_steps(method, address, size))
    save = list(IDENTIFY)
    pending = []
    for name, method, address, size, protection in parameters:
        if name not in edits:
            continue
        before, after = edits[name]
        writable = protection not in ("factory", "special") if written is None else name in written
        if writable:
            pending.append((name, method, address, size, protection, before, after))
    for _, method, address, size, *_ in sorted(pending,
                                               key=lambda row: (SPACE_ORDER[row[1]], row[2])):
        save.extend(read_steps(method, address, size))
    wrote = False
    for name, method, address, size, protection, before, after in pending:
        if before == after:
            continue
        if plan.first_store_index is None:
            plan.first_store_index = len(IDENTIFY) + len(load) + len(save)
        steps, stores, unlocks = store_steps(method, address, after, locked=protection == "lock")
        save.extend(steps)
        plan.stores.extend(stores)
        plan.unlocks.extend(unlocks)
        wrote = True
    if wrote and nvm_spec:
        save.append((NVM_EXECUTE, "direct"))
        plan.nvm.append("execute")
        if nvm_running:
            save.append((NVM_POLL, "direct"))
            plan.nvm.append("poll")
    sequence = [*IDENTIFY, *load, *save, *IDENTIFY, *load]
    plan.wires = [request_wire(route, cal, envelope) for cal, envelope in sequence]
    return plan


# --------------------------------------------------------------------------
# Independent scripted PCI peer
# --------------------------------------------------------------------------

class ProgrammingPCI(PCISimulator):
    """Stateful peer for the exact PP wire contract over one route."""

    def __init__(self, route, layout, memory, *, drop_after_store=None, nvm_running=False,
                 fragment=None, overflow_on_first_recall=False):
        super().__init__(profile="captured", command_checksum=True)
        self.route = tuple(route)
        # layout: (method, first physical/logical address, end) per parameter
        self.layout = list(layout)
        self.memory = {space: dict(values) for space, values in memory.items()}
        self.selected_page = None
        self.oem_pointer = None
        self.goc_pointer = None
        self.giu_running = True
        self.requests = []
        self.stores = []
        self.unlocks = []
        self.run_flags = []
        self.nvm = []
        self.noise_frames = 0
        self.drop_after_store = drop_after_store
        self.dropped = False
        self.dropped_at = None
        self.nvm_running = nvm_running
        self.fragment = fragment or {}
        self.overflow_on_first_recall = overflow_on_first_recall
        self.overflow_sent = False
        self._peer_lock = threading.Lock()

    def _connection(self, conn, connection, shutdown):
        try:
            super()._connection(conn, connection, shutdown)
        except _DropConnection:
            # Returning closes the TCP stream: the daemon must classify the
            # in-flight mutation as uncertain and never replay it.
            return

    def _method(self, space, address):
        for method, start, end in self.layout:
            if start <= address < end and (
                    (space == "standard" and method not in PAGED + OEM + GOC)
                    or (space == "paged" and method in PAGED)
                    or (space == "oem" and method in OEM)
                    or (space == "goc" and method in GOC)):
                return method
        raise AssertionError(f"no {space} parameter covers 0x{address:X}")

    def _standard(self, parameter):
        return any(start <= parameter < end for method, start, end in self.layout
                   if method not in PAGED + OEM + GOC)

    def _frames(self, cals, stale, envelope):
        # Every accepted exchange first sees three complete distractions:
        # another route, the wrong terminal unit and a stale parameter/tag.
        wrong_route = ((self.route[0] - 1, *self.route[1:]) if self.route else (0xFD,))
        frames = (reply_frame(wrong_route, cals[0], envelope=envelope)
                  + reply_frame(self.route, cals[0], unit=UNIT + 1, envelope=envelope)
                  + reply_frame(self.route, stale, envelope=envelope))
        self.noise_frames += 3
        return frames + b"".join(reply_frame(self.route, cal, envelope=envelope) for cal in cals)

    def _parse(self, line):
        code = b""
        if line and ord("g") <= line[-1] <= ord("z"):
            code, line = line[-1:], line[:-1]
        if not line.startswith(b"\\"):
            raise AssertionError(f"unexpected PCI command {line!r}")
        raw = bytes.fromhex(line[1:].decode("ascii"))
        if self.route:
            header = bytes((0x46, self.route[0], 9 * len(self.route), *self.route[1:], UNIT))
            if not raw.startswith(header) or sum(raw) & 0xFF:
                raise AssertionError(f"routed command lacks route or checksum: {raw.hex()}")
            envelope, cal = "routed", raw[len(header):-1]
        elif raw[:4] == bytes((0x46, UNIT, 0x09, 0x00)):
            if sum(raw) & 0xFF:
                raise AssertionError(f"OEM command lacks its checksum: {raw.hex()}")
            envelope, cal = "oem", raw[4:-1]
        elif raw[:3] == bytes((0x46, UNIT, 0x00)):
            envelope = "direct"
            if raw[3] in UNCHECKSUMMED_LOCAL:
                cal = raw[3:]
            elif sum(raw) & 0xFF:
                raise AssertionError(f"direct command lacks its checksum: {raw.hex()}")
            else:
                cal = raw[3:-1]
        else:
            raise AssertionError(f"unexpected local target: {raw.hex()}")
        with self._peer_lock:
            self.requests.append({
                "wire_hex": _hex(raw),
                "cal_hex": _hex(cal),
                "envelope": envelope,
                "confirmation": code.decode("ascii") if code else None,
                "time": time.monotonic(),
            })
        return code, cal, "oem" if envelope == "oem" else "direct"

    def read(self, space, address, count):
        try:
            return bytes(self.memory[space][address + index] for index in range(count))
        except KeyError as error:
            raise AssertionError(f"{space} read beyond fixture at {error}") from None

    def _answer(self, code, cals, stale, envelope):
        return (code + b"." if code else b"") + self._frames(cals, stale, envelope), None

    def _fragments(self, method, parameter, data, advancing):
        size = self.fragment.get(method)
        if not size or len(data) <= size:
            return [_reply(parameter, data)]
        return [_reply((parameter + offset) & 0xFF if advancing else parameter,
                       data[offset:offset + size])
                for offset in range(0, len(data), size)]

    def _record_store(self, method, tag, address, data):
        with self._peer_lock:
            self.stores.append({
                "method": method, "tag": tag, "address": address, "data": bytes(data),
                "giu_running": self.giu_running, "time": time.monotonic(),
            })
        if self.drop_after_store == method and not self.dropped:
            self.dropped = True
            self.dropped_at = time.monotonic()
            raise _DropConnection()

    def _command(self, line, context):
        if line in (b"~", b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"):
            return b"", None
        code, cal, envelope = self._parse(line)
        opcode = cal[0]

        if opcode == 0x21:
            if len(cal) != 2 or cal[1] not in (1, 2):
                raise AssertionError(f"unexpected IDENTIFY {cal.hex()}")
            data = b"PPTEST" if cal[1] == 1 else b"1.0.00"
            return self._answer(code, [_reply(cal[1], data)], _reply(cal[1] ^ 3, data), envelope)

        if opcode == 0x1A:
            if len(cal) != 3 or cal[2] == 0:
                raise AssertionError(f"unexpected RECALL {cal.hex()}")
            parameter, count = cal[1:]
            if parameter == 0x01 and self.oem_pointer is not None and not self._standard(1):
                method = self._method("oem", self.oem_pointer)
                data = self.read("oem", self.oem_pointer, count)
                self.oem_pointer += count
                cals = self._fragments(method, parameter, data, advancing=False)
            elif parameter == 0xFF and self.goc_pointer is not None:
                method = self._method("goc", self.goc_pointer)
                data = self.read("goc", self.goc_pointer, count)
                self.goc_pointer += count
                cals = self._fragments(method, parameter, data, advancing=False)
            else:
                method = self._method("standard", parameter)
                data = self.read("standard", parameter, count)
                cals = [_reply(parameter, data)]
            if self.overflow_on_first_recall and not self.overflow_sent:
                # A complete correlated first byte, then an excess reply.
                self.overflow_sent = True
                cals = [_reply(parameter, data[:1]), _reply(parameter, data)]
            return self._answer(code, cals, _reply((parameter + 1) & 0xFF, data), envelope)

        if opcode == 0x1B:
            if len(cal) != 4 or cal[3] == 0:
                raise AssertionError(f"unexpected paged RECALL {cal.hex()}")
            page, parameter, count = cal[1:]
            if parameter + count > 256:
                raise AssertionError(f"paged RECALL crosses a page: {cal.hex()}")
            address = page * 256 + parameter
            method = self._method("paged", address)
            data = self.read("paged", address, count)
            cals = self._fragments(method, parameter, data, advancing=True)
            return self._answer(code, cals, _reply((parameter + 1) & 0xFF, data), envelope)

        if opcode == 0x39:
            if len(cal) != 2:
                raise AssertionError(f"unexpected SET_PAGE {cal.hex()}")
            self.selected_page = cal[1]
            return self._answer(code, [_reply(cal[1], b"")], _reply((cal[1] + 1) & 0xFF, b""),
                                envelope)

        if opcode == 0x11:
            if len(cal) != 2:
                raise AssertionError(f"unexpected UNLOCK {cal.hex()}")
            parameter = cal[1]
            page = None if self._standard(parameter) else self.selected_page
            with self._peer_lock:
                self.unlocks.append((page, parameter))
            return self._answer(code, [_reply(parameter, b"\x5A")],
                                _reply((parameter + 1) & 0xFF, b"\x5A"), envelope)

        if opcode == 0xE3 and len(cal) == 4 and cal[2:] == b"\x00\x04" and cal[1] in (0x81, 0x82):
            execute = cal[1] == 0x81
            with self._peer_lock:
                self.nvm.append("execute" if execute else "poll")
            status = 1 if execute and self.nvm_running else 0
            return self._answer(code, [bytes((0xE4, 0x83, 0, 4, status))],
                                bytes((0xE4, 0x83, 0, 5, status)), envelope)

        if opcode & 0xE0 == 0xA0:
            declared = opcode & 0x1F
            if declared < 2 or len(cal) != declared + 1:
                raise AssertionError(f"malformed WRITE {cal.hex()}")
            parameter, data = cal[1], cal[2:]
            tag = data[0]
            if parameter == 0 and tag == 0x41 and len(data) in (3, 5):
                self.oem_pointer = int.from_bytes(data[1:], "little")
            elif parameter == 1 and tag == 0x42 and self.oem_pointer is not None:
                method = self._method("oem", self.oem_pointer)
                address = self.oem_pointer
                for offset, value in enumerate(data[1:]):
                    self.memory["oem"][address + offset] = value
                self.oem_pointer += len(data) - 1
                self._record_store(method, tag, address, data[1:])
            elif parameter == 0xFC and data in (b"\x03\x00", b"\x03\x01"):
                self.giu_running = data == b"\x03\x01"
                with self._peer_lock:
                    self.run_flags.append((data[1], time.monotonic()))
            elif parameter == 0xFF and tag == 0x42 and len(data) == 3:
                self.goc_pointer = int.from_bytes(data[1:], "big")
            elif parameter == 0xFF and len(data) >= 4:
                address = int.from_bytes(data[1:3], "big")
                method = self._method("goc", address)
                for offset, value in enumerate(data[3:]):
                    self.memory["goc"][address + offset] = value
                self._record_store(method, tag, address, data[3:])
            elif self._standard(parameter):
                method = self._method("standard", parameter)
                for offset, value in enumerate(data[1:]):
                    self.memory["standard"][parameter + offset] = value
                self._record_store(method, tag, parameter, data[1:])
            elif self.selected_page is not None:
                address = self.selected_page * 256 + parameter
                method = self._method("paged", address)
                for offset, value in enumerate(data[1:]):
                    self.memory["paged"][address + offset] = value
                self._record_store(method, tag, address, data[1:])
            else:
                raise AssertionError(f"unclassified WRITE {cal.hex()}")
            return self._answer(code, [bytes((0x32, parameter, tag))],
                                bytes((0x32, parameter, tag ^ 0xFF)), envelope)

        raise AssertionError(f"unsupported CAL {cal.hex()}")


# --------------------------------------------------------------------------
# Fixture files and process control
# --------------------------------------------------------------------------

@dataclass
class Param:
    name: str
    method: str
    address: int
    size: int
    protection: str = "none"
    kind: str = "int"
    bit_address: int = 0
    before: bytes = b""

    @property
    def row(self):
        return (self.name, self.method, self.address, self.size, self.protection)

    @property
    def space(self):
        return ("paged" if self.method in PAGED else "oem" if self.method in OEM
                else "goc" if self.method in GOC else "standard")


def pattern(size, base, step):
    return bytes((base + step * index) & 0xFF for index in range(size))


def write_project(path, route):
    target_network = route[-1] if route else 254
    networks = ['<Network oid="n254"><TagName>Local</TagName><Address>254</Address>'
                '<Interface><InterfaceType>CNI</InterfaceType>'
                '<InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>'
                '<Unit oid="pci"><Address>16</Address><UnitType>PC_CNI2</UnitType></Unit>']
    target = ('<Unit oid="target"><Address>5</Address><UnitType>PPTEST</UnitType>'
              '<FirmwareVersion>1.0.00</FirmwareVersion></Unit>')
    parent = 254
    for bridge in route:
        networks[-1] += (f'<Unit oid="b{bridge}"><Address>{bridge}</Address>'
                         '<UnitType>BRIDGE2N</UnitType></Unit></Network>')
        networks.append(f'<Network oid="n{bridge}"><TagName>Net{bridge}</TagName>'
                        f'<Address>{bridge}</Address><Interface><InterfaceType>Bridge'
                        f'</InterfaceType><InterfaceAddress>{parent}/p/{bridge}'
                        '</InterfaceAddress></Interface>')
        parent = bridge
    networks[-1] += target + "</Network>"
    path.write_text('<Installation><Project oid="project"><TagName>TEST</TagName>'
                    + "".join(networks) + "</Project></Installation>", encoding="utf-8")
    return f"//TEST/{target_network}/p/{UNIT}"


def write_spec(directory, params):
    rows = []
    for param in params:
        array = 1 if param.kind == "bit" else param.size
        bit = f"<BitAddress>{param.bit_address}</BitAddress>" if param.kind == "bit" else ""
        rows.append(f"<Param><Name>{param.name}</Name><Type>{param.kind}</Type>"
                    f"<Address>${param.address:X}</Address><ArraySize>{array}</ArraySize>{bit}"
                    f"<ProgramMethod>{param.method}</ProgramMethod>"
                    f"<Protection>{param.protection}</Protection></Param>")
    (directory / "PPTEST.xml").write_text(
        f"<UnitSpecification><Parameters>{''.join(rows)}</Parameters></UnitSpecification>",
        encoding="utf-8")


def peer_state(params):
    memory = {"standard": {}, "paged": {}, "oem": {}, "goc": {}}
    layout = []
    for param in params:
        start = physical(param.method, param.address)
        width = 1 if param.kind == "bit" else param.size
        layout.append((param.method, start, start + width))
        for offset, value in enumerate(param.before):
            memory[param.space][start + offset] = value
    return layout, memory


@contextmanager
def running_daemon(tmp_path, pci, project, specs):
    with socket.socket() as broker:
        broker.bind(("127.0.0.1", 0))
        broker.listen(1)
        log_path = tmp_path / "programming-methods-daemon.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen([
                str(BIN), "--tcp", f"{pci[0]}:{pci[1]}",
                "--broker-address", "127.0.0.1",
                "--broker-port", str(broker.getsockname()[1]),
                "--broker-disable-tls", "--timesync", "0", "--status-resync", "0",
                "--project-file", str(project), "--cgate-bind", "127.0.0.1:0",
                "--cgate-state", str(tmp_path / "state.json"),
                "--cgate-unitspec", str(specs),
            ], stdout=subprocess.DEVNULL, stderr=log)
            try:
                deadline = time.monotonic() + 20
                port = None
                output = ""
                while time.monotonic() < deadline:
                    log.seek(0)
                    output = log.read()
                    match = re.search(r"C-Gate service listening on 127\.0\.0\.1:(\d+)", output)
                    if match:
                        port = match[1]
                        break
                    assert process.poll() is None, output
                    time.sleep(0.02)
                assert port is not None, output
                yield port
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def value_text(param, value):
    if param.kind == "bit":
        return str(value)
    return " ".join(f"0x{byte:02X}" for byte in value)


def invoke(port, target, method, edits, *, timeout=180):
    command = [
        sys.executable, "-m", "cbus_toolkit", "cgate",
        "--host", "127.0.0.1", "--port", str(port), "--timeout", "45",
        "physical-pp", "apply", target, "--method", method,
    ]
    for name, text in edits:
        command += ["--set", name, text]
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


@dataclass
class Run:
    result: subprocess.CompletedProcess
    peer: ProgrammingPCI
    target: str

    @property
    def document(self):
        return json.loads(self.result.stdout if self.result.returncode == 0 else self.result.stderr)


def run_apply(tmp_path, route, params, edits, *, method=None, **peer_options):
    """Program ``edits`` ({name: text}) through the real CLI and daemon."""
    specs = tmp_path / "unitspec"
    specs.mkdir()
    project = tmp_path / "project.xml"
    target = write_project(project, route)
    write_spec(specs, params)
    layout, memory = peer_state(params)
    peer = ProgrammingPCI(route, layout, memory, **peer_options)
    selected = method or next(param.method for param in params if param.name in edits)
    with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
        result = invoke(port, target, selected, list(edits.items()))
    return Run(result, peer, target)


def numbers(values):
    """Spelling-independent numeric view of PP GET values."""
    return {name: [int(item, 0) for item in text.split()] for name, text in values.items()}


def assert_complete(run, method):
    assert run.result.returncode == 0, run.result.stderr
    value = run.document
    assert value["complete"]
    assert value["method"] == method
    assert value["save_attempts"] == 1
    assert value["automatic_write_retries"] == 0
    assert value["staged_readback_verified"]
    assert value["fresh_physical_readback_verified"]
    assert numbers(value["verified"]) == numbers(value["staged"])
    assert not value["power_cycle_persistence_verified"]
    assert not value["hardware_method_matrix_accepted"]
    return value


def assert_exchange_shape(run, plan):
    peer = run.peer
    assert [row["wire_hex"] for row in peer.requests] == plan.wires
    for row in peer.requests:
        if row["cal_hex"].startswith(("21", "11")):
            assert row["confirmation"] is not None, row
    assert [(row["method"], row["tag"], row["address"], row["data"]) for row in peer.stores] == [
        (store.method, store.tag, store.address, bytes(store.data)) for store in plan.stores]
    assert peer.unlocks == plan.unlocks
    assert peer.nvm == plan.nvm
    assert len({row["connection"] for row in peer.wire_log}) == 1


def method_case(method, size, *, protection="none", address=None):
    address = ADDRESSES[method] if address is None else address
    before = pattern(size, 0x10, 3)
    after = pattern(size, 0xA0, 5)
    return Param(method, method, address, size, protection, before=before), after


def assert_method_semantics(run, method, plan):
    peer = run.peer
    if method == "giu":
        # bm: halt (FC 03 00) before the first GIU STORE and resume after
        # the last one; every STORE happened while halted.
        assert [flag for flag, _ in peer.run_flags] == [0, 1]
        halted, resumed = (moment for _, moment in peer.run_flags)
        assert all(not row["giu_running"] and halted <= row["time"] <= resumed
                   for row in peer.stores)
        assert peer.giu_running
    else:
        assert not peer.run_flags
    if method == "dali":
        # lP save case 6 sleeps one second before the first DALI STORE; the
        # preceding request is the last SAVE pre-read recall.
        index = plan.first_store_index
        gap = peer.requests[index]["time"] - peer.requests[index - 1]["time"]
        assert gap >= 1.0, gap


def test_expected_limits_match_retained_native_method_evidence():
    fixture = json.loads((ROOT / "rust/testdata/fixtures/native_cgate_routed_pp_methods.json")
                         .read_text(encoding="utf-8"))["native_method_limits"]
    assert STORE_LIMIT == fixture["store_group_bytes"]
    assert RECALL_LIMIT == {**fixture["recall_request_bytes"],
                            "edlt": fixture["cmqttd_edlt_recall_block"]}
    assert fixture["protection_classes"]["factory_bit"] == 14


ROUTE_CASES = [
    *(pytest.param(method, "local", 2, id=f"{method}-local") for method in METHODS),
    *(pytest.param(method, "one-bridge", 2, id=f"{method}-one-bridge") for method in METHODS),
    *(pytest.param(method, "one-bridge", MULTI[method][1], id=f"{method}-one-bridge-multi")
      for method in METHODS),
    *(pytest.param(method, "six-bridges", MULTI[method][1], id=f"{method}-six-bridges-multi")
      for method in SIX_BRIDGE_METHODS),
]


@needs_cmqttd
@pytest.mark.parametrize("method,route_name,size", ROUTE_CASES)
def test_exact_method_transcript_chunks_and_fresh_readback(tmp_path, method, route_name, size):
    route = ROUTES[route_name]
    address = MULTI[method][0] if size > 2 else ADDRESSES[method]
    param, after = method_case(method, size, address=address)
    nvm_spec = method == "ncc"
    run = run_apply(tmp_path, route, [param], {param.name: value_text(param, after)},
                    nvm_running=nvm_spec,
                    # Native L names each paged fragment by its first byte;
                    # bj repeats parameter 1 in every eDLT fragment.
                    fragment={"ncc": 8, "edlt": 16})
    value = assert_complete(run, method)
    assert value["parameters"][0]["protection"] == "none"
    plan = expected_transcript(route, [param.row], {param.name: (param.before, after)},
                               nvm_spec=nvm_spec, nvm_running=nvm_spec)
    assert_exchange_shape(run, plan)
    assert_method_semantics(run, method, plan)
    start = physical(method, address)
    assert run.peer.read(param.space, start, size) == after
    stores = run.peer.stores
    if size > 2:
        # Chunk sizes, offsets and tags independently of the plan builder.
        assert [len(row["data"]) for row in stores] == list(MULTI_CHUNKS[method])
        offsets = [0, *(sum(MULTI_CHUNKS[method][:index])
                        for index in range(1, len(MULTI_CHUNKS[method])))]
        assert [row["address"] for row in stores] == [start + offset for offset in offsets]
        assert [row["tag"] for row in stores] == ([0x42] * 3 if method in OEM else [0, 1, 2])
    assert run.peer.noise_frames == 3 * len(run.peer.requests)


@needs_cmqttd
def test_real_cli_programs_all_ten_methods_through_one_routed_session(tmp_path):
    """All methods share one daemon, route and PCI connection."""
    params, expected = [], {}
    for index, method in enumerate(METHODS):
        param = Param(method, method, ADDRESSES[method], 2,
                      before=bytes((0x10 + index, 0x11 + index)))
        params.append(param)
        expected[method] = bytes((0xB0 + index, 0xC0 + index))
    route = ROUTES["one-bridge"]
    specs = tmp_path / "unitspec"
    specs.mkdir()
    project = tmp_path / "project.xml"
    target = write_project(project, route)
    write_spec(specs, params)
    layout, memory = peer_state(params)
    peer = ProgrammingPCI(route, layout, memory)
    with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
        for param in params:
            result = invoke(port, target, param.method,
                            [(param.name, value_text(param, expected[param.method]))])
            assert result.returncode == 0, (param.method, result.stderr)
            value = json.loads(result.stdout)
            assert value["method"] == param.method and value["complete"]
            assert value["fresh_physical_readback_verified"]
    for param in params:
        assert peer.read(param.space, physical(param.method, param.address), 2) == \
            expected[param.method]
    assert {row["method"] for row in peer.stores} == set(METHODS)
    # The specification declares NCC, so every confirmed change is committed.
    assert peer.nvm == ["execute"] * len(METHODS)
    assert len({row["connection"] for row in peer.wire_log}) == 1


@needs_cmqttd
def test_routed_programming_rejects_excess_correlated_readback_before_any_save(tmp_path):
    param, after = method_case("direct", 2)
    run = run_apply(tmp_path, ROUTES["one-bridge"], [param],
                    {param.name: value_text(param, after)}, overflow_on_first_recall=True)
    assert run.result.returncode == 1
    evidence = run.document["physical_programming_evidence"]
    assert evidence["phase"].startswith("physical-load")
    assert not evidence["save_attempted"]
    assert not run.peer.stores
    assert run.peer.overflow_sent


DISCONNECT_CASES = [
    pytest.param("direct", "one-bridge", 2, id="direct"),
    pytest.param("paged", "one-bridge", MULTI["paged"][1], id="paged-multi"),
    pytest.param("ncc", "local", MULTI["ncc"][1], id="ncc-local-multi"),
    pytest.param("giu", "one-bridge", MULTI["giu"][1], id="giu-multi"),
    pytest.param("edlt", "local", MULTI["edlt"][1], id="edlt-local-multi"),
    pytest.param("gocbyt", "six-bridges", MULTI["gocbyt"][1], id="gocbyt-six-bridges-multi"),
    pytest.param("goc2", "one-bridge", MULTI["goc2"][1], id="goc2-multi"),
]


@needs_cmqttd
@pytest.mark.parametrize("method,route_name,size", DISCONNECT_CASES)
def test_disconnect_after_first_store_is_uncertain_and_never_replayed(
        tmp_path, method, route_name, size):
    address = MULTI[method][0] if size > 2 else ADDRESSES[method]
    param, after = method_case(method, size, address=address)
    run = run_apply(tmp_path, ROUTES[route_name], [param],
                    {param.name: value_text(param, after)}, drop_after_store=method)
    assert run.result.returncode == 1
    evidence = run.document["physical_programming_evidence"]
    assert evidence["save_attempts"] == 1
    assert evidence["save_attempted"]
    assert evidence["save_outcome_uncertain"]
    assert not evidence["saved"]
    assert run.peer.dropped
    # Exactly the first native group reached the unit; no later chunk,
    # repeated STORE, NVM commit or GIU resume followed the lost stream.
    plan = expected_transcript(ROUTES[route_name], [param.row],
                               {param.name: (param.before, after)}, nvm_spec=method == "ncc")
    first = plan.stores[0]
    assert [(row["method"], row["tag"], row["address"], row["data"])
            for row in run.peer.stores] == [(first.method, first.tag, first.address,
                                             bytes(first.data))]
    assert not run.peer.nvm
    if method == "giu":
        assert [flag for flag, _ in run.peer.run_flags] == [0]
    # Everything up to the lost STORE followed the derived transcript.
    sent = [row for row in run.peer.requests if row["time"] <= run.peer.dropped_at]
    assert [row["wire_hex"] for row in sent] == plan.wires[:len(sent)]
    assert int(sent[-1]["cal_hex"][:2], 16) & 0xE0 == 0xA0
    later = [row["cal_hex"] for row in run.peer.requests if row["time"] > run.peer.dropped_at]
    assert not [cal for cal in later
                if int(cal[:2], 16) & 0xE0 == 0xA0 or cal[:2] in ("11", "39", "E3")], later


# --------------------------------------------------------------------------
# Protection matrix (P4.02)
# --------------------------------------------------------------------------

MATRIX_PATH = ROOT / "toolkit-cli/docs/pp-protection-matrix.json"
MATRIX = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
ADMITTED = tuple(pair["id"] for pair in MATRIX["admitted_pairs"])
# Type=bit factory fields are native class 14 and are written; every other
# factory field and every special field is skipped by PP SAVE.
FACTORY_BIT_PAIRS = tuple(
    pair["id"] for pair in MATRIX["admitted_pairs"]
    if pair["protection"] == "factory" and pair["types"].get("bit"))


def test_committed_protection_matrix_is_bound_to_the_interop_cases():
    assert MATRIX["format"] == "cbus-pp-protection-matrix-v1"
    assert MATRIX["methods_without_declarations"] == ["goc"]
    assert set(ADMITTED) == {
        "direct/none", "direct/checksum", "direct/lock", "direct/factory", "direct/special",
        "paged/none", "paged/checksum", "paged/lock", "paged/factory",
        "ncc/checksum", "ncc/factory", "edlt/none", "giu/none", "sgiu/none",
        "sgiu/factory", "dali/none", "gocbyt/none", "goc2/none", "goc2/factory"}
    assert FACTORY_BIT_PAIRS == ("direct/factory", "paged/factory")
    for pair in MATRIX["admitted_pairs"]:
        assert pair["declarations"] == sum(pair["types"].values()) > 0
        assert pair["specification_files"] == len(pair["sources"])
        assert set(pair["sources"]) <= set(MATRIX["input"]["file_sha256"])
    # No specification text beyond names, counts and digests is retained.
    assert set(MATRIX["admitted_pairs"][0]) == {
        "id", "method", "protection", "declarations", "specification_files", "types",
        "sources", "native_save_contract"}


@pytest.mark.skipif(not os.environ.get("CBUS_UNITSPEC_DIR"),
                    reason="Set CBUS_UNITSPEC_DIR to re-derive the matrix from decoded specs")
def test_protection_matrix_matches_a_fresh_derivation():
    sys.path.insert(0, str(ROOT / "toolkit-cli"))
    try:
        from research.derive_pp_protection_matrix import derive
    finally:
        sys.path.pop(0)
    assert derive(Path(os.environ["CBUS_UNITSPEC_DIR"])) == MATRIX


def protection_case(pair, *, bit=False):
    method, protection = pair.split("/")
    if bit:
        address = {"direct": 0x21, "paged": 0x1FE}[method]
        param = Param(method, method, address, 1, protection, kind="bit", bit_address=3,
                      before=b"\x00")
        return param, b"\x08", "1"
    # Lock-protected fields use the multi-group layout so every native group
    # shows its own UNLOCK; the others use the two-byte layout.
    size = MULTI[method][1] if protection == "lock" else 2
    address = MULTI[method][0] if protection == "lock" else ADDRESSES[method]
    param, after = method_case(method, size, protection=protection, address=address)
    return param, after, value_text(param, after)


PROTECTION_CASES = [
    *(pytest.param(pair, route_name, False, id=f"{pair}-{route_name}")
      for pair in ADMITTED for route_name in ("local", "one-bridge")),
    *(pytest.param(pair, route_name, True, id=f"{pair}-bit-{route_name}")
      for pair in FACTORY_BIT_PAIRS for route_name in ("local", "one-bridge")),
]


@needs_cmqttd
@pytest.mark.parametrize("pair,route_name,bit", PROTECTION_CASES)
def test_admitted_method_protection_pair(tmp_path, pair, route_name, bit):
    method, protection = pair.split("/")
    route = ROUTES[route_name]
    param, after, text = protection_case(pair, bit=bit)
    skipped = protection in ("factory", "special") and not bit
    nvm_spec = method == "ncc"
    run = run_apply(tmp_path, route, [param], {param.name: text}, nvm_running=nvm_spec)
    plan = expected_transcript(route, [param.row], {param.name: (param.before, after)},
                               nvm_spec=nvm_spec, nvm_running=nvm_spec,
                               written=set() if skipped else {param.name})
    assert_exchange_shape(run, plan)
    start = physical(method, param.address)
    if skipped:
        # Native lP skips the field; the confirmed SAVE leaves the unit
        # unchanged and the CLI's fresh reload reports the difference.
        assert run.result.returncode == 1
        evidence = run.document["physical_programming_evidence"]
        assert evidence["saved"] and not evidence["save_outcome_uncertain"]
        assert evidence["phase"] == "fresh-physical-verification"
        assert not evidence["fresh_physical_readback_verified"]
        assert set(evidence["verification_mismatches"]) == {param.name}
        assert not run.peer.stores and not run.peer.nvm
        assert run.peer.read(param.space, start, param.size) == param.before
        return
    value = assert_complete(run, method)
    assert value["parameters"][0]["protection"] == protection
    assert run.peer.read(param.space, start, param.size) == after
    if protection == "lock":
        assert len(run.peer.unlocks) == len(run.peer.stores) == 3
    else:
        assert not run.peer.unlocks


@needs_cmqttd
@pytest.mark.parametrize("pair", ("direct/none", "paged/lock", "ncc/checksum", "giu/none",
                                  "goc2/none"))
def test_unchanged_range_is_read_but_never_stored_or_committed(tmp_path, pair):
    method, protection = pair.split("/")
    param, _ = method_case(method, 2, protection=protection)
    run = run_apply(tmp_path, ROUTES["one-bridge"], [param],
                    {param.name: value_text(param, param.before)},
                    nvm_running=method == "ncc")
    assert_complete(run, method)
    plan = expected_transcript(ROUTES["one-bridge"], [param.row],
                               {param.name: (param.before, param.before)},
                               nvm_spec=method == "ncc", nvm_running=method == "ncc")
    assert_exchange_shape(run, plan)
    assert not run.peer.stores and not run.peer.unlocks and not run.peer.nvm
    assert not run.peer.run_flags


@needs_cmqttd
@pytest.mark.parametrize("route_name", ("local", "one-bridge"))
def test_ncc_specification_commits_nvm_after_any_confirmed_change(tmp_path, route_name):
    """NVM EXECUTE is gated on the unit-wide NCC family, not the edited method."""
    route = ROUTES[route_name]
    direct, after = method_case("direct", 2, protection="checksum")
    ncc = Param("ncc", "ncc", ADDRESSES["ncc"], 2, "checksum", before=b"\x33\x44")
    run = run_apply(tmp_path, route, [direct, ncc], {direct.name: value_text(direct, after)},
                    method="direct", nvm_running=True)
    assert_complete(run, "direct")
    plan = expected_transcript(route, [direct.row, ncc.row],
                               {direct.name: (direct.before, after)},
                               nvm_spec=True, nvm_running=True)
    assert_exchange_shape(run, plan)
    assert run.peer.nvm == ["execute", "poll"]
    assert [row["method"] for row in run.peer.stores] == ["direct"]
    assert run.peer.read("paged", 0x300, 2) == b"\x33\x44"
