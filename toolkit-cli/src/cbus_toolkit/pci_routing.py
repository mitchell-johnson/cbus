"""Pure point-to-point CAL route encoding and wire inspection.

The original aW.k(int) transformation is the oracle. This module does not
resolve network identities, inspect received traffic or send commands.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .pci import (AcknowledgeCAL, CAL, IdentifyCAL, ProtocolError, RecallCAL,
                  ReplyCAL, WriteCAL, add_checksum, decode_cal, encode_cal)


_CAL_TYPES = (IdentifyCAL, RecallCAL, WriteCAL, AcknowledgeCAL, ReplyCAL)


def _byte(value, name):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(name + ' must be an integer in 0..255')
    return value


def _boolean(value, name):
    if type(value) is not bool:
        raise TypeError(name + ' must be a Boolean')
    return value


def _confirmation(value):
    if value is None:
        return b''
    if type(value) is not bytes or len(value) != 1 or not ord('g') <= value[0] <= ord('z'):
        raise ValueError('confirmation must be one byte in g..z or None')
    return value


@dataclass(frozen=True)
class RoutedCALCommand:
    """One CAL addressed through explicit bytes, nearest bridge first.

    A programming zero consumes one of the six available route entries.
    The supplied addresses are wire values, not verified network topology.
    """
    unit: int
    cal: CAL
    bridges: tuple[int, ...] = field(default=(), kw_only=True)
    addressing: str = field(default='direct', kw_only=True)

    def __post_init__(self):
        _byte(self.unit, 'unit')
        if type(self.cal) not in _CAL_TYPES:
            raise TypeError('cal must be an existing supported CAL value')
        if type(self.bridges) not in (tuple, list):
            raise TypeError('bridges must be a tuple or list of address bytes')
        if type(self.addressing) is not str or self.addressing not in ('direct', 'programming'):
            raise ValueError('addressing must be direct or programming')
        if len(self.bridges) + (self.addressing == 'programming') > 6:
            raise ValueError('At most six route entries are supported, including the programming zero')
        bridges = tuple(_byte(value, 'bridge') for value in self.bridges)
        object.__setattr__(self, 'bridges', bridges)

    @property
    def address_path(self) -> tuple[int, ...]:
        return self.bridges + (self.unit,) + ((0,) if self.addressing == 'programming' else ())

    def encode(self, *, confirmation: bytes | None = None, checksum: bool = False) -> bytes:
        """Return the single ASCII command with CR; no I/O or configuration."""
        _boolean(checksum, 'checksum')
        suffix = _confirmation(confirmation)
        path = self.address_path
        payload = bytes((0x46, path[0], 9 * (len(path) - 1), *path[1:])) + encode_cal(self.cal)
        if checksum:
            payload = add_checksum(payload)
        return b'\\' + payload.hex().upper().encode('ascii') + suffix + b'\r'


@dataclass(frozen=True)
class RoutedCALWireCommand:
    """Observed outgoing command fields; no inferred unit/network identity."""
    address_path: tuple[int, ...]
    cal: CAL
    confirmation: bytes | None
    checksum_included: bool
    raw: bytes

    @property
    def route_count(self) -> int:
        return len(self.address_path) - 1

    def as_dict(self) -> dict:
        return {'format': 'cbus-routed-cal-wire-command-v1', 'header': 0x46,
                'address_path': list(self.address_path), 'route_count': self.route_count,
                'routing_byte': self.route_count * 9,
                'cal_hex': encode_cal(self.cal).hex().upper(),
                'confirmation': None if self.confirmation is None else self.confirmation.decode('ascii'),
                'checksum_included': self.checksum_included,
                'raw_hex': self.raw.hex().upper(), 'logical_network_resolved': False,
                'programming_mode_inferred': False, 'command_sent': False}


def inspect_routed_cal_command(raw: bytes, *, checksum: bool = False) -> RoutedCALWireCommand:
    """Strictly parse one outgoing header46 command in the explicit SRCHK mode.

    The final path byte zero is retained literally. It is not interpreted as
    a programming selector or a verified destination at unit zero.
    """
    _boolean(checksum, 'checksum')
    if type(raw) not in (bytes, bytearray, memoryview):
        raise TypeError('raw must be bytes')
    if (raw.nbytes if type(raw) is memoryview else len(raw)) > 87:
        raise ProtocolError('Expected one bounded outgoing CAL command ending in CR')
    data = bytes(raw)
    if not data.startswith(b'\\') or not data.endswith(b'\r'):
        raise ProtocolError('Expected one bounded outgoing CAL command ending in CR')
    line = data[1:-1]
    confirmation = None
    if line and ord('g') <= line[-1] <= ord('z'):
        confirmation, line = line[-1:], line[:-1]
    if not line or len(line) % 2 or any(c not in b'0123456789abcdefABCDEF' for c in line):
        raise ProtocolError('Command must contain an even number of hexadecimal characters')
    payload = bytes.fromhex(line.decode('ascii'))
    if checksum:
        if len(payload) < 2 or sum(payload) & 255:
            raise ProtocolError('Invalid command checksum')
        payload = payload[:-1]
    if len(payload) < 5 or payload[0] != 0x46:
        raise ProtocolError('Only outgoing point-to-point CAL header46 is supported')
    routing = payload[2]
    if routing > 54 or routing % 9:
        raise ProtocolError('Unsupported routing byte')
    count = routing // 9
    offset = 3 + count
    if len(payload) <= offset:
        raise ProtocolError('Truncated route or CAL')
    cal, used = decode_cal(payload[offset:])
    if offset + used != len(payload):
        raise ProtocolError('Expected exactly one CAL after the route')
    return RoutedCALWireCommand((payload[1], *payload[3:offset]), cal, confirmation, checksum, data)


@dataclass(frozen=True)
class ReceivedCALRoute:
    """Literal fields of one received addressed CAL frame, without cache resolution.

    The path may include marker bytes. It is not verified physical topology,
    and its final byte is not promoted to a logical source or unit identity.
    """
    header: int
    outer_source_byte: int
    destination_byte: int
    route_entries: tuple[int, ...]
    cal: CAL
    checksum_byte: int
    raw: bytes

    @property
    def route_count(self) -> int:
        return len(self.route_entries)

    @property
    def address_path(self) -> tuple[int, ...]:
        return (self.outer_source_byte, *self.route_entries)

    def as_dict(self) -> dict:
        return {'format': 'cbus-received-cal-route-v1', 'header': self.header,
                'outer_source_byte': self.outer_source_byte,
                'destination_byte': self.destination_byte,
                'route_count': self.route_count, 'route_entries': list(self.route_entries),
                'address_path': list(self.address_path),
                'cal_hex': encode_cal(self.cal).hex().upper(),
                'checksum_byte': self.checksum_byte, 'checksum_valid': True,
                'raw_hex': self.raw.hex().upper(), 'logical_network_resolved': False,
                'programming_mode_inferred': False, 'device_origin_verified': False,
                'io_performed': False}


def inspect_received_cal_route(raw: bytes) -> ReceivedCALRoute:
    """Inspect one received addressed06/86 CAL frame with its original checksum.

    This explicit profile requires ASCII hex and exactly one final CR. It
    never retries a rejected addressed frame as bare CAL. The87-byte bound
    follows from six route entries and one supported CAL; it is not a claim
    about the original receiver's universal packet limit. No cache lookup,
    logical identity inference, response correlation or I/O occurs.
    """
    if type(raw) not in (bytes, bytearray, memoryview):
        raise TypeError('raw must be bytes, bytearray or memoryview')
    size = raw.nbytes if type(raw) is memoryview else len(raw)
    if not 15 <= size <= 87:
        raise ProtocolError('Expected one received CAL frame within15..87bytes')
    data = bytes(raw)
    if not data.endswith(b'\r'):
        raise ProtocolError('Received frame must end in exactly one CR')
    line = data[:-1]
    if len(line) % 2 or any(c not in b'0123456789abcdefABCDEF' for c in line):
        raise ProtocolError('Received frame must contain only complete ASCII hex pairs before CR')
    payload = bytes.fromhex(line.decode('ascii'))
    if payload[0] not in (0x06, 0x86):
        raise ProtocolError('Only addressed received headers06 and86 are supported')
    count = payload[3]
    if count > 6:
        raise ProtocolError('Received route count must be in0..6')
    offset = 4 + count
    if len(payload) < offset + 3:
        raise ProtocolError('Truncated received route, CAL or checksum')
    if sum(payload) & 255:
        raise ProtocolError('Invalid original received checksum')
    cal, used = decode_cal(payload[offset:-1])
    if offset + used != len(payload) - 1:
        raise ProtocolError('Expected exactly one CAL after the received route')
    return ReceivedCALRoute(payload[0], payload[1], payload[2],
                            tuple(payload[4:offset]), cal, payload[-1], data)
