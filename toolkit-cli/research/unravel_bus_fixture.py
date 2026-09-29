"""Research-only serial-keyed bus fixture for native UNRAVEL captures.

The fixture holds any number of synthetic KEYE1 2.5.00 nodes plus the local
synthetic PC_CNIED at 16. Several nodes may share one address, including the
PCI address. Every node answers addressed reads at its current address with
its own complete frame, in configured node order. This models separate
received frames, not analogue collision or timing.

Physical policies are explicit fixture choices, never firmware claims:

* ``co`` (05FF000F00 serial destination) moves every node carrying that serial
  whether or not the destination is occupied, and leaves parameter 0x20
  unchanged, so any later protected STORE is visible.
* The legacy 1120 unlock answers 82/20/5A from each node at the address. A
  following A3/20/4E destination/5A STORE moves every unlocked node there,
  again regardless of destination occupancy, and updates parameter 0x20.
* A node that lacks a requested read block stays silent (recorded).
* Local PCI option STOREs A3/42/97/05|07 are accepted as in the earlier fork.

Moves into occupied destinations, unmatched serials and every rejected write
are recorded, so an unsafe native action cannot be hidden by the fixture.
"""
from __future__ import annotations

from cbus_toolkit.simulator import PCISimulator, UnitState, synthetic_units

FORMAT = "cbus-unravel-bus-fixture-v1"
CHALLENGE = 0x5A
KEYE1_SERIAL_BASE = 0x18B10600  # Synthetic 101136.1536 upwards.


def _clone(unit):
    return UnitState(unit.address, unit.attributes, unit.parameters, unit.write_tags, unit.mmi_state)


def packed_serial(unit):
    return unit.attributes[4][5:9]


def canonical(packed):
    value = int.from_bytes(packed, "big")
    return f"{value >> 12}.{value & 4095}"


def keye1(address, serial_low):
    """A synthetic KEYE1 node; ``serial_low`` selects packed 18B106xx."""
    template = synthetic_units()[0]
    node = _clone(template)
    node.address = address
    identity = bytearray(node.attributes[4])
    identity[5:9] = (KEYE1_SERIAL_BASE | serial_low).to_bytes(4, "big")
    node.attributes[4] = bytes(identity)
    node.parameters[0x20] = bytes([address])
    return node


def pci_unit():
    return _clone(synthetic_units()[2])


class UnravelBusFixture(PCISimulator):
    def __init__(self, nodes, *, response_delay=0.01, wire_log_path=None):
        pci = pci_unit()
        self._pci = pci
        self._physical = [_clone(node) for node in nodes]
        serials = [packed_serial(node) for node in self._physical]
        if len(set(serials)) != len(serials) or packed_serial(pci) in serials:
            raise ValueError("Fixture serials must be distinct")
        super().__init__([pci], local_unit=pci.address, profile="synthetic", physical_memory={},
                         response_delay=response_delay, wire_log_path=wire_log_path)
        self.co_operations = []
        self.store_operations = []
        self.unlock_operations = []
        self.pci_operations = []
        self.rejected_writes = []
        self.silent_reads = []
        self._unlocked = set()
        self._rebuild()

    def _rebuild(self):
        self.units = {self.local_unit: self._pci}
        for node in self._physical:
            self.units.setdefault(node.address, node)

    def at(self, address):
        return [node for node in self._physical if node.address == address]

    def topology(self):
        """Serial -> address for every physical node, in node order."""
        with self._lock:
            return {canonical(packed_serial(node)): node.address for node in self._physical}

    def snapshot(self):
        with self._lock:
            return {"format": FORMAT, "fixture_only": True, "local_unit": self.local_unit,
                    "pci_serial": canonical(packed_serial(self._pci)),
                    "pci_parameter66": self._pci.parameters[0x42].hex(),
                    "nodes": [{"serial": canonical(packed_serial(node)), "address": node.address,
                               "parameter32": node.parameters[0x20].hex()} for node in self._physical],
                    "policies": {"co": "moves every matching serial regardless of occupancy; parameter32 unchanged",
                                 "protected_store": "moves every unlocked node regardless of occupancy; parameter32 updated",
                                 "collisions": "separate complete frames in node order"}}

    def _occupants(self, address):
        serials = [canonical(packed_serial(node)) for node in self.at(address)]
        if address == self.local_unit:
            serials.insert(0, canonical(packed_serial(self._pci)))
        return serials

    def _command(self, line, context):
        code = line[-1:] if line and ord("g") <= line[-1] <= ord("z") else b""
        raw = line[:-1] if code else line
        explicit, basic = raw.startswith(b"\\"), raw.startswith(b"@")
        text = raw[1:] if explicit or basic else raw
        if basic or not text or len(text) % 2 or any(c not in b"0123456789abcdefABCDEF" for c in text):
            return super()._command(line, context)
        payload = bytes.fromhex(text.decode())
        if not explicit and context["header"] is not None:
            payload = context["header"] + payload
        ack = code + b"." if code else b""
        with self._lock:
            if payload[:5] == bytes.fromhex("05FF000F00"):
                if len(payload) != 11 or sum(payload[4:]) & 255:
                    self.rejected_writes.append(payload.hex())
                    return code + b"#", "co shape/checksum invalid"
                packed, new = payload[5:9], payload[9]
                matching = [node for node in self._physical if packed_serial(node) == packed]
                record = {"serial": canonical(packed), "requested": new, "payload": payload.hex(),
                          "old": [node.address for node in matching],
                          "destination_occupants_before": self._occupants(new)}
                if explicit:
                    context["header"] = payload[:3]
                if not matching:
                    record.update(outcome="no_matching_serial", reply=None)
                    self.co_operations.append(record)
                    return ack, None
                for node in matching:
                    node.address = new
                self._rebuild()
                response = bytes([0x86, new, self.local_unit, 0, 0x87, 0]) + packed + b"\x00\x00"
                record.update(outcome="moved_into_occupied" if record["destination_occupants_before"] else "moved",
                              reply=response.hex())
                self.co_operations.append(record)
                return ack + self._reply(response), None
            if payload[:3] == bytes([0x46, self.local_unit, 0]) and payload[3:] in (b"\xa3\x42\x97\x05", b"\xa3\x42\x97\x07"):
                self._pci.parameters[0x42] = payload[-1:]
                self.pci_operations.append(payload.hex())
                if explicit:
                    context["header"] = payload[:3]
                return ack + self._reply(b"\x32\x42\x97"), None
            if len(payload) == 6 and payload[:4] == b"\x05\xff\x00\xfa" and payload[5] == 0:
                return PCISimulator._command(self, line, context)
            if len(payload) < 4 or payload[0] != 0x46 or payload[2] != 0:
                self.rejected_writes.append(payload.hex())
                return code + b"#", "Unsupported route or application"
            address, cal = payload[1], payload[3:]
            nodes = self.at(address)
            if explicit:
                context["header"] = payload[:3]
            if cal == b"\x11\x20":
                self.unlock_operations.append({"address": address, "responders": self._occupants(address)})
                self._unlocked = {id(node) for node in nodes}
                frames = b"".join(self._reply(bytes([0x86, address, self.local_unit, 0, 0x82, 0x20, CHALLENGE]))
                                  for _ in nodes)
                return ack + frames, None
            if cal[:3] == b"\xa3\x20\x4e" and len(cal) == 5:
                new, token = cal[3:]
                movers = [node for node in nodes if id(node) in self._unlocked] if token == CHALLENGE else []
                self._unlocked = set()
                record = {"old": address, "new": new, "payload": payload.hex(),
                          "movers": [canonical(packed_serial(node)) for node in movers],
                          "destination_occupants_before": self._occupants(new)}
                for node in movers:
                    node.address = new
                    node.parameters[0x20] = bytes([new])
                self._rebuild()
                record["outcome"] = ("not_unlocked" if not movers else
                                     "moved_into_occupied" if record["destination_occupants_before"] else "moved")
                self.store_operations.append(record)
                frames = b"".join(self._reply(bytes([0x86, new, self.local_unit, 0, 0x32, 0x20, 0x4e]))
                                  for _ in movers)
                return ack + frames, None
            remaining = cal
            while remaining:
                size = 2 if remaining[0] == 0x21 else 3 if remaining[0] in (0x1A, 0x2A) else 0
                if not size or len(remaining) < size:
                    self.rejected_writes.append(payload.hex())
                    return code + b"#", "Research fixture rejects unproven CAL/write"
                remaining = remaining[size:]
            replies = []
            if address == self.local_unit:
                reply, reason = PCISimulator._command(self, line, context)
                if reason:
                    return reply, reason
                replies.append(reply[len(ack):])
            elif not nodes:
                return ack, None
            for node in nodes:
                self.units[address] = node
                node_context = dict(context)
                try:
                    reply, reason = PCISimulator._command(self, line, node_context)
                finally:
                    self._rebuild()
                if reason:
                    # A node without the requested block stays silent; it
                    # cannot cancel other nodes' or the PCI's frames.
                    self.silent_reads.append({"address": address, "serial": canonical(packed_serial(node)),
                                              "request": payload.hex(), "reason": reason})
                    continue
                body = reply[len(ack):]
                if address == self.local_unit:
                    # A bus node sharing the PCI address answers as a remote unit.
                    body = self._reemit(body, address)
                replies.append(body)
            return ack + b"".join(replies), None

    def _reemit(self, body, address):
        """Rewrite a raw PCI-local reply as a remote frame from ``address``."""
        frames = []
        for line in body.split(b"\r\n"):
            if not line:
                continue
            data = bytes.fromhex(line.decode())[:-1]
            frames.append(self._reply(bytes([0x86, address, self.local_unit, 0]) + data))
        return b"".join(frames)
