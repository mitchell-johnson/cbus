"""Read-only, one-shot direct-PCI multi-response serial observations.

The original cT command reads IDENTIFY4 with a 2000ms quiet interval and up
to seven responses. This collector preserves that default quiet interval,
adds hard bounds, and never equates an ACK or first response with completeness.
It has no write methods and closes its socket after every observation.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import math
import socket
import threading
import time

from .pci import Confirmation, Frame, FrameStream, IdentifyCAL, Notification, ProtocolError, ReplyCAL, encode_command


def _byte(value, name):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(name + " must be an integer in 0..255")
    return value


def _seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 60:
        raise ValueError(name + " must be finite and in (0,60] seconds")
    return float(value)


@dataclass(frozen=True)
class SerialReply:
    source: int | None
    destination: int | None
    serial: str | None
    known: bool
    data: bytes
    raw: bytes
    received_after: float

    def as_dict(self):
        return {"source": self.source, "destination": self.destination, "serial": self.serial,
                "known": self.known, "data_hex": self.data.hex(), "raw_hex": self.raw.hex(),
                "received_after_seconds": self.received_after}


@dataclass(frozen=True)
class SerialObservation:
    address: int
    local_unit: int
    request: bytes
    received: bytes
    confirmation: str | None
    replies: tuple[SerialReply, ...]
    unrelated: tuple[dict, ...]
    errors: tuple[str, ...]
    termination: str
    elapsed: float
    quiet_period: float
    overall_timeout: float
    confirmation_timeout: float
    max_frames: int
    bytes_received: int
    connection_closed: bool

    @property
    def serials(self):
        return tuple(sorted({reply.serial for reply in self.replies if reply.known},
                            key=lambda text: tuple(map(int, text.split(".")))))

    @property
    def repeated_responses(self):
        return len(self.replies) - len({(reply.serial, reply.data) for reply in self.replies})

    @property
    def complete(self):
        """The documented window completed; this does not imply a unique unit."""
        return self.termination == "quiet" and self.confirmation == "." and not self.errors

    @property
    def status(self):
        if not self.complete: return "incomplete"
        return "absent" if not self.serials else "single" if len(self.serials) == 1 else "duplicate_address"

    def as_dict(self):
        return {"format": "cbus-pci-serial-observation-v1", "address": self.address,
                "local_unit": self.local_unit, "status": self.status, "complete": self.complete,
                "serials": list(self.serials), "replies": [reply.as_dict() for reply in self.replies],
                "repeated_responses": self.repeated_responses, "confirmation": self.confirmation,
                "termination": self.termination, "errors": list(self.errors),
                "unrelated": [dict(item) for item in self.unrelated],
                "request_hex": self.request.hex(), "received_hex": self.received.hex(),
                "bytes_received": self.bytes_received,
                "timing": {"elapsed_seconds": self.elapsed, "quiet_period_seconds": self.quiet_period,
                    "overall_timeout_seconds": self.overall_timeout,
                    "confirmation_timeout_seconds": self.confirmation_timeout,
                    "vendor_quiet_period": self.quiet_period == 2.0},
                "max_frames": self.max_frames, "scope": "one_address",
                "physical_addresses_changed": False, "database_updated": False,
                "automatic_retries": 0, "connection_closed": self.connection_closed}


class PCISerialCollector:
    """One IDENTIFY4 request on a fresh TCP connection, closed on every outcome.

    The caller must exclusively own a numeric IP endpoint and supply its known attached
    PCI address. It validates routed response destinations; naked CAL replies
    are attributable only when querying that explicit local address. No SMART
    reset, interface configuration, C-Gate lifecycle operation or write occurs.

    This object can be used once. Failed or completed sockets are never reused,
    so a late response cannot satisfy another request on that stream. Opening
    another connection does not prove the physical bus has no delayed traffic;
    establishing fresh ownership/quiet conditions remains the caller's job.

    A serial response restarts the quiet interval. Other traffic does not.
    Reaching a hard bound, unknown serial, pending fragment, wrong destination,
    unassigned bare response, or framing/transport failure yields an incomplete
    observation. Counts include repeated identical frames; saturation never
    proves absence of additional serials. Shorter explicit quiet periods are
    useful for tests but are marked as differing from the native default.
    """

    def __init__(self, host, port=10001, *, local_unit, quiet_period=2.0,
                 overall_timeout=10.0, confirmation_timeout=2.0, max_frames=7,
                 max_unrelated=64, max_bytes=65536, command_checksum=False):
        if not isinstance(host, str) or "%" in host:
            raise ValueError("The bounded collector requires a numeric IPv4 or IPv6 address without a scope suffix")
        try: numeric_host = ipaddress.ip_address(host)
        except ValueError as error:
            raise ValueError("The bounded collector requires a numeric IPv4 or IPv6 address; DNS is not deadline-bounded") from error
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer in 1..65535")
        self.host, self.port, self.local_unit = str(numeric_host), port, _byte(local_unit, "local_unit")
        self._family = socket.AF_INET6 if numeric_host.version == 6 else socket.AF_INET
        self.quiet_period = _seconds(quiet_period, "quiet_period")
        self.overall_timeout = _seconds(overall_timeout, "overall_timeout")
        self.confirmation_timeout = _seconds(confirmation_timeout, "confirmation_timeout")
        if self.overall_timeout <= self.quiet_period or self.confirmation_timeout > self.overall_timeout:
            raise ValueError("overall_timeout must exceed quiet_period and include confirmation_timeout")
        for value, name, maximum in ((max_frames, "max_frames", 256), (max_unrelated, "max_unrelated", 1024),
                                     (max_bytes, "max_bytes", 1048576)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer in 1..{maximum}")
        if type(command_checksum) is not bool:
            raise ValueError("command_checksum must be boolean")
        self.max_frames, self.max_unrelated, self.max_bytes = max_frames, max_unrelated, max_bytes
        self.command_checksum = command_checksum
        self._used = False
        self._lock = threading.Lock()
        self.last_observation = None
        self._absolute_deadline = None  # Internal coordinator budget; never extends this child's timeout.

    def collect_serials(self, address):
        """Return a SerialObservation, including partial evidence on I/O failure.

        Invalid inputs or object reuse raise before connecting. A failed
        connection is an incomplete observation with no request transmitted.
        """
        _byte(address, "address")
        with self._lock:
            if self._used:
                raise RuntimeError("Collector is one-shot; establish fresh transport ownership before another observation")
            self._used = True
            return self._collect(address)

    def _make_socket(self):
        return socket.socket(self._family, socket.SOCK_STREAM)

    def _collect(self, address):
        started = time.monotonic()
        last_clock = started

        def read_clock():
            nonlocal last_clock
            last_clock = time.monotonic()
            return last_clock

        request = encode_command(address, IdentifyCAL(4), confirmation=b"g", checksum=self.command_checksum)
        sent_request = b""
        received, replies, unrelated, errors = bytearray(), [], [], []
        confirmation = None
        termination = "connection_error"
        stream = FrameStream()
        sock = None
        total_bytes = 0
        connection_closed = True
        serial_data = {}
        overall_deadline = started + self.overall_timeout
        if self._absolute_deadline is not None:
            overall_deadline = min(overall_deadline, self._absolute_deadline)
        quiet_deadline = confirmation_deadline = None
        interruption = None

        def stop(reason, error=None):
            nonlocal termination
            termination = reason
            if error: errors.append(error)

        def other(event, reason="unrelated"):
            if isinstance(event, Frame): item = {"kind": "frame", "source": event.source,
                "destination": event.destination, "route_hex": event.route.hex(), "raw_hex": event.raw.hex()}
            elif isinstance(event, Confirmation): item = {"kind": "confirmation", "code": event.code.decode(), "status": event.status}
            else: item = {"kind": "notification", "code": event.code}
            item["reason"] = reason; unrelated.append(item)
            if len(unrelated) >= self.max_unrelated:
                stop("unrelated_limit", "Unrelated traffic reached the collection limit")

        def process(event, arrived):
            nonlocal confirmation, quiet_deadline
            if isinstance(event, Confirmation):
                if event.code != b"g":
                    other(event, "foreign_confirmation")
                    stop("correlation_error", "Another command's confirmation appeared on the owned stream")
                elif confirmation is not None:
                    other(event, "duplicate_confirmation")
                    stop("correlation_error", "Multiple PCI confirmations are ambiguous")
                else:
                    confirmation = event.status
                    if event.status != ".": stop("rejected", "PCI rejected IDENTIFY4: " + event.status)
                    elif quiet_deadline is None: quiet_deadline = arrived + self.quiet_period
                return
            if isinstance(event, Notification):
                other(event)
                if event.code == "!": stop("rejected", "PCI reported busy or rejected the request")
                return
            matching = [cal for cal in event.cals if isinstance(cal, ReplyCAL) and cal.parameter == 4]
            if not matching:
                other(event); return
            if event.bare:
                if address != self.local_unit:
                    other(event, "unattributed_serial")
                    stop("correlation_error", "A bare serial reply cannot identify a remote addressed unit")
                    return
            elif event.source != address:
                other(event); return
            elif event.destination != self.local_unit or event.route != b"\x00":
                other(event, "wrong_destination_or_route")
                stop("correlation_error", "Serial reply destination or route does not match this PCI request")
                return
            if len(event.cals) != 1 or len(matching) != 1:
                other(event, "ambiguous_serial_chain")
                stop("invalid_reply", "IDENTIFY4 must return exactly one serial CAL per frame")
                return
            cal = matching[0]
            packed = int.from_bytes(cal.data[5:9], "big") if len(cal.data) == 12 else None
            serial = f"{packed >> 12}.{packed & 4095}" if packed is not None else None
            known = packed is not None and packed not in (0, 0xFFFFFFFF)
            replies.append(SerialReply(event.source, event.destination, serial, known,
                                       cal.data, event.raw, arrived - started))
            quiet_deadline = arrived + self.quiet_period
            if confirmation != ".":
                stop("correlation_error", "Serial data arrived before this request's PCI confirmation")
            elif packed is None:
                stop("invalid_reply", "IDENTIFY4 must contain exactly twelve data bytes")
            elif not known:
                stop("unknown_serial", "IDENTIFY4 returned an unset or unknown serial")
            elif serial in serial_data and serial_data[serial] != cal.data:
                stop("conflicting_serial", "The same serial returned conflicting IDENTIFY4 blocks")
            elif len(replies) >= self.max_frames:
                stop("frame_limit", "Serial response count reached the collection limit")
            serial_data[serial] = cal.data

        def begin():
            nonlocal sock, connection_closed, sent_request, confirmation_deadline, termination
            # Numeric endpoints avoid unbounded DNS and per-address timeout
            # multiplication in socket.create_connection's resolution loop.
            if read_clock() >= overall_deadline:
                stop("overall_timeout", "Overall deadline reached before socket creation"); return
            sock = self._make_socket()
            connection_closed = False
            remaining = overall_deadline - read_clock()
            if remaining <= 0:
                stop("overall_timeout", "Overall deadline reached before connection"); return
            sock.settimeout(remaining)
            endpoint = (self.host, self.port, 0, 0) if self._family == socket.AF_INET6 else (self.host, self.port)
            sock.connect(endpoint)
            remaining = overall_deadline - read_clock()
            if remaining <= 0:
                stop("overall_timeout", "Connection establishment exhausted the overall timeout")
            else:
                sock.settimeout(remaining)
                # Mark attempted transmission before sendall: a send failure
                # may have delivered a partial request, so never replay it.
                sent_request = request
                sock.sendall(request)
                sent_at = read_clock()
                confirmation_deadline = min(overall_deadline, sent_at + self.confirmation_timeout)
                termination = "collecting"
        try:
            begin()
            while termination == "collecting":
                now = read_clock()
                deadline = min(overall_deadline, quiet_deadline if confirmation == "." else confirmation_deadline)
                if now >= deadline:
                    if stream.buffer:
                        stop("truncated_frame", "Collection ended with a partial PCI frame or confirmation")
                    elif now >= overall_deadline:
                        stop("overall_timeout", "The overall collection timeout was reached")
                    elif confirmation != ".":
                        stop("confirmation_timeout", "No matching PCI confirmation arrived")
                    else: stop("quiet")
                    break
                sock.settimeout(deadline - now)
                try: chunk = sock.recv(min(4096, self.max_bytes + 1 - len(received)))
                except socket.timeout: continue
                arrived = read_clock()
                if not chunk:
                    stop("truncated_frame" if stream.buffer else "disconnected",
                         "PCI disconnected before the collection window completed")
                    break
                total_bytes += len(chunk)
                received.extend(chunk[:self.max_bytes - len(received)])
                if total_bytes > self.max_bytes:
                    stop("byte_limit", "Incoming traffic exceeded the byte limit"); break
                if arrived >= deadline:
                    stop("late_data", "Data arrived at or after the observation deadline"); break
                # Feed incrementally so a malformed later frame cannot erase
                # already-completed valid replies from the same socket read.
                for byte in chunk:
                    for event in stream.feed(bytes([byte])):
                        process(event, arrived)
                        if termination != "collecting": break
                    if termination != "collecting": break
        except ProtocolError as error:
            stop("framing_error", str(error))
        except (OSError, TimeoutError) as error:
            stop("transport_error" if sent_request else "connection_error", str(error))
        except BaseException as error:
            interruption = error
            stop("interrupted", type(error).__name__ + ": " + str(error))
        finally:
            if sock is not None:
                try:
                    sock.close()
                    connection_closed = True
                except BaseException as error:
                    errors.append("Closing the PCI connection failed: " + type(error).__name__ + ": " + str(error))
                    if not isinstance(error, Exception) and interruption is None:
                        interruption = error
                    if termination == "quiet": termination = "close_error"
        try:
            read_clock()
        except BaseException as error:
            if interruption is None: interruption = error
            stop("interrupted", "Final clock sample failed: " + type(error).__name__ + ": " + str(error))
        observation = SerialObservation(address, self.local_unit, sent_request, bytes(received), confirmation,
                                 tuple(replies), tuple(unrelated), tuple(errors), termination,
                                 last_clock - started, self.quiet_period, self.overall_timeout,
                                 self.confirmation_timeout, self.max_frames, total_bytes, connection_closed)
        self.last_observation = observation
        if interruption is not None:
            try: interruption.pci_serial_observation = observation.as_dict()
            except BaseException: pass
            raise interruption
        return observation
