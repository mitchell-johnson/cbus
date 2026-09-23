"""One-shot read-only install MMI with explicit coverage of every address.

Exact C-Gate cs/dk/dn establishes the standard C/D MMI framing, contiguous
offset requirement and low-to-high two-bit states. Missing ranges remain
unknown; neither a confirmation nor a count of three frames proves coverage.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
import threading
import time

from .pci import Confirmation, Frame, Notification, ProtocolError, decode_frame
from .pci_serials import _byte, _seconds


@dataclass(frozen=True)
class MMIBlock:
    application: int
    start: int
    states: tuple[int, ...]
    marker: int
    raw: bytes

    @property
    def end(self): return self.start + len(self.states)

    def as_dict(self):
        return {"application": self.application, "start": self.start, "end_exclusive": self.end,
                "states": list(self.states), "marker": self.marker, "raw_hex": self.raw.hex()}


def _decode_line(raw):
    if not raw or len(raw) % 2 or any(byte not in b"0123456789ABCDEFabcdef" for byte in raw):
        raise ProtocolError("MMI transport frame must contain even-length hexadecimal text")
    data = bytes.fromhex(raw.decode("ascii"))
    if len(data) < 2 or sum(data) & 255:
        raise ProtocolError("Invalid C-Bus checksum")
    if data[0] & 0xE0 != 0xC0:
        return decode_frame(raw, checksum=True)
    count = data[0] & 31
    if count < 3 or len(data) != count + 2:
        raise ProtocolError("Invalid standard MMI block length")
    states = tuple((value >> shift) & 3 for value in data[3:-1] for shift in (0, 2, 4, 6))
    if data[2] + len(states) > 256:
        raise ProtocolError("MMI block extends beyond address 255")
    return MMIBlock(data[1], data[2], states, data[0], raw)


class _MMIStream:
    def __init__(self): self.buffer = bytearray()

    def feed_byte(self, byte):
        if byte in (0x11, 0x13): return ()
        self.buffer.append(byte)
        events = []
        while self.buffer:
            if self.buffer[0] in (10, 13):
                del self.buffer[0]; continue
            if self.buffer[0] in b"+!":
                events.append(Notification(chr(self.buffer.pop(0)))); continue
            if ord("g") <= self.buffer[0] <= ord("z"):
                if len(self.buffer) < 2: break
                code, status = bytes(self.buffer[:1]), chr(self.buffer[1])
                if status not in ".#$%!": raise ProtocolError("Invalid PCI confirmation status")
                del self.buffer[:2]; events.append(Confirmation(code, status)); continue
            end = self.buffer.find(b"\r")
            if end < 0:
                if len(self.buffer) > 8192: raise ProtocolError("MMI transport frame exceeds buffer limit")
                break
            raw = bytes(self.buffer[:end])
            event = _decode_line(raw)
            del self.buffer[:end + 1]; events.append(event)
        return events


@dataclass(frozen=True)
class MMIObservation:
    local_unit: int
    states: tuple[int | None, ...]
    blocks: tuple[MMIBlock, ...]
    request: bytes
    received: bytes
    confirmation: str | None
    unrelated: tuple[dict, ...]
    errors: tuple[str, ...]
    termination: str
    elapsed: float
    overall_timeout: float
    confirmation_timeout: float
    response_timeout: float
    max_frames: int
    bytes_received: int
    connection_closed: bool

    @property
    def coverage_complete(self): return all(state is not None for state in self.states)

    @property
    def addresses(self): return tuple(index for index, state in enumerate(self.states) if state not in (None, 0))

    @property
    def local_present(self): return self.states[self.local_unit] not in (None, 0)

    @property
    def error_addresses(self): return tuple(index for index, state in enumerate(self.states) if state == 3)

    @property
    def missing_ranges(self):
        ranges, start = [], None
        for index, state in enumerate(self.states + (0,)):
            if state is None and start is None: start = index
            elif state is not None and start is not None:
                ranges.append((start, index)); start = None
        return tuple(ranges)

    @property
    def complete(self):
        return (self.termination == "coverage_complete" and self.confirmation == "."
                and self.coverage_complete and self.local_present and self.connection_closed and not self.errors)

    @property
    def status(self):
        return "incomplete" if not self.complete else "mmi_errors" if self.error_addresses else "complete"

    def as_dict(self):
        return {"format": "cbus-pci-mmi-observation-v1", "status": self.status, "complete": self.complete,
                "coverage_complete": self.coverage_complete, "local_unit": self.local_unit,
                "local_present": self.local_present, "addresses": list(self.addresses),
                "states": list(self.states), "error_addresses": list(self.error_addresses),
                "missing_ranges": [{"start": start, "end_exclusive": end} for start, end in self.missing_ranges],
                "blocks": [block.as_dict() for block in self.blocks], "confirmation": self.confirmation,
                "unrelated": [dict(event) for event in self.unrelated], "errors": list(self.errors),
                "termination": self.termination, "request_hex": self.request.hex(), "received_hex": self.received.hex(),
                "bytes_received": self.bytes_received, "max_frames": self.max_frames,
                "timing": {"elapsed_seconds": self.elapsed, "overall_timeout_seconds": self.overall_timeout,
                           "confirmation_timeout_seconds": self.confirmation_timeout,
                           "response_timeout_seconds": self.response_timeout},
                "scope": "standard_direct_install_mmi", "serials_observed": False,
                "physical_addresses_changed": False, "database_updated": False, "automatic_retries": 0,
                "connection_closed": self.connection_closed}


class PCIMMICollector:
    """Collect one install MMI on a freshly owned numeric-IP TCP endpoint.

    The caller supplies the known local PCI address and exclusive transport
    ownership. No SMART reset, local-address discovery, configuration or write
    occurs. Standard direct C/D blocks are supported; routed/extended MMI is
    rejected. A complete observation establishes contiguous protocol coverage,
    not serial identity, uniqueness or an atomic physical network snapshot.
    """

    def __init__(self, host, port=10001, *, local_unit, overall_timeout=10.0,
                 confirmation_timeout=2.0, response_timeout=5.5, max_frames=7,
                 max_unrelated=64, max_bytes=65536, command_checksum=False):
        if not isinstance(host, str) or "%" in host:
            raise ValueError("MMI collector requires a numeric IPv4 or IPv6 address without a scope suffix")
        try: numeric = ipaddress.ip_address(host)
        except ValueError as error: raise ValueError("MMI collector requires a numeric IP address; DNS is not deadline-bounded") from error
        if type(port) is not int or not 1 <= port <= 65535: raise ValueError("port must be in 1..65535")
        self.host, self.port, self.local_unit = str(numeric), port, _byte(local_unit, "local_unit")
        self._family = socket.AF_INET6 if numeric.version == 6 else socket.AF_INET
        self.overall_timeout = _seconds(overall_timeout, "overall_timeout")
        self.confirmation_timeout = _seconds(confirmation_timeout, "confirmation_timeout")
        self.response_timeout = _seconds(response_timeout, "response_timeout")
        if max(self.confirmation_timeout, self.response_timeout) > self.overall_timeout:
            raise ValueError("Overall timeout must include the confirmation and response timeouts")
        for value, name, maximum in ((max_frames, "max_frames", 256), (max_unrelated, "max_unrelated", 1024),
                                     (max_bytes, "max_bytes", 1048576)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer in 1..{maximum}")
        if type(command_checksum) is not bool: raise ValueError("command_checksum must be boolean")
        self.max_frames, self.max_unrelated, self.max_bytes = max_frames, max_unrelated, max_bytes
        self.command_checksum = command_checksum
        self._used = False
        self._lock = threading.Lock()
        self.last_observation = None
        self._absolute_deadline = None  # Internal coordinator budget; never extends this child's timeout.

    def _make_socket(self): return socket.socket(self._family, socket.SOCK_STREAM)

    def collect_mmi(self):
        with self._lock:
            if self._used: raise RuntimeError("MMI collector is one-shot; establish fresh transport ownership")
            self._used = True
            return self._collect()

    def _collect(self):
        started = time.monotonic()
        last_clock = started

        def read_clock():
            nonlocal last_clock
            last_clock = time.monotonic()
            return last_clock

        request = b"\\05FF00FAFF00" + (b"03" if self.command_checksum else b"") + b"g\r"
        sent_request = b""
        states, blocks, unrelated, errors = [None] * 256, [], [], []
        received, total_bytes, confirmation = bytearray(), 0, None
        termination, sock, connection_closed = "connection_error", None, True
        stream = _MMIStream()
        overall_deadline = started + self.overall_timeout
        if self._absolute_deadline is not None:
            overall_deadline = min(overall_deadline, self._absolute_deadline)
        confirmation_deadline = response_deadline = None
        next_start = 0
        interruption = None

        def stop(reason, error=None):
            nonlocal termination
            termination = reason
            if error: errors.append(error)

        def other(event, reason="unrelated"):
            if isinstance(event, MMIBlock): item = {"kind": "mmi", **event.as_dict()}
            elif isinstance(event, Frame): item = {"kind": "frame", "source": event.source,
                "destination": event.destination, "route_hex": event.route.hex(), "raw_hex": event.raw.hex()}
            elif isinstance(event, Confirmation): item = {"kind": "confirmation", "code": event.code.decode(), "status": event.status}
            else: item = {"kind": "notification", "code": event.code}
            item["reason"] = reason; unrelated.append(item)
            if len(unrelated) >= self.max_unrelated: stop("unrelated_limit", "Unrelated traffic reached its limit")

        def process(event, arrived):
            nonlocal confirmation, response_deadline, next_start
            if isinstance(event, Confirmation):
                if event.code != b"g" or confirmation is not None:
                    other(event, "foreign_or_duplicate_confirmation")
                    stop("correlation_error", "MMI received another command's or a repeated PCI confirmation")
                else:
                    confirmation = event.status
                    if confirmation != ".": stop("rejected", "PCI rejected install MMI: " + confirmation)
                    else: response_deadline = arrived + self.response_timeout
                return
            if isinstance(event, Notification):
                other(event)
                if event.code == "!": stop("rejected", "PCI reported busy or rejected the request")
                return
            if not isinstance(event, MMIBlock): other(event); return
            if event.application != 255: other(event, "other_application"); return
            blocks.append(event)
            if confirmation != ".":
                stop("correlation_error", "MMI block arrived before this request's PCI confirmation"); return
            if event.start != next_start:
                stop("coverage_error", "MMI block offset is repeated, overlapping or noncontiguous"); return
            states[event.start:event.end] = event.states
            next_start = event.end
            response_deadline = arrived + self.response_timeout
            if len(blocks) >= self.max_frames and next_start != 256:
                stop("frame_limit", "MMI frame limit reached before full coverage")

        def begin():
            nonlocal sock, connection_closed, sent_request, confirmation_deadline, termination
            if read_clock() >= overall_deadline:
                stop("overall_timeout", "Overall deadline reached before socket creation"); return
            sock = self._make_socket(); connection_closed = False
            remaining = overall_deadline - read_clock()
            if remaining <= 0:
                stop("overall_timeout", "Overall deadline reached before connection"); return
            sock.settimeout(remaining)
            endpoint = (self.host, self.port, 0, 0) if self._family == socket.AF_INET6 else (self.host, self.port)
            sock.connect(endpoint)
            remaining = overall_deadline - read_clock()
            if remaining <= 0: stop("overall_timeout", "Connection exhausted the overall timeout")
            else:
                sock.settimeout(remaining); sent_request = request; sock.sendall(request)
                confirmation_deadline = min(overall_deadline, read_clock() + self.confirmation_timeout)
                termination = "collecting"
        try:
            begin()
            while termination == "collecting":
                now = read_clock()
                deadline = min(overall_deadline, response_deadline if confirmation == "." else confirmation_deadline)
                if now >= deadline:
                    if stream.buffer: stop("truncated_frame", "MMI window ended with a partial frame or confirmation")
                    elif now >= overall_deadline: stop("overall_timeout", "Overall MMI deadline reached")
                    elif confirmation != ".": stop("confirmation_timeout", "No matching PCI confirmation arrived")
                    else: stop("response_timeout", "MMI response ended before full address coverage")
                    break
                sock.settimeout(deadline - now)
                try: chunk = sock.recv(min(4096, self.max_bytes + 1 - len(received)))
                except socket.timeout: continue
                arrived = read_clock()
                if not chunk:
                    stop("truncated_frame" if stream.buffer else "disconnected", "PCI disconnected before full MMI coverage")
                    break
                total_bytes += len(chunk)
                received.extend(chunk[:self.max_bytes - len(received)])
                if total_bytes > self.max_bytes: stop("byte_limit", "Incoming MMI traffic exceeded its byte limit"); break
                if arrived >= deadline: stop("late_data", "MMI data arrived at or after the observation deadline"); break
                for byte in chunk:
                    for event in stream.feed_byte(byte):
                        process(event, arrived)
                        if termination != "collecting": break
                    if termination != "collecting": break
                if termination == "collecting" and next_start == 256:
                    if stream.buffer: stop("truncated_frame", "Extra partial data followed completed MMI coverage")
                    elif states[self.local_unit] == 0: stop("local_absent", "Complete MMI does not include the supplied local PCI address")
                    else: stop("coverage_complete")
        except ProtocolError as error: stop("framing_error", str(error))
        except (OSError, TimeoutError) as error: stop("transport_error" if sent_request else "connection_error", str(error))
        except BaseException as error:
            interruption = error
            stop("interrupted", type(error).__name__ + ": " + str(error))
        finally:
            if sock is not None:
                try: sock.close(); connection_closed = True
                except BaseException as error:
                    errors.append("Closing the MMI connection failed: " + type(error).__name__ + ": " + str(error))
                    if not isinstance(error, Exception) and interruption is None: interruption = error
                    if termination == "coverage_complete": termination = "close_error"
        try:
            read_clock()
        except BaseException as error:
            if interruption is None: interruption = error
            stop("interrupted", "Final clock sample failed: " + type(error).__name__ + ": " + str(error))
        observation = MMIObservation(self.local_unit, tuple(states), tuple(blocks), sent_request, bytes(received), confirmation,
            tuple(unrelated), tuple(errors), termination, last_clock - started, self.overall_timeout,
            self.confirmation_timeout, self.response_timeout, self.max_frames, total_bytes, connection_closed)
        self.last_observation = observation
        if interruption is not None:
            try: interruption.pci_mmi_observation = observation.as_dict()
            except BaseException: pass
            raise interruption
        return observation
