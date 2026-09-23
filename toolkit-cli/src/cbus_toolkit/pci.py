"""Strict CAL codecs and a synchronous TCP PCI client.

Wire evidence: repository proxy.log packets 6995 onward and
``docs/proxy-capture-analysis-2026-04-26.md``. This module implements raw
parameter operations; it assigns no unverified meaning to programming bytes.
The client expects a PCI in SMART/CONNECT mode. It does not reset the bus or
change interface configuration on connection. Incoming frames require their
C-Bus checksum; outgoing checksums can be enabled for SRCHK interfaces.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import socket
import threading
import time
from typing import Union


class ProtocolError(ValueError):
    """Malformed, unsupported, or uncorrelatable PCI protocol data."""


class PCIRejected(ProtocolError):
    """The PCI rejected the command; no successful unit write is implied."""


def _byte(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer in 0..255")
    return value


def _payload(value: bytes) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("CAL data must be bytes")
    data = bytes(value)
    if len(data) > 30:
        raise ValueError("A single CAL can contain at most 30 data bytes")
    return data


@dataclass(frozen=True)
class IdentifyCAL:
    attribute: int

    def __post_init__(self):
        _byte(self.attribute, "attribute")

    def encode(self) -> bytes:
        return bytes((0x21, self.attribute))


@dataclass(frozen=True)
class RecallCAL:
    parameter: int
    count: int

    def __post_init__(self):
        _byte(self.parameter, "parameter")
        _byte(self.count, "count")
        if self.count == 0:
            raise ValueError("Recall count must be positive")

    def encode(self) -> bytes:
        return bytes((0x1A, self.parameter, self.count))


@dataclass(frozen=True)
class WriteCAL:
    parameter: int
    data: bytes

    def __post_init__(self):
        _byte(self.parameter, "parameter")
        object.__setattr__(self, "data", _payload(self.data))

    def encode(self) -> bytes:
        return bytes((0xA0 | (len(self.data) + 1), self.parameter)) + self.data


@dataclass(frozen=True)
class AcknowledgeCAL:
    parameter: int
    tag: int

    def __post_init__(self):
        _byte(self.parameter, "parameter")
        _byte(self.tag, "tag")

    def encode(self) -> bytes:
        return bytes((0x32, self.parameter, self.tag))


@dataclass(frozen=True)
class ReplyCAL:
    parameter: int
    data: bytes

    def __post_init__(self):
        _byte(self.parameter, "parameter")
        object.__setattr__(self, "data", _payload(self.data))

    def encode(self) -> bytes:
        return bytes((0x80 | (len(self.data) + 1), self.parameter)) + self.data


CAL = Union[IdentifyCAL, RecallCAL, WriteCAL, AcknowledgeCAL, ReplyCAL]


def encode_cal(cal: CAL) -> bytes:
    if not isinstance(cal, (IdentifyCAL, RecallCAL, WriteCAL, AcknowledgeCAL, ReplyCAL)):
        raise TypeError("Unsupported CAL object")
    return cal.encode()


def decode_cal(data: bytes) -> tuple[CAL, int]:
    """Decode one CAL and return its exact consumed length, including opcode."""
    if not data:
        raise ProtocolError("Missing CAL opcode")
    opcode = data[0]
    lengths = {0x21: 2, 0x1A: 3, 0x32: 3}
    family = opcode & 0xE0
    if opcode in lengths:
        length = lengths[opcode]
    elif family in (0x80, 0xA0):
        if opcode & 0x1F == 0:
            raise ProtocolError("CAL count must include a parameter byte")
        length = 1 + (opcode & 0x1F)
    else:
        raise ProtocolError(f"Unsupported CAL opcode 0x{opcode:02X}")
    if len(data) < length:
        raise ProtocolError(f"Truncated CAL: expected {length} bytes, received {len(data)}")
    if opcode == 0x21:
        cal = IdentifyCAL(data[1])
    elif opcode == 0x1A:
        if data[2] == 0:
            raise ProtocolError("Recall count must be positive")
        cal = RecallCAL(data[1], data[2])
    elif opcode == 0x32:
        cal = AcknowledgeCAL(data[1], data[2])
    elif family == 0x80:
        cal = ReplyCAL(data[1], data[2:length])
    else:
        cal = WriteCAL(data[1], data[2:length])
    return cal, length


def decode_cals(data: bytes) -> tuple[CAL, ...]:
    result = []
    while data:
        cal, consumed = decode_cal(data)
        result.append(cal)
        data = data[consumed:]
    if not result:
        raise ProtocolError("Empty CAL message")
    return tuple(result)


@dataclass(frozen=True)
class Confirmation:
    code: bytes
    status: str

    @property
    def success(self) -> bool:
        return self.status == "."


@dataclass(frozen=True)
class Notification:
    code: str


@dataclass(frozen=True)
class Frame:
    source: int | None
    destination: int | None
    cals: tuple[CAL, ...]
    route: bytes = b""
    confirmation: bytes | None = None
    raw: bytes = b""

    @property
    def bare(self) -> bool:
        return self.source is None and self.destination is None


def add_checksum(data: bytes) -> bytes:
    return data + bytes((-sum(data) & 255,))


def _confirmation(code: bytes | None) -> bytes:
    if code is None:
        return b""
    if not isinstance(code, bytes) or len(code) != 1 or code[0] not in range(ord("g"), ord("z") + 1):
        raise ValueError("Confirmation code must be one byte in g..z")
    return code


def encode_command(unit: int | None, cal: CAL, *, addressing: str = "direct",
                   confirmation: bytes | None = None, checksum: bool = False) -> bytes:
    """Encode raw CAL to attached PCI (unit=None), or addressed bus unit.

    ``programming`` preserves the captured 09 00 routing bytes. It does not
    select programming memory or implement any vendor register semantics.
    """
    if addressing not in ("direct", "programming"):
        raise ValueError("addressing must be direct or programming")
    payload = encode_cal(cal)
    prefix = b""
    if unit is not None:
        _byte(unit, "unit")
        route = b"\x00" if addressing == "direct" else b"\x09\x00"
        payload = bytes((0x46, unit)) + route + payload
        prefix = b"\\"
    elif addressing != "direct":
        raise ValueError("Programming addressing requires a bus unit")
    if checksum:
        payload = add_checksum(payload)
    return prefix + payload.hex().upper().encode("ascii") + _confirmation(confirmation) + b"\r"


def decode_frame(data: bytes, *, from_pci: bool = True, checksum: bool | None = None,
                 bare: bool = False) -> Frame:
    """Decode a complete ASCII frame, retaining source and routing bytes.

    Incoming addressed traffic supports local routing 00 and the captured
    programming response routing 01 00. Multi-network routes are rejected.
    A CAL-only reply is never assigned a fabricated source address. Because
    0x86 can mean either a reply CAL or a packet header, use ``bare=True``
    when the interface is known to return naked CALs; otherwise a valid
    addressed header takes precedence, as in the unit-4 capture.
    """
    checksum = from_pci if checksum is None else checksum
    raw = bytes(data)
    line = raw.rstrip(b"\r\n").translate(None, b"\x11\x13")
    confirmation = None
    addressed = line.startswith(b"\\")
    if addressed:
        line = line[1:]
    if not from_pci and line and ord("g") <= line[-1] <= ord("z"):
        confirmation, line = line[-1:], line[:-1]
    if not line or len(line) % 2 or any(c not in b"0123456789abcdefABCDEF" for c in line):
        raise ProtocolError("Frame must contain an even number of hexadecimal characters")
    payload = bytes.fromhex(line.decode("ascii"))
    if checksum:
        if len(payload) < 2 or sum(payload) & 255:
            raise ProtocolError("Invalid C-Bus checksum")
        payload = payload[:-1]
    if not from_pci:
        if not addressed:
            return Frame(None, None, decode_cals(payload), confirmation=confirmation, raw=raw)
        if len(payload) < 4 or payload[0] != 0x46:
            raise ProtocolError("Unsupported command packet header")
        unit = payload[1]
        if payload[2] == 0:
            route, offset = payload[2:3], 3
        elif payload[2:4] == b"\x09\x00":
            route, offset = payload[2:4], 4
        else:
            raise ProtocolError("Unsupported command routing")
        return Frame(None, unit, decode_cals(payload[offset:]), route, confirmation, raw)

    # Full addressed messages and naked reply CALs overlap at opcode 0x86.
    candidates = []
    errors = []
    if not bare and payload[0] in (0x06, 0x46, 0x86, 0xC6):
        try:
            if len(payload) < 5:
                raise ProtocolError("Truncated point-to-point header")
            if payload[3] == 0:
                route, offset = payload[3:4], 4
            elif payload[3:5] == b"\x01\x00":
                route, offset = payload[3:5], 5
            else:
                raise ProtocolError("Unsupported response routing")
            return Frame(payload[1], payload[2], decode_cals(payload[offset:]), route, raw=raw)
        except ProtocolError as error:
            errors.append(error)
    try:
        cals = decode_cals(payload)
        if not all(isinstance(cal, (ReplyCAL, AcknowledgeCAL)) for cal in cals):
            raise ProtocolError("Unsupported bare PCI response")
        candidates.append(Frame(None, None, cals, raw=raw))
    except ProtocolError as error:
        errors.append(error)
    if len(candidates) != 1:
        if candidates:
            raise ProtocolError("Ambiguous addressed/bare PCI response")
        raise ProtocolError("Unsupported PCI frame: " + "; ".join(map(str, errors)))
    return candidates[0]


class FrameStream:
    """Incremental parser; consumes all complete frames and retains fragments."""

    def __init__(self, *, from_pci: bool = True, checksum: bool | None = None,
                 max_buffer: int = 8192, bare: bool = False):
        if max_buffer <= 0:
            raise ValueError("max_buffer must be positive")
        self.from_pci = from_pci
        self.checksum = checksum
        self.bare = bare
        self.max_buffer = max_buffer
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame | Confirmation | Notification]:
        self.buffer.extend(bytes(data).translate(None, b"\x11\x13"))
        events = []
        while self.buffer:
            if self.buffer[0] in (10, 13):
                del self.buffer[0]
                continue
            if self.from_pci and self.buffer[0] in b"+!":
                events.append(Notification(chr(self.buffer.pop(0))))
                continue
            if self.from_pci and ord("g") <= self.buffer[0] <= ord("z"):
                if len(self.buffer) < 2:
                    break
                code, status = bytes(self.buffer[:1]), chr(self.buffer[1])
                del self.buffer[:2]
                # CBUS-QS issue 2.0 section 4.2: # = retries exhausted,
                # $ = corrupt command checksum, % = lost network clock.
                if status not in ".#$%!":
                    raise ProtocolError(f"Invalid PCI confirmation status {status!r}")
                events.append(Confirmation(code, status))
                continue
            end = self.buffer.find(b"\r")
            if end < 0:
                if len(self.buffer) > self.max_buffer:
                    self.buffer.clear()
                    raise ProtocolError("PCI frame exceeds maximum buffer size")
                break
            if end > self.max_buffer:
                self.buffer.clear()
                raise ProtocolError("PCI frame exceeds maximum buffer size")
            line = bytes(self.buffer[:end])
            del self.buffer[:end + 1]
            events.append(decode_frame(line, from_pci=self.from_pci, checksum=self.checksum, bare=self.bare))
        return events

    def finish(self) -> None:
        if self.buffer:
            raise ProtocolError("Connection ended with a truncated PCI frame")


class PCIClient:
    """One outstanding CAL request per connection, including confirmation.

    ``unit=None`` first discovers the attached address with the proven BASIC
    ``@1A2001`` query unless ``local_unit`` was supplied, then sends an explicit
    destination. A new TCP connection does not reset PCI routing compression.
    A bare response can satisfy a request to ``unit=None`` (the attached PCI),
    or a unit explicitly identified by ``local_unit``. Bare data cannot prove
    the identity of an arbitrary addressed bus unit. Unrelated events are
    retained in ``unsolicited``. No write is retried automatically.
    """

    def __init__(self, host: str, port: int = 10001, *, timeout: float = 5.0,
                 local_unit: int | None = None, command_checksum: bool = False):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer in 1..65535")
        if local_unit is not None:
            _byte(local_unit, "local_unit")
        self.host, self.port, self.timeout = host, port, timeout
        self.local_unit = local_unit
        self._configured_local_unit = local_unit
        self.command_checksum = command_checksum
        self.socket: socket.socket | None = None
        self.stream = FrameStream()
        self.unsolicited: deque[Frame | Confirmation | Notification] = deque()
        self._confirmation_index = 0
        self._lock = threading.Lock()

    def connect(self) -> PCIClient:
        if self.socket is not None:
            raise RuntimeError("PCI client is already connected")
        self.socket = socket.create_connection((self.host, self.port), self.timeout)
        self.stream = FrameStream()
        self.local_unit = self._configured_local_unit
        return self

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def __enter__(self) -> PCIClient:
        return self.connect()

    def __exit__(self, *_):
        self.close()

    def identify(self, unit: int | None, attribute: int) -> bytes:
        reply = self._request(unit, IdentifyCAL(attribute), ReplyCAL, attribute)
        return reply.data

    def recall(self, unit: int | None, parameter: int, count: int, *, addressing="direct") -> bytes:
        """Read 1..255 bytes, assembling complete source/parameter-matched CALs.

        Vendor bj/bD and captured FA44 transfers use repeated parameter codes
        across multiple replies. Each CAL remains limited to30 data bytes.
        """
        request = RecallCAL(parameter, count)
        return self._request(unit, request, ReplyCAL, parameter,
                             addressing=addressing, reply_count=count)

    def write(self, unit: int | None, parameter: int, data: bytes, *,
              addressing: str = "direct", ack_tag: int | None = None) -> AcknowledgeCAL:
        request = WriteCAL(parameter, data)
        if ack_tag is not None:
            _byte(ack_tag, "ack_tag")
        return self._request(unit, request, AcknowledgeCAL, parameter,
                             addressing=addressing, ack_tag=ack_tag)

    def _discover_local_unit(self, deadline):
        """BASIC access bypasses the previous packet's cached bus destination."""
        if self.socket is None:
            raise RuntimeError("PCI client is not connected")
        sock = self.socket
        sock.sendall(b"@1A2001\r")
        result = None
        while result is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out discovering the attached PCI address")
            sock.settimeout(remaining)
            chunk = sock.recv(4096)
            if not chunk:
                self.stream.finish()
                raise ConnectionError("PCI disconnected before its local address was discovered")
            for event in self.stream.feed(chunk):
                if isinstance(event, Notification) and event.code == "!":
                    raise PCIRejected("PCI rejected BASIC local-address discovery")
                if (isinstance(event, Frame) and event.bare and len(event.cals) == 1
                        and isinstance(event.cals[0], ReplyCAL) and event.cals[0].parameter == 0x20):
                    data = event.cals[0].data
                    if len(data) != 1:
                        raise ProtocolError("BASIC local-address reply must contain exactly one byte")
                    if result is not None:
                        raise ProtocolError("Multiple BASIC local-address replies are ambiguous")
                    result = data[0]
                else:
                    self.unsolicited.append(event)
        self.local_unit = result

    def _request(self, unit, cal, response_type, parameter, *, addressing="direct", ack_tag=None, reply_count=None):
        with self._lock:
            # Validate before the potentially necessary BASIC discovery query.
            encode_command(unit, cal, addressing=addressing, checksum=self.command_checksum)
            if self.socket is None:
                raise RuntimeError("PCI client is not connected")
            sock = self.socket
            deadline = time.monotonic() + self.timeout
            confirmed = False
            response = None
            reply_data = bytearray()
            try:
                if unit is None:
                    if self.local_unit is None:
                        self._discover_local_unit(deadline)
                    target = self.local_unit
                else:
                    target = unit
                code = bytes((ord("g") + self._confirmation_index % 20,))
                wire = encode_command(target, cal, addressing=addressing,
                                      confirmation=code, checksum=self.command_checksum)
                self._confirmation_index += 1
                sock.sendall(wire)
                while not (confirmed and response is not None):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for PCI confirmation and matching CAL response")
                    sock.settimeout(remaining)
                    chunk = sock.recv(4096)
                    if not chunk:
                        self.stream.finish()
                        if reply_count is not None and reply_data and len(reply_data) != reply_count:
                            raise ProtocolError(f"Recall length mismatch: requested {reply_count}, received {len(reply_data)}")
                        raise ConnectionError("PCI disconnected before request completed")
                    # Handle every event in this read, including trailing events
                    # after a response and confirmation have both been received.
                    for event in self.stream.feed(chunk):
                        if isinstance(event, Confirmation) and event.code == code:
                            if not event.success:
                                raise PCIRejected(f"PCI rejected command {code.decode()}: {event.status}")
                            confirmed = True
                        elif isinstance(event, Notification) and event.code == "!":
                            raise PCIRejected("PCI reported busy; request outcome cannot be confirmed")
                        elif isinstance(event, Frame):
                            source_matches = (event.source == target if event.source is not None
                                              else target == self.local_unit)
                            matches = [item for item in event.cals
                                       if source_matches and isinstance(item, response_type)
                                       and item.parameter == parameter
                                       and (ack_tag is None or item.tag == ack_tag)]
                            if matches:
                                if reply_count is not None:
                                    for item in matches:
                                        reply_data.extend(item.data)
                                    if len(reply_data) > reply_count:
                                        raise ProtocolError(f"Recall length mismatch: requested {reply_count}, received {len(reply_data)}")
                                    if len(reply_data) == reply_count:
                                        response = bytes(reply_data)
                                else:
                                    if len(matches) != 1 or response is not None:
                                        raise ProtocolError("Multiple matching CAL responses are ambiguous")
                                    response = matches[0]
                                others = tuple(item for item in event.cals if not any(item is match for match in matches))
                                if others:
                                    self.unsolicited.append(Frame(event.source, event.destination, others,
                                                                  event.route, event.confirmation, event.raw))
                            else:
                                self.unsolicited.append(event)
                        else:
                            self.unsolicited.append(event)
                return response
            except socket.timeout as error:
                self.close()
                raise TimeoutError("Timed out waiting for PCI confirmation and matching CAL response") from error
            except (OSError, ProtocolError):
                # Reuse after timeout could associate a late reply with another
                # request to the same parameter. Reconnect before further work.
                self.close()
                raise
