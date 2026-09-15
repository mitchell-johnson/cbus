"""Pure codecs for the original CAL selected-serial address broadcast.

No function opens a connection or sends bytes. A matching receipt establishes
packet correlation only; independent physical inventory remains necessary.
"""
from __future__ import annotations

from dataclasses import dataclass

from .pci import Confirmation, Frame, FrameStream, Notification, ProtocolError, ReplyCAL
from .serials import parse_native_serial


def _selected_serial(value):
    serial = parse_native_serial(value)
    if not serial.known:
        raise ValueError("Selected serial must be known; zero and FFFFFFFF are unsupported")
    return serial.canonical, ((serial.first << 12) | serial.second).to_bytes(4, "big")


def _destination(value):
    if type(value) is not int or not 2 <= value <= 254:
        raise ValueError("Selected-serial destination must be an integer in the supported range 2..254")
    return value


def _confirmation(value):
    if not isinstance(value, bytes) or len(value) != 1 or not b"g" <= value <= b"z":
        raise ValueError("Confirmation must be exactly one byte in g..z")
    return value


def encode_serial_address(serial, destination, *, command_checksum=False, confirmation=b"g"):
    """Encode one explicit serial/destination broadcast; do not transmit it.

    Original co.a(cn,int) checksums 00 + four big-endian serial bytes + target.
    Outgoing SRCHK adds a distinct checksum over the whole binary packet.
    The frame has no source-address field and cannot enforce source location.
    """
    _, packed = _selected_serial(serial)
    destination, confirmation = _destination(destination), _confirmation(confirmation)
    if type(command_checksum) is not bool:
        raise ValueError("command_checksum must be boolean")
    body = b"\x00" + packed + bytes([destination])
    payload = b"\x05\xff\x00\x0f" + body + bytes([-sum(body) & 255])
    if command_checksum:
        payload += bytes([-sum(payload) & 255])
    return b"\\" + payload.hex().upper().encode("ascii") + confirmation + b"\r"


@dataclass(frozen=True)
class SerialAddressReply:
    header: int | None
    source: int | None
    destination: int | None
    route: bytes
    serial: str
    serial_known: bool
    packed_serial: bytes
    opaque_tail: bytes
    raw: bytes

    def as_dict(self):
        return {"header": self.header, "source": self.source, "destination": self.destination,
                "route_hex": self.route.hex(), "serial": self.serial, "serial_known": self.serial_known,
                "packed_serial_hex": self.packed_serial.hex(), "opaque_tail_hex": self.opaque_tail.hex(),
                "opaque_tail_interpreted": False, "raw_hex": self.raw.hex()}


@dataclass(frozen=True)
class SerialAddressReceipt:
    expected_serial: str
    expected_destination: int
    local_unit: int
    expected_confirmation: bytes
    raw: bytes
    status: str
    issues: tuple[str, ...]
    errors: tuple[str, ...]
    confirmations: tuple[Confirmation, ...]
    replies: tuple[SerialAddressReply, ...]
    frames: tuple[Frame, ...]
    notifications: tuple[str, ...]
    pending: bytes

    @property
    def matched(self):
        """The bytes correlate; this is never proof of physical movement."""
        return self.status == "matched"

    @property
    def movement_verified(self): return False

    @property
    def persistence_verified(self): return False

    def as_dict(self):
        return {"format": "cbus-pci-serial-address-receipt-v1", "status": self.status,
                "receipt_matches_request": self.matched, "expected_serial": self.expected_serial,
                "expected_destination": self.expected_destination, "local_unit": self.local_unit,
                "expected_confirmation": self.expected_confirmation.decode("ascii"), "raw_hex": self.raw.hex(),
                "issues": list(self.issues), "errors": list(self.errors),
                "confirmations": [{"code": item.code.decode("ascii"), "status": item.status}
                                  for item in self.confirmations], "replies": [item.as_dict() for item in self.replies],
                "frames": [{"source": item.source, "destination": item.destination, "route_hex": item.route.hex(),
                            "bare": item.bare, "raw_hex": item.raw.hex()} for item in self.frames],
                "notifications": list(self.notifications), "pending_hex": self.pending.hex(),
                "movement_verified": False, "persistence_verified": False,
                "requires_independent_verification": True, "io_performed": False}


def decode_serial_address_receipt(data, *, serial, destination, local_unit, confirmation=b"g"):
    """Classify one bounded captured PCI exchange without I/O or state changes.

    A matched exchange requires one successful expected confirmation before
    one exact direct 86/target/local/00 receipt with CAL 87/00/selected serial.
    Bare receipts, other headers/routes, missing confirmation and mismatches
    remain unverified. Multiple/foreign/reordered responses are ambiguous.
    Framing/checksum errors are invalid; missing/truncated input is incomplete.
    Every classification retains original bytes and any valid parsed prefix.
    """
    expected_serial, packed = _selected_serial(serial)
    destination, confirmation = _destination(destination), _confirmation(confirmation)
    if type(local_unit) is not int or not 0 <= local_unit <= 255:
        raise ValueError("local_unit must be an integer in 0..255")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("Receipt must be captured PCI bytes")
    raw = bytes(data)
    if len(raw) > 4096:
        raise ValueError("Receipt exceeds the supported 4096-byte captured exchange limit")
    stream = FrameStream(max_buffer=4096)
    events, issues, errors = [], [], []
    invalid = False
    try:
        for byte in raw:
            events.extend(stream.feed(bytes([byte])))
    except ProtocolError as error:
        invalid = True
        issues.append("invalid_framing_or_checksum")
        errors.append(str(error))
    confirmations = tuple(item for item in events if isinstance(item, Confirmation))
    frames = tuple(item for item in events if isinstance(item, Frame))
    notifications = tuple(item.code for item in events if isinstance(item, Notification))
    replies = []
    for frame in frames:
        if any(byte not in b"0123456789abcdefABCDEF" for byte in frame.raw):
            invalid = True
            issues.append("unsupported_incoming_frame_prefix")
            errors.append("A receipt frame must contain hexadecimal response bytes without a command prefix")
            continue
        if len(frame.cals) != 1:
            issues.append("multiple_cals")
            continue
        cal = frame.cals[0]
        if not isinstance(cal, ReplyCAL) or cal.parameter != 0 or len(cal.data) != 6:
            issues.append("unsupported_receipt_cal")
            continue
        value = int.from_bytes(cal.data[:4], "big")
        replies.append(SerialAddressReply(None if frame.bare else int(frame.raw[:2], 16),
            frame.source, frame.destination, frame.route, f"{value >> 12}.{value & 4095}",
            value not in (0, 0xFFFFFFFF), cal.data[:4], cal.data[4:], frame.raw))
    ambiguous = False
    if len(confirmations) > 1:
        issues.append("multiple_confirmations"); ambiguous = True
    if any(item.code != confirmation for item in confirmations):
        issues.append("foreign_confirmation"); ambiguous = True
    if len(frames) > 1:
        issues.append("multiple_frames"); ambiguous = True
    if "multiple_cals" in issues:
        ambiguous = True
    if notifications:
        issues.append("unsolicited_notification"); ambiguous = True
    if frames and confirmations and next(i for i, item in enumerate(events) if isinstance(item, Frame)) < \
            next(i for i, item in enumerate(events) if isinstance(item, Confirmation)):
        issues.append("receipt_before_confirmation"); ambiguous = True
    rejected = any(item.code == confirmation and item.status != "." for item in confirmations)
    if rejected:
        issues.append("command_rejected")
        if frames:
            issues.append("receipt_after_rejection"); ambiguous = True
    if not confirmations:
        issues.append("missing_confirmation")
    if not frames:
        issues.append("missing_receipt")
    for reply in replies:
        if reply.header is None:
            issues.append("bare_receipt_unattributed")
        elif reply.header != 0x86:
            issues.append("unsupported_receipt_header")
        if reply.source != destination: issues.append("source_mismatch")
        if reply.destination != local_unit: issues.append("local_destination_mismatch")
        if reply.route != b"\x00": issues.append("route_mismatch")
        if reply.packed_serial != packed: issues.append("serial_mismatch")
        if not reply.serial_known: issues.append("unknown_serial")
    if stream.buffer:
        issues.append("truncated_input")
    if invalid: status = "invalid"
    elif ambiguous: status = "ambiguous"
    elif stream.buffer: status = "incomplete"
    elif rejected: status = "rejected"
    elif not frames: status = "incomplete"
    elif issues: status = "unverified"
    else: status = "matched"
    return SerialAddressReceipt(expected_serial, destination, local_unit, confirmation, raw, status,
        tuple(dict.fromkeys(issues)), tuple(errors), confirmations, tuple(replies), frames, notifications, bytes(stream.buffer))
