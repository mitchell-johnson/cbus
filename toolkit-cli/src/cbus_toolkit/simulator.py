"""Deterministic, bounded PCI test simulator with an independent wire codec.

Implemented: SMART/CONNECT shortcut, local BASIC discovery, IDENTIFY,
read-only CAL chains, install MMI and single-CAL WRITE/ACK exchanges.
The default raw profile stores explicitly configured blocks (RECALL1..30).
Captured and synthetic profiles additionally implement sparse OEM address
selection, memory READ/WRITE and segmented RECALL1..255. Synthetic SIMTEST
adds schema-encoded names, chosen terminal levels, timed lighting control and
dynamic lighting MMI.
Explicit sparse legacy memory supports native PP field transfers; synthetic
SAL labels persist independently. Full EEPROM checksum/protection behavior,
bridges and flash are not emulated.
Unknown units, attributes, blocks, routes, and commands are rejected. There
are no synthetic success responses, automatically provisioned units, or
invented memory/register meanings. This module deliberately does not import
``pci``: client and peer must not share a potentially faulty codec.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import time

from .simulator_labels import LabelPacketError, LabelState
from .simulator_applications import ApplicationPacketError, TriggerState
from .simulator_enable import EnablePacketError, EnableState
from .lighting_state import LightingPacketError, LightingState, RAMP_SECONDS
from . import simulator_addressing, simulator_serial_addressing


def _byte(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer in 0..255")
    return value


def _blocks(value, name):
    result = {}
    for key, data in value.items():
        _byte(key, name)
        if not isinstance(data, (bytes, bytearray)) or len(data) > 30:
            raise ValueError(f"{name} values must contain 0..30 bytes")
        result[key] = bytes(data)
    return result


@dataclass
class UnitState:
    """Explicit simulated blocks and fixture ACK tags for writable parameters.

    A WRITE replaces exactly one configured block. RECALL reads a requested
    prefix of that block. ``write_tags`` also acts as the writable allowlist;
    ACK tags are supplied by the fixture, never inferred from unknown data.
    """
    address: int
    attributes: dict[int, bytes] = field(default_factory=dict)
    parameters: dict[int, bytes] = field(default_factory=dict)
    write_tags: dict[int, int] = field(default_factory=dict)
    mmi_state: int = 1

    def __post_init__(self):
        _byte(self.address, "unit address")
        if isinstance(self.mmi_state, bool) or not isinstance(self.mmi_state, int) or not 0 <= self.mmi_state <= 3:
            raise ValueError("MMI state must be in 0..3")
        self.attributes = _blocks(self.attributes, "attribute")
        self.parameters = _blocks(self.parameters, "parameter")
        self.write_tags = dict(self.write_tags)
        for parameter, tag in self.write_tags.items():
            _byte(parameter, "write parameter")
            _byte(tag, "ACK tag")
            if parameter not in self.parameters:
                raise ValueError("Writable parameters must have an explicit initial block")


def default_units() -> list[UnitState]:
    """Small fixture network; coverage is limited to the configured blocks."""
    return [
        UnitState(4, {1: b"KEYE1   ", 2: b"2.5.00  ", 4: bytes.fromhex("38FFFFFFFF18B10616A20005")},
                  {0x30: b"\x03", 0x21: bytes.fromhex("38FF9B192D8229E4FF42682D"),
                   0x36: bytes.fromhex("010204081020408020590103"),
                   0x45: bytes.fromhex("0000FF0F0F0F0F0F0F0F0F0C"),
                   0x50: bytes.fromhex("0CFFFFFFFFFFFFFFFFFFFFFF")}, mmi_state=2),
        UnitState(5, {1: b"KEYGL5  ", 2: b"5.5.00  ",
                       4: bytes.fromhex("FFFFFF000018B3F682A40001"), 0x10: bytes.fromhex("800000FF")},
                  {0: b"\x41\x00\x00", 1: b"\x42\x00", 0x21: bytes.fromhex("FFFF9B192D8229E4FF923AF3")},
                  {0: 0x41, 1: 0x42, 0x21: 0}, mmi_state=2),
        UnitState(16, {1: b"PC_CNIED", 2: b"5.5.00  ",
                       4: bytes.fromhex("FFFFFF000018A664A3B10005"),
                       0x10: bytes.fromhex("030000FF")},
                  {0x20: b"\x10", 0x21: bytes.fromhex("FFFF9B192D8229E4FFB64CF6"),
                   0x23: bytes.fromhex("9B192D8229E4"), 0x2A: bytes.fromhex("B64CF6BB1A9E"),
                   0x30: b"\x55", 0x42: b"\x07", 0xF2: b"\xff"}),
    ]


def synthetic_units() -> list[UnitState]:
    """Named SIMTEST fixture: captured identities plus deliberately chosen state.

    KEYE/KEYGL5 unitspec files place the sixbit Project and UnitName fields at
    0x23 and 0x2A. CBus2InputUnit.s reads IDENTIFY8 as terminal levels; the
    native KEYE1 scan requests nine groups, so this fixture chooses nine OFF
    levels. These values are generated fixture state, not original device data.
    """
    from .memory import encode_sixbit

    units = default_units()
    for unit, name in zip(units[:2], ("SIMKEY1", "SIMEDLT")):
        unit.parameters[0x23] = encode_sixbit("SIMTEST")
        unit.parameters[0x2A] = encode_sixbit(name)
        unit.parameters[0x21] = (unit.parameters[0x21][:2] + unit.parameters[0x23]
                                 + unit.parameters[0x21][8:9] + unit.parameters[0x2A][:3])
        # CBusUnit.g polls the configured change byte (ac=242). This fixture
        # chooses FF, matching the native initial value w; no checksum claim.
        unit.parameters[0xF2] = b"\xFF"
    units[0].attributes[8] = bytes(9)
    return units


class _Rejected(Exception):
    def __init__(self, reason, status="#"):
        super().__init__(reason)
        self.status = status


class PCISimulator:
    """Persistent bounded simulator, suitable for deterministic socket tests.

    ``smart=True`` starts configured for PCIClient. With ``smart=False``, the
    client must first send ``|\r`` or ``||\r``. ``null\r`` and empty sync lines
    are accepted without modifying state. Checksum mode is fixed explicitly;
    its parser never heuristically treats bad checksums as absent checksums.
    ``chatter`` contains complete caller-supplied incoming PCI wire messages,
    inserted before every successful unit response. ``fragment_sizes`` cycles
    deterministic write sizes; OS TCP reads may coalesce those writes.
    ``response_delay`` adds a fixed delay before each nonempty command reply.
    This is an explicit test transport setting, not inferred device timing.
    ``profile='raw'`` keeps generic blocks. ``captured`` enables the exact
    recorded eDLT memory transport. ``synthetic`` names its deliberate test
    state SIMTEST and supports the bounded native C-Gate discovery fixture.
    """

    def __init__(self, units: list[UnitState] | None = None, *, state_path=None,
                 local_unit=16, smart=True, command_checksum=False,
                 fragment_sizes=(), chatter=(), wire_log_path=None,
                 profile="raw", physical_memory=None, legacy_memory=None,
                 legacy_writable=None, status_blocks=None, lighting_groups=None,
                 lighting_clock=time.monotonic, pci_settings_units=None,
                 clock_generator=None, response_delay=0, readdress_challenges=None,
                 readdress_empty_addresses=None, serial_readdress_reply_tails=None):
        _byte(local_unit, "local_unit")
        if profile not in ("raw", "captured", "synthetic"):
            raise ValueError("profile must be raw, captured or synthetic")
        if physical_memory is not None and profile == "raw":
            raise ValueError("physical_memory requires an explicit hardware profile")
        self.profile = profile
        self.pci_settings_units = set()
        self.clock_generator = None
        self.readdress_challenges = {}
        self.readdress_empty_addresses = set()
        self.serial_readdress_reply_tails = {}
        self._pending_readdress = {}
        self.labels = LabelState()
        self.triggers = TriggerState()
        self.enable = EnableState()
        self._lighting_clock = lighting_clock
        self.lighting = LightingState(clock=lighting_clock)
        if lighting_groups is not None and profile != "synthetic":
            raise ValueError("Lighting state requires the synthetic profile")
        source_memory = ({5: {16: 0x38, 17: 0xFF}} if profile != "raw" else {}) if physical_memory is None else physical_memory
        self.physical_memory = self._validate_physical_memory(source_memory)
        if profile == "raw" and any(value is not None for value in (legacy_memory, legacy_writable, status_blocks)):
            raise ValueError("Legacy hardware memory requires an explicit hardware profile")
        self.legacy_memory = self._validate_legacy_memory(legacy_memory or {})
        self.legacy_writable = self._validate_legacy_writable(legacy_writable or {})
        self.status_blocks = {_byte(unit, "status unit"): _blocks(blocks, "status block")
                              for unit, blocks in (status_blocks or {}).items()}
        self._physical_pointers = {}
        self._programming_registers = {5: {
            0xFA: bytes.fromhex("FFFFFFFFFFFFFFFFFFFFFFFF381B381938213818FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"),
            0xFB: bytes.fromhex("30312E30352E303000")}}

        if not isinstance(smart, bool) or not isinstance(command_checksum, bool):
            raise ValueError("smart and command_checksum must be booleans")
        self.fragment_sizes = tuple(fragment_sizes)
        if any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in self.fragment_sizes):
            raise ValueError("fragment_sizes must contain positive integers")
        if (isinstance(response_delay, bool) or not isinstance(response_delay, (int, float))
                or not math.isfinite(response_delay) or not 0 <= response_delay <= 60):
            raise ValueError("response_delay must be a finite number in 0..60 seconds")
        self.response_delay = response_delay
        self.chatter = tuple(chatter)
        if any(not isinstance(item, bytes) for item in self.chatter):
            raise TypeError("chatter entries must be complete wire bytes")
        self.state_path = Path(state_path) if state_path is not None else None
        self.wire_log_path = Path(wire_log_path) if wire_log_path is not None else None
        self.local_unit = local_unit
        self.smart = smart
        self.command_checksum = command_checksum
        self._lock = threading.RLock()
        self._next_connection = 0
        self.wire_log = []
        if self.state_path is not None and self.state_path.exists():
            if any(value is not None for value in (units, physical_memory, legacy_memory, legacy_writable, status_blocks, lighting_groups, pci_settings_units, clock_generator, readdress_challenges, readdress_empty_addresses, serial_readdress_reply_tails)):
                raise ValueError("An existing state file cannot be combined with replacement units or memory")
            self._load()
        else:
            provided = (synthetic_units() if profile == "synthetic" else default_units()) if units is None else units
            self.units = {}
            for source in provided:
                unit = UnitState(source.address, source.attributes, source.parameters, source.write_tags, source.mmi_state)
                if unit.address in self.units:
                    raise ValueError("Duplicate unit address")
                self.units[unit.address] = unit
            if self.local_unit not in self.units:
                raise ValueError("local_unit must identify a configured simulated unit")
            self._configure_pci_settings(pci_settings_units or (), clock_generator)
            self.readdress_challenges = simulator_addressing.configure(self, {} if readdress_challenges is None else readdress_challenges)
            self.readdress_empty_addresses = simulator_serial_addressing.configure_empty(self, () if readdress_empty_addresses is None else readdress_empty_addresses)
            self.serial_readdress_reply_tails = simulator_serial_addressing.configure_tails(self, {} if serial_readdress_reply_tails is None else serial_readdress_reply_tails)
            self.lighting = LightingState(self._fixture_lighting_groups() if lighting_groups is None else lighting_groups,
                                          clock=self._lighting_clock)
            self._persist()

    def _configure_pci_settings(self, units, generator):
        """Opt-in PCI.xml settings, with an explicitly chosen fixture generator.

        Configuration bits at EEPROM3E come from PCI.xml. IDENTIFY16 status
        bits come from native dz.b: active1, enabled2, burden128. Choosing the
        generator is fixture setup, not a simulation of clock arbitration.
        """
        configured = {_byte(unit, "PCI settings unit") for unit in units}
        if configured and self.profile != "synthetic":
            raise ValueError("PCI settings require the synthetic profile")
        for address in configured:
            unit = self.units.get(address)
            if (unit is None or unit.attributes.get(1) not in (b"PC_CNIED", b"PC_CNICD")
                    or unit.attributes.get(2, b"").strip() != b"5.5.00"
                    or len(unit.attributes.get(16, b"")) != 4
                    or 0x3E not in self.legacy_memory.get(address, {})):
                raise ValueError("PCI settings require supported PCI 5.5.00 identity, IDENTIFY16 and explicit EEPROM3E")
        if generator is not None and _byte(generator, "clock generator") not in configured:
            raise ValueError("Clock generator must be an explicitly configured PCI settings unit")
        self.pci_settings_units = configured
        self.clock_generator = generator

    def _output_summary(self, unit):
        data = bytearray(unit.attributes[16])
        if unit.address in self.pci_settings_units:
            settings = self.legacy_memory[unit.address][0x3E]
            enabled = bool(settings & 1)
            active = enabled and unit.address == self.clock_generator
            data[0] = (data[0] & ~0x83) | (2 if enabled else 0) | int(active) | (128 if settings & 64 else 0)
        return bytes(data)

    def _fixture_lighting_groups(self):
        """Explicit captured membership with deliberately chosen OFF levels."""
        groups = {}
        if self.profile != "synthetic":
            return groups
        for unit in self.units.values():
            applications = unit.parameters.get(0x21, b"")[:2]
            addresses = unit.parameters.get(0x50, b"")
            memory = self.legacy_memory.get(unit.address, {})
            if memory:
                applications = bytes(memory[address] for address in (0x21, 0x22) if address in memory)
                addresses = bytes(memory[address] for address in range(0x50, 0x50 + len(unit.attributes.get(8, b"")))
                                  if address in memory)
            for app in applications:
                if 48 <= app <= 95:
                    groups.update({(app, group): 0 for group in addresses if group != 255})
        for unit, registers in self._programming_registers.items():
            if unit not in self.units:
                continue
            pairs = registers.get(0xFA, b"")
            groups.update({(pairs[i], pairs[i + 1]): 0 for i in range(0, len(pairs), 2)
                           if 48 <= pairs[i] <= 95 and pairs[i + 1] != 255})
        return groups

    def _terminal_levels(self, unit):
        """Project fixture GAVs onto the proven KEY4/KEYE1 IDENTIFY8 slots.

        CBus2InputUnit.s maps each IDENTIFY8 byte to the same-index configured
        group. The continuous test model is truncated to the protocol byte;
        this does not emulate a physical dimmer's PWM quantization.
        """
        data = bytearray(unit.attributes[8])
        if self.profile != "synthetic" or unit.attributes.get(1, b"").rstrip() not in (b"KEY4", b"KEYE1"):
            return bytes(data)
        applications = unit.parameters.get(0x21, b"")
        groups = unit.parameters.get(0x50, b"")
        memory = self.legacy_memory.get(unit.address, {})
        if memory:
            applications = bytes([memory[0x21]]) if 0x21 in memory else b""
            groups = [memory.get(address) for address in range(0x50, 0x50 + len(data))]
        if applications:
            for index, group in enumerate(groups[:len(data)]):
                if (applications[0], group) in self.lighting.groups:
                    data[index] = int(self.lighting.level(applications[0], group))
        return bytes(data)

    @classmethod
    def _validate_legacy_memory(cls, source):
        result = cls._validate_physical_memory(source)
        if any(address > 255 for memory in result.values() for address in memory):
            raise ValueError("Direct legacy addresses must fit one byte")
        return result

    def _validate_legacy_writable(self, source):
        result = {}
        for unit, addresses in source.items():
            _byte(unit, "legacy writable unit")
            result[unit] = {_byte(address, "legacy writable address") for address in addresses}
            if not result[unit] <= self.legacy_memory.get(unit, {}).keys():
                raise ValueError("Writable legacy bytes must exist in the explicit memory image")
        return result

    @staticmethod
    def _validate_physical_memory(source):
        result = {}
        for unit, memory in source.items():
            _byte(unit, "physical memory unit")
            result[unit] = {}
            for address, value in memory.items():
                if isinstance(address, bool) or not isinstance(address, int) or not 0 <= address < 2**32:
                    raise ValueError("Physical memory addresses must fit 32 bits")
                result[unit][address] = _byte(value, "physical memory value")
        return result

    def _document(self):
        return {"schema": 1, "local_unit": self.local_unit, "profile": self.profile,
                "physical_memory": {str(unit): {str(address): value for address, value in sorted(memory.items())}
                                    for unit, memory in sorted(self.physical_memory.items())}, "units": [
            {"address": unit.address, "mmi_state": unit.mmi_state,
             "attributes": {str(k): v.hex() for k, v in sorted(unit.attributes.items())},
             "parameters": {str(k): v.hex() for k, v in sorted(unit.parameters.items())},
             "write_tags": {str(k): v for k, v in sorted(unit.write_tags.items())}}
            for _, unit in sorted(self.units.items())],
                "legacy_memory": {str(unit): {str(address): value for address, value in sorted(memory.items())}
                                  for unit, memory in sorted(self.legacy_memory.items())},
                "legacy_writable": {str(unit): sorted(addresses) for unit, addresses in sorted(self.legacy_writable.items())},
                "status_blocks": {str(unit): {str(parameter): data.hex() for parameter, data in sorted(blocks.items())}
                                  for unit, blocks in sorted(self.status_blocks.items())},
                "labels": self.labels.snapshot(), "triggers": self.triggers.snapshot(), "enable": self.enable.snapshot(),
                "lighting": self.lighting.snapshot(), "pci_settings_units": sorted(self.pci_settings_units),
                "clock_generator": self.clock_generator,
                "readdress_challenges": {str(unit): value for unit, value in sorted(self.readdress_challenges.items())},
                "readdress_empty_addresses": sorted(self.readdress_empty_addresses),
                "serial_readdress_reply_tails": {serial: tail.hex() for serial, tail in sorted(self.serial_readdress_reply_tails.items())}}

    def snapshot(self):
        with self._lock:
            return self._document()

    def _load(self):
        try:
            document = json.loads(self.state_path.read_text())
            if not {"schema", "local_unit", "units"} <= set(document) <= {"schema", "local_unit", "units", "profile", "physical_memory", "legacy_memory", "legacy_writable", "status_blocks", "labels", "triggers", "enable", "lighting", "pci_settings_units", "clock_generator", "readdress_challenges", "readdress_empty_addresses", "serial_readdress_reply_tails"} or document["schema"] != 1:
                raise ValueError("Unsupported simulator state schema")
            stored_profile = document.get("profile", "raw")
            if self.profile != stored_profile:
                raise ValueError("State file profile differs from requested simulator profile")
            self.physical_memory = self._validate_physical_memory({
                int(unit): {int(address): value for address, value in memory.items()}
                for unit, memory in document.get("physical_memory", {}).items()})
            self.legacy_memory = self._validate_legacy_memory({
                int(unit): {int(address): value for address, value in memory.items()}
                for unit, memory in document.get("legacy_memory", {}).items()})
            self.legacy_writable = self._validate_legacy_writable({int(unit): addresses
                for unit, addresses in document.get("legacy_writable", {}).items()})
            self.status_blocks = {_byte(int(unit), "status unit"): _blocks(
                {int(parameter): bytes.fromhex(data) for parameter, data in blocks.items()}, "status block")
                for unit, blocks in document.get("status_blocks", {}).items()}
            if "labels" in document:
                self.labels = LabelState.from_snapshot(document["labels"])
            if "triggers" in document:
                self.triggers = TriggerState.from_snapshot(document["triggers"])
            if "enable" in document:
                self.enable = EnableState.from_snapshot(document["enable"])
            self.local_unit = _byte(document["local_unit"], "local_unit")
            self.units = {}
            for item in document["units"]:
                if set(item) not in ({"address", "attributes", "parameters", "write_tags"},
                                     {"address", "attributes", "parameters", "write_tags", "mmi_state"}):
                    raise ValueError("Invalid simulator unit state fields")
                unit = UnitState(item["address"],
                                 {int(k): bytes.fromhex(v) for k, v in item["attributes"].items()},
                                 {int(k): bytes.fromhex(v) for k, v in item["parameters"].items()},
                                 {int(k): v for k, v in item["write_tags"].items()}, item.get("mmi_state", 1))
                if unit.address in self.units:
                    raise ValueError("Duplicate unit address in simulator state")
                self.units[unit.address] = unit
            if self.local_unit not in self.units:
                raise ValueError("local_unit must identify a configured simulated unit")
            self._configure_pci_settings(document.get("pci_settings_units", ()), document.get("clock_generator"))
            self.readdress_challenges = simulator_addressing.configure(self, {
                int(unit): value for unit, value in document.get("readdress_challenges", {}).items()})
            self.readdress_empty_addresses = simulator_serial_addressing.configure_empty(self, document.get("readdress_empty_addresses", ()))
            self.serial_readdress_reply_tails = simulator_serial_addressing.configure_tails(self, {
                serial: bytes.fromhex(tail) for serial, tail in document.get("serial_readdress_reply_tails", {}).items()})
            self.lighting = (LightingState.from_snapshot(document["lighting"], clock=self._lighting_clock)
                             if "lighting" in document else LightingState(self._fixture_lighting_groups(), clock=self._lighting_clock))
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("Invalid simulator state file") from error

    def _persist(self):
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".pci-state-", dir=self.state_path.parent)
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(self._document(), handle, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _record(self, connection, direction, data, reason=None):
        with self._lock:
            record = {"sequence": len(self.wire_log), "connection": connection,
                      "direction": direction, "hex": data.hex()}
            if reason is not None:
                record["reason"] = reason
            self.wire_log.append(record)
            if self.wire_log_path is not None:
                self.wire_log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.wire_log_path.open("a") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")

    @staticmethod
    def _reply(payload):
        checksum = (-sum(payload)) & 0xFF
        return (payload + bytes([checksum])).hex().upper().encode("ascii") + b"\r\n"

    def _install_mmi(self, application=0xFF):
        """Standard binary install MMI, app FF: two bits per unit address.

        C-Gate cs/dk/dn decompilation verifies 3 contiguous blocks covering all
        256 units, little-endian pairs, >0 present, 3 conflict. The captured
        D8FF00/D8FF58/D6FFB0 framing carries 88,88,80 states respectively.
        Values for fixture units4/5/16 (2,2,1) match the recorded MMI.
        """
        frames = []
        with self._lock:
            if application == 0xFF:
                states = {address: unit.mmi_state for address, unit in self.units.items()}
            elif 48 <= application <= 95 and self.profile == "synthetic":
                # CBUS-QS section8: state1 is nonzero, state2 is zero.
                states = self.lighting.mmi_states(application)
            else:
                raise _Rejected("Unsupported MMI application")
            for start, count in ((0, 88), (88, 88), (176, 80)):
                packed = bytearray(count // 4)
                for address, state in states.items():
                    if start <= address < start + count:
                        relative = address - start
                        packed[relative // 4] |= state << (2 * (relative % 4))
                frames.append(self._reply(bytes([0xC0 | (len(packed) + 2), application, start]) + packed))
        return b"".join(frames)

    def _physical_cal(self, unit, request):
        """Captured OEM transport, independent of PP logical memory encoding.

        Vendor aV selects a 2..4-byte little-endian address with parameter0,
        tag41. aU/bj RECALL parameter1 reads memory; bj assembles repeated
        parameter replies. lP uses this path only for OEM logical offsets>=256
        with physical address=logical-256. Unknown bytes remain unreadable.
        """
        if unit not in self.physical_memory:
            raise _Rejected("No captured physical memory profile for this unit")
        opcode = request[0]
        if opcode & 0xE0 == 0xA0:
            parameter, data = request[1], request[2:]
            if parameter == 0 and 3 <= len(data) <= 5 and data[0] == 0x41:
                self._physical_pointers[unit] = int.from_bytes(data[1:], "little")
                return [b"\x32\x00\x41"]
            if parameter != 1 or len(data) < 2 or data[0] != 0x42:
                raise _Rejected("Unsupported physical-memory WRITE form")
            pointer = self._physical_pointers.get(unit)
            if pointer is None:
                raise _Rejected("Physical memory address has not been selected")
            memory = self.physical_memory[unit]
            addresses = range(pointer, pointer + len(data) - 1)
            if any(address not in memory for address in addresses):
                raise _Rejected("Physical memory WRITE includes uncaptured bytes")
            previous = {address: memory[address] for address in addresses}
            memory.update(zip(addresses, data[1:]))
            try:
                self._persist()
            except OSError as error:
                memory.update(previous)
                raise _Rejected("Physical memory persistence failed") from error
            self._physical_pointers[unit] = pointer + len(data) - 1
            return [b"\x32\x01\x42"]
        if opcode != 0x1A or len(request) != 3 or request[2] == 0:
            raise _Rejected("Unsupported physical-memory CAL")
        parameter, count = request[1:]
        if parameter == 1:
            pointer = self._physical_pointers.get(unit)
            if pointer is None:
                raise _Rejected("Physical memory address has not been selected")
            memory = self.physical_memory[unit]
            try:
                data = bytes(memory[address] for address in range(pointer, pointer + count))
            except KeyError as error:
                raise _Rejected("Physical memory RECALL includes uncaptured bytes") from error
            self._physical_pointers[unit] = pointer + count
        else:
            data = self._programming_registers.get(unit, {}).get(parameter)
            if data is None or len(data) < count:
                raise _Rejected("Unknown or short captured programming register")
            data = data[:count]
        return [bytes([0x80 | (len(data[offset:offset + 16]) + 1), parameter]) + data[offset:offset + 16]
                for offset in range(0, len(data), 16)]

    def _command(self, line, context):
        """Independent decoder: only exact supported shapes can reach mutation."""
        code = b""
        if line and ord("g") <= line[-1] <= ord("z"):
            code, line = line[-1:], line[:-1]
        try:
            addressed = line.startswith(b"\\")
            explicit_header = addressed
            basic = line.startswith(b"@")
            text = line[1:] if addressed or basic else line
            if not text or len(text) % 2 or any(c not in b"0123456789abcdefABCDEF" for c in text):
                raise _Rejected("Malformed hexadecimal command")
            payload = bytes.fromhex(text.decode("ascii"))
            if self.command_checksum and not basic:
                if len(payload) < 2 or sum(payload) & 255:
                    raise _Rejected("Invalid C-Bus checksum", "$")
                payload = payload[:-1]
            # Vendor cl.b(): repeated packet headers are omitted on the wire.
            # BASIC @ access is local and never reuses the cached bus header.
            if not addressed and not basic and context["header"] is not None:
                payload = context["header"] + payload
                addressed = True
            if addressed and payload[:4] == b"\x05\xff\x00\x0f":
                with self._lock:
                    try: response = simulator_serial_addressing.handle(self, payload)
                    except ValueError as error: raise _Rejected(str(error)) from error
                    if explicit_header: context["header"] = payload[:3]
                return ((code + b".") if code else b"") + (self._reply(response) if response else b""), None
            if (addressed and self.profile == "synthetic" and len(payload) >= 4
                    and payload[0] == 5 and (48 <= payload[1] <= 95 or payload[1] in (202, 203)) and payload[2] == 0):
                trigger = payload[1] == 202 and payload[3] in (1, 2, 9, 121)
                enable = payload[1] == 203 and payload[3] == 2
                lighting = 48 <= payload[1] <= 95 and (payload[3] in (1, 9, 121) or payload[3] in RAMP_SECONDS)
                with self._lock:
                    state = self.triggers if trigger else self.enable if enable else self.lighting if lighting else self.labels
                    previous = state.snapshot()
                    try:
                        committed = state.receive(payload[3:]) if trigger or enable else state.receive(payload[1], payload[3:])
                    except (LabelPacketError, ApplicationPacketError, EnablePacketError, LightingPacketError) as error:
                        raise _Rejected(str(error)) from error
                    if committed:
                        try:
                            self._persist()
                        except OSError as error:
                            if trigger:
                                self.triggers = TriggerState.from_snapshot(previous)
                            elif enable:
                                self.enable = EnableState.from_snapshot(previous)
                            elif lighting:
                                self.lighting = LightingState.from_snapshot(previous, clock=self._lighting_clock)
                            else:
                                self.labels = LabelState.from_snapshot(previous)
                            raise _Rejected("Application state persistence failed") from error
                    if explicit_header:
                        context["header"] = payload[:3]
                # Native outgoing SAL capture proves confirmation; no incoming
                # SAL echo is synthesized without independent wire evidence.
                return ((code + b".") if code else b""), None
            if addressed and len(payload) == 6 and payload[:4] == b"\x05\xff\x00\xfa" and payload[5] == 0:
                if explicit_header:
                    context["header"] = payload[:3]
                return ((code + b".") if code else b"") + b"".join(self.chatter) + self._install_mmi(payload[4]), None
            programming = False
            unit_address = self.local_unit
            if addressed:
                if len(payload) < 4 or payload[0] != 0x46:
                    raise _Rejected("Unsupported packet header")
                unit_address = payload[1]
                if payload[2] == 0:
                    if explicit_header:
                        context["header"] = payload[:3]
                    payload = payload[3:]
                elif payload[2:4] == b"\x09\x00":
                    programming = True
                    if explicit_header:
                        context["header"] = payload[:4]
                    payload = payload[4:]
                else:
                    raise _Rejected("Unsupported routing")
            if not payload:
                raise _Rejected("Missing CAL")
            # C-Gate cc.h(): one-shot BASIC read of the attached PCI address.
            # Broader BASIC command behavior remains explicitly unsupported.
            if basic and (payload != b"\x1a\x20\x01" or code):
                raise _Rejected("Unsupported BASIC command")
            if not programming and not basic:
                with self._lock:
                    try: moved = simulator_addressing.handle(self, unit_address, payload)
                    except ValueError as error: raise _Rejected(str(error)) from error
                    if moved is not None:
                        source, response = moved
                        if not response: return ((code + b".") if code else b""), None
                        if addressed and source != self.local_unit:
                            response = bytes([0x86, source, self.local_unit, 0]) + response
                        return ((code + b".") if code else b"") + b"".join(self.chatter) + self._reply(response), None
            requests = []
            remaining = payload
            while remaining:
                opcode = remaining[0]
                if opcode == 0x21:
                    length = 2
                elif opcode in (0x1A, 0x2A):
                    length = 3
                elif opcode & 0xE0 == 0xA0:
                    length = (opcode & 0x1F) + 1
                    if length < 2:
                        raise _Rejected("Invalid WRITE count")
                else:
                    raise _Rejected("Unsupported CAL command")
                if len(remaining) < length:
                    raise _Rejected("Truncated CAL command")
                requests.append(remaining[:length])
                remaining = remaining[length:]
            if len(requests) > 1 and any(request[0] & 0xE0 == 0xA0 for request in requests):
                raise _Rejected("Chained writes are unsupported")
            with self._lock:
                unit = self.units.get(unit_address)
                if unit is None:
                    raise _Rejected("Unknown unit")
                if programming and self.profile != "raw":
                    if len(requests) != 1:
                        raise _Rejected("Chained physical-memory CALs are unsupported")
                    responses = self._physical_cal(unit_address, requests[0])
                    prefix = bytes([0x86, unit_address, self.local_unit, 0x01, 0x00])
                    frames = b"".join(self._reply(prefix + response) for response in responses)
                    return ((code + b".") if code else b"") + b"".join(self.chatter) + frames, None
                responses = []
                for payload in requests:
                    opcode = payload[0]
                    if opcode == 0x21:
                        if len(payload) != 2 or programming:
                            raise _Rejected("Invalid or unsupported IDENTIFY form")
                        parameter = payload[1]
                        if parameter not in unit.attributes:
                            raise _Rejected("Unknown IDENTIFY attribute")
                        data = (self._terminal_levels(unit) if parameter == 8 else
                                self._output_summary(unit) if parameter == 16 else unit.attributes[parameter])
                        response = bytes([0x80 | (len(data) + 1), parameter]) + data
                    elif opcode == 0x1A:
                        if len(payload) != 3 or programming or not 1 <= payload[2] <= 30:
                            raise _Rejected("Invalid or unsupported RECALL form")
                        parameter, count = payload[1:]
                        if unit_address in self.legacy_memory:
                            memory = self.legacy_memory[unit_address]
                            try:
                                data = bytes(memory[i] for i in range(parameter, parameter + count))
                            except KeyError as error:
                                raise _Rejected("Legacy RECALL includes unmapped fixture bytes") from error
                        else:
                            data = unit.parameters.get(parameter)
                        if data is None or len(data) < count:
                            raise _Rejected("RECALL exceeds a configured parameter block")
                        response = bytes([0x80 | (count + 1), parameter]) + data[:count]
                    elif opcode == 0x2A:
                        if programming or len(payload) != 3 or not 1 <= payload[2] <= 30:
                            raise _Rejected("Unsupported status READ form")
                        parameter, count = payload[1:]
                        data = self.status_blocks.get(unit_address, {}).get(parameter)
                        if data is None or len(data) < count:
                            raise _Rejected("Unknown or short fixture status READ block")
                        response = bytes([0x80 | (count + 1), parameter]) + data[:count]
                    elif opcode & 0xE0 == 0xA0:
                        count = opcode & 0x1F
                        if count < 1 or len(payload) != count + 1:
                            raise _Rejected("Invalid WRITE count")
                        parameter = payload[1]
                        if unit_address in self.legacy_memory:
                            if len(payload) < 4:
                                raise _Rejected("Legacy STORE needs a tag and data")
                            tag, data = payload[2], payload[3:]
                            addresses = range(parameter, parameter + len(data))
                            if not set(addresses) <= self.legacy_writable.get(unit_address, set()):
                                raise _Rejected("Legacy STORE includes unmapped or protected fixture bytes")
                            memory = self.legacy_memory[unit_address]
                            previous = {i: memory[i] for i in addresses}
                            memory.update(zip(addresses, data))
                            try:
                                self._persist()
                            except OSError as error:
                                memory.update(previous)
                                raise _Rejected("Legacy memory persistence failed") from error
                            responses.append(bytes([0x32, parameter, tag]))
                            continue
                        if parameter not in unit.write_tags:
                            raise _Rejected("Parameter is unknown or read-only")
                        previous = unit.parameters[parameter]
                        unit.parameters[parameter] = payload[2:]
                        try:
                            self._persist()
                        except OSError as error:
                            unit.parameters[parameter] = previous
                            raise _Rejected("State persistence failed") from error
                        response = bytes([0x32, parameter, unit.write_tags[parameter]])
                    else:
                        raise _Rejected("Unsupported CAL command")
                    responses.append(response)
                response = b"".join(responses)
                if addressed and unit_address != self.local_unit:
                    route = b"\x01\x00" if programming else b"\x00"
                    response = bytes([0x86, unit_address, self.local_unit]) + route + response
                return ((code + b".") if code else b"") + b"".join(self.chatter) + self._reply(response), None
        except _Rejected as error:
            return (code + error.status.encode("ascii")) if code else b"!", str(error)

    def _connection(self, conn, connection, shutdown):
        conn.settimeout(0.2)
        buffer = bytearray()
        configured = self.smart
        context = {"header": None}

        def send(data, reason=None):
            if data and self.response_delay and shutdown.wait(self.response_delay):
                return
            sizes = self.fragment_sizes or (len(data),)
            offset = index = 0
            while offset < len(data):
                part = data[offset:offset + sizes[index % len(sizes)]]
                conn.sendall(part)
                self._record(connection, "tx", part, reason)
                offset += len(part)
                index += 1

        while not shutdown.is_set():
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                if buffer:
                    self._record(connection, "rejected", bytes(buffer), "Truncated command on disconnect")
                return
            buffer.extend(data.translate(None, b"\x11\x13"))
            while b"\r" in buffer:
                end = buffer.index(13)
                line = bytes(buffer[:end])
                del buffer[:end + 1]
                self._record(connection, "rx", line + b"\r")
                if not line or line == b"null":
                    continue
                if line in (b"|", b"||"):
                    configured = True
                    context["header"] = None
                    continue
                if len(line) > 4096:
                    response, reason = b"!", "Command exceeds maximum size"
                elif not configured and not line.startswith(b"@"):
                    code = line[-1:] if ord("g") <= line[-1] <= ord("z") else b""
                    response, reason = code + b"#", "SMART/CONNECT is not configured"
                else:
                    response, reason = self._command(line, context)
                try:
                    send(response, reason)
                except OSError:
                    return
            if len(buffer) > 4096:
                self._record(connection, "rejected", bytes(buffer), "Command exceeds maximum size")
                buffer.clear()
                try:
                    send(b"!", "Command exceeds maximum size")
                except OSError:
                    return

    def _server(self, host, port):
        engine = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                with engine._lock:
                    connection = engine._next_connection
                    engine._next_connection += 1
                engine._connection(self.request, connection, self.server.stopping)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = False

        server = Server((host, port), Handler)
        server.stopping = threading.Event()
        return server

    @contextmanager
    def running(self, host="127.0.0.1", port=0):
        """Start a real TCP server; yield its (host, port), then shut it down."""
        server = self._server(host, port)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            yield server.server_address
        finally:
            server.stopping.set()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def serve(self, host="127.0.0.1", port=10001):
        """Block serving TCP requests until interrupted."""
        with self._server(host, port) as server:
            try:
                server.serve_forever(poll_interval=0.1)
            finally:
                server.stopping.set()


def serve(host="127.0.0.1", port=10001, **options):
    """Convenience entrypoint used by the CLI."""
    PCISimulator(**options).serve(host, port)
