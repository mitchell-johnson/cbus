"""Opt-in discovery-only fixture with two explicit KEYE1 nodes at address255.

This topology cannot be loaded by PCISimulator's address-keyed state format.
It intentionally rejects all unit/application writes and programming transport.
"""
from __future__ import annotations

from copy import deepcopy

from .simulator import PCISimulator, UnitState


def _clone(unit):
    if not isinstance(unit, UnitState):
        raise ValueError("Each physical node must be an explicit UnitState")
    return UnitState(unit.address, unit.attributes, unit.parameters,
                     unit.write_tags, unit.mmi_state)


def _serial(unit):
    data = unit.attributes.get(4)
    if data is None or len(data) != 12:
        raise ValueError("Each node requires an explicit 12-byte IDENTIFY4 block")
    value = int.from_bytes(data[5:9], "big")
    if value in (0, 0xFFFFFFFF):
        raise ValueError("Fixture serials must be known")
    return f"{value >> 12}.{value & 4095}"


class DuplicateAddressSimulator(PCISimulator):
    """Read-only pair of otherwise identical KEYE1 nodes at factory address255.

    The input order defines deterministic response order; each node emits its
    own complete CAL reply with an independent outer checksum. One PCI command
    confirmation covers the bus request. This models distinct received frames,
    not analogue bus contention or collision-resolution timing.

    ``snapshot`` includes both serial-keyed physical nodes. File persistence,
    loading standard address-keyed snapshots, and every write are unsupported.
    The inherited ``units[255]`` is only a representative for MMI/read plumbing;
    callers must use ``nodes`` or ``snapshot`` to inspect this topology.
    """

    FORMAT = "cbus-duplicate-address-discovery-fixture-v1"

    def __init__(self, nodes, pci, *, state_path=None, smart=True,
                 command_checksum=False, fragment_sizes=(), wire_log_path=None,
                 response_delay=0):
        if state_path is not None:
            raise ValueError("Duplicate-node topology has no supported state-file format")
        if not isinstance(nodes, (tuple, list)) or len(nodes) != 2:
            raise ValueError("Exactly two explicit physical nodes are required")
        nodes = [_clone(node) for node in nodes]
        pci = _clone(pci)
        for node in nodes:
            if (node.address != 255 or node.attributes.get(1) != b"KEYE1   "
                    or node.attributes.get(2) != b"2.5.00  "
                    or node.parameters.get(32) != b"\xff" or node.write_tags):
                raise ValueError("Discovery nodes require read-only KEYE1 2.5.00 at address255")
        if (not 1 <= pci.address <= 254 or pci.attributes.get(1) != b"PC_CNIED"
                or pci.attributes.get(2) != b"5.5.00  "
                or pci.parameters.get(32) != bytes([pci.address]) or pci.write_tags):
            raise ValueError("Local PCI must be an explicit read-only PC_CNIED 5.5.00")
        serials = [_serial(unit) for unit in nodes + [pci]]
        if len(set(serials)) != 3:
            raise ValueError("All physical nodes must have distinct known serials")
        first_attributes = {k: v for k, v in nodes[0].attributes.items() if k != 4}
        second_attributes = {k: v for k, v in nodes[1].attributes.items() if k != 4}
        if (first_attributes != second_attributes or nodes[0].parameters != nodes[1].parameters
                or nodes[0].mmi_state != nodes[1].mmi_state):
            raise ValueError("This bounded fixture requires identical profiles apart from IDENTIFY4")
        super().__init__([pci, nodes[0]], local_unit=pci.address, smart=smart,
                         command_checksum=command_checksum, fragment_sizes=fragment_sizes,
                         wire_log_path=wire_log_path, response_delay=response_delay,
                         profile="synthetic", physical_memory={})
        self._collision_nodes = (self.units[255], nodes[1])
        self._node_serials = tuple(serials[:2])

    @property
    def nodes(self):
        """Detached serial-keyed physical node copies, retaining both address255s."""
        with self._lock:
            return {serial: _clone(node) for serial, node in
                    zip(self._node_serials, self._collision_nodes)}

    def snapshot(self):
        with self._lock:
            return {"format": self.FORMAT, "read_only": True,
                    "physical_nodes": [{"serial": serial, "address": node.address,
                        "attributes": {str(k): v.hex() for k, v in node.attributes.items()},
                        "parameters": {str(k): v.hex() for k, v in node.parameters.items()},
                        "write_tags": {}, "mmi_state": node.mmi_state}
                        for serial, node in zip(self._node_serials, self._collision_nodes)],
                    "base_state": deepcopy(super().snapshot())}

    def _command(self, line, context):
        code = line[-1:] if line and ord("g") <= line[-1] <= ord("z") else b""
        text = line[:-1] if code else line
        explicit, basic = text.startswith(b"\\"), text.startswith(b"@")
        if explicit or basic:
            text = text[1:]

        def reject(reason, status=b"#"):
            return code + status if code else b"!", reason

        if not text or len(text) % 2 or any(c not in b"0123456789abcdefABCDEF" for c in text):
            return reject("Malformed hexadecimal command")
        payload = bytes.fromhex(text.decode("ascii"))
        if self.command_checksum and not basic:
            if len(payload) < 2 or sum(payload) & 255:
                return reject("Invalid C-Bus checksum", b"$")
            payload = payload[:-1]
        addressed = explicit
        if not explicit and not basic and context["header"] is not None:
            payload = context["header"] + payload
            addressed = True
        if basic:
            if payload != b"\x1a\x20\x01" or code:
                return reject("Unsupported BASIC command")
            return super()._command(line, context)
        if addressed and payload == b"\x05\xff\x00\xfa\xff\x00":
            return super()._command(line, context)
        unit_address = self.local_unit
        if addressed:
            if len(payload) < 4 or payload[0] != 0x46 or payload[2] != 0:
                return reject("Discovery-only fixture rejects this routing or application command")
            unit_address, payload = payload[1], payload[3:]
        if not payload:
            return reject("Missing read CAL")
        remaining = payload
        while remaining:
            length = 2 if remaining[0] == 0x21 else 3 if remaining[0] in (0x1A, 0x2A) else 0
            if not length:
                return reject("Discovery-only fixture rejects all writes and unlock commands")
            if len(remaining) < length:
                return reject("Truncated read CAL")
            remaining = remaining[length:]
        if unit_address != 255:
            return super()._command(line, context)
        with self._lock:
            original = self.units[255]
            replies, contexts = [], []
            try:
                for node in self._collision_nodes:
                    self.units[255] = node
                    node_context = dict(context)
                    response, reason = super()._command(line, node_context)
                    if reason is not None:
                        return response, reason
                    replies.append(response)
                    contexts.append(node_context)
            finally:
                self.units[255] = original
            context.update(contexts[0])
            confirmation = code + b"." if code else b""
            return confirmation + b"".join(response[len(confirmation):] for response in replies), None
