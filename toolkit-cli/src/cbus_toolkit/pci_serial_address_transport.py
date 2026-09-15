"""One selected-serial broadcast and a bounded whole-capture receipt window.

This low-level transport performs no inventory or commissioning preconditions.
A correlated receipt never verifies movement or persistence. Use only with
exclusive endpoint ownership and independently established mutation authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import math
import socket
import threading
import time

from .pci_serial_address import SerialAddressReceipt, decode_serial_address_receipt, encode_serial_address


def _seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 60:
        raise ValueError(name + " must be finite and in (0,60] seconds")
    return float(value)


@dataclass(frozen=True)
class SerialAddressExchange:
    request: bytes
    received: bytes
    send_attempted: bool
    send_completed: bool
    bytes_received: int
    receipt: SerialAddressReceipt
    termination: str
    capture_complete: bool
    elapsed: float | None
    response_elapsed: float | None
    response_timeout: float
    overall_timeout: float
    max_bytes: int
    connection_closed: bool
    errors: tuple[dict, ...]

    @property
    def movement_verified(self): return False

    @property
    def persistence_verified(self): return False

    def as_dict(self):
        return {"format": "cbus-pci-serial-address-exchange-v1", "request_hex": self.request.hex(),
                "received_hex": self.received.hex(), "send_attempted": self.send_attempted,
                "send_completed": self.send_completed, "bytes_received": self.bytes_received,
                "retained_bytes": len(self.received), "sent_byte_count": None,
                "receipt": self.receipt.as_dict(), "correlation_status": self.receipt.status,
                "retained_receipt_matches_request": self.receipt.matched,
                "termination": self.termination, "capture_complete": self.capture_complete,
                "timing": {"elapsed_seconds": self.elapsed, "response_elapsed_seconds": self.response_elapsed,
                           "response_timeout_seconds": self.response_timeout,
                           "overall_timeout_seconds": self.overall_timeout,
                           "native_response_timeout": self.response_timeout == 2.0},
                "max_bytes": self.max_bytes, "connection_closed": self.connection_closed,
                "errors": [dict(item) for item in self.errors], "automatic_retries": 0,
                "movement_verified": False, "persistence_verified": False,
                "requires_independent_verification": True,
                "inventory_performed": False, "database_updated": False,
                "request_has_source_address": False}


class PCISerialAddressTransport:
    """Exactly one co command on a fresh numeric-IP socket, then close.

    The fixed capture window begins when sendall returns; every byte is retained
    up to max_bytes. No receipt, rejection, malformed prefix or first frame ends
    that window early. EOF, byte saturation overflow, transport errors and the
    absolute total deadline leave capture incomplete. A valid retained prefix
    can correlate even when the full capture is incomplete.

    No SMART reset, PCI option change, inventory, retry, rollback or other
    request occurs. send_completed describes sendall returning, not bus delivery.
    On I/O errors return partial evidence. On interruption/unexpected exception,
    retain the original exception and attach pci_serial_address_exchange after
    closing. The same evidence remains in last_exchange, with first error in
    last_error. This object cannot be reused.
    """

    def __init__(self, host, port=10001, *, local_unit, response_timeout=2.0,
                 overall_timeout=5.0, max_bytes=4096, confirmation=b"g", command_checksum=False):
        if not isinstance(host, str) or "%" in host:
            raise ValueError("A numeric IPv4 or IPv6 endpoint without a scope suffix is required")
        try: address = ipaddress.ip_address(host)
        except ValueError as error:
            raise ValueError("A numeric IP endpoint is required; DNS is not deadline-bounded") from error
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer in 1..65535")
        if type(local_unit) is not int or not 0 <= local_unit <= 255:
            raise ValueError("local_unit must be an integer in 0..255")
        # Pure codec preflight also validates confirmation and outgoing checksum.
        encode_serial_address("0.1", 2, confirmation=confirmation, command_checksum=command_checksum)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 4096:
            raise ValueError("max_bytes must be an integer in 1..4096")
        self.response_timeout = _seconds(response_timeout, "response_timeout")
        self.overall_timeout = _seconds(overall_timeout, "overall_timeout")
        if self.overall_timeout <= self.response_timeout:
            raise ValueError("overall_timeout must strictly exceed response_timeout")
        self.host, self.port, self.local_unit = str(address), port, local_unit
        self._family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        self.max_bytes, self.confirmation, self.command_checksum = max_bytes, confirmation, command_checksum
        self._lock = threading.Lock(); self._used = False
        self._absolute_deadline = None  # Internal parent admission budget; cannot extend the local deadline.
        self.last_exchange = None; self.last_error = None

    def _make_socket(self):
        return socket.socket(self._family, socket.SOCK_STREAM)

    def send_serial_address(self, serial, destination):
        """Preflight pure inputs, send once, and return only capture evidence."""
        request = encode_serial_address(serial, destination, confirmation=self.confirmation,
                                        command_checksum=self.command_checksum)
        empty = decode_serial_address_receipt(b"", serial=serial, destination=destination,
                                             local_unit=self.local_unit, confirmation=self.confirmation)
        with self._lock:
            if self._used:
                raise RuntimeError("Selected-serial transport is one-shot; requests must never be replayed automatically")
            self._used = True
            return self._exchange(request, empty)

    def _exchange(self, request, empty):
        started = last_clock = sent_at = None
        sock = None; closed = True; attempted = completed = capture_complete = False
        received = bytearray(); total_bytes = 0; errors = []
        termination = "not_started"; phase = "initial_clock"; interruption = None
        receipt = empty

        def clock():
            nonlocal last_clock
            last_clock = time.monotonic()
            return last_clock

        def fail(error, where):
            nonlocal interruption
            errors.append({"phase": where, "type": type(error).__name__, "message": str(error)})
            if self.last_error is None: self.last_error = error
            if interruption is None and not isinstance(error, (OSError, TimeoutError)):
                interruption = error

        try:
            started = clock()
            deadline = started + self.overall_timeout
            if self._absolute_deadline is not None:
                if isinstance(self._absolute_deadline, bool) or not isinstance(self._absolute_deadline, (int, float)) or not math.isfinite(self._absolute_deadline):
                    raise ValueError("Internal absolute deadline must be finite")
                deadline = min(deadline, self._absolute_deadline)
            if clock() >= deadline:
                termination = "overall_timeout"
            else:
                phase = "socket_creation"; sock = self._make_socket(); closed = False
                remaining = deadline - clock()
                if remaining <= 0:
                    termination = "overall_timeout"
                else:
                    phase = "connect"; sock.settimeout(remaining)
                    if clock() >= deadline:
                        termination = "overall_timeout"
                    else:
                        endpoint = (self.host, self.port, 0, 0) if self._family == socket.AF_INET6 else (self.host, self.port)
                        sock.connect(endpoint)
                        remaining = deadline - clock()
                        if remaining <= 0: termination = "overall_timeout"
                        elif remaining <= self.response_timeout: termination = "insufficient_response_budget"
                        else:
                            phase = "send"; sock.settimeout(remaining)
                            remaining = deadline - clock()
                            if remaining <= 0: termination = "overall_timeout"
                            elif remaining <= self.response_timeout: termination = "insufficient_response_budget"
                            else:
                                attempted = True
                                sock.sendall(request)
                                completed = True; sent_at = clock()
                                response_deadline = sent_at + self.response_timeout
                                # Parent wins ties. A late send cannot admit any follow-up receive.
                                if sent_at >= deadline: termination = "overall_timeout"
                                elif response_deadline >= deadline: termination = "insufficient_response_budget"
                                else:
                                    phase = "receive"; termination = "collecting"
                                    while termination == "collecting":
                                        now = clock()
                                        if now >= deadline: termination = "overall_timeout"; break
                                        if now >= response_deadline:
                                            termination = "response_window_elapsed"; capture_complete = True; break
                                        sock.settimeout(min(deadline, response_deadline) - now)
                                        now = clock()
                                        if now >= deadline: termination = "overall_timeout"; break
                                        if now >= response_deadline:
                                            termination = "response_window_elapsed"; capture_complete = True; break
                                        try: chunk = sock.recv(min(4096, self.max_bytes + 1 - len(received)))
                                        except socket.timeout: continue
                                        # Save all bounded received evidence before any interruptible clock call.
                                        if chunk:
                                            total_bytes += len(chunk)
                                            received.extend(chunk[:self.max_bytes - len(received)])
                                        arrived = clock()
                                        if total_bytes > self.max_bytes:
                                            termination = "byte_limit"; break
                                        if arrived >= deadline: termination = "overall_timeout"; break
                                        if arrived >= response_deadline: termination = "late_data"; break
                                        if not chunk: termination = "disconnected"; break
        except BaseException as error:
            fail(error, phase)
            termination = "interrupted" if interruption is not None else (
                "send_error" if phase == "send" else "receive_error" if phase == "receive" else "connection_error")
        finally:
            if sock is not None:
                try: sock.close(); closed = True
                except BaseException as error: fail(error, "close")
        try:
            receipt = decode_serial_address_receipt(received, serial=empty.expected_serial,
                destination=empty.expected_destination, local_unit=self.local_unit, confirmation=self.confirmation)
        except BaseException as error: fail(error, "receipt_parse")
        try: clock()
        except BaseException as error: fail(error, "final_clock")
        exchange = SerialAddressExchange(request, bytes(received), attempted, completed, total_bytes,
            receipt, termination, capture_complete,
            None if started is None or last_clock is None else max(0.0, last_clock-started),
            None if sent_at is None or last_clock is None else max(0.0, last_clock-sent_at),
            self.response_timeout, self.overall_timeout, self.max_bytes, closed, tuple(errors))
        self.last_exchange = exchange
        if interruption is not None:
            interruption.pci_serial_address_exchange = exchange.as_dict()
            raise interruption
        return exchange
